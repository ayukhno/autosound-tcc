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

import html
import math
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.theme import current_theme

# The two trace colours, in order. Deliberately the theme's own accent + info rather than
# pyqtgraph's defaults: a plot that does not belong to the window it is in reads as a screenshot
# of another program, which is the thing this feature exists to stop needing.
_TRACE_TOKENS = ("accent", "info")
# Marker colours: the model's reading and the Arbiter's, and they must never be confusable. The
# whole point of the panel is showing that these two are different numbers.
_MODEL_TOKEN = "muted"
_ARBITER_TOKEN = "ok"


class LogHzAxis(pg.AxisItem):
    """A frequency axis a human reads: 20 · 30 · 50 · 100 · 200 · 1k · 2k · 10k · 20k.

    pyqtgraph's own log axis prints `2·10¹`, `3·10¹`, `4·10¹` … and at audio widths they collide
    into an unreadable smear (user, 2026-08-11, with the picture). REW has had this right forever
    and it is not a matter of taste: the numbers on this axis are the vocabulary the whole trade
    speaks in — nobody says "the null at four times ten to the second".

    Ticks are chosen from the 1-2-3-5 series per decade, most significant first, and thinned to
    whatever the axis is actually wide enough to print.
    """

    _MAJOR = (1, 2, 5)
    _MINOR = (3, 4, 6, 8)
    #: Pixels a label needs before another one may be placed. Measured against the widest string
    #: this axis ever prints ("20kHz"), with room to breathe.
    _MIN_LABEL_PX = 34

    def tickValues(self, minVal, maxVal, size):  # noqa: N802 (Qt/pyqtgraph naming)
        # Values arrive in LOG10 space because the plot is in log mode.
        low, high = 10.0 ** min(minVal, maxVal), 10.0 ** max(minVal, maxVal)
        decades = range(int(math.floor(math.log10(max(low, 1e-9)))),
                        int(math.ceil(math.log10(max(high, 1e-9)))) + 1)
        out = []
        for step, group in ((0, self._MAJOR), (1, self._MINOR)):
            values = [
                math.log10(mult * 10 ** decade)
                for decade in decades
                for mult in group
                if low <= mult * 10 ** decade <= high
            ]
            if values:
                out.append((step, self._thin(values, size, minVal, maxVal, out)))
        return out

    def _thin(self, values, size, minVal, maxVal, already):
        """Drop what will not fit. Crowding is what made the default unreadable, and a tick with
        no room is worse than no tick: it overprints the one that had room."""
        span = abs(maxVal - minVal) or 1.0
        per_unit = (size or 1.0) / span
        taken = [v for _, group in already for v in group]
        kept = []
        for value in sorted(values):
            near = taken + kept
            if all(abs(value - other) * per_unit >= self._MIN_LABEL_PX for other in near):
                kept.append(value)
        return kept

    def tickStrings(self, values, scale, spacing):  # noqa: N802 (Qt/pyqtgraph naming)
        out = []
        for value in values:
            hz = 10.0 ** value
            if hz >= 1000:
                thousands = hz / 1000.0
                out.append(f"{thousands:g}k")
            elif hz >= 1:
                out.append(f"{hz:.0f}")
            else:
                out.append(f"{hz:.2g}")
        return out


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
        # Antialiasing off: a REW impulse is 262 144 points per trace (measured, not estimated),
        # and smoothing every segment of that is most of the cost of drawing it. At this density
        # the line is a solid block of pixels anyway.
        pg.setConfigOptions(antialias=False)
        self._unit = x_label
        self._y_unit = ""
        self._log_x = False
        # Which way the markers read. On an FR the question is as often "how many dB is that dip"
        # as "at what frequency" (user, 2026-08-11), and on a joint it is both at once.
        self._axes_mode = "v"
        self._zoom_buttons: list[tuple[QPushButton, str]] = []
        self._axes_buttons: list[tuple[QPushButton, str]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._hz_axis = LogHzAxis(orientation="bottom")
        self._plot = pg.PlotWidget(background=theme.panel)
        self._plot.showGrid(x=True, y=True, alpha=0.18)
        # No axis label under the ticks: it is a whole row of window spent centring one word, and
        # the readout wants that row (user, 2026-08-11). The unit moves to the right end of the
        # readout, where it labels the numbers rather than the axis.
        # The two settings that make a quarter-million points usable: draw a peak-preserving
        # decimation instead of every sample, and only the samples inside the current view. Peak
        # mode rather than mean because the thing being looked for IS the extreme — a mean-
        # downsampled impulse loses the very onset the argument is about.
        self._plot.setDownsampling(auto=True, mode="peak")
        self._plot.setClipToView(True)
        # pyqtgraph's own right-click menu is off. It offers this app nothing that the A/D/−/+
        # buttons do not (and several things that mean nothing here — "Link Axis", "Auto Pan
        # Only"), while being a native QMenu full of unstyled spin boxes that renders as
        # white-on-white in the dark theme (user, 2026-08-11, with the picture). Removing the
        # menu removes the whole class of problem rather than restyling somebody else's dialog.
        self._plot.setMenuEnabled(False)
        for axis in ("bottom", "left"):
            self._plot.getAxis(axis).setPen(pg.mkPen(theme.border2))
            self._plot.getAxis(axis).setTextPen(pg.mkPen(theme.muted))
        self._legend = self._plot.addLegend(offset=(-8, 8), labelTextColor=theme.text)
        layout.addWidget(self._plot, stretch=1)

        # Its own row, above the buttons (user, 2026-08-11). Sharing a line with eight controls
        # left the reading fighting them for width — it stretched the window when it could and was
        # cut when it could not, and the numbers ARE the output of this panel.
        self._readout = QLabel("")
        self._readout.setProperty("class", "kv-val")
        self._readout.setTextFormat(Qt.TextFormat.RichText)
        self._readout.setWordWrap(True)
        # A wrapping label still reports its unwrapped width as what it "wants"; without this the
        # window would keep growing to fit the reading on one line anyway.
        self._readout.setMinimumWidth(80)
        self._readout.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._readout.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._readout)

        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(6)
        # The axis's own unit, at the left of the controls that read in it.
        self._unit_label = QLabel("")
        self._unit_label.setProperty("class", "phead-sub")
        row.addWidget(self._unit_label)
        row.addStretch(1)
        # Zoom without a wheel (user, 2026-08-11 — a trackpad is not a scroll wheel, and this
        # window is used in a car). "All" is everything the capture holds; "Detail" is the span
        # the window opened on, which is the one worth coming back to after wandering.
        for mode in ("v", "h", "vh", "vhs"):
            button = QPushButton("VHs" if mode == "vhs" else mode.upper())
            button.setProperty("class", "zoom-btn")
            button.setCheckable(True)
            button.setChecked(mode == self._axes_mode)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(30, 24)
            attach_tip(button, i18n.t(f"curveAxes_{mode}"))
            button.clicked.connect(lambda _checked, m=mode: self.set_axes_mode(m))
            row.addWidget(button)
            self._axes_buttons.append((button, mode))

        for key, handler in (
            ("curveZoomAll", self.show_all),
            ("curveZoomDetail", self.show_detail),
            ("curveZoomOut", lambda: self.zoom(1.6)),
            ("curveZoomIn", lambda: self.zoom(1 / 1.6)),
        ):
            button = QPushButton(i18n.t(key + "Short"))
            button.setProperty("class", "zoom-btn")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(30, 24)
            attach_tip(button, i18n.t(key))
            button.clicked.connect(handler)
            row.addWidget(button)
            self._zoom_buttons.append((button, key))
        self._send_btn = QPushButton(i18n.t("curveSend"))
        self._send_btn.setProperty("class", "composer-send")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self._send_btn)
        layout.addLayout(row)

        self._detail_range: Optional[tuple[float, float]] = None
        self._traces: list[Trace] = []
        self._markers: list[pg.InfiniteLine] = []
        self._h_markers: list[pg.InfiniteLine] = []
        self._marker_tokens: list[str] = []
        self._syncing = False
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
                # Arrays, not Python lists: pyqtgraph converts a list element by element, and a
                # list comprehension over 262 144 floats had already been paid for upstream.
                np.asarray(trace.x, dtype=float), np.asarray(trace.y, dtype=float),
                pen=pg.mkPen(getattr(theme, token), width=1.0), name=trace.name,
            )
        for line in self._markers:
            self._plot.addItem(line)
        self._render_readout()

    def set_markers(
        self, positions: Sequence[float], names: Sequence[str] = (),
        tokens: Sequence[str] = (),
    ) -> None:
        """Place markers at `positions`.

        By default the FIRST is the model's reading and the rest are the Arbiter's, coloured apart
        because a panel that shows two numbers in one colour lets them be confused for each other.
        `tokens` overrides that: when the markers are one-per-curve rather than model-versus-you,
        each takes its own curve's colour, and calling one of them "the model's" would be a lie.
        """
        for line in self._markers:
            self._plot.removeItem(line)
        self._markers = []
        self._marker_names = list(names) or [
            i18n.t("curveMarkerModel") if i == 0 else i18n.t("curveMarkerYou")
            for i in range(len(positions))
        ]
        theme = current_theme()
        for index, position in enumerate(positions):
            if index < len(tokens):
                token = tokens[index]
            else:
                token = _MODEL_TOKEN if index == 0 else _ARBITER_TOKEN
            line = pg.InfiniteLine(
                pos=self._to_view(float(position)), angle=90, movable=True,
                pen=pg.mkPen(getattr(theme, token), width=1.6,
                             style=Qt.PenStyle.DashLine if index == 0 and not tokens
                             else Qt.PenStyle.SolidLine),
                label=self._marker_names[index] if index < len(self._marker_names) else "",
                # Staggered heights: the two markers START on top of each other (that is the
                # point — the Arbiter drags away from the model's reading), and labels printed at
                # the same height would overlap into one unreadable word until they separate.
                labelOpts={"color": getattr(theme, token),
                           "position": 0.94 - 0.07 * index},
            )
            line.setVisible("v" in self._axes_mode)
            line.sigPositionChanged.connect(self._on_marker_moved)
            self._plot.addItem(line)
            self._markers.append(line)
        self._marker_tokens = list(tokens)
        self._rebuild_h_markers()
        self._render_readout()

    def apply_theme(self) -> None:
        """Re-read the palette after a theme switch.

        Everything else in the app repaints from the stylesheet; a plot draws with explicit pens
        and brushes, so it keeps the colours it was built with until somebody says otherwise — a
        light plot sitting in a dark window (user, 2026-08-11).
        """
        theme = current_theme()
        self._plot.setBackground(theme.panel)
        for axis_name in ("bottom", "left"):
            axis = self._plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(theme.border2))
            axis.setTextPen(pg.mkPen(theme.muted))
        if self._legend is not None:
            self._legend.setLabelTextColor(theme.text)
        # Traces and markers are rebuilt rather than recoloured in place: both already know how to
        # draw themselves from the current theme, and two ways of doing it is one too many.
        traces, positions = list(self._traces), self.positions()
        names, tokens = list(self._marker_names), list(self._marker_tokens)
        if traces:
            self.set_traces(traces)
        if positions:
            self.set_markers(positions, names, tokens)

    def set_log_x(self, on: bool) -> None:
        """Frequency is read on a log axis; time is not.

        pyqtgraph's log mode transforms the DATA and leaves everything else in view coordinates —
        so a marker placed at 96.6 lands at 10^96.6 and the axis runs to 1e+27 (seen, 2026-08-11).
        Every position that crosses this class's boundary is therefore converted here rather than
        by each caller, who would otherwise have to know which mode the plot happens to be in.
        """
        self._log_x = bool(on)
        self._plot.setLogMode(x=self._log_x, y=False)
        # The frequency axis only makes sense in log mode; time keeps pyqtgraph's own.
        theme = current_theme()
        axis = self._hz_axis if self._log_x else pg.AxisItem(orientation="bottom")
        axis.setPen(pg.mkPen(theme.border2))
        axis.setTextPen(pg.mkPen(theme.muted))
        self._plot.setAxisItems({"bottom": axis})

    def _to_view(self, x: float) -> float:
        return math.log10(x) if self._log_x and x > 0 else float(x)

    def _from_view(self, x: float) -> float:
        return 10.0 ** x if self._log_x else float(x)

    def set_unit(self, unit: str) -> None:
        """What the marker positions are IN. Wrong units in a reading are worse than no reading."""
        self._unit = unit
        self._render_readout()

    def focus_x(self, low: float, high: float) -> None:
        """Show this span, and no padding around it.

        A REW impulse spans −995 ms to +1735 ms; auto-ranged, the two millimetres the argument is
        about are a vertical line. The full sweep is still there — zoom out and it is all present.
        """
        if high > low:
            self._detail_range = (low, high)
            self._plot.setXRange(self._to_view(low), self._to_view(high), padding=0.02)

    def autoscale_y(self) -> None:
        self._plot.enableAutoRange(axis="y")

    def show_all(self) -> None:
        """Everything the capture holds — for an impulse that is seconds of room, on purpose."""
        self._plot.getViewBox().autoRange(padding=0.02)

    def show_detail(self) -> None:
        """Back to the span the window opened on."""
        if self._detail_range:
            low, high = self._detail_range
            self._plot.setXRange(self._to_view(low), self._to_view(high), padding=0.02)
        self.autoscale_y()

    def zoom(self, factor: float) -> None:
        """Scale the x view about its centre. `>1` shows more, `<1` shows less."""
        view = self._plot.getViewBox()
        (low, high), _ = view.viewRange()
        centre = (low + high) / 2.0
        half = (high - low) * factor / 2.0
        view.setXRange(centre - half, centre + half, padding=0)

    def set_y_unit(self, unit: str) -> None:
        """dB on a frequency response, degrees on a phase, nothing on an impulse."""
        self._y_unit = unit
        self._render_readout()

    def set_axes_mode(self, mode: str) -> None:
        """`v` reads frequencies, `h` reads levels, `vh` reads both.

        The same markers either way — a horizontal line is added beside each vertical one rather
        than replacing it, so switching to VH does not lose a position already placed.
        """
        self._axes_mode = mode if mode in ("v", "h", "vh", "vhs") else "v"
        for button, value in self._axes_buttons:
            button.setChecked(value == self._axes_mode)
        self._rebuild_h_markers()
        for line in self._markers:
            line.setVisible("v" in self._axes_mode)
        self._render_readout()

    def _rebuild_h_markers(self) -> None:
        """One horizontal marker per vertical one, on its own curve's value at that x.

        Starting them ON the curve is what makes them useful immediately: the first thing anybody
        wants from a level marker is "what is this trace doing here", and a line parked at zero
        answers nothing.
        """
        for line in self._h_markers:
            self._plot.removeItem(line)
        self._h_markers = []
        if "h" not in self._axes_mode:
            return
        theme = current_theme()
        for index, x in enumerate(self.positions()):
            token = self._marker_tokens[index] if index < len(self._marker_tokens) else (
                _MODEL_TOKEN if index == 0 else _ARBITER_TOKEN
            )
            line = pg.InfiniteLine(
                pos=self._y_at(index, x), angle=0,
                # In sync mode the level is not a second thing to place: it IS the curve's value
                # where the vertical marker stands. Making it draggable there would let the two
                # halves of one reading disagree.
                movable=self._axes_mode != "vhs",
                pen=pg.mkPen(getattr(theme, token), width=1.2, style=Qt.PenStyle.DotLine),
            )
            line.sigPositionChanged.connect(self._on_marker_moved)
            self._plot.addItem(line)
            self._h_markers.append(line)

    def _y_at(self, index: int, x: float) -> float:
        """The value of trace `index` at `x`, or 0 when there is no such trace."""
        if index >= len(self._traces):
            return 0.0
        trace = self._traces[index]
        xs = np.asarray(trace.x, dtype=float)
        if not xs.size:
            return 0.0
        return float(np.asarray(trace.y, dtype=float)[int(np.abs(xs - x).argmin())])

    # ---- what the Arbiter is saying --------------------------------------

    def positions(self) -> list[float]:
        """In the unit the axis is labelled with — Hz, not log10(Hz)."""
        return [self._from_view(float(line.value())) for line in self._markers]

    def levels(self) -> list[float]:
        """Where the horizontal markers sit, in the y axis's own unit."""
        return [float(line.value()) for line in self._h_markers]

    def reading(self) -> str:
        """The markers as a sentence a model can parse — names, positions, and the delta.

        A sentence rather than a dict because this goes into the dialog, where the Arbiter can see
        and edit it before it is sent. Nothing is recorded behind their back.
        """
        if not self._markers:
            return ""
        names = [t.name for t in self._traces] or [""]
        digits = 3 if self._unit == "ms" else 1
        lines = []
        if "v" in self._axes_mode:
            lines.append(self._axis_reading(self.positions(), self._unit, digits))
        if "h" in self._axes_mode:
            lines.append(self._axis_reading(self.levels(), self._y_unit or "", 1))
        parts = [part for part in lines if part]
        if not parts:
            return ""
        # One line per axis when both are live: "at 96.6 Hz" and "at 75.0 dB" are two readings,
        # and running them together is how the row got too long to read in the first place.
        # A NEWLINE, not `<br>`: this string is what gets sent to the model, and markup in a
        # message is markup the model has to see through. The label does its own conversion.
        return f"{' / '.join(names)} — " + "\n".join(parts)

    def _axis_reading(self, values: list[float], unit: str, digits: int) -> str:
        if not values:
            return ""
        suffix = f" {unit}" if unit else ""
        parts = [
            f"{self._marker_names[i] if i < len(self._marker_names) else i}: "
            f"{value:.{digits}f}{suffix}"
            for i, value in enumerate(values)
        ]
        out = ", ".join(parts)
        if len(values) >= 2:
            out += f" (Δ {abs(values[1] - values[0]):.{digits}f}{suffix})"
        return out

    def on_send(self, handler: Callable[[str], None]) -> None:
        self._send_btn.clicked.connect(lambda: handler(self.reading()))

    # ---- internals -------------------------------------------------------

    def _on_marker_moved(self) -> None:
        self._sync_levels()
        self._render_readout()
        self.markersChanged.emit()

    def _sync_levels(self) -> None:
        """In `vhs`, follow the curve: one point, both coordinates.

        Guarded against re-entry because moving a marker emits the same signal that brought us
        here, and a line that chases its own move never settles.
        """
        if self._axes_mode != "vhs" or self._syncing:
            return
        self._syncing = True
        try:
            for index, x in enumerate(self.positions()):
                if index < len(self._h_markers):
                    self._h_markers[index].setValue(self._y_at(index, x))
        finally:
            self._syncing = False

    def _render_readout(self) -> None:
        unit = getattr(self, "_unit_label", None)
        if unit is not None:
            axes = "/".join(
                part for part in (self._unit if "v" in self._axes_mode else "",
                                  self._y_unit if "h" in self._axes_mode else "") if part
            )
            unit.setText(axes)
        text = self.reading()
        self._readout.setText(
            html.escape(text).replace("\n", "<br>") if text else i18n.t("curveNoMarkers")
        )
        self._send_btn.setEnabled(bool(text))

    def retranslate(self) -> None:
        self._send_btn.setText(i18n.t("curveSend"))
        for button, mode in self._axes_buttons:
            if getattr(button, "hover_tip", None) is not None:
                button.hover_tip.set_text(i18n.t(f"curveAxes_{mode}"))
        for button, key in self._zoom_buttons:
            button.setText(i18n.t(key + "Short"))
            if getattr(button, "hover_tip", None) is not None:
                button.hover_tip.set_text(i18n.t(key))
        self._render_readout()
