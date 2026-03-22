#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# SysControl — One-line installer
#
# Usage:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ks6573/SyscontrolMCP/master/swift/install.sh)"
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_NAME="SysControl"
REPO_URL="https://github.com/ks6573/SyscontrolMCP.git"
INSTALL_DIR="$HOME/.syscontrol/build"

echo ""
echo "══════════════════════════════════════════"
echo " SysControl Installer"
echo "══════════════════════════════════════════"
echo ""

# ── Preflight checks ─────────────────────────────────────────────────────────

if [ "$(uname)" != "Darwin" ]; then
    echo "✗ SysControl requires macOS."
    exit 1
fi

if ! xcode-select -p &>/dev/null; then
    echo "Xcode Command Line Tools not found. Installing..."
    xcode-select --install
    echo ""
    echo "After installation completes, re-run this script."
    exit 1
fi

if ! command -v swift &>/dev/null; then
    echo "✗ Swift compiler not found. Install Xcode Command Line Tools:"
    echo "  xcode-select --install"
    exit 1
fi

# ── Clone or update ──────────────────────────────────────────────────────────

if [ -d "$INSTALL_DIR" ]; then
    echo "► Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull --ff-only 2>/dev/null || {
        echo "  Could not fast-forward — re-cloning..."
        cd /
        rm -rf "$INSTALL_DIR"
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    }
else
    echo "► Downloading SysControl..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ── Set up Python venv ───────────────────────────────────────────────────────

echo ""
echo "► Setting up Python backend..."

if command -v uv &>/dev/null; then
    uv sync 2>&1 | tail -1
else
    echo "  uv not found — installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null
    export PATH="$HOME/.local/bin:$PATH"
    uv sync 2>&1 | tail -1
fi

# ── Build ────────────────────────────────────────────────────────────────────

echo ""
echo "► Building app (this may take a minute on first run)..."
cd swift
./build.sh release 2>&1 | grep -E "^[✓✗►]|^  App|^  DMG|Build complete"

APP_PATH="$INSTALL_DIR/swift/.build/$APP_NAME.app"
DEST="/Applications/$APP_NAME.app"

if [ ! -d "$APP_PATH" ]; then
    echo ""
    echo "✗ Build failed. Check the output above for errors."
    exit 1
fi

# ── Install to /Applications ─────────────────────────────────────────────────

echo ""
echo "► Installing to /Applications..."

if [ -d "$DEST" ]; then
    rm -rf "$DEST"
fi
cp -R "$APP_PATH" "$DEST"

echo "✓ Installed: $DEST"

# ── Launch ───────────────────────────────────────────────────────────────────

echo ""
echo "══════════════════════════════════════════"
echo " ✓ SysControl installed!"
echo ""
echo " Opening the app now..."
echo " Configure your provider in Settings."
echo "══════════════════════════════════════════"
echo ""

open "$DEST"
