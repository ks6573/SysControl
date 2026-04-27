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
VERSION=$(cat "$PROJECT_ROOT/VERSION" 2>/dev/null || echo "1.0.0")
# Trim whitespace/newlines
VERSION="${VERSION//[$'\t\r\n ']}"

MODE="${1:-debug}"

echo "══════════════════════════════════════════"
echo " SysControl Build Script"
echo " Version: $VERSION  Mode: $MODE"
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
    <string>$VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
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

# Copy app icon (.icns) from tracked source
ICON_SOURCE="$SCRIPT_DIR/SysControl/Resources/AppIcon.icns"
if [ -f "$ICON_SOURCE" ]; then
    cp "$ICON_SOURCE" "$RESOURCES/AppIcon.icns"
    echo "  App icon: $ICON_SOURCE"
else
    echo "  Warning: app icon not found at $ICON_SOURCE"
fi

# Copy Python backend into Resources
echo "  Copying Python backend..."
cp -r "$PROJECT_ROOT/agent" "$RESOURCES/agent"
cp -r "$PROJECT_ROOT/mcp" "$RESOURCES/mcp"

# Copy venv if it exists
if [ -d "$PROJECT_ROOT/.venv" ]; then
    echo "  Copying Python venv (this may take a moment)..."
    rm -rf "$RESOURCES/.venv"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete \
            --no-owner --no-group --no-perms --executability \
            --exclude '__pycache__/' \
            --exclude '*.pyc' \
            "$PROJECT_ROOT/.venv/" "$RESOURCES/.venv/"
    else
        cp -R "$PROJECT_ROOT/.venv" "$RESOURCES/.venv"
    fi

    # ── Make venv relocatable ──────────────────────────────────────────
    echo "  Making venv relocatable..."
    VENV_DIR="$RESOURCES/.venv"

    # 1. Resolve the real Python binary (follow all symlinks)
    REAL_PYTHON="$(python3 -c "import os; print(os.path.realpath('$VENV_DIR/bin/python3'))")"

    if [ -f "$REAL_PYTHON" ]; then
        # 2. Replace symlinks with the actual binary
        rm -f "$VENV_DIR/bin/python3" "$VENV_DIR/bin/python"
        cp "$REAL_PYTHON" "$VENV_DIR/bin/python3"
        ln -s python3 "$VENV_DIR/bin/python"

        # 3. Copy Python stdlib — uv keeps it outside the venv
        PYTHON_HOME="$(dirname "$REAL_PYTHON")/.."
        PYTHON_LIB="$(find "$PYTHON_HOME/lib" -maxdepth 1 -name 'python3.*' -type d 2>/dev/null | head -1)"
        VENV_LIB="$(find "$VENV_DIR/lib" -maxdepth 1 -name 'python3.*' -type d 2>/dev/null | head -1)"

        if [ -n "$PYTHON_LIB" ] && [ -n "$VENV_LIB" ]; then
            echo "  Copying Python stdlib from $PYTHON_LIB..."
            rsync -a --copy-links \
                --exclude 'site-packages/' \
                --exclude '__pycache__/' \
                --exclude '*.pyc' \
                "$PYTHON_LIB/" "$VENV_LIB/"
        fi

        # 4. Patch pyvenv.cfg to point at the bundled bin/
        # Use Python instead of sed to avoid corruption when $VENV_DIR contains
        # characters that have special meaning to sed (|, &, \, etc.).
        if [ -f "$VENV_DIR/pyvenv.cfg" ]; then
            VENV_BIN_DIR="$VENV_DIR/bin" python3 - <<'PYCFG'
import os, pathlib, re
cfg = pathlib.Path(os.environ["VENV_BIN_DIR"]).parent / "pyvenv.cfg"
new_home = os.environ["VENV_BIN_DIR"]
text = cfg.read_text()
text = re.sub(r"(?m)^home\s*=.*$", f"home = {new_home}", text)
cfg.write_text(text)
PYCFG
        fi

        echo "  ✓ Venv made relocatable"
    else
        echo "  ⚠ Warning: could not resolve real Python binary at $REAL_PYTHON"
    fi

    # 5. Ad-hoc sign all shared libraries in the venv so macOS
    #    does not block them with "library load disallowed by system policy"
    echo "  Signing bundled shared libraries..."
    SIGN_COUNT=0
    while IFS= read -r -d '' lib; do
        codesign --force --sign - "$lib" 2>/dev/null && SIGN_COUNT=$((SIGN_COUNT + 1))
    done < <(find "$VENV_DIR" \( -name '*.so' -o -name '*.dylib' \) -print0)
    echo "  ✓ Signed $SIGN_COUNT shared libraries"

    # 6. Validate the bundled venv
    echo "  Validating bundled Python..."
    if "$VENV_DIR/bin/python3" -c "import psutil, openai; print('  ✓ Bundled Python validated (psutil, openai importable)')" 2>/dev/null; then
        :
    else
        echo "  ⚠ Warning: Bundled Python cannot import required modules"
        echo "    DMG users may experience 'Could not connect to backend' errors"
    fi
fi

# Ad-hoc code sign the entire app bundle
echo "  Code signing app bundle..."
if codesign --force --deep --sign - "$APP_DIR" >/dev/null 2>&1; then
    echo "  ✓ App bundle signed"
else
    echo "  ✗ Code signing failed"
    if [ "$MODE" = "release" ]; then
        echo "    Release build aborted because code signing is required."
        exit 1
    fi
    echo "    Continuing debug build without valid signature."
fi

# Verify signature integrity for release builds
if [ "$MODE" = "release" ]; then
    echo "  Verifying app signature..."
    if codesign --verify --deep --strict --verbose=2 "$APP_DIR" >/dev/null 2>&1; then
        echo "  ✓ Signature verification passed"
    else
        echo "  ✗ Signature verification failed"
        exit 1
    fi
fi

echo "✓ App bundle: $APP_DIR"

# ── Step 3: Create .dmg (release only) ───────────────────────────────────────
if [ "$MODE" = "release" ]; then
    echo ""
    echo "► Creating .dmg installer..."

    DMG_DIR="$BUILD_DIR/dmg_staging"
    DMG_PATH="$BUILD_DIR/$APP_NAME.dmg"

    rm -rf "$DMG_DIR" "$DMG_PATH"
    mkdir -p "$DMG_DIR"
    if command -v rsync >/dev/null 2>&1; then
        mkdir -p "$DMG_DIR/$APP_NAME.app"
        rsync -a --delete \
            --no-owner --no-group --no-perms --executability \
            --omit-dir-times --no-times \
            "$APP_DIR/" "$DMG_DIR/$APP_NAME.app/"
    else
        cp -R "$APP_DIR" "$DMG_DIR/"
    fi

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
