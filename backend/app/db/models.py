"""SQLAlchemy models — production schema (see docs/PRODUCTION_ARCHITECTURE.md §B.1).

Phase 1 scope: users + auth (refresh tokens), search history, matters, usage
metering. Billing tables land in Phase 2. The judgment corpus (pgvector) is
optional and only imported when pgvector is installed.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    full_name: Mapped[str] = mapped_column(String, default="")
    role: Mapped[str] = mapped_column(String, default="member")   # owner/admin/member
    plan: Mapped[str] = mapped_column(String, default="free")     # free/advocate/firm/enterprise
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Matter(Base):
    __tablename__ = "matters"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Search(Base):
    __tablename__ = "searches"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    matter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("matters.id"), nullable=True)
    facts_text: Mapped[str] = mapped_column(Text)
    parsed_json: Mapped[str] = mapped_column(Text, default="{}")
    jurisdiction: Mapped[str] = mapped_column(String, default="any")
    court_level: Mapped[str] = mapped_column(String, default="any")
    deep: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    results: Mapped[list["SearchResult"]] = relationship(
        back_populates="search", cascade="all, delete-orphan"
    )


class SearchResult(Base):
    __tablename__ = "search_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_id: Mapped[str] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    judgment_id: Mapped[str] = mapped_column(String)
    citation: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    court: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    court_level: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    date: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    relevance_score: Mapped[int] = mapped_column(Integer, default=0)
    relevance_note: Mapped[str] = mapped_column(Text, default="")
    holding: Mapped[str] = mapped_column(Text, default="")
    search: Mapped["Search"] = relationship(back_populates="results")


class UsageDaily(Base):
    __tablename__ = "usage_daily"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    search_count: Mapped[int] = mapped_column(Integer, default=0)
    deep_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String)
    target: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
