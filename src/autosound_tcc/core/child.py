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

import functools
import inspect
import os
import subprocess
import sys
from typing import Optional


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


def hidden_console() -> dict:
    """A console for the agent process that nobody ever sees — for its GRANDCHILDREN to inherit.

    The problem this is for (tcc#13): `CREATE_NO_WINDOW` gives the agent NO console at all, which
    is right for a short probe and wrong for a long-running CLI that spawns dozens of console
    programs itself. A console program started by a parent with no console gets a NEW console, and
    a new console is a new window — so TCC's own correct choice at its level produced the flashing
    one level down, on `python`, `git` and `gh` calls TCC never makes. "Blinking with terminal and
    win windows", continuously, for a whole working session.

    So: one console, created hidden (`CREATE_NEW_CONSOLE` + `STARTUPINFO` with `SW_HIDE`), which
    every grandchild attaches to instead of allocating its own. Nothing is drawn because the
    console window is never shown.

    **Not verified on Windows.** It is written from the documented behaviour of console
    inheritance and has been run on nothing but a Mac, where every branch here is empty by
    definition. The corner cases are real — a child that calls `AllocConsole` itself, a
    non-console binary in the chain — and this note stays until somebody watches it on the machine
    that has the problem.

    **Which is why it has a switch.** `AUTOSOUND_TCC_AGENT_CONSOLE=0` puts the old behaviour back
    (no console at all for the agent either). The failure mode this can have is worse than the one
    it fixes: `SW_HIDE` is exactly the kind of hint that may quietly not take, and then the console
    is VISIBLE for the whole session instead of blinking for a moment. A person who meets that must
    be able to turn it off where they are, not wait for a build — the same escape hatch the MCP
    server and the splash already carry.
    """
    # DEFAULT OFF since 2026-09-09, on measurement rather than argument.
    #
    # The mechanism was written from the documented behaviour of console inheritance and run on
    # nothing but a Mac, where every branch of it is empty. On the machine that has the problem it
    # does the opposite of its purpose: a desktop-wide window watch caught
    #
    #     proc=git class=ConsoleWindowClass size=930x516 layered title='…\Git\cmd\git.exe'
    #
    # half a second after the main window — the user's "and once after". `SW_HIDE` is a hint, the
    # note above always said so, and here it does not take: instead of preventing a window the
    # hidden console CREATES one.
    #
    # The same pair had already been measured and not read: on probe2 the ordinary start showed
    # ONE window and the same start with this switch off showed NONE.
    #
    # So the default is off, and the switch now turns it ON for anybody who wants to test whether
    # a newer Windows behaves as the documentation says.
    if os.environ.get("AUTOSOUND_TCC_AGENT_CONSOLE", "0") != "1":
        return {}
    new_console = getattr(subprocess, "CREATE_NEW_CONSOLE", None)
    if not sys.platform.startswith("win") or new_console is None:
        return {}
    info_cls = getattr(subprocess, "STARTUPINFO", None)
    if info_cls is None:
        # A Windows without the structure is not a Windows this can hide a console on. The console
        # would be VISIBLE, which is worse than the flashing it is meant to stop.
        return {}
    info = info_cls()
    info.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    info.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {"creationflags": int(new_console), "startupinfo": info}


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

    hidden = hidden_console()

    @functools.wraps(original)
    async def open_process(*args, **kwargs):
        # The agent's CLI gets a hidden console of its own to hand DOWN to the `python`, `git` and
        # `gh` it runs (tcc#13); everything else keeps "no console at all", which is right for a
        # child that spawns nothing.
        if hidden and is_agent_command(args[0] if args else kwargs.get("command")):
            kwargs.setdefault("startupinfo", hidden["startupinfo"])
            kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) \
                | hidden["creationflags"]
            return await original(*args, **kwargs)
        kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | flag
        return await original(*args, **kwargs)

    open_process._autosound_quiet = True  # type: ignore[attr-defined]
    _subprocesses.open_process = open_process
    anyio.open_process = open_process


def _note_spawn(command: object) -> None:
    """Say in the log WHICH program this app just started. Never raises, never blocks.

    Written for one question that reading could not answer: on Windows a window flashes on the
    FIRST run of a new version and never again (measured, 2026-09-09), and nothing in this code
    base branches on a version change — so the thing that spawns it is not ours to find by
    guessing. The next first-run log names it.

    Two words only, the program and its first argument. A full command line carries project paths
    and model names, and this file is what people paste into an issue.
    """
    try:
        from autosound_tcc.core import app_log  # here, not at module scope: app_log imports late

        if isinstance(command, str):
            words = command.split()
        else:
            words = [str(part) for part in (command or [])]
        if not words:
            return
        name = os.path.basename(words[0])
        app_log.logger().info("spawn: %s", " ".join([name, *words[1:2]]))
    except Exception:  # noqa: BLE001 — a diagnostic that can break a spawn is worse than none
        return


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
        flag = _no_window()
        if flag and not kwargs.get("creationflags") and len(args) <= positional:
            # The agent's CLI gets a console of its own to hand DOWN, exactly as in the async
            # path: those programs spawn `node`, `git` and `gh` themselves, and a parent with NO
            # console makes each grandchild allocate one — which is a window. This treatment was
            # wired into `hide_console_windows`'s anyio patch only, while the startup log from the
            # user's Windows machine (2026-09-09) shows the same programs going out the ordinary
            # way: `agy models` twice and `claude.EXE auth`, nine processes in two seconds.
            hidden = hidden_console() if is_agent_command(command) else {}
            if hidden:
                kwargs["creationflags"] = hidden["creationflags"]
                kwargs.setdefault("startupinfo", hidden["startupinfo"])
            else:
                kwargs["creationflags"] = flag
        return original(self, *args, **kwargs)

    __init__._autosound_quiet = True  # type: ignore[attr-defined]
    cls.__init__ = __init__  # type: ignore[method-assign]
