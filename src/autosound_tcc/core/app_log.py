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

import functools
import logging
import os
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Optional

LOGGER_NAME = "autosound_tcc"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUPS = 3

# Set by `set_ui_sink` once a window exists: (short message, log path or None) -> shown in the
# status strip. Optional on purpose -- a crash during startup has no window to tell, and must still
# land in the file.
_ui_sink: Optional[Callable[[str, Optional[Path]], None]] = None
_log_path: Optional[Path] = None


#: How much of a tool's arguments and of its answer goes into the log. Enough to tell one call
#: from the next — which field was saved, whether the writer refused — and not the whole payload:
#: a tool can answer with kilobytes, and a log nobody can page through is the same as no log
#: (report on the run of 2026-09-01: 88 lines, 34 of them Qt warnings, and a completed interview
#: that left no trace at all).
LOG_VALUE_CHARS = 200


def brief(value: Any) -> str:
    """One line, bounded, and it says when it cut."""
    text = " ".join(str(value).split())
    return text if len(text) <= LOG_VALUE_CHARS else text[:LOG_VALUE_CHARS] + "… (cut)"


#: How long a tool may take before every thread's stack goes into the log (tcc#72, finding 80): an
#: omp turn hung inside `get_tcc_state` with the call logged and its answer never, and nothing on
#: disk said where. A local tool answers in milliseconds; twenty seconds is a hang.
SLOW_TOOL_S = 20.0


def dump_threads(reason: str) -> None:
    """Every thread's stack into the log file — through `faulthandler`, which takes no lock.

    Not through `logging`: if the hang is a lock the logging machinery waits on, a dump that needs
    it would hang too, and the one hang worth a dump would leave none."""
    import faulthandler

    path = _log_path
    try:
        with open(path, "a", encoding="utf-8") if path else open(os.devnull, "w") as sink:
            target = sink if path else sys.stderr
            target.write(f"\n{reason}\n")
            target.flush()
            faulthandler.dump_traceback(file=target, all_threads=True)
            target.flush()
    except Exception:  # noqa: BLE001 — a diagnostic must not become a second failure
        pass


def logged_tool(fn):
    """Wrap an async agent tool so it says, at INFO, that it was called and what it answered.

    One wrapper rather than a log line inside each tool: a line per tool is one chance per tool to
    forget, and the one that gets forgotten is the one whose absence is later reported as "the log
    shows nothing" (`SKL-009`).

    It lives HERE, not in `core/mcp_server.py` where it was written, because there are two tool
    servers and only one of them was covered: the external CLI talks to `mcp_server`, and the
    in-app onboarding window drives `agent_session.build_tools` instead. The half a person meets
    first was the half with no log at all (tcc#9). `core/app_log` is what both may import —
    `mcp_server` pulls in FastMCP and uvicorn, and the onboarding path must not.

    `functools.wraps` is what keeps this invisible to FastMCP and to the SDK: the schema they
    build comes from `inspect.signature` and `__doc__`, and both follow `__wrapped__`.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        log = logger()
        shown = kwargs if kwargs else args
        log.info("tool %s(%s)", fn.__name__, brief(shown) if shown else "")
        # A tool that does not come back says where everything was (tcc#72): on its own thread,
        # so it fires even when this one — or the whole event loop — is the thing stuck.
        watch = threading.Timer(SLOW_TOOL_S, dump_threads, args=(
            f"tool {fn.__name__} has not returned in {SLOW_TOOL_S:.0f}s; every thread's stack:",))
        watch.daemon = True
        watch.start()
        try:
            result = await fn(*args, **kwargs)
        except Exception:
            # `exception` and re-raise: the caller still gets the failure it would have got, and
            # the file now says which tool produced it.
            log.exception("tool %s raised", fn.__name__)
            raise
        finally:
            watch.cancel()
        log.info("tool %s -> %s", fn.__name__, brief(result))
        return result

    return wrapper


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


#: How much of the log the panel shows and a person pastes. A rotating file is bounded already;
#: this is about what a reader can take in and what a chat message will carry — the end is where
#: the answer is, and the beginning is last week.
TAIL_LINES = 400


def tail(lines: int = TAIL_LINES) -> str:
    """The end of the log file, as text — or a sentence saying why there is none.

    Never raises: it is read by a panel somebody opened BECAUSE something is wrong, and the one
    thing it must not do there is fail in a way that needs its own log.
    """
    path = log_path()
    if path is None:
        return "no log file — this run is writing to the terminal only"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"could not read {path}: {exc}"
    if not text.strip():
        return f"{path} is empty — nothing has been logged this run"
    kept = text.splitlines()[-lines:]
    return "\n".join(kept)


def logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def note_start() -> bool:
    """Write the one line the log never had, and say whether this is a NEW version's first run.

    The log was not quiet because INFO is suppressed — it is not, and that was checked — but
    because nothing on the startup path ever wrote a line. So every question about a Windows
    machine ("which build was that?", "was that the run right after the update?") has been
    answered by memory, and TCC-006 stayed unfalsifiable for days on exactly that.

    The first run of a version is a DIFFERENT event from the ones after it (user, 2026-09-09: the
    window flashes after an update and then stops), and only the app can know which run it is. The
    marker file sits beside the log rather than in QSettings: this runs before Qt is imported, and
    a diagnostic that needs the toolkit is a diagnostic that cannot report a failure to start.

    Returns True on the first run of this version. Never raises: an unwritable marker means the
    answer degrades to "cannot tell", which is said in the line rather than crashing a launch.
    """
    version = _version_string()
    log = logger()
    directory = log_dir()
    marker = directory / "last-version.txt"
    seen = ""
    try:
        seen = marker.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    first = seen != version
    if first:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            marker.write_text(version, encoding="utf-8")
        except OSError:
            log.info("started: version=%s platform=%s (cannot tell: marker unwritable)",
                     version, sys.platform)
            return True
    log.info(
        "started: version=%s platform=%s%s",
        version, sys.platform, " — first run of this version" if first else "",
    )
    return first


def _version_string() -> str:
    """This build's version, or `unknown`. Never raises — a log line must not be a failure point."""
    try:
        from importlib.metadata import version as package_version

        return package_version("autosound-tcc")
    except Exception:  # noqa: BLE001 — running from a checkout, or metadata missing
        return "unknown"


