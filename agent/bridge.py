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

from agent.core import (
    MCPClient,
    MCPClientPool,
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
        _emit({"type": "error", "category": "Protocol", "message": f"Invalid JSON: {line.strip()}"})
        return {}


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Redirect stderr so Python warnings/tracebacks don't pollute the
    # JSON stdout channel.  We keep a reference for logging.
    log = sys.stderr

    # ── Startup ──────────────────────────────────────────────────────
    try:
        mcp_client = MCPClient()
        pool = MCPClientPool(mcp_client)

        mcp_tools = mcp_client.list_tools()
        tools = mcp_to_openai_tools(mcp_tools)

        system_prompt = load_system_prompt()
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
    except Exception as exc:
        _emit({"type": "error", "category": "Startup", "message": str(exc)})
        sys.exit(1)

    # ── Per-session state ────────────────────────────────────────────
    # The Swift app tells us which provider/model to use via the first
    # config command.  For now, we read env vars or default to local.
    import os
    api_key  = os.environ.get("SYSCONTROL_API_KEY", "ollama")
    base_url = os.environ.get("SYSCONTROL_BASE_URL", "http://localhost:11434/v1")
    model    = os.environ.get("SYSCONTROL_MODEL", "qwen2.5:7b")

    llm = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)

    _emit({"type": "ready", "tool_count": len(tools), "model": model})

    messages: list[dict] = []

    # ── Event loop ───────────────────────────────────────────────────
    try:
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
                # Allow runtime reconfiguration of provider
                api_key  = cmd.get("api_key", api_key)
                base_url = cmd.get("base_url", base_url)
                model    = cmd.get("model", model)
                llm = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
                _emit({"type": "configured", "model": model})

            elif cmd_type == "user_message":
                text = cmd.get("text", "").strip()
                if not text:
                    continue
                messages.append({"role": "user", "content": text})

                callbacks = TurnCallbacks(
                    on_token=lambda t: _emit({"type": "token", "text": t}),
                    on_tool_started=lambda names: _emit({"type": "tool_started", "names": names}),
                    on_tool_finished=lambda name, result: _emit({
                        "type": "tool_finished",
                        "name": name,
                        "result": result[:2000],  # cap to avoid overwhelming the UI
                    }),
                    on_error=lambda cat, msg: _emit({"type": "error", "category": cat, "message": msg}),
                )

                try:
                    finish_reason, elapsed = run_streaming_turn(
                        llm, pool, tools, system_message, messages, model, callbacks,
                    )
                    _emit({"type": "turn_done", "finish_reason": finish_reason, "elapsed": round(elapsed, 2)})
                except Exception as exc:
                    log.write(f"[bridge] turn error: {exc}\n")
                    _emit({"type": "error", "category": "Turn", "message": str(exc)})

            # Unknown command types are silently ignored for forward compatibility.

    except KeyboardInterrupt:
        pass
    finally:
        pool.close_all()


if __name__ == "__main__":
    main()
