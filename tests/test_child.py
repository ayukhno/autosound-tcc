"""How TCC starts a process it only wants an answer from — and what a person sees when it does.

Every case here is a Windows one, because that is the only platform where a child process can put
a window in front of the app. They run on any platform: the flag is faked, not the OS.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

from autosound_tcc.core import child


def test_a_probe_gets_no_stdin_to_wait_on():
    """A CLI that finds a terminal on stdin may wait for input nobody will type."""
    assert child.quiet()["stdin"] == subprocess.DEVNULL
def test_the_sdk_s_own_children_get_the_no_window_flag(monkeypatch):
    """The console window a user sees is opened by a process TCC does not spawn itself: the Agent
    SDK starts `claude` through `anyio.open_process` and passes no creation flags. The default is
    moved underneath it rather than the call being rewritten."""
    import anyio
    from anyio._core import _subprocesses

    seen: dict = {}

    async def fake_open_process(*args, **kwargs):
        seen.update(kwargs)
        return "process"

    monkeypatch.setattr(_subprocesses, "open_process", fake_open_process)
    monkeypatch.setattr(anyio, "open_process", fake_open_process)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    child.hide_console_windows()

    assert asyncio.run(anyio.open_process(["claude"], stdin=-1)) == "process"
    assert seen["creationflags"] & 0x08000000
    assert seen["stdin"] == -1, "the SDK's own arguments must survive"


def test_hiding_console_windows_twice_does_not_stack_wrappers(monkeypatch):
    """Called once at startup, but a second call must be a no-op rather than another layer."""
    import anyio
    from anyio._core import _subprocesses

    async def fake_open_process(*args, **kwargs):
        return "process"

    monkeypatch.setattr(_subprocesses, "open_process", fake_open_process)
    monkeypatch.setattr(anyio, "open_process", fake_open_process)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    child.hide_console_windows()
    once = anyio.open_process
    child.hide_console_windows()

    assert anyio.open_process is once


def test_nothing_is_patched_away_from_windows(monkeypatch):
    """On macOS and Linux there is no flag and no window — the module must leave anyio alone."""
    import anyio

    monkeypatch.setattr(sys, "platform", "darwin")
    before = anyio.open_process

    child.hide_console_windows()

    assert anyio.open_process is before


def test_a_piped_child_gets_the_flag_without_losing_its_stdin():
    """`quiet()` would close the stdin an agent session is driven through; `flags()` is the rest."""
    assert "stdin" not in child.flags()
