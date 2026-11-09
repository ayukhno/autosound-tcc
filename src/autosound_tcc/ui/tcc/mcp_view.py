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


#: The strip's name for the key's standing line: one at a time, taken back when it stops being true.
_KEY_SLOT = "mcp_key"


def _key_standing(server, after_reset: bool) -> str:
    """The line that stays until the cause is fixed, or "". Holds the reason, never the key.
    Standing because it comes true again on every start, and the window's own opening lines would
    otherwise replace it before anyone read it. `after_reset`: the person asked for a new key, so
    the line also says what that did not reach, a second TCC, which read the key once at its start."""
    note = getattr(server, "key_note", mcp_key.KEPT)
    if note == mcp_key.OLD_ON_DISK:
        return i18n.t("mcpKeyOldOnDisk").format(why=server.key_problem)
    if note == mcp_key.RUN_ONLY:
        line = "mcpKeyResetRunOnly" if after_reset else "mcpKeyRunOnly"
        return i18n.t(line).format(why=server.key_problem)
    return ""


def _key_news(server) -> tuple[str, str]:
    """The line and its level for a key that changed and a session must reconnect to, else "". A
    key that did not change is not news: that is the whole of #247."""
    note = getattr(server, "key_note", mcp_key.KEPT)
    if note == mcp_key.MADE:
        return i18n.t("mcpKeyMade"), "info"
    if note == mcp_key.REPLACED:
        return i18n.t("mcpKeyReplaced"), "warn"
    if note == mcp_key.RESET:
        return i18n.t("mcpKeyReset"), "warn"
    return "", "info"


def say_started(server, strip, after_reset: bool = False) -> None:
    """What the strip says once the server is up, or its key was reset. The key's standing line
    goes up, or comes down when it stopped being true. The key's news and the advertisement's
    trouble go in one line, since the second would replace the first at once: the server is up and
    `.mcp.json` may still not be, which is real and invisible otherwise (a terminal session will
    not find TCC) but is NOT "the server did not start", which is what it used to say about a
    server that was serving (user's log, 2026-09-06)."""
    if standing := _key_standing(server, after_reset):
        strip.notify(standing, level="warn", sticky=True, slot=_KEY_SLOT)
    else:
        strip.let_go(_KEY_SLOT)
    news, level = _key_news(server)
    if error := getattr(server, "config_error", ""):
        news, level = " ".join(filter(None, [news, i18n.t("mcpNoConfig").format(error=error)])), "warn"
    if news:
        strip.notify(news, level=level)


def reset_key(host) -> None:
    """The menu's «reset key»: a new key, and the strip says who has to reconnect."""
    host._mcp_server.reset_token()
    say_started(host._mcp_server, host._status_strip, after_reset=True)


def _can_reset(host) -> bool:
    """Not with no server, and not with a dead one: nothing is listening for the new key."""
    server = host._mcp_server
    return server is not None and getattr(server, "stopped_reason", None) is None


def menu_entries() -> list:
    from autosound_tcc.ui.tcc.menu_registry import MenuEntry

    return [MenuEntry("mcp_key_reset", "settings", label_key="menuMcpKeyReset",
                      tip_key="menuMcpKeyResetTip", on=reset_key,
                      enabled=_can_reset, after="reviewer_key")]
