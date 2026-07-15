# Product Overview — Nyaya

## 1. The problem

An advocate preparing a matter needs precedent. Today the workflow is:

1. Read the brief, identify the legal issues.
2. Open Indian Kanoon / SCC Online / Manupatra / court websites.
3. Guess keywords, run many searches, open dozens of judgments.
4. Skim each to decide whether it's on point.
5. Note citations, copy source links, repeat for every issue.

This takes **2–6 hours per matter** for a junior, and it's the single most
time-consuming, least-leveraged part of litigation prep. Paid databases
(SCC Online, Manupatra) are expensive (₹25k–₹1L+/year per seat) and still
require the same manual keyword-guessing.

## 2. The product

A single text box. The advocate pastes or types the **facts of the case in plain
language**. Nyaya returns **5–10 judgments** most relevant to those facts, each
with:

- Case title and neutral/reporter citation
- Court and year
- **Direct source link** (Indian Kanoon doc, or court PDF)
- A one-line **relevance note**: *why this case matters to these facts*
- The **holding / ratio** in 1–2 sentences
- Key statutes/sections the case turns on

The advocate scans 10 lines instead of 50 PDFs, clicks through to verify, and
gets to drafting.

### What makes it "senior-lawyer-like"

Nyaya doesn't keyword-match. It runs the same reasoning a senior does:

- **Issue-spotting**: extracts the legal issues, causes of action, statutes,
  and the specific sections in play — not just nouns from the text.
- **Query strategy**: builds several targeted searches (by statute, by issue,
  by fact-pattern) rather than one naive query.
- **Relevance judgement**: re-reads the candidate judgments against *these*
  facts and ranks by genuine on-point-ness, discounting superficial keyword hits.

## 3. Target users

| Segment | Need | Willingness to pay |
|--------|------|-------------------|
| Individual advocates / juniors | Fast precedent for daily matters | ₹500–2,000/mo |
| Small & mid law firms (2–20) | Team seats, shared history, matters | ₹1,500–5,000/seat/mo |
| Litigation boutiques | Deep search, brief-drafting assist | ₹5,000+/seat/mo |
| Legal researchers / academics | Corpus search, citation graphs | Institutional |
| Law students / interns | Learning, moot prep | Freemium / student tier |

Primary beachhead: **individual advocates and juniors in trial and High Courts**
who can't justify SCC Online but lose hours to manual search.

## 4. Monetisation

### Pricing tiers

| Tier | Price (₹/mo) | Searches | Features |
|------|-------------|----------|----------|
| **Free** | 0 | 5 / day | Core search, source links |
| **Advocate** | 799 | 100 / day | + saved searches, matters, export to PDF/Word, citation copy |
| **Firm** | 1,499 / seat | Unlimited* | + shared workspace, team history, roles, priority queue |
| **Enterprise** | Custom | Unlimited | + API access, SSO, on-prem/VPC, custom corpora, SLA |

\* fair-use cap.

### Revenue levers

- **Seat-based SaaS** (primary): monthly/annual per-seat subscriptions.
- **Usage add-ons**: bulk "deep research" runs, brief-drafting assist.
- **API access**: expose the search API to legal-tech partners / DMS vendors
  (billed per call).
- **Enterprise/VPC**: firms that need data isolation pay a premium.

### Unit economics (rough)

- Cost per search ≈ retrieval (cheap, cached) + one LLM extract + one LLM rerank.
  With Claude on a small candidate set and prompt caching on the system prompt,
  target **₹3–8 per search**.
- Advocate tier at ₹799 with ~40 searches/mo → **>85% gross margin** after infra.
- Free tier is capped to keep CAC-funded acquisition sustainable.

## 5. Trust, accuracy & positioning

The single biggest risk in legal AI is a **hallucinated citation**. Nyaya's
architecture forbids it: a judgment is surfaced **only if a real, fetched source
document backs it**. The LLM ranks and explains real documents; it never
free-generates a case name. Every card links to the source so the advocate
verifies in one click. See the anti-hallucination section of the system design.

Positioning: **"A research associate that never sleeps"** — not a replacement for
the advocate's judgement, an accelerator for it.

## 6. Competitive landscape

| Competitor | What they do | Where Nyaya wins |
|-----------|--------------|------------------|
| Indian Kanoon | Free full-text search | Nyaya does issue-spotting + ranking + "why", not raw search |
| SCC Online / Manupatra | Paid databases, headnotes | Far cheaper; plain-facts input; AI relevance |
| Manupatra / CaseMine | Some AI ("citation graph") | Facts-to-precedent flow, PWA, price |
| Generic LLM chatbots | Answer questions | **Won't hallucinate citations**; source-linked; India-tuned |

## 7. Roadmap

**Phase 1 — MVP (this repo)**
Facts → 5–10 judgments with source links & relevance notes. Indian Kanoon
retriever + internal vector corpus. Web + PWA. Auth, quotas, billing hooks.

**Phase 2 — Advocate workflow**
Saved matters, search history, export to Word/PDF, citation formatting
(SC/HC neutral citations), "copy as brief snippet".

**Phase 3 — Depth**
Direct SC/HC connectors, statute & section browser, "distinguish/followed"
signals, citation graph, headnote generation.

**Phase 4 — Assist**
Draft a precedent-backed argument paragraph. Compare two lines of authority.
Alert on new judgments touching a saved matter.

**Phase 5 — Platform**
Public API, DMS integrations, firm analytics, regional-language facts input.

## 8. Key risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Hallucinated citations | Source-backed-only architecture; verify links |
| Source ToS / rate limits | Licensed Indian Kanoon API; caching; polite crawling; see DATA_SOURCES |
| Accuracy of relevance | Human-in-loop (advocate verifies); feedback loop to tune |
| Data privacy of case facts | Encryption at rest/in transit; no training on client facts; per-firm isolation option |
| LLM cost at scale | Small candidate sets, prompt caching, tiered model routing |
| Professional-liability perception | Clear "research aid, not advice" framing; verification-first UX |
