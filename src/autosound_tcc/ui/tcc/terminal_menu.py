"""«Open terminal in this project…» as a submenu (tcc #180, W-10 Codex task 8).

Terminal, Claude, Codex, Antigravity, OMP — in that order, wherever the action is: the main
menu's lines (`menu_registry`, place «terminal») and the footer's button (`attach`), both drawn
from the same lines. A client that is not installed stays visible, greyed; the plain terminal is
always there. Asked again each time the submenu is about to show, by stat calls only — nothing
runs, no sign-in opens (`terminal_launcher.client_available`).

A click opens exactly the client named: one that is gone says so on the status strip, and
nothing else opens in its place — never `default_cli()`, never the pick's CLI. The window keeps
one-line calls (`_open_terminal`), so the window does not grow.
"""

from __future__ import annotations

import shlex
import sys
from typing import Optional

from PySide6.QtCore import QTimer

from autosound_tcc.core import child, config, critic, session_routes, terminal_launcher
from autosound_tcc.ui.tcc import control_layout, i18n, main_menu, menu_registry


def label(client: str) -> str:
    """What the line says for `client`; also what the status strip names after it opened."""
    if client == terminal_launcher.TERMINAL:
        return i18n.t("terminalPlain")
    return dict(terminal_launcher.MENU_CLIENTS).get(client, client)


def codex_note() -> str:
    """The plain terminal's one printed line: how to start Codex there with TCC's tools. The
    project is `.` — the shell is already in it — so no path needs quoting but the interpreter's,
    and that is the console one (`python.exe`, not the GUI's `pythonw.exe`)."""
    python = child.script_interpreter()
    if sys.platform.startswith("win"):
        start = f'"{python}" -m {session_routes.CODEX_TERMINAL} .'
    else:
        start = shlex.join([python, "-m", session_routes.CODEX_TERMINAL, "."])
    return i18n.t("codexTerminalHint").format(command=start)


def open_in(host, client: Optional[str] = None) -> None:
    """Open `client`'s terminal in the window's project; no client named → the one that carries
    the current pick (the handoff's «start in a terminal», as before #180). A refusal goes on the
    status strip and nothing else is tried."""
    project_dir = host._mcp_server.project_dir if host._mcp_server else config.project_dir()
    env = critic.session_env(project_dir)  # the reviewer's route, as in-app (hub #236)
    choice = host._generator_choice()
    # No model chosen: a named client opens on its own model; none named, the plain terminal —
    # there is no pick to carry (`client_of(None)` raised in the Qt slot, the group review, M6).
    client = client or (session_routes.client_of(choice) if choice is not None
                        else terminal_launcher.TERMINAL)
    try:
        if client == terminal_launcher.TERMINAL:
            terminal_launcher.open_shell(project_dir, env=env, note=codex_note())
            opened = label(client)
        else:
            cli, model, extra = session_routes.client_invocation(client, choice, project_dir)
            terminal_launcher.launch(project_dir, cli=cli, model=model, extra=extra, env=env)
            opened = client  # by its name: Codex's line starts with TCC's own interpreter
    except terminal_launcher.TerminalLaunchError as exc:
        host._status_strip.notify(str(exc), level="warn")
        return
    host._status_strip.notify(i18n.t("terminalOpened").format(cli=opened))
    if host._control_layout.active:
        # The terminal takes the left half (F-069, A12) — once its window exists.
        screen = host.screen().availableGeometry()
        QTimer.singleShot(1500, lambda: control_layout.place_terminal_left(screen))


def attach(button, host) -> None:
    """The footer's button opens the same lines as the main menu's submenu, enabled afresh each
    time it opens."""
    menu = main_menu.tip_menu(button)
    lines = []
    for entry in menu_registry.ordered(menu_registry.window_entries(), "terminal"):
        action = menu.addAction(entry.text())
        action.triggered.connect(lambda _checked=False, e=entry: e.on(host))
        lines.append((entry, action))

    def refresh() -> None:
        for entry, action in lines:
            action.setEnabled(bool(entry.enabled(host)) if entry.enabled else True)

    menu.aboutToShow.connect(refresh)
    refresh()
    button.setMenu(menu)
