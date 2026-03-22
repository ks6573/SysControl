#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# SysControl — Build & Package Script
#
# Usage:
#   ./build.sh           Build debug .app
#   ./build.sh release   Build release .app + .dmg
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$SCRIPT_DIR/.build"
APP_NAME="SysControl"
BUNDLE_ID="com.syscontrol.app"

MODE="${1:-debug}"

echo "══════════════════════════════════════════"
echo " SysControl Build Script"
echo " Mode: $MODE"
echo "══════════════════════════════════════════"

# ── Step 1: Build Swift binary ────────────────────────────────────────────────
echo ""
echo "► Building Swift binary ($MODE)..."

if [ "$MODE" = "release" ]; then
    swift build -c release --package-path "$SCRIPT_DIR" 2>&1
    BINARY_PATH="$BUILD_DIR/release/SysControl"
else
    swift build --package-path "$SCRIPT_DIR" 2>&1
    BINARY_PATH="$BUILD_DIR/debug/SysControl"
fi

if [ ! -f "$BINARY_PATH" ]; then
    echo "✗ Build failed — binary not found at $BINARY_PATH"
    exit 1
fi
echo "✓ Binary built: $BINARY_PATH"

# ── Step 2: Create .app bundle ────────────────────────────────────────────────
echo ""
echo "► Creating .app bundle..."

APP_DIR="$BUILD_DIR/$APP_NAME.app"
rm -rf "$APP_DIR"

CONTENTS="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

mkdir -p "$MACOS_DIR" "$RESOURCES"

# Copy binary
cp "$BINARY_PATH" "$MACOS_DIR/$APP_NAME"

# Create Info.plist
cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>SysControl</string>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSSupportsAutomaticTermination</key>
    <false/>
</dict>
</plist>
PLIST

# Copy Python backend into Resources
echo "  Copying Python backend..."
cp -r "$PROJECT_ROOT/agent" "$RESOURCES/agent"
cp -r "$PROJECT_ROOT/mcp" "$RESOURCES/mcp"

# Copy venv if it exists
if [ -d "$PROJECT_ROOT/.venv" ]; then
    echo "  Copying Python venv (this may take a moment)..."
    cp -r "$PROJECT_ROOT/.venv" "$RESOURCES/.venv"
fi

# Ad-hoc code sign
echo "  Code signing..."
codesign --force --deep --sign - "$APP_DIR" 2>/dev/null || true

echo "✓ App bundle: $APP_DIR"

# ── Step 3: Create .dmg (release only) ───────────────────────────────────────
if [ "$MODE" = "release" ]; then
    echo ""
    echo "► Creating .dmg installer..."

    DMG_DIR="$BUILD_DIR/dmg_staging"
    DMG_PATH="$BUILD_DIR/$APP_NAME.dmg"

    rm -rf "$DMG_DIR" "$DMG_PATH"
    mkdir -p "$DMG_DIR"
    cp -r "$APP_DIR" "$DMG_DIR/"

    # Create symlink to Applications
    ln -s /Applications "$DMG_DIR/Applications"

    # Create DMG
    hdiutil create -volname "$APP_NAME" \
        -srcfolder "$DMG_DIR" \
        -ov -format UDZO \
        "$DMG_PATH" 2>/dev/null

    rm -rf "$DMG_DIR"
    echo "✓ DMG: $DMG_PATH"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo " Build complete!"
echo ""
echo " To run:"
echo "   open $APP_DIR"
echo ""
if [ "$MODE" = "release" ] && [ -f "${DMG_PATH:-}" ]; then
    echo " To distribute:"
    echo "   $DMG_PATH"
    echo ""
fi
echo "══════════════════════════════════════════"
