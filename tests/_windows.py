"""What a test does with the window it built once it is done with it (TODO F-053).

A test ends with its `MainWindow` still alive — deleting windows between tests made crashes worse
(`conftest._end_qt_before_python_finalises`, `ui/tcc/qt_shutdown.py`) — and a live window keeps
running its deferred work: timers, file watchers, model pickers. Tests point `config` at their own
folder, so a window left behind resolved the NEXT test's folder and wrote into it: `.tcc/` created
by another window's model picker, a capture card emptied by another window's project watcher.

So nothing is deleted: the window is told it is closing, its timers stop and its watchers let go of
their paths. What a closing window does not do, it does not do here either.
"""

from __future__ import annotations


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
