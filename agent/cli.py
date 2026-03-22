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
import datetime
import getpass
import itertools
import sys
import threading
import time
from openai import OpenAI

from agent.core import (
    BLUE, BOLD, CLOUD_BASE_URL, CLOUD_MODEL, CYAN, DIM, EXIT_PHRASES, GREEN,
    HAS_FCNTL, LOCAL_API_KEY, LOCAL_BASE_URL, LOCAL_MODEL, MAX_TOKENS,
    RESET, SERVER_PATH, YELLOW,
    MCPClient, MCPClientPool, TurnCallbacks,
    _colorize, fcntl_mod, fetch_ollama_models, load_memory, load_system_prompt,
    mcp_to_openai_tools, prune_history, run_streaming_turn,
)
from agent.paths import MEMORY_FILE

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

def print_banner() -> None:
    print(f"\n{BOLD}{CYAN}┌─────────────────────────────────────────────────────┐")
    print(f"│               SysControl Agent                      │")
    print(f"│     Your AI system monitoring assistant             │")
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

def run_turn(
    ollama_client:  OpenAI,
    pool:           MCPClientPool,
    tools:          list[dict],
    system_message: dict,          # pre-built {"role": "system", "content": ...}
    messages:       list[dict],
    model:          str,
) -> None:
    """Run one user-turn: stream response, execute any tool calls, repeat."""
    spinner = _Spinner()
    _first_content = True       # tracks whether "Assistant:" header has been printed
    _pending = ""               # line buffer for colorized output
    _error_info: list[tuple[str, str]] = []  # captures (category, message) from callback

    # ── Callbacks ──────────────────────────────────────────────────────────

    def _on_token(text: str) -> None:
        nonlocal _first_content, _pending
        if _first_content:
            spinner.stop()
            sys.stdout.write(f"\n{BOLD}{GREEN}Assistant:{RESET} ")
            sys.stdout.flush()
            _first_content = False
        _pending += text
        while "\n" in _pending:
            line, _pending = _pending.split("\n", 1)
            print(_colorize(line), flush=True)

    def _on_tool_started(names: list[str]) -> None:
        nonlocal _first_content
        # Stop spinner if it's still running from the thinking phase
        if _first_content:
            spinner.stop()
            _first_content = False
        n = len(names)
        label = names[0] + (f" +{n - 1} more" if n > 1 else "")
        spinner.start(f"Running {label}…")

    def _on_tool_finished(_name: str, _result: str) -> None:
        spinner.stop()

    def _on_error(category: str, message: str) -> None:
        spinner.stop()
        _error_info.append((category, message))

    callbacks = TurnCallbacks(
        on_token=_on_token,
        on_tool_started=_on_tool_started,
        on_tool_finished=_on_tool_finished,
        on_error=_on_error,
    )

    # ── Start spinner and delegate to the shared loop ──────────────────────
    spinner.start("Thinking…")

    finish_reason, elapsed = run_streaming_turn(
        ollama_client, pool, tools, system_message, messages, model, callbacks,
    )

    # Flush any partial last line.
    if _pending:
        print(_colorize(_pending), end="", flush=True)

    # If the shared loop reported an error via callback, raise typed exceptions
    # so the REPL can display appropriate user-facing messages.
    if _error_info:
        cat, msg = _error_info[0]
        if cat in ("Timeout", "Connection", "Auth", "API", "LLM"):
            raise _LLMError(msg)
        elif cat == "MCP":
            raise _MCPError(msg)
        else:
            raise _ToolError(msg)

    # Normal stop — print elapsed time.
    if finish_reason in ("stop", "length", "content_filter", "unknown"):
        if finish_reason == "stop":
            print()  # final newline
            print(f"{DIM}  thought for {elapsed:.1f}s{RESET}")
        else:
            print(f"\n{DIM}[stopped: {finish_reason}] thought for {elapsed:.1f}s{RESET}")


def _pick_model(models: list[str]) -> str:
    """Present a numbered list of models and return the user's choice."""
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
        if raw.isdigit() and 1 <= int(raw) <= len(models):
            return models[int(raw) - 1]
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
    return parser.parse_args()


