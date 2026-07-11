"""Settings dialog: LLM provider configuration, connection test, and the
permission toggles that write ``~/.syscontrol/config.json`` (shared with the
CLI and MCP server).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft

from flet_app import theme
from flet_app.store import permissions, provider_config

if TYPE_CHECKING:
    from flet_app.controller import AppController

_FLAG_LABELS = {
    "allow_shell": "Shell commands",
    "allow_messaging": "Send messages",
    "allow_message_history": "Read message history",
    "allow_screenshot": "Screenshots",
    "allow_file_read": "Read files",
    "allow_file_write": "Write files",
    "allow_calendar": "Calendar",
    "allow_contacts": "Contacts",
    "allow_accessibility": "Accessibility / window info",
    "allow_tool_creation": "Self-extension (create tools)",
    "allow_deep_research": "Deep research",
    "allow_email": "Email",
    "allow_notes": "Notes",
    "allow_brew": "Homebrew (macOS)",
    "allow_agents": "Sub-agents",
    "allow_clipboard": "Clipboard",
    "allow_automations": "Scheduled automations",
    "allow_connectors": "External MCP connectors",
}


def _humanize(flag: str) -> str:
    return _FLAG_LABELS.get(flag, flag.removeprefix("allow_").replace("_", " ").title())


def build_settings_dialog(controller: AppController) -> ft.AlertDialog:
    cur = controller.provider
    is_cloud = not provider_config.is_local(cur.get("baseURL", ""))

    seg = ft.SegmentedButton(
        selected={"cloud" if is_cloud else "local"},
        segments=[
            ft.Segment(value="local", label=ft.Text("Local (Ollama)")),
            ft.Segment(value="cloud", label=ft.Text("Cloud / Compatible")),
        ],
    )
    base_url = ft.TextField(
        label="Base URL", value=cur.get("baseURL", ""), text_size=13,
        border_color=theme.BORDER, focused_border_color=theme.ACCENT,
    )
    model = ft.TextField(
        label="Model", value=cur.get("model", ""), text_size=13,
        border_color=theme.BORDER, focused_border_color=theme.ACCENT,
    )
    api_key = ft.TextField(
        label="API key (Cloud only)", value=cur.get("api_key", ""),
        password=True, can_reveal_password=True, text_size=13, visible=is_cloud,
        border_color=theme.BORDER, focused_border_color=theme.ACCENT,
    )
    test_result = ft.Text("", size=12, color=theme.TEXT_DIM)

    def on_provider_change(_e: ft.ControlEvent) -> None:
        choice = next(iter(seg.selected))
        defaults = provider_config.default_cloud() if choice == "cloud" else provider_config.default_local()
        base_url.value = defaults["baseURL"]
        model.value = defaults["model"]
        api_key.visible = choice == "cloud"
        dlg.update()

    seg.on_change = on_provider_change

    def on_test(_e: ft.ControlEvent) -> None:
        test_result.value = "Testing…"
        test_result.color = theme.TEXT_DIM
        dlg.update()
        ok, msg = controller.test_connection(
            base_url.value or "", model.value or "", api_key.value or "",
        )
        test_result.value = msg
        test_result.color = theme.SUCCESS if ok else theme.ERROR
        dlg.update()

    def on_save(_e: ft.ControlEvent) -> None:
        choice = next(iter(seg.selected))
        label = provider_config.CLOUD_LABEL if choice == "cloud" else provider_config.LOCAL_LABEL
        controller.apply_provider(
            base_url.value or "", model.value or "", label, api_key.value or "",
        )
        controller.close_dialog()

    # Permission switches.
    current_perms = permissions.load_permissions()
    perm_switches: list[ft.Control] = []
    for flag in permissions.PERMISSION_FLAGS:
        perm_switches.append(
            ft.Row(
                [
                    ft.Text(_humanize(flag), size=13, color=theme.TEXT, expand=True),
                    ft.Switch(
                        value=current_perms.get(flag, False),
                        active_color=theme.ACCENT,
                        on_change=lambda e, f=flag: permissions.set_permission(f, e.control.value),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

    provider_section = ft.Column(
        [
            ft.Text("Provider", size=14, weight=ft.FontWeight.BOLD, color=theme.TEXT),
            seg, base_url, model, api_key,
            ft.Row([ft.OutlinedButton("Test connection", on_click=on_test), test_result],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
        ],
        spacing=10, tight=True,
    )
    perms_section = ft.Column(
        [
            ft.Container(height=8),
            ft.Text("Permissions", size=14, weight=ft.FontWeight.BOLD, color=theme.TEXT),
            ft.Text(
                "Sensitive tools are off by default. Some are macOS-only and will "
                "report 'not supported on Windows' if used here.",
                size=11, color=theme.TEXT_DIM,
            ),
            *perm_switches,
        ],
        spacing=8, tight=True,
    )

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text("Settings"),
        content=ft.Container(
            width=460, height=520,
            content=ft.Column([provider_section, perms_section], scroll=ft.ScrollMode.AUTO, spacing=6),
        ),
        actions=[
            ft.TextButton("Close", on_click=lambda _e: controller.close_dialog()),
            ft.FilledButton("Save provider", on_click=on_save),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    return dlg
