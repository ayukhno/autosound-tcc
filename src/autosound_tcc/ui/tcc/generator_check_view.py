"""The main AI picker's check, on screen: the line beside the pick and the worker that asks
(finding 160, tcc#222). What it says is decided in `core.generator_check`; this only draws it.

Out of `main_window` (the structure ratchet, G13): the window holds one of these and tells it of a
pick. The host gives `_generator_choice()` (the pick on screen), `_reload_model_choices()` (the
lists the check read, into the pickers) and `_refresh_main_warning()` (the picker's own tint,
which asks `ok()`).
"""
from __future__ import annotations

from PySide6.QtWidgets import QSizePolicy

from autosound_tcc.core import generator_check
from autosound_tcc.ui.tcc import i18n, qt_shutdown
from autosound_tcc.ui.tcc.labels import ElidedLabel


class GeneratorCheckView:
    def __init__(self, host, worker=None) -> None:
        if worker is None:
            from autosound_tcc.ui.tcc.workers import GeneratorCheckWorker as worker
        self._host = host
        self._make = worker
        self._worker = None
        self.checks = generator_check.Checks()
        self.label = ElidedLabel("", min_width=40, policy=QSizePolicy.Policy.Maximum)
        self.label.setProperty("class", "kv-val")
        self.label.setVisible(False)

    def picked(self, choice) -> None:
        """A pick was made: ask its route now, or after the check that is running."""
        if self.checks.picked(choice) is not None:
            self._start(choice)
        self.show()

    def _start(self, choice) -> None:
        worker = self._make(choice)
        worker.done.connect(self._answered)
        worker.finished.connect(self._ended)
        self._worker = worker
        worker.start()

    def _pick(self):
        return self._host._generator_choice()

    def _answered(self, result) -> None:
        pick = self._pick()
        if self.checks.answered(result, pick.key if pick is not None else None):
            # The lists and logins it read are the pickers' own: a model gone from this login's
            # list turns red there as well.
            self._host._reload_model_choices()
        self.show()

    def _ended(self) -> None:
        pick = self._pick()
        if self.checks.ended(pick) is not None:
            self._start(pick)
        self.show()

    def state(self) -> generator_check.Shown:
        pick = self._pick()
        return generator_check.shown(pick, self.checks.result, self.checks.checking(pick))

    def ok(self) -> bool:
        """Whether the picker is framed green: its route's list for this login names the pick."""
        return self.state().frame == "ok"

    def show(self) -> None:
        said = self.state()
        text = i18n.t(said.note).format(**said.args) if said.note else ""
        self.label.setText(text)
        self.label.set_tip(i18n.t(said.tip).format(**said.args) if said.tip else "")
        self.label.setVisible(bool(text))
        self.label.setProperty("class", "kv-val kv-warn" if said.frame == "missing" else "kv-val")
        self.label.style().unpolish(self.label)
        self.label.style().polish(self.label)
        self._host._refresh_main_warning()

    def stop(self) -> None:
        """The window is closing: the check is asked to stop, and handed over if it will not."""
        worker = self._worker
        if worker is None:
            return
        try:  # this slot only: a bare disconnect would cut `qt_shutdown.watch`'s own `finished`
            worker.finished.disconnect(self._ended)
        except (RuntimeError, TypeError):
            pass
        qt_shutdown.stop_or_detach(worker, 2000, mute=[worker.done])
