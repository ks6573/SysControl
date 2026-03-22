#!/bin/bash
# Create a .dmg installer with a drag-to-Applications layout.
# Requires: brew install create-dmg
set -euo pipefail

APP_NAME="SysControl"
VERSION="0.2.0"
DMG_NAME="${APP_NAME}-${VERSION}.dmg"
APP_PATH="dist/${APP_NAME}.app"
DMG_DIR="dist/dmg"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$ROOT_DIR"

if [ ! -d "$APP_PATH" ]; then
    echo "Error: $APP_PATH not found. Run build_macos.sh first." >&2
    exit 1
fi

# Prepare staging directory
rm -rf "$DMG_DIR"
mkdir -p "$DMG_DIR"
cp -a "$APP_PATH" "$DMG_DIR/"

ICON_PATH="build_resources/SysControl.icns"

# Build the DMG
if command -v create-dmg &>/dev/null; then
    CREATE_DMG_ARGS=(
        --volname "$APP_NAME"
        --window-pos 200 120
        --window-size 600 400
        --icon-size 100
        --icon "${APP_NAME}.app" 175 190
        --hide-extension "${APP_NAME}.app"
        --app-drop-link 425 190
        --no-internet-enable
    )
    # Add volume icon only if it exists
    if [ -f "$ICON_PATH" ]; then
        CREATE_DMG_ARGS+=(--volicon "$ICON_PATH")
    fi

    # create-dmg exits 2 if the DMG already exists — remove first
    rm -f "dist/$DMG_NAME"

    create-dmg "${CREATE_DMG_ARGS[@]}" "dist/$DMG_NAME" "$DMG_DIR/"
else
    echo "create-dmg not found — falling back to hdiutil (no drag-to-Applications layout)"
    # Create a simple Applications symlink
    ln -sf /Applications "$DMG_DIR/Applications"
    rm -f "dist/$DMG_NAME"
    hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_DIR" \
        -ov -format UDZO "dist/$DMG_NAME"
fi

# Clean up staging
rm -rf "$DMG_DIR"

echo ""
echo "DMG created: dist/$DMG_NAME"
