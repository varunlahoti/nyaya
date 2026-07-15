"""Nyaya — Streamlit app (deployable to Streamlit Community Cloud).

Runs the full pipeline (parse → retrieve → rerank) in-process.

Keys are read from Streamlit Secrets on Cloud, or backend/.env locally — NEVER
committed to the repo. A password gate protects the app so public visitors can't
burn your Indian Kanoon / OpenRouter credits.

Local run:
    cd backend
    pip install -r requirements.txt streamlit   # (Python 3.10+; 3.9.7 is unsupported by Streamlit)
    streamlit run streamlit_app.py

Cloud deploy: see docs/DEPLOY_STREAMLIT.md.
"""
from __future__ import annotations

import os
import sys

import streamlit as st

st.set_page_config(page_title="Nyaya — Legal Research", page_icon="⚖️", layout="centered")

# --- Make the `app` package importable (local + Streamlit Cloud) ------------ #
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _secret(key: str):
    """Read a value from Streamlit Secrets, falling back to env. Never logs it."""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key)


# --- Bridge secrets into the environment BEFORE importing app.config -------- #
# (app.config reads env / .env once and caches it, so this must run first.)
for _k in ("OPENROUTER_API_KEY", "INDIAN_KANOON_API_TOKEN", "LLM_MODEL",
           "LLM_PARSER_MODEL", "MAX_QUERIES_PER_SEARCH"):
    _v = _secret(_k)
    if _v and not os.environ.get(_k):
        os.environ[_k] = str(_v)


# --- Password gate: protect your credits from public visitors --------------- #
def _require_password() -> None:
    expected = _secret("APP_PASSWORD")
    if not expected:            # no password configured (local dev) → open
        return
    if st.session_state.get("_authed"):
        return
    st.title("Nyaya  न्याय")
    pw = st.text_input("Access password", type="password")
    if not pw:
        st.stop()
    if pw == str(expected):
        st.session_state["_authed"] = True
        st.rerun()
    else:
        st.error("Incorrect password.")
        st.stop()


_require_password()

import asyncio  # noqa: E402  (after gate so a blocked visitor loads nothing else)

from app.config import settings  # noqa: E402
from app.schemas import CourtLevel, SearchRequest  # noqa: E402
from app.services.pipeline import SearchPipeline  # noqa: E402

SAMPLE = (
    "My client is a tenant facing eviction. The landlord issued a quit notice "
    "under the Transfer of Property Act and claims wilful default in payment of "
    "rent for 8 months. The tenant argues the notice was defective and that he "
    "is a statutory tenant under the State Rent Act."
)


@st.cache_resource
def get_pipeline() -> SearchPipeline:
    """Build the pipeline once, wiring the corpus backend from config."""
    db = None
    if settings.VECTOR_BACKEND == "memory":
        from app.services.memory_store import InMemoryCorpus

        db = asyncio.run(InMemoryCorpus.from_seed(settings.SEED_CORPUS_PATH))
    elif settings.VECTOR_BACKEND == "postgres" and settings.DATABASE_URL:
        from app.db.base import VectorStore

        db = VectorStore()
    return SearchPipeline(db=db)


def run_search(req: SearchRequest):
    return asyncio.run(get_pipeline().run(req))


# --- Daily spend cap: hard ceiling on live searches to protect credits ------ #
MAX_SEARCHES_PER_DAY = int(_secret("MAX_SEARCHES_PER_DAY") or 40)


@st.cache_resource
def _quota_state() -> dict:
    # Process-global (shared across sessions), survives reruns. Resets on
    # Space restart — fine as a soft ceiling for a shared demo.
    return {"date": None, "count": 0}


def _quota_remaining() -> int:
    import datetime

    q = _quota_state()
    today = datetime.date.today().isoformat()
    if q["date"] != today:
        q["date"], q["count"] = today, 0
    return MAX_SEARCHES_PER_DAY - q["count"]


def _quota_consume() -> None:
    _quota_state()["count"] += 1


# ----------------------------- UI ---------------------------------------- #
st.title("Nyaya  न्याय")
st.caption("Type the facts. Get relevant Indian judgments, ranked, with source links.")

