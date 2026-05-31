"""Design tokens for the SysControl Flet GUI (dark-first palette)."""

from __future__ import annotations

import flet as ft

ACCENT = "#7C5CFF"          # violet accent
ACCENT_DIM = "#5B45C7"
BG = "#0F0F14"              # window background
SURFACE = "#17171F"         # panels / cards
SURFACE_ALT = "#1F1F2A"     # hovered / nested surfaces
BORDER = "#2B2B38"
TEXT = "#E8E8EF"
TEXT_DIM = "#9A9AB0"
USER_BUBBLE = "#2A2440"     # accent-tinted user message
TOOL_SURFACE = "#15202B"
TOOL_BORDER = "#24323F"
ERROR = "#FF6B6B"
SUCCESS = "#4ADE80"

# Markdown code-block theme name understood by Flet's Markdown control.
CODE_THEME = "atom-one-dark"


def apply_theme(page: ft.Page) -> None:
    """Apply the dark theme + window chrome defaults to *page*."""
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme_seed=ACCENT, use_material3=True)
    page.bgcolor = BG
    page.padding = 0
    page.title = "SysControl"
