"""The window `CurveView` lives in: pull the named measurements out of REW, show them, read back.

Opened when the model and the Arbiter disagree about a number — by the model itself, eventually,
through an MCP tool that names the measurements and its own reading. Until that lands, `show()`
is the entry point and it takes the same arguments the tool will.

The REW read runs on a QThread for the reason every other REW call in this app does: `rew_api`
speaks plain synchronous `urllib`, and a GUI thread that waits on HTTP is a window that stops
repainting while somebody is sitting in a car with the engine off.
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from autosound_tcc.core import config, delay_bank
from autosound_tcc.core.rew_bridge import RewBridge
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.curve_view import _TRACE_TOKENS, CurveView, Trace

#: What can be plotted, and how each one is fetched and labelled. Impulse first because that is
#: where the argument that prompted this happened; the others are the same widget with a different
#: reader, added when they are actually asked for rather than because a menu looked incomplete.
KINDS = {
    "impulse": {"label_x": "ms", "scale_x": 1000.0, "log_x": False, "label_y": ""},
    "fr": {"label_x": "Hz", "scale_x": 1.0, "log_x": True, "label_y": "dB"},
    # Phase is where a crossover argument actually gets settled (Δφ at the joint, then Δt from
    # it), and reading it off a picture is the thing this window exists to replace. Only a sweep
    # carries one -- REW returns no phase for an MMM capture.
    "phase": {"label_x": "Hz", "scale_x": 1.0, "log_x": True, "label_y": "°"},
}
#: How far either side of the peak the impulse view opens on. A REW impulse spans −995 ms to
#: +1735 ms (measured); the arrival argument happens inside a couple of milliseconds of the peak,
#: and everything else is there for whoever zooms out.
_IMPULSE_WINDOW_MS = 4.0
#: What an FR view opens on. REW reports out to 47 kHz and down to 4 Hz; outside the audible band
#: it is measurement noise, and auto-ranging over it flattens the part being argued about.
_FR_BAND_HZ = (20.0, 20000.0)


def kind_for(titles: Sequence[str], asked: str = "") -> str:
    """Which curve these measurements can actually show.

    An MMM/RTA capture has NO impulse response — REW answers 400 — so asking for one is an error
    the Arbiter sees as a broken window (user, 2026-08-11). The method suffix already says which
    kind a measurement is, so the window can pick rather than fail: any sweep in the selection
    means an impulse is available, all-RTA means frequency response.
    """
    all_rta = bool(titles) and all(str(t).rstrip().endswith("(rta)") for t in titles)
    if asked in KINDS and not all_rta:
        return asked
    if all_rta:
        # An MMM capture has a magnitude and nothing else: no impulse, no phase.
        return "fr"
    return asked if asked in KINDS else "impulse"


def _peak_x(trace) -> float:
    """The x of the largest |y| — an impulse's arrival, read the crudest way there is.

    numpy, because a Python loop over 262 144 samples is a visible pause per trace.
    """
    y = np.asarray(trace.y, dtype=float)
    if not y.size:
        return 0.0
    return float(np.asarray(trace.x, dtype=float)[int(np.argmax(np.abs(y)))])


class _CurveWorker(QThread):
    """Fetch each named measurement's curve. One `find_id` + one curve call per title."""

    done = Signal(list)  # list[Trace]
    failed = Signal(str)

    def __init__(self, bridge: RewBridge, titles: Sequence[str], kind: str) -> None:
        super().__init__()
        self._bridge = bridge
        self._titles = list(titles)
        self._kind = kind

    def run(self) -> None:
        traces: list[Trace] = []
        problems: list[str] = []
        for title in self._titles:
            # Per measurement, not per batch: one curve REW cannot produce must not take the other
            # one off the screen with it. The window shows what it has and names what it does not.
            try:
                mid = self._bridge.find_id(title)
                if self._kind == "impulse":
                    times, samples = self._bridge.impulse_response(mid)
                    # numpy from here down. These are 262 144 points per trace, and a Python list
                    # comprehension over them was the panel's actual cost, not the HTTP call
                    # (measured: fetch 0.03 s).
                    x = np.asarray(times, dtype=float) * KINDS["impulse"]["scale_x"]
                    traces.append(Trace(title, x, np.asarray(samples, dtype=float)))
                else:
                    freqs, mag, phase = self._bridge.frequency_response(mid)
                    values = phase if self._kind == "phase" else mag
                    if values is None:
                        raise ValueError("no phase in this measurement")
                    traces.append(
                        Trace(title, np.asarray(freqs, dtype=float),
                              np.asarray(values, dtype=float))
                    )
            except Exception as exc:  # noqa: BLE001 — a REW failure is a message, not a crash
                problems.append(f"{title}: {type(exc).__name__}")
        if not traces:
            self.failed.emit("; ".join(problems) or "no curves")
            return
        self.done.emit(traces)


