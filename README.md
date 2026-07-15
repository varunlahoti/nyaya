---
title: Nyaya Legal Research
emoji: ⚖️
colorFrom: indigo
colorTo: orange
sdk: streamlit
app_file: backend/streamlit_app.py
pinned: false
short_description: AI legal research for Indian advocates — facts in, judgments out
---

# Nyaya — AI Legal Research for Indian Advocates

> Type the facts of a case in plain English. Get 5–10 relevant, citable judgments
> from the Supreme Court, High Courts, and Indian Kanoon — each with a source link
> and a one-line reason it matters.

Nyaya ("न्याय" — justice) is a web app + installable PWA that does what a senior
advocate does when a brief lands on the desk: reads the facts, spots the legal
issues, and surfs the case law. It compresses hours of manual searching into
seconds, and every result links back to the authoritative source so the advocate
verifies before citing.

---

## What's in this repo

| Path | What it is |
|------|-----------|
| [`docs/PRODUCT_OVERVIEW.md`](docs/PRODUCT_OVERVIEW.md) | Vision, users, pricing, monetisation, roadmap |
| [`docs/SYSTEM_DESIGN.md`](docs/SYSTEM_DESIGN.md) | Architecture, retrieval pipeline, data model, scaling |
| [`docs/API_SPEC.md`](docs/API_SPEC.md) | REST API reference (OpenAPI-style) |
| [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) | Source integrations + **legal / ToS / compliance** notes |
| [`backend/`](backend/) | FastAPI service: the retrieval pipeline |
| [`frontend/`](frontend/) | Next.js 14 PWA: the advocate-facing app |
| [`docker-compose.yml`](docker-compose.yml) | Postgres + pgvector, Redis, API, web — one command up |

---

## The core idea in one diagram

```
Advocate types facts
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  1. Claude reads facts → extracts legal issues, statutes,  │
│     acts, sections, keywords, jurisdiction, court level    │
│  2. Query builder → structured queries for each source     │
│  3. Retrievers (parallel):                                 │
│        • Indian Kanoon Search API                          │
│        • Internal pgvector corpus (semantic)               │
│        • Supreme Court / High Court connectors             │
│  4. Dedupe + merge candidates                              │
│  5. Claude re-ranks top N by relevance to THESE facts,     │
│     writes a one-line "why this matters" per judgment      │
└───────────────────────────────────────────────────────────┘
        │
        ▼
5–10 judgments, each: case title • citation • court • year •
                       source link • relevance note • holding
```

---

## Quick start (local, Docker)

```bash
cp .env.example .env
# edit .env — set OPENROUTER_API_KEY and INDIAN_KANOON_API_TOKEN
docker compose up --build
```

- Web app → http://localhost:3000
- API docs (Swagger) → http://localhost:8000/docs

## Run it offline — zero API keys, zero Indian Kanoon credits

The app ships with a seed corpus of ~14 landmark Indian judgments and an
in-memory vector store. Set `VECTOR_BACKEND=memory` (the default in
`.env.example`) and searches run entirely offline:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
VECTOR_BACKEND=memory uvicorn app.main:app --reload
# then POST facts to /api/v1/search — real cases come back, 0 IK credits spent
```

Add `OPENROUTER_API_KEY` to upgrade parsing/ranking from the heuristic fallback
to real LLM issue-spotting and relevance notes — still 0 Indian Kanoon credits.
The LLM runs via OpenRouter on cheap, strong models (DeepSeek V3 reranker,
Gemini Flash parser) — a fraction of frontier cost.

### Stretching the free Indian Kanoon credits (dev)

The credit-burn per search is the ~6 live IK queries. Two ways to make the free
500 credits last through development:

1. **Seed corpus (0 credits):** `VECTOR_BACKEND=memory` → searches hit the local
   landmark corpus only. Great for building/testing the UI and pipeline.
2. **Ingest-once, search-many (spend ~100–150 credits total):** build a real
   local corpus from Indian Kanoon *once*, then search it offline forever:
   ```bash
   # spends IK credits ONCE to build the corpus
   python -m scripts.ingest --query "section 138 negotiable instruments act" --limit 40
   python -m scripts.ingest --query "eviction transfer of property act section 106" --limit 40
   # then set VECTOR_BACKEND=postgres and disable the live IK retriever for dev:
   #   ENABLED_RETRIEVERS=["vector"]
   ```
   Every subsequent dev search reads your local pgvector corpus → **0 IK
   credits**. The 500 free credits become a one-time corpus-building budget
   instead of a per-search cost.

> This is exactly the production cost strategy in miniature: the vector corpus
> is what drives per-search Indian Kanoon cost toward zero over time.

## Test harness (Streamlit) — quickest way to try it

A single-command UI that runs the real pipeline in-process (reads `backend/.env`
for your keys — no separate API/frontend needed):

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt -r requirements-streamlit.txt
streamlit run streamlit_app.py
```

Opens a browser at http://localhost:8501 — type facts, get ranked judgments.
(The production, licence-compliant UI is the Next.js app in `frontend/`.)

## Quick start (backend only, no Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env      # set keys
uvicorn app.main:app --reload
```

Then POST a search:

```bash
curl -s http://localhost:8000/api/v1/search \
  -H 'content-type: application/json' \
  -d '{"facts":"The tenant stopped paying rent for 8 months. Landlord issued notice under the Transfer of Property Act and now seeks eviction. Tenant claims the notice was defective.","jurisdiction":"any","max_results":8}' | jq
```

---

## Design principles

1. **Advocate verifies, tool assists.** Every result links to the primary source.
   The tool never invents a citation — a judgment is only returned if a real
   source document backs it. (See "Anti-hallucination" in the system design.)
2. **Explain the "why".** A list of cases is only half the job; each result says
   in one line why it's relevant to *these* facts.
3. **Respect the sources.** We honour rate limits, ToS, and licensing of every
   upstream. See [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).
4. **Fast and cheap at the margin.** Aggressive caching of source documents and
   embeddings; the expensive LLM step runs on a small candidate set.

---

## Status

This is a reference implementation / MVP scaffold. It runs end-to-end with an
Anthropic key and an Indian Kanoon API token. The Supreme Court / High Court
direct connectors ship as pluggable adapters with a working Indian Kanoon
adapter as the default retriever; see `backend/app/services/retrievers/`.

**Not legal advice.** Nyaya is a research aid for qualified legal professionals.
