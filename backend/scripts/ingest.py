"""Corpus ingestion CLI — build Nyaya's own searchable judgment store.

Thin wrapper over `app.services.ingest`. Fetches judgments from Indian Kanoon
(cached), chunks (legal-aware), embeds, and stores them for hybrid retrieval.

Two sinks:
  * jsonl     -> data/corpus.jsonl, read by the in-memory backend (no DB). Great
                 for growing a local/demo corpus; 0 IK credits per search after.
  * postgres  -> pgvector (needs DATABASE_URL). Production backend.

Examples:
    # From ad-hoc queries into the local JSONL corpus:
    python -m scripts.ingest --query "section 138 negotiable instruments dishonour" \
                             --query "anticipatory bail section 438" --per-query 30

    # From a curated query list into pgvector:
    python -m scripts.ingest --queries-file data/ingest_queries.txt \
                             --sink postgres

    # From explicit Indian Kanoon doc ids:
    python -m scripts.ingest --doc-ids 1766147 1233094 --sink jsonl

Respect the Indian Kanoon ToS + rate limits (see docs/DATA_SOURCES.md). Only
ingest content you are licensed to store.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from app.services import ingest

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def _read_queries_file(path: str) -> list[str]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    # Ignore blanks and #-comments.
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


async def _run(args) -> None:
    queries: list[str] = list(args.query or [])
    if args.queries_file:
        queries.extend(_read_queries_file(args.queries_file))

    summary = await ingest.run_ingest(
        queries=queries or None,
        doc_ids=args.doc_ids or None,
        per_query=args.per_query,
        court_level=args.court_level,
        sink=args.sink,
    )
    logging.getLogger("nyaya.ingest").info("Ingest complete: %s", summary)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest judgments into Nyaya's corpus.")
    ap.add_argument("--query", action="append", help="Search query (repeatable).")
    ap.add_argument("--queries-file", help="File with one query per line (#=comment).")
    ap.add_argument("--doc-ids", nargs="*", default=[], help="Explicit IK doc ids.")
    ap.add_argument("--per-query", type=int, default=20, help="Docs per query.")
    ap.add_argument("--court-level", default="any",
                    choices=["any", "supreme_court", "high_court"])
    ap.add_argument("--sink", default="jsonl", choices=["jsonl", "postgres"])
    args = ap.parse_args()

    if not (args.query or args.queries_file or args.doc_ids):
        ap.error("provide --query, --queries-file, or --doc-ids")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
