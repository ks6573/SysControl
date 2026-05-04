"""
Persistent CLI credential cache.

Stores the user's Ollama Cloud API key (and any future provider secrets)
under ``~/.syscontrol/cli_credentials.json`` with 0600 perms so the user
isn't asked to re-enter it on every CLI launch.

The file is local-only: the bridge/MCP server have their own env-var
plumbing (``SYSCONTROL_API_KEY``) and do not read this cache.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from agent.paths import USER_DATA_DIR, ensure_user_data_dir

CREDENTIALS_FILE: Path = USER_DATA_DIR / "cli_credentials.json"
_CLOUD_KEY = "ollama_cloud_api_key"


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
    os.chmod(CREDENTIALS_FILE, 0o600)


def load_cloud_api_key() -> str | None:
    value = _read().get(_CLOUD_KEY)
    return value.strip() if isinstance(value, str) and value.strip() else None


def save_cloud_api_key(api_key: str) -> None:
    data = _read()
    data[_CLOUD_KEY] = api_key.strip()
    _write(data)


def clear_cloud_api_key() -> bool:
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
