"""Tests for agent/credentials.py — load/save/clear round-trip + perms."""

import os
from pathlib import Path

import pytest

from agent import credentials


@pytest.fixture(autouse=True)
def _isolated_credentials_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "cli_credentials.json"
    monkeypatch.setattr(credentials, "CREDENTIALS_FILE", target)
    monkeypatch.setattr(credentials, "ensure_user_data_dir", lambda: tmp_path.mkdir(exist_ok=True))
    return target


def test_load_returns_none_when_missing() -> None:
    assert credentials.load_cloud_api_key() is None


def test_save_then_load_round_trip(_isolated_credentials_file: Path) -> None:
    credentials.save_cloud_api_key("sk-test-123")
    assert credentials.load_cloud_api_key() == "sk-test-123"


def test_save_writes_file_with_owner_only_perms(_isolated_credentials_file: Path) -> None:
    credentials.save_cloud_api_key("sk-test-perms")
    mode = _isolated_credentials_file.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0600 perms, got {oct(mode)}"


def test_save_repairs_existing_permissive_file(_isolated_credentials_file: Path) -> None:
    _isolated_credentials_file.write_text("{}", encoding="utf-8")
    os.chmod(_isolated_credentials_file, 0o644)
    credentials.save_cloud_api_key("sk-test-repair")
    mode = _isolated_credentials_file.stat().st_mode & 0o777
    assert mode == 0o600, f"expected repaired 0600 perms, got {oct(mode)}"


def test_save_strips_whitespace() -> None:
    credentials.save_cloud_api_key("  sk-padded  ")
    assert credentials.load_cloud_api_key() == "sk-padded"


def test_load_returns_none_for_blank_value() -> None:
    credentials.save_cloud_api_key("")
    assert credentials.load_cloud_api_key() is None


def test_clear_removes_key_and_returns_true(_isolated_credentials_file: Path) -> None:
    credentials.save_cloud_api_key("sk-test")
    assert credentials.clear_cloud_api_key() is True
    assert credentials.load_cloud_api_key() is None
    assert not _isolated_credentials_file.exists()


def test_clear_returns_false_when_nothing_to_clear() -> None:
    assert credentials.clear_cloud_api_key() is False


def test_clear_preserves_other_keys(_isolated_credentials_file: Path) -> None:
    credentials.save_cloud_api_key("sk-test")
    raw = _isolated_credentials_file.read_text()
    _isolated_credentials_file.write_text(raw.replace("}", ',\n  "other": "x"\n}'))
    os.chmod(_isolated_credentials_file, 0o600)

    assert credentials.clear_cloud_api_key() is True
    assert _isolated_credentials_file.exists()
    assert "other" in _isolated_credentials_file.read_text()
