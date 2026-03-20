"""
SysControl GUI — Agent worker thread.

Runs the streaming agentic loop on a background QThread, emitting Qt signals
for every token, tool call, and completion event. The main GUI thread never
blocks on network or subprocess I/O.

The streaming loop here is modeled after agent/cli.py:run_turn (L225-382)
and agent/remote.py:run_agent, but emits signals instead of printing to stdout.
"""

from __future__ import annotations

import json
import queue
import time
from dataclasses import dataclass
from pathlib import Path

import openai
from openai import OpenAI
from PySide6.QtCore import QThread, Signal

from agent.core import (
    LOCAL_API_KEY,
    LOCAL_BASE_URL,
    MAX_TOKENS,
    MCPClient,
    MCPClientPool,
    load_system_prompt,
    mcp_to_openai_tools,
)


@dataclass
class ProviderConfig:
    """Encapsulates everything needed to create an LLM client."""
    api_key: str
    base_url: str
    model: str
    label: str


# ── History pruning (same logic as cli.py:_prune_history) ─────────────────────

MAX_HISTORY_MESSAGES = 40


def _prune_history(messages: list[dict], max_messages: int = MAX_HISTORY_MESSAGES) -> list[dict]:
    """Trim history while preserving tool-call coherence."""
    if len(messages) <= max_messages:
        return messages

    groups: list[list[dict]] = []
    current: list[dict] = []
    for msg in messages:
        if msg["role"] == "user" and current:
            groups.append(current)
            current = []
        current.append(msg)
    if current:
        groups.append(current)

    total = sum(len(g) for g in groups)
    while groups and total > max_messages:
        total -= len(groups[0])
        groups.pop(0)

    return [msg for group in groups for msg in group]


# ── Memory helpers (same as cli.py, no ANSI) ──────────────────────────────────

MEMORY_FILE = Path(__file__).parent.parent.parent / "SysControl_Memory.md"


def _load_memory() -> str | None:
    if MEMORY_FILE.exists():
        text = MEMORY_FILE.read_text(encoding="utf-8").strip()
        return text if text else None
    return None


# ── Sentinel messages ─────────────────────────────────────────────────────────

_SHUTDOWN = object()


