"""Test isolation: force offline mode BEFORE the app/config is imported.

Without this, tests read backend/.env (live keys) and would make real Indian
Kanoon + LLM calls — spending credits. These overrides take precedence over the
.env file, so the whole suite runs offline with the heuristic fallbacks.
"""
import os

os.environ["INDIAN_KANOON_API_TOKEN"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["ENABLED_RETRIEVERS"] = "[]"
os.environ["VECTOR_BACKEND"] = "none"
