"""A child process that never answers, for the code that has to give up on one (tcc#132).

On Windows a timed-out `subprocess.run` kills the ONE process and then calls `communicate()` with
no bound, and that waits for the pipes: a grandchild -- the `csc.exe` that PowerShell's `Add-Type`
starts, the `node.exe` behind an npm shim -- inherits them and holds them open after its parent is
gone. So the child here never finishes, its pipes stay held after any kill, and where the real one
would block for good it raises `WaitedForever`: a test sees the hang as an error instead of sitting
in it.

Nothing is started: no process exists, real or hung.
"""

from __future__ import annotations

import itertools
import subprocess
import sys
import threading

_PIDS = itertools.count(4200)


class WaitedForever(BaseException):
    """Where the real call would never return. A `BaseException`, so that the `except Exception`
    around a probe cannot swallow it and pass it off as an answer."""


class HungChild:
    """A child that never finishes, with a grandchild that outlives every kill and holds its
    pipes. `timeouts` is every bound it was waited on with, in order."""

    def __init__(self, args) -> None:
        self.args = args
        self.pid = next(_PIDS)
        self.killed = False
        self.timeouts: list = []

    def communicate(self, input=None, timeout=None):
        self.timeouts.append(timeout)
        if timeout is None:
            raise WaitedForever(f"communicate() with no bound on {self.args[0]}: a grandchild "
                                "holds its pipes, and this never returns")
        raise subprocess.TimeoutExpired(self.args, timeout)

    def kill(self) -> None:
        self.killed = True

    terminate = kill

    def poll(self):
        return 1 if self.killed else None

    def wait(self, timeout=None):
        if self.killed:
            return 1
        if timeout is None:
            raise WaitedForever(f"wait() with no bound on {self.args[0]}, never killed")
        raise subprocess.TimeoutExpired(self.args, timeout)

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


class _Answered:
    """`taskkill`: done at once, and nothing to say."""

    returncode = 0

    def __init__(self, args) -> None:
        self.args = args
        self.pid = next(_PIDS)

    def communicate(self, input=None, timeout=None):
        return "", ""

    def poll(self) -> int:
        return 0

    def wait(self, timeout=None) -> int:
        return 0

    def kill(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


class Spawns:
    """Stands in for `subprocess.Popen`: every child it starts hangs, except `taskkill`, which
    answers at once. Each spawn's arguments and keywords are written down, and the thread it
    came from."""

    def __init__(self) -> None:
        self.hung: list[HungChild] = []
        self.taskkills: list[list[str]] = []
        self.calls: list[tuple[list, dict]] = []
        self.threads: list[threading.Thread] = []

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        self.threads.append(threading.current_thread())
        if list(args)[:1] == ["taskkill"]:
            self.taskkills.append(list(args))
            return _Answered(args)
        hung = HungChild(args)
        self.hung.append(hung)
        return hung


def install(monkeypatch, *, windows: bool = True) -> Spawns:
    """Every `Popen` from here on hangs. `windows` makes this Windows as far as the code asks: its
    own platform check, and `subprocess.run`'s, whose timeout branch is per platform -- the hang
    is in the Windows one, which calls `communicate()` again, unbounded, after the kill."""
    spawns = Spawns()
    monkeypatch.setattr(subprocess, "Popen", spawns)
    if windows:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(subprocess, "_mswindows", True)
    return spawns
