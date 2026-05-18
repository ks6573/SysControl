"""
SysControl — User-defined slash commands.

A user command is a markdown file at ``~/.syscontrol/commands/<name>.md`` with
the schema below.  Each file produces a single ``SlashCommand`` that, when
invoked, sends a templated user message to the LLM.

Schema:

    ---
    name: foo
    description: Short one-line description shown in /help.
    ---
    Multi-line prompt template that becomes the user message.
    Use {{args}} to interpolate the text following /foo.

User commands are loaded once at REPL startup; ``/skills reload`` does NOT
re-scan them (the loader is cheap, but we want predictable startup behavior).
Restart the CLI to pick up new ``commands/*.md`` files.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from agent.frontmatter import split_frontmatter
from agent.paths import COMMANDS_DIR, ensure_skill_dirs
from agent.slash import CONTINUE, SlashCommand, SlashHandler, SlashResult

logger = logging.getLogger(__name__)


def _make_handler(template: str) -> SlashHandler:
    """Return a SlashCommand-compatible handler that fills the template."""
    def _handler(_ctx: object, args: str) -> SlashResult:
        filled = template.replace("{{args}}", args.strip())
        if filled.strip() == "":
            return CONTINUE
        return SlashResult(message=filled)
    return _handler


def load_user_commands() -> Iterable[SlashCommand]:
    """Yield SlashCommand entries discovered under ``COMMANDS_DIR``.

    Files that fail to parse or lack a ``name`` are skipped with a warning.
    """
    ensure_skill_dirs()
    if not COMMANDS_DIR.exists():
        return
    for path in sorted(COMMANDS_DIR.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read user command %s: %s", path, exc)
            continue
        front, body = split_frontmatter(text)
        name = (front.get("name") or path.stem).strip().lower()
        if not name:
            continue
        description = front.get("description", "").strip() or f"User command from {path.name}"
        # Body is the template; if it's empty fall back to the description.
        template = body.strip() or description
        yield SlashCommand(
            name=name,
            description=f"(user) {description}",
            handler=_make_handler(template),
            usage=f"/{name} [args]",
        )
