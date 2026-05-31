"""Bottom input bar: multiline TextField with Enter-to-send / Shift+Enter newline,
a file-attachment chip, and Send/Stop buttons that track streaming state.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from flet_app import theme

# File types the agent can read via its document/file tools.
ATTACH_EXTENSIONS = ["pdf", "xlsx", "xls", "csv", "docx", "doc", "txt", "md", "rst", "json", "log"]


class InputBar:
    def __init__(
        self,
        on_send: Callable[[str], None],
        on_cancel: Callable[[], None],
        on_attach: Callable[[], None],
    ) -> None:
        self._on_send = on_send
        self._on_cancel = on_cancel
        self._on_attach = on_attach
        self._streaming = False
        self._attached: tuple[str, str] | None = None  # (path, name)

        self.field = ft.TextField(
            hint_text="Ask about your system…   (Enter to send · Shift+Enter for a new line)",
            multiline=True, min_lines=1, max_lines=8, shift_enter=True,
            text_size=14, expand=True, on_submit=self._submit,
            filled=True, bgcolor=theme.SURFACE,
            border_color=theme.BORDER, focused_border_color=theme.ACCENT,
            content_padding=ft.Padding.symmetric(vertical=12, horizontal=14),
        )
        self.attach_btn = ft.IconButton(
            icon=ft.Icons.ATTACH_FILE, icon_color=theme.TEXT_DIM,
            tooltip="Attach a file", on_click=lambda _e: self._on_attach(),
        )
        self.send_btn = ft.IconButton(
            icon=ft.Icons.ARROW_UPWARD_ROUNDED, icon_color=theme.ACCENT,
            tooltip="Send", on_click=self._submit,
        )
        self.stop_btn = ft.IconButton(
            icon=ft.Icons.STOP_CIRCLE_ROUNDED, icon_color=theme.ERROR,
            tooltip="Stop", on_click=self._cancel, visible=False,
        )

        self._chip_label = ft.Text("", size=12, color=theme.TEXT, max_lines=1,
                                   overflow=ft.TextOverflow.ELLIPSIS)
        self.chip = ft.Container(
            visible=False,
            content=ft.Row(
                [ft.Icon(ft.Icons.INSERT_DRIVE_FILE, size=14, color=theme.ACCENT),
                 self._chip_label,
                 ft.IconButton(icon=ft.Icons.CLOSE, icon_size=14, icon_color=theme.TEXT_DIM,
                               tooltip="Remove", on_click=lambda _e: self.clear_attachment())],
                spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=theme.SURFACE, border=ft.Border.all(1, theme.BORDER),
            border_radius=8, padding=ft.Padding.only(left=8, right=2, top=2, bottom=2),
            margin=ft.Margin.only(bottom=6, left=4),
        )

        self.control = ft.Container(
            padding=ft.Padding.symmetric(vertical=10, horizontal=16),
            bgcolor=theme.BG,
            content=ft.Column(
                [
                    ft.Row([self.chip], tight=True),
                    ft.Row(
                        [self.attach_btn, self.field, self.send_btn, self.stop_btn],
                        vertical_alignment=ft.CrossAxisAlignment.END, spacing=4,
                    ),
                ],
                spacing=0, tight=True,
            ),
        )

    def _submit(self, _e: ft.ControlEvent | None = None) -> None:
        if self._streaming:
            return
        text = (self.field.value or "").strip()
        if not text and self._attached is None:
            return
        if self._attached is not None:
            note = f"[Attached file: {self._attached[0]}]"
            text = f"{text}\n\n{note}".strip()
            self.clear_attachment()
        self.field.value = ""
        self.field.update()
        self._on_send(text)

    def _cancel(self, _e: ft.ControlEvent | None = None) -> None:
        self._on_cancel()

    def set_attachment(self, path: str, name: str) -> None:
        self._attached = (path, name)
        self._chip_label.value = name
        self.chip.visible = True
        self.control.update()

    def clear_attachment(self) -> None:
        self._attached = None
        self.chip.visible = False
        self.control.update()

    def set_streaming(self, streaming: bool) -> None:
        self._streaming = streaming
        self.send_btn.visible = not streaming
        self.stop_btn.visible = streaming
        self.control.update()

    def set_enabled(self, enabled: bool) -> None:
        self.field.disabled = not enabled
        self.send_btn.disabled = not enabled
        self.attach_btn.disabled = not enabled
        self.control.update()
