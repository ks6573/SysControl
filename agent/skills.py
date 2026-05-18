"""
SysControl — User-extensible skills system.

A *skill* is a reusable, named workflow defined in a single markdown file at
``~/.syscontrol/skills/<name>.md``.  Each file consists of:

1. A YAML-style frontmatter block delimited by ``---`` lines, with the schema
   below.
2. A body containing free-form instructions injected as a system prompt when
   the skill is invoked.

Frontmatter schema (every field optional except ``name`` and ``description``):

    ---
    name: diag
    description: Quick system triage when something feels off.
    trigger: "diagnose|why is X slow|something's wrong"   # optional regex hint
    tools: [get_system_alerts, get_top_processes, tail_system_logs]
    permissions: [allow_shell]
    agent: explorer                                       # run inside a sub-agent
    confirm: false
    ---
    Body markdown / playbook here.

Skills can be invoked from the CLI via ``/skills <name>`` or the
shorthand ``/<name>`` (which falls through to skill lookup when no built-in
slash command matches), and from the MCP server via the ``run_skill`` tool.

Built-in skills are shipped under ``agent/skills_builtin/*.md`` and copied to
the user directory on first run, so they appear as editable starting points
rather than hidden built-ins.
"""
from __future__ import annotations

import functools
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from agent.frontmatter import split_frontmatter, split_list
from agent.paths import (
    BUILTIN_SKILLS_DIR,
    SKILLS_DIR,
    ensure_skill_dirs,
)

logger = logging.getLogger(__name__)


# ── Dataclass ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SkillSpec:
    """Immutable skill specification loaded from a ``*.md`` file."""

    name: str
    description: str
    body: str
    path: Path
    trigger: str = ""
    tools: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    agent: str = ""
    confirm: bool = False


# ── Loader ───────────────────────────────────────────────────────────────────


def load_skill_file(path: Path) -> SkillSpec | None:
    """Parse a single ``*.md`` skill file.

    Returns ``None`` (logging a warning) when the file is unreadable or its
    frontmatter omits the required fields.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Skill file unreadable: %s (%s)", path, exc)
        return None
    front, body = split_frontmatter(text)
    name = (front.get("name") or path.stem).strip()
    description = front.get("description", "").strip()
    if not name:
        logger.warning("Skill at %s has empty name; skipping", path)
        return None
    if not description:
        # Fall back to the first non-empty body line so the listing is useful.
        for ln in body.splitlines():
            if ln.strip():
                description = ln.strip()
                break
    confirm_raw = front.get("confirm", "").strip().lower()
    return SkillSpec(
        name=name,
        description=description or "(no description)",
        body=body.strip(),
        path=path,
        trigger=front.get("trigger", "").strip(),
        tools=split_list(front.get("tools", "")),
        permissions=split_list(front.get("permissions", "")),
        agent=front.get("agent", "").strip(),
        confirm=confirm_raw in {"true", "yes", "1"},
    )


def _populate_builtins_if_missing() -> None:
    """Copy built-in skill files to ``SKILLS_DIR`` on first run.

    We never overwrite a file the user has touched — this is a one-shot
    bootstrap so brand-new installs see useful examples immediately.
    """
    ensure_skill_dirs()
    if not BUILTIN_SKILLS_DIR.exists():
        return
    for src in BUILTIN_SKILLS_DIR.glob("*.md"):
        dest = SKILLS_DIR / src.name
        if dest.exists():
            continue
        try:
            shutil.copyfile(src, dest)
        except OSError as exc:
            logger.warning("Could not seed skill %s: %s", src.name, exc)


# ── Registry ─────────────────────────────────────────────────────────────────


@dataclass
class SkillRegistry:
    """In-memory store of user-visible skills, keyed by name (case-insensitive)."""

    skills: dict[str, SkillSpec] = field(default_factory=dict)

    def get(self, name: str) -> SkillSpec | None:
        return self.skills.get(name.lower())

    def all(self) -> list[SkillSpec]:
        return sorted(self.skills.values(), key=lambda s: s.name)

    def names(self) -> list[str]:
        return [s.name for s in self.all()]


def _load_registry() -> SkillRegistry:
    """Build a fresh registry by walking ``SKILLS_DIR``."""
    _populate_builtins_if_missing()
    reg = SkillRegistry()
    if not SKILLS_DIR.exists():
        return reg
    for path in sorted(SKILLS_DIR.glob("*.md")):
        spec = load_skill_file(path)
        if spec is None:
            continue
        reg.skills[spec.name.lower()] = spec
    return reg


@functools.cache
def _cached_registry() -> SkillRegistry:
    return _load_registry()


def get_registry(*, refresh: bool = False) -> SkillRegistry:
    """Return the process-level skill registry.

    Pass ``refresh=True`` to discard the cached snapshot and re-scan disk —
    useful after ``/skills new`` or after the user edits a file outside the
    REPL.
    """
    if refresh:
        _cached_registry.cache_clear()
    return _cached_registry()


def list_skills() -> list[dict[str, str]]:
    """Return a JSON-friendly summary of every available skill."""
    reg = get_registry()
    return [
        {
            "name": s.name,
            "description": s.description,
            "tools": ", ".join(s.tools) if s.tools else "all",
            "agent": s.agent or "",
            "path": str(s.path),
        }
        for s in reg.all()
    ]


# ── Scaffolding helpers (used by the /skills CLI command) ────────────────────


_TEMPLATE = """---
name: {name}
description: One-line summary of what this skill does.
tools: []
permissions: []
---

Describe the workflow the assistant should follow when this skill runs.
Be specific — list the tools to call in order, the data to gather, the
output format you want, and any edge cases to watch for.
"""


def scaffold_skill(name: str) -> Path:
    """Write a starter ``<name>.md`` file under ``SKILLS_DIR`` and return its path.

    Refuses to overwrite an existing skill so a typo can't destroy work.
    """
    ensure_skill_dirs()
    slug = name.strip().lower().replace(" ", "-")
    if not slug:
        raise ValueError("skill name is required")
    dest = SKILLS_DIR / f"{slug}.md"
    if dest.exists():
        raise FileExistsError(f"skill already exists: {dest}")
    dest.write_text(_TEMPLATE.format(name=slug), encoding="utf-8")
    get_registry(refresh=True)
    return dest
