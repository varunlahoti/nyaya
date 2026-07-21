# Nyaya — Session Handover (crystal-clear context for the next session)

> Read this first. It captures the entire product, everything built, every
> decision, the deploy state, gotchas, and the open questions — so a fresh
> session can continue without re-deriving context. Last updated: 2026-07-16.

> **Update (this session):** the **hybrid retrieval engine is now built** — own
> semantic (vector) + lexical (BM25) index over an ingested corpus, fused with
> Reciprocal Rank Fusion (RRF), on top of IK-live. Legal-aware chunker,
> ingestion pipeline (JSONL + pgvector), and an offline benchmark harness
> (`recall@k`/MRR) are in. See **`docs/RETRIEVAL.md`**. Still TODO before it goes
> live: run ingestion with a real embeddings key (`voyage-law-2`) to build a
> larger corpus, then benchmark with `--embeddings voyage` to confirm vector +
> hybrid beat BM25 on Indian legal text (the embedding de-risk).

---

## 0. TL;DR

**Nyaya** = AI legal-research tool for Indian advocates. Advocate types **case
facts in plain language** → gets **5–10 relevant judgments** (Supreme Court /
High Courts via Indian Kanoon) each with a **source link**, a **relevance note**
("why it matters"), and the **holding**.

- **Live demo:** password-gated Streamlit app at **https://nyayaindia.streamlit.app**
- **Repo:** https://github.com/varunlahoti/nyaya (public)
- **Status:** demo is being validated by an advocate friend. The user wants a
  **full production-grade system for thousands of users** built **later, after
  feedback** — do NOT start the big build unprompted.
- **Phase 1 (multi-user foundation) is already built + committed** (backend auth
  + frontend auth + DB + caching). Blueprint in `docs/PRODUCTION_ARCHITECTURE.md`.

---

## 1. The retrieval question (IMPORTANT — user asked this last)

**User's concern:** "Indian Kanoon isn't giving the best set of results — what
else can we integrate?"

**Honest diagnosis:** Indian Kanoon has arguably the **most comprehensive free
Indian case-law corpus** (millions of judgments). The weak link is usually **our
retrieval strategy**, not IK's data:
- We rely on IK's **keyword search + its ranking**, fetch only top-N per query,
  and rerank on **short snippets** (not full text).
- Small prompt changes → different LLM queries → different IK results.

### The bigger lever (recommended before adding sources): build our own retrieval
1. **Ingest a large corpus once** (via IK API + eSCR bulk) into **pgvector**.
2. **Legal embeddings** (`voyage-law-2` or similar) → **semantic search** over
   full judgment text (beats keyword matching).
3. **Hybrid retrieval** = BM25 (keyword) + vector (semantic), fused.
4. **Full-text reranking** (deep mode) instead of snippet-only.
5. **Better query generation** + more candidates + citation/authority boosting.
This gives us control over ranking → materially better results than depending on
IK's search. **This is the real quality unlock.**

### Sources we CAN add (data)
| Source | Type | Notes |
|---|---|---|
| **eSCR / digiscr.sci.gov.in** | Official SC judgments | Free, downloadable, **neutral citations**, authoritative. Prefer official bulk data. |
| **eCourts / High Court portals** | HC + district judgments | APIs vary by state; some have services. CAPTCHAs on many — enable only where ToS permits. |
| **India Code (indiacode.nic.in)** | Bare acts / statutes | For statute text + section context (not judgments). |
| **Manupatra API** | Paid commercial | Good coverage + headnotes; needs a paid licence. |
| **SCC Online** | Paid, gold-standard headnotes | Expensive; licensing deal required; best editorial quality. |

### Sources that are NOT data APIs (enrichment only)
- **CaseMine** — paid AI competitor, **no public API**. Integration = partnership
  only. Treat as a benchmark, not a source.
- **LiveLaw / Bar & Bench** — legal **news** publishers. **RSS feeds** exist →
  use for a "recent legal news / developments" feed + **cross-links** (attributed,
  linking back). Do **not** scrape/republish their copyrighted articles or host
  their PDFs. Judgments themselves come from primary sources, not news sites.

**Recommendation:** (1) build the semantic/hybrid retrieval over an ingested
corpus (biggest win), (2) add **eSCR** for official SC + neutral citations,
(3) add **eCourts/HC** where permitted, (4) LiveLaw/Bar&Bench as an RSS news
enrichment layer + cross-links, (5) Manupatra/SCC only if budget + licensing.

---

## 2. What Nyaya is (product)

Pipeline (facts → judgments):
1. **Parse** (LLM) — extract legal issues, statutes/sections, keywords from facts.
2. **Build queries** — ~4 targeted searches (per issue, per statute, fact-pattern,
   + a Supreme Court priority query).
