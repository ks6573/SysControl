"""Ctrl+K command palette: fuzzy-search chat sessions + quick "New chat" action."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from flet_app import theme
from flet_app.models import GuiSession


def build_command_palette(
    sessions: list[GuiSession],
    on_select: Callable[[str], None],
    on_new: Callable[[], None],
) -> ft.AlertDialog:
    results = ft.ListView(height=340, spacing=2)

    def action_row(icon: str, label: str, handler: Callable[[], None]) -> ft.Control:
        return ft.Container(
            content=ft.Row(
                [ft.Icon(icon, size=16, color=theme.ACCENT),
                 ft.Text(label, size=13, color=theme.TEXT, expand=True)],
                spacing=10,
            ),
            on_click=lambda _e: handler(), ink=True, border_radius=8,
            padding=ft.Padding.symmetric(vertical=9, horizontal=10),
        )

    def session_row(session: GuiSession) -> ft.Control:
        return ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE, size=15, color=theme.TEXT_DIM),
                 ft.Text(session.title, size=13, color=theme.TEXT, expand=True,
                         max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                spacing=10,
            ),
            on_click=lambda _e, sid=session.id: on_select(sid), ink=True, border_radius=8,
            padding=ft.Padding.symmetric(vertical=9, horizontal=10),
        )

    def rows_for(query: str) -> list[ft.Control]:
        q = query.lower().strip()
        rows: list[ft.Control] = [action_row(ft.Icons.ADD, "New chat", on_new)]
        for s in sessions:
            if not q or q in s.title.lower():
                rows.append(session_row(s))
        return rows

    def on_change(e: ft.ControlEvent) -> None:
        results.controls = rows_for(e.control.value or "")
        results.update()

    field = ft.TextField(
        hint_text="Search chats…", autofocus=True, on_change=on_change,
        prefix_icon=ft.Icons.SEARCH, border_color=theme.BORDER,
        focused_border_color=theme.ACCENT, text_size=14,
    )
    results.controls = rows_for("")  # initial population (no update before mount)

    return ft.AlertDialog(
        modal=True,
        content=ft.Container(
            width=480,
            content=ft.Column([field, ft.Divider(height=1, color=theme.BORDER), results], tight=True, spacing=8),
        ),
    )
