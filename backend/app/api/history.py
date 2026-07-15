"""Search history + saved-search endpoints (authenticated)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..db import crud
from ..db.session import get_db_optional
from ..deps import CurrentUser, get_current_user

router = APIRouter(prefix="/history", tags=["history"])


@router.get("")
async def history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db_optional),
):
    if db is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "History requires a database.")
    searches = await crud.list_searches(db, user.id, limit=limit, offset=offset)
    return [
        {
            "id": s.id,
            "facts": s.facts_text[:200],
            "jurisdiction": s.jurisdiction,
            "court_level": s.court_level,
            "deep": s.deep,
            "latency_ms": s.latency_ms,
            "cached": s.cached,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in searches
    ]
