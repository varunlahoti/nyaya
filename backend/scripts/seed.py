"""Load the seed judgment corpus into pgvector (for the postgres backend).

For dev/demo you don't need this — set VECTOR_BACKEND=memory and the seed loads
into RAM at startup. Use this to persist the seed corpus into Postgres for a
production-like setup.

    python -m scripts.seed
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from app.config import settings
from app.services.embeddings import embed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nyaya.seed")


async def main():
    if not settings.DATABASE_URL:
        raise SystemExit("Set DATABASE_URL to seed Postgres.")
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    path = Path(__file__).resolve().parents[1] / settings.SEED_CORPUS_PATH
    records = json.loads(path.read_text(encoding="utf-8"))
    texts = [f"{r.get('title','')}. {r.get('text','')}" for r in records]
    vectors = await embed(texts)

    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        for rec, vec in zip(records, vectors):
            await conn.execute(
                text(
                    """INSERT INTO judgments (id, source, source_doc_id, citation,
                            title, court, court_level, date, url, full_text)
                       VALUES (:id,:source,:sdid,:cit,:title,:court,:lvl,
                            NULLIF(:date,'')::date,:url,:full)
                       ON CONFLICT (id) DO NOTHING"""
                ),
                {
                    "id": rec["id"], "source": rec["source"],
                    "sdid": rec["id"], "cit": rec.get("citation"),
                    "title": rec["title"], "court": rec.get("court"),
                    "lvl": rec.get("court_level"), "date": rec.get("date") or "",
                    "url": rec.get("url"), "full": rec.get("text", ""),
                },
            )
            await conn.execute(
                text(
                    """INSERT INTO judgment_chunks (judgment_id, chunk_index, text, embedding)
                       VALUES (:jid, 0, :text, :emb)"""
                ),
                {"jid": rec["id"], "text": rec.get("text", ""), "emb": str(vec)},
            )
    await engine.dispose()
    logger.info("Seeded %d judgments into Postgres.", len(records))


if __name__ == "__main__":
    asyncio.run(main())
