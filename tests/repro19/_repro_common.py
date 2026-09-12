"""`#19` bisection on the Windows runner. NOT part of the suite: no `test_` prefix on the files, so
`pytest tests/` never collects them; a series names one by path (`pytest_args`).

What is being bisected. Under cdb the crash is deterministic (2026-09-12, 5 of 5): right after
`test_attaching_an_agent_clears_the_mock_transcript`, the next `DialogPanel()` dies at
`self._chat = QWidget()`, inside `PySide::SignalManager::retrieveMetaObject` — the new object's
`metaObject()` looked its Python half up by address and got a wrapper that is not there. The
freed-memory walk after that test was clean, so what the clear leaves behind is not freed Python
memory. Which part of the clear leaves it is the question; each variant changes ONE thing.

The three tests replay the first three of `test_dialog_live.py`, which is the exact sequence cdb
showed. They assert nothing: the only result that matters is whether the process lives.
"""
from __future__ import annotations

import gc
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from autosound_tcc.core.signal_bus import SignalBus
from autosound_tcc.ui.tcc import dialog_panel
from autosound_tcc.ui.tcc.dialog_panel import DialogPanel


class FakeWorker(QObject):
    chunk = Signal(object)
    turn_done = Signal()
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.sent: list[str] = []
        self.interrupted = False

    def send(self, text):
        self.sent.append(text)

    def interrupt(self):
        self.interrupted = True


def _rows_first(panel) -> None:
    """The clear with its two halves swapped: rows out of the chat layout first, widgets after."""
    discard = dialog_panel.discard
    panel._live_bubble = None
    panel._live_text = ""
    panel._clear_new_below()
    panel._stick_to_bottom = True
    while panel._chat_layout.count() > 1:
        item = panel._chat_layout.takeAt(0)
        row = item.layout()
        if row is not None:
            while row.count():
                child = row.takeAt(0)
                widget = child.widget()
                if widget is not None:
                    discard.drop(widget)
    if panel._question_widgets is not None:
        discard.drop(panel._question_widgets)
        panel._question_widgets = None
    for bubble in panel._bubbles:
        discard.drop(bubble)
    panel._bubbles.clear()


def _take_out(layout, widget) -> bool:
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is widget:
            layout.takeAt(i)
            return True
        inner = item.layout()
        if inner is not None and _take_out(inner, widget):
            return True
    return False


def _unlayout_then_drop(widget) -> None:
    """`discard.drop` as a general fix would be: out of whatever layout holds it, THEN as today."""
    if widget is None:
        return
    parent = widget.parentWidget()
    if parent is not None and parent.layout() is not None:
        _take_out(parent.layout(), widget)
    widget.hide()
    widget.setParent(None)
    widget.deleteLater()


def _apply(variant: str, monkeypatch) -> None:
    if variant == "as-is":
        return
    if variant == "no-clear":
        monkeypatch.setattr(DialogPanel, "_clear_bubbles", lambda self: None)
    elif variant == "rows-first":
        monkeypatch.setattr(DialogPanel, "_clear_bubbles", _rows_first)
    elif variant == "no-drops":
        monkeypatch.setattr(dialog_panel.discard, "drop", lambda widget: None)
    elif variant == "delete-later-only":
        monkeypatch.setattr(dialog_panel.discard, "drop",
                            lambda w: None if w is None else (w.hide(), w.deleteLater()))
    elif variant == "set-parent-only":
        monkeypatch.setattr(dialog_panel.discard, "drop",
                            lambda w: None if w is None else (w.hide(), w.setParent(None)))
    elif variant == "unlayout-first":
        monkeypatch.setattr(dialog_panel.discard, "drop", _unlayout_then_drop)
    elif variant != "no-attach":
        raise ValueError(variant)


def _panel(variant: str, tmp_path, monkeypatch):
    _apply(variant, monkeypatch)
    panel = DialogPanel()
    if variant != "no-attach":
        panel.attach_agent(FakeWorker(), SignalBus(tmp_path), resumed=True, phase="2")
    return panel


def make_tests(variant: str):
    def test_1_mock_transcript():
        QApplication.instance() or QApplication([])
        DialogPanel()

    def test_2_attach_clears(tmp_path, monkeypatch):
        _panel(variant, tmp_path, monkeypatch)

    def test_3_next_panel(tmp_path, monkeypatch):
        # cdb's crash site: `self._chat = QWidget()` inside this constructor.
        _panel(variant, tmp_path, monkeypatch)

    return test_1_mock_transcript, test_2_attach_clears, test_3_next_panel


def make_stress(variant: str, cycles: int = 150):
    """The same sequence, looped. Replaying it once was deterministic under cdb only until the code
    around it changed: v0 crashed 2/2 on eb68d98 and 0/1 on 65a3beb, where nothing but helper
    functions had been added — the allocation pattern moved, and one reuse of one address is all
    the crash needs. A hundred and fifty cycles give a variant that leaves a bad entry a hundred
    and fifty chances; a variant that does not leave one has none, whatever the allocator does."""
    def test_stress(tmp_path, monkeypatch):
        QApplication.instance() or QApplication([])
        _apply(variant, monkeypatch)
        for _ in range(cycles):
            DialogPanel()
            panel = DialogPanel()
            if variant != "no-attach":
                panel.attach_agent(FakeWorker(), SignalBus(tmp_path), resumed=True, phase="2")
            del panel
            gc.collect()

    return test_stress
