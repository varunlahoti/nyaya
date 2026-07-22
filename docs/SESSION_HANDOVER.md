# Session Handover — rolling detailed log

Newest session on top. This is the "what actually happened + how to continue" doc.
Broad project context lives in `HANDOVER.md`; cross-session facts in the agent
memory. This file is the granular ground truth for the retrieval/infra work.

---

# Session 2026-07-22 → retrieval-quality bug fixes (relevance)

**Symptom (reported from the live demo):** query "can a person be accused of
dowry and domestic violence?" → **0 judgments** on first run, then on rerun **8
judgments all scored 0** with "this case does not address dowry/DV" notes
(Supriyo, Shayara Bano, Puttaswamy — famous unrelated SC landmarks).

**Root cause:** the pipeline sent the parser's **verbose 40-word essay issues** as
the retrieval query text. IK/BM25 are lexical — on an essay they return famous
generic landmarks; on short keywords ("section 498A dowry cruelty") they return
the right cases (verified both ways). Also: `MAX_QUERIES_PER_SEARCH=3` dropped the
good keyword/statute queries; BM25 `websearch_to_tsquery` ANDs all terms → 0 hits
on multi-term queries; the reranker showed **every** LLM result including score-0
ones; and returning `[]` (LLM judged nothing relevant) vs all-scored-0 caused the
flaky 0-vs-8.

**Fixes (all verified end-to-end):**
- `query_builder.py`: **lead with short keyword queries** (from `parsed.keywords`),
  **condense** verbose issues to salient terms (`_condense`) so retrievers get
  keywords not essays.
- `reranker.py`: **drop results below `RERANK_MIN_SCORE`** (config, default 25);
  sort by score, re-rank. No more score-0 noise.
- `pipeline.py`: when candidates exist but none clear the bar → return a **helpful
  notice** ("none squarely on-point, add specifics") instead of a bare 0 / garbage.
- `db/base.py`: BM25 `keyword_search` uses an **OR tsquery** (`a | b | c`) via
  `_or_tsquery` so multi-term queries recall (ts_rank still ranks precise matches
  first).
- `.env`: `MAX_QUERIES_PER_SEARCH` 3 → 6.

**After:** dowry query → top hit "IN RE: ENFORCEMENT AND IMPLEMENTATION OF DOWRY"
(SC, score 90) + real DV/matrimonial HC cases; anticipatory-bail query → Sushila
Aggarwal (landmark, 95); off-domain query → the no-match notice. Tests pass (4/4).

**Round 2 (same issue, deeper causes):** even after round 1, "domestic violence and
dowry" still surfaced Shayara Bano/Puttaswamy (famous, off-topic). Found two more
root causes: (a) **fusion cite-boost + SC court-weight over-favoured famous
high-cite cases**, burying on-point low-cite HC/§498A cases → gentled the weights
(`COURT_WEIGHTS` SC 1.15→1.05, `cite_boost` max 0.20→0.06 in `pipeline.py`).
(b) **The vector HC library (3.5k random KanoonGPT sample) has no good DV cases**,
but `knn` returns its top-K regardless of how weak, flooding the pool with random
writ petitions (BHARAT SALT vs STATE, sim ~0.15) and burying IK → added a
**similarity floor** `MIN_VECTOR_SIMILARITY=0.30` (`vector.py`, config). Also
recalibrated the reranker prompt (score by legal-AREA/statute match, not exact
sub-question; famous-off-subject → <20) + fed it the parsed statutes.
**Verified:** dowry → "IN RE ENFORCEMENT OF DOWRY" + "Delhi Domestic Working
Women's Forum" (no landmarks); anticipatory bail → Gurbaksh Singh Sibbia (90),
Sushila Aggarwal (85). **Lesson: the random HC sample hurts more than helps — a
curated corpus matters (see open items).**

**Still known (not blocking):** deep mode slow (~56s); HC library is a random
snippet-level sample (low value — curate it). Deployed via PR.

---

# Session 2026-07-21 → hosted hybrid retrieval (Neon pgvector + multi-source)

## Goal of the session
Reduce sole reliance on Indian Kanoon (IK). IK was the *only live* source and our
own corpus had only ever been ingested from IK, so IK effectively ranked every
result. Build a **hosted hybrid**: live IK **+** our own embedded judgment library,
fused, so the best case surfaces regardless of IK's ranking.

## END STATE (what is live right now)
- **Hosted library on Neon** (free Postgres+pgvector, region AWS **Singapore**,
  db `neondb`): **31,503 judgments** =
  - `sci_index` = **28,003** Supreme Court (1950→~2014 tail cut off), official
    **digiscr.sci.gov.in** PDF links + neutral/SCR citations. Title+citation only
    (NO body text).
  - `kanoon` = **3,500** High Court, snippet text (~423 chars), S3 links.
