"""One-off: load data/corpus.jsonl into the Neon pgvector store (resumable).

Skips judgments already stored (idempotent + resumable across restarts), so a
run interrupted by the free-tier rate limit can just be re-run to continue.
Progress is logged so a background run can be monitored.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from app.db.base import VectorStore
from app.services import ingest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("load_neon")


async def _existing_ids(store) -> set:
    from sqlalchemy import text
    async with store._sm() as s:
        res = await s.execute(text("SELECT id FROM judgments"))
        return {r[0] for r in res}


async def main() -> None:
    records = [json.loads(l) for l in Path("data/corpus.jsonl").read_text().splitlines() if l.strip()]
    store = VectorStore()
    await store.ensure_corpus_schema()
    done = await _existing_ids(store)
    todo = [r for r in records if r["id"] not in done]
    log.info("corpus=%d already=%d todo=%d", len(records), len(done), len(todo))

    BATCH = 25  # judgments per progress checkpoint
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        await ingest.ingest_to_postgres(chunk, store)
        log.info("stored %d/%d", min(i + BATCH, len(todo)), len(todo))
    log.info("DONE — %d judgments now in Neon", len(await _existing_ids(store)))


if __name__ == "__main__":
    asyncio.run(main())
