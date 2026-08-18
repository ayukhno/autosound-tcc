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

Markers are draggable and their delta is the readout, because "how far apart are these two
arrivals" is the question that keeps being asked.

As many traces as the tuner names. It began as two, because a disagreement is nearly always about
a pair (w-L against w-R, a driver against its joint partner), and that is still the commonest
question — but the tune itself is argued about in GROUPS: the woofers, sub+woofers, a whole side,
everything (user, 2026-08-18). Nothing below is pair-shaped any more except the cross modes, which
answer a question that has no N-curve form at all — see `cross_pair`.
"""

from __future__ import annotations

import html
import importlib
import math
import textwrap
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import curve_sum
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.theme import current_theme

# The two trace colours, in order. Deliberately the theme's own accent + info rather than
# pyqtgraph's defaults: a plot that does not belong to the window it is in reads as a screenshot
# of another program, which is the thing this feature exists to stop needing.
_TRACE_TOKENS = ("accent", "info")
#: Hues, in degrees, for traces three and up — a whole side is four drivers and ALL+C is seven
#: (CURVE-ANALYSIS-PLAN.md, step 3), and two colours cycling would paint driver three the same as
#: driver one. Not new palette tokens: `theme.py` is the whole app's vocabulary and this window is
#: not the place to grow it for its own plot. They are the accent's own saturation and value at
#: another hue, so they keep the palette's contrast in both themes, and the hues themselves are
#: chosen to stand clear of what a colour already MEANS here — `ok` green, `warn` red, `yellow`
#: for the predicted sum, and the accent/info the first two traces have.
_TRACE_HUES = (285, 175, 330, 250, 105, 75)
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
#: The predicted sum's pen. Dashed, because it is a PREDICTION standing among measurements — but
#: readable, which the first attempt was not: `text` at alpha 150 and 1.2 px came out as a thin
#: grey dash nobody could follow across the plot (user, 2026-08-18, with the screenshot). Yellow
#: is the one bright token left over: `accent` and `info` are the two traces, `muted` and `ok` are
#: the markers, and `warn`/`ok` carry a verdict in this palette — "wrong" and "fine" — which a
#: prediction is neither of. Near-full alpha rather than full, so the dash still sits a step
#: behind the measured curves it was computed from.
_SUM_TOKEN = "yellow"
_SUM_ALPHA = 235
_SUM_WIDTH = 2.2
#: How far under its own loudest point the drawn sum is allowed to fall. `curve_sum` returns −inf
#: at an exact null and says in as many words that the floor is the DRAWING's decision — without
#: one, a synthetic cancellation takes the whole right-hand axis to −inf and the curve with it.
_SUM_FLOOR_DB = 60.0
#: Fallback delay step, in ms, when no profile has been read. What DSPs seen so far let you TYPE;
#: the hardware resolves in whole samples, which is a different number — see `set_resolution`.
_DEFAULT_STEP_MS = 0.01
#: How far the Σ toggle sits from the corner of the plot AREA, in pixels. Inside the axes, over
#: the data, at the end furthest from the legend — which is anchored to the top RIGHT, so the pill
#: naming each driver and its delay is never covered.
_OVERLAY_MARGIN_PX = 6
#: How the hover tips that replaced the paragraphs under the plot are built.
#:
#: `_TIP_FONT_PX` because the paragraphs they replaced were 11 px `phead-sub` grey and the user
#: could not read them (2026-08-18). `_TIP_WRAP_CHARS` because the shared tip widget is a QLabel
#: with word wrap OFF, so a long sentence asks for a label as wide as the sentence and
#: `adjustSize` clips it to two thirds of the screen: measured here, a 200-character line wants
#: 1434 px and gets 533. Wrapping the text ourselves is the only lever this side of
#: `rounded_tooltip`, which is shared with every other tip in the app.
_TIP_WRAP_CHARS = 72
_TIP_FONT_PX = 15
#: How tall the sum's own strip stands under an impulse, in pixels. Short on purpose: the plot
#: above it is what is being worked in — the delay is DRAGGED there — and the strip answers one
#: question, "is the joint filling in", which a band 6 dB deep is enough to show.
_STRIP_HEIGHT_PX = 132
#: The name a trace colour goes by when the palette has no token for it — `trace#N`, resolved
#: against the CURRENT theme by `colour_of`. A hex string would have done, except that markers
#: keep their colour name across a theme switch (`apply_theme` re-sets them with the same list),
#: and a hex captured under the dark palette would come back dark on the light one.
_DERIVED_PREFIX = "trace#"


def trace_token(index: int) -> str:
    """The colour NAME of trace `index`: a palette token for the first two, a derived one after.

    A name rather than a value, everywhere, because every colour in this widget is re-resolved on
    a theme switch — the plot draws with explicit pens and does not repaint from a stylesheet.
    """
    if index < len(_TRACE_TOKENS):
        return _TRACE_TOKENS[index]
    return f"{_DERIVED_PREFIX}{index}"


def colour_of(token: str) -> QColor:
    """A colour by name: a palette token, or one of this window's derived trace hues."""
    if str(token).startswith(_DERIVED_PREFIX):
        try:
            index = int(str(token)[len(_DERIVED_PREFIX):])
        except ValueError:
            index = len(_TRACE_TOKENS)
        base = QColor(getattr(current_theme(), _TRACE_TOKENS[0]))
        hue = _TRACE_HUES[(index - len(_TRACE_TOKENS)) % len(_TRACE_HUES)]
        return QColor.fromHsv(hue, base.saturation(), base.value())
    return QColor(getattr(current_theme(), str(token), None) or str(token))


def tip_html(text: str, head: str = "", warn: bool = False) -> str:
    """`text` as a hover tip: large, wrapped, with a bold head, warning-coloured when in doubt.

    The three paragraphs that used to stand under the plot are behind buttons now (user,
    2026-08-18: they took the space and could not be read), so the text that was a wall of small
    grey type is the same text laid out to be read — which is the whole point of moving it.

    Nothing that LEAVES the window comes through here: `statement()` and the bank's own sentence
    are built from the plain strings and are unchanged. This is drawing, only.
    """
    theme = current_theme()
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        wrapped = textwrap.wrap(
            paragraph, _TIP_WRAP_CHARS, break_long_words=False, break_on_hyphens=False
        )
        lines.extend(html.escape(part) for part in (wrapped or [""]))
    body = "<br>".join(lines)
    if head:
        body = f"<b>{html.escape(head)}</b><br>{body}"
    if warn:
        body = f'<span style="color: {theme.warn}">{body}</span>'
    return f'<div style="font-size: {_TIP_FONT_PX}px; color: {theme.text}">{body}</div>'


def _restyle(widget: QWidget, sheet: str) -> None:
    """Give a widget its own stylesheet, and only when it is not the one it already has.

    `setStyleSheet` re-polishes the widget on every call, and the state colours here are decided
    inside `_render_readout` — which runs on every step of every marker drag. A re-polish per
    mouse move, for a colour that changes twice in a session, is not a trade worth making.
    """
    if widget.styleSheet() != sheet:
        widget.setStyleSheet(sheet)


class _UnbuiltSubmenu:
    """Stands in for a submenu that is never created, and swallows whatever is done to it.

    Permissive on purpose: a later pyqtgraph that calls something else on the object `addMenu`
    returned must get a no-op, not an `AttributeError` at plot construction.
    """

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *args, **kwargs: None


class _PlotOptionsMenu(QMenu):
    """pyqtgraph's `ctrlMenu`, real but left empty — see `_do_not_build_the_plot_options_menu`."""

    def addMenu(self, *args, **kwargs) -> _UnbuiltSubmenu:  # noqa: N802 (Qt naming)
        return _UnbuiltSubmenu()


class _QtWidgetsWithoutSubmenus:
    """`PlotItem.py`'s view of `QtWidgets`, with only `QMenu` swapped."""

    QMenu = _PlotOptionsMenu

    def __init__(self, real) -> None:
        self._real = real

    def __getattr__(self, name: str):
        return getattr(self._real, name)


