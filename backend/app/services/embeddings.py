"""Pluggable embeddings provider for the internal vector corpus.

Providers:
  * "voyage"  — Voyage AI (recommended; `voyage-law-2` is tuned for legal text)
  * "openai"  — OpenAI embeddings
  * "hash"    — deterministic, dependency-free DEV fallback so the vector path
                runs without any embeddings key. NOT for production quality.
"""
from __future__ import annotations

import hashlib
import logging
import math
from typing import List

from ..config import settings

logger = logging.getLogger("nyaya.embeddings")


async def embed(texts: List[str]) -> List[List[float]]:
    provider = settings.EMBEDDINGS_PROVIDER
    if provider == "voyage" and settings.VOYAGE_API_KEY:
        return await _voyage(texts)
    if provider == "openai" and settings.OPENAI_API_KEY:
        return await _openai(texts)
    return [_hash_embed(t) for t in texts]


async def embed_one(text: str) -> List[float]:
    return (await embed([text]))[0]


# --------------------------------------------------------------------------- #
async def _voyage(texts: List[str]) -> List[List[float]]:
    import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {settings.VOYAGE_API_KEY}"},
            json={"input": texts, "model": settings.EMBEDDINGS_MODEL},
        )
        resp.raise_for_status()
        return [d["embedding"] for d in resp.json()["data"]]


async def _openai(texts: List[str]) -> List[List[float]]:
    import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={"input": texts, "model": "text-embedding-3-large"},
        )
        resp.raise_for_status()
        return [d["embedding"] for d in resp.json()["data"]]


def _hash_embed(text: str) -> List[float]:
    """Deterministic bag-of-hashed-tokens vector. Dev-only, no external calls."""
    dim = settings.EMBEDDINGS_DIM
    vec = [0.0] * dim
    for token in text.lower().split():
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]
