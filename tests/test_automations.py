"""Tests for persistent scheduled automations and server-side policy."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from agent import automations
from mcp import server


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(automations, "AUTOMATIONS_FILE", tmp_path / "automations.json")
    monkeypatch.setattr(automations, "AUTOMATION_RUNS_FILE", tmp_path / "runs.json")
    monkeypatch.setattr(automations, "ensure_user_data_dir", lambda: tmp_path.mkdir(exist_ok=True))


def test_create_list_claim_and_delete() -> None:
    created = automations.create_automation("Health", "get_system_alerts", {}, 15)
    assert automations.list_automations() == [created]

    future = dt.datetime.fromisoformat(created["next_run"]) + dt.timedelta(seconds=1)
    claimed = automations.due_automations(future)
    assert [item["id"] for item in claimed] == [created["id"]]
    assert automations.due_automations(future) == []

    assert automations.delete_automation(created["id"]) is True
    assert automations.delete_automation(created["id"]) is False


def test_pause_and_resume() -> None:
    created = automations.create_automation("Health", "get_system_alerts", {}, 5)
    paused = automations.set_automation_enabled(created["id"], False)
    assert paused is not None and paused["enabled"] is False
    assert automations.due_automations(dt.datetime.now(dt.UTC) + dt.timedelta(days=1)) == []
    resumed = automations.set_automation_enabled(created["id"], True)
    assert resumed is not None and resumed["enabled"] is True


def test_scheduler_records_success_and_error() -> None:
    created = automations.create_automation("Health", "get_system_alerts", {}, 5)
    scheduler = automations.AutomationScheduler(lambda _tool, _args: {"ok": True})
    run = scheduler.run(created)
    assert run["status"] == "success"
    assert automations.list_runs()[0]["automation_id"] == created["id"]

    failing = automations.AutomationScheduler(
        lambda _tool, _args: {"error": "offline"},
    )
    assert failing.run(created)["status"] == "error"


def test_server_allows_only_read_only_tool_automations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_permission_check", lambda _flag, _tool: None)
    allowed = server.create_scheduled_automation(
        "Health", "get_system_alerts", {}, 60,
    )
    assert allowed["status"] == "created"

    denied = server.create_scheduled_automation(
        "Danger", "run_shell_command", {"command": "true"}, 60,
    )
    assert "read-only" in denied["error"]
