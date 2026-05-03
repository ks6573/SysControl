"""Tests for agent/cli_session.py — JSON round-trip, atomic write, pruning."""

import json
from pathlib import Path

import pytest

from agent import cli_session


@pytest.fixture(autouse=True)
def _isolated_sessions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "cli_sessions"
    target.mkdir()
    monkeypatch.setattr(cli_session, "SESSIONS_DIR", target)
    monkeypatch.setattr(cli_session, "ensure_user_data_dir", lambda: tmp_path.mkdir(exist_ok=True))
    return target


def test_save_round_trip(_isolated_sessions_dir: Path) -> None:
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    path = cli_session.save(
        messages=msgs, model="qwen3:30b", provider_label="⚙ Local",
        cli_mode="system", approval_mode=None, session_path=None,
    )
    payload = cli_session.load(path)
    assert payload["messages"] == msgs
    assert payload["model"] == "qwen3:30b"
    assert payload["version"] == cli_session.SCHEMA_VERSION


def test_save_uses_existing_path(_isolated_sessions_dir: Path) -> None:
    first = cli_session.save(
        messages=[{"role": "user", "content": "a"}],
        model="m", provider_label="p", cli_mode="system",
        approval_mode=None, session_path=None,
    )
    second = cli_session.save(
        messages=[{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}],
        model="m", provider_label="p", cli_mode="system",
        approval_mode=None, session_path=first,
    )
    assert first == second
    payload = cli_session.load(first)
    assert len(payload["messages"]) == 2


def test_save_writes_with_owner_only_perms(_isolated_sessions_dir: Path) -> None:
    path = cli_session.save(
        messages=[], model="m", provider_label="p", cli_mode="system",
        approval_mode=None, session_path=None,
    )
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_atomic_write_leaves_no_temp_files(_isolated_sessions_dir: Path) -> None:
    cli_session.save(
        messages=[{"role": "user", "content": "x"}],
        model="m", provider_label="p", cli_mode="system",
        approval_mode=None, session_path=None,
    )
    leftover = list(_isolated_sessions_dir.glob(".session-*.tmp"))
    assert leftover == []


def test_list_sessions_orders_newest_first(_isolated_sessions_dir: Path) -> None:
    p1 = cli_session.save(
        messages=[{"role": "user", "content": "first"}],
        model="m", provider_label="p", cli_mode="system",
        approval_mode=None, session_path=None,
    )
    # Force second mtime to be newer.
    import os
    import time
    os.utime(p1, (time.time() - 60, time.time() - 60))
    p2 = cli_session.save(
        messages=[{"role": "user", "content": "second"}],
        model="m", provider_label="p", cli_mode="system",
        approval_mode=None, session_path=None,
    )
    summaries = cli_session.list_sessions()
    assert summaries[0].path == p2
    assert summaries[0].first_user_text == "second"


def test_load_rejects_unknown_schema(_isolated_sessions_dir: Path) -> None:
    bad = _isolated_sessions_dir / "bad.json"
    bad.write_text(json.dumps({"version": 999}), encoding="utf-8")
    with pytest.raises(ValueError):
        cli_session.load(bad)


def test_prune_caps_to_keep(_isolated_sessions_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_session, "ROLLING_CAP", 3)
    paths = []
    for i in range(6):
        p = cli_session.save(
            messages=[{"role": "user", "content": f"msg {i}"}],
            model="m", provider_label="p", cli_mode="system",
            approval_mode=None, session_path=None,
        )
        paths.append(p)
    remaining = sorted(_isolated_sessions_dir.glob("*.json"))
    assert len(remaining) == 3
