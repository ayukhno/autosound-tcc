"""How this app runs a command it only wants an ANSWER from.

Every probe TCC makes — `claude auth status`, `agy models`, a `--version`, the skill's checker —
is a child process started from a window. Two things about that are not obvious and both bite on
one platform only:

**stdin.** A CLI that finds a terminal on its stdin may wait for input. Started from a GUI it
inherits whatever the parent had, which on Windows is nothing useful and on macOS may be the
terminal the app was launched from. A probe that waits for a keypress nobody will make is a probe
that times out, and eight of those in a row is a panel that appears to hang (measured here,
2026-08-19: an installation report that takes 2.7 s from a shell took over 9 s from the window).

**A console window.** On Windows, a GUI process starting a console program gets a black window
flashed on screen for the duration — once per probe. `CREATE_NO_WINDOW` is the documented way to
say "this one has no user interface"; on every other platform the flag does not exist and this is
an empty dict.

Deliberately NOT used by `core/terminal_launcher`: that one's whole purpose is to open a terminal
the person can see and type in.
"""

from __future__ import annotations

import ctypes
import functools
import inspect
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional


def _no_window() -> int:
    """`CREATE_NO_WINDOW` where it exists and this is Windows, `0` everywhere else."""
    flag = getattr(subprocess, "CREATE_NO_WINDOW", None)
    if sys.platform.startswith("win") and flag is not None:
        return int(flag)
    return 0


def quiet() -> dict:
    """Keyword arguments for a `subprocess` call that must not wait for input or show a window."""
    kwargs: dict = {"stdin": subprocess.DEVNULL}
    flag = _no_window()
    if flag:
        kwargs["creationflags"] = flag
    return kwargs


def flags() -> dict:
    """The window half of `quiet()` alone, for a child whose stdin the caller is holding.

    A long-lived agent process is driven THROUGH its stdin — `asyncio.create_subprocess_exec` with
    a pipe — so it cannot take `DEVNULL`, but it still has no business opening a console.
    """
    flag = _no_window()
    return {"creationflags": flag} if flag else {}


def wants_a_console() -> dict:
    """The opposite of `quiet()`: for the one caller whose whole purpose IS a visible window.

    `hide_console_windows()` makes "no window" the DEFAULT for every child, so the terminal
    launcher has to say out loud that it wants one -- otherwise the blanket default would take
    away the window it exists to open. On anything but Windows this is empty, as always.
    """
    flag = getattr(subprocess, "CREATE_NEW_CONSOLE", None)
    if sys.platform.startswith("win") and flag is not None:
        return {"creationflags": int(flag)}
    return {}


#: Argv heads that mean "this is the agent's own CLI". Matched by basename without an extension,
#: because Windows spells it `claude.cmd` / `claude.exe` and POSIX spells it `claude`. Short and
#: closed on purpose: it decides which child is given a console to hand DOWN, and a loose match
#: would hand one to something that then shows it.
AGENT_COMMANDS = frozenset({"claude", "omp", "agy", "node"})


def is_agent_command(args) -> bool:
    """Does this argv start the agent's own CLI? Used to decide who gets the hidden console.

    Deliberately narrow: everything else keeps `CREATE_NO_WINDOW`, which is the right default for
    a child that spawns nothing.
    """
    first = args[0] if isinstance(args, (list, tuple)) and args else args
    if isinstance(first, (list, tuple)):
        first = first[0] if first else ""
    try:
        name = str(first).replace("\\", "/").rsplit("/", 1)[-1].lower()
    except Exception:  # noqa: BLE001 — an argv we cannot read is not the agent
        return False
    return name.split(".", 1)[0] in AGENT_COMMANDS


#: What Windows calls a console window. Under **conhost** that window belongs to our own child and
#: can be found by its pid; under **Windows Terminal** it belongs to `WindowsTerminal.exe` and a
#: search by our pid returns nothing at all, so none of this can work there (measured on Windows
#: 11, 2026-09-11 — that is also why `STARTUPINFO`+`SW_HIDE` never worked: there was no window of
#: ours to hide). `core/default_terminal.py` is the half that makes conhost the default.
CONSOLE_CLASS = "ConsoleWindowClass"

#: How long the keeper stays with a process. conhost shows the window back ONCE, a second or so
#: after the first hide, so this has to outlive that; it must not outlive the session, because a
#: thread spinning for hours is worse than a window nobody sees.
CONSOLE_KEEPER_BUDGET_S = 30.0


