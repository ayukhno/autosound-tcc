"""A curve with markers on it — the shared object a disagreement can be pointed at.

Not a REW replacement, and the boundary matters or this grows without end. REW is where curves are
looked at. This exists for one moment: the model has read a number off a measurement, the Arbiter
reads a different one, and until now there was nothing both of them could point to. That gap is
what sent a screenshot through the transport yesterday, and the screenshot killed the session.

So the design rule is: **this is an input device, not a viewer.** What comes out of it is not "the
Arbiter looked" but a NUMBER the Arbiter produced — a marker position, in milliseconds, on a named
measurement. That is machine-readable the instant it is placed, which is exactly the standard
`user_decision` was written to (SCR-030): record the Arbiter's ruling when it becomes a fact, not
as prose about a fact.

Two traces at a time, because a disagreement is nearly always about a pair (w-L against w-R, a
driver against its joint partner). Markers are draggable and their delta is the readout, because
"how far apart are these two arrivals" is the question that keeps being asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.theme import current_theme

# The two trace colours, in order. Deliberately the theme's own accent + info rather than
# pyqtgraph's defaults: a plot that does not belong to the window it is in reads as a screenshot
# of another program, which is the thing this feature exists to stop needing.
_TRACE_TOKENS = ("accent", "info")
# Marker colours: the model's reading and the Arbiter's, and they must never be confusable. The
# whole point of the panel is showing that these two are different numbers.
_MODEL_TOKEN = "muted"
_ARBITER_TOKEN = "ok"


@dataclass(frozen=True)
class Trace:
    """One curve: a name the skill would recognise, and its samples."""

    name: str
    x: Sequence[float]
    y: Sequence[float]


class CurveView(QWidget):
    """Traces, draggable markers, and a readout of what the markers say.

    `markersChanged` fires while a marker is dragged; `reading()` is the answer at any moment. The
    widget itself decides nothing and records nothing — the caller does both, which keeps this a
    renderer and keeps the recording in one place.
    """

    markersChanged = Signal()

    def __init__(self, x_label: str = "ms", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        theme = current_theme()
        pg.setConfigOptions(antialias=True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._plot = pg.PlotWidget(background=theme.panel)
        self._plot.showGrid(x=True, y=True, alpha=0.18)
        self._plot.setLabel("bottom", x_label)
        for axis in ("bottom", "left"):
            self._plot.getAxis(axis).setPen(pg.mkPen(theme.border2))
            self._plot.getAxis(axis).setTextPen(pg.mkPen(theme.muted))
        self._legend = self._plot.addLegend(offset=(-8, 8), labelTextColor=theme.text)
        layout.addWidget(self._plot, stretch=1)

        self._readout = QLabel("")
        self._readout.setProperty("class", "kv-val")
        self._readout.setTextFormat(Qt.TextFormat.RichText)

        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(8)
        row.addWidget(self._readout, stretch=1)
        self._send_btn = QPushButton(i18n.t("curveSend"))
        self._send_btn.setProperty("class", "composer-send")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self._send_btn)
        layout.addLayout(row)

        self._traces: list[Trace] = []
        self._markers: list[pg.InfiniteLine] = []
        self._marker_names: list[str] = []
        self._render_readout()

    # ---- content ---------------------------------------------------------

    def set_traces(self, traces: Sequence[Trace]) -> None:
        theme = current_theme()
        self._plot.clear()
        # `addLegend` returns the same item across clears, so its rows have to go too or the
        # names stack up one pass at a time.
        if self._legend is not None:
            self._legend.clear()
        self._traces = list(traces)
        for index, trace in enumerate(self._traces):
            token = _TRACE_TOKENS[index % len(_TRACE_TOKENS)]
            self._plot.plot(
                list(trace.x), list(trace.y),
                pen=pg.mkPen(getattr(theme, token), width=1.4), name=trace.name,
            )
        for line in self._markers:
            self._plot.addItem(line)
        self._render_readout()

    def set_markers(self, positions: Sequence[float], names: Sequence[str] = ()) -> None:
        """Place markers at `positions`. The FIRST is the model's reading, the rest are the
        Arbiter's — coloured apart, because a panel that shows two numbers as one colour is a panel
        that lets them be confused for each other."""
        for line in self._markers:
            self._plot.removeItem(line)
        self._markers = []
        self._marker_names = list(names) or [
            i18n.t("curveMarkerModel") if i == 0 else i18n.t("curveMarkerYou")
            for i in range(len(positions))
        ]
        theme = current_theme()
        for index, position in enumerate(positions):
            token = _MODEL_TOKEN if index == 0 else _ARBITER_TOKEN
            line = pg.InfiniteLine(
                pos=float(position), angle=90, movable=True,
                pen=pg.mkPen(getattr(theme, token), width=1.6,
                             style=Qt.PenStyle.DashLine if index == 0 else Qt.PenStyle.SolidLine),
                label=self._marker_names[index] if index < len(self._marker_names) else "",
                labelOpts={"color": getattr(theme, token), "position": 0.92},
            )
            line.sigPositionChanged.connect(self._on_marker_moved)
            self._plot.addItem(line)
            self._markers.append(line)
        self._render_readout()

    # ---- what the Arbiter is saying --------------------------------------

    def positions(self) -> list[float]:
        return [float(line.value()) for line in self._markers]

    def reading(self) -> str:
        """The markers as a sentence a model can parse — names, positions, and the delta.

        A sentence rather than a dict because this goes into the dialog, where the Arbiter can see
        and edit it before it is sent. Nothing is recorded behind their back.
        """
        if not self._markers:
            return ""
        names = [t.name for t in self._traces] or [""]
        parts = [
            f"{self._marker_names[i] if i < len(self._marker_names) else i}: {p:.3f} ms"
            for i, p in enumerate(self.positions())
        ]
        line = ", ".join(parts)
        if len(self._markers) >= 2:
            positions = self.positions()
            line += f" (Δ {abs(positions[1] - positions[0]):.3f} ms)"
        return f"{' / '.join(names)} — {line}"

    def on_send(self, handler: Callable[[str], None]) -> None:
        self._send_btn.clicked.connect(lambda: handler(self.reading()))

    # ---- internals -------------------------------------------------------

    def _on_marker_moved(self) -> None:
        self._render_readout()
        self.markersChanged.emit()

    def _render_readout(self) -> None:
        text = self.reading()
        self._readout.setText(text or i18n.t("curveNoMarkers"))
        self._send_btn.setEnabled(bool(text))

    def retranslate(self) -> None:
        self._send_btn.setText(i18n.t("curveSend"))
        self._render_readout()
