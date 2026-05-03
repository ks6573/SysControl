#!/usr/bin/env python3
"""
SysControl Agent — Interactive CLI.

Spawns the MCP server as a subprocess, converts its tools to the OpenAI format,
then runs a streaming agentic loop so you can ask natural-language questions
about your system and the model will call the right tools autonomously.

Usage:
    uv run agent.py [--provider {cloud,local}] [--model MODEL] [--api-key KEY]
    python agent.py

When selecting the cloud provider you will be prompted to enter your
Ollama API key interactively — no environment variable export needed.
Pass --api-key to skip the prompt entirely (e.g. for scripted/CI use).
"""

import argparse
import contextlib
import datetime
import getpass
import itertools
import json
import os
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from agent import cli_compact, cli_session
from agent.cli_completers import build_completer, expand_at_mentions
from agent.cli_keys import build_key_bindings, install_sigint_handler
from agent.core import (
    BLUE,
    BOLD,
    CYAN,
    DIM,
    EXIT_PHRASES,
    GREEN,
    HAS_FCNTL,
    LOCAL_API_KEY,
    LOCAL_BASE_URL,
    LOCAL_MODEL,
    OLLAMA_CLOUD_BASE_URL,
    OLLAMA_CLOUD_MODEL,
    RESET,
    SERVER_PATH,
    YELLOW,
    MCPClient,
    MCPClientPool,
    TurnCallbacks,
    build_full_system_prompt,
    colorize,
    fcntl_mod,
    fetch_ollama_models,
    llm_client_max_retries,
    llm_client_timeout,
    load_memory,
    load_system_prompt,
    mcp_to_openai_tools,
    run_streaming_turn,
)
from agent.credentials import (
    CREDENTIALS_FILE,
    clear_cloud_api_key,
    load_cloud_api_key,
    save_cloud_api_key,
)
from agent.paths import MEMORY_FILE, USER_DATA_DIR, ensure_user_data_dir
from agent.runner import close_subagent_pool
from agent.slash import CONTINUE, EXIT, SlashCommand, SlashRegistry, SlashResult, parse
from agent.updater import check_for_update, current_version, update_via_uv

# ── Memory ────────────────────────────────────────────────────────────────────

_PRIVACY_NOTICE = (
    f"\n{DIM}╔══════════════════════════════════════════════════════════════╗\n"
    f"║  Privacy Notice                                              ║\n"
    f"║  SysControl stores only what you explicitly choose to save.  ║\n"
    f"║  No personal data is retained by the agent or the LLM.       ║\n"
    f"║  Ollama processes queries locally — see ollama.com/tos for   ║\n"
    f"║  full details on cloud usage (if applicable).                ║\n"
    f"╚══════════════════════════════════════════════════════════════╝{RESET}\n"
)


def offer_memory_save(messages: list[dict]) -> None:
    """
    Ask the user if they want to jot a note into SysControl_Memory.md.
    Called just before the agent exits.
    """
    has_content = any(
        m.get("role") in ("user", "assistant") and m.get("content")
        for m in messages
    )
    if not has_content:
        return

    print(_PRIVACY_NOTICE)
    print(f"{BOLD}Anything worth remembering from this session?{RESET}")
    print(f"{DIM}  Type a short note (e.g. 'User prefers Celsius. Main machine has 32 GB RAM.')  {RESET}")
    print(f"{DIM}  Or press Enter to skip.{RESET}")
    print(f"{BOLD}Note:{RESET} ", end="", flush=True)

    try:
        note = input("").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if note:
        _append_memory_note(note)
    else:
        print(f"{DIM}Nothing saved.{RESET}")


def _append_memory_note(note: str) -> None:
    """Append a single timestamped note line to SysControl_Memory.md."""
    ensure_user_data_dir()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n- [{timestamp}] {note}\n"

    with MEMORY_FILE.open("a", encoding="utf-8") as fh:
        if HAS_FCNTL:
            fcntl_mod.flock(fh, fcntl_mod.LOCK_EX)
        try:
            fh.seek(0, 2)
            if fh.tell() == 0:
                fh.write("# SysControl Memory\n\n")
            fh.write(entry)
        finally:
            if HAS_FCNTL:
                fcntl_mod.flock(fh, fcntl_mod.LOCK_UN)

    print(f"{GREEN}✓ Note saved to {MEMORY_FILE.name}{RESET}")


# ── Banner ────────────────────────────────────────────────────────────────────

def print_banner(mode: str = "system") -> None:
    """Print the startup banner and memory-file status to stdout."""
    subtitle = "Your AI coding assistant" if mode == "coding" else "Your AI system monitoring assistant"
    subtitle = subtitle[:47]
    print(f"\n{BOLD}{CYAN}┌─────────────────────────────────────────────────────┐")
    print("│               SysControl Agent                      │")
    print(f"│     {subtitle:<47} │")
    print(f"└─────────────────────────────────────────────────────┘{RESET}")
    if load_memory() is not None:
        print(f"{DIM}  Memory file found — agent can recall past sessions via read_memory.{RESET}")


# ── Error classification ───────────────────────────────────────────────────────

class _LLMError(Exception):
    """Wraps errors from the OpenAI/Ollama API call."""

class _ToolError(Exception):
    """Wraps errors from MCP tool execution."""

class _MCPError(Exception):
    """Wraps errors from the MCP subprocess itself (crash or closed pipe)."""


# ── CLI profiles / approval policies ─────────────────────────────────────────

CODING_READ_TOOLS: tuple[str, ...] = (
    "read_file",
    "read_file_lines",
    "list_directory",
    "grep_files",
    "glob_files",
    "git_status",
    "git_diff",
)

CODING_WRITE_TOOLS: tuple[str, ...] = (
    "write_file",
    "edit_file",
    "move_file",
    "copy_file",
    "delete_file",
    "create_directory",
)

CODING_EXEC_TOOLS: tuple[str, ...] = ("run_shell_command",)
CODING_TOOLS: tuple[str, ...] = CODING_READ_TOOLS + CODING_WRITE_TOOLS + CODING_EXEC_TOOLS
RISKY_CODING_TOOLS: frozenset[str] = frozenset(CODING_WRITE_TOOLS + CODING_EXEC_TOOLS)

