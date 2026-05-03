"""
prompt_toolkit completers for the SysControl REPL.

- :class:`AtFileCompleter` triggers when the token under the cursor matches
  ``@<partial>``.  File list comes from ``git ls-files`` when the cwd is in a
  git repo (cached per ``(cwd, HEAD)``); otherwise we fall back to a recursive
  ``glob_files`` call against the MCP server.

- :func:`build_completer` merges the slash completer (kept in
  ``agent/cli.py:_SlashCompleter``) with the @file completer so both fire from
  one prompt.

- :func:`expand_at_mentions` is invoked by the REPL at submit time: every
  ``@path`` token in the user's text is replaced with the inlined file content
  wrapped in a fenced code block, capped at ``MAX_FILE_BYTES`` per file.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

from prompt_toolkit.completion import (
    CompleteEvent,
    Completer,
    Completion,
    merge_completers,
)
from prompt_toolkit.document import Document

MAX_FILES_LISTED = 500
MAX_FILE_BYTES = 64 * 1024
_AT_TOKEN_RE = re.compile(r"@([^\s@`]+)$")
_AT_MENTION_RE = re.compile(r"@(?P<path>[^\s@`]+)")
_LANG_BY_SUFFIX: dict[str, str] = {
    ".py": "python", ".swift": "swift", ".rs": "rust", ".go": "go",
    ".js": "javascript", ".jsx": "jsx", ".ts": "typescript", ".tsx": "tsx",
    ".json": "json", ".toml": "toml", ".yaml": "yaml", ".yml": "yaml",
    ".sh": "bash", ".md": "markdown", ".html": "html", ".css": "css",
    ".sql": "sql", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
}


def _git_head_sha(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _git_ls_files(cwd: str) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=cwd, capture_output=True, text=True, timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


def _walk_files(cwd: str) -> list[str]:
    """Fallback file list when not in a git repo: skip dotdirs, cap entries."""
    out: list[str] = []
    cwd_path = Path(cwd)
    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
        for name in files:
            if name.startswith("."):
                continue
            rel = Path(root, name).relative_to(cwd_path).as_posix()
            out.append(rel)
            if len(out) >= MAX_FILES_LISTED * 2:
                return out
    return out


class AtFileCompleter(Completer):
    """Pop a file picker when the cursor is on an `@<partial>` token."""

    def __init__(self) -> None:
        self._cache_key: tuple[str, str | None] | None = None
        self._cache: list[str] = []

    def _files_for(self, cwd: str) -> list[str]:
        key = (cwd, _git_head_sha(cwd))
        if key == self._cache_key and self._cache:
            return self._cache
        files = _git_ls_files(cwd) or _walk_files(cwd)
        files = sorted(files, key=len)[:MAX_FILES_LISTED]
        self._cache_key = key
        self._cache = files
        return files

    def get_completions(
        self, document: Document, _complete_event: CompleteEvent,
    ) -> Iterable[Completion]:
        text = document.text_before_cursor
        match = _AT_TOKEN_RE.search(text)
        if match is None:
            return
        partial = match.group(1).lower()
        files = self._files_for(os.getcwd())
        for path in files:
            if partial in path.lower():
                yield Completion(
                    path,
                    start_position=-len(match.group(1)),
                    display_meta="@file",
                )


def build_completer(slash_completer: Completer) -> Completer:
    """Combine the slash completer with the file-mention completer."""
    return merge_completers([slash_completer, AtFileCompleter()])


def _language_for(path: str) -> str:
    return _LANG_BY_SUFFIX.get(Path(path).suffix.lower(), "")


def expand_at_mentions(text: str, cwd: Path | None = None) -> tuple[str, list[str]]:
    """Inline every ``@path`` mention in *text* as a fenced code block.

    Returns a ``(expanded_text, warnings)`` tuple.  Unknown paths are left
    verbatim and added to *warnings*; oversized files are truncated with a
    visible footer.
    """
    base = cwd or Path.cwd()
    warnings: list[str] = []
    seen: set[str] = set()
    chunks: list[str] = []

    def _read(path: Path) -> tuple[str, bool]:
        data = path.read_bytes()
        truncated = len(data) > MAX_FILE_BYTES
        if truncated:
            data = data[:MAX_FILE_BYTES]
        try:
            return data.decode("utf-8"), truncated
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace"), truncated

    for m in _AT_MENTION_RE.finditer(text):
        rel = m.group("path")
        if rel in seen:
            continue
        seen.add(rel)
        candidate = (base / rel).resolve()
        try:
            candidate.relative_to(base.resolve())
        except ValueError:
            warnings.append(f"@{rel}: outside cwd, skipping")
            continue
        if not candidate.is_file():
            warnings.append(f"@{rel}: not found")
            continue
        body, truncated = _read(candidate)
        lang = _language_for(rel)
        fence = f"```{lang}\n{body}"
        if truncated:
            fence += f"\n... (truncated to {MAX_FILE_BYTES} bytes)"
        fence += "\n```"
        chunks.append(f"\n\n--- @{rel} ---\n{fence}")

    if not chunks:
        return text, warnings
    return text + "\n" + "".join(chunks), warnings
