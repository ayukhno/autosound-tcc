"""The MCP server's advertisement for people: what the chat says when an omp session cannot reach
TCC through `.mcp.json` — and, with it, any launch `session_routes.blocker` refuses. Qt-free, so it
is tested as a function — `main_window.py` may not grow."""
from __future__ import annotations

from autosound_tcc.core import session_routes
from autosound_tcc.ui.tcc import i18n


def say(refusal: session_routes.Refusal) -> str:
    """A launch refusal as the chat says it, in the current language."""
    return i18n.t(refusal.key).format(**refusal.args)


def omp_without_config(server) -> str:
    """Why an omp session cannot start (`session_routes.omp_without_config`), as a sentence.

    The window says it through `session_routes.blocker` and `say` now; this stays for its tests,
    which pin the three sentences."""
    return say(session_routes.omp_without_config(server))
