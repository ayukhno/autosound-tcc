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

from autosound_tcc.core import app_log, config, macos_identity

#: What a person sees this called: the Dock, the menu bar, window titles. Not the package name —
#: `autosound-tcc` is what you type, "Autosound TCC" is what it is.
APP_DISPLAY_NAME = "Autosound TCC"
#: Shipped inside the package so every install has it, however it was installed. The `.icns`
#: beside it is the same artwork for the macOS bundle, and the installer's app builder reads it
#: from here rather than keeping a second copy in the other repository.
APP_ICON = Path(__file__).resolve().parent / "assets" / "app-icon.png"
APP_ICNS = APP_ICON.with_suffix(".icns")
#: The same artwork for a Windows shortcut (.lnk), which can only take an .ico. The installer's
#: shortcut builder asks this module for it, the same way the macOS bundle builder asks for the
#: .icns, so neither installer keeps a copy of the artwork.
APP_ICO = APP_ICON.with_suffix(".ico")

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
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication

        from autosound_tcc.ui.tcc import qt_shutdown
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
    # BEFORE the QApplication, because Qt reads the bundle's name while the Cocoa plugin starts.
    # Without this the Dock tile says "python3.12" and the menu bar says "python" — macOS asks the
    # bundle that owns the running executable, which is Apple's own Python.app, not ours.
    macos_identity.rename(APP_DISPLAY_NAME)
    # Reuse whatever QApplication exists rather than constructing a second one: Qt allows exactly
    # one per process and raises otherwise, which is how running the window tests before this
    # module's own turned a green suite red depending on file order alone.
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("autosound-tcc")
    # What windows and dialogs are titled with. `setApplicationName` above is the identifier Qt
    # uses for QSettings and friends, and is deliberately the package name; this is the one a
    # person reads.
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    # The Dock tile of the RUNNING app. The bundle's own `.icns` is what Finder and Spotlight
    # show, and it only exists for people who installed through the installer — a `uv tool
    # install` and `autosound-tcc` from a terminal has no bundle at all, and used to run under
    # the generic Python rocket. Same artwork either way, from inside the package.
    if APP_ICON.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON)))
    app_log.install_qt_handler()  # Qt's own warnings, into the same file
    # Before the window, not inside it: `MainWindow.__init__` binds the MCP server, the session
    # registry and the file watchers to one folder, so there is no meaningful window to build
    # until that folder is known. Backing out of the gate exits rather than falling through to a
    # folder nobody picked -- which is what used to happen, silently, on every fresh install.
    if not ensure_project_chosen(force=args.choose_project):
        return 0
    window = MainWindow()
    window.show()
    code = app.exec()
    # Qt ends HERE rather than in whatever is left of the interpreter. Returning straight out of
    # `exec()` leaves the window and the QApplication alive, so `~QApplication` runs from inside
    # `Py_FinalizeEx` and takes the pyqtgraph plots down with it -- the SIGSEGV a person quitting
    # TCC could meet, as "Python quit unexpectedly", after their work was already saved. Same
    # destructor, run early enough that PySide can still find the Python half of what it touches;
    # see ui/tcc/qt_shutdown.py for the stack and for the six teardowns that made it worse.
    qt_shutdown.destroy_application()  # the window goes with it: `~QApplication` owns that walk
    del window  # by now a wrapper around nothing; dropped so no dead reference outlives `main()`
    return code


if __name__ == "__main__":
    raise SystemExit(main())
