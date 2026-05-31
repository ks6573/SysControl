"""In-process agent backend for the Flet GUI.

Mirrors ``agent/cli.py:main()`` setup but renders to the GUI instead of a
terminal: it creates the MCP client + pool, builds the OpenAI client and the
tool/system-prompt context, then runs ``run_streaming_turn()`` on a worker
thread driven by ``TurnCallbacks``.  Because the GUI is itself Python, there is
no subprocess bridge — the agent loop runs directly in this process.
"""

from __future__ import annotations

import contextlib
import threading

from agent.core import (
    MCPClient,
    MCPClientPool,
    OpenAI,
    TurnCallbacks,
    build_full_system_prompt,
    llm_client_max_retries,
    llm_client_timeout,
    load_system_prompt,
    mcp_to_openai_tools,
    run_streaming_turn,
)
from agent.runner import close_subagent_pool


class Backend:
    """Owns the MCP pool + OpenAI client and runs turns on worker threads."""

    def __init__(self) -> None:
        self._pool: MCPClientPool | None = None
        self._llm: OpenAI | None = None
        self._tools: list[dict] = []
        self._system_message: dict = {"role": "system", "content": ""}
        self._model: str = ""
        self._lock = threading.Lock()
        self.ready = False
        self.tool_count = 0

    def connect(self, api_key: str, base_url: str, model: str) -> None:
        """Spawn the MCP server, list tools, build the prompt + LLM client.

        Blocking and potentially slow (subprocess handshake) — call from a
        worker thread.  Raises ``RuntimeError`` if the MCP handshake fails (the
        message carries the server's stderr tail).
        """
        mcp_client = MCPClient()
        pool = MCPClientPool(
            mcp_client, provider_api_key=api_key, provider_base_url=base_url,
        )
        tools = mcp_to_openai_tools(mcp_client.list_tools())
        tool_names = [t["function"]["name"] for t in tools]
        full_system = build_full_system_prompt(load_system_prompt(), tool_names)
        llm = OpenAI(
            api_key=api_key, base_url=base_url,
            timeout=llm_client_timeout(), max_retries=llm_client_max_retries(),
        )
        with self._lock:
            self._pool = pool
            self._llm = llm
            self._tools = tools
            self._system_message = {"role": "system", "content": full_system}
            self._model = model
            self.tool_count = len(tools)
            self.ready = True

    def reconfigure(self, api_key: str, base_url: str, model: str) -> None:
        """Swap provider credentials / model without re-spawning the MCP server."""
        with self._lock:
            if self._pool is None:
                return
            self._pool.set_provider_config(api_key, base_url)
            self._llm = OpenAI(
                api_key=api_key, base_url=base_url,
                timeout=llm_client_timeout(), max_retries=llm_client_max_retries(),
            )
            self._model = model

    def warm_up(self) -> None:
        """Pre-spawn extra MCP workers in the background (best-effort)."""
        with self._lock:
            pool = self._pool
        if pool is not None:
            with contextlib.suppress(Exception):
                pool.warm_up()

    def run_turn(self, messages: list[dict], callbacks: TurnCallbacks) -> tuple[str, float]:
        """Run one streaming turn (blocking; mutates *messages* in place)."""
        with self._lock:
            llm, pool, tools = self._llm, self._pool, self._tools
            system_message, model = self._system_message, self._model
        if llm is None or pool is None:
            raise RuntimeError("Backend is not connected yet.")
        return run_streaming_turn(
            llm, pool, tools, system_message, messages, model, callbacks,
        )

    def close(self) -> None:
        """Tear down the MCP pool and any sub-agent pool (idempotent)."""
        with self._lock:
            pool = self._pool
            self._pool = None
            self.ready = False
        close_subagent_pool()
        if pool is not None:
            with contextlib.suppress(Exception):
                pool.close_all()
