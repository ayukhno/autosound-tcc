"""End Qt's life at a moment we choose, instead of inside `Py_FinalizeEx`.

PySide registers `destroyQCoreApplication` as an `atexit` handler the moment QtCore is imported,
so a process that simply ends with widgets alive destroys them from inside `Py_FinalizeEx`: C++
destructors running against Python halves that are already going. Four of the five macOS crash
reports collected on 2026-08-18 end in exactly that:

    Py_FinalizeEx -> atexit -> destroyQCoreApplication -> ~QGraphicsScene
      -> ~QGraphicsWidget (a pyqtgraph PlotItem) -> QObjectPrivate::deleteChildren
      -> ~QWidgetActionWrapper -> Shiboken::Object::destroy -> SIGSEGV

`~QApplication` destroys whatever top-level widgets are still standing, which is how a pyqtgraph
plot ends up on an exit path nobody wrote. One full test suite leaves **16631** of them alive --
4451 QLabels, 87 MainWindows, 174 QMenus, and 39 CurveViews with 27 CurveDialogs among them --
and the process died on roughly one run in ten.

So run `~QApplication` early, in one step, while Python can still answer for its objects. That is
all `destroy_application` does, and the "in one step" is the whole point.

**Walking the widgets ourselves instead is wrong, and was measured on 2026-08-18.** Sweeping
top-level widgets with `deleteLater()` and a DeferredDelete flush -- the obvious reading of "tear
it down deterministically" -- made things dramatically WORSE: the two plot-heavy test files, which
had never crashed on their own (0 in 20), crashed 6 times in 6; the full suite 2 in 2; and a
one-window one-plot process 3 in 10 against 0 in 10 for changing nothing. Seven arrangements were
tried and every one of them only moved the SIGSEGV to a different frame -- with pyqtgraph's own
`PlotWidget.close()` and without it, holding every wrapper alive across the close, deleting the
items `close()` strands (all of them, then only the roots), dropping the `processEvents()` from
the flush, and finally skipping every plot-bearing widget outright, which still read 4 in 4. The
frames seen: `QGridLayoutEngine::fillRowData` under a `~QGraphicsScene`, `~QWidgetActionWrapper`
under `QGraphicsScene::clear`, `Shiboken::BindingManager::getOverride` under a
`~QGraphicsTextItem` and again under `QGraphicsScene::itemsBoundingRect`, and
`~QGraphicsLayoutItem` under PySide's exit-time `destructionVisitor`.

A pyqtgraph item graph cannot be taken down piecemeal under PySide 6.11 with pyqtgraph 0.13.7.
`~QApplication` can still take it down whole -- it just has to happen before Python starts
dismantling itself.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QWidget

#: How long to wait for a background thread that ignores being asked to stop. Bounded because a
#: teardown that hangs is worse than the crash it prevents: the wait only has to cover a normal
#: in-flight call, and every worker in this app talks over timeout-bounded HTTP.
_THREAD_WAIT_MS = 3000


def quiesce_widgets(widgets: Iterable[QWidget]) -> None:
    """Bring these widgets' background threads to a stop, so nothing is running when Qt goes.

    Qt calls `qFatal` on a QThread object destroyed while its thread still runs, which aborts the
    process -- the same failure `MainWindow.closeEvent` already guards against, and the reason
    this has to happen before `~QApplication` and not after. `stop_workers` and `shutdown` are the
    two methods `closeEvent` itself calls, both documented as idempotent, so a window that has
    already been closed pays nothing; they are looked for on the whole subtree because the
    measurement panel that owns the REW workers is a child, not the window. The generic QThread
    sweep afterwards is for what neither method covers -- a panel built standalone by a test never
    sees a close event at all.

    Nothing here destroys anything. Defensive throughout, because a teardown that raises would
    turn a clean exit into a traceback and a green test session into an error.
    """
    for widget in widgets:
        try:
            family = [widget, *widget.findChildren(QWidget)]
            threads = widget.findChildren(QThread)
        except RuntimeError:  # noqa: PERF203 -- its C++ half is already gone
            continue
        for member in family:
            for method in ("stop_workers", "shutdown"):
                hook = getattr(member, method, None)
                if callable(hook):
                    try:
                        hook()
                    except Exception:  # noqa: BLE001 -- a failed cleanup must not stop the rest
                        pass
        for thread in threads:
            try:
                if not thread.isRunning():
                    continue
                thread.requestInterruption()
                thread.quit()
                thread.wait(_THREAD_WAIT_MS)
            except Exception:  # noqa: BLE001 -- same reason as above
                pass


def destroy_application() -> bool:
    """Destroy the QApplication now, and report whether there was one to destroy.

    `shiboken6.delete` runs the C++ destructor immediately rather than posting an event, which is
    what makes this a single step: `~QApplication` walks the remaining top-level widgets itself,
    in Qt's own order, with no Python event pumping interleaved. Every attempt to do that walk
    from Python instead crashed -- see the module docstring.

    Anything holding a Python reference to a widget keeps a wrapper around nothing afterwards, so
    call this when the widgets are finished with: after `exec()` returns, or after the last test.
    """
    app = QApplication.instance()
    if app is None:
        return False
    quiesce_widgets(list(app.topLevelWidgets()))
    try:
        import shiboken6

        shiboken6.delete(app)
    except Exception:  # noqa: BLE001 -- a failed teardown must not become a failed exit
        return False
    return True
