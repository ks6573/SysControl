"""Persist GUI chat sessions to ``~/.syscontrol/gui_chats/``.

One JSON file per session (``<id>.json``).  Mirrors the atomic-write idiom from
``agent/cli_session.py`` and the per-session-file layout of the macOS app's
PersistenceManager, but keeps its own directory — the stores are intentionally
independent across the CLI, the SwiftUI app, and this GUI.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

from agent.paths import USER_DATA_DIR, ensure_user_data_dir
from flet_app.models import GuiSession

SESSIONS_DIR: Path = USER_DATA_DIR / "gui_chats"
MAX_SESSIONS = 200


def _ensure_dir() -> None:
    ensure_user_data_dir()
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def save_session(session: GuiSession) -> None:
    """Atomically write *session* to disk (temp file + os.replace)."""
    _ensure_dir()
    fd, tmp = tempfile.mkstemp(dir=str(SESSIONS_DIR), prefix=".gui-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(session.to_dict(), fh, indent=2)
        os.replace(tmp, SESSIONS_DIR / f"{session.id}.json")
    except (OSError, TypeError):
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def load_session(session_id: str) -> GuiSession | None:
    path = SESSIONS_DIR / f"{session_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return GuiSession.from_dict(data)


def list_sessions() -> list[GuiSession]:
    """Return all saved sessions, newest-updated first."""
    if not SESSIONS_DIR.exists():
        return []
    out: list[GuiSession] = []
    for p in SESSIONS_DIR.glob("*.json"):
        if p.name.startswith((".", "_")):
            continue
        try:
            out.append(GuiSession.from_dict(json.loads(p.read_text(encoding="utf-8-sig"))))
        except (json.JSONDecodeError, OSError):
            continue
    out.sort(key=lambda s: s.updated_at, reverse=True)
    return out


def delete_session(session_id: str) -> None:
    with contextlib.suppress(OSError):
        (SESSIONS_DIR / f"{session_id}.json").unlink()


def prune(max_sessions: int = MAX_SESSIONS) -> None:
    """Trim the oldest unpinned sessions beyond *max_sessions*."""
    for stale in list_sessions()[max_sessions:]:
        if not stale.pinned:
            delete_session(stale.id)
