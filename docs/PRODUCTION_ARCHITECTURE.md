# Nyaya — Production Architecture (HLD + LLD)

Target: a multi-tenant, monetizable SaaS. Advocates sign up, subscribe, and run
searches; usage is metered and billed; results are cached deterministically.

---

# PART A — High-Level Design (HLD)

## A.1 System context

```
        Advocates (web + installable PWA + mobile)
                          │  HTTPS
                          ▼
                 ┌─────────────────┐
                 │   CDN / Edge    │  (Vercel/Cloudflare) — static frontend, TLS
                 └────────┬────────┘
                          │  /api/*  (JSON)
                          ▼
        ┌───────────────────────────────────────────┐
        │        API Gateway / Load Balancer         │  rate-limit, WAF, TLS
        └───────────────────┬───────────────────────┘
                            ▼
        ┌───────────────────────────────────────────┐
        │        FastAPI app (stateless, N pods)     │
        │  auth · search · billing · matters · admin │
        └───┬───────────┬──────────┬─────────┬───────┘
            │           │          │         │
      ┌─────▼───┐ ┌─────▼────┐ ┌───▼────┐ ┌──▼──────────┐
      │ Postgres│ │  Redis   │ │  LLM   │ │ Indian Kanoon│
      │ (users, │ │ (cache,  │ │ (Open- │ │  + SC/HC     │
      │ billing,│ │ rate-lim,│ │ Router)│ │  sources     │
      │ history)│ │ queue)   │ └────────┘ └──────────────┘
      └─────────┘ └──────────┘
            │           
      ┌─────▼──────────────────┐   ┌───────────────┐
      │ Object store (S3/R2)   │   │ Payment (Razorpay
      │ exports, judgment PDFs │   │  / Stripe) webhooks
      └────────────────────────┘   └───────────────┘

      Background workers (Celery/RQ): corpus ingestion, embeddings,
      "watch matter for new judgments", async exports, email.
```

## A.2 Components & responsibilities

| Component | Responsibility |
|---|---|
| **Frontend** (Next.js PWA) | UI, offline shell, auth session, calls `/api/*` |
| **API (FastAPI)** | Auth, search orchestration, billing, matters, admin. Stateless → scale horizontally |
| **Postgres** | Source of truth: users, orgs, subscriptions, usage, search history, matters, judgments corpus |
| **Redis** | Search-result cache, IK/doc cache, rate-limit counters, quota counters, job queue broker |
| **Object store** (S3 / Cloudflare R2) | Exported memos (PDF/DOCX), cached judgment PDFs |
| **LLM** (OpenRouter) | Fact parsing + reranking |
| **Sources** | Indian Kanoon API (primary), SC/HC connectors |
| **Payments** | Razorpay (India) / Stripe — subscriptions + metered add-ons; webhooks update entitlements |
| **Workers** | Ingestion, embeddings, scheduled "watch" alerts, async export, transactional email |
| **Observability** | Structured logs, metrics (Prometheus), tracing, error tracking (Sentry), per-search cost |

## A.3 Key non-functional requirements

- **Determinism:** identical query → identical result (Redis cache, frozen TTL).
- **Multi-tenant isolation:** row-level scoping by `user_id` / `org_id`; Enterprise gets schema/VPC isolation.
- **Metered billing:** every search recorded; plan quotas enforced; overage billed or blocked.
- **Availability:** stateless API + managed Postgres/Redis; graceful degradation if a source is down.
- **Security:** OWASP baseline, encrypted secrets, PII protection for case facts, audit log.
- **Scale:** horizontal API pods; Redis + Postgres managed; workers scale independently.

## A.4 Request flow (search)

```
1. Frontend POST /api/v1/search  (JWT in Authorization)
2. API: authenticate → resolve user + plan
3. Enforce quota (Redis counter) → 402/429 if over
4. Cache lookup (Redis, key = hash(normalised facts + params))
     hit  → return cached result (0 credits, deterministic)  [cached=true]
     miss ↓
5. Pipeline: parse (LLM) → build queries → retrieve (IK + vector) →
   merge/rank → rerank (LLM)
6. Persist: searches row + results rows + usage row + cost_micros
7. Cache result (Redis, frozen TTL)
8. Return
```

