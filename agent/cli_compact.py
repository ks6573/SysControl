"""
Conversation compaction helper for the CLI.

A single non-streaming LLM call summarizes prior turns; on success the
existing message list is replaced by ``[summary, last user, last assistant]``
and the original list is stashed for ``/compact undo``.  On any failure the
original list is left untouched — partial mutation must never happen.
"""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING

import openai

if TYPE_CHECKING:
    from agent.cli import ReplContext

_SYSTEM_PROMPT = (
    "You are a senior engineer summarizing an in-progress technical conversation "
    "so it fits a smaller context window. Preserve verbatim: every file path, "
    "decision made, open question, and any error messages. Drop repeated tool "
    "output. Aim for ~300 words. Output plain text — no headings, no preamble."
)
_MAX_HISTORY_CHARS = 60_000


def _serialize_history(messages: list[dict]) -> str:
    truncated = []
    used = 0
    for m in messages:
        chunk = json.dumps({"role": m.get("role"), "content": m.get("content")}, ensure_ascii=False)
        if used + len(chunk) > _MAX_HISTORY_CHARS:
            break
        truncated.append(chunk)
        used += len(chunk)
    return "\n".join(truncated)


def compact(ctx: ReplContext) -> tuple[bool, str]:
    """Summarize ``ctx.messages`` and replace it on success.

    Returns ``(ok, info)`` — *info* is the summary on success, or an error
    message on failure.  ``ctx.messages`` is mutated only when ``ok`` is True.
    """
    if len(ctx.messages) < 4:
        return False, "Conversation is too short to compact."

    history = _serialize_history(ctx.messages)
    try:
        response = ctx.ollama_client.chat.completions.create(
            model=ctx.model,
            stream=False,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": history},
            ],
        )
    except openai.OpenAIError as exc:
        return False, f"LLM summarization failed: {exc}"

    summary = ""
    if response.choices:
        summary = (response.choices[0].message.content or "").strip()
    if not summary:
        return False, "Summarizer returned no text."

    last_user = next(
        (m for m in reversed(ctx.messages) if m.get("role") == "user"), None,
    )
    last_assistant = next(
        (m for m in reversed(ctx.messages) if m.get("role") == "assistant"), None,
    )

    ctx.compact_undo = copy.deepcopy(ctx.messages)
    new_history: list[dict] = [{"role": "system", "content": f"<prior conversation summary>\n{summary}"}]
    if last_user:
        new_history.append(last_user)
    if last_assistant:
        new_history.append(last_assistant)
    ctx.messages.clear()
    ctx.messages.extend(new_history)
    return True, summary


def undo(ctx: ReplContext) -> bool:
    """Restore the pre-compact message list, if one is stashed."""
    if not ctx.compact_undo:
        return False
    ctx.messages.clear()
    ctx.messages.extend(ctx.compact_undo)
    ctx.compact_undo = None
    return True