def _do_not_build_the_plot_options_menu() -> None:
    """Stop pyqtgraph filling a menu we never show — the line the process dies on.

    `PlotItem.__init__` builds six submenus and six `QWidgetAction`s unconditionally
    (0.14.0 `PlotItem.py:231-237`; byte-identical on upstream master, and `enableMenu=False`
    governs the ViewBox's menu, not this one). Adding a Python-created `QWidgetAction` to a QMenu
    makes Qt connect to it BY SIGNAL NAME, which asks PySide for the action's metaobject:

        Sbk_QMenuFunc_addAction → QWidget::insertAction → QMenu::actionEvent
          → QObject::connect → PySide::SignalManager::retrieveMetaObject → SIGSEGV

    The crash report has `x0 = 0` at that last frame: a C++ object asked for a metaobject it has
    no Python half left to answer with. Two sessions read this as a leak or a GC accident and both
    were wrong — the count of live QMenus settles at zero, and neither `gc.disable()` nor
    per-test teardown moved the rate.

    Measured 2026-08-13, 40 runs each of the two plot-heavy test files (44 plots per run):
    5/40 crashes as shipped, **0/40 with this patch**. Three other candidates, same protocol,
    did not fix it: keeping pyqtgraph's ctrl form widget alive 1/40, dropping
    `_adopt_orphan_menus` 3/40, keeping the `QWidgetAction` wrappers alive 3/40. The rate over
    all baseline runs is 12/81, so 0/40 is worth 0.15%, not luck.

    Nothing is lost: the menu is disabled twice over (`enableMenu=False` at construction and
    `setMenuEnabled(False)` after), it renders white-on-white in the dark theme, and everything
    it offers is on the A/D/−/+ buttons. `self.ctrl` — which `showGrid`, `setDownsampling`,
    `setClipToView` and `setLogMode` all read — is untouched, and so is the `ctrlMenu` object
    itself, which `PlotItem.close()` expects to find.

    Written defensively for the same reason `_adopt_orphan_menus` is: a pyqtgraph that stops
    building the menu, or restructures it, must leave this a no-op rather than an import-time
    crash.
    """
    try:
        module = importlib.import_module("pyqtgraph.graphicsItems.PlotItem.PlotItem")
    except ImportError:  # pragma: no cover — pyqtgraph is a hard dependency of this module
        return
    real = getattr(module, "QtWidgets", None)
    if real is None or not hasattr(real, "QMenu") or isinstance(real, _QtWidgetsWithoutSubmenus):
        return
    module.QtWidgets = _QtWidgetsWithoutSubmenus(real)


_do_not_build_the_plot_options_menu()


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
    """One curve: a name the skill would recognise, its samples, and what a sum needs of it.

    `x`/`y` are what is DRAWN, in this view's own units — degrees against hertz on the phase plot,
    dB against hertz on the frequency response, a sample value against milliseconds on an impulse.
    `magnitude_db` and `phase_deg` are the MEASUREMENT, both halves of it, because a complex sum
    needs both at once and REW returns them from one call. Either may be `None`: an MMM/RTA capture
    carries a magnitude and no phase at all.

    `freqs_hz` is what those two are stated AGAINST, and it exists for exactly one view: the
    impulse, where `x` is time and cannot double as the frequency axis the way it does on the other
    two. `None` means "`x` is already the frequency axis", which is true wherever this window plots
    against hertz.

    `config_version` and `method` are `_N` and the `(sw)`/`(rta)` suffix as the skill's own grammar
    reads them (`naming-and-structure.md` §3). They are not decoration — they are what decides
    whether these curves may be added together at all (`core/curve_sum.summability`), and `None`
    means "this title is not in the grammar", which that module has its own verdict for rather
    than a crash. `start_time_s` is REW's own timing reference for the capture, carried so it can
    be REPORTED with the sum; nothing in TCC judges it, and the module docstring of `curve_sum`
    says why nothing can.
    """

    name: str
    x: Sequence[float]
    y: Sequence[float]
    magnitude_db: Optional[Sequence[float]] = None
    phase_deg: Optional[Sequence[float]] = None
    config_version: Optional[str] = None
    method: Optional[str] = None
    start_time_s: Optional[float] = None
    freqs_hz: Optional[Sequence[float]] = None


