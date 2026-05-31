"""Cloud API-key storage for the GUI.

Thin re-export of :mod:`agent.credentials` so the GUI and CLI share one cloud
key cache (``~/.syscontrol/cli_credentials.json``).  Kept as a separate module
so a future Windows Credential Manager (``keyring``) backend can slot in here
without touching call sites.
"""

from __future__ import annotations

from agent.credentials import clear_cloud_api_key, load_cloud_api_key, save_cloud_api_key

__all__ = ["clear_cloud_api_key", "load_cloud_api_key", "save_cloud_api_key"]
