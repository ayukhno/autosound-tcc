"""Front-end B's launcher (core/terminal_launcher.py).

Nothing here actually opens a window: the platform branches are exercised through a recorded
`subprocess`, because the thing worth testing is the command that gets built -- a quoting bug in a
path the user chose is the realistic failure, not whether Terminal.app opens.
"""

from __future__ import annotations

import sys

import pytest

from autosound_tcc.core import terminal_launcher
from autosound_tcc.core.terminal_launcher import TerminalLaunchError, launch


@pytest.fixture
def recorded(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(terminal_launcher.subprocess, "run", lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(terminal_launcher.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(terminal_launcher.shutil, "which", lambda name: f"/usr/bin/{name}")
    return calls


def test_macos_builds_an_applescript_that_cds_then_runs_the_cli(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")

    assert launch(tmp_path, "claude") == "claude"

    script = recorded[0][2]
    assert recorded[0][0] == "osascript"
    assert f"cd {tmp_path}" in script
    assert "exec claude" in script


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

    assert recorded[0].startswith('start "" /d')


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