with st.sidebar:
    st.subheader("Configuration")
    st.write(f"**LLM:** {'✅ ' + settings.LLM_PROVIDER if settings.has_llm else '❌ not set (heuristic)'}")
    st.write(f"**Reranker:** `{settings.LLM_MODEL}`")
    st.write(f"**Parser:** `{settings.parser_model}`")
    st.write(f"**Indian Kanoon:** {'✅ on' if settings.has_indian_kanoon else '❌ token not set'}")
    st.write(f"**Corpus:** {settings.VECTOR_BACKEND}")
    st.divider()
    court_level = st.selectbox(
        "Judgments from",
        ["any", "supreme_court", "high_court"],
        format_func=lambda v: {"any": "All courts", "supreme_court": "Supreme Court only",
                               "high_court": "High Courts only"}[v],
    )
    max_results = st.slider("Results", 5, 10, 6)
    deep = st.checkbox("Deep mode (full-text ranking)",
                       help="Fetches full judgment text for top candidates — "
                            "higher quality, uses more Indian Kanoon credits.")
    st.divider()
    st.caption(f"Searches left today: {_quota_remaining()} / {MAX_SEARCHES_PER_DAY}")

if "facts_input" not in st.session_state:
    st.session_state["facts_input"] = ""
if st.button("Use sample"):
    st.session_state["facts_input"] = SAMPLE

facts = st.text_area(
    "Facts of the case", height=180, key="facts_input",
    placeholder="Describe the dispute in plain language…",
)

go = st.button("🔎 Find relevant judgments", type="primary", use_container_width=True)

if go:
    if len(facts.strip()) < 20:
        st.error("Please describe the facts in a little more detail (min 20 characters).")
        st.stop()
    if _quota_remaining() <= 0:
        st.error(f"Daily search limit reached ({MAX_SEARCHES_PER_DAY}/day). "
                 "This protects the API credits — try again tomorrow.")
        st.stop()
    _quota_consume()
    req = SearchRequest(
        facts=facts, jurisdiction="any",
        court_level=CourtLevel(court_level), max_results=max_results, deep=deep,
    )
    with st.spinner("Reading facts, searching case law, ranking…"):
        try:
            resp = run_search(req)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Search failed: {exc}")
            st.stop()

    st.success(
        f"{len(resp.results)} judgments · {resp.latency_ms} ms · "
        f"sources: {', '.join(resp.sources_used) or 'none'}"
        + (" · cached" if resp.cached else "")
        + (" · partial" if resp.partial else "")
    )
    if resp.notice:
        st.warning(resp.notice)

    # How the tool read the facts
    p = resp.parsed
    if p.summary or p.legal_issues or p.statutes:
        with st.expander("How the tool read your facts", expanded=True):
            if p.summary:
                st.write(p.summary)
            if p.legal_issues:
                st.markdown("**Legal issues**")
                for i in p.legal_issues:
                    st.markdown(f"- {i}")
            if p.statutes:
                st.markdown("**Statutes engaged**")
                for s in p.statutes:
                    secs = f" — s. {', '.join(s.sections)}" if s.sections else ""
                    st.markdown(f"- {s.act}{secs}")
            if p.keywords:
                st.caption("Keywords: " + ", ".join(p.keywords))

    # MANDATORY Indian Kanoon attribution on top of results
    if resp.results and "indian_kanoon" in resp.sources_used:
        st.markdown(
            '<div style="text-align:right"><a href="https://www.indiankanoon.org/" '
            'target="_blank" style="color:#26348c;font-weight:600;text-decoration:none">'
            'powered by <span style="color:#ea7a2b">i</span>kanoon</a></div>',
            unsafe_allow_html=True,
        )

    # Results
    for r in resp.results:
        with st.container(border=True):
            top = st.columns([6, 1])
            title = f"**{r.title}**"
            if r.url:
                title = f"**[{r.title}]({r.url})**"
            top[0].markdown(f"#{r.rank} · {title}")
            top[1].metric("score", r.relevance_score)
            meta = " · ".join(x for x in [r.citation, r.court, r.date] if x)
            if meta:
                st.caption(meta)
            if r.relevance_note:
                st.markdown(f"**Why it matters —** {r.relevance_note}")
            if r.holding:
                st.markdown(f"*Holding —* {r.holding}")
            if r.url:
                st.markdown(f"[Open source →]({r.url})")

    st.divider()
    st.caption(resp.disclaimer + "  ·  Case law via Indian Kanoon.")