---

# PART B — Low-Level Design (LLD)

## B.1 Data model (Postgres)

```sql
orgs(id, name, plan, seats, billing_customer_id, created_at)
users(id, org_id, email, password_hash, full_name, role, plan,
      email_verified, created_at)
--   role ∈ {owner, admin, member};  plan ∈ {free, advocate, firm, enterprise}

api_keys(id, user_id, hashed_key, name, last_used_at, revoked_at)

subscriptions(id, org_id, provider, provider_sub_id, plan, status,
              current_period_end, created_at)
--   status ∈ {active, past_due, canceled, trialing}
invoices(id, org_id, provider_invoice_id, amount, currency, status, created_at)

searches(id, user_id, org_id, matter_id, facts_text, parsed_json,
         jurisdiction, court_level, deep, status, latency_ms,
         cost_micros, cached, created_at)
search_results(id, search_id, rank, judgment_id, citation, title, court,
               court_level, date, url, relevance_score, relevance_note, holding)

matters(id, user_id, org_id, title, notes, created_at)
saved_searches(id, user_id, search_id, label)
feedback(id, search_id, judgment_id, signal, created_at)  -- relevant/not/cited

judgments(id, source, source_doc_id, citation, title, court, court_level,
          bench, date, url, cites, full_text_ref, metadata_json, created_at)
judgment_chunks(id, judgment_id, chunk_index, text, embedding vector(1024))

usage_daily(user_id, day, search_count, deep_count, cost_micros)
audit_log(id, actor_id, action, target, meta_json, ip, created_at)
watches(id, user_id, matter_id, query_json, last_checked_at, active)  -- alerts
```

Indexes: `searches(user_id, created_at)`, `judgments(source, source_doc_id)`,
HNSW on `judgment_chunks.embedding`, unique `users(email)`.

## B.2 Auth (LLD)

- **Sign-up/login:** email + password (argon2/bcrypt). Email verification token.
- **Tokens:** short-lived **access JWT** (15 min) + rotating **refresh token**
  (httpOnly cookie, 30 d, stored hashed for revocation).
- **Password reset:** signed, single-use, time-boxed token → email.
- **API keys** (Enterprise): `X-API-Key`, hashed at rest, scoped + revocable.
- **RBAC:** `owner/admin/member` for firm workspaces; middleware checks role.
- **Optional:** SSO (SAML/OIDC) for Enterprise.

Endpoints: `POST /auth/register|login|refresh|logout|verify-email|forgot|reset`,
`GET /auth/me`.

## B.3 Billing (LLD) — Razorpay (India) or Stripe

- **Plans** as products/prices in the provider. Checkout → subscription.
- **Webhooks** (`/api/v1/billing/webhook`, HMAC-verified) update
  `subscriptions` + entitlements on `subscription.activated/charged/halted`.
- **Entitlement resolution:** on each request, plan → quota + features (deep,
  export, API). Cached in Redis (short TTL) to avoid a DB hit per request.
- **Metering:** every search writes `usage_daily`; nightly job reconciles;
  overage either blocked (hard cap) or billed (usage-based add-on).
- **Portal:** hosted customer portal for card/plan management.

## B.4 Caching (LLD) — the determinism guarantee

| Cache | Key | TTL | Purpose |
|---|---|---|---|
| Search result | `search:{sha256(norm_facts+params)}` | 30 d (config) | Deterministic replay, 0 credits |
| IK query | `ik:q:{sha256(query+limit)}` | 7 d | Cross-search credit savings |
| IK document | `ik:doc:{id}` | 7 d | Avoid re-fetch |
| Entitlements | `ent:{user_id}` | 60 s | Avoid per-request DB hit |
| LLM system prompt | (provider prompt cache) | — | Cheaper LLM |

Redis is the shared store → same result for all users/instances, survives
restart/deploy. Cache invalidation: version prefix bump on pipeline changes.

## B.5 Rate limiting & quotas (LLD)

