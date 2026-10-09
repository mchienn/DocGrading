"""Summary-cache correctness cases (``evaluation/cache_cases.jsonl``).

Every case runs inside ``rolled_back_session``: summaries it creates, the
chunk it edits, the document version it inserts - all of it is rolled back
when the case ends, so the database is unchanged and the cases can be re-run.

Case kinds:

- ``miss_then_hit``: no summary row yet. Request 1 must call the LLM (proves
  the write path); request 2 must make no LLM call and return the same text.
- ``precached_hit``: a summary row already exists and its ``source_hash``
  matches the current chunks. Both requests must make no LLM call and return
  exactly the stored text.
- ``legacy_row_regenerates``: a summary row exists but was written before
  ``source_hash`` existed (NULL) or for other chunks. Request 1 must rebuild
  it (>= 1 LLM call) and stamp the current hash; request 2 must hit it.
- ``content_change_same_version``: after a miss + hit, one chunk of the SAME
  document version gets new text (``UPDATE`` of one row). Request 3 must
  rebuild the summary (>= 1 LLM call) instead of serving the stale one.
- ``new_version``: a new document version (version_number + 1, one chunk
  changed) is inserted for the submission. The next request must build a
  summary for it (>= 1 LLM call) and the one after must hit the new row.

Run on its own (hybrid configuration, real LLM, rolled back):

    POSTGRES_DB=docgrading_test uv run python -m evaluation.cache_suite
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.core.config import get_settings
from app.db.session import _engine
from app.models.analysis import DocumentIR
from app.models.chunk import DocumentChunk, DocumentSummary
from app.models.identity import User
from app.models.submission import DocumentVersion
from app.services.chat import handle_chat
from app.services.rag import SummaryChunk, summary_source_hash
from evaluation import scoring
from evaluation.instrumentation import (
    CountingChatClient,
    RetrievalRecorder,
    TokenLedger,
    ablation_config,
)
from evaluation.sandbox import rolled_back_session

CACHE_CASES_PATH = Path(__file__).resolve().parent / "cache_cases.jsonl"
SUMMARY_QUESTION = "Tóm tắt bài này"
CHANGE_MARKER = " [eval: nội dung đã sửa để kiểm tra cache]"


def load_cache_cases() -> list[dict[str, Any]]:
    with CACHE_CASES_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


async def _latest_version(db: Any, submission_id: uuid.UUID) -> uuid.UUID:
    return await db.scalar(
        sa.select(DocumentVersion.id)
        .where(DocumentVersion.submission_id == submission_id)
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    )


async def _stored_summary(db: Any, version_id: uuid.UUID) -> str | None:
    return await db.scalar(
        sa.select(DocumentSummary.summary).where(
            DocumentSummary.document_version_id == version_id
        )
    )


async def _row_state(db: Any, version_id: uuid.UUID) -> str:
    """ "none" (no summary row), "fresh" (row hash matches the current
    chunks) or "stale" (NULL/other hash), computed with the service's own
    hash function, so it says what ``summarize_document`` will do."""
    row = await db.scalar(
        sa.select(DocumentSummary).where(
            DocumentSummary.document_version_id == version_id
        )
    )
    if row is None:
        return "none"
    rows = (
        await db.execute(
            sa.select(
                DocumentChunk.section_path,
                DocumentChunk.text,
                DocumentChunk.token_count,
            )
            .where(DocumentChunk.document_version_id == version_id)
            .order_by(DocumentChunk.chunk_index)
        )
    ).all()
    chunks = [SummaryChunk(r[0], r[1], r[2]) for r in rows]
    parser_version = await db.scalar(
        sa.select(DocumentIR.parser_version).where(
            DocumentIR.document_version_id == version_id
        )
    )
    fresh = row.source_hash == summary_source_hash(parser_version, chunks)
    return "fresh" if fresh else "stale"


async def _edit_one_chunk(db: Any, version_id: uuid.UUID) -> uuid.UUID:
    chunk_id = await db.scalar(
        sa.select(DocumentChunk.id)
        .where(DocumentChunk.document_version_id == version_id)
        .order_by(DocumentChunk.chunk_index)
        .limit(1)
    )
    await db.execute(
        sa.update(DocumentChunk)
        .where(DocumentChunk.id == chunk_id)
        .values(text=DocumentChunk.text + CHANGE_MARKER)
    )
    return chunk_id


async def _insert_new_version(db: Any, old_version_id: uuid.UUID) -> uuid.UUID:
    """Copy the version row (version_number + 1) and its chunks, with the
    first chunk's text changed - what a re-upload of an edited PDF yields."""
    new_id = uuid.uuid4()
    columns = [
        row[0]
        for row in (
            await db.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t "
                    "ORDER BY ordinal_position"
                ),
                {"t": "document_versions"},
            )
        ).all()
    ]
    overrides = {
        "id": ":new_id",
        "created_at": "now()",
        "updated_at": "now()",
        "version_number": "version_number + 1",
        "previous_version_id": "id",
        "sha256": "md5(id::text || 'eval-a') || md5(id::text || 'eval-b')",
        "idempotency_key": "NULL",
        "idempotency_fingerprint": "NULL",
    }
    select_list = ", ".join(overrides.get(c, c) for c in columns)
    await db.execute(
        sa.text(
            f"INSERT INTO document_versions ({', '.join(columns)}) "
            f"SELECT {select_list} FROM document_versions WHERE id = :old_id"
        ),
        {"new_id": new_id, "old_id": old_version_id},
    )
    await db.execute(
        sa.text(
            "INSERT INTO document_chunks (id, created_at, updated_at, "
            "document_version_id, chunk_index, section_path, page_start, page_end, "
            "paragraph_ids, text, token_count, embedding) "
            "SELECT gen_random_uuid(), now(), now(), :new_id, chunk_index, "
            "section_path, page_start, page_end, paragraph_ids, "
            "CASE WHEN chunk_index = (SELECT min(chunk_index) "
            "  FROM document_chunks WHERE document_version_id = :old_id) "
            "THEN text || :marker ELSE text END, "
            "token_count, embedding FROM document_chunks "
            "WHERE document_version_id = :old_id"
        ),
        {"new_id": new_id, "old_id": old_version_id, "marker": CHANGE_MARKER},
    )
    return new_id


