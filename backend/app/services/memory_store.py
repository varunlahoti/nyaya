"""In-memory hybrid corpus — zero-DB semantic + lexical retrieval for dev/demo.

Loads a seed set of judgments, chunks each one (legal-aware), embeds the chunks
once at startup, and builds a BM25 index over the same chunks. It answers BOTH
`knn_search` (vector) and `keyword_search` (BM25), plus `get_judgment`, so the
VectorRetriever and BM25Retriever both drop straight in with no Postgres.

This is what lets you run real hybrid searches offline: seed once, then every
search hits local RAM and spends ZERO Indian Kanoon credits.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from .chunking import chunk
from .embeddings import embed
from .lexical import BM25Index

logger = logging.getLogger("nyaya.memory_store")


class InMemoryCorpus:
    def __init__(self):
        self._judgments: Dict[str, Dict[str, Any]] = {}
        # Each chunk: {judgment_id, text, embedding}
        self._chunks: List[Dict[str, Any]] = []
        self._bm25 = BM25Index()

    @classmethod
    async def from_seed(cls, path: str) -> "InMemoryCorpus":
        corpus = cls()
        p = Path(path)
        if not p.is_absolute():
            # Resolve relative to the backend package root.
            p = Path(__file__).resolve().parents[2] / path
        if not p.exists():
            logger.warning("Seed corpus not found at %s; corpus is empty.", p)
            return corpus
        records = json.loads(p.read_text(encoding="utf-8"))
        await corpus.load(records)
        return corpus

    async def load(self, records: List[Dict[str, Any]]) -> None:
        """(Re)build the corpus from judgment records (id/title/text/…)."""
        texts: List[str] = []
        chunk_meta: List[Dict[str, Any]] = []
        for rec in records:
            jid = rec["id"]
            self._judgments[jid] = rec
            # Chunk the full text (legal-aware); fall back to title if empty.
            body = rec.get("text", "") or ""
            pieces = chunk(body) or [rec.get("title", "")]
            for piece in pieces:
                searchable = f"{rec.get('title','')}. {piece}".strip()
                texts.append(searchable)
                chunk_meta.append({"judgment_id": jid, "text": piece})

        vectors = await embed(texts) if texts else []
        self._chunks = []
        for meta, vec, searchable in zip(chunk_meta, vectors, texts):
            self._chunks.append({**meta, "embedding": vec, "_search": searchable})

        # BM25 over the same (title + chunk) searchable text.
        self._bm25.build([c["_search"] for c in self._chunks])
        logger.info(
            "Corpus ready: %d judgments, %d chunks (vector + BM25).",
            len(self._judgments), len(self._chunks),
        )

    # ------------------------------------------------------------------ #
    def _row(self, j: Dict[str, Any], chunk_text: str, **extra) -> Dict[str, Any]:
        return {
            "judgment_id": j["id"],
            "title": j.get("title", ""),
            "url": j.get("url"),
            "citation": j.get("citation"),
            "court": j.get("court"),
            "court_level": j.get("court_level"),
            "date": j.get("date"),
            "cites": j.get("cites", 0),
            "chunk_text": chunk_text,
            **extra,
        }

    def _passes_court(self, j: Dict[str, Any], court_level: Optional[str]) -> bool:
        return not court_level or j.get("court_level") in (court_level, None)

    async def knn_search(
        self, embedding: List[float], limit: int, court_level: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        scored = []
        for ch in self._chunks:
            j = self._judgments[ch["judgment_id"]]
            if not self._passes_court(j, court_level):
                continue
            sim = _cosine(embedding, ch["embedding"])
            scored.append((sim, ch, j))
        scored.sort(key=lambda x: x[0], reverse=True)
        # Collapse to best chunk per judgment so one long case can't flood the list.
        return _dedupe_by_judgment(
            (self._row(j, ch["text"], distance=1.0 - sim) for sim, ch, j in scored),
            limit,
        )

    async def keyword_search(
        self, query: str, limit: int, court_level: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        hits = self._bm25.search(query, limit=limit * 4)  # over-fetch, then filter/dedupe
        rows_iter = []
        for idx, score in hits:
            ch = self._chunks[idx]
            j = self._judgments[ch["judgment_id"]]
            if not self._passes_court(j, court_level):
                continue
            rows_iter.append(self._row(j, ch["text"], score=score))
        return _dedupe_by_judgment(rows_iter, limit)

    async def get_judgment(self, judgment_id: str) -> Optional[Dict[str, Any]]:
        j = self._judgments.get(judgment_id)
        if not j:
            return None
        return {
            "title": j.get("title", ""),
            "url": j.get("url"),
            "citation": j.get("citation"),
            "court": j.get("court"),
            "date": j.get("date"),
            "full_text": j.get("text", ""),
        }


def _dedupe_by_judgment(rows, limit: int) -> List[Dict[str, Any]]:
    """Keep the first (best-ranked) row per judgment; preserve input order."""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        jid = r["judgment_id"]
        if jid in seen:
            continue
        seen.add(jid)
        out.append(r)
        if len(out) >= limit:
            break
    return out


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
