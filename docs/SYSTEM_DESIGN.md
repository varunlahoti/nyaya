# System Design — Nyaya

## 1. High-level architecture

```
                    ┌──────────────────────────────────────────┐
                    │              Clients                      │
                    │  Next.js PWA (web + installable mobile)   │
                    └───────────────┬──────────────────────────┘
                                    │ HTTPS / JSON
                                    ▼
                    ┌──────────────────────────────────────────┐
                    │            API Gateway / Nginx            │
                    │   TLS, rate-limit, auth pass-through      │
                    └───────────────┬──────────────────────────┘
                                    ▼
        ┌───────────────────────────────────────────────────────────────┐
        │                    FastAPI application                         │
        │                                                               │
        │   /auth        /search        /matters      /history  /admin  │
        │      │             │              │             │             │
        │      │             ▼                                          │
        │      │   ┌───────────────────── Retrieval Orchestrator ─────┐ │
        │      │   │  1 FactParser (LLM)                              │ │
        │      │   │  2 QueryBuilder                                  │ │
        │      │   │  3 Retrievers (async fan-out):                   │ │
        │      │   │       IndianKanoon | Vector | SC | HC adapters   │ │
        │      │   │  4 Merge + dedupe                                │ │
        │      │   │  5 Reranker (LLM) + relevance notes              │ │
        │      │   └──────────────────────────────────────────────────┘│
        └───────┼───────────────┬───────────────┬──────────────────────┘
                │               │               │
        ┌───────▼──────┐ ┌──────▼───────┐ ┌─────▼─────────┐  ┌──────────────┐
        │  Postgres    │ │    Redis     │ │  Anthropic    │  │ Upstream     │
        │  + pgvector  │ │  cache+queue │ │  Claude API   │  │ sources      │
        │  users,      │ │  rate-limit  │ │  extract+rank │  │ IndianKanoon │
        │  matters,    │ │  doc cache   │ └───────────────┘  │ SC / HC      │
        │  history,    │ └──────────────┘                    └──────────────┘
        │  judgments,  │
        │  embeddings  │
        └──────────────┘
```

Async workers (optional, Phase 2+) run background jobs: corpus ingestion,
embedding generation, and "watch this matter for new judgments".

## 2. The retrieval pipeline (the heart of the product)

Implemented in `backend/app/services/pipeline.py` and the `services/` modules.

### Step 1 — Fact parsing (LLM)

Input: raw facts text. Output (structured JSON via Claude structured outputs):

```json
{
  "summary": "one-paragraph neutral restatement of the dispute",
  "legal_issues": ["whether the eviction notice under s.106 TPA was valid", ...],
  "causes_of_action": ["eviction", "arrears of rent"],
  "statutes": [{"act": "Transfer of Property Act, 1882", "sections": ["106", "111"]}],
  "keywords": ["defective notice", "month-to-month tenancy", "wilful default"],
  "area_of_law": "Property / Landlord-Tenant",
  "jurisdiction_hint": "any | supreme_court | high_court | <state>",
  "court_level_hint": "trial | high_court | supreme_court | any"
}
```

Why an LLM and not regex: issue-spotting requires reading comprehension. "The
tenant claims the notice was defective" implies s.106 TPA notice validity even
though the section is never mentioned.

### Step 2 — Query building

`QueryBuilder` turns the parsed structure into **several** targeted queries:

- One per legal issue (natural-language + boolean).
- One per statute/section (`"Transfer of Property Act" AND "section 106"`).
- One broad fact-pattern query for semantic retrieval.
- Applies jurisdiction/court filters where the source supports them.

Indian Kanoon supports a query DSL (`doctypes:`, `fromdate:`, `todate:`,
`title:`, `ANDD`/`ORR`, phrase quoting). The builder emits IK-native queries plus
plain queries for the vector store.

### Step 3 — Retrieval (async fan-out)

