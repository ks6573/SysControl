"""
SysControl — Centralized path resolution.

Resolves repo-relative resource paths and the writable user-data directory.
The user-data directory is *not* created at import time — call
:func:`ensure_user_data_dir` (or write through ``MEMORY_FILE``'s callers
that handle creation themselves) when persistence is actually needed.
"""

import sys
from pathlib import Path

# When frozen by PyInstaller, bundled resources live under ``sys._MEIPASS``
# (the onedir/extraction root), not next to this source file.  Resolve
# read-only resource paths against that root when frozen, and against the repo
# layout for normal source/venv runs.  Writable user data (below) always lives
# in the user's home directory regardless of how the app was launched.
IS_FROZEN = bool(getattr(sys, "frozen", False))
if IS_FROZEN:
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    BASE_DIR = Path(__file__).parent.parent

# ── MCP server / prompt ──────────────────────────────────────────────────────
SERVER_PATH = BASE_DIR / "mcp" / "server.py"
PROMPT_PATH = BASE_DIR / "mcp" / "prompt.json"


def server_spawn_cmd() -> list[str]:
    """Return the argv to launch the MCP server as a child process.

    Source/venv installs run the server script with the current interpreter.
    In a PyInstaller bundle ``sys.executable`` is the frozen app (not a Python
    interpreter), so we re-exec the same executable with a sentinel flag that
    ``flet_app/main.py`` intercepts to run ``mcp.server.main()`` instead of
    launching the GUI — letting one bundled binary serve as both the GUI and
    the spawned MCP server.
    """
    if IS_FROZEN:
        return [sys.executable, "--run-mcp-server"]
    return [sys.executable, str(SERVER_PATH)]

# ── Writable user data ───────────────────────────────────────────────────────
USER_DATA_DIR = Path.home() / ".syscontrol"
MEMORY_FILE = USER_DATA_DIR / "SysControl_Memory.md"
AUTOMATIONS_FILE = USER_DATA_DIR / "automations.json"
AUTOMATION_RUNS_FILE = USER_DATA_DIR / "automation_runs.json"
CONNECTORS_FILE = USER_DATA_DIR / "connectors.json"
AUDIT_LOG_FILE = USER_DATA_DIR / "audit.jsonl"

# Skill / user-command / user-agent definition directories.  Each holds a
# collection of ``*.md`` files with YAML-style frontmatter.  See
# ``agent/skills.py`` for the schema.
SKILLS_DIR = USER_DATA_DIR / "skills"
COMMANDS_DIR = USER_DATA_DIR / "commands"
USER_AGENTS_DIR = USER_DATA_DIR / "agents"

# Bundled-with-source skill definitions (copied to ``SKILLS_DIR`` on first run).
BUILTIN_SKILLS_DIR = BASE_DIR / "agent" / "skills_builtin"


def ensure_user_data_dir() -> None:
    """Create ``~/.syscontrol/`` if missing.  Call before writing user data."""
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)


def ensure_skill_dirs() -> None:
    """Create skill/command/agent directories under ``~/.syscontrol`` if missing."""
    ensure_user_data_dir()
    for directory in (SKILLS_DIR, COMMANDS_DIR, USER_AGENTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
