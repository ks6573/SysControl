"""
SysControl Agent — Sub-agent runner.

Executes an AgentSpec in a fully isolated context:

* A fresh MCPClient subprocess with ``SYSCONTROL_AGENT_DEPTH=1`` in its
  environment, which blocks nested ``run_agent`` calls inside the sub-agent.
* A single-client MCPClientPool (``pool_size=1``) — sub-agents do not spawn
  extra workers; parallel tool calls are serialised on the primary client.
* A filtered tool list built from ``spec.allowed_tools``.
* A clean message history containing only the delegated task.

Only the agent's final text response is returned to the caller; intermediate
token events and tool-call details are discarded (or forwarded to an optional
``on_progress`` callback for CLI spinners).
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable

from openai import OpenAI

from agent.agents import AgentSpec
from agent.core import (
    MCPClient,
    MCPClientPool,
    TurnCallbacks,
    load_system_prompt,
    mcp_to_openai_tools,
    run_streaming_turn,
)

logger = logging.getLogger(__name__)

# Env-var injected into sub-agent subprocess to prevent recursive spawning.
_DEPTH_ENV_VAR = "SYSCONTROL_AGENT_DEPTH"

# Env vars propagated to sub-agent subprocesses.  Only these (plus all
# SYSCONTROL_* vars) are forwarded — secrets in the parent env are NOT leaked.
_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "PYTHONPATH",
    "VIRTUAL_ENV", "TMPDIR", "TZ",
)


def _build_subprocess_env() -> dict[str, str]:
    """Build a minimal environment dict for the sub-agent subprocess.

    Propagates only allowlisted vars and ``SYSCONTROL_*`` prefixed vars from
    the parent, then sets the depth guard to block nested agent spawning.
    """
    env: dict[str, str] = {}
    for key in _ENV_ALLOWLIST:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    # Forward all SYSCONTROL_* vars (API key, base URL, model, etc.).
    for key, val in os.environ.items():
        if key.startswith("SYSCONTROL_"):
            env[key] = val
    env[_DEPTH_ENV_VAR] = "1"
    return env


def _build_filtered_tools(client: MCPClient, spec: AgentSpec) -> list[dict]:
    """Return the MCP tool list filtered by *spec* and stripped of ``run_agent``.

    Raises:
        RuntimeError: If ``client.list_tools()`` does not return a list.
    """
    all_tools = client.list_tools()
    if not isinstance(all_tools, list):
        raise RuntimeError(
            f"list_tools() returned {type(all_tools).__name__}, expected list"
        )
    if spec.allowed_tools is not None:
        allowed = frozenset(spec.allowed_tools)
        all_tools = [t for t in all_tools if t["name"] in allowed]
    # Always strip run_agent — sub-agents must not spawn further agents.
    return [t for t in all_tools if t["name"] != "run_agent"]


def _build_system_message(spec: AgentSpec) -> dict[str, str]:
    """Construct the system message combining the base prompt with the agent persona.

    Falls back to the agent persona alone if the base prompt cannot be loaded,
    logging a warning so the degradation is visible.
    """
    try:
        base = load_system_prompt()
        content = f"{base}\n\n---\n\n{spec.system_prompt}"
    except Exception:
        logger.warning(
            "Failed to load base system prompt; using agent persona only",
            exc_info=True,
        )
        content = spec.system_prompt
    return {"role": "system", "content": content}


def run_subagent(
    spec: AgentSpec,
    task: str,
    llm: OpenAI,
    model: str,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """Run *spec* on *task* in an isolated context and return the final text.

    Starts a dedicated MCP server subprocess, restricts its tool list to
    ``spec.allowed_tools``, then calls ``run_streaming_turn()`` with a fresh
    message history.  The sub-agent's output is collected token-by-token and
    returned as a single stripped string.

    Args:
        spec:        AgentSpec describing the sub-agent's role, tools, and prompt.
        task:        Self-contained task description passed as the first user turn.
        llm:         Configured OpenAI-compatible client (credentials from caller).
        model:       Model identifier passed to the LLM API.
        on_progress: Optional single-argument callback invoked with brief status
                     strings during tool use (e.g. to drive a CLI spinner).

    Returns:
        The agent's final stripped text response, or an ``[Agent error …]``
        string if the run fails for any reason.
    """
    env = _build_subprocess_env()

    client: MCPClient | None = None
    pool: MCPClientPool | None = None
    try:
        client = MCPClient(extra_env=env)
        pool = MCPClientPool(client, pool_size=1)

        openai_tools = mcp_to_openai_tools(_build_filtered_tools(client, spec))
        system_message = _build_system_message(spec)
        messages: list[dict] = [{"role": "user", "content": task}]

        # Callbacks accumulate output tokens and capture the first error.
        # Note: run_streaming_turn() invokes callbacks from a single thread,
        # so no synchronisation is needed for these lists.
        output_parts: list[str] = []
        errors: list[tuple[str, str]] = []

        def _on_token(text: str) -> None:
            output_parts.append(text)

        def _on_error(category: str, message: str) -> None:
            errors.append((category, message))
            if len(errors) > 1:
                logger.debug("Sub-agent '%s' additional error: [%s] %s",
                             spec.name, category, message)

        def _on_tool_started(names: list[str]) -> None:
            if on_progress and names:
                on_progress(f"[{spec.name}] {names[0]}")

        def _noop_tool_finished(_name: str, _result: str) -> None:
            pass

        callbacks = TurnCallbacks(
            on_token=_on_token,
            on_tool_started=_on_tool_started,
            on_tool_finished=_noop_tool_finished,
            on_error=_on_error,
        )

        run_streaming_turn(
            llm=llm, pool=pool, tools=openai_tools,
            system_message=system_message, messages=messages,
            model=model, callbacks=callbacks,
        )

        if errors:
            category, message = errors[0]
            return f"[Agent error ({category}): {message}]"
        result = "".join(output_parts).strip()
        return result or "[Agent produced no output]"

    except Exception as exc:
        logger.exception("Sub-agent '%s' raised unexpectedly", spec.name)
        return f"[Agent error (Internal): {exc}]"

    finally:
        if pool is not None:
            pool.close_all()
        elif client is not None:
            client.close()
