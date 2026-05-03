#!/usr/bin/env python3
"""
SysControl Bridge — JSON-over-stdio bridge for the Swift frontend.

Reads newline-delimited JSON commands from stdin and writes JSON events
to stdout.  Reuses the full agent/core.py infrastructure (MCPClient,
MCPClientPool, run_streaming_turn) so every existing tool and the
streaming agentic loop work out of the box.

Protocol (stdin → bridge):
    {"type":"user_message","text":"...","session_id":"...","history":[{"role":"user","content":"..."}]}
    {"type":"clear_session","session_id":"..."}  # omit session_id to clear all
    {"type":"shutdown"}

Protocol (bridge → stdout):
    {"type":"ready","tool_count":92,"model":"..."}
    {"type":"token","text":"Hello"}
    {"type":"tool_started","names":["get_cpu_usage"]}
    {"type":"tool_finished","name":"get_cpu_usage","result":"..."}
    {"type":"turn_done","finish_reason":"stop","elapsed":1.23}
    {"type":"error","category":"LLM","message":"..."}
"""

from __future__ import annotations

import json
import os
import re
import select
import sys
import tempfile
import threading
from typing import IO

from openai import OpenAI

from agent.core import (
    LOCAL_BASE_URL,
    MCPClient,
    MCPClientPool,
    TurnCallbacks,
    build_full_system_prompt,
    llm_client_max_retries,
    llm_client_timeout,
    load_system_prompt,
    mcp_to_openai_tools,
    run_streaming_turn,
)
from agent.runner import close_subagent_pool

# ── Helpers ───────────────────────────────────────────────────────────────────

_write_lock = threading.Lock()


def _emit(event: dict) -> None:
    """Write a single JSON event to stdout (thread-safe)."""
    with _write_lock:
        sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
        sys.stdout.flush()


_PARENT_PID = os.getppid()  # captured once at startup as baseline for orphan detection
_STDIN_TIMEOUT = 30.0       # seconds between orphan checks when stdin is idle


def _parent_alive() -> bool:
    """Check if the original parent process is still alive.

    Compares the current parent PID against the one captured at startup.
    When the parent dies, the OS re-parents this process to ``launchd``
    (PID 1 on macOS) or ``init``, causing ``getppid()`` to change.  This
    is more reliable than ``os.kill(pid, 0)`` which can false-positive on
    PID reuse after long uptimes.

    Returns:
        ``True`` if our parent PID has not changed since startup.
    """
    return os.getppid() == _PARENT_PID


def _read_command() -> dict | None:
    """Read one JSON command from stdin, with orphan detection.

    Returns:
        Parsed command dict on success, empty ``{}`` on idle timeout with a
        live parent (signals the event loop to continue without dispatching),
        or ``None`` on EOF / orphan detection (signals clean shutdown).
    """
    try:
        ready, _, _ = select.select([sys.stdin], [], [], _STDIN_TIMEOUT)
    except (ValueError, OSError):
        return None
    if not ready:
        # Timed out — check if parent is still alive.
        if not _parent_alive():
            return None  # orphaned — trigger clean shutdown
        return {}  # no command yet; keep looping (intentional no-op in _event_loop)
    line = sys.stdin.readline()
    if not line:
        return None
    # Hard cap on line size — guards against runaway producers that never
    # newline-terminate.  1 MB is far above any expected command (largest
    # legitimate payload is a history list, typically a few KB).
    if len(line) > 1_048_576:
        _emit({
            "type": "error", "category": "Protocol",
            "message": "Command exceeds 1 MB line size limit",
        })
        return {}
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        _emit({
            "type": "error", "category": "Protocol",
            "message": f"Invalid JSON: {line.strip()[:200]}",
        })
        return {}
    if not isinstance(parsed, dict):
        _emit({
            "type": "error", "category": "Protocol",
            "message": f"Command must be a JSON object, got {type(parsed).__name__}",
        })
        return {}
    return parsed


_CHART_IMAGE_RE = re.compile(r"\[chart_image:(.+?)\]")
_INLINE_IMAGE_PREFIXES = ("syscontrol_chart_", "syscontrol_artifact_")
_ALLOWED_HISTORY_ROLES = {"system", "user", "assistant", "tool"}
_TMP_DIR_REAL = os.path.realpath(tempfile.gettempdir())


