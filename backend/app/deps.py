"""Shared FastAPI dependencies: current user, quota enforcement, app-password.

Modes:
  * Dev / password-gated demo (AUTH_REQUIRED=False): a synthetic user; the
    APP_PASSWORD header + a global daily cap protect credits.
  * Production (AUTH_REQUIRED=True + DATABASE_URL): real users via JWT, loaded
    from Postgres, with per-plan quotas metered in the DB.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from .config import settings
from .core.security import decode_token
from .db import crud
from .db.session import db_configured, get_db_optional


@dataclass
class CurrentUser:
    id: str
    email: str
    plan: str = "free"

    @property
    def daily_limit(self) -> int:
        return {
            "free": settings.QUOTA_FREE,
            "advocate": settings.QUOTA_ADVOCATE,
            "firm": settings.QUOTA_FIRM,
            "enterprise": 10 ** 9,
        }.get(self.plan, settings.QUOTA_FREE)


DEV_USER = CurrentUser(id="dev", email="dev@nyaya.local", plan="advocate")


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db=Depends(get_db_optional),
) -> CurrentUser:
    if not settings.AUTH_REQUIRED:
        return DEV_USER

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    # Load the user from the DB for the authoritative plan (JWT plan can be stale).
    if db is not None:
        user = await crud.get_user_by_id(db, payload["sub"])
        if not user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
        return CurrentUser(id=user.id, email=user.email, plan=user.plan)

    return CurrentUser(id=payload["sub"], email=payload.get("email", ""),
                       plan=payload.get("plan", "free"))


async def verify_app_password(
    x_app_password: Optional[str] = Header(default=None),
) -> None:
    """Shared-password gate for the public demo. Open when APP_PASSWORD unset."""
    if not settings.APP_PASSWORD:
        return
    if x_app_password != settings.APP_PASSWORD:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing app password.")


async def enforce_quota(
    user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db_optional),
) -> CurrentUser:
    """Enforce the daily search cap.

    Production (real user + DB): meter per-user in Postgres against the plan.
    Demo (no auth): global cap via Redis/in-process counter.
    """
    if settings.AUTH_REQUIRED and db is not None:
        used = await crud.increment_usage(db, user.id, deep=False)
        if used > user.daily_limit:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily search limit reached for the {user.plan} plan "
                       f"({user.daily_limit}/day). Upgrade for more.",
                headers={"Retry-After": "3600"},
            )
        return user

    from .core import ratelimit

    if settings.MAX_SEARCHES_PER_DAY > 0:
        used = await ratelimit.incr_daily("global")
        if used > settings.MAX_SEARCHES_PER_DAY:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily search limit reached ({settings.MAX_SEARCHES_PER_DAY}/day). "
                       "This protects the API credits — try again tomorrow.",
                headers={"Retry-After": "3600"},
            )
    return user
