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
        super().__init__(parent)
        self.setWindowTitle("End Session")
        self.setFixedSize(380, 180)
        self.setModal(True)

        bg = palette["window_bg"]
        fg = palette["asst_bubble_text"]
        dim = palette["placeholder"]
        accent = palette["accent"]
        border = palette["border"]
        input_bg = palette["input_bg"]

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg};
                border-radius: 12px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        # Header
        header = QLabel("Goodbye!")
        header.setFont(QFont("-apple-system", 18, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {fg}; background: transparent;")
        layout.addWidget(header)

        # Body
        body = QLabel(f"Save {message_count} messages from this session?")
        body.setFont(QFont("-apple-system", 13))
        body.setStyleSheet(f"color: {dim}; background: transparent;")
        body.setWordWrap(True)
        layout.addWidget(body)

        layout.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_style_secondary = f"""
            QPushButton {{
                background-color: {input_bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 7px 16px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {palette["sidebar_item_hover"]};
            }}
        """
        btn_style_primary = f"""
            QPushButton {{
                background-color: {accent};
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

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(btn_style_secondary)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        discard_btn = QPushButton("Don't Save")
        discard_btn.setStyleSheet(btn_style_secondary)
        discard_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        discard_btn.clicked.connect(lambda: self.done(self.DISCARD))

        save_btn = QPushButton("Save Chat")
        save_btn.setStyleSheet(btn_style_primary)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(lambda: self.done(self.SAVE))
        save_btn.setDefault(True)

        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(discard_btn)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)
