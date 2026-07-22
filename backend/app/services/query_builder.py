"""Step 2 of the pipeline: turn parsed facts into targeted retrieval queries.

Emits several complementary queries rather than one naive search:
  * one per legal issue (semantic),
  * one per statute/section (boolean, source-native),
  * a broad fact-pattern query for semantic/vector retrieval.

Indian Kanoon boolean DSL is used for the `boolean` field where helpful:
  phrase quoting "...", ANDD / ORR, doctypes:, fromdate:/todate:.
"""
from __future__ import annotations

from typing import List, Optional

from ..config import settings
from ..schemas import ParsedFacts, RetrievalQuery, SearchRequest


def build(parsed: ParsedFacts, req: SearchRequest) -> List[RetrievalQuery]:
    queries: List[RetrievalQuery] = []
    jur = req.jurisdiction or "any"
    lvl = req.court_level.value if hasattr(req.court_level, "value") else str(req.court_level)
    dfrom = req.date_from.isoformat() if req.date_from else None
    dto = req.date_to.isoformat() if req.date_to else None

    # 1. Keyword queries FIRST — short, keyword-dense. Indian Kanoon and BM25 are
    # lexical: they return real on-point cases for "section 498A dowry cruelty"
    # but famous unrelated landmarks for a 40-word essay question. Keywords also
    # work well for the vector retriever, so these lead and survive the cap.
    for kw in parsed.keywords[:4]:
        queries.append(RetrievalQuery(
            text=kw,
            jurisdiction=jur, court_level=lvl,
            date_from=dfrom, date_to=dto,
            limit=settings.PER_RETRIEVER_LIMIT, tag="keyword",
        ))

    # 2. One query per legal issue — but CONDENSED to salient terms for retrieval
    # (the full verbose issue text dilutes keyword search).
    for issue in parsed.legal_issues[:3]:
        queries.append(RetrievalQuery(
            text=_condense(issue),
            boolean=_phrase_boolean(issue),
            jurisdiction=jur, court_level=lvl,
            date_from=dfrom, date_to=dto,
            limit=settings.PER_RETRIEVER_LIMIT, tag="issue",
        ))

    # 3. One query per statute/section (boolean, precise).
    for st in parsed.statutes[:3]:
        act_phrase = f'"{st.act.split(",")[0]}"'
        if st.sections:
            for sec in st.sections[:3]:
                queries.append(RetrievalQuery(
                    text=f"{st.act} section {sec}",
                    boolean=f'{act_phrase} ANDD "section {sec}"',
                    jurisdiction=jur, court_level=lvl,
                    date_from=dfrom, date_to=dto,
                    limit=settings.PER_RETRIEVER_LIMIT, tag="statute",
                ))
        else:
            queries.append(RetrievalQuery(
                text=st.act,
                boolean=act_phrase,
                jurisdiction=jur, court_level=lvl,
                date_from=dfrom, date_to=dto,
                limit=settings.PER_RETRIEVER_LIMIT, tag="statute",
            ))

    # 3. Broad fact-pattern query (great for vector/semantic retrieval).
    fact_query = parsed.summary or " ".join(parsed.keywords)
    if fact_query:
        queries.append(RetrievalQuery(
            text=fact_query,
            boolean=_keywords_boolean(parsed.keywords),
            jurisdiction=jur, court_level=lvl,
            date_from=dfrom, date_to=dto,
            limit=settings.PER_RETRIEVER_LIMIT, tag="fact_pattern",
        ))

    # De-duplicate identical query texts.
    seen = set()
    unique: List[RetrievalQuery] = []
    for q in queries:
        key = (q.text.strip().lower(), q.tag)
        if key not in seen and q.text.strip():
            seen.add(key)
            unique.append(q)

    # Cap total queries to control Indian Kanoon credit burn (each query ≈ 1
    # credit). Ordering keeps issue queries first, so the cap drops the least
    # important (extra statute/fact-pattern) queries.
    capped = unique[: settings.MAX_QUERIES_PER_SEARCH]

    # Supreme Court priority: add one SC-scoped query (over the cap) so binding
    # authority surfaces even when the user searches "any" court. This fixes the
    # common miss where landmark SC precedent is buried under High Court hits.
    if settings.SC_PRIORITY_QUERY and lvl == "any":
        primary = parsed.legal_issues[0] if parsed.legal_issues else (parsed.summary or fact_query)
        if primary:
            capped.append(RetrievalQuery(
                text=primary,
                jurisdiction="supreme_court", court_level="supreme_court",
                date_from=dfrom, date_to=dto,
                limit=settings.PER_RETRIEVER_LIMIT, tag="supreme_court",
            ))
    return capped


# Filler words that dilute a keyword search — dropped when condensing a verbose
# legal issue into a retrieval query.
_FILLER = {
    "whether", "the", "a", "an", "of", "under", "can", "be", "is", "are", "and",
    "or", "to", "in", "on", "for", "with", "as", "by", "from", "same", "based",
    "specifically", "concurrently", "simultaneously", "constitute", "against",
    "person", "case", "matter", "any", "such", "these", "this", "that", "which",
    "commission", "maintained", "initiated", "available", "sought", "conjunction",
}


def _condense(issue: str, max_terms: int = 12) -> str:
    """Verbose legal issue → short keyword query (drop filler, keep legal terms).

    'Whether the commission of an offence under the Dowry Prohibition Act, 1961,
    ... can concurrently constitute domestic violence' -> 'offence Dowry
    Prohibition Act 1961 domestic violence'. Keeps section numbers + Act names.
    """
    import re

    out, seen = [], set()
    for raw in re.split(r"[\s,;.]+", issue):
        w = raw.strip()
        if not w:
            continue
        key = w.lower()
        if key in _FILLER or (len(w) <= 2 and not w.isdigit()):
            continue
        if key not in seen:
            seen.add(key)
            out.append(w)
        if len(out) >= max_terms:
            break
    return " ".join(out) or issue[:80]


def _phrase_boolean(issue: str) -> Optional[str]:
    """Extract a couple of salient noun-phrases for a boolean query."""
    words = [w for w in issue.split() if len(w) > 3][:6]
    if not words:
        return None
    return " ".join(words)


def _keywords_boolean(keywords: List[str]) -> Optional[str]:
    if not keywords:
        return None
    top = keywords[:5]
    return " ORR ".join(f'"{k}"' for k in top)
