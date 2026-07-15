"""Async data-access helpers (users, auth tokens, searches, usage)."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update

from ..schemas import SearchResponse
from .models import RefreshToken, Search, SearchResult, UsageDaily, User


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
async def create_user(db, *, email: str, password_hash: str, full_name: str = "",
                      plan: str = "free", role: str = "owner") -> User:
    user = User(id=_uid("u"), email=email.lower(), password_hash=password_hash,
                full_name=full_name, plan=plan, role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_user_by_email(db, email: str) -> Optional[User]:
    res = await db.execute(select(User).where(User.email == email.lower()))
    return res.scalar_one_or_none()


async def get_user_by_id(db, user_id: str) -> Optional[User]:
    res = await db.execute(select(User).where(User.id == user_id))
    return res.scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Refresh tokens (rotating, revocable)
# --------------------------------------------------------------------------- #
async def store_refresh_token(db, *, user_id: str, token_hash: str, expires_at: datetime) -> None:
    db.add(RefreshToken(id=_uid("rt"), user_id=user_id, token_hash=token_hash,
                        expires_at=expires_at))
    await db.commit()


async def get_valid_refresh_token(db, token_hash: str) -> Optional[RefreshToken]:
    res = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    return res.scalar_one_or_none()


async def revoke_refresh_token(db, token_hash: str) -> None:
    await db.execute(
        update(RefreshToken).where(RefreshToken.token_hash == token_hash)
        .values(revoked=True)
    )
    await db.commit()


# --------------------------------------------------------------------------- #
# Search history + usage metering
# --------------------------------------------------------------------------- #
async def save_search(db, *, user_id: str, resp: SearchResponse, facts: str,
                      jurisdiction: str, court_level: str, deep: bool,
                      cost_micros: int = 0, matter_id: Optional[str] = None) -> None:
    search = Search(
        id=resp.search_id, user_id=user_id, matter_id=matter_id, facts_text=facts,
        parsed_json=resp.parsed.model_dump_json(), jurisdiction=jurisdiction,
        court_level=court_level, deep=deep, latency_ms=resp.latency_ms,
        cost_micros=cost_micros, cached=resp.cached,
    )
    db.add(search)
    for r in resp.results:
        db.add(SearchResult(
            search_id=resp.search_id, rank=r.rank, judgment_id=r.judgment_id,
            citation=r.citation, title=r.title, court=r.court,
            court_level=r.court_level, date=r.date, url=r.url,
            relevance_score=r.relevance_score, relevance_note=r.relevance_note,
            holding=r.holding,
        ))
    await db.commit()


async def list_searches(db, user_id: str, limit: int = 20, offset: int = 0):
    res = await db.execute(
        select(Search).where(Search.user_id == user_id)
        .order_by(Search.created_at.desc()).limit(limit).offset(offset)
    )
    return list(res.scalars())


async def increment_usage(db, user_id: str, *, deep: bool, cost_micros: int = 0) -> int:
    """Upsert today's usage row; return the new search_count."""
    today = date.today()
    row = await db.get(UsageDaily, (user_id, today))
    if row is None:
        row = UsageDaily(user_id=user_id, day=today, search_count=0,
                         deep_count=0, cost_micros=0)
        db.add(row)
    row.search_count += 1
    row.deep_count += 1 if deep else 0
    row.cost_micros += cost_micros
    await db.commit()
    return row.search_count


async def usage_today(db, user_id: str) -> int:
    row = await db.get(UsageDaily, (user_id, date.today()))
    return row.search_count if row else 0
