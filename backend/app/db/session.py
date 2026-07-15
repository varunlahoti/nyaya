"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""
from __future__ import annotations

from typing import AsyncGenerator, Optional

from ..config import settings

_engine = None
_sessionmaker = None


def _normalise_url(url: str) -> str:
    # Accept plain postgres URLs and upgrade them to the async driver.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def engine():
    global _engine, _sessionmaker
    if _engine is None:
        if not settings.DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not configured")
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        _engine = create_async_engine(_normalise_url(settings.DATABASE_URL), pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def sessionmaker():
    engine()
    return _sessionmaker


async def get_db() -> AsyncGenerator:
    """FastAPI dependency yielding an async session (requires DATABASE_URL)."""
    sm = sessionmaker()
    async with sm() as session:
        yield session


async def get_db_optional() -> AsyncGenerator:
    """Yields a session, or None if no database is configured (dev mode)."""
    if not db_configured():
        yield None
        return
    sm = sessionmaker()
    async with sm() as session:
        yield session


async def init_models() -> None:
    """Create tables if they don't exist (dev/bootstrap; use Alembic in prod)."""
    from .models import Base

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def db_configured() -> bool:
    return bool(settings.DATABASE_URL)
