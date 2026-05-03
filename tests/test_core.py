"""Tests for agent/core.py — pure functions and helpers."""


from agent.core import (
    TurnCallbacks,
    _execute_tool_calls,
    _handle_finish_reason,
    _parse_tool_call_args,
    colorize,
    load_memory,
    mcp_to_openai_tools,
    prune_history,
)

# ── prune_history ────────────────────────────────────────────────────────────


class TestPruneHistory:
    """Tests for the conversation-history pruning logic."""

    def test_no_pruning_needed(self) -> None:
        msgs = [{"role": "user", "content": "hi"}]
        assert prune_history(msgs, max_messages=10) == msgs

    def test_prunes_oldest_turns(self) -> None:
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "q3"},
            {"role": "assistant", "content": "a3"},
        ]
        result = prune_history(msgs, max_messages=4)
        assert len(result) <= 4
        # Newest turn must be preserved.
        assert result[-1]["content"] == "a3"
        assert result[-2]["content"] == "q3"

    def test_preserves_tool_call_coherence(self) -> None:
        """Tool messages grouped with their user turn should not be split."""
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "t1"}]},
            {"role": "tool", "tool_call_id": "t1", "content": "result1"},
            {"role": "assistant", "content": "a2"},
        ]
        result = prune_history(msgs, max_messages=4)
        # The tool message and its preceding assistant must stay together.
        tool_msgs = [m for m in result if m["role"] == "tool"]
        if tool_msgs:
            # If tool msg survived, its assistant must also be present.
            assistant_before = None
            for i, m in enumerate(result):
                if m["role"] == "tool":
                    assistant_before = result[i - 1] if i > 0 else None
                    break
            assert assistant_before is not None
            assert assistant_before["role"] == "assistant"

    def test_empty_history(self) -> None:
        assert prune_history([], max_messages=10) == []

    def test_exact_limit(self) -> None:
        msgs = [{"role": "user", "content": f"q{i}"} for i in range(10)]
        assert prune_history(msgs, max_messages=10) == msgs


# ── mcp_to_openai_tools ─────────────────────────────────────────────────────


