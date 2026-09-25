"""One-off: chunk + embed every DocumentIR that has no document_chunks yet.

Runs strictly sequentially (one version at a time) so it never bursts past the
embedding API rate limit.

    uv run python -m scripts.backfill_chunks
    uv run python -m scripts.backfill_chunks --fill-embeddings   # after adding a key
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter

import sqlalchemy as sa

from app.db.session import _engine, _session_factory
from app.models.analysis import DocumentIR
from app.models.chunk import DocumentChunk
from app.workers.index_document_chunks import _default_provider, index_document_version


async def _pending_version_ids(fill_embeddings: bool) -> list:
    async with _session_factory()() as db:
        no_chunks = sa.select(DocumentIR.document_version_id).where(
            ~sa.exists().where(
                DocumentChunk.document_version_id == DocumentIR.document_version_id
            )
        )
        ids = list((await db.execute(no_chunks)).scalars().all())
        if fill_embeddings:
            missing_vectors = (
                sa.select(DocumentChunk.document_version_id)
                .where(DocumentChunk.embedding.is_(None))
                .distinct()
            )
            ids += list((await db.execute(missing_vectors)).scalars().all())
        return list(dict.fromkeys(ids))


async def main(fill_embeddings: bool) -> None:
    try:
        version_ids = await _pending_version_ids(fill_embeddings)
        print(f"{len(version_ids)} document version(s) to index")
        provider = _default_provider()
        outcomes: Counter[str] = Counter()
        for position, version_id in enumerate(version_ids, start=1):
            async with _session_factory()() as db:
                outcome = await index_document_version(db, version_id, provider)
            outcomes[outcome] += 1
            print(f"[{position}/{len(version_ids)}] {version_id}: {outcome}")
        print("Done:", dict(outcomes) or "nothing to do")
    finally:
        await _engine().dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fill-embeddings",
        action="store_true",
        help="Also embed chunks stored earlier without a vector",
    )
    args = parser.parse_args()
    asyncio.run(main(args.fill_embeddings))
