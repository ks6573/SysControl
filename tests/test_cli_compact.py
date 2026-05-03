"""Tests for agent/cli_compact.py — atomic swap + undo."""

from dataclasses import dataclass
from typing import Any

import openai

from agent import cli_compact


@dataclass
class _StubChoice:
    message: Any


@dataclass
class _StubResponse:
    choices: list[_StubChoice]


class _StubClient:
    """Minimal OpenAI stub for compact()."""

    def __init__(self, *, summary: str | None = None, raise_exc: Exception | None = None) -> None:
        self._summary = summary
        self._raise = raise_exc

        class _Chat:
            class completions:  # noqa: N801
                @staticmethod
                def create(**_kwargs: Any) -> _StubResponse:
                    if self._raise:
                        raise self._raise
                    msg = type("M", (), {"content": self._summary})()
                    return _StubResponse(choices=[_StubChoice(message=msg)])

        self.chat = _Chat()


@dataclass
class _Ctx:
    """Minimal ReplContext stand-in (compact only touches a few fields)."""
    messages: list[dict]
    model: str = "test-model"
    compact_undo: list[dict] | None = None
    ollama_client: Any = None


def _make_messages(n: int) -> list[dict]:
    msgs = []
    for i in range(n):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    return msgs


def test_compact_too_short_does_not_mutate() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    ctx = _Ctx(messages=msgs[:], ollama_client=_StubClient(summary="ignored"))
    ok, info = cli_compact.compact(ctx)
    assert ok is False
    assert "too short" in info.lower()
    assert ctx.messages == msgs


def test_compact_swaps_and_stashes_undo() -> None:
    original = _make_messages(5)
    ctx = _Ctx(messages=original[:], ollama_client=_StubClient(summary="The conversation covered X, Y, Z."))
    ok, info = cli_compact.compact(ctx)
    assert ok is True
    assert "X, Y, Z" in info
    assert ctx.compact_undo == original
    # New history: 1 system summary + last user + last assistant.
    assert len(ctx.messages) == 3
    assert ctx.messages[0]["role"] == "system"
    assert "<prior conversation summary>" in ctx.messages[0]["content"]


def test_compact_failure_leaves_messages_untouched() -> None:
    original = _make_messages(5)
    ctx = _Ctx(
        messages=original[:],
        ollama_client=_StubClient(raise_exc=openai.OpenAIError("network down")),
    )
    ok, info = cli_compact.compact(ctx)
    assert ok is False
    assert "network down" in info
    assert ctx.messages == original
    assert ctx.compact_undo is None


def test_compact_empty_summary_treated_as_failure() -> None:
    original = _make_messages(5)
    ctx = _Ctx(messages=original[:], ollama_client=_StubClient(summary=""))
    ok, info = cli_compact.compact(ctx)
    assert ok is False
    assert "no text" in info.lower()
    assert ctx.messages == original


def test_undo_restores_prior_history() -> None:
    original = _make_messages(5)
    ctx = _Ctx(messages=original[:], ollama_client=_StubClient(summary="ok"))
    cli_compact.compact(ctx)
    assert cli_compact.undo(ctx) is True
    assert ctx.messages == original
    assert ctx.compact_undo is None


def test_undo_returns_false_with_no_snapshot() -> None:
    ctx = _Ctx(messages=[], ollama_client=_StubClient(summary="ok"))
    assert cli_compact.undo(ctx) is False
