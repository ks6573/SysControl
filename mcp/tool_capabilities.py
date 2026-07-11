"""Structured capability metadata for SysControl tools.

The dispatch registry intentionally stays focused on execution.  This module
provides the product-facing metadata needed by clients, approval UIs, connector
discovery, and future policy engines without duplicating tool implementations.
"""

from __future__ import annotations

import platform
from typing import Literal, TypedDict

PlatformName = Literal["macos", "windows", "linux"]
RiskLevel = Literal["read", "write", "destructive"]


class ToolCapability(TypedDict):
    category: str
    platforms: tuple[PlatformName, ...]
    permission: str | None
    risk: RiskLevel
    available: bool


ALL_PLATFORMS: tuple[PlatformName, ...] = ("macos", "windows", "linux")
MACOS_ONLY: tuple[PlatformName, ...] = ("macos",)
DESKTOP_PLATFORMS: tuple[PlatformName, ...] = ("macos", "windows")

_MACOS_ONLY_TOOLS = frozenset({
    "brew_list", "brew_install", "brew_upgrade", "brew_uninstall",
    "get_time_machine_status", "send_imessage", "get_imessage_history",
    "read_emails", "send_email", "search_emails", "browser_navigate",
    "browser_get_page", "get_now_playing", "media_control", "get_calendar_events",
    "get_contact", "list_notes", "read_note", "create_note", "run_shortcut",
    "toggle_do_not_disturb", "eject_disk", "cleanup_caches",
    "do_not_disturb_status", "focus_mode_set",
})

_DESKTOP_TOOLS = frozenset({
    "get_wifi_networks", "open_app", "quit_app", "get_volume", "set_volume",
    "get_frontmost_app", "battery_health_report",
})

_PERMISSION_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    ("allow_shell", frozenset({"run_shell_command"})),
    ("allow_messaging", frozenset({"send_imessage"})),
    ("allow_message_history", frozenset({"get_imessage_history"})),
    ("allow_screenshot", frozenset({"take_screenshot"})),
    ("allow_file_read", frozenset({
        "read_file", "read_file_lines", "glob_files", "grep_files", "git_status",
        "git_diff", "read_spreadsheet", "read_document", "read_pdf", "list_directory",
        "search_files", "tail_file", "summarize_directory", "open_file_at_path",
    })),
    ("allow_file_write", frozenset({
        "write_file", "edit_file", "edit_spreadsheet", "edit_document", "move_file",
        "copy_file", "delete_file", "create_directory", "cleanup_downloads",
        "cleanup_caches",
    })),
    ("allow_calendar", frozenset({"get_calendar_events"})),
    ("allow_contacts", frozenset({"get_contact"})),
    ("allow_accessibility", frozenset({
        "browser_navigate", "browser_get_page", "get_frontmost_app",
    })),
    ("allow_tool_creation", frozenset({"create_tool"})),
    ("allow_deep_research", frozenset({"deep_research"})),
    ("allow_email", frozenset({"read_emails", "send_email", "search_emails"})),
    ("allow_notes", frozenset({"list_notes", "read_note", "create_note"})),
    ("allow_brew", frozenset({"brew_list", "brew_install", "brew_upgrade", "brew_uninstall"})),
    ("allow_agents", frozenset({"run_agent"})),
    ("allow_clipboard", frozenset({"get_clipboard", "set_clipboard"})),
    ("allow_automations", frozenset({
        "create_automation", "update_automation", "delete_automation", "run_automation_now",
    })),
    ("allow_connectors", frozenset({
        "add_connector", "remove_connector", "refresh_connectors",
    })),
)

_DESTRUCTIVE_TOOLS = frozenset({
    "kill_process", "brew_uninstall", "delete_file", "cleanup_downloads",
    "cleanup_caches", "eject_disk", "delete_automation", "remove_connector",
})