3. **Retrieve** — Indian Kanoon search (relevance-ranked, up to 25/query) + a
   local **seed corpus** of 14 landmark cases (blended in).
4. **Merge / dedupe / score** — blend IK rank + court authority (SC>HC>trial) +
   citation count → top 25 candidates.
5. **Rerank** (LLM) — read facts + 25 candidates → pick best 5/8/10, write
   relevance note + holding. **References candidates by id → never hallucinates
   a citation** (anti-hallucination guarantee).

Not random: two relevance filters (IK search + LLM rerank). Bounded by what IK
surfaces for the generated queries.

---

## 3. Current state / what's deployed

- **Streamlit demo** — LIVE, password-gated, at `nyayaindia.streamlit.app`.
  Entry file `backend/streamlit_app.py`. Deployed via Streamlit Community Cloud
  from the GitHub repo (auto-redeploys on `git push`). Runs the real pipeline
  in-process. Prettified UI (cream/navy/serif, result cards, ikanoon logo).
  Secrets (keys + `APP_PASSWORD`) live in the Streamlit dashboard, NOT the repo.
- **The full accounts product (Next.js + FastAPI)** — code done + committed, but
  **NOT deployed yet**. Would deploy on Vercel + Render + Neon/Upstash (free).

---

## 4. What's been built (inventory)

Repo layout:
```
backend/                 FastAPI app + Streamlit app
  app/
    config.py            all settings (env-driven)
    schemas.py           API + pipeline types
    main.py              FastAPI entrypoint (routers, startup)
    deps.py              auth deps, quota, app-password gate
    core/security.py     argon2 hashing, JWT, refresh tokens
    core/ratelimit.py    Redis/in-process daily counters
    api/                 health, auth, search, history
    db/                  session.py, models.py, crud.py, base.py (VectorStore)
    services/
      llm.py             OpenRouter (default) + Anthropic; JSON, temp 0
      fact_parser.py     step 1 (LLM + heuristic fallback)
      query_builder.py   step 2 (targeted queries + SC-priority)
      reranker.py        step 5 (closed-set rerank, anti-hallucination)
      pipeline.py        orchestrator (fan-out, merge, cite/court boost, cache)
      cache.py           Redis-or-in-process cache (search + IK query/doc)
      embeddings.py      pluggable (voyage/openai/hash-dev-fallback)
      memory_store.py    in-RAM seed corpus (landmark blend)
      retrievers/        base, indian_kanoon (live API), vector, sc/hc stubs
    data/seed_judgments.json   14 landmark cases (Arnesh Kumar, Dhanapal Chettiar…)
  streamlit_app.py       deployed demo UI (secrets bridge, password gate, quota, cards)
  requirements.txt       MINIMAL (streamlit deploy) — streamlit,pydantic,pydantic-settings,httpx
  requirements-api.txt   full FastAPI deps (fastapi,uvicorn,sqlalchemy,asyncpg,argon2,…)
  Dockerfile             FastAPI image (binds $PORT for Render)
frontend/                Next.js 14 PWA (TypeScript, Tailwind)
  app/page.tsx           protected search UI (redirects to /login if not authed)
  app/login/page.tsx     login/register screen
  lib/auth.ts            JWT token mgmt + auth API calls
  lib/api.ts             search with Bearer + auto-refresh on 401
  components/            ResultCard, ParsedPanel, Attribution (ikanoon logo)
  public/                manifest, service worker, ikanoon SVG logos
docs/
  PRODUCT_OVERVIEW.md, SYSTEM_DESIGN.md, API_SPEC.md, DATA_SOURCES.md
  PRODUCTION_ARCHITECTURE.md   full HLD + LLD (the build blueprint)
  DEPLOY_STREAMLIT.md, HANDOVER.md (this file)
render.yaml              Render blueprint: multi-user backend + free Postgres
docker-compose.yml       local: db(pgvector)+redis+api+web
.streamlit/config.toml   forces light theme (fix white-text-on-cream)
```

**Phase 1 (multi-user) — built + verified end-to-end (SQLite test passed):**
- Custom auth: `register/login/refresh/logout/me`, **argon2** passwords, JWT
  access + **rotating refresh tokens** (hashed, revocable).
- Postgres persistence: users, refresh_tokens, searches+results, matters,
  usage_daily, audit_log. Tables auto-create on startup (`DB_AUTO_CREATE`).
- Per-user, per-plan daily quotas metered in DB.
- Search history endpoint (`GET /api/v1/history`).
- Frontend: login/register UI, protected app, sign-out, JWT refresh-on-401.

---

## 5. Key technical decisions

