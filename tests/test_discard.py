"""Taking a widget out of a layout must not put a window on the desktop on the way out.

The bug this closes was hunted as a console problem for a day. It was not a subprocess at all:
`setParent(None)` makes a widget top-level, so a VISIBLE child handed `None` is a real window for
the instant before `deleteLater()` runs — sized like the panel it came from and titled with the
application name, because that is what a parentless widget inherits.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget  # noqa: E402

from autosound_tcc.ui.tcc import discard  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Spy:
    """Records the order, because the order IS the fix.

    Deliberately NOT a QWidget. `drop()` only ever calls these methods, and overriding Qt
    virtuals — `deleteLater` above all — means Python is re-entered while C++ is destroying the
    object, which is a segfault during garbage collection rather than a failed assertion. The
    suite produced exactly that on macOS (2026-09-11) and it is not a risk worth carrying for a
    test that needs no widget at all. The real widgets are exercised below.
    """

    def __init__(self, calls: list | None = None) -> None:
        self.calls: list = [] if calls is None else calls
        self.parent = None

    def parentWidget(self):  # noqa: N802 (mirrors the Qt name `drop` calls)
        return self.parent

    def hide(self) -> None:
        self.calls.append("hide")

    def setParent(self, parent) -> None:  # noqa: N802 (mirrors the Qt name `drop` calls)
        self.calls.append(f"setParent:{parent!r}")

    def deleteLater(self) -> None:  # noqa: N802 (mirrors the Qt name `drop` calls)
        self.calls.append("deleteLater")


class _SpyItem:
    def __init__(self, widget=None, layout=None) -> None:
        self._widget, self._layout = widget, layout

    def widget(self):
        return self._widget

    def layout(self):
        return self._layout


class _SpyLayout:
    def __init__(self, calls: list, name: str, items: list) -> None:
        self.calls, self.name, self.items = calls, name, list(items)

    def count(self) -> int:
        return len(self.items)

    def itemAt(self, index):  # noqa: N802 (mirrors the Qt name `drop` calls)
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):  # noqa: N802 (mirrors the Qt name `drop` calls)
        self.calls.append(f"takeAt:{self.name}:{index}")
        return self.items.pop(index)


class _SpyParent:
    def __init__(self, layout) -> None:
        self._layout = layout

    def layout(self):
        return self._layout


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


def test_a_widget_leaves_its_layout_before_it_is_unparented():
    """`#19`, the Windows access violation that killed a CI run in two of three.

    `setParent(None)` on a widget that is still in a layout makes Qt delete the widget's
    `QWidgetItem` in C++ — and PySide had made a Python wrapper for that item when the row went
    into the chat (`addLayoutOwnership`), which nobody tells. The wrapper stays in shiboken's
    address table. The next Qt object built on that address looks its Python half up by address
    alone and dies in `SignalManager::retrieveMetaObject` (cdb, 10 captures of 10).

    Measured on the Windows runner under cdb, 150 cycles per attempt of build panel → attach
    (which clears the transcript) → build the next panel:

        as it was (hide, setParent(None), deleteLater)          crashed 2 of 2, first attempt
        hide + setParent(None), no deleteLater                  crashed 2 of 2
        hide + deleteLater, no setParent(None)                  0 in 1500 cycles
        rows taken out of the chat first, then dropped          0 in 1500 cycles
        widget taken out of ITS layout first, then as it was    0 in 1500 cycles  ← this

    So the widget leaves the layout first — the row it sits in, however deep — and only then is
    it hidden, unparented and scheduled, in the order the test above still holds.
    """
    _app()
    calls: list = []
    spy = _Spy(calls)
    row = _SpyLayout(calls, "row", [_SpyItem(), _SpyItem(widget=spy)])  # a stretch, then the bubble
    chat = _SpyLayout(calls, "chat", [_SpyItem(layout=row), _SpyItem()])
    spy.parent = _SpyParent(chat)

    discard.drop(spy)

    assert calls == ["takeAt:row:1", "hide", "setParent:None", "deleteLater"]
    assert chat.count() == 2, "only the widget leaves; the row it sat in stays where it is"


def test_a_widget_in_a_nested_row_goes_and_the_row_stays():
    _app()
    holder = QWidget()
    chat = QVBoxLayout(holder)
    row = QHBoxLayout()
    bubble = QLabel("bubble")
    row.addWidget(bubble)
    row.addStretch(1)
    chat.addLayout(row)

    discard.drop(bubble)

    assert row.count() == 1, "the bubble's item left the row, the stretch stayed"
    assert chat.count() == 1
    assert not bubble.isVisible()
    assert bubble.parent() is None


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
