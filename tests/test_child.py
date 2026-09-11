"""How TCC starts a process it only wants an answer from — and what a person sees when it does.

Every case here is a Windows one, because that is the only platform where a child process can put
a window in front of the app. They run on any platform: the flag is faked, not the OS.
"""

from __future__ import annotations

import asyncio
import os
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


def test_only_the_agents_own_cli_is_given_a_console():
    """Narrow on purpose: a child that spawns nothing has no use for a console, and one that is
    handed a console it then shows is the bug this is fixing, backwards."""
    assert child.is_agent_command(["claude", "--print"])
    assert child.is_agent_command([r"C:\Users\x\claude.cmd"])
    assert child.is_agent_command(["/opt/homebrew/bin/omp"])
    assert not child.is_agent_command(["python3", "-c", "print(1)"])
    assert not child.is_agent_command(["git", "status"])
    assert not child.is_agent_command("")


def test_the_sdk_gives_the_agent_a_console_of_its_own_and_everyone_else_no_window(monkeypatch):
    """The agent gets a REAL console, not the `SW_HIDE` hint this used to pass.

    That hint is ignored on Windows 11 — measured twice, under both terminals — so asking for a
    console "created hidden" produced a VISIBLE one. The console is created plainly and hidden
    afterwards by `hide_agent_console_later`, which is the only order that works."""
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
    assert agent["creationflags"] & 0x00000010, "one console, for its shells to inherit"
    assert "startupinfo" not in agent, "the SW_HIDE hint is gone; it never worked"
    assert other["creationflags"] & 0x08000000 and "startupinfo" not in other


def test_by_default_the_agent_gets_the_console_and_the_switch_puts_the_old_way_back(monkeypatch):
    """On by default, because it is the fix rather than an option: without a console of its own,
    every shell the agent's Bash tool starts allocates one, which is a window per command.

    The switch stays for the machine where this turns out worse than the flash it replaces —
    under Windows Terminal the console cannot be hidden at all (`core/default_terminal.py`), and
    somebody meeting that needs a way out where they are, not a new build."""
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

    assert seen[0]["creationflags"] & 0x00000010, "a console of its own, by default"

    monkeypatch.setenv("AUTOSOUND_TCC_AGENT_CONSOLE", "0")
    asyncio.run(anyio.open_process(["claude", "--print"], stdin=-1))

    assert seen[1]["creationflags"] & 0x08000000, "and the switch puts the old behaviour back"


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


def test_an_agent_cli_started_the_ordinary_way_gets_a_console_too(monkeypatch):
    """The agent's CLIs spawn console programs of their own, and a parent with NO console makes
    each grandchild allocate one. This was wired into the ASYNC path only — while the startup log
    from the user's Windows machine (2026-09-09) shows the same programs going out the ordinary
    way: `agy models` twice and `claude.EXE auth`, nine processes in two seconds.

    Same programs, same reason, same treatment. Everything else keeps "no console at all", which
    is right for a child that spawns nothing."""
    from autosound_tcc.core import child

    monkeypatch.setattr(child, "_no_window", lambda: 0x08000000)
    monkeypatch.setattr(child, "agent_console", lambda: {"creationflags": 0x00000010})
    seen = []

    class _Fake:
        def __init__(self, *args, **kwargs):
            seen.append(kwargs)

    child.hide_subprocess_console_windows(target=_Fake)

    _Fake(["agy", "models"])
    _Fake(["git", "status"])

    assert seen[0]["creationflags"] == 0x00000010, "the agent CLI hands a console DOWN"
    assert seen[1]["creationflags"] == 0x08000000, "git spawns nothing; no console at all"


# ---------------------------------------------------------------- the step gate (TCC-006 probe)
# A diagnostic that holds each background spawn until a person presses Enter in a control window,
# so "a window flashed right after STEP 4" names the exact process. Gated by AUTOSOUND_TCC_STEP;
# off, it must be invisible. Everything is injected because the alternative is a test that needs
# real threads and a real clock to tell a wait from a hang — the same shape as `_wait_until_painted`.


