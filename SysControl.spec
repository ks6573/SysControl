# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for building SysControl.app on macOS."""

from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH)

a = Analysis(
    [str(project_root / "gui.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # MCP server package (executed as subprocess via --mcp-server flag)
        (str(project_root / "mcp" / "server.py"),    "mcp"),
        (str(project_root / "mcp" / "prompt.json"),   "mcp"),
        (str(project_root / "mcp" / "__init__.py"),   "mcp"),
    ],
    hiddenimports=[
        # Qt
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        # GUI modules
        "agent.gui",
        "agent.gui.app",
        "agent.gui.main_window",
        "agent.gui.chat_widget",
        "agent.gui.input_widget",
        "agent.gui.message_bubble",
        "agent.gui.settings_dialog",
        "agent.gui.theme",
        "agent.gui.worker",
        "agent.gui.chat_history",
        "agent.gui.goodbye_dialog",
        "agent.gui.sidebar",
        # Agent core
        "agent.core",
        "agent.paths",
        "agent.cli",
        # MCP server (imported at runtime via --mcp-server flag)
        "mcp",
        "mcp.server",
        # Third-party
        "markdown",
        "markdown.extensions",
        "psutil",
        "openai",
        "matplotlib",
        "matplotlib.pyplot",
        "matplotlib.ticker",
        "matplotlib.backends.backend_agg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pynvml",           # No NVIDIA GPUs on macOS
        "nvidia_ml_py",
        "tkinter",          # Not needed
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SysControl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX can corrupt Qt shared libraries on macOS
    console=False,      # Windowed app — no Terminal window
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="SysControl",
)

# ── macOS .app bundle ─────────────────────────────────────────────────────────

_icon_path = project_root / "build_resources" / "SysControl.icns"

app = BUNDLE(
    coll,
    name="SysControl.app",
    icon=str(_icon_path) if _icon_path.exists() else None,
    bundle_identifier="com.syscontrol.app",
    info_plist={
        "CFBundleName": "SysControl",
        "CFBundleDisplayName": "SysControl",
        "CFBundleVersion": "0.2.0",
        "CFBundleShortVersionString": "0.2.0",
        "NSHighResolutionCapable": True,
        # Required: the app uses AppleScript to detect system appearance
        "NSAppleEventsUsageDescription":
            "SysControl uses AppleScript to detect system appearance.",
        "LSMinimumSystemVersion": "12.0",
        # Support macOS dark mode natively
        "NSRequiresAquaSystemAppearance": False,
    },
)
