"""The MCP server's advertisement for people: what the chat says when an omp session cannot reach
TCC through `.mcp.json` — and, with it, any launch `session_routes.blocker` refuses. Qt-free, so it
is tested as a function — `main_window.py` may not grow."""
from __future__ import annotations

from autosound_tcc.core import session_routes
from autosound_tcc.ui.tcc import i18n


#: How an MCP client names itself in the handshake → the command a person knows it by.
_CLIENT_NAMES = {"antigravity": "agy", "antigravity-cli": "agy", "gemini-cli": "gemini",
                 "gemini-cli-mcp-client": "gemini", "claude-code": "claude", "codex": "codex",
                 "codex-mcp-client": "codex"}


def client_name(client: str) -> str:
    """The footer's «a session outside TCC»: the client by the command a person knows it by
    (moved out of the window with W-10 task 9)."""
    return _CLIENT_NAMES.get(client.lower(), client) or "?"


def say(refusal: session_routes.Refusal) -> str:
    """A launch refusal as the chat says it, in the current language."""
    return i18n.t(refusal.key).format(**refusal.args)


def omp_without_config(server) -> str:
    """Why an omp session cannot start (`session_routes.omp_without_config`), as a sentence.

    The window says it through `session_routes.blocker` and `say` now; this stays for its tests,
    which pin the three sentences."""
    return say(session_routes.omp_without_config(server))
