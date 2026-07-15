"""Health / readiness endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..config import settings
from ..services.retrievers import build_retrievers

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    # Reflect the live pipeline's corpus backend, not a throwaway one.
    from .search import pipeline

    active = {r.name for r in build_retrievers(db=pipeline.db)}
    return {
        "status": "ok",
        "version": __version__,
        "llm": "configured" if settings.has_llm else "not_configured",
        "sources": {
            "indian_kanoon": "up" if "indian_kanoon" in active else "off",
            "vector": "up" if "vector" in active else "off",
            "supreme_court": "up" if "supreme_court" in active else "off",
            "high_court": "up" if "high_court" in active else "off",
        },
    }
