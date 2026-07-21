"""Legal-aware text chunking for the ingestion + corpus pipeline.

Indian judgments are long and structured (headnote, facts, issues, arguments,
"held", obiter). Naive fixed-window chunking splits a holding mid-sentence and
buries it across two chunks, which hurts both embedding quality and BM25 recall.

This chunker:
  * splits on paragraph boundaries first (judgments use blank lines / numbered
    paragraphs), never mid-sentence,
  * packs paragraphs into ~CHUNK_TARGET_CHARS windows with a small overlap so a
    holding that straddles a boundary still appears whole in one chunk,
  * hard-splits any single oversized paragraph on sentence boundaries.

Deterministic and dependency-free so it runs anywhere (incl. Python 3.9).
"""
from __future__ import annotations

import re
from typing import List

from ..config import settings

# Paragraph boundary: blank line, OR a numbered-paragraph marker common in
# Indian judgments ("12.", "(iv)", "Para 5") at line start.
_PARA_SPLIT = re.compile(r"\n\s*\n+|\n(?=\s*(?:\d{1,3}[.)]|\([ivxlcdm]+\)|\(\d+\))\s)")
_SENT_SPLIT = re.compile(r"(?<=[.?!])\s+(?=[A-Z(])")
_WS = re.compile(r"[ \t]+")


def _normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse runs of spaces/tabs but keep newlines (paragraph structure).
    return "\n".join(_WS.sub(" ", line).strip() for line in text.split("\n"))


def _paragraphs(text: str) -> List[str]:
    parts = [p.strip() for p in _PARA_SPLIT.split(text) if p and p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _split_oversized(para: str, limit: int) -> List[str]:
    """Break a single paragraph longer than `limit` on sentence boundaries."""
    if len(para) <= limit:
        return [para]
    out: List[str] = []
    buf = ""
    for sent in _SENT_SPLIT.split(para):
        # A single "sentence" longer than the limit (e.g. a table or a run with
        # no punctuation) is hard-wrapped by characters so no chunk runs away.
        while len(sent) > limit:
            if buf:
                out.append(buf)
                buf = ""
            out.append(sent[:limit])
            sent = sent[limit:]
        if buf and len(buf) + 1 + len(sent) > limit:
            out.append(buf)
            buf = sent
        else:
            buf = f"{buf} {sent}".strip()
    if buf:
        out.append(buf)
    return out


def chunk(
    text: str,
    target_chars: int | None = None,
    overlap_chars: int | None = None,
    max_chunks: int | None = None,
) -> List[str]:
    """Split judgment text into overlapping, paragraph-aligned chunks."""
    target = target_chars or settings.CHUNK_TARGET_CHARS
    overlap = overlap_chars or settings.CHUNK_OVERLAP_CHARS
    cap = max_chunks or settings.CHUNK_MAX_PER_DOC

    text = _normalise(text or "")
    if not text:
        return []

    # Expand oversized paragraphs, then greedily pack paragraphs into windows.
    paras: List[str] = []
    for p in _paragraphs(text):
        paras.extend(_split_oversized(p, target))

    chunks: List[str] = []
    buf = ""
    for p in paras:
        if buf and len(buf) + 2 + len(p) > target:
            chunks.append(buf)
            # Carry a tail of the previous chunk forward for context overlap.
            tail = buf[-overlap:] if overlap else ""
            buf = f"{tail} {p}".strip() if tail else p
        else:
            buf = f"{buf}\n\n{p}".strip() if buf else p
        if len(chunks) >= cap:
            break
    if buf and len(chunks) < cap:
        chunks.append(buf)

    return chunks[:cap]
