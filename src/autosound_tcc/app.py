"""Application entry point.

Launches the TCC main window (see ui/tcc/main_window.py) -- the DSP tree, detail pane, AI
dialog, and plan/measurement panels are real; see docs/TCC-TZ.md and the plan file for what's
wired to real data vs. still mock. Packages as a normal Python console entry point on macOS and
Windows.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from autosound_tcc.core import app_log, child, config, macos_identity, windows_identity

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


def _make_splash(QtCore, QtGui, QtWidgets):
    """The window that says the app is starting, before there is a window to say it in.

    Between a double-click and the first pixel of TCC there is about a second and a half of import
    on a warm cache — `mcp`, `pyqtgraph`, PySide6, numpy — and then a `MainWindow.__init__` that
    reads the project, runs git and binds the MCP server. The first start after an update is
    longer still: `uv tool install --upgrade` rewrites the whole tool environment, so every one of
    those modules is byte-compiled again on the way in. Nothing was on screen for any of it (user,
    2026-09-06: "після оновлення довгий старт — добре показати щось").

    Drawn here rather than loaded from a file: the artwork we ship is a 1024-pixel icon, and a
    splash is a small dark card with a line of text under the app's name.
    """
    scale = QtWidgets.QApplication.primaryScreen().devicePixelRatio() if \
        QtWidgets.QApplication.primaryScreen() else 1.0
    width, height = 420, 160
    pixmap = QtGui.QPixmap(int(width * scale), int(height * scale))
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(QtGui.QColor("#14181d"))
    painter = QtGui.QPainter(pixmap)
    try:
        if APP_ICON.is_file():
            icon = QtGui.QPixmap(str(APP_ICON)).scaled(
                int(48 * scale), int(48 * scale),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation)
            icon.setDevicePixelRatio(scale)
            painter.drawPixmap(28, 34, icon)
        painter.setPen(QtGui.QColor("#e8eaed"))
        font = painter.font()
        font.setPointSizeF(font.pointSizeF() + 4)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(92, 66, APP_DISPLAY_NAME)
    finally:
        painter.end()
    splash = QtWidgets.QSplashScreen(pixmap)
    splash.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, False)
    return splash


def _wait_until_painted(is_painted, pump, budget_s: float, now) -> None:
    """Keep the event loop turning until the window has actually DRAWN, or the budget runs out.

    `QSplashScreen.finish(window)` waits for the window to be SHOWN, and its own comment here used
    to say that was enough. It is not, on Windows: `show()` returns long before anything is
    painted, so the splash closes and leaves a blank white rectangle with a spinner where the
    application should be. On video (user, 2026-09-09): 5.6 s — splash, "building the window";
    6.2 s — no splash, an empty white window. That gap is what reads as a flash.

    The budget is small and deliberate. A splash that lingers is untidy; a splash that never
    leaves is a hang, and this runs before there is any way to report one.

    Everything injected, because the alternative is a test that needs a real window manager to
    tell a wait from a hang.
    """
    started = now()
    while not is_painted():
        if now() - started >= budget_s:
            return
        pump()


def _stray_windows(widgets, known=()) -> list:
    """Visible top-level widgets that nobody meant to be windows — `(class, size)` for each.

    A widget shown before it has a parent becomes a TOP-LEVEL WINDOW in Qt: it gets a frame, and
    a title Windows fills in with the application's name. Narrow and tall, because nothing has
    laid it out yet. That is what was caught on video over the painted main window (2026-09-09),
    and what the earlier reports called "a narrow tall window like the left panel".

    Marked `known` are the ones that are supposed to be windows — the main window and the splash.
    Everything else visible at this point is a finding, and naming its CLASS is the whole value:
    4 400 lines of window code is too much to search by reading.
    """
    ours = {id(w) for w in known if w is not None}
    return [
        (w.metaObject().className(), f"{w.width()}x{w.height()}")
        for w in widgets
        if w.isVisible() and id(w) not in ours and not getattr(w, "known", False)
    ]


#: State for the stray-window watch, module level because the two things that can pump the event
#: queue during startup — `_say` and the timer — are in different places and must share one
#: "already reported" set.
_STRAY: dict = {"known": [], "seen": set(), "log": None}


def _note_strays(app) -> None:
    """Report any window that should not be there, once per shape.

    Called from `_say`, and that is the point of it. Qt timers do not fire before `app.exec()`,
    and the whole startup — where these windows appear — happens before it: the first version of
    this watch was a `QTimer` and reported NOTHING three builds running, on a machine where the
    user could see two of them (2026-09-09). `_say` is the one thing that turns the event queue
    while the splash is up, so the check belongs where the queue actually moves.
    """
    log = _STRAY["log"]
    if log is None:
        return
    ours = {id(w) for w in _STRAY["known"] if w is not None}
    for w in app.topLevelWidgets():
        if not w.isVisible():
            continue
        name = w.metaObject().className()
        shape = f"{name} {w.width()}x{w.height()} {w.windowTitle()!r}"
        if shape in _STRAY["seen"]:
            continue
        _STRAY["seen"].add(shape)
        # Everything visible, not only the unexpected: three builds of "report the strays" found
        # nothing while the user could see two windows, and at that point the useful question
        # stops being "what is wrong" and becomes "what does Qt think it has at all".
        log.info("%s window: %s", "own" if id(w) in ours else "stray", shape)
    # And the QWindows, which are NOT the same list. A `QWindow` can exist without a widget —
    # pyqtgraph and any OpenGL surface make them — so it never appears in `topLevelWidgets()`, and
    # three probes reported "nothing" while two framed windows were on the user's screen
    # (2026-09-09). A watch that only knows about widgets cannot see them at all.
    try:
        from PySide6.QtGui import QGuiApplication

        for handle in QGuiApplication.topLevelWindows():
            if not handle.isVisible():
                continue
            shape = (f"{handle.metaObject().className()} "
                     f"{handle.width()}x{handle.height()} {handle.title()!r}")
            if shape in _STRAY["seen"]:
                continue
            _STRAY["seen"].add(shape)
            log.info("qwindow: %s", shape)
    except Exception:  # noqa: BLE001 — a diagnostic must not be able to stop a launch
        pass


def _watch_for_stray_windows(app, QtCore, known, log) -> None:
    """Sample the top-level widgets a few times over the first seconds and log what should not be.

    A timer rather than an event filter: the flash lasts under a second and happens while the
    window is still settling, so what matters is catching it at all, not catching every frame of
    it. Costs nothing when there is nothing to report — which is the normal case, and the reason
    this can stay in.
    """
    _STRAY["known"] = known
    _STRAY["log"] = log
    checks = {"n": 0}

    def look() -> None:
        checks["n"] += 1
        _note_strays(app)
        if checks["n"] < 80:
            QtCore.QTimer.singleShot(150, look)

    # The timer covers the time AFTER `app.exec()` starts. Before it, nothing fires — see
    # `_note_strays`, which `_say` calls on every splash line.
    QtCore.QTimer.singleShot(0, look)


def watch_windows_again(reason: str = "closing") -> None:
    """Re-arm the window watch for a phase it was never armed for: the shutdown.

    The startup watch stops after its rounds, so windows flashing AT CLOSE were never recorded
    from inside. The desktop-wide watcher outside cannot settle it either: it logs a window when
    its state CHANGES between passes, so one that appears and goes within a single pass leaves no
    trace — and a burst at shutdown is exactly that shape. Measured 2026-09-11: nine seconds of
    closing with not one event recorded, while the user was watching windows flash.

    From inside there is nothing to under-sample: `_note_strays` asks Qt what top-level windows it
    has, rather than trying to catch them on screen.
    """
    log = _STRAY["log"]
    if log is None:
        return
    try:
        from PySide6 import QtCore
        from PySide6.QtWidgets import QApplication
    except Exception:  # noqa: BLE001 — no toolkit here means nothing to watch
        return
    app = QApplication.instance()
    if app is None:
        return
    log.info("window watch re-armed: %s", reason)
    # Cleared on purpose: a window already reported at startup must be reported again now. The
    # question has changed from "what is new since we opened" to "what does the close put up".
    _STRAY["seen"].clear()
    _watch_for_stray_windows(app, QtCore, _STRAY["known"], log)


def _say(app, splash, text: str) -> None:
    """Put a line on the splash and let Qt actually paint it.

    `processEvents` is the point: everything after this call is a synchronous import or a blocking
    read, so without it the splash is a grey rectangle for the whole start.
    """
    if splash is None:
        return
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor

    _note_strays(app)
    splash.showMessage(
        f"  {text}",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
        QColor("#9aa4af"),
    )
    app.processEvents()
    _note_strays(app)  # after the queue moved: a window that just appeared is only now listed


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
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the installed version and exit.",
    )
    parser.add_argument(
        "--install-desktop",
        action="store_true",
        help="Build the macOS app bundle (or the Windows shortcuts) for this install, and exit.",
    )
    parser.add_argument(
        "--uninstall-desktop",
        action="store_true",
        help="Remove what --install-desktop made — the macOS bundle and its Desktop alias, or the "
             "Windows shortcuts. Recognised as ours by the bundle id in Info.plist, by an alias "
             "being a symlink to a bundle of that name, and by a shortcut's target being one of "
             "our launchers. Anything else under those names is left alone and named on stderr. "
             "Never touches a project, an environment or the package itself.",
    )
    parser.add_argument(
        "--restore-terminal",
        action="store_true",
        help="Put Windows' default terminal back to what it was before TCC changed it. TCC "
             "switches it to the old console host because that is the only way to hide the "
             "console the AI's shell commands would otherwise flash on screen (TCC-006). This "
             "undoes that, writes the same undo out as a .reg file you can read, and exits. "
             "Safe to run at any time, and run for you by --uninstall-desktop.",
    )
    known, _ = parser.parse_known_args(argv[1:])  # Qt takes its own flags off the same line
    return known


def main() -> int:
    """Start the Qt event loop. Returns the process exit code."""
    # First, before anything can fail: an exception raised from here on lands in a file instead of
    # in the terminal TCC was launched from. On macOS a line arriving there while the window is a
    # full-screen space switches the user out of the app mid-tune (see core/app_log.py).
    app_log.setup()
    # One line, before anything can spawn a child, saying WHICH build this is and whether this is
    # the first run of it. Both were missing, and the second is what turns "it flashes after an
    # update and then stops" (user, 2026-09-09) from a memory into something a log can settle.
    app_log.note_start()
    # Before anything can start a child: on Windows the Agent SDK's own `claude` process would
    # otherwise open a console window in front of the app at every session (see core/child.py).
    # ONE console for this process, said out loud and then hidden, before anything can start a
    # child. Everything TCC runs afterwards inherits it instead of allocating its own — and a
    # console allocated by a child IS the window people have been seeing (TCC-006). A console
    # cannot be created already hidden on Windows 11, so this pays that cost once, at startup,
    # where it can say what it is rather than being an unexplained black rectangle.
    # Windows only; a no-op on macOS and Linux, where none of this exists.
    child.open_app_console("Autosound TCC is starting — this window hides itself.")
    child.hide_console_windows()
    # Before the toolkit is even looked for: making a Dock entry needs no window, and a light
    # install -- the one WITHOUT PySide6 -- is exactly the install whose owner will want the app
    # on the Dock once the extras arrive. This used to be a shell script in the method's
    # repository that the installer had to find by guessing a path (F-026).
    args = _parse(sys.argv)
    # Before anything else can start: asking a program its version must not RUN the program. It
    # used to -- there was no such flag, and `parse_known_args` (which exists so Qt can take its
    # own flags off the same line) swallowed it silently, so `autosound-tcc --version` launched the
    # whole app, MCP server and all. Found on a Windows VM whose build was too old to have an
    # update panel, by the one command the test plan uses to say what is installed there
    # (2026-08-22). A version query is also what an installer wants before it decides to replace
    # us, and a server bound to a port is a bad answer to it.
    if args.version:
        from autosound_tcc.core import install_report

        print(install_report.app_version() or "unknown")
        return 0
    if args.restore_terminal:
        # Before Qt, like every other flag that answers and leaves: undoing a machine setting must
        # work on an install whose window will not open at all.
        from autosound_tcc.core import default_terminal

        was = default_terminal.current()
        done = default_terminal.restore()
        written = default_terminal.write_restore_file()
        print(f"default terminal was: {was}")
        print("restored" if done else "could NOT restore — see the file below", file=
              sys.stdout if done else sys.stderr)
        if written is not None:
            print(f"the same undo, as a file you can read and run: {written}")
        return 0 if done else 1
    if args.install_desktop or args.uninstall_desktop:
        from autosound_tcc.core import desktop_entry

        result = (desktop_entry.uninstall_desktop() if args.uninstall_desktop
                  else desktop_entry.install_desktop())
        for line in result.lines:
            print(line, file=sys.stdout if result.ok else sys.stderr)
        # Always stderr, success or not: the calling installer parses stdout for the paths, and
        # "left this alone, it is not mine" is for the person reading, not for the parser.
        for line in result.notes:
            print(line, file=sys.stderr)
        return 0 if result.ok else 1
    # Imported HERE, not at module scope. A light install has no PySide6, and an entry point that
    # cannot even be imported gives its user a traceback where a sentence belongs.
    # Split in two on purpose (2026-09-06): the toolkit first, so there can be a window on screen
    # saying "starting" while the expensive half — `main_window`, and through it mcp, pyqtgraph
    # and numpy — is still being imported. Both halves answer a missing PySide6 with the same
    # sentence, because a light install fails at the first one.
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication

        from autosound_tcc.ui.tcc import i18n
        from autosound_tcc.ui.tcc.app_settings import get_settings
    except ImportError as exc:
        print(_NO_GUI.format(error=exc), file=sys.stderr)
        return 2
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
    # BEFORE the QApplication for the same reason, on the other operating system: Windows
    # resolves which application a window belongs to when the window is created, and a process
    # that never said otherwise belongs to the executable hosting it -- `pythonw.exe`, whose
    # icon the taskbar then draws beside our window (user's Parallels VM, 2026-08-23).
    windows_identity.claim()
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
    # The `.ico` first on Windows, and only there: it carries seven sizes down to 16x16, drawn
    # for those sizes, while the `.png` is one 1024-pixel image Qt would shrink to a title bar.
    icon = APP_ICO if os.name == "nt" and APP_ICO.is_file() else APP_ICON
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    app_log.install_qt_handler()  # Qt's own warnings, into the same file
    # The same language the window will come up in — read from the same store `MainWindow` reads
    # it from, so the three lines below are not in English on a Ukrainian install.
    try:
        i18n.set_language(get_settings().value("ui/lang", "en"))
    except Exception:  # noqa: BLE001 — an unreadable setting is not a reason not to start
        pass
    splash = None
    if os.environ.get("AUTOSOUND_TCC_SPLASH", "1") != "0":
        try:
            splash = _make_splash(QtCore, QtGui, QtWidgets)
            splash.show()
        except Exception:  # noqa: BLE001 — a splash that cannot be drawn must not stop the app
            splash = None
    # The watch starts HERE, not after the window: the two narrow tall frames caught on the
    # user's screen (2026-09-09) appear WHILE the splash is up, which is why the first version of
    # this — armed after `window.show()` — reported nothing. `known` is a list that grows: the
    # window is appended to it the moment it exists.
    known: list = [splash]
    _watch_for_stray_windows(app, QtCore, known, app_log.logger())
    _say(app, splash, i18n.t("splashStarting"))
    try:
        from autosound_tcc.ui.tcc import qt_shutdown
        from autosound_tcc.ui.tcc.main_window import MainWindow
        from autosound_tcc.ui.tcc.project_gate_dialog import ensure_project_chosen
    except ImportError as exc:
        if splash is not None:
            splash.close()
        print(_NO_GUI.format(error=exc), file=sys.stderr)
        return 2
    # Before the window, not inside it: `MainWindow.__init__` binds the MCP server, the session
    # registry and the file watchers to one folder, so there is no meaningful window to build
    # until that folder is known. Backing out of the gate exits rather than falling through to a
    # folder nobody picked -- which is what used to happen, silently, on every fresh install.
    _say(app, splash, i18n.t("splashProject"))
    # The splash is NOT hidden around the gate. It was, on the argument that a modal has to be
    # answered and a splash over it is in the way — but the gate only appears when nothing is
    # remembered, and on every ordinary launch that hide-and-show was a window blinking on and off
    # for no reason at all (user, on Windows, 2026-09-06, on the first run of v0.1.32). The splash
    # does not hold `WindowStaysOnTopHint`, so a modal that does open takes focus above it.
    if not ensure_project_chosen(force=args.choose_project):
        return 0
    _say(app, splash, i18n.t("splashWindow"))
    window = MainWindow()
    # AFTER the window exists, and a different question from `claim()` above. That one told
    # Windows which application this PROCESS is; this tells it what to put in a pin of this
    # WINDOW, and Windows asks the two in different places -- which is why claiming the id
    # was not enough and F-037 came back on the pin. `winId()` forces the native handle the
    # property store hangs off; a widget that has never been shown does not have one yet.
    # Guarded here rather than only inside, so no other platform grows a new call at startup.
    if os.name == "nt":
        windows_identity.stamp_window(int(window.winId()))
    known.append(window)
    # The Arbiter's counting experiment (`AUTOSOUND_TCC_FLASH_PROBE`), off in an ordinary build.
    # Three before the window and two after: if the count on screen is three then two, the flashes
    # ARE this command; if it stays one and one, they are not — and no log had to be believed.
    child.flash_probe("before")
    window.show()
    child.flash_probe("after")
    if splash is not None:
        # `finish`, not `close`: it waits for the window it is handed to be up, so there is no
        # frame with neither of them on screen.
        #
        # But "up" is not "drawn". `show()` returns before the window has painted, and the splash
        # then leaves a blank white rectangle behind it — caught on video on Windows, 2026-09-09.
        # So the loop below turns the event queue until the window reports itself exposed, and
        # only then hands over.
        # `isExposed()` was the first attempt and it is NOT enough: it turns true the moment the
        # window is mapped, which on Windows is about half a second before anything is drawn.
        # Caught on video at 19.80 s (probe5, which already had that version): the frame is up,
        # the title bar is up, and the desktop shows THROUGH it — an empty pane standing there
        # until 20.4 s. That transparent rectangle is the flash people have been reporting.
        #
        # So: wait for a real paint. The window says when it has drawn; nothing else can.
        painted = {"yes": False}

        class _FirstPaint(QtCore.QObject):
            def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
                if event.type() == QtCore.QEvent.Type.Paint:
                    painted["yes"] = True
                return False

        watcher = _FirstPaint()
        window.installEventFilter(watcher)
        _wait_until_painted(
            is_painted=lambda: painted["yes"],
            pump=lambda: app.processEvents(),
            budget_s=3.0,
            now=time.monotonic,
        )
        window.removeEventFilter(watcher)
        splash.finish(window)

    code = app.exec()
    # Qt ends HERE rather than in whatever is left of the interpreter. Returning straight out of
    # `exec()` leaves the window and the QApplication alive, so `~QApplication` runs from inside
    # `Py_FinalizeEx` and takes the pyqtgraph plots down with it -- the SIGSEGV a person quitting
    # TCC could meet, as "Python quit unexpectedly", after their work was already saved. Same
    # destructor, run early enough that PySide can still find the Python half of what it touches;
    # see ui/tcc/qt_shutdown.py for the stack and for the six teardowns that made it worse.
    if not qt_shutdown.destroy_application():
        # It declined: a background thread outlived the wait, and destroying Qt around it is
        # `qFatal` -- the abort a person met on 2026-08-21 after answering "save" to the quit
        # question. Leaving through `os._exit` is the point of this branch: it skips PySide's own
        # `atexit` handler, which would otherwise reach the same `~QThread` from inside
        # `Py_FinalizeEx` and abort there instead. Flushed by hand first, because `_exit` does
        # not run the buffers down for us and the log of a rough exit is worth keeping.
        logging.shutdown()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
    del window  # by now a wrapper around nothing; dropped so no dead reference outlives `main()`
    return code


if __name__ == "__main__":
    raise SystemExit(main())
