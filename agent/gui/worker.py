"""
SysControl GUI — Agent worker thread.

Runs the streaming agentic loop on a background QThread, emitting Qt signals
for every token, tool call, and completion event. The main GUI thread never
blocks on network or subprocess I/O.

The streaming loop here is modeled after agent/cli.py:run_turn (L225-382)
and agent/remote.py:run_agent, but emits signals instead of printing to stdout.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from openai import OpenAI
from PySide6.QtCore import QObject, QThread, Signal

from agent.core import (
    MAX_TOKENS,
    MCPClient,
    MCPClientPool,
    TurnCallbacks,
    load_memory,
    load_system_prompt,
    mcp_to_openai_tools,
    run_streaming_turn,
)

_RESPONSE_STYLE_GUIDANCE = (
    "\n\n---\n\n# Response Style\n\n"
    "When replying to the user:\n"
    "- Avoid a single dense paragraph for non-trivial answers.\n"
    "- Prefer a short direct lead, then concise bullets or numbered steps when helpful.\n"
    "- Prefer headings + bullet lists over markdown tables unless the user explicitly asks for a table.\n"
    "- Insert blank lines between sections so responses are easy to scan.\n"
    "- Use markdown structure naturally (headings, bullets, code blocks) when it improves clarity.\n"
    "- Keep simple requests short (1-2 sentences).\n"
    "- For actionable instructions, provide concrete commands/examples.\n"
)


@dataclass
class ProviderConfig:
    """Encapsulates everything needed to create an LLM client."""
    api_key: str
    base_url: str
    model: str
    label: str


# ── Sentinel messages ─────────────────────────────────────────────────────────

_SHUTDOWN = object()
_CLEAR_SESSION = object()


class AgentWorker(QThread):
    """Background thread that owns the MCP pool and streams LLM responses."""

    # Signals — all cross the thread boundary safely via Qt's event loop.
    token_received = Signal(str)         # each text chunk from the model
    tool_started   = Signal(list)        # list of tool names being executed
    tool_finished  = Signal(str, str)    # tool name, result text
    turn_finished  = Signal(float)       # elapsed seconds
    error_occurred = Signal(str, str)    # category, message
    ready          = Signal(int, str, str)  # tool_count, provider_label, model

    def __init__(self, config: ProviderConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._queue: queue.Queue = queue.Queue()
        self._messages: list[dict] = []
        self._msg_lock = threading.Lock()  # CR-4: protects _messages across threads
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
        """Thread-safe: ask the worker to clear message history."""
        self._queue.put(_CLEAR_SESSION)

    def get_messages(self) -> list[dict]:
        """Return a snapshot of the current message history.

        Called from the main thread when the worker is idle (between turns).
        Thread-safe via _msg_lock.
        """
        with self._msg_lock:
            return list(self._messages)

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
            if item is _CLEAR_SESSION:
                with self._msg_lock:
                    self._messages.clear()
                continue

            text = str(item)
            with self._msg_lock:
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

        if load_memory() is not None:
            full_system += (
                "\n\n---\n\n# Memory\n\n"
                "A persistent memory file exists with notes from past sessions. "
                "Call `read_memory` when the user references something from a previous session, "
                "asks what you remember, or when prior context seems relevant. "
                "Call `append_memory_note` to save a key fact mid-session without waiting for exit."
            )
        full_system += _RESPONSE_STYLE_GUIDANCE

        self._system_message = {"role": "system", "content": full_system}
        self._llm = OpenAI(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            timeout=120.0,
        )

        self.ready.emit(len(self._tools), self._config.label, self._config.model)

    # ── Streaming agentic loop ─────────────────────────────────────────────

    def _run_turn(self) -> None:
        """One complete user turn — delegates to the shared streaming loop."""
        assert self._pool is not None, "MCP pool must be initialised before running turns"
        assert self._llm is not None, "LLM client must be initialised before running turns"

        callbacks = TurnCallbacks(
            on_token=lambda text: self.token_received.emit(text),
            on_tool_started=lambda names: self.tool_started.emit(names),
            on_tool_finished=lambda name, result: self.tool_finished.emit(name, result),
            on_error=lambda cat, msg: self.error_occurred.emit(cat, msg),
        )

        finish_reason, elapsed = run_streaming_turn(
            self._llm, self._pool, self._tools,
            self._system_message, self._messages,
            self._config.model, callbacks,
        )

        if finish_reason != "error":
            self.turn_finished.emit(elapsed)
