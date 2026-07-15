"""Caching layer — Redis-backed with an in-process fallback.

Two jobs, both aimed at cost + latency:
  1. Search-result cache: identical facts within the TTL return the prior result
     without re-running retrieval or the LLM (0 Indian Kanoon credits, 0 LLM).
  2. Upstream cache: Indian Kanoon query results and documents are cached so
     repeated queries across searches don't re-spend credits.

Set REDIS_URL for a shared cache across instances; otherwise an in-process dict
is used (fine for single-instance dev).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any, Optional

from ..config import settings

logger = logging.getLogger("nyaya.cache")

_redis = None
_local: dict = {}  # key -> (expires_at_epoch, json_string)


def _client():
    global _redis
    if _redis is None and settings.REDIS_URL:
        try:
            import redis.asyncio as aioredis

            _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis unavailable, using in-process cache: %s", exc)
    return _redis


async def get_json(key: str) -> Optional[Any]:
    client = _client()
    if client is not None:
        try:
            raw = await client.get(key)
            return json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001
            return None
    entry = _local.get(key)
    if not entry:
        return None
    expires_at, raw = entry
    if expires_at < time.time():
        _local.pop(key, None)
        return None
    return json.loads(raw)


async def set_json(key: str, value: Any, ttl_seconds: int) -> None:
    raw = json.dumps(value)
    client = _client()
    if client is not None:
        try:
            await client.set(key, raw, ex=ttl_seconds)
            return
        except Exception:  # noqa: BLE001
            pass
    _local[key] = (time.time() + ttl_seconds, raw)


def search_key(facts: str, jurisdiction: str, court_level: str,
               max_results: int, date_from: Optional[str],
               date_to: Optional[str]) -> str:
    norm = re.sub(r"\s+", " ", facts.strip().lower())
    payload = f"{norm}|{jurisdiction}|{court_level}|{max_results}|{date_from}|{date_to}"
    digest = hashlib.sha256(payload.encode()).hexdigest()[:24]
    return f"search:{digest}"


def ik_query_key(form_input: str, limit: int) -> str:
    digest = hashlib.sha256(f"{form_input}|{limit}".encode()).hexdigest()[:24]
    return f"ik:q:{digest}"


def ik_doc_key(doc_id: str) -> str:
    return f"ik:doc:{doc_id}"
