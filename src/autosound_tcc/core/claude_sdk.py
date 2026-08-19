"""Bind the Claude Agent SDK's names on demand, so a machine without it still runs TCC.

`claude-agent-sdk` is an EXTRA, not a base dependency: TCC drives other models too — Gemini,
Codex and anything else — through `omp`, which shells out to a CLI and needs no Python package of
its own. Until now the SDK was imported at the top of `tuning_session.py` and `agent_session.py`,
and `main_window.py` imports `TuningSession` on its first line, so **the window would not start
without it** even for someone who never intends to talk to Claude. They also downloaded 277 MB of
Claude Code bundled inside that wheel and never ran it (found by asking "what if someone installs
with Gemini or Codex?", user, 2026-08-12).

Deferring the import is not enough on its own. Python resolves a bare global inside a function
against the module's `__dict__` and then builtins — it does **not** fall back to the module's
`__getattr__` (PEP 562 covers `module.attr`, not global lookup; verified rather than assumed). So
the names have to be really present in the module's globals by the time a method runs, which is
what `bind()` does: called once from the constructor of whatever needs the SDK, it fills them in
and every existing use site keeps working unchanged.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Optional

from autosound_tcc.core import child

#: The command that installs it, kept in one place so the message never drifts from the README.
INSTALL_HINT = (
    "uv tool install --upgrade "
    "'autosound-tcc[claude] @ git+https://github.com/ayukhno/autosound-tcc'"
)
#: What a person types to fix a logged-out CLI. Same reasoning as `INSTALL_HINT`.
LOGIN_HINT = "claude auth login"
#: Short on purpose: this runs on a worker thread at launch, and a CLI that does not answer in
#: two seconds has told us what we need ("cannot tell"), which is not a failure state.
_AUTH_TIMEOUT_S = 2.0
#: Tri-state, cached for the life of the process: True, False, and None for "could not tell".
_SIGNED_IN: Optional[bool] = None


class ClaudeSdkMissing(ImportError):
    """The Claude route was asked for on an install that does not have the SDK.

    An `ImportError` subclass so existing `except ImportError` paths still catch it, with a message
    that names the remedy — the alternative is `ModuleNotFoundError: claude_agent_sdk` in front of
    somebody who chose Gemini on purpose.
    """


def available() -> bool:
    """Is the SDK installed. Uses `find_spec`, which does not execute the package: this is called
    from the model picker, on the UI thread, on every rebuild.

    `find_spec` is documented to return None for a missing module, but it RAISES for a broken one
    — a half-removed install, a shadowing file, an import hook that objects. Either way the answer
    the picker needs is "no", and a model picker is not a place to take the window down.
    """
    try:
        return importlib.util.find_spec("claude_agent_sdk") is not None
    except (ImportError, ValueError):
        return False


def cli_path() -> Optional[str]:
    """Where this machine's `claude` is — PATH or not.

    `shutil.which` alone is the wrong question here. The window is normally opened from the Dock,
    and an app launched by Finder inherits the system PATH, which does NOT include `~/.local/bin`
    — the directory Claude Code installs itself into. Asking only PATH answers "no claude" on a
    machine that has one, which would then be reported as "not signed in".
    """
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "claude"
    return str(fallback) if os.access(fallback, os.X_OK) else None


def signed_in() -> Optional[bool]:
    """Has the Claude route got something to authenticate with, as last probed.

    Never runs anything: this is read by the pickers, on the UI thread, on every rebuild. The
    answer comes from `probe_signed_in()`, which a worker calls once at launch.

    Tri-state on purpose. `None` means "could not tell" — no CLI to ask, a timeout, an output
    shape we do not recognise — and must never be drawn as a fault. Telling somebody their login
    is missing when the truth is that we failed to ask is worse than saying nothing: they would go
    and re-do a login that was fine.
    """
    return _SIGNED_IN


def probe_signed_in() -> Optional[bool]:
    """Ask `claude auth status` once, off the GUI thread, and remember the answer.

    The SDK route deliberately runs the user's own `claude` session rather than an API key, so
    "installed" and "usable" are different states and only this call can tell them apart —
    `available()` above answers whether the PYTHON PACKAGE is present, which stays true on a
    machine nobody has ever logged in on. That gap is why a fresh install offered three Claude
    models that could not have answered any of them (found on a clean Mac, 2026-08-13).

    An `ANTHROPIC_API_KEY` is the other way the route can work, and it needs no CLI at all.
    """
    global _SIGNED_IN
    if os.environ.get("ANTHROPIC_API_KEY"):
        _SIGNED_IN = True
        return _SIGNED_IN
    binary = cli_path()
    if binary is None:
        _SIGNED_IN = None
        return _SIGNED_IN
    try:
        proc = subprocess.run(
            [binary, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=_AUTH_TIMEOUT_S, **child.quiet())
    except (OSError, subprocess.SubprocessError):
        _SIGNED_IN = None
        return _SIGNED_IN
    text = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    # Read both answers explicitly rather than treating "no true" as false: a `claude` whose
    # output we do not recognise must land on None, not on an accusation.
    if re.search(r'"loggedIn"\s*:\s*true', text):
        _SIGNED_IN = True
    elif re.search(r'"loggedIn"\s*:\s*false', text):
        _SIGNED_IN = False
    else:
        _SIGNED_IN = None
    return _SIGNED_IN


def bind(names: Iterable[str], namespace: dict) -> None:
    """Import the SDK and put `names` into `namespace` (a module's `globals()`).

    Idempotent and cheap after the first call: `import` hits `sys.modules`, and the names are
    already bound.
    """
    names = tuple(names)
    if all(name in namespace for name in names):
        return
    try:
        module = importlib.import_module("claude_agent_sdk")
    except ImportError as exc:
        raise ClaudeSdkMissing(
            "the Claude Agent SDK is not installed, so Claude routes are unavailable.\n"
            f"    {INSTALL_HINT}\n"
            "Other models (Gemini, Codex, …) run through `omp` and need no Python package."
        ) from exc
    for name in names:
        namespace[name] = getattr(module, name)
