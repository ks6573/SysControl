"""
SysControl — Centralized path resolution.

Provides frozen-app-aware paths so that both normal ``python gui.py``
invocations and PyInstaller-bundled ``.app`` builds resolve resources
correctly.
"""

import sys
from pathlib import Path


def _base_dir() -> Path:
    """Return the project root directory.

    When running from source, this is the repo root (one level above agent/).
    When running inside a PyInstaller bundle, this is the temporary
    extraction directory (``sys._MEIPASS``).
    """
    if getattr(sys, "frozen", False):
        # PyInstaller stores extracted data files here
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent.parent


BASE_DIR = _base_dir()

# ── MCP server / prompt ──────────────────────────────────────────────────────
SERVER_PATH = BASE_DIR / "mcp" / "server.py"
PROMPT_PATH = BASE_DIR / "mcp" / "prompt.json"

# ── Writable user data (must NOT point inside the frozen bundle) ─────────────
_USER_DATA_DIR = Path.home() / ".syscontrol"
_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

MEMORY_FILE = _USER_DATA_DIR / "SysControl_Memory.md"
