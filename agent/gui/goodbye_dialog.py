"""
SysControl GUI — Goodbye dialog.

Shown when the user types a farewell phrase, offering to save the chat
before clearing the session.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _btn_style_secondary(palette: dict[str, str]) -> str:
    """Return QSS for secondary (Cancel / Don't Save) buttons."""
    return f"""
        QPushButton {{
            background-color: {palette["input_bg"]};
            color: {palette["asst_bubble_text"]};
            border: 1px solid {palette["border"]};
            border-radius: 8px;
            padding: 7px 16px;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background-color: {palette["sidebar_item_hover"]};
        }}
    """


def _btn_style_primary(palette: dict[str, str]) -> str:
    """Return QSS for the primary (Save Chat) button."""
    return f"""
        QPushButton {{
            background-color: {palette["accent"]};
            color: #ffffff;
            border: none;
            border-radius: 8px;
            padding: 7px 16px;
            font-size: 13px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {palette["send_hover"]};
        }}
    """


class GoodbyeDialog(QDialog):
    """Modal dialog asking whether to save the current chat."""

    SAVE = 1
    DISCARD = 2
    # CANCEL = QDialog.Rejected (0)

    def __init__(
        self,
        message_count: int,
        palette: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        assert isinstance(message_count, int) and message_count >= 0, (
            f"GoodbyeDialog: message_count must be a non-negative int, got {message_count!r}"
        )
        super().__init__(parent)
        self.setWindowTitle("End Session")
        self.setFixedSize(380, 180)
        self.setModal(True)
        self._apply_stylesheet(palette)

        fg  = palette["asst_bubble_text"]
        dim = palette["placeholder"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        header = QLabel("Goodbye!")
        header.setFont(QFont(".AppleSystemUIFont", 18, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {fg}; background: transparent;")
        layout.addWidget(header)

        body = QLabel(f"Save {message_count} messages from this session?")
        body.setFont(QFont(".AppleSystemUIFont", 13))
        body.setStyleSheet(f"color: {dim}; background: transparent;")
        body.setWordWrap(True)
        layout.addWidget(body)

        layout.addStretch()
        self._setup_buttons(palette, layout)

    def _apply_stylesheet(self, palette: dict[str, str]) -> None:
        """Apply the dialog background stylesheet from the current palette."""
        bg = palette["window_bg"]
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg};
                border-radius: 12px;
            }}
        """)

    def _setup_buttons(
        self,
        palette: dict[str, str],
        layout: QVBoxLayout,
    ) -> None:
        """Create Cancel / Don't Save / Save Chat buttons and append to *layout*."""
        secondary = _btn_style_secondary(palette)
        primary   = _btn_style_primary(palette)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(secondary)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        discard_btn = QPushButton("Don't Save")
        discard_btn.setStyleSheet(secondary)
        discard_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        discard_btn.clicked.connect(lambda: self.done(self.DISCARD))

        save_btn = QPushButton("Save Chat")
        save_btn.setStyleSheet(primary)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(lambda: self.done(self.SAVE))
        save_btn.setDefault(True)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(discard_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)