def _emit_tool_finished(name: str, result: str) -> None:
    """Emit tool_finished event and any inline image events found in the result."""
    _emit({"type": "tool_finished", "name": name})
    for match in _CHART_IMAGE_RE.finditer(result):
        # Validate: must be inside the system temp dir with expected prefix
        resolved = os.path.realpath(match.group(1))
        if os.path.commonpath([resolved, _TMP_DIR_REAL]) != _TMP_DIR_REAL:
            continue
        if not os.path.basename(resolved).startswith(_INLINE_IMAGE_PREFIXES):
            continue
        _emit({"type": "chart_image", "path": resolved})


def _coerce_history(raw_history: object) -> list[dict]:
    """Validate and normalize optional history payload from stdin command."""
    if not isinstance(raw_history, list):
        return []

    normalized: list[dict] = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            continue
        role_name = role.strip().lower()
        if role_name not in _ALLOWED_HISTORY_ROLES:
            continue
        if not content.strip():
            continue
        normalized.append({"role": role_name, "content": content})
    return normalized


# ── Bridge helpers ────────────────────────────────────────────────────────────

def _initialise_agent(
    provider_api_key: str | None = None,
    provider_base_url: str | None = None,
) -> tuple[MCPClientPool, list[dict], dict]:
    """Start the MCP client pool and build the full system message.

    Returns:
        A ``(pool, tools, system_message)`` triple ready for the event loop.

    Raises:
        Exception: Any startup failure — callers should catch and emit an error event.
    """
    mcp_client = MCPClient()
    pool       = MCPClientPool(
        mcp_client,
        provider_api_key=provider_api_key,
        provider_base_url=provider_base_url,
    )

    # Pre-warm worker pool in background to eliminate first-batch latency.
    threading.Thread(target=pool.warm_up, daemon=True).start()

    mcp_tools = mcp_client.list_tools()
    tools     = mcp_to_openai_tools(mcp_tools)

    system_prompt = load_system_prompt()
    tool_names    = [t["function"]["name"] for t in tools]
    full_system   = build_full_system_prompt(system_prompt, tool_names)

    system_message = {"role": "system", "content": full_system}
    return pool, tools, system_message


