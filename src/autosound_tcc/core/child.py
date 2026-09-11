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


#: Whether THIS process owns a console we allocated and hid (`open_app_console`). Windows only,
#: and false everywhere else by construction.
_APP_CONSOLE = {"ours": False}


def have_app_console() -> bool:
    """Does this process own one hidden console that its children can inherit?"""
    return bool(_APP_CONSOLE["ours"])


def _alloc_console() -> bool:
    if not ctypes.windll.kernel32.AllocConsole():
        return False
    try:
        ctypes.windll.kernel32.SetConsoleTitleW("Autosound TCC")
    except Exception:  # noqa: BLE001 — a title is decoration; the console is the point
        pass
    return True


#: `GetStdHandle`'s argument for standard output. Named rather than spelled `-11` at the call,
#: because a bare negative literal next to a handle is the kind of thing a reader silently "fixes".
_STD_OUTPUT_HANDLE = -11


def _write_to_console(message: str, *, kernel32=None) -> None:
    """Straight to the console handle, not through `sys.stdout`: a GUI process may not have one.

    The types are declared for exactly the reason they are declared around `OpenProcess` below,
    and this call site was missed when that one was fixed: a HANDLE is pointer-sized, ctypes
    defaults a return to a C int, and a 64-bit handle comes back with its top half gone. Passing
    an undeclared one back IN truncates it a second time.

    What it would cost here is one line of startup banner going missing, with no exception and no
    log — which is precisely why nobody would ever have found it. Same class, smaller blast.
    """
    kernel32 = kernel32 or ctypes.windll.kernel32
    text = message + "\r\n"
    written = ctypes.c_ulong(0)
    kernel32.GetStdHandle.restype = ctypes.c_void_p  # a handle, not a C int
    handle = kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
    kernel32.WriteConsoleW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p,
    ]
    kernel32.WriteConsoleW(handle, text, len(text), ctypes.byref(written), None)


def _hide_own_console() -> int:
    kernel32 = ctypes.windll.kernel32
    kernel32.GetConsoleWindow.restype = ctypes.c_void_p  # a handle, not a C int
    hwnd = kernel32.GetConsoleWindow()
    if not hwnd:
        return 0
    _hide_window(hwnd)
    return 1


#: What `AUTOSOUND_TCC_FLASH_PROBE` runs, per name. Nothing here does any work — each is a real
#: program started exactly the way TCC starts its own, which is the only thing being measured.
_FLASH_PROBES = {
    "git": ["git", "--version"],
    "python": [None, "-c", "pass"],       # None is filled with `script_interpreter()`
    "claude": ["claude", "--version"],
    "cmd": ["cmd.exe", "/c", "exit"],
}

#: How many times each probe runs, per moment. Three and two, because a COUNT is a far stronger
#: answer than a yes/no: if the Arbiter sees three flashes and then two, the flashes are this
#: command; if they still see one and one, they are not, and no log had to be believed.
FLASH_PROBE_COUNTS = {"before": 3, "after": 2}


def flash_probe(when: str, *, run=None, environ=None) -> int:
    """Start a chosen program N times so a person can COUNT the flashes. Returns how many ran.

    The Arbiter's idea, and a better instrument than either watcher: every window watch so far has
    polled the desktop, and a `git rev-parse` lives 30-80 ms — shorter than one pass. One of those
    logs carried `proc=Idle`, a window whose process had already died before the poll named it.
    So "no window was recorded" was never evidence that no window appeared. An eye counting to
    three has no such blind spot.

    Off unless `AUTOSOUND_TCC_FLASH_PROBE` names a probe, and it never runs in an ordinary build.
    """
    environ = os.environ if environ is None else environ
    name = (environ.get("AUTOSOUND_TCC_FLASH_PROBE") or "").strip().lower()
    argv = _FLASH_PROBES.get(name)
    if not argv:
        return 0
    argv = [script_interpreter() if part is None else part for part in argv]
    run = run or (lambda a: subprocess.run(a, capture_output=True, **quiet()))
    done = 0
    for _ in range(FLASH_PROBE_COUNTS.get(when, 0)):
        try:
            run(argv)
        except Exception:  # noqa: BLE001 — a probe that cannot start is not a crash
            continue
        done += 1
    return done


