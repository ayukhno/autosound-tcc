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
from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
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
#: The marker modes, and what their buttons say. `vx`/`hx` are the CROSS modes: one line, read
#: where it crosses each curve — "at this frequency, how far apart are the two channels" and "at
#: this level, where does each one reach it". Both are questions about a PAIR, which the
#: one-marker-per-curve modes cannot ask, because there the two markers are at different places.
_MODE_LABELS = {"v": "V", "h": "H", "vh": "VH", "vhs": "VHs", "vx": "Vx", "hx": "Hx"}
_CROSS_MODES = ("vx", "hx")
#: Guides are drawn heavier than the traces they cross. At trace weight they vanish into a dense
#: impulse — 262 144 points is a solid block of pixels, and a 1 px line over it is not a line.
_GUIDE_WIDTH = 2.4


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
        # `enableMenu=False` at CONSTRUCTION, not `setMenuEnabled(False)` afterwards. pyqtgraph
        # builds the whole ViewBox menu eagerly — several QMenus, a QWidgetAction and a generated
        # UI form each — and disabling it later leaves all of that built. Constructing and
        # dropping enough of them segfaults the process inside `ViewBoxMenu.__init__`
        # (reproduced in the suite, 2026-08-12). We do not use the menu at all: everything it
        # offers is on the A/D/−/+ buttons, and in the dark theme it renders white-on-white.
        self._plot = pg.PlotWidget(background=theme.panel, enableMenu=False)
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
        self._plot.setMenuEnabled(False)  # belt and braces; the menu was never built
        # pyqtgraph parks its own auto-range "A" in the bottom-left corner whenever the view is
        # not auto-ranged. We already have an A button that says what it does, and two of them --
        # one of which is an unlabelled square sitting on top of the data -- is one too many.
        self._plot.getPlotItem().hideButtons()
        # `hx` picks the crossing nearest the middle of what is on screen, so panning or zooming
        # changes the answer and the dots have to follow.
        self._plot.getViewBox().sigRangeChanged.connect(self._on_view_changed)
        # Double-click anywhere on the plot fetches the markers back. `mouseDoubleClickEvent` on
        # the scene rather than the widget: the ViewBox owns the mouse inside the plot area.
        self._plot.getPlotItem().scene().sigMouseClicked.connect(self._on_scene_click)
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
        # Shift the second trace in time. A spin box rather than buttons: 0.198 ms is typed as
        # often as it is nudged, and the step matches the finest a DSP usually offers.
        self._shift_label = QLabel(i18n.t("curveShift"))
        self._shift_label.setProperty("class", "phead-sub")
        row.addWidget(self._shift_label)
        self._shift_box = QDoubleSpinBox()
        self._shift_box.setProperty("class", "mini-select")
        self._shift_box.setDecimals(3)
        self._shift_box.setSingleStep(0.01)
        self._shift_box.setRange(-50.0, 50.0)
        self._shift_box.setSuffix(" ms")
        self._shift_box.setFixedWidth(96)
        # C locale: everything else in this window prints a dot, and a box that reads "0,198" next
        # to a readout saying "0.198" makes the reader check whether they are the same number.
        self._shift_box.setLocale(QLocale(QLocale.Language.C))
        self._shift_box.valueChanged.connect(self.set_shift)
        attach_tip(self._shift_box, i18n.t("curveShiftTip"))
        row.addWidget(self._shift_box)

        for mode in ("v", "h", "vh", "vhs", "vx", "hx"):
            button = QPushButton(_MODE_LABELS[mode])
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
        self._shift_ms = 0.0
        self._crossing_dots = None
        self._syncing = False
        self._marker_names: list[str] = []
        self._render_readout()

    def bring_markers_into_view(self) -> None:
        """Put every marker back inside the visible span, keeping their order and spacing where it
        fits.

        After a zoom the markers are usually somewhere off-screen, and hunting for them is worse
        than the zoom was worth (user, 2026-08-12). Markers already visible are left exactly where
        they are — moving a reading nobody asked to move would destroy the answer being read.
        """
        (low, high), _ = self._plot.getViewBox().viewRange()
        if high <= low:
            return
        span = high - low
        for index, line in enumerate(self._markers):
            if low <= line.value() <= high:
                continue
            # Spread the strays across the middle third, in their own order, so two of them do not
            # land on top of each other.
            share = (index + 1) / (len(self._markers) + 1)
            line.setValue(low + span * (0.34 + 0.32 * share))
        for line in self._h_markers:
            (_x, (y_low, y_high)) = (None, self._plot.getViewBox().viewRange()[1])
            if not y_low <= line.value() <= y_high:
                line.setValue((y_low + y_high) / 2.0)
        self._sync_levels()
        self._render_crossings()
        self._render_readout()
        self.markersChanged.emit()

    # ---- content ---------------------------------------------------------

    def set_shift(self, ms: float) -> None:
        """Offset the SECOND trace by `ms`, and redraw.

        One trace, not both, because alignment is always relative — and the second, because the
        first is the reference the Arbiter is aligning to. Their own working order is pairwise:
        w-L against w-R, then each against the sub, then the mid.

        On an impulse this slides the curve along time. On a phase plot it is the same fact seen
        differently: a pure delay is `φ = −360·f·Δt`, exactly, so the shift becomes a ramp. That
        direction is arithmetic; reading a delay OFF a wrapped phase curve is the hard one, and
        this deliberately does not attempt it.
        """
        self._shift_ms = float(ms)
        box = getattr(self, "_shift_box", None)
        if box is not None and abs(box.value() - self._shift_ms) > 1e-9:
            # Set programmatically — by the model opening the window with a proposal of its own,
            # or by a reset. The control must show what is drawn.
            blocked = box.blockSignals(True)
            box.setValue(self._shift_ms)
            box.blockSignals(blocked)
        if self._traces:
            self.set_traces(self._traces)
        self._render_readout()

    def _shifted(self, index: int, trace: "Trace"):
        """`(x, y)` for trace `index` with the current shift applied, in the plot's own units."""
        x = np.asarray(trace.x, dtype=float)
        y = np.asarray(trace.y, dtype=float)
        if index != 1 or not self._shift_ms:
            return x, y
        if self._unit == "ms":
            return x + self._shift_ms, y
        if self._y_unit == "°":
            # Degrees per hertz for this delay, then wrapped back into ±180 so the curve stays on
            # the axis it is drawn on rather than walking off it.
            shifted = y - 360.0 * x * (self._shift_ms / 1000.0)
            return x, (shifted + 180.0) % 360.0 - 180.0
        return x, y  # a magnitude response does not move when you delay it

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
            # Arrays, not Python lists: pyqtgraph converts a list element by element, and a list
            # comprehension over 262 144 floats had already been paid for upstream.
            x, y = self._shifted(index, trace)
            label = trace.name
            if index == 1 and self._shift_ms:
                label = f"{trace.name}  {self._shift_ms:+.3f} ms"
            self._plot.plot(x, y, pen=pg.mkPen(getattr(theme, token), width=1.0), name=label)
        for line in self._markers:
            self._plot.addItem(line)
        self._render_crossings()
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
                # Thicker than the traces, deliberately. A guide the same weight as a dense
                # impulse disappears into it — on the frequency response, where the trace is
                # sparser, the same line read clearly, which is what made the difference visible
                # (user, 2026-08-12). It is furniture over the data, not another curve.
                pen=pg.mkPen(getattr(theme, token), width=_GUIDE_WIDTH,
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
        self._render_crossings()
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
        self._axes_mode = mode if mode in _MODE_LABELS else "v"
        for button, value in self._axes_buttons:
            button.setChecked(value == self._axes_mode)
        self._rebuild_h_markers()
        for index, line in enumerate(self._markers):
            # A cross mode has exactly ONE line: the whole question is what a single position says
            # about both curves at once, and a second line would be a second question.
            line.setVisible(
                index == 0 if self._axes_mode == "vx"
                else False if self._axes_mode == "hx"
                else "v" in self._axes_mode
            )
        self._render_crossings()
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
        if self._axes_mode == "hx":
            # One horizontal line, placed at whatever the first curve is doing where the vertical
            # marker last stood -- a level somewhere on the data rather than at zero.
            theme = current_theme()
            level = self._y_at(0, self.positions()[0]) if self.positions() else 0.0
            line = pg.InfiniteLine(
                pos=level, angle=0, movable=True,
                pen=pg.mkPen(theme.accent, width=1.4, style=Qt.PenStyle.DashLine),
            )
            line.sigPositionChanged.connect(self._on_marker_moved)
            self._plot.addItem(line)
            self._h_markers = [line]
            return
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
                pen=pg.mkPen(getattr(theme, token), width=_GUIDE_WIDTH,
                             style=Qt.PenStyle.DotLine),
            )
            line.sigPositionChanged.connect(self._on_marker_moved)
            self._plot.addItem(line)
            self._h_markers.append(line)

    def _render_crossings(self) -> None:
        """Dots where the single line meets each curve. Nothing to draw outside the cross modes."""
        if self._crossing_dots is not None:
            self._plot.removeItem(self._crossing_dots)
            self._crossing_dots = None
        if self._axes_mode not in _CROSS_MODES or not self._traces:
            return
        theme = current_theme()
        spots = []
        for index, (x, y) in enumerate(self.crossings()):
            token = self._marker_tokens[index] if index < len(self._marker_tokens) else "accent"
            spots.append({
                "pos": (self._to_view(x), y), "size": 9,
                "brush": pg.mkBrush(getattr(theme, token)),
                "pen": pg.mkPen(theme.panel, width=1.5),
            })
        if spots:
            self._crossing_dots = pg.ScatterPlotItem(spots)
            self._plot.addItem(self._crossing_dots)

    def crossings(self) -> list[tuple[float, float]]:
        """Where the single line meets each curve, as (x, y) in the axes' own units.

        `vx` is exact: a vertical line has one y per curve. `hx` is a choice — a level line can
        cross a response many times — and the choice is the crossing nearest the middle of what is
        currently on screen, because that is the one being pointed at. Zooming to the region of
        interest is therefore part of asking the question, which is honest about the ambiguity
        rather than hiding it behind a rule nobody can see.
        """
        if self._axes_mode == "vx":
            if not self._markers:
                return []
            x = self.positions()[0]
            return [(x, self._y_at(i, x)) for i in range(len(self._traces))]
        if self._axes_mode == "hx":
            if not self._h_markers:
                return []
            level = float(self._h_markers[0].value())
            (low, high), _ = self._plot.getViewBox().viewRange()
            centre = self._from_view((low + high) / 2.0)
            out = []
            for index in range(len(self._traces)):
                x = self._crossing_near(index, level, centre)
                if x is not None:
                    out.append((x, level))
            return out
        return []

    def _crossing_near(self, index: int, level: float, centre: float) -> Optional[float]:
        """The x where trace `index` crosses `level`, closest to `centre`. None if it never does."""
        trace = self._traces[index]
        xs = np.asarray(trace.x, dtype=float)
        ys = np.asarray(trace.y, dtype=float) - level
        if xs.size < 2:
            return None
        sign_change = np.nonzero(np.diff(np.signbit(ys)))[0]
        if not sign_change.size:
            return None
        # Linear interpolation across the sample pair that straddles the level -- at 262 144
        # points the difference is invisible, but at 957 (a frequency response) it is not.
        x0, x1 = xs[sign_change], xs[sign_change + 1]
        y0, y1 = ys[sign_change], ys[sign_change + 1]
        with np.errstate(divide="ignore", invalid="ignore"):
            crossings = np.where(y1 != y0, x0 - y0 * (x1 - x0) / (y1 - y0), x0)
        return float(crossings[int(np.abs(crossings - centre).argmin())])

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
        if self._axes_mode in _CROSS_MODES:
            return self._cross_reading(digits)
        lines = []
        if "v" in self._axes_mode:
            lines.append(self._axis_reading(self.positions(), self._unit, digits))
        if "h" in self._axes_mode:
            lines.append(self._axis_reading(self.levels(), self._y_unit or "", 1))
        parts = [part for part in lines if part]
        if self._shift_ms and len(self._traces) > 1:
            # Named as a PROPOSAL. The panel changes nothing: this sentence goes to the composer,
            # the Arbiter sends it, and the delta is banked 🟡 like every other proposed change.
            parts.append(i18n.t("curveShiftReading").format(
                name=self._traces[1].name, ms=f"{self._shift_ms:+.3f}"))
        if not parts:
            return ""
        # One line. It has a full-width row of its own now, which is room enough — the wrapping is
        # there for a narrow window, not as the normal shape (user, 2026-08-11).
        body = "; ".join(parts)
        # ...and the header is dropped when the markers are already named after their curves,
        # which is the ordinary case: "tw-L / tw-R — tw-L: …, tw-R: …" says each name twice for
        # no reader's benefit.
        if list(names) == list(self._marker_names):
            return body
        return f"{' / '.join(names)} — {body}"

    def _cross_reading(self, digits: int) -> str:
        """One line, both curves. "At 2.5 kHz the channels are 6 dB apart" is a single fact about
        a pair, and it is the reason these modes exist — the per-curve markers cannot state it,
        because there the two markers are in different places."""
        crossings = self.crossings()
        if not crossings:
            return ""
        names = [t.name for t in self._traces]
        if self._axes_mode == "vx":
            at = f"{crossings[0][0]:.{digits}f} {self._unit}".strip()
            unit = f" {self._y_unit}" if self._y_unit else ""
            values = [y for _x, y in crossings]
            body = ", ".join(
                f"{names[i] if i < len(names) else i}: {y:.1f}{unit}"
                for i, y in enumerate(values)
            )
            if len(values) >= 2:
                body += f" (Δ {abs(values[1] - values[0]):.1f}{unit})"
        else:
            level_unit = f" {self._y_unit}" if self._y_unit else ""
            at = f"{crossings[0][1]:.1f}{level_unit}".strip()
            values = [x for x, _y in crossings]
            body = ", ".join(
                f"{names[i] if i < len(names) else i}: {x:.{digits}f} {self._unit}"
                for i, x in enumerate(values)
            )
            if len(values) >= 2:
                body += f" (Δ {abs(values[1] - values[0]):.{digits}f} {self._unit})"
        return f"{i18n.t('curveAt')} {at} — {body}"

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
        self._on_any_move()
        self._render_readout()
        self.markersChanged.emit()

    def _on_any_move(self) -> None:
        self._render_crossings()

    def _on_scene_click(self, event) -> None:
        if getattr(event, "double", lambda: False)():
            self.bring_markers_into_view()

    def _on_view_changed(self, *_args) -> None:
        if self._axes_mode == "hx":
            self._render_crossings()
            self._render_readout()

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
        self._shift_label.setText(i18n.t("curveShift"))
        for button, mode in self._axes_buttons:
            if getattr(button, "hover_tip", None) is not None:
                button.hover_tip.set_text(i18n.t(f"curveAxes_{mode}"))
        for button, key in self._zoom_buttons:
            button.setText(i18n.t(key + "Short"))
            if getattr(button, "hover_tip", None) is not None:
                button.hover_tip.set_text(i18n.t(key))
        self._render_readout()
