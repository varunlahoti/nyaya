"""Common contract every source adapter implements."""
from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from ...schemas import Candidate, JudgmentDoc, RetrievalQuery


@runtime_checkable
class BaseRetriever(Protocol):
    name: str

    def enabled(self) -> bool:
        """Whether this retriever is configured and usable."""
        ...

    async def search(self, query: RetrievalQuery) -> List[Candidate]:
        """Return candidate judgments for a single query."""
        ...

    async def fetch_document(self, doc_id: str) -> Optional[JudgmentDoc]:
        """Fetch a full judgment document (for caching / holding extraction)."""
        ...
