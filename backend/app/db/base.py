"""Async engine/session factory and a pgvector-backed VectorStore.

`VectorStore` implements the two methods the VectorRetriever calls
(`knn_search`, `get_judgment`). Instantiate it at startup and pass to
`SearchPipeline(db=VectorStore(...))` to enable semantic retrieval over the
internal corpus.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..config import settings

_engine = None
_sessionmaker = None


def _init():
    global _engine, _sessionmaker
    if _engine is None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


class VectorStore:
    """Thin data-access layer for semantic retrieval."""

    def __init__(self):
        self._sm = _init()

    async def knn_search(
        self,
        embedding: List[float],
        limit: int,
        court_level: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        from sqlalchemy import text

        # HNSW cosine distance (<=>). Join back to the judgment for metadata.
        sql = text(
            """
            SELECT j.id AS judgment_id, j.title, j.url, j.citation, j.court,
                   j.court_level, j.date::text AS date, c.text AS chunk_text,
                   (c.embedding <=> :qvec) AS distance
            FROM judgment_chunks c
            JOIN judgments j ON j.id = c.judgment_id
            WHERE (:court_level IS NULL OR j.court_level = :court_level)
            ORDER BY c.embedding <=> :qvec
            LIMIT :limit
            """
        )
        async with self._sm() as session:
            res = await session.execute(
                sql, {"qvec": str(embedding), "court_level": court_level, "limit": limit}
            )
            return [dict(row._mapping) for row in res]

    async def get_judgment(self, judgment_id: str) -> Optional[Dict[str, Any]]:
        from sqlalchemy import text

        sql = text("SELECT * FROM judgments WHERE id = :id")
        async with self._sm() as session:
            res = await session.execute(sql, {"id": judgment_id})
            row = res.first()
            return dict(row._mapping) if row else None
