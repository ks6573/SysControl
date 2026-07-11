"""Tests for custom OpenAI-compatible CLI provider selection."""

from __future__ import annotations

import argparse

import pytest

from agent.cli import _custom_selection


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "base_url": "https://provider.example/v1",
        "model": "tool-model",
        "api_key": "sk-custom",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_custom_provider_selection() -> None:
    selection = _custom_selection(_args())
    assert selection.base_url == "https://provider.example/v1"
    assert selection.model == "tool-model"
    assert selection.api_key == "sk-custom"


def test_custom_provider_allows_keyless_endpoint() -> None:
    selection = _custom_selection(_args(api_key=""))
    assert selection.api_key == "not-required"


def test_custom_provider_rejects_non_http_url() -> None:
    with pytest.raises(SystemExit) as exc:
        _custom_selection(_args(base_url="file:///tmp/socket"))
    assert exc.value.code == 1
