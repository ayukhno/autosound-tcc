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
from typing import Iterable

#: The command that installs it, kept in one place so the message never drifts from the README.
INSTALL_HINT = (
    "uv tool install --upgrade "
    "'autosound-tcc[claude] @ git+https://github.com/ayukhno/autosound-tcc'"
)


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
