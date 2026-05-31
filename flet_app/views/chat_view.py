"""The central chat area: a scrolling message list, an empty/welcome state, a
status banner (connecting / errors), and a Ctrl+F search bar.  The controller
owns the live-turn state and appends/updates controls in ``self.list``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

import flet as ft

from flet_app import theme

_STARTERS = [
    ("What's my CPU and memory usage right now?", ft.Icons.MEMORY),
    ("Show me the top 5 processes by memory.", ft.Icons.LIST_ALT),
    ("How much disk space is free?", ft.Icons.STORAGE),
    ("Check my battery and network status.", ft.Icons.BOLT),
]


class ChatView:
    def __init__(self, on_starter: Callable[[str], None]) -> None:
        self._on_starter = on_starter
        # Search callbacks are wired by the controller.
        self.on_search_change: Callable[[str], None] = lambda _q: None
        self.on_search_next: Callable[[], None] = lambda: None
        self.on_search_prev: Callable[[], None] = lambda: None

        self.list = ft.ListView(
            expand=True, spacing=10, auto_scroll=True,
            padding=ft.Padding.symmetric(vertical=18, horizontal=22),
        )

        # ── status banner ──
        self._banner_text = ft.Text("", size=12, color=theme.TEXT, expand=True)
        self._banner_ring = ft.ProgressRing(width=13, height=13, stroke_width=2, color=theme.ACCENT)
        self.banner = ft.Container(
            visible=False,
            content=ft.Row([self._banner_ring, self._banner_text], spacing=8,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=theme.SURFACE_ALT, padding=ft.Padding.symmetric(vertical=8, horizontal=16),
        )

        # ── search bar (Ctrl+F) ──
        self.search_field = ft.TextField(
            hint_text="Find in conversation…", autofocus=True, expand=True, text_size=13,
            border_color=theme.BORDER, focused_border_color=theme.ACCENT,
            on_change=lambda e: self.on_search_change(e.control.value or ""),
            on_submit=lambda _e: self.on_search_next(),
        )
        self.search_label = ft.Text("", size=12, color=theme.TEXT_DIM)
        self.search_bar = ft.Container(
            visible=False, bgcolor=theme.SURFACE_ALT,
            padding=ft.Padding.symmetric(vertical=6, horizontal=12),
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SEARCH, size=16, color=theme.TEXT_DIM),
                    self.search_field, self.search_label,
                    ft.IconButton(ft.Icons.KEYBOARD_ARROW_UP, icon_size=18, tooltip="Previous",
                                  on_click=lambda _e: self.on_search_prev()),
                    ft.IconButton(ft.Icons.KEYBOARD_ARROW_DOWN, icon_size=18, tooltip="Next",
                                  on_click=lambda _e: self.on_search_next()),
                    ft.IconButton(ft.Icons.CLOSE, icon_size=18, tooltip="Close",
                                  on_click=lambda _e: self.hide_search()),
                ],
                spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        self.control = ft.Column([self.banner, self.search_bar, self.list], expand=True, spacing=0)

    # ── banner ──────────────────────────────────────────────────────────────
    def set_banner(self, text: str, *, busy: bool = False, error: bool = False) -> None:
        self._banner_text.value = text
        self._banner_text.color = theme.ERROR if error else theme.TEXT
        self._banner_ring.visible = busy
        self.banner.bgcolor = ft.Colors.with_opacity(0.12, theme.ERROR) if error else theme.SURFACE_ALT
        self.banner.visible = True
        self.banner.update()

    def hide_banner(self) -> None:
        self.banner.visible = False
        self.banner.update()

    # ── search ────────────────────────────────────────────────────────────────
    def show_search(self) -> None:
        self.search_bar.visible = True
        self.search_field.value = ""
        self.search_label.value = ""
        self.search_bar.update()
        self.search_field.focus()

    def hide_search(self) -> None:
        self.search_bar.visible = False
        self.search_bar.update()
        self.on_search_change("")  # clears highlights

    def set_search_label(self, text: str) -> None:
        self.search_label.value = text
        self.search_label.update()

    # ── message list ─────────────────────────────────────────────────────────
    def clear(self) -> None:
        self.list.controls.clear()

    def add(self, control: ft.Control) -> None:
        self.list.controls.append(control)

    def commit(self) -> None:
        self.list.update()

    def scroll_to_key(self, key: str) -> None:
        # Scroll is best-effort; the highlight still conveys the match if the
        # Flet scroll-key API shifts between versions.
        with contextlib.suppress(Exception):
            self.list.scroll_to(scroll_key=key, duration=200)

    def show_empty(self) -> None:
        """Render the welcome / starter-prompt state."""
        self.clear()
        cards = [
            ft.Container(
                content=ft.Row(
                    [ft.Icon(icon, size=18, color=theme.ACCENT),
                     ft.Text(prompt, size=13, color=theme.TEXT, expand=True)],
                    spacing=10,
                ),
                on_click=lambda _e, p=prompt: self._on_starter(p),
                ink=True, bgcolor=theme.SURFACE, border=ft.Border.all(1, theme.BORDER),
                border_radius=12, padding=ft.Padding.symmetric(vertical=14, horizontal=16),
            )
            for prompt, icon in _STARTERS
        ]
        self.list.controls.append(
            ft.Column(
                [
                    ft.Container(height=40),
                    ft.Icon(ft.Icons.MONITOR_HEART_ROUNDED, size=46, color=theme.ACCENT),
                    ft.Text("SysControl", size=24, weight=ft.FontWeight.BOLD, color=theme.TEXT),
                    ft.Text(
                        "Ask about your system — processes, hardware, files, network, and more.",
                        size=13, color=theme.TEXT_DIM, text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(height=16),
                    *cards,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10,
            )
        )
