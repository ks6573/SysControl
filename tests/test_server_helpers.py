"""Tests for mcp/server.py — pure helper functions.

Imports are at module level.  ``mcp.server`` is heavy (~4650 lines, pulls in
psutil/matplotlib) but is loaded only once per test session.
"""

from mcp.server import (
    _classify_pressure,
    _detect_cpu_oc,
    _detect_gpu_oc,
    _get_upgrade_feasibility,
    make_error,
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