All retrievers implement one interface (`BaseRetriever.search(query) -> [Candidate]`)
and run concurrently with `asyncio.gather`. Shipped adapters:

- **IndianKanoonRetriever** — calls the Indian Kanoon Search API, then fetches
  doc metadata. Primary source. (Requires an API token.)
- **VectorRetriever** — semantic search over our own pgvector corpus of ingested
  judgments (embeddings). Great for fact-pattern matching where keywords fail.
- **SupremeCourtRetriever / HighCourtRetriever** — pluggable adapters for direct
  court sources (eCourts / judgment portals). Ship as stubs with a clear
  contract; enable per deployment where ToS permits (see DATA_SOURCES).

Each `Candidate` carries: `source`, `source_doc_id`, `url`, `title`, `court`,
`date`, `snippet`, and a `raw_score` from the source.

### Step 4 — Merge & dedupe

Candidates from all sources are merged. Dedupe key = normalised citation /
Indian Kanoon doc id / title+court+date fuzzy match. Source-provided scores are
normalised to a common 0–1 scale and blended (weighted by source trust) into a
`prelim_score`. Top **K (default 25)** candidates proceed to rerank.

### Step 5 — LLM rerank + relevance notes

The candidate set (title + court + date + snippet + key holding if cached) is
handed to Claude with the original facts and parsed issues. Claude:

1. Scores each candidate 0–100 for **relevance to these specific facts**.
2. Selects the top `max_results` (5–10).
3. Writes a one-line **relevance note** and a 1–2 sentence **holding** per pick.

Output is constrained with **structured outputs** so it's always parseable, and
**critically, Claude may only reference candidates from the provided list** — it
returns candidate ids, not free-text case names. This is the anti-hallucination
guarantee (see §6).

The system prompt is stable and marked with `cache_control` for prompt caching,
so repeated searches only pay full price for the variable candidate/facts part.

## 3. Data model (Postgres)

```
users(id, email, password_hash, full_name, role, firm_id, plan, created_at)
firms(id, name, plan, seats, created_at)
api_keys(id, user_id, hashed_key, name, last_used_at, revoked)

searches(id, user_id, matter_id, facts_text, parsed_json, jurisdiction,
         status, latency_ms, cost_micros, created_at)
search_results(id, search_id, rank, judgment_id, relevance_score,
               relevance_note, holding)

matters(id, user_id, firm_id, title, notes, created_at)   -- Phase 2
saved_searches(id, user_id, search_id, label)

judgments(id, source, source_doc_id, citation, title, court, court_level,
          bench, date, url, full_text_ref, metadata_json, created_at)
judgment_chunks(id, judgment_id, chunk_index, text, embedding vector(1024))

usage_counters(user_id, day, search_count)  -- quota enforcement
audit_log(id, user_id, action, meta_json, created_at)
```

`judgment_chunks.embedding` is a `pgvector` column with an HNSW index for fast
approximate nearest-neighbour semantic search.

## 4. Caching strategy

| What | Where | TTL | Why |
|------|-------|-----|-----|
| Source documents (IK docs, PDFs) | Postgres `judgments` + object store | Long | Avoid re-fetching; respect rate limits |
| Embeddings | `judgment_chunks` | Permanent | Expensive to recompute |
| Identical-facts search result | Redis (hash of normalised facts) | 24h | Dedup repeat queries |
| Claude system prompt | Anthropic prompt cache (`cache_control`) | 5 min rolling | Cheaper reranks |
| Rate-limit / quota counters | Redis | Rolling window | Fast quota checks |

## 5. Scaling & reliability

- **Stateless API** behind a load balancer; scale horizontally.
- **Async fan-out** keeps p95 latency near the slowest single retriever, not the
  sum. Per-retriever timeouts (e.g. 4s) with graceful degradation — if IK is
  slow, return vector results and flag partial.
