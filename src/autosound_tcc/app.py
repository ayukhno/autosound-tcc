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

from autosound_tcc.core import app_log, config

#: What to say when the window is asked for and the toolkit that draws it is not installed.
#: `autosound-tcc` ships in two sizes — the CLI half needs `claude-agent-sdk` and nothing else,
#: the window needs PySide6 + pyqtgraph, which is hundreds of megabytes. A person who installed
#: the light one and then typed the GUI command must get a sentence they can act on, not a
#: traceback about a module they have never heard of.
#: The git URL, not a bare package name. `autosound-tcc` is not on PyPI, so the obvious
#: `uv tool install 'autosound-tcc[gui]'` fails with "no such package" — a message that sends its
#: reader looking for a typo in their own command (caught by running it, 2026-08-12). Whatever is
#: printed here has to be a line somebody can paste.
_NO_GUI = """\
autosound-tcc: the graphical window is not installed.

    uv tool install --upgrade \
      'autosound-tcc[gui] @ git+https://github.com/ayukhno/autosound-tcc'

(The CLI half — `tuning-session`, `dsp-profile-interview` — works without it.)
Missing: {error}"""


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
    # First, before anything can fail: an exception raised from here on lands in a file instead of
    # in the terminal TCC was launched from. On macOS a line arriving there while the window is a
    # full-screen space switches the user out of the app mid-tune (see core/app_log.py).
    app_log.setup()
    # Imported HERE, not at module scope. A light install has no PySide6, and an entry point that
    # cannot even be imported gives its user a traceback where a sentence belongs.
    try:
        from PySide6.QtWidgets import QApplication

        from autosound_tcc.ui.tcc.main_window import MainWindow
        from autosound_tcc.ui.tcc.project_gate_dialog import ensure_project_chosen
    except ImportError as exc:
        print(_NO_GUI.format(error=exc), file=sys.stderr)
        return 2
    args = _parse(sys.argv)
    if args.project_dir is not None:
        # Into the environment rather than a private variable: `AUTOSOUND_PROJECT_DIR` is the
        # skill's own (SCR-011), so every subprocess TCC starts -- the reviewer, the recorder, an
        # agent CLI -- lands on the same folder without being told separately.
        chosen = str(args.project_dir.expanduser().resolve())
        os.environ["AUTOSOUND_PROJECT_DIR"] = chosen
        # Remembered as well, not only exported. Otherwise the flag and the saved choice are two
        # sources of truth that agree until they do not: TCC restarts itself on a project switch,
        # the restart carries no flag, and the window comes back on the *previous* folder while
        # the person who typed the flag believes they are still where they started. Reported as
        # exactly that confusion.
        config.set_project_dir(Path(chosen))
    # Reuse whatever QApplication exists rather than constructing a second one: Qt allows exactly
    # one per process and raises otherwise, which is how running the window tests before this
    # module's own turned a green suite red depending on file order alone.
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("autosound-tcc")
    app_log.install_qt_handler()  # Qt's own warnings, into the same file
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
