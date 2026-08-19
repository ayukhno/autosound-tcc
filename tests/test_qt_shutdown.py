"""The teardown that keeps `~QApplication` from running inside `Py_FinalizeEx`.

`destroy_application` itself is not exercised here and cannot be: it destroys the QApplication
this process is still using, and every widget the plot tests deliberately hold alive for the whole
session (`_KEEP`, `_KEEP_WINDOWS`) would go with it. What is tested is the half that runs first --
stopping the background threads, without which `~QApplication` meets a live QThread and Qt calls
`qFatal`. The teardown as a whole is measured by running the suite and reading the exit code, not
by a test inside it.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from autosound_tcc.ui.tcc import qt_shutdown  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_the_close_contract_is_asked_for_across_the_whole_subtree():
    """`stop_workers` and `shutdown` are what `MainWindow.closeEvent` calls; so does this."""
    called: list[str] = []

    class _Panel(QWidget):
        def shutdown(self) -> None:
            called.append("shutdown")

    class _Window(QWidget):
        def stop_workers(self) -> None:
            called.append("stop_workers")

    _app()
    window = _Window()
    panel = _Panel(window)  # a child, the way the measurement panel sits under the window
    assert panel.parent() is window
    qt_shutdown.quiesce_widgets([window])
    assert sorted(called) == ["shutdown", "stop_workers"]


def test_a_running_thread_is_stopped_before_qt_can_be_destroyed_under_it():
    """Qt calls `qFatal` on a QThread destroyed while it runs, which aborts the whole process."""

    class _Sleeper(QThread):
        def run(self) -> None:
            while not self.isInterruptionRequested():
                self.msleep(5)

    _app()
    holder = QWidget()
    thread = _Sleeper(holder)
    thread.start()
    while not thread.isRunning():
        thread.msleep(1)
    qt_shutdown.quiesce_widgets([holder])
    assert not thread.isRunning()


def test_a_failing_cleanup_does_not_stop_the_teardown():
    """A broken teardown must not turn a clean exit into a traceback."""
    reached: list[str] = []

    class _Angry(QWidget):
        def stop_workers(self) -> None:
            raise RuntimeError("no")

    class _Calm(QWidget):
        def stop_workers(self) -> None:
            reached.append("calm")

    _app()
    qt_shutdown.quiesce_widgets([_Angry(), _Calm()])
    assert reached == ["calm"]


def test_a_widget_whose_c_half_is_gone_is_skipped():
    """The list is taken before the walk, and Qt may have destroyed something in between."""
    import shiboken6

    _app()
    widget = QWidget()
    shiboken6.delete(widget)
    qt_shutdown.quiesce_widgets([widget])  # no exception is the assertion
