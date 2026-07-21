"""Bulk-ingest an open judgment dataset into Nyaya's corpus (IK-independent).

Loads a freely-licensed JSONL/CSV judgment export (HuggingFace ILDC / opennyai
exports, Supreme Court bulk archive, etc.), maps its columns onto the canonical
schema, and stores it in the same corpus IK feeds — so retrieval is *your* hybrid
RRF, not IK's ranking. See docs/DATA_SOURCES.md before ingesting: only load
content you are licensed to store.

Field mapping: pass `--map canonical=source_column` (repeatable). Common column
names are auto-detected, so you usually only map the odd one out.

Examples:
    # Pull a HuggingFace dataset file straight in (parquet auto-detected):
    python -m scripts.bulk_ingest --hf-repo opennyai/InJudgements \
        --hf-file data/train.parquet --source injudgements --map text=judgment

    # A local JSONL export → local JSONL corpus
    python -m scripts.bulk_ingest --path data/ildc.jsonl --source ildc \
        --map text=judgment --map title=name --map date=decision_date

    # A folder of official SCR/HC judgment PDFs → pgvector (production backend)
    python -m scripts.bulk_ingest --path data/scr_pdfs/ --source scr_bulk \
        --format pdf-dir --sink postgres
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from app.services import bulk_ingest, ingest

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("nyaya.bulk_ingest")


def _parse_map(pairs: list[str]) -> dict[str, str]:
    """['text=judgment', 'title=name'] → {'text': 'judgment', 'title': 'name'}."""
    field_map: dict[str, str] = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"--map expects canonical=source_column, got {p!r}")
        canonical, source_col = p.split("=", 1)
        field_map[canonical.strip()] = source_col.strip()
    return field_map


_EXT_FORMAT = {".jsonl": "jsonl", ".json": "json", ".csv": "csv", ".parquet": "parquet"}


def _resolve_source(args) -> tuple[str, str]:
    """Return (local_path, format), downloading from HuggingFace if requested."""
    if args.hf_repo:
        from huggingface_hub import hf_hub_download

        if not args.hf_file:
            raise SystemExit("--hf-repo needs --hf-file (path within the dataset repo).")
        log.info("Downloading %s:%s from HuggingFace…", args.hf_repo, args.hf_file)
        path = hf_hub_download(
            repo_id=args.hf_repo, filename=args.hf_file, repo_type="dataset",
        )
    else:
        if not args.path:
            raise SystemExit("Provide --path or --hf-repo/--hf-file.")
        path = args.path
    # Auto-detect format from the extension unless the user forced one.
    fmt = args.format or _EXT_FORMAT.get(Path(path).suffix.lower(), "jsonl")
    return path, fmt


async def _run(args) -> None:
    path, fmt = _resolve_source(args)
    records = bulk_ingest.load_bulk(
        path=path,
        source=args.source,
        fmt=fmt,
        field_map=_parse_map(args.map),
        limit=args.limit,
    )
    if not records:
        log.warning("No records ingested (empty or all rows lacked body text).")
        return

    if args.sink == "postgres":
        from app.db.base import VectorStore

        store = VectorStore()
        await store.ensure_corpus_schema()
        chunks = await ingest.ingest_to_postgres(records, store)
        log.info("Bulk ingest complete: %d judgments / %d chunks → pgvector.",
                 len(records), chunks)
    else:
        stored = ingest.write_jsonl(records)
        log.info("Bulk ingest complete: corpus JSONL now holds %d judgments.", stored)


def main() -> None:
    ap = argparse.ArgumentParser(description="Bulk-ingest an open judgment dataset.")
    ap.add_argument("--path", help="Local dataset file or directory.")
    ap.add_argument("--hf-repo", help="HuggingFace dataset repo id to download from.")
    ap.add_argument("--hf-file", help="File path within the HF dataset repo.")
    ap.add_argument("--source", required=True,
                    help="Source tag stored on each record (e.g. ildc, scr_bulk).")
    ap.add_argument("--format", default=None,
                    choices=["jsonl", "json", "csv", "parquet", "pdf-dir"],
                    help="Override the auto-detected format (by file extension).")
    ap.add_argument("--map", action="append", default=[],
                    help="Field map canonical=source_column (repeatable).")
    ap.add_argument("--limit", type=int, help="Max records to ingest (for testing).")
    ap.add_argument("--sink", default="jsonl", choices=["jsonl", "postgres"])
    asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    main()
