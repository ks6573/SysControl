"""Tests for mcp/server.py — pure helper functions.

Imports are at module level.  ``mcp.server`` is heavy (~4650 lines, pulls in
psutil/matplotlib) but is loaded only once per test session.
"""
import ast

from mcp.server import (
    TOOLS,
    _ast_security_scan,
    _classify_pressure,
    _detect_cpu_oc,
    _detect_gpu_oc,
    _escape_applescript,
    _get_upgrade_feasibility,
    make_error,
)

# ── Tool registry ────────────────────────────────────────────────────────────


def test_tool_count_matches_documented() -> None:
    """Bumping a tool requires updating CLAUDE.md / README — keep in sync."""
    expected = 91
    assert len(TOOLS) == expected, (
        f"TOOLS dict has {len(TOOLS)} entries; expected {expected}. "
        "If this change is intentional, update the constant here, "
        "CLAUDE.md, and README.md together."
    )

# ── _classify_pressure ───────────────────────────────────────────────────────


class TestClassifyPressure:
    """Tests for the resource-pressure severity classifier."""

    def test_critical(self) -> None:
        assert _classify_pressure(95.0) == "critical"
        assert _classify_pressure(90.0) == "critical"

    def test_high(self) -> None:
        assert _classify_pressure(80.0) == "high"
        assert _classify_pressure(75.0) == "high"

    def test_moderate(self) -> None:
        assert _classify_pressure(60.0) == "moderate"
        assert _classify_pressure(50.0) == "moderate"

    def test_low(self) -> None:
        assert _classify_pressure(30.0) == "low"
        assert _classify_pressure(0.0) == "low"

    def test_boundary_values(self) -> None:
        assert _classify_pressure(89.9) == "high"
        assert _classify_pressure(74.9) == "moderate"
        assert _classify_pressure(49.9) == "low"


# ── _detect_cpu_oc ───────────────────────────────────────────────────────────


class TestDetectCPUOC:
    """Tests for CPU overclocking detection."""

    def test_apple_silicon(self) -> None:
        result = _detect_cpu_oc("Apple M2 Pro", "Darwin", "arm64")
        assert result["supported"] is False

    def test_intel_mac(self) -> None:
        result = _detect_cpu_oc("Intel Core i7-9750H", "Darwin", "x86_64")
        assert result["supported"] is False

    def test_intel_k_unlocked(self) -> None:
        result = _detect_cpu_oc("Intel Core i9-13900K", "Linux", "x86_64")
        assert result["supported"] is True
        assert "Intel" in result["tools"][0]

    def test_intel_locked(self) -> None:
        result = _detect_cpu_oc("Intel Core i7-13700", "Linux", "x86_64")
        assert result["supported"] is False

    def test_amd_ryzen(self) -> None:
        result = _detect_cpu_oc("AMD Ryzen 9 7950X", "Linux", "x86_64")
        assert result["supported"] is True
        assert any("Ryzen" in t for t in result["tools"])

    def test_unknown_cpu(self) -> None:
        result = _detect_cpu_oc("Unknown Brand XYZ", "Linux", "x86_64")
        assert result["supported"] is False


# ── _detect_gpu_oc ───────────────────────────────────────────────────────────


class TestDetectGPUOC:
    """Tests for GPU overclocking detection."""

    def test_apple_silicon_gpu(self) -> None:
        result = _detect_gpu_oc("Darwin", "arm64", {})
        assert result["supported"] is False

    def test_macos_intel_gpu(self) -> None:
        result = _detect_gpu_oc("Darwin", "x86_64", {"name": "Radeon"})
        assert result["supported"] is False

    def test_linux_discrete_gpu(self) -> None:
        result = _detect_gpu_oc("Linux", "x86_64", {"name": "RTX 4090"})
        assert result["supported"] is True
        assert len(result["tools"]) > 0

    def test_no_gpu_detected(self) -> None:
        result = _detect_gpu_oc("Linux", "x86_64", {"error": "No GPU"})
        assert result["supported"] is False


# ── make_error ───────────────────────────────────────────────────────────────


class TestMakeError:
    """Tests for JSON-RPC error envelope construction."""

    def test_basic_error(self) -> None:
        result = make_error(1, -32601, "Method not found")
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 1
        assert result["error"]["code"] == -32601
        assert result["error"]["message"] == "Method not found"

    def test_null_id(self) -> None:
        result = make_error(None, -32700, "Parse error")
        assert result["id"] is None


# ── _get_upgrade_feasibility ─────────────────────────────────────────────────