#: Reports made while no sink was registered, oldest first, for the next one (`set_ui_sink`).
#: Bounded: the log keeps every one of them, and a window needs the latest.
_held: list[str] = []
_HELD_MAX = 20
#: Whether one was dropped past the bound since a sink last took them: logged once (`_hold`).
_held_dropped = False
#: `_ui_sink` and `_held` change together, so a report made on another thread while a window
#: registers is either held and handed over, or told directly — never neither.
_sink_lock = threading.Lock()


def set_ui_sink(sink: Optional[Callable[[str, Optional[Path]], None]]) -> None:
    """Register (or clear) the callback that tells the user something was logged.

    A sink registered after reports were made hears them now, in order and once each. On every
    launch the ☰ menu reads `tcc-project.json` while the header is built, before the window gets
    here, and a file found broken then was said to the log alone (the review of Task 17). Only
    `report`s are held; the excepthooks tell a window when there is one, as before."""
    global _ui_sink, _held, _held_dropped
    with _sink_lock:
        _ui_sink = sink
        held: list[str] = []
        if sink is not None:
            held, _held, _held_dropped = _held, [], False
    for message in held:
        _tell(message)


def clear_ui_sink(sink: Callable[[str, Optional[Path]], None]) -> None:
    """Clear the sink only if it is still `sink`: a window going away takes its own sink with it,
    not the next window's. In the new-project hand-off the new window registers in `__init__`
    and the old one's `close()` came after, and from then on every report reached the log alone
    (Task 19's review, M6). Equality, not identity: a window hands over a bound method, a new
    object on every access. Held reports stay held, as with `set_ui_sink(None)`."""
    global _ui_sink
    with _sink_lock:
        if _ui_sink == sink:
            _ui_sink = None


def _notify(message: str) -> None:
    """Tell the sink, with the log file to point at — or None when `setup` could not open one:
    the machine whose log cannot hold the sentence is no reason for the strip not to."""
    if _ui_sink is None:
        return
    try:
        _ui_sink(message, _log_path)
    except Exception:  # noqa: BLE001 — a failing notifier must never mask the error it reports
        logger().exception("the UI log sink raised")


#: Set on a thread while its report is being handed to the sink (`report`).
_reporting = threading.local()


def report(message: str) -> None:
    """Something the person has to hear about: an ERROR line in the log AND the window's strip.

    An ERROR line alone never reached the strip — only the two excepthooks call the sink — so a
    settings file set aside after a bad hand edit would have been said to a file nobody opens
    (#173). A call rather than a handler that forwards every ERROR record: the places that log an
    error and then say it in their own words would each have been said twice.

    Made before a window exists, it is held and handed to the window when it registers
    (`set_ui_sink`).

    Re-entrancy guarded, per thread: a sink whose own work reports (a window reading a store that
    is broken) is not called back into — that report goes to the log only — and a sink that raises
    is logged once, by `_notify`, and the report returns. What is being reported must not be lost
    to the failure of what reports it.
    """
    logger().error("%s", message)
    with _sink_lock:
        told = _ui_sink is not None
        first_drop = False if told else _hold(message)
    if told:
        _tell(message)
    elif first_drop:
        logger().warning("more than %d reports came with no window to tell: a window that "
                         "registers hears the latest %d, and every one is in this log",
                         _HELD_MAX, _HELD_MAX)


def _hold(message: str) -> bool:
    """Keep `message` for the next sink, the latest `_HELD_MAX` of them (under `_sink_lock`). True
    when it drops the first one since a sink last took them: a window that registers later is told
    the latest and nothing about the rest, so the log says it once (the group review, G7)."""
    global _held_dropped
    _held.append(message)
    if len(_held) <= _HELD_MAX:
        return False
    del _held[:-_HELD_MAX]
    first, _held_dropped = not _held_dropped, True
    return first


def _tell(message: str) -> None:
    """One report to the sink, unless this thread is already inside the sink (`report`)."""
    if getattr(_reporting, "active", False):
        return
    _reporting.active = True
    try:
        _notify(message)
    finally:
        _reporting.active = False


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
