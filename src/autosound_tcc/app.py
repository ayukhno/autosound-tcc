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
from autosound_tcc.ui.tcc.project_gate_dialog import ensure_project_chosen


def main() -> int:
    """Start the Qt event loop. Returns the process exit code."""
    app = QApplication(sys.argv)
    app.setApplicationName("autosound-tcc")
    # Before the window, not inside it: `MainWindow.__init__` binds the MCP server, the session
    # registry and the file watchers to one folder, so there is no meaningful window to build
    # until that folder is known. Backing out of the gate exits rather than falling through to a
    # folder nobody picked -- which is what used to happen, silently, on every fresh install.
    if not ensure_project_chosen():
        return 0
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
