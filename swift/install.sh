#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# SysControl — One-line installer
#
# Usage:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ks6573/SysControl/master/swift/install.sh)"
#
# Flags:
#   --uninstall   Remove SysControl from Applications (and optionally ~/.syscontrol)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_NAME="SysControl"
REPO_URL="https://github.com/ks6573/SysControl.git"
INSTALL_DIR="$HOME/.syscontrol/build"
LOG_FILE="$HOME/.syscontrol/install.log"
DEST="/Applications/$APP_NAME.app"
MIN_MACOS_MAJOR=14

normalize_repo_slug() {
    local url="$1"
    url="${url#git@github.com:}"
    url="${url#https://github.com/}"
    url="${url#http://github.com/}"
    url="${url%.git}"
    printf "%s" "$url" | tr '[:upper:]' '[:lower:]'
}

EXPECTED_REPO_SLUG="$(normalize_repo_slug "$REPO_URL")"

# ── Uninstall flag ────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    echo ""
    echo "══════════════════════════════════════════"
    echo " SysControl Uninstaller"
    echo "══════════════════════════════════════════"
    echo ""

    if [ -d "$DEST" ]; then
        rm -rf "$DEST"
        echo "✓ Removed $DEST"
    else
        echo "  $DEST not found — skipping"
    fi

    if [ -f "$HOME/.local/bin/syscontrol-update" ]; then
        rm -f "$HOME/.local/bin/syscontrol-update"
        echo "✓ Removed syscontrol-update"
    fi

    echo ""
    read -r -p "  Also remove ~/.syscontrol (config, logs, build)? [y/N] " answer
    if [[ "${answer:-n}" =~ ^[Yy]$ ]]; then
        rm -rf "$HOME/.syscontrol"
        echo "✓ Removed ~/.syscontrol"
    fi

    echo ""
    echo "✓ Uninstall complete."
    echo ""
    exit 0
fi

echo ""
echo "══════════════════════════════════════════"
echo " SysControl Installer"
echo "══════════════════════════════════════════"
echo ""

# ── [1/5] Requirements ────────────────────────────────────────────────────────
echo "[1/5] Checking requirements..."

if [ "$(uname)" != "Darwin" ]; then
    echo "✗ SysControl requires macOS."
    exit 1
fi

# Check macOS version >= 14
MACOS_VERSION=$(sw_vers -productVersion)
MACOS_MAJOR=$(echo "$MACOS_VERSION" | cut -d. -f1)
if [ "$MACOS_MAJOR" -lt "$MIN_MACOS_MAJOR" ]; then
    echo "✗ SysControl requires macOS $MIN_MACOS_MAJOR (Sonoma) or later."
    echo "  Detected: macOS $MACOS_VERSION"
    exit 1
fi
echo "  macOS $MACOS_VERSION — OK"

if ! xcode-select -p &>/dev/null; then
    echo "  Xcode Command Line Tools not found. Installing..."
    xcode-select --install
    echo ""
    echo "  After installation completes, re-run this script."
    exit 1
fi

if ! command -v swift &>/dev/null; then
    echo "✗ Swift compiler not found. Install Xcode Command Line Tools:"
    echo "  xcode-select --install"
    exit 1
fi
echo "  Swift $(swift --version 2>&1 | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1) — OK"

# ── [2/5] Download ────────────────────────────────────────────────────────────
echo ""
echo "[2/5] Downloading SysControl..."

# Create ~/.syscontrol early so we can write the log
mkdir -p "$HOME/.syscontrol"

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  Updating existing installation..."
    cd "$INSTALL_DIR"

    CURRENT_REMOTE_URL="$(git remote get-url origin 2>/dev/null || true)"
    if [ -n "$CURRENT_REMOTE_URL" ]; then
        CURRENT_REMOTE_SLUG="$(normalize_repo_slug "$CURRENT_REMOTE_URL")"
        if [ "$CURRENT_REMOTE_SLUG" != "$EXPECTED_REPO_SLUG" ]; then
            echo "  Correcting git remote origin -> $REPO_URL"
            git remote set-url origin "$REPO_URL" 2>>"$LOG_FILE"
        fi
    else
        echo "  No origin remote found — setting origin to $REPO_URL"
        git remote add origin "$REPO_URL" 2>>"$LOG_FILE" || git remote set-url origin "$REPO_URL" 2>>"$LOG_FILE"
    fi

    git pull --ff-only 2>>"$LOG_FILE" || {
        echo "  Could not fast-forward — re-cloning..."
        cd /
        rm -rf "$INSTALL_DIR"
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>>"$LOG_FILE"
        cd "$INSTALL_DIR"
    }
else
    if [ -d "$INSTALL_DIR" ]; then
        echo "  Existing install directory is not a git checkout — re-cloning..."
        rm -rf "$INSTALL_DIR"
    fi
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>>"$LOG_FILE"
    cd "$INSTALL_DIR"
fi

VERSION=$(cat "$INSTALL_DIR/VERSION" 2>/dev/null || echo "1.0.0")
echo "  Version: $VERSION"

# ── [3/5] Python backend ──────────────────────────────────────────────────────
echo ""
echo "[3/5] Setting up Python backend..."

cd "$INSTALL_DIR"
if command -v uv &>/dev/null; then
    uv sync >>"$LOG_FILE" 2>&1
