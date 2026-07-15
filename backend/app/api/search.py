"""Search endpoints — the core of the product."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from ..config import settings
from ..db import crud
from ..db.session import get_db_optional
from ..deps import CurrentUser, enforce_quota, verify_app_password
from ..schemas import SearchRequest, SearchResponse
from ..services.pipeline import SearchPipeline

logger = logging.getLogger("nyaya.api.search")
router = APIRouter(prefix="/search", tags=["search"])

# The corpus backend (`.db`) is attached during app startup (see main.py).
pipeline = SearchPipeline(db=None)


@router.post("", response_model=SearchResponse, dependencies=[Depends(verify_app_password)])
async def search(
    req: SearchRequest,
    user: CurrentUser = Depends(enforce_quota),
    db=Depends(get_db_optional),
) -> SearchResponse:
    logger.info("search user=%s jur=%s len=%d", user.id, req.jurisdiction, len(req.facts))
    resp = await pipeline.run(req)

    # Persist to history for real (authenticated) users.
    if settings.AUTH_REQUIRED and db is not None and user.id != "dev":
        try:
            await crud.save_search(
                db, user_id=user.id, resp=resp, facts=req.facts,
                jurisdiction=req.jurisdiction,
                court_level=req.court_level.value if hasattr(req.court_level, "value") else str(req.court_level),
                deep=req.deep, matter_id=req.matter_id,
            )
        except Exception as exc:  # noqa: BLE001 — history is best-effort
            logger.warning("failed to persist search %s: %s", resp.search_id, exc)
    return resp
