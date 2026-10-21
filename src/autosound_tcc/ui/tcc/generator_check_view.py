"""The main AI picker's check, on screen: the line beside the pick and the worker that asks
(finding 160, tcc#222). What it says is decided in `core.generator_check`; this only draws it.

Out of `main_window` (the structure ratchet, G13): the window holds one of these and tells it of a
pick. The host gives `_generator_choice()` (the pick on screen), `_ai_main_combo` (the picker,
whose key outlives a pick the registry lost), `_reload_model_choices(offer=)` (the lists the check
read, into the pickers) and `_refresh_main_warning()` (the picker's own tint, which asks `tint()`).
"""
from __future__ import annotations

import shiboken6
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
        self._checked = None  # the pick the running (or last) check asked about
        self._closed = False
        self.checks = generator_check.Checks()
        self.label = ElidedLabel("", min_width=40, policy=QSizePolicy.Policy.Maximum)
        self.label.setProperty("class", "kv-val")
        self.label.setVisible(False)
        i18n.on_language_changed(self._retranslate)  # the window's own pass does not reach it

    def picked(self, choice) -> None:
        """A pick was made: ask its route now, or after the check that is running."""
        if self.checks.picked(choice) is not None:
            self._start(choice)
        self.show()

    def _start(self, choice) -> None:
        worker = self._make(choice)
        worker.done.connect(self._answered)
        worker.finished.connect(self._ended)
        self._worker, self._checked = worker, choice
        worker.start()

    def _pick(self):
        """The pick on screen. One its route's list does not name leaves the registry with the
        reload its answer causes, while the picker keeps its key in a «missing» row: that is still
        the pick that was checked, and the line goes on saying why (the group review)."""
        pick = self._host._generator_choice()
        result, checked = self.checks.result, self._checked
        if pick is None and result is not None and checked is not None and checked.key == result.key:
            combo = getattr(self._host, "_ai_main_combo", None)
            if combo is not None and str(combo.currentData() or "") == result.key:
                return checked
        return pick

    def _answered(self, result) -> None:
        if self._closed:
            return
        pick = self._pick()
        if self.checks.answered(result, pick.key if pick is not None else None):
            # The lists and logins it read are the pickers' own: a model gone from this login's
            # list turns red there as well. With no «gone» dialog: an answer that comes on its own
            # seconds after a pick opened a modal from a callback, inviting a machine-wide alias
            # for a model only this login lacks — the line and the frame already say it (W-11's
            # final review, I1). The launch and ↻ still offer one.
            self._host._reload_model_choices(offer=False)
        self.show()

    def _ended(self) -> None:
        if self._closed:
            return
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

    def tint(self) -> dict:
        """The picker's frame for `availability_view.mark_missing`: green for a listed pick, red for
        one the login does not list or a signed-out route — the line's red reaches the picker too.

        Asked whenever the window re-tints the picker, and the line is redrawn here as well: a pick
        changed with the picker's signals blocked — a reload, an accepted replacement, a new
        project's model — reaches the line only this way (the group review)."""
        said = self.state()
        self._draw(said)
        return {"ok": said.frame == "ok", "refused": said.frame == "missing"}

    def show(self) -> None:
        self._draw(self.state())
        self._host._refresh_main_warning()

    def _draw(self, said: generator_check.Shown) -> None:
        text = i18n.t(said.note).format(**said.args) if said.note else ""
        self.label.setText(text)
        self.label.set_tip(i18n.t(said.tip).format(**said.args) if said.tip else "")
        self.label.setVisible(bool(text))
        self.label.setProperty("class", "kv-val kv-warn" if said.frame == "missing" else "kv-val")
        self.label.style().unpolish(self.label)
        self.label.style().polish(self.label)

    def _retranslate(self) -> None:
        if not self._closed and shiboken6.isValid(self.label):
            self._draw(self.state())

    def stop(self) -> None:
        """The window is closing: the check is asked to stop, and handed over if it will not."""
        self._closed = True
        worker = self._worker
        if worker is None:
            return
        # Before the wait, not only on a detach: `stop_or_detach` cuts `done` only for a worker it
        # hands over, and one that answers during the wait — or starts after it — reached
        # `_answered` and reloaded a closing window's pickers (the group review).
        for signal, slot in ((worker.done, self._answered), (worker.finished, self._ended)):
            try:  # these slots only: a bare disconnect would cut `qt_shutdown.watch`'s `finished`
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        qt_shutdown.stop_or_detach(worker, 2000, mute=[worker.done])
