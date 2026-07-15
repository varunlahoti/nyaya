"""Step 1 of the pipeline: turn plain-language facts into structured legal issues.

Uses Claude (structured outputs) when available; falls back to a lightweight
heuristic extractor so the pipeline still runs without an API key.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict

from ..schemas import ParsedFacts, Statute
from . import llm

logger = logging.getLogger("nyaya.fact_parser")

SYSTEM_PROMPT = """You are a senior Indian litigation advocate with 25 years at \
the Bar. A junior hands you the facts of a matter. Your job is to spot the legal \
issues the way a seasoned lawyer does before researching precedent.

Read the facts and produce:
- A neutral one-paragraph restatement of the dispute.
- The precise legal issues (frame them as a court would, e.g. "whether a notice \
under section 106 of the Transfer of Property Act, 1882 is mandatory for \
eviction under a State Rent Act").
- The causes of action.
- The statutes and specific sections engaged — infer sections even when the \
facts only imply them (e.g. a "defective quit notice" implies s.106 TPA).
- Search keywords a lawyer would actually use on a case-law database.
- The area of law, and hints on jurisdiction and court level if the facts \
suggest them.

Be precise and use correct Indian statute names and section numbers. Do not \
invent case citations — you are only analysing the facts, not citing precedent."""

# JSON schema for structured outputs.
SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "legal_issues": {"type": "array", "items": {"type": "string"}},
        "causes_of_action": {"type": "array", "items": {"type": "string"}},
        "statutes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "act": {"type": "string"},
                    "sections": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["act", "sections"],
                "additionalProperties": False,
            },
        },
        "keywords": {"type": "array", "items": {"type": "string"}},
        "area_of_law": {"type": "string"},
        "jurisdiction_hint": {"type": "string"},
        "court_level_hint": {"type": "string"},
    },
    "required": [
        "summary", "legal_issues", "causes_of_action", "statutes",
        "keywords", "area_of_law", "jurisdiction_hint", "court_level_hint",
    ],
    "additionalProperties": False,
}


async def parse(facts: str) -> ParsedFacts:
    if llm.available():
        try:
            data = await llm.complete_json(
                system=SYSTEM_PROMPT,
                user=f"Facts of the matter:\n\n{facts}",
                schema=SCHEMA,
                model=llm.settings.parser_model,
                use_thinking=False,
            )
            return ParsedFacts(
                summary=data.get("summary", ""),
                legal_issues=data.get("legal_issues", []),
                causes_of_action=data.get("causes_of_action", []),
                statutes=[Statute(**s) for s in data.get("statutes", [])],
                keywords=data.get("keywords", []),
                area_of_law=data.get("area_of_law", ""),
                jurisdiction_hint=data.get("jurisdiction_hint", "any"),
                court_level_hint=data.get("court_level_hint", "any"),
            )
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            logger.warning("LLM fact parse failed, using heuristic: %s", exc)

    return _heuristic_parse(facts)


# --------------------------------------------------------------------------- #
# Heuristic fallback (no LLM). Coarse but keeps the pipeline alive for demos.
# --------------------------------------------------------------------------- #
_ACT_PATTERNS = [
    (r"transfer of property", "Transfer of Property Act, 1882"),
    (r"\bipc\b|penal code", "Indian Penal Code, 1860"),
    (r"\bcrpc\b|code of criminal procedure", "Code of Criminal Procedure, 1973"),
    (r"\bcpc\b|code of civil procedure", "Code of Civil Procedure, 1908"),
    (r"contract act", "Indian Contract Act, 1872"),
    (r"negotiable instrument|cheque|section 138", "Negotiable Instruments Act, 1881"),
    (r"hindu marriage", "Hindu Marriage Act, 1955"),
    (r"consumer protection", "Consumer Protection Act, 2019"),
    (r"arbitration", "Arbitration and Conciliation Act, 1996"),
    (r"companies act", "Companies Act, 2013"),
    (r"income tax", "Income Tax Act, 1961"),
    (r"specific relief", "Specific Relief Act, 1963"),
    (r"motor vehicle", "Motor Vehicles Act, 1988"),
]

_STOPWORDS = set(
    "the a an and or of to in on for with by is are was were that this his her "
    "he she it they them their as at from be been being has have had not no now "
    "under seeks claims claim case matter facts".split()
)


def _heuristic_parse(facts: str) -> ParsedFacts:
    low = facts.lower()
    statutes = []
    for pat, name in _ACT_PATTERNS:
        if re.search(pat, low):
            secs = re.findall(r"section\s+(\d+[A-Za-z\-]*)", low)
            statutes.append(Statute(act=name, sections=sorted(set(secs))))

    words = re.findall(r"[a-zA-Z]{4,}", low)
    freq: Dict[str, int] = {}
    for w in words:
        if w not in _STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    keywords = [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:8]]

    return ParsedFacts(
        summary=facts.strip()[:300] + ("…" if len(facts) > 300 else ""),
        legal_issues=[],
        causes_of_action=[],
        statutes=statutes,
        keywords=keywords,
        area_of_law=statutes[0].act if statutes else "General",
        jurisdiction_hint="any",
        court_level_hint="any",
    )
