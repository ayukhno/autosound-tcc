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
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.t("curveTitle"))
        self.resize(880, 520)
        self._kind = kind if kind in KINDS else "impulse"
        self._markers = list(markers)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        self._status = QLabel(i18n.t("curveLoading"))
        self._status.setProperty("class", "phead-sub")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._view = CurveView(x_label=str(KINDS[self._kind]["label_x"]))
        self._view.on_send(self._on_send)
        layout.addWidget(self._view, stretch=1)

        self._worker = _CurveWorker(bridge or RewBridge(), titles, self._kind)
        self._worker.done.connect(self._on_curves)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_curves(self, traces: list) -> None:
        self._status.setVisible(False)
        self._view.set_traces(traces)
        # The model's marker first, then a second one for the Arbiter placed on top of it: dragging
        # away from where the model read it IS the disagreement, so it starts where the model is
        # and every millimetre of movement is meant.
        if self._markers:
            positions = list(self._markers)
            if len(positions) == 1:
                positions.append(positions[0])
            self._view.set_markers(positions)

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
        if self._worker.isRunning():
            self._worker.wait(4000)
        super().closeEvent(event)
