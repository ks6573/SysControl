"""Persist the non-secret LLM provider config to ``~/.syscontrol/gui_config.json``.

Mirrors the macOS SwiftUI app's ProviderConfigStore shape (``baseURL`` / ``model``
/ ``label``) so the two GUIs share a convention.  The API key is NOT stored here
— see :mod:`flet_app.store.credentials`.
"""

from __future__ import annotations

import json

from agent.core import LOCAL_BASE_URL, LOCAL_MODEL, OLLAMA_CLOUD_BASE_URL, OLLAMA_CLOUD_MODEL
from agent.paths import USER_DATA_DIR, ensure_user_data_dir

CONFIG_FILE = USER_DATA_DIR / "gui_config.json"

LOCAL_LABEL = "Local (Ollama)"
CLOUD_LABEL = "Cloud (Ollama Cloud)"


def load_provider_config() -> dict:
    """Return the saved provider config, or {} if none/invalid."""
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_provider_config(base_url: str, model: str, label: str) -> None:
    ensure_user_data_dir()
    payload = {"baseURL": base_url, "model": model, "label": label}
    CONFIG_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def is_configured() -> bool:
    """True once the user has chosen a provider (onboarding complete)."""
    return bool(load_provider_config().get("baseURL"))


def default_local() -> dict:
    return {"baseURL": LOCAL_BASE_URL, "model": LOCAL_MODEL, "label": LOCAL_LABEL}


def default_cloud() -> dict:
    return {"baseURL": OLLAMA_CLOUD_BASE_URL, "model": OLLAMA_CLOUD_MODEL, "label": CLOUD_LABEL}


def is_local(base_url: str) -> bool:
    return base_url.rstrip("/") == LOCAL_BASE_URL.rstrip("/")
