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


class _Spy(QLabel):
    """Records the order, because the order IS the fix."""

    def __init__(self) -> None:
        super().__init__("x")
        self.calls: list = []

    def hide(self) -> None:
        self.calls.append("hide")
        super().hide()

    def setParent(self, parent) -> None:  # noqa: N802 (Qt override)
        self.calls.append(f"setParent:{parent!r}")
        super().setParent(parent)

    def deleteLater(self) -> None:  # noqa: N802 (Qt override)
        self.calls.append("deleteLater")
        super().deleteLater()


def test_a_widget_is_hidden_before_it_is_unparented():
    """Hidden FIRST. A hidden widget has no window to map, so the reparent is invisible; the other
    way round is a window on the desktop, caught by class and title on the Arbiter's machine:
    `class='Qt6112QWindowIcon' title='Autosound TCC' 213x764`, shown and gone in 60 ms."""
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
    spies = [_Spy() for _ in range(3)]
    for spy in spies:
        layout.addWidget(spy)

    discard.clear(layout)

    assert layout.count() == 0
    for spy in spies:
        assert spy.calls[0] == "hide", "every one of them, not just the first"
        assert spy.parent() is None
