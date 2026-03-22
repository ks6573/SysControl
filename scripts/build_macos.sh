#!/bin/bash
# Build SysControl.app and optionally create a .dmg installer.
# Usage: bash scripts/build_macos.sh [--dmg] [--sign IDENTITY]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

BUILD_DMG=false
SIGN_IDENTITY=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dmg)       BUILD_DMG=true; shift ;;
        --sign)      SIGN_IDENTITY="$2"; shift 2 ;;
        *)           echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ── Step 1: Generate app icon ────────────────────────────────────────────────
echo "=== Step 1: Generating app icon ==="
if [ ! -f "build_resources/SysControl.icns" ]; then
    uv run python scripts/make_icon.py
else
    echo "  Icon already exists, skipping."
fi

# ── Step 2: Build .app with PyInstaller ──────────────────────────────────────
echo ""
echo "=== Step 2: Building .app with PyInstaller ==="
uv run --extra bundle pyinstaller SysControl.spec --clean --noconfirm

# ── Step 3: Optional code signing ────────────────────────────────────────────
if [ -n "$SIGN_IDENTITY" ]; then
    echo ""
    echo "=== Step 3: Signing .app ==="
    ENTITLEMENTS="build_resources/entitlements.plist"
    SIGN_ARGS=(
        --deep --force --verify --verbose
        --sign "$SIGN_IDENTITY"
        --options runtime
    )
    if [ -f "$ENTITLEMENTS" ]; then
        SIGN_ARGS+=(--entitlements "$ENTITLEMENTS")
    fi
    codesign "${SIGN_ARGS[@]}" dist/SysControl.app
    echo "  Signed with: $SIGN_IDENTITY"
fi

# ── Step 4: Optional .dmg ────────────────────────────────────────────────────
if [ "$BUILD_DMG" = true ]; then
    echo ""
    echo "=== Step 4: Creating .dmg ==="
    bash scripts/build_dmg.sh
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "=== Build complete ==="
echo "  .app: dist/SysControl.app"
if [ "$BUILD_DMG" = true ]; then
    echo "  .dmg: dist/SysControl-0.2.0.dmg"
fi
echo ""
echo "To test: dist/SysControl.app/Contents/MacOS/SysControl"
