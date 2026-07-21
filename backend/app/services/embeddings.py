"""Pluggable embeddings provider for the internal vector corpus.

Providers:
  * "voyage"  — Voyage AI (recommended; `voyage-law-2` is tuned for legal text)
  * "openai"  — OpenAI embeddings
  * "hash"    — deterministic, dependency-free DEV fallback so the vector path
                runs without any embeddings key. NOT for production quality.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from typing import List

from ..config import settings

logger = logging.getLogger("nyaya.embeddings")

# Free embedding tiers are rate-limited (Voyage w/o payment: ~3 RPM / 10K TPM).
# Retry 429/5xx with backoff (honouring Retry-After) so bulk ingestion paces
# itself instead of crashing.
_EMBED_MAX_RETRIES = 8


async def _post_with_retry(client, url: str, headers: dict, payload: dict):
    import httpx

    for attempt in range(_EMBED_MAX_RETRIES):
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code not in (429, 500, 502, 503, 529):
            resp.raise_for_status()
            return resp
        if attempt == _EMBED_MAX_RETRIES - 1:
            resp.raise_for_status()
        retry_after = resp.headers.get("Retry-After")
        wait = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() \
            else min(60.0, 2.0 * (2 ** attempt))
        logger.warning("Embeddings %s; backing off %.1fs (attempt %d/%d)",
                       resp.status_code, wait, attempt + 1, _EMBED_MAX_RETRIES)
        await asyncio.sleep(wait)
    raise httpx.HTTPError("embeddings retries exhausted")  # pragma: no cover


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

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await _post_with_retry(
            client, "https://api.voyageai.com/v1/embeddings",
            {"Authorization": f"Bearer {settings.VOYAGE_API_KEY}"},
            {"input": texts, "model": settings.EMBEDDINGS_MODEL},
        )
        return [d["embedding"] for d in resp.json()["data"]]


async def _openai(texts: List[str]) -> List[List[float]]:
    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await _post_with_retry(
            client, "https://api.openai.com/v1/embeddings",
            {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            {"input": texts, "model": "text-embedding-3-large"},
        )
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
