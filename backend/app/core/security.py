"""JWT + password hashing utilities."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from ..config import settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def create_access_token(subject: str, extra: Optional[Dict[str, Any]] = None) -> str:
    return _create_token(subject, timedelta(minutes=settings.ACCESS_TOKEN_TTL_MIN),
                         "access", extra)


def create_refresh_token(subject: str) -> str:
    return _create_token(subject, timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
                         "refresh", None)


def _create_token(subject: str, ttl: timedelta, kind: str,
                  extra: Optional[Dict[str, Any]]) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {"sub": subject, "type": kind,
                               "iat": now, "exp": now + ttl}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
    except JWTError:
        return None
