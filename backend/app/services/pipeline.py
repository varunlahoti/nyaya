"""The retrieval orchestrator — ties the five steps together.

facts → parse → build queries → fan-out retrieve → merge/dedupe → rerank → results
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Dict, List

from ..config import settings
from ..schemas import (
    Candidate,
    JudgmentResult,
    ParsedFacts,
    SearchRequest,
    SearchResponse,
)
from . import cache, fact_parser, query_builder, reranker
from .retrievers import build_retrievers

logger = logging.getLogger("nyaya.pipeline")

# Identical-search cache TTL (24h). Repeat facts return instantly, 0 credits.
SEARCH_CACHE_TTL = 24 * 3600

# Trust weights per source, used when blending scores across retrievers.
SOURCE_WEIGHTS = {
    "indian_kanoon": 1.0,
    "supreme_court": 1.05,
    "high_court": 1.0,
    "vector": 0.9,
}

# Court-authority weights — binding precedent ranks above persuasive. Nudges
# Supreme Court authority up so landmarks aren't buried under High Court hits.
COURT_WEIGHTS = {
    "supreme_court": 1.15,
    "high_court": 1.0,
    "trial": 0.9,
    None: 0.95,
}


class SearchPipeline:
    def __init__(self, db=None):
        self.db = db

    async def run(self, req: SearchRequest) -> SearchResponse:
        t0 = time.perf_counter()
        search_id = "s_" + uuid.uuid4().hex[:10]

        # 0. Serve identical prior searches from cache (0 credits, 0 LLM).
        ckey = cache.search_key(
            req.facts, req.jurisdiction,
            req.court_level.value if hasattr(req.court_level, "value") else str(req.court_level),
            req.max_results,
            req.date_from.isoformat() if req.date_from else None,
            req.date_to.isoformat() if req.date_to else None,
        )
        hit = await cache.get_json(ckey)
        if hit:
            hit["cached"] = True
            hit["search_id"] = search_id
            hit["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            logger.info("search cache HIT %s", ckey)
            return SearchResponse(**hit)

        # 1. Parse facts into legal issues.
        parsed = await fact_parser.parse(req.facts)

        # 2. Build targeted queries.
        queries = query_builder.build(parsed, req)

        # 3. Fan out to all enabled retrievers, all queries, concurrently.
        retrievers = build_retrievers(db=self.db)
        sources_used = [r.name for r in retrievers]
        partial = False

        if not retrievers:
            return self._empty_response(
                search_id, parsed, t0,
                notice=("No retrieval sources are configured. Set "
                        "INDIAN_KANOON_API_TOKEN (and/or enable the vector "
                        "corpus) to get results."),
            )

        tasks = [r.search(q) for r in retrievers for q in queries]
        try:
            results_nested = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:  # noqa: BLE001
            logger.error("Retrieval fan-out error: %s", exc)
            results_nested = []

        all_candidates: List[Candidate] = []
        for res in results_nested:
            if isinstance(res, Exception):
                partial = True
                continue
            all_candidates.extend(res)

        # 4. Merge, dedupe, blend scores (incl. court authority), cap.
        candidates = self._merge_and_dedupe(all_candidates)
        candidates = candidates[: settings.CANDIDATE_CAP]

        if not candidates:
            return self._empty_response(
                search_id, parsed, t0, sources_used=sources_used, partial=partial,
                notice=("No source-backed judgments matched. Try adding more "
                        "detail to the facts, or broaden the jurisdiction."),
            )

        # 4b. Deep mode: fetch full judgment text for the top candidates so the
        # reranker judges on real text, not headline snippets.
        if req.deep:
            await self._enrich_full_text(candidates, retrievers)

        # 5. Rerank the closed candidate set against the facts.
        results: List[JudgmentResult] = await reranker.rerank(
            req.facts, parsed, candidates, req.max_results
        )

        latency_ms = int((time.perf_counter() - t0) * 1000)
        response = SearchResponse(
            search_id=search_id,
            cached=False,
            latency_ms=latency_ms,
            parsed=parsed,
            results=results,
            sources_used=sources_used,
            partial=partial,
        )

        # Cache the completed search (skip partial results — they may improve).
        if results and not partial:
            await cache.set_json(ckey, response.model_dump(mode="json"), SEARCH_CACHE_TTL)

        return response

    # ------------------------------------------------------------------ #
    def _merge_and_dedupe(self, candidates: List[Candidate]) -> List[Candidate]:
        # Normalise raw scores per source, then blend with source trust weight.
        by_source: Dict[str, List[Candidate]] = {}
        for c in candidates:
            by_source.setdefault(c.source, []).append(c)

        for source, group in by_source.items():
            scores = [c.raw_score for c in group] or [0.0]
            lo, hi = min(scores), max(scores)
            span = (hi - lo) or 1.0
            w = SOURCE_WEIGHTS.get(source, 1.0)
            for c in group:
                norm = (c.raw_score - lo) / span
                # Blend source trust with court authority (binding > persuasive).
                cw = COURT_WEIGHTS.get(c.court_level, COURT_WEIGHTS[None])
                c.prelim_score = norm * w * cw

        # Dedupe: keep the highest prelim_score per dedupe key; if a judgment
        # appears from multiple queries/sources, boost it slightly (corroboration).
        best: Dict[str, Candidate] = {}
        hits: Dict[str, int] = {}
        for c in candidates:
            k = c.dedupe_key
            hits[k] = hits.get(k, 0) + 1
            if k not in best or c.prelim_score > best[k].prelim_score:
                best[k] = c
        for k, c in best.items():
            if hits[k] > 1:
                c.prelim_score = min(1.0, c.prelim_score * (1 + 0.08 * (hits[k] - 1)))

        return sorted(best.values(), key=lambda c: c.prelim_score, reverse=True)

    async def _enrich_full_text(self, candidates: List[Candidate], retrievers) -> None:
        """Fetch full judgment text for the top-N candidates (deep mode).

        Replaces the short headline snippet with a truncated slice of the real
        judgment so the reranker judges + writes holdings on actual text. Docs
        are cached (7d), so this cost is paid once per judgment.
        """
        by_name = {r.name: r for r in retrievers}
        top = candidates[: settings.DEEP_FETCH_TOP_N]

        async def fetch(c: Candidate):
            r = by_name.get(c.source)
            if r is None:
                return
            doc = await r.fetch_document(c.source_doc_id)
            if doc and doc.text:
                c.snippet = doc.text[: settings.DEEP_FETCH_CHARS]
                if doc.citation and not c.citation:
                    c.citation = doc.citation

        await asyncio.gather(*(fetch(c) for c in top), return_exceptions=True)

    def _empty_response(
        self, search_id, parsed: ParsedFacts, t0, *,
        sources_used=None, partial=False, notice=None,
    ) -> SearchResponse:
        return SearchResponse(
            search_id=search_id,
            cached=False,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            parsed=parsed,
            results=[],
            sources_used=sources_used or [],
            partial=partial,
            notice=notice,
        )
