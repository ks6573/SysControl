"""Tests for agent/core.py — pure functions and helpers."""


from agent.core import (
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
