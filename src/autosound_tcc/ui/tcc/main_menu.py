"""The one renderer of the main menu: `menu_registry`'s lines drawn as a QMenu tree (G13 A2, #161).

Rebuilt rather than retranslated: a menu's labels are set once at construction, so a language
switch draws the whole tree again (`render`), which is also what keeps the language ticks honest.
Every line is wired the same way — `triggered`, never `toggled`, and through `_fire`, so a handler
gets the host and nothing of Qt's: the `checked` flag once landed in `seed` and in `opening`.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPoint, QUrl
from PySide6.QtGui import QAction, QCursor, QDesktopServices
from PySide6.QtWidgets import QMenu

from autosound_tcc.core import app_log
from autosound_tcc.ui.tcc import i18n, menu_registry, rounded_tooltip
from autosound_tcc.ui.tcc.menu_registry import MenuEntry


def tip_menu(parent) -> QMenu:
    """A menu styled and tipped like the rest of the app.

    `setToolTipsVisible` is deliberately NOT used: the platform tooltip's window frame stays
    square on macOS whatever the QSS says, which is the exact limitation `rounded_tooltip`
    exists for. The menu drives the shared rounded popup as the highlight moves instead.
    """
    menu = QMenu(parent)
    menu.setProperty("class", "support-menu")
    menu.hovered.connect(show_action_tip)
    menu.aboutToHide.connect(rounded_tooltip.RoundedTooltip.instance().hide_tip)
    return menu


def show_action_tip(action) -> None:
    tip = action.toolTip()
    popup = rounded_tooltip.RoundedTooltip.instance()
    if not tip or tip == action.text():
        popup.hide_tip()
        return
    popup.show_at(QCursor.pos(), tip)


def add_heading(menu, text) -> None:
    """A visible section heading.

    NOT `QMenu.addSection`, which is the obvious call and draws nothing here: with a custom
    stylesheet Qt renders a section as a plain separator and drops its text on the floor
    (grabbed the menu and looked -- five headings, none of them visible). A disabled action
    is text a style cannot swallow, and it is unclickable, which is what a heading is.
    """
    if not menu.isEmpty():
        menu.addSeparator()
    # Upper case in the text, because QSS has no `text-transform` -- and the caps are how
    # every other label in this window says "this names what is under it" (`apply_caps`).
    heading = menu.addAction(text.upper())
    heading.setEnabled(False)


def popup(anchor, entries, host) -> QMenu:
    """`entries` as a menu of their own for `anchor` — the footer's coffee button, the impulse path
    to the menu's support lines (user, 2026-07-28): one click instead of three."""
    menu = tip_menu(anchor)
    for entry in entries:
        action = menu.addAction(entry.text())
        action.triggered.connect(lambda _checked=False, e=entry: _act(e, host))
    return menu


def show_above(anchor, menu) -> None:
    """Open `menu` upward from `anchor`: the footer sits on the window's bottom edge."""
    top_left = anchor.mapToGlobal(QPoint(0, 0))
    menu.adjustSize()
    menu.exec(QPoint(top_left.x(), top_left.y() - menu.sizeHint().height()))


def _act(entry: MenuEntry, host) -> None:
    if entry.on is not None:
        entry.on(host)
    elif entry.url is not None:
        QDesktopServices.openUrl(QUrl(entry.url()))


def _embolden(action) -> None:
    font = action.font()
    font.setBold(True)
    action.setFont(font)


class MainMenu:
    """The ☰ button's menu, drawn from `entries()` (by default every line `collect()` finds)."""

    def __init__(self, button, host,
                 entries: Optional[Callable[[], list[MenuEntry]]] = None) -> None:
        self._button = button
        self._host = host
        self._entries = entries or menu_registry.collect
        self._actions: dict[str, QAction] = {}
        self._lines: list[tuple[MenuEntry, QAction]] = []

    def render(self) -> QMenu:
        entries = self._entries()
        for problem in menu_registry.problems(entries, set(i18n.T["en"])):
            app_log.logger().warning("main menu: %s", problem)
        self._actions, self._lines = {}, []
        menu = tip_menu(self._button)
        for section, key in menu_registry.SECTIONS:
            add_heading(menu, i18n.t(key))
            self._fill(menu, entries, section)
        previous = self._button.menu()
        self._button.setMenu(menu)
        if previous is not None:
            # Deferred, never here: this can run from inside a language action's own handler, and
            # destroying the menu that emitted it is the crash shape this app has paid for twice.
            previous.deleteLater()
        self._set_aliases()
        # The ticks and enabled states the freshly built lines do not have yet.
        self.sync()
        return menu

    def sync(self) -> None:
        """Re-ask every line whether it is enabled and whether it is ticked. A line whose state
        cannot be asked is shown off and unticked, and logged; the others still sync."""
        for entry, action in self._lines:
            try:
                action.setEnabled(bool(entry.enabled(self._host)) if entry.enabled else True)
                if entry.checked is not None:
                    action.setChecked(bool(entry.checked(self._host)))
            except Exception:  # noqa: BLE001 — one line must not stop the menu's state
                app_log.logger().warning("main menu: the line %r could not say its state",
                                         entry.id, exc_info=True)
                action.setEnabled(False)
                action.setChecked(False)

    def action(self, entry_id: str) -> Optional[QAction]:
        return self._actions.get(entry_id)

    def _fill(self, menu: QMenu, entries, place: str) -> None:
        for entry in menu_registry.ordered(entries, place):
            if entry.submenu:
                sub = tip_menu(menu)
                sub.setTitle(entry.text())
                self._fill(sub, entries, entry.id)
                action = menu.addMenu(sub)
            else:
                action = menu.addAction(entry.text())
                action.setCheckable(entry.checked is not None)
                action.triggered.connect(lambda _checked=False, e=entry: self._fire(e))
            if entry.tip_key:
                action.setToolTip(entry.tip())
            if entry.bold:
                _embolden(action)
            self._actions[entry.id] = action
            self._lines.append((entry, action))

    def _fire(self, entry: MenuEntry) -> None:
        _act(entry, self._host)

    def _set_aliases(self) -> None:
        """The window attributes tests drive lines by; a dict alias starts empty on each render,
        so its order is the order drawn."""
        fresh: set[str] = set()
        for entry, action in self._lines:
            if not entry.alias:
                continue
            if not entry.alias_key:
                setattr(self._host, entry.alias, action)
                continue
            if entry.alias not in fresh:
                setattr(self._host, entry.alias, {})
                fresh.add(entry.alias)
            getattr(self._host, entry.alias)[entry.alias_key] = action
