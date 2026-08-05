"""Application entry point.

Launches the TCC main window (see ui/tcc/main_window.py) -- the DSP tree, detail pane, AI
dialog, and plan/measurement panels are real; see docs/TCC-TZ.md and the plan file for what's
wired to real data vs. still mock. Packages as a normal Python console entry point on macOS and
Windows.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from autosound_tcc.ui.tcc.main_window import MainWindow
from autosound_tcc.ui.tcc.project_gate_dialog import ensure_project_chosen


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="autosound-tcc", description=__doc__)
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="Work on this folder, `.` for the current one. Outranks the remembered choice.",
    )
    parser.add_argument(
        "--choose-project",
        action="store_true",
        help="Ask which project to open even though one is remembered.",
    )
    known, _ = parser.parse_known_args(argv[1:])  # Qt takes its own flags off the same line
    return known


def main() -> int:
    """Start the Qt event loop. Returns the process exit code."""
    args = _parse(sys.argv)
    if args.project_dir is not None:
        # Into the environment rather than a private variable: `AUTOSOUND_PROJECT_DIR` is the
        # skill's own (SCR-011), so every subprocess TCC starts -- the reviewer, the recorder, an
        # agent CLI -- lands on the same folder without being told separately.
        os.environ["AUTOSOUND_PROJECT_DIR"] = str(args.project_dir.expanduser().resolve())
    app = QApplication(sys.argv)
    app.setApplicationName("autosound-tcc")
    # Before the window, not inside it: `MainWindow.__init__` binds the MCP server, the session
    # registry and the file watchers to one folder, so there is no meaningful window to build
    # until that folder is known. Backing out of the gate exits rather than falling through to a
    # folder nobody picked -- which is what used to happen, silently, on every fresh install.
    if not ensure_project_chosen(force=args.choose_project):
        return 0
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
