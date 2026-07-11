"""Tests for privacy-preserving audit events and health trend summaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent import audit, automations
from mcp import server


@pytest.fixture(autouse=True)
def _isolated_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit, "AUDIT_LOG_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(audit, "ensure_user_data_dir", lambda: tmp_path.mkdir(exist_ok=True))
    monkeypatch.setattr(automations, "AUTOMATION_RUNS_FILE", tmp_path / "runs.json")
    monkeypatch.setattr(automations, "ensure_user_data_dir", lambda: tmp_path.mkdir(exist_ok=True))


def test_audit_does_not_persist_argument_values(tmp_path: Path) -> None:
    audit.record_tool_call(
        "send_email",
        {"recipient": "person@example.com", "body": "private message"},
        {"status": "sent", "provider_id": "secret-id"},
        risk="write",
    )
    raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "person@example.com" not in raw
    assert "private message" not in raw
    assert "secret-id" not in raw
    event = audit.list_events()[0]
    assert event["argument_keys"] == ["body", "recipient"]
    assert event["status"] == "success"


def test_audit_filter_and_error_summary() -> None:
    audit.record_tool_call("first", {}, {"ok": True}, risk="read")
    audit.record_tool_call("second", {"path": "/private"}, {"error": "denied"}, risk="read")
    events = audit.list_events(tool="second")
    assert len(events) == 1
    assert events[0]["status"] == "error"
    assert events[0]["error"] == "denied"


def test_health_trends_summarize_scheduled_snapshots() -> None:
    automations.record_run({
        "automation_id": "one",
        "automation_name": "Health",
        "tool": "get_full_snapshot",
        "started_at": "2026-07-10T10:00:00+00:00",
        "finished_at": "2026-07-10T10:00:01+00:00",
        "status": "success",
        "result": {
            "cpu": {"total_percent": 20},
            "ram": {"ram": {"percent_used": 40}},
            "disk": {"partitions": [{"percent_used": 60}]},
        },
    })
    automations.record_run({
        "automation_id": "one",
        "automation_name": "Health",
        "tool": "get_full_snapshot",
        "started_at": "2026-07-10T11:00:00+00:00",
        "finished_at": "2026-07-10T11:00:01+00:00",
        "status": "success",
        "result": {
            "cpu": {"total_percent": 40},
            "ram": {"ram": {"percent_used": 50}},
            "disk": {"partitions": [{"percent_used": 70}]},
        },
    })

    trends = server.get_health_trends()

    assert trends["sample_count"] == 2
    assert trends["summary"]["cpu_percent"] == {
        "latest": 40.0, "average": 30.0, "minimum": 20.0, "maximum": 40.0,
    }