def _console_windows_of(pid: int) -> list:
    """`(hwnd, class, visible)` for every top-level window owned by `pid`. Empty off Windows."""
    if not sys.platform.startswith("win"):
        return []
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        signature = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        found: list = []

        def visit(hwnd, _lparam):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid:
                name = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, name, 256)
                found.append((hwnd, name.value, bool(user32.IsWindowVisible(hwnd))))
            return True

        user32.EnumWindows(signature(visit), 0)
        return found
    except Exception:  # noqa: BLE001 — a window we cannot enumerate is one we cannot hide
        return []


def _hide_window(hwnd: object) -> None:
    try:
        ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:  # noqa: BLE001 — hiding is cosmetic; failing at it must not stop a spawn
        return


def hide_console_of(pid: int, *, windows_of=None, hide=None) -> int:
    """Hide every VISIBLE console window owned by `pid`. Returns how many it hid."""
    windows_of = windows_of or _console_windows_of
    hide = hide or _hide_window
    count = 0
    for hwnd, name, visible in windows_of(pid):
        if visible and CONSOLE_CLASS in name:
            hide(hwnd)
            count += 1
    return count


def keep_console_hidden(
    pid: int,
    *,
    still_running,
    hide_once=None,
    sleep=None,
    now=None,
    budget_s: float = CONSOLE_KEEPER_BUDGET_S,
) -> int:
    """Keep the agent's console hidden for as long as it runs. Returns how many windows it hid.

    Hiding once is not enough and that is measured, not assumed: hidden 97 ms after the spawn, the
    console was visible again a second later, because conhost shows its window after we hid it.
    Run on a daemon thread by `hide_agent_console_later`; injected here so a test can tell a loop
    from a hang without a real process or a real second passing.
    """
    hide_once = hide_once or (lambda: hide_console_of(pid))
    sleep = sleep or time.sleep
    now = now or time.monotonic
    total = 0
    started = now()
    while still_running():
        if now() - started >= budget_s:
            break
        total += hide_once()
        sleep(0.05)
    return total


def agent_console() -> dict:
    """One console OF ITS OWN for the agent — the opposite of what every other child gets.

    `CREATE_NO_WINDOW` is right for a probe that spawns nothing, and it is exactly wrong here: a
    console program started by a parent with no console allocates its own, so `claude`'s Bash tool
    opened a window per command (the flash during a session). Given one console, every shell it
    starts inherits that console and opens nothing — `cmd`, `bash` and `agy` all ran silently
    inside a hidden one (measured, 2026-09-11).

    The console is created VISIBLE and hidden immediately afterwards, because `SW_HIDE` at
    creation is ignored on Windows 11. That leaves one short flash at the start of a session in
    place of one per command. `AUTOSOUND_TCC_AGENT_CONSOLE=0` puts the old behaviour back.
    """
    if os.environ.get("AUTOSOUND_TCC_AGENT_CONSOLE", "1") == "0":
        return {}
    flag = getattr(subprocess, "CREATE_NEW_CONSOLE", None)
    if not sys.platform.startswith("win") or flag is None:
        return {}
    return {"creationflags": int(flag)}


def hide_agent_console_later(pid: int) -> None:
    """Start the keeper for a freshly spawned agent. Never raises, never blocks the caller."""
    if not sys.platform.startswith("win") or not pid:
        return
    def still_running() -> bool:
        try:
            os.kill(pid, 0)
            return True
        except Exception:  # noqa: BLE001 — gone, or not ours to ask about
            return False

    try:
        threading.Thread(
            target=keep_console_hidden,
            args=(pid,),
            kwargs={"still_running": still_running},
            name=f"tcc-hide-console-{pid}",
            daemon=True,
        ).start()
    except Exception:  # noqa: BLE001 — a diagnostic thread that cannot start is not a failure
        return