_WRITE_TOOLS = frozenset({
    "set_reminder", "cancel_reminder", "brew_install", "brew_upgrade",
    "grant_browser_access", "browser_open_url", "browser_navigate", "send_imessage",
    "send_email", "set_clipboard", "take_screenshot", "generate_image", "open_app",
    "quit_app", "set_volume", "media_control", "write_file", "edit_file",
    "edit_spreadsheet", "edit_document", "move_file", "copy_file", "create_directory",
    "run_shell_command", "create_note", "run_shortcut", "toggle_do_not_disturb",
    "create_tool", "append_memory_note", "run_agent", "run_skill", "notify_user",
    "focus_mode_set", "open_file_at_path",
    "create_automation", "update_automation", "run_automation_now",
    "add_connector", "refresh_connectors",
})

_CATEGORY_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    ("monitoring", frozenset({
        "get_cpu_usage", "get_ram_usage", "get_gpu_usage", "get_disk_usage",
        "get_network_usage", "get_realtime_io", "get_full_snapshot",
        "get_system_alerts", "get_hardware_profile", "battery_health_report",
    })),
    ("processes", frozenset({
        "get_top_processes", "get_process_details", "search_process", "kill_process",
        "process_tree", "get_startup_items",
    })),
    ("network", frozenset({
        "get_network_connections", "network_latency_check", "get_wifi_networks",
        "get_weather", "track_package", "get_docker_status",
    })),
    ("browser", frozenset({
        "web_fetch", "web_search", "grant_browser_access", "browser_open_url",
        "browser_navigate", "browser_get_page",
    })),
    ("productivity", frozenset({
        "send_imessage", "get_imessage_history", "read_emails", "send_email",
        "search_emails", "get_calendar_events", "get_contact", "list_notes",
        "read_note", "create_note", "run_shortcut",
    })),
    ("files", frozenset({
        "read_file", "write_file", "read_file_lines", "edit_file", "glob_files",
        "grep_files", "git_status", "git_diff", "read_spreadsheet", "edit_spreadsheet",
        "read_document", "edit_document", "read_pdf", "list_directory", "move_file",
        "copy_file", "delete_file", "create_directory", "search_files", "find_large_files",
        "tail_file", "cleanup_downloads", "cleanup_caches", "summarize_directory",
        "open_file_at_path",
    })),
    ("automation", frozenset({
        "set_reminder", "list_reminders", "cancel_reminder", "notify_user",
        "toggle_do_not_disturb", "do_not_disturb_status", "focus_mode_set",
        "create_automation", "list_automations", "update_automation",
        "delete_automation", "run_automation_now", "list_automation_runs",
        "get_health_trends", "get_audit_log",
    })),
    ("extensions", frozenset({
        "list_user_tools", "create_tool", "list_agents", "run_agent", "list_skills",
        "run_skill", "list_connectors", "add_connector", "remove_connector",
        "refresh_connectors",
    })),
    ("research", frozenset({"deep_research", "generate_image"})),
)


def current_platform_name() -> PlatformName:
    """Return the normalized platform identifier used in tool metadata."""
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    return "linux"


def _platforms_for(name: str) -> tuple[PlatformName, ...]:
    if name in _MACOS_ONLY_TOOLS:
        return MACOS_ONLY
    if name in _DESKTOP_TOOLS:
        return DESKTOP_PLATFORMS
    return ALL_PLATFORMS


def _permission_for(name: str) -> str | None:
    for permission, names in _PERMISSION_GROUPS:
        if name in names:
            return permission
    return None


def _category_for(name: str) -> str:
    for category, names in _CATEGORY_GROUPS:
        if name in names:
            return category
    return "system"


def capability_for(name: str, *, platform_name: PlatformName | None = None) -> ToolCapability:
    """Build normalized metadata for *name* on the selected/current platform."""
    platforms = _platforms_for(name)
    active_platform = platform_name or current_platform_name()
    if name in _DESTRUCTIVE_TOOLS:
        risk: RiskLevel = "destructive"
    elif name in _WRITE_TOOLS:
        risk = "write"
    else:
        risk = "read"
    return {
        "category": _category_for(name),
        "platforms": platforms,
        "permission": _permission_for(name),
        "risk": risk,
        "available": active_platform in platforms,
    }