class AgentWorker(QThread):
    """Background thread that owns the MCP pool and streams LLM responses."""

    # Signals — all cross the thread boundary safely via Qt's event loop.
    token_received = Signal(str)         # each text chunk from the model
    tool_started   = Signal(list)        # list of tool names being executed
    tool_finished  = Signal(str, str)    # tool name, result text
    turn_finished  = Signal(float)       # elapsed seconds
    error_occurred = Signal(str, str)    # category, message
    ready          = Signal(int, str, str)  # tool_count, provider_label, model

    def __init__(self, config: ProviderConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._queue: queue.Queue = queue.Queue()
        self._messages: list[dict] = []
        self._pool: MCPClientPool | None = None
        self._tools: list[dict] = []
        self._system_message: dict = {}
        self._llm: OpenAI | None = None

    # ── Main thread calls these ────────────────────────────────────────────

    def submit_message(self, text: str) -> None:
        """Thread-safe: enqueue a user message for the worker to process."""
        self._queue.put(text)

    def shutdown(self) -> None:
        """Thread-safe: ask the worker to stop and clean up."""
        self._queue.put(_SHUTDOWN)
        self.wait(5000)  # wait up to 5s for graceful exit

    def clear_session(self) -> None:
        """Reset the message history (called from main thread between turns)."""
        # Not perfectly thread-safe, but only called when worker is idle.
        self._messages.clear()

    # ── QThread entry point ────────────────────────────────────────────────

    def run(self) -> None:
        """Worker event loop: init MCP, then process messages from the queue."""
        try:
            self._init_agent()
        except Exception as exc:
            self.error_occurred.emit("Startup", str(exc))
            return

        while True:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is _SHUTDOWN:
                break

            text = str(item)
            self._messages.append({"role": "user", "content": text})

            try:
                self._run_turn()
            except Exception as exc:
                self.error_occurred.emit("Error", str(exc))

        # Cleanup
        if self._pool:
            self._pool.close_all()

    # ── Agent initialisation ───────────────────────────────────────────────

    def _init_agent(self) -> None:
        """Spawn MCP server, load tools, build system message, create LLM client."""
        mcp_client = MCPClient()
        self._pool = MCPClientPool(mcp_client)

        mcp_tools = mcp_client.list_tools()
        self._tools = mcp_to_openai_tools(mcp_tools)

        system_prompt = load_system_prompt()
        tool_names = [t["function"]["name"] for t in self._tools]
        tool_list_block = (
            "\n\n---\n\n# Available Tools\n\n"
            "You have access to the following tools (call them by name):\n"
            + "\n".join(f"- {n}" for n in tool_names)
        )
        full_system = system_prompt + tool_list_block

        if _load_memory() is not None:
            full_system += (
                "\n\n---\n\n# Memory\n\n"
                "A persistent memory file exists with notes from past sessions. "
                "Call `read_memory` when the user references something from a previous session, "
                "asks what you remember, or when prior context seems relevant. "
                "Call `append_memory_note` to save a key fact mid-session without waiting for exit."
            )

        self._system_message = {"role": "system", "content": full_system}
        self._llm = OpenAI(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            timeout=120.0,
        )

        self.ready.emit(len(self._tools), self._config.label, self._config.model)

    # ── Streaming agentic loop ─────────────────────────────────────────────

    def _run_turn(self) -> None:
        """
        One complete user turn: stream response, execute tool calls, repeat.
        Modeled after cli.py:run_turn (L225-382).
        """
        start_time = time.monotonic()

        while True:
            # Prune history
            self._messages[:] = _prune_history(self._messages)

            # ── Stream LLM response ───────────────────────────────────────
            try:
                stream = self._llm.chat.completions.create(
                    model=self._config.model,
                    max_tokens=MAX_TOKENS,
                    tools=self._tools,
                    messages=[self._system_message] + self._messages,
                    stream=True,
                )
            except openai.APITimeoutError as exc:
                self.error_occurred.emit("Timeout", f"LLM request timed out ({exc})")
                return
            except openai.APIConnectionError as exc:
                self.error_occurred.emit("Connection", f"Cannot reach LLM endpoint: {exc}")
                return
            except openai.AuthenticationError as exc:
                self.error_occurred.emit("Auth", f"Invalid API key: {exc}")
                return
            except openai.APIStatusError as exc:
                self.error_occurred.emit("API", f"LLM error {exc.status_code}: {exc.message}")
                return
            except openai.OpenAIError as exc:
                self.error_occurred.emit("LLM", f"LLM error: {exc}")
                return

            # Accumulate streamed content
            content_parts: list[str] = []
            tool_calls: list[dict] = []
            finish_reason: str | None = None

            for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                delta = choice.delta

                # Text tokens
                if delta.content:
                    content_parts.append(delta.content)
                    self.token_received.emit(delta.content)

                # Tool call fragments (streaming JSON)
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        while len(tool_calls) <= tc.index:
                            tool_calls.append({
                                "id": "",
                                "function": {"name": "", "arguments": ""},
                            })
                        entry = tool_calls[tc.index]
                        if tc.id:
                            entry["id"] = tc.id
                        if tc.function and tc.function.name:
                            entry["function"]["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            entry["function"]["arguments"] += tc.function.arguments

                if choice.finish_reason:
                    finish_reason = choice.finish_reason

            content = "".join(content_parts)

            # ── Handle finish reason ──────────────────────────────────────
            if finish_reason in ("stop", None) and not tool_calls:
                self._messages.append({"role": "assistant", "content": content})
                elapsed = time.monotonic() - start_time
                self.turn_finished.emit(elapsed)
                break

            elif finish_reason == "tool_calls":
                # Record assistant message with tool call metadata
                self._messages.append({
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": [
                        {
                            "id":   tc["id"],
                            "type": "function",
                            "function": {
                                "name":      tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        }
                        for tc in tool_calls
                    ],
                })

                # Execute tools in parallel
                names = [tc["function"]["name"] for tc in tool_calls]
                self.tool_started.emit(names)

                try:
                    results = self._pool.call_tools_parallel(tool_calls)
                except RuntimeError as exc:
                    self.error_occurred.emit("MCP", f"MCP server crashed: {exc}")
                    return
                except Exception as exc:
                    self.error_occurred.emit("Tool", f"Tool execution failed: {exc}")
                    return

                for tc_id, name, result in results:
                    self._messages.append({
                        "role":         "tool",
                        "tool_call_id": tc_id,
                        "content":      result,
                    })
                    self.tool_finished.emit(name, result)

                # Loop — model will process tool results on next iteration

            else:
                # max_tokens, content_filter, etc.
                self._messages.append({"role": "assistant", "content": content})
                elapsed = time.monotonic() - start_time
                self.turn_finished.emit(elapsed)
                break