class TestMCPToOpenAITools:
    """Tests for MCP → OpenAI tool-definition conversion."""

    def test_basic_conversion(self) -> None:
        mcp_tools = [
            {
                "name": "get_cpu_usage",
                "description": "Get CPU usage",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            }
        ]
        result = mcp_to_openai_tools(mcp_tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "get_cpu_usage"
        assert result[0]["function"]["description"] == "Get CPU usage"

    def test_missing_description(self) -> None:
        mcp_tools = [{"name": "test_tool"}]
        result = mcp_to_openai_tools(mcp_tools)
        assert result[0]["function"]["description"] == ""

    def test_missing_schema(self) -> None:
        mcp_tools = [{"name": "test_tool", "description": "d"}]
        result = mcp_to_openai_tools(mcp_tools)
        schema = result[0]["function"]["parameters"]
        assert schema["type"] == "object"
        assert schema["properties"] == {}

    def test_empty_list(self) -> None:
        assert mcp_to_openai_tools([]) == []


# ── tool-call handling ───────────────────────────────────────────────────────


class TestToolCallHandling:
    """Regression tests for provider/tool-call edge cases."""

    def test_parse_tool_call_accepts_dict_arguments(self) -> None:
        name, args = _parse_tool_call_args({
            "function": {"name": "get_cpu_usage", "arguments": {"n": 1}},
        })
        assert name == "get_cpu_usage"
        assert args == {"n": 1}

    def test_parse_tool_call_rejects_invalid_json(self) -> None:
        try:
            _parse_tool_call_args({
                "function": {"name": "get_cpu_usage", "arguments": "{bad"},
            })
        except ValueError as exc:
            assert "not valid JSON" in str(exc)
        else:
            raise AssertionError("invalid JSON arguments should raise")

    def test_execute_tool_calls_synthesizes_missing_call_id(self) -> None:
        class Pool:
            def call_tools_parallel(self, tool_calls):
                tc = tool_calls[0]
                return [(tc["id"], tc["function"]["name"], "ok")]

        messages: list[dict] = []
        errors: list[tuple[str, str]] = []
        callbacks = TurnCallbacks(on_error=lambda cat, msg: errors.append((cat, msg)))
        result = _execute_tool_calls(
            [{"id": "", "function": {"name": "get_cpu_usage", "arguments": "{}"}}],
            "",
            Pool(),
            messages,
            callbacks,
            0,
        )

        assert result is None
        assert errors == []
        assert messages[0]["tool_calls"][0]["id"] == "call_0"
        assert messages[1]["tool_call_id"] == messages[0]["tool_calls"][0]["id"]

    def test_handle_finish_reason_executes_tool_calls_even_when_finish_reason_stop(self) -> None:
        class Pool:
            def call_tools_parallel(self, tool_calls):
                tc = tool_calls[0]
                return [(tc["id"], tc["function"]["name"], "ok")]

        messages: list[dict] = []
        callbacks = TurnCallbacks()
        result = _handle_finish_reason(
            "stop",
            "",
            [{"id": "tc_1", "function": {"name": "get_cpu_usage", "arguments": "{}"}}],
            Pool(),
            messages,
            callbacks,
            0,
        )

        assert result is None
        assert messages[0]["role"] == "assistant"
        assert messages[1] == {"role": "tool", "tool_call_id": "tc_1", "content": "ok"}


# ── colorize ─────────────────────────────────────────────────────────────────


class TestColorize:
    """Tests for markdown → ANSI colorization."""

    def test_plain_text_unchanged(self) -> None:
        # No ANSI escapes when running in non-tty (test environment).
        result = colorize("hello world")
        assert "hello world" in result

    def test_heading(self) -> None:
        result = colorize("# Title")
        assert "Title" in result

    def test_bullet(self) -> None:
        result = colorize("- item")
        assert "item" in result

    def test_hr(self) -> None:
        result = colorize("---")
        # Should return something (possibly decorated), not crash.
        assert isinstance(result, str)


# ── load_memory ──────────────────────────────────────────────────────────────


class TestLoadMemory:
    """Tests for memory file loading."""

    def test_returns_none_when_missing(self, tmp_path, monkeypatch) -> None:
        import agent.core as core_mod
        monkeypatch.setattr(core_mod, "MEMORY_FILE", tmp_path / "nonexistent.md")
        assert load_memory() is None

    def test_returns_none_for_empty_file(self, tmp_path, monkeypatch) -> None:
        import agent.core as core_mod
        f = tmp_path / "memory.md"
        f.write_text("   \n  ")
        monkeypatch.setattr(core_mod, "MEMORY_FILE", f)
        assert load_memory() is None

    def test_returns_content(self, tmp_path, monkeypatch) -> None:
        import agent.core as core_mod
        f = tmp_path / "memory.md"
        f.write_text("User prefers dark mode")
        monkeypatch.setattr(core_mod, "MEMORY_FILE", f)
        assert load_memory() == "User prefers dark mode"


# ── TurnCallbacks defaults ─────────────────────────────────────────────────


class TestTurnCallbacksDefaults:
    """Regression tests: default no-op callbacks must be callable with the
    signatures their type annotations declare. A previous version stored a
    zero-arg outer lambda as the default, which silently broke any caller
    that instantiated ``TurnCallbacks()`` without overriding all four hooks.
    """

    def test_on_token_default_accepts_str(self) -> None:
        cb = TurnCallbacks()
        cb.on_token("hello")  # must not raise

    def test_on_tool_started_default_accepts_list(self) -> None:
        cb = TurnCallbacks()
        cb.on_tool_started(["get_cpu_usage", "get_ram_usage"])

    def test_on_tool_finished_default_accepts_two_strs(self) -> None:
        cb = TurnCallbacks()
        cb.on_tool_finished("get_cpu_usage", '{"total_percent": 12}')

    def test_on_error_default_accepts_two_strs(self) -> None:
        cb = TurnCallbacks()
        cb.on_error("API", "rate limited")

    def test_each_instance_gets_independent_default(self) -> None:
        a = TurnCallbacks()
        b = TurnCallbacks()
        # default_factory yields a fresh callable per instance — no shared mutable state.
        assert a.on_token is not b.on_token


# ── Sub-agent registry thread safety ───────────────────────────────────────


class TestAgentRegistry:
    """Sanity checks for the lazy AgentRegistry singleton."""

    def test_get_returns_same_instance_under_concurrent_access(self) -> None:
        import threading

        import agent.agents as agents_mod

        # Reset the cache so the test exercises the first-call path.
        agents_mod._get_registry.cache_clear()  # noqa: SLF001 — test reaches into private state

        results: list[object] = []
        barrier = threading.Barrier(8)

        def grab() -> None:
            barrier.wait()
            results.append(agents_mod._get_registry())  # noqa: SLF001

        threads = [threading.Thread(target=grab) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        first = results[0]
        assert all(r is first for r in results)

    def test_built_in_agents_resolve(self) -> None:
        from agent.agents import get_agent

        for name in ("explorer", "analyst", "researcher", "writer", "coder"):
            spec = get_agent(name)
            assert spec.name == name


# ── paths.py: import side-effects ──────────────────────────────────────────


class TestPaths:
    """Ensure ``import agent.paths`` does not create directories on disk."""

    def test_import_does_not_create_user_data_dir(self, tmp_path, monkeypatch) -> None:
        # Point HOME at an empty tmpdir, then re-import paths cleanly.
        monkeypatch.setenv("HOME", str(tmp_path))
        import importlib

        import agent.paths as paths_mod

        # Reload so module-level statements run again under the new HOME.
        importlib.reload(paths_mod)

        # Module must NOT have created ~/.syscontrol on import.
        assert not (tmp_path / ".syscontrol").exists()

        # ensure_user_data_dir() is the documented opt-in.
        paths_mod.ensure_user_data_dir()
        assert (tmp_path / ".syscontrol").exists()
