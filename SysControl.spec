# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the SysControl Windows GUI (one-folder bundle).

Build:
    uv run --extra gui --extra build pyinstaller SysControl.spec

Produces ``dist/SysControl/SysControl.exe`` plus an ``_internal/`` folder.
Zip the whole ``dist/SysControl`` directory for distribution.

Key design points:
  * One-folder (``--onedir``) — fast startup, AV-friendlier, and the bundled
    exe can cheaply re-exec itself as the MCP server (see flet_app/main.py's
    ``--run-mcp-server`` sentinel; ``mcp.server`` is a hidden import because it
    is only ever launched via a spawned process, never imported directly).
  * Flet's desktop Flutter client (``flet_desktop``) and assets are collected
    whole so the GUI window can render.
  * matplotlib (Agg fonts) and certifi (TLS CA bundle) data are collected so
    chart tools render and HTTPS to the LLM provider works.
  * ``mcp/prompt.json`` + ``agent/skills_builtin`` ship as data so the frozen
    server finds its prompt and first-run skills.
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas = []
binaries = []
hiddenimports = ["mcp.server"]

# Flet desktop client (prebuilt Flutter binary) + flet package assets.
for _pkg in ("flet", "flet_desktop"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# Keyring backends are discovered dynamically through package metadata; collect
# them explicitly so the frozen Windows app can use Credential Manager.
_d, _b, _h = collect_all("keyring")
datas += _d
binaries += _b
hiddenimports += _h

# Runtime data for heavy deps.
datas += collect_data_files("matplotlib")   # Agg fonts / mpl-data
datas += collect_data_files("certifi")       # TLS CA bundle (HTTPS to providers)

# Our own resources (the frozen MCP server reads these).
datas += [
    ("mcp/prompt.json", "mcp"),
    ("agent/skills_builtin", "agent/skills_builtin"),
]

# Pull in our sub-packages + lazily-imported tool backends that PyInstaller's
# static analysis might otherwise miss.
for _pkg in ("mcp", "agent", "flet_app", "deep_research"):
    hiddenimports += collect_submodules(_pkg)
hiddenimports += [
    "openai", "psutil", "pyperclip", "send2trash",
    "pycaw", "comtypes", "winotify", "PIL", "PIL.ImageGrab",
]

_icon = "flet_app/resources/icon.ico"
_icon = _icon if os.path.exists(_icon) else None

a = Analysis(
    ["flet_app/main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SysControl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed GUI (stdio pipes still work for the MCP child)
    icon=_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SysControl",
)
