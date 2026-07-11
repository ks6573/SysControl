"""Cloud API-key storage shared by the GUI and CLI.

The underlying implementation uses macOS Keychain or Windows Credential
Manager when available and falls back to a protected local file on Linux.
"""

from __future__ import annotations

from agent.credentials import clear_cloud_api_key, load_cloud_api_key, save_cloud_api_key

__all__ = ["clear_cloud_api_key", "load_cloud_api_key", "save_cloud_api_key"]
