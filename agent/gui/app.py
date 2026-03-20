"""
SysControl GUI — Application entry point.

Sets up the QApplication, detects dark/light mode, shows the settings dialog
on first launch, and creates the main window.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QDialog

from agent.gui.main_window import MainWindow
from agent.gui.settings_dialog import SettingsDialog, load_saved_config, save_config
from agent.gui.theme import get_palette, is_dark_mode, load_stylesheet


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("SysControl")
    app.setOrganizationName("SysControl")

    # Detect and apply theme
    dark = is_dark_mode()
    palette = get_palette(dark)
    app.setStyleSheet(load_stylesheet(dark))

    # Load saved config or show settings dialog
    config = load_saved_config()
    if config is None:
        dialog = SettingsDialog(palette)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
        config = dialog.get_config()
        save_config(config)

    window = MainWindow(config, palette)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
