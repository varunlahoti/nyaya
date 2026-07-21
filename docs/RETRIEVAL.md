# Retrieval — Hybrid engine (the #1 quality lever)

Nyaya's biggest quality gap was relying on Indian Kanoon's keyword search + its
ranking, then reranking on short snippets. This document describes the hybrid
retrieval engine that fixes that: our own **semantic + lexical** index, fused
with **Reciprocal Rank Fusion (RRF)**, on top of IK-live.

---

## 1. The pipeline (facts → judgments)

```
facts
  │  parse (LLM)                     legal issues, statutes, keywords
  │  build queries                   per-issue / per-statute / fact-pattern (+SC)
  ▼
fan-out to ALL enabled retrievers, ALL queries, concurrently
  ├── indian_kanoon   live keyword search over IK's full corpus (millions)
  ├── vector          semantic KNN over OUR corpus (embeddings)
  └── bm25            lexical BM25 over OUR corpus (exact tokens)
  ▼
RRF fusion            fuse the ranked lists → court-authority + citation boosts
  ▼
candidate cap (25)  → deep full-text fetch (opt-in) → LLM rerank (closed set)
  ▼
5–10 judgments with relevance note + holding
```

Enable/disable sources with `ENABLED_RETRIEVERS`. Default is all three
(`indian_kanoon, vector, bm25`). Drop `indian_kanoon` for a fully self-hosted,
zero-credit deployment once the corpus is large enough.

## 2. Why hybrid (and not vector-only)

- **Vector (semantic)** matches *meaning* — two tenancy disputes with different
  words still land near each other. Catches what keyword search misses.
- **BM25 (lexical)** matches *exact tokens* embeddings blur over — a section
  number (`498A`), a statute name, a neutral citation. Catches what vectors miss.
- **IK-live** keeps the recall breadth of millions of judgments so a case we
  haven't ingested yet can still surface.
- **RRF** fuses their ranked lists by *rank*, not raw score, so it's robust when
  the three retrievers score on totally different scales — and it rewards a
  judgment that shows up across several lists (corroboration).

Vector-only over a small corpus would *lose* to today (coverage collapse). Hybrid
+ IK-live retained is strictly safer and better.

## 3. RRF, concretely

For each ranked list *L* and rank *r* (0-based), a candidate gets
`weight_source / (RRF_K + r)`, summed across every list it appears in, then
multiplied by court-authority (SC > HC > trial), a gentle citation-count boost,
and a small cross-source agreement boost. `RRF_K=60` (standard). Switch to the
old score-normalisation blend with `FUSION_METHOD=weighted` for A/B.

## 4. Chunking

Judgments are long and structured. `app/services/chunking.py` splits on
paragraph/numbered-para boundaries (never mid-sentence), packs into
`CHUNK_TARGET_CHARS` (~1200) windows with `CHUNK_OVERLAP_CHARS` (~150) overlap so
a holding straddling a boundary still appears whole in one chunk, and hard-wraps
any runaway block. Deterministic, dependency-free.

## 5. Building the corpus (ingestion)

```bash
cd backend
# Into the local JSONL corpus (no DB — feeds the in-memory backend):
python -m scripts.ingest --queries-file data/ingest_queries.txt --per-query 30

# Into pgvector (production):
DATABASE_URL=postgresql+asyncpg://... EMBEDDINGS_PROVIDER=voyage VOYAGE_API_KEY=... \
  python -m scripts.ingest --queries-file data/ingest_queries.txt --sink postgres
```

`scripts/ingest.py` → `app/services/ingest.py`: discover doc ids (IK search over
the curated `data/ingest_queries.txt`, or `--doc-ids`), fetch full text (cached,
concurrency-limited), chunk, embed, store. Idempotent (upsert by id), resumable
(JSONL de-duped on load). **Only ingest content you are licensed to store** —
follow IK's retention terms (see `DATA_SOURCES.md`).

- **In-memory backend** (`VECTOR_BACKEND=memory`): seed landmarks +
  `data/corpus.jsonl` load into RAM at startup as one hybrid (vector + BM25)
  index. Zero DB, zero IK credits per search.
- **Postgres backend** (`VECTOR_BACKEND=postgres`): pgvector HNSW for KNN + a GIN
  `tsvector` index for BM25-equivalent full-text ranking. `scripts/seed.py`
  loads the landmark seed; `--sink postgres` loads ingested judgments.

## 6. Benchmark (prove it works + de-risk embeddings)

`eval/queries.jsonl` holds labeled `facts → expected judgment id` queries.
`scripts/benchmark.py` runs each retrieval mode over the corpus and reports
recall@k + MRR — isolating *retrieval* quality from the LLM rerank, so it runs
offline with no keys.

```bash
python -m scripts.benchmark --k 10                 # hash embeddings (dev floor)
python -m scripts.benchmark --embeddings voyage    # real semantic quality
```

Reference run (14 landmark queries, **hash** dev embeddings — a floor, not the
ceiling):

| mode          | recall@1 | recall@5 | recall@10 | MRR   |
|---------------|---------:|---------:|----------:|------:|
| bm25          | 0.93     | 1.00     | 1.00      | 0.964 |
| vector        | 0.71     | 1.00     | 1.00      | 0.845 |
| hybrid-weight | 0.71     | 1.00     | 1.00      | 0.845 |
| hybrid-rrf    | 0.93     | 1.00     | 1.00      | 0.964 |

Read: with a deliberately weak vector (hash), **RRF stays at the best retriever's
level (0.93/0.964)** while the weighted blend is dragged down to the weak one.
That is RRF's robustness. **The real test is `--embeddings voyage`** on a larger
ingested corpus — there the vector + hybrid rows should exceed BM25. That run is
the embedding-quality de-risk: if `voyage-law-2` underperforms on Indian legal
text, try `--embeddings openai` before scaling ingestion.

## 7. Config knobs (all env-driven, see `app/config.py`)

| Setting | Default | Purpose |
|---|---|---|
| `ENABLED_RETRIEVERS` | `indian_kanoon,vector,bm25` | which sources fan out |
| `FUSION_METHOD` | `rrf` | `rrf` or `weighted` |
| `RRF_K` | `60` | RRF damping |
| `EMBEDDINGS_PROVIDER` | `hash` | `voyage` / `openai` / `hash` (dev) |
| `CHUNK_TARGET_CHARS` | `1200` | chunk size |
| `CHUNK_OVERLAP_CHARS` | `150` | chunk overlap |
| `VECTOR_BACKEND` | `memory` | `memory` / `postgres` / `none` |
| `INGEST_CONCURRENCY` | `4` | polite parallel IK fetches |
| `INGEST_MAX_DOCS` | `500` | safety cap per run |
```
