"""Privacy-preserving local audit log for tool execution."""

from __future__ import annotations

import datetime as dt
import json
import threading
from typing import Any, TypedDict

from agent.paths import AUDIT_LOG_FILE, ensure_user_data_dir

MAX_AUDIT_BYTES = 2 * 1024 * 1024
MAX_RETAINED_EVENTS = 2_000


class AuditEvent(TypedDict):
    timestamp: str
    tool: str
    source: str
    risk: str
    argument_keys: list[str]
    status: str
    error: str | None


_LOCK = threading.Lock()


def _event_error(result: Any) -> str | None:
    if isinstance(result, dict) and "error" in result:
        return str(result["error"])[:300]
    return None


def record_tool_call(
    tool: str,
    arguments: dict[str, Any],
    result: Any,
    *,
    risk: str,
    source: str = "chat",
) -> None:
    """Append a tool event without persisting argument or result values."""
    event: AuditEvent = {
        "timestamp": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "tool": tool,
        "source": source,
        "risk": risk,
        "argument_keys": sorted(str(key) for key in arguments),
        "status": "error" if _event_error(result) else "success",
        "error": _event_error(result),
    }
    try:
        ensure_user_data_dir()
        with _LOCK:
            with AUDIT_LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
            if AUDIT_LOG_FILE.stat().st_size > MAX_AUDIT_BYTES:
                _trim_log()
    except OSError:
        # Auditing is best-effort and must never break the requested tool call.
        return


def _trim_log() -> None:
    """Keep the newest bounded set of events. Must be called under ``_LOCK``."""
    try:
        lines = AUDIT_LOG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    retained = lines[-MAX_RETAINED_EVENTS:]
    temporary = AUDIT_LOG_FILE.with_suffix(".jsonl.tmp")
    temporary.write_text("\n".join(retained) + "\n", encoding="utf-8")
    temporary.replace(AUDIT_LOG_FILE)


def list_events(limit: int = 100, tool: str = "") -> list[AuditEvent]:
    """Return newest audit events, optionally filtered by exact tool name."""
    bounded = max(1, min(int(limit), 500))
    try:
        lines = AUDIT_LOG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[AuditEvent] = []
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict) or (tool and value.get("tool") != tool):
            continue
        events.append(value)  # type: ignore[arg-type]
        if len(events) >= bounded:
            break
    return events