def test_the_step_gate_does_nothing_when_step_mode_is_off(monkeypatch):
    """Off is the default and the shipped state: it must not even look at the control file."""
    monkeypatch.delenv("AUTOSOUND_TCC_STEP", raising=False)
    looked = []
    child._step_gate("git ls-remote", read_release=lambda: looked.append(1) or 0)
    assert looked == []


def test_the_step_gate_never_holds_the_main_thread(monkeypatch):
    """Blocking the GUI thread freezes the window into a Windows 'Not Responding' ghost — itself
    a flash, and the very thing being hunted. Only background spawns are stepped."""
    monkeypatch.setenv("AUTOSOUND_TCC_STEP", "1")
    looked = []
    child._step_gate(
        "git ls-remote",
        is_main=lambda: True,
        read_release=lambda: looked.append(1) or 0,
    )
    assert looked == []


def test_the_step_gate_holds_a_background_spawn_until_it_is_released(monkeypatch):
    """A background spawn waits until the control counter reaches its ticket, then proceeds."""
    monkeypatch.setenv("AUTOSOUND_TCC_STEP", "1")
    child._reset_step_counter()
    release = iter([0, 0, 1])  # not yet, not yet, the person pressed Enter
    slept = []
    child._step_gate(
        "git ls-remote",
        is_main=lambda: False,
        read_release=lambda: next(release),
        sleep=lambda s: slept.append(s),
        now=lambda: 0.0,  # the clock never advances, so the budget can never end the wait
    )
    assert slept, "it waited at least once before the release"


def test_the_step_gate_gives_up_after_the_budget_so_a_spawn_never_hangs_forever(monkeypatch):
    """A forgotten Enter must not wedge TCC: past the budget the spawn proceeds on its own."""
    monkeypatch.setenv("AUTOSOUND_TCC_STEP", "1")
    child._reset_step_counter()
    clock = iter([0.0, 0.0, 999.0])
    child._step_gate(
        "git ls-remote",
        is_main=lambda: False,
        read_release=lambda: 0,  # never released
        sleep=lambda s: None,
        now=lambda: next(clock),
        budget_s=300.0,
    )
    # Reaching this line without hanging IS the assertion.


# ------------------------------------------------- one hidden console for the agent (TCC-006)
# The flash during an AI session is `claude`'s Bash tool spawning shells: each is a console
# program started by a parent with NO console, so each allocates its own — a window. Measured on
# Windows 11 (probe, 2026-09-11): give the agent ONE console and hide it, and every shell started
# inside it inherits that console and opens nothing. `cmd`, `bash` and even `agy` all ran silently.
#
# Two facts the measurements forced, and both are in the tests:
#   * conhost shows the window BACK once after the first hide, so hiding once is not enough;
#   * this works only under conhost — under Windows Terminal the window belongs to
#     WindowsTerminal.exe and a search by our pid returns nothing at all.


def test_only_a_visible_console_window_of_that_process_is_hidden():
    """A Qt window of the same process is not a console, and one already hidden is not hidden
    twice — the count is what the keeper reports, so it has to mean something."""
    hidden = []
    seen = [(11, "ConsoleWindowClass", True), (22, "Qt6112QWindowIcon", True),
            (33, "ConsoleWindowClass", False)]

    count = child.hide_console_of(
        4242, windows_of=lambda pid: seen, hide=lambda hwnd: hidden.append(hwnd))

    assert hidden == [11]
    assert count == 1


def test_the_keeper_hides_again_because_conhost_shows_the_window_back():
    """Hidden 97 ms after spawn, the console was visible again a second later (measured). Hiding
    once is the bug; the keeper is the fix."""
    alive = iter([True, True, False])

    total = child.keep_console_hidden(
        4242,
        still_running=lambda: next(alive),
        hide_once=lambda: 1,
        sleep=lambda s: None,
        now=lambda: 0.0,
    )

    assert total == 2, "it must keep hiding for as long as the process runs"


def test_the_keeper_stops_as_soon_as_the_process_is_gone():
    slept = []

    total = child.keep_console_hidden(
        4242,
        still_running=lambda: False,
        hide_once=lambda: 1,
        sleep=lambda s: slept.append(s),
        now=lambda: 0.0,
    )

    assert (total, slept) == (0, [])


