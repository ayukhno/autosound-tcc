"""Taking a widget out of a layout must not put a window on the desktop on the way out.

The bug this closes was hunted as a console problem for a day. It was not a subprocess at all:
`setParent(None)` makes a widget top-level, so a VISIBLE child handed `None` is a real window for
the instant before `deleteLater()` runs — sized like the panel it came from and titled with the
application name, because that is what a parentless widget inherits.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget  # noqa: E402

from autosound_tcc.ui.tcc import discard  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Spy:
    """Records the order, because the order IS the fix.

    Deliberately NOT a QWidget. `drop()` only ever calls these three methods, and overriding Qt
    virtuals — `deleteLater` above all — means Python is re-entered while C++ is destroying the
    object, which is a segfault during garbage collection rather than a failed assertion. The
    suite produced exactly that on macOS (2026-09-11) and it is not a risk worth carrying for a
    test that needs no widget at all. The real widgets are exercised below.
    """

    def __init__(self) -> None:
        self.calls: list = []

    def hide(self) -> None:
        self.calls.append("hide")

    def setParent(self, parent) -> None:  # noqa: N802 (mirrors the Qt name `drop` calls)
        self.calls.append(f"setParent:{parent!r}")

    def deleteLater(self) -> None:  # noqa: N802 (mirrors the Qt name `drop` calls)
        self.calls.append("deleteLater")


def test_a_widget_is_hidden_before_it_is_unparented():
    """Hidden FIRST. A hidden widget has no window to map, so the reparent is invisible; the other
    way round is a window on the desktop, caught by class and title on the Arbiter's machine:
    `class='Qt6112QWindowIcon' title='Autosound TCC'`, shown and gone in 60 ms.

    And `setParent(None)` stays. An outside review argued for removing it (agy, 2026-09-11) and
    the suite refuted that in one run: it also detaches from the parent's CHILD LIST, immediately,
    while `deleteLater()` waits for the event loop — so without it `test_plan_panel` counted 14
    rows where 7 were expected. Hiding a widget does not take it out of the object tree."""
    _app()
    spy = _Spy()

    discard.drop(spy)

    assert spy.calls[0] == "hide", "hidden before anything else"
    assert spy.calls[1].startswith("setParent:None"), "and only then unparented"
    assert spy.calls[2] == "deleteLater"


def test_dropping_nothing_is_not_an_error():
    """`layout.takeAt()` hands back items that are spacers, not widgets."""
    _app()
    discard.drop(None)


def test_clearing_a_layout_empties_it_without_flashing_anything():
    _app()
    holder = QWidget()
    layout = QVBoxLayout(holder)
    rows = [QLabel(str(i)) for i in range(3)]
    for row in rows:
        layout.addWidget(row)

    discard.clear(layout)

    assert layout.count() == 0
    for row in rows:
        assert not row.isVisible(), "hidden, so there is no window to map while it is unparented"
        assert row.parent() is None, "and out of the object tree at once, not on the event loop"
