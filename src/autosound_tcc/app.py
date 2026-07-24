"""Application entry point.

Launches an empty Qt window ("hello Qt"). No REW/DSP data is wired in yet —
that is a later milestone. This module only proves the app starts and packages
as a normal Python console entry point on macOS and Windows.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from autosound_tcc.ui.tcc.main_window import MainWindow


def main() -> int:
    """Start the Qt event loop. Returns the process exit code."""
    app = QApplication(sys.argv)
    app.setApplicationName("autosound-tcc")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
