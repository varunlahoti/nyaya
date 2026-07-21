"""Supreme Court of India retriever — direct-source adapter (pluggable stub).

Enable only where automated access is permitted. Prefer the official Supreme
Court Reports (SCR) bulk/downloadable data over page scraping — as of 8 May 2025
the eSCR and DigiSCR portals were merged into the free SCR portal at
https://scr.sci.gov.in/scrsearch/ (judgments 1950-, no login). It exposes no
documented API, so the ToS-preferred integration is: download the official
judgment PDFs and load them via `scripts.bulk_ingest` (see docs/DATA_SOURCES.md),
NOT live scraping of its internal endpoints.

The contract is identical to every other retriever, so wiring a real
implementation later requires no changes to the orchestrator: implement
`search()` and `fetch_document()`, flip `enabled()` on, and add "supreme_court"
to ENABLED_RETRIEVERS.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ...config import settings
from ...schemas import Candidate, JudgmentDoc, RetrievalQuery

logger = logging.getLogger("nyaya.retriever.supreme_court")


class SupremeCourtRetriever:
    name = "supreme_court"

    def enabled(self) -> bool:
        # Disabled by default: requires an authorised eSCR data feed.
        return "supreme_court" in settings.ENABLED_RETRIEVERS and False

    async def search(self, query: RetrievalQuery) -> List[Candidate]:
        if not self.enabled():
            return []
        # TODO: query the eSCR feed / authorised SC data source here.
        logger.debug("SupremeCourtRetriever is a stub; returning no candidates.")
        return []

    async def fetch_document(self, doc_id: str) -> Optional[JudgmentDoc]:
        return None
