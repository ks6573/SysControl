"""Data models for the SysControl Flet GUI.

The authoritative LLM transcript lives in ``GuiSession.messages`` (OpenAI
chat-completion format, mutated in place by ``agent.core.run_streaming_turn``);
the chat view renders directly from it plus a live streaming buffer held by the
controller.  Sessions persist to ``~/.syscontrol/gui_chats/`` as plain JSON.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"
ROLE_SYSTEM = "system"

DEFAULT_TITLE = "New chat"


@dataclass
class GuiSession:
    """A persisted chat session.

    ``messages`` is the OpenAI-format transcript (user/assistant/tool entries,
    excluding the system prompt which is supplied separately at turn time).
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = DEFAULT_TITLE
    messages: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    pinned: bool = False
    archived: bool = False

    def touch(self) -> None:
        """Update the modified timestamp (call after mutating messages)."""
        self.updated_at = time.time()

    def derive_title(self) -> None:
        """Set the title from the first user message if still the default."""
        if self.title and self.title != DEFAULT_TITLE:
            return
        for msg in self.messages:
            if msg.get("role") == ROLE_USER and isinstance(msg.get("content"), str):
                text = msg["content"].strip().replace("\n", " ")
                if text:
                    self.title = text[:60] + ("…" if len(text) > 60 else "")
                    return

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "messages": self.messages,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pinned": self.pinned,
            "archived": self.archived,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GuiSession:
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex),
            title=str(data.get("title") or DEFAULT_TITLE),
            messages=list(data.get("messages") or []),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            pinned=bool(data.get("pinned")),
            archived=bool(data.get("archived")),
        )
