"""main.py — Application entry point.

Responsibilities limited to:
  1. Constructing the QApplication with platform-appropriate settings.
  2. Instantiating and showing the main window.
  3. Returning the event-loop exit code to the OS.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> int:
    # Enable HiDPI fractional scaling before QApplication is constructed
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("ECC Micromechanics Calculator")
    app.setOrganizationName("OpenECC")
    app.setStyle("Fusion")

    # NOTE: Inter/Segoe UI fall back to the system sans-serif on platforms
    # where neither is installed. Matplotlib uses its own font stack.
    font = QFont("Inter, Segoe UI, Arial", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