- **Embeddings:** Voyage **`voyage-law-2`** (1024-dim), real (not the `hash` dev
  fallback). Payment method added → Tier-1 rate limits; still $0 under the 50M
  free-token allowance (used ~5M).
- **Retrieval:** `SearchPipeline` fuses IK (live) + `vector` + `bm25` (both over
  Neon) via RRF. Verified end-to-end: good, cited, multi-source results.
- **Code merged to `main`** via PR #1 (squash commit `d5f9f0d`). Streamlit Cloud
  set to auto-rebuild.
- **Local config** in `backend/.env`: `VECTOR_BACKEND=postgres`,
  `EMBEDDINGS_PROVIDER=voyage`, `ENABLED_RETRIEVERS=["indian_kanoon","vector","bm25"]`,
  `MAX_QUERIES_PER_SEARCH=3`, plus `DATABASE_URL` + `VOYAGE_API_KEY` (line 30–31).

## DONE this session
1. **Ran benchmark** (`scripts/benchmark.py`) — offline recall@k/MRR over the
   in-memory corpus. hybrid-rrf ties bm25 at top; both > vector on hash embeddings.
2. **Fixed IK single-page bug** — `retrievers/indian_kanoon.py` only fetched
   `pagenum=0` (~10 hits) then ranked those; now paginates to `IK_MAX_PAGES`
   (config, default 3) → reranker sees the full ~30 pool. Also corrected stale
   eSCR/DigiSCR refs → the merged **SCR portal** (see gotchas).
3. **Generic bulk-ingest infra** — `app/services/bulk_ingest.py` +
   `scripts/bulk_ingest.py`: loads jsonl/json/csv/**parquet**/**pdf-dir**, plus
   `--hf-repo/--hf-file` (HuggingFace). Column-mapping to a canonical schema,
   richer-copy dedupe, idempotent. `requirements-ingest.txt` (pandas/pyarrow/
   pypdf/huggingface_hub — lazy-imported).
4. **Neon pgvector path** — `app/db/base.py`: fixed asyncpg URL driver + SSL
   (strip `?sslmode/channel_binding`, pass `ssl` via connect_args), fixed
   `AmbiguousParameterError` (cast `:court_level`), added **batched `bulk_insert`**
   (executemany, one txn per batch — remote loads in seconds not per-row).
5. **Embeddings resilience** — `app/services/embeddings.py`: retry/backoff
   honouring `Retry-After` for 429/5xx (free-tier rate limits).
6. **Loaded the corpus into Neon** — `scripts/load_corpus_to_neon.py` (resumable):
   3,640 KanoonGPT rows (HC-heavy). Then pruned the 140 KanoonGPT SC dups (they
   had clunky S3 links; sci_index covers SC with clean digiscr links).
7. **Loaded the SC index** — `scripts/load_sc_index.py`: HF
   `debkanchan/supreme-court-of-india-judgements` (~37k). Got to 28,003 then hit
   Neon's 512 MB cap (`DiskFullError`).
8. **Wired Streamlit to Neon** — `streamlit_app.py` bridges DATABASE_URL /
   VOYAGE_API_KEY / EMBEDDINGS_PROVIDER / VECTOR_BACKEND / ENABLED_RETRIEVERS from
   secrets; `requirements.txt` adds SQLAlchemy + asyncpg.
9. **Docs** — `docs/RETRIEVAL.md`, `docs/DATA_SOURCES.md` (bulk-ingest strategy,
   SCR portal), `HANDOVER.md` §11 open items.