- **Circuit breakers** per upstream; cached fallback when a source is down.
- **Background ingestion** decouples corpus growth from request latency.
- **Cost guardrails**: candidate cap (K), model routing by tier (Enterprise gets
  the strongest model; Free can use a cheaper one), and prompt caching.
- **Observability**: structured logs, per-stage timings, per-search cost in
  `cost_micros`, request ids propagated to Anthropic (`_request_id`).

## 6. Anti-hallucination (non-negotiable)

The failure mode that kills legal-AI trust is a confident, fake citation. Design
guarantees against it:

1. **Retrieve-then-rank, never generate.** Case names/citations come only from
   fetched source documents. The LLM ranks a *closed set*.
2. **Reference by id.** The reranker returns candidate ids; the server maps ids
   back to the fetched documents. If the model emits an id not in the set, it's
   dropped.
3. **Every card links to source.** The UI shows the source link prominently; the
   advocate verifies before citing.
4. **No result is better than a wrong one.** If retrieval finds nothing solid,
   the API returns an empty/low-confidence result with guidance, not filler.
5. **Confidence surfaced.** Each result carries a score; low-confidence sets are
   labelled so the advocate knows to dig further manually.

## 7. Security & privacy

- TLS everywhere; secrets from env / secret manager (never in code).
- Passwords hashed (argon2/bcrypt); JWT access + refresh tokens.
- Case facts are sensitive: encrypted at rest; **not used to train models**;
  per-firm data isolation available on Enterprise (separate schema / VPC).
- Rate limiting and quotas per user/plan (Redis).
- Audit log of searches for firm compliance.
- Anthropic requests are transient; no client data persisted by the model
  provider beyond their standard retention (configurable to ZDR for enterprise).

## 8. Model choice (provider-abstracted)

The LLM layer (`backend/app/services/llm.py`) is provider-abstracted:

- **OpenRouter (default)** — OpenAI-compatible; access to cheap, strong models at
  a fraction of frontier cost. Defaults: **DeepSeek V3** (`deepseek/deepseek-chat`)
  for the quality-sensitive **reranker**, **Gemini Flash**
  (`google/gemini-2.0-flash-001`) for the lower-stakes **parser**. This drops
  per-search LLM cost from ~₹6–7 (Opus) to ~₹0.15 while keeping strong ranking.
- **Anthropic** — set `LLM_PROVIDER=anthropic` to use Claude (structured outputs
  + prompt caching).

Both providers return clean JSON: Anthropic via structured outputs, OpenRouter
via JSON-object mode + a lenient parser (tolerates fences/prose) so even the
cheapest models are safe. The reranker stays the strong model; the parser can be
the cheapest — tune per tier via `LLM_MODEL` / `LLM_PARSER_MODEL`.

### Caching (cost + latency)
`backend/app/services/cache.py` (Redis, or in-process fallback):
- **Identical-search cache (24h):** repeat facts → prior result, **0 IK credits,
  0 LLM**. Response carries `cached: true`.
- **IK query + document cache (7d):** the same query across different searches is
  served from cache — the direct lever on Indian Kanoon credit burn.
- **Query cap** (`MAX_QUERIES_PER_SEARCH`): each query ≈ 1 IK credit; cap trims
  the least-important queries.

## 9. Tech stack summary

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind, PWA | SSR + installable, one codebase web+mobile |
| Backend | FastAPI (Python 3.11), Pydantic v2 | Async, great LLM/ML ecosystem, typed |
| DB | Postgres 16 + pgvector | Relational + vector in one store |
| Cache/queue | Redis | Caching, rate-limit, light queue |
| LLM | OpenRouter (DeepSeek V3 / Gemini Flash) — Anthropic optional | Cheap + strong; provider-abstracted |
| Embeddings | Pluggable (`EMBEDDINGS_PROVIDER`) | Voyage/OpenAI/self-hosted BGE |
| Infra | Docker Compose (dev) → K8s (prod) | Portable |
