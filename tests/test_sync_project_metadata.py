"""Tests for the derived project-metadata synchronizer."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from scripts.sync_project_metadata import registry_tool_names, synchronized_text


def test_registry_tool_names_reads_literal_registry() -> None:
    source = "TOOLS: dict[str, object] = {'alpha': {}, 'beta': {}}"
    assert registry_tool_names(source) == ("alpha", "beta")


def test_registry_tool_names_rejects_dynamic_keys() -> None:
    source = "name = 'alpha'\nTOOLS: dict[str, object] = {name: {}}"
    try:
        registry_tool_names(source)
    except ValueError as exc:
        assert "literal string" in str(exc)
    else:
        raise AssertionError("dynamic registry key should be rejected")


def test_synchronized_text_updates_count() -> None:
    pattern = re.compile(r"access to \d+ live tools")
    assert synchronized_text("access to 92 live tools", pattern, "access to {count} live tools", 104) == (
        "access to 104 live tools"
    )


def test_repository_metadata_is_synchronized() -> None:
    root = Path(__file__).resolve().parents[1]
    namespace: dict[str, object] = {}
    # Verify the script itself remains valid Python without importing mcp.server.
    ast.parse((root / "scripts" / "sync_project_metadata.py").read_text(encoding="utf-8"))
    exec("from scripts.sync_project_metadata import sync", namespace)
    assert namespace["sync"](write=False) == []
