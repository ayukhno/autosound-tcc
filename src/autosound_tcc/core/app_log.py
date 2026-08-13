"""Where TCC's own errors go, now that it is not the terminal.

Two things wrote to the terminal TCC was launched from: Qt's own warnings, and Python tracebacks
from exceptions raised inside signal handlers (PySide6 routes those through `sys.excepthook`).
Both are invaluable and both were in the wrong place — on macOS, a line arriving in the launching
Terminal while the window is a full-screen space pulls the user out of the app mid-tune (reported
2026-08-11, confirmed: a line did appear in the terminal at the moment of the switch).

So they go to a file instead, and the window says one short sentence pointing at it. Nothing is
dropped: the point is to move the noise, not to swallow it. `AUTOSOUND_TCC_LOG_STDERR=1` puts it
back on stderr as well, which is what you want when you are debugging from a terminal on purpose.

What this CANNOT catch: messages macOS itself writes from native code, e.g.

    Python[30393]: TSMSendMessageToUIServer: CFMessagePortSendRequest FAILED(-1) ...

That is the Text Services Manager failing to reach the input-method server, which it does for any
GUI process without a proper `.app` bundle. It is harmless, it says nothing about project state,
and it is written straight to the process's stderr by AppKit — below every Python-level hook.
Packaging a real bundle is what removes it.

Nothing here imports Qt at module level: `app.py` sets this up before the QApplication exists.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

LOGGER_NAME = "autosound_tcc"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUPS = 3

# Set by `set_ui_sink` once a window exists: (short message, log path) -> shown in the status
# strip. Optional on purpose -- a crash during startup has no window to tell, and must still land
# in the file.
_ui_sink: Optional[Callable[[str, Path], None]] = None
_log_path: Optional[Path] = None


def log_dir() -> Path:
    """The platform's own place for user-facing logs.

    Not the project folder: a project is chosen after startup, and a crash before that has to go
    somewhere. One location also means one thing to ask for in a bug report.
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "autosound-tcc"
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "autosound-tcc" / "logs"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "autosound-tcc"


def log_path() -> Optional[Path]:
    """The file `setup()` is writing to, or None if it has not run."""
    return _log_path


def logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def set_ui_sink(sink: Optional[Callable[[str, Path], None]]) -> None:
    """Register (or clear) the callback that tells the user something was logged."""
    global _ui_sink
    _ui_sink = sink


def _notify(message: str) -> None:
    if _ui_sink is None or _log_path is None:
        return
    try:
        _ui_sink(message, _log_path)
    except Exception:  # noqa: BLE001 — a failing notifier must never mask the error it reports
        logger().exception("the UI log sink raised")


def _install_excepthooks() -> None:
    previous = sys.excepthook

    def hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc, tb)  # Ctrl-C is a user's decision, not a defect
            return
        logger().error(
            "unhandled exception\n%s", "".join(traceback.format_exception(exc_type, exc, tb))
        )
        _notify(f"{exc_type.__name__}: {exc}")

    sys.excepthook = hook

    def thread_hook(args) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        logger().error(
            "unhandled exception in thread %s\n%s",
            getattr(args.thread, "name", "?"),
            "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
        )
        _notify(f"{args.exc_type.__name__}: {args.exc_value}")

    threading.excepthook = thread_hook


def install_qt_handler() -> None:
    """Route Qt's own warnings into the same file. Separate from `setup()` because it needs Qt
    imported, and `setup()` deliberately runs before there is a QApplication."""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode, context, message) -> None:
        logger().log(levels.get(mode, logging.INFO), "Qt: %s", message)

    qInstallMessageHandler(handler)


def setup(*, to_stderr: Optional[bool] = None) -> Optional[Path]:
    """Start logging to a file and take over the exception hooks. Returns the file, or None.

    Returns None rather than raising if the log directory cannot be created: a machine where the
    log is unwritable is a machine where TCC should still open.
    """
    global _log_path
    if to_stderr is None:
        to_stderr = os.environ.get("AUTOSOUND_TCC_LOG_STDERR", "0") not in ("0", "", "false")

    log = logger()
    log.setLevel(logging.INFO)
    log.propagate = False  # the root logger's default handler prints to stderr, which is the point
    for handler in list(log.handlers):
        log.removeHandler(handler)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        directory = log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "tcc.log"
        file_handler = RotatingFileHandler(
            path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)
        _log_path = path
    except OSError:
        _log_path = None

    if to_stderr or _log_path is None:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        log.addHandler(stream)

    _capture_python_warnings(log.handlers)
    _install_excepthooks()
    return _log_path


def _capture_python_warnings(handlers: list) -> None:
    """Python's own warnings into the same file, for the same reason Qt's go there.

    The first line a person saw when launching TCC from a terminal was three lines of somebody
    else's jargon — `pydantic_settings` complaining, through `mcp`, that a field named `lifespan`
    has an unresolved forward reference and someone should call `model_rebuild()`. Nothing of ours
    is involved and nothing breaks, but on a first launch it reads as "this is broken" (user, on a
    fresh install 2026-08-13).

    Captured rather than FILTERED. A `filterwarnings("ignore", …)` narrow enough to hit only that
    one would still be a rule that silently swallows the next real warning from the same category,
    and a rule nobody would think to check. Here nothing is lost: it is in `tcc.log` with
    everything else, and the terminal is clean.
    """
    # Off, then on. `captureWarnings(True)` only installs its hook `if _warnings_showwarning is
    # None` — so a SECOND call is a silent no-op, and if anything replaced `warnings.showwarning`
    # in between (pytest does, around every test) the capture is quietly dead and the warnings go
    # back to the terminal. Turning it off first clears that flag, so this is idempotent in the
    # way it appears to be. Found by the test below failing only when it was not run alone.
    logging.captureWarnings(False)
    logging.captureWarnings(True)
    captured = logging.getLogger("py.warnings")
    captured.setLevel(logging.WARNING)
    captured.propagate = False  # `logger()` does not propagate either; this is the same argument
    for handler in list(captured.handlers):
        captured.removeHandler(handler)
    for handler in handlers:
        captured.addHandler(handler)
