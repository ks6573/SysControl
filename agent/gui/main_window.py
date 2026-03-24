"""
SysControl GUI — Main window.

Assembles the chat widget, input widget, and toolbar, and wires all
signals between the AgentWorker thread and the UI components.
"""

from __future__ import annotations

import atexit
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt

from PySide6.QtGui import QAction, QCloseEvent, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from agent.gui.chat_history import EXIT_PHRASES, generate_title, save_chat
from agent.gui.chat_widget import ChatWidget
from agent.gui.input_widget import InputWidget
from agent.gui.settings_dialog import SettingsDialog, save_config
from agent.gui.sidebar import ChatHistorySidebar, ChatViewerDialog
from agent.gui.worker import AgentWorker, ProviderConfig


_SIDEBAR_WIDTH = 380  # px — expanded sidebar panel width


class MainWindow(QMainWindow):
    """Main application window — chat interface with toolbar and status bar."""

    def __init__(self, config: ProviderConfig, palette: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._palette = palette
        self._worker: AgentWorker | None = None
        self._session_saved = False

        self.setWindowTitle("SysControl")
        self.setMinimumSize(600, 500)
        self.resize(800, 650)

        self._setup_menu_bar()
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_status_bar()

        # ── Wire input ─────────────────────────────────────────────────────
        self._input.message_submitted.connect(self._on_user_submit)

        # Safety net: clean up MCP subprocesses on exit (registered once)
        atexit.register(self._cleanup)

        # ── Start worker ───────────────────────────────────────────────────
        self._start_worker(config)

    def _setup_menu_bar(self) -> None:
        """Build the Edit menu with standard text-editing shortcuts."""
        menu_bar = self.menuBar()
        edit_menu = menu_bar.addMenu("Edit")

        for label, shortcut, method in (
            ("Undo",       QKeySequence.StandardKey.Undo,      "undo"),
            ("Redo",       QKeySequence.StandardKey.Redo,      "redo"),
            (None, None, None),  # separator
            ("Cut",        QKeySequence.StandardKey.Cut,       "cut"),
            ("Copy",       QKeySequence.StandardKey.Copy,      "copy"),
            ("Paste",      QKeySequence.StandardKey.Paste,     "paste"),
            (None, None, None),  # separator
            ("Select All", QKeySequence.StandardKey.SelectAll, "selectAll"),
        ):
            if label is None:
                edit_menu.addSeparator()
                continue
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda _checked=False, m=method: self._forward_to_focus(m))
            edit_menu.addAction(action)

    def _setup_toolbar(self) -> None:
        """Build the top toolbar with history, model label, new-chat, and settings buttons."""
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setFixedHeight(44)
        self.addToolBar(toolbar)

        self._history_btn = QToolButton()
        self._history_btn.setText("\u2630")  # ☰ hamburger menu icon
        self._history_btn.setToolTip("Chat History")
        self._history_btn.setCheckable(True)
        self._history_btn.toggled.connect(self._on_toggle_sidebar)
        toolbar.addWidget(self._history_btn)

        self._model_label = QLabel("SysControl")
        self._model_label.setFont(QFont(".AppleSystemUIFont", 13, QFont.Weight.DemiBold))
        toolbar.addWidget(self._model_label)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        new_chat_btn = QToolButton()
        new_chat_btn.setText("+ New")
        new_chat_btn.clicked.connect(self._on_new_chat)
        toolbar.addWidget(new_chat_btn)

        settings_btn = QPushButton("\u2699")
        settings_btn.setFont(QFont(".AppleSystemUIFont", 28))
        settings_btn.setFixedSize(44, 44)
        settings_btn.setStyleSheet(
            "QPushButton { padding: 0; margin: 0; border: none; "
            "text-align: center; }"
        )
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(self._on_settings)
        toolbar.addWidget(settings_btn)

    def _setup_central_widget(self) -> None:
        """Build the central area: sidebar + chat + input."""
        central = QWidget()
        self.setCentralWidget(central)
        h_layout = QHBoxLayout(central)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(0)

        # Sidebar (hidden by default)
        self._sidebar = ChatHistorySidebar(self._palette, parent=central)
        self._sidebar.setMaximumWidth(0)
        self._sidebar.chat_selected.connect(self._on_chat_selected)
        self._sidebar.closed.connect(lambda: self._history_btn.setChecked(False))
        h_layout.addWidget(self._sidebar)

        # Right panel: chat + input
        right_panel = QWidget()
        v_layout = QVBoxLayout(right_panel)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(0)

        self._chat = ChatWidget(self._palette, parent=right_panel)
        v_layout.addWidget(self._chat, 1)

        self._input = InputWidget(self._palette, parent=right_panel)
        v_layout.addWidget(self._input, 0)

        h_layout.addWidget(right_panel, 1)

        # Keyboard shortcut: Ctrl+H to toggle sidebar
        shortcut = QShortcut(QKeySequence("Ctrl+H"), self)
        shortcut.activated.connect(self._history_btn.toggle)

    def _setup_status_bar(self) -> None:
        """Build the bottom status bar."""
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status_label = QLabel("Connecting\u2026")
        self._status.addPermanentWidget(self._status_label)

    # ── Worker lifecycle ───────────────────────────────────────────────────

    def _start_worker(self, config: ProviderConfig) -> None:
        """Create and start the agent worker thread."""
        if self._worker is not None:
            self._worker.shutdown()

        self._worker = AgentWorker(config, parent=self)
        self._worker.ready.connect(self._on_worker_ready)
        self._worker.token_received.connect(self._on_token)
        self._worker.tool_started.connect(self._on_tool_started)
        self._worker.tool_finished.connect(self._on_tool_finished)
        self._worker.turn_finished.connect(self._on_turn_finished)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    def _cleanup(self) -> None:
        if self._worker is not None:
            self._worker.shutdown()
            self._worker = None

    # ── Slots: user actions ────────────────────────────────────────────────

    def _on_user_submit(self, text: str) -> None:
        if text.strip().lower() in EXIT_PHRASES:
            self._handle_goodbye()
            return
        self._chat.add_user_message(text)
        self._chat.begin_assistant_message()
        self._input.set_enabled(False)
        self._worker.submit_message(text)

    def _handle_goodbye(self) -> None:
        """Auto-save session and start a new chat."""
        self._auto_save()
        self._on_new_chat()

    def _on_new_chat(self) -> None:
        self._auto_save()
        self._chat.clear_chat()
        if self._worker:
            self._worker.clear_session()
        self._session_saved = False

    def _auto_save(self, title_timeout: float = 10.0) -> None:
        """Save the current session if it has meaningful content.

        Args:
            title_timeout: Timeout in seconds for the LLM title-generation
                call. Use a short value (e.g. 3s) during closeEvent.
        """
        if self._session_saved or not self._worker:
            return
        messages = self._worker.get_messages()
        has_user = any(m.get("role") == "user" and m.get("content") for m in messages)
        has_asst = any(m.get("role") == "assistant" and m.get("content") for m in messages)
        if not (has_user and has_asst):
            return
        title = generate_title(
            messages,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            model=self._config.model,
            timeout=title_timeout,
        )
        path = save_chat(messages, title=title)
        if path:
            self._status_label.setText(f"Chat saved to {path.name}")
            self._sidebar.refresh()
        self._session_saved = True

    def _on_settings(self) -> None:
        dialog = SettingsDialog(self._palette, parent=self)
        dialog.load_from_config(self._config)
        if dialog.exec():
            self._auto_save()
            new_config = dialog.get_config()
            save_config(new_config)
            self._config = new_config
            self._chat.clear_chat()
            if self._worker:
                self._worker.clear_session()
            self._session_saved = False
            self._status_label.setText("Reconnecting\u2026")
            self._start_worker(new_config)

    # ── Slots: worker signals ──────────────────────────────────────────────

    def _on_worker_ready(self, tool_count: int, label: str, model: str) -> None:
        self._model_label.setText(model)
        self._status_label.setText(f"{tool_count} tools \u00b7 {label}")
        self._input.set_enabled(True)

    def _on_token(self, text: str) -> None:
        self._chat.append_to_current(text)

    def _on_tool_started(self, names: list[str]) -> None:
        self._chat.show_tool_indicator(names)

    def _on_tool_finished(self, name: str, result: str) -> None:
        self._chat.hide_tool_indicator()

    def _on_turn_finished(self, elapsed: float) -> None:
        self._chat.finalize_current(elapsed)
        self._input.set_enabled(True)

    def _on_error(self, category: str, message: str) -> None:
        self._chat.show_error(category, message)
        self._input.set_enabled(True)

    # ── Sidebar ────────────────────────────────────────────────────────────

    def _on_toggle_sidebar(self, checked: bool) -> None:
        if checked:
            self._sidebar.refresh()
        anim = QPropertyAnimation(self._sidebar, b"maximumWidth")
        anim.setDuration(200)
        anim.setStartValue(self._sidebar.maximumWidth())
        anim.setEndValue(_SIDEBAR_WIDTH if checked else 0)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._sidebar_anim = anim  # prevent GC
        anim.start()

    def _on_chat_selected(self, path: Path) -> None:
        viewer = ChatViewerDialog(path, self._palette, parent=self)
        viewer.exec()

    # ── Edit menu helpers ──────────────────────────────────────────────

    @staticmethod
    def _forward_to_focus(method: str) -> None:
        """Forward an edit action (copy, paste, …) to the currently focused widget."""
        from PySide6.QtWidgets import QApplication

        widget = QApplication.focusWidget()
        if widget is not None and hasattr(widget, method):
            getattr(widget, method)()

    # ── Window lifecycle ───────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:
        self._auto_save(title_timeout=3.0)  # quick LLM title attempt on close
        self._cleanup()
        super().closeEvent(event)
