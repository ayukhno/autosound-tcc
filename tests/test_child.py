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
    monkeypatch.setenv("AUTOSOUND_TCC_AGENT_CONSOLE", "1")  # off by default since 2026-09-09

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
    monkeypatch.setenv("AUTOSOUND_TCC_AGENT_CONSOLE", "1")  # the path this test is about

    child.hide_console_windows()
    asyncio.run(anyio.open_process(["claude", "--print"], stdin=-1))
    asyncio.run(anyio.open_process(["git", "status"], stdin=-1))

    agent, other = seen
    assert agent["creationflags"] & 0x00000010 and "startupinfo" in agent
    assert other["creationflags"] & 0x08000000 and "startupinfo" not in other


def test_the_hidden_console_is_off_until_somebody_asks_for_it(monkeypatch):
    """`SW_HIDE` is a hint, and on the machine that has the problem it does not take: a desktop
    window watch caught `proc=git class=ConsoleWindowClass 930x516` half a second after the main
    window (2026-09-09). So the mechanism CREATES the window it was written to prevent, and the
    default is off — with the switch left in place for anybody testing a newer Windows."""
    _as_windows(monkeypatch)

    assert child.hidden_console() == {}, "off by default"

    monkeypatch.setenv("AUTOSOUND_TCC_AGENT_CONSOLE", "1")

    assert child.hidden_console(), "and on for whoever asks"


def test_by_default_the_agent_is_treated_like_every_other_child(monkeypatch):
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

    # No switch set: this IS the default now, and the agent is treated like every other child.
    assert seen[0]["creationflags"] & 0x08000000 and "startupinfo" not in seen[0]


def test_every_child_this_app_starts_is_named_in_the_log(tmp_path, monkeypatch):
    """TCC-006. A window flashes on the FIRST run of a new version and never again — measured on
    Windows, 2026-09-09 — and nothing in this code base runs once per version, so the thing that
    spawns it is not ours to find by reading. So stop reading: every child TCC starts says its own
    name in the log, and the next first-run log names the culprit instead of us guessing at it.

    Truncated to the program and its first argument: the point is WHICH program, and a full
    command line would put project paths and model names in a file people paste into issues."""
    from autosound_tcc.core import app_log, child

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(app_log, "_log_path", None, raising=False)
    path = app_log.setup()

    class _Fake:
        def __init__(self, *args, **kwargs):
            pass

    child.hide_subprocess_console_windows(target=_Fake)
    _Fake(["git", "ls-remote", "--tags", "https://example.invalid/secret-repo.git"])

    said = path.read_text(encoding="utf-8")
    assert "spawn: git ls-remote" in said, said
    assert "secret-repo" not in said, "the rest of the line is not the log's business"


def test_an_agent_cli_started_the_ordinary_way_gets_the_hidden_console_too(monkeypatch):
    """`child.hidden_console` was written for the agent's CLI because those spawn console programs
    of their own, and a parent with NO console makes each grandchild allocate one. It was wired
    into the ASYNC path only — and the startup log from the user's Windows machine (2026-09-09)
    shows the same programs going out the ordinary way: `agy models` twice and `claude.EXE auth`,
    nine processes in two seconds.

    Same programs, same reason, so the same treatment. Everything else keeps "no console at all",
    which is right for a child that spawns nothing."""
    from autosound_tcc.core import child

    monkeypatch.setattr(child, "_no_window", lambda: 0x08000000)
    monkeypatch.setattr(
        child, "hidden_console",
        lambda: {"creationflags": 0x00000010, "startupinfo": "STARTUPINFO"},
    )
    seen = []

    class _Fake:
        def __init__(self, *args, **kwargs):
            seen.append(kwargs)

    child.hide_subprocess_console_windows(target=_Fake)

    _Fake(["agy", "models"])
    _Fake(["git", "status"])

    assert seen[0].get("startupinfo") == "STARTUPINFO", "the agent CLI hands a console DOWN"
    assert seen[1].get("startupinfo") is None, "git spawns nothing; no console at all is right"
