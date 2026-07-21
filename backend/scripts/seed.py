"""Load the seed judgment corpus into pgvector (for the postgres backend).

For dev/demo you don't need this — set VECTOR_BACKEND=memory and the seed loads
into RAM at startup. Use this to persist the seed corpus into Postgres for a
production-like setup (chunks + embeds + full-text, same path as ingestion).

    python -m scripts.seed
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from app.config import settings
from app.services import ingest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nyaya.seed")


async def main() -> None:
    if not settings.DATABASE_URL:
        raise SystemExit("Set DATABASE_URL to seed Postgres.")
    from app.db.base import VectorStore

    path = Path(__file__).resolve().parents[1] / settings.SEED_CORPUS_PATH
    records = json.loads(path.read_text(encoding="utf-8"))

    store = VectorStore()
    await store.ensure_corpus_schema()
    chunks = await ingest.ingest_to_postgres(records, store)
    logger.info("Seeded %d judgments / %d chunks into Postgres.", len(records), chunks)


if __name__ == "__main__":
    asyncio.run(main())
