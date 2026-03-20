"""
SysControl GUI — Settings dialog for provider/model selection.

Replaces the CLI's interactive select_provider() prompt with a Qt dialog.
Detects locally installed Ollama models and persists the user's choice.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from agent.core import (
    CLOUD_BASE_URL,
    CLOUD_MODEL,
    LOCAL_API_KEY,
    LOCAL_BASE_URL,
    LOCAL_MODEL,
)
from agent.gui.worker import ProviderConfig

# ── Persistence ───────────────────────────────────────────────────────────────

CONFIG_DIR = Path.home() / ".syscontrol"
CONFIG_FILE = CONFIG_DIR / "gui_config.json"


def load_saved_config() -> ProviderConfig | None:
    """Load previously saved provider config, or None if not found."""
    if not CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return ProviderConfig(
            api_key=data["api_key"],
            base_url=data["base_url"],
            model=data["model"],
            label=data["label"],
        )
    except Exception:
        return None


def save_config(config: ProviderConfig) -> None:
    """Persist provider config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps({
            "api_key": config.api_key,
            "base_url": config.base_url,
            "model": config.model,
            "label": config.label,
        }, indent=2),
        encoding="utf-8",
    )


# ── Ollama detection (same as cli.py:_fetch_ollama_models) ────────────────────

def fetch_ollama_models(base_url: str = "http://localhost:11434") -> list[str]:
    """Return sorted list of locally installed Ollama model names."""
    try:
        req = urllib.request.Request(
            f"{base_url}/api/tags",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read().decode())
        return sorted(m["name"] for m in data.get("models", []))
    except Exception:
        return []


# ── Dialog ────────────────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    """Provider and model selection dialog."""

    def __init__(self, palette: dict[str, str], parent: QWidget | None = None):
        super().__init__(parent)
        self._palette = palette
        self.setWindowTitle("SysControl — Settings")
        self.setMinimumWidth(440)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {palette["window_bg"]};
            }}
            QLabel {{
                color: {palette["asst_bubble_text"]};
            }}
            QGroupBox {{
                color: {palette["asst_bubble_text"]};
                border: 1px solid {palette["border"]};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 16px;
                font-weight: 600;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
            QRadioButton {{
                color: {palette["asst_bubble_text"]};
                spacing: 6px;
            }}
            QLineEdit, QComboBox {{
                background-color: {palette["input_bg"]};
                color: {palette["input_text"]};
                border: 1px solid {palette["input_border"]};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 1px solid {palette["accent"]};
            }}
            QPushButton {{
                background-color: {palette["send_bg"]};
                color: {palette["send_text"]};
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {palette["send_hover"]};
            }}
            QPushButton#secondary {{
                background-color: {palette["input_bg"]};
                color: {palette["asst_bubble_text"]};
                border: 1px solid {palette["border"]};
            }}
            QPushButton#secondary:hover {{
                background-color: {palette["tool_indicator"]};
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        # Title
        title = QLabel("Configure Provider")
        title.setFont(QFont("SF Pro Display", 18, QFont.Weight.Bold))
        main_layout.addWidget(title)

        # ── Provider radio buttons ─────────────────────────────────────────
        self._radio_local = QRadioButton("Local (Ollama)")
        self._radio_cloud = QRadioButton("Cloud (Ollama Cloud)")
        self._radio_local.setChecked(True)

        self._radio_group = QButtonGroup(self)
        self._radio_group.addButton(self._radio_local, 0)
        self._radio_group.addButton(self._radio_cloud, 1)
        self._radio_group.idToggled.connect(self._on_provider_changed)

        radio_row = QHBoxLayout()
        radio_row.addWidget(self._radio_local)
        radio_row.addWidget(self._radio_cloud)
        radio_row.addStretch()
        main_layout.addLayout(radio_row)

        # ── Local panel ────────────────────────────────────────────────────
        self._local_group = QGroupBox("Local Settings")
        local_layout = QVBoxLayout(self._local_group)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self._model_combo = QComboBox()
        self._model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        model_row.addWidget(self._model_combo)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("secondary")
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.clicked.connect(self._refresh_models)
        model_row.addWidget(self._refresh_btn)
        local_layout.addLayout(model_row)

        main_layout.addWidget(self._local_group)

        # ── Cloud panel ────────────────────────────────────────────────────
        self._cloud_group = QGroupBox("Cloud Settings")
        cloud_layout = QVBoxLayout(self._cloud_group)

        cloud_layout.addWidget(QLabel("API Key:"))
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("Enter your Ollama Cloud API key")
        cloud_layout.addWidget(self._api_key_edit)

        cloud_layout.addWidget(QLabel("Model (optional override):"))
        self._cloud_model_edit = QLineEdit()
        self._cloud_model_edit.setPlaceholderText(CLOUD_MODEL)
        cloud_layout.addWidget(self._cloud_model_edit)

        main_layout.addWidget(self._cloud_group)

        # ── Buttons ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton("Connect")
        ok_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(ok_btn)

        main_layout.addLayout(btn_row)

        # Initial state
        self._on_provider_changed(0, True)
        self._refresh_models()

    # ── Public API ─────────────────────────────────────────────────────────

    def get_config(self) -> ProviderConfig:
        """Return the configured provider settings."""
        if self._radio_local.isChecked():
            model = self._model_combo.currentText() or LOCAL_MODEL
            return ProviderConfig(
                api_key=LOCAL_API_KEY,
                base_url=LOCAL_BASE_URL,
                model=model,
                label="\u2699  Local (Ollama)",
            )
        else:
            api_key = self._api_key_edit.text().strip()
            model = self._cloud_model_edit.text().strip() or CLOUD_MODEL
            return ProviderConfig(
                api_key=api_key,
                base_url=CLOUD_BASE_URL,
                model=model,
                label="\u2601  Cloud",
            )

    def load_from_config(self, config: ProviderConfig) -> None:
        """Pre-fill the dialog from a saved config."""
        if config.base_url == LOCAL_BASE_URL:
            self._radio_local.setChecked(True)
            # Try to select the saved model in the combo
            idx = self._model_combo.findText(config.model)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)
        else:
            self._radio_cloud.setChecked(True)
            self._api_key_edit.setText(config.api_key)
            if config.model != CLOUD_MODEL:
                self._cloud_model_edit.setText(config.model)

    # ── Internal ───────────────────────────────────────────────────────────

    def _on_provider_changed(self, button_id: int, checked: bool) -> None:
        if not checked:
            return
        is_local = button_id == 0
        self._local_group.setVisible(is_local)
        self._cloud_group.setVisible(not is_local)

    def _refresh_models(self) -> None:
        self._model_combo.clear()
        models = fetch_ollama_models()
        if models:
            self._model_combo.addItems(models)
        else:
            self._model_combo.addItem(LOCAL_MODEL)

    def _on_accept(self) -> None:
        if self._radio_cloud.isChecked():
            if not self._api_key_edit.text().strip():
                QMessageBox.warning(self, "Missing API Key", "Please enter your Ollama Cloud API key.")
                return
        self.accept()
