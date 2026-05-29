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

# ── Build a self-contained, relocatable Python runtime for the bundle ─────────
# macOS framework Python (Homebrew / python.org) is NOT relocatable: its thin
# bin/python3 launcher loads the interpreter from a Python framework dylib by
# ABSOLUTE path (e.g. /opt/homebrew/Cellar/python@3.14/3.14.4/.../Python). A
# copied bundle then runs only where that exact path exists on the build machine
# — it breaks on every other Mac, and even on the build machine after a
# `brew upgrade` bumps the patch version. Instead we build from a uv-managed
# standalone CPython (astral-sh/python-build-standalone): its binary resolves
# libpython via @rpath = @executable_path/../lib and its C-extensions carry no
# external absolute paths, so it runs on any Mac once physically copied.
BUNDLE_PYTHON_VERSION="${SYSCONTROL_BUNDLE_PYTHON:-3.14}"

if ! command -v uv >/dev/null 2>&1; then
    echo "  ⚠ 'uv' not found — cannot build a relocatable Python bundle."
    echo "    Install uv (https://docs.astral.sh/uv/) and re-build, otherwise"
    echo "    users will hit 'Library not loaded' dyld errors on launch."
    if [ "$MODE" = "release" ]; then
        echo "    Release build aborted: a working bundled runtime is required."
        exit 1
    fi
else
    VENV_DIR="$RESOURCES/.venv"
    BUNDLE_VENV="$BUILD_DIR/bundle-venv"

    echo "  Provisioning standalone CPython $BUNDLE_PYTHON_VERSION (uv)..."
    uv python install "$BUNDLE_PYTHON_VERSION" 2>&1 | sed 's/^/    /'

    echo "  Creating bundle venv from the standalone interpreter..."
    rm -rf "$BUNDLE_VENV"
    uv venv --python "$BUNDLE_PYTHON_VERSION" --managed-python --no-project "$BUNDLE_VENV" >/dev/null

    echo "  Installing runtime dependencies into the bundle venv..."
    uv pip install --quiet --python "$BUNDLE_VENV/bin/python3" -r "$PROJECT_ROOT/pyproject.toml"

    echo "  Copying bundle venv into Resources..."
    rm -rf "$VENV_DIR"
    rsync -a --no-owner --no-group --no-perms --executability \
        --exclude '__pycache__/' --exclude '*.pyc' \
        "$BUNDLE_VENV/" "$VENV_DIR/"

    # ── Materialize: make the venv physically self-contained ──────────────
    echo "  Making venv relocatable..."

    # 1. Resolve the real standalone binary the venv symlinks point at.
    REAL_PYTHON="$(/usr/bin/python3 -c "import os; print(os.path.realpath('$VENV_DIR/bin/python3'))")"
    if [ ! -f "$REAL_PYTHON" ]; then
        echo "  ✗ Could not resolve standalone Python at: $REAL_PYTHON"
        exit 1
    fi
    STANDALONE_ROOT="$(dirname "$(dirname "$REAL_PYTHON")")"

    # 2. Replace the venv's interpreter symlinks with the real binary.
    rm -f "$VENV_DIR/bin/python3" "$VENV_DIR/bin/python" "$VENV_DIR"/bin/python3.[0-9]*
    cp "$REAL_PYTHON" "$VENV_DIR/bin/python3"
    ln -s python3 "$VENV_DIR/bin/python"

    # 3. Copy the interpreter dylib into lib/ so the binary's @rpath
    #    (@executable_path/../lib) resolves INSIDE the bundle. This is the step
    #    that makes a copied standalone Python actually run on another machine.
    cp "$STANDALONE_ROOT/lib/libpython"*.dylib "$VENV_DIR/lib/"

    # 4. Copy the standalone stdlib (incl. lib-dynload) — uv keeps it outside the
    #    venv — while preserving the venv's own site-packages.
    STD_LIB="$(find "$STANDALONE_ROOT/lib" -maxdepth 1 -name 'python3.*' -type d 2>/dev/null | head -1)"
    VENV_LIB="$(find "$VENV_DIR/lib" -maxdepth 1 -name 'python3.*' -type d 2>/dev/null | head -1)"
    if [ -n "$STD_LIB" ] && [ -n "$VENV_LIB" ]; then
        echo "  Copying Python stdlib from $STD_LIB..."
        rsync -a --copy-links \
            --exclude 'site-packages/' --exclude '__pycache__/' --exclude '*.pyc' \
            "$STD_LIB/" "$VENV_LIB/"
    fi

    # 5. Patch pyvenv.cfg to point at the bundled bin/. Use Python, not sed, to
    #    avoid corruption when the path contains sed-special characters.
    if [ -f "$VENV_DIR/pyvenv.cfg" ]; then
        VENV_BIN_DIR="$VENV_DIR/bin" /usr/bin/python3 - <<'PYCFG'
import os, pathlib, re
cfg = pathlib.Path(os.environ["VENV_BIN_DIR"]).parent / "pyvenv.cfg"
new_home = os.environ["VENV_BIN_DIR"]
text = cfg.read_text()
text = re.sub(r"(?m)^home\s*=.*$", f"home = {new_home}", text)
cfg.write_text(text)
PYCFG
    fi
    echo "  ✓ Venv made relocatable"

    # 6. Ad-hoc sign every Mach-O in the venv (incl. the interpreter binary and
    #    libpython dylib we just copied) so macOS does not block them with
    #    "library load disallowed by system policy".
    echo "  Signing bundled Mach-O objects..."
    SIGN_COUNT=0
    while IFS= read -r -d '' obj; do
        codesign --force --sign - "$obj" 2>/dev/null && SIGN_COUNT=$((SIGN_COUNT + 1))
    done < <(find "$VENV_DIR" \( -name '*.so' -o -name '*.dylib' \) -print0)
    codesign --force --sign - "$VENV_DIR/bin/python3" 2>/dev/null && SIGN_COUNT=$((SIGN_COUNT + 1))
    echo "  ✓ Signed $SIGN_COUNT objects"

    # 7. Guard against regressions: no bundled Mach-O may reference an absolute
    #    external path (/opt, /Library, /usr/local) — that is exactly what makes
    #    a bundle non-relocatable and breaks it on other Macs (the dyld error).
    echo "  Checking bundle is relocatable (no external absolute dylib refs)..."
    EXTERNAL_REFS="$(find "$VENV_DIR" \( -name '*.so' -o -name '*.dylib' -o -name 'python3' \) \
        -exec otool -L {} \; 2>/dev/null | grep -E '^[[:space:]]+/(opt|Library|usr/local)' | sort -u || true)"
    if [ -n "$EXTERNAL_REFS" ]; then
        echo "  ✗ Bundle references external absolute paths (NOT relocatable):"
        echo "$EXTERNAL_REFS" | sed 's/^/      /'
        if [ "$MODE" = "release" ]; then
            exit 1
        fi
    else
        echo "  ✓ No external absolute dylib refs — bundle is relocatable"
    fi

    # 8. Validate: the bundled Python must RUN and import deps + TLS. The ssl
    #    import proves the relocated crypto works, which the OpenAI client needs.
    echo "  Validating bundled Python..."
    if "$VENV_DIR/bin/python3" -c "import ssl, psutil, openai; print('  ✓ Bundled Python validated (ssl + psutil + openai importable)')"; then
        :
    else
        echo "  ✗ Bundled Python failed validation — DMG users would see"
        echo "    'Could not connect to backend' errors."
        if [ "$MODE" = "release" ]; then
            exit 1
        fi
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