def select_provider(args: argparse.Namespace) -> tuple[str, str, str, str]:
    """
    Return (api_key, base_url, model, label).
    Prefers CLI flags; falls back to interactive prompts.
    """
    # ── Cloud ──────────────────────────────────────────────────────────────
    if args.provider == "cloud":
        api_key = args.api_key or ""
        if not api_key:
            try:
                api_key = getpass.getpass(f"{BOLD}Ollama API key:{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{DIM}Goodbye!{RESET}")
                sys.exit(0)
        if not api_key:
            print(f"{YELLOW}⚠  API key cannot be empty.{RESET}")
            sys.exit(1)
        model = args.model or CLOUD_MODEL
        return api_key, CLOUD_BASE_URL, model, "☁  Cloud"

    # ── Local ──────────────────────────────────────────────────────────────
    if args.provider == "local":
        model = args.model or _resolve_local_model()
        return LOCAL_API_KEY, LOCAL_BASE_URL, model, "⚙  Local (Ollama)"

    # ── Interactive fallback ───────────────────────────────────────────────
    print(f"\n{BOLD}Select AI model (type {CYAN}cloud{RESET}{BOLD} or {CYAN}local{RESET}{BOLD}):{RESET} ", end="", flush=True)
    while True:
        try:
            choice = input("").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Goodbye!{RESET}")
            sys.exit(0)

        if choice == "cloud":
            try:
                api_key = getpass.getpass(f"{BOLD}Ollama API key:{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{DIM}Goodbye!{RESET}")
                sys.exit(0)
            if not api_key:
                print(f"{YELLOW}⚠  API key cannot be empty. Please try again.{RESET}")
                print(f"{BOLD}Select AI model (type {CYAN}cloud{RESET}{BOLD} or {CYAN}local{RESET}{BOLD}):{RESET} ", end="", flush=True)
                continue
            model = args.model or CLOUD_MODEL
            return api_key, CLOUD_BASE_URL, model, "☁  Cloud"

        elif choice == "local":
            model = args.model or _resolve_local_model()
            return LOCAL_API_KEY, LOCAL_BASE_URL, model, "⚙  Local (Ollama)"

        else:
            print(f"{YELLOW}Please type 'cloud' or 'local':{RESET} ", end="", flush=True)


# ── Main REPL ─────────────────────────────────────────────────────────────────

def _init_mcp_and_prompt() -> tuple[MCPClient, str]:
    """Start MCP server and load system prompt in parallel.

    Returns:
        A ``(mcp_client, system_prompt)`` tuple. Exits the process on failure.
    """
    mcp_client:    MCPClient | None = None
    system_prompt: str | None       = None
    startup_error: Exception | None = None

    def _start_mcp() -> None:
        nonlocal mcp_client, startup_error
        try:
            mcp_client = MCPClient()
        except Exception as exc:
            startup_error = exc

    def _load_prompt() -> None:
        nonlocal system_prompt
        system_prompt = load_system_prompt()

    t_mcp    = threading.Thread(target=_start_mcp,    daemon=True)
    t_prompt = threading.Thread(target=_load_prompt,  daemon=True)
    t_mcp.start()
    t_prompt.start()
    t_mcp.join()
    t_prompt.join()

    if startup_error:
        print(f"\nFailed to start MCP server: {startup_error}", file=sys.stderr)
        sys.exit(1)

    assert mcp_client is not None
    assert system_prompt is not None
    return mcp_client, system_prompt


def _repl_loop(
    ollama_client: OpenAI,
    pool: MCPClientPool,
    tools: list[dict],
    system_message: dict,
    model: str,
    provider_label: str,
) -> None:
    """Interactive read-eval-print loop for the CLI agent."""
    print(f"\r{GREEN}✓{RESET} Connected — {len(tools)} tools available. {DIM}[{provider_label}  ·  {model}]{RESET}")
    print(f"{DIM}  Type your question, or 'exit' / 'bye' / 'goodbye' to quit.{RESET}\n")

    messages: list[dict] = []

    while True:
        try:
            user_input = input(f"{BOLD}{BLUE}You:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Goodbye!{RESET}")
            offer_memory_save(messages)
            break

        if not user_input:
            continue

        if user_input.lower() in EXIT_PHRASES:
            print(f"{DIM}Goodbye!{RESET}")
            offer_memory_save(messages)
            break

        messages.append({"role": "user", "content": user_input})

        try:
            run_turn(ollama_client, pool, tools, system_message, messages, model)
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
    print_banner()

    if not SERVER_PATH.exists():
        print(f"mcp/server.py not found at {SERVER_PATH}", file=sys.stderr)
        sys.exit(1)

    api_key, base_url, model, provider_label = select_provider(args)

    print(f"\n{DIM}Connecting to system monitor backend…{RESET}", end="", flush=True)

    mcp_client, system_prompt = _init_mcp_and_prompt()
    pool = MCPClientPool(mcp_client)

    try:
        mcp_tools = mcp_client.list_tools()
        tools     = mcp_to_openai_tools(mcp_tools)

        # Inject available tool names so the model can answer introspection questions
        tool_names = [t["function"]["name"] for t in tools]
        tool_list_block = (
            "\n\n---\n\n# Available Tools\n\n"
            "You have access to the following tools (call them by name):\n"
            + "\n".join(f"- {n}" for n in tool_names)
        )

        full_system = system_prompt + tool_list_block
        if load_memory() is not None:
            full_system += (
                "\n\n---\n\n# Memory\n\n"
                "A persistent memory file exists with notes from past sessions. "
                "Call `read_memory` when the user references something from a previous session, "
                "asks what you remember, or when prior context seems relevant. "
                "Call `append_memory_note` to save a key fact mid-session without waiting for exit."
            )

        system_message = {"role": "system", "content": full_system}
        ollama_client  = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)

        _repl_loop(ollama_client, pool, tools, system_message, model, provider_label)

    finally:
        pool.close_all()


if __name__ == "__main__":
    main()

