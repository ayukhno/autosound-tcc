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

import logging
import sys
import threading
import weakref
from collections.abc import Iterable

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QWidget

_log = logging.getLogger("autosound_tcc")

#: How long to wait for a background thread that ignores being asked to stop. Bounded because a
#: teardown that hangs is worse than the crash it prevents: the wait only has to cover a normal
#: in-flight call, and every worker in this app talks over timeout-bounded HTTP.
_THREAD_WAIT_MS = 3000

#: Threads still running with no widget behind them (F-027).
#:
#: A window that is closing cannot wait indefinitely for its own worker and cannot destroy it
#: either — Qt answers a QThread destroyed while running with `qFatal`. So it hands it here: the
#: set is what keeps the object alive, since a parentless QThread lives exactly as long as some
#: Python reference to it does. `quiesce_widgets` could never have covered these, and not only
#: after they are detached: it looks for threads with `findChildren`, and every REW worker in this
#: app is built with NO parent, so it was never a child of the widget that started it.
_DETACHED: set = set()


def detach(thread: QThread) -> None:
    """Take a still-running thread off a closing widget's hands; forget it when it ends.

    `finished` crosses back as a queued connection — the thread OBJECT's affinity is the GUI
    thread, whatever its `run` is doing — so the set is only ever touched from one thread.
    """
    _DETACHED.add(thread)
    thread.finished.connect(lambda: _DETACHED.discard(thread))


def watch(thread: QThread) -> QThread:
    """Have this worker say who it was when it is destroyed. Returns it, so it can wrap a `self`.

    MEASURED, 2026-09-20 (finding 35): dropping the last external reference to a RUNNING worker
    aborts the process, and the destructor runs on the worker's OWN thread right after `run()`
    returns — from the moment the external reference goes, the running frame holds the only one,
    and the frame dies when `run()` does. Qt then prints `QThread: Destroyed while thread '' is
    still running` and calls `abort()`.

    That message does not say WHICH worker, and the app has eight kinds. Three crashes were
    collected from the Arbiter's machine (2026-08-27, twice on 2026-09-19) and none of them could
    be pinned to a worker by reading the log. This line lands immediately before Qt's, and names
    it.

    A `weakref.finalize` rather than `__del__`: it cannot resurrect the object, it runs even when
    the object dies inside a reference cycle, and it carries no reference of its own — a
    `__del__` on a QThread subclass would keep every worker alive until the collector felt like
    it, which is the opposite of what this is for. The finalizer may not touch `thread`, so what
    it needs is captured now: the class name, and a flag a `finished` connection sets.
    """
    name = type(thread).__name__
    # `started` as well as `finished`: a worker built and never started has not finished either,
    # and warning about those buries the one line that matters — the suite alone produced five of
    # them the first time this ran. Only a worker that RAN and did not finish is the fatal shape.
    state = {"started": False, "finished": False}
    thread.started.connect(lambda: state.__setitem__("started", True))
    thread.finished.connect(lambda: state.__setitem__("finished", True))
    weakref.finalize(thread, _gone, name, state)
    return thread


def _gone(name: str, state: dict) -> None:
    """One line about a worker's death — loud when it is the fatal shape, quiet otherwise."""
    where = "GUI" if threading.current_thread() is threading.main_thread() else "a worker"
    if state.get("finished") or not state.get("started"):
        _log.debug("worker %s destroyed on %s thread (started=%s finished=%s)",
                   name, where, state.get("started"), state.get("finished"))
        return
    # Not "probably": Qt aborts on this, and the abort is the next thing in the log.
    _log.warning(
        "worker %s destroyed on %s thread while it had NOT finished — this is the abort "
        "(finding 35). Whoever dropped the last reference to it is the bug.", name, where
    )


def detached() -> frozenset:
    """What is running with nothing behind it. For the exit path, and for tests to check."""
    return frozenset(_DETACHED)


