"""Tests for platform, permission, and risk metadata exposed by tools/list."""

from __future__ import annotations

from mcp.server import TOOLS, handle_request
from mcp.tool_capabilities import ALL_PLATFORMS, capability_for


def test_every_tool_has_well_formed_capabilities() -> None:
    for name in TOOLS:
        capability = capability_for(name, platform_name="linux")
        assert capability["category"]
        assert capability["platforms"]
        assert capability["risk"] in {"read", "write", "destructive"}


def test_platform_specific_availability() -> None:
    assert capability_for("send_imessage", platform_name="macos")["available"] is True
    assert capability_for("send_imessage", platform_name="windows")["available"] is False
    assert capability_for("get_cpu_usage", platform_name="linux")["platforms"] == ALL_PLATFORMS


def test_sensitive_tool_metadata() -> None:
    shell = capability_for("run_shell_command", platform_name="linux")
    assert shell["permission"] == "allow_shell"
    assert shell["risk"] == "write"
    delete = capability_for("delete_file", platform_name="linux")
    assert delete["permission"] == "allow_file_write"
    assert delete["risk"] == "destructive"


def test_tools_list_exposes_capability_extensions() -> None:
    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response is not None
    tools = response["result"]["tools"]
    cpu = next(tool for tool in tools if tool["name"] == "get_cpu_usage")
    assert cpu["annotations"]["readOnlyHint"] is True
    assert cpu["_meta"]["syscontrol"]["category"] == "monitoring"
    assert all(tool["_meta"]["syscontrol"]["available"] for tool in tools)