else
    echo "  uv not found — installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh >>"$LOG_FILE" 2>&1
    export PATH="$HOME/.local/bin:$PATH"
    uv sync >>"$LOG_FILE" 2>&1
fi
echo "  Python backend ready"

# ── [4/5] Build app ───────────────────────────────────────────────────────────
echo ""
echo "[4/5] Building app (first run ~2 min)...   [log: $LOG_FILE]"

cd "$INSTALL_DIR/swift"
./build.sh release >>"$LOG_FILE" 2>&1

APP_PATH="$INSTALL_DIR/swift/.build/$APP_NAME.app"

if [ ! -d "$APP_PATH" ]; then
    echo ""
    echo "✗ Build failed. Check the log:"
    echo "  $LOG_FILE"
    exit 1
fi
echo "  Build complete"

# ── [5/5] Install ─────────────────────────────────────────────────────────────
echo ""
echo "[5/5] Installing to /Applications..."

if [ -d "$DEST" ]; then
    rm -rf "$DEST"
fi
cp -R "$APP_PATH" "$DEST"
echo "  Installed: $DEST"

# Install syscontrol-update command
UPDATE_BIN="$HOME/.local/bin/syscontrol-update"
mkdir -p "$HOME/.local/bin"
cat > "$UPDATE_BIN" <<'EOF'
#!/bin/bash
# syscontrol-update — pull latest changes and rebuild SysControl
set -euo pipefail

INSTALL_DIR="$HOME/.syscontrol/build"
LOG_FILE="$HOME/.syscontrol/install.log"
DEST="/Applications/SysControl.app"
REPO_URL="https://github.com/ks6573/SysControl.git"
# GUI-launched shells often miss user-local binaries.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

normalize_repo_slug() {
    local url="$1"
    url="${url#git@github.com:}"
    url="${url#https://github.com/}"
    url="${url#http://github.com/}"
    url="${url%.git}"
    printf "%s" "$url" | tr '[:upper:]' '[:lower:]'
}

EXPECTED_REPO_SLUG="$(normalize_repo_slug "$REPO_URL")"

echo "══════════════════════════════════════════"
echo " SysControl Updater"
echo "══════════════════════════════════════════"
echo ""

if [ ! -d "$INSTALL_DIR" ]; then
    echo "✗ SysControl source not found at $INSTALL_DIR."
    echo "  Run the full installer first:"
    echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ks6573/SysControl/master/swift/install.sh)"'
    exit 1
fi

echo "[1/3] Pulling latest changes..."

if [ ! -d "$INSTALL_DIR/.git" ]; then
    echo "  Existing source is missing git metadata — re-cloning..."
    cd /
    rm -rf "$INSTALL_DIR"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>>"$LOG_FILE"
fi

cd "$INSTALL_DIR"
CURRENT_REMOTE_URL="$(git remote get-url origin 2>/dev/null || true)"
if [ -n "$CURRENT_REMOTE_URL" ]; then
    CURRENT_REMOTE_SLUG="$(normalize_repo_slug "$CURRENT_REMOTE_URL")"
    if [ "$CURRENT_REMOTE_SLUG" != "$EXPECTED_REPO_SLUG" ]; then
        echo "  Correcting git remote origin -> $REPO_URL"
        git remote set-url origin "$REPO_URL" 2>>"$LOG_FILE"
    fi
else
    echo "  No origin remote found — setting origin to $REPO_URL"
    git remote add origin "$REPO_URL" 2>>"$LOG_FILE" || git remote set-url origin "$REPO_URL" 2>>"$LOG_FILE"
fi

git pull --ff-only 2>>"$LOG_FILE" || {
    echo "  Fast-forward failed — re-cloning..."
    cd /
    rm -rf "$INSTALL_DIR"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>>"$LOG_FILE"
    cd "$INSTALL_DIR"
}
VERSION=$(cat "$INSTALL_DIR/VERSION" 2>/dev/null || echo "?")
echo "  Version: $VERSION"

echo ""
echo "[2/3] Updating Python backend..."
if ! command -v uv &>/dev/null; then
    echo "  uv not found on PATH — installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh >>"$LOG_FILE" 2>&1
    export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv &>/dev/null; then
    echo "✗ uv is still unavailable after install attempt. Check: $LOG_FILE"
    exit 127
fi

uv sync >>"$LOG_FILE" 2>&1
echo "  Done"

echo ""
echo "[3/3] Rebuilding app...   [log: $LOG_FILE]"
cd "$INSTALL_DIR/swift"
./build.sh release >>"$LOG_FILE" 2>&1
APP_PATH="$INSTALL_DIR/swift/.build/SysControl.app"

if [ ! -d "$APP_PATH" ]; then
    echo "✗ Build failed. Check: $LOG_FILE"
    exit 1
fi

[ -d "$DEST" ] && rm -rf "$DEST"
cp -R "$APP_PATH" "$DEST"
echo "  Installed: $DEST"

echo ""
echo "══════════════════════════════════════════"
echo " ✓ Updated to v$VERSION"
echo "══════════════════════════════════════════"
echo ""
open "$DEST"
EOF
chmod +x "$UPDATE_BIN"
echo "  Update command: syscontrol-update"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo " ✓ SysControl v$VERSION installed!"
echo ""
echo " To update later:  syscontrol-update"
echo " Opening now. Press ⌘, in the app"
echo " to configure your AI provider."
echo "══════════════════════════════════════════"
echo ""

open "$DEST"
