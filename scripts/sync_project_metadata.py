#!/usr/bin/env python3
"""Synchronize derived project metadata without importing the MCP server.

The MCP server has intentional import-time setup (matplotlib and optional GPU
initialization), so this script reads its AST instead of importing it.  Run with
``--write`` after adding or removing tools; CI uses the default ``--check`` mode.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_FILE = ROOT / "mcp" / "server.py"

_TARGETS: tuple[tuple[Path, re.Pattern[str], str], ...] = (
    (
        ROOT / "README.md",
        re.compile(r"\b\d+ (?:real-time|built-in) tools\b"),
        "{count} built-in tools",
    ),
    (
        ROOT / "README.md",
        re.compile(r"## Tools \(\d+ total\)"),
        "## Tools ({count} total)",
    ),
    (
        ROOT / "CLAUDE.md",
        re.compile(r"\busing \d+ MCP tools\b"),
        "using {count} MCP tools",
    ),
    (
        ROOT / "CLAUDE.md",
        re.compile(r"\ball \d+(?: built-in)? tools\b"),
        "all {count} built-in tools",
    ),
    (
        ROOT / "mcp" / "prompt.json",
        re.compile(r"\baccess to \d+ live tools\b"),
        "access to {count} live tools",
    ),
)


def registry_tool_names(source: str) -> tuple[str, ...]:
    """Return literal tool names from the module-level ``TOOLS`` dictionary."""
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "TOOLS":
            continue
        if not isinstance(node.value, ast.Dict):
            raise ValueError("TOOLS must be defined as a dictionary literal")
        names: list[str] = []
        for key in node.value.keys:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                raise ValueError("every TOOLS key must be a literal string")
            names.append(key.value)
        if len(names) != len(set(names)):
            raise ValueError("TOOLS contains duplicate names")
        return tuple(names)
    raise ValueError("could not find the module-level TOOLS registry")


def synchronized_text(text: str, pattern: re.Pattern[str], replacement: str, count: int) -> str:
    """Return *text* with every matching derived count synchronized."""
    updated, matches = pattern.subn(replacement.format(count=count), text)
    if matches == 0:
        raise ValueError(f"metadata pattern not found: {pattern.pattern}")
    return updated


def sync(*, write: bool) -> list[Path]:
    """Check or update derived metadata and return files that were out of date."""
    names = registry_tool_names(SERVER_FILE.read_text(encoding="utf-8"))
    stale: list[Path] = []
    staged: dict[Path, str] = {}
    for path, pattern, replacement in _TARGETS:
        current = staged.get(path, path.read_text(encoding="utf-8"))
        updated = synchronized_text(current, pattern, replacement, len(names))
        staged[path] = updated
        if updated != current and path not in stale:
            stale.append(path)
    if write:
        for path, updated in staged.items():
            if path in stale:
                path.write_text(updated, encoding="utf-8")
    return stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Update stale files instead of failing the check.",
    )
    args = parser.parse_args()
    try:
        stale = sync(write=args.write)
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"metadata synchronization failed: {exc}", file=sys.stderr)
        return 2
    if stale and not args.write:
        print("Derived tool metadata is stale:", file=sys.stderr)
        for path in stale:
            print(f"  - {path.relative_to(ROOT)}", file=sys.stderr)
        print("Run: uv run python scripts/sync_project_metadata.py --write", file=sys.stderr)
        return 1
    action = "Updated" if stale else "Verified"
    print(f"{action} tool metadata from {len(registry_tool_names(SERVER_FILE.read_text()))} tools.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