class CurveDialog(QDialog):
    """`titles` from REW, `markers` where the model says the answer is.

    `readingSent` carries the Arbiter's own reading back as a sentence — the caller decides what to
    do with it (put it in the dialog, record it as a `user_decision`), because deciding that here
    would put the recording in two places.
    """

    readingSent = Signal(str)

    def __init__(
        self,
        titles: Sequence[str],
        markers: Sequence[float] = (),
        kind: str = "impulse",
        bridge: Optional[RewBridge] = None,
        available: Sequence[str] = (),
        parent=None,
    ) -> None:
        """`titles` is what to plot. `available` is everything REW holds, for the two pickers —
        pass it and the Arbiter can change their mind about which pair is being argued about
        without closing the window and finding a different button."""
        super().__init__(parent)
        self.setWindowTitle(i18n.t("curveTitle"))
        self.resize(880, 560)
        self._kind = kind_for(titles, kind)
        self._markers = list(markers)
        self._bridge = bridge or RewBridge()
        self._worker: Optional[_CurveWorker] = None
        #: Which measurement the delay currently on screen is banked against, so that moving the
        #: radio moves the entry instead of leaving one behind on the other curve.
        self._restoring = False
        #: `() -> {channel code: ms}` — what the DSP is set to now, supplied by the window because
        #: this dialog has no business loading a ledger. Without it the panel simply does not
        #: state a total, which is honest; with it, it can say when a correction would take a
        #: channel below zero (user, 2026-08-12).
        self._delays_provider = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        # Two pickers, because a disagreement is nearly always about a pair. The second may be
        # empty: one curve is a legitimate thing to argue about too.
        self._pickers: list[QComboBox] = []
        options = list(available) or list(titles)
        if options:
            picker_row = QHBoxLayout()
            picker_row.setSpacing(8)
            for index in range(2):
                combo = QComboBox()
                combo.setProperty("class", "mini-select")
                if index:
                    combo.addItem(i18n.t("curveNoSecond"), "")
                for title in options:
                    combo.addItem(title, title)
                wanted = titles[index] if index < len(titles) else ""
                at = combo.findData(wanted)
                combo.setCurrentIndex(at if at >= 0 else 0)
                combo.currentIndexChanged.connect(lambda _i: self._reload())
                picker_row.addWidget(combo, 1)
                self._pickers.append(combo)
            layout.addLayout(picker_row)

        # The kind is a property of the WINDOW, not of a measurement: two curves in different
        # units on one pair of axes would be a picture of nothing. Switching it re-fetches.
        self._kind_combo = QComboBox()
        self._kind_combo.setProperty("class", "mini-select")
        for key in KINDS:
            self._kind_combo.addItem(i18n.t(f"curveKind_{key}"), key)
        self._kind_combo.setCurrentIndex(max(0, self._kind_combo.findData(self._kind)))
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        if self._pickers:
            picker_row.addWidget(self._kind_combo)
        else:
            layout.addWidget(self._kind_combo)

        self._status = QLabel(i18n.t("curveLoading"))
        self._status.setProperty("class", "phead-sub")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._view = CurveView(x_label=str(KINDS[self._kind]["label_x"]))
        self._view.on_send(self._on_send)
        self._view.delayChanged.connect(self._bank_current_delay)
        layout.addWidget(self._view, stretch=1)

        # Everything read so far, and one button that hands the whole set to the model. A delay is
        # only ever relative to the rest of the car, so one pair's number decides nothing — and
        # this window used to drop each one as soon as the next pair loaded (user, 2026-08-12).
        bank_row = QHBoxLayout()
        bank_row.setContentsMargins(0, 0, 0, 0)
        bank_row.setSpacing(8)
        self._bank_label = QLabel("")
        self._bank_label.setProperty("class", "phead-sub")
        self._bank_label.setWordWrap(True)
        bank_row.addWidget(self._bank_label, stretch=1)
        self._bank_ask_btn = QPushButton(i18n.t("curveBankAskBtn"))
        self._bank_ask_btn.setProperty("class", "zoom-btn")
        self._bank_ask_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bank_ask_btn.clicked.connect(self._on_ask_about_bank)
        bank_row.addWidget(self._bank_ask_btn)
        self._bank_clear_btn = QPushButton(i18n.t("curveBankClear"))
        self._bank_clear_btn.setProperty("class", "zoom-btn")
        self._bank_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bank_clear_btn.clicked.connect(self._on_clear_bank)
        bank_row.addWidget(self._bank_clear_btn)
        layout.addLayout(bank_row)

        self._titles = list(titles)
        self._apply_delay_resolution()
        self._render_bank()
        self._apply_kind()
        self._reload()

    # ---- the delay bank -----------------------------------------------------

    def set_delays_provider(self, provider) -> None:
        self._delays_provider = provider
        self._sync_channel_delay()

    def _current_delay_of(self, title: str):
        if not self._delays_provider or not title:
            return None
        try:
            return (self._delays_provider() or {}).get(delay_bank.code_of(title))
        except Exception:  # noqa: BLE001 — a curve window must not die on a ledger read
            return None

    def _sync_channel_delay(self) -> None:
        """What each of the two channels is set to now — both, because both may carry a proposal
        and the reading states a total for each."""
        for index, trace in enumerate(self._view._traces[:2]):
            self._view.set_channel_delay(self._current_delay_of(trace.name), index)

    def _bank_current_delay(self) -> None:
        """Remember what the Arbiter just read, against the measurement they read it on.

        Written on every change rather than on close: this window is left open across a whole
        alignment pass, and a crash or a forgotten close would take the afternoon's readings with
        it. Zero removes the entry — "needs no delay" and "not looked at yet" are different claims
        and only the second is honest about a curve nobody opened.

        Moving the radio MOVES the reading rather than copying it. One pair has one answer and it
        sits on one side; both sides banked at 0.198 ms would be the window claiming the Arbiter
        read the same gap twice. What it must not do is touch a delay banked on the OTHER curve
        from an earlier pair — those are two independent facts about two alignments, and they
        coexist happily.
        """
        if self._restoring:
            return
        for index, trace in enumerate(self._view._traces[:2]):
            # Both, every time. Each driver carries its own delay now, so there is nothing to move
            # from one entry to another — the radio only chooses which one you are typing into.
            # The arrival AS CAPTURED goes with it: a delay with no origin cannot be checked, and
            # checking the set is the only reason it is ever sent anywhere.
            delay_bank.put(
                trace.name, self._view.delay_ms(index),
                arrival_ms=_peak_x(trace) if self._kind == "impulse" else None,
            )
        self._sync_channel_delay()
        self._render_bank()

    def _render_bank(self) -> None:
        """The banked set under the plot, and the same numbers beside the titles in the pickers.

        In the pickers because that is where the Arbiter is choosing the next pair: seeing that
        w-L already carries +0.198 ms is what stops the same channel being read twice against two
        different partners and banked twice with different answers.
        """
        bank = delay_bank.load()
        if bank:
            shown = ", ".join(f"{title} {ms:+.3f}" for title, ms in sorted(bank.items()))
            self._bank_label.setText(f"{i18n.t('curveBankLabel')} {shown}")
        else:
            self._bank_label.setText(i18n.t("curveBankEmpty"))
        self._bank_ask_btn.setEnabled(bool(bank))
        self._bank_clear_btn.setEnabled(bool(bank))
        for combo in self._pickers:
            for row in range(combo.count()):
                title = str(combo.itemData(row) or "")
                if not title:
                    continue
                ms = bank.get(title)
                combo.setItemText(row, f"{title}  ·  {ms:+.3f} ms" if ms else title)

    def _on_ask_about_bank(self) -> None:
        """The whole set, to be LOOKED AT — never written.

        It goes into the composer like every other statement of the Arbiter's, so they read it
        before it is sent. Nothing about this touches a DSP: the model is being asked whether the
        picture holds together, not to apply it (user, 2026-08-12: "відправити на аналіз ШІ (не
        для запису)").
        """
        text = delay_bank.as_sentence(
            delay_bank.load(), self._sample_rate_hz(), i18n.t, self._current_delay_of,
            at=delay_bank.arrivals(),
        )
        if text:
            self.readingSent.emit(text)

    def _on_clear_bank(self) -> None:
        delay_bank.clear()
        self._view.set_delay(0.0)
        self._render_bank()

    def _sample_rate_hz(self):
        return getattr(self._view, "_sample_rate_hz", None)

    def _apply_delay_resolution(self) -> None:
        """Step the delay control by what THIS processor accepts, from its own profile.

        Two different numbers, and the panel needs both. Helix takes 0.01 ms in its box while the
        hardware resolves samples (1/96 kHz = 0.010417 ms), which is why typing successive steps
        sometimes moves nothing and sometimes moves two — the user has watched it happen and had
        no way to explain it. MUSWAY shows thousandths on a step nobody here has confirmed. So the
        control steps by `delay.step_ms` where the profile states one, and the reading carries the
        sample count only when a sample rate is on record. Guessing either would put a number in
        front of the Arbiter that the DSP never agreed to.
        """
        step, rate = None, None
        try:
            import json

            raw = json.loads(config.dsp_profile_path().read_text(encoding="utf-8"))
            profile = raw.get("dsp_profile") if isinstance(raw.get("dsp_profile"), dict) else raw
            delay = profile.get("delay")
            if isinstance(delay, dict):
                step = delay.get("step_ms")
            rate = profile.get("sample_rate_hz")
        except Exception:  # noqa: BLE001 — no profile yet is the ordinary case, not a failure
            pass
        self._view.set_resolution(
            float(step) if isinstance(step, (int, float)) else None,
            float(rate) if isinstance(rate, (int, float)) else None,
        )

    def _on_kind_changed(self, _index: int) -> None:
        self._kind = str(self._kind_combo.currentData() or "impulse")
        self._apply_kind()
        self._reload()

    def _apply_kind(self) -> None:
        spec = KINDS[self._kind]
        self._view.set_unit(str(spec["label_x"]))
        self._view.set_y_unit(str(spec["label_y"]))
        self._view.set_log_x(bool(spec["log_x"]))
        # A frequency response is as often read for its level as for its frequency, so it opens
        # with both; an impulse is an arrival time and nothing else.
        self._view.set_axes_mode("vh" if self._kind in ("fr", "phase") else "v")

    def _chosen(self) -> list[str]:
        if not self._pickers:
            return list(self._titles)
        return [str(c.currentData() or "") for c in self._pickers if c.currentData()]

    def _reload(self) -> None:
        """Fetch whatever is selected. Waits out an in-flight worker rather than assigning over
        it: Qt aborts the process when a running QThread is destroyed, which the measurement
        panel learned the expensive way."""
        titles = self._chosen()
        if not titles:
            return
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(4000)
        self._status.setVisible(True)
        self._status.setText(i18n.t("curveLoading"))
        self._worker = _CurveWorker(self._bridge, titles, self._kind)
        self._worker.done.connect(self._on_curves)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_curves(self, traces: list) -> None:
        self._status.setVisible(False)
        self._view.set_traces(traces)
        # A pair already argued about comes back with its answer on it. `set_traces` clears the
        # delay by design (a new pair is a new question); the bank is what makes coming BACK to a
        # pair different from meeting it for the first time.
        bank = delay_bank.load()
        # Restoring, not reading: `_bank_current_delay` must not see these calls, or the zeros
        # they pass through on the way would erase what they are restoring.
        self._restoring = True
        try:
            target = self._view.delay_target()
            for index, trace in enumerate(traces[:2]):
                if trace.name in bank:
                    self._view.set_delay_target(index)
                    self._view.set_delay(bank[trace.name])
            self._view.set_delay_target(target)
        finally:
            self._restoring = False
        positions, names, tokens = self._starting_markers(traces)
        self._view.set_markers(positions, names, tokens)
        self._frame(traces, positions)
        self._sync_channel_delay()
        self._render_bank()

    def _frame(self, traces: list, positions: list) -> None:
        """Open on the part being argued about rather than on everything REW recorded."""
        if self._kind in ("fr", "phase"):
            self._view.focus_x(*_FR_BAND_HZ)
        elif positions:
            centre = sum(positions) / len(positions)
            self._view.focus_x(centre - _IMPULSE_WINDOW_MS, centre + _IMPULSE_WINDOW_MS)
        self._view.autoscale_y()

    def _starting_markers(self, traces: list):
        """Where the markers begin, and what to call them.

        With a reading from the model, ON it — and a second marker on top of the first, because
        dragging away from where the model read it IS the disagreement, so every millimetre of
        movement is deliberate.

        Without one (the Arbiter opened this themselves), on each trace's own largest peak. For an
        impulse that is the arrival by the crudest possible reading, which makes the delta
        meaningful before anything has been touched — and a starting point that is obviously a
        guess invites correction better than two markers parked at zero.
        """
        if self._markers:
            positions = list(self._markers)
            names = [i18n.t("curveMarkerModel"), i18n.t("curveMarkerYou")]
            if len(positions) == 1:
                positions.append(positions[0])
            return positions[:2], names[:len(positions[:2])], []
        usable = [t for t in traces[:2] if len(t.x)]
        # One marker per curve, each in its curve's own colour: nobody has claimed a reading yet,
        # so calling the first one "the model's" would be a lie the colour tells.
        return ([_peak_x(t) for t in usable], [t.name for t in usable],
                list(_TRACE_TOKENS[:len(usable)]))

    def reset(self, titles, markers=(), kind="impulse", available=()) -> None:
        """Re-point an existing window at a new question, instead of building another one.

        pyqtgraph's `PlotItem` builds several parentless QMenus and `QWidgetAction`s on every
        construction, whatever `enableMenu` says, and constructing/destroying enough of them
        segfaults the process from inside its own `__init__` — reproduced in the suite, and
        reachable in the app by opening this window twenty times during a tune (2026-08-12).
        One window, re-pointed, avoids the whole class rather than betting on the collector.
        """
        self._kind = kind_for(titles, kind)
        self._markers = [float(m) for m in (markers or [])]
        self._titles = list(titles)
        options = list(available) or list(titles)
        for index, combo in enumerate(self._pickers):
            blocked = combo.blockSignals(True)
            combo.clear()
            if index:
                combo.addItem(i18n.t("curveNoSecond"), "")
            for title in options:
                combo.addItem(title, title)
            wanted = titles[index] if index < len(titles) else ""
            at = combo.findData(wanted)
            combo.setCurrentIndex(at if at >= 0 else 0)
            combo.blockSignals(blocked)
        at = self._kind_combo.findData(self._kind)
        blocked = self._kind_combo.blockSignals(True)
        self._kind_combo.setCurrentIndex(max(0, at))
        self._kind_combo.blockSignals(blocked)
        # Re-read: the window outlives the project, and switching projects switches processors —
        # and switching projects switches the bank with it.
        self._apply_delay_resolution()
        self._render_bank()
        self._apply_kind()
        self._reload()

    def apply_theme(self) -> None:
        """Passed through from the window: a plot does not repaint from a stylesheet."""
        self._view.apply_theme()

    def _on_failed(self, message: str) -> None:
        self._status.setVisible(True)
        self._status.setText(i18n.t("curveFailed").format(error=message))

    def _on_send(self, reading: str) -> None:
        if reading:
            self.readingSent.emit(reading)
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Qt aborts the process if a QThread is destroyed while running — the same `qFatal` the
        measurement panel's workers are guarded against."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(4000)
        super().closeEvent(event)
