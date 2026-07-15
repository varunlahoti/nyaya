"""Retriever registry.

Add a new source by dropping in an adapter that satisfies BaseRetriever and
registering it here. Enable/disable per deployment via ENABLED_RETRIEVERS.
"""
from __future__ import annotations

from typing import List

from ...config import settings
from .base import BaseRetriever
from .high_court import HighCourtRetriever
from .indian_kanoon import IndianKanoonRetriever
from .supreme_court import SupremeCourtRetriever
from .vector import VectorRetriever

__all__ = ["BaseRetriever", "build_retrievers"]


def build_retrievers(db=None) -> List[BaseRetriever]:
    """Instantiate the enabled + configured retrievers."""
    registry = {
        "indian_kanoon": IndianKanoonRetriever(),
        "vector": VectorRetriever(db=db),
        "supreme_court": SupremeCourtRetriever(),
        "high_court": HighCourtRetriever(),
    }
    active: List[BaseRetriever] = []
    for name in settings.ENABLED_RETRIEVERS:
        r = registry.get(name)
        if r is not None and r.enabled():
            active.append(r)
    return active