- **LLM via OpenRouter** (not Anthropic, for cost): reranker `deepseek/deepseek-chat`,
  parser `google/gemini-2.5-flash`. `temperature=0` (determinism). Provider is
  swappable (`LLM_PROVIDER=anthropic` supported). JSON via lenient parse.
- **Auth:** custom (argon2 + JWT + rotating refresh) on **managed Postgres**
  (Neon/Supabase). NOT Supabase-Auth/Clerk — full control, no per-MAU fee.
- **Cache:** Redis (Upstash) for **deterministic** results across restarts +
  shared across instances. In-process fallback for single instance. Search cache
  TTL 30 days (`SEARCH_CACHE_TTL_HOURS`, configurable) — determinism vs freshness.
  **Note: LLMs aren't byte-deterministic even at temp 0 — the cache is the real
  determinism guarantee (freeze-on-first-run).**
- **Billing:** Razorpay (India — UPI/cards) — **deferred to Phase 2**.
- **Hosting (launch):** FREE stack — Vercel (frontend) + Render (backend + free
  Postgres) + Upstash (Redis). Free subdomains, **no AWS, no domain** to start.
  AWS + custom domain are later, at scale.
- **Anti-hallucination:** reranker only references retrieved candidates by id.
- **Retrieval quality fixes applied:** bigger pool (25/query), citation-count
  boost, temp 0, landmark seed blend (`VECTOR_BACKEND=memory` default).

---

## 6. Cost model (per search)

- LLM (DeepSeek + Gemini via OpenRouter): ~₹0.15–0.35
- Indian Kanoon: ~₹1.5–2 (≈4 queries, each ~1 credit). **Cached repeats = ₹0.**
- Result count (5/8/10): **no meaningful cost difference** (same queries).
- **Deep mode** (full-text rerank): ~₹6.5 (adds ~8 IK doc fetches) — the real
  cost lever, opt-in.
- IK per-call rate ~₹0.50 is an **estimate** — verify on IK's pricing page.
- Margins (Advocate ₹799/mo): ~70–90% with model routing + cache hits.

---

## 7. Compliance / legal

- **Indian Kanoon API licence (binding):** mandatory **"Powered by IKanoon" logo**
  — on top of results (direct display) AND in footer (RAG use). Implemented:
  SVG logos in `frontend/public/` + `Attribution.tsx`; text/HTML mark in Streamlit.
  Pre-paid (balance out → no results); AS-IS (no accuracy warranty → verify-at-
  source disclaimer on every response); Bangalore jurisdiction. Auth = `Authorization: Token <key>` header (confirmed working).
- **Other sources:** respect ToS/robots; RSS for news (LiveLaw/Bar&Bench) is OK
  for headlines+links, not article republishing; don't scrape CAPTCHA'd portals.
- **User data:** case facts are sensitive → encrypt at rest, tenant-scoped, never
  train models; ZDR LLM option for Enterprise.

---

## 8. Environment gotchas (bit us this session)

- **User's ISP intermittently blocks github.com AND streamlit.io at the IP level**
  (DNS tampering + IP block; external DNS 1.1.1.1/8.8.8.8 also blocked). Fix:
  **Cloudflare WARP** (free VPN — install "1.1.1.1" app, enable WARP mode) or a
  **mobile hotspot**. huggingface.co stays reachable even when blocked.
- **Local Python is exactly 3.9.7** — Streamlit refuses to install on 3.9.7
  (known exclusion). Also `cryptography` needs Rust to build on 3.9.7 → use
  `python-jose` without the crypto extra locally (HS256 works pure-python).
- **Streamlit Cloud runs Python 3.14** → pinned old `pydantic` had no wheel →
  Rust build failed. Fix: keep the **deploy** `requirements.txt` minimal +
  loosely pinned (prebuilt wheels). Heavy API deps live in `requirements-api.txt`.
- **HF Spaces now requires PRO ($9/mo)** for Docker/Gradio Spaces (streamlit SDK
  rejected; only static is free) — so HF was abandoned for Streamlit Cloud.
- **API keys were exposed in this chat** (OpenRouter + Indian Kanoon). **User
  should rotate both** and re-enter in Streamlit secrets. Keys are NOT in the
  repo (verified with ripgrep + git check-ignore); they live only in `backend/.env`
  (git-ignored) and the Streamlit dashboard.
- **`gh` CLI is authenticated** as `varunlahoti` on the machine (SSH). **`hf` CLI**
  authenticated as `varunlahoti13`. Local venv for testing: `/tmp/nyaya-venv`
  (may not persist); project venv `backend/.venv`.

---

## 9. How to run locally (quick ref)

