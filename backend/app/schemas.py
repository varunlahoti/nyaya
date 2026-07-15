"""Pydantic schemas (API contract) and internal dataclasses for the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Jurisdiction(str, Enum):
    any = "any"
    supreme_court = "supreme_court"
    high_court = "high_court"


class CourtLevel(str, Enum):
    any = "any"
    trial = "trial"
    high_court = "high_court"
    supreme_court = "supreme_court"


# --------------------------------------------------------------------------- #
# Request / response models (the public API contract)
# --------------------------------------------------------------------------- #
class SearchRequest(BaseModel):
    facts: str = Field(..., min_length=20, max_length=8000,
                       description="Plain-language facts of the case.")
    jurisdiction: str = Field(default="any")
    court_level: CourtLevel = Field(default=CourtLevel.any)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    max_results: int = Field(default=8, ge=5, le=10)
    deep: bool = Field(
        default=False,
        description="Deep mode: fetch full judgment text for top candidates "
                    "before ranking (higher quality, more IK credits).",
    )
    matter_id: Optional[str] = None


class Statute(BaseModel):
    act: str
    sections: List[str] = Field(default_factory=list)


class ParsedFacts(BaseModel):
    summary: str = ""
    legal_issues: List[str] = Field(default_factory=list)
    causes_of_action: List[str] = Field(default_factory=list)
    statutes: List[Statute] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    area_of_law: str = ""
    jurisdiction_hint: str = "any"
    court_level_hint: str = "any"


class JudgmentResult(BaseModel):
    rank: int
    judgment_id: str
    title: str
    citation: Optional[str] = None
    court: Optional[str] = None
    court_level: Optional[str] = None
    date: Optional[str] = None
    source: str
    url: Optional[str] = None
    relevance_score: int = Field(ge=0, le=100)
    relevance_note: str = ""
    holding: str = ""


class SearchResponse(BaseModel):
    search_id: str
    cached: bool = False
    latency_ms: int
    parsed: ParsedFacts
    results: List[JudgmentResult]
    sources_used: List[str]
    partial: bool = False
    notice: Optional[str] = None
    disclaimer: str = (
        "Research aid for qualified professionals. Verify each citation at its "
        "source before relying on it."
    )


# --------------------------------------------------------------------------- #
# Internal pipeline types (not exposed on the wire)
# --------------------------------------------------------------------------- #
@dataclass
class RetrievalQuery:
    """A single query dispatched to one or more retrievers."""
    text: str                       # human/semantic query
    boolean: Optional[str] = None   # source-native boolean/DSL query
    jurisdiction: str = "any"
    court_level: str = "any"
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    limit: int = 15
    tag: str = "general"            # which strategy produced it (issue/statute/…)


@dataclass
class Candidate:
    """A judgment candidate returned by a retriever, before reranking."""
    source: str
    source_doc_id: str
    title: str
    url: Optional[str] = None
    citation: Optional[str] = None
    court: Optional[str] = None
    court_level: Optional[str] = None
    date: Optional[str] = None
    snippet: str = ""
    raw_score: float = 0.0          # source-native score
    prelim_score: float = 0.0       # normalised + blended
    holding: str = ""               # filled if we have the doc cached

    @property
    def dedupe_key(self) -> str:
        if self.citation:
            return _norm(self.citation)
        return f"{self.source}:{self.source_doc_id}"


@dataclass
class JudgmentDoc:
    """A fetched full judgment document."""
    source: str
    source_doc_id: str
    title: str
    url: Optional[str] = None
    citation: Optional[str] = None
    court: Optional[str] = None
    date: Optional[str] = None
    text: str = ""
    metadata: dict = field(default_factory=dict)


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())
