"""Tests for agent/cli_completers.py — @file expansion + completer cache."""

from pathlib import Path

import pytest

from agent.cli_completers import AtFileCompleter, expand_at_mentions


def test_expand_at_mentions_inlines_fenced_block(tmp_path: Path) -> None:
    target = tmp_path / "hello.py"
    target.write_text("print('hi')\n", encoding="utf-8")
    expanded, warnings = expand_at_mentions("Look at @hello.py please", cwd=tmp_path)
    assert warnings == []
    assert "--- @hello.py ---" in expanded
    assert "```python" in expanded
    assert "print('hi')" in expanded


def test_expand_at_mentions_warns_on_missing_path(tmp_path: Path) -> None:
    expanded, warnings = expand_at_mentions("Open @does/not/exist.txt", cwd=tmp_path)
    assert expanded == "Open @does/not/exist.txt"  # untouched
    assert any("not found" in w for w in warnings)


def test_expand_at_mentions_dedupes(tmp_path: Path) -> None:
    target = tmp_path / "x.txt"
    target.write_text("a", encoding="utf-8")
    expanded, _ = expand_at_mentions("@x.txt and @x.txt again", cwd=tmp_path)
    assert expanded.count("--- @x.txt ---") == 1


def test_expand_at_mentions_blocks_path_traversal(tmp_path: Path) -> None:
    sibling = tmp_path.parent / "outside.txt"
    sibling.write_text("secret", encoding="utf-8")
    try:
        expanded, warnings = expand_at_mentions("@../outside.txt", cwd=tmp_path)
        assert "secret" not in expanded
        assert any("outside cwd" in w for w in warnings)
    finally:
        sibling.unlink(missing_ok=True)


def test_expand_at_mentions_truncates_oversized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent.cli_completers.MAX_FILE_BYTES", 16)
    big = tmp_path / "big.txt"
    big.write_text("x" * 1024, encoding="utf-8")
    expanded, _ = expand_at_mentions("@big.txt", cwd=tmp_path)
    assert "(truncated to 16 bytes)" in expanded


def test_at_file_completer_caches_per_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "alpha.py").write_text("", encoding="utf-8")
    (tmp_path / "beta.py").write_text("", encoding="utf-8")
    completer = AtFileCompleter()
    files1 = completer._files_for(str(tmp_path))
    assert {"alpha.py", "beta.py"}.issubset(set(files1))

    other = tmp_path / "sub"
    other.mkdir()
    (other / "gamma.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(other)
    files2 = completer._files_for(str(other))
    assert "gamma.py" in files2  # different cwd → different cache key
