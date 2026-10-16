"""Rebuild Document IR, chunks and embeddings after a parser change; optionally
regenerate submission summaries so their rows carry a real source_hash.

    # see what would change (no writes):
    uv run python -m scripts.reindex_documents --dry-run --pdf-dir ../test_submissions
    # write (the configured database must be named explicitly):
    uv run python -m scripts.reindex_documents --pdf-dir ../test_submissions \\
        --expect-db docgrading_test --summaries --report reindex.json

Re-runnable: a version whose IR already has the current parser version is
skipped. PDF bytes come from object storage (unless --no-storage) or from
--pdf-dir, matched by SHA-256 and checked against document_versions.sha256.
A version whose PDF cannot be found keeps its old IR, chunks and summary.

Per version, the IR rebuild, the chunk replacement and the new embeddings are
committed together (one transaction); a failure leaves the old data.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import _engine, _session_factory
from app.models.analysis import DocumentIR
from app.models.chunk import DocumentChunk
from app.models.submission import DocumentVersion
from app.services.document_ir import PARSER_VERSION, get_or_build_document_ir
from app.services.embeddings import EmbeddingProvider, OpenAIEmbeddingProvider
from app.services.rag import (
    LLMClient,
    OpenAIChatClient,
    strip_section_prefix,
    summarize_document,
)
from app.services.storage import S3Storage
from app.workers.index_document_chunks import _default_provider, index_document_version

LONG_CHUNK_TOKENS = 450


class Usage:
    """Token usage the OpenAI API reports, summed over the run."""

    def __init__(self) -> None:
        self.llm = {"calls": 0, "prompt": 0, "completion": 0, "errors": 0}
        self.embedding = {"calls": 0, "tokens": 0, "errors": 0}


class _CountingChat(OpenAIChatClient):
    def __init__(self, usage: Usage, **kwargs) -> None:
        super().__init__(**kwargs)
        self._usage = usage

    def _record_success(self, system: str, response) -> None:
        self._usage.llm["calls"] += 1
        if response.usage:
            self._usage.llm["prompt"] += response.usage.prompt_tokens
            self._usage.llm["completion"] += response.usage.completion_tokens

    def _record_failure(self, system: str) -> None:
        self._usage.llm["errors"] += 1


class _CountingEmbeddings(OpenAIEmbeddingProvider):
    def __init__(self, usage: Usage, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._usage = usage

    def _record_response(self, response) -> None:
        self._usage.embedding["calls"] += 1
        if response.usage:
            self._usage.embedding["tokens"] += response.usage.total_tokens

    def _record_failure(self) -> None:
        self._usage.embedding["errors"] += 1


def _counting_providers(usage: Usage) -> tuple[EmbeddingProvider | None, LLMClient]:
    """Same settings as the product (backfill embeddings, summary retries)."""
    settings = get_settings()
    provider = _default_provider()
    if isinstance(provider, OpenAIEmbeddingProvider):
        provider = _CountingEmbeddings(
            usage,
            settings.embedding_api_key.strip(),
            settings.embedding_model,
            timeout_seconds=settings.embedding_timeout_seconds,
            max_retries=settings.embedding_max_retries,
        )
    client = _CountingChat(
        usage,
        api_key=settings.llm_api_key.strip(),
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_summary_max_retries,
    )
    return provider, client


class PdfIndex:
    """Local PDFs by SHA-256 (the hash document_versions stores)."""

    def __init__(self, paths: dict[str, Path]) -> None:
        self._paths = paths

    @classmethod
    def from_directory(cls, directory: Path | None) -> PdfIndex:
        paths: dict[str, Path] = {}
        if directory is not None:
            for path in sorted(directory.rglob("*.pdf")):
                paths.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(), path)
        return cls(paths)

    def get(self, sha256: str) -> bytes | None:
        path = self._paths.get(sha256)
        return path.read_bytes() if path is not None else None


@dataclass
class VersionResult:
    version_id: str
    outcome: str
    parser_before: str | None = None
    chunks_before: int = 0
    chunks_after: int = 0
    over_450_before: int = 0
    over_450_after: int = 0
    empty_before: int = 0
    empty_after: int = 0
    tables_before: int = 0
    tables_after: int = 0


async def _chunk_stats(db: AsyncSession, version_id: uuid.UUID) -> tuple[int, int, int]:
    rows = (
        await db.execute(
            sa.select(DocumentChunk.text, DocumentChunk.token_count).where(
                DocumentChunk.document_version_id == version_id
            )
        )
    ).all()
    empty = sum(1 for text_, _ in rows if not strip_section_prefix(text_).strip())
    return len(rows), sum(1 for _, n in rows if n > LONG_CHUNK_TOKENS), empty


async def _ir(db: AsyncSession, version_id: uuid.UUID) -> DocumentIR | None:
    return await db.scalar(
        sa.select(DocumentIR).where(DocumentIR.document_version_id == version_id)
    )


def _load_pdf(
    version: DocumentVersion, index: PdfIndex, storage: S3Storage | None
) -> bytes | None:
    if storage is not None and version.storage_key:
        try:
            return storage.get_bounded(
                version.storage_key, get_settings().pdf_max_size_bytes
            )
        except Exception:  # missing object/bucket: fall back to the local copy
            pass
    return index.get(version.sha256)


async def reindex_version(
    db: AsyncSession,
    version_id: uuid.UUID,
    index: PdfIndex,
    provider: EmbeddingProvider | None,
    *,
    dry_run: bool,
    storage: S3Storage | None = None,
) -> VersionResult:
    result = VersionResult(str(version_id), "pending")
    ir = await _ir(db, version_id)
    if ir is None:
        result.outcome = "no_document_ir"
        return result
    result.parser_before = ir.parser_version
    result.tables_before = len((ir.content or {}).get("tables", []))
    (
        result.chunks_before,
        result.over_450_before,
        result.empty_before,
    ) = await _chunk_stats(db, version_id)
    # Unless rebuilt below, the "after" numbers are the current ones.
    result.tables_after = result.tables_before
    result.chunks_after = result.chunks_before
    result.over_450_after = result.over_450_before
    result.empty_after = result.empty_before
    if ir.parser_version == PARSER_VERSION:
        result.outcome = "up_to_date"
        return result

    version = await db.get(DocumentVersion, version_id)
    data = _load_pdf(version, index, storage)
    if data is None:
        result.outcome = "pdf_missing"
        return result
    if hashlib.sha256(data).hexdigest() != version.sha256:
        result.outcome = "sha256_mismatch"
        return result
    if dry_run:
        result.outcome = "would_reindex"
        return result

    try:
        rebuilt = await get_or_build_document_ir(db, version_id, data, rebuild=True)
        result.tables_after = len(rebuilt.content.get("tables", []))
        await db.execute(
            sa.delete(DocumentChunk).where(
                DocumentChunk.document_version_id == version_id
            )
        )
        # Builds the chunks from the new IR and commits everything at once.
        await index_document_version(db, version_id, provider)
    except Exception:
        await db.rollback()
        raise
    (
        result.chunks_after,
        result.over_450_after,
        result.empty_after,
    ) = await _chunk_stats(db, version_id)
    result.outcome = "reindexed"
    return result


async def refresh_summary(
    db: AsyncSession, version_id: uuid.UUID, client: LLMClient
) -> str:
    summary = await summarize_document(db, version_id, client)
    if summary is None:
        return "no_chunks"
    if summary.failed:
        return "failed_not_stored"
    return "cached" if summary.cached else "regenerated"


async def _version_ids() -> list[uuid.UUID]:
    async with _session_factory()() as db:
        return list(
            (
                await db.execute(
                    sa.select(DocumentIR.document_version_id).order_by(
                        DocumentIR.document_version_id
                    )
                )
            )
            .scalars()
            .all()
        )


async def main(
    *,
    dry_run: bool,
    pdf_dir: Path | None,
    use_storage: bool,
    summaries: bool,
    expect_db: str | None,
    report: Path | None,
) -> None:
    settings = get_settings()
    if not dry_run and expect_db != settings.postgres_db:
        sys.exit(
            f"refusing to write: POSTGRES_DB is {settings.postgres_db!r}; "
            "pass --expect-db with that exact name (after taking a backup)"
        )
    print(
        f"database {settings.postgres_db!r}, parser {PARSER_VERSION}, "
        f"{'DRY RUN' if dry_run else 'WRITE'}"
    )
    try:
        index = PdfIndex.from_directory(pdf_dir)
        storage = S3Storage() if use_storage else None
        usage = Usage()
        provider, summary_client = (
            (None, None) if dry_run else _counting_providers(usage)
        )
        results: list[VersionResult] = []
        for position, version_id in enumerate(await _version_ids(), start=1):
            async with _session_factory()() as db:
                try:
                    result = await reindex_version(
                        db,
                        version_id,
                        index,
                        provider,
                        dry_run=dry_run,
                        storage=storage,
                    )
                except Exception as exc:
                    result = VersionResult(str(version_id), "error")
                    print(f"  error: {type(exc).__name__}")
            results.append(result)
            print(f"[{position}] {version_id}: {result.outcome}", flush=True)

        summary_outcomes: Counter[str] = Counter()
        if summaries and not dry_run:
            client = summary_client
            for result in results:
                if result.outcome not in ("reindexed", "up_to_date", "pdf_missing"):
                    continue
                async with _session_factory()() as db:
                    try:
                        outcome = await refresh_summary(
                            db, uuid.UUID(result.version_id), client
                        )
                    except Exception as exc:
                        outcome = f"error:{type(exc).__name__}"
                summary_outcomes[outcome] += 1
                print(f"summary {result.version_id}: {outcome}", flush=True)

        totals = Counter(r.outcome for r in results)
        print("versions:", dict(totals))
        if summaries:
            print("summaries:", dict(summary_outcomes))
        print("usage:", {"llm": usage.llm, "embedding": usage.embedding})
        if report is not None:
            report.write_text(
                json.dumps(
                    {
                        "database": settings.postgres_db,
                        "parser_version": PARSER_VERSION,
                        "dry_run": dry_run,
                        "versions": [asdict(r) for r in results],
                        "summaries": dict(summary_outcomes),
                        "usage": {"llm": usage.llm, "embedding": usage.embedding},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
    finally:
        await _engine().dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pdf-dir", type=Path, default=None)
    parser.add_argument("--no-storage", action="store_true")
    parser.add_argument("--summaries", action="store_true")
    parser.add_argument("--expect-db", default=None)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    asyncio.run(
        main(
            dry_run=args.dry_run,
            pdf_dir=args.pdf_dir,
            use_storage=not args.no_storage,
            summaries=args.summaries,
            expect_db=args.expect_db,
            report=args.report,
        )
    )
