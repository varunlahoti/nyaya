-- Nyaya database bootstrap: pgvector extension + minimal corpus schema.
-- The relational app tables (users, searches, …) are created by SQLAlchemy /
-- Alembic when you wire persistence. This file ensures the vector-search path
-- has its extension and tables so semantic retrieval doesn't error on an empty
-- corpus (it simply returns no rows until you ingest judgments).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS judgments (
    id            TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    source_doc_id TEXT NOT NULL,
    citation      TEXT,
    title         TEXT NOT NULL,
    court         TEXT,
    court_level   TEXT,
    bench         TEXT,
    date          DATE,
    url           TEXT,
    full_text     TEXT DEFAULT '',
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_judgments_source ON judgments (source, source_doc_id);

CREATE TABLE IF NOT EXISTS judgment_chunks (
    id           BIGSERIAL PRIMARY KEY,
    judgment_id  TEXT REFERENCES judgments(id) ON DELETE CASCADE,
    chunk_index  INT NOT NULL,
    text         TEXT NOT NULL,
    embedding    vector(1024)
);

-- HNSW index for fast approximate nearest-neighbour cosine search.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON judgment_chunks USING hnsw (embedding vector_cosine_ops);
