"""Rendering of chat messages: user bubbles, assistant markdown, tool cards, charts.

The controller owns the live-turn state and calls these to build/update controls.
``ToolCard`` is a small live widget whose status/result/charts update in place as
the matching tool finishes.
"""

from __future__ import annotations

import flet as ft

from flet_app import theme
from flet_app.charts import extract_chart_paths, strip_chart_markers

MONO = "monospace"
MAX_CHART_WIDTH = 520
_PREVIEW_CHARS = 90


def user_bubble(text: str) -> ft.Control:
    """A right-aligned, accent-tinted bubble for a user message."""
    return ft.Row(
        [ft.Container(
            content=ft.Text(text, color=theme.TEXT, selectable=True, size=14),
            bgcolor=theme.USER_BUBBLE,
            border=ft.Border.all(1, theme.BORDER),
            border_radius=14,
            padding=ft.Padding.symmetric(vertical=9, horizontal=13),
            margin=ft.Margin.only(left=72),
        )],
        alignment=ft.MainAxisAlignment.END,
    )


def assistant_markdown(text: str = "") -> ft.Markdown:
    """A Markdown control for assistant output (returned so it can stream-update)."""
    return ft.Markdown(
        value=text,
        selectable=True,
        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
        code_theme=theme.CODE_THEME,
    )


def assistant_block(md: ft.Markdown) -> ft.Control:
    """Wrap an assistant Markdown control with left-aligned padding."""
    return ft.Container(
        content=md,
        padding=ft.Padding.only(top=2, bottom=2, right=40),
    )


def error_bubble(text: str) -> ft.Control:
    return ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.ERROR_OUTLINE, color=theme.ERROR, size=18),
             ft.Text(text, color=theme.ERROR, selectable=True, size=13, expand=True)],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.START,
        ),
        bgcolor=ft.Colors.with_opacity(0.08, theme.ERROR),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.4, theme.ERROR)),
        border_radius=10,
        padding=ft.Padding.symmetric(vertical=8, horizontal=10),
        margin=ft.Margin.symmetric(vertical=4, horizontal=0),
    )


def chart_image(path: str) -> ft.Control:
    return ft.Container(
        content=ft.Image(src=path, width=MAX_CHART_WIDTH, fit=ft.BoxFit.CONTAIN, border_radius=8),
        margin=ft.Margin.only(top=6),
    )


class ToolCard:
    """A live, expandable card representing one tool call."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.done = False
        self._lead = ft.ProgressRing(width=14, height=14, stroke_width=2, color=theme.ACCENT)
        self._preview = ft.Text(
            "Running…", size=12, color=theme.TEXT_DIM, expand=True,
            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._chevron = ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16, color=theme.TEXT_DIM)
        self._lead_slot = ft.Row([self._lead], width=20)
        self._body = ft.Column(visible=False, spacing=8)
        self._expanded = False
        header = ft.Container(
            content=ft.Row(
                [self._lead_slot,
                 ft.Text(name, size=13, weight=ft.FontWeight.W_500, color=theme.TEXT),
                 self._preview, self._chevron],
                spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_click=self._toggle, ink=True,
            padding=ft.Padding.symmetric(vertical=7, horizontal=10),
            border_radius=10,
        )
        self.control = ft.Container(
            content=ft.Column([header, self._body], spacing=0),
            bgcolor=theme.TOOL_SURFACE,
            border=ft.Border.all(1, theme.TOOL_BORDER),
            border_radius=10,
            margin=ft.Margin.symmetric(vertical=4, horizontal=0),
        )

    def _toggle(self, _e: ft.ControlEvent) -> None:
        self._expanded = not self._expanded
        self._body.visible = self._expanded
        self._chevron.name = ft.Icons.EXPAND_MORE if self._expanded else ft.Icons.CHEVRON_RIGHT
        self.control.update()

    def finish(self, result: str, is_error: bool, live: bool = True) -> None:
        """Mark the tool finished and fill in its result + any inline charts.

        When *live* is False the card is being built for an already-mounted list
        render (loaded session), so we skip the per-control ``update()`` — the
        caller commits the whole list once.
        """
        self.done = True
        self._lead_slot.controls = [ft.Icon(
            ft.Icons.ERROR_OUTLINE if is_error else ft.Icons.CHECK_CIRCLE,
            size=16, color=theme.ERROR if is_error else theme.SUCCESS,
        )]
        clean = strip_chart_markers(result)
        first_line = next((ln for ln in clean.splitlines() if ln.strip()), "")
        self._preview.value = first_line[:_PREVIEW_CHARS] or ("error" if is_error else "done")
        self._preview.color = theme.ERROR if is_error else theme.TEXT_DIM
        body: list[ft.Control] = []
        if clean:
            body.append(ft.Text(
                clean, size=12, color=theme.TEXT_DIM, selectable=True, font_family=MONO,
            ))
        for path in extract_chart_paths(result):
            body.append(chart_image(path))
        self._body.controls = body
        if live:
            self.control.update()
