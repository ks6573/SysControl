"""Constants, LLM call helpers, and JSON extraction for the deep-research pipeline."""

from __future__ import annotations

import json
import logging
import re

from openai import OpenAI

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_RESEARCH_LOOPS = 5
MAX_SOURCES = 15
MAX_SEARCH_RESULTS = 8
MAX_PAGE_CHARS = 6000
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 4096

# Source-type trustworthiness scores (higher = more reliable).
SOURCE_TYPE_SCORES: dict[str, float] = {
    "official": 0.95,
    "paper": 0.90,
    "dataset": 0.85,
    "news": 0.75,
    "blog": 0.50,
    "forum": 0.30,
    "unknown": 0.40,
}

log = logging.getLogger("deep_research")

# ── LLM helpers ───────────────────────────────────────────────────────────────


class LLMCallError(RuntimeError):
    """Raised when a deep-research LLM call fails (timeout, auth, transport)."""


def llm_call(client: OpenAI, model: str, system: str, user: str) -> str:
    """Make a non-streaming LLM call and return the response text.

    Raises:
        LLMCallError: Wraps the underlying OpenAI exception so callers can
            distinguish "model produced empty content" from "API failed".  The
            orchestrator decides whether to abort or continue with a fallback.
    """
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
    except Exception as exc:
        log.warning("LLM call failed: %s", exc)
        raise LLMCallError(str(exc)) from exc
    if not resp.choices:
        log.warning("LLM returned no choices")
        return ""
    return resp.choices[0].message.content or ""


def llm_json(client: OpenAI, model: str, system: str, user: str) -> dict:
    """Make an LLM call and extract JSON from the response.

    Falls back to an empty dict if extraction fails or the call raises.
    """
    try:
        text = llm_call(client, model, system, user)
    except LLMCallError:
        return {}
    if not text:
        return {}
    return extract_json(text)


# ── JSON extraction ──────────────────────────────────────────────────────────

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict:
    """Best-effort JSON extraction from LLM output.

    Tries, in order: direct parse, markdown code fences, bare ``{…}`` scan.
    """
    text = text.strip()

    # 1. Direct parse
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else {"data": result}
    except json.JSONDecodeError:
        pass

    # 2. Markdown ```json ... ``` block
    match = _JSON_FENCE_RE.search(text)
    if match:
        try:
            result = json.loads(match.group(1).strip())
            return result if isinstance(result, dict) else {"data": result}
        except json.JSONDecodeError:
            pass

    # 3. First balanced { ... }
    start = text.find("{")
    if start >= 0:
        end = text.rfind("}")
        if end > start:
            try:
                result = json.loads(text[start : end + 1])
                return result if isinstance(result, dict) else {"data": result}
            except json.JSONDecodeError:
                pass

    return {}