class TestUpgradeFeasibility:
    """Tests for hardware upgrade feasibility analysis."""

    def test_apple_silicon(self) -> None:
        result = _get_upgrade_feasibility("Darwin", "arm64")
        assert result["ram"]["upgradeable"] is False
        assert result["cpu"]["upgradeable"] is False
        assert result["gpu"]["upgradeable"] is False
        assert result["storage"]["upgradeable"] is False

    def test_intel_mac(self) -> None:
        result = _get_upgrade_feasibility("Darwin", "x86_64")
        # Some fields are "model-dependent", not simply True/False.
        assert "ram" in result
        assert "cpu" in result

    def test_linux(self) -> None:
        result = _get_upgrade_feasibility("Linux", "x86_64")
        assert result["ram"]["upgradeable"] == "likely"


# ── _escape_applescript ──────────────────────────────────────────────────────


class TestEscapeAppleScript:
    """Regression tests for AppleScript literal escaping (security: no literal break-out)."""

    def test_escapes_double_quotes(self) -> None:
        assert _escape_applescript('he said "hi"') == 'he said \\"hi\\"'

    def test_escapes_backslash_first(self) -> None:
        assert _escape_applescript("a\\b") == "a\\\\b"

    def test_escapes_newline(self) -> None:
        result = _escape_applescript("line1\nline2")
        assert "\n" not in result
        assert result == "line1\\nline2"

    def test_escapes_carriage_return(self) -> None:
        result = _escape_applescript("line1\rline2")
        assert "\r" not in result
        assert result == "line1\\rline2"

    def test_escapes_tab(self) -> None:
        result = _escape_applescript("a\tb")
        assert "\t" not in result
        assert result == "a\\tb"

    def test_strips_other_control_characters(self) -> None:
        assert _escape_applescript("a\x00b\x01c") == "abc"

    def test_no_unescaped_quote_or_newline_in_injection_payload(self) -> None:
        payload = 'recipient"\nset x to "pwned'
        result = _escape_applescript(payload)
        # Raw " must not survive un-escaped; raw \n must not survive at all.
        assert '"\n' not in result
        assert "\n" not in result
        assert result == 'recipient\\"\\nset x to \\"pwned'

    def test_idempotent_on_safe_input(self) -> None:
        safe = "Hello, world! 123"
        assert _escape_applescript(safe) == safe


# ── _ast_security_scan ───────────────────────────────────────────────────────


def _scan(src: str) -> list[str]:
    return _ast_security_scan(ast.parse(src))


class TestASTSecurityScan:
    """Reject dynamic-tool implementations that try to escape the sandbox."""

    def test_clean_code_passes(self) -> None:
        assert _scan("def my_tool(): return {'ok': True}") == []

    def test_blocks_direct_eval(self) -> None:
        assert _scan("def t(): return eval('1+1')")  # not empty

    def test_blocks_direct_exec(self) -> None:
        assert _scan("def t(): exec('x=1')")

    def test_blocks_import_os(self) -> None:
        violations = _scan("import os\ndef t(): pass")
        assert any("os" in v for v in violations)

    def test_blocks_import_subprocess(self) -> None:
        violations = _scan("import subprocess\ndef t(): pass")
        assert any("subprocess" in v for v in violations)

    def test_blocks_from_import(self) -> None:
        violations = _scan("from importlib import import_module\ndef t(): pass")
        assert any("importlib" in v for v in violations)

    def test_blocks_builtins_subscript(self) -> None:
        violations = _scan("def t(): return __builtins__['eval']('1')")
        assert any("__builtins__" in v or "subscript" in v for v in violations)

    def test_blocks_builtins_attribute(self) -> None:
        violations = _scan("def t(): return __builtins__.eval('1')")
        assert any("__builtins__" in v for v in violations)

    def test_blocks_getattr(self) -> None:
        violations = _scan("def t(): return getattr(0, 'real')")
        assert any("getattr" in v for v in violations)

    def test_blocks_indirect_system_call(self) -> None:
        # Even if `os` were already in scope, `.system(...)` is rejected.
        violations = _scan("def t(x): return x.system('ls')")
        assert any("system" in v for v in violations)

    def test_blocks_rmtree(self) -> None:
        violations = _scan("def t(x): return x.rmtree('/')")
        assert any("rmtree" in v for v in violations)

    def test_blocks_pickle_module(self) -> None:
        # pickle is rejected at import; once the module isn't reachable, a
        # bare ``.loads()`` on an arbitrary parameter is harmless.
        violations = _scan("import pickle\ndef t(d): return pickle.loads(d)")
        assert any("pickle" in v for v in violations)

    def test_blocks_compile(self) -> None:
        violations = _scan("def t(): return compile('1', '', 'exec')")
        assert any("compile" in v for v in violations)
