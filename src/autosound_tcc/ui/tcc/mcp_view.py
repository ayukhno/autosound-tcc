"""The MCP server's advertisement for people: what the chat says when an omp session cannot reach
TCC through `.mcp.json`. Qt-free, so it is tested as a function — `main_window.py` may not grow."""
from __future__ import annotations

from autosound_tcc.ui.tcc import i18n


def omp_without_config(server) -> str:
    """Why an omp session cannot start: omp reaches TCC only through `.mcp.json`, and TCC's entry
    is not in it. A file TCC could not read is named, and the advice is to check it; the folder's
    write permission would not open it (#173, the review of Task 19, M4). A damaged file TCC read
    but could not move aside is named too, and the advice is to fix or remove it, or to make the
    folder writable (N2). A write that failed keeps the folder's advice."""
    unmoved = getattr(server, "config_unmoved", None)
    if unmoved:
        return i18n.t("mcpConfigUnmovedOmp").format(path=unmoved, error=server.config_error)
    unreadable = getattr(server, "config_unreadable", None)
    if unreadable:
        return i18n.t("mcpConfigUnreadOmp").format(path=unreadable, error=server.config_error)
    return i18n.t("mcpNoConfigOmp").format(error=server.config_error)
