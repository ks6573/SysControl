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
