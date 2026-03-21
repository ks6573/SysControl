"""
SysControl GUI — Chat history sidebar and viewer.

Provides a collapsible "Other Chats" panel listing saved .md chat files,
with drag-and-drop import support and a read-only viewer dialog.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    import markdown as md
    _HAS_MARKDOWN = True
except ImportError:
    _HAS_MARKDOWN = False

from agent.gui.chat_history import import_chat, list_saved_chats, read_chat


# ── Single chat item row ─────────────────────────────────────────────────────


class _ChatItem(QFrame):
    """A clickable row in the sidebar representing one saved chat."""

    clicked = Signal(Path)

    def __init__(
        self,
        chat_info: dict,
        palette: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._path: Path = chat_info["path"]
        self._palette = palette

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(52)
        self._set_bg(palette["sidebar_bg"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(2)

        title = QLabel(chat_info["title"])
        title.setFont(QFont("-apple-system", 13, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {palette['sidebar_title']}; background: transparent;")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout.addWidget(title)

        date = QLabel(chat_info["date_str"])
        date.setFont(QFont("-apple-system", 11))
        date.setStyleSheet(f"color: {palette['sidebar_subtitle']}; background: transparent;")
        date.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout.addWidget(date)

    def _set_bg(self, color: str) -> None:
        self.setStyleSheet(f"""
            _ChatItem {{
                background-color: {color};
                border: none;
                border-radius: 8px;
            }}
        """)

    def enterEvent(self, event) -> None:
        self._set_bg(self._palette["sidebar_item_hover"])
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_bg(self._palette["sidebar_bg"])
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._path)
        super().mousePressEvent(event)


# ── Sidebar panel ─────────────────────────────────────────────────────────────


class ChatHistorySidebar(QFrame):
    """Collapsible sidebar showing saved chat history files."""

    chat_selected = Signal(Path)

    def __init__(
        self,
        palette: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self.setAcceptDrops(True)

        self.setStyleSheet(f"""
            ChatHistorySidebar {{
                background-color: {palette["sidebar_bg"]};
                border-right: 1px solid {palette["border"]};
            }}
        """)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(44)
        header.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 8, 0)

        title = QLabel("Other Chats")
        title.setFont(QFont("-apple-system", 13, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {palette['sidebar_title']}; background: transparent;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        close_btn = QToolButton()
        close_btn.setText("\u2715")  # ✕
        close_btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                color: {palette["sidebar_subtitle"]};
                border: none;
                font-size: 14px;
                padding: 4px 8px;
                border-radius: 4px;
            }}
            QToolButton:hover {{
                background-color: {palette["sidebar_item_hover"]};
                color: {palette["sidebar_title"]};
            }}
        """)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self._on_close)
        header_layout.addWidget(close_btn)

        root.addWidget(header)

        # ── Scroll area for chat items ────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"background: {palette['sidebar_bg']}; border: none;")

        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(8, 4, 8, 8)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()

        self._scroll.setWidget(self._list_container)
        root.addWidget(self._scroll, 1)

        # ── Empty state ───────────────────────────────────────────────────
        self._empty_label = QLabel("No past chats.\nSave something and\nI'll pick up from there!")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setFont(QFont("-apple-system", 12))
        self._empty_label.setStyleSheet(f"color: {palette['sidebar_empty']}; background: transparent;")
        self._empty_label.setWordWrap(True)
        self._list_layout.insertWidget(0, self._empty_label)

    # ── Public API ────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload the chat list from disk."""
        # Clear existing items (keep stretch at the end)
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        chats = list_saved_chats()

        if not chats:
            self._empty_label = QLabel("No past chats.\nSave something and\nI'll pick up from there!")
            self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._empty_label.setFont(QFont("-apple-system", 12))
            self._empty_label.setStyleSheet(
                f"color: {self._palette['sidebar_empty']}; background: transparent;"
            )
            self._empty_label.setWordWrap(True)
            self._list_layout.insertWidget(0, self._empty_label)
            return

        for i, chat_info in enumerate(chats):
            chat_item = _ChatItem(chat_info, self._palette, parent=self._list_container)
            chat_item.clicked.connect(self.chat_selected.emit)
            self._list_layout.insertWidget(i, chat_item)

    # ── Close button ──────────────────────────────────────────────────────

    closed = Signal()

    def _on_close(self) -> None:
        self.closed.emit()

    # ── Drag and drop ─────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().endswith(".md"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        imported = 0
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local.endswith(".md"):
                result = import_chat(Path(local))
                if result:
                    imported += 1
        if imported:
            self.refresh()
        event.acceptProposedAction()


# ── Chat viewer dialog ────────────────────────────────────────────────────────


class ChatViewerDialog(QDialog):
    """Read-only dialog for viewing a saved chat."""

    def __init__(
        self,
        chat_path: Path,
        palette: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(chat_path.stem.replace("_", " "))
        self.resize(600, 500)
        self.setModal(True)

        bg = palette["window_bg"]
        fg = palette["asst_bubble_text"]
        accent = palette["accent"]
        border = palette["border"]
        code_bg = palette.get("code_bg", "#222020")

        self.setStyleSheet(f"QDialog {{ background-color: {bg}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Content browser ───────────────────────────────────────────────
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setFrameShape(QFrame.Shape.NoFrame)
        browser.setFont(QFont("-apple-system", 14))
        browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {bg};
                color: {fg};
                border: none;
                padding: 20px 32px;
            }}
        """)

        content = read_chat(chat_path)
        if _HAS_MARKDOWN:
            html = md.markdown(content, extensions=["fenced_code", "tables", "nl2br"])
            styled = f"""
            <style>
                body {{
                    color: {fg};
                    font-family: -apple-system, 'SF Pro Text', system-ui, sans-serif;
                    font-size: 14px; line-height: 1.6;
                    margin: 0; padding: 0;
                }}
                h1 {{ font-size: 18px; font-weight: 700; margin: 0 0 8px; }}
                h3 {{ font-size: 15px; font-weight: 650; margin: 16px 0 4px; color: {accent}; }}
                p {{ margin: 6px 0; }}
                code {{
                    background: {code_bg}; padding: 2px 6px;
                    border-radius: 5px; font-family: 'SF Mono', monospace; font-size: 13px;
                }}
                pre {{
                    background: {code_bg}; padding: 14px 16px;
                    border-radius: 8px; margin: 8px 0; overflow-x: auto;
                }}
                pre code {{ background: transparent; padding: 0; }}
                hr {{ border: none; border-top: 1px solid {border}; margin: 12px 0; }}
                strong {{ font-weight: 650; }}
                em {{ font-style: italic; color: {palette["sidebar_subtitle"]}; }}
                a {{ color: {accent}; text-decoration: none; }}
            </style>
            {html}
            """
            browser.setHtml(styled)
        else:
            browser.setPlainText(content)

        layout.addWidget(browser, 1)

        # ── Close button row ──────────────────────────────────────────────
        btn_row = QWidget()
        btn_row.setStyleSheet(f"background-color: {bg};")
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(16, 8, 16, 12)

        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {palette["input_bg"]};
                color: {fg};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 7px 16px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {palette["sidebar_item_hover"]};
            }}
        """)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addWidget(btn_row)
