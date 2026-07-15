"""Nyaya API — FastAPI application entrypoint."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import auth, health, history, search
from .config import settings

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("nyaya")

app = FastAPI(
    title="Nyaya API",
    version=__version__,
    description="AI legal research for Indian advocates — facts in, judgments out.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(history.router, prefix="/api/v1")


async def _build_corpus():
    """Attach the vector-corpus backend selected by VECTOR_BACKEND."""
    backend = settings.VECTOR_BACKEND
    if backend == "memory":
        from .services.memory_store import InMemoryCorpus

        return await InMemoryCorpus.from_seed(settings.SEED_CORPUS_PATH)
    if backend == "postgres" and settings.DATABASE_URL:
        from .db.base import VectorStore

        return VectorStore()
    return None


@app.on_event("startup")
async def _startup():
    from .api.search import pipeline

    # Create DB tables if a database is configured (Alembic recommended for prod).
    if settings.DATABASE_URL and settings.DB_AUTO_CREATE:
        try:
            from .db.session import init_models

            await init_models()
            logger.info("DB tables ensured.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("DB init failed: %s", exc)

    try:
        pipeline.db = await _build_corpus()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Corpus backend init failed (%s); vector retrieval off.", exc)

    logger.info(
        "Nyaya %s starting | env=%s | llm=%s | indian_kanoon=%s | corpus=%s | auth_required=%s",
        __version__, settings.ENV,
        "on" if settings.has_llm else "off",
        "on" if settings.has_indian_kanoon else "off",
        settings.VECTOR_BACKEND if pipeline.db else "off",
        settings.AUTH_REQUIRED,
    )
    if not settings.has_llm:
        logger.warning("ANTHROPIC_API_KEY not set — using heuristic parse/rerank "
                       "(reduced quality). Set it for production behaviour.")
    if not settings.has_indian_kanoon:
        logger.warning("INDIAN_KANOON_API_TOKEN not set — the primary retriever "
                       "is disabled. Searches will be empty until it's configured.")


@app.get("/")
async def root():
    return {"service": "nyaya", "version": __version__, "docs": "/docs"}
