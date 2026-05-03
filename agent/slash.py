"""
Slash-command registry for the interactive CLI.

Each command is a small dataclass holding metadata + a handler.  Handlers
receive a ``ReplContext`` (see ``agent/cli.py``) and the raw argument string,
and return a ``SlashResult`` telling the REPL whether to keep looping, exit,
or send a synthetic user message to the LLM.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.cli import ReplContext


@dataclass(frozen=True)
class SlashResult:
    """Outcome of a slash-command handler."""

    exit: bool = False
    message: str | None = None  # if set, send as a user message to the LLM


CONTINUE = SlashResult()
EXIT = SlashResult(exit=True)


SlashHandler = Callable[["ReplContext", str], SlashResult]


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    handler: SlashHandler
    usage: str = ""
    aliases: tuple[str, ...] = ()
    arg_choices: tuple[str, ...] = ()
    visible: Callable[[ReplContext], bool] = field(default=lambda _ctx: True)


class SlashRegistry:
    """Ordered registry of slash commands, indexed by name + aliases."""

    def __init__(self) -> None:
        self._commands: list[SlashCommand] = []
        self._by_name: dict[str, SlashCommand] = {}

    def register(self, command: SlashCommand) -> None:
        self._commands.append(command)
        for key in (command.name, *command.aliases):
            if key in self._by_name:
                raise ValueError(f"Slash command '{key}' is already registered.")
            self._by_name[key] = command

    def get(self, name: str) -> SlashCommand | None:
        return self._by_name.get(name.lower())

    def visible(self, ctx: ReplContext) -> list[SlashCommand]:
        return [c for c in self._commands if c.visible(ctx)]

    def names(self, ctx: ReplContext) -> Iterable[str]:
        for cmd in self.visible(ctx):
            yield cmd.name


def parse(line: str) -> tuple[str, str]:
    """Split a `/name args...` line into (lowercase name, raw args)."""
    body = line.lstrip()
    if not body.startswith("/"):
        return "", ""
    name, _, rest = body[1:].partition(" ")
    return name.strip().lower(), rest.strip()
