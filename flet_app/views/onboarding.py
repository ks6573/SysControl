"""First-run onboarding: pick a provider (Local Ollama vs Ollama Cloud) and,
for cloud, enter an API key.  Shown when no ``gui_config.json`` exists yet.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from flet_app import theme
from flet_app.store import provider_config

OnComplete = Callable[[str, str, str, str], None]  # base_url, model, label, api_key


def build_onboarding(on_complete: OnComplete) -> ft.AlertDialog:
    state = {"provider": "local"}
    key_field = ft.TextField(
        label="Ollama Cloud API key", password=True, can_reveal_password=True,
        visible=False, border_color=theme.BORDER, focused_border_color=theme.ACCENT,
    )
    error = ft.Text("", size=12, color=theme.ERROR, visible=False)
    hint = ft.Text(
        "Local runs models on your machine via Ollama (no key needed). "
        "Cloud uses Ollama Cloud and needs an API key.",
        size=12, color=theme.TEXT_DIM,
    )

    seg = ft.SegmentedButton(
        selected={"local"},
        segments=[
            ft.Segment(value="local", label=ft.Text("Local (Ollama)")),
            ft.Segment(value="cloud", label=ft.Text("Cloud")),
        ],
    )

    def on_change(_e: ft.ControlEvent) -> None:
        state["provider"] = next(iter(seg.selected))
        key_field.visible = state["provider"] == "cloud"
        error.visible = False
        dlg.update()

    seg.on_change = on_change

    def cont(_e: ft.ControlEvent) -> None:
        if state["provider"] == "cloud":
            api = (key_field.value or "").strip()
            if not api:
                error.value = "An API key is required for Ollama Cloud."
                error.visible = True
                dlg.update()
                return
            cfg = provider_config.default_cloud()
            on_complete(cfg["baseURL"], cfg["model"], cfg["label"], api)
        else:
            cfg = provider_config.default_local()
            on_complete(cfg["baseURL"], cfg["model"], cfg["label"], "")

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            [ft.Icon(ft.Icons.MONITOR_HEART_ROUNDED, color=theme.ACCENT),
             ft.Text("Welcome to SysControl")],
            spacing=10,
        ),
        content=ft.Container(
            width=420,
            content=ft.Column(
                [hint, ft.Container(height=6), seg, key_field, error],
                tight=True, spacing=10,
            ),
        ),
        actions=[ft.FilledButton("Continue", on_click=cont)],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    return dlg
