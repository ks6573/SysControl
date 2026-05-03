"""
SysControl Agent — Sub-agent specifications and registry.

Defines built-in sub-agent types and provides a registry for looking them up.
Each AgentSpec describes the agent's purpose, the subset of MCP tools it may
use, and an overriding system prompt that narrows its focus.

Built-in agents
---------------
explorer    Read-only system investigator (metrics, processes, file listings).
analyst     Data analyst (reads files, spreadsheets, PDFs, CSVs).
researcher  Web researcher (search + fetch, no local file access).
writer      Writer/editor (reads existing content, can write files).
coder       Code editor/developer (read, search, edit code, git, shell).
"""
from __future__ import annotations

import functools
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    """Immutable specification for a named sub-agent.

    Attributes:
        name:          Short identifier used to invoke the agent.
        description:   One-sentence summary shown to the orchestrating LLM.
        system_prompt: Focused instruction injected as the sub-agent's persona.
        allowed_tools: Tuple of tool names the sub-agent may call.
                       ``None`` means all tools are available (minus run_agent).
        max_rounds:    Upper bound on tool-call rounds per run.
    """

    name: str
    description: str
    system_prompt: str
    allowed_tools: tuple[str, ...] | None
    max_rounds: int = 8


class AgentNotFoundError(KeyError):
    """Raised when an agent name is not present in the registry."""


# ── Tool allowlists ────────────────────────────────────────────────────────────

_EXPLORER_TOOLS: tuple[str, ...] = (
    # System metrics
    "get_cpu_usage", "get_ram_usage", "get_disk_usage", "get_network_usage",
    "get_gpu_usage", "get_battery_status", "get_temperature",
    "get_top_processes", "get_process_info", "get_full_snapshot",
    "list_open_files", "get_network_connections", "get_system_info",
    "get_installed_apps", "get_startup_items",
    # File system (read-only)
    "read_file", "list_directory", "search_files",
    # Web (read-only)
    "web_search", "web_fetch",
    # macOS helpers (read-only)
    "get_calendar_events", "get_reminders", "get_clipboard_content",
)

_ANALYST_TOOLS: tuple[str, ...] = (
    "read_file", "list_directory", "search_files",
    "read_spreadsheet", "read_pdf", "read_document",
    "web_search", "web_fetch",
)

_RESEARCHER_TOOLS: tuple[str, ...] = (
    "web_search", "web_fetch",
)

_WRITER_TOOLS: tuple[str, ...] = (
    "read_file", "read_file_lines", "write_file", "edit_file",
    "list_directory", "grep_files", "glob_files",
    "read_document", "read_pdf",
)

_CODER_TOOLS: tuple[str, ...] = (
    # File reading
    "read_file", "read_file_lines", "list_directory",
    # File writing / editing
    "write_file", "edit_file",
    # Search & navigation
    "grep_files", "glob_files",
    # Git awareness
    "git_status", "git_diff",
    # Shell (for tests, builds, linters)
    "run_shell_command",
)


# ── Built-in agent definitions ────────────────────────────────────────────────

BUILT_IN_AGENTS: dict[str, AgentSpec] = {
    "explorer": AgentSpec(
        name="explorer",
        description=(
            "Read-only system investigator. Gathers CPU, memory, disk, network, "
            "process, and file-system data. Cannot write files or run shell commands."
        ),
        system_prompt=(
            "You are a focused system investigator. "
            "Answer the task using precise system data gathered from available tools. "
            "Be concise and factual — return only what was asked, with real values."
        ),
        allowed_tools=_EXPLORER_TOOLS,
    ),
    "analyst": AgentSpec(
        name="analyst",
        description=(
            "Data analyst. Reads files, spreadsheets, PDFs, and CSVs to answer "
            "analytical questions. Cannot write or modify files."
        ),
        system_prompt=(
            "You are a precise data analyst. "
            "Read the requested data and provide clear findings with numbers and evidence. "
            "Include actual values, not vague summaries."
        ),
        allowed_tools=_ANALYST_TOOLS,
    ),
    "researcher": AgentSpec(
        name="researcher",
        description=(
            "Web researcher. Searches the web and reads pages to answer questions. "
            "For deep multi-step research with claim verification, use deep_research instead."
        ),
        system_prompt=(
            "You are a web researcher. "
            "Search for information, read relevant pages, and provide a well-sourced answer. "
            "Cite your sources. Note conflicting information when present."
        ),
        allowed_tools=_RESEARCHER_TOOLS,
    ),
    "writer": AgentSpec(
        name="writer",
        description=(
            "Writer and editor. Reads existing files for context, then produces or "
            "rewrites content. Can write files when explicitly requested."
        ),
        system_prompt=(
            "You are a precise technical writer. "
            "Read any referenced files for context, then produce the requested content. "
            "Be clear, correct, and concise. Match the tone and style of existing content "
            "when editing."
        ),
        allowed_tools=_WRITER_TOOLS,
    ),
    "coder": AgentSpec(
        name="coder",
        description=(
            "Code editor and developer. Reads, searches, and edits code files with "
            "targeted find-and-replace. Can run shell commands for testing and linting. "
            "Use for code modifications, refactoring, and development tasks."
        ),
        system_prompt=(
            "You are a precise code editor. Follow these rules strictly:\n"
            "1. ALWAYS read the file before editing — never guess at content.\n"
            "2. Make minimal, targeted changes using edit_file — avoid rewriting entire files.\n"
            "3. Use grep_files and glob_files to understand the codebase before making changes.\n"
            "4. After editing, verify your changes by reading the modified section.\n"
            "5. Run relevant tests or linters after code changes when possible.\n"
            "6. Preserve existing code style, indentation, and conventions."
        ),
        allowed_tools=_CODER_TOOLS,
        max_rounds=12,
    ),
}


# ── Registry ──────────────────────────────────────────────────────────────────


class AgentRegistry:
    """Provides lookup access to AgentSpec instances."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentSpec] = dict(BUILT_IN_AGENTS)

    def get(self, name: str) -> AgentSpec:
        """Return the AgentSpec for *name*.

        Raises:
            AgentNotFoundError: If *name* is not registered.
        """
        if name not in self._agents:
            raise AgentNotFoundError(
                f"Agent '{name}' not found. "
                f"Available: {sorted(self._agents)}"
            )
        return self._agents[name]

    def list_all(self) -> list[dict[str, str]]:
        """Return a list of ``{"name": …, "description": …}`` dicts."""
        return [
            {"name": s.name, "description": s.description}
            for s in self._agents.values()
        ]


# Lazy singleton — initialized on first access, not at import time.
# functools.cache uses an internal RLock, so concurrent first-calls are safe
# without an explicit double-checked-locking pattern.
@functools.cache
def _get_registry() -> AgentRegistry:
    """Return the module-level AgentRegistry, creating it on first call."""
    return AgentRegistry()


def get_agent(name: str) -> AgentSpec:
    """Look up an AgentSpec by name (module-level convenience wrapper)."""
    return _get_registry().get(name)


def list_agents() -> list[dict[str, str]]:
    """Return a list of all registered agents with name and description."""
    return _get_registry().list_all()
