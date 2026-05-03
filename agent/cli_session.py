"""
Interactive-CLI session persistence.

Stores full conversation transcripts (including tool_calls) as JSON under
``~/.syscontrol/cli_sessions/``.  Used by ``--continue`` / ``--resume``.
The Swift app keeps a separate, lossy markdown log under
``~/.syscontrol/chat_history/`` — the two stores are intentionally
independent because Markdown can't round-trip OpenAI tool_calls.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from agent.paths import USER_DATA_DIR, ensure_user_data_dir

SCHEMA_VERSION = 1
SESSIONS_DIR: Path = USER_DATA_DIR / "cli_sessions"
ROLLING_CAP = 50  # keep most recent N sessions on disk


@dataclass(frozen=True)
class SessionSummary:
    path: Path
    started_at: str
    last_active: str
    model: str
    provider_label: str
    cli_mode: str
    message_count: int
    first_user_text: str


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def _new_session_filename() -> str:
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}.json"


def _atomic_write(path: Path, payload: dict) -> None:
    ensure_user_data_dir()
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(SESSIONS_DIR), prefix=".session-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=False)
            f.write("\n")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except (OSError, json.JSONDecodeError):
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def save(
    *,
    messages: list[dict],
    model: str,
    provider_label: str,
    cli_mode: str,
    approval_mode: str | None,
    session_path: Path | None,
    started_at: str | None = None,
) -> Path:
    """Persist the active conversation; returns the path written."""
    path = session_path or (SESSIONS_DIR / _new_session_filename())
    payload = {
        "version": SCHEMA_VERSION,
        "started_at": started_at or _now_iso(),
        "last_active": _now_iso(),
        "model": model,
        "provider_label": provider_label,
        "cli_mode": cli_mode,
        "approval_mode": approval_mode,
        "messages": messages,
    }
    _atomic_write(path, payload)
    _prune(ROLLING_CAP)
    return path


def _prune(keep: int) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        (p for p in SESSIONS_DIR.glob("*.json") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            continue


def list_sessions(limit: int = 20) -> list[SessionSummary]:
    """Return up to *limit* sessions, newest first, with summary metadata."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    paths = sorted(
        (p for p in SESSIONS_DIR.glob("*.json") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]
    out: list[SessionSummary] = []
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        first_user = next(
            (m.get("content", "") for m in data.get("messages", []) if m.get("role") == "user"),
            "",
        )
        out.append(SessionSummary(
            path=p,
            started_at=data.get("started_at", ""),
            last_active=data.get("last_active", ""),
            model=data.get("model", ""),
            provider_label=data.get("provider_label", ""),
            cli_mode=data.get("cli_mode", ""),
            message_count=len(data.get("messages", [])),
            first_user_text=str(first_user or "").splitlines()[0][:80] if first_user else "",
        ))
    return out


def load(path: Path) -> dict:
    """Read a session file; raises ``ValueError`` on a schema mismatch."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Session payload must be a JSON object")
    if raw.get("version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported session version {raw.get('version')!r}")
    return raw


def load_latest() -> dict | None:
    """Return the most recently active session, or ``None`` if there is none."""
    sessions = list_sessions(limit=1)
    if not sessions:
        return None
    return load(sessions[0].path)


def pick_interactive() -> dict | None:
    """Prompt the user to pick a session.  Returns the loaded payload or ``None``."""
    sessions = list_sessions()
    if not sessions:
        return None

    if not sys.stdout.isatty():
        return _pick_numbered(sessions)

    try:
        from prompt_toolkit.shortcuts import radiolist_dialog
    except ImportError:
        return _pick_numbered(sessions)

    values = [
        (
            s.path,
            f"{s.last_active}  ·  {s.model}  ·  {s.message_count} msgs  ·  {s.first_user_text or '(no user msgs)'}",
        )
        for s in sessions
    ]
    chosen = radiolist_dialog(
        title="Resume which session?",
        text="Use ↑/↓ to navigate, Enter to confirm, Ctrl-C to cancel.",
        values=values,
    ).run()
    if chosen is None:
        return None
    return load(chosen)


def _pick_numbered(sessions: list[SessionSummary]) -> dict | None:
    print("Recent sessions:")
    for i, s in enumerate(sessions, start=1):
        print(f"  [{i:>2}]  {s.last_active}  {s.model:<14}  {s.message_count:>3} msgs  {s.first_user_text}")
    try:
        raw = input("Pick a session number (or blank to skip): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw:
        return None
    try:
        idx = int(raw) - 1
    except ValueError:
        return None
    if not 0 <= idx < len(sessions):
        return None
    return load(sessions[idx].path)
