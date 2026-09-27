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

from autosound_tcc.core import app_log, child

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
    # Which door was taken, in the log. A person cannot screenshot a console window that blinks
    # (user, Windows, 2026-09-02: "зʼявляються віндоус вікна одне не велике інше зовсім мале —
    # але швидко і я не встигаю зробити скріншот"), and this line turns that into something
    # readable afterwards: which branch, and the exact command it started.
    log = app_log.logger()
    if sys.platform == "darwin":
        app = "iTerm" if Path("/Applications/iTerm.app").exists() else "Terminal"
        log.info("terminal: %s via osascript", app)
        _yield_focus_to(app)
        _osascript(_mac_script(app, line))
        return
    if sys.platform.startswith("win"):
        # `/k` keeps the window after the command ends — the whole point here.
        # `wants_a_console()`, out loud: TCC makes "no console window" the default for every
        # child it starts (`core/child.hide_console_windows`), and this is the one call whose
        # entire purpose is a window somebody types in. Saying so beats being an exception
        # somebody has to remember.
        if shutil.which("wt"):
            log.info("terminal: windows terminal (wt cmd /k), line=%s", line)
            subprocess.Popen(["wt", "cmd", "/k", line], close_fds=True, **child.wants_a_console())
            return
        # ONE console, and no shell. `start "" cmd /k …` run with `shell=True` opened TWO by
        # construction — cmd.exe's own, which exits at once, and the one `start` keeps — and that
        # is the likeliest reading of the two windows reported on Windows (TCC-006). `start` was
        # there only to detach the process, which `CREATE_NEW_CONSOLE` does directly; a shell in
        # between buys nothing and costs a window.
        log.info("terminal: cmd /k in a new console, line=%s", line)
        subprocess.Popen(["cmd", "/k", line], close_fds=True, **child.wants_a_console())
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
        log.info("terminal: %s", argv[0])
        subprocess.Popen([*argv, *tail], close_fds=True)
        return
    raise TerminalLaunchError("no supported terminal emulator found on PATH")


#: The bundle each macOS terminal app answers to, for yielding the focus to it.
_MAC_BUNDLES = {"Terminal": "com.apple.Terminal", "iTerm": "com.googlecode.iterm2"}


def _yield_focus_to(app: str) -> None:
    """Let `app` come to the front: TCC yields the activation first (finding 78, tcc#71).

    Since macOS 14 activation is cooperative: an app comes forward only when the active one
    yields to it, and an `activate` sent through osascript while TCC is in front was ignored —
    the terminal opened behind TCC's maximised window. `yieldActivationToApplication…` is the
    API for exactly this. Through the Objective-C runtime with ctypes, so no new dependency;
    silent where the call does not exist (an older macOS) or AppKit is not loaded."""
    bundle = _MAC_BUNDLES.get(app)
    if sys.platform != "darwin" or not bundle:
        return
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        send = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
        call0 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(send)
        call_ptr = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p)(send)
        call_str = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_char_p)(send)
        call_bool = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.c_void_p)(send)
        ns_app_class = objc.objc_getClass(b"NSApplication")
        if not ns_app_class:
            return
        ns_app = call0(ns_app_class, objc.sel_registerName(b"sharedApplication"))
        selector = objc.sel_registerName(b"yieldActivationToApplicationWithBundleIdentifier:")
        if not ns_app or not call_bool(ns_app, objc.sel_registerName(b"respondsToSelector:"),
                                       selector):
            return
        ns_string = call_str(objc.objc_getClass(b"NSString"),
                             objc.sel_registerName(b"stringWithUTF8String:"), bundle.encode())
        call_ptr(ns_app, selector, ns_string)
    except Exception:  # noqa: BLE001 — a terminal that opens behind is not worth a failed launch
        app_log.logger().info("terminal: could not yield the focus to %s", app)


def _mac_script(app: str, line: str) -> str:
    """The AppleScript that opens `app` on one shell line — addressed by BUNDLE ID, not by name.

    By name, "Terminal" is whatever answers to it: with a Parallels VM running, that was the VM's
    Windows Terminal (`com.parallels.winapp…`), which has no `do script`, and osascript stopped at
    compile — «A "script" can't go after this identifier (-2740)» — with no window at all (finding
    89, tcc#71). The bundle id names Apple's Terminal and iTerm whatever else is installed."""
    bundle = _MAC_BUNDLES[app]
    if app == "iTerm":
        return (
            f'tell application id "{bundle}"\n'
            "  activate\n"
            "  set w to (create window with default profile)\n"
            f"  tell current session of w to write text {_applescript_literal(line)}\n"
            "end tell"
        )
    return (
        f'tell application id "{bundle}" to do script {_applescript_literal(line)}\n'
        f'tell application id "{bundle}" to activate'
    )


def _osascript(script: str) -> None:
    """Run it, and keep osascript's own words: «exit status 1» alone named no reason (finding 89)."""
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    except subprocess.CalledProcessError as exc:
        said = (exc.stderr or "").strip()
        raise TerminalLaunchError(
            f"could not open a terminal: osascript: {said or f'exit status {exc.returncode}'}"
        ) from exc


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
    _yield_focus_to(app)
    _osascript(_mac_script(app, command))


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
    # ONE console, no shell, no `start`. The old line ran `start "" … cmd /k …` through
    # `shell=True`, which opens two consoles by construction (TCC-006); `start` was only ever
    # there to detach, and `CREATE_NEW_CONSOLE` does that on its own.
    #
    # **The folder travels as `cwd`, never inside the line.** `/d "{project_dir}"` used to
    # interpolate it into a string run with `shell=True`, and `cmd` splits on `&` before it looks
    # at quotes — so `Golf R & Passat`, an ordinary name for somebody who tunes two cars, either
    # opened no terminal or opened one in the wrong place; a `"` in the name closed `/d "…"` early
    # and the rest became arguments to `start` (HUB-053). The path is chosen by the person, so
    # this is self-harm rather than an attack — which is the kind that actually happens.
    #
    # `cwd` is not an escaping trick that has to be got right; it is the path not being text.
    inner = _win_cli_invocation(cli, hint, model, extra)
    subprocess.Popen(
        ["cmd", "/k", inner], close_fds=True, cwd=str(project_dir), **child.wants_a_console()
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
