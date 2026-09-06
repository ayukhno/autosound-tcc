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

    assert asyncio.run(anyio.open_process(["python3"], stdin=-1)) == "process"
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


class _FakeStartupInfo:
    def __init__(self) -> None:
        self.dwFlags = 0
        self.wShowWindow = None


def _as_windows(monkeypatch) -> None:
    """Windows, as far as `child` can tell. The flags are faked, not the OS — every case here is a
    Windows one and none of them can run there."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010, raising=False)
    monkeypatch.setattr(subprocess, "STARTUPINFO", _FakeStartupInfo, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)


def test_the_agent_gets_one_hidden_console_for_its_grandchildren_to_inherit(monkeypatch):
    """`CREATE_NO_WINDOW` gives the agent NO console, and a console program started by a parent
    with no console gets a NEW one — so every `python`, `git` and `gh` the agent runs opened its
    own window. TCC's correct choice at its level produced the flashing one level down (tcc#13)."""
    _as_windows(monkeypatch)

    kwargs = child.hidden_console()

    assert kwargs["creationflags"] == 0x00000010, "a console of its own"
    assert kwargs["startupinfo"].dwFlags & 0x00000001
    assert kwargs["startupinfo"].wShowWindow == 0, "and it is never shown"


def test_only_the_agents_own_cli_is_given_a_console():
    """Narrow on purpose: a child that spawns nothing has no use for a console, and one that is
    handed a console it then shows is the bug this is fixing, backwards."""
    assert child.is_agent_command(["claude", "--print"])
    assert child.is_agent_command([r"C:\Users\x\claude.cmd"])
    assert child.is_agent_command(["/opt/homebrew/bin/omp"])
    assert not child.is_agent_command(["python3", "-c", "print(1)"])
    assert not child.is_agent_command(["git", "status"])
    assert not child.is_agent_command("")


def test_the_sdk_gives_the_agent_the_hidden_console_and_everyone_else_no_window(monkeypatch):
    import anyio
    from anyio._core import _subprocesses

    seen: list = []

    async def fake_open_process(*args, **kwargs):
        seen.append(kwargs)
        return "process"

    monkeypatch.setattr(_subprocesses, "open_process", fake_open_process)
    monkeypatch.setattr(anyio, "open_process", fake_open_process)
    _as_windows(monkeypatch)

    child.hide_console_windows()
    asyncio.run(anyio.open_process(["claude", "--print"], stdin=-1))
    asyncio.run(anyio.open_process(["git", "status"], stdin=-1))

    agent, other = seen
    assert agent["creationflags"] & 0x00000010 and "startupinfo" in agent
    assert other["creationflags"] & 0x08000000 and "startupinfo" not in other