class CurveView(QWidget):
    """Traces, draggable markers, and a readout of what the markers say.

    `markersChanged` fires while a marker is dragged; `reading()` is the answer at any moment. The
    widget itself decides nothing and records nothing — the caller does both, which keeps this a
    renderer and keeps the recording in one place.
    """

    markersChanged = Signal()
    #: The delay, or which trace it applies to, changed. The window banks it per measurement; the
    #: view keeps nothing across a pair — a delay read here is worth as much as the six read
    #: before it, and holding only the current one is what left the rest in the Arbiter's head.
    delayChanged = Signal()

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
        self._plot.setMenuEnabled(False)  # belt and braces
        self._adopt_orphan_menus()
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

        #: Whether the predicted sum is drawn, and everything it produced last time it was.
        #: OFF by default, deliberately. This window is opened to compare two measured curves as
        #: often as to predict their joint, and a sum drawn unasked would put a prediction — plus
        #: its refusal notice, on every mixed sweep/MMM pair — in front of somebody who asked for
        #: neither. The kind picker has the same manners: it never jumps on its own, it only stops
        #: refusing. Once switched on it STAYS on, across a new pair and across `reset()`, because
        #: a tuner working through a car wants it for all of them, not for one.
        self._sum_on = False
        #: Built on FIRST USE and never rebuilt — see `_build_sum_axis`. With the sum off, which
        #: is the default and most of a session, this window holds exactly the graphics items it
        #: held before this feature existed. In a file whose crash history is entirely about how
        #: many graphics objects get constructed and destroyed, that is worth a lazy branch.
        self._sum_vb: Optional[pg.ViewBox] = None
        self._sum_axis_failed = False
        self._sum_curve = None
        self._sum_result: Optional[curve_sum.SumResult] = None
        self._sum_text = ""
        self._sum_doubted = False
        #: The sum's own strip under the impulse — the same lazy bargain as the axis above, and for
        #: a stronger reason: this one is a second `PlotWidget`, so building it at construction
        #: would double the number of `PlotItem`s every curve window ever makes, in the file whose
        #: crash history is exactly that (`_do_not_build_the_plot_options_menu`). Kept as a member
        #: of THIS widget and put in THIS widget's layout, so Qt destroys it with the view.
        self._strip: Optional[pg.PlotWidget] = None
        self._strip_failed = False
        self._strip_curve = None
        self._layout = layout

        # ON the chart, in the plot AREA's top-left corner (user, 2026-08-18, with the
        # screenshot): the toggle belongs to the picture it changes rather than to the row of
        # controls under it, where it stood among eight other square buttons and had to be hunted
        # for. A child widget of the plot rather than a graphics item, because it is a button —
        # checkable, hoverable, and wearing the same stylesheet as every other button here.
        # `_place_sum_button` keeps it in the corner; nothing inside the plot moves, so the legend
        # pill naming each driver and its delay stays exactly where it was.
        self._sum_btn = QPushButton("Σ", self._plot)
        self._sum_btn.setProperty("class", "zoom-btn")
        self._sum_btn.setCheckable(True)
        self._sum_btn.setChecked(self._sum_on)
        self._sum_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sum_btn.setFixedSize(30, 24)
        # Not in the tab order: it floats over the data, and a focus rectangle wandering onto a
        # control drawn on top of the plot is one more thing on screen that is not the curve.
        self._sum_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        attach_tip(self._sum_btn, tip_html(i18n.t("curveSumTip")))
        self._sum_btn.clicked.connect(self.set_sum_shown)
        self._plot.getPlotItem().vb.sigResized.connect(self._place_sum_button)
        self._place_sum_button()

        # What used to be four lines of small grey text and a red sentence under the plot: two
        # compact buttons that NAME what stands behind them, with the whole text in a hover tip
        # (user, 2026-08-18: "займають місце і не читаються"). The verdict is about the CURVE and
        # the reading is about the MARKERS, so they stay two things, side by side, one row high.
        notes = QHBoxLayout()
        notes.setContentsMargins(2, 0, 2, 0)
        notes.setSpacing(6)
        # The summability verdict and the timing assumption, verbatim from `curve_sum` — a drawn
        # sum ends an argument, so a sum that cannot be believed has to say so where the eye
        # already is (CURVE-ANALYSIS-PLAN.md, "The precondition"). It says it on the BUTTON, in
        # colour, because a reader who is not going to read a paragraph will not read it in a tip
        # either. Hidden entirely while the sum is off, which is why turning it off leaves this
        # window exactly the shape it was before the feature existed.
        self._sum_note_btn = QPushButton(i18n.t("curveSumNoteBtn"))
        self._sum_note_btn.setProperty("class", "clear-btn")
        self._sum_note_btn.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._sum_note_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        attach_tip(self._sum_note_btn, "")
        self._sum_note_btn.setVisible(False)
        notes.addWidget(self._sum_note_btn)
        # The markers' own reading — the sentence that goes to the model. Same treatment: it was a
        # full-width paragraph that grew a red half whenever a total went below zero, and both the
        # length and the red were the reason it stopped being read.
        self._readout_btn = QPushButton(i18n.t("curveReadoutBtn"))
        self._readout_btn.setProperty("class", "clear-btn")
        self._readout_btn.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._readout_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        attach_tip(self._readout_btn, "")
        notes.addWidget(self._readout_btn)
        # WHICH two curves the cross modes read. Only on screen when there is a choice to make —
        # more than two traces and a cross mode selected — and in this row rather than beside the
        # mode buttons because that row is already full at seven drivers, and because what these
        # two combos configure is the READING, which is what this row is about.
        self._cross_label = QLabel("×")
        self._cross_label.setProperty("class", "phead-sub")
        self._cross_combos: list[QComboBox] = []
        for slot in (0, 1):
            combo = QComboBox()
            combo.setProperty("class", "mini-select")
            combo.setFixedWidth(96)
            combo.currentIndexChanged.connect(
                lambda _index, at=slot: self._on_cross_combo(at)
            )
            attach_tip(combo, i18n.t("curveCrossPairTip"))
            combo.setVisible(False)
            if slot:
                notes.addWidget(self._cross_label)
            notes.addWidget(combo)
            self._cross_combos.append(combo)
        self._cross_label.setVisible(False)
        notes.addStretch(1)
        layout.addLayout(notes)

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
        # WHICH trace is held back, then by how much. Radio buttons rather than a signed number: a
        # DSP has no negative delay, so the question is which driver waits, and the two answers are
        # the same alignment read from either end. One per trace, built as traces arrive — a whole
        # side is four drivers and ALL is six, and a pair of radios would have made those
        # unreachable.
        self._target_buttons: list[QRadioButton] = []
        #: Where in this row a new radio goes. Recorded rather than counted later: the delay
        #: group's own action is inserted into the same row (`add_delay_action`), so the two
        #: insertion points have to move together as radios appear.
        self._radio_slot = row.count()
        self._ensure_target_buttons(2, row)

        self._shift_label = QLabel(i18n.t("curveShift"))
        self._shift_label.setProperty("class", "phead-sub")
        row.addWidget(self._shift_label)
        self._shift_box = QDoubleSpinBox()
        self._shift_box.setProperty("class", "mini-select")
        self._shift_box.setDecimals(3)
        self._shift_box.setSingleStep(_DEFAULT_STEP_MS)
        # Negative is allowed again (user, 2026-08-12): on a later pass you correct a channel that
        # is already delayed, and taking time BACK off it is an ordinary move. What must not go
        # below zero is the channel's TOTAL — which this widget cannot know on its own, so the
        # caller supplies it via `set_channel_delay()` and the readout says when the sum is
        # impossible instead of the box refusing to express it.
        self._shift_box.setRange(-50.0, 50.0)
        self._shift_box.setSuffix(" ms")
        self._shift_box.setFixedWidth(96)
        # C locale: everything else in this window prints a dot, and a box that reads "0,198" next
        # to a readout saying "0.198" makes the reader check whether they are the same number.
        self._shift_box.setLocale(QLocale(QLocale.Language.C))
        self._shift_box.valueChanged.connect(self.set_delay)
        attach_tip(self._shift_box, i18n.t("curveShiftTip"))
        row.addWidget(self._shift_box)
        #: Where the delay group's action goes — see `add_delay_action`.
        self._delay_slot = row.count()

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
        # Each group of controls ends with the action that group produces, and both are named
        # after their group — the same two names the Clear section uses (user, 2026-08-12:
        # "кнопки називаються однаково і ті що відправляють і ті що в секції очистки"). So the
        # window has two verbs, "Затримки" and "Маркери", and each appears twice: once to send,
        # once to clear. Nothing is called "this is my reading" any more.
        self._send_btn = QPushButton(i18n.t("curveSendMarkers"))
        self._send_btn.setProperty("class", "composer-send")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self._send_btn)
        self._action_row = row
        layout.addLayout(row)

        self._detail_range: Optional[tuple[float, float]] = None
        self._traces: list[Trace] = []
        self._markers: list[pg.InfiniteLine] = []
        self._h_markers: list[pg.InfiniteLine] = []
        self._marker_tokens: list[str] = []
        #: One delay per TRACE, not one per pair. A pair is not the unit of alignment — the car
        #: is: every driver is delayed against a single origin (x = 0 here), and only then are the
        #: numbers mutually consistent. The earlier one-delay-per-pair model produced two curves
        #: 2.4 ms apart from a 1.2 ms reading the moment the radio moved (user, with the picture,
        #: 2026-08-12), because it moved the amount to the other curve instead of leaving each
        #: driver its own. The radio now chooses WHICH DRIVER YOU ARE EDITING; both keep theirs.
        self._delays = [0.0, 0.0]
        #: What each channel is ALREADY set to on the DSP, when the caller knows. `None` means
        #: unknown, and unknown must never be rendered as zero: "this channel sits at 0.0" and
        #: "nobody told me" lead to opposite conclusions about a −0.15 ms proposal.
        self._channel_delays = [None, None]
        #: Which trace is held back. Defaults to the one that ARRIVES FIRST once traces are set —
        #: the only one a DSP can actually delay.
        self._shift_target = 0
        self._sample_rate_hz = None
        self._step_ms = _DEFAULT_STEP_MS
        self._crossing_dots = None
        self._syncing = False
        self._marker_names: list[str] = []
        #: Which two traces the cross modes compare — see `cross_pair` for why it is two.
        self._cross_indices = (0, 1)
        self._render_sum()
        self._render_readout()

    def _place_sum_button(self, *_args) -> None:
        """Keep the Σ toggle in the plot AREA's top-left corner — inside the axes, not over them.

        Driven by the ViewBox's own resize signal rather than by this widget's `resizeEvent`: the
        area the button has to sit in is the ViewBox's, and that settles AFTER the layout has
        finished with the plot. Scene coordinates map one-to-one onto the plot widget's (measured:
        a ViewBox at scene x=36 maps to widget x=36), and `mapFromScene` says so rather than
        assuming it.

        A Qt slot, so it can also arrive while the window is being torn down and the plot's C++
        half is already gone — the same `RuntimeError` `_resize_sum_axis` swallows, for the same
        reason: there is nothing left to place by then.
        """
        button = getattr(self, "_sum_btn", None)
        if button is None:
            return
        try:
            corner = self._plot.mapFromScene(
                self._plot.getPlotItem().vb.sceneBoundingRect().topLeft()
            )
        except RuntimeError:
            return
        button.move(corner.x() + _OVERLAY_MARGIN_PX, corner.y() + _OVERLAY_MARGIN_PX)
        # The plot's viewport is a sibling child of the same QGraphicsView, and stacking order is
        # creation order: a control drawn on the chart has to be told it is on top.
        button.raise_()

    def _sum_offered(self) -> bool:
        """Whether the Σ toggle is on screen at all: the phase and the impulse, never the FR.

        The user's own rule (2026-08-18) and it is about their workflow, not about the maths: the
        frequency response is where MMM/RTA captures get compared, and an MMM capture carries no
        phase, so on that view the answer to Σ is usually a refusal. A control that mostly refuses
        is a control that teaches people to ignore it.

        The CAPABILITY is untouched — `set_sum_shown(True)` still computes and draws the sum of
        two sweeps on a frequency response, and every test of the engine goes through that path.
        Only the button is not offered there.

        Asked in this widget's own vocabulary, which is units: the impulse's x is time, the
        phase's y is degrees, and the frequency response is the one that answers in dB.
        """
        return self._unit == "ms" or self._y_unit == "°"

    def _ensure_sum_axis(self) -> bool:
        """Build the right-hand axis the first time a sum is actually drawn, and only then.

        Not at construction: the sum is off by default, and a window that never shows one should
        not be carrying the graphics items for it. One attempt, then the answer is remembered
        either way — retrying a failed build on every redraw would turn a broken pyqtgraph into a
        stutter instead of a switched-off feature.
        """
        if self._sum_vb is None and not self._sum_axis_failed:
            self._build_sum_axis()
        return self._sum_vb is not None

    def _build_sum_axis(self) -> None:
        """A second Y axis on the right, in dB, with its own ViewBox behind the plot's.

        The sum is in dB and the plot it goes over may be in degrees (phase) or in dB at a
        completely different level (a two-driver sum sits ~6 dB above either driver), so it cannot
        share the left axis without either flattening itself or moving the measurements. A second
        ViewBox X-linked to the plot's is pyqtgraph's own answer to that (`MultiplePlotAxes.py`),
        and the right-hand axis already exists on every `PlotItem` — it is only hidden.

        **Ownership, because this file has been bitten by it.** The ViewBox goes into the plot's
        SCENE, which belongs to the `PlotWidget`, which is a child of this widget: it is destroyed
        with the view, in order, by Qt, and nothing is left parked on the `PlotItem` to outlive it
        (`_do_not_build_the_plot_options_menu` above is what that costs when it goes wrong).
        `enableMenu=False` for the same reason it is passed at the plot's own construction:
        `ViewBox.__init__` builds a whole `ViewBoxMenu` otherwise, and constructing and dropping
        enough of those segfaults the process from inside its own `__init__`.

        Guarded end to end. Reaching into `PlotItem` is reaching into somebody else's internals,
        and a pyqtgraph that renames or restructures them must leave this feature switched off
        rather than take the window down with it.
        """
        try:
            item = self._plot.getPlotItem()
            box = pg.ViewBox(enableMenu=False)
            item.scene().addItem(box)
            axis = item.getAxis("right")
            axis.linkToView(box)
            box.setXLink(item.vb)
            # Never in the way of a marker. The second box sits below the plot's own in the
            # stacking order, so it would not receive a press anyway — but the markers ARE this
            # panel's output, and "would not" is not a guarantee to rest a feature on.
            box.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            box.setMouseEnabled(x=False, y=False)
            item.vb.sigResized.connect(self._resize_sum_axis)
            self._sum_vb = box
            self._style_sum_axis()
            self._resize_sum_axis()
        except Exception:  # noqa: BLE001 — pyqtgraph moved; the feature is off, not the window
            self._sum_vb = None
            self._sum_axis_failed = True

    def _resize_sum_axis(self, *_args) -> None:
        """Keep the sum's ViewBox exactly over the plot's. It has no geometry of its own.

        This is a Qt signal's slot, so it can also arrive while the window is being torn down and
        the plot's C++ half is already gone — PySide answers that with a `RuntimeError` from a
        thread nobody is catching on. Swallowed, because there is nothing to resize by then.
        """
        if self._sum_vb is None:
            return
        try:
            item = self._plot.getPlotItem()
            self._sum_vb.setGeometry(item.vb.sceneBoundingRect())
            # The linked axis was updated while the two had different shapes, so it has to be told
            # again — pyqtgraph's own example carries the same two lines, and the same comment.
            self._sum_vb.linkedViewChanged(item.vb, self._sum_vb.XAxis)
        except RuntimeError:
            self._sum_vb = None

    def _style_sum_axis(self) -> None:
        """The right-hand axis wears the sum's own colour, so the eye pairs scale with curve."""
        if self._sum_vb is None:
            return
        theme = current_theme()
        axis = self._plot.getPlotItem().getAxis("right")
        axis.setPen(pg.mkPen(theme.border2))
        axis.setTextPen(pg.mkPen(self._sum_colour()))

    def _sum_colour(self) -> QColor:
        colour = QColor(getattr(current_theme(), _SUM_TOKEN))
        colour.setAlpha(_SUM_ALPHA)
        return colour

    def _adopt_orphan_menus(self, plot: Optional[pg.PlotWidget] = None) -> None:
        """Give pyqtgraph's parentless menus an owner, so they die with this widget.

        `PlotItem.__init__` builds `QMenu("Plot Options")` with **no parent**, unconditionally —
        `enableMenu=False` is checked for the ViewBox's menu, not this one (pyqtgraph 0.14,
        `PlotItem.py:231`). A top-level QMenu is left behind by every plot ever constructed.
        `_do_not_build_the_plot_options_menu` above keeps that menu EMPTY, which is what stops
        the segfault; this keeps the empty menu from outliving the widget that caused it.

        Reparenting is the fix rather than another workaround: an owned menu is destroyed with
        its widget, in order, by Qt itself. Written defensively because it reaches into
        pyqtgraph's internals — a version that stops building the menu, or names it something
        else, must leave this a no-op rather than a crash on startup.

        Takes the plot rather than assuming the main one: the sum's strip is a second `PlotWidget`
        and leaves a second orphan behind.
        """
        item = (plot or self._plot).getPlotItem()
        for name in ("ctrlMenu", "stateGroup"):
            menu = getattr(item, name, None)
            if menu is not None and hasattr(menu, "setParent"):
                try:
                    menu.setParent(self)
                except (RuntimeError, TypeError):  # noqa: PERF203 — one-time, at construction
                    pass

    def _ensure_target_buttons(self, count: int, row: Optional[QHBoxLayout] = None) -> None:
        """Have one delay radio per trace, making the missing ones.

        Grown and never shrunk: the extra radios are hidden by `set_traces` when a smaller
        selection arrives, and destroying a widget that a `toggled` connection is standing on is
        how this app has crashed before (a widget deleted from its own event handler is a SIGSEGV).
        Six spare hidden radios cost nothing; a torn-down one costs the window.
        """
        row = row if row is not None else self._action_row
        while len(self._target_buttons) < count:
            index = len(self._target_buttons)
            button = QRadioButton(str(index + 1))
            button.setProperty("class", "phead-sub")
            button.setChecked(index == 0)
            button.toggled.connect(
                lambda checked, i=index: self.set_delay_target(i) if checked else None
            )
            row.insertWidget(self._radio_slot + index, button)
            self._target_buttons.append(button)
            # Everything to the right of the radios moved one place along, including the slot the
            # delay group's action is inserted at.
            if getattr(self, "_delay_slot", None) is not None:
                self._delay_slot += 1

    def add_delay_action(self, button: QWidget) -> None:
        """Put the delay group's own action immediately after the delay controls.

        Not at the end of the row: an action belongs beside the controls that produce it, and
        parked at the far end it reads as a second opinion about the markers.
        """
        self._action_row.insertWidget(self._delay_slot, button)

    def on_send(self, handler: Callable[[str], None]) -> None:
        self._send_btn.clicked.connect(lambda: handler(self.statement()))

    def bring_markers_into_view(self, force: bool = False) -> None:
        """Put the markers back inside the visible span, keeping their order and spacing.

        After a zoom the markers are usually somewhere off-screen, and hunting for them is worse
        than the zoom was worth (user, 2026-08-12). On a double-click, markers already visible are
        left exactly where they are — moving a reading nobody asked to move would destroy the
        answer being read. `force` is the Clear button: there the whole point is to put them back
        in the middle of the screen, spread apart, and start the reading over ("очистка Маркери це
        повинно бути як дабл-клік — поставити по центру з зміщенням").
        """
        (low, high), _ = self._plot.getViewBox().viewRange()
        if high <= low:
            return
        span = high - low
        for index, line in enumerate(self._markers):
            if not force and low <= line.value() <= high:
                continue
            # Spread the strays across the middle third, in their own order, so two of them do not
            # land on top of each other.
            share = (index + 1) / (len(self._markers) + 1)
            line.setValue(low + span * (0.34 + 0.32 * share))
        for line in self._h_markers:
            (_x, (y_low, y_high)) = (None, self._plot.getViewBox().viewRange()[1])
            if force or not y_low <= line.value() <= y_high:
                line.setValue((y_low + y_high) / 2.0)
        self._sync_levels()
        self._render_crossings()
        self._render_readout()
        self.markersChanged.emit()

    # ---- content ---------------------------------------------------------

    def set_delay(self, ms: float) -> None:
        """Delay the CHOSEN trace by `ms`, and redraw.

        A delay, not a shift: this is time added to a channel, which is why the radio asks WHICH
        driver waits and why the default is the one that arrives first. Negative is allowed — on
        a later pass you are correcting a channel that already carries a delay, and taking time
        back off it is an ordinary move (user, 2026-08-12).

        The limit is on the SUM, not on this number: a channel cannot end up below zero. That is
        a fact about the ledger, not about this widget, so `set_channel_delay()` feeds it in and
        the readout reports an impossible total rather than the box quietly refusing to type it.

        On an impulse this slides the curve later in time. On a phase plot it is the same fact
        seen differently: a pure delay is `φ = −360·f·Δt`, exactly, so it becomes a ramp. That
        direction is arithmetic; reading a delay OFF a wrapped phase curve is the hard one, and
        this deliberately does not attempt it.
        """
        self._delays[self._shift_target] = float(ms)
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
        self.delayChanged.emit()

    @property
    def _shift_ms(self) -> float:
        """The selected driver's delay — what the box shows and what typing in it changes."""
        return self._delays[self._shift_target] if self._shift_target < len(self._delays) else 0.0

    def set_channel_delay(self, ms, index: Optional[int] = None) -> None:
        """What a channel is already set to, from the ledger. `None` when not known.

        Defaults to the selected driver; `index` addresses the other one, because the reading
        states a total for every driver that carries a proposal, not only the one being edited.
        """
        at = self._shift_target if index is None else index
        if 0 <= at < len(self._channel_delays):
            self._channel_delays[at] = None if ms is None else float(ms)
        self._render_readout()

    def total_delay_ms(self, index: Optional[int] = None):
        """A channel's delay if its proposal were applied, or None when the current one is not
        known. The one number that has to stay non-negative."""
        at = self._shift_target if index is None else index
        if not (0 <= at < len(self._channel_delays)) or self._channel_delays[at] is None:
            return None
        return self._channel_delays[at] + self._delays[at]

    def delay_ms(self, index: Optional[int] = None) -> float:
        at = self._shift_target if index is None else index
        return self._delays[at] if 0 <= at < len(self._delays) else 0.0

    def delays(self) -> list[float]:
        """Every driver's delay, in trace order."""
        return list(self._delays)

    def delay_target_name(self) -> str:
        """The name of the trace being held back, or "" when there is no such trace."""
        if self._shift_target < len(self._traces):
            return self._traces[self._shift_target].name
        return ""

    def set_resolution(self, step_ms, sample_rate_hz) -> None:
        """Step the delay by what the DSP offers, and count samples with its rate.

        Two different numbers, and the profile carries both: `delay.step_ms` is what the vendor's
        software lets you TYPE (0.01 ms on this Helix), one sample at `sample_rate_hz` is what the
        hardware RESOLVES (0.010417 ms at 96 kHz). The control steps by the first, because that is
        the box the Arbiter types into; the reading gives both, because the skill's own rule is
        that a delay is always stated in milliseconds AND samples.

        The two do not divide evenly, and that is not a rounding detail: 0.01 ms is 0.96 samples
        at 96 kHz, so roughly every twenty-fifth typed step moves the driver by nothing at all.
        The user has been watching PC-Tool swallow a step with no explanation for it
        (2026-08-12); printing both numbers is the explanation.
        """
        self._sample_rate_hz = float(sample_rate_hz) if sample_rate_hz else None
        step = float(step_ms) if step_ms else (
            1000.0 / self._sample_rate_hz if self._sample_rate_hz else _DEFAULT_STEP_MS
        )
        self._step_ms = step
        self._shift_box.setSingleStep(step)
        self._shift_box.setDecimals(4 if step < 0.01 else 3)

    def samples(self, ms: float):
        """`ms` in whole samples at the DSP's rate, or None when the rate is not on record."""
        if not self._sample_rate_hz:
            return None
        return int(round(ms * self._sample_rate_hz / 1000.0))

    def set_delay_target(self, index: int) -> None:
        """Choose WHICH DRIVER you are editing. It does not move anything by itself.

        Each driver keeps its own delay, so switching shows that driver's number in the box and
        leaves the other curve exactly where it was. The previous behaviour carried the amount
        across, which turned one 1.2 ms reading into two curves 2.4 ms apart the moment the radio
        moved (user, with the picture, 2026-08-12).
        """
        self._shift_target = min(max(int(index), 0), max(len(self._delays) - 1, 0))
        for i, button in enumerate(self._target_buttons):
            blocked = button.blockSignals(True)
            button.setChecked(i == self._shift_target)
            button.blockSignals(blocked)
        box = getattr(self, "_shift_box", None)
        if box is not None:
            blocked = box.blockSignals(True)
            box.setValue(self._shift_ms)
            box.blockSignals(blocked)
        self._render_readout()
        self.delayChanged.emit()

    def delay_target(self) -> int:
        return self._shift_target

    def _shifted(self, index: int, trace: "Trace"):
        """`(x, y)` for trace `index` with the current delay applied, in the plot's own units."""
        x = np.asarray(trace.x, dtype=float)
        y = np.asarray(trace.y, dtype=float)
        delay = self._delays[index] if index < len(self._delays) else 0.0
        if not delay:
            return x, y
        if self._unit == "ms":
            return x + delay, y
        if self._y_unit == "°":
            # Degrees per hertz for this delay, then wrapped back into ±180 so the curve stays on
            # the axis it is drawn on rather than walking off it.
            shifted = y - 360.0 * x * (delay / 1000.0)
            return x, (shifted + 180.0) % 360.0 - 180.0
        return x, y  # a magnitude response does not move when you delay it

    def _arrival_of(self, index: int):
        """Where trace `index` arrives as CAPTURED, by its largest peak. Only meaningful on an
        impulse; on an FR or a phase plot the x axis is not time and there is no arrival."""
        if self._unit != "ms" or index >= len(self._traces):
            return None
        trace = self._traces[index]
        y = np.asarray(trace.y, dtype=float)
        if not y.size:
            return None
        return float(np.asarray(trace.x, dtype=float)[int(np.abs(y).argmax())])

    def _default_delay_target(self, traces) -> int:
        """The trace that ARRIVES FIRST, of however many there are.

        It is the only one a DSP can hold back: every other driver is already at whatever delay it
        has, and there is no negative to give it. Over a whole side or a whole car that is the same
        rule as over a pair — the earliest arrival is the one everything else is waiting for.
        """
        if len(traces) < 2 or self._unit != "ms":
            return 0
        peaks = []
        for trace in traces:
            y = np.asarray(trace.y, dtype=float)
            if not y.size:
                return 0
            peaks.append(float(np.asarray(trace.x, dtype=float)[int(np.abs(y).argmax())]))
        return int(np.argmin(peaks))

    def set_traces(self, traces: Sequence[Trace]) -> None:
        """Draw these curves — two of them, or a whole side, or everything the car has.

        The count is not fixed anywhere below this line: one delay per trace, one radio per trace,
        one colour per trace. The pair was never the unit of alignment (see `_delays`); it was only
        the unit the window happened to be built for.
        """
        self._plot.clear()
        # `addLegend` returns the same item across clears, so its rows have to go too or the
        # names stack up one pass at a time.
        if self._legend is not None:
            self._legend.clear()
        first_time = [t.name for t in self._traces] != [t.name for t in traces]
        self._traces = list(traces)
        self._ensure_target_buttons(len(self._traces))
        if first_time:
            # A new selection is a new question: every delay goes back to zero, the radio points at
            # whichever of these arrives first, and the cross modes go back to comparing the first
            # two — the pair chosen out of the last selection was about drivers that may not even
            # be on screen now.
            self._delays = [0.0] * max(len(self._traces), 2)
            self._channel_delays = [None] * max(len(self._traces), 2)
            self._cross_indices = (0, 1)
            self._shift_target = self._default_delay_target(self._traces)
            box = getattr(self, "_shift_box", None)
            if box is not None:
                blocked = box.blockSignals(True)
                box.setValue(0.0)
                box.blockSignals(blocked)
            for i, button in enumerate(getattr(self, "_target_buttons", [])):
                blocked = button.blockSignals(True)
                button.setChecked(i == self._shift_target)
                button.blockSignals(blocked)
        for index, button in enumerate(getattr(self, "_target_buttons", [])):
            # The radios are named after the curves they hold back, and coloured like them. Beyond
            # a pair the version and method suffix come off the label: seven radios reading
            # "w-L_02" do not fit the row, and the legend above already prints the whole name.
            if index < len(self._traces):
                name = self._traces[index].name.split(" ")[0]
                button.setText(name.rpartition("_")[0] if len(self._traces) > 2 else name)
                button.setVisible(True)
                button.setStyleSheet(f"color: {colour_of(trace_token(index)).name()}")
            else:
                button.setVisible(False)
        for index, trace in enumerate(self._traces):
            # Arrays, not Python lists: pyqtgraph converts a list element by element, and a list
            # comprehension over 262 144 floats had already been paid for upstream.
            x, y = self._shifted(index, trace)
            label = trace.name
            delay = self._delays[index] if index < len(self._delays) else 0.0
            if delay:
                label = f"{trace.name}  {delay:+.3f} ms"
            self._plot.plot(
                x, y, pen=pg.mkPen(colour_of(trace_token(index)), width=1.0), name=label
            )
        for line in self._markers:
            self._plot.addItem(line)
        self._sync_cross_combos()
        self._render_crossings()
        # Every delay change comes back through here (`set_delay` re-sets the same traces), which
        # is what makes the sum follow the delays without another fetch from REW.
        self._render_sum()
        self._render_readout()

    # ---- the predicted sum (CURVE-ANALYSIS-PLAN.md, step 2) --------------

    def set_sum_shown(self, on: bool) -> None:
        """Draw the predicted sum of the curves on screen, or take it off again.

        Kept on the view and never reset by `set_traces` or by the window's `reset()`: a tuner
        who has asked to see joints is working through a whole car, and having to ask again for
        each pair is how a feature stops being used.
        """
        self._sum_on = bool(on)
        button = getattr(self, "_sum_btn", None)
        if button is not None and button.isChecked() != self._sum_on:
            blocked = button.blockSignals(True)
            button.setChecked(self._sum_on)
            button.blockSignals(blocked)
        self._render_sum()
        self._render_readout()

    def sum_shown(self) -> bool:
        return self._sum_on

    def sum_result(self) -> Optional[curve_sum.SumResult]:
        """What was last computed, or None when nothing could be — the caller can ask why."""
        return self._sum_result

    def sum_text(self) -> str:
        """What stands under the plot: what was summed, and what that sum does not show."""
        return self._sum_text

    def _on_strip(self) -> bool:
        """Whether the sum belongs in its own strip rather than on the right-hand axis.

        The impulse's x is TIME and the sum's is frequency, so those two cannot share one pair of
        axes — the strip under the plot is the answer, and it is under the plot rather than on
        another view because the delay is DRAGGED here: the tuner should watch the joint fill in
        while dragging (user, 2026-08-18).
        """
        return self._unit == "ms"

    def _sum_possible(self) -> bool:
        """Whether this view has somewhere to draw a sum at all.

        Every view has one now. What can still say no is pyqtgraph: both drawing surfaces are built
        by reaching into somebody else's internals, and a version that moved them leaves the
        feature switched off rather than taking the window down (`_build_sum_axis` and
        `_build_strip` both end in the same `except`).

        Deliberately does not BUILD either surface to find out — this is asked on every redraw and
        every retranslate, and the answer must not have a side effect.
        """
        return not (self._strip_failed if self._on_strip() else self._sum_axis_failed)

    def _sum_inputs(self) -> list[curve_sum.SumInput]:
        """Every plotted trace as the engine's own input, at the delay currently on screen.

        The delay comes from `self._delays`, the same list `_shifted` draws with, so the curve and
        the sum can never disagree about how far a driver has been held back. Gain and polarity are
        fixed at "as measured": there is no control for either yet, and a silent normalisation
        would make a sum of drivers at different calibrations look like a sum of one car.
        """
        inputs: list[curve_sum.SumInput] = []
        for index, trace in enumerate(self._traces):
            if trace.magnitude_db is None:
                return []
            # `x` is the frequency axis on the two views that plot against hertz, and TIME on the
            # impulse — where the strip under the plot needs the frequency axis the capture also
            # carries. `Trace.freqs_hz` is that axis, and `None` means x already is it.
            freqs = trace.freqs_hz if trace.freqs_hz is not None else trace.x
            inputs.append(
                curve_sum.SumInput(
                    name=trace.name,
                    freqs_hz=np.asarray(freqs, dtype=float),
                    magnitude_db=np.asarray(trace.magnitude_db, dtype=float),
                    phase_deg=(
                        None if trace.phase_deg is None
                        else np.asarray(trace.phase_deg, dtype=float)
                    ),
                    delay_ms=self._delays[index] if index < len(self._delays) else 0.0,
                    start_time_s=trace.start_time_s,
                    config_version=trace.config_version,
                    method=trace.method,
                )
            )
        return inputs

    def _render_sum(self) -> None:
        """Recompute the sum, draw it, and say in words what it is and is not.

        The two halves are deliberately not conditional on each other: whenever the sum is on,
        SOMETHING is said under the plot — the verdict when there is a curve, the reason when
        there is not. A sum that quietly fails to appear is the one outcome this must not have.
        """
        self._sum_result = None
        self._sum_text = ""
        self._sum_doubted = False
        self._clear_sum_curve()
        self._update_sum_button()
        if not self._sum_on:
            self._plot.getPlotItem().hideAxis("right")
            self._show_strip(False)
            self._sum_note_btn.setVisible(False)
            return

        self._sum_text, self._sum_doubted = self._compute_sum()
        drawn = self._sum_result is not None and self._draw_sum(self._sum_result)
        if self._sum_result is not None and not drawn:
            # Computed, and still nothing to put on screen: every point of it is an exact
            # cancellation, which only ever happens to synthetic data. Better said out loud than
            # left as a heading over an empty axis.
            self._sum_text = f"{i18n.t('curveSumNone')} {self._sum_text}"
            self._sum_doubted = True
        # Whichever surface this view draws on appears with the curve and leaves with it: an axis
        # over an empty ViewBox is a scale for nothing, and an empty strip under the impulse is a
        # band of window spent saying the same.
        on_strip = self._on_strip()
        self._plot.getPlotItem().showAxis("right", bool(drawn) and not on_strip)
        self._show_strip(bool(drawn) and on_strip)
        self._render_sum_note()

    def _compute_sum(self) -> tuple[str, bool]:
        """`(what to print, is it doubtful)`, computing the sum on the way if there is one."""
        if not self._sum_possible():
            # Only reachable when pyqtgraph refused to give this view a surface to draw on. Not
            # about the measurements, so it is stated rather than doubted.
            return f"{i18n.t('curveSumNone')} {i18n.t('curveSumNoPlot')}", False
        if len(self._traces) < 2:
            return f"{i18n.t('curveSumNone')} {i18n.t('curveSumTooFew')}", True
        inputs = self._sum_inputs()
        if not inputs:
            return f"{i18n.t('curveSumNone')} {i18n.t('curveSumNoData')}", True

        verdict = curve_sum.summability(inputs)
        if verdict.refused:
            # The engine's own sentence, verbatim: it already names the measurement that cannot be
            # summed and why, and a paraphrase here would be a second, quietly diverging rule.
            return f"{i18n.t('curveSumNone')} {verdict.text}", True
        try:
            result = curve_sum.sum_responses(inputs)
        except curve_sum.CurveSumError as exc:
            return f"{i18n.t('curveSumNone')} {exc}", True
        self._sum_result = result
        lines = [f"{i18n.t('curveSumHead')} {' + '.join(result.names)}"]
        where_hz, depth_db = result.deepest_null()
        if np.isfinite(where_hz) and np.isfinite(depth_db):
            lines.append(
                i18n.t("curveSumWorst").format(depth=f"{depth_db:+.1f}", hz=f"{where_hz:.0f}")
            )
        # Both of these come out of `curve_sum` in English and stay that way — they go into a
        # model's prompt at least as often as onto this screen, and which language TCC speaks to a
        # model in is one open decision, not one to settle here by accident.
        lines.append(result.summability.text)
        lines.append(result.assumption)
        return "\n".join(lines), not result.summability.ok

    def _draw_sum(self, result: curve_sum.SumResult) -> bool:
        """Draw the sum where this view keeps it: its own strip, or the right-hand dB axis."""
        values = np.asarray(result.magnitude_db, dtype=float)
        finite = values[np.isfinite(values)]
        if not finite.size:
            return False
        # An exact null is −inf out of the engine, by design. Floored HERE, where the drawing
        # happens, and floored relative to the sum's own loudest point so the number under the plot
        # stays the honest one.
        values = np.where(np.isneginf(values), float(finite.max()) - _SUM_FLOOR_DB, values)
        freqs = np.asarray(result.freqs_hz, dtype=float)
        if self._on_strip():
            return self._draw_sum_on_strip(freqs, values)
        return self._draw_sum_on_axis(freqs, values)

    def _draw_sum_on_axis(self, freqs, values) -> bool:
        """The frequency views: over the measurements, on the second ViewBox's dB scale."""
        if not self._ensure_sum_axis():
            return False
        # log10 by hand: pyqtgraph's log mode transforms the items IT owns, and this curve lives on
        # a ViewBox of ours. The X ranges are linked, so both must be in the same coordinates.
        x = np.log10(freqs) if self._log_x else freqs
        self._sum_curve = pg.PlotCurveItem(
            x, values,
            pen=pg.mkPen(self._sum_colour(), width=_SUM_WIDTH, style=Qt.PenStyle.DashLine),
            # Outside the band every measurement covers, the sum is NaN rather than a guess. Left
            # as a gap: a line drawn straight across it would be the one part of this curve that
            # no measurement stands behind.
            connect="finite",
        )
        self._sum_curve.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._sum_vb.addItem(self._sum_curve)
        low, high = float(np.nanmin(values)), float(np.nanmax(values))
        pad = max((high - low) * 0.08, 1.0)
        self._sum_vb.setYRange(low - pad, high + pad, padding=0)
        self._resize_sum_axis()
        return True

    def _draw_sum_on_strip(self, freqs, values) -> bool:
        """The impulse: in the strip below the plot, which has a frequency axis of its own.

        Raw hertz, not log10: this curve is owned by the strip's own `PlotItem`, so pyqtgraph's log
        mode transforms it — which is the whole reason it is a `PlotDataItem` here and a
        `PlotCurveItem` on the second ViewBox above, where nothing would.
        """
        if not self._ensure_strip():
            return False
        self._strip_curve = self._strip.plot(
            freqs, values,
            pen=pg.mkPen(self._sum_colour(), width=_SUM_WIDTH, style=Qt.PenStyle.DashLine),
            connect="finite",
        )
        self._strip_curve.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        low, high = float(np.nanmin(values)), float(np.nanmax(values))
        pad = max((high - low) * 0.08, 1.0)
        self._strip.setYRange(low - pad, high + pad, padding=0)
        return True

    def _clear_sum_curve(self) -> None:
        if self._sum_curve is not None and self._sum_vb is not None:
            self._sum_vb.removeItem(self._sum_curve)
        self._sum_curve = None
        if self._strip_curve is not None and self._strip is not None:
            self._strip.removeItem(self._strip_curve)
        self._strip_curve = None

    # ---- the sum's own strip, under the impulse (user, 2026-08-18) -------

    def _ensure_strip(self) -> bool:
        """Build the strip the first time a sum is actually drawn on an impulse, and only then.

        Same bargain as `_ensure_sum_axis`, and a bigger one: this is a whole second `PlotWidget`,
        and the crash this file documents at length is about how many `PlotItem`s get constructed
        and destroyed. A window that never puts a sum on an impulse carries exactly the graphics
        items it carried before this feature existed. One attempt, then the answer is remembered
        either way.
        """
        if self._strip is None and not self._strip_failed:
            self._build_strip()
        return self._strip is not None

    def _build_strip(self) -> None:
        """A short second plot under the impulse: x in hertz, y in dB, the sum and nothing else.

        Not a second Y axis on the impulse (user, 2026-08-18): the impulse's x is TIME and the
        sum's is FREQUENCY, so there is no pair of axes they can share. It goes under the plot
        rather than on another view because the delay is dragged HERE, and the point of the whole
        feature is watching the joint fill in while it is dragged.

        **Ownership, because this file has been bitten by it.** The widget is a child of this one,
        in this one's layout, destroyed with it by Qt, in order. `enableMenu=False` at construction
        for the reason spelled out at `self._plot`: `ViewBox.__init__` builds a whole `ViewBoxMenu`
        otherwise, and constructing and dropping enough of those segfaults the process from inside
        its own `__init__`. `_adopt_orphan_menus` then takes ownership of the parentless "Plot
        Options" menu `PlotItem` builds whatever anyone says.

        Guarded end to end: a pyqtgraph that moved these internals leaves the impulse without a
        strip, not the window without a curve.
        """
        try:
            theme = current_theme()
            strip = pg.PlotWidget(background=theme.panel, enableMenu=False)
            strip.setMenuEnabled(False)
            strip.getPlotItem().hideButtons()
            strip.setFixedHeight(_STRIP_HEIGHT_PX)
            strip.setLogMode(x=True, y=False)
            axis = LogHzAxis(orientation="bottom")
            axis.setPen(pg.mkPen(theme.border2))
            axis.setTextPen(pg.mkPen(theme.muted))
            strip.setAxisItems({"bottom": axis})
            strip.getAxis("left").setPen(pg.mkPen(theme.border2))
            # The left axis wears the sum's own colour, the same pairing of scale with curve the
            # right-hand axis uses on the frequency views.
            strip.getAxis("left").setTextPen(pg.mkPen(self._sum_colour()))
            strip.showGrid(x=True, y=True, alpha=0.18)
            self._adopt_orphan_menus(strip)
            # Directly under the plot and above the two note buttons: the verdict for what is in
            # the strip should read below it, not above the plot it is not about.
            self._layout.insertWidget(1, strip)
            strip.setVisible(False)
            self._strip = strip
        except Exception:  # noqa: BLE001 — pyqtgraph moved; the strip is off, not the window
            self._strip = None
            self._strip_failed = True

    def _show_strip(self, on: bool) -> None:
        """Put the strip on screen, or take it off. Never builds one to hide it."""
        if self._strip is not None:
            self._strip.setVisible(bool(on))

    def strip_shown(self) -> bool:
        """Whether the sum's own strip is on screen: the impulse, Σ on, and a sum to draw."""
        return self._strip is not None and self._strip.isVisibleTo(self)

    def _render_sum_note(self) -> None:
        """The sum's verdict as a button that names it, with the whole of it in the tip.

        The colour is on the BUTTON and not only in the text: the reason the paragraph was
        replaced is that nobody was reading it, so a sum nobody may believe has to be visible
        without being read (user, 2026-08-18). Normal when the set is summable, the warning colour
        when it is not.
        """
        button = self._sum_note_btn
        button.setVisible(bool(self._sum_text))
        if getattr(button, "hover_tip", None) is not None:
            button.hover_tip.set_text(
                tip_html(self._sum_text, head=i18n.t("curveSumNoteBtn"), warn=self._sum_doubted)
            )
        theme = current_theme()
        # Empty puts it back on `.clear-btn`'s own colours: a per-widget sheet is merged over the
        # class rule, so clearing it is how "normal" is said.
        warn = f"color: {theme.warn}; border-color: {theme.warn};"
        _restyle(button, warn if self._sum_doubted else "")

    def _update_sum_button(self) -> None:
        """Show the Σ toggle where it applies, and say ON it whether the sum is on.

        Not on the frequency response at all — see `_sum_offered`. On the impulse it is now a live
        control rather than a marked-shut one: the strip it used to promise is under the plot.

        The checked state is coloured here rather than in the stylesheet, which has no `:checked`
        rule for `.zoom-btn`. A toggle floating over the data whose state cannot be read is worse
        than one in a row of controls: there is nothing beside it to compare it with.
        """
        button = getattr(self, "_sum_btn", None)
        if button is None:
            return
        button.setVisible(self._sum_offered())
        possible = self._sum_possible()
        button.setEnabled(possible)
        theme = current_theme()
        _restyle(
            button, f"color: {theme.accent}; border-color: {theme.accent};" if self._sum_on else ""
        )
        if getattr(button, "hover_tip", None) is not None:
            button.hover_tip.set_text(
                tip_html(i18n.t("curveSumTip") if possible else i18n.t("curveSumNoPlot"))
            )

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
        for index, position in enumerate(positions):
            if index < len(tokens):
                token = tokens[index]
            else:
                token = _MODEL_TOKEN if index == 0 else _ARBITER_TOKEN
            colour = colour_of(token)
            line = pg.InfiniteLine(
                pos=self._to_view(float(position)), angle=90, movable=True,
                # Thicker than the traces, deliberately. A guide the same weight as a dense
                # impulse disappears into it — on the frequency response, where the trace is
                # sparser, the same line read clearly, which is what made the difference visible
                # (user, 2026-08-12). It is furniture over the data, not another curve.
                pen=pg.mkPen(colour, width=_GUIDE_WIDTH,
                             style=Qt.PenStyle.DashLine if index == 0 and not tokens
                             else Qt.PenStyle.SolidLine),
                label=self._marker_names[index] if index < len(self._marker_names) else "",
                # Staggered heights: the two markers START on top of each other (that is the
                # point — the Arbiter drags away from the model's reading), and labels printed at
                # the same height would overlap into one unreadable word until they separate.
                labelOpts={"color": colour, "position": 0.94 - 0.07 * index},
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
        self._style_sum_axis()
        if self._strip is not None:
            self._strip.setBackground(theme.panel)
            for axis_name in ("bottom", "left"):
                self._strip.getAxis(axis_name).setPen(pg.mkPen(theme.border2))
            self._strip.getAxis("bottom").setTextPen(pg.mkPen(theme.muted))
            self._strip.getAxis("left").setTextPen(pg.mkPen(self._sum_colour()))
        # Traces and markers are rebuilt rather than recoloured in place: both already know how to
        # draw themselves from the current theme, and two ways of doing it is one too many.
        traces, positions = list(self._traces), self.positions()
        names, tokens = list(self._marker_names), list(self._marker_tokens)
        if traces:
            self.set_traces(traces)
        self._render_crossings()
        self._render_sum()
        # The two note buttons carry their state as a colour written from the palette that was
        # current when it was written — the same reason the plot's pens are rebuilt above.
        self._render_readout()
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
        # The sum lives on a ViewBox pyqtgraph's log mode does not reach, so its x coordinates are
        # computed against this flag — which has just changed.
        self._render_sum()

    def _to_view(self, x: float) -> float:
        return math.log10(x) if self._log_x and x > 0 else float(x)

    def _from_view(self, x: float) -> float:
        return 10.0 ** x if self._log_x else float(x)

    def set_unit(self, unit: str) -> None:
        """What the marker positions are IN. Wrong units in a reading are worse than no reading."""
        self._unit = unit
        # It also decides whether a sum can be drawn here at all: milliseconds means the x axis is
        # time, and a sum stated against frequency has no place on it.
        self._render_sum()
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
        # It is also what tells the phase from the frequency response, and the Σ toggle is offered
        # on one and not the other (`_sum_offered`). Only the button is touched: nothing about the
        # sum itself has changed, and recomputing it here would do the work twice per kind switch.
        self._update_sum_button()
        self._render_readout()

    def set_axes_mode(self, mode: str) -> None:
        """`v` reads frequencies, `h` reads levels, `vh` reads both.

        The same markers either way — a horizontal line is added beside each vertical one rather
        than replacing it, so switching to VH does not lose a position already placed.
        """
        self._axes_mode = mode if mode in _MODE_LABELS else "v"
        for button, value in self._axes_buttons:
            button.setChecked(value == self._axes_mode)
        # The pair pickers belong to the cross modes and appear with them.
        self._sync_cross_combos()
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
            # One horizontal line, placed at whatever the first of the two CHOSEN curves is doing
            # where the vertical marker last stood -- a level somewhere on the data rather than at
            # zero.
            theme = current_theme()
            first = self.cross_pair()[0]
            level = self._y_at(first, self.positions()[0]) if self.positions() else 0.0
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
                pen=pg.mkPen(colour_of(token), width=_GUIDE_WIDTH,
                             style=Qt.PenStyle.DotLine),
            )
            line.sigPositionChanged.connect(self._on_marker_moved)
            self._plot.addItem(line)
            self._h_markers.append(line)

    # ---- which two curves a cross mode is about --------------------------

    def cross_pair(self) -> tuple[int, int]:
        """The two traces `vx`/`hx` read, as indices. Defaults to the first two on screen.

        **The cross modes stay pairwise however many curves are plotted, on purpose.** They exist
        to answer one shaped question — "at this x, how far apart are these two" — and the answer
        is a single Δ. Over six drivers there is no such number: fifteen pairwise gaps are not a
        reading, and picking one of them silently would be the window choosing which comparison the
        Arbiter meant. So the tuner names the two, and the per-curve markers (`v`, `h`, `vh`) keep
        answering for the rest, one number each, which is a shape that DOES generalise.
        (`vhs` needs no pair either: it ties each marker to its own curve and compares nothing.)
        """
        pair = getattr(self, "_cross_indices", (0, 1))
        count = len(self._traces)
        if count < 2:
            return (0, min(1, max(count - 1, 0)))
        first = pair[0] if 0 <= pair[0] < count else 0
        second = pair[1] if 0 <= pair[1] < count else 1
        if first == second:
            second = 1 if first == 0 else 0
        return (first, second)

    def set_cross_pair(self, first: int, second: int) -> None:
        """Read the cross modes against these two traces."""
        self._cross_indices = (int(first), int(second))
        self._sync_cross_combos()
        self._rebuild_h_markers()
        self._render_crossings()
        self._render_readout()

    def _sync_cross_combos(self) -> None:
        """Offer the choice of pair only where there is one to make.

        With two traces the pair IS the selection and a control for it would be furniture; outside
        a cross mode there is no pairwise question on screen at all. So both combos appear together
        with the first Vx or Hx over a third curve, and go away again with it.
        """
        combos = getattr(self, "_cross_combos", [])
        if not combos:
            return
        wanted = len(self._traces) > 2 and self._axes_mode in _CROSS_MODES
        pair = self.cross_pair()
        for slot, combo in enumerate(combos):
            blocked = combo.blockSignals(True)
            combo.clear()
            for index, trace in enumerate(self._traces):
                combo.addItem(trace.name.split(" ")[0], index)
            at = combo.findData(pair[slot])
            combo.setCurrentIndex(at if at >= 0 else slot)
            combo.blockSignals(blocked)
            combo.setVisible(wanted)
        self._cross_label.setVisible(wanted)

    def _on_cross_combo(self, slot: int) -> None:
        combos = getattr(self, "_cross_combos", [])
        if len(combos) < 2 or not self._traces:
            return
        chosen = [combos[0].currentData(), combos[1].currentData()]
        if chosen[slot] is None:
            return
        other = 1 - slot
        if chosen[other] == chosen[slot] or chosen[other] is None:
            # A curve compared with itself reads "Δ 0.0" and means nothing. The slot the tuner did
            # not touch is the one that moves.
            chosen[other] = next(
                (i for i in range(len(self._traces)) if i != chosen[slot]), chosen[slot]
            )
        self.set_cross_pair(int(chosen[0]), int(chosen[1]))

    def _render_crossings(self) -> None:
        """Dots where the single line meets each curve. Nothing to draw outside the cross modes."""
        if self._crossing_dots is not None:
            self._plot.removeItem(self._crossing_dots)
            self._crossing_dots = None
        if self._axes_mode not in _CROSS_MODES or not self._traces:
            return
        theme = current_theme()
        spots = []
        for slot, (x, y) in enumerate(self.crossings()):
            # The dot wears the colour of the CURVE it sits on, not of a marker: with more than two
            # traces on screen the reader's first question about a dot is which driver it belongs
            # to.
            index = self.cross_pair()[slot] if slot < 2 else slot
            spots.append({
                "pos": (self._to_view(x), y), "size": 9,
                "brush": pg.mkBrush(colour_of(trace_token(index))),
                "pen": pg.mkPen(theme.panel, width=1.5),
            })
        if spots:
            self._crossing_dots = pg.ScatterPlotItem(spots)
            self._plot.addItem(self._crossing_dots)

    def crossings(self) -> list[tuple[float, float]]:
        """Where the single line meets the two CHOSEN curves, as (x, y) in the axes' own units.

        `vx` is exact: a vertical line has one y per curve. `hx` is a choice — a level line can
        cross a response many times — and the choice is the crossing nearest the middle of what is
        currently on screen, because that is the one being pointed at. Zooming to the region of
        interest is therefore part of asking the question, which is honest about the ambiguity
        rather than hiding it behind a rule nobody can see.

        Two, never N: see `cross_pair` for why that is the honest shape of this question.
        """
        # Deduplicated: with a single curve on screen both halves of the pair are trace 0, and
        # reporting it twice would print a Δ of zero between a curve and itself.
        pair: list[int] = []
        for index in self.cross_pair():
            if index < len(self._traces) and index not in pair:
                pair.append(index)
        if self._axes_mode == "vx":
            if not self._markers:
                return []
            x = self.positions()[0]
            return [(x, self._y_at(i, x)) for i in pair]
        if self._axes_mode == "hx":
            if not self._h_markers:
                return []
            level = float(self._h_markers[0].value())
            (low, high), _ = self._plot.getViewBox().viewRange()
            centre = self._from_view((low + high) / 2.0)
            out = []
            for index in pair:
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
        if not self._markers and not any(self._delays):
            return ""
        names = [t.name for t in self._traces] or [""]
        digits = 3 if self._unit == "ms" else 1
        if self._markers and self._axes_mode in _CROSS_MODES:
            return self._cross_reading(digits)
        lines = []
        if self._markers and "v" in self._axes_mode:
            lines.append(self._axis_reading(self.positions(), self._unit, digits))
        if self._markers and "h" in self._axes_mode:
            lines.append(self._axis_reading(self.levels(), self._y_unit or "", 1))
        parts = [part for part in lines if part]
        proposals = []
        for index, trace in enumerate(self._traces):
            # EVERY driver that carries a proposal, not only the selected one. Alignment is what
            # the whole set says together, and a sentence naming one of two delayed curves would
            # describe a picture nobody is looking at.
            delay = self._delays[index] if index < len(self._delays) else 0.0
            if not delay:
                continue
            # In ms AND samples, because that is the skill's own rule for every delay it states,
            # and signed, because an unsigned "0.150 ms" beside a channel already at 1.2 ms is two
            # different instructions depending on a sign the reader cannot see.
            samples = self.samples(delay)
            clause = f"{trace.name} {delay:+.3f} {i18n.t('unitMs')}"
            if samples is not None:
                clause += f" ({samples:+d} {i18n.t('unitSmp')})"
            arrival = self._arrival_of(index)
            if arrival is not None:
                # Where it LANDS, not only how far it moves. Without this the sentence reads as a
                # contradiction whenever the pair on screen is not what the driver is being
                # aligned to: markers 1.191 ms apart, proposal +1.890 ms, and nothing saying that
                # the reference is a third curve (user, with the message, 2026-08-12).
                clause += ", " + i18n.t("curveDelayLands").format(
                    was=f"{arrival:.3f}", now=f"{arrival + delay:.3f}")
            total = self.total_delay_ms(index)
            if total is not None:
                clause += ", " + i18n.t("curveDelayTotal").format(total=f"{total:.3f}")
                if total < 0:
                    # Stated, not prevented. The Arbiter decides; the panel's job is to make sure
                    # the impossible one is never proposed by accident (user, 2026-08-12: "головне
                    # щоб загалом не йшло менш нуля").
                    clause += " " + i18n.t("curveDelayBelowZero")
            proposals.append(clause)
        if proposals:
            # The caveat once, at the head, not once per driver. It is a property of the whole
            # statement — the panel changes nothing; this goes to the composer, the Arbiter sends
            # it, and the delta is banked 🟡 like every other proposed change. Repeating it on
            # each driver was most of the sentence by the second one (user's screenshot).
            parts.append(i18n.t("curveDelayHead") + " " + "; ".join(proposals))
        if not parts:
            return ""
        # One line. It has a full-width row of its own now, which is room enough — the wrapping is
        # there for a narrow window, not as the normal shape (user, 2026-08-11).
        body = "; ".join(parts)
        # ...and the header is dropped when the markers are already named after their curves,
        # which is the ordinary case: "tw-L / tw-R — tw-L: …, tw-R: …" says each name twice for
        # no reader's benefit.
        if not self._markers or list(names) == list(self._marker_names):
            return body
        return f"{' / '.join(names)} — {body}"

    def statement(self) -> str:
        """Everything this panel is saying — the markers' reading, and the sum when it is shown.

        This, not `reading()`, is what leaves the window. A delay proposal and the joint it
        predicts are one statement: sending the first without the second would ask the model about
        an alignment while withholding the picture it was read off. `reading()` stays what it was,
        because the readout under the plot is about the markers and the sum has its own line.

        The sum arrives with its verdict and its timing assumption attached — `as_sentence()` puts
        them there — so nothing downstream has to remember to add the caveat, which is exactly the
        kind of remembering that eventually does not happen.
        """
        parts = [self.reading()]
        if self._sum_on and self._sum_text:
            parts.append(
                f"{i18n.t('curveSumHead')}\n{self._sum_result.as_sentence()}"
                if self._sum_result is not None else self._sum_text
            )
        return "\n".join(part for part in parts if part)

    def _cross_reading(self, digits: int) -> str:
        """One line, both curves. "At 2.5 kHz the channels are 6 dB apart" is a single fact about
        a pair, and it is the reason these modes exist — the per-curve markers cannot state it,
        because there the two markers are in different places.

        Which two, when more than two are plotted, is `cross_pair()` — and the names printed here
        come from it, so the sentence that leaves the window says which drivers were compared
        rather than leaving the reader to assume the first two.
        """
        crossings = self.crossings()
        if not crossings:
            return ""
        names = [
            self._traces[index].name
            for index in self.cross_pair() if index < len(self._traces)
        ]
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
        totals = [self.total_delay_ms(i) for i in range(len(self._traces) or 1)]
        # The one reading in this panel that is not merely a number but a claim the hardware will
        # reject. It colours the BUTTON, not a word inside the sentence: a warning inside a
        # sentence made of numbers is read last, and this sentence is now behind a hover.
        impossible = any(total is not None and total < 0 for total in totals)
        if getattr(self._readout_btn, "hover_tip", None) is not None:
            self._readout_btn.hover_tip.set_text(tip_html(
                text or i18n.t("curveNoMarkers"),
                head=i18n.t("curveReadoutBtn"), warn=impossible,
            ))
        theme = current_theme()
        _restyle(
            self._readout_btn,
            f"color: {theme.warn}; border-color: {theme.warn};" if impossible else "",
        )
        # A predicted sum on screen is worth sending on its own — it is a statement about the pair
        # whether or not a marker has been placed.
        self._send_btn.setEnabled(bool(self.statement()))

    def retranslate(self) -> None:
        self._shift_label.setText(i18n.t("curveShift"))
        for combo in getattr(self, "_cross_combos", []):
            if getattr(combo, "hover_tip", None) is not None:
                combo.hover_tip.set_text(i18n.t("curveCrossPairTip"))
        for button, mode in self._axes_buttons:
            if getattr(button, "hover_tip", None) is not None:
                button.hover_tip.set_text(i18n.t(f"curveAxes_{mode}"))
        self._send_btn.setText(i18n.t("curveSendMarkers"))
        # The two note buttons carry their own name twice: on the button and as the head of the
        # tip, so the hover says what it is answering about.
        self._sum_note_btn.setText(i18n.t("curveSumNoteBtn"))
        self._readout_btn.setText(i18n.t("curveReadoutBtn"))
        # The sum's own line is half translated framing and half `curve_sum`'s English, so it is
        # rebuilt rather than patched — see `_compute_sum`.
        self._render_sum()
        for button, key in self._zoom_buttons:
            button.setText(i18n.t(key + "Short"))
            if getattr(button, "hover_tip", None) is not None:
                button.hover_tip.set_text(i18n.t(key))
        self._render_readout()