def hide_console_windows() -> None:
    """Stop console windows appearing for children this process does not spawn itself.

    The Claude Agent SDK starts the `claude` CLI through `anyio.open_process`, and passes no
    creation flags. On Windows that is a console program started by a windowed process, so the
    system gives it a console — which on Windows 11 means a Windows Terminal window jumping in
    front of the app every time a session starts (user, on Windows 11, 2026-08-19: "вілітають
    вікна терміналу"). Piping stdin/stdout does not prevent it; only the flag does.

    We do not own that call, so the default is moved underneath it: `anyio.open_process` keeps its
    signature and gains `CREATE_NO_WINDOW` unless a caller asked for something. Both names are
    replaced — the one the SDK calls (`anyio.open_process`) and the one `anyio.run_process` calls
    (its defining module) — and the wrapper marks itself, so calling this twice does nothing.

    `subprocess` is patched too, and the terminal launcher opts OUT of it by asking for a console
    explicitly (`wants_a_console()`). That is the way round it has to be: every call site here
    already passes `quiet()`, and the flashes a user still sees on Windows come from the ones that
    CANNOT -- a grandchild. The agent CLI runs the method's own `python3` and `git`, and a console
    program started by a console-less parent gets a console of its own. A default that has to be
    remembered at each call site is a default that will be forgotten; this one is the process's.
    (User, Windows 11, 2026-08-22: a terminal window blinked before the main window, again after
    it, and once more on opening the version panel -- with every call site in this repo already
    passing `quiet()`.)
    """
    hide_subprocess_console_windows()
    flag = _no_window()
    if not flag:
        return
    try:
        import anyio
        from anyio._core import _subprocesses
    except Exception:  # noqa: BLE001 — no anyio, or a version that moved it: nothing to hide
        return
    original = getattr(_subprocesses, "open_process", None)
    if original is None or getattr(original, "_autosound_quiet", False):
        return

    @functools.wraps(original)
    async def open_process(*args, **kwargs):
        # This path had NO spawn log, while the user's Windows startup showed the same programs
        # going out here — so a session-time flash left no trace of who opened it (2026-09-09).
        # Logged, not stepped: a blocking gate here would freeze the SDK's own event loop.
        command = args[0] if args else kwargs.get("command")
        _note_spawn(command)
        # THE agent, on the path that actually runs a tuning session. It gets one console of its
        # own so the shells its Bash tool starts inherit one instead of each allocating a window;
        # the console is hidden the moment it exists (`agent_console`). Everything else keeps "no
        # console at all", which is right for a child that spawns nothing.
        console = agent_console() if is_agent_command(command) else {}
        if console:
            kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) \
                | console["creationflags"]
            process = await original(*args, **kwargs)
            hide_agent_console_later(getattr(process, "pid", 0))
            return process
        kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | flag
        return await original(*args, **kwargs)

    open_process._autosound_quiet = True  # type: ignore[attr-defined]
    _subprocesses.open_process = open_process
    anyio.open_process = open_process


def _spawn_label(command: object) -> str:
    """The program and its first argument, no more. A full command line carries project paths and
    model names, and the log is what people paste into an issue."""
    if isinstance(command, str):
        words = command.split()
    else:
        words = [str(part) for part in (command or [])]
    if not words:
        return ""
    return " ".join([os.path.basename(words[0]), *words[1:2]])


def _note_spawn(command: object) -> None:
    """Say in the log WHICH program this app just started. Never raises, never blocks.

    Written for one question that reading could not answer: on Windows a window flashes on the
    FIRST run of a new version and never again (measured, 2026-09-09), and nothing in this code
    base branches on a version change — so the thing that spawns it is not ours to find by
    guessing. The next first-run log names it.
    """
    try:
        from autosound_tcc.core import app_log  # here, not at module scope: app_log imports late

        label = _spawn_label(command)
        if not label:
            return
        app_log.logger().info("spawn: %s", label)
    except Exception:  # noqa: BLE001 — a diagnostic that can break a spawn is worse than none
        return


#: Where the control window writes how many steps it has released. The launcher script sets the
#: env var; the default keeps script and app agreeing without one. Off unless AUTOSOUND_TCC_STEP=1.
_STEP_LOCK = threading.Lock()
_STEP_STATE = {"served": 0}


def _reset_step_counter() -> None:
    """Back to zero — for a fresh process, and for a test that wants ticket 1 to mean the first."""
    _STEP_STATE["served"] = 0


def _step_file() -> Path:
    env = os.environ.get("AUTOSOUND_TCC_STEP_FILE")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "autosound-tcc" / "step.control"


def _read_step_release() -> int:
    """How many steps the person has allowed so far. Unreadable or absent counts as zero."""
    try:
        return int(_step_file().read_text(encoding="utf-8").strip() or "0")
    except Exception:  # noqa: BLE001 — a missing or half-written file just means "not yet"
        return 0


def _log_step(message: str) -> None:
    try:
        from autosound_tcc.core import app_log

        app_log.logger().info("%s", message)
    except Exception:  # noqa: BLE001 — a diagnostic must never be able to stop a spawn
        return


