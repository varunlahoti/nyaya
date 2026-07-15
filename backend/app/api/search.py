"""Search endpoints — the core of the product."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from ..deps import CurrentUser, enforce_quota
from ..schemas import SearchRequest, SearchResponse
from ..services.pipeline import SearchPipeline

logger = logging.getLogger("nyaya.api.search")
router = APIRouter(prefix="/search", tags=["search"])

# The corpus backend (`.db`) is attached during app startup (see main.py).
pipeline = SearchPipeline(db=None)


@router.post("", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    user: CurrentUser = Depends(enforce_quota),
) -> SearchResponse:
    logger.info("search user=%s jur=%s len=%d", user.id, req.jurisdiction, len(req.facts))
    return await pipeline.run(req)
