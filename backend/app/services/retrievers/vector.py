"""Vector retriever — semantic search over our own ingested judgment corpus.

Uses pgvector nearest-neighbour search over `judgment_chunks.embedding`. When no
database is configured it reports itself disabled (the orchestrator skips it).

This is what makes fact-pattern matching work where keyword search fails: two
tenancy disputes with different vocabulary still land near each other in
embedding space.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ...config import settings
from ...schemas import Candidate, JudgmentDoc, RetrievalQuery
from ..embeddings import embed_one

logger = logging.getLogger("nyaya.retriever.vector")


class VectorRetriever:
    name = "vector"

    def __init__(self, db=None):
        # `db` is an optional async session factory injected at startup.
        self._db = db

    def enabled(self) -> bool:
        # Enabled whenever a corpus backend is injected (in-memory or pgvector).
        return self._db is not None

    async def search(self, query: RetrievalQuery) -> List[Candidate]:
        if not self.enabled():
            return []
        try:
            qvec = await embed_one(query.text)
            rows = await self._db.knn_search(  # type: ignore[union-attr]
                embedding=qvec,
                limit=query.limit,
                court_level=None if query.court_level == "any" else query.court_level,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vector search failed (%s): %s", query.tag, exc)
            return []

        candidates: List[Candidate] = []
        for r in rows:
            similarity = float(1.0 - r.get("distance", 1.0))
            # Skip weak matches: knn always returns top-K, so a query the corpus
            # can't answer would otherwise contribute near-random cases that drown
            # out the live-IK hits. Below the floor = not a real semantic match.
            if similarity < settings.MIN_VECTOR_SIMILARITY:
                continue
            candidates.append(Candidate(
                source=self.name,
                source_doc_id=str(r["judgment_id"]),
                title=r.get("title", ""),
                url=r.get("url"),
                citation=r.get("citation"),
                court=r.get("court"),
                court_level=r.get("court_level"),
                date=r.get("date"),
                snippet=r.get("chunk_text", "")[:400],
                raw_score=similarity,
            ))
        return candidates

    async def fetch_document(self, doc_id: str) -> Optional[JudgmentDoc]:
        if not self.enabled():
            return None
        try:
            j = await self._db.get_judgment(doc_id)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            return None
        if not j:
            return None
        return JudgmentDoc(
            source=self.name,
            source_doc_id=doc_id,
            title=j.get("title", ""),
            url=j.get("url"),
            citation=j.get("citation"),
            court=j.get("court"),
            date=j.get("date"),
            text=j.get("full_text", ""),
        )
