"""Application entry point.

Launches the TCC main window (see ui/tcc/main_window.py) -- the DSP tree, detail pane, AI
dialog, and plan/measurement panels are real; see docs/TCC-TZ.md and the plan file for what's
wired to real data vs. still mock. Packages as a normal Python console entry point on macOS and
Windows.
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
