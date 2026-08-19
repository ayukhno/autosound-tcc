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
    ("omp", "omp"),
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


def _posix_cli_invocation(
    cli: str, hint: Optional[str], model: Optional[str], extra: tuple[str, ...] = ()
) -> str:
    """`cli [extra…] [--model M] ["hint"]`, POSIX-quoted. `--model` is assumed for every known CLI
    here (confirmed for `claude` and `omp`; `gemini`/`codex`/`agy` follow the same near-universal
    convention, not independently verified per-CLI) -- comes before the prompt positional
    argument, matching ordinary CLI argument-parsing order."""
    parts = [shlex.quote(cli)]
    parts += [shlex.quote(arg) for arg in extra]
    if model:
        parts += ["--model", shlex.quote(model)]
    if hint:
        parts.append(shlex.quote(hint))
    return " ".join(parts)


def _win_cli_invocation(
    cli: str, hint: Optional[str], model: Optional[str], extra: tuple[str, ...] = ()
) -> str:
    """Same shape as `_posix_cli_invocation`, Windows quoting (always double-quote, no escaping
    needed for the short executable names / plain text this handles)."""
    parts = [f'"{cli}"']
    parts += [f'"{arg}"' for arg in extra]
    if model:
        parts += ["--model", f'"{model}"']
    if hint:
        parts.append(f'"{hint}"')
    return " ".join(parts)


def _posix_command(
    project_dir: Path,
    cli: str,
    hint: Optional[str] = None,
    model: Optional[str] = None,
    extra: tuple[str, ...] = (),
) -> str:
    """The shell line the terminal will run: enter the project, then hand over to the CLI.

    `hint`, when given, is passed as the CLI's own initial-prompt ARGUMENT (`cli "hint text"`) --
    NOT shell output printed before it. Every known CLI here (claude, gemini, codex, agy) is a
    full-screen TUI that switches to the terminal's alternate screen buffer on start, which wipes
    whatever the shell printed a moment earlier -- an `echo` before `exec` was confirmed
    (2026-07-29 dogfood) to render as nothing at all once the TUI took over.
    """
    return (
        f"cd {shlex.quote(str(project_dir))} && "
        f"exec {_posix_cli_invocation(cli, hint, model, extra)}"
    )


def run_line(line: str) -> None:
    """Open a terminal running one shell line, and LEAVE it open when the line finishes.

    For the commands a person has to be able to watch and read the ending of — the updater above
    all: it downloads hundreds of megabytes, and when it fails it fails in a sentence that must
    still be on screen afterwards. Deliberately not `core/child.py`'s quiet spawn: this one is a
    window on purpose.

    `line` is a shell line this app composed, never user text.
    """
    if sys.platform == "darwin":
        app = "iTerm" if Path("/Applications/iTerm.app").exists() else "Terminal"
        if app == "iTerm":
            script = (
                'tell application "iTerm"\n'
                "  activate\n"
                "  set w to (create window with default profile)\n"
                f"  tell current session of w to write text {_applescript_literal(line)}\n"
                "end tell"
            )
        else:
            script = (
                f'tell application "Terminal" to do script {_applescript_literal(line)}\n'
                'tell application "Terminal" to activate'
            )
        subprocess.run(["osascript", "-e", script], check=True)
        return
    if sys.platform.startswith("win"):
        # `/k` keeps the window after the command ends — the whole point here.
        if shutil.which("wt"):
            subprocess.Popen(["wt", "cmd", "/k", line], close_fds=True)
            return
        subprocess.Popen(f'start "" cmd /k {line}', shell=True, close_fds=True)
        return
    for argv, wants_shell_string in (
        (["x-terminal-emulator", "-e"], True),
        (["gnome-terminal", "--"], False),
        (["konsole", "-e"], False),
        (["xfce4-terminal", "-e"], True),
        (["xterm", "-e"], True),
    ):
        if not shutil.which(argv[0]):
            continue
        held = f"{line}; echo; read -p 'Enter to close '"
        tail = [held] if wants_shell_string else ["bash", "-lc", held]
        subprocess.Popen([*argv, *tail], close_fds=True)
        return
    raise TerminalLaunchError("no supported terminal emulator found on PATH")


def _applescript_literal(text: str) -> str:
    """Quote a Python string as an AppleScript string literal.

    AppleScript only escapes backslash and double quote, and a project path is user-supplied
    (the dogfood folder is literally named `--MyCar_Jul26`), so this is not decorative.
    """
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _launch_macos(
    project_dir: Path,
    cli: str,
    hint: Optional[str] = None,
    model: Optional[str] = None,
    extra: tuple[str, ...] = (),
) -> None:
    command = _posix_command(project_dir, cli, hint, model, extra)
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


def _launch_windows(
    project_dir: Path,
    cli: str,
    hint: Optional[str] = None,
    model: Optional[str] = None,
    extra: tuple[str, ...] = (),
) -> None:
    if shutil.which("wt"):
        argv = ["wt", "-d", str(project_dir)]
        # Plain case stays exactly the original bare-argv shape; a hint or model needs a single
        # `wt` argument, which only cmd /k can express as one string.
        argv += (
            ["cmd", "/k", _win_cli_invocation(cli, hint, model, extra)]
            if (hint or model or extra)
            else [cli]
        )
        subprocess.Popen(argv, close_fds=True)
        return
    # `start` is a cmd builtin, so this needs the shell; `/d` sets the working directory and the
    # empty "" is the window title `start` would otherwise eat from the first quoted argument.
    inner = _win_cli_invocation(cli, hint, model, extra)
    subprocess.Popen(
        f'start "" /d "{project_dir}" cmd /k {inner}', shell=True, close_fds=True
    )


def _launch_linux(
    project_dir: Path,
    cli: str,
    hint: Optional[str] = None,
    model: Optional[str] = None,
    extra: tuple[str, ...] = (),
) -> None:
    command = _posix_command(project_dir, cli, hint, model, extra)
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


def launch(
    project_dir: Path,
    cli: Optional[str] = None,
    hint: Optional[str] = None,
    model: Optional[str] = None,
    extra: tuple[str, ...] = (),
) -> str:
    """Open a terminal in `project_dir` running `cli`. Returns the CLI that was launched.

    `hint`, if given, is passed as the CLI's own initial-prompt argument (e.g. "onboarding a Helix
    DSP Ultra S" for the "Create new project" terminal path) -- not shell output TCC prints, since
    every known CLI's full-screen TUI would swallow that before the human ever saw it.

    `model`, if given, is passed as `--model <model>` before the hint -- e.g. "opus" for `claude`,
    "gemini-2.5-pro" for `gemini`. Each CLI has its own model-name vocabulary; TCC doesn't validate
    it, the CLI does.

    `extra`, if given, is passed verbatim before `--model` -- omp needs `--config <overlay>` or
    TCC's MCP tools stay behind `xd://` and never enter the model's function list, which would
    make this front-end quietly weaker than the in-app one for no visible reason.

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
            _launch_macos(project_dir, cli, hint, model, extra)
        elif sys.platform.startswith("win"):
            _launch_windows(project_dir, cli, hint, model, extra)
        else:
            _launch_linux(project_dir, cli, hint, model, extra)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise TerminalLaunchError(f"could not open a terminal: {exc}") from exc
    return cli
