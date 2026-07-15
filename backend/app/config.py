"""Application configuration, loaded from environment / .env.

Everything degrades gracefully: with no external keys the API still boots and
serves the pipeline (returning partial/empty results and a clear message),
which makes the scaffold runnable out of the box.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    APP_NAME: str = "Nyaya"
    ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # --- LLM ---
    # Provider: "openrouter" (OpenAI-compatible, cheap models) or "anthropic".
    LLM_PROVIDER: str = "openrouter"

    # OpenRouter (default) — cheap, strong models. Set OPENROUTER_API_KEY.
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # Sent as attribution headers to OpenRouter (optional but recommended).
    OPENROUTER_APP_URL: str = "https://nyaya.local"
    OPENROUTER_APP_TITLE: str = "Nyaya Legal Research"

    # Anthropic (alternative provider). Set ANTHROPIC_API_KEY + LLM_PROVIDER=anthropic.
    ANTHROPIC_API_KEY: Optional[str] = None

    # Reranker model (quality matters most here). DeepSeek V3 = strong + very cheap.
    LLM_MODEL: str = "deepseek/deepseek-chat"
    # Parser model (issue-spotting; cheap but capable). Gemini 2.5 Flash.
    LLM_PARSER_MODEL: Optional[str] = "google/gemini-2.5-flash"
    LLM_MAX_TOKENS: int = 8000

    # --- Indian Kanoon API ---
    INDIAN_KANOON_API_TOKEN: Optional[str] = None
    INDIAN_KANOON_BASE_URL: str = "https://api.indiankanoon.org"

    # --- Retrieval ---
    ENABLED_RETRIEVERS: List[str] = ["indian_kanoon", "vector"]
    CANDIDATE_CAP: int = 25           # how many candidates go to the reranker (cost lever)
    # IK boolean/phrase queries can take 10-15s; keep this generous.
    RETRIEVER_TIMEOUT_SECONDS: float = 20.0
    # Fetch more per query (same # of IK calls = same credits) so landmark cases
    # are more likely to enter the candidate pool.
    PER_RETRIEVER_LIMIT: int = 25     # results requested per source per query
    # Cap queries per search. Each query ≈ 1 Indian Kanoon credit, so this is the
    # direct lever on credit burn. 3 = conserve (free-tier dev); 6 = full breadth.
    MAX_QUERIES_PER_SEARCH: int = 6
    # Always add one Supreme-Court-priority query so binding authority surfaces
    # (over and above the cap). Costs 1 extra IK query per search.
    SC_PRIORITY_QUERY: bool = True

    # Deep mode: fetch full judgment text for the top-N candidates before
    # reranking (richer ranking + accurate holdings). Opt-in per search via the
    # `deep` flag — costs N extra IK document fetches.
    DEEP_FETCH_TOP_N: int = 8
    DEEP_FETCH_CHARS: int = 4000

    # --- Embeddings (for the internal vector corpus) ---
    # "hash" is a deterministic dev-only fallback so the vector path runs without
    # an embeddings key. Use "voyage" or "openai" in production.
    EMBEDDINGS_PROVIDER: str = "hash"
    EMBEDDINGS_MODEL: str = "voyage-law-2"
    EMBEDDINGS_DIM: int = 1024
    VOYAGE_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None

    # --- Vector corpus backend ---
    # "none"     -> no internal corpus (retrieval relies on Indian Kanoon only)
    # "memory"   -> load a seed corpus into RAM at startup (zero DB, great for
    #               offline dev/demo — 0 Indian Kanoon credits per search)
    # "postgres" -> pgvector-backed corpus (production; needs DATABASE_URL)
    # Default "memory": blends the landmark seed corpus into every search (0 cost,
    # local) so famous binding cases are always in the candidate pool.
    VECTOR_BACKEND: str = "memory"
    SEED_CORPUS_PATH: str = "data/seed_judgments.json"

    # --- Persistence / cache (optional) ---
    DATABASE_URL: Optional[str] = None   # e.g. postgresql+asyncpg://user:pass@db/nyaya
    REDIS_URL: Optional[str] = None      # e.g. redis://redis:6379/0

    # --- Auth / quotas ---
    AUTH_REQUIRED: bool = False          # dev default: open; set True in prod
    # Simple shared-password gate for the public deploy. When set, every search
    # requires the X-App-Password header to match (the frontend prompts for it).
    # Leave empty for open/local dev.
    APP_PASSWORD: Optional[str] = None
    # Per-search daily cap (protects credits even with the password). 0 = no cap.
    MAX_SEARCHES_PER_DAY: int = 0
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_TTL_MIN: int = 60
    REFRESH_TOKEN_TTL_DAYS: int = 30

    # --- Quotas by plan (searches/day) ---
    QUOTA_FREE: int = 5
    QUOTA_ADVOCATE: int = 100
    QUOTA_FIRM: int = 2000

    @property
    def has_llm(self) -> bool:
        if self.LLM_PROVIDER == "anthropic":
            return bool(self.ANTHROPIC_API_KEY)
        return bool(self.OPENROUTER_API_KEY)

    @property
    def has_indian_kanoon(self) -> bool:
        return bool(self.INDIAN_KANOON_API_TOKEN)

    @property
    def parser_model(self) -> str:
        return self.LLM_PARSER_MODEL or self.LLM_MODEL


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
