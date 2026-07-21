"""Bulk corpus ingestion — load open judgment datasets, IK-independent.

Indian Kanoon is the only *live* external source; everything else in the corpus
was ingested from IK, so IK effectively ranks every result. This module breaks
that dependency by loading **open, freely-licensed judgment datasets** (e.g.
HuggingFace ILDC / opennyai exports, the Supreme Court's own bulk archive) into
the same corpus. Once ingested they are retrieved by *our* hybrid RRF, not IK's
ranking — so a good case surfaces even when IK buries it, and cases IK lacks (or
OCRs poorly) become searchable from a cleaner source.

Design: a **generic normaliser**, not a per-dataset parser. Every open dataset
uses different column names, so we map arbitrary source fields onto our canonical
judgment schema via a field map, then reuse the existing JSONL / pgvector sinks
(`ingest.write_jsonl`, `ingest.ingest_to_postgres`). Point it at any JSONL or CSV
export:

    from app.services import bulk_ingest
    records = bulk_ingest.load_bulk(
        "data/ildc.jsonl", source="ildc", fmt="jsonl",
        field_map={"text": "judgment", "title": "name", "date": "decision_date"},
    )

Canonical schema (matches ingest.fetch_judgments output):
    id, source, title, citation, court, court_level, date, url, cites, text

Only ingest content you are licensed to store (see docs/DATA_SOURCES.md).
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .retrievers.indian_kanoon import _infer_level

logger = logging.getLogger("nyaya.bulk_ingest")

# Canonical fields we try to populate for every record.
CANONICAL = ("id", "title", "citation", "court", "date", "url", "cites", "text")

# Common column-name aliases across open Indian-law datasets → canonical field.
# A user-supplied field_map always wins over these defaults.
DEFAULT_ALIASES: Dict[str, str] = {
    # text / body
    "text": "text", "judgment": "text", "judgement": "text", "body": "text",
    "full_text": "text", "content": "text", "case_text": "text", "raw_text": "text",
    # title / case name
    "title": "title", "name": "title", "case_name": "title", "case_title": "title",
    "casename": "title",
    # citation
    "citation": "citation", "cite": "citation", "neutral_citation": "citation",
    "citations": "citation",
    # court
    "court": "court", "docsource": "court", "bench": "court", "court_name": "court",
    # date
    "date": "date", "decision_date": "date", "publishdate": "date",
    "judgment_date": "date", "date_of_judgment": "date",
    # url
    "url": "url", "link": "url", "source_url": "url",
    # citation count (authority signal)
    "cites": "cites", "numcitedby": "cites", "num_cited_by": "cites",
    "cited_by": "cites",
    # id
    "id": "id", "doc_id": "id", "docid": "id", "tid": "id", "case_id": "id",
}


def _resolve_map(field_map: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Build source-col → canonical lookup: defaults, overlaid by user's map.

    `field_map` is given canonical->source ("text": "judgment") for readability;
    we invert it to source->canonical and layer it over the aliases.
    """
    resolved = dict(DEFAULT_ALIASES)
    for canonical, source_col in (field_map or {}).items():
        resolved[source_col] = canonical
    return resolved


def _stable_id(source: str, raw: Dict[str, Any], mapped: Dict[str, Any]) -> str:
    """`{source}_{origid}` when the dataset has an id, else a content hash.

    Content hash keeps ingestion idempotent (re-running upserts, never dupes)
    even for datasets with no native identifier.
    """
    if mapped.get("id"):
        return f"{source}_{mapped['id']}"
    basis = f"{mapped.get('title','')}|{mapped.get('date','')}|{str(mapped.get('text','') or '')[:200]}"
    digest = hashlib.sha1(basis.encode("utf-8", "ignore")).hexdigest()[:16]
    return f"{source}_{digest}"


def _empty(v: Any) -> bool:
    """True for None, blank, or NaN/NaT — treat all as missing.

    NaN (float) and pandas NaT share the property of not equalling themselves,
    which catches both without importing pandas on the jsonl/csv paths.
    """
    if v is None or v == "":
        return True
    try:
        return bool(v != v)
    except Exception:  # noqa: BLE001 — non-scalar; treat as present
        return False


def _s(v: Any) -> Optional[str]:
    """Coerce a scalar to a stripped str (parquet gives Timestamps/ints)."""
    if _empty(v):
        return None
    return str(v).strip() or None


