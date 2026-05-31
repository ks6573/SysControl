"""Tests for the Flet GUI's pure-logic layer (no display / no Flet import).

Covers chart-marker extraction + path validation, the GuiSession model
round-trip, and the session store's save/load/list/delete.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from flet_app import charts
from flet_app.models import DEFAULT_TITLE, GuiSession
from flet_app.store import sessions


# ── charts ──────────────────────────────────────────────────────────────────
def test_extract_chart_paths_accepts_valid_tmp_png() -> None:
    fd, path = tempfile.mkstemp(prefix="syscontrol_chart_", suffix=".png")
    os.close(fd)  # Windows won't unlink a file with an open handle
    Path(path).write_bytes(b"x")
    try:
        result = charts.extract_chart_paths(f"chart ready [chart_image:{path}]")
        assert Path(result[0]).name == Path(path).name
    finally:
        Path(path).unlink(missing_ok=True)


def test_extract_chart_paths_rejects_outside_tmp() -> None:
    # A path outside the temp dir must never be surfaced, even if marked.
    assert charts.extract_chart_paths("[chart_image:C:/Windows/system32/x.png]") == []


def test_extract_chart_paths_rejects_wrong_prefix() -> None:
    fd, path = tempfile.mkstemp(prefix="not_a_chart_", suffix=".png")
    os.close(fd)  # Windows won't unlink a file with an open handle
    Path(path).write_bytes(b"x")
    try:
        assert charts.extract_chart_paths(f"[chart_image:{path}]") == []
    finally:
        Path(path).unlink(missing_ok=True)


def test_strip_chart_markers() -> None:
    assert charts.strip_chart_markers("done [chart_image:/tmp/a.png]") == "done"


# ── model ────────────────────────────────────────────────────────────────────
def test_gui_session_roundtrip() -> None:
    s = GuiSession(title="hello", messages=[{"role": "user", "content": "hi"}], pinned=True)
    restored = GuiSession.from_dict(s.to_dict())
    assert restored.id == s.id
    assert restored.title == "hello"
    assert restored.pinned is True
    assert restored.messages == [{"role": "user", "content": "hi"}]


def test_derive_title_from_first_user_message() -> None:
    s = GuiSession(messages=[{"role": "user", "content": "What is my CPU usage?"}])
    s.derive_title()
    assert s.title == "What is my CPU usage?"


def test_derive_title_noop_when_already_set() -> None:
    s = GuiSession(title="Custom", messages=[{"role": "user", "content": "x"}])
    s.derive_title()
    assert s.title == "Custom"


def test_derive_title_default_when_no_user_message() -> None:
    s = GuiSession()
    s.derive_title()
    assert s.title == DEFAULT_TITLE


# ── session store ──────────────────────────────────────────────────────────────
@pytest.fixture
def _isolated_sessions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "gui_chats"
    monkeypatch.setattr(sessions, "SESSIONS_DIR", target)
    return target


def test_session_store_save_load_list_delete(_isolated_sessions_dir: Path) -> None:
    s = GuiSession(title="t1", messages=[{"role": "user", "content": "a"}])
    sessions.save_session(s)

    loaded = sessions.load_session(s.id)
    assert loaded is not None and loaded.title == "t1"

    listing = sessions.list_sessions()
    assert [x.id for x in listing] == [s.id]

    sessions.delete_session(s.id)
    assert sessions.load_session(s.id) is None
    assert sessions.list_sessions() == []


def test_session_store_load_missing_returns_none(_isolated_sessions_dir: Path) -> None:
    assert sessions.load_session("nonexistent") is None
