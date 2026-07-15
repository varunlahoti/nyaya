# API Specification — Nyaya

Base URL (local): `http://localhost:8000`
All endpoints are prefixed with `/api/v1`.
Auth: Bearer JWT in `Authorization` header, except `/auth/*` and `/health`.
Interactive docs (Swagger UI): `GET /docs` · OpenAPI JSON: `GET /openapi.json`.

---

## Conventions

- Content type: `application/json`.
- Timestamps: ISO 8601 UTC.
- Errors: `{ "detail": "<message>" }` with appropriate HTTP status.
- Rate limits: per-plan; `429` with `Retry-After` header when exceeded.
- Idempotency: `POST /search` is safe to retry; identical facts within 24h may
  return a cached result (`cached: true`).

---

## Health

### `GET /health`
Liveness/readiness probe. No auth.

**200**
```json
{ "status": "ok", "version": "0.1.0", "sources": { "indian_kanoon": "up", "vector": "up" } }
```

---

## Auth

### `POST /api/v1/auth/register`
```json
{ "email": "adv@example.com", "password": "•••••••", "full_name": "Adv. R. Sharma" }
```
**201** → user + tokens.

### `POST /api/v1/auth/login`
```json
{ "email": "adv@example.com", "password": "•••••••" }
```
**200**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "user": { "id": "u_123", "email": "adv@example.com", "plan": "advocate" }
}
```

### `POST /api/v1/auth/refresh`
```json
{ "refresh_token": "eyJ..." }
```
**200** → new access token.

---

## Search — the core endpoint

### `POST /api/v1/search`
Turn facts into ranked judgments.

**Request**
```json
{
  "facts": "The tenant stopped paying rent for 8 months. The landlord issued a notice under the Transfer of Property Act and now seeks eviction. The tenant claims the notice was defective and that he was a statutory tenant.",
  "jurisdiction": "any",
  "court_level": "any",
  "date_from": null,
  "date_to": null,
  "max_results": 8,
  "matter_id": null
}
```

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `facts` | string (20–8000 chars) | — | Required. Plain-language facts. |
| `jurisdiction` | enum | `any` | `any` \| `supreme_court` \| `high_court` \| `<state slug>` |
| `court_level` | enum | `any` | `any` \| `trial` \| `high_court` \| `supreme_court` |
| `date_from` / `date_to` | date \| null | null | Restrict judgment date range |
| `max_results` | int (5–10) | 8 | How many judgments to return |
| `deep` | bool | false | Deep mode: fetch full judgment text for top candidates before ranking (higher quality, more IK credits) |
| `matter_id` | string \| null | null | Attach search to a saved matter |

Ranking notes: a Supreme Court–priority query is always added (so binding
authority surfaces even for `jurisdiction=any`), and candidates are weighted by
court authority (SC > HC > trial). With `deep=true`, the reranker judges on full
judgment text and writes accurate holdings instead of headline snippets.

**200**
```json
{
  "search_id": "s_9f2a",
  "cached": false,
  "latency_ms": 4120,
  "parsed": {
    "summary": "Landlord seeks eviction for 8 months' rent arrears; tenant challenges validity of the s.106 TPA notice and claims statutory tenancy.",
    "legal_issues": [
      "Validity of a notice to quit under section 106 of the Transfer of Property Act, 1882",
      "Whether wilful default in payment of rent justifies eviction",
      "Whether the tenant is a statutory tenant and the effect on eviction"
    ],
    "statutes": [
      { "act": "Transfer of Property Act, 1882", "sections": ["106", "111"] }
    ],
    "keywords": ["defective notice", "wilful default", "statutory tenant", "eviction"],
    "area_of_law": "Property / Landlord–Tenant",
    "jurisdiction_hint": "any",
    "court_level_hint": "any"
  },
  "results": [
    {
      "rank": 1,
      "judgment_id": "j_ik_123456",
      "title": "V. Dhanapal Chettiar v. Yesodai Ammal",
      "citation": "(1979) 4 SCC 214",
      "court": "Supreme Court of India",
      "court_level": "supreme_court",
      "date": "1979-08-16",
      "source": "indian_kanoon",
      "url": "https://indiankanoon.org/doc/1983203/",
      "relevance_score": 94,
      "relevance_note": "Directly settles that a notice to quit under s.106 TPA is not a pre-condition for eviction under State Rent Acts — squarely addresses the tenant's defective-notice defence.",
      "holding": "A notice under s.106 of the Transfer of Property Act is not necessary to seek eviction under State Rent Control legislation; the ground of eviction alone must be proved."
    }
  ],
  "sources_used": ["indian_kanoon", "vector"],
  "partial": false,
  "disclaimer": "Research aid for qualified professionals. Verify each citation at its source before relying on it."
}
```

**Errors**
- `400` — facts too short/long, invalid enum.
- `401` — missing/invalid token.
- `402` — quota exceeded / plan required (also usable via 429 for daily caps).
- `429` — rate/daily-quota limit; `Retry-After` provided.
- `503` — all sources unavailable.

### `GET /api/v1/search/{search_id}`
Fetch a previous search + its results (own searches only).

---

## History & matters (Phase 2)

### `GET /api/v1/history?limit=20&cursor=...`
Paginated list of the user's past searches.

### `POST /api/v1/matters`
```json
{ "title": "Sharma v. Verma — eviction", "notes": "HC appeal" }
```

### `GET /api/v1/matters/{id}` · `GET /api/v1/matters/{id}/searches`

### `POST /api/v1/searches/{id}/save`
Bookmark a search.

---

## Export

### `POST /api/v1/search/{id}/export`
```json
{ "format": "pdf" }   // "pdf" | "docx" | "markdown"
```
**200** → file stream (or a signed URL). Includes citations, source links, and
relevance notes formatted for a research memo.

---

## Feedback (tuning loop)

### `POST /api/v1/search/{id}/feedback`
```json
{ "judgment_id": "j_ik_123456", "signal": "relevant" }  // relevant | not_relevant | cited
```
Feeds the reranking-quality loop and per-user personalisation.

---

## Admin / usage

### `GET /api/v1/me`
Current user, plan, quota remaining today.

### `GET /api/v1/me/usage`
```json
{ "plan": "advocate", "searches_today": 12, "daily_limit": 100, "period_cost_micros": 41000 }
```

---

## API keys (Enterprise)

### `POST /api/v1/keys` → create · `GET /api/v1/keys` → list · `DELETE /api/v1/keys/{id}` → revoke
Programmatic access to `POST /search` with `X-API-Key` instead of a JWT.

---

## Rate limits (defaults)

| Plan | Searches/day | Burst (req/min) |
|------|-------------|-----------------|
| Free | 5 | 5 |
| Advocate | 100 | 20 |
| Firm | fair-use (2000) | 60 |
| Enterprise | custom | custom |
