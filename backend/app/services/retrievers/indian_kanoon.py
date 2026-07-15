"""Indian Kanoon retriever — the primary, licensed source.

Integrates with the official Indian Kanoon API (token-based). The API exposes:
  * POST /search/?formInput=<query>&pagenum=<n>   -> search hits
  * POST /doc/<docid>/                            -> document (metadata + text)
  * POST /docmeta/<docid>/                        -> document metadata only

Auth: header `Authorization: Token <API_TOKEN>`.

If no token is configured this retriever reports itself disabled and the
orchestrator simply skips it (returning results from other sources).

Docs / access: https://api.indiankanoon.org/  — respect their ToS and rate
limits. We cache documents to minimise paid calls (see DATA_SOURCES.md).
"""
from __future__ import annotations

import dataclasses
import logging
from typing import List, Optional

import httpx

from ...config import settings
from ...schemas import Candidate, JudgmentDoc, RetrievalQuery
from .. import cache

logger = logging.getLogger("nyaya.retriever.indian_kanoon")

# Case law is stable — cache IK queries/docs for a week to avoid re-spending
# credits on the same query across searches.
IK_CACHE_TTL = 7 * 24 * 3600

# Map our court-level filter to Indian Kanoon `doctypes`.
_DOCTYPE_MAP = {
    "supreme_court": "supremecourt",
    "high_court": "highcourts",
}


class IndianKanoonRetriever:
    name = "indian_kanoon"

    def enabled(self) -> bool:
        return settings.has_indian_kanoon

    def _headers(self) -> dict:
        return {
            "Authorization": f"Token {settings.INDIAN_KANOON_API_TOKEN}",
            "Accept": "application/json",
        }

    def _form_input(self, query: RetrievalQuery) -> str:
        # Prefer the natural-language query — IK's search handles it well and it's
        # much faster than heavy boolean (ORR/quoted) queries.
        parts = [query.text or query.boolean or ""]
        # Court/jurisdiction filter via doctypes. Default to "judgments" so we
        # return case law, not bare-act statute sections.
        doctype = (
            _DOCTYPE_MAP.get(query.court_level)
            or _DOCTYPE_MAP.get(query.jurisdiction)
            or "judgments"
        )
        parts.append(f"doctypes:{doctype}")
        if query.date_from:
            parts.append(f"fromdate:{_ik_date(query.date_from)}")
        if query.date_to:
            parts.append(f"todate:{_ik_date(query.date_to)}")
        return " ".join(parts)

    async def search(self, query: RetrievalQuery) -> List[Candidate]:
        if not self.enabled():
            return []
        form_input = self._form_input(query)

        # Cache: identical IK query within the week → no credit spent.
        ckey = cache.ik_query_key(form_input, query.limit)
        cached = await cache.get_json(ckey)
        if cached is not None:
            return [Candidate(**c) for c in cached]

        url = f"{settings.INDIAN_KANOON_BASE_URL}/search/"
        try:
            async with httpx.AsyncClient(timeout=settings.RETRIEVER_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    url,
                    headers=self._headers(),
                    params={"formInput": form_input, "pagenum": 0},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Indian Kanoon search failed (%s): %s", query.tag, exc)
            return []

        candidates: List[Candidate] = []
        docs = data.get("docs", []) or []
        for i, d in enumerate(docs[: query.limit]):
            docid = str(d.get("tid") or d.get("docid") or "")
            if not docid:
                continue
            candidates.append(Candidate(
                source=self.name,
                source_doc_id=docid,
                title=_clean(d.get("title", "")),
                url=f"https://indiankanoon.org/doc/{docid}/",
                citation=d.get("citation") or None,
                court=d.get("docsource") or None,
                court_level=_infer_level(d.get("docsource", "")),
                date=d.get("publishdate") or d.get("date") or None,
                snippet=_clean(d.get("headline", "")),
                # Rank-based fallback score; blended later.
                raw_score=float(len(docs) - i) / max(len(docs), 1),
                # Authority signal (if IK returns it) → boosts well-cited landmarks.
                cites=int(d.get("numcitedby") or d.get("numcites") or 0),
            ))

        await cache.set_json(
            ckey, [dataclasses.asdict(c) for c in candidates], IK_CACHE_TTL
        )
        return candidates

    async def fetch_document(self, doc_id: str) -> Optional[JudgmentDoc]:
        if not self.enabled():
            return None

        ckey = cache.ik_doc_key(doc_id)
        cached = await cache.get_json(ckey)
        if cached is not None:
            return JudgmentDoc(**cached)

        url = f"{settings.INDIAN_KANOON_BASE_URL}/doc/{doc_id}/"
        try:
            async with httpx.AsyncClient(timeout=settings.RETRIEVER_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, headers=self._headers())
                resp.raise_for_status()
                d = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Indian Kanoon doc fetch failed (%s): %s", doc_id, exc)
            return None
        doc = JudgmentDoc(
            source=self.name,
            source_doc_id=doc_id,
            title=_clean(d.get("title", "")),
            url=f"https://indiankanoon.org/doc/{doc_id}/",
            citation=d.get("citation") or None,
            court=d.get("docsource") or None,
            date=d.get("publishdate") or None,
            text=_clean(d.get("doc", "")),
            metadata={"numcites": d.get("numcites"), "numcitedby": d.get("numcitedby")},
        )
        await cache.set_json(ckey, dataclasses.asdict(doc), IK_CACHE_TTL)
        return doc


def _clean(html: str) -> str:
    """Strip the light HTML Indian Kanoon returns in titles/snippets/docs."""
    import re

    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _ik_date(iso: str) -> str:
    # Indian Kanoon expects DD-MM-YYYY.
    y, m, d = iso.split("-")
    return f"{d}-{m}-{y}"


def _infer_level(docsource: str) -> Optional[str]:
    s = (docsource or "").lower()
    if "supreme court" in s:
        return "supreme_court"
    if "high court" in s:
        return "high_court"
    if s:
        return "trial"
    return None