#: The child whose console we borrow. Module state because it must outlive this call: kill it and
#: the console goes with it, taking every inheriting child's output handle along.
_CONSOLE_HOLDER: dict = {"proc": None}

#: How long to wait for the holder's console to exist. It is created with the process, but
#: `AttachConsole` can lose a race with a child that has only just been handed its handles.
_HOLDER_WAIT_S = 2.0


def _spawn_console_holder():
    """A process that exists only to own a console with no window. `None` if it cannot start."""
    flag = getattr(subprocess, "CREATE_NO_WINDOW", None)
    if not flag:
        return None
    try:
        # `cmd /k` with its input on a pipe nobody writes to: it waits for a command forever,
        # costs about a megabyte, and starts instantly. `DEVNULL` would hand it EOF and it would
        # exit — taking the console we are borrowing with it.
        return subprocess.Popen(
            ["cmd.exe", "/k"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=int(flag))
    except OSError:
        return None


def borrow_windowless_console(*, spawn=None, attach=None, free=None, sleep=None, now=None) -> bool:
    """Join a console that NEVER HAD A WINDOW, instead of making one and hiding it.

    This is the answer to the flash itself rather than to who caused it. `AllocConsole` on
    Windows 11 always produces a VISIBLE console — `SW_HIDE` at creation is ignored, measured
    twice — so owning one means letting it appear and hiding it afterwards. That flash is not a
    child's window. It is ours, and no amount of hiding gets in front of it.

    `CREATE_NO_WINDOW` does not mean what its name suggests: the child gets a real console, and
    that console has **no window at all**. Nothing is ever shown, so there is nothing to hide.
    `AttachConsole` lets this process join it, and from then on every child and grandchild
    inherits a console that cannot flash, because it has no window to flash with.

    Returns False on anything unexpected, and the caller falls back to allocating one.
    """
    if not sys.platform.startswith("win"):
        return False
    spawn = spawn or _spawn_console_holder
    now = now or time.monotonic
    sleep = sleep or time.sleep
    if attach is None or free is None:
        # Asked for ONLY when a real one is needed. Reaching for `windll` even when the caller has
        # handed both in makes the whole function untestable off Windows — the seam is there to be
        # used, and a seam the code steps around is not a seam.
        try:
            kernel32 = ctypes.windll.kernel32
            if attach is None:
                # Declared, for the reason this file declares them everywhere: an undeclared call
                # gets a C int, and a wrong type fails silently — straight back to the flash.
                kernel32.AttachConsole.argtypes = [ctypes.c_uint32]
                kernel32.AttachConsole.restype = ctypes.c_int
                attach = kernel32.AttachConsole
            free = free or kernel32.FreeConsole
        except Exception:  # noqa: BLE001 — no windll: nothing to borrow
            return False
    proc = spawn()
    if proc is None:
        return False
    _CONSOLE_HOLDER["proc"] = proc
    try:
        free()  # we have none under pythonw, but saying so costs nothing and makes the state sure
    except Exception:  # noqa: BLE001 — already console-less, which is the state we want
        pass
    deadline = now() + _HOLDER_WAIT_S
    while True:
        try:
            if attach(int(proc.pid)):
                return True
        except Exception:  # noqa: BLE001 — a pid that died, a console that is not ours to join
            return False
        if now() >= deadline:
            return False
        sleep(0.02)


def open_app_console(message: str, *, alloc=None, write=None, hide=None, defer=None) -> bool:
    """Give this process ONE console, say what it is, and hide it. Windows only; False elsewhere.

    Per-agent consoles work, but they pay the same price every time a session starts: a console
    cannot be created already hidden (`SW_HIDE` at creation is ignored on Windows 11, measured
    twice), so each one flashes before we can hide it. One console for the PROCESS pays it once,
    at startup, and every child and grandchild inherits it instead of allocating its own — `cmd`,
    `bash`, `agy` and `git` all ran silently inside a hidden one (measured 2026-09-11).

    It SAYS something first, on purpose. A black rectangle for a third of a second reads as a
    glitch; the same rectangle with a line in it reads as the application starting, which is what
    it is. That was the Arbiter's call, and it is the better one.

    Claimed only when it really was allocated: pretending otherwise would switch off
    `CREATE_NO_WINDOW` for every child and hand the machine a window per probe, which is worse
    than the flash this replaces.
    """
    _APP_CONSOLE["ours"] = False
    if not sys.platform.startswith("win"):
        return False
    # Better than allocating one, when it works: a BORROWED console never had a window, so there
    # is nothing to hide and nothing to flash. Falls through to the old way when it does not.
    if borrow_windowless_console():
        _APP_CONSOLE["ours"] = True
        hide_agent_console_later(os.getpid(), budget_s=APP_CONSOLE_KEEPER_BUDGET_S)
        return True
    alloc = alloc or _alloc_console
    write = write or _write_to_console
    hide = hide or _hide_own_console
    try:
        if not alloc():
            return False
        write(message)
    except Exception:  # noqa: BLE001 — no console is the state we were already in
        return False
    _APP_CONSOLE["ours"] = True
    # HELD long enough to read, then hidden — and that is the Arbiter's call, not a compromise.
    # Reaching here means the console could not be borrowed and one had to be made, so it WILL be
    # seen. A black rectangle for a third of a second reads as a glitch and makes a person doubt
    # the application; the same rectangle, legible, saying what is starting, reads as a launch.
    # Given that it cannot be hidden in time, the honest move is to make it worth the glance.
    #
    # Hidden from a thread rather than inline: the window is up while the app loads, so the wait
    # costs the user nothing. The keeper starts after the hide, because starting it first would
    # hide the console immediately and there would be nothing to read.
    (defer or _spawn_daemon)(_hide_after_showing,
                             {"hide": hide, "seconds": APP_CONSOLE_VISIBLE_S})
    return True


def _hide_after_showing(*, hide, seconds: float, sleep=None, keeper=None) -> None:
    """Leave the console up for a moment, hide it, then keep it hidden for the session."""
    (sleep or time.sleep)(seconds)
    try:
        hide()
    except Exception:  # noqa: BLE001 — a console that will not hide is still ours to lend
        pass
    # And KEEP it hidden. Hiding once is not enough for a console we lend to everything we start:
    # `claude` takes the console it inherits, retitles it and resizes it to its own buffer, and
    # that makes it visible again — a console owned by our process, titled `claude`, `990x396`
    # (measured 2026-09-11). That is the flash that appears just after the main window.
    (keeper or hide_agent_console_later)(os.getpid(), budget_s=APP_CONSOLE_KEEPER_BUDGET_S)


def quiet() -> dict:
    """Keyword arguments for a `subprocess` call that must not wait for input or show a window.

    With a console of our own, the window half is DELIBERATELY absent: `CREATE_NO_WINDOW` denies
    the child a console, and a child denied one allocates its own — the very flash we removed.
    Inheriting ours is what keeps it silent.
    """
    kwargs: dict = {"stdin": subprocess.DEVNULL}
    if have_app_console():
        return kwargs
    flag = _no_window()
    if flag:
        kwargs["creationflags"] = flag
    return kwargs


def flags() -> dict:
    """The window half of `quiet()` alone, for a child whose stdin the caller is holding.

    A long-lived agent process is driven THROUGH its stdin — `asyncio.create_subprocess_exec` with
    a pipe — so it cannot take `DEVNULL`, but it still has no business opening a console.

    Empty once we own one: see `quiet()` for why denying a child a console is what makes it open
    a window.
    """
    if have_app_console():
        return {}
    flag = _no_window()
    return {"creationflags": flag} if flag else {}


def script_interpreter(*, executable: Optional[str] = None, exists=None) -> str:
    """The interpreter a helper SCRIPT is run with: console-subsystem, even though we are not.

    TCC is a GUI application, so `sys.executable` is `pythonw.exe` — a WINDOWED binary with no
    console at all, and `CREATE_NO_WINDOW` means nothing to it. Anything such a script goes on to
    run therefore has no console to inherit and allocates its own, which is a window on screen.

    That is the whole of the flashing that outlived three wrong theories. Every visible git console
    in a session followed a `pythonw.exe … rew_tool\\state\\process.py` spawn by 330-500 ms, all
    seven of them, and the bursts of them were the saving-and-closing the user kept reporting
    (measured 2026-09-11). `python.exe` under the same flag DOES have a console, simply one that is
    never shown, and every child and grandchild inherits it instead of making its own.

    Falls back to whatever it was given: a script that runs with a flash beats one that cannot run.
    """
    executable = executable or sys.executable
    if not sys.platform.startswith("win"):
        return executable
    exists = exists or (lambda path: Path(path).exists())
    # Split by hand rather than with `Path`, for the same reason `is_agent_command` does: these
    # are WINDOWS paths and the tests that check them run on macOS, where `pathlib` does not treat
    # a backslash as a separator and hands back the whole string as the file name.
    name = executable.replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower() != "pythonw.exe":
        return executable
    console = executable[: len(executable) - len(name)] + "python.exe"
    return console if exists(console) else executable


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

#: How long the keeper fights for the agent's console. conhost shows the window back ONCE, about a
#: second after the first hide, and then leaves it alone — measured, with the first hide landing at
#: 172-250 ms — so a few seconds covers it with room to spare.
#:
#: A safety net now, not the rule: the keeper ends with the process (`process_is_running`). It was
#: the rule for one build, because the first liveness probe was `os.kill` and that had to go — and
#: eight seconds turned out to be too short. Measured: `agy`'s console was hidden, then shown again
#: 420 ms later, by which time the keeper had left, and the window stayed up for the session.
CONSOLE_KEEPER_BUDGET_S = 600.0

#: Rights enough to ASK about a process and nothing more. Deliberately NOT `PROCESS_TERMINATE`:
#: the whole reason `process_is_running` exists is that the obvious probe terminates.
_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x00000102


def process_is_running(pid: int, *, kernel32=None) -> bool:
    """Is this process still alive? Asks Windows and signals nothing. False everywhere else.

    `os.kill(pid, 0)` is the POSIX way to ask and the Windows way to kill, so it is not used here
    and a test forbids it. `WaitForSingleObject` with a zero timeout answers immediately: still
    waiting means still running.

    **The types are declared, and that is not tidiness.** With no `restype` ctypes hands back a C
    int, so a 64-bit handle arrives with its top half gone; `WaitForSingleObject` then refuses the
    mangled handle, this reads the refusal as "already gone", and the keeper it drives leaves on
    its very first pass. Measured before it was found: four sessions with ZERO hide transitions
    while `agy` held a console on screen, including the one at shutdown. The app console went on
    hiding correctly throughout, because that path opens no handle — which is precisely why this
    looked like it was working.

    `c_void_p` rather than `wintypes.HANDLE` on purpose: `ctypes.wintypes` cannot even be imported
    off Windows, and these lines have to run in a suite that lives on macOS.
    """
    if not sys.platform.startswith("win") or not pid:
        return False
    try:
        kernel32 = kernel32 or ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(_SYNCHRONIZE, False, int(pid))
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001 — a process we cannot ask about is one we stop hiding for
        return False


def _console_windows_of(pid: int) -> list:
    """`(hwnd, class, visible)` for every top-level window owned by `pid`. Empty off Windows."""
    if not sys.platform.startswith("win"):
        return []
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        # Declared, like every other handle call here: undeclared, a 64-bit window handle is passed
        # as a C int and loses its top half without a word (see `process_is_running`).
        user32.IsWindowVisible.restype = ctypes.c_int
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,
                                                    ctypes.POINTER(wintypes.DWORD)]
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
        user32 = ctypes.windll.user32
        # Declared for the same reason as in `process_is_running`: an undeclared window handle is
        # passed as a C int and a 64-bit one loses its top half, silently.
        user32.ShowWindow.restype = ctypes.c_int
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.ShowWindow(hwnd, 0)  # SW_HIDE
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
        elapsed = now() - started
        if elapsed >= budget_s:
            break
        total += hide_once()
        # Tight while the window is still being fought over, then slow: conhost shows it back
        # within a second or two, and after that this only has to outlast the process without
        # spinning a core for the length of a tuning session.
        sleep(0.05 if elapsed < 5.0 else 0.5)
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
    if have_app_console():
        # Ours is already there and already hidden: the agent inherits it, and asking for a second
        # one would buy nothing but the flash that creating a console always costs.
        return {}
    flag = getattr(subprocess, "CREATE_NEW_CONSOLE", None)
    if not sys.platform.startswith("win") or flag is None:
        return {}
    return {"creationflags": int(flag)}


