"""Per-user daily quota counters.

Backed by Redis when REDIS_URL is set; otherwise an in-process fallback so the
app runs standalone (fine for a single-instance dev deployment).
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Optional

from ..config import settings

_redis = None
_local: Dict[str, int] = {}


def _client():
    global _redis
    if _redis is None and settings.REDIS_URL:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def incr_daily(user_id: str) -> int:
    key = f"quota:{user_id}:{date.today().isoformat()}"
    client = _client()
    if client is not None:
        val = await client.incr(key)
        if val == 1:
            await client.expire(key, 86400)
        return int(val)
    # In-process fallback.
    _local[key] = _local.get(key, 0) + 1
    return _local[key]


async def get_daily(user_id: str) -> int:
    key = f"quota:{user_id}:{date.today().isoformat()}"
    client = _client()
    if client is not None:
        val = await client.get(key)
        return int(val) if val else 0
    return _local.get(key, 0)
