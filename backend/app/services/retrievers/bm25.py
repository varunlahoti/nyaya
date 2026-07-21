"""BM25 lexical retriever — keyword search over our own ingested corpus.

The lexical counterpart to the VectorRetriever. Both read the same corpus
backend (in-memory or pgvector); this one ranks by BM25 term overlap, the other
by embedding similarity. The pipeline fuses their ranked lists with RRF.

Lexical retrieval is what catches the exact tokens embeddings blur over —
section numbers, statute names, neutral citations — so a search for "Section
498A cruelty" reliably surfaces 498A cases even if the phrasing differs.

Disabled when no corpus backend is injected (the orchestrator skips it).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ...schemas import Candidate, JudgmentDoc, RetrievalQuery

logger = logging.getLogger("nyaya.retriever.bm25")


class BM25Retriever:
    name = "bm25"

    def __init__(self, db=None):
        self._db = db

    def enabled(self) -> bool:
        # Needs a corpus backend that exposes keyword_search.
        return self._db is not None and hasattr(self._db, "keyword_search")

    async def search(self, query: RetrievalQuery) -> List[Candidate]:
        if not self.enabled():
            return []
        try:
            rows = await self._db.keyword_search(  # type: ignore[union-attr]
                query=query.boolean or query.text,
                limit=query.limit,
                court_level=None if query.court_level == "any" else query.court_level,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("BM25 search failed (%s): %s", query.tag, exc)
            return []

        candidates: List[Candidate] = []
        for r in rows:
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
                raw_score=float(r.get("score", 0.0)),
                cites=int(r.get("cites") or 0),
            ))
        return candidates

    async def fetch_document(self, doc_id: str) -> Optional[JudgmentDoc]:
        if not self.enabled() or not hasattr(self._db, "get_judgment"):
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
