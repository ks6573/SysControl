"""
SysControl GUI — Theme detection and QSS stylesheets.

Detects macOS dark/light mode and provides matching Qt Style Sheets.
"""

import subprocess


def is_dark_mode() -> bool:
    """Detect macOS dark mode via AppleInterfaceStyle defaults."""
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True, text=True, timeout=2,
        )
        return result.stdout.strip().lower() == "dark"
    except Exception:
        return True


# ── Color palettes ────────────────────────────────────────────────────────────

DARK = {
    "window_bg":        "#171717",
    "chat_bg":          "#171717",
    "user_bubble":      "#2d2d2d",
    "user_bubble_text": "#ffffff",
    "asst_bubble":      "transparent",
    "asst_bubble_text": "#d9d9d9",
    "input_bg":         "#1f1f1f",
    "input_border":     "#2e2e2e",
    "input_text":       "#d9d9d9",
    "placeholder":      "#404040",
    "status_bg":        "#171717",
    "status_text":      "#404040",
    "accent":           "#3b82f6",
    "send_bg":          "#2563eb",
    "send_hover":       "#1d4ed8",
    "send_text":        "#ffffff",
    "toolbar_bg":       "#171717",
    "toolbar_text":     "#909090",
    "tool_indicator":   "#1f1f1f",
    "tool_text":        "#606060",
    "error_bg":         "#2d1515",
    "error_text":       "#f87171",
    "scrollbar":        "#2e2e2e",
    "scrollbar_bg":     "transparent",
    "border":           "#222222",
    "code_bg":          "#0d0d0d",
}

LIGHT = {
    "window_bg":        "#fafafa",
    "chat_bg":          "#fafafa",
    "user_bubble":      "#e0e0e5",
    "user_bubble_text": "#1a1a1a",
    "asst_bubble":      "transparent",
    "asst_bubble_text": "#1d1d1f",
    "input_bg":         "#ffffff",
    "input_border":     "#e5e5e5",
    "input_text":       "#1d1d1f",
    "placeholder":      "#c0c0c0",
    "status_bg":        "#f0f0f0",
    "status_text":      "#b0b0b0",
    "accent":           "#0071e3",
    "send_bg":          "#0071e3",
    "send_hover":       "#0062c4",
    "send_text":        "#ffffff",
    "toolbar_bg":       "#f0f0f0",
    "toolbar_text":     "#5a5a5a",
    "tool_indicator":   "#ebebeb",
    "tool_text":        "#909090",
    "error_bg":         "#fff0f0",
    "error_text":       "#dc2626",
    "scrollbar":        "#d0d0d0",
    "scrollbar_bg":     "transparent",
    "border":           "#e5e5e5",
    "code_bg":          "#f0f0f0",
}


def get_palette(dark: bool = True) -> dict[str, str]:
    """Return the color palette dict for the given mode."""
    return DARK if dark else LIGHT


def load_stylesheet(dark: bool = True) -> str:
    """Return a QSS stylesheet string for the given mode."""
    c = get_palette(dark)
    return f"""
    QMainWindow, QDialog {{
        background-color: {c["window_bg"]};
    }}
    QWidget {{
        font-family: -apple-system, 'SF Pro Text', system-ui, sans-serif;
    }}

    /* ── Toolbar ─────────────────────────────────────── */
    QToolBar {{
        background-color: {c["toolbar_bg"]};
        border: none;
        spacing: 2px;
        padding: 0 12px;
    }}
    QToolBar QToolButton {{
        background: transparent;
        color: {c["toolbar_text"]};
        border: none;
        padding: 4px 10px;
        border-radius: 5px;
        font-size: 12px;
    }}
    QToolBar QToolButton:hover {{
        background-color: {c["input_bg"]};
        color: {c["input_text"]};
    }}
    QToolBar QLabel {{
        color: {c["toolbar_text"]};
        font-size: 13px;
        font-weight: 600;
    }}

    /* ── Status bar ──────────────────────────────────── */
    QStatusBar {{
        background-color: {c["status_bg"]};
        color: {c["status_text"]};
        border: none;
        font-size: 11px;
    }}
    QStatusBar QLabel {{
        color: {c["status_text"]};
        padding: 0 4px;
        font-size: 11px;
    }}

    /* ── Scroll area (chat) ──────────────────────────── */
    QScrollArea {{
        background-color: {c["chat_bg"]};
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background-color: {c["chat_bg"]};
    }}

    /* ── Scrollbar ───────────────────────────────────── */
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        border: none;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {c["scrollbar"]};
        min-height: 24px;
        border-radius: 3px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {c["accent"]};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    """