def _spawn_daemon(target, kwargs: dict) -> None:
    threading.Thread(target=target, kwargs=kwargs, name="tcc-hide-console", daemon=True).start()


#: How long a console we were FORCED to make stays readable before it is hidden. It is going to
#: be seen either way — `SW_HIDE` at creation is ignored on Windows 11 — so it is shown on
#: purpose, long enough to read, instead of flickering past as an unexplained black rectangle.
APP_CONSOLE_VISIBLE_S = 1.2

#: The keeper for OUR OWN console runs as long as the application does, not for a few seconds.
#: A child can show it back at any point in a session — `claude` retitles the console it inherits
#: and makes it visible — so this one has to outlast the agent rather than the spawn.
APP_CONSOLE_KEEPER_BUDGET_S = 43200.0


def hide_agent_console_later(pid: int, *, spawn=None, budget_s: Optional[float] = None) -> None:
    """Start the keeper for a freshly spawned agent. Never raises, never blocks the caller.

    **Deliberately not liveness-checked.** The first version asked `os.kill(pid, 0)` — the POSIX
    idiom for "is this still alive" — which on Windows does not answer the question but carries it
    out: every signal except CTRL_C/CTRL_BREAK goes to `TerminateProcess`.

    What that cost is measured, on the user's machine, 2026-09-11. The call raised before it could
    terminate anything, the keeper read the exception as "already gone" and left on its very first
    check, and the agent's console was never hidden once in a whole session — while the commands
    around it had already stopped flashing, so the console itself was doing its job. The agent
    survived by that accident alone. Bounded by the budget instead, which is all this ever needed.
    """
    if not sys.platform.startswith("win") or not pid:
        return
    spawn = spawn or _spawn_daemon
    try:
        spawn(keep_console_hidden, {
            "pid": pid,
            "still_running": lambda: process_is_running(pid),
            "budget_s": budget_s or CONSOLE_KEEPER_BUDGET_S,
        })
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
        console = agent_console() if is_agent_command(command) else {}
        if console:
            # No console of ours to inherit, so the agent is given one to hand down.
            kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) \
                | console["creationflags"]
        elif not have_app_console():
            # Denied a console, which is right for a child that spawns nothing — but ONLY while we
            # have none ourselves. With an app console this line is exactly backwards: a child
            # denied a console allocates its own, and that is the window (measured on probe22,
            # where `agy` opened one while `git` and `claude` inherited ours and stayed silent).
            kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | flag
        process = await original(*args, **kwargs)
        if is_agent_command(command):
            # Watched even when it was handed nothing: `agy` allocates a console of ITS own,
            # sometimes, and that one is nobody's to hide but ours.
            hide_agent_console_later(getattr(process, "pid", 0))
        return process

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
        if not kwargs.get("creationflags") and len(args) <= positional:
            if console:
                kwargs["creationflags"] = console["creationflags"]
            elif flag and not have_app_console():
                # Only while we have no console of our own — see the async path for why denying
                # one is what makes a child open a window.
                kwargs["creationflags"] = flag
        started = original(self, *args, **kwargs)
        if is_agent_command(command):
            hide_agent_console_later(getattr(self, "pid", 0))
        return started

    __init__._autosound_quiet = True  # type: ignore[attr-defined]
    cls.__init__ = __init__  # type: ignore[method-assign]
