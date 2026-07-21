"""Corpus ingestion — build our own searchable judgment store.

Flow:  seed queries / doc-ids  ->  Indian Kanoon full-text fetch (cached)
       ->  normalise  ->  chunk (legal-aware)  ->  embed  ->  store.

Two sinks:
  * JSONL (`data/corpus.jsonl`)  — feeds the in-memory backend. The corpus is
    chunked + embedded at load time, so JSONL only stores normalised judgments.
  * Postgres/pgvector            — chunks + embeds here and upserts rows, for
    the production backend.

Idempotent (upsert by id) and resumable (JSONL append is de-duped on load).
Rate-limited by INGEST_CONCURRENCY so we stay polite to Indian Kanoon.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..config import settings
from .chunking import chunk
from .embeddings import embed
from .retrievers.indian_kanoon import IndianKanoonRetriever, _infer_level

logger = logging.getLogger("nyaya.ingest")


def _resolve(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[2] / path
    return p


# --------------------------------------------------------------------------- #
# 1. Discover judgment ids
# --------------------------------------------------------------------------- #
async def gather_doc_ids(
    queries: Iterable[str],
    per_query: int = 20,
    court_level: str = "any",
) -> List[str]:
    """Run seed queries through Indian Kanoon search; collect unique doc ids."""
    from ..schemas import RetrievalQuery

    ik = IndianKanoonRetriever()
    if not ik.enabled():
        raise RuntimeError("INDIAN_KANOON_API_TOKEN not set — cannot ingest from IK.")

    ids: List[str] = []
    seen: set = set()
    for q in queries:
        cands = await ik.search(RetrievalQuery(
            text=q, court_level=court_level, jurisdiction=court_level, limit=per_query,
        ))
        for c in cands:
            if c.source_doc_id not in seen:
                seen.add(c.source_doc_id)
                ids.append(c.source_doc_id)
        if len(ids) >= settings.INGEST_MAX_DOCS:
            break
    return ids[: settings.INGEST_MAX_DOCS]


# --------------------------------------------------------------------------- #
# 2. Fetch + normalise full judgments
# --------------------------------------------------------------------------- #
async def fetch_judgments(doc_ids: List[str]) -> List[Dict[str, Any]]:
    """Fetch full text for each id (concurrency-limited) → normalised records."""
    ik = IndianKanoonRetriever()
    sem = asyncio.Semaphore(settings.INGEST_CONCURRENCY)

    async def one(docid: str) -> Optional[Dict[str, Any]]:
        async with sem:
            doc = await ik.fetch_document(docid)
        if not doc or not doc.text:
            return None
        cites = 0
        try:
            cites = int(doc.metadata.get("numcitedby") or 0)
        except (TypeError, ValueError):
            cites = 0
        return {
            "id": f"ik_{docid}",
            "source": "indian_kanoon",
            "title": doc.title,
            "citation": doc.citation,
            "court": doc.court,
            "court_level": _infer_level(doc.court or ""),
            "date": doc.date,
            "url": doc.url,
            "cites": cites,
            "text": doc.text,
        }

    results = await asyncio.gather(*(one(d) for d in doc_ids), return_exceptions=True)
    records = [r for r in results if isinstance(r, dict)]
    logger.info("Fetched %d/%d judgments.", len(records), len(doc_ids))
    return records


# --------------------------------------------------------------------------- #
# 3a. Sink: JSONL (in-memory backend)
# --------------------------------------------------------------------------- #
def write_jsonl(records: List[Dict[str, Any]], path: Optional[str] = None) -> int:
    """Upsert records into the JSONL corpus (de-dupe by id, newest wins)."""
    p = _resolve(path or settings.CORPUS_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)

    existing: Dict[str, Dict[str, Any]] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rec = json.loads(line)
                existing[rec["id"]] = rec
    for rec in records:
        existing[rec["id"]] = rec

    with p.open("w", encoding="utf-8") as f:
        for rec in existing.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    logger.info("Corpus JSONL now holds %d judgments (%s).", len(existing), p)
    return len(existing)


def load_jsonl(path: Optional[str] = None) -> List[Dict[str, Any]]:
    p = _resolve(path or settings.CORPUS_PATH)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# --------------------------------------------------------------------------- #
# 3b. Sink: Postgres / pgvector (production backend)
# --------------------------------------------------------------------------- #
async def ingest_to_postgres(records: List[Dict[str, Any]], store) -> int:
    """Chunk + embed each judgment and upsert it (+ chunks) into pgvector."""
    total_chunks = 0
    for rec in records:
        pieces = chunk(rec.get("text", "")) or [rec.get("title", "")]
        searchable = [f"{rec.get('title','')}. {p}".strip() for p in pieces]
        vectors: List[List[float]] = []
        for i in range(0, len(searchable), settings.EMBEDDINGS_BATCH):
            vectors.extend(await embed(searchable[i:i + settings.EMBEDDINGS_BATCH]))
        await store.upsert_judgment(rec, list(zip(pieces, vectors)))
        total_chunks += len(pieces)
    logger.info("Upserted %d judgments / %d chunks into pgvector.", len(records), total_chunks)
    return total_chunks


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
async def run_ingest(
    queries: Optional[List[str]] = None,
    doc_ids: Optional[List[str]] = None,
    per_query: int = 20,
    court_level: str = "any",
    sink: str = "jsonl",
    store=None,
) -> Dict[str, Any]:
    """End-to-end: discover ids → fetch → store. Returns a small run summary."""
    if not doc_ids:
        if not queries:
            raise ValueError("Provide either queries or doc_ids to ingest.")
        doc_ids = await gather_doc_ids(queries, per_query=per_query, court_level=court_level)

    records = await fetch_judgments(doc_ids)
    if not records:
        return {"fetched": 0, "stored": 0, "sink": sink}

    if sink == "postgres":
        if store is None:
            from ..db.base import VectorStore
            store = VectorStore()
        await store.ensure_corpus_schema()
        chunks = await ingest_to_postgres(records, store)
        return {"fetched": len(records), "stored": len(records), "chunks": chunks, "sink": sink}

    stored = write_jsonl(records)
    return {"fetched": len(records), "stored": stored, "sink": sink}
