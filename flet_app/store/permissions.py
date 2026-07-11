"""Read/write ``~/.syscontrol/config.json`` permission flags.

This is the SAME file the MCP server reads (with a 5 s TTL cache) and the CLI
writes, so toggles made in the GUI take effect without restarting anything.
"""

from __future__ import annotations

import json

from agent.paths import USER_DATA_DIR, ensure_user_data_dir

CONFIG_FILE = USER_DATA_DIR / "config.json"

# Keep in sync with agent/cli.py:_PERMISSION_FLAGS and the server's tools.
PERMISSION_FLAGS: tuple[str, ...] = (
    "allow_shell", "allow_messaging", "allow_message_history", "allow_screenshot",
    "allow_file_read", "allow_file_write", "allow_calendar", "allow_contacts",
    "allow_accessibility", "allow_tool_creation", "allow_deep_research",
    "allow_email", "allow_notes", "allow_brew", "allow_agents", "allow_clipboard",
    "allow_automations", "allow_connectors",
)


def load_permissions() -> dict[str, bool]:
    """Return the current permission flags (empty dict if no/invalid config)."""
    try:
        # utf-8-sig tolerates a BOM (Windows editors add one).
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: bool(v) for k, v in data.items()}


def set_permission(flag: str, value: bool) -> None:
    """Set a single permission flag, preserving any other keys in the file."""
    data = load_permissions()
    data[flag] = bool(value)
    ensure_user_data_dir()
    CONFIG_FILE.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
