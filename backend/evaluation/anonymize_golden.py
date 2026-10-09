"""Write ``golden_set.anonymized.jsonl`` from the original ``golden_set.jsonl``.

    POSTGRES_DB=docgrading_test uv run python -m evaluation.anonymize_golden

Student names are taken (read-only) from the display names of the students
who submitted to the anchor course; each name becomes a stable code
``SV001``, ``SV002``... The name -> code map lives in
``evaluation/private/anonymization_map.json`` (git-ignored, like the
original golden set) and is reused on later runs, so codes never change.

Only case ids carry names today. Any name found in another field stops the
script instead of being rewritten silently: rewriting a question could change
which submission the chatbot resolves, i.e. change the case.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import sqlalchemy as sa

from app.db.session import _engine, _session_factory
from app.models.assignment import Assignment
from app.models.identity import User
from app.models.submission import Submission
from evaluation.golden import ANONYMIZED_PATH, ORIGINAL_PATH
from evaluation.scoring import fold_compact

PRIVATE_DIR = Path(__file__).resolve().parent / "private"
MAP_PATH = PRIVATE_DIR / "anonymization_map.json"
ANCHOR_COURSE_ID = "2acdc4ff-b11c-437a-bcb8-3bb811c101c1"
# Placeholder display names of seeded/demo accounts, not people.
GENERIC_NAMES = frozenset({"student"})


async def student_names() -> list[str]:
    async with _session_factory()() as db:
        rows = (
            await db.execute(
                sa.select(User.display_name)
                .join(Submission, Submission.student_id == User.id)
                .join(Assignment, Assignment.id == Submission.assignment_id)
                .where(Assignment.course_id == uuid.UUID(ANCHOR_COURSE_ID))
                .distinct()
            )
        ).all()
    await _engine().dispose()
    # Group-named uploads ("[N8] - OPRO") are project titles, not people.
    return sorted(
        name
        for (name,) in rows
        if name and not name.startswith("[") and fold_compact(name) not in GENERIC_NAMES
    )


def anonymize(
    cases: list[dict], names: list[str], mapping: dict[str, str]
) -> tuple[list[dict], dict[str, str]]:
    tokens = {fold_compact(n) for n in names}
    out = []
    for case in cases:
        for key, value in case.items():
            if key == "id":
                continue
            blob = fold_compact(json.dumps(value, ensure_ascii=False))
            leaked = [t for t in tokens if t in blob]
            if leaked:
                raise SystemExit(
                    f"{case['id']}: student name in field {key!r}; not rewriting it "
                    "automatically (it could change the case) - fix by hand"
                )
        parts = []
        for part in case["id"].split("-"):
            token = fold_compact(part)
            if token in tokens:
                if token not in mapping:
                    mapping[token] = f"SV{len(mapping) + 1:03d}"
                parts.append(mapping[token])
            else:
                parts.append(part)
        out.append({**case, "id": "-".join(parts)})
    ids = [c["id"] for c in out]
    if len(ids) != len(set(ids)):
        raise SystemExit("anonymized ids are not unique")
    final_blob = fold_compact(json.dumps(out, ensure_ascii=False))
    if any(t in final_blob for t in tokens):
        raise SystemExit("a student name is still present after anonymization")
    return out, mapping


def main() -> int:
    if not ORIGINAL_PATH.exists():
        print(f"{ORIGINAL_PATH} not found - nothing to anonymize")
        return 1
    cases = [
        json.loads(line)
        for line in ORIGINAL_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    names = asyncio.run(student_names())
    mapping = (
        json.loads(MAP_PATH.read_text(encoding="utf-8")) if MAP_PATH.exists() else {}
    )
    anonymized, mapping = anonymize(cases, names, mapping)
    PRIVATE_DIR.mkdir(exist_ok=True)
    MAP_PATH.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    ANONYMIZED_PATH.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in anonymized),
        encoding="utf-8",
    )
    changed = sum(
        1 for a, b in zip(cases, anonymized, strict=True) if a["id"] != b["id"]
    )
    print(
        f"{len(anonymized)} cases, {changed} ids rewritten, {len(mapping)} codes; "
        f"wrote {ANONYMIZED_PATH.name}; map at {MAP_PATH}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