- **Per-plan daily quota** (searches, deep-searches) — Redis `INCR` + `EXPIRE`.
- **Burst limit** (req/min) — token bucket in Redis.
- **Global safety cap** — protects API credits from abuse.
- Over quota → `429` + `Retry-After`; over plan → `402` upsell.

## B.6 API surface (v1)

```
POST /api/v1/search                 core search (JWT)   [dependencies: quota, entitlement]
GET  /api/v1/search/{id}            fetch prior search
GET  /api/v1/history                paginated
POST /api/v1/matters                CRUD matters
POST /api/v1/search/{id}/export     pdf/docx (async → object store → signed URL)
POST /api/v1/search/{id}/feedback   tuning signal
GET  /api/v1/me / me/usage          profile + quota
auth/*  billing/*  admin/*  keys/*
```

## B.7 Deployment topology

- **Frontend:** Vercel / Cloudflare Pages (Next.js, PWA, global edge).
- **API:** container (Docker) on Render/Railway/Fly (managed) → later K8s/ECS.
- **Postgres:** managed (Supabase / Neon / RDS) with pgvector.
- **Redis:** managed (Upstash / Redis Cloud / ElastiCache).
- **Object store:** Cloudflare R2 / S3.
- **Workers:** same image, `celery worker` / `rq worker` command.
- **CI/CD:** GitHub Actions → build, test, migrate (Alembic), deploy.
- **Envs:** dev / staging / prod, isolated secrets.

## B.8 Security & compliance

- TLS everywhere; secrets in a manager (not env files in prod).
- Passwords hashed (argon2); JWT rotation; refresh revocation.
- Case facts = sensitive: encrypted at rest, tenant-scoped, **never used to
  train models**; ZDR LLM setting for Enterprise.
- Input validation, output encoding, SQL via ORM (no raw string SQL with input).
- Rate limiting, WAF, bot protection on auth + search.
- Audit log; GDPR/DPDP-style data export + deletion endpoints.
- Indian Kanoon licence: mandatory "Powered by IKanoon" attribution (already
  implemented) + respect ToS/rate limits.

## B.9 Observability

- Structured JSON logs with request id (propagated to LLM as `_request_id`).
- Metrics: search latency (p50/p95), cache hit rate, cost/search, error rate,
  source availability, quota rejections.
- Tracing across parse→retrieve→rerank stages.
- Error tracking (Sentry). Alerts on cost spikes, source outages, quota abuse.

## B.10 Cost & unit economics (per search)

- LLM (OpenRouter, DeepSeek+Gemini): ~₹0.15–0.35
- Indian Kanoon: ~₹1.5–2 (4 queries) — **cached repeats = ₹0**
- Infra amortised: negligible
- **~₹2/search; repeats ₹0.** Deep mode ~₹6.5.
- Margins: Advocate ₹799/mo ≈ 70–90% depending on model routing + cache hit rate.

---

# PART C — Monetization

| Plan | ₹/mo | Searches/day | Features |
|---|---|---|---|
| Free | 0 | 3 | core search, source links |
| Advocate | 799 | 100 | + history, matters, export, deep mode |
| Firm | 1,499/seat | fair-use | + shared workspace, roles, team history |
| Enterprise | custom | custom | + API, SSO, VPC, custom corpora, SLA |

Revenue levers: seat subscriptions (primary), usage add-ons (bulk deep
research), API access (per-call), Enterprise/VPC premium.

---

# PART D — Build phases

- **Phase 1 — Foundation (multi-user core):** Postgres + Alembic, real auth
  (register/login/JWT/refresh), per-user quotas, Redis cache/rate-limit, search
  history, deploy on managed infra. → *app usable by real accounts.*
- **Phase 2 — Monetization:** Razorpay/Stripe subscriptions + webhooks +
  entitlements + billing portal + metering. → *taking money.*
- **Phase 3 — Product depth:** exports, matters, feedback loop, saved searches,
  full-text deep-rank, SC/HC connectors, larger corpus.
- **Phase 4 — Scale & moat:** watch-alerts, citation graph, analytics, API
  product, SSO/VPC, observability hardening.
```
