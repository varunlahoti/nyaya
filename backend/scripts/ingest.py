"""Corpus ingestion: fetch judgments, chunk, embed, and store in pgvector.

This closes the loop for the internal vector retriever. Point it at Indian Kanoon
doc ids (or feed your own licensed corpus) to build the semantic index that
powers fact-pattern retrieval.

Usage:
    python -m scripts.ingest --doc-ids 1983203 1766147 ...
    python -m scripts.ingest --query "section 138 negotiable instruments" --limit 50

Requires DATABASE_URL (and, for real embeddings, an embeddings key). Respect the
Indian Kanoon ToS and rate limits — see docs/DATA_SOURCES.md.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from typing import List

from app.config import settings
from app.services.embeddings import embed
from app.services.retrievers.indian_kanoon import IndianKanoonRetriever
from app.schemas import RetrievalQuery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nyaya.ingest")

CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200


def chunk(text: str) -> List[str]:
    chunks, i = [], 0
    while i < len(text):
        chunks.append(text[i : i + CHUNK_CHARS])
        i += CHUNK_CHARS - CHUNK_OVERLAP
    return [c for c in chunks if c.strip()]


async def _store(engine, doc, chunks: List[str], vectors: List[List[float]]):
    from sqlalchemy import text

    jid = f"j_{doc.source}_{doc.source_doc_id}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO judgments (id, source, source_doc_id, citation, title,
                        court, date, url, full_text)
                   VALUES (:id,:source,:sdid,:cit,:title,:court,
                        NULLIF(:date,'')::date,:url,:full)
                   ON CONFLICT (id) DO NOTHING"""
            ),
            {
                "id": jid, "source": doc.source, "sdid": doc.source_doc_id,
                "cit": doc.citation, "title": doc.title, "court": doc.court,
                "date": doc.date or "", "url": doc.url, "full": doc.text,
            },
        )
        for idx, (c, v) in enumerate(zip(chunks, vectors)):
            await conn.execute(
                text(
                    """INSERT INTO judgment_chunks (judgment_id, chunk_index, text, embedding)
                       VALUES (:jid,:idx,:text,:emb)"""
                ),
                {"jid": jid, "idx": idx, "text": c, "emb": str(v)},
            )
    logger.info("stored %s (%d chunks)", jid, len(chunks))


async def ingest_doc_ids(doc_ids: List[str]):
    if not settings.DATABASE_URL:
        raise SystemExit("Set DATABASE_URL to ingest.")
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.DATABASE_URL)
    ik = IndianKanoonRetriever()
    for did in doc_ids:
        doc = await ik.fetch_document(did)
        if not doc or not doc.text:
            logger.warning("skip %s (no document)", did)
            continue
        chunks = chunk(doc.text)
        vectors = await embed(chunks)
        await _store(engine, doc, chunks, vectors)
    await engine.dispose()


async def ingest_query(query: str, limit: int):
    ik = IndianKanoonRetriever()
    cands = await ik.search(RetrievalQuery(text=query, limit=limit))
    await ingest_doc_ids([c.source_doc_id for c in cands])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc-ids", nargs="*", default=[])
    ap.add_argument("--query", default=None)
    ap.add_argument("--limit", type=int, default=25)
    args = ap.parse_args()

    if args.query:
        asyncio.run(ingest_query(args.query, args.limit))
    elif args.doc_ids:
        asyncio.run(ingest_doc_ids(args.doc_ids))
    else:
        ap.error("provide --doc-ids or --query")


if __name__ == "__main__":
    main()
