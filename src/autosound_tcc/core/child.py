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
import subprocess
import sys


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

    Nothing here touches `subprocess`: `core/terminal_launcher` opens a terminal on purpose, and a
    blanket patch would take that window away too.
    """
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
        kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | flag
        return await original(*args, **kwargs)

    open_process._autosound_quiet = True  # type: ignore[attr-defined]
    _subprocesses.open_process = open_process
    anyio.open_process = open_process
