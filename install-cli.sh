#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# SysControl CLI — One-line installer
#
# Usage:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ks6573/SysControl/master/install-cli.sh)"
#
# Flags:
#   --uninstall   Remove the syscontrol CLI (and optionally ~/.syscontrol)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="https://github.com/ks6573/SysControl.git"
TOOL_NAME="syscontrol"
LOG_FILE="$HOME/.syscontrol/install-cli.log"
UPDATE_BIN="$HOME/.local/bin/syscontrol-cli-update"

mkdir -p "$HOME/.syscontrol" "$HOME/.local/bin"

# ── Uninstall flag ────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    echo ""
    echo "══════════════════════════════════════════"
    echo " SysControl CLI Uninstaller"
    echo "══════════════════════════════════════════"
    echo ""

    if command -v uv &>/dev/null && uv tool list 2>/dev/null | grep -q "^$TOOL_NAME"; then
        uv tool uninstall "$TOOL_NAME" >>"$LOG_FILE" 2>&1 || true
        echo "✓ Removed syscontrol CLI"
    else
        echo "  syscontrol not installed via uv tool — skipping"
    fi

    if [ -f "$UPDATE_BIN" ]; then
        rm -f "$UPDATE_BIN"
        echo "✓ Removed syscontrol-cli-update"
    fi

    echo ""
    read -r -p "  Also remove ~/.syscontrol (config, chat history, memory)? [y/N] " answer
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
echo " SysControl CLI Installer"
echo "══════════════════════════════════════════"
echo ""

# ── [1/3] Requirements ────────────────────────────────────────────────────────
echo "[1/3] Checking requirements..."

OS_NAME="$(uname)"
case "$OS_NAME" in
    Darwin|Linux) ;;
    *)
        echo "✗ Unsupported OS: $OS_NAME (need macOS or Linux)."
        exit 1
        ;;
esac
echo "  OS: $OS_NAME — OK"

if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -gt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -ge 11 ]; }; then
        echo "  Python $PY_VERSION — OK"
    else
        echo "  Python $PY_VERSION present but <3.11 — uv will fetch a newer one"
    fi
else
    echo "  Python not found — uv will fetch one"
fi

# ── [2/3] uv ──────────────────────────────────────────────────────────────────
echo ""
echo "[2/3] Setting up uv..."
if ! command -v uv &>/dev/null; then
    echo "  uv not found — installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh >>"$LOG_FILE" 2>&1
    export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv &>/dev/null; then
    echo "✗ uv install failed. Check: $LOG_FILE"
    exit 127
fi
echo "  uv $(uv --version 2>/dev/null | awk '{print $2}') — OK"

# ── [3/3] Install syscontrol ──────────────────────────────────────────────────
echo ""
echo "[3/3] Installing syscontrol from $REPO_URL ..."
if ! uv tool install --force "git+$REPO_URL" >>"$LOG_FILE" 2>&1; then
    echo "✗ uv tool install failed. Check: $LOG_FILE"
    exit 1
fi
echo "  Installed (uv tool)"

# Ensure ~/.local/bin is on PATH for future shells
SHELL_NAME="$(basename "${SHELL:-/bin/bash}")"
case "$SHELL_NAME" in
    zsh)  PROFILE="$HOME/.zshrc" ;;
    bash) PROFILE="$HOME/.bashrc" ;;
    *)    PROFILE="$HOME/.profile" ;;
esac

PATH_NOTE=""
if ! echo ":$PATH:" | grep -q ":$HOME/.local/bin:"; then
    if ! grep -q '\.local/bin' "$PROFILE" 2>/dev/null; then
        {
            echo ""
            echo "# Added by syscontrol installer"
            echo 'export PATH="$HOME/.local/bin:$PATH"'
        } >> "$PROFILE"
        echo "  Added ~/.local/bin to PATH in $PROFILE"
    fi
    PATH_NOTE='  ⚠  Restart your shell or run:  export PATH="$HOME/.local/bin:$PATH"'
fi

# ── Install updater ───────────────────────────────────────────────────────────
cat > "$UPDATE_BIN" <<'EOF'
#!/bin/bash
# syscontrol-cli-update — reinstall syscontrol CLI from latest master
set -euo pipefail
REPO_URL="https://github.com/ks6573/SysControl.git"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v uv &>/dev/null; then
    echo "✗ uv not found on PATH. Re-run the installer:"
    echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ks6573/SysControl/master/install-cli.sh)"'
    exit 127
fi

echo "Updating syscontrol from $REPO_URL ..."
uv tool install --force "git+$REPO_URL"
echo "✓ Updated. Run: syscontrol --help"
EOF
chmod +x "$UPDATE_BIN"
echo "  Update command: syscontrol-cli-update"

# ── Done ──────────────────────────────────────────────────────────────────────
INSTALLED_VERSION="$(uv tool list 2>/dev/null | awk -v t="$TOOL_NAME" '$1==t {print $2}')"
echo ""
echo "══════════════════════════════════════════"
echo " ✓ SysControl CLI ${INSTALLED_VERSION:+v$INSTALLED_VERSION }installed!"
echo ""
echo "   Run:           syscontrol"
echo "   Update later:  syscontrol-cli-update"
echo "   Uninstall:     /bin/bash -c \"\$(curl -fsSL \\"
echo "                  https://raw.githubusercontent.com/ks6573/SysControl/master/install-cli.sh)\" -- --uninstall"
echo ""
echo "   Provider setup:"
echo "     • Local (default):  install Ollama from https://ollama.com"
echo "                         then:  ollama pull qwen3:30b"
echo "     • Cloud:            syscontrol --provider cloud --api-key <KEY>"
[ -n "$PATH_NOTE" ] && echo "" && echo "$PATH_NOTE"
echo "══════════════════════════════════════════"
echo ""
