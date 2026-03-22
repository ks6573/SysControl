"""
SysControl GUI — Chat history persistence.

Serializes conversations to Markdown files and manages the
~/.syscontrol/chat_history/ directory for the sidebar and goodbye-save flow.
"""

from __future__ import annotations

import datetime
import re
import shutil
import sys
from pathlib import Path

from openai import OpenAI

from agent.core import EXIT_PHRASES  # noqa: F401 — re-exported for main_window.py

CHAT_HISTORY_DIR = Path.home() / ".syscontrol" / "chat_history"


def ensure_history_dir() -> Path:
    """Create the chat history directory if it doesn't exist."""
    CHAT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return CHAT_HISTORY_DIR


def _slugify(text: str, max_len: int = 40) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug).strip("-")
    return slug[:max_len].rstrip("-") or "untitled"


def serialize_chat(messages: list[dict], title: str = "") -> str | None:
    """Convert a worker message list to a clean Markdown string.

    Returns None if there are no user/assistant messages with content.
    """
    visible = [
        m for m in messages
        if m.get("role") in ("user", "assistant") and (
            m.get("content") or m.get("tool_calls")
        )
    ]
    if not visible:
        return None

    now = datetime.datetime.now()
    display_title = title or "Chat"
    header = f"# {display_title} — {now.strftime('%B %d, %Y %I:%M %p')}\n"
    msg_count = len(visible)
    meta = f"\n**Messages:** {msg_count}\n"

    parts = [header, meta, "\n---\n"]

    for msg in visible:
        role = msg["role"]
        content = (msg.get("content") or "").strip()

        if role == "user":
            parts.append(f"\n### You\n{content}\n\n---\n")
        elif role == "assistant":
            if content:
                parts.append(f"\n### Assistant\n{content}\n\n---\n")
            elif msg.get("tool_calls"):
                names = [tc["function"]["name"] for tc in msg["tool_calls"]]
                parts.append(f"\n### Assistant\n*[Used tools: {', '.join(names)}]*\n\n---\n")

    return "".join(parts)


def save_chat(messages: list[dict], title: str = "") -> Path | None:
    """Serialize and save a conversation to the chat history directory.

    Args:
        messages: The worker message list to serialize.
        title: Optional LLM-generated title. Embedded in the markdown header
               and used by the sidebar for display.

    Returns the path of the saved file, or None if there was nothing to save.
    """
    md = serialize_chat(messages, title=title)
    if md is None:
        return None

    ensure_history_dir()

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H%M%S")

    slug = _slugify(title) if title else _slugify(
        next(
            (m["content"] for m in messages if m.get("role") == "user" and m.get("content")),
            "",
        )
    )
    filename = f"{timestamp}_{slug}.md"
    path = CHAT_HISTORY_DIR / filename

    # Handle collision
    counter = 2
    while path.exists():
        path = CHAT_HISTORY_DIR / f"{timestamp}_{slug}_{counter}.md"
        counter += 1

    path.write_text(md, encoding="utf-8")
    return path


def list_saved_chats() -> list[dict]:
    """Scan the history directory and return chat metadata sorted newest-first.

    Each entry: {path, filename, title, date_str}
    """
    if not CHAT_HISTORY_DIR.exists():
        return []

    chats: list[dict] = []
    for p in sorted(CHAT_HISTORY_DIR.glob("*.md"), reverse=True):
        title = _extract_title(p)
        date_str = _extract_date(p.name)
        chats.append({
            "path": p,
            "filename": p.name,
            "title": title,
            "date_str": date_str,
        })
    return chats


def read_chat(path: Path) -> str:
    """Read the full text of a saved chat file."""
    return path.read_text(encoding="utf-8")


def import_chat(source_path: Path) -> Path | None:
    """Copy an external .md file into the chat history directory.

    Returns the new path, or None on failure.
    """
    if not source_path.exists() or source_path.suffix.lower() != ".md":
        return None

    ensure_history_dir()

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H%M%S")
    slug = _slugify(source_path.stem)
    dest = CHAT_HISTORY_DIR / f"{timestamp}_{slug}.md"

    counter = 2
    while dest.exists():
        dest = CHAT_HISTORY_DIR / f"{timestamp}_{slug}_{counter}.md"
        counter += 1

    shutil.copy2(source_path, dest)
    return dest


def generate_title(messages: list[dict], api_key: str, base_url: str, model: str) -> str:
    """Ask the LLM for a brief chat title (3-6 words). Returns '' on failure."""
    # Collect the first few user/assistant exchanges for context
    snippet_parts: list[str] = []
    for m in messages:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            role = "User" if m["role"] == "user" else "Assistant"
            text = m["content"][:200]
            snippet_parts.append(f"{role}: {text}")
            if len(snippet_parts) >= 4:
                break
    if not snippet_parts:
        return ""
    snippet = "\n".join(snippet_parts)
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=10.0)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": (
                    "Write a short title (3-6 words, no quotes, no punctuation) "
                    f"for this conversation:\n\n{snippet}"
                ),
            }],
        )
        title = (resp.choices[0].message.content or "").strip().strip('"\'.')
        return title[:50] if title else ""
    except Exception as exc:
        sys.stderr.write(f"[syscontrol] generate_title LLM call failed: {exc}\n")
        return ""


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_title(path: Path) -> str:
    """Extract a display title from a chat .md file.

    Reads the '# Title — Date' header line first. Falls back to the first
    user message content, then the filename stem.
    """
    try:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            # Parse "# Title — Date" header
            if stripped.startswith("# ") and " — " in stripped:
                title_part = stripped[2:].split(" — ", 1)[0].strip()
                if title_part and title_part != "Chat":
                    return title_part[:50]
                break  # header found but no meaningful title — fall through
        # Fallback: first user message content
        in_you = False
        for line in text.splitlines():
            if line.strip() == "### You":
                in_you = True
                continue
            if in_you and line.strip():
                return line.strip()[:50]
    except OSError:
        pass
    return path.stem


def _extract_date(filename: str) -> str:
    """Parse a human-readable date from the filename timestamp prefix."""
    # Expected: YYYY-MM-DD_HHMMSS_slug.md
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})", filename)
    if match:
        y, mo, d, h, mi, s = match.groups()
        try:
            dt = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
            today = datetime.date.today()
            if dt.date() == today:
                return f"Today {dt.strftime('%I:%M %p')}"
            elif dt.date() == today - datetime.timedelta(days=1):
                return f"Yesterday {dt.strftime('%I:%M %p')}"
            else:
                return dt.strftime("%b %d, %Y")
        except ValueError:
            pass
    return filename
