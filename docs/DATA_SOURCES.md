# Data Sources, Integrations & Legal / Compliance

Nyaya is only as trustworthy as its sources. This document describes each
upstream, how we integrate, and — importantly — the **terms-of-service, rate,
and licensing** constraints we honour. Read this before enabling a connector in
production.

> ⚠️ **Compliance first.** Indian court judgments are public records, but the
> *websites and databases* that host them have their own terms of use, robots
> policies, and rate limits. Nyaya's default and recommended integration is the
> **licensed Indian Kanoon API**. Direct scraping of court portals must only be
> enabled where the portal's terms permit automated access, and always within
> polite rate limits. Get legal sign-off for your jurisdiction before enabling
> scraping connectors.

---

## 1. Indian Kanoon (primary, licensed API)

- **What**: The largest free full-text search engine for Indian case law and
  bare acts (Supreme Court, all High Courts, tribunals, Central/State acts).
- **How we integrate**: The **official Indian Kanoon API** (paid, token-based).
  It exposes document search and document-fetch endpoints and is the intended,
  ToS-compliant way to programmatically query the corpus.
  - Search: returns doc ids, titles, courts, dates, snippets, scores.
  - Document: returns metadata and text for a doc id.
- **Auth**: API token (`INDIAN_KANOON_API_TOKEN`), sent as a header.
- **Rate/billing**: Pay-per-call. We **cache aggressively** (documents and
  search results) to minimise calls and cost, and we respect their published
  limits.
- **Query DSL** (used by `QueryBuilder`): phrase quoting `"..."`, `ANDD`/`ORR`,
  `doctypes:`, `fromdate:` / `todate:`, `title:`, `cites:`, `citedby:`.
- **Adapter**: `backend/app/services/retrievers/indian_kanoon.py`.

This is the retriever enabled by default. Everything else is optional/pluggable.

### ⚖️ Indian Kanoon API licence — binding obligations

From the IKanoon API Services Agreement. These are contractual, not optional:

1. **Mandatory attribution (the big one).** Whenever IK search results,
   documents, or classifiers are shown to users — **or** used to build RAG
   context / fine-tune models — you must display the **"Powered by IKanoon"
   logo**, unaltered and fully visible:
   - **Direct display** (we show IK results): logo **on top of the results**,
     desktop *and* mobile. → implemented in `frontend/components/Attribution.tsx`,
     rendered above the results list in `app/page.tsx`.
   - **Integrated/RAG use** (we feed IK docs to Claude): attribution in a
     prominent place (About/docs/footer). → implemented as the persistent
     footer attribution.
   - **Shipped:** `frontend/public/powered-by-ikanoon.svg` (desktop) +
     `…-mobile.svg` reproduce the mark; `Attribution.tsx` picks per screen size.
     For strict brand compliance, replace them with the exact official assets
     from the IKanoon API Terms page (same filenames). Never alter,
     disproportionately resize, or partially cover the logo, or imply IKanoon
     endorsement.
2. **Authentication** is via IKanoon's documented scheme (API key / request
   signing). Secure the private key — misuse is the customer's liability, no
   refund. Store it only in `.env` (git-ignored), never in code or the client.
3. **Pre-paid.** Balance exhausted → the API returns nothing. Our pipeline
   already degrades gracefully (empty results + a notice), but monitor balance
   and set the dashboard's balance alert.
4. **AS-IS, no accuracy warranty.** IK sources public records and disclaims
   liability for accuracy/fitness. This is exactly why Nyaya is verify-at-source
   and carries a "research aid, not advice" disclaimer on every response.
5. **Same results for all users**; pricing may change with one week's notice;
   Indian law, Bangalore jurisdiction/arbitration; one month's notice to
   terminate.

---

## 2. Internal vector corpus (our own store)

- **What**: Judgments we have lawfully ingested (via the IK API or public court
  PDFs where permitted), chunked and embedded into pgvector.
- **Why**: Semantic, fact-pattern retrieval that keyword search misses. Also
  reduces upstream calls (cache) and enables offline/enterprise deployments.
- **How**: Background ingestion → chunk → embed (`EMBEDDINGS_PROVIDER`) →
  `judgment_chunks.embedding` (HNSW index) → nearest-neighbour search.
- **Adapter**: `backend/app/services/retrievers/vector.py`.
- **Licensing note**: Only ingest content you are licensed to store. For IK-API
  content, follow their caching/retention terms. For court PDFs, follow the
  court portal's terms.

### Breaking IK-rank dependency: bulk open-dataset ingest

Until now the corpus was ingested *from IK*, so IK effectively ranked every
result. To get cases IK ranks poorly (or lacks, or OCRs badly), bulk-load
**open, freely-licensed judgment datasets** into the same corpus — then results
are ranked by *our* hybrid RRF, not IK's page order.

- **Loader**: `backend/app/services/bulk_ingest.py` — a generic normaliser that
  maps arbitrary dataset columns onto the canonical judgment schema (`id, title,
  citation, court, court_level, date, url, cites, text`). Auto-detects common
  column names; override the odd one with a field map.
