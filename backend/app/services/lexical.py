"""Pure-Python BM25 lexical index — the keyword half of hybrid retrieval.

Deliberately dependency-free (no rank_bm25 / sklearn) so it runs in the minimal
Streamlit deploy image and on Python 3.9. BM25-Okapi over a modest local corpus
(thousands of chunks) is fast enough in pure Python; for a very large pgvector
corpus, Postgres full-text search plays this role instead (see db/base.py).

Why BM25 and not just vectors: embeddings match meaning but miss exact tokens
that matter in law — a specific section number ("498A"), a statute name, a
neutral citation. BM25 nails those. Fusing the two (RRF) beats either alone.
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Sequence, Tuple

_TOKEN = re.compile(r"[a-z0-9]+")

# Very common English words that carry no legal signal. Kept tiny on purpose —
# legal terms of art ("held", "section", "act") are NOT stopped.
_STOP = frozenset(
    "a an the of to in on and or for with is are was were be been by at as from "
    "that this these those it its into under over per vs".split()
)


def tokenize(text: str) -> List[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP and len(t) > 1]


class BM25Index:
    """BM25-Okapi. Build once over a corpus of documents, then `search`."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs_tokens: List[List[str]] = []
        self._doc_len: List[int] = []
        self._avg_len: float = 0.0
        self._df: Dict[str, int] = {}
        self._idf: Dict[str, float] = {}
        self._tf: List[Dict[str, int]] = []

    @property
    def size(self) -> int:
        return len(self._docs_tokens)

    def build(self, documents: Sequence[str]) -> "BM25Index":
        self._docs_tokens = [tokenize(d) for d in documents]
        self._doc_len = [len(t) for t in self._docs_tokens]
        n = len(self._docs_tokens)
        self._avg_len = (sum(self._doc_len) / n) if n else 0.0

        self._tf = []
        self._df = {}
        for toks in self._docs_tokens:
            tf: Dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            self._tf.append(tf)
            for t in tf:
                self._df[t] = self._df.get(t, 0) + 1

        # BM25 idf with the +0.5 smoothing (non-negative variant).
        self._idf = {
            t: math.log(1 + (n - df + 0.5) / (df + 0.5)) for t, df in self._df.items()
        }
        return self

    def search(self, query: str, limit: int) -> List[Tuple[int, float]]:
        """Return [(doc_index, score)] for the top `limit` docs, score desc."""
        q_tokens = set(tokenize(query))
        if not q_tokens or not self._avg_len:
            return []

        scores: List[Tuple[int, float]] = []
        for i, tf in enumerate(self._tf):
            s = 0.0
            dl = self._doc_len[i]
            denom_norm = self.k1 * (1 - self.b + self.b * dl / self._avg_len)
            for t in q_tokens:
                f = tf.get(t)
                if not f:
                    continue
                s += self._idf.get(t, 0.0) * (f * (self.k1 + 1)) / (f + denom_norm)
            if s > 0:
                scores.append((i, s))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:limit]
