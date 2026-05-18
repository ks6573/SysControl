"""
SysControl — Minimal YAML-frontmatter parser shared by skills, user commands,
and user agents.

Avoiding a real YAML dependency keeps the import surface tiny and the failure
modes obvious: this parser only handles flat ``key: value`` pairs (with inline
``# comments``) and inline lists (``[a, b, c]``).  Multi-line scalars, anchors,
nested structures, and anything else PyYAML can do are out of scope — by
design.  Callers needing more should adopt PyYAML themselves.

Schema delimiters: the frontmatter block must start at line one with ``---``
and end with another ``---``.  Anything else is treated as a body-only file.
"""
from __future__ import annotations


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return ``(key_value_pairs, body)`` from a markdown source.

    When parsing fails or no frontmatter block is present, returns
    ``({}, text)`` so callers can fall back to a body-only document.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end_idx: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, text
    raw_block = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1:]).lstrip("\n")
    return parse_flat_yaml(raw_block), body


def parse_flat_yaml(block: str) -> dict[str, str]:
    """Parse a flat ``key: value`` YAML block (one entry per line)."""
    out: dict[str, str] = {}
    for raw in block.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def split_list(raw: str) -> tuple[str, ...]:
    """Parse a YAML inline list (``[a, b, c]``) or comma-separated string.

    Returns an empty tuple for ``""`` or ``"[]"``.
    """
    text = raw.strip().strip("[]").strip()
    if not text:
        return ()
    parts = [p.strip().strip('"').strip("'") for p in text.split(",")]
    return tuple(p for p in parts if p)
