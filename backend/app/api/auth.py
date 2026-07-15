"""Auth endpoints — register / login / refresh / logout / me.

Custom auth on Postgres: bcrypt passwords, short-lived access JWT + rotating
refresh tokens (stored hashed for revocation). Requires DATABASE_URL.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from ..config import settings
from ..core.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from ..db import crud
from ..db.session import db_configured, get_db_optional
from ..deps import CurrentUser, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


def _require_db(db):
    if db is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Auth requires a database. Set DATABASE_URL.",
        )


async def _issue_tokens(db, user) -> TokenResponse:
    access = create_access_token(user.id, extra={"email": user.email, "plan": user.plan})
    refresh = new_refresh_token()
    await crud.store_refresh_token(
        db, user_id=user.id, token_hash=hash_token(refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
    )
    return TokenResponse(
        access_token=access, refresh_token=refresh,
        user={"id": user.id, "email": user.email, "full_name": user.full_name,
              "plan": user.plan, "role": user.role},
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(req: RegisterRequest, db=Depends(get_db_optional)):
    _require_db(db)
    if await crud.get_user_by_email(db, req.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered.")
    user = await crud.create_user(
        db, email=req.email, password_hash=hash_password(req.password),
        full_name=req.full_name, plan="free", role="owner",
    )
    return await _issue_tokens(db, user)


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db=Depends(get_db_optional)):
    _require_db(db)
    user = await crud.get_user_by_email(db, req.email)
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    return await _issue_tokens(db, user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db=Depends(get_db_optional)):
    _require_db(db)
    th = hash_token(req.refresh_token)
    row = await crud.get_valid_refresh_token(db, th)
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token.")
    await crud.revoke_refresh_token(db, th)          # rotate: one-time use
    user = await crud.get_user_by_id(db, row.user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found.")
    return await _issue_tokens(db, user)


@router.post("/logout", status_code=204)
async def logout(req: RefreshRequest, db=Depends(get_db_optional)):
    _require_db(db)
    await crud.revoke_refresh_token(db, hash_token(req.refresh_token))


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user), db=Depends(get_db_optional)):
    used = 0
    if db is not None:
        used = await crud.usage_today(db, user.id)
    return {
        "id": user.id, "email": user.email, "plan": user.plan,
        "searches_today": used, "daily_limit": user.daily_limit,
    }