def normalize_record(
    raw: Dict[str, Any], source: str, colmap: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """Map one raw dataset row onto the canonical judgment record (or None)."""
    mapped: Dict[str, Any] = {}
    for col, value in raw.items():
        canonical = colmap.get(col) or colmap.get(str(col).lower())
        if canonical and canonical in CANONICAL and not _empty(value):
            mapped[canonical] = value

    text = _s(mapped.get("text"))
    if not text:
        return None  # no body → nothing to retrieve on; skip

    try:
        cites = int(mapped.get("cites") or 0)
    except (TypeError, ValueError):
        cites = 0

    court = _s(mapped.get("court"))
    return {
        "id": _stable_id(source, raw, mapped),
        "source": source,
        "title": _s(mapped.get("title")) or "Untitled judgment",
        "citation": _s(mapped.get("citation")),
        "court": court,
        "court_level": _infer_level(court or ""),
        "date": _s(mapped.get("date")),
        "url": _s(mapped.get("url")),
        "cites": cites,
        "text": text,
    }


def _richness(rec: Dict[str, Any]) -> tuple:
    """On id collision, prefer the fuller record: longer text, then more cites."""
    return (len(rec.get("text") or ""), rec.get("cites") or 0)


def _iter_rows(path: Path, fmt: str) -> Iterable[Dict[str, Any]]:
    if fmt == "jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                yield json.loads(line)
    elif fmt == "json":
        data = json.loads(path.read_text(encoding="utf-8"))
        yield from (data if isinstance(data, list) else [data])
    elif fmt == "csv":
        with path.open(encoding="utf-8", newline="") as f:
            yield from csv.DictReader(f)
    elif fmt == "parquet":
        # HuggingFace datasets ship as parquet — read via pandas (pyarrow engine).
        import pandas as pd

        for _, row in pd.read_parquet(path).iterrows():
            yield row.to_dict()
    elif fmt == "pdf-dir":
        # A directory of judgment PDFs (e.g. downloaded official SCR/HC PDFs).
        # Each file → one record; filename stem is the id/title fallback.
        yield from _iter_pdf_dir(path)
    else:
        raise ValueError(
            f"Unsupported bulk format: {fmt!r} (use jsonl/json/csv/parquet/pdf-dir)"
        )


def _iter_pdf_dir(path: Path) -> Iterable[Dict[str, Any]]:
    """Extract text from every *.pdf under `path` → raw rows for normalisation."""
    from pypdf import PdfReader

    pdfs = sorted(path.glob("**/*.pdf")) if path.is_dir() else [path]
    for pdf in pdfs:
        try:
            reader = PdfReader(str(pdf))
            text = "\n".join((pg.extract_text() or "") for pg in reader.pages).strip()
        except Exception as exc:  # noqa: BLE001 — a corrupt PDF shouldn't kill the batch
            logger.warning("PDF extract failed for %s: %s", pdf.name, exc)
            continue
        if not text:
            logger.warning("No extractable text (likely scanned/needs OCR): %s", pdf.name)
            continue
        # Canonical column names so the default aliases pick them up directly.
        yield {"id": pdf.stem, "title": pdf.stem.replace("_", " "), "text": text}


def load_bulk(
    path: str,
    source: str,
    fmt: str = "jsonl",
    field_map: Optional[Dict[str, str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Read + normalise a dataset file into canonical judgment records.

    De-dupes by id (idempotent). Records with no body text are dropped.
    """
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[2] / path
    if not p.exists():
        raise FileNotFoundError(f"Bulk dataset not found: {p}")

    colmap = _resolve_map(field_map)
    out: Dict[str, Dict[str, Any]] = {}
    seen = skipped = 0
    for raw in _iter_rows(p, fmt):
        seen += 1
        rec = normalize_record(raw, source, colmap)
        if rec is None:
            skipped += 1
            continue
        # De-dupe by id, keeping the richer copy (longer text, then more cites)
        # so a truncated/degenerate duplicate can't clobber the full record.
        prev = out.get(rec["id"])
        if prev is None or _richness(rec) > _richness(prev):
            out[rec["id"]] = rec
        if limit and len(out) >= limit:
            break

    logger.info(
        "Bulk load %s: %d rows read, %d normalised, %d skipped (no text).",
        source, seen, len(out), skipped,
    )
    return list(out.values())