def test_the_keeper_gives_up_at_the_budget_rather_than_running_for_the_session():
    """A process that outlives the budget must not leave a thread spinning for hours."""
    clock = iter([0.0, 0.0, 999.0])

    total = child.keep_console_hidden(
        4242,
        still_running=lambda: True,
        hide_once=lambda: 1,
        sleep=lambda s: None,
        now=lambda: next(clock),
        budget_s=30.0,
    )

    assert total == 1, "one pass, then the budget ended it"


def test_an_agent_is_given_a_console_of_its_own_only_on_windows(monkeypatch):
    """`CREATE_NO_WINDOW` is what every other child gets. The agent needs the opposite: a console
    that EXISTS (so its shells inherit one) and is then hidden."""
    monkeypatch.setenv("AUTOSOUND_TCC_AGENT_CONSOLE", "1")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010, raising=False)
    assert child.agent_console()["creationflags"] == 0x00000010

    monkeypatch.setattr(sys, "platform", "darwin")
    assert child.agent_console() == {}


def test_the_keeper_never_asks_the_os_to_signal_the_agent(monkeypatch):
    """`os.kill(pid, 0)` is a POSIX liveness idiom and a loaded gun on Windows: every signal but
    CTRL_C/CTRL_BREAK goes to `TerminateProcess`, so the "probe" kills the agent it was asking
    about.

    Measured on the user's machine, 2026-09-11: the agent's console was created (its commands
    stopped flashing, so the shells did inherit it) and then never hidden — zero hide transitions
    in a whole session. The probe raised before it could terminate anything, the keeper read that
    as "already gone" and exited on its first check, and the agent survived by that accident
    alone. So the keeper is bounded by its budget instead of by a signal."""
    monkeypatch.setattr(sys, "platform", "win32")

    def loaded_gun(*_args, **_kwargs):
        raise AssertionError("os.kill must never be used as a liveness probe on Windows")

    monkeypatch.setattr(os, "kill", loaded_gun)
    started: dict = {}

    child.hide_agent_console_later(4242, spawn=lambda target, kwargs: started.update(kwargs))

    assert started["pid"] == 4242
    # The trap above is the real assertion: reaching `os.kill` fails the test outright. This only
    # says the probe answers rather than raising — `process_is_running` is asked on every pass.
    assert isinstance(started["still_running"](), bool), "it answers, and never by signalling"


# ------------------------------------------ the interpreter a helper SCRIPT is run with (TCC-006)
# The last source of flashing, and the one that survived three wrong theories. Every visible
# `proc=git ConsoleWindowClass` in a session followed a `pythonw.exe ... process.py` spawn by
# 330-500 ms — all seven of them, measured 2026-09-11.
#
# `pythonw.exe` is a WINDOWED binary: it has no console at all, and `CREATE_NO_WINDOW` means
# nothing to it. So the git those scripts call has nothing to inherit and allocates its own — a
# window. `python.exe` with the same flag DOES have a console, just an invisible one, and
# everything it starts inherits that instead. Measured both ways in the same probe: the console
# child opened nothing, the windowed one is what the user saw all week.
#
# TCC runs under `pythonw.exe` itself, being a GUI app, so `sys.executable` hands the windowed
# interpreter to every helper script by default. That default is the bug.


