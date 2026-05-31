"""Assemble the SysControl GUI: theme, window, sidebar | chat | input layout."""

from __future__ import annotations

import atexit
import contextlib

import flet as ft

from flet_app import theme
from flet_app.controller import AppController


def build_app(page: ft.Page) -> None:
    """Flet entry target — builds the UI and starts the backend."""
    theme.apply_theme(page)
    with contextlib.suppress(Exception):
        page.window.width = 1120
        page.window.height = 768
        page.window.min_width = 720
        page.window.min_height = 520

    controller = AppController(page)
    page.overlay.append(controller.file_picker)  # FilePicker must live in the overlay
    page.on_keyboard_event = controller.handle_key

    chat_area = ft.Container(
        expand=True, bgcolor=theme.BG,
        content=ft.Column(
            [
                controller.chat.control,
                ft.Divider(height=1, color=theme.BORDER),
                controller.input.control,
            ],
            expand=True, spacing=0,
        ),
    )
    page.add(
        ft.Row(
            [
                controller.sidebar.control,
                ft.VerticalDivider(width=1, color=theme.BORDER),
                chat_area,
            ],
            expand=True, spacing=0,
        )
    )

    page.on_disconnect = lambda _e: controller.shutdown()
    atexit.register(controller.shutdown)
    controller.start()
