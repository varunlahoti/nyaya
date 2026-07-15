"""Shared FastAPI dependencies: current user + per-plan quota enforcement.

In dev (AUTH_REQUIRED=False) a synthetic user is returned so the search path
works with zero setup. In prod (AUTH_REQUIRED=True) a valid JWT is required.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from .config import settings
from .core.security import decode_token


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
) -> CurrentUser:
    if not settings.AUTH_REQUIRED:
        return DEV_USER

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return CurrentUser(
        id=payload["sub"],
        email=payload.get("email", ""),
        plan=payload.get("plan", "free"),
    )


async def verify_app_password(
    x_app_password: Optional[str] = Header(default=None),
) -> None:
    """Shared-password gate for the public deploy. Open when APP_PASSWORD unset."""
    if not settings.APP_PASSWORD:
        return
    if x_app_password != settings.APP_PASSWORD:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or missing app password."
        )


async def enforce_quota(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Enforce a per-day search cap (Redis-backed if present, else in-process).

    Uses a global counter when MAX_SEARCHES_PER_DAY is set (public deploy), else
    the per-user plan quota.
    """
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

    used = await ratelimit.incr_daily(user.id)
    if used > user.daily_limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily search limit reached for the {user.plan} plan "
                   f"({user.daily_limit}/day). Upgrade for more.",
            headers={"Retry-After": "3600"},
        )
    return user
