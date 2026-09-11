"""Front-end B's launcher (core/terminal_launcher.py).

Nothing here actually opens a window: the platform branches are exercised through a recorded
`subprocess`, because the thing worth testing is the command that gets built -- a quoting bug in a
path the user chose is the realistic failure, not whether Terminal.app opens.
"""

from __future__ import annotations

import os
import sys

import pytest

from autosound_tcc.core import terminal_launcher
from autosound_tcc.core.terminal_launcher import TerminalLaunchError, launch


@pytest.fixture
def recorded(monkeypatch):
    class _Calls(list):
        """The commands, plus the kwargs of the last spawn.

        A test has to be able to ask WHERE a terminal was started, not only WHAT was run: the
        project folder travels as `cwd` now rather than inside a shell line (HUB-053), and a
        fixture that records only the line cannot tell the fixed shape from the broken one.
        """

        kwargs: dict = {}

    calls = _Calls()

    def record(argv, **kw):
        calls.append(argv)
        calls.kwargs = kw

    monkeypatch.setattr(terminal_launcher.subprocess, "run", record)
    monkeypatch.setattr(terminal_launcher.subprocess, "Popen", record)
    monkeypatch.setattr(terminal_launcher.shutil, "which", lambda name: f"/usr/bin/{name}")
    return calls


@pytest.mark.skipif(os.name == "nt", reason="AppleScript: the command this builds exists only on macOS")
def test_macos_builds_an_applescript_that_cds_then_runs_the_cli(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")

    assert launch(tmp_path, "claude") == "claude"

    script = recorded[0][2]
    assert recorded[0][0] == "osascript"
    assert f"cd {tmp_path}" in script
    assert "exec claude" in script


@pytest.mark.skipif(
    os.name == "nt",
    reason="AppleScript, and the fixture path it quotes is not a legal Windows filename",
)
def test_macos_quotes_a_path_that_would_break_applescript(recorded, monkeypatch, tmp_path):
    """A real project folder is named `--MyCar_Jul26`; a quote or backslash in a path must not end
    the AppleScript string early."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")
    awkward = tmp_path / 'we"ird \\ dir'
    awkward.mkdir()

    launch(awkward, "claude")

    script = recorded[0][2]
    assert '\\"' in script and "\\\\" in script
    # The shell layer quotes independently of the AppleScript layer.
    assert "'" in script


def test_windows_prefers_windows_terminal(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")

    launch(tmp_path, "claude")

    assert recorded[0][:2] == ["wt", "-d"]
    assert recorded[0][-1] == "claude"


def test_windows_falls_back_to_cmd_when_wt_is_missing(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    monkeypatch.setattr(
        terminal_launcher.shutil, "which", lambda name: None if name == "wt" else f"C:/{name}"
    )

    launch(tmp_path, "claude")

    assert recorded[0][:2] == ["cmd", "/k"], recorded[0]
    # The folder is NOT in the line: `cmd` splits on `&` before it looks at quotes, so a path
    # travelling as text is a path that breaks on an ordinary folder name (HUB-053).
    assert recorded.kwargs["cwd"] == str(tmp_path)
    assert str(tmp_path) not in " ".join(recorded[0])


def test_linux_uses_the_first_terminal_on_path(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "linux")
    monkeypatch.setattr(
        terminal_launcher.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in ("konsole", "claude") else None,
    )

    launch(tmp_path, "claude")

    assert recorded[0][0] == "konsole"


def test_linux_without_any_terminal_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "linux")
    monkeypatch.setattr(
        terminal_launcher.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None
    )

    with pytest.raises(TerminalLaunchError, match="terminal emulator"):
        launch(tmp_path, "claude")


def test_missing_cli_is_reported_rather_than_silently_doing_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.shutil, "which", lambda name: None)

    with pytest.raises(TerminalLaunchError, match="no agent CLI"):
        launch(tmp_path)


def test_a_path_that_is_not_a_directory_is_refused(recorded, tmp_path):
    missing = tmp_path / "nope"

    with pytest.raises(TerminalLaunchError, match="not a directory"):
        launch(missing, "claude")


def test_available_clis_reports_only_what_is_installed(monkeypatch):
    monkeypatch.setattr(
        terminal_launcher.shutil, "which", lambda name: "/usr/bin/gemini" if name == "gemini" else None
    )

    assert terminal_launcher.available_clis() == [("gemini", "Gemini CLI")]
    assert terminal_launcher.default_cli() == "gemini"


def test_no_clis_installed_means_no_default(monkeypatch):
    monkeypatch.setattr(terminal_launcher.shutil, "which", lambda name: None)

    assert terminal_launcher.available_clis() == []
    assert terminal_launcher.default_cli() is None


@pytest.mark.skipif(sys.platform != "darwin", reason="reads the real PATH on the dev machine")
def test_this_machine_has_at_least_one_agent_cli():
    """Sanity check for the dogfood machine -- front-end B is unusable without one."""
    assert terminal_launcher.available_clis()


def test_macos_hint_is_passed_as_the_clis_own_argument(recorded, monkeypatch, tmp_path):
    """Regression (2026-07-29 dogfood): an `echo` before `exec` rendered as nothing at all --
    every known CLI is a full-screen TUI that wipes the shell's prior output on start. The hint
    must be an argument TO the cli, not text printed before it."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")

    launch(tmp_path, "gemini", hint="onboarding a Helix DSP Ultra S")

    script = recorded[0][2]
    assert "echo" not in script
    assert "exec gemini 'onboarding a Helix DSP Ultra S'" in script


