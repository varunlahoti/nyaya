"""LLM client — provider-abstracted (OpenRouter default, Anthropic optional).

`complete_json()` returns parsed JSON matching a schema, regardless of provider.
Callers (fact_parser, reranker) don't care which model runs underneath.

Provider notes:
  * OpenRouter (default): OpenAI-compatible /chat/completions. Cheap, strong
    models (DeepSeek V3, Gemini Flash, …) at a fraction of frontier cost —
    ideal for dev and cost-controlled prod. We request JSON-object mode and
    embed the schema in the prompt, then parse robustly (works across the widest
    set of cheap models, many of which don't support strict json_schema).
  * Anthropic: uses structured outputs + prompt caching (see git history) when
    LLM_PROVIDER=anthropic.

Design: the reranker (legal judgement) uses the stronger LLM_MODEL; the parser
(lower stakes) uses the cheaper LLM_PARSER_MODEL. Both configurable.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

import httpx

from ..config import settings

logger = logging.getLogger("nyaya.llm")


def available() -> bool:
    return settings.has_llm


async def complete_json(
    *,
    system: str,
    user: str,
    schema: Dict[str, Any],
    model: Optional[str] = None,
    use_thinking: bool = False,   # honoured by the anthropic provider; hint only
    effort: str = "high",
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    if not available():
        raise RuntimeError("No LLM provider configured")

    model = model or settings.LLM_MODEL
    max_tokens = max_tokens or settings.LLM_MAX_TOKENS

    if settings.LLM_PROVIDER == "anthropic":
        return await _anthropic(system, user, schema, model, use_thinking, effort, max_tokens)
    return await _openrouter(system, user, schema, model, max_tokens)


# --------------------------------------------------------------------------- #
# OpenRouter (default) — OpenAI-compatible chat completions
# --------------------------------------------------------------------------- #
async def _openrouter(
    system: str, user: str, schema: Dict[str, Any],
    model: str, max_tokens: int,
) -> Dict[str, Any]:
    # Embed the schema so cheap models return the right shape; ask for JSON only.
    sys_with_schema = (
        f"{system}\n\n"
        f"Respond with a single valid JSON object and NOTHING else "
        f"(no markdown, no code fences). It must conform to this JSON schema:\n"
        f"{json.dumps(schema)}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_with_schema},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,  # deterministic — same prompt gives the same result
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.OPENROUTER_APP_URL,
        "X-Title": settings.OPENROUTER_APP_TITLE,
    }
    url = f"{settings.OPENROUTER_BASE_URL}/chat/completions"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    return _parse_json_lenient(content)


# --------------------------------------------------------------------------- #
# Anthropic (optional) — structured outputs + prompt caching
# --------------------------------------------------------------------------- #
_anthropic_client = None


async def _anthropic(
    system: str, user: str, schema: Dict[str, Any],
    model: str, use_thinking: bool, effort: str, max_tokens: int,
) -> Dict[str, Any]:
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    kwargs: Dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [{"role": "user", "content": user}],
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }
    if use_thinking:
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"]["effort"] = effort

    resp = await _anthropic_client.messages.create(**kwargs)
    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("LLM refused the request")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("LLM returned no text content")
    return _parse_json_lenient(text)


# --------------------------------------------------------------------------- #
def _parse_json_lenient(text: str) -> Dict[str, Any]:
    """Parse JSON, tolerating code fences / stray prose around the object."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown fences.
    fenced = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(fenced.strip())
    except json.JSONDecodeError:
        pass
    # Grab the outermost {...}.
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise RuntimeError("LLM returned unparseable JSON")
