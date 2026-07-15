"""In-memory vector corpus — zero-DB semantic retrieval for dev/demo.

Loads a seed set of judgments, embeds them once at startup, and answers
`knn_search` / `get_judgment` with brute-force cosine similarity. Implements the
same interface the VectorRetriever expects, so it drops in wherever the
pgvector VectorStore would go — but needs no Postgres.

This is what lets you run real searches offline: seed once, then every search
hits local RAM and spends ZERO Indian Kanoon credits.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from .embeddings import embed

logger = logging.getLogger("nyaya.memory_store")


class InMemoryCorpus:
    def __init__(self):
        self._judgments: Dict[str, Dict[str, Any]] = {}
        self._chunks: List[Dict[str, Any]] = []  # {judgment_id, text, embedding}

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
        await corpus._load(records)
        logger.info("Loaded %d seed judgments into memory corpus.", len(records))
        return corpus

    async def _load(self, records: List[Dict[str, Any]]):
        texts: List[str] = []
        for rec in records:
            jid = rec["id"]
            self._judgments[jid] = rec
            # One chunk per seed doc (they're short); embed the searchable text.
            text = f"{rec.get('title','')}. {rec.get('text','')}"
            texts.append(text)
        vectors = await embed(texts) if texts else []
        for rec, vec in zip(records, vectors):
            self._chunks.append({
                "judgment_id": rec["id"],
                "text": rec.get("text", ""),
                "embedding": vec,
            })

    async def knn_search(
        self,
        embedding: List[float],
        limit: int,
        court_level: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        scored = []
        for ch in self._chunks:
            j = self._judgments[ch["judgment_id"]]
            if court_level and j.get("court_level") not in (court_level, None):
                continue
            sim = _cosine(embedding, ch["embedding"])
            scored.append((sim, ch, j))
        scored.sort(key=lambda x: x[0], reverse=True)
        rows: List[Dict[str, Any]] = []
        for sim, ch, j in scored[:limit]:
            rows.append({
                "judgment_id": j["id"],
                "title": j.get("title", ""),
                "url": j.get("url"),
                "citation": j.get("citation"),
                "court": j.get("court"),
                "court_level": j.get("court_level"),
                "date": j.get("date"),
                "chunk_text": ch["text"],
                "distance": 1.0 - sim,
            })
        return rows

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


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
