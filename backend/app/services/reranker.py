"""Step 5 of the pipeline: rerank the candidate set against the specific facts.

Anti-hallucination guarantee: the model is given a *closed list* of real,
retrieved candidates and must reference them by `id`. It never emits a free-text
case name. The server maps returned ids back to fetched documents and drops any
id not in the set. If the LLM is unavailable, we fall back to the preliminary
retrieval score so the pipeline still returns source-backed results.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..schemas import Candidate, JudgmentResult, ParsedFacts
from . import llm

logger = logging.getLogger("nyaya.reranker")

SYSTEM_PROMPT = """You are a senior Indian advocate selecting the most relevant \
precedents for a matter. You are given the facts, the legal issues, and a \
numbered list of REAL candidate judgments retrieved from Indian legal databases \
(title, court, date, and a snippet each).

Your task:
1. Judge each candidate's relevance to THESE specific facts and issues, 0-100. \
Reward genuinely on-point authority (same legal issue, similar fact pattern). \
Penalise superficial keyword overlap. When two judgments are similarly on-point, \
PREFER the one from the higher / binding court (Supreme Court over High Court \
over trial court / tribunal) — binding precedent outranks merely persuasive.
2. Select the best ones (up to the requested count).
3. For each selected judgment, write:
   - relevance_note: ONE sentence on why it matters to THIS matter.
   - holding: 1-2 sentences stating the ratio / what the court held, based only \
on the snippet provided. If the snippet is insufficient, say what the case \
appears to address without inventing specifics.

CRITICAL RULES:
- You may ONLY reference candidates from the provided list, by their integer id.
- NEVER invent a case name, citation, or holding that is not supported by a \
provided candidate. It is better to return fewer results than to fabricate.
- Order results best-first."""

SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "relevance_score": {"type": "integer"},
                    "relevance_note": {"type": "string"},
                    "holding": {"type": "string"},
                },
                "required": ["id", "relevance_score", "relevance_note", "holding"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


async def rerank(
    facts: str,
    parsed: ParsedFacts,
    candidates: List[Candidate],
    max_results: int,
) -> List[JudgmentResult]:
    if not candidates:
        return []

    if llm.available():
        try:
            return await _llm_rerank(facts, parsed, candidates, max_results)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM rerank failed, using prelim score: %s", exc)

    return _fallback_rerank(candidates, max_results)


async def _llm_rerank(
    facts: str,
    parsed: ParsedFacts,
    candidates: List[Candidate],
    max_results: int,
) -> List[JudgmentResult]:
    lines = []
    for i, c in enumerate(candidates):
        lines.append(
            f"[{i}] {c.title}\n"
            f"    Court: {c.court or 'unknown'} | Date: {c.date or 'unknown'}"
            f" | Citation: {c.citation or 'n/a'}\n"
            f"    Snippet: {c.snippet[:500] or '(no snippet)'}"
        )
    issues = "\n".join(f"- {x}" for x in parsed.legal_issues) or "(not extracted)"
    user = (
        f"FACTS:\n{facts}\n\n"
        f"LEGAL ISSUES:\n{issues}\n\n"
        f"CANDIDATE JUDGMENTS:\n" + "\n\n".join(lines) + "\n\n"
        f"Select up to {max_results} best-matching judgments."
    )

    data = await llm.complete_json(
        system=SYSTEM_PROMPT,
        user=user,
        schema=SCHEMA,
        use_thinking=True,   # reranking is a judgement task — let Claude reason
        effort="high",
    )

    from ..config import settings

    results: List[JudgmentResult] = []
    for item in data.get("results", []):
        idx = item.get("id")
        if idx is None or not (0 <= idx < len(candidates)):
            continue  # drop any id not in the closed set (anti-hallucination)
        score = _clamp(item.get("relevance_score", 0))
        # Drop clearly off-point candidates rather than showing a "score 0, this
        # case does not address the issue" card. If NOTHING clears the bar the
        # pipeline surfaces a "no strong match" notice instead of noise.
        if score < settings.RERANK_MIN_SCORE:
            continue
        c = candidates[idx]
        results.append(_to_result(
            0, c,
            score=score,
            note=item.get("relevance_note", ""),
            holding=item.get("holding", ""),
        ))
    # Sort by score (best-first) and assign display ranks.
    results.sort(key=lambda r: r.relevance_score, reverse=True)
    out = results[:max_results]
    for rank, r in enumerate(out, start=1):
        r.rank = rank
    return out


def _fallback_rerank(candidates: List[Candidate], max_results: int) -> List[JudgmentResult]:
    ranked = sorted(candidates, key=lambda c: c.prelim_score, reverse=True)[:max_results]
    return [
        _to_result(
            i + 1, c,
            score=int(min(100, round(c.prelim_score * 100))),
            note="Matched by keyword/semantic retrieval (LLM ranking unavailable).",
            holding=c.holding or c.snippet[:200],
        )
        for i, c in enumerate(ranked)
    ]


def _to_result(rank: int, c: Candidate, *, score: int, note: str, holding: str) -> JudgmentResult:
    return JudgmentResult(
        rank=rank,
        judgment_id=f"j_{c.source}_{c.source_doc_id}",
        title=c.title,
        citation=c.citation,
        court=c.court,
        court_level=c.court_level,
        date=c.date,
        source=c.source,
        url=c.url,
        relevance_score=score,
        relevance_note=note,
        holding=holding,
    )


def _clamp(v: int) -> int:
    return max(0, min(100, int(v)))
