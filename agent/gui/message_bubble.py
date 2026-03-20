"""
SysControl GUI — Message bubble widget.

User messages render as a clean blue bubble (right-aligned, dynamically sized to text).
Assistant messages show a typing indicator while streaming, then render as Markdown HTML
on finalize — raw markdown characters are never visible to the user.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

try:
    import markdown as md
    _HAS_MARKDOWN = True
except ImportError:
    _HAS_MARKDOWN = False


class MessageBubble(QFrame):
    """
    A single chat message.

    - User:      right-aligned blue bubble, sized to content width.
    - Assistant: typing indicator while streaming; full markdown HTML on finalize.
    """

    def __init__(
        self,
        role: str,          # "user" or "assistant"
        palette: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._role = role
        self._palette = palette
        self._raw_text = ""
        self._is_user = role == "user"

        self.setStyleSheet("background: transparent; border: none;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        fg = palette["user_bubble_text"] if self._is_user else palette["asst_bubble_text"]

        # ── Text browser ───────────────────────────────────────────────────
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.setFrameShape(QFrame.Shape.NoFrame)
        self._browser.setFont(QFont("-apple-system", 15))
        self._browser.document().contentsChanged.connect(self._adjust_height)

        if self._is_user:
            self._browser.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            self._browser.setStyleSheet(f"""
                QTextBrowser {{
                    background-color: {palette["user_bubble"]};
                    color: {palette["user_bubble_text"]};
                    border: none;
                    padding: 8px 13px;
                    border-radius: 16px;
                    selection-background-color: rgba(255,255,255,0.25);
                }}
            """)
        else:
            self._browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            self._browser.setStyleSheet(f"""
                QTextBrowser {{
                    background: transparent;
                    color: {palette["asst_bubble_text"]};
                    border: none;
                    padding: 2px 0px;
                    selection-background-color: {palette["accent"]};
                }}
            """)

        # ── Typing indicator (assistant only) ──────────────────────────────
        self._typing_label: QLabel | None = None
        if not self._is_user:
            self._typing_label = QLabel("●●●")
            self._typing_label.setFont(QFont("-apple-system", 16))
            self._typing_label.setStyleSheet(
                f"color: {palette['tool_text']}; background: transparent;"
            )
            # Animate opacity by cycling the label text
            self._dot_state = 0
            self._dot_timer = QTimer(self)
            self._dot_timer.setInterval(500)
            self._dot_timer.timeout.connect(self._animate_dots)
            self._dot_timer.start()
            self._browser.hide()  # hidden until finalize

        # ── Layout ─────────────────────────────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        if self._is_user:
            row.addStretch(1)
            row.addWidget(self._browser)
        else:
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(4)
            if self._typing_label:
                col.addWidget(self._typing_label)
            col.addWidget(self._browser)
            row.addLayout(col)

        outer.addLayout(row)

    # ── Public API ─────────────────────────────────────────────────────────

    def append_text(self, text: str) -> None:
        """Accumulate streaming text — kept in _raw_text, not shown yet (typing indicator stays)."""
        self._raw_text += text
        # For user messages this path isn't called (set_text is used instead).
        # For assistant messages we intentionally do NOT update the browser here.

    def set_text(self, text: str) -> None:
        """Set complete text for a user message bubble."""
        self._raw_text = text
        self._browser.setPlainText(text)
        self._adjust_width()   # size bubble to text content

    def finalize(self) -> None:
        """Hide typing indicator; render accumulated text as Markdown HTML."""
        if self._typing_label:
            self._dot_timer.stop()
            self._typing_label.hide()
        self._browser.show()

        if not self._raw_text.strip():
            return

        if _HAS_MARKDOWN and self._role == "assistant":
            html = md.markdown(
                self._raw_text,
                extensions=["fenced_code", "tables", "nl2br"],
            )
            self._browser.setHtml(self._wrap_html(html))
        else:
            self._browser.setPlainText(self._raw_text)

    def raw_text(self) -> str:
        return self._raw_text

    # ── Internal ───────────────────────────────────────────────────────────

    def _animate_dots(self) -> None:
        """Cycle the typing indicator between ●●● / ●●○ / ●○○."""
        if self._typing_label is None or not self._typing_label.isVisible():
            return
        self._dot_state = (self._dot_state + 1) % 3
        dots = ["●●●", "●●○", "●○○"]
        self._typing_label.setText(dots[self._dot_state])

    def _adjust_width(self) -> None:
        """For user bubbles: shrink to natural text width, capped at 75% of parent."""
        if not self._is_user:
            return
        doc = self._browser.document()
        doc.setTextWidth(-1)          # disable wrapping to measure natural width
        ideal_w = doc.idealWidth()
        parent = self.parentWidget()
        max_w = min(620, int(parent.width() * 0.75)) if parent else 620
        target_w = min(int(ideal_w) + 28, max_w)  # 28 = 14px padding × 2
        self._browser.setFixedWidth(max(target_w, 48))

    def _adjust_height(self) -> None:
        """Resize browser to fit its document content."""
        if self._is_user:
            self._adjust_width()
        doc_height = self._browser.document().size().height()
        self._browser.setMinimumHeight(int(doc_height) + 6)

    def _wrap_html(self, body: str) -> str:
        """Wrap markdown-generated HTML with inline CSS styled for the current palette."""
        fg = self._palette["asst_bubble_text"]
        code_bg = self._palette.get("code_bg", "#0a0a0a")
        accent = self._palette["accent"]
        border = self._palette["border"]
        return f"""
        <style>
            body {{
                color: {fg};
                font-family: -apple-system, 'SF Pro Text', system-ui, sans-serif;
                font-size: 15px;
                line-height: 1.7;
                margin: 0; padding: 0;
            }}
            p {{ margin: 6px 0; }}
            strong {{ font-weight: 650; }}
            em {{ font-style: italic; }}
            code {{
                background: {code_bg};
                padding: 2px 6px;
                border-radius: 5px;
                font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
                font-size: 13px;
            }}
            pre {{
                background: {code_bg};
                padding: 14px 16px;
                border-radius: 8px;
                margin: 8px 0;
                overflow-x: auto;
            }}
            pre code {{
                background: transparent;
                padding: 0;
                border-radius: 0;
                font-size: 13px;
            }}
            a {{ color: {accent}; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            table {{ border-collapse: collapse; margin: 10px 0; width: 100%; }}
            th, td {{ border: 1px solid {border}; padding: 7px 12px; text-align: left; }}
            th {{ font-weight: 600; }}
            h1 {{ font-size: 20px; font-weight: 700; margin: 14px 0 6px; }}
            h2 {{ font-size: 17px; font-weight: 650; margin: 12px 0 5px; }}
            h3 {{ font-size: 15px; font-weight: 650; margin: 10px 0 4px; }}
            ul, ol {{ margin: 6px 0; padding-left: 24px; }}
            li {{ margin: 3px 0; }}
            blockquote {{
                margin: 8px 0 8px 4px;
                padding-left: 12px;
                border-left: 3px solid {accent};
                opacity: 0.8;
            }}
            hr {{ border: none; border-top: 1px solid {border}; margin: 12px 0; }}
        </style>
        {body}
        """

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._is_user:
            self._adjust_width()
