"""Persistence helpers for the Flet GUI — all under ``~/.syscontrol/``.

These deliberately read/write the SAME files the CLI and MCP server use:
``config.json`` (permission flags) and the cloud API-key cache, so settings
made in the GUI are honoured everywhere without a restart.
"""