def test_macos_model_comes_before_the_hint(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")

    launch(tmp_path, "claude", hint="onboarding a Musway M6V4", model="opus")

    script = recorded[0][2]
    assert "exec claude --model opus 'onboarding a Musway M6V4'" in script


def test_macos_model_without_a_hint(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")

    launch(tmp_path, "gemini", model="gemini-2.5-pro")

    script = recorded[0][2]
    assert "exec gemini --model gemini-2.5-pro" in script


def test_macos_without_a_hint_is_unchanged(recorded, monkeypatch, tmp_path):
    """No hint must not append anything at all -- same command shape as before this feature."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")

    launch(tmp_path, "claude")

    script = recorded[0][2]
    assert "exec claude" in script
    assert "echo" not in script


def test_windows_terminal_hint_is_passed_as_the_clis_own_argument(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")

    launch(tmp_path, "codex", hint="onboarding a Musway M6V4")

    assert recorded[0][:2] == ["wt", "-d"]
    assert recorded[0][3:5] == ["cmd", "/k"]
    assert recorded[0][-1] == '"codex" "onboarding a Musway M6V4"'


def test_windows_terminal_without_a_hint_is_unchanged(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")

    launch(tmp_path, "claude")

    assert recorded[0] == ["wt", "-d", str(tmp_path), "claude"]


def test_windows_model_alone_still_switches_to_cmd_k(recorded, monkeypatch, tmp_path):
    """A model with no hint still needs the cmd /k wrapper -- only the truly bare case stays a
    plain argv element."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")

    launch(tmp_path, "claude", model="opus")

    assert recorded[0][3:5] == ["cmd", "/k"]
    assert recorded[0][-1] == '"claude" --model "opus"'


def test_no_console_is_the_processes_default_and_the_terminal_opts_out(monkeypatch):
    """A default that has to be remembered at each call site is a default that gets forgotten.

    Every `subprocess` call in this repo already passed `child.quiet()`, and a user on Windows 11
    still saw a console window blink three times in one session (2026-08-22): before the main
    window, after it, and on opening the version panel. The ones that cannot pass it are the
    GRANDCHILDREN — the agent CLI runs the method's `python3` and `git`, and a console program
    started by a console-less parent gets a console of its own. So the flag became the process's
    default, and the one caller that WANTS a window says so.

    Patched onto a stand-in class, never onto the real `subprocess.Popen`: doing that leaked past
    the test and killed 74 later ones (see the note in `child.hide_subprocess_console_windows`).
    """
    from autosound_tcc.core import child

    monkeypatch.setattr(child, "_no_window", lambda: 0x08000000)  # CREATE_NO_WINDOW

    class FakePopen:
        def __init__(self, argv, creationflags=None, **kwargs):
            self.argv = argv
            self.creationflags = creationflags

    child.hide_subprocess_console_windows(FakePopen)

    assert FakePopen(["anything"]).creationflags == 0x08000000, "a plain call gets the flag"
    asked = FakePopen(["anything"], creationflags=0x00000010)  # CREATE_NEW_CONSOLE
    assert asked.creationflags == 0x00000010, "a caller that said what it wants is left alone"

    # Twice does nothing: the wrapper marks itself, so a second call cannot double-wrap.
    first = FakePopen.__init__
    child.hide_subprocess_console_windows(FakePopen)
    assert FakePopen.__init__ is first


def test_wants_a_console_is_empty_off_windows(monkeypatch):
    from autosound_tcc.core import child

    monkeypatch.setattr(child.sys, "platform", "darwin")
    assert child.wants_a_console() == {}


# --- a project folder is named by a person, and people use `&` (HUB-053) --------------------


def test_a_project_path_with_an_ampersand_does_not_reach_the_shell(monkeypatch, tmp_path):
    """`start "" /d "{project_dir}" cmd /k …` interpolated the path into a line run with
    `shell=True`. `cmd` splits on `&` before anything else, so a folder called
    `Golf R & Passat` — an ordinary name for somebody tuning two cars — either opens no terminal
    or opens one in the wrong place. The user picks the folder, so this is self-harm rather than
    an attack, and self-harm is the kind that actually happens."""
    from autosound_tcc.core import terminal_launcher

    seen = {}

    def fake_popen(command, **kwargs):
        seen["command"] = command
        seen["cwd"] = kwargs.get("cwd")
        return object()

    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    monkeypatch.setattr(terminal_launcher.shutil, "which", lambda _name: None)
    monkeypatch.setattr(terminal_launcher.subprocess, "Popen", fake_popen)
    folder = tmp_path / "Golf R & Passat"
    folder.mkdir()

    terminal_launcher._launch_windows(folder, "claude")

    assert "&" not in str(seen["command"]), seen["command"]
    assert seen["cwd"] == str(folder), "the folder travels as cwd, not as text in a shell line"


def test_a_project_path_with_a_quote_does_not_reach_the_shell(monkeypatch, tmp_path):
    """The other half of the same hole: a `"` closes `/d "…"` early and the rest of the path
    becomes arguments to `start`."""
    from autosound_tcc.core import terminal_launcher

    seen = {}
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    monkeypatch.setattr(terminal_launcher.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        terminal_launcher.subprocess, "Popen",
        lambda command, **kwargs: seen.update(command=command, cwd=kwargs.get("cwd")),
    )
    # NOT created on disk, and it cannot be: Windows forbids `"` in a filename, so `mkdir()` here
    # failed with WinError 123 on the very platform the test is about — it only ever passed on the
    # developer's Mac. Nothing needs the folder to exist: the launcher passes it straight through
    # as `cwd`, and `Popen` is stubbed. A path is a path whether or not something is behind it.
    folder = tmp_path / 'the "loud" car'

    terminal_launcher._launch_windows(folder, "claude")

    assert '"loud"' not in str(seen["command"]), seen["command"]
    assert seen["cwd"] == str(folder)


def test_windows_opens_ONE_console_not_two(recorded, monkeypatch, tmp_path):
    """TCC-006, the third source. `start "" cmd /k …` run with `shell=True` opens TWO consoles by
    construction: cmd.exe's own, which exits at once, and the one `start` keeps. `start` was there
    only to detach the process — and `CREATE_NEW_CONSOLE` does that directly, without a shell in
    between. The break this catches is a `shell=True` creeping back."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    monkeypatch.setattr(
        terminal_launcher.shutil, "which", lambda name: None if name == "wt" else f"C:/{name}"
    )

    launch(tmp_path, "claude")

    assert recorded[0][:2] == ["cmd", "/k"], recorded[0]
    assert recorded.kwargs.get("shell") is not True
    assert recorded.kwargs["cwd"] == str(tmp_path)


def test_the_plain_terminal_also_opens_one_console(monkeypatch):
    """`run_line` is the other door onto the same shape — the update button's."""
    seen = {}
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    monkeypatch.setattr(terminal_launcher.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        terminal_launcher.subprocess, "Popen",
        lambda argv, **kw: seen.update(argv=argv, kwargs=kw),
    )

    terminal_launcher.run_line("echo hi")

    assert seen["argv"][:2] == ["cmd", "/k"], seen["argv"]
    assert seen["kwargs"].get("shell") is not True
