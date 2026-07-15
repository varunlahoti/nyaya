"""SQLAlchemy models — the persistence schema (mirrors docs/SYSTEM_DESIGN.md §3).

These define the production data model. The MVP search path runs without a DB;
wire these up (plus Alembic migrations) to enable auth, history, matters, and
the internal vector corpus.
"""
from __future__ import annotations

from datetime import datetime, date
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
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover - pgvector optional at import time
    Vector = None  # type: ignore

from ..config import settings


class Base(DeclarativeBase):
    pass


class Firm(Base):
    __tablename__ = "firms"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    plan: Mapped[str] = mapped_column(String, default="firm")
    seats: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    full_name: Mapped[str] = mapped_column(String, default="")
    role: Mapped[str] = mapped_column(String, default="advocate")
    plan: Mapped[str] = mapped_column(String, default="free")
    firm_id: Mapped[Optional[str]] = mapped_column(ForeignKey("firms.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Matter(Base):
    __tablename__ = "matters"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    firm_id: Mapped[Optional[str]] = mapped_column(ForeignKey("firms.id"), nullable=True)
    title: Mapped[str] = mapped_column(String)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Search(Base):
    __tablename__ = "searches"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    matter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("matters.id"), nullable=True)
    facts_text: Mapped[str] = mapped_column(Text)
    parsed_json: Mapped[str] = mapped_column(Text, default="{}")
    jurisdiction: Mapped[str] = mapped_column(String, default="any")
    status: Mapped[str] = mapped_column(String, default="completed")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    results: Mapped[list["SearchResult"]] = relationship(back_populates="search")


class SearchResult(Base):
    __tablename__ = "search_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_id: Mapped[str] = mapped_column(ForeignKey("searches.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    judgment_id: Mapped[str] = mapped_column(String)
    relevance_score: Mapped[int] = mapped_column(Integer, default=0)
    relevance_note: Mapped[str] = mapped_column(Text, default="")
    holding: Mapped[str] = mapped_column(Text, default="")
    search: Mapped["Search"] = relationship(back_populates="results")


class Judgment(Base):
    __tablename__ = "judgments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, index=True)
    source_doc_id: Mapped[str] = mapped_column(String, index=True)
    citation: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    court: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    court_level: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    bench: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    full_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


if Vector is not None:
    class JudgmentChunk(Base):
        __tablename__ = "judgment_chunks"
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        judgment_id: Mapped[str] = mapped_column(ForeignKey("judgments.id"), index=True)
        chunk_index: Mapped[int] = mapped_column(Integer)
        text: Mapped[str] = mapped_column(Text)
        embedding = mapped_column(Vector(settings.EMBEDDINGS_DIM))