async def run_cache_case(
    case: dict[str, Any],
    llm: CountingChatClient,
    teacher_id: uuid.UUID,
    course_id: str,
) -> dict[str, Any]:
    submission_id = uuid.UUID(case["submission_id"])
    kind = case["kind"]
    out: dict[str, Any] = {"case_id": case["id"], "kind": kind}
    start = time.perf_counter()
    try:
        async with rolled_back_session() as db:
            user = await db.get(User, teacher_id)

            async def ask() -> tuple[int, str]:
                before = llm.calls
                response = await handle_chat(
                    db,
                    user=user,
                    message=SUMMARY_QUESTION,
                    course_id=course_id,
                    assignment_id=None,
                    submission_id=submission_id,
                )
                if response.intent != "SUMMARIZE_SUBMISSION":
                    raise RuntimeError(f"unexpected intent {response.intent}")
                return llm.calls - before, response.reply

            version_id = await _latest_version(db, submission_id)
            stored = await _stored_summary(db, version_id)
            state = await _row_state(db, version_id)
            out["row_state_before"] = state
            required = {
                "miss_then_hit": "none",
                "content_change_same_version": "none",
                "precached_hit": "fresh",
                "legacy_row_regenerates": "stale",
            }.get(kind)
            if required is not None and state != required:
                out.update(ok=None, status="precondition_failed")
                return out

            calls1, reply1 = await ask()
            calls2, reply2 = await ask()
            out.update(calls=[calls1, calls2], same_reply_1_2=reply1 == reply2)
            if kind == "miss_then_hit":
                ok = scoring.cache_case_ok(calls1, calls2, reply1, reply2)
            elif kind == "precached_hit":
                ok = calls1 == 0 and calls2 == 0 and reply1 == reply2 == stored
            elif kind == "legacy_row_regenerates":
                out["row_state_after"] = await _row_state(db, version_id)
                ok = (
                    scoring.cache_case_ok(calls1, calls2, reply1, reply2)
                    and out["row_state_after"] == "fresh"
                )
            elif kind == "content_change_same_version":
                await _edit_one_chunk(db, version_id)
                calls3, reply3 = await ask()
                out["calls"].append(calls3)
                out["reply_changed_after_edit"] = reply3 != reply2
                ok = scoring.cache_case_ok(
                    calls1, calls2, reply1, reply2
                ) and scoring.cache_invalidated_ok(calls3, reply2, reply3)
            elif kind == "new_version":
                new_version = await _insert_new_version(db, version_id)
                calls3, reply3 = await ask()
                calls4, reply4 = await ask()
                out["calls"] += [calls3, calls4]
                out["new_version_summary_row"] = (
                    await _stored_summary(db, new_version) is not None
                )
                # Old version: served from cache only if its row was fresh.
                old_ok = (calls1 > 0) == (state != "fresh") and calls2 == 0
                ok = (
                    old_ok
                    and scoring.cache_invalidated_ok(calls3, reply2, reply3)
                    and scoring.cache_case_ok(calls3, calls4, reply3, reply4)
                    and out["new_version_summary_row"]
                )
            else:
                raise ValueError(f"unknown cache case kind {kind!r}")
            out.update(ok=bool(ok), status="pass" if ok else "fail")
    except Exception as exc:  # noqa: BLE001 - reported per case
        out.update(ok=False, status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        out["latency_s"] = round(time.perf_counter() - start, 3)
    return out


def score_cache(details: list[dict[str, Any]]) -> dict[str, Any]:
    counted = [d for d in details if d.get("status") != "precondition_failed"]
    passed = sum(1 for d in counted if d.get("ok"))
    by_kind: dict[str, dict[str, int]] = {}
    for d in counted:
        bucket = by_kind.setdefault(d["kind"], {"n": 0, "pass": 0})
        bucket["n"] += 1
        bucket["pass"] += 1 if d.get("ok") else 0
    return {
        "n_total": len(details),
        "n_counted": len(counted),
        "n_precondition_failed": len(details) - len(counted),
        "pass": passed,
        "rate": scoring.rate(passed, len(counted)),
        "by_kind": by_kind,
        "details": details,
    }


async def main(label: str) -> int:
    settings = get_settings()
    print(f"[cache] POSTGRES_DB={settings.postgres_db}")
    if settings.postgres_db == "docgrading":
        print("[cache] refusing to run against the dev database")
        return 2
    from evaluation.run_ablation import ANCHOR_COURSE_ID, TEACHER_ID

    ledger = TokenLedger()
    details = []
    try:
        with ablation_config("hybrid", ledger, RetrievalRecorder()) as llm:
            for case in load_cache_cases():
                d = await run_cache_case(case, llm, TEACHER_ID, ANCHOR_COURSE_ID)
                print(f"  - {d}")
                details.append(d)
    finally:
        await _engine().dispose()
    result = score_cache(details)
    result["tokens"] = ledger.snapshot()
    result["llm_model"] = settings.llm_model
    stamp = datetime.now(UTC)
    result["timestamp"] = stamp.strftime("%Y%m%dT%H%M%SZ")
    out = (
        Path(__file__).resolve().parent
        / "results"
        / f"cache_{stamp.strftime('%Y%m%d')}_{label}.json"
    )
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[cache] pass {result['pass']}/{result['n_counted']} "
        f"(precondition_failed {result['n_precondition_failed']}); "
        f"by kind {result['by_kind']}; LLM tokens {ledger.llm_total:,}; "
        f"wrote {out.name}"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", default="source_hash_fix")
    sys.exit(asyncio.run(main(parser.parse_args().label)))
