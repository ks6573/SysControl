"""Coding-mode project helpers for the interactive CLI.

These helpers intentionally live on the CLI side instead of becoming MCP tools:
they compose existing file/shell capabilities, keep approval policy centralized,
and avoid expanding the server tool surface for workflows that are mostly
project-command detection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectCommand:
    command: str
    reason: str
    timeout: int = 120


@dataclass(frozen=True)
class ProjectProfile:
    kind: str
    root: Path
    test: ProjectCommand | None = None
    lint: ProjectCommand | None = None


class ProjectDetector:
    """Detect likely test/lint commands from files in a project root."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.cwd()).resolve()

    def detect(self) -> ProjectProfile:
        for detector in (
            self._node,
            self._python,
            self._swift_package,
            self._rust,
            self._go,
        ):
            profile = detector()
            if profile is not None:
                return profile
        return ProjectProfile(kind="generic", root=self.root)

    def _node(self) -> ProjectProfile | None:
        package = self.root / "package.json"
        if not package.is_file():
            return None
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
        scripts = scripts if isinstance(scripts, dict) else {}
        package_manager = "npm"
        if (self.root / "pnpm-lock.yaml").is_file():
            package_manager = "pnpm"
        elif (self.root / "yarn.lock").is_file():
            package_manager = "yarn"
        test = None
        lint = None
        if "test" in scripts:
            test = ProjectCommand(f"{package_manager} test", "package.json test script")
        if "lint" in scripts:
            lint = ProjectCommand(f"{package_manager} run lint", "package.json lint script")
        elif "typecheck" in scripts:
            lint = ProjectCommand(
                f"{package_manager} run typecheck",
                "package.json typecheck script",
            )
        return ProjectProfile("node", self.root, test=test, lint=lint)

    def _python(self) -> ProjectProfile | None:
        if not (self.root / "pyproject.toml").is_file():
            return None
        runner = "uv run" if (self.root / "uv.lock").is_file() else "python -m"
        test_cmd = f"{runner} pytest" if runner == "uv run" else "python -m pytest"
        lint_cmd = f"{runner} ruff check ." if runner == "uv run" else "python -m ruff check ."
        test = ProjectCommand(test_cmd, "pyproject.toml Python project")
        lint = ProjectCommand(lint_cmd, "ruff check for Python project", timeout=120)
        return ProjectProfile("python", self.root, test=test, lint=lint)

    def _swift_package(self) -> ProjectProfile | None:
        if not (self.root / "Package.swift").is_file():
            return None
        return ProjectProfile(
            "swift",
            self.root,
            test=ProjectCommand("swift test", "Swift Package manifest"),
            lint=ProjectCommand("swift build", "Swift build as static check"),
        )

    def _rust(self) -> ProjectProfile | None:
        if not (self.root / "Cargo.toml").is_file():
            return None
        lint_cmd = "cargo clippy --all-targets --all-features"
        return ProjectProfile(
            "rust",
            self.root,
            test=ProjectCommand("cargo test", "Cargo project"),
            lint=ProjectCommand(lint_cmd, "Cargo clippy check"),
        )

    def _go(self) -> ProjectProfile | None:
        if not (self.root / "go.mod").is_file():
            return None
        return ProjectProfile(
            "go",
            self.root,
            test=ProjectCommand("go test ./...", "Go module"),
            lint=ProjectCommand("go vet ./...", "Go vet static check"),
        )


class CheckRunner:
    """Prepare coding-mode check commands."""

    def __init__(self, detector: ProjectDetector | None = None) -> None:
        self.detector = detector or ProjectDetector()

    def test_command(self, override: str = "") -> tuple[ProjectProfile, ProjectCommand | None]:
        profile = self.detector.detect()
        if override.strip():
            return profile, ProjectCommand(override.strip(), "user-provided test command")
        return profile, profile.test

    def lint_command(self, override: str = "") -> tuple[ProjectProfile, ProjectCommand | None]:
        profile = self.detector.detect()
        if override.strip():
            return profile, ProjectCommand(override.strip(), "user-provided lint command")
        return profile, profile.lint
