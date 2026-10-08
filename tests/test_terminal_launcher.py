"""Front-end B's launcher (core/terminal_launcher.py).

Nothing here actually opens a window: the platform branches are exercised through a recorded
`subprocess`, because the thing worth testing is the command that gets built -- a quoting bug in a
path the user chose is the realistic failure, not whether Terminal.app opens.
"""

from __future__ import annotations

import os
import shlex
import sys

import pytest

from autosound_tcc.core import method_binding, terminal_launcher
from autosound_tcc.core.terminal_launcher import TerminalLaunchError, launch

from tests._method_copies import entry as _entry, linked_and_approved as _linked_and_approved


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


def _argv_the_c_runtime_way(command: str) -> list[str]:
    """How a Windows program splits its command line (`CommandLineToArgvW`, which `wt` uses):
    quotes group, `\\"` is a literal quote, backslashes count only before a quote."""
    args, word, quoted, have, i = [], [], False, False, 0
    while i < len(command):
        char = command[i]
        if char == "\\":
            run = len(command[i:]) - len(command[i:].lstrip("\\"))
            i += run
            if command[i:i + 1] == '"':
                word.append("\\" * (run // 2))
                if run % 2:
                    word.append('"')
                    i += 1
            else:
                word.append("\\" * run)
            have = True
        elif char == '"':
            quoted, have, i = not quoted, True, i + 1
        elif char in " \t" and not quoted:
            if have:
                args.append("".join(word))
            word, have, i = [], False, i + 1
        else:
            word.append(char)
            have, i = True, i + 1
    if have:
        args.append("".join(word))
    return args


def _as_wt_starts_it(command: str) -> tuple[str, str]:
    """`(folder, the tab's command line)` the way wt builds them: its own argv, `\\;` back to
    `;`, and the command written back out with an argument that holds a space wrapped in quotes."""
    argv = [arg.replace("\\;", ";") for arg in _argv_the_c_runtime_way(command)]
    assert argv[0] == "wt" and ";" not in command.replace("\\;", ""), command
    folder = argv[argv.index("-d") + 1] if "-d" in argv else ""
    rest = argv[argv.index("-d") + 2:] if "-d" in argv else argv[1:]
    return folder, " ".join(f'"{arg}"' if " " in arg else arg for arg in rest)


def _as_cmd_runs_it(command: str) -> str:
    """What `cmd /s /k` runs: what follows `/k`, its first and its last quote taken off."""
    assert command.startswith("cmd /s /k "), command
    rest = command[len("cmd /s /k "):]
    if rest.startswith('"'):
        last = rest.rfind('"')
        rest = rest[1:last] + rest[last + 1:]
    return rest


def _posix_root() -> str:
    """The copy of the method a session's line names (#169), as `env` sets it: TCC's own, which a
    project with no link of its own runs — every `tmp_path` here is one."""
    return f"{method_binding.SKILL_ROOT_ENV}={shlex.quote(str(method_binding.own_copy()))}"


def _win_root() -> str:
    """The same copy as cmd sets it, before the CLI."""
    return f'set "{method_binding.SKILL_ROOT_ENV}={method_binding.own_copy()}" && '


def _in_applescript(line: str) -> str:
    """`line` as the AppleScript carries it (`_applescript_literal`, tested on its own below): a
    Windows path's backslashes doubled, for the macOS tests that run on the Windows shard too."""
    return terminal_launcher._applescript_literal(line)[1:-1]


@pytest.mark.skipif(os.name == "nt", reason="AppleScript: the command this builds exists only on macOS")
def test_macos_builds_an_applescript_that_cds_then_runs_the_cli(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")

    assert launch(tmp_path, "claude") == "claude"

    script = recorded[0][2]
    assert recorded[0][0] == "osascript"
    assert f"cd {tmp_path}" in script
    assert _in_applescript(f"exec env {_posix_root()} claude") in script


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

    folder, tab = _as_wt_starts_it(recorded[0])
    assert folder == str(tmp_path)
    assert _as_cmd_runs_it(tab) == _win_root() + '"claude"'


def test_windows_falls_back_to_cmd_when_wt_is_missing(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    monkeypatch.setattr(
        terminal_launcher.shutil, "which", lambda name: None if name == "wt" else f"C:/{name}"
    )

    launch(tmp_path, "claude")

    assert _as_cmd_runs_it(recorded[0]) == _win_root() + '"claude"', recorded[0]
    # The folder is NOT in the line: `cmd` splits on `&` before it looks at quotes, so a path
    # travelling as text is a path that breaks on an ordinary folder name (HUB-053).
    assert recorded.kwargs["cwd"] == str(tmp_path)
    assert str(tmp_path) not in recorded[0]


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
def test_macos_hint_is_passed_as_the_clis_own_argument(recorded, monkeypatch, tmp_path):
    """Regression (2026-07-29 dogfood): an `echo` before `exec` rendered as nothing at all --
    every known CLI is a full-screen TUI that wipes the shell's prior output on start. The hint
    must be an argument TO the cli, not text printed before it."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")

    launch(tmp_path, "gemini", hint="onboarding a Helix DSP Ultra S")

    script = recorded[0][2]
    assert "echo" not in script
    assert _in_applescript(f"exec env {_posix_root()} gemini 'onboarding a Helix DSP Ultra S'") \
        in script


def test_macos_model_comes_before_the_hint(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")

    launch(tmp_path, "claude", hint="onboarding a Musway M6V4", model="opus")

    script = recorded[0][2]
    assert _in_applescript(
        f"exec env {_posix_root()} claude --model opus 'onboarding a Musway M6V4'") in script


def test_macos_model_without_a_hint(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")

    launch(tmp_path, "gemini", model="gemini-2.5-pro")

    script = recorded[0][2]
    assert _in_applescript(f"exec env {_posix_root()} gemini --model gemini-2.5-pro") in script


def test_macos_without_a_hint_is_unchanged(recorded, monkeypatch, tmp_path):
    """No hint must not append anything at all -- same command shape as before this feature."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")

    launch(tmp_path, "claude")

    script = recorded[0][2]
    assert _in_applescript(f"exec env {_posix_root()} claude") + '"' in script, "the line ends there"
    assert "echo" not in script


def test_windows_terminal_hint_is_passed_as_the_clis_own_argument(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")

    launch(tmp_path, "codex", hint="onboarding a Musway M6V4")

    folder, tab = _as_wt_starts_it(recorded[0])
    assert folder == str(tmp_path)
    assert _as_cmd_runs_it(tab) == _win_root() + '"codex" "onboarding a Musway M6V4"'


def test_windows_terminal_without_a_hint_is_unchanged(recorded, monkeypatch, tmp_path):
    """The bare argv. Only a CLI that runs no session still gets it (`method=False`): a session's
    line names the method's copy, which takes cmd /k to set (#169)."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")

    launch(tmp_path, "claude", method=False)

    assert recorded[0] == ["wt", "-d", str(tmp_path), "claude"]


def test_windows_model_alone_still_switches_to_cmd_k(recorded, monkeypatch, tmp_path):
    """A model with no hint still needs the cmd /k wrapper -- only the truly bare case stays a
    plain argv element. With no method's copy in the line (`method=False`), the model alone is
    what asks for it."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")

    launch(tmp_path, "claude", model="opus", method=False)

    assert _as_cmd_runs_it(_as_wt_starts_it(recorded[0])[1]) == '"claude" --model "opus"'


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

    assert recorded[0].startswith("cmd /s /k "), recorded[0]
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

    assert seen["argv"] == 'cmd /s /k "echo hi"', seen["argv"]
    assert seen["kwargs"].get("shell") is not True


@pytest.mark.skipif(os.name == "nt", reason="the macOS path")
def test_macos_yields_the_focus_to_the_terminal_before_activating_it(recorded, monkeypatch, tmp_path):
    """Finding 78 (tcc#71): «Налаштувати omp…» opened a terminal behind TCC's maximised window.
    Since macOS 14 activation is cooperative — TCC has to yield before the terminal can come
    forward — so the yield comes first, then the AppleScript."""
    order = []
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")
    monkeypatch.setattr(terminal_launcher, "_yield_focus_to", lambda app: order.append(("yield", app)))
    monkeypatch.setattr(terminal_launcher.subprocess, "run",
                        lambda argv, **kw: order.append(("run", argv[0])))

    launch(tmp_path, "claude")

    assert order[0][0] == "yield" and order[0][1] in ("Terminal", "iTerm")
    assert order[1] == ("run", "osascript")


@pytest.mark.skipif(sys.platform != "darwin", reason="the Objective-C runtime is macOS's")
def test_yielding_the_focus_never_raises():
    """A terminal that opens behind is not worth a failed launch: no AppKit, an older macOS,
    anything — the call is silent."""
    terminal_launcher._yield_focus_to("Terminal")
    terminal_launcher._yield_focus_to("NoSuchApp")


@pytest.mark.skipif(os.name == "nt", reason="AppleScript exists only on macOS")
def test_macos_addresses_the_terminal_by_its_bundle_id_not_its_name(recorded, monkeypatch, tmp_path):
    """Finding 89 (tcc#71): with a Parallels VM running, `application "Terminal"` named the VM's
    Windows Terminal (`com.parallels.winapp…`), which has no `do script` — osascript stopped at
    compile, «A "script" can't go after this identifier (-2740)», and no terminal opened at all."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")
    monkeypatch.setattr(terminal_launcher.Path, "exists", lambda self: False)  # no iTerm
    monkeypatch.setattr(terminal_launcher, "_yield_focus_to", lambda app: None)

    launch(tmp_path, "claude")
    terminal_launcher.run_line("echo hi")

    for argv in recorded:
        script = argv[2]
        assert 'application id "com.apple.Terminal"' in script, script
        assert 'application "Terminal"' not in script, script

    recorded.clear()
    monkeypatch.setattr(terminal_launcher.Path, "exists", lambda self: True)  # iTerm is there
    launch(tmp_path, "claude")
    assert 'application id "com.googlecode.iterm2"' in recorded[0][2]


@pytest.mark.skipif(os.name == "nt", reason="AppleScript exists only on macOS")
def test_a_refused_applescript_is_reported_in_osascripts_own_words(monkeypatch, tmp_path):
    """The message said «returned non-zero exit status 1» and nothing else: the reason was on
    osascript's stderr, which nobody kept (finding 89)."""
    import subprocess

    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")
    monkeypatch.setattr(terminal_launcher.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(terminal_launcher, "_yield_focus_to", lambda app: None)

    def refuse(argv, **kw):
        raise subprocess.CalledProcessError(
            1, argv, stderr="31:40: syntax error: A “script” can’t go after this identifier. (-2740)")

    monkeypatch.setattr(terminal_launcher.subprocess, "run", refuse)
    with pytest.raises(TerminalLaunchError) as refused:
        launch(tmp_path, "claude")
    assert "-2740" in str(refused.value)


# ---- the update window: a script run by name, never typed out (hub #221, skill #94) -----------

@pytest.mark.skipif(os.name == "nt", reason="AppleScript exists only on macOS")
def test_macos_runs_the_update_script_by_its_path_and_types_nothing_else(recorded, monkeypatch,
                                                                         tmp_path):
    """The line zsh echoes is `sh '<file>'` and nothing more — and the file's first act clears it.
    A folder with a space and a quote in it stays one argument."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")
    monkeypatch.setattr(terminal_launcher.Path, "exists", lambda self: False)  # no iTerm
    monkeypatch.setattr(terminal_launcher, "_yield_focus_to", lambda app: None)
    script = tmp_path / "it's here" / "tcc-update.sh"

    terminal_launcher.run_script(script)

    applescript = recorded[0][2]
    typed = applescript.split("do script ", 1)[1].split("\n", 1)[0]
    assert typed == terminal_launcher._applescript_literal(
        "sh " + "'" + str(script).replace("'", "'\"'\"'") + "'")
    assert "uv" not in typed


@pytest.mark.parametrize("wt", [True, False])
def test_windows_runs_the_update_script_by_name_from_its_own_folder(recorded, monkeypatch,
                                                                    tmp_path, wt):
    """cmd does not echo a `/k` command, and the script turns its own echo off first. The folder
    travels as the window's starting folder (`wt -d`, or `cwd`), never inside the line — a user
    name with a space or `&` in it is in every temp path (the HUB-053 rule)."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    monkeypatch.setattr(terminal_launcher.shutil, "which",
                        lambda name: f"C:/{name}" if (wt or name != "wt") else None)
    script = tmp_path / "A & B" / "tcc-update.cmd"

    terminal_launcher.run_script(script)

    if wt:
        assert recorded[0] == ["wt", "-d", str(script.parent), "cmd", "/k", "tcc-update.cmd"]
    else:
        assert recorded[0] == ["cmd", "/k", "tcc-update.cmd"]
        assert recorded.kwargs["cwd"] == str(script.parent)
    assert recorded.kwargs.get("shell") is not True


_PICK_ENV = {"AUTOSOUND_CRITIC_MODEL": "gemini-3.8-flash-high", "AUTOSOUND_CRITIC_VIA": "cli"}


@pytest.mark.skipif(os.name == "nt", reason="AppleScript: the command this builds exists only on macOS")
def test_macos_terminal_session_gets_the_reviewers_model_and_route(recorded, monkeypatch, tmp_path):
    """hub #236, tcc#134 (task 9 review, I1): the terminal session is the other front-end; its
    own run of the method must follow the footer's route, not a stored key. Neither Terminal nor
    iTerm passes TCC's environment through osascript, so the variables ride in the line."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "darwin")

    launch(tmp_path, "claude", env=_PICK_ENV)

    script = recorded[0][2]
    assert _in_applescript("exec env AUTOSOUND_CRITIC_MODEL=gemini-3.8-flash-high "
                           f"AUTOSOUND_CRITIC_VIA=cli {_posix_root()} claude") in script


def test_windows_terminal_session_gets_the_reviewers_model_and_route(recorded, monkeypatch, tmp_path):
    """`wt` does not pass the caller's environment either: with one, the `cmd /k` branch sets it."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")

    launch(tmp_path, "claude", env=_PICK_ENV)

    folder, tab = _as_wt_starts_it(recorded[0])
    assert folder == str(tmp_path)
    assert _as_cmd_runs_it(tab) == (
        'set "AUTOSOUND_CRITIC_MODEL=gemini-3.8-flash-high" && '
        'set "AUTOSOUND_CRITIC_VIA=cli" && ' + _win_root() + '"claude"'), recorded[0]


def test_windows_console_session_gets_them_too(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    monkeypatch.setattr(
        terminal_launcher.shutil, "which", lambda name: None if name == "wt" else f"C:/{name}")

    launch(tmp_path, "claude", env=_PICK_ENV)

    assert _as_cmd_runs_it(recorded[0]).startswith(
        'set "AUTOSOUND_CRITIC_MODEL=gemini-3.8-flash-high" && ')


def test_linux_terminal_session_gets_them_too(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(terminal_launcher.sys, "platform", "linux")

    launch(tmp_path, "claude", env=_PICK_ENV)

    assert ("exec env AUTOSOUND_CRITIC_MODEL=gemini-3.8-flash-high AUTOSOUND_CRITIC_VIA=cli "
            f"{_posix_root()} claude") in " ".join(recorded[0])


#: A CLI path a person really has: a space, an `&` and an apostrophe (night review of #134, M10).
_AWKWARD_BIN = {"posix": "/Users/O'Neil/R&D tools/agy",
                "win32": "C:\\Users\\O'Neil\\R&D tools\\agy.exe"}


def _posix_line(recorded, monkeypatch, platform, tmp_path, env) -> str:
    """The shell line the terminal runs: Linux hands it over as the last argument, macOS inside
    an AppleScript literal (whose escaping has tests of its own above)."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", platform)
    lines: list = []
    real = terminal_launcher._mac_script
    monkeypatch.setattr(terminal_launcher, "_mac_script",
                        lambda app, line: lines.append(line) or real(app, line))
    launch(tmp_path, "claude", env=env)
    return lines[0] if platform == "darwin" else recorded[0][-1]


@pytest.mark.parametrize("platform", [
    "linux",
    pytest.param("darwin", marks=pytest.mark.skipif(os.name == "nt", reason="AppleScript")),
])
def test_a_value_that_needs_quoting_reaches_the_cli_whole(recorded, monkeypatch, tmp_path,
                                                          platform):
    """`shlex.quote` per value: the line splits back into exactly the value it was given."""
    import shlex

    monkeypatch.setenv("GEMINI_API_KEY", "AQ.not-a-real-key")
    env = {**_PICK_ENV, "AUTOSOUND_CRITIC_BIN": _AWKWARD_BIN["posix"]}

    line = _posix_line(recorded, monkeypatch, platform, tmp_path, env)

    words = shlex.split(line)
    assert f"AUTOSOUND_CRITIC_BIN={_AWKWARD_BIN['posix']}" in words
    assert words[words.index("env") + 1:][:3] == [f"{k}={v}" for k, v in env.items()]
    assert "_API_KEY" not in line, "the line carries the pick, never a key from TCC's environment"


@pytest.mark.parametrize("wt", [True, False])
def test_a_value_that_needs_quoting_is_set_whole_on_windows(recorded, monkeypatch, tmp_path, wt):
    """`set "K=V"`: the quotes keep the space and the `&` in the value. Whether cmd reads the
    line as Python hands it over is the Arbiter's VM check (night review of #134, M9)."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    monkeypatch.setattr(terminal_launcher.shutil, "which",
                        lambda name: f"C:/{name}" if (wt or name != "wt") else None)
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.not-a-real-key")

    launch(tmp_path, "claude", env={**_PICK_ENV, "AUTOSOUND_CRITIC_BIN": _AWKWARD_BIN["win32"]})

    line = _as_cmd_runs_it(_as_wt_starts_it(recorded[0])[1] if wt else recorded[0])
    assert f'set "AUTOSOUND_CRITIC_BIN={_AWKWARD_BIN["win32"]}" && ' in line
    assert "_API_KEY" not in recorded[0]


def test_no_env_keeps_every_line_as_it_was(recorded, monkeypatch, tmp_path):
    """For a CLI that runs no session (`method=False`): a session's line always names the method's
    copy (#169)."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")

    launch(tmp_path, "claude", env={}, method=False)

    assert recorded[0] == ["wt", "-d", str(tmp_path), "claude"]


# --- the line reaches cmd as it was written (finding 148) -----------------------------------------


def _line() -> str:
    """A session's whole line: the reviewer's pick, the method's copy, then the CLI."""
    return ('set "AUTOSOUND_CRITIC_MODEL=gemini-3.8-flash-high" && set "AUTOSOUND_CRITIC_VIA=cli" && '
            f'{_win_root()}"claude" --model "opus" "tune the car"')


def test_cmd_is_handed_the_line_verbatim(recorded, monkeypatch, tmp_path):
    """Finding 148, on the Arbiter's VM: `cmd /k` started from an argv got `set \\"K=V\\"` —
    Python's argv quoting writes `"` as `\\"`, which cmd does not read — and answered «Environment
    variable AUTOSOUND not defined». The command line is one string now, written for cmd: `/s`,
    then the line in one pair of quotes that cmd takes off. The folder is still `cwd` (HUB-053)."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    monkeypatch.setattr(
        terminal_launcher.shutil, "which", lambda name: None if name == "wt" else f"C:/{name}")

    launch(tmp_path, "claude", hint="tune the car", model="opus", env=_PICK_ENV)

    assert recorded[0] == f'cmd /s /k "{_line()}"'
    assert _as_cmd_runs_it(recorded[0]) == _line()
    assert recorded.kwargs["cwd"] == str(tmp_path)


def test_windows_terminal_hands_cmd_the_same_line(recorded, monkeypatch, tmp_path):
    """wt reads its own command line the C runtime's way and writes the tab's back out, so the
    line goes to wt as one argument in that quoting and reaches cmd as it was written."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    folder = tmp_path / "Golf R & Passat"
    folder.mkdir()

    launch(folder, "claude", hint="tune the car", model="opus", env=_PICK_ENV)

    escaped = _line().replace('"', '\\"')
    assert recorded[0] == f'wt -d "{folder}" cmd /s /k "{escaped}"'
    assert _as_wt_starts_it(recorded[0]) == (str(folder), f'cmd /s /k "{_line()}"')
    assert _as_cmd_runs_it(_as_wt_starts_it(recorded[0])[1]) == _line()


def test_a_semicolon_is_not_taken_by_windows_terminal_for_its_own(recorded, monkeypatch, tmp_path):
    """`;` separates wt's own commands: a hint holding one would open a second tab running the
    rest. It goes over as `\\;`, wt's escape."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")

    launch(tmp_path, "claude", hint="sub first; then the doors")

    assert "\\;" in recorded[0]
    assert _as_cmd_runs_it(_as_wt_starts_it(recorded[0])[1]) == \
        _win_root() + '"claude" "sub first; then the doors"'


@pytest.mark.parametrize("wt", [True, False])
def test_the_plain_terminal_hands_cmd_the_line_verbatim_too(recorded, monkeypatch, wt):
    """`run_line` is the reviewer-key window's door (`key move-shell`), and its line is quoted
    for cmd the same way: an interpreter under a folder with a space is `"…"` in it."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    monkeypatch.setattr(terminal_launcher.shutil, "which",
                        lambda name: f"C:/{name}" if (wt or name != "wt") else None)
    line = '"C:\\Program Files\\Python\\python.exe" "C:\\a b\\key.py" key move-shell'

    terminal_launcher.run_line(line)

    tab = _as_wt_starts_it(recorded[0])[1] if wt else recorded[0]
    assert _as_cmd_runs_it(tab) == line


def test_a_semicolon_in_the_project_folder_does_not_split_the_bare_wt_line(recorded, monkeypatch,
                                                                         tmp_path):
    """Review of finding 148, M10: the bare `wt -d <folder> <cli>` never went through
    `_wt_command`, so a folder named with a `;` still started a second wt command. Bare is a CLI
    that runs no session now (`method=False`); a session's line goes through `_wt_command`."""
    import subprocess

    monkeypatch.setattr(terminal_launcher.sys, "platform", "win32")
    folder = tmp_path / "Golf; Passat"
    folder.mkdir()

    launch(folder, "claude", method=False)

    assert _as_wt_starts_it(subprocess.list2cmdline(recorded[0])) == (str(folder), "claude")


# --- the copy of the method the terminal's session runs (#169, N4) --------------------------------


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_the_terminal_session_is_told_the_copy_the_project_is_bound_to(
        recorded, monkeypatch, tmp_path, other_copy, own_copy_is_the_submodule, platform):
    """The terminal's own session loads the project's link — `claude` reads the project's
    `.claude/skills`, omp its overlay's `includeSkills` — and its line carried the reviewer's
    variables alone, so the session's shell ran the method's scripts unaware of the copy it had
    loaded. The line names the bound copy after the reviewer's pick, as the in-app routes do."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", platform)
    project = tmp_path / "car"
    root = str(_linked_and_approved(project, other_copy).skill_dir)

    launch(project, "claude", env=_PICK_ENV)

    if platform == "linux":
        words = shlex.split(recorded[0][-1])
        assert words[words.index("env") + 1:][:4] == [
            *(f"{key}={value}" for key, value in _PICK_ENV.items()),
            f"{method_binding.SKILL_ROOT_ENV}={root}", "claude"]
    else:
        assert _as_cmd_runs_it(_as_wt_starts_it(recorded[0])[1]) == (
            'set "AUTOSOUND_CRITIC_MODEL=gemini-3.8-flash-high" && set "AUTOSOUND_CRITIC_VIA=cli" '
            f'&& set "{method_binding.SKILL_ROOT_ENV}={root}" && "claude"'), recorded[0]


def test_a_copy_tcc_will_not_run_opens_no_terminal(recorded, monkeypatch, tmp_path):
    """R-i: G5 refuses a copy TCC cannot trust, and the terminal's session would load it from the
    project's link as surely as an in-app one. A folder at the entry — inside the project,
    travelling with it — opens no terminal, and the error carries the binding's own sentence: the
    window puts `str(exc)` of a `TerminalLaunchError` on its status line."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "linux")
    project = tmp_path / "car"
    _entry(project).mkdir(parents=True)
    binding = method_binding.for_project(project)
    assert binding.state == "refused" and binding.reason, binding

    with pytest.raises(TerminalLaunchError) as refused:
        launch(project, "claude", env=_PICK_ENV)

    assert str(refused.value) == binding.reason
    assert recorded == [], "no terminal was opened"


def test_a_cli_that_runs_no_session_is_not_held_to_the_projects_copy(recorded, monkeypatch,
                                                                       tmp_path):
    """`omp setup` configures the machine, not the car (`model_config_dialog`). It opens in the
    project folder when there is one, and a copy refused there is no reason to refuse it — nor is
    a copy anything its line has to name."""
    monkeypatch.setattr(terminal_launcher.sys, "platform", "linux")
    project = tmp_path / "car"
    _entry(project).mkdir(parents=True)

    assert launch(project, "omp", extra=("setup",), method=False) == "omp"

    assert shlex.split(recorded[0][-1])[-2:] == ["omp", "setup"]
    assert method_binding.SKILL_ROOT_ENV not in recorded[0][-1]
