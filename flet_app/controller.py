"""AppController — central coordinator for the Flet GUI.

Owns the page, the in-process :class:`~flet_app.backend.Backend`, the view
objects, the session list, and the per-turn live-render state.  Streaming
``TurnCallbacks`` fire on a worker thread and are marshaled onto the Flet UI
thread via ``page.run_thread``.
"""

from __future__ import annotations

import contextlib
import threading
import time

import flet as ft

from agent.core import OpenAI, TurnCallbacks, fetch_ollama_models
from flet_app import theme
from flet_app.backend import Backend
from flet_app.models import ROLE_ASSISTANT, ROLE_TOOL, ROLE_USER, GuiSession
from flet_app.store import credentials, provider_config, sessions
from flet_app.views import message_bubble as mb
from flet_app.views.chat_view import ChatView
from flet_app.views.input_bar import InputBar
from flet_app.views.settings import build_settings_dialog
from flet_app.views.sidebar import Sidebar

_FLUSH_INTERVAL = 0.06  # seconds between streamed-token UI commits


def _is_tool_error(result: str) -> bool:
    head = result.lstrip()[:200]
    return head.startswith(("[tool error", "[tool denied")) or '"error":' in head


class AppController:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.backend = Backend()
        self.sessions: list[GuiSession] = []
        self.current = GuiSession()
        self.provider: dict = {}
        self._dialog: ft.AlertDialog | None = None

        # Per-turn live-render state.
        self._cancel_event: threading.Event | None = None
        self._live_md: ft.Markdown | None = None
        self._buffer = ""
        self._buffer_lock = threading.Lock()
        self._last_flush = 0.0
        self._pending_tools: list[mb.ToolCard] = []

        # Search (Ctrl+F) state: (lowercased text, keyed wrapper container).
        self._search_blocks: list[tuple[str, ft.Container]] = []
        self._search_matches: list[int] = []
        self._search_pos = 0

        self.chat = ChatView(on_starter=self.send)
        self.chat.on_search_change = self._search_change
        self.chat.on_search_next = self._search_next
        self.chat.on_search_prev = self._search_prev
        self.sidebar = Sidebar(
            on_new=self.new_chat, on_select=self.select_session,
            on_delete=self.delete_session, on_pin=self.toggle_pin,
            on_settings=self.open_settings,
        )
        self.input = InputBar(
            on_send=self.send, on_cancel=self.cancel, on_attach=self._open_file_picker,
        )
        self.file_picker = ft.FilePicker()

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        """Load state, render, and connect the backend on a worker thread."""
        self.sessions = sessions.list_sessions()
        self.current = self.sessions[0] if self.sessions else GuiSession()
        self.provider = self._load_provider()
        self.sidebar.refresh(self.sessions, self.current.id)
        self.render_session()
        self.input.set_enabled(False)
        if not provider_config.is_configured():
            self._show_onboarding()
        else:
            self._connect_async()

    def _load_provider(self) -> dict:
        cfg = provider_config.load_provider_config() or provider_config.default_local()
        cfg = dict(cfg)
        cfg["api_key"] = credentials.load_cloud_api_key() or ""
        return cfg

    def _connect_async(self) -> None:
        self.chat.set_banner("Connecting to the system agent…", busy=True)

        def work() -> None:
            try:
                self.backend.connect(
                    self.provider.get("api_key", "") or "ollama",
                    self.provider.get("baseURL", ""),
                    self.provider.get("model", ""),
                )
            except Exception as exc:  # surfaces MCP handshake / import failures
                self.page.run_thread(self._on_connect_failed, str(exc))
                return
            self.page.run_thread(self._on_connected)
            self.backend.warm_up()

        threading.Thread(target=work, daemon=True, name="syscontrol-connect").start()

    def _on_connected(self) -> None:
        self.chat.set_banner(
            f"Ready · {self.backend.tool_count} tools · {self.provider.get('model', '')}",
            busy=False,
        )
        self.input.set_enabled(True)
        # Auto-hide the ready banner shortly after.
        self.chat.hide_banner()

    def _on_connect_failed(self, message: str) -> None:
        self.chat.set_banner(f"Could not start the agent: {message}", error=True)
        self.input.set_enabled(False)

    def shutdown(self) -> None:
        with contextlib.suppress(Exception):
            self.backend.close()

    # ── rendering ──────────────────────────────────────────────────────────────
    def _add_block(self, search_text: str, control: ft.Control) -> None:
        """Wrap a message control in a keyed container and register it for search."""
        key = f"m{len(self._search_blocks)}"
        wrapper = ft.Container(content=control, key=key, border_radius=8, padding=ft.Padding.all(2))
        self._search_blocks.append((search_text.lower(), wrapper))
        self.chat.add(wrapper)

    def render_session(self) -> None:
        """Rebuild the chat list from the current session's transcript (static)."""
        self.chat.clear()
        self._search_blocks = []
        msgs = list(self.current.messages)  # snapshot — worker may append concurrently
        if not msgs:
            self.chat.show_empty()
            self.chat.commit()
            return
        # Map tool_call_id -> tool name from assistant messages.
        names: dict[str, str] = {}
        for m in msgs:
            for call in m.get("tool_calls") or []:
                fn = (call.get("function") or {}).get("name")
                if call.get("id") and fn:
                    names[call["id"]] = fn
        for m in msgs:
            role, content = m.get("role"), m.get("content")
            if role == ROLE_USER and isinstance(content, str):
                self._add_block(content, mb.user_bubble(content))
            elif role == ROLE_ASSISTANT and isinstance(content, str) and content.strip():
                self._add_block(content, mb.assistant_block(mb.assistant_markdown(content)))
            elif role == ROLE_TOOL:
                name = names.get(m.get("tool_call_id", ""), "tool")
                card = mb.ToolCard(name)
                card.finish(content or "", _is_tool_error(content or ""), live=False)
                self._add_block(f"{name} {content or ''}", card.control)
        self.chat.commit()

    # ── sending a turn ──────────────────────────────────────────────────────────
    def send(self, text: str) -> None:
        if not self.backend.ready or self._cancel_event is not None:
            return
        first_message = not self.current.messages
        self.current.messages.append({"role": ROLE_USER, "content": text})
        self.current.derive_title()
        self.current.touch()
        if first_message:
            self.chat.clear()  # drop the empty-state
            if self.current not in self.sessions:
                self.sessions.insert(0, self.current)
        self.chat.add(mb.user_bubble(text))
        self.chat.commit()
        self.sidebar.refresh(self.sessions, self.current.id)

        self._cancel_event = threading.Event()
        self._live_md = None
        self._buffer = ""
        self._pending_tools = []
        self.input.set_streaming(True)

        callbacks = self._build_callbacks()
        threading.Thread(
            target=self._run_turn, args=(callbacks,), daemon=True, name="syscontrol-turn",
        ).start()

    def _run_turn(self, callbacks: TurnCallbacks) -> None:
        try:
            self.backend.run_turn(self.current.messages, callbacks)
        except Exception as exc:
            self.page.run_thread(self._append_error, f"Turn failed: {exc}")
        finally:
            self.page.run_thread(self._finalize_turn)

    def cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    # ── streaming callbacks (fire on the worker thread) ──────────────────────────
    def _build_callbacks(self) -> TurnCallbacks:
        page = self.page
        return TurnCallbacks(
            on_token=self._on_token,
            on_tool_started=lambda names: page.run_thread(self._on_tools_started, names),
            on_tool_finished=lambda name, result: page.run_thread(
                self._on_tool_finished, name, result,
            ),
            on_error=lambda cat, msg: page.run_thread(self._append_error, f"{cat}: {msg}"),
            cancel_event=self._cancel_event,
        )

    def _on_token(self, token: str) -> None:
        with self._buffer_lock:
            self._buffer += token
        now = time.monotonic()
        if now - self._last_flush >= _FLUSH_INTERVAL:
            self._last_flush = now
            self.page.run_thread(self._flush_live)

    def _flush_live(self) -> None:
        with self._buffer_lock:
            text = self._buffer
        if not text:
            return
        if self._live_md is None:
            self._live_md = mb.assistant_markdown(text)
            self.chat.add(mb.assistant_block(self._live_md))
            self.chat.commit()
        else:
            self._live_md.value = text
            self._live_md.update()

    def _on_tools_started(self, names: list[str]) -> None:
        self._flush_live()
        self._live_md = None
        with self._buffer_lock:
            self._buffer = ""
        for name in names:
            card = mb.ToolCard(name)
            self._pending_tools.append(card)
            self.chat.add(card.control)
        self.chat.commit()

    def _on_tool_finished(self, name: str, result: str) -> None:
        for card in self._pending_tools:
            if card.name == name and not card.done:
                card.finish(result, _is_tool_error(result))
                return

    def _append_error(self, message: str) -> None:
        self.chat.add(mb.error_bubble(message))
        self.chat.commit()

    def _finalize_turn(self) -> None:
        self._flush_live()
        self._cancel_event = None
        self._live_md = None
        self._pending_tools = []
        self.input.set_streaming(False)
        self.current.touch()
        with contextlib.suppress(Exception):
            sessions.save_session(self.current)
        self.sidebar.refresh(self.sessions, self.current.id)

    # ── session management ──────────────────────────────────────────────────────
    def new_chat(self) -> None:
        if self._cancel_event is not None:
            return
        self.current = GuiSession()
        self.render_session()
        self.sidebar.refresh(self.sessions, self.current.id)

    def select_session(self, session_id: str) -> None:
        if self._cancel_event is not None or session_id == self.current.id:
            return
        found = next((s for s in self.sessions if s.id == session_id), None)
        if found is None:
            return
        self.current = found
        self.render_session()
        self.sidebar.refresh(self.sessions, self.current.id)

    def delete_session(self, session_id: str) -> None:
        sessions.delete_session(session_id)
        self.sessions = [s for s in self.sessions if s.id != session_id]
        if self.current.id == session_id:
            self.current = self.sessions[0] if self.sessions else GuiSession()
            self.render_session()
        self.sidebar.refresh(self.sessions, self.current.id)

    def toggle_pin(self, session_id: str) -> None:
        target = next((s for s in self.sessions if s.id == session_id), None)
        if target is None:
            return
        target.pinned = not target.pinned
        with contextlib.suppress(Exception):
            sessions.save_session(target)
        self.sidebar.refresh(self.sessions, self.current.id)

    # ── settings / provider ─────────────────────────────────────────────────────
    def open_settings(self) -> None:
        self._dialog = build_settings_dialog(self)
        self.page.show_dialog(self._dialog)

    def close_dialog(self) -> None:
        if self._dialog is not None:
            self.page.pop_dialog()
            self._dialog = None

    def apply_provider(self, base_url: str, model: str, label: str, api_key: str) -> None:
        provider_config.save_provider_config(base_url, model, label)
        if api_key.strip():
            credentials.save_cloud_api_key(api_key.strip())
        self.provider = {"baseURL": base_url, "model": model, "label": label, "api_key": api_key}
        if self.backend.ready:
            self.backend.reconfigure(api_key or "ollama", base_url, model)
            self.chat.set_banner(f"Provider updated · {model}", busy=False)
            self.chat.hide_banner()
        else:
            self._connect_async()

    def test_connection(self, base_url: str, model: str, api_key: str) -> tuple[bool, str]:
        try:
            if provider_config.is_local(base_url):
                models = fetch_ollama_models(base_url)
                if not models:
                    return False, "No response from Ollama. Is it running?"
                hit = model in models
                return True, f"Connected · {len(models)} models" + ("" if hit else f" (‘{model}’ not pulled)")
            client = OpenAI(api_key=api_key or "ollama", base_url=base_url, timeout=10, max_retries=0)
            data = list(client.models.list().data)
            return True, f"Connected · {len(data)} models available"
        except Exception as exc:
            return False, f"Failed: {exc}"

    # ── file attachments ─────────────────────────────────────────────────────────
    def _open_file_picker(self) -> None:
        from flet_app.views.input_bar import ATTACH_EXTENSIONS
        try:
            files = self.file_picker.pick_files(
                dialog_title="Attach a file",
                allow_multiple=False,
                allowed_extensions=ATTACH_EXTENSIONS,
            )
        except Exception:
            files = None
        if files and getattr(files[0], "path", None):
            self.input.set_attachment(files[0].path, files[0].name)

    # ── command palette (Ctrl+K) ──────────────────────────────────────────────────
    def open_command_palette(self) -> None:
        from flet_app.views.command_palette import build_command_palette

        def pick(sid: str) -> None:
            self.close_dialog()
            self.select_session(sid)

        def new() -> None:
            self.close_dialog()
            self.new_chat()

        self._dialog = build_command_palette(self.sessions, pick, new)
        self.page.show_dialog(self._dialog)

    # ── in-chat search (Ctrl+F) ──────────────────────────────────────────────────
    def toggle_search(self) -> None:
        if self.chat.search_bar.visible:
            self.chat.hide_search()
            return
        self.render_session()  # refresh keyed, searchable blocks from the transcript
        self.chat.show_search()

    def _clear_highlights(self) -> None:
        for _text, wrapper in self._search_blocks:
            if wrapper.bgcolor is not None:
                wrapper.bgcolor = None
                wrapper.update()

    def _search_change(self, query: str) -> None:
        q = query.lower().strip()
        self._clear_highlights()
        self._search_matches = [i for i, (text, _w) in enumerate(self._search_blocks) if q and q in text]
        self._search_pos = 0
        if self._search_matches:
            self._highlight_current()
            self.chat.set_search_label(f"1/{len(self._search_matches)}")
        else:
            self.chat.set_search_label("0/0" if q else "")

    def _highlight_current(self) -> None:
        if not self._search_matches:
            return
        wrapper = self._search_blocks[self._search_matches[self._search_pos]][1]
        wrapper.bgcolor = ft.Colors.with_opacity(0.18, theme.ACCENT)
        wrapper.update()
        if wrapper.key:
            self.chat.scroll_to_key(str(wrapper.key))

    def _move_search(self, delta: int) -> None:
        if not self._search_matches:
            return
        current = self._search_blocks[self._search_matches[self._search_pos]][1]
        current.bgcolor = None
        current.update()
        self._search_pos = (self._search_pos + delta) % len(self._search_matches)
        self._highlight_current()
        self.chat.set_search_label(f"{self._search_pos + 1}/{len(self._search_matches)}")

    def _search_next(self) -> None:
        self._move_search(1)

    def _search_prev(self) -> None:
        self._move_search(-1)

    # ── global keyboard shortcuts ─────────────────────────────────────────────────
    def handle_key(self, e: ft.KeyboardEvent) -> None:
        key = (e.key or "").lower()
        mod = e.ctrl or e.meta
        if mod and key == "k":
            self.open_command_palette()
        elif mod and key == "f":
            self.toggle_search()
        elif mod and key == "n":
            self.new_chat()
        elif key == "escape":
            if self._dialog is not None:
                self.close_dialog()
            elif self.chat.search_bar.visible:
                self.chat.hide_search()

    # ── onboarding ────────────────────────────────────────────────────────────
    def _show_onboarding(self) -> None:
        from flet_app.views.onboarding import build_onboarding

        def done(base_url: str, model: str, label: str, api_key: str) -> None:
            self.close_dialog()
            self.apply_provider(base_url, model, label, api_key)

        self._dialog = build_onboarding(done)
        self.page.show_dialog(self._dialog)
