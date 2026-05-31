"""Left sidebar: app header, New-chat button, grouped session list, settings gear."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from flet_app import theme
from flet_app.models import GuiSession

OnId = Callable[[str], None]


class Sidebar:
    def __init__(
        self,
        on_new: Callable[[], None],
        on_select: OnId,
        on_delete: OnId,
        on_pin: OnId,
        on_settings: Callable[[], None],
    ) -> None:
        self._on_new = on_new
        self._on_select = on_select
        self._on_delete = on_delete
        self._on_pin = on_pin

        header = ft.Row(
            [
                ft.Icon(ft.Icons.MONITOR_HEART_ROUNDED, size=20, color=theme.ACCENT),
                ft.Text("SysControl", size=16, weight=ft.FontWeight.BOLD, color=theme.TEXT, expand=True),
                ft.IconButton(
                    icon=ft.Icons.SETTINGS_OUTLINED, icon_size=18, icon_color=theme.TEXT_DIM,
                    tooltip="Settings", on_click=lambda _e: on_settings(),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        new_btn = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.ADD, size=18, color=theme.ACCENT),
                 ft.Text("New chat", size=14, weight=ft.FontWeight.W_500, color=theme.TEXT)],
                spacing=8,
            ),
            on_click=lambda _e: on_new(), ink=True,
            bgcolor=theme.SURFACE, border=ft.Border.all(1, theme.BORDER),
            border_radius=10, padding=ft.Padding.symmetric(vertical=10, horizontal=12),
        )
        self.list = ft.ListView(expand=True, spacing=2)
        self.control = ft.Container(
            width=274, bgcolor=theme.SURFACE,
            padding=ft.Padding.symmetric(vertical=14, horizontal=12),
            content=ft.Column(
                [header, ft.Container(height=8), new_btn, ft.Container(height=10), self.list],
                expand=True, spacing=0,
            ),
        )

    def _section(self, label: str) -> ft.Control:
        return ft.Container(
            content=ft.Text(label.upper(), size=11, weight=ft.FontWeight.W_500, color=theme.TEXT_DIM),
            padding=ft.Padding.only(left=8, top=12, bottom=4),
        )

    def _row(self, session: GuiSession, current_id: str) -> ft.Control:
        active = session.id == current_id
        menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_HORIZ, icon_size=16, tooltip="",
            items=[
                ft.PopupMenuItem(
                    text="Unpin" if session.pinned else "Pin",
                    on_click=lambda _e, sid=session.id: self._on_pin(sid),
                ),
                ft.PopupMenuItem(
                    text="Delete",
                    on_click=lambda _e, sid=session.id: self._on_delete(sid),
                ),
            ],
        )
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.PUSH_PIN if session.pinned else ft.Icons.CHAT_BUBBLE_OUTLINE,
                        size=14, color=theme.ACCENT if session.pinned else theme.TEXT_DIM,
                    ),
                    ft.Text(
                        session.title, size=13, color=theme.TEXT, expand=True,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    menu,
                ],
                spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_click=lambda _e, sid=session.id: self._on_select(sid), ink=True,
            bgcolor=theme.SURFACE_ALT if active else None,
            border_radius=8, padding=ft.Padding.only(left=10, right=2, top=2, bottom=2),
        )

    def refresh(self, sessions: list[GuiSession], current_id: str) -> None:
        rows: list[ft.Control] = []
        pinned = [s for s in sessions if s.pinned and not s.archived]
        recent = [s for s in sessions if not s.pinned and not s.archived]
        if pinned:
            rows.append(self._section("Pinned"))
            rows.extend(self._row(s, current_id) for s in pinned)
        if recent:
            rows.append(self._section("Chats"))
            rows.extend(self._row(s, current_id) for s in recent)
        if not rows:
            rows.append(ft.Container(
                content=ft.Text("No chats yet", size=12, color=theme.TEXT_DIM),
                padding=ft.Padding.all(10),
            ))
        self.list.controls = rows
        self.list.update()
