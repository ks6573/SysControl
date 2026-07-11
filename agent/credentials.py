"""Persistent provider credentials with native secure-storage support.

The preferred backend is the operating system credential vault through
``keyring`` (macOS Keychain or Windows Credential Manager).  A mode-0600 JSON
file remains as a compatibility fallback for headless Linux environments with
no usable keyring backend.  Existing file credentials are migrated on read.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

from agent.paths import USER_DATA_DIR, ensure_user_data_dir

_keyring: Any
try:
    import keyring as _keyring
except ImportError:  # pragma: no cover - dependency is present in normal installs
    _keyring = None

CREDENTIALS_FILE: Path = USER_DATA_DIR / "cli_credentials.json"
_CLOUD_KEY = "ollama_cloud_api_key"
_KEYRING_SERVICE = "SysControl"
_KEYRING_ACCOUNT = "ollama-cloud-api-key"


def _read() -> dict:
    try:
        loaded = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write(data: dict) -> None:
    ensure_user_data_dir()
    fd = os.open(CREDENTIALS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    # Best-effort 0600 — meaningful on POSIX; on Windows os.chmod only toggles
    # the read-only bit, so the key's confidentiality relies on per-user
    # profile ACLs.  A perms quirk must never fail credential persistence.
    with contextlib.suppress(OSError):
        os.chmod(CREDENTIALS_FILE, 0o600)


def _keyring_load() -> str | None:
    """Return the native-vault credential, or ``None`` if unavailable/missing."""
    if _keyring is None:
        return None
    try:
        value = _keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
    except Exception:  # keyring raises backend-specific errors
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _keyring_save(api_key: str) -> bool:
    """Persist to the native vault and report whether it succeeded."""
    if _keyring is None:
        return False
    try:
        _keyring.set_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT, api_key)
    except Exception:
        return False
    return True


def _keyring_clear() -> bool:
    """Remove a native-vault credential, returning whether one existed."""
    if _keyring is None:
        return False
    existing = _keyring_load()
    if existing is None:
        return False
    try:
        _keyring.delete_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
    except Exception:
        return False
    return True


def _clear_file_key() -> bool:
    """Remove the legacy file credential while preserving unrelated values."""
    data = _read()
    if _CLOUD_KEY not in data:
        return False
    data.pop(_CLOUD_KEY, None)
    if data:
        _write(data)
    else:
        with contextlib.suppress(FileNotFoundError):
            CREDENTIALS_FILE.unlink()
    return True


def load_cloud_api_key() -> str | None:
    native = _keyring_load()
    if native is not None:
        return native
    value = _read().get(_CLOUD_KEY)
    legacy = value.strip() if isinstance(value, str) and value.strip() else None
    if legacy is not None and _keyring_save(legacy):
        _clear_file_key()
    return legacy


def save_cloud_api_key(api_key: str) -> None:
    normalized = api_key.strip()
    if normalized and _keyring_save(normalized):
        _clear_file_key()
        return
    data = _read()
    data[_CLOUD_KEY] = normalized
    _write(data)


def clear_cloud_api_key() -> bool:
    native_removed = _keyring_clear()
    file_removed = _clear_file_key()
    return native_removed or file_removed