10. **Merged to main (PR #1)**, memory updated.

## OPEN ITEMS (prioritised)
1. **Load the remaining ~9k SC** — Neon free (0.5 GB) is FULL. 1024-dim vectors +
   HNSW index are the space hog (not text). Choose one:
   - **Re-embed at 256/512-dim** (voyage-3-lite / Matryoshka) → all 37k fits free.
     Requires: set `EMBEDDINGS_MODEL`/`EMBEDDINGS_DIM`, recreate the `vector(dim)`
     column, re-run loaders. Cheapest full-coverage path.
   - **Neon paid** (~$19/mo) — trivial, no code.
   - **Oracle/VPS** (200 GB) — the original plan; enables full-text later.
2. **Full-text SC** — sci_index is **title+citation only** → strong for
   name/citation lookup, weak for fact-pattern. To make SC fact-searchable: fetch
   the digiscr PDFs (url is on every row) → `bulk_ingest --format pdf-dir` or
   pipeline deep-fetch. Needs >0.5 GB storage.
3. **Verify the Streamlit Cloud deploy** — the rebuild needs Python **3.12/3.13**
   (asyncpg wheels) + the 5 secrets. If Python is wrong the build FAILS and takes
   down the (previously IK-only) demo. Confirm the app came back up hybrid.
4. **HC coverage is thin** — only the 3,640-row KanoonGPT *sample* (snippet). Real
   HC = pull the KanoonGPT structured year-files (11 GB total) filtered to court,
   or another source.
5. **`load_corpus_to_neon.py` re-adds the 140 SC dups** on a from-scratch rebuild
   (they're still in `data/corpus.jsonl`). Filter SC out of that path if rebuilding.

## KEY DECISIONS + WHY
- **Neon over Oracle** — Oracle Cloud free signup repeatedly failed ("unable to
  complete sign up" — VPN/WARP + fraud wall). Neon: no card, Google login, works.
  Oracle stays the plan for full-text/200 GB later.
- **Snippet-level, not full text** — the available datasets carry short text;
  full text is a storage-heavy later upgrade. Pipeline already deep-fetches full
  text for top hits from IK.
- **Accepted 28k SC** (of 37k) — Neon cap; good enough for a pilot.
- **RRF fusion** — robust across IK-rank vs cosine vs BM25 scales; no source
  dominates; already in `pipeline.py`.

## GOTCHAS / TRAPS (read before continuing)
- **Neon free = 512 MB hard cap.** At the cap, *writes fail* (`DiskFullError`);
  reads/search still work. Current DB is at the cap — free up space or upgrade
  before loading more.
- **asyncpg on Streamlit Cloud needs Python 3.12/3.13** (wheels). Default newer
  Python may fail the build.
- **Local `.venv` is Python 3.9** (anaconda) — modern Streamlit (≥1.40) will NOT
  install here (max 1.12), so you **cannot run the Streamlit UI locally**. Test
  the code path directly: `SearchPipeline(db=VectorStore()).run(SearchRequest(...))`.
- **Voyage free tier w/o a card ≈ 3 RPM / 10K TPM** → floods 429s. A payment
  method (added) unlocks Tier-1; still free under 50M tokens.
- **Background python buffers stdout** — use `python -u` or the run finishes before
  you see prints.
- **IK token** in `.env` was rotated this session (`ceb1…`); the old one 401'd.
- **`data/corpus.jsonl` is git-ignored** (regenerable via `bulk_ingest`).
- `.venv` gained this session: pytest, pytest-asyncio, asyncpg, sqlalchemy, pypdf.

## HOW TO CONTINUE (commands, run from `backend/`, use `.venv/bin/python`)
```bash
# Neon contents
.venv/bin/python -c "import asyncio;from app.db.base import VectorStore;from sqlalchemy import text
async def c():
 s=VectorStore()
 async with s._sm() as x: print({r[0]:r[1] for r in await x.execute(text('SELECT source,count(*) FROM judgments GROUP BY source'))})
asyncio.run(c())"

# Run a search exactly as Streamlit does (needs .env: VECTOR_BACKEND=postgres etc.)
.venv/bin/python -u -c "import asyncio;from app.db.base import VectorStore
from app.services.pipeline import SearchPipeline;from app.schemas import SearchRequest
async def m():
 r=await SearchPipeline(db=VectorStore()).run(SearchRequest(facts='<facts>',max_results=6))
 print(r.sources_used); [print(x.source,x.title[:40],x.citation,x.url[:50]) for x in r.results]
asyncio.run(m())"

# Load more into Neon (resumable). Free space first if at the 0.5GB cap.
.venv/bin/python -m scripts.load_sc_index          # SC index (debkanchan)
.venv/bin/python -m scripts.bulk_ingest --hf-repo <repo> --hf-file <f> --source <tag> --sink postgres
```

## FILES CHANGED (merged in d5f9f0d)
- New: `app/services/bulk_ingest.py`, `app/services/chunking.py`,
  `app/services/ingest.py`, `app/services/lexical.py`,
  `app/services/retrievers/bm25.py`, `scripts/bulk_ingest.py`,
  `scripts/benchmark.py`, `scripts/load_corpus_to_neon.py`,
  `scripts/load_sc_index.py`, `eval/queries.jsonl`, `requirements-ingest.txt`,
  `docs/RETRIEVAL.md`.
- Modified: `app/config.py` (IK_MAX_PAGES), `app/db/base.py`,
  `app/services/embeddings.py`, `app/services/retrievers/indian_kanoon.py`,
  `app/services/retrievers/supreme_court.py`, `app/services/pipeline.py`,
  `app/services/memory_store.py`, `app/schemas.py`, `streamlit_app.py`,
  `requirements.txt`, `docs/DATA_SOURCES.md`, `docs/HANDOVER.md`.

## EXTERNAL RESOURCES
- Neon console: neon.tech (project `nyaya`/`neondb`, AWS Singapore, free tier FULL).
- Voyage: voyageai.com (voyage-law-2, payment method added, 50M free tokens).
- Data: HF `KanoonGPT/indian-case-laws` (HC snippets), HF
  `debkanchan/supreme-court-of-india-judgements` (~37k SC index).
- SC official source: **scr.sci.gov.in/scrsearch** (digiscr merged into it
  2025-05-08; no public API; PDFs are the ingest path).
- Repo: github.com/varunlahoti/nyaya (Streamlit Cloud deploys from `main`).
