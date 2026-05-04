"""Tests for coding-mode project command detection."""

from pathlib import Path

from agent.cli_coding import CheckRunner, ProjectDetector


def test_detects_python_uv_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    profile = ProjectDetector(tmp_path).detect()

    assert profile.kind == "python"
    assert profile.test is not None
    assert profile.test.command == "uv run pytest"
    assert profile.lint is not None
    assert profile.lint.command == "uv run ruff check ."


def test_detects_node_scripts_and_package_manager(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"vitest","typecheck":"tsc --noEmit"}}',
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")

    profile = ProjectDetector(tmp_path).detect()

    assert profile.kind == "node"
    assert profile.test is not None
    assert profile.test.command == "pnpm test"
    assert profile.lint is not None
    assert profile.lint.command == "pnpm run typecheck"


def test_detects_node_lint_before_typecheck(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts":{"lint":"eslint .","typecheck":"tsc --noEmit"}}',
        encoding="utf-8",
    )

    profile = ProjectDetector(tmp_path).detect()

    assert profile.lint is not None
    assert profile.lint.command == "npm run lint"


def test_detects_swift_package(tmp_path: Path) -> None:
    (tmp_path / "Package.swift").write_text("// swift-tools-version: 6.0\n", encoding="utf-8")

    profile = ProjectDetector(tmp_path).detect()

    assert profile.kind == "swift"
    assert profile.test is not None
    assert profile.test.command == "swift test"
    assert profile.lint is not None
    assert profile.lint.command == "swift build"


def test_detects_rust_project(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'demo'\n", encoding="utf-8")

    profile = ProjectDetector(tmp_path).detect()

    assert profile.kind == "rust"
    assert profile.test is not None
    assert profile.test.command == "cargo test"
    assert profile.lint is not None
    assert profile.lint.command == "cargo clippy --all-targets --all-features"


def test_detects_go_module(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module demo\n", encoding="utf-8")

    profile = ProjectDetector(tmp_path).detect()

    assert profile.kind == "go"
    assert profile.test is not None
    assert profile.test.command == "go test ./..."
    assert profile.lint is not None
    assert profile.lint.command == "go vet ./..."


def test_generic_project_has_no_detected_commands(tmp_path: Path) -> None:
    profile = ProjectDetector(tmp_path).detect()

    assert profile.kind == "generic"
    assert profile.test is None
    assert profile.lint is None


def test_runner_uses_user_override(tmp_path: Path) -> None:
    runner = CheckRunner(ProjectDetector(tmp_path))

    profile, command = runner.test_command("pytest tests/test_cli.py -q")

    assert profile.kind == "generic"
    assert command is not None
    assert command.command == "pytest tests/test_cli.py -q"
    assert command.reason == "user-provided test command"