def test_a_helper_script_gets_the_console_interpreter_not_the_windowed_one(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    chosen = child.script_interpreter(
        executable=r"C:\uv\tools\autosound-tcc\Scripts\pythonw.exe", exists=lambda _p: True)

    assert chosen.endswith("python.exe"), "a script needs a console to hand down"
    assert "pythonw" not in chosen


def test_without_a_console_interpreter_beside_it_the_windowed_one_still_runs(monkeypatch):
    """A flash is worse than nothing happening, but not much worse than a script that cannot run
    at all. If `python.exe` is not there, the script still gets started."""
    monkeypatch.setattr(sys, "platform", "win32")
    windowed = r"C:\uv\tools\autosound-tcc\Scripts\pythonw.exe"

    assert child.script_interpreter(executable=windowed, exists=lambda _p: False) == windowed


def test_off_windows_the_interpreter_is_left_exactly_as_it_is(monkeypatch):
    """There is no windowed/console split anywhere else, and rewriting the path would only be a
    way to point at something that is not there."""
    monkeypatch.setattr(sys, "platform", "darwin")

    assert child.script_interpreter(executable="/usr/bin/python3") == "/usr/bin/python3"


def test_the_keeper_stays_with_the_agent_for_as_long_as_it_runs(monkeypatch):
    """Eight seconds was not enough, and the measurement says so: `agy`'s console was hidden, then
    shown again 420 ms later, and by then the keeper had already left (2026-09-11). It was bounded
    by time only because the first liveness probe was `os.kill`, which on Windows kills.

    So it asks properly now — `OpenProcess` + `WaitForSingleObject`, which answers without
    signalling anything — and the budget goes back to being a safety net rather than the rule."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(child, "process_is_running", lambda pid: pid == 4242)
    started: dict = {}

    child.hide_agent_console_later(4242, spawn=lambda target, kwargs: started.update(kwargs))

    assert started["still_running"]() is True, "alive: keep hiding"

    monkeypatch.setattr(child, "process_is_running", lambda pid: False)

    assert started["still_running"]() is False, "gone: stop"


# --------------------------------------------- ONE console for the whole app (TCC-006, the fix)
# Giving each agent its own console and hiding it works, but it pays the same price every time a
# session starts: the console is created VISIBLE and cannot be created otherwise (`SW_HIDE` at
# creation is ignored on Windows 11, measured twice). So the flash moved rather than went.
#
# One console for the PROCESS is the way out, and it is measured: allocate it, hide it, and every
# child and grandchild inherits it instead of making its own — `cmd`, `bash`, `agy` and `git` all
# ran silently inside one (probe, 2026-09-11). One visible moment for the whole run, at startup,
# where it can also SAY what it is instead of being an unexplained black rectangle.
#
# The other half is that `CREATE_NO_WINDOW` then becomes wrong: it denies a child any console at
# all, so the child allocates one — exactly the flash we are removing. Once we own a console, the
# right thing is to let children inherit it.


def test_children_inherit_our_console_instead_of_being_denied_one(monkeypatch):
    """With a console of our own, forcing `CREATE_NO_WINDOW` on a child would defeat the whole
    point: denied a console, it allocates its own, which is a window."""
    _as_windows(monkeypatch)
    monkeypatch.setattr(child, "have_app_console", lambda: True)

    assert "creationflags" not in child.quiet(), "let it inherit ours"
    assert child.quiet()["stdin"] == subprocess.DEVNULL, "the stdin half still stands"
    assert child.flags() == {}


def test_without_a_console_of_our_own_children_still_get_no_window(monkeypatch):
    """The fallback has to keep working: a machine where the console could not be allocated is a
    machine that still must not flash a window per probe."""
    _as_windows(monkeypatch)
    monkeypatch.setattr(child, "have_app_console", lambda: False)

    assert child.quiet()["creationflags"] & 0x08000000


def test_the_app_console_says_what_it_is_before_it_hides(monkeypatch):
    """A black rectangle for a third of a second reads as a glitch. The same rectangle with a line
    in it reads as the application starting, which is what it is."""
    _as_windows(monkeypatch)
    order: list = []

    ok = child.open_app_console(
        "Autosound TCC is starting",
        alloc=lambda: order.append("alloc") or True,
        write=lambda text: order.append(f"write:{text}"),
        hide=lambda: order.append("hide") or 1,
    )

    assert ok is True
    assert order == ["alloc", "write:Autosound TCC is starting", "hide"], "say it, THEN hide"
    assert child.have_app_console() is True


def test_a_console_that_cannot_be_allocated_is_not_claimed(monkeypatch):
    """Claiming one we do not have would turn off `CREATE_NO_WINDOW` for every child and give the
    machine a window per probe — worse than the flash this replaces."""
    _as_windows(monkeypatch)

    ok = child.open_app_console("x", alloc=lambda: False, write=lambda _t: None, hide=lambda: 0)

    assert ok is False
    assert child.have_app_console() is False
