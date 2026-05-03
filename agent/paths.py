"""
SysControl — Centralized path resolution.

Resolves repo-relative resource paths and the writable user-data directory.
The user-data directory is *not* created at import time — call
:func:`ensure_user_data_dir` (or write through ``MEMORY_FILE``'s callers
that handle creation themselves) when persistence is actually needed.
"""

from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

# ── MCP server / prompt ──────────────────────────────────────────────────────
SERVER_PATH = BASE_DIR / "mcp" / "server.py"
PROMPT_PATH = BASE_DIR / "mcp" / "prompt.json"

# ── Writable user data ───────────────────────────────────────────────────────
USER_DATA_DIR = Path.home() / ".syscontrol"
MEMORY_FILE = USER_DATA_DIR / "SysControl_Memory.md"


def ensure_user_data_dir() -> None:
    """Create ``~/.syscontrol/`` if missing.  Call before writing user data."""
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
