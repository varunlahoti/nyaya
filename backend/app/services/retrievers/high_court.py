"""High Court / eCourts retriever — direct-source adapter (pluggable stub).

eCourts services and individual High Court judgment portals vary by state in
availability and terms. Many use CAPTCHAs and explicitly restrict automated
access — enable per-court only where permitted, and never build CAPTCHA
evasion. See docs/DATA_SOURCES.md.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ...config import settings
from ...schemas import Candidate, JudgmentDoc, RetrievalQuery

logger = logging.getLogger("nyaya.retriever.high_court")


class HighCourtRetriever:
    name = "high_court"

    def enabled(self) -> bool:
        return "high_court" in settings.ENABLED_RETRIEVERS and False

    async def search(self, query: RetrievalQuery) -> List[Candidate]:
        if not self.enabled():
            return []
        # TODO: query authorised eCourts/HC data source per state here.
        logger.debug("HighCourtRetriever is a stub; returning no candidates.")
        return []

    async def fetch_document(self, doc_id: str) -> Optional[JudgmentDoc]:
        return None