- **CLI**: `python -m scripts.bulk_ingest --source <tag> [--sink jsonl|postgres]`
  with one input:
  - `--path <file|dir>` — local `jsonl` / `json` / `csv` / `parquet`, or a
    directory of PDFs with `--format pdf-dir` (official SCR/HC judgment PDFs;
    scanned/image PDFs need OCR first and are skipped with a warning).
  - `--hf-repo <id> --hf-file <path>` — pull a HuggingFace dataset file directly
    (parquet auto-detected). Format is auto-detected from the extension.
  - `--map canonical=source_column` (repeatable) overrides the auto-detected
    column names. Idempotent: de-dupes by id, keeps the richer copy on collision.
- **Extra deps**: format-specific and lazy-imported — `pip install -r
  requirements-ingest.txt` (pandas/pyarrow for parquet, pypdf for PDFs,
  huggingface_hub for `--hf-*`). Not needed by the API/Streamlit runtime.
- **Candidate datasets** (verify each licence before ingesting): HuggingFace
  Indian-law corpora (e.g. ILDC, opennyai judgment sets), the Supreme Court SCR
  portal's official judgment PDFs (§3), and any court open-data export.
- **Effect**: adds coverage + independence with zero orchestrator changes — the
  RRF fusion already treats every source uniformly, so a better case surfaces
  regardless of which source it came from.

---

## 3. Supreme Court of India (direct — pluggable)

- **What**: The **SCR portal** (`scr.sci.gov.in/scrsearch/`) — the free official
  Supreme Court Reports search, formed on **8 May 2025** by merging the older
  **eSCR** and **DigiSCR** portals (which are now decommissioned). Covers
  judgments from 1950 onward with official PDFs and neutral citations; no login.
- **Integration status**: **Adapter stub**. The portal exposes **no documented
  API** — it's a JS front-end over an internal endpoint. Do **not** scrape that
  live; the ToS-preferred path is to download the official judgment PDFs and load
  them through the **bulk ingest** pipeline (§2), which puts SC judgments into our
  own corpus and out of IK's ranking. A live adapter is only worth it for
  same-day freshness, and only if automated access is confirmed permissible.
- **Adapter**: `backend/app/services/retrievers/supreme_court.py`.
- **Value when enabled**: authoritative neutral citations and clean official
  PDFs (not IK OCR).

---

## 4. High Courts / eCourts (direct — pluggable)

- **What**: The eCourts Services platform and individual High Court judgment
  portals publish HC judgments.
- **Integration status**: **Adapter stub**. eCourts has APIs/services in some
  states; availability and terms vary by court. Enable per-court where permitted.
- **Adapter**: `backend/app/services/retrievers/high_court.py`.
- **Caution**: Many portals use CAPTCHAs / session tokens and explicitly limit
  automated access. Respect that. Do not build CAPTCHA-evasion.

---

## 5. Trustworthy secondary sources (optional, Phase 3)

- Bare-act text (India Code — `indiacode.nic.in`) for statute/section context.
- Reputable legal commentary/news for context (linked, never presented as
  authority). Always subordinate to the primary judgment.

---

## Retriever contract

Every source implements one interface so the orchestrator treats them uniformly:

```python
class BaseRetriever(Protocol):
    name: str
    async def search(self, query: RetrievalQuery) -> list[Candidate]: ...
    async def fetch_document(self, doc_id: str) -> JudgmentDoc | None: ...
```

Add a source by dropping in a new adapter that satisfies this contract and
registering it in `services/retrievers/__init__.py`. Enable/disable per
deployment via `ENABLED_RETRIEVERS`.

---

## Rate limiting & politeness

- Per-source concurrency caps and per-source timeouts (default 4s).
- Exponential backoff on 429/5xx; circuit breaker after repeated failures.
- Response and document caching (Redis + Postgres) to avoid duplicate fetches.
- A shared, respectful crawl budget for any HTML source; identify with a proper
  User-Agent and honour `robots.txt`.

---

## Data retention & privacy of user facts

- **User-submitted case facts are confidential.** Stored encrypted, scoped to
  the user/firm, never shared across tenants, never used to train models.
- Judgments (public records) are cached in `judgments` / `judgment_chunks`.
- Enterprise deployments can run with zero-data-retention LLM settings and a
  private corpus in the customer's VPC.

---

## Summary table

| Source | Method | Default | ToS posture | Adapter |
|--------|--------|---------|-------------|---------|
| Indian Kanoon | Licensed API | ✅ on | Compliant (paid API) | `indian_kanoon.py` |
| Internal vector corpus | pgvector | ✅ on | Ingest only licensed content | `vector.py` |
| Supreme Court (eSCR) | Official data / API | ⚙️ opt-in | Prefer official bulk data | `supreme_court.py` |
| High Courts / eCourts | Per-court API/service | ⚙️ opt-in | Varies; enable where permitted | `high_court.py` |
| India Code (statutes) | Public data | ⚙️ opt-in (Phase 3) | Public | — |