def stop_or_detach(thread: QThread | None, wait_ms: int, mute: Iterable = ()) -> bool:
    """Ask a worker to stop; hand it over here if it will not, rather than destroying it.

    The one move a closing widget can make that is neither `abort()` nor a hang, and the whole of
    F-027. `mute` is the worker's own signals — cut before it is let go, so nothing arrives at a
    widget that is already on its way out. True when it had to be detached.

    `requestInterruption` is a REQUEST: a worker whose `run` never reads it simply does not stop
    early, and that is not a reason to skip asking. What makes this safe either way is the branch
    below, not the worker's cooperation.
    """
    if thread is None or not thread.isRunning():
        return False
    thread.requestInterruption()
    if thread.wait(wait_ms):
        return False
    for signal in mute:
        try:
            signal.disconnect()
        except (RuntimeError, TypeError):  # nothing connected, or the receiver is already gone
            pass
    detach(thread)
    return True


def _stop(thread: QThread) -> bool:
    """Ask one thread to stop and wait out the bounded grace. True when it is still running."""
    if not thread.isRunning():
        return False
    thread.requestInterruption()
    thread.quit()
    thread.wait(_THREAD_WAIT_MS)
    return thread.isRunning()


def quiesce_widgets(widgets: Iterable[QWidget]) -> list[QThread]:
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

    Returns the threads that were STILL RUNNING when the wait ran out. That answer used to be
    thrown away, and `destroy_application` deleted the QApplication regardless -- which is not
    bad luck but a guarantee: Qt calls `qFatal` on a QThread destroyed while its thread runs, so
    an agent worker busy with a model turn (5s of grace against a turn that takes minutes) ended
    the process with `abort()` and a macOS crash report, every time (user, 2026-08-21 19:00).
    """
    stubborn: list[QThread] = []
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
                if _stop(thread):
                    stubborn.append(thread)
            except Exception:  # noqa: BLE001 -- same reason as above
                pass
    return stubborn


def quiesce_detached() -> list[QThread]:
    """The same, for the threads no widget owns any more. Returns those still running."""
    stubborn: list[QThread] = []
    for thread in list(_DETACHED):
        try:
            if _stop(thread):
                stubborn.append(thread)
        except Exception:  # noqa: BLE001 -- a failed cleanup must not stop the rest
            pass
    return stubborn


def destroy_application() -> bool:
    """Destroy the QApplication now. Answers whether Qt is safe to leave behind.

    `True` means there is nothing left that can fault on the way out -- either the application
    was destroyed here, or there was none to destroy. `False` means it DECLINED: a background
    thread outlived the wait, and destroying the application would run `~QThread` against a
    running thread, which is `qFatal` and `abort()` rather than an error anyone can catch. The
    caller has to leave the process without letting PySide's own `atexit` handler try the same
    thing (see `app.main`).

    Refusing is the third option nobody had taken: the wait is bounded because "a teardown that
    hangs is worse than the crash it prevents" -- true, and it left only two outcomes, both of
    them bad. Leaving without tidying is worse than a clean exit and much better than handing
    someone a crash report for work they had already saved.

    `shiboken6.delete` runs the C++ destructor immediately rather than posting an event, which is
    what makes this a single step: `~QApplication` walks the remaining top-level widgets itself,
    in Qt's own order, with no Python event pumping interleaved. Every attempt to do that walk
    from Python instead crashed -- see the module docstring.

    Anything holding a Python reference to a widget keeps a wrapper around nothing afterwards, so
    call this when the widgets are finished with: after `exec()` returns, or after the last test.
    """
    app = QApplication.instance()
    if app is None:
        return True
    still_running = quiesce_widgets(list(app.topLevelWidgets())) + quiesce_detached()
    if still_running:
        names = ", ".join(t.objectName() or type(t).__name__ for t in still_running)
        # Not silent: an exit that skipped its own teardown is a fact about the run, and the
        # thread that would not stop is the one worth naming when it happens twice.
        print(f"autosound-tcc: leaving without destroying Qt -- still running: {names}",
              file=sys.stderr)
        return False
    try:
        import shiboken6

        shiboken6.delete(app)
    except Exception:  # noqa: BLE001 -- a failed teardown must not become a failed exit
        return False
    return True
