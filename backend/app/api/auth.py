"""Auth endpoints (register / login / refresh).

Persistence requires DATABASE_URL. When no DB is configured these endpoints
return 503 — the core /search path still works in dev mode (AUTH_REQUIRED=False).
Wire these to the SQLAlchemy models in app/db/models.py for production.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from ..config import settings
from ..core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from ..deps import CurrentUser, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


def _require_db():
    if not settings.DATABASE_URL:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Auth requires a database. Set DATABASE_URL, or run in dev mode "
            "(AUTH_REQUIRED=False) where /search works without login.",
        )


@router.post("/register", status_code=201)
async def register(req: RegisterRequest):
    _require_db()
    # TODO: create user via app/db/models.py, hash password, return tokens.
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED,
                        "Persistence layer not wired in this scaffold.")


@router.post("/login")
async def login(req: LoginRequest):
    _require_db()
    # TODO: verify credentials against the DB.
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED,
                        "Persistence layer not wired in this scaffold.")


@router.post("/refresh")
async def refresh(req: RefreshRequest):
    payload = decode_token(req.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    access = create_access_token(payload["sub"],
                                 extra={"plan": payload.get("plan", "free")})
    return {"access_token": access, "token_type": "bearer"}


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    from ..core import ratelimit

    used = await ratelimit.get_daily(user.id)
    return {
        "id": user.id,
        "email": user.email,
        "plan": user.plan,
        "searches_today": used,
        "daily_limit": user.daily_limit,
    }