def _step_gate(
    name: object,
    *,
    is_main: Optional[Callable[[], bool]] = None,
    read_release: Optional[Callable[[], int]] = None,
    sleep: Optional[Callable[[float], None]] = None,
    now: Optional[Callable[[], float]] = None,
    budget_s: float = 300.0,
) -> None:
    """When AUTOSOUND_TCC_STEP=1, hold this spawn until a person releases it in the control window.

    The point is attribution: with each background spawn waiting for its own Enter, "a window
    flashed right after STEP 4" names the exact process, instead of a dozen going out in two
    seconds while the eye tries to keep up (the user's Windows log, 2026-09-09).

    The MAIN thread is never held. Blocking the GUI thread freezes the window, and a frozen
    top-level window is what Windows redraws as a grey "Not Responding" ghost — itself a flash,
    and the very thing being hunted. So only the background spawns (the update check, the CLI
    catalogue, the reviewer) are stepped; the few main-thread probes are logged and go straight
    through, named in the instructions so their windows are not mistaken for a finding.

    Everything is injected for the same reason `_wait_until_painted` injects its clock: so a test
    can tell a wait from a hang without a real thread or a real second passing. A forgotten Enter
    is not a hang — past `budget_s` the spawn proceeds on its own and says so.
    """
    if os.environ.get("AUTOSOUND_TCC_STEP") != "1":
        return
    is_main = is_main or (lambda: threading.current_thread() is threading.main_thread())
    if is_main():
        return
    read_release = read_release or _read_step_release
    sleep = sleep or time.sleep
    now = now or time.monotonic
    label = _spawn_label(name) or str(name)
    with _STEP_LOCK:  # one spawn waits at a time, so tickets match the order they arrive
        _STEP_STATE["served"] += 1
        ticket = _STEP_STATE["served"]
        _log_step(f"STEP {ticket}: waiting to spawn {label} — press Enter to allow")
        started = now()
        while read_release() < ticket:
            if now() - started >= budget_s:
                _log_step(f"STEP {ticket}: no Enter in {budget_s:.0f}s — proceeding with {label}")
                return
            sleep(0.05)
        _log_step(f"STEP {ticket}: allowed {label}")


def hide_subprocess_console_windows(target: Optional[type] = None) -> None:
    """The same for `subprocess`, as a process-wide default rather than a per-call kwarg.

    Idempotent, and it never overrides a caller: a `creationflags` that was passed -- including
    `wants_a_console()`'s -- wins. Called from `hide_console_windows()`, so there is one entry
    point to remember.

    The flag is read at CALL time, not at patch time, and that is the whole safety of this
    function: the wrapper installs on every platform and does nothing wherever
    `CREATE_NO_WINDOW` does not exist. Capturing it at patch time cost 74 test failures in one
    run -- `test_child.py` fakes Windows to check the SDK path, and a wrapper holding a captured
    Windows flag then poisoned every later subprocess on macOS with "creationflags is only
    supported on Windows platforms". A global patch that a test can arm and not disarm is the
    wrong shape regardless of who calls it.

    `target` exists for the test, so it can check the behaviour without patching the real class at
    all.
    """
    cls = target or subprocess.Popen
    original = cls.__init__
    if getattr(original, "_autosound_quiet", False):
        return

    # Where `creationflags` sits if somebody passes it positionally -- asked of the signature
    # rather than counted by hand, because that count is a Python-version detail (14 including
    # `self` on 3.13) and being wrong about it would silently override a caller who said what
    # they wanted.
    try:
        names = list(inspect.signature(original).parameters)
        positional = names.index("creationflags") - 1  # `self` is not in `args` below
    except (ValueError, TypeError):  # pragma: no cover -- a signature we do not recognise
        positional = 13

    @functools.wraps(original)
    def __init__(self, *args, **kwargs):  # noqa: N807 (patching a dunder on purpose)
        command = args[0] if args else kwargs.get("args")
        _note_spawn(command)
        _step_gate(command)  # held here, before the child exists, when AUTOSOUND_TCC_STEP=1
        flag = _no_window()
        # The agent's CLI gets a console of its own to hand DOWN, exactly as in the async path:
        # those programs spawn `node`, `git` and `gh` themselves, and a parent with NO console
        # makes each grandchild allocate one — which is a window. The startup log from the user's
        # Windows machine (2026-09-09) shows them going out this ordinary way too: `agy models`
        # twice and `claude.EXE auth`, nine processes in two seconds.
        console = agent_console() if is_agent_command(command) else {}
        if flag and not kwargs.get("creationflags") and len(args) <= positional:
            kwargs["creationflags"] = console["creationflags"] if console else flag
        started = original(self, *args, **kwargs)
        if console:
            hide_agent_console_later(getattr(self, "pid", 0))
        return started

    __init__._autosound_quiet = True  # type: ignore[attr-defined]
    cls.__init__ = __init__  # type: ignore[method-assign]
