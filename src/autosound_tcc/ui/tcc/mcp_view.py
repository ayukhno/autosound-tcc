"""The MCP server's advertisement for people: what the chat says when an omp session cannot reach
TCC through `.mcp.json` — and, with it, any launch `session_routes.blocker` refuses — and what the
strip says about the server's key (#247). Qt-free, so it is tested as a function — `main_window.py`
may not grow."""
from __future__ import annotations

from autosound_tcc.core import mcp_key, session_routes
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


def _say_key(server, strip) -> None:
    """The line for what became of the key — when a session must reconnect, and only then. A key
    that did not change is not news: that is the whole of #247. Holds the reason, never the key."""
    note = getattr(server, "key_note", mcp_key.KEPT)
    if note == mcp_key.MADE:
        strip.notify(i18n.t("mcpKeyMade"))
    elif note == mcp_key.REPLACED:
        strip.notify(i18n.t("mcpKeyReplaced"), level="warn")
    elif note == mcp_key.RESET:
        strip.notify(i18n.t("mcpKeyReset"), level="warn")
    elif note == mcp_key.RUN_ONLY:
        # Standing: it comes true again on every start until the cause is fixed, and the window's
        # own opening lines would otherwise replace it before anyone read it.
        strip.notify(i18n.t("mcpKeyRunOnly").format(why=server.key_problem), level="warn",
                     sticky=True)


def say_started(server, strip) -> None:
    """What the strip says once the server is up, or its key was reset: the key's line, then the
    advertisement's — the server is up and `.mcp.json` may still not be, which is real and
    invisible otherwise (a terminal session will not find TCC) but is NOT "the server did not
    start", which is what it used to say about a server that was serving (user's log, 2026-09-06)."""
    _say_key(server, strip)
    if getattr(server, "config_error", ""):
        strip.notify(i18n.t("mcpNoConfig").format(error=server.config_error), level="warn")


def reset_key(host) -> None:
    """The menu's «reset key»: a new key, and the strip says who has to reconnect."""
    host._mcp_server.reset_token()
    say_started(host._mcp_server, host._status_strip)


def menu_entries() -> list:
    from autosound_tcc.ui.tcc.menu_registry import MenuEntry

    return [MenuEntry("mcp_key_reset", "settings", label_key="menuMcpKeyReset",
                      tip_key="menuMcpKeyResetTip", on=reset_key,
                      enabled=lambda w: w._mcp_server is not None, after="reviewer_key")]