```bash
# Streamlit demo (needs Python 3.10+ — NOT 3.9.7)
cd backend && pip install -r requirements.txt && streamlit run streamlit_app.py

# FastAPI backend (dev, heuristic fallback if no keys)
cd backend && pip install -r requirements-api.txt
VECTOR_BACKEND=memory uvicorn app.main:app --reload   # localhost:8000/docs

# Frontend
cd frontend && npm install && npm run build && npm start   # localhost:3000

# Full stack (Docker): docker compose up --build
```
Config: copy `.env.example` → `backend/.env`. Keys: `OPENROUTER_API_KEY`,
`INDIAN_KANOON_API_TOKEN`. For accounts: `DATABASE_URL`, `AUTH_REQUIRED=true`,
strong `JWT_SECRET`, `REDIS_URL`.

---

## 10. Deploy the real product (free, no AWS/domain) — for later

1. **Backend + Postgres:** render.com → New → **Blueprint** → the repo (reads
   `render.yaml`; provisions API + free Postgres). Set dashboard secrets:
   `OPENROUTER_API_KEY`, `INDIAN_KANOON_API_TOKEN`, `REDIS_URL`. Get API URL.
2. **Redis:** upstash.com → create Redis → copy URL → into Render `REDIS_URL`.
3. **Frontend:** vercel.com → import repo → **Root Directory = `frontend`** →
   env `API_BASE_URL` = Render URL → deploy.
4. Open Vercel URL → register → search. Friends sign up themselves.
Note: cannot be done by the assistant — needs the user's Render/Vercel/Upstash
logins. Assistant guides; user clicks.

---

## 11. Roadmap / open actions

- **LIVE now — hosted hybrid library (built 2026-07-21):** IK + own Neon
  pgvector corpus, Voyage `voyage-law-2` embeddings, fused. Streamlit reads it
  when secrets are set. **Open items:**
  - [ ] **Load remaining ~9k SC judgments.** Neon free tier (0.5 GB) filled at
    ~31,500 rows (**28,003 of ~37k SC + 3.5k HC**) — `DiskFullError`. 1024-dim
    vectors + HNSW index are the space hog, not text. Options: re-embed at
    256/512-dim (voyage-3-lite) to fit all 37k free, OR Neon paid ($19/mo), OR
    move to Oracle/VPS (200 GB) for full set + eventual full-text. **Accepted 28k
    for now.**
  - [ ] **Full-text SC** (currently title+citation snippet only → coverage/lookup
    layer, weak for fact-pattern). Fetch digiscr PDFs → deep-fetch/pdf-dir ingest;
    needs >0.5 GB storage.
  - [ ] Prune 140 duplicate SC done; watch that `load_corpus_to_neon.py` re-run
    doesn't re-add them (filter SC out of that path if rebuilding).
- **NOW:** advocate friend validates the Streamlit demo → collect feedback
  (relevance, missing landmarks, willingness-to-pay, UX friction, features).
- **THEN (user's signal) — production build for thousands:**
  - **Phase 2 Billing:** Razorpay subscriptions + webhooks + metering + portal.
  - **Retrieval upgrade (top priority for quality) — BUILT this session:** own
    hybrid index over an ingested corpus (vector + BM25, RRF fusion), legal-aware
    chunker, ingestion pipeline (`scripts/ingest.py`), benchmark harness
    (`scripts/benchmark.py`). Remaining: run ingestion with `voyage-law-2` to
    build a real corpus, benchmark to confirm gains, add eSCR + eCourts sources.
    Full-text (deep) rerank already existed. See `docs/RETRIEVAL.md`.
  - **Depth:** exports (Word/PDF memo), matters, saved searches, feedback loop,
    statute browser, LiveLaw/Bar&Bench RSS news layer + cross-links.
  - **Scale/ops:** observability (Sentry, metrics, cost/search), rate-limit
    hardening, email verification + password reset, SSO/VPC for Enterprise,
    AWS + custom domain, CI/CD + Alembic migrations.

---

## 12. Monetization

Free (3/day) → Advocate ₹799/mo (100/day, history, matters, export, deep) →
Firm ₹1,499/seat (workspace, roles) → Enterprise (API, SSO, VPC, custom corpora).
Levers: seat subscriptions, usage add-ons (bulk deep research), API access.

---

**Bottom line for the next session:** the demo is live and being validated; the
production foundation + full architecture are built and committed. When the user
returns with feedback and says "build it," start from `PRODUCTION_ARCHITECTURE.md`,
prioritise the **retrieval upgrade** (own semantic index) since that's the #1
quality gap, and wire **billing (Razorpay)**. Do not deploy to the user's cloud
accounts yourself — guide them.
```
