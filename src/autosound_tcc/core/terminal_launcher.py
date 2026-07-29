"""Front-end B: open the user's own terminal on their own agent CLI, in the project folder.

The point of this front-end is what it *doesn't* do. TCC starts no agent, holds no credentials,
and reads no stdout — it opens a terminal the way an IDE does, and the session inside it belongs
entirely to the user. TCC and that session meet only at the MCP server (`core.mcp_server`), which
the CLI discovers through the `.mcp.json` TCC wrote into the project.

That makes this the one path with no authentication question attached: whatever the user's CLI is
logged into is between them and their provider. It also happens to be provider-agnostic for free,
since `claude`, `gemini` and `codex` all speak MCP.

Nothing here imports Qt.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Agent CLIs we know how to launch, in the order we'd suggest them. The value is the executable
# name to look for on PATH; `agy` is Antigravity's Gemini CLI, which the tuning skill's own critic
# wrappers already prefer over `gemini` when present.
KNOWN_CLIS: tuple[tuple[str, str], ...] = (
    ("claude", "Claude Code"),
    ("agy", "Gemini (Antigravity)"),
    ("gemini", "Gemini CLI"),
    ("codex", "Codex CLI"),
)


class TerminalLaunchError(RuntimeError):
    """No terminal emulator could be driven on this platform."""


def available_clis() -> list[tuple[str, str]]:
    """The known agent CLIs actually installed, as (executable, label) pairs."""
    return [(exe, label) for exe, label in KNOWN_CLIS if shutil.which(exe)]


def default_cli() -> Optional[str]:
    found = available_clis()
    return found[0][0] if found else None


def _posix_command(project_dir: Path, cli: str, hint: Optional[str] = None) -> str:
    """The shell line the terminal will run: enter the project, then hand over to the CLI.

    `hint`, when given, is passed as the CLI's own initial-prompt ARGUMENT (`cli "hint text"`) --
    NOT shell output printed before it. Every known CLI here (claude, gemini, codex, agy) is a
    full-screen TUI that switches to the terminal's alternate screen buffer on start, which wipes
    whatever the shell printed a moment earlier -- an `echo` before `exec` was confirmed
    (2026-07-29 dogfood) to render as nothing at all once the TUI took over.
    """
    cli_invocation = shlex.quote(cli)
    if hint:
        cli_invocation += f" {shlex.quote(hint)}"
    return f"cd {shlex.quote(str(project_dir))} && exec {cli_invocation}"


def _applescript_literal(text: str) -> str:
    """Quote a Python string as an AppleScript string literal.

    AppleScript only escapes backslash and double quote, and a project path is user-supplied
    (the dogfood folder is literally named `--MyCar_Jul26`), so this is not decorative.
    """
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _launch_macos(project_dir: Path, cli: str, hint: Optional[str] = None) -> None:
    command = _posix_command(project_dir, cli, hint)
    app = "iTerm" if Path("/Applications/iTerm.app").exists() else "Terminal"
    if app == "iTerm":
        script = (
            'tell application "iTerm"\n'
            "  activate\n"
            "  set w to (create window with default profile)\n"
            f"  tell current session of w to write text {_applescript_literal(command)}\n"
            "end tell"
        )
    else:
        script = (
            f'tell application "Terminal" to do script {_applescript_literal(command)}\n'
            'tell application "Terminal" to activate'
        )
    subprocess.run(["osascript", "-e", script], check=True)


def _launch_windows(project_dir: Path, cli: str, hint: Optional[str] = None) -> None:
    if shutil.which("wt"):
        argv = ["wt", "-d", str(project_dir)]
        # Unhinted case stays exactly the plain-argv shape it always was; a hint needs a single
        # `wt` argument, which only cmd /k can express as one string.
        argv += ["cmd", "/k", f'{cli} "{hint}"'] if hint else [cli]
        subprocess.Popen(argv, close_fds=True)
        return
    # `start` is a cmd builtin, so this needs the shell; `/d` sets the working directory and the
    # empty "" is the window title `start` would otherwise eat from the first quoted argument.
    inner = f'"{cli}" "{hint}"' if hint else f'"{cli}"'
    subprocess.Popen(
        f'start "" /d "{project_dir}" cmd /k {inner}', shell=True, close_fds=True
    )


def _launch_linux(project_dir: Path, cli: str, hint: Optional[str] = None) -> None:
    command = _posix_command(project_dir, cli, hint)
    candidates = (
        (["x-terminal-emulator", "-e"], True),
        (["gnome-terminal", "--working-directory", str(project_dir), "--"], False),
        (["konsole", "--workdir", str(project_dir), "-e"], False),
        (["xfce4-terminal", "--working-directory", str(project_dir), "-e"], True),
        (["xterm", "-e"], True),
    )
    for argv, wants_shell_string in candidates:
        if not shutil.which(argv[0]):
            continue
        tail = ["bash", "-lc", command] if not wants_shell_string else [command]
        subprocess.Popen([*argv, *tail], close_fds=True)
        return
    raise TerminalLaunchError("no supported terminal emulator found on PATH")


def launch(project_dir: Path, cli: Optional[str] = None, hint: Optional[str] = None) -> str:
    """Open a terminal in `project_dir` running `cli`. Returns the CLI that was launched.

    `hint`, if given, is passed as the CLI's own initial-prompt argument (e.g. "onboarding a Helix
    DSP Ultra S" for the "Create new project" terminal path) -- not shell output TCC prints, since
    every known CLI's full-screen TUI would swallow that before the human ever saw it.

    Raises `TerminalLaunchError` if no agent CLI is installed or no terminal can be driven — the
    caller is expected to turn that into a message, since "nothing happened" after clicking a
    button is the worst possible outcome here.
    """
    cli = cli or default_cli()
    if not cli:
        raise TerminalLaunchError(
            "no agent CLI found on PATH (looked for: "
            + ", ".join(exe for exe, _ in KNOWN_CLIS)
            + ")"
        )
    if not shutil.which(cli):
        raise TerminalLaunchError(f"{cli!r} is not on PATH")
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        raise TerminalLaunchError(f"{project_dir} is not a directory")

    # Dispatch on `sys.platform` alone. `os.name` would work too, but two seams means a test can
    # patch one and not the other -- and patching `os.name` silently switches `pathlib` to Windows
    # semantics, so the mismatch shows up as a bogus "not a directory" rather than as itself.
    try:
        if sys.platform == "darwin":
            _launch_macos(project_dir, cli, hint)
        elif sys.platform.startswith("win"):
            _launch_windows(project_dir, cli, hint)
        else:
            _launch_linux(project_dir, cli, hint)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise TerminalLaunchError(f"could not open a terminal: {exc}") from exc
    return cli
