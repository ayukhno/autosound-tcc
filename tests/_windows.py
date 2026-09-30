"""What a test does with the window it built once it is done with it (TODO F-053), and how it
keeps a theme or a language switch to its own widgets (F-065).

A test ends with its `MainWindow` still alive — deleting windows between tests made crashes worse
(`conftest._end_qt_before_python_finalises`, `ui/tcc/qt_shutdown.py`) — and a live window keeps
running its deferred work: timers, file watchers, model pickers. Tests point `config` at their own
folder, so a window left behind resolved the NEXT test's folder and wrote into it: `.tcc/` created
by another window's model picker, a capture card emptied by another window's project watcher.

So nothing is deleted: the window is told it is closing, its timers stop and its watchers let go of
their paths. What a closing window does not do, it does not do here either.
"""

from __future__ import annotations

import sys


def main_windows() -> list:
    """Every live `MainWindow`, from the window module's own weak registry (`_live_windows`).

    Not by walking `QApplication.topLevelWidgets()`: that is every menu, tooltip and dialog the
    run has left alive, each given a Python wrapper to be asked its type, twice per test -- 99 s
    of the 2730-s serial run on the Mac at 956e8a8 (F-065). Empty while nothing has imported the
    window."""
    module = sys.modules.get("autosound_tcc.ui.tcc.main_window")
    if module is None:
        return []
    return [window for window in list(module._live_windows)
            if type(window).__name__ == "MainWindow"]


def quiet(window) -> None:
    """Stop a test's window from acting on anything after its test."""
    import shiboken6
    from PySide6.QtCore import QFileSystemWatcher, QTimer

    if not shiboken6.isValid(window):
        return
    window._closing = True
    for timer in window.findChildren(QTimer):
        timer.stop()
    for watcher in window.findChildren(QFileSystemWatcher):
        paths = list(watcher.files()) + list(watcher.directories())
        if paths:
            watcher.removePaths(paths)


class _StandIn:
    """What `theme.apply_theme` asks of the application -- its palette and its sheet -- answered
    by one widget instead."""

    def __init__(self, widget) -> None:
        self._widget = widget

    def palette(self):
        return self._widget.palette()

    def setPalette(self, palette) -> None:  # noqa: N802 (Qt's name)
        self._widget.setPalette(palette)

    def setStyleSheet(self, sheet) -> None:  # noqa: N802 (Qt's name)
        self._widget.setStyleSheet(sheet)


def theme_on(monkeypatch, widget, mode, scale=1.0):
    """`theme.apply_theme(app, mode, scale)`, with `widget` standing in for the application: the
    palette and the sheet go on that widget alone, and the current theme and the record of what
    was applied are set as the real call sets them -- and put back at teardown (F-065).

    `QApplication.setStyleSheet` re-polishes every widget in the process, and the windows of every
    test before this one are still alive (F-053): 0.13 s for each window they left, so late in one
    process a theme switch cost more than a minute. A widget's own sheet is the one it and its
    children resolve first, so what they draw and measure is the same. The application's sheet
    and palette are never touched, so nothing needs putting back there."""
    from autosound_tcc.ui.tcc import theme

    monkeypatch.setattr(theme, "_APPLIED", theme._APPLIED)
    monkeypatch.setattr(theme, "_CURRENT", theme._CURRENT)
    return theme.apply_theme(_StandIn(widget), mode, scale)


def theme_on_the_window(monkeypatch, window) -> None:
    """Have `window`'s own theme calls -- a zoom, a theme switch -- go through `theme_on`, onto
    that window alone, for the rest of the test (F-065). The zoom tests pin their numbers, and
    those did not move."""
    from autosound_tcc.ui.tcc import main_window

    monkeypatch.setattr(main_window, "apply_theme",
                        lambda _app, mode, scale=1.0: theme_on(monkeypatch, window, mode, scale))


def language_listeners() -> list:
    """What `i18n.set_language` calls now -- the entries themselves, so none of them can be freed
    and its id handed to a later one (the reason `_quiet_windows_left_behind` holds wrappers).
    Empty while nothing has imported the UI."""
    i18n = sys.modules.get("autosound_tcc.ui.tcc.i18n")
    return list(i18n._listeners) if i18n is not None else []


def drop_language_listeners_since(before: list) -> None:
    """Take out of `i18n`'s list every listener registered since `before` was read (F-065): a
    finished test's panes keep the words they had, and the next language switch -- or the next
    window, which switches to its saved language as it is built -- does not redo them."""
    i18n = sys.modules.get("autosound_tcc.ui.tcc.i18n")
    if i18n is None:
        return
    kept = {id(entry) for entry in before}
    i18n._listeners[:] = [entry for entry in i18n._listeners if id(entry) in kept]
