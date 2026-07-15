"""Smoke tests that run without any external keys (heuristic fallbacks)."""
from __future__ import annotations

import asyncio

from app.schemas import Candidate, ParsedFacts, SearchRequest
from app.services import query_builder, reranker
from app.services.fact_parser import _heuristic_parse
from app.services.pipeline import SearchPipeline


def test_heuristic_parse_extracts_statute():
    parsed = _heuristic_parse(
        "The tenant defaulted on rent. Landlord issued notice under the "
        "Transfer of Property Act section 106 and seeks eviction."
    )
    acts = [s.act for s in parsed.statutes]
    assert "Transfer of Property Act, 1882" in acts
    assert "106" in parsed.statutes[0].sections


def test_query_builder_produces_queries():
    parsed = ParsedFacts(
        summary="tenancy eviction dispute",
        legal_issues=["validity of s.106 notice"],
        keywords=["eviction", "notice", "tenant"],
    )
    req = SearchRequest(facts="x" * 40)
    queries = query_builder.build(parsed, req)
    assert len(queries) >= 1
    assert any(q.tag == "issue" for q in queries)


def test_fallback_rerank_orders_by_prelim_score():
    cands = [
        Candidate(source="indian_kanoon", source_doc_id="1", title="A", prelim_score=0.2),
        Candidate(source="indian_kanoon", source_doc_id="2", title="B", prelim_score=0.9),
    ]
    results = reranker._fallback_rerank(cands, max_results=5)
    assert results[0].title == "B"
    assert results[0].rank == 1


def test_pipeline_runs_without_sources():
    req = SearchRequest(facts="A landlord seeks eviction for rent arrears " * 3)
    resp = asyncio.run(SearchPipeline(db=None).run(req))
    assert resp.search_id.startswith("s_")
    # No sources configured in the test env → empty results + a notice.
    assert resp.results == [] or isinstance(resp.results, list)
    assert resp.disclaimer