CONFIG_FILE = USER_DATA_DIR / "config.json"

CODING_PROMPT = """
---

# CLI Coding Agent Mode

You are running as a coding agent in the user's current working directory.
Behave like a pragmatic terminal coding assistant:
- Inspect before editing. Use `grep_files`, `glob_files`, `read_file_lines`,
  `git_status`, and `git_diff` to understand the codebase and protect user work.
- Make focused changes with `edit_file` or `write_file`; avoid unrelated refactors.
- Run relevant checks with `run_shell_command` after edits when the policy allows it.
- Never discard or overwrite user changes unless the user explicitly asks.
- Explain what changed and what you verified.
- If the task is ambiguous, ask one concise follow-up; otherwise make a sensible
  assumption and move.

Approval policy for this session:
{approval_guidance}
"""

APPROVAL_GUIDANCE = {
    "plan": (
        "PLAN mode. Read/search/git-status tools are allowed. Do not edit files, "
        "create/delete/move files, or run shell commands. Produce a concrete plan "
        "and ask the user to switch to standard or nuke before implementation."
    ),
    "standard": (
        "STANDARD mode. Read/search/git-status tools are allowed automatically. "
        "File writes and shell commands require explicit CLI approval before they run."
    ),
    "nuke": (
        "NUKE mode. Read, edit, and shell tools may run without per-call approval. "
        "Still avoid destructive work unrelated to the user's task."
    ),
}


def _filter_tools(tools: list[dict], allowed_names: tuple[str, ...]) -> list[dict]:
    """Return OpenAI tool definitions whose function names are allowed."""
    allowed = set(allowed_names)
    return [t for t in tools if t.get("function", {}).get("name") in allowed]


def _coding_system_message(base_prompt: str, approval_mode: str) -> dict:
    """Build the coding-mode system message for the current approval policy."""
    guidance = APPROVAL_GUIDANCE[approval_mode]
    return {"role": "system", "content": base_prompt + CODING_PROMPT.format(
        approval_guidance=guidance,
    )}


def _load_config_file() -> dict:
    try:
        loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _save_config_file(config: dict) -> None:
    ensure_user_data_dir()
    CONFIG_FILE.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ensure_flags(flags: tuple[str, ...], auto: bool) -> None:
    """Ensure MCP permission flags needed by coding mode are enabled."""
    config = _load_config_file()
    missing = [flag for flag in flags if config.get(flag) is not True]
    if not missing:
        return

    if not auto:
        print(f"\n{YELLOW}Coding mode needs MCP permissions: {', '.join(missing)}{RESET}")
        print(f"{DIM}  These are stored in {CONFIG_FILE}. Risky tool calls still follow the CLI approval mode.{RESET}")
        print(f"{BOLD}Enable them now? [y/N]:{RESET} ", end="", flush=True)
        try:
            if input("").strip().lower() not in {"y", "yes"}:
                print(f"{DIM}Continuing without changing permissions; gated tools may return permission hints.{RESET}")
                return
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Continuing without changing permissions.{RESET}")
            return

    for flag in missing:
        config[flag] = True
    _save_config_file(config)
    print(f"{GREEN}✓ Enabled {', '.join(missing)} in {CONFIG_FILE}{RESET}")


def ensure_coding_permissions(approval_mode: str) -> None:
    """Enable or offer the MCP gates required for the selected coding policy."""
    if approval_mode == "plan":
        _ensure_flags(("allow_file_read",), auto=False)
    elif approval_mode == "standard":
        _ensure_flags(("allow_file_read", "allow_file_write", "allow_shell"), auto=False)
    elif approval_mode == "nuke":
        _ensure_flags(("allow_file_read", "allow_file_write", "allow_shell"), auto=True)


def _summarize_tool_call(name: str, args: dict) -> str:
    """Return a concise human prompt for a risky tool call."""
    if name == "run_shell_command":
        return f"run shell: {args.get('command', '')}"
    if name in {"write_file", "edit_file", "delete_file", "create_directory"}:
        return f"{name}: {args.get('path', '')}"
    if name in {"move_file", "copy_file"}:
        return f"{name}: {args.get('src', '')} → {args.get('dst', '')}"
    return name


