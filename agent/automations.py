"""Persistent, bounded scheduler for local SysControl tool automations.

The scheduler is deliberately execution-agnostic: the MCP server supplies the
tool callback and enforces tool risk/permission policy before an automation is
created.  Advancing ``next_run`` before execution prevents duplicate runs if a
tool is slow or the scheduler is polled concurrently.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict, cast

from agent.paths import AUTOMATION_RUNS_FILE, AUTOMATIONS_FILE, ensure_user_data_dir

MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 7 * 24 * 60
MAX_AUTOMATIONS = 100
MAX_RUN_HISTORY = 500


class Automation(TypedDict):
    id: str
    name: str
    tool: str
    arguments: dict[str, Any]
    interval_minutes: int
    enabled: bool
    created_at: str
    next_run: str


class AutomationRun(TypedDict):
    automation_id: str
    automation_name: str
    tool: str
    started_at: str
    finished_at: str
    status: str
    result: Any


_LOCK = threading.Lock()


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat(timespec="seconds")


def _read_list(path: Path) -> list[dict[str, Any]]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return loaded if isinstance(loaded, list) else []


def _write_list(path: Path, values: list[dict[str, Any]]) -> None:
    ensure_user_data_dir()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(values, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def list_automations() -> list[Automation]:
    """Return all persisted automations sorted by creation time."""
    with _LOCK:
        values = _read_list(AUTOMATIONS_FILE)
    return [value for value in values if _valid_automation(value)]  # type: ignore[misc]


def _valid_automation(value: dict[str, Any]) -> bool:
    required = {"id", "name", "tool", "arguments", "interval_minutes", "next_run"}
    return required.issubset(value) and isinstance(value.get("arguments"), dict)


def create_automation(
    name: str,
    tool: str,
    arguments: dict[str, Any],
    interval_minutes: int,
) -> Automation:
    """Persist a recurring automation and return its normalized record."""
    interval = max(MIN_INTERVAL_MINUTES, min(int(interval_minutes), MAX_INTERVAL_MINUTES))
    now = _now_utc()
    automation: Automation = {
        "id": uuid.uuid4().hex[:12],
        "name": name.strip()[:120] or f"Run {tool}",
        "tool": tool,
        "arguments": arguments,
        "interval_minutes": interval,
        "enabled": True,
        "created_at": _iso(now),
        "next_run": _iso(now + dt.timedelta(minutes=interval)),
    }
    with _LOCK:
        values = _read_list(AUTOMATIONS_FILE)
        if len(values) >= MAX_AUTOMATIONS:
            raise ValueError(f"automation limit reached ({MAX_AUTOMATIONS})")
        values.append(dict(automation))
        _write_list(AUTOMATIONS_FILE, values)
    return automation


def delete_automation(automation_id: str) -> bool:
    """Delete one automation by ID and report whether it existed."""
    with _LOCK:
        values = _read_list(AUTOMATIONS_FILE)
        survivors = [value for value in values if value.get("id") != automation_id]
        if len(survivors) == len(values):
            return False
        _write_list(AUTOMATIONS_FILE, survivors)
    return True


def set_automation_enabled(automation_id: str, enabled: bool) -> Automation | None:
    """Enable or pause an automation and return the updated record."""
    with _LOCK:
        values = _read_list(AUTOMATIONS_FILE)
        updated: Automation | None = None
        for value in values:
            if value.get("id") != automation_id:
                continue
            value["enabled"] = bool(enabled)
            if enabled:
                interval = int(value.get("interval_minutes", MIN_INTERVAL_MINUTES))
                value["next_run"] = _iso(_now_utc() + dt.timedelta(minutes=interval))
            updated = value  # type: ignore[assignment]
            break
        if updated is not None:
            _write_list(AUTOMATIONS_FILE, values)
    return updated


def due_automations(now: dt.datetime | None = None) -> list[Automation]:
    """Claim due automations and advance their next-run timestamps atomically."""
    current = (now or _now_utc()).astimezone(dt.UTC)
    claimed: list[Automation] = []
    with _LOCK:
        values = _read_list(AUTOMATIONS_FILE)
        changed = False
        for value in values:
            if not _valid_automation(value) or value.get("enabled") is False:
                continue
            try:
                next_run = dt.datetime.fromisoformat(str(value["next_run"]))
            except ValueError:
                continue
            if next_run.astimezone(dt.UTC) > current:
                continue
            interval = max(MIN_INTERVAL_MINUTES, int(value["interval_minutes"]))
            value["next_run"] = _iso(current + dt.timedelta(minutes=interval))
            claimed.append(dict(value))  # type: ignore[arg-type]
            changed = True
        if changed:
            _write_list(AUTOMATIONS_FILE, values)
    return claimed


def record_run(run: AutomationRun) -> None:
    """Append a bounded automation run record."""
    with _LOCK:
        values = _read_list(AUTOMATION_RUNS_FILE)
        values.append(dict(run))
        _write_list(AUTOMATION_RUNS_FILE, values[-MAX_RUN_HISTORY:])


def list_runs(limit: int = 50) -> list[AutomationRun]:
    """Return newest automation runs first."""
    bounded = max(1, min(int(limit), 200))
    with _LOCK:
        values = _read_list(AUTOMATION_RUNS_FILE)
    return [cast(AutomationRun, value) for value in reversed(values[-bounded:])]


class AutomationScheduler:
    """Daemon scheduler that executes claimed automations through a callback."""

    def __init__(
        self,
        execute: Callable[[str, dict[str, Any]], Any],
        on_failure: Callable[[Automation, str], None] | None = None,
    ) -> None:
        self._execute = execute
        self._on_failure = on_failure
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="syscontrol-automations",
        )

    def start(self) -> None:
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(timeout=15.0):
            for automation in due_automations():
                self.run(automation)

    def run(self, automation: Automation) -> AutomationRun:
        """Execute one automation, record the result, and return its run record."""
        started = _now_utc()
        status = "success"
        try:
            result = self._execute(automation["tool"], automation["arguments"])
            if isinstance(result, dict) and "error" in result:
                status = "error"
        except Exception as exc:  # callback boundary; error is persisted for diagnosis
            status = "error"
            result = {"error": str(exc)}
        finished = _now_utc()
        run: AutomationRun = {
            "automation_id": automation["id"],
            "automation_name": automation["name"],
            "tool": automation["tool"],
            "started_at": _iso(started),
            "finished_at": _iso(finished),
            "status": status,
            "result": result,
        }
        record_run(run)
        if status == "error" and self._on_failure is not None:
            self._on_failure(automation, str(result))
        return run
