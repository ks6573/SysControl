#!/usr/bin/env python3
"""
SysControl Bridge — JSON-over-stdio bridge for the Swift frontend.

Reads newline-delimited JSON commands from stdin and writes JSON events
to stdout.  Reuses the full agent/core.py infrastructure (MCPClient,
MCPClientPool, run_streaming_turn) so every existing tool and the
streaming agentic loop work out of the box.

Protocol (stdin → bridge):
    {"type":"user_message","text":"...","session_id":"..."}
    {"type":"clear_session"}
    {"type":"shutdown"}

Protocol (bridge → stdout):
    {"type":"ready","tool_count":57,"model":"..."}
    {"type":"token","text":"Hello"}
    {"type":"tool_started","names":["get_cpu_usage"]}
    {"type":"tool_finished","name":"get_cpu_usage","result":"..."}
    {"type":"turn_done","finish_reason":"stop","elapsed":1.23}
    {"type":"error","category":"LLM","message":"..."}
"""

from __future__ import annotations

import json
import sys
import threading
from typing import IO

from agent.core import (
    MCPClient,
    MCPClientPool,
    RESPONSE_STYLE_GUIDANCE,
    TurnCallbacks,
    load_memory,
    load_system_prompt,
    mcp_to_openai_tools,
    run_streaming_turn,
)
from openai import OpenAI

# ── Helpers ───────────────────────────────────────────────────────────────────

_write_lock = threading.Lock()


def _emit(event: dict) -> None:
    """Write a single JSON event to stdout (thread-safe)."""
    with _write_lock:
        sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _read_command() -> dict | None:
    """Read one JSON command from stdin.  Returns None on EOF."""
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        _emit({
            "type": "error", "category": "Protocol",
            "message": f"Invalid JSON: {line.strip()}",
        })
        return {}


# ── Bridge helpers ────────────────────────────────────────────────────────────

def _initialise_agent() -> tuple[MCPClientPool, list[dict], dict]:
    """Start the MCP client pool and build the full system message.

    Returns:
        A ``(pool, tools, system_message)`` triple ready for the event loop.

    Raises:
        Exception: Any startup failure — callers should catch and emit an error event.
    """
    mcp_client = MCPClient()
    pool       = MCPClientPool(mcp_client)

    mcp_tools = mcp_client.list_tools()
    tools     = mcp_to_openai_tools(mcp_tools)

    system_prompt  = load_system_prompt()
    tool_names     = [t["function"]["name"] for t in tools]
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
    full_system += RESPONSE_STYLE_GUIDANCE

    system_message = {"role": "system", "content": full_system}
    return pool, tools, system_message


def _handle_user_message(
    cmd: dict,
    messages: list[dict],
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
        messages: Mutable conversation history — appended in-place.
        llm: OpenAI-compatible client.
        pool: MCP client pool for tool execution.
        tools: Tool definitions in OpenAI format.
        system_message: Pre-built system message dict.
        model: Model identifier string.
        log: File-like object for internal error logging (typically stderr).
    """
    text = cmd.get("text", "").strip()
    if not text:
        return
    messages.append({"role": "user", "content": text})

    callbacks = TurnCallbacks(
        on_token=lambda t: _emit({"type": "token", "text": t}),
        on_tool_started=lambda names: _emit(
            {"type": "tool_started", "names": names}
        ),
        # UI only needs completion signal; omit bulky tool output payload.
        on_tool_finished=lambda name, _result: _emit({
            "type": "tool_finished",
            "name": name,
        }),
        on_error=lambda cat, msg: _emit(
            {"type": "error", "category": cat, "message": msg}
        ),
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

    Runs until EOF or a ``shutdown`` command. Unknown command types are
    silently ignored for forward compatibility.
    """
    messages: list[dict] = []

    while True:
        cmd = _read_command()
        if cmd is None:
            break  # EOF — parent closed pipe

        cmd_type = cmd.get("type", "")

        if cmd_type == "shutdown":
            break
        elif cmd_type == "clear_session":
            messages.clear()
            _emit({"type": "session_cleared"})
        elif cmd_type == "configure":
            # Allow runtime reconfiguration of provider.
            api_key = cmd.get("api_key", llm.api_key)
            base_url = cmd.get("base_url", str(llm.base_url))
            model = cmd.get("model", model)
            llm = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
            _emit({"type": "configured", "model": model})
        elif cmd_type == "user_message":
            _handle_user_message(
                cmd, messages, llm, pool, tools, system_message, model, log,
            )

    return llm, model


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """Run the JSON-over-stdio bridge.

    Starts the MCP client pool, emits a ``ready`` event, then delegates
    to :func:`_event_loop` for command processing.
    """
    import os

    log = sys.stderr

    try:
        pool, tools, system_message = _initialise_agent()
    except Exception as exc:
        _emit({"type": "error", "category": "Startup", "message": str(exc)})
        sys.exit(1)

    api_key = os.environ.get("SYSCONTROL_API_KEY", "ollama")
    base_url = os.environ.get("SYSCONTROL_BASE_URL", "http://localhost:11434/v1")
    model = os.environ.get("SYSCONTROL_MODEL", "qwen2.5:7b")

    llm = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
    _emit({"type": "ready", "tool_count": len(tools), "model": model})

    try:
        _event_loop(pool, tools, system_message, llm, model, log)
    except KeyboardInterrupt:
        pass
    finally:
        pool.close_all()


if __name__ == "__main__":
    main()