class _CancelRegistry:
    """Thread-safe holder for the currently-active turn's cancel event.

    Replaces the previous module-global ``_cancel_event``.  Turns are
    serialised by the event loop (a new ``user_message`` waits for the prior
    turn thread to join), so at most one entry is live at any time — but the
    lock makes the read/write pattern explicit and safe against any future
    refactor that loosens the serialisation.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: threading.Event | None = None

    def begin(self) -> threading.Event:
        event = threading.Event()
        with self._lock:
            self._active = event
        return event

    def end(self, event: threading.Event) -> None:
        with self._lock:
            if self._active is event:
                self._active = None

    def cancel(self) -> bool:
        with self._lock:
            if self._active is None:
                return False
            self._active.set()
            return True


_cancel_registry = _CancelRegistry()


def _handle_user_message(
    cmd: dict,
    session_histories: dict[str, list[dict]],
    llm: OpenAI,
    pool: MCPClientPool,
    tools: list[dict],
    system_message: dict,
    model: str,
    log: IO[str],
) -> None:
    """Process a ``user_message`` command: run a streaming turn and emit events.

    Args:
        cmd: The parsed command dict (must have ``type == "user_message"``).
        session_histories: Mutable map of ``session_id`` to conversation history.
        llm: OpenAI-compatible client.
        pool: MCP client pool for tool execution.
        tools: Tool definitions in OpenAI format.
        system_message: Pre-built system message dict.
        model: Model identifier string.
        log: File-like object for internal error logging (typically stderr).
    """
    raw_session_id = cmd.get("session_id", "default")
    session_id = str(raw_session_id).strip() or "default"
    messages = session_histories.setdefault(session_id, [])
    if not messages:
        messages.extend(_coerce_history(cmd.get("history")))

    raw_text = cmd.get("text", "")
    if not isinstance(raw_text, str):
        _emit({
            "type": "error", "category": "Protocol",
            "message": f"user_message.text must be a string, got {type(raw_text).__name__}",
        })
        return
    text = raw_text.strip()
    if not text:
        return
    messages.append({"role": "user", "content": text})

    cancel_event = _cancel_registry.begin()

    callbacks = TurnCallbacks(
        on_token=lambda t: _emit({"type": "token", "text": t}),
        on_tool_started=lambda names: _emit(
            {"type": "tool_started", "names": names}
        ),
        on_tool_finished=lambda name, result: _emit_tool_finished(name, result),
        on_error=lambda cat, msg: _emit(
            {"type": "error", "category": cat, "message": msg}
        ),
        cancel_event=cancel_event,
    )

    try:
        finish_reason, elapsed = run_streaming_turn(
            llm, pool, tools, system_message, messages, model, callbacks,
        )
        _emit({
            "type": "turn_done",
            "finish_reason": finish_reason,
            "elapsed": round(elapsed, 2),
        })
    except Exception as exc:
        log.write(f"[bridge] turn error: {exc}\n")
        _emit({"type": "error", "category": "Turn", "message": str(exc)})
    finally:
        _cancel_registry.end(cancel_event)


# ── Event loop ────────────────────────────────────────────────────────────────


def _event_loop(
    pool: MCPClientPool,
    tools: list[dict],
    system_message: dict,
    llm: OpenAI,
    model: str,
    log: IO[str],
) -> tuple[OpenAI, str]:
    """Read stdin commands, dispatch them, and return the (possibly reconfigured) client/model.

    Runs until EOF or a ``shutdown`` command.  User messages are dispatched
    to a worker thread so ``cancel`` commands can be read while a turn is
    in progress.  Unknown command types are silently ignored for forward
    compatibility.
    """
    session_histories: dict[str, list[dict]] = {}
    turn_thread: threading.Thread | None = None

    while True:
        cmd = _read_command()
        if cmd is None:
            break  # EOF — parent closed pipe

        cmd_type = cmd.get("type", "")

        if cmd_type == "shutdown":
            # Signal cancellation if a turn is running, then break.
            _cancel_registry.cancel()
            if turn_thread is not None:
                turn_thread.join(timeout=3.0)
            break
        elif cmd_type == "cancel":
            _cancel_registry.cancel()
        elif cmd_type == "clear_session":
            raw_session_id = cmd.get("session_id")
            session_id = str(raw_session_id).strip() if isinstance(raw_session_id, str) else ""
            if session_id:
                session_histories.pop(session_id, None)
                _emit({"type": "session_cleared", "session_id": session_id})
            else:
                session_histories.clear()
                _emit({"type": "session_cleared"})
        elif cmd_type == "configure":
            # Allow runtime reconfiguration of provider.  Cancel and wait for
            # any in-flight turn before swapping the client and clearing
            # history, otherwise the active turn can read stale or empty state
            # mid-stream.  Cancelling first means a stuck LLM call doesn't
            # block configure indefinitely.
            if turn_thread is not None:
                _cancel_registry.cancel()
                turn_thread.join()
                turn_thread = None
            api_key = cmd.get("api_key", llm.api_key)
            base_url = cmd.get("base_url", str(llm.base_url))
            model = cmd.get("model", model)
            llm = OpenAI(
                api_key=api_key, base_url=base_url,
                timeout=llm_client_timeout(),
                max_retries=llm_client_max_retries(),
            )
            pool.set_provider_config(str(api_key), str(base_url))
            session_histories.clear()
            _emit({"type": "configured", "model": model})
        elif cmd_type == "user_message":
            # Wait for any prior turn to finish before starting a new one.
            if turn_thread is not None:
                turn_thread.join()
            turn_thread = threading.Thread(
                target=_handle_user_message,
                args=(cmd, session_histories, llm, pool, tools, system_message, model, log),
                daemon=True,
            )
            turn_thread.start()

    return llm, model


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """Run the JSON-over-stdio bridge.

    Starts the MCP client pool, emits a ``ready`` event, then delegates
    to :func:`_event_loop` for command processing.
    """
    log = sys.stderr

    try:
        pool, tools, system_message = _initialise_agent(
            os.environ.get("SYSCONTROL_API_KEY", "ollama"),
            os.environ.get("SYSCONTROL_BASE_URL", LOCAL_BASE_URL),
        )
    except Exception as exc:
        _emit({"type": "error", "category": "Startup", "message": str(exc)})
        sys.exit(1)

    api_key = os.environ.get("SYSCONTROL_API_KEY", "ollama")
    base_url = os.environ.get("SYSCONTROL_BASE_URL", LOCAL_BASE_URL)
    model = os.environ.get("SYSCONTROL_MODEL", "qwen2.5:7b")

    llm = OpenAI(
        api_key=api_key, base_url=base_url,
        timeout=llm_client_timeout(),
        max_retries=llm_client_max_retries(),
    )
    _emit({"type": "ready", "tool_count": len(tools), "model": model})

    try:
        _event_loop(pool, tools, system_message, llm, model, log)
    except KeyboardInterrupt:
        pass
    finally:
        close_subagent_pool()
        pool.close_all()


if __name__ == "__main__":
    main()
