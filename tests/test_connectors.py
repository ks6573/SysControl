"""Tests for external stdio MCP connector configuration and routing."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from mcp import connectors

_FAKE_SERVER = '''
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools": [{
            "name": "echo",
            "description": "Echo text",
            "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
        }]}
    elif method == "tools/call":
        text = request.get("params", {}).get("arguments", {}).get("text", "")
        result = {"content": [{"type": "text", "text": text}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connectors, "CONNECTORS_FILE", tmp_path / "connectors.json")
    monkeypatch.setattr(connectors, "ensure_user_data_dir", lambda: tmp_path.mkdir(exist_ok=True))


def test_validate_command_is_shell_free_but_allows_paths_with_spaces() -> None:
    config = connectors.validate_config("github", "/Program Files/MCP/server.exe")
    assert config["command"] == "/Program Files/MCP/server.exe"
    with pytest.raises(ValueError, match="arrays"):
        connectors.validate_config("github", "npx", "--yes")


def test_config_round_trip_and_remove() -> None:
    config = connectors.validate_config(
        "GitHub", "npx", ["-y", "@example/server"], ["GITHUB_TOKEN"],
    )
    connectors.add_config(config)
    assert connectors.list_configs() == [config]
    assert connectors.remove_config("github") is True
    assert connectors.list_configs() == []


def test_connector_environment_is_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("UNRELATED_SECRET", "nope")
    config = connectors.validate_config("github", "npx", inherit_env=["GITHUB_TOKEN"])
    child_env = connectors._connector_env(config)
    assert child_env["GITHUB_TOKEN"] == "secret"
    assert "UNRELATED_SECRET" not in child_env


def test_stdio_connector_and_namespaced_manager(tmp_path: Path) -> None:
    server_file = tmp_path / "fake_mcp.py"
    server_file.write_text(_FAKE_SERVER, encoding="utf-8")
    config = connectors.validate_config("demo", sys.executable, [str(server_file)])
    connectors.add_config(config)

    manager = connectors.ConnectorManager()
    try:
        catalog = manager.tool_catalog()
        assert [tool["name"] for tool in catalog] == ["demo__echo"]
        content = manager.call_tool("demo__echo", {"text": "hello"})
        assert content == [{"type": "text", "text": "hello"}]
    finally:
        manager.refresh()
