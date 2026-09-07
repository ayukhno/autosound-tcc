"""The guard in `conftest.py` has one moving part outside our code: Qt's own error routing.

An exception raised inside a Qt slot cannot travel back through C++, so PySide6 hands it to
`sys.excepthook` and the program carries on. The whole of the conftest fixture
`_an_exception_in_a_qt_slot_fails_the_test` rests on that: if a PySide6 upgrade sends those
exceptions somewhere else (`sys.unraisablehook`, or straight to stderr), the fixture would keep
passing while catching nothing, which is the exact silence it was written to end (HUB-046).

So the routing is checked here, live, once per run.
"""

from __future__ import annotations

import sys


def test_qt_hands_a_slot_exception_to_whatever_sys_excepthook_is():
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])

    seen: list[tuple] = []
    # The conftest fixture's own recorder is installed right now. Borrow the slot and give it back
    # untouched, so this test's deliberate exception is not reported as the suite catching a bug.
    guard = sys.excepthook
    sys.excepthook = lambda *exc: seen.append(exc)
    try:
        def boom():
            raise RuntimeError("a slot that raises")

        loop = QEventLoop()
        QTimer.singleShot(0, boom)
        QTimer.singleShot(50, loop.quit)
        loop.exec()
    finally:
        sys.excepthook = guard

    assert seen, (
        "PySide6 no longer routes slot exceptions through sys.excepthook -- the guard in "
        "conftest.py is now catching nothing, and slot errors are invisible again"
    )
    kind, value, _tb = seen[0]
    assert kind is RuntimeError and str(value) == "a slot that raises"
