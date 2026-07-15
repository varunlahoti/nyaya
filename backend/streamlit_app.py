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
import html as _html  # noqa: E402

# --- Theme / CSS ---------------------------------------------------------- #
st.markdown(
    """
    <style>
      .stApp {
        background:
          radial-gradient(1200px 500px at 50% -10%, #efe9dd 0%, transparent 60%),
          #f7f4ee;
      }
      #MainMenu, footer, [data-testid="stToolbar"] {visibility: hidden;}
      .block-container {padding-top: 2.2rem; max-width: 820px;}
      h1, h2, h3 {font-family: Georgia, 'Times New Roman', serif;}
      /* header */
      .nyaya-hero {text-align:center; margin-bottom: 0.4rem;}
      .nyaya-logo {font-family:Georgia,serif; font-size:2.5rem; font-weight:700; color:#1a1f2e;}
      .nyaya-logo span {color:#b3873f;}
      .nyaya-sub {color:#233043; opacity:.78; max-width:560px; margin:.4rem auto 0; line-height:1.5;}
      /* primary button -> navy */
      .stButton button[kind="primary"] {background:#233043 !important; border:0 !important; color:#f7f4ee !important;}
      .stButton button[kind="primary"]:hover {background:#1a1f2e !important;}
      /* result card */
      .nyaya-card {background:rgba(255,255,255,.86); border:1px solid rgba(0,0,0,.10);
        border-radius:14px; padding:16px 20px; margin-bottom:14px;
        box-shadow:0 1px 3px rgba(0,0,0,.05);}
      .nyaya-badge {float:right; display:inline-grid; place-items:center; width:44px; height:44px;
        border-radius:50%; color:#fff; font-weight:700; font-size:.95rem; margin-left:12px;}
      .nyaya-rank {display:inline-block; background:rgba(35,48,67,.10); color:#233043;
        border-radius:6px; padding:1px 8px; font-size:.75rem; font-weight:600; margin-right:6px;}
      .nyaya-title {font-family:Georgia,serif; font-size:1.14rem; font-weight:700; color:#1a1f2e; margin-top:2px;}
      .nyaya-title a {color:#1a1f2e; text-decoration:none;}
      .nyaya-title a:hover {color:#b3873f; text-decoration:underline;}
      .nyaya-cite {color:#233043; opacity:.75; font-size:.82rem; margin-top:2px;}
      .nyaya-why {margin-top:10px; color:#1a1f2e; line-height:1.5;}
      .nyaya-why b {color:#b3873f;}
      .nyaya-hold {margin-top:6px; color:rgba(26,31,46,.72); font-size:.9rem; line-height:1.5;}
      .nyaya-src {margin-top:8px; font-size:.8rem;}
      .nyaya-src a {color:#b3873f; font-weight:600; text-decoration:none;}
      .nyaya-attr {text-align:right; margin:6px 0 2px;}
      .nyaya-attr a {color:#26348c; font-weight:700; text-decoration:none; font-size:.95rem;}
      .nyaya-attr a span {color:#ea7a2b;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="nyaya-hero">'
    '<div class="nyaya-logo">Nyaya <span>न्याय</span></div>'
    '<div class="nyaya-sub">Type the facts of your case in plain language. Get the '
    "judgments that matter — from the Supreme Court, High Courts and Indian Kanoon — "
    'each with a source link and why it&rsquo;s relevant.</div></div>',
    unsafe_allow_html=True,
)

# --- Search form ---------------------------------------------------------- #
if "facts_input" not in st.session_state:
    st.session_state["facts_input"] = ""

facts = st.text_area(
    "Facts of the case", height=170, key="facts_input",
    placeholder="e.g. My client is a tenant facing eviction. The landlord…",
)
sc1, sc2 = st.columns([1, 3])
if sc1.button("Try a sample"):
    st.session_state["facts_input"] = SAMPLE
    st.rerun()
sc2.markdown(
    f"<div style='text-align:right; color:#233043; opacity:.6; font-size:.8rem; padding-top:8px'>"
    f"Searches left today: {_quota_remaining()} / {MAX_SEARCHES_PER_DAY}</div>",
    unsafe_allow_html=True,
)

col1, col2, col3 = st.columns([3, 2, 2])
court_level = col1.selectbox(
    "Judgments from", ["any", "supreme_court", "high_court"],
    format_func=lambda v: {"any": "All courts", "supreme_court": "Supreme Court only",
                           "high_court": "High Courts only"}[v],
)
max_results = col2.selectbox("Results", [5, 8, 10], index=1,
                             format_func=lambda n: f"{n} judgments")
with col3:
    st.write("")
    deep = st.checkbox("Deep mode", help="Rank on full judgment text — higher "
                                         "quality, uses more Indian Kanoon credits.")

go = st.button("🔎  Find relevant judgments", type="primary", use_container_width=True)


def _score_color(s: int) -> str:
    if s >= 80:
        return "#2f7d4f"
    if s >= 60:
        return "#b3873f"
    return "#8a8a8a"


def _render_card(r) -> str:
    title = _html.escape(r.title or "")
    if r.url:
        title = f'<a href="{_html.escape(r.url)}" target="_blank">{title}</a>'
    meta = " · ".join(_html.escape(x) for x in [r.citation, r.court, r.date] if x)
    parts = [
        '<div class="nyaya-card">',
        f'<span class="nyaya-badge" style="background:{_score_color(r.relevance_score)}">'
        f'{r.relevance_score}</span>',
        f'<div class="nyaya-title"><span class="nyaya-rank">#{r.rank}</span>{title}</div>',
    ]
    if meta:
        parts.append(f'<div class="nyaya-cite">{meta}</div>')
    if r.relevance_note:
        parts.append(f'<div class="nyaya-why"><b>Why it matters —</b> '
                     f'{_html.escape(r.relevance_note)}</div>')
    if r.holding:
        parts.append(f'<div class="nyaya-hold"><i>Holding —</i> {_html.escape(r.holding)}</div>')
    if r.url:
        parts.append(f'<div class="nyaya-src"><a href="{_html.escape(r.url)}" '
                     f'target="_blank">Open source →</a></div>')
    parts.append("</div>")
    return "".join(parts)


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

    st.markdown(
        f"<div style='color:#233043; opacity:.6; font-size:.8rem; margin-top:10px'>"
        f"{len(resp.results)} judgments · {resp.latency_ms} ms · "
        f"sources: {', '.join(resp.sources_used) or 'none'}"
        + (" · cached" if resp.cached else "")
        + (" · partial" if resp.partial else "") + "</div>",
        unsafe_allow_html=True,
    )
    if resp.notice:
        st.warning(resp.notice)

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
            '<div class="nyaya-attr"><a href="https://www.indiankanoon.org/" target="_blank">'
            'powered by <span>i</span>kanoon</a></div>',
            unsafe_allow_html=True,
        )

    for r in resp.results:
        st.markdown(_render_card(r), unsafe_allow_html=True)

    st.markdown(
        f"<div style='text-align:center; color:#233043; opacity:.55; font-size:.78rem; "
        f"margin-top:18px'>{_html.escape(resp.disclaimer)} · Case law via Indian Kanoon.</div>",
        unsafe_allow_html=True,
    )
