"""The retrieval orchestrator — ties the five steps together.

facts → parse → build queries → fan-out retrieve → merge/dedupe → rerank → results
"""
from __future__ import annotations

import asyncio
import logging
import math
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

# Identical-search cache TTL — repeat facts return the same frozen result,
# instantly, 0 credits. Configurable (default 30 days) for reproducibility.
SEARCH_CACHE_TTL = settings.SEARCH_CACHE_TTL_HOURS * 3600

# Trust weights per source, used when blending scores across retrievers.
SOURCE_WEIGHTS = {
    "indian_kanoon": 1.0,
    "supreme_court": 1.05,
    "high_court": 1.0,
    "vector": 0.95,   # semantic (own corpus)
    "bm25": 0.9,      # lexical (own corpus)
}

# Court-authority weights — a GENTLE nudge only. Kept small on purpose: an
# aggressive SC boost buries on-point High Court cases under famous-but-off-topic
# Supreme Court landmarks. Relevance (RRF rank) should lead; the reranker makes
# the final authority call (prefer binding court when genuinely on-point).
COURT_WEIGHTS = {
    "supreme_court": 1.05,
    "high_court": 1.0,
    "trial": 0.97,
    None: 1.0,
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

        # Keep the ranked lists intact (one per successful retriever×query) — RRF
        # fuses by rank, so it needs the per-list ordering, not a flat bag.
        ranked_lists: List[List[Candidate]] = []
        for res in results_nested:
            if isinstance(res, Exception):
                partial = True
                continue
            if res:
                ranked_lists.append(res)

        # 4. Fuse across sources/queries, blend court authority + citations, cap.
        candidates = self._fuse(ranked_lists)
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

        # Candidates existed but none cleared the relevance bar → tell the user
        # rather than returning a bare empty list (or, worse, score-0 noise).
        if not results:
            return self._empty_response(
                search_id, parsed, t0, sources_used=sources_used, partial=partial,
                notice=("Found related cases but none squarely on-point. Try adding "
                        "more specific facts, the statute/section, or party details "
                        "(e.g. 'section 498A IPC cruelty by husband')."),
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
    def _fuse(self, ranked_lists: List[List[Candidate]]) -> List[Candidate]:
        """Combine the per-retriever ranked lists into one ordered candidate set.

        `rrf` (default) = Reciprocal Rank Fusion: robust across sources whose raw
        scores live on different scales (IK rank vs cosine similarity vs BM25),
        and it naturally rewards a judgment that surfaces in several lists
        (corroboration). `weighted` keeps the older score-normalisation blend.
        """
        if settings.FUSION_METHOD == "weighted":
            flat = [c for lst in ranked_lists for c in lst]
            return self._merge_and_dedupe(flat)
        return self._fuse_rrf(ranked_lists)

    def _fuse_rrf(self, ranked_lists: List[List[Candidate]]) -> List[Candidate]:
        k = settings.RRF_K
        fused: Dict[str, float] = {}
        best: Dict[str, Candidate] = {}
        srcs: Dict[str, set] = {}

        for lst in ranked_lists:
            # Retrievers return best-first; re-sort defensively before ranking.
            ordered = sorted(lst, key=lambda c: c.raw_score, reverse=True)
            for rank, c in enumerate(ordered):
                key = c.dedupe_key
                w = SOURCE_WEIGHTS.get(c.source, 1.0)
                fused[key] = fused.get(key, 0.0) + w / (k + rank)
                srcs.setdefault(key, set()).add(c.source)
                # Keep the representative with the richest snippet / metadata.
                cur = best.get(key)
                if cur is None or _richness(c) > _richness(cur):
                    best[key] = c

        out: List[Candidate] = []
        for key, c in best.items():
            cw = COURT_WEIGHTS.get(c.court_level, COURT_WEIGHTS[None])
            cite_boost = 1 + min(0.06, 0.02 * math.log10(1 + c.cites)) if c.cites else 1.0
            # Cross-source agreement (both lexical AND semantic AND IK) is a strong
            # signal — nudge multi-source hits up beyond their summed RRF score.
            agree_boost = 1 + 0.05 * (len(srcs[key]) - 1)
            c.prelim_score = fused[key] * cw * cite_boost * agree_boost
            out.append(c)

        return sorted(out, key=lambda c: c.prelim_score, reverse=True)

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
                # Blend source trust with court authority (binding > persuasive)
                # and a gentle citation-count boost (well-cited = more authoritative).
                cw = COURT_WEIGHTS.get(c.court_level, COURT_WEIGHTS[None])
                cite_boost = 1 + min(0.06, 0.02 * math.log10(1 + c.cites)) if c.cites else 1.0
                c.prelim_score = norm * w * cw * cite_boost

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


def _richness(c: Candidate) -> tuple:
    """Prefer the representative with a citation and the longest snippet."""
    return (bool(c.citation), len(c.snippet or ""), c.cites)