class ApprovalController:
    """Interactive approval state for coding-mode tool calls."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self._auto_approve_rest = False
        self._spinner: _Spinner | None = None

    def bind_spinner(self, spinner: "_Spinner") -> None:
        self._spinner = spinner

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._auto_approve_rest = mode == "nuke"

    def approve(self, name: str, args: dict) -> bool:
        if name not in RISKY_CODING_TOOLS:
            return True
        if self.mode == "plan":
            print(f"\n{YELLOW}Plan mode blocked {name}.{RESET}")
            return False
        if self.mode == "nuke" or self._auto_approve_rest:
            return True

        if self._spinner is not None:
            self._spinner.stop()
        summary = _summarize_tool_call(name, args)
        print(f"\n{BOLD}{YELLOW}Approve tool call?{RESET} {summary}")
        print(f"{DIM}  y = yes, n = no, a = approve all for this session, p = switch to plan{RESET}")
        print(f"{BOLD}[y/n/a/p]:{RESET} ", end="", flush=True)
        try:
            choice = input("").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if choice in {"a", "all"}:
            self._auto_approve_rest = True
            return True
        if choice in {"p", "plan"}:
            self.set_mode("plan")
            return False
        return choice in {"y", "yes"}


# ── Spinner ────────────────────────────────────────────────────────────────────

_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class _Spinner:
    """Thread-backed terminal spinner — no-ops when stdout is not a TTY."""

    def __init__(self) -> None:
        self._message = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._is_tty: bool = sys.stdout.isatty()

    def start(self, message: str = "") -> None:
        self.stop()   # stop any currently running spinner first
        if not self._is_tty:
            return
        self._message = message
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=0.5)
        if self._is_tty:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def _run(self) -> None:
        for frame in itertools.cycle(_SPINNER_FRAMES):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r{DIM}{frame}  {self._message}{RESET}")
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


# ── Agentic Loop ──────────────────────────────────────────────────────────────

_MAX_PENDING = 8192  # flush the line buffer if no newline arrives within this many chars


def _flush_token(
    text: str,
    spinner: "_Spinner",
    first_content: list[bool],
    pending: list[str],
) -> None:
    """Write a streaming token to stdout, flushing complete lines via colorize()."""
    if first_content[0]:
        spinner.stop()
        sys.stdout.write(f"\n{BOLD}{GREEN}Assistant:{RESET} ")
        sys.stdout.flush()
        first_content[0] = False

    pending[0] += text

    while "\n" in pending[0]:
        line, pending[0] = pending[0].split("\n", 1)
        print(colorize(line), flush=True)

    # CR-6: guard against unbounded buffer (e.g. base64 blobs with no newlines).
    if len(pending[0]) > _MAX_PENDING:
        print(colorize(pending[0]), flush=True)
        pending[0] = ""


def _build_cli_callbacks(
    spinner: _Spinner,
    cancel_event: threading.Event,
    tool_results: dict[str, str] | None = None,
) -> tuple[TurnCallbacks, list[str], list[tuple[str, str]]]:
    """Build CLI-specific presentation callbacks for a single turn.

    Args:
        spinner: Terminal spinner instance managed by the caller.
        cancel_event: Signal flipped by the SIGINT handler to abort streaming.
        tool_results: Optional mutable dict the ``on_tool_finished`` callback
            populates with the latest result text per tool name.  Consumed by
            the ``/show`` slash command.

    Returns:
        A ``(callbacks, pending_buf, errors)`` triple.  *pending_buf* is a
        single-element list used as a mutable string ref so the caller
        can flush any trailing partial line after the turn completes.
        *errors* is a mutable list that the ``on_error`` callback appends
        to; the caller inspects it after the turn to raise typed exceptions.
    """
    first_content = [True]  # mutable flag — avoids nonlocal across closures
    pending = [""]          # line buffer for colorized output
    errors: list[tuple[str, str]] = []
    tool_starts: dict[str, float] = {}

    def _on_token(text: str) -> None:
        _flush_token(text, spinner, first_content, pending)

    def _on_tool_started(names: list[str]) -> None:
        if first_content[0]:
            spinner.stop()
            first_content[0] = False
        now = time.monotonic()
        for n in names:
            tool_starts[n] = now
        label = names[0] + (f" +{len(names) - 1} more" if len(names) > 1 else "")
        spinner.start(f"Running {label}…")

    def _on_tool_finished(name: str, result: str) -> None:
        spinner.stop()
        elapsed = time.monotonic() - tool_starts.pop(name, time.monotonic())
        if tool_results is not None:
            tool_results[name] = result
        _render_tool_summary(name, result, elapsed)

    def _on_error(category: str, message: str) -> None:
        spinner.stop()
        if not errors:  # keep only the first error
            errors.append((category, message))

    callbacks = TurnCallbacks(
        on_token=_on_token,
        on_tool_started=_on_tool_started,
        on_tool_finished=_on_tool_finished,
        on_error=_on_error,
        cancel_event=cancel_event,
    )

    return callbacks, pending, errors


def _render_tool_summary(name: str, result: str, elapsed: float) -> None:
    """Print a one-line themed header per finished tool call."""
    char_count = len(result or "")
    line_count = (result or "").count("\n") + (1 if result else 0)
    suffix = "no output" if not result else f"{line_count} line{'s' if line_count != 1 else ''}, {char_count} chars"
    print(f"{DIM}  → {name} · {elapsed:.1f}s · {suffix}{RESET}", flush=True)


def run_turn(
    ollama_client: OpenAI,
    pool: MCPClientPool,
    tools: list[dict],
    system_message: dict,
    messages: list[dict],
    model: str,
    approval_controller: ApprovalController | None = None,
    cancel_event: threading.Event | None = None,
    tool_results: dict[str, str] | None = None,
) -> None:
    """Execute one user turn: stream the LLM response and run tool calls.

    Args:
        ollama_client: OpenAI-compatible LLM client.
        pool: MCP client pool for parallel tool execution.
        tools: Tool definitions in OpenAI format.
        system_message: Pre-built ``{"role": "system", ...}`` dict.
        messages: Mutable conversation history — modified in-place.
        model: Model identifier string.
        cancel_event: Optional ``threading.Event`` set by the SIGINT handler to
            abort the in-flight LLM stream.
        tool_results: Optional dict the renderer populates with the most recent
            output per tool name (consumed by ``/show``).

    Raises:
        _LLMError: On API/auth/connection/timeout errors.
        _MCPError: On MCP subprocess crash.
        _ToolError: On tool execution failure.
    """
    spinner = _Spinner()
    if approval_controller is not None:
        approval_controller.bind_spinner(spinner)
    callbacks, pending, errors = _build_cli_callbacks(
        spinner,
        cancel_event if cancel_event is not None else threading.Event(),
        tool_results,
    )

    spinner.start("Thinking…")

    finish_reason, elapsed = run_streaming_turn(
        ollama_client, pool, tools, system_message, messages, model, callbacks,
    )

    # Flush any partial last line.
    if pending[0]:
        print(colorize(pending[0]), end="", flush=True)

    # If the shared loop reported an error, raise a typed exception
    # so the REPL can display appropriate user-facing recovery guidance.
    if errors:
        cat, msg = errors[0]
        if cat in ("Timeout", "Connection", "Auth", "API", "LLM", "Loop"):
            raise _LLMError(msg)
        elif cat == "MCP":
            raise _MCPError(msg)
        else:
            raise _ToolError(msg)

    # Normal stop — print elapsed time.
    if finish_reason == "cancelled":
        print(f"\n{YELLOW}  ✗ cancelled after {elapsed:.1f}s{RESET}")
    elif finish_reason in ("stop", "length", "content_filter", "unknown"):
        if finish_reason == "stop":
            print()  # final newline
            print(f"{DIM}  thought for {elapsed:.1f}s{RESET}")
        else:
            print(f"\n{DIM}[stopped: {finish_reason}] thought for {elapsed:.1f}s{RESET}")


def _pick_model(models: list[str]) -> str:
    """Present a numbered list of Ollama models and return the user's choice.

    Args:
        models: Non-empty list of model name strings.

    Returns:
        The selected model name.  Exits the process on EOF/interrupt.
    """
    assert models, "Cannot pick from an empty model list"
    print(f"\n{BOLD}Available local models:{RESET}")
    for i, name in enumerate(models, 1):
        print(f"  {CYAN}{i}{RESET}) {name}")
    print(f"{BOLD}Select model [1-{len(models)}]:{RESET} ", end="", flush=True)
    while True:
        try:
            raw = input("").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Goodbye!{RESET}")
            sys.exit(0)
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(models):
                return models[idx - 1]
        if raw in models:
            return raw
        print(f"{YELLOW}Please enter a number between 1 and {len(models)}:{RESET} ", end="", flush=True)


def _resolve_local_model() -> str:
    """Detect installed Ollama models and return the user's selection.

    - 0 models / unreachable → warns and returns LOCAL_MODEL fallback
    - 1 model               → auto-selects it silently
    - 2+ models             → shows numbered picker
    """
    models = fetch_ollama_models()
    if not models:
        print(f"{YELLOW}⚠  No local models detected (is Ollama running?). "
              f"Using default: {LOCAL_MODEL}{RESET}")
        return LOCAL_MODEL
    if len(models) == 1:
        print(f"{DIM}  Auto-selected the only installed model: {models[0]}{RESET}")
        return models[0]
    return _pick_model(models)


# ── CLI args ──────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SysControl Agent — AI-powered system monitor",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--provider", choices=["cloud", "local"],
        help="Skip the interactive provider prompt and use this provider directly.",
    )
    parser.add_argument(
        "--model",
        help="Override the default model for the chosen provider.",
    )
    parser.add_argument(
        "--api-key",
        help="Ollama API key for the cloud provider (skips the getpass prompt).",
    )
    parser.add_argument(
        "--mode",
        choices=["system", "coding"],
        default="system",
        help="Run the normal system assistant or the coding-agent CLI profile.",
    )
    parser.add_argument(
        "--coding",
        action="store_true",
        help="Shortcut for --mode coding.",
    )
    parser.add_argument(
        "--approval",
        choices=["plan", "standard", "nuke"],
        default="standard",
        help="Coding-mode approval policy: plan is read-only, standard asks before risky tools, nuke auto-accepts.",
    )
    parser.add_argument(
        "--no-save-key", action="store_true",
        help="Do not persist the Ollama Cloud API key to ~/.syscontrol/cli_credentials.json.",
    )
    parser.add_argument(
        "--continue", dest="continue_session", action="store_true",
        help="Resume the most recent CLI session.",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Pick a previous CLI session from a list to resume.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass the model-mismatch warning when resuming a session.",
    )
    parser.add_argument(
        "--update", action="store_true",
        help="Check for and install the latest SysControl release, then exit.",
    )
    parser.add_argument(
        "--version", action="store_true",
        help="Print the installed SysControl version and exit.",
    )
    return parser.parse_args()


class ProviderSelection(NamedTuple):
    """Result of provider selection — named fields prevent field-order bugs."""

    api_key: str
    base_url: str
    model: str
    label: str


def _prompt_cloud_api_key() -> str:
    """Interactively prompt for the Ollama cloud API key."""
    try:
        api_key = getpass.getpass(f"{BOLD}Ollama API key:{RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print(f"\n{DIM}Goodbye!{RESET}")
        sys.exit(0)
    if not api_key:
        print(f"{YELLOW}⚠  API key cannot be empty.{RESET}")
        sys.exit(1)
    return api_key


def _resolve_cloud_api_key(args: argparse.Namespace) -> str:
    """Pick the cloud API key from --api-key, the saved cache, or a prompt.

    The first time the user enters a key it gets persisted to
    ``~/.syscontrol/cli_credentials.json`` (0600) so subsequent launches
    don't re-prompt.  ``--no-save-key`` disables persistence; ``/logout``
    inside the REPL clears the cache.
    """
    if args.api_key:
        api_key = str(args.api_key)
        if not args.no_save_key:
            save_cloud_api_key(api_key)
        return api_key

    cached = load_cloud_api_key()
    if cached:
        print(f"{DIM}  Using saved Ollama Cloud API key ({CREDENTIALS_FILE.name}).{RESET}")
        return cached

    api_key = _prompt_cloud_api_key()
    if not args.no_save_key:
        save_cloud_api_key(api_key)
        print(f"{DIM}  Saved to {CREDENTIALS_FILE} (use /logout or --no-save-key to forget).{RESET}")
    return api_key


def _cloud_selection(args: argparse.Namespace, api_key: str) -> ProviderSelection:
    model = args.model or OLLAMA_CLOUD_MODEL
    return ProviderSelection(api_key, OLLAMA_CLOUD_BASE_URL, model, "☁  Ollama Cloud")


def _local_selection(args: argparse.Namespace) -> ProviderSelection:
    model = args.model or _resolve_local_model()
    return ProviderSelection(LOCAL_API_KEY, LOCAL_BASE_URL, model, "⚙  Local (Ollama)")


def select_provider(args: argparse.Namespace) -> ProviderSelection:
    """Resolve the LLM provider from CLI flags or interactive prompts.

    Args:
        args: Parsed CLI arguments (may contain provider, model, api_key).

    Returns:
        A ``ProviderSelection`` with api_key, base_url, model, and label.
    """
    if args.provider == "cloud":
        return _cloud_selection(args, _resolve_cloud_api_key(args))
    if args.provider == "local":
        return _local_selection(args)

    prompt = (
        f"\n{BOLD}Select AI model "
        f"(type {CYAN}cloud{RESET}{BOLD} or {CYAN}local{RESET}{BOLD}):{RESET} "
    )
    print(prompt, end="", flush=True)
    while True:
        try:
            choice = input("").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Goodbye!{RESET}")
            sys.exit(0)

        if choice == "cloud":
            return _cloud_selection(args, _resolve_cloud_api_key(args))
        if choice == "local":
            return _local_selection(args)
        print(f"{YELLOW}Please type 'cloud' or 'local':{RESET} ", end="", flush=True)


# ── Main REPL ─────────────────────────────────────────────────────────────────

def _init_mcp_and_prompt() -> tuple[MCPClient, str]:
    """Start MCP server and load system prompt in parallel.

    Returns:
        A ``(mcp_client, system_prompt)`` tuple. Exits the process on failure.
    """
    mcp_client: MCPClient | None = None
    system_prompt: str | None = None
    startup_error: Exception | None = None

    def _start_mcp() -> None:
        nonlocal mcp_client, startup_error
        try:
            mcp_client = MCPClient()
        except Exception as exc:
            startup_error = exc

    def _load_prompt() -> None:
        nonlocal system_prompt, startup_error
        try:
            system_prompt = load_system_prompt()
        except Exception as exc:
            if startup_error is None:
                startup_error = exc

    t_mcp = threading.Thread(target=_start_mcp, daemon=True)
    t_prompt = threading.Thread(target=_load_prompt, daemon=True)
    t_mcp.start()
    t_prompt.start()
    t_mcp.join()
    t_prompt.join()

    if startup_error:
        print(f"\nFailed to start MCP server: {startup_error}", file=sys.stderr)
        sys.exit(1)

    assert mcp_client is not None, (
        "_init_mcp_and_prompt: MCPClient not set — startup thread failed"
    )
    assert system_prompt is not None, (
        "_init_mcp_and_prompt: system_prompt not set — prompt thread failed"
    )
    return mcp_client, system_prompt


@dataclass
class ReplContext:
    """Mutable session state shared between the REPL loop and slash handlers."""

    ollama_client: OpenAI
    pool: MCPClientPool
    tools: list[dict]
    system_message: dict
    model: str
    provider_label: str
    cli_mode: str = "system"
    approval_controller: ApprovalController | None = None
    base_system_prompt: str | None = None
    messages: list[dict] = field(default_factory=list)
    registry: SlashRegistry = field(default_factory=SlashRegistry)
    last_tool_results: dict[str, str] = field(default_factory=dict)
    compact_undo: list[dict] | None = None
    session_path: Path | None = None
    session_started_at: str | None = None


# ── Slash commands ───────────────────────────────────────────────────────────

def _cmd_help(ctx: ReplContext, _args: str) -> SlashResult:
    width = max(len(c.usage or f"/{c.name}") for c in ctx.registry.visible(ctx))
    print(f"\n{BOLD}Commands{RESET}")
    for cmd in ctx.registry.visible(ctx):
        usage = cmd.usage or f"/{cmd.name}"
        print(f"  {CYAN}{usage:<{width}}{RESET}   {cmd.description}")
    print(f"\n{BOLD}Keyboard{RESET}")
    print(f"  {CYAN}↑/↓{RESET}            History     {CYAN}Ctrl+R{RESET}     Reverse-search")
    print(f"  {CYAN}Tab{RESET}            Complete    {CYAN}Ctrl+L{RESET}     Clear screen")
    print(f"  {CYAN}Esc, Enter{RESET}     Newline     {CYAN}Ctrl+D{RESET}     Exit\n")
    return CONTINUE


def _cmd_clear(_ctx: ReplContext, _args: str) -> SlashResult:
    print("\033[2J\033[H", end="")
    return CONTINUE


def _cmd_reset(ctx: ReplContext, _args: str) -> SlashResult:
    ctx.messages.clear()
    print(f"{GREEN}✓ Conversation history cleared.{RESET}\n")
    return CONTINUE


def _cmd_tools(ctx: ReplContext, args: str) -> SlashResult:
    needle = args.strip().lower()
    names = sorted(t["function"]["name"] for t in ctx.tools)
    if needle:
        names = [n for n in names if needle in n.lower()]
    if not names:
        print(f"{DIM}No tools matched '{needle}'.{RESET}\n")
        return CONTINUE
    print(f"{BOLD}{len(names)} tool(s){RESET}")
    for n in names:
        print(f"  {n}")
    print()
    return CONTINUE


def _cmd_model(ctx: ReplContext, _args: str) -> SlashResult:
    print(f"{DIM}model: {ctx.model}  ·  {ctx.provider_label}{RESET}\n")
    return CONTINUE


def _cmd_memory(_ctx: ReplContext, args: str) -> SlashResult:
    note = args.strip()
    if not note:
        print(f"{YELLOW}Usage: /memory <note text>{RESET}\n")
        return CONTINUE
    _append_memory_note(note)
    print()
    return CONTINUE


def _cmd_exit(_ctx: ReplContext, _args: str) -> SlashResult:
    return EXIT


def _cmd_sessions(_ctx: ReplContext, _args: str) -> SlashResult:
    """List recently saved CLI sessions."""
    summaries = cli_session.list_sessions()
    if not summaries:
        print(f"{DIM}No saved sessions yet.{RESET}\n")
        return CONTINUE
    print(f"\n{BOLD}Recent sessions{RESET} {DIM}({cli_session.SESSIONS_DIR}){RESET}")
    for s in summaries:
        print(
            f"  {DIM}{s.last_active}{RESET}  {s.model:<14} "
            f"{s.message_count:>3} msgs  {s.first_user_text or DIM + '(no user msg)' + RESET}"
        )
    print(f"\n{DIM}Resume the latest with `syscontrol --continue` or pick one with `syscontrol --resume`.{RESET}\n")
    return CONTINUE


_INIT_PROMPT = (
    "I want you to initialize a CLAUDE.md file in the current working directory "
    "to act as the project's onboarding guide for future LLM agents.\n\n"
    "Steps:\n"
    "1. Use list_directory to see the top-level layout, then read the README, "
    "pyproject.toml/package.json/Cargo.toml/go.mod (whichever exist), and any "
    "`.github/workflows/*.yml`. Use grep_files for hints (build commands, test "
    "commands, lint config) when helpful.\n"
    "2. Produce a CLAUDE.md with these sections, in order: \"What is this project?\", "
    "\"Architecture\", \"Build & Test\", \"Coding Standards\", \"Common Tasks\", "
    "and \"File Size Reference\" listing the largest files with line counts.\n"
    "3. Save it via write_file to ./CLAUDE.md.\n"
    "4. After writing, summarize what you put in it in three bullets.\n"
)


def _cmd_init(_ctx: ReplContext, _args: str) -> SlashResult:
    """Inject a templated user message that asks the LLM to write CLAUDE.md."""
    return SlashResult(message=_INIT_PROMPT)


def _cmd_compact(ctx: ReplContext, args: str) -> SlashResult:
    """Summarize the conversation; `undo` restores the prior history."""
    if args.strip().lower() == "undo":
        if cli_compact.undo(ctx):
            print(f"{GREEN}✓ Restored pre-compact history "
                  f"({len(ctx.messages)} messages).{RESET}\n")
        else:
            print(f"{DIM}Nothing to undo.{RESET}\n")
        return CONTINUE

    spinner = _Spinner()
    spinner.start("Summarizing conversation…")
    try:
        ok, info = cli_compact.compact(ctx)
    finally:
        spinner.stop()
    if not ok:
        print(f"{YELLOW}Compact failed:{RESET} {info}\n")
        return CONTINUE
    print(f"{GREEN}✓ Compacted{RESET} {DIM}(now {len(ctx.messages)} messages — "
          f"`/compact undo` restores).{RESET}\n")
    return CONTINUE


def _cmd_show(ctx: ReplContext, args: str) -> SlashResult:
    """Dump the full output of the most recent tool call (or a named one)."""
    if not ctx.last_tool_results:
        print(f"{DIM}No tool output captured yet.{RESET}\n")
        return CONTINUE
    name = args.strip()
    if not name:
        name = next(reversed(ctx.last_tool_results))
    result = ctx.last_tool_results.get(name)
    if result is None:
        available = ", ".join(ctx.last_tool_results.keys())
        print(f"{YELLOW}No output captured for '{name}'.{RESET} {DIM}Available: {available}{RESET}\n")
        return CONTINUE
    print(f"\n{BOLD}── {name} ──{RESET}")
    print(result if result else f"{DIM}(empty){RESET}")
    print()
    return CONTINUE


def _cmd_logout(_ctx: ReplContext, _args: str) -> SlashResult:
    if clear_cloud_api_key():
        print(f"{GREEN}✓ Cleared saved Ollama Cloud API key.{RESET}\n")
    else:
        print(f"{DIM}No saved API key to clear.{RESET}\n")
    return CONTINUE


def _cmd_update(_ctx: ReplContext, args: str) -> SlashResult:
    force = args.strip().lower() in {"force", "-f", "--force"}
    info = check_for_update()
    print(f"\n{BOLD}SysControl{RESET} {DIM}v{info.current}{RESET}")
    if info.error:
        print(f"{YELLOW}Could not reach GitHub: {info.error}{RESET}\n")
        return CONTINUE
    if info.latest:
        print(f"{DIM}  Latest release: v{info.latest}{RESET}")
    if not info.is_newer and not force:
        print(f"{GREEN}✓ Already on the latest release.{RESET} "
              f"{DIM}(use '/update force' to reinstall){RESET}\n")
        return CONTINUE

    print(f"{DIM}  Running: uv tool install --force git+{REPO_URL_DISPLAY}{RESET}")
    ok, msg = update_via_uv()
    print()
    if ok:
        print(f"{GREEN}✓ Updated.{RESET} {DIM}Restart the CLI to load the new version.{RESET}\n")
    else:
        print(f"{YELLOW}Update failed:{RESET} {msg}\n")
    return CONTINUE


REPO_URL_DISPLAY = "https://github.com/ks6573/SysControl.git"


def _run_update_flow() -> int:
    """Shell-mode entry for `syscontrol --update`. Returns a process exit code."""
    info = check_for_update()
    print(f"{BOLD}SysControl{RESET} {DIM}v{info.current}{RESET}")
    if info.error:
        print(f"{YELLOW}Could not reach GitHub: {info.error}{RESET}")
        return 1
    if info.latest:
        print(f"{DIM}  Latest release: v{info.latest}{RESET}")
    if not info.is_newer:
        print(f"{GREEN}✓ Already on the latest release.{RESET}")
        return 0
    print(f"{DIM}  Running: uv tool install --force git+{REPO_URL_DISPLAY}{RESET}")
    ok, msg = update_via_uv()
    if ok:
        print(f"{GREEN}✓ Updated.{RESET} {DIM}Restart the CLI to load the new version.{RESET}")
        return 0
    print(f"{YELLOW}Update failed:{RESET} {msg}")
    return 1


def _cmd_approval(ctx: ReplContext, args: str) -> SlashResult:
    mode = args.strip().lower()
    if mode not in APPROVAL_GUIDANCE:
        print(f"{YELLOW}Usage: /approval plan|standard|nuke{RESET}\n")
        return CONTINUE
    assert ctx.approval_controller is not None
    ctx.approval_controller.set_mode(mode)
    ctx.pool.set_tool_approver(ctx.approval_controller.approve)
    ensure_coding_permissions(mode)
    if ctx.base_system_prompt is not None:
        ctx.system_message = _coding_system_message(ctx.base_system_prompt, mode)
    print(f"{GREEN}✓ Coding approval mode is now {mode}.{RESET}\n")
    return CONTINUE


def _build_registry(coding: bool) -> SlashRegistry:
    """Build the slash-command registry for the current CLI profile."""
    reg = SlashRegistry()
    reg.register(SlashCommand("help", "Show available commands and shortcuts",
                              _cmd_help, usage="/help", aliases=("?",)))
    reg.register(SlashCommand("clear", "Clear the screen", _cmd_clear, usage="/clear"))
    reg.register(SlashCommand("reset", "Clear conversation history (keeps system prompt)",
                              _cmd_reset, usage="/reset"))
    reg.register(SlashCommand("tools", "List available tools (optional substring filter)",
                              _cmd_tools, usage="/tools [filter]"))
    reg.register(SlashCommand("model", "Show the active model and provider",
                              _cmd_model, usage="/model"))
    reg.register(SlashCommand("memory", "Append a note to SysControl_Memory.md",
                              _cmd_memory, usage="/memory <note>"))
    reg.register(SlashCommand("update", "Check for and install the latest SysControl release",
                              _cmd_update, usage="/update [force]",
                              arg_choices=("force",)))
    reg.register(SlashCommand("logout", "Forget the saved Ollama Cloud API key",
                              _cmd_logout, usage="/logout"))
    reg.register(SlashCommand("show", "Dump the full output of the most recent tool call",
                              _cmd_show, usage="/show [tool_name]"))
    reg.register(SlashCommand("sessions", "List recently saved CLI sessions",
                              _cmd_sessions, usage="/sessions"))
    reg.register(SlashCommand("init", "Generate a CLAUDE.md for the current project",
                              _cmd_init, usage="/init"))
    reg.register(SlashCommand("compact", "Summarize the conversation (use 'undo' to restore)",
                              _cmd_compact, usage="/compact [undo]",
                              arg_choices=("undo",)))
    reg.register(SlashCommand("exit", "Quit the session", _cmd_exit,
                              usage="/exit", aliases=("quit", "bye")))
    if coding:
        reg.register(SlashCommand(
            "approval", "Switch coding-mode approval policy",
            _cmd_approval, usage="/approval plan|standard|nuke",
            aliases=("mode",), arg_choices=tuple(APPROVAL_GUIDANCE.keys()),
        ))
    return reg


# ── prompt_toolkit integration ───────────────────────────────────────────────

class _SlashCompleter(Completer):
    """Pop a completion menu when the user types `/<name>` or `/<name> <arg>`."""

    def __init__(self, ctx: ReplContext) -> None:
        self._ctx = ctx

    def get_completions(
        self, document: Document, _complete_event: CompleteEvent,
    ) -> Iterable[Completion]:
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        head, sep, tail = text[1:].partition(" ")
        if not sep:
            partial = head.lower()
            for cmd in self._ctx.registry.visible(self._ctx):
                for key in (cmd.name, *cmd.aliases):
                    if key.startswith(partial):
                        yield Completion(
                            f"/{key}",
                            start_position=-len(text),
                            display_meta=cmd.description,
                        )
                        break
            return
        match = self._ctx.registry.get(head.lower())
        if match is None:
            return
        partial = tail.lower()
        choices: tuple[str, ...] = match.arg_choices
        if match.name == "show":
            choices = tuple(self._ctx.last_tool_results.keys())
        for choice in choices:
            if choice.startswith(partial):
                yield Completion(choice, start_position=-len(tail))


def _bottom_toolbar(ctx: ReplContext) -> Callable[[], FormattedText]:
    """Return a closure that renders the live status strip beneath the prompt."""
    def _render() -> FormattedText:
        cwd = os.path.basename(os.getcwd()) or "/"
        approval = (
            f" · {ctx.approval_controller.mode}"
            if ctx.cli_mode == "coding" and ctx.approval_controller is not None
            else ""
        )
        msg_count = sum(1 for m in ctx.messages if m.get("role") in ("user", "assistant"))
        return FormattedText([
            ("class:tb", f" {ctx.model} · {ctx.provider_label} · {ctx.cli_mode}{approval} "),
            ("class:tb.sep", "│ "),
            ("class:tb", f"{cwd} · {msg_count} msgs "),
            ("class:tb.sep", "│ "),
            ("class:tb.hint", "/help · Enter submits · Ctrl-D submits multiline · Ctrl-C cancels"),
        ])
    return _render


def _build_prompt_session(ctx: ReplContext) -> PromptSession:
    """Configure prompt_toolkit with history, key bindings, and slash completion."""
    ensure_user_data_dir()
    history = FileHistory(str(USER_DATA_DIR / "cli_history"))

    style = Style.from_dict({
        "completion-menu.completion": "bg:#222222 #cccccc",
        "completion-menu.completion.current": "bg:#0066cc #ffffff",
        "completion-menu.meta.completion": "bg:#222222 #888888",
        "completion-menu.meta.completion.current": "bg:#0066cc #cccccc",
        "tb": "bg:#1c1c1c #cccccc",
        "tb.sep": "bg:#1c1c1c #555555",
        "tb.hint": "bg:#1c1c1c #888888",
        "bottom-toolbar": "bg:#1c1c1c",
    })

    return PromptSession(
        history=history,
        completer=build_completer(_SlashCompleter(ctx)),
        complete_while_typing=True,
        auto_suggest=AutoSuggestFromHistory(),
        key_bindings=build_key_bindings(),
        style=style,
        enable_history_search=True,
        multiline=True,
        bottom_toolbar=_bottom_toolbar(ctx),
    )


def _read_input(session: PromptSession) -> str | None:
    """Return the next user input, or None on EOF/Ctrl+D."""
    try:
        text: str = session.prompt(ANSI(f"{BOLD}{BLUE}You:{RESET} "))
    except EOFError:
        return None
    except KeyboardInterrupt:
        return ""  # Ctrl+C at the prompt clears it; keep looping
    return text.strip()


def _dispatch_slash(ctx: ReplContext, raw: str) -> SlashResult:
    name, args = parse(raw)
    cmd = ctx.registry.get(name)
    if cmd is None:
        print(f"{YELLOW}Unknown command '/{name}'. Type /help for options.{RESET}\n")
        return CONTINUE
    return cmd.handler(ctx, args)


def _hydrate_session(ctx: ReplContext, args: argparse.Namespace) -> None:
    """If --continue / --resume was passed, load the chosen session into ctx."""
    if not (args.continue_session or args.resume):
        return
    try:
        payload = (
            cli_session.load_latest()
            if args.continue_session
            else cli_session.pick_interactive()
        )
    except (OSError, ValueError) as exc:
        print(f"{YELLOW}Could not load session: {exc}{RESET}")
        return
    if payload is None:
        if args.continue_session:
            print(f"{DIM}No saved sessions to continue.{RESET}")
        return

    saved_model = payload.get("model", "")
    if saved_model and saved_model != ctx.model and not args.force:
        print(
            f"{YELLOW}Session was saved on '{saved_model}', current model is '{ctx.model}'.{RESET}"
        )
        print(f"{DIM}  Re-run with --force to load anyway, or pass --model {saved_model}.{RESET}")
        return

    ctx.messages = list(payload.get("messages", []))
    ctx.session_path = Path(cli_session.SESSIONS_DIR / Path(payload.get("path", "")).name) if payload.get("path") else None
    ctx.session_started_at = payload.get("started_at")
    msg_count = sum(1 for m in ctx.messages if m.get("role") in ("user", "assistant"))
    print(f"{GREEN}✓ Resumed session{RESET} {DIM}({msg_count} prior messages, model {saved_model or 'unknown'}){RESET}")


def _save_session_safely(ctx: ReplContext) -> None:
    """Persist the active session JSON; never raise into the REPL on failure."""
    try:
        ctx.session_path = cli_session.save(
            messages=ctx.messages,
            model=ctx.model,
            provider_label=ctx.provider_label,
            cli_mode=ctx.cli_mode,
            approval_mode=ctx.approval_controller.mode if ctx.approval_controller else None,
            session_path=ctx.session_path,
            started_at=ctx.session_started_at,
        )
    except OSError as exc:
        print(f"{DIM}  (session not saved: {exc}){RESET}")


def _run_shell_escape(ctx: ReplContext, command: str) -> None:
    """Run a `!shell` command directly via the MCP server, bypass the LLM."""
    if not command:
        print(f"{YELLOW}Usage: !<shell command>{RESET}\n")
        return
    print(f"{DIM}  $ {command}{RESET}")
    result = ctx.pool.call_one("run_shell_command", {"command": command})
    if result.startswith("[tool error"):
        print(f"{YELLOW}{result}{RESET}")
        if "permission" in result.lower() or "allow_shell" in result.lower():
            print(f"{DIM}  Enable allow_shell in ~/.syscontrol/config.json to run shell commands.{RESET}")
    else:
        print(result)
    print()


def _print_status_line(ctx: ReplContext) -> None:
    mode_label = ""
    if ctx.cli_mode == "coding" and ctx.approval_controller is not None:
        mode_label = f"  ·  coding:{ctx.approval_controller.mode}"
    print(
        f"\r{GREEN}✓{RESET} Connected — {len(ctx.tools)} tools available. "
        f"{DIM}[{ctx.provider_label}  ·  {ctx.model}{mode_label}]{RESET}"
    )
    print(f"{DIM}  Type your request, '/' for commands, Ctrl+D to exit.{RESET}\n")


def _repl_loop(ctx: ReplContext) -> None:
    """Interactive read-eval-print loop for the CLI agent."""
    _print_status_line(ctx)
    session = _build_prompt_session(ctx)
    cancel_event = threading.Event()

    def _on_double_ctrl_c() -> None:
        with contextlib.suppress(Exception):
            ctx.pool.close_all()
        with contextlib.suppress(Exception):
            close_subagent_pool()

    with install_sigint_handler(cancel_event, on_exit=_on_double_ctrl_c):
        while True:
            cancel_event.clear()
            user_input = _read_input(session)
            if user_input is None:
                print(f"{DIM}Goodbye!{RESET}")
                offer_memory_save(ctx.messages)
                break
            if not user_input:
                continue

            if user_input.startswith("!"):
                _run_shell_escape(ctx, user_input[1:].strip())
                continue

            if user_input.startswith("/"):
                result = _dispatch_slash(ctx, user_input)
                if result.exit:
                    print(f"{DIM}Goodbye!{RESET}")
                    offer_memory_save(ctx.messages)
                    break
                if result.message is None:
                    continue
                user_input = result.message

            if user_input.lower() in EXIT_PHRASES:
                print(f"{DIM}Goodbye!{RESET}")
                offer_memory_save(ctx.messages)
                break

            expanded, warnings = expand_at_mentions(user_input)
            for warn in warnings:
                print(f"{YELLOW}  {warn}{RESET}")
            ctx.messages.append({"role": "user", "content": expanded})

            try:
                run_turn(
                    ctx.ollama_client, ctx.pool, ctx.tools, ctx.system_message,
                    ctx.messages, ctx.model, ctx.approval_controller,
                    cancel_event=cancel_event,
                    tool_results=ctx.last_tool_results,
                )
                _save_session_safely(ctx)
            except _LLMError as e:
                print(f"\n{YELLOW}LLM error: {e}{RESET}")
                print(f"{DIM}  Check your API key or network connection, then try again.{RESET}")
            except _MCPError as e:
                print(f"\n{YELLOW}MCP server error: {e}{RESET}")
                print(f"{DIM}  The system monitor backend crashed — restarting is recommended.{RESET}")
                break
            except _ToolError as e:
                print(f"\n{YELLOW}Tool error: {e}{RESET}")
                print(f"{DIM}  The tool failed but the session is intact — try again.{RESET}")
            except Exception as e:
                print(f"\n{YELLOW}Unexpected error: {e}{RESET}")

            print()   # blank line between turns


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    if args.version:
        print(f"syscontrol {current_version()}")
        return
    if args.update:
        sys.exit(_run_update_flow())
    if args.coding:
        args.mode = "coding"
    print_banner(args.mode)

    if not SERVER_PATH.exists():
        print(f"mcp/server.py not found at {SERVER_PATH}", file=sys.stderr)
        sys.exit(1)

    api_key, base_url, model, provider_label = select_provider(args)

    print(f"\n{DIM}Connecting to system monitor backend…{RESET}", end="", flush=True)

    mcp_client, system_prompt = _init_mcp_and_prompt()
    approval_controller: ApprovalController | None = None
    if args.mode == "coding":
        ensure_coding_permissions(args.approval)
        approval_controller = ApprovalController(args.approval)
    pool = MCPClientPool(
        mcp_client,
        provider_api_key=api_key,
        provider_base_url=base_url,
        tool_approver=approval_controller.approve if approval_controller else None,
    )

    try:
        mcp_tools = mcp_client.list_tools()
        all_tools = mcp_to_openai_tools(mcp_tools)
        tools = _filter_tools(all_tools, CODING_TOOLS) if args.mode == "coding" else all_tools

        tool_names = [t["function"]["name"] for t in tools]
        full_system = build_full_system_prompt(system_prompt, tool_names)
        system_message = (
            _coding_system_message(full_system, args.approval)
            if args.mode == "coding"
            else {"role": "system", "content": full_system}
        )
        ollama_client = OpenAI(
            api_key=api_key, base_url=base_url,
            timeout=llm_client_timeout(),
            max_retries=llm_client_max_retries(),
        )

        ctx = ReplContext(
            ollama_client=ollama_client,
            pool=pool,
            tools=tools,
            system_message=system_message,
            model=model,
            provider_label=provider_label,
            cli_mode=args.mode,
            approval_controller=approval_controller,
            base_system_prompt=full_system,
            registry=_build_registry(coding=args.mode == "coding"),
        )
        _hydrate_session(ctx, args)
        _repl_loop(ctx)

    finally:
        close_subagent_pool()
        pool.close_all()


if __name__ == "__main__":
    main()
