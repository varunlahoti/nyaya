"""Async engine/session factory and a pgvector-backed VectorStore.

`VectorStore` implements the two methods the VectorRetriever calls
(`knn_search`, `get_judgment`). Instantiate it at startup and pass to
`SearchPipeline(db=VectorStore(...))` to enable semantic retrieval over the
internal corpus.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..config import settings

_engine = None
_sessionmaker = None


# Generic tokens that carry no legal signal but flood keyword search — they
# appear in thousands of case titles / party names (e.g. "M/s X Pvt Ltd vs Union
# of India"). Matching on these returns party-name coincidences, not on-point law,
# so they are dropped from the tsquery. Distinctive terms (statute names, section
# numbers, offences, "freelancer", "moonlighting") are kept.
_TSQUERY_STOP = {
    "the", "and", "for", "with", "under", "while", "can", "you", "your", "who",
    "what", "how", "why", "are", "was", "will", "our", "any", "all", "not", "but",
    "company", "companies", "limited", "ltd", "pvt", "private", "corporation",
    "corp", "union", "india", "indian", "state", "states", "ors", "anr", "another",
    "others", "versus", "through", "thru", "rep", "represented", "mrs", "smt",
    "sri", "shri", "person", "matter", "case", "cases", "act", "acts", "section",
    "sections", "working", "work", "employee", "employees", "employer", "same",
    "time", "full", "part", "whether", "government", "authority", "board", "ltd.",
}


def _or_tsquery(query: str, max_terms: int = 20) -> str:
    """Sanitise free text into an OR tsquery of DISTINCTIVE terms: 'a | b | c'.

    Keeps alphanumeric tokens (incl. section numbers like 498a), drops 1-2 char
    noise and generic legal/party-name stopwords, de-dupes. Sanitised so it is
    safe to pass to to_tsquery().
    """
    seen, terms = set(), []
    for tok in re.split(r"[^0-9A-Za-z]+", query.lower()):
        if len(tok) > 2 and tok not in seen and tok not in _TSQUERY_STOP:
            seen.add(tok)
            terms.append(tok)
        if len(terms) >= max_terms:
            break
    return " | ".join(terms)


def _init():
    global _engine, _sessionmaker
    if _engine is None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from .session import _normalise_url

        raw = settings.DATABASE_URL or ""
        url = _normalise_url(raw)
        # asyncpg's SQLAlchemy dialect rejects libpq query params (sslmode,
        # channel_binding) in the URL — strip them and pass SSL via connect_args.
        connect_args = {}
        if "?" in url:
            url = url.split("?", 1)[0]
        if "sslmode=" in raw and "sslmode=disable" not in raw:
            connect_args["ssl"] = True
        _engine = create_async_engine(url, pool_pre_ping=True, connect_args=connect_args)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


class VectorStore:
    """Thin data-access layer for semantic retrieval."""

    def __init__(self):
        self._sm = _init()

    async def ensure_corpus_schema(self) -> None:
        """Create the pgvector extension, corpus tables, and indexes (idempotent)."""
        from sqlalchemy import text

        dim = settings.EMBEDDINGS_DIM
        stmts = [
            "CREATE EXTENSION IF NOT EXISTS vector",
            """
            CREATE TABLE IF NOT EXISTS judgments (
                id text PRIMARY KEY,
                source text,
                title text,
                citation text,
                court text,
                court_level text,
                date date,
                url text,
                cites integer DEFAULT 0,
                full_text text
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS judgment_chunks (
                id bigserial PRIMARY KEY,
                judgment_id text REFERENCES judgments(id) ON DELETE CASCADE,
                text text,
                tsv tsvector,
                embedding vector({dim})
            )
            """,
            # HNSW for fast cosine KNN; GIN for BM25-style full-text ranking.
            "CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON judgment_chunks "
            "USING hnsw (embedding vector_cosine_ops)",
            "CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON judgment_chunks USING gin (tsv)",
        ]
        async with self._sm() as session:
            for s in stmts:
                await session.execute(text(s))
            await session.commit()

    async def upsert_judgment(self, rec: Dict[str, Any], chunks) -> None:
        """Upsert one judgment and replace its chunks. `chunks` = [(text, embedding)]."""
        from sqlalchemy import text

        async with self._sm() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO judgments (id, source, title, citation, court,
                        court_level, date, url, cites, full_text)
                    VALUES (:id, :source, :title, :citation, :court, :court_level,
                        NULLIF(:date,'')::date, :url, :cites, :full_text)
                    ON CONFLICT (id) DO UPDATE SET
                        title=EXCLUDED.title, citation=EXCLUDED.citation,
                        court=EXCLUDED.court, court_level=EXCLUDED.court_level,
                        date=EXCLUDED.date, url=EXCLUDED.url, cites=EXCLUDED.cites,
                        full_text=EXCLUDED.full_text
                    """
                ),
                {
                    "id": rec["id"], "source": rec.get("source"),
                    "title": rec.get("title"), "citation": rec.get("citation"),
                    "court": rec.get("court"), "court_level": rec.get("court_level"),
                    "date": rec.get("date") or "", "url": rec.get("url"),
                    "cites": int(rec.get("cites") or 0), "full_text": rec.get("text", ""),
                },
            )
            await session.execute(
                text("DELETE FROM judgment_chunks WHERE judgment_id = :jid"),
                {"jid": rec["id"]},
            )
            for ctext, emb in chunks:
                await session.execute(
                    text(
                        "INSERT INTO judgment_chunks (judgment_id, text, tsv, embedding) "
                        "VALUES (:jid, :t, to_tsvector('english', :t), (:emb)::vector)"
                    ),
                    {"jid": rec["id"], "t": ctext, "emb": str(emb)},
                )
            await session.commit()

    async def bulk_insert(self, items) -> int:
        """Fast batched insert for a fresh load. `items` = [(rec, [(text, emb)])].

        One transaction for the whole batch via executemany (list of param dicts),
        so 10k+ judgments load in seconds instead of a round-trip each. Judgments
        conflict-skip (idempotent); chunks assume the judgment is new (caller
        filters already-stored ids), so no per-row delete.
        """
        from sqlalchemy import text

        jparams = [{
            "id": r["id"], "source": r.get("source"), "title": r.get("title"),
            "citation": r.get("citation"), "court": r.get("court"),
            "court_level": r.get("court_level"), "date": r.get("date") or "",
            "url": r.get("url"), "cites": int(r.get("cites") or 0),
            "full_text": r.get("text", ""),
        } for r, _ in items]
        cparams = [{"jid": r["id"], "t": ct, "emb": str(emb)}
                   for r, chunks in items for ct, emb in chunks]

        async with self._sm() as session:
            await session.execute(text(
                """
                INSERT INTO judgments (id, source, title, citation, court,
                    court_level, date, url, cites, full_text)
                VALUES (:id, :source, :title, :citation, :court, :court_level,
                    NULLIF(:date,'')::date, :url, :cites, :full_text)
                ON CONFLICT (id) DO NOTHING
                """), jparams)
            if cparams:
                await session.execute(text(
                    "INSERT INTO judgment_chunks (judgment_id, text, tsv, embedding) "
                    "VALUES (:jid, :t, to_tsvector('english', :t), (:emb)::vector)"
                ), cparams)
            await session.commit()
        return len(jparams)

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
            SELECT DISTINCT ON (j.id)
                   j.id AS judgment_id, j.title, j.url, j.citation, j.court,
                   j.court_level, j.date::text AS date, j.cites, c.text AS chunk_text,
                   (c.embedding <=> (:qvec)::vector) AS distance
            FROM judgment_chunks c
            JOIN judgments j ON j.id = c.judgment_id
            WHERE (CAST(:court_level AS text) IS NULL OR j.court_level = :court_level)
            ORDER BY j.id, c.embedding <=> (:qvec)::vector
            LIMIT :limit
            """
        )
        async with self._sm() as session:
            res = await session.execute(
                sql, {"qvec": str(embedding), "court_level": court_level, "limit": limit}
            )
            rows = [dict(row._mapping) for row in res]
        rows.sort(key=lambda r: r["distance"])
        return rows[:limit]

    async def keyword_search(
        self,
        query: str,
        limit: int,
        court_level: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Postgres full-text ranking — the pgvector backend's BM25 equivalent.

        Uses an OR tsquery (`term1 | term2 | ...`) rather than websearch's implicit
        AND: a multi-term query like "section 498A dowry cruelty" should still
        match a case containing most of those terms. `ts_rank` naturally ranks
        docs matching more/rarer terms higher, so recall goes up without wrecking
        precision.
        """
        from sqlalchemy import text

        tsq = _or_tsquery(query)
        if not tsq:
            return []
        sql = text(
            """
            SELECT DISTINCT ON (j.id)
                   j.id AS judgment_id, j.title, j.url, j.citation, j.court,
                   j.court_level, j.date::text AS date, j.cites, c.text AS chunk_text,
                   ts_rank(c.tsv, to_tsquery('english', :tsq)) AS score
            FROM judgment_chunks c
            JOIN judgments j ON j.id = c.judgment_id
            WHERE c.tsv @@ to_tsquery('english', :tsq)
              AND (CAST(:court_level AS text) IS NULL OR j.court_level = :court_level)
            ORDER BY j.id, score DESC
            LIMIT :limit
            """
        )
        async with self._sm() as session:
            res = await session.execute(
                sql, {"tsq": tsq, "court_level": court_level, "limit": limit * 4}
            )
            rows = [dict(row._mapping) for row in res]
        rows.sort(key=lambda r: r["score"], reverse=True)
        return rows[:limit]

    async def get_judgment(self, judgment_id: str) -> Optional[Dict[str, Any]]:
        from sqlalchemy import text

        sql = text("SELECT * FROM judgments WHERE id = :id")
        async with self._sm() as session:
            res = await session.execute(sql, {"id": judgment_id})
            row = res.first()
            return dict(row._mapping) if row else None
