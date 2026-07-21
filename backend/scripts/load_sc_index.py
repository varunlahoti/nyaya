"""Load the full Supreme Court citation index into Neon (resumable).

Source: HuggingFace `debkanchan/supreme-court-of-india-judgements` — ~37k SC
judgments (1950→) with official SCR + neutral citations, judges, dates, and
digiscr PDF links. No body text, so the searchable field is built from
title + case number + citations + bench; the PDF url enables full-text
deep-fetch of top hits later. This gives complete SC *coverage* (every case
findable by name/citation), fused with IK's fact-pattern search.
"""
from __future__ import annotations

import asyncio
import logging

from app.db.base import VectorStore
from app.services.embeddings import embed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("load_sc")

REPO = "debkanchan/supreme-court-of-india-judgements"
FILE = "data/train-00000-of-00001.parquet"
EMBED_BATCH = 128   # texts per Voyage call
DB_BATCH = 500      # judgments per Neon transaction


def _clean(v) -> str:
    return "" if v is None or v != v else str(v).strip()


def _record(row) -> dict:
    title = _clean(row.get("title"))
    neutral = _clean(row.get("neutral_citation"))
    scr = _clean(row.get("scr_citation"))
    judges = row.get("judges")
    judges = ", ".join(judges) if hasattr(judges, "__iter__") and not isinstance(judges, str) else _clean(judges)
    caseno = _clean(row.get("case_number"))
    fid = _clean(row.get("filename")) or (neutral or title)[:60]
    searchable = (f"{title}. {caseno}. Supreme Court of India. "
                  f"Citation: {scr} {neutral}. Bench: {judges}").strip()
    return {
        "id": f"scin_{fid}",
        "source": "sci_index",
        "title": title or "Supreme Court judgment",
        "citation": neutral or scr or None,
        "court": "Supreme Court of India",
        "court_level": "supreme_court",
        "date": _clean(row.get("date"))[:10] or None,
        "url": _clean(row.get("source")) or None,
        "cites": 0,
        "text": searchable,
    }


async def _existing_ids(store) -> set:
    from sqlalchemy import text
    async with store._sm() as s:
        res = await s.execute(text("SELECT id FROM judgments WHERE source = 'sci_index'"))
        return {r[0] for r in res}


async def main() -> None:
    from huggingface_hub import hf_hub_download
    import pandas as pd

    path = hf_hub_download(REPO, FILE, repo_type="dataset")
    df = pd.read_parquet(path)
    recs = [_record(r) for _, r in df.iterrows()]
    # de-dupe by id within the file
    recs = list({r["id"]: r for r in recs}.values())

    store = VectorStore()
    await store.ensure_corpus_schema()
    done = await _existing_ids(store)
    todo = [r for r in recs if r["id"] not in done]
    log.info("SC index: %d rows, %d already stored, %d to load", len(recs), len(done), len(todo))

    for i in range(0, len(todo), DB_BATCH):
        batch = todo[i:i + DB_BATCH]
        vectors: list = []
        texts = [r["text"] for r in batch]
        for j in range(0, len(texts), EMBED_BATCH):
            vectors.extend(await embed(texts[j:j + EMBED_BATCH]))
        items = [(r, [(r["text"], v)]) for r, v in zip(batch, vectors)]
        await store.bulk_insert(items)
        log.info("stored %d/%d", min(i + DB_BATCH, len(todo)), len(todo))
    log.info("DONE — SC index loaded")


if __name__ == "__main__":
    asyncio.run(main())
