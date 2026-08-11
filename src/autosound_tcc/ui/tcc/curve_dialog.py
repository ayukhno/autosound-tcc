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

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout

from autosound_tcc.core.rew_bridge import RewBridge
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.curve_view import CurveView, Trace

#: What can be plotted, and how each one is fetched and labelled. Impulse first because that is
#: where the argument that prompted this happened; the others are the same widget with a different
#: reader, added when they are actually asked for rather than because a menu looked incomplete.
KINDS = {
    "impulse": {"label_x": "ms", "scale_x": 1000.0},
    "fr": {"label_x": "Hz", "scale_x": 1.0},
}


def _peak_x(trace) -> float:
    """The x of the largest |y| — an impulse's arrival, read the crudest way there is."""
    best, best_x = -1.0, float(trace.x[0])
    for x, y in zip(trace.x, trace.y):
        if abs(y) > best:
            best, best_x = abs(y), float(x)
    return best_x


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
        try:
            for title in self._titles:
                mid = self._bridge.find_id(title)
                if self._kind == "impulse":
                    times, samples = self._bridge.impulse_response(mid)
                    scale = KINDS["impulse"]["scale_x"]
                    traces.append(Trace(title, [t * scale for t in times], list(samples)))
                else:
                    freqs, mag, _phase = self._bridge.frequency_response(mid)
                    traces.append(Trace(title, list(freqs), list(mag)))
        except Exception as exc:  # noqa: BLE001 — any REW failure is a message, not a crash
            self.failed.emit(f"{type(exc).__name__}: {exc}")
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
        self._kind = kind if kind in KINDS else "impulse"
        self._markers = list(markers)
        self._bridge = bridge or RewBridge()
        self._worker: Optional[_CurveWorker] = None

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

        self._status = QLabel(i18n.t("curveLoading"))
        self._status.setProperty("class", "phead-sub")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._view = CurveView(x_label=str(KINDS[self._kind]["label_x"]))
        self._view.on_send(self._on_send)
        layout.addWidget(self._view, stretch=1)

        self._titles = list(titles)
        self._reload()

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
        self._view.set_markers(*self._starting_markers(traces))

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
            return positions[:2], names[:len(positions[:2])]
        positions = [_peak_x(t) for t in traces[:2] if len(t.x)]
        return positions, [t.name for t in traces[:2] if len(t.x)]

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
