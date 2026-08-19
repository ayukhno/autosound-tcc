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
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import allpass as allpass_mod
from autosound_tcc.core import curve_sum
from autosound_tcc.core.allpass import Allpass, AllpassError
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.theme import current_theme, mini_combo

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
#: How strongly the grid is drawn. pyqtgraph scales this per tick level -- level 0 (the decades)
#: gets the full share and level 1 (the 2-3-4-5-6-8 ladder) half of it -- so one number gives the
#: two weights REW's axis has. At the old 0.18 that worked out to 46 and 23 of 255, which is not a
#: grid, it is a rumour (user, 2026-08-18, with REW's own axis beside ours). At this value it is
#: 166 and 83: readable across a car seat, and still behind seven traces drawn at full alpha.
_GRID_ALPHA = 1.0
#: How far the grid's colour is mixed from `muted` towards the panel it is drawn on. This is the
#: lever, not the alpha: `border2` — the app's hairline between panels, which the axes wore — is
#: 0x33404f on a 0x161b22 panel, and raising `showGrid`'s alpha from 0.18 through 0.5 and 0.65 to
#: 1.0 changed almost nothing on screen (rendered and compared at each step). Alpha modulates a
#: colour that was never far enough from the background to modulate. Mixed from `muted` instead:
#: bright enough to count decades off across a car seat, dark enough to stay behind a trace drawn
#: at full strength, and it lands correctly in both palettes because it is a mix of two tokens.
_GRID_MIX = 70
#: Guides are drawn heavier than the traces they cross. At trace weight they vanish into a dense
#: impulse — 262 144 points is a solid block of pixels, and a 1 px line over it is not a line.
_GUIDE_WIDTH = 2.4
#: How close two level lines may START to each other before `_h_marker_levels` gives up on putting
#: them on their own curves and spreads them out instead. A fraction of the VISIBLE height rather
#: than a number of pixels: the same 0.01 of an impulse sample is a hair on one zoom and half the
#: window on another, and what has to be readable is the gap on screen. 6% of the height is about
#: 20 px in this window — a hand's width apart at a glance, and small enough that two drivers a real
#: decibel apart on a frequency response keep the placement that says so.
_H_MARKER_MIN_GAP = 0.06
#: How much of the visible height the spread-out levels are laid across. The middle half: high
#: enough to be clear of the axis labels at the bottom, low enough that the top line is not read as
#: part of the frame.
_H_MARKER_SPREAD = 0.5
#: The predicted sum's pen. Dashed, because it is a PREDICTION standing among measurements — but
#: readable, which the first attempt was not: `text` at alpha 150 and 1.2 px came out as a thin
#: grey dash nobody could follow across the plot (user, 2026-08-18, with the screenshot). Yellow
#: is the one bright token left over: `accent` and `info` are the two traces, `muted` and `ok` are
#: the markers, and `warn`/`ok` carry a verdict in this palette — "wrong" and "fine" — which a
#: prediction is neither of. Near-full alpha rather than full, so the dash still sits a step
#: behind the measured curves it was computed from.
#: One width for the sum wherever it is drawn — the strip and the right-hand axis both take it
#: from here, so the prediction never reads as two different things in two views. 3.0 rather than
#: the first 2.2 because the strip put the drivers' own curves beside it: among four thin lines a
#: dash only slightly heavier than the rest is just another line (user, 2026-08-18, second look:
#: "на АЧХ все супер, тільки зроби суму жирніше").
_SUM_TOKEN = "yellow"
_SUM_ALPHA = 235
_SUM_WIDTH = 3.0
#: The drivers' own magnitudes in the strip, under the sum. Thin and a little translucent on
#: purpose: they are there to be COMPARED with the sum — "is the joint filling in, and by how much
#: over the drivers that make it" — and at the sum's weight four of them would bury the one curve
#: the strip exists for. Each keeps its own trace colour, so the strip and the plot above name the
#: same driver the same way.
_STRIP_TRACE_WIDTH = 1.0
_STRIP_TRACE_ALPHA = 165
#: How far under its own loudest point the drawn sum is allowed to fall. `curve_sum` returns −inf
#: at an exact null and says in as many words that the floor is the DRAWING's decision — without
#: one, a synthetic cancellation takes the whole right-hand axis to −inf and the curve with it.
_SUM_FLOOR_DB = 60.0
#: Fallback delay step, in ms, when no profile has been read. What DSPs seen so far let you TYPE;
#: the hardware resolves in whole samples, which is a different number — see `set_resolution`.
_DEFAULT_STEP_MS = 0.01
#: Where the all-pass's `f0` box opens. A number the tuner will type over, so only its ORDER OF
#: MAGNITUDE matters: a woofer↔mid joint, the one an all-pass is most often dialled on. Kept from one
#: driver to the next within a window rather than reset, because the joint being worked on is the
#: same joint from either side of it.
_DEFAULT_APF_F0_HZ = 250.0
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
#: What the readout prints where a trace never reaches the level being read. An em dash rather
#: than a blank: a blank cell reads as a number somebody forgot to fill in, and "this curve never
#: gets there" is an answer to the question that was asked.
_NO_CROSSING = "—"
#: How the plot and the sum's strip share the height. A THIRD to the strip by default — short,
#: because the plot above is what is being worked in (the delay is dragged there) — but the
#: boundary is a splitter handle the tuner drags (user, 2026-08-18: "треба щоб можна було кордон
#: між верхнім і нижнім вікном двигати"), so this is only where it starts. The two minimums are
#: what `setChildrenCollapsible(False)` needs to mean anything: without them a drag to the end
#: leaves one of the two plots a few pixels tall, which is neither hidden nor usable.
_STRIP_SHARE = 0.32
_STRIP_MIN_PX = 84
#: What the strip opens on when it is NOT following the plot above — the impulse, where the plot
#: is in time, and the phase after the link has been switched off. The audible band, the same one
#: `curve_dialog` opens a frequency view on: outside it a REW sweep is measurement noise, and
#: auto-ranging over that flattens the part being argued about.
_STRIP_BAND_HZ = (20.0, 20000.0)
_PLOT_MIN_PX = 140
#: Where the share the tuner dragged to is kept. In the app's own store, beside the theme, the
#: zoom and the tree's collapse state — the same store this window's siblings already persist
#: their layout in (`app_settings`), so a curve window opened tomorrow opens the way it was left.
#: The FRACTION rather than the two pixel sizes: the window is resized between sessions and
#: between machines, and pixels restored into a different height are not the same split.
_SPLIT_KEY = "curve/sumSplitShare"
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


def _grid_colour() -> QColor:
    """The colour the axes and their grid are drawn in — see `_GRID_MIX` for why it is a mix.

    Mixed here rather than through `Theme.mix`, which answers in the CSS `rgb(r, g, b)` spelling a
    stylesheet wants and pyqtgraph refuses ("Unable to convert rgb(75, 83, 93) to QColor"). Same
    arithmetic, a QColor out: this side of the app draws with pens, not with sheets.
    """
    theme = current_theme()
    muted, panel = QColor(theme.muted), QColor(theme.panel)
    share = _GRID_MIX / 100.0
    return QColor(
        round(muted.red() * share + panel.red() * (1 - share)),
        round(muted.green() * share + panel.green() * (1 - share)),
        round(muted.blue() * share + panel.blue() * (1 - share)),
    )


def trace_colour(index: int) -> QColor:
    """The colour trace `index` is drawn in — for whatever names the same trace OUTSIDE the plot.

    One call rather than two, and it lives here because this is where the pens are made:
    `_TRACE_TOKENS` and `_TRACE_HUES` are this widget's own, and the chip row in `curve_dialog` —
    which is a legend of the selection, one chip per plotted curve — would have to hold a second
    copy of them to colour itself. Two copies of a palette drift the first time a hue moves, and a
    legend that disagrees with the plot is worse than no legend at all.
    """
    return colour_of(trace_token(index))


def _wrapped(text: str) -> str:
    """`text` escaped and broken into lines by hand — see `_TIP_WRAP_CHARS` for why by hand."""
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        wrapped = textwrap.wrap(
            paragraph, _TIP_WRAP_CHARS, break_long_words=False, break_on_hyphens=False
        )
        lines.extend(html.escape(part) for part in (wrapped or [""]))
    return "<br>".join(lines)


def _wrapped_html(text: str, colour: str = "") -> str:
    """A paragraph inside a tip that is not all paragraph — the readout's own (`_readout_html`).

    Its own block rather than a run of text, so a table above it and a sentence below it do not
    end up on the same line: Qt's rich text lays `<table>` out inline otherwise.
    """
    style = f' style="color: {colour}"' if colour else ""
    return f"<div{style}>{_wrapped(text)}</div>"


def _fmt(value: float, digits: int) -> str:
    """A number the way the reading prints one — and never "-0.0", which is a value that rounds to
    nothing wearing a sign that says it does not. Two curves a hair apart at one marker produce it
    on every second cell."""
    text = f"{value:.{digits}f}"
    return text[1:] if text.startswith("-") and float(text) == 0.0 else text


def _cell(value: str, colour: str) -> str:
    """One table cell, coloured. Right-aligned because these are numbers to be compared down a
    column, and a ragged left edge is what makes two decimals look like a different order."""
    return f'<td align="right" style="color: {colour}">{html.escape(str(value))}</td>'


@dataclass(frozen=True)
class _TableRow:
    """One marker's line in the readout: what to call it, what colour it wears, its numbers."""

    label: str
    token: str
    cells: list
    delta: bool


@dataclass(frozen=True)
class _MarkerTable:
    """One block of the reading. `head_unit` labels each row's first number (the marker's own
    position — a frequency in the vertical block, a level in the horizontal one) and `cell_unit`
    labels the rest, one per trace. Rendered twice, from here: as text for the model and as a
    table for the tuner."""

    traces: list
    head_unit: str
    cell_unit: str
    rows: list


def tip_html(text: str, head: str = "", warn: bool = False) -> str:
    """`text` as a hover tip: large, wrapped, with a bold head, warning-coloured when in doubt.

    The three paragraphs that used to stand under the plot are behind buttons now (user,
    2026-08-18: they took the space and could not be read), so the text that was a wall of small
    grey type is the same text laid out to be read — which is the whole point of moving it.

    Nothing that LEAVES the window comes through here: `statement()` and the bank's own sentence
    are built from the plain strings and are unchanged. This is drawing, only.
    """
    theme = current_theme()
    body = _wrapped(text)
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


class _NoWidgetAction:
    """Stands in for the six `QWidgetAction`s `PlotItem.__init__` parents to itself, and never
    becomes a Qt object at all.

    Every report of the TEARDOWN SIGSEGV — five collected on 2026-08-18, and it killed about one
    full-suite run in ten — ends in the same three frames: `~QGraphicsWidget` (the PlotItem) →
    `QObjectPrivate::deleteChildren` → `~QWidgetActionWrapper` → `Shiboken::Object::destroy`.
    Those actions are the only children of that kind a PlotItem has, and pyqtgraph 0.13.7 builds
    them for a menu this window never shows (`_do_not_build_the_plot_options_menu` already keeps
    them out of the menu, which is what fixed the CONSTRUCTION crash a week earlier). Not creating
    them at all removes the frame — and, measured, the crash: **0 in 40 full-suite runs**, against
    4 in 40 without it, on a still worktree.

    `setDefaultWidget` is swallowed on purpose. The real one REPARENTS the ctrl form's group boxes
    into the action, and losing that owner is exactly what broke `showGrid` / `setDownsampling` /
    `setLogMode` when this was tried on 2026-08-13; here the boxes stay where `setupUi` put them,
    on the form `_KeptCtrlForm` keeps alive.
    """

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *args, **kwargs: None


#: The ctrl forms pyqtgraph builds `self.ctrl` on, held so their group boxes — which `showGrid`,
#: `setDownsampling`, `setClipToView` and `setLogMode` all read — outlive the local that built
#: them. `PlotItem.__init__` rebinds that local two lines later, so without this they would be
#: collected the moment the actions stopped owning them. Plain parentless QWidgets with ordinary
#: children: nothing of the graphics scene is in them, which is why holding them costs nothing at
#: teardown.
_KEPT_CTRL_FORMS: list = []


class _KeptCtrlForm(QWidget):
    """The plain QWidget `PlotItem.__init__` calls `setupUi` on, kept alive by this module."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        _KEPT_CTRL_FORMS.append(self)


class _QtWidgetsWithoutSubmenus:
    """`PlotItem.py`'s view of `QtWidgets`: `QMenu`, `QWidgetAction` and `QWidget` swapped."""

    QMenu = _PlotOptionsMenu
    QWidgetAction = _NoWidgetAction
    QWidget = _KeptCtrlForm

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

    Two tick levels, because they do two different jobs. The DECADES are the frame of the picture
    and carry the heavier grid line; the 2-3-4-5-6-8 ladder between them is what lets a frequency
    be read off the grid without a label under it, which is what REW's axis does and what this one
    did not (user, 2026-08-18: "а що до сітки, має сенс її мати", with REW's axis beside it).

    **Labels are thinned; LINES are not.** Crowding is a problem for text and not for a 1-pixel
    line, so the thinning moved out of `tickValues` — which decides what is DRAWN — and into
    `tickStrings`, which decides what is READ. Before this the two thinned together: as the window
    narrowed the grid lost lines along with the labels, leaving a picture with nothing to measure
    against at exactly the width where measuring by eye matters most.
    """

    #: The decade line: 10, 100, 1k, 10k. Level 0, so pyqtgraph draws its grid at full alpha.
    _MAJOR = (1,)
    #: REW's own ladder inside a decade. Level 1, drawn at half alpha — present, not competing.
    _MINOR = (2, 3, 4, 5, 6, 8)
    #: Which multiples get a LABEL when there is room, in order of preference. The 1-2-5 series
    #: first because it is the vocabulary the trade speaks in (20, 50, 100, 200, 500, 1k), and the
    #: rest afterwards if the axis is wide enough to print them.
    _LABEL_FIRST = (1, 2, 5)
    _LABEL_THEN = (3, 4, 6, 8)
    #: Pixels a label needs before another one may be placed. Measured against the widest string
    #: this axis ever prints ("20kHz"), with room to breathe.
    _MIN_LABEL_PX = 34
    #: Which of the drawn values earned a label at the last `tickValues`. A frozenset because it is
    #: a class default that must never be mutated in place by one axis on behalf of another.
    _labelled: frozenset = frozenset()

    def tickValues(self, minVal, maxVal, size):  # noqa: N802 (Qt/pyqtgraph naming)
        # Values arrive in LOG10 space because the plot is in log mode. Widened by a hair on the
        # way back out of it: `10 ** log10(20)` is 20.000000000000004, so an axis whose edge is
        # exactly 20 Hz filtered its own edge tick out and opened with no grid line at 20.
        low = 10.0 ** min(minVal, maxVal) * (1 - 1e-9)
        high = 10.0 ** max(minVal, maxVal) * (1 + 1e-9)
        decades = range(int(math.floor(math.log10(max(low, 1e-9)))),
                        int(math.ceil(math.log10(max(high, 1e-9)))) + 1)

        def series(multiples):
            return sorted(
                math.log10(mult * 10 ** decade)
                for decade in decades
                for mult in multiples
                if low <= mult * 10 ** decade <= high
            )

        # What gets a label, decided here because this is the only place that knows the axis's
        # width in pixels — `tickStrings` is handed values and a spacing, never a size.
        labelled = self._thin(series(self._LABEL_FIRST), size, minVal, maxVal, [])
        labelled = labelled + self._thin(
            series(self._LABEL_THEN), size, minVal, maxVal, [(0, labelled)]
        )
        self._labelled = frozenset(round(value, 9) for value in labelled)

        out = []
        for step, group in ((0, self._MAJOR), (1, self._MINOR)):
            values = series(group)
            if values:
                out.append((step, values))
        return out

    def _thin(self, values, size, minVal, maxVal, already):
        """Drop what will not fit. Crowding is what made the default unreadable, and a label with
        no room is worse than no label: it overprints the one that had room."""
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
            if round(value, 9) not in self._labelled:
                # Drawn, and deliberately not named — see the class docstring. A grid line every
                # tuner can count off is worth more than a label that would collide.
                out.append("")
                continue
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
    #: The predicted sum was switched on or off. Carried out of the view because the WINDOW has
    #: controls that only make sense with a sum on screen — the group picker fills the selection in
    #: order to sum it — and the alternative was the dialog polling `sum_shown()` on a timer or
    #: reaching into the button.
    sumToggled = Signal(bool)
    #: An all-pass was set on, changed on, or taken off a trace. Its own signal and not a second
    #: meaning of `delayChanged`: the window banks the two side by side per measurement, and a
    #: handler that could not tell which one moved would have to re-bank both on every change.
    allpassChanged = Signal()

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
        #: Whether every guide is off the picture. Set before anything that draws one, because the
        #: rule that decides a marker's visibility (`_marker_visible`) reads it on every pass.
        self._guides_hidden = False
        #: Whether the strip follows the plot's frequency scale. True by default because on the
        #: phase the two pictures are read as one; meaningless on the impulse, where
        #: `_strip_linkable` refuses it whatever this says.
        self._strip_linked = True
        #: Whether the strip is mid-follow. `setXRange` emits a range-changed signal of its own,
        #: and a follower that answers its own move never settles — see `_follow_plot_x`.
        self._following_x = False
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
        self._plot.showGrid(x=True, y=True, alpha=_GRID_ALPHA)
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
            self._plot.getAxis(axis).setPen(pg.mkPen(_grid_colour()))
            self._plot.getAxis(axis).setTextPen(pg.mkPen(theme.muted))
        self._thin_the_y_grid(self._plot)
        self._legend = self._plot.addLegend(offset=(-8, 8), labelTextColor=theme.text)
        # The plot goes in a SPLITTER rather than straight into the layout, so the boundary between
        # it and the sum's strip is a handle the tuner drags (user, 2026-08-18). Built here and not
        # with the strip: reparenting the plot after it has been laid out, drawn and had a button
        # placed on it is a rearrangement of the one widget this window is about, and doing it once
        # at construction costs a splitter with a single child in the windows that never show a
        # strip. `setChildrenCollapsible(False)` because a boundary dragged to the end should give
        # one side everything it can use, not make the other disappear — hiding the strip is what
        # the Σ toggle is for, and a strip collapsed to nothing looks exactly like a broken one.
        self._split = QSplitter(Qt.Orientation.Vertical)
        self._split.setProperty("class", "curve-split")
        self._split.setChildrenCollapsible(False)
        self._split.setHandleWidth(8)
        self._plot.setMinimumHeight(_PLOT_MIN_PX)
        self._split.addWidget(self._plot)
        self._split.splitterMoved.connect(self._on_split_moved)
        layout.addWidget(self._split, stretch=1)
        #: What share of the height the strip takes, as the tuner last left it. Read once here:
        #: the store is on disk, this is asked on every show of the strip, and a window that has
        #: not been dragged yet must not pay for a settings read per redraw.
        self._settings = get_settings()
        self._strip_share = self._read_split_share()

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
        #: The drivers' own magnitudes drawn thin in the strip, under the sum. Held so they can be
        #: taken off again with the sum: they are redrawn from the traces on every pass, like the
        #: sum itself, and a curve left behind would be a second driver drawn at the old delay.
        self._strip_traces: list = []
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

        # ---- row A: which driver is being edited, and everything that has been read ----------
        #
        # What used to be four lines of small grey text and a red sentence under the plot: two
        # compact buttons that NAME what stands behind them, with the whole text in a hover tip
        # (user, 2026-08-18: "займають місце і не читаються"). The verdict is about the CURVE and
        # the reading is about the MARKERS, so they stay two things, side by side, one row high.
        #
        # The DELAY RADIOS lead this row (user, 2026-08-19, with the screenshot: "перенеси
        # «Показання», «Зчитані затримки», «Σ прогноз» вправо до «очистити:», а на їх місце
        # радіокнопки драйверів"). They are the window's "which driver am I working on", so they
        # belong at the start of a row rather than buried in the middle of the controls that read
        # a view; and the three counters, which are all reports rather than actions, gather at the
        # right beside the Clear pair that undoes them.
        notes = QHBoxLayout()
        notes.setContentsMargins(2, 0, 2, 0)
        notes.setSpacing(6)
        # WHICH trace is held back. Radio buttons rather than a signed number: a DSP has no
        # negative delay, so the question is which driver waits, and the two answers are the same
        # alignment read from either end. One per trace, built as traces arrive — a whole side is
        # four drivers and ALL is six, and a pair of radios would have made those unreachable.
        self._target_buttons: list[QRadioButton] = []
        #: Where in this row a new radio goes. Recorded rather than counted later: the window's own
        #: note buttons are inserted into the same row (`add_note`), so the two insertion points
        #: have to move together as radios appear.
        self._radio_slot = notes.count()
        self._ensure_target_buttons(2, notes)
        # Everything past here is right-aligned: a note appearing on the left never moves the
        # counters, and the counters never move the Clear buttons.
        notes.addStretch(1)
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
        #: Where the WINDOW's own note buttons go — see `add_note`. Recorded rather than counted
        #: later, for the same reason `_radio_slot` is: the Clear actions are appended after this
        #: point, so an inserted note has to land before them and not after.
        self._notes_row = notes
        self._note_slot = notes.count()
        layout.addLayout(notes)

        # ---- row B: the chosen driver's settings, all of them, on ONE line ------------------
        #
        # The delay and the all-pass were two rows because the delay's row also carried the mode
        # buttons and the zoom; with the radios and the counters moved to row A there is width for
        # both (user, 2026-08-19: "всі налаштування обраного драйвера в один рядок"). One line,
        # one driver, and the row opens with the driver's NAME in its own colour so "which one am
        # I changing" is answered where the change is typed rather than a glance away.
        #
        # What the all-pass is for: it changes no level and rotates the phase around `f0`, which is
        # how the method aligns a crossover joint without moving the driver's every arrival
        # (`phase_2_eq.md`). Until it was here the only way to see what one would do was to type it
        # into the DSP, re-sweep, and look; now it is applied to the measured trace and the
        # predicted sum answers while the number is being typed. The filter is the skill's own
        # (`core/allpass.py` → `dsp_math`), never a copy here (SCR-050).
        settings = QHBoxLayout()
        settings.setContentsMargins(2, 0, 2, 0)
        settings.setSpacing(6)
        # The driver being edited, named and in its own colour. `.curve-chip-name` because that is
        # exactly what it is — a trace's name in the trace's colour, the way the selection row
        # names one.
        self._apf_target_label = QLabel("")
        self._apf_target_label.setProperty("class", "curve-chip-name")
        settings.addWidget(self._apf_target_label)

        self._shift_label = QLabel(i18n.t("curveShift"))
        self._shift_label.setProperty("class", "phead-sub")
        settings.addWidget(self._shift_label)
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
        settings.addWidget(self._shift_box)
        #: Where the delay group's action goes — see `add_delay_action`. In THIS row, beside the
        #: box that produces it, which is what it was always for; the row it used to sit in is now
        #: about the view rather than about the driver.
        self._delay_slot = settings.count()

        # Which order, where, and — second order only — how sharp. That is the whole filter.
        self._apf_label = QLabel(i18n.t("curveApfLabel"))
        self._apf_label.setProperty("class", "phead-sub")
        attach_tip(self._apf_label, tip_html(i18n.t("curveApfTip")))
        settings.addWidget(self._apf_label)
        self._apf_kind = mini_combo()
        self._apf_kind.setProperty("class", "mini-select")
        self._apf_kind.setFixedWidth(84)
        self._apf_kind.addItem(i18n.t("curveApfNone"), 0)
        self._apf_kind.addItem(allpass_mod.APF1, 1)
        self._apf_kind.addItem(allpass_mod.APF2, 2)
        attach_tip(self._apf_kind, tip_html(i18n.t("curveApfKindTip")))
        self._apf_kind.currentIndexChanged.connect(self._on_apf_control)
        settings.addWidget(self._apf_kind)
        self._apf_f0_label = QLabel("f0")
        self._apf_f0_label.setProperty("class", "phead-sub")
        settings.addWidget(self._apf_f0_label)
        self._apf_f0 = QDoubleSpinBox()
        self._apf_f0.setProperty("class", "mini-select")
        self._apf_f0.setDecimals(1)
        self._apf_f0.setRange(*allpass_mod.F0_RANGE_HZ)
        self._apf_f0.setSingleStep(1.0)
        self._apf_f0.setAccelerated(True)
        self._apf_f0.setSuffix(" Hz")
        self._apf_f0.setValue(_DEFAULT_APF_F0_HZ)
        self._apf_f0.setFixedWidth(104)
        # C locale, like the delay box beside it: one window, one decimal separator.
        self._apf_f0.setLocale(QLocale(QLocale.Language.C))
        self._apf_f0.valueChanged.connect(self._on_apf_control)
        attach_tip(self._apf_f0, tip_html(i18n.t("curveApfF0Tip")))
        settings.addWidget(self._apf_f0)
        self._apf_q_label = QLabel("Q")
        self._apf_q_label.setProperty("class", "phead-sub")
        settings.addWidget(self._apf_q_label)
        self._apf_q = QDoubleSpinBox()
        self._apf_q.setProperty("class", "mini-select")
        self._apf_q.setDecimals(2)
        self._apf_q.setRange(*allpass_mod.Q_RANGE)
        self._apf_q.setSingleStep(0.05)
        self._apf_q.setAccelerated(True)
        self._apf_q.setValue(allpass_mod.DEFAULT_Q)
        self._apf_q.setFixedWidth(72)
        self._apf_q.setLocale(QLocale(QLocale.Language.C))
        self._apf_q.valueChanged.connect(self._on_apf_control)
        attach_tip(self._apf_q, tip_html(i18n.t("curveApfQTip")))
        settings.addWidget(self._apf_q)
        # Why a filter was NOT accepted, when the skill's maths could not be reached for it. Empty
        # and hidden in the ordinary case; a row that grew a warning label for a case that needs
        # a broken install would be a row saying nothing most of the time.
        self._apf_note = QLabel("")
        self._apf_note.setProperty("class", "phead-sub")
        self._apf_note.setVisible(False)
        settings.addWidget(self._apf_note)
        settings.addStretch(1)
        self._settings_row = settings
        layout.addLayout(settings)

        # ---- row C: how the markers read, and what the view is showing ----------------------
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(6)
        # The axis's own unit, at the left of the numbers that are read in it.
        self._unit_label = QLabel("")
        self._unit_label.setProperty("class", "phead-sub")
        row.addWidget(self._unit_label)
        row.addStretch(1)

        for mode in ("v", "h", "vh", "vhs", "vx", "hx"):
            button = QPushButton(_MODE_LABELS[mode])
            button.setProperty("class", "zoom-btn")
            button.setCheckable(True)
            button.setChecked(mode == self._axes_mode)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(30, 24)
            attach_tip(button, i18n.t(f"curveAxes_{mode}"))
            button.clicked.connect(lambda _checked, m=mode: self._on_mode_button(m))
            row.addWidget(button)
            self._axes_buttons.append((button, mode))

        # WHICH two curves the cross modes read. Only on screen when there is a choice to make —
        # more than two traces and a cross mode selected — and here, immediately after the mode
        # buttons that switch those modes on (user, 2026-08-19: the settings of one thing on one
        # line). They used to stand in the notes row, which is now three counters and a Clear pair
        # and has nothing to do with how a marker reads.
        self._cross_label = QLabel("×")
        self._cross_label.setProperty("class", "phead-sub")
        self._cross_combos: list[QComboBox] = []
        for slot in (0, 1):
            combo = mini_combo()
            combo.setProperty("class", "mini-select")
            combo.setFixedWidth(96)
            combo.currentIndexChanged.connect(
                lambda _index, at=slot: self._on_cross_combo(at)
            )
            attach_tip(combo, i18n.t("curveCrossPairTip"))
            combo.setVisible(False)
            if slot:
                row.addWidget(self._cross_label)
            row.addWidget(combo)
            self._cross_combos.append(combo)
        self._cross_label.setVisible(False)

        # Take every guide off the picture at once and put it back (user, 2026-08-18: "додай кнопку
        # сховати всі направляючі, типу '0' або 'Х'"). Beside the mode buttons because it is about
        # the same objects they place, and "×" rather than "0": a nought reads as a value, and this
        # is a crossing-out. The only other × in this window is the LABEL between the two cross-pair
        # combos beside it, which is not a button and does not act.
        # A big X, and red (user, 2026-08-18: "велика 'X' і кнопка червоного кольору"). Bigger
        # than the zoom buttons beside it and in the warning colour whatever its state, because it
        # is the one control here that takes something OFF the picture -- the others move a view,
        # this one removes what the numbers were read from. Red at rest, filled red when the
        # guides are actually hidden, so the state is legible from across a car seat.
        # All of that is `.guides-btn` in `theme.py` and not a QFont plus an inline stylesheet: a
        # QSS `font-size` beats a font set in code, so while this button wore `.zoom-btn` the
        # enlarged glyph never reached the screen -- and the inline colours were only written by
        # `_update_guides_button`, which nothing called at construction, so it opened grey (user,
        # 2026-08-18, with the screenshot).
        self._guides_btn = QPushButton("✕")
        self._guides_btn.setProperty("class", "guides-btn")
        self._guides_btn.setCheckable(True)
        self._guides_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._guides_btn.setFixedSize(34, 26)
        # The strip's link to the plot's frequency scale. Beside the guides toggle because both
        # are about what the picture shows rather than about the measurements, and hidden entirely
        # on the impulse, where there is no frequency above to link to. `.link-btn` gives it the
        # orange ring the user asked for -- see the class in `theme.py` for which token and why.
        self._link_btn = QPushButton("⇅")
        self._link_btn.setProperty("class", "link-btn")
        self._link_btn.setCheckable(True)
        self._link_btn.setChecked(True)
        self._link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._link_btn.setFixedSize(30, 24)
        self._link_btn.setVisible(False)
        attach_tip(self._link_btn, tip_html(i18n.t("curveStripLinkTip")))
        self._link_btn.clicked.connect(self.set_strip_linked)
        attach_tip(self._guides_btn, tip_html(i18n.t("curveGuidesTip")))
        self._guides_btn.clicked.connect(self.set_guides_hidden)
        row.addWidget(self._guides_btn)
        row.addWidget(self._link_btn)

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
        #: One all-pass per TRACE, or None — the same shape as `_delays` and for the same reason:
        #: it is a proposal about one driver, and the radio says which one is being edited.
        self._allpasses: list[Optional[Allpass]] = [None, None]
        #: Whether the APF controls are being written FROM the model rather than by the tuner —
        #: `_sync_apf_controls` sets three widgets, each of which would otherwise answer back.
        self._syncing_apf = False
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
        # Both toggles put into their opening state HERE, at the end of construction. Neither used
        # to be, and the ✕ opened grey because of it: its look was written only by
        # `_update_guides_button`, which nothing called until a theme switch or the first press.
        self._update_guides_button()
        self._update_link_button()
        # ...and the all-pass boxes into theirs: nothing chosen, so f0 and Q are shut.
        self._sync_apf_controls()

    @staticmethod
    def _thin_the_y_grid(plot: pg.PlotWidget) -> None:
        """Two levels of horizontal grid line, not three (user, 2026-08-19: "сітка по вертикалі
        дуже густа").

        pyqtgraph's linear axis offers THREE tick levels by default: the major spacing, a tenth of
        it, and — where there is room — a tenth of that. On a phase plot ranged ±180° that is a
        line every 5°, which at this window's height is a hatch pattern with the curves inside it.
        `maxTickLevel=1` keeps the majors and their one subdivision, which is the same two weights
        the frequency axis draws (`LogHzAxis`) and the same two REW's own axis has.

        The alphas are untouched: `_GRID_ALPHA` and `_GRID_MIX` are what made the grid VISIBLE
        (2026-08-18, with REW's axis beside ours), and the complaint here is about how many lines
        there are, not how bright they are. Only the LEFT axis — the bottom one is either the log
        frequency axis, which decides its own levels, or time, which was never the dense one.
        """
        try:
            plot.getAxis("left").setStyle(maxTickLevel=1)
        except (AttributeError, TypeError):  # pragma: no cover — a pyqtgraph that moved this
            pass

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
        """Whether the Σ toggle is on screen at all. Every view, since 2026-08-19.

        It was kept OFF the frequency response for a day, on the user's own rule (2026-08-18): the
        FR is where MMM/RTA captures get compared, an MMM capture carries no phase, so there the
        answer to Σ would usually be a refusal — and a control that mostly refuses teaches people
        to ignore it.

        **The user reversed it on 2026-08-19 after using the window** ("десь ділась кнопка суми",
        on the frequency response). The rule was written from the RTA case and the workflow turned
        out to be the other one: the sweeps a joint is argued about are compared on the FR as much
        as on the phase, the sum there needs no second scale — the plot is already in dB, over the
        curves it was computed from — and hunting for a toggle that exists on two views out of
        three is worse than a refusal that says why.

        Nothing else changed: a selection that cannot be summed still refuses in words on the Σ
        note button, which is where the reason belongs.
        """
        return True

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
        axis.setPen(pg.mkPen(_grid_colour()))
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
                    # `setParent` resets a QMenu's window flags, so it stops being a popup and
                    # becomes an ordinary child widget — 640×480, at (0, 0), and shown WITH its
                    # parent unless it has been hidden explicitly. The main plot's one is buried
                    # under the splitter, which is parented later; the strip's is parented last
                    # of all, and when the strip is built before the window is shown (the sum
                    # switched on while the window is hidden) it comes up as a black rectangle
                    # over the plot (seen in an offscreen render, 2026-08-19). Hidden explicitly,
                    # once, here — an empty menu with no window flags has nothing to show anyway.
                    if hasattr(menu, "hide"):
                        menu.hide()
                except (RuntimeError, TypeError):  # noqa: PERF203 — one-time, at construction
                    pass

    def _ensure_target_buttons(self, count: int, row: Optional[QHBoxLayout] = None) -> None:
        """Have one delay radio per trace, making the missing ones.

        Grown and never shrunk: the extra radios are hidden by `set_traces` when a smaller
        selection arrives, and destroying a widget that a `toggled` connection is standing on is
        how this app has crashed before (a widget deleted from its own event handler is a SIGSEGV).
        Six spare hidden radios cost nothing; a torn-down one costs the window.

        They live in the NOTES row now (user, 2026-08-19), which is why the slot that moves along
        with them is the notes' one and not the delay group's: the delay's action is in the
        settings row below, where nothing is ever inserted before it.
        """
        row = row if row is not None else self._notes_row
        while len(self._target_buttons) < count:
            index = len(self._target_buttons)
            button = QRadioButton(str(index + 1))
            # `.delay-radio` and not `.phead-sub`: that class is for secondary captions, and it
            # made a CONTROL's own name faint 11 px type. More to the point, an unstyled radio
            # indicator on this dark ground is a dark circle on a dark background, so a row of
            # three read as one bright control and two smudges — the user counted two (2026-08-18:
            # "сорі, я не побачив що їх вже три"). The class gives the unselected state a ring
            # that can be counted; see `theme.py`.
            button.setProperty("class", "delay-radio")
            button.setChecked(index == 0)
            button.toggled.connect(
                lambda checked, i=index: self.set_delay_target(i) if checked else None
            )
            row.insertWidget(self._radio_slot + index, button)
            self._target_buttons.append(button)
            # Everything to the right of the radios moved one place along, including the slot the
            # window's own note buttons are inserted at. Guarded because the first two radios are
            # made while this row is still being built and that slot does not exist yet.
            if getattr(self, "_note_slot", None) is not None:
                self._note_slot += 1

    def add_delay_action(self, button: QWidget) -> None:
        """Put the delay group's own action immediately after the delay controls.

        Not at the end of the row: an action belongs beside the controls that produce it, and
        parked at the far end it reads as a second opinion about the markers. Since 2026-08-19
        that means the SETTINGS row — the delay box, this button, and the all-pass are one line
        about one driver.
        """
        self._settings_row.insertWidget(self._delay_slot, button)

    def add_note(self, button: QWidget) -> None:
        """Put one of the WINDOW's own note buttons in this view's notes row, beside its two.

        The same shape as `add_delay_action` and for the same reason. The view owns the plot and
        the dialog owns the delay bank, but a tuner reads "Σ forecast", "Reading →" and "Delays
        read (n)" as one line of the same kind of thing — three counts with their text behind them
        — and three of them on three rows was three rows of a window that is short of height now
        that it carries a strip (user, 2026-08-18: "ось ці кнопки всі стануть в ряд в самому низу,
        щоб не займати простір").
        """
        self._notes_row.insertWidget(self._note_slot, button)
        self._note_slot += 1

    def add_note_action(self, button: QWidget) -> None:
        """Put an action at the RIGHT-hand end of the notes row, after the notes themselves.

        The stretch in that row is now in front of BOTH — the radios have the left of it (user,
        2026-08-19) — so this end of the row is a block: three counters and the two Clear buttons
        that undo what they count, in that order, never moved by a note appearing with the sum.
        """
        self._notes_row.addWidget(button)

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

        Either way it is a gesture ABOUT the markers, so it ends the hide first (`_guides_wanted`):
        fetching invisible lines back into a view answers nothing, and the button looks broken.
        """
        self._guides_wanted()
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

    def proposed_delays(self) -> list[float]:
        """The delay set this window PROPOSES: the drags with their common part taken off.

        **A delay set is only defined up to a common offset.** What the curves measure is the
        DIFFERENCE between arrivals; where the tuner happened to drop them is not a measurement of
        anything. Drag three drivers onto a common 14.8 ms and this window used to propose +10.690,
        +10.670 and +10.000 — numbers that are both physically meaningless and past what most
        processors will accept (user, 2026-08-18, checking the bank against their own project:
        "затримки виходять значно більшими, ніж вони там є"). The same three with the common part
        removed are 0.000, +0.670, +0.690, and 0.69 ms is 23 cm: a real car.

        Nothing is lost. Every difference survives a constant shift, which is the whole point —
        the spread of the landings is the same number before and after.

        Taken over EVERY trace on screen, zeros included. Skipping the zeros was tried and is
        wrong: a driver sitting at 0 is as often the reference the others were aligned TO as one
        nobody has dragged, and this window cannot tell the two apart (`delay_bank.references`
        records the same ambiguity). Counting it in errs the safe way — the offset is then 0, the
        set is proposed exactly as read, and nothing is invented; skipping it re-based a set that
        already had an origin and quietly moved the alignment (a set at 0 / +0.67 / +0.69 came back
        as 0 / 0 / +0.02). It also makes this idempotent, which a second look at the same curves
        depends on.

        A no-op below two traces, and with nothing dragged. With one curve there is nothing to be
        relative TO, and zeroing the only proposal would erase the tuner's work while putting
        nothing in its place.

        `delays()` stays RAW, and so do the spin box, the drag and the bank's stored value: that is
        the tuner's own handle on the picture, and it must not jump under their fingers mid-drag.
        This is what leaves the window, not what it is operated with.
        """
        raw = list(self._delays)
        live = raw[:len(self._traces)]
        if len(live) < 2 or not any(live):
            return raw
        offset = min(live)
        # Every live entry, including a zero — which can only BE the minimum, so it stays at zero.
        return [ms - offset for ms in live] + raw[len(live):]

    def delay_reference_name(self) -> str:
        """The driver the proposed set is stated FROM — the one that ends up taking no delay.

        Named in the reading so nobody has to work out which zero is the origin: the set says
        "hold these back until they meet this one", and which one that is IS the alignment. Empty
        when there is no set to have an origin — one trace, or nothing dragged yet.
        """
        live = self.proposed_delays()[:len(self._traces)]
        if len(live) < 2 or not any(self._delays[:len(self._traces)]):
            return ""
        for index, value in enumerate(live):
            if not value:
                return self._traces[index].name
        return ""

    def total_delay_ms(self, index: Optional[int] = None):
        """A channel's delay if its proposal were applied, or None when the current one is not
        known. The one number that has to stay non-negative.

        Against the PROPOSED delay, not the raw drag: what a DSP would receive is the normalised
        set (`proposed_delays`), so the below-zero warning has to be about that number. Checking
        the raw one warned about a channel nobody was ever going to be asked to set.
        """
        at = self._shift_target if index is None else index
        if not (0 <= at < len(self._channel_delays)) or self._channel_delays[at] is None:
            return None
        proposed = self.proposed_delays()
        return self._channel_delays[at] + (proposed[at] if at < len(proposed) else 0.0)

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
        # The all-pass boxes follow the same radio: they show THIS driver's filter now.
        self._sync_apf_controls()
        self._render_readout()
        self.delayChanged.emit()

    def delay_target(self) -> int:
        return self._shift_target

    # ---- an all-pass per driver (CURVE-ANALYSIS-PLAN.md step 4) ------------

    def set_allpass(self, ap: Optional[Allpass], index: Optional[int] = None) -> None:
        """Put an all-pass on trace `index` (the chosen driver by default), or take it off.

        Applied to the measured curve rather than to the DSP: on the phase plot the trace rotates
        around `f0`, on the frequency response it does not move (unit magnitude — that is what
        makes it an all-pass), and on either the predicted sum answers at once. On the impulse the
        DRAWN trace stays as captured — an all-pass smears an impulse and re-filtering the time
        series is a round trip through the FFT this window does not make — while the strip's sum
        carries it, which is where the joint is read anyway.

        Probed before it is kept: the filter is the skill's, and a filter that cannot be computed
        must not be accepted as if it could, or the legend would name a rotation the plot does not
        show. Raises `AllpassError` with the reason; the control handler shows it on the row.
        """
        at = self._shift_target if index is None else int(index)
        if not (0 <= at < len(self._allpasses)):
            return
        if ap is not None:
            try:
                ap.response(np.array([ap.f0_hz]))
            except Exception as exc:  # noqa: BLE001 — no skill, or one without the function
                raise AllpassError(i18n.t("curveApfNoMaths").format(error=exc)) from exc
        self._allpasses[at] = ap
        if at == self._shift_target:
            self._sync_apf_controls()
        if self._traces:
            self.set_traces(self._traces)
        self._render_readout()
        self.allpassChanged.emit()

    def allpass(self, index: Optional[int] = None) -> Optional[Allpass]:
        """The all-pass on trace `index` (the chosen driver by default), or None."""
        at = self._shift_target if index is None else int(index)
        return self._allpasses[at] if 0 <= at < len(self._allpasses) else None

    def allpasses(self) -> list:
        """Every driver's all-pass, in trace order — None where there is none."""
        return list(self._allpasses)

    def _on_apf_control(self, *_args) -> None:
        """One of the three APF boxes changed under the tuner's hand: rebuild the filter from all
        three and put it on the chosen driver. Ignored while `_sync_apf_controls` is the writer."""
        if self._syncing_apf:
            return
        kind = self._apf_kind.currentData()
        try:
            if not kind:
                self.set_allpass(None)
            elif int(kind) == 1:
                self.set_allpass(Allpass(1, self._apf_f0.value()))
            else:
                self.set_allpass(Allpass(2, self._apf_f0.value(), self._apf_q.value()))
        except AllpassError as exc:
            # The row says why, and goes back to "none" so the picture and the boxes agree.
            self._apf_note.setText(str(exc))
            self._apf_note.setVisible(True)
            _restyle(self._apf_note, f"color: {current_theme().warn};")
            self._syncing_apf = True
            try:
                self._apf_kind.setCurrentIndex(0)
            finally:
                self._syncing_apf = False
            self._sync_apf_controls()
            return
        self._apf_note.setVisible(False)

    def _sync_apf_controls(self) -> None:
        """Make the three boxes and the name label say what the chosen driver carries.

        The boxes are only ever written from here when the model changes under them — a new
        target, a new selection, a value set in code — so a tuner mid-typing is never overwritten
        by their own keystroke coming back through the model.
        """
        kind_box = getattr(self, "_apf_kind", None)
        if kind_box is None:
            return
        ap = self.allpass()
        self._syncing_apf = True
        try:
            kind_box.setCurrentIndex(max(0, kind_box.findData(0 if ap is None else ap.order)))
            if ap is not None:
                self._apf_f0.setValue(ap.f0_hz)
                if ap.q is not None:
                    self._apf_q.setValue(ap.q)
            self._apf_f0.setEnabled(ap is not None)
            self._apf_q.setEnabled(ap is not None and ap.order == 2)
            self._apf_f0_label.setEnabled(ap is not None)
            self._apf_q_label.setEnabled(ap is not None and ap.order == 2)
        finally:
            self._syncing_apf = False
        # The driver's name, in its colour, so the row says whose filter this is.
        label = self._apf_target_label
        if self._shift_target < len(self._traces):
            name = self._traces[self._shift_target].name.split(" ")[0]
            label.setText(name)
            label.setStyleSheet(
                f"QLabel {{ color: {colour_of(trace_token(self._shift_target)).name()}; }}"
            )
            label.setVisible(True)
        else:
            label.setText("")
            label.setVisible(False)

    def _rotation_deg(self, index: int, freqs_hz) -> Optional[np.ndarray]:
        """The all-pass on trace `index` as wrapped degrees on `freqs_hz`, or None when none.

        Wrapped is fine here and only here: `_shifted` re-wraps the whole phase curve into ±180
        after adding it, so a continuous rotation and a wrapped one draw the same picture.
        """
        ap = self._allpasses[index] if index < len(self._allpasses) else None
        if ap is None:
            return None
        try:
            return np.degrees(np.angle(ap.response(np.asarray(freqs_hz, dtype=float))))
        except Exception:  # noqa: BLE001 — cannot happen after `set_allpass` probed it
            return None

    def _shifted(self, index: int, trace: "Trace"):
        """`(x, y)` for trace `index` with the current delay and all-pass applied, in the plot's
        own units."""
        x = np.asarray(trace.x, dtype=float)
        y = np.asarray(trace.y, dtype=float)
        delay = self._delays[index] if index < len(self._delays) else 0.0
        rotated = index < len(self._allpasses) and self._allpasses[index] is not None
        if not delay and not rotated:
            return x, y
        if self._unit == "ms":
            # The all-pass does not move the drawn impulse — see `set_allpass`.
            return (x + delay) if delay else x, y
        if self._y_unit == "°":
            # Degrees per hertz for this delay, plus the all-pass's own rotation at each hertz,
            # then wrapped back into ±180 so the curve stays on the axis it is drawn on rather
            # than walking off it.
            shifted = y - 360.0 * x * (delay / 1000.0)
            rotation = self._rotation_deg(index, x)
            if rotation is not None:
                shifted = shifted + rotation
            return x, (shifted + 180.0) % 360.0 - 180.0
        return x, y  # a magnitude response moves for neither a delay nor an all-pass

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
            # A new selection is a new question: every delay goes back to zero and every all-pass
            # comes off, the radio points at whichever of these arrives first, and the cross modes
            # go back to comparing the first two — the pair chosen out of the last selection was
            # about drivers that may not even be on screen now. (The window's bank puts a driver's
            # own delay and all-pass back the moment it recognises the title; this view keeps
            # nothing across a selection.)
            self._delays = [0.0] * max(len(self._traces), 2)
            self._allpasses = [None] * max(len(self._traces), 2)
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
                # The NAME takes the trace's colour, so a radio can be matched to a curve without
                # reading it; the indicator's own ring and fill come from `.delay-radio` and stay
                # the same on every radio, which is what keeps "these are your curves" and "this is
                # the one being delayed" two separate statements. Selector-scoped, so the sheet
                # cannot reach into the `::indicator` rules the class provides.
                button.setStyleSheet(
                    f"QRadioButton {{ color: {colour_of(trace_token(index)).name()}; }}"
                )
            else:
                button.setVisible(False)
        for index, trace in enumerate(self._traces):
            # Arrays, not Python lists: pyqtgraph converts a list element by element, and a list
            # comprehension over 262 144 floats had already been paid for upstream.
            x, y = self._shifted(index, trace)
            # The legend names the proposal with the driver: its delay, its all-pass, or both. A
            # curve that has been rotated and a legend that says only the name would be a plot
            # nobody can read back into a DSP setting.
            delay = self._delays[index] if index < len(self._delays) else 0.0
            ap = self._allpasses[index] if index < len(self._allpasses) else None
            bits = ([f"{delay:+.3f} ms"] if delay else []) + ([ap.label()] if ap else [])
            label = f"{trace.name}  " + "  ".join(bits) if bits else trace.name
            self._plot.plot(
                x, y, pen=pg.mkPen(colour_of(trace_token(index)), width=1.0), name=label
            )
        for line in self._markers:
            self._plot.addItem(line)
        self._sync_cross_combos()
        self._sync_apf_controls()
        self._render_crossings()
        # Every delay or all-pass change comes back through here (`set_delay` and `set_allpass`
        # re-set the same traces), which is what makes the sum follow both without another fetch
        # from REW.
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
        self.sumToggled.emit(self._sum_on)

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

        On the impulse it MUST: that x is TIME and the sum's is frequency, so those two cannot
        share one pair of axes. The strip goes under the plot rather than on another view because
        the delay is DRAGGED here, and the point is watching the joint fill in while dragging
        (user, 2026-08-18).

        On the phase it is the user's own verdict after using it ("давай і на фазі використовувати
        вікно внизу — дуже клево"), and the reason is the same one that made the strip work: a sum
        squeezed onto a second scale over a plot in degrees is a fourth line among the curves,
        while a band of its own with the drivers drawn thin under it is a picture of one question.
        The frequency response keeps the right-hand axis — there the plot is ALREADY in dB, so the
        sum stands in the same units over the curves it was computed from, and the user asked for
        nothing there but a heavier line.

        Asked in this widget's own vocabulary, which is units: milliseconds is the impulse,
        degrees is the phase, and the frequency response is the one that answers in dB.
        """
        return self._unit == "ms" or self._y_unit == "°"

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

        The delay comes from `self._delays` and the all-pass from `self._allpasses`, the same lists
        `_shifted` draws with, so the curve and the sum can never disagree about how far a driver
        has been held back or how it has been rotated. Gain and polarity are fixed at "as
        measured": there is no control for either yet, and a silent normalisation would make a sum
        of drivers at different calibrations look like a sum of one car.
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
                    allpass=self._allpasses[index] if index < len(self._allpasses) else None,
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
        # After the strip's visibility settles, not before: the link toggle is offered only while
        # there is a strip on screen to link, and `_apply_strip_link` is what puts an unlinked
        # strip back on its own band when the kind changed under it.
        self._apply_strip_link()
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
        """The strip below the plot: every driver's magnitude thin, and the sum over them thick.

        Raw hertz, not log10: these curves are owned by the strip's own `PlotItem`, so pyqtgraph's
        log mode transforms them — which is the whole reason they are `PlotDataItem`s here and a
        `PlotCurveItem` on the second ViewBox above, where nothing would.

        The drivers are drawn FIRST and the sum last, because pyqtgraph stacks in insertion order
        and the sum is the answer: it crosses four thin lines and has to stay readable across all
        of them.
        """
        if not self._ensure_strip():
            return False
        floors = self._draw_traces_on_strip()
        self._strip_curve = self._strip.plot(
            freqs, values,
            pen=pg.mkPen(self._sum_colour(), width=_SUM_WIDTH, style=Qt.PenStyle.DashLine),
            connect="finite",
        )
        self._strip_curve.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._set_strip_range(np.concatenate([np.asarray(values, dtype=float), floors])
                              if floors.size else values)
        return True

    def _draw_traces_on_strip(self):
        """Each plotted driver's own magnitude, thin, in its own colour. Returns what it drew.

        Asked for after the strip had been used for a day (user, 2026-08-18: "давай там покажемо
        ще і обидві криві тоненько, а суму зробимо товще"), and it is what makes the strip a
        reading rather than a shape: +6 dB over the drivers is two drivers adding, and the same
        curve with no drivers under it is just a line that goes up and down.

        A magnitude does not move when a driver is delayed — only the sum does — so these are
        drawn from the measurement exactly as captured, and only the dashed curve over them
        answers to the radio and the spin box.
        """
        for item in self._strip_traces:
            self._strip.removeItem(item)
        self._strip_traces = []
        drawn: list = []
        for index, trace in enumerate(self._traces):
            if trace.magnitude_db is None:
                continue
            # `x` is the frequency axis wherever this window plots against hertz, and TIME on the
            # impulse — where `freqs_hz` is the axis the capture also carries. The same choice
            # `_sum_inputs` makes, for the same reason.
            hz = trace.freqs_hz if trace.freqs_hz is not None else trace.x
            magnitude = np.asarray(trace.magnitude_db, dtype=float)
            colour = colour_of(trace_token(index))
            colour.setAlpha(_STRIP_TRACE_ALPHA)
            item = self._strip.plot(
                np.asarray(hz, dtype=float), magnitude,
                pen=pg.mkPen(colour, width=_STRIP_TRACE_WIDTH),
                connect="finite",
            )
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._strip_traces.append(item)
            drawn.append(magnitude[np.isfinite(magnitude)])
        return np.concatenate(drawn) if drawn else np.asarray([], dtype=float)

    def _set_strip_range(self, values) -> None:
        """Fit the strip to the sum AND the drivers under it, without either flattening the other.

        The top is whatever is loudest, which is normally the sum — two drivers add to ~6 dB over
        either of them, and a band that cut that off would hide the one number the strip is read
        for. The bottom is the drivers, which is the point of drawing them, but not without limit:
        a measurement runs into the noise floor at the edges of its band, and 100 dB of that in a
        band 132 px tall leaves the top 6 dB indistinguishable from a straight line. So the floor
        is the same 60 dB window the sum's own null is floored into, taken from the top.
        """
        finite = np.asarray(values, dtype=float)
        finite = finite[np.isfinite(finite)]
        if not finite.size:
            return
        high = float(finite.max())
        low = max(float(finite.min()), high - _SUM_FLOOR_DB)
        pad = max((high - low) * 0.08, 1.0)
        self._strip.setYRange(low - pad, high + pad, padding=0)

    def _clear_sum_curve(self) -> None:
        if self._sum_curve is not None and self._sum_vb is not None:
            self._sum_vb.removeItem(self._sum_curve)
        self._sum_curve = None
        if self._strip is not None:
            if self._strip_curve is not None:
                self._strip.removeItem(self._strip_curve)
            # The drivers' own lines go with the sum, always: they are the same redraw. Left
            # behind, a driver would still be on screen after the selection that named it was
            # replaced.
            for item in self._strip_traces:
                self._strip.removeItem(item)
        self._strip_curve = None
        self._strip_traces = []

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
        """A second plot under the main one: x in hertz, y in dB, the drivers and their sum.

        Not a second Y axis on the impulse (user, 2026-08-18): the impulse's x is TIME and the
        sum's is FREQUENCY, so there is no pair of axes they can share. It goes under the plot
        rather than on another view because the delay is dragged HERE, and the point of the whole
        feature is watching the joint fill in while it is dragged. The phase view sends its sum
        here too — see `_on_strip`.

        **Ownership, because this file has been bitten by it.** The widget goes into this widget's
        own splitter, which is in this widget's layout: destroyed with the view by Qt, in order.
        `enableMenu=False` at construction for the reason spelled out at `self._plot`:
        `ViewBox.__init__` builds a whole `ViewBoxMenu` otherwise, and constructing and dropping
        enough of those segfaults the process from inside its own `__init__`. `_adopt_orphan_menus`
        then takes ownership of the parentless "Plot Options" menu `PlotItem` builds whatever
        anyone says.

        Guarded end to end: a pyqtgraph that moved these internals leaves the view without a strip,
        not the window without a curve.
        """
        try:
            theme = current_theme()
            strip = pg.PlotWidget(background=theme.panel, enableMenu=False)
            strip.setMenuEnabled(False)
            strip.getPlotItem().hideButtons()
            # A minimum, not a fixed height: the boundary is dragged now, and a fixed height is a
            # handle that refuses to move. The minimum is what keeps a drag to the bottom from
            # leaving a band too short to read a curve in.
            strip.setMinimumHeight(_STRIP_MIN_PX)
            strip.setLogMode(x=True, y=False)
            # No `enableAutoRange(x=False)` here, unlike `set_log_x`: measured, the strip's x
            # auto-range is already off by the time anything is drawn, because BOTH branches of
            # `_apply_strip_link` set an explicit range — the plot's span when it is following, and
            # `_STRIP_BAND_HZ` when it is not — and `setXRange` disables the auto-range as it goes.
            # A line that changes nothing is worse than no line: it reads as a fact about pyqtgraph
            # that is not true.
            axis = LogHzAxis(orientation="bottom")
            axis.setPen(pg.mkPen(_grid_colour()))
            axis.setTextPen(pg.mkPen(theme.muted))
            strip.setAxisItems({"bottom": axis})
            strip.getAxis("left").setPen(pg.mkPen(_grid_colour()))
            # The left axis wears the sum's own colour, the same pairing of scale with curve the
            # right-hand axis uses on the frequency views.
            strip.getAxis("left").setTextPen(pg.mkPen(self._sum_colour()))
            # ...and the same two levels of horizontal line as the plot above: a band 130 px tall
            # is where a third level is least readable and most likely to be drawn.
            self._thin_the_y_grid(strip)
            strip.showGrid(x=True, y=True, alpha=_GRID_ALPHA)
            self._adopt_orphan_menus(strip)
            # Hidden BEFORE it is put in the splitter. `QSplitter::insertWidget` shows what it is
            # given unless the widget has been told otherwise explicitly, and a strip that flashes
            # into the window at the moment the second Σ is pressed is a redraw nobody asked for.
            strip.setVisible(False)
            # Under the plot, inside the splitter, so the boundary between them is a handle. The
            # two note buttons stay below both: the verdict for what is in the strip should read
            # under it, not above the plot it is not about.
            self._split.addWidget(strip)
            self._strip = strip
            # The plot's own range-changed signal is what the strip follows — one way, and the
            # only wire between the two. Connected once, here, because the strip is built once.
            self._plot.getPlotItem().vb.sigXRangeChanged.connect(self._follow_plot_x)
            self._apply_strip_link()
        except Exception:  # noqa: BLE001 — pyqtgraph moved; the strip is off, not the window
            self._strip = None
            self._strip_failed = True

    def _strip_linkable(self) -> bool:
        """Whether the strip CAN share the plot's x — only when the plot above is in hertz.

        On the phase it can, and by default does: both are frequency on a log axis, so one zoom
        moves both and a feature seen at 3 kHz above is at 3 kHz below (user, 2026-08-18: "той
        самий масштаб і позиціювання, що і фаза"). On the impulse it cannot: that x is time, and
        linking it to hertz would be two different quantities forced onto one scale.
        """
        return self._unit != "ms"

    def _follow_plot_x(self, *_args) -> None:
        """Put the strip on the plot's frequency span. ONE way, always: the strip follows.

        This used to be `ViewBox.setXLink`, and that is the bug the user photographed (2026-08-18:
        a phase axis ticking out to 500000k with the curves crushed into a corner). pyqtgraph's
        link is TWO-WAY — the slave's `updateViewRange` calls `linkedViewChanged` on the MASTER —
        and it lines the two up by dividing a view's width by its SCREEN width. So any moment when
        the strip's own range or geometry is not yet settled arrives on the plot as a range
        computed from nonsense. Measured, with the plot showing 20 Hz … 20 kHz: turning Σ on took
        it from **(1.241, 4.361) to (-307.60, 308.20)** — a span of 615 log-decades — from inside
        `addItem` on the STRIP, and nothing afterwards took it back.

        Copying the numbers cannot do that, because the strip has no way to speak back. It also
        cannot be got wrong by a geometry that has not settled: both views are in log-hertz, the
        same transform on both sides, so the same two numbers mean the same two frequencies.

        Guarded against re-entry: `setXRange` on the strip emits its own range-changed signal, and
        a follower that answers its own move never settles.
        """
        if self._strip is None or self._following_x:
            return
        if not (self._strip_linkable() and self._strip_linked):
            return
        self._following_x = True
        try:
            low, high = self._plot.getPlotItem().vb.viewRange()[0]
            self._strip.getPlotItem().vb.setXRange(low, high, padding=0)
        except (RuntimeError, AttributeError, TypeError, ValueError):
            pass  # torn down, or pyqtgraph moved: the curve matters more than the alignment
        finally:
            self._following_x = False

    def _match_axis_widths(self) -> None:
        """Give the strip's left axis the plot's width, so equal numbers are equal POSITIONS.

        With the link done by copying numbers rather than by pyqtgraph's screen-space maths, the
        two pictures share a scale automatically and share a POSITION only if the space left of
        them is the same. It is not: the phase axis prints "-180" and the strip's prints "84".
        Pinned once here rather than tracked, because a width set from inside a resize is how a
        layout comes to oscillate — and this is worth a few pixels of accuracy, not a loop.
        """
        try:
            width = self._plot.getPlotItem().getAxis("left").width()
            if width > 1:
                self._strip.getPlotItem().getAxis("left").setWidth(width)
        except (RuntimeError, AttributeError, TypeError):
            pass

    def _apply_strip_link(self, *_args) -> None:
        """Have the strip follow the plot's x, or set it free on the audible band.

        Unlinked, the strip opens on the band the rest of this window uses for a frequency view
        rather than on whatever the last link left behind, which would look like a zoom nobody
        asked for. See `_follow_plot_x` for why the following half is not `setXLink`.
        """
        if self._strip is None:
            return
        try:
            box = self._strip.getPlotItem().vb
            # Never pyqtgraph's own link, in either state — including a stale one left by an older
            # build of this window.
            box.setXLink(None)
            if self._strip_linkable() and self._strip_linked:
                self._match_axis_widths()
                self._follow_plot_x()
            else:
                low, high = _STRIP_BAND_HZ
                box.setXRange(math.log10(low), math.log10(high), padding=0)
        except Exception:  # noqa: BLE001 — a link is a convenience; the curve matters more
            pass
        self._update_link_button()

    def set_strip_linked(self, on: bool) -> None:
        """Follow the plot's frequency scale, or zoom the strip on its own.

        Both directions are the point: a tuner reading a joint wants the two pictures over one
        another, and a tuner reading the null itself wants to zoom into it without dragging the
        phase along (user, 2026-08-18: unlink, and be able to come back).
        """
        self._strip_linked = bool(on)
        self._apply_strip_link()

    def strip_linked(self) -> bool:
        """Whether the strip currently follows the plot's x. False on the impulse, always."""
        return self._strip_linked and self._strip_linkable()

    def _update_link_button(self) -> None:
        """Show the link toggle only where a link is possible, and say which state it is in."""
        button = getattr(self, "_link_btn", None)
        if button is None:
            return
        offered = self._strip_linkable() and self._strip is not None and self._strip.isVisibleTo(self)
        button.setVisible(offered)
        if not offered:
            return
        if button.isChecked() != self._strip_linked:
            blocked = button.blockSignals(True)
            button.setChecked(self._strip_linked)
            button.blockSignals(blocked)
        # No colours written here: `.link-btn` in `theme.py` carries the orange ring in both states
        # and tells them apart by the fill, so a theme switch repaints it like everything else and
        # the ring is there before anything has called this (the bug the ✕ had — see
        # `_update_guides_button`).

    def _show_strip(self, on: bool) -> None:
        """Put the strip on screen, or take it off. Never builds one to hide it.

        A hidden splitter child takes no height and Qt hides the handle beside it, so with the
        sum off the window is exactly the shape it was before this feature existed — no dead band,
        no handle for a boundary that is not there.
        """
        if self._strip is None:
            return
        was = self._strip.isVisibleTo(self)
        self._strip.setVisible(bool(on))
        if on and not was:
            # Coming back: Qt gave the hidden child zero height, so the remembered share has to be
            # laid out again. Only on the transition, because doing it on every redraw would undo
            # a drag the moment the delay moved.
            self._apply_split()

    def strip_shown(self) -> bool:
        """Whether the sum's own strip is on screen: an impulse or a phase, Σ on, a sum to draw."""
        return self._strip is not None and self._strip.isVisibleTo(self)

    # ---- the boundary between the two (user, 2026-08-18) -----------------

    def _read_split_share(self) -> float:
        """The strip's share of the height as it was last left, or the default.

        Defensive about what comes back: `QSettings` returns whatever was written, a hand-edited
        INI can hold anything, and a share of 0 or 1.4 is a window with one of its two plots
        missing. Anything outside the range the minimums allow falls back to the default.
        """
        try:
            share = float(self._settings.value(_SPLIT_KEY, _STRIP_SHARE))
        except (TypeError, ValueError):
            return _STRIP_SHARE
        return share if 0.05 <= share <= 0.9 else _STRIP_SHARE

    def _apply_split(self) -> None:
        """Give the strip its remembered share of the height.

        Per-mille rather than pixels: `setSizes` scales what it is given to the space there
        actually is, and this runs before the first layout as often as after it — at which point
        the splitter's own height is still whatever Qt guessed.
        """
        if self._strip is None:
            return
        strip = int(round(1000 * self._strip_share))
        self._split.setSizes([1000 - strip, strip])

    def _on_split_moved(self, *_args) -> None:
        """Remember where the tuner put the boundary — for this window, and for the next one.

        Only while the strip is on screen: hidden, it reports a height of zero, and banking that
        would mean a boundary dragged today comes back tomorrow as no strip at all.
        """
        if self._strip is None or not self._strip.isVisibleTo(self):
            return
        sizes = self._split.sizes()
        total = sum(sizes)
        if len(sizes) < 2 or total <= 0:
            return
        self._strip_share = sizes[-1] / total
        self._settings.setValue(_SPLIT_KEY, self._strip_share)

    def split_share(self) -> float:
        """What share of the height the strip has — the number the boundary is remembered as."""
        return self._strip_share

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

        Which is everywhere now — see `_sum_offered`, where the user's 2026-08-18 rule and its
        2026-08-19 reversal are both written down.

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

    # ---- taking every guide off the picture (user, 2026-08-18) -----------

    def set_guides_hidden(self, on: bool) -> None:
        """Take every guide off the picture at once, or put them all back where they were.

        Every one: the per-curve vertical markers, the levels beside them, the single line the
        cross modes read, and the dots where it meets each curve. The ask was for a look at the
        curves themselves ("додай кнопку сховати всі направляючі"), and a button that hid four of
        the five kinds would be a button you still have to tidy up after.

        **Hidden, not cleared.** Every position is exactly where it was when they come back, and
        `reading()` is the same sentence throughout — the numbers were read off the markers, and
        not drawing a marker does not unread it. Dragging is off while they are hidden, because a
        guide moved by a mouse that cannot see it is a reading nobody took.
        """
        self._guides_hidden = bool(on)
        for index, line in enumerate(self._markers):
            line.setVisible(self._marker_visible(index))
            line.setMovable(not self._guides_hidden)
        for line in self._h_markers:
            # In place rather than through `_rebuild_h_markers`: rebuilding puts each level back
            # onto its curve, which is where it STARTED, not where it was dragged to.
            line.setVisible(not self._guides_hidden)
            line.setMovable(self._h_marker_movable())
        self._render_crossings()
        self._update_guides_button()
        self._update_link_button()
        self._render_readout()

    def guides_hidden(self) -> bool:
        return self._guides_hidden

    def _marker_visible(self, index: int) -> bool:
        """Whether vertical marker `index` is drawn, by the mode and by the hide toggle.

        One rule in one place because it was two: `set_markers` asked "is there a v in the mode"
        and `set_axes_mode` knew about the cross modes as well, so a marker placed while Vx was
        selected appeared and then vanished at the next mode change.
        """
        if self._guides_hidden:
            return False
        if self._axes_mode == "vx":
            # A cross mode has exactly ONE line: the whole question is what a single position says
            # about both curves at once, and a second line would be a second question.
            return index == 0
        if self._axes_mode == "hx":
            return False
        return "v" in self._axes_mode

    def _h_marker_movable(self) -> bool:
        """Whether a level line may be dragged: not while hidden, and never in `vhs`.

        In sync mode the level is not a second thing to place — it IS the curve's value where the
        vertical marker stands, and making it draggable would let the two halves of one reading
        disagree.
        """
        return not self._guides_hidden and self._axes_mode != "vhs"

    def _update_guides_button(self) -> None:
        """Keep the button's own checked state in step with whether the guides are hidden.

        The COLOURS are not written here any more — they are `.guides-btn` in `theme.py`, red
        outlined at rest and filled red while the guides are off, through a `:checked` rule. Both
        halves of that move were bugs, not tidying: an inline stylesheet is only written when
        something CALLS this, and nothing called it at construction, so the ✕ opened looking
        exactly like the grey zoom buttons beside it; and a QSS `font-size` from the application
        sheet beats a QFont set in code, so while the button wore `.zoom-btn` the big red X that
        was asked for was never big (user, 2026-08-18, with the screenshot).

        What is left has to stay: `set_guides_hidden` can be called in code (the marker controls
        end the hide themselves), and a toggle that does not follow its own state is a toggle that
        gets pressed twice.
        """
        button = getattr(self, "_guides_btn", None)
        if button is None:
            return
        if button.isChecked() != self._guides_hidden:
            blocked = button.blockSignals(True)
            button.setChecked(self._guides_hidden)
            button.blockSignals(blocked)

    def set_markers(
        self, positions: Sequence[float], names: Sequence[str] = (),
        tokens: Sequence[str] = (),
    ) -> None:
        """Place markers at `positions`.

        By default the FIRST is the model's reading and the rest are the Arbiter's, coloured apart
        because a panel that shows two numbers in one colour lets them be confused for each other.
        `tokens` overrides that, and is how a caller says these are not model-versus-you.

        What the window opens with is a PAIR, whatever is plotted (`curve_dialog._starting_markers`,
        user 2026-08-19) — but nothing here counts them: a caller with a reason for five markers
        gets five, and everything below reads `self._markers`.
        """
        for line in self._markers:
            self._plot.removeItem(line)
        self._markers = []
        self._marker_names = list(names) or [
            i18n.t("curveMarkerModel") if i == 0 else i18n.t("curveMarkerYou")
            for i in range(len(positions))
        ]
        self._marker_tokens = list(tokens)
        for index, position in enumerate(positions):
            token = self._marker_token(index)
            colour = colour_of(token)
            line = pg.InfiniteLine(
                pos=self._to_view(float(position)), angle=90,
                movable=not self._guides_hidden,
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
            line.setVisible(self._marker_visible(index))
            line.sigPositionChanged.connect(self._on_marker_moved)
            self._plot.addItem(line)
            self._markers.append(line)
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
            axis.setPen(pg.mkPen(_grid_colour()))
            axis.setTextPen(pg.mkPen(theme.muted))
        if self._legend is not None:
            self._legend.setLabelTextColor(theme.text)
        self._style_sum_axis()
        if self._strip is not None:
            self._strip.setBackground(theme.panel)
            for axis_name in ("bottom", "left"):
                self._strip.getAxis(axis_name).setPen(pg.mkPen(_grid_colour()))
            self._strip.getAxis("bottom").setTextPen(pg.mkPen(theme.muted))
            self._strip.getAxis("left").setTextPen(pg.mkPen(self._sum_colour()))
        # The hide-guides toggle carries its state as a colour written from the palette that was
        # current when it was written — the same reason the plot's pens are rebuilt below.
        self._update_guides_button()
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
        # ...and then take the x auto-range back off, because `PlotItem.updateLogMode` ends with a
        # bare `enableAutoRange()` that turns BOTH axes back on. From that moment the x range is at
        # the mercy of every item added or removed, in whatever coordinates that item happens to
        # carry — and a kind switch is exactly when those coordinates change underneath it: the
        # impulse's x is milliseconds and the other two are log-hertz.
        #
        # Measured, driving 180 sequences of kind switches, Σ and zoom through the window and
        # watching every `setRange` on the log axis: **138 of the 180 widened the frequency range
        # without this line, and 0 with it**. One of them, caught in the act inside `set_traces` on
        # an impulse -> phase switch: `x (0.551, 4.466) -> (-307.600, 308.200)`, which a log axis
        # labels out past 10^308 Hz with the curves crushed into a corner. That is the shape of
        # what the user photographed (2026-08-18: ticks running to 500000k).
        #
        # This window never wants an auto-ranged x: it states its own span on every fetch
        # (`curve_dialog._frame` -> `focus_x`) and by hand after that (`show_all`, `show_detail`,
        # `zoom`). Y is untouched — that one IS asked for, by `autoscale_y`.
        self._plot.getViewBox().enableAutoRange(axis="x", enable=False)
        # The frequency axis only makes sense in log mode; time keeps pyqtgraph's own.
        theme = current_theme()
        axis = self._hz_axis if self._log_x else pg.AxisItem(orientation="bottom")
        axis.setPen(pg.mkPen(_grid_colour()))
        axis.setTextPen(pg.mkPen(theme.muted))
        # The grid belongs to the axis ITEM, and this call installs a new one — so it has to be
        # given the grid before it goes in. This is the whole of "the grid is nearly invisible"
        # (user, 2026-08-18, with REW's axis beside ours): there WAS no vertical grid on any view
        # this window opens on. `showGrid` in `__init__` set it on the axis pyqtgraph built, every
        # kind switch replaced that axis with one whose grid flag was False, and asking `showGrid`
        # again changes nothing because it only ticks pyqtgraph's own checkbox — already ticked, so
        # no `toggled`, so no `updateGrid`. Measured on a frequency view: `bottom.grid = False`
        # while `left.grid = 255`, which is exactly why one direction of the same picture had lines
        # and the other did not. `setGrid` on the item skips the checkbox entirely.
        axis.setGrid(int(_GRID_ALPHA * 255))
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
        # It is also what tells the phase from the frequency response, which decides both whether
        # the Σ toggle is offered (`_sum_offered`) and WHERE a sum is drawn (`_on_strip`) — so the
        # sum is re-rendered here rather than left to the next redraw. It used to be only the
        # button, on the grounds that nothing about the sum had changed; since the phase moved to
        # the strip that is no longer true, and a kind switch that leaves the sum on the surface
        # the PREVIOUS kind used is a window disagreeing with itself until something else redraws.
        self._update_sum_button()
        self._render_sum()
        self._render_readout()

    def _guides_wanted(self) -> None:
        """A control ABOUT the guides was pressed, so the guides come back.

        With them hidden the mode buttons and the marker actions all appear dead: they place and
        move lines nothing is drawing, so the picture does not answer and the control looks broken
        (user, 2026-08-18: "коли нажав любу іншу то Х скинувся"). Pressing one of them is a
        statement that the tuner wants the guides, and this is where the hide ends.

        Deliberately not wired to the rest of the row. The Σ toggle, the strip's link toggle, the
        zoom buttons and the delay controls are about the curves or about the view, not about the
        guides — and a tuner who took every line off in order to LOOK at the traces would lose that
        the moment they zoomed in.

        On the button handlers rather than inside `set_axes_mode`, because the window calls that
        itself on every kind switch (`curve_dialog._apply_kind`): in the setter it would put the
        guides back behind the tuner while they were reading a curve.
        """
        if self._guides_hidden:
            self.set_guides_hidden(False)

    def _on_mode_button(self, mode: str) -> None:
        """The guides come back, then the mode changes — see `_guides_wanted` for which do that."""
        self._guides_wanted()
        self.set_axes_mode(mode)

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
            line.setVisible(self._marker_visible(index))
        self._render_crossings()
        self._render_readout()

    def _visible_y(self) -> Optional[tuple[float, float]]:
        """The Y span currently on screen, or None while there is no settled view to ask."""
        try:
            low, high = self._plot.getViewBox().viewRange()[1]
        except (RuntimeError, TypeError, ValueError):  # torn down, or nothing plotted yet
            return None
        return (float(low), float(high)) if high > low else None

    def _h_marker_levels(self, on_curve: Sequence[float]) -> list[float]:
        """Where the level lines START: on their own curves, unless that draws lines nobody can read.

        The on-curve start is a preference, not a rule, and this is where the drawing surrenders it.
        What it wanted is still right — the first thing anybody asks of a level marker is "what is
        this trace doing here", and a line parked at zero answers nothing. What it did NOT survive
        is an impulse: outside the arrival every trace sits at about the same value, and the markers
        start on each trace's own peak, so two lines landed within a hair of each other at the
        bottom edge of a view scaled to ±peak, and read as one line at the bottom of the picture
        (user, 2026-08-18: "коли вибираю горизонтальні маркери, вони в самому низу — зручно було,
        коли вони по середині рознесені між собою"). A wrapped phase does the same at −180°.

        So: keep the on-curve placement while every line is inside the visible span and no two are
        within `_H_MARKER_MIN_GAP` of the height apart — which is the frequency-response case, where
        two drivers at one frequency are a real and readable number of decibels apart — and spread
        them evenly across the middle of the picture when they are not. They are draggable to
        anywhere afterwards either way, and `reading()` is the same sentence whichever start they
        were given: a starting point is not an answer.
        """
        levels = [float(value) for value in on_curve]
        span = self._visible_y()
        if span is None or not levels:
            return levels
        low, high = span
        height = high - low
        gap = height * _H_MARKER_MIN_GAP
        inside = all(low <= value <= high for value in levels)
        apart = all(
            abs(a - b) >= gap
            for index, a in enumerate(levels) for b in levels[index + 1:]
        )
        if inside and apart:
            return levels
        # Evenly across the middle band, in marker order, top down: the order the reading names
        # them in is the order they are stacked in, so a line can be matched to its curve by eye
        # before anything has been dragged.
        middle = (low + high) / 2.0
        if len(levels) == 1:
            return [middle]
        band = height * _H_MARKER_SPREAD
        step = band / (len(levels) - 1)
        return [middle + band / 2.0 - step * index for index in range(len(levels))]

    def _rebuild_h_markers(self) -> None:
        """One horizontal marker per vertical one, started on a curve's value at that x.

        Marker `i` starts on trace `i` while there is a trace `i` to start on, and on the LAST one
        after that (`_y_at` clamps). The markers are a constant pair now and the traces are however
        many were chosen, so the two lists stopped being the same length on 2026-08-19: over one
        curve both lines start on it, over four the pair reads the first two, and either way the
        line is on a curve rather than parked at zero.

        Where that would draw two lines nobody can tell apart, they are spread across the middle of
        the view instead — see `_h_marker_levels`, which owns that decision for both shapes below.
        """
        for line in self._h_markers:
            self._plot.removeItem(line)
        self._h_markers = []
        if self._axes_mode == "hx":
            # One horizontal line, placed at whatever the first of the two CHOSEN curves is doing
            # where the vertical marker last stood -- a level somewhere on the data rather than at
            # zero. Through the same helper, which for a single line only has to keep it on screen.
            theme = current_theme()
            first = self.cross_pair()[0]
            level = self._h_marker_levels(
                [self._y_at(first, self.positions()[0])] if self.positions() else [0.0]
            )[0]
            line = pg.InfiniteLine(
                pos=level, angle=0, movable=self._h_marker_movable(),
                pen=pg.mkPen(theme.accent, width=1.4, style=Qt.PenStyle.DashLine),
            )
            line.setVisible(not self._guides_hidden)
            line.sigPositionChanged.connect(self._on_marker_moved)
            self._plot.addItem(line)
            self._h_markers = [line]
            return
        if "h" not in self._axes_mode:
            return
        theme = current_theme()
        levels = self._h_marker_levels(
            [self._y_at(index, x) for index, x in enumerate(self.positions())]
        )
        for index, _x in enumerate(self.positions()):
            token = self._marker_token(index)
            line = pg.InfiniteLine(
                pos=levels[index], angle=0,
                movable=self._h_marker_movable(),
                pen=pg.mkPen(colour_of(token), width=_GUIDE_WIDTH,
                             style=Qt.PenStyle.DotLine),
            )
            line.setVisible(not self._guides_hidden)
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
        # Naming the two curves a cross mode reads is a gesture about the guides — the line and its
        # dots are what would move — so it ends the hide (`_guides_wanted`). Safe to do here rather
        # than on the signal because `_sync_cross_combos` blocks these signals when IT moves them:
        # nothing but a hand reaches this method.
        self._guides_wanted()
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
        # A dot marks where a hidden line meets a curve, so it goes with the line. Nothing is lost
        # by not making it: the dots are derived from the markers on every pass, and `crossings()`
        # — which is what the reading is built from — reads the lines, not these.
        if self._guides_hidden or self._axes_mode not in _CROSS_MODES or not self._traces:
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
        """The x where trace `index` crosses `level`, closest to `centre`. None if it never does.

        Off the DRAWN curve, for the same reason `_y_at` is: the level line crosses what is on
        screen, and a driver that has been delayed or rotated is on screen where `_shifted` put it.
        """
        if not (0 <= index < len(self._traces)):
            return None
        xs, ys = self._shifted(index, self._traces[index])
        xs = np.asarray(xs, dtype=float)
        ys = np.asarray(ys, dtype=float) - level
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
        """The value of the DRAWN curve `index` at `x`, or 0 when there is nothing plotted.

        Drawn, not captured: `_shifted` is what the plot is given, so a delayed impulse and a
        rotated phase are read where the marker actually crosses them. Reading the raw measurement
        instead meant that the moment a driver was held back, the level line placed "on its curve"
        landed beside it and the reading stated a value the picture does not show.

        The index is CLAMPED rather than refused. Markers are a constant pair now (user,
        2026-08-19) and traces are however many the tuner chose, so marker 2 over a single curve
        has no trace of its own — it reads the last one, which is the same curve the eye reads it
        against.
        """
        if not self._traces:
            return 0.0
        at = min(max(int(index), 0), len(self._traces) - 1)
        xs, ys = self._shifted(at, self._traces[at])
        xs = np.asarray(xs, dtype=float)
        if not xs.size:
            return 0.0
        return float(np.asarray(ys, dtype=float)[int(np.abs(xs - x).argmin())])

    # ---- what the Arbiter is saying --------------------------------------

    def positions(self) -> list[float]:
        """In the unit the axis is labelled with — Hz, not log10(Hz)."""
        return [self._from_view(float(line.value())) for line in self._markers]

    def levels(self) -> list[float]:
        """Where the horizontal markers sit, in the y axis's own unit."""
        return [float(line.value()) for line in self._h_markers]

    def reading(self) -> str:
        """The markers as a sentence a model can parse — what each one crosses, then the delta.

        A sentence rather than a dict because this goes into the dialog, where the Arbiter can see
        and edit it before it is sent. Nothing is recorded behind their back.

        Per MARKER since 2026-08-19, and that is the shape the user asked for ("додати поточні
        показники пересічення маркерів більш структуровано… щоб зразу бачити де що пересікається").
        It used to be per AXIS — every marker's frequency in one clause, every level in another —
        which reads as two lists the reader has to zip together, and stopped saying anything at all
        about the curves once there were more than two of them. Now each marker names what it
        crosses on every trace on screen, and the Δ block states the differences.
        """
        rotated = any(ap is not None for ap in self._allpasses[:len(self._traces)])
        if not self._markers and not any(self._delays) and not rotated:
            return ""
        names = [t.name for t in self._traces if t.name]
        digits = 3 if self._unit == "ms" else 1
        if self._markers and self._axes_mode in _CROSS_MODES:
            return self._cross_reading(digits)
        tables = self._marker_tables(digits)
        parts = [text for text in (self._table_text(table) for table in tables) if text]
        # The curves named ONCE at the head, and only where the clauses do not name them
        # themselves — which is the impulse, where the reading is arrival times and nothing else.
        # Everywhere else each clause already prints every trace, and a header would say each name
        # twice for no reader's benefit.
        head = "" if any(table.traces for table in tables) or not names else " / ".join(names)
        parts.extend(self._proposal_clauses())
        if not parts:
            return ""
        # One line. It has a full-width row of its own now, which is room enough — the wrapping is
        # there for a narrow window, not as the normal shape (user, 2026-08-11).
        body = "; ".join(parts)
        return f"{head} — {body}" if head else body

    def _proposal_clauses(self) -> list[str]:
        """What this window is PROPOSING about the drivers: the delay set, then the all-passes.

        Its own method because two readers want exactly these sentences and neither wants the
        markers with them: `reading()` puts them after the marker clauses, and the readout tip puts
        them under the table as prose (a proposal is a sentence, not a row of numbers).
        """
        proposals = []
        # The set with its common part removed — see `proposed_delays`. Which drivers are IN the
        # set is still decided by the raw drag (a driver nobody moved is not a proposal); what is
        # PRINTED for each of them is the normalised number, including the 0.000 that names the
        # one the rest are held back to meet.
        proposed = self.proposed_delays()
        reference = self.delay_reference_name()
        for index, trace in enumerate(self._traces):
            # EVERY driver that carries a proposal, not only the selected one. Alignment is what
            # the whole set says together, and a sentence naming one of two delayed curves would
            # describe a picture nobody is looking at.
            #
            # ...and the ORIGIN, whether or not it was dragged. It reads +0.000, and it has to be
            # in the list: a set whose reference is named in the caveat but missing from the
            # numbers is a set the reader has to assemble themselves.
            raw = self._delays[index] if index < len(self._delays) else 0.0
            if not raw and trace.name != reference:
                continue
            delay = proposed[index] if index < len(proposed) else 0.0
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
        clauses = []
        if proposals:
            # The caveat once, at the head, not once per driver. It is a property of the whole
            # statement — the panel changes nothing; this goes to the composer, the Arbiter sends
            # it, and the delta is banked 🟡 like every other proposed change. Repeating it on
            # each driver was most of the sentence by the second one (user's screenshot).
            delays = i18n.t("curveDelayHead") + " " + "; ".join(proposals)
            if reference:
                # One clause, and only where a set was actually normalised. Without it the reader
                # has to work out for themselves which of the numbers is the origin and why one of
                # them is zero — and that is the difference between a set they can enter and a
                # set they have to reverse-engineer.
                delays += ". " + i18n.t("curveDelayRelative").format(name=reference)
            clauses.append(delays)
        rotations = [
            f"{trace.name}: {self._allpasses[index].label()}"
            for index, trace in enumerate(self._traces)
            if index < len(self._allpasses) and self._allpasses[index] is not None
        ]
        if rotations:
            # Its own clause, not folded into the delay's: a delay and an all-pass are two
            # different DSP settings on the same driver (`ta_ms` and an EQ band), and a reader
            # entering them types them in two different places. Named in the ledger's vocabulary
            # (`APF2 250 Hz Q 0.71`) so what is read here is what would be proposed there. Same
            # caveat as the delay's, once: proposed, not applied.
            clauses.append(i18n.t("curveApfHead") + " " + "; ".join(rotations))
        return clauses

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

    # ---- the reading as a TABLE (user, 2026-08-19) ------------------------

    def _marker_label(self, index: int) -> str:
        """What marker `index` is called in a SENTENCE.

        On the plot a marker's label sits a hand's width from its own line, so a bare digit is
        enough and that is what `curve_dialog` names them; in a sentence made of numbers a lone
        "1" is not, so a digit prints as "marker 1". A name that is not a number — the model's
        reading, the Arbiter's, or a title a caller passed — is printed as it is.
        """
        name = (
            str(self._marker_names[index]) if index < len(self._marker_names) else str(index + 1)
        )
        return i18n.t("curveMarkerN").format(n=name) if name.strip().isdigit() else name

    def _marker_token(self, index: int) -> str:
        """The colour NAME marker `index` wears — the one rule, so the line, the level line and
        the reading cannot disagree about which marker a number belongs to."""
        if index < len(self._marker_tokens):
            return self._marker_tokens[index]
        return _MODEL_TOKEN if index == 0 else _ARBITER_TOKEN

    def _marker_tables(self, digits: int) -> list["_MarkerTable"]:
        """The reading, as blocks of numbers: the vertical markers, then the levels.

        One structure, two renderings — `_table_text` for the model and `_table_html` for the
        tuner's tip — so the sentence that leaves the window and the table on screen can never
        state different numbers.
        """
        if not self._markers:
            return []
        tables = []
        if "v" in self._axes_mode:
            tables.append(self._v_table(digits))
        # `vhs` gets no level block: there the level IS the curve's value where the vertical
        # marker stands, so a second table would print the same reading again under another head.
        if "h" in self._axes_mode and self._axes_mode != "vhs" and self._h_markers:
            tables.append(self._h_table(digits))
        return tables

    def _v_table(self, digits: int) -> "_MarkerTable":
        """Each vertical marker's position, and what every trace is doing there."""
        positions = self.positions()
        # Every trace on screen — except where the y axis has no unit at all, which is the
        # impulse. There a sample value is not a reading anybody takes, and the arrival IS the
        # question, so the block stays positions-only (and `reading()` then names the curves at
        # the head instead).
        traces = [t.name for t in self._traces] if self._y_unit else []
        rows = []
        for index, x in enumerate(positions):
            rows.append(_TableRow(
                self._marker_label(index), self._marker_token(index),
                [_fmt(x, digits)] + [_fmt(self._y_at(at, x), 1) for at in range(len(traces))],
                False,
            ))
        if len(positions) >= 2:
            # Marker 2 minus marker 1, signed: which way the second one is off the first is half
            # of what a Δ is read for, and the pair has a fixed order to be signed against
            # (positions[0] is marker 1 / the model's reading, always).
            rows.append(_TableRow("Δ", "", [_fmt(positions[1] - positions[0], digits)] + [
                _fmt(self._y_at(at, positions[1]) - self._y_at(at, positions[0]), 1)
                for at in range(len(traces))
            ], True))
        return _MarkerTable(traces, self._unit, self._y_unit, rows)

    def _h_table(self, digits: int) -> "_MarkerTable":
        """Each level, and where every trace reaches it.

        Which crossing, when a curve reaches a level many times: the one nearest the vertical
        marker of the same number in `vh` — the two halves of one reading, so they are read at the
        same place — and nearest the middle of the view in `h`, where there is no vertical marker
        to be near and the tuner is pointing with the zoom. Both through `_crossing_near`, which is
        the same choice the `hx` mode makes and documents.
        """
        levels = self.levels()
        positions = self.positions()
        centre = 0.0
        try:
            (low, high), _ = self._plot.getViewBox().viewRange()
            centre = self._from_view((low + high) / 2.0)
        except (RuntimeError, TypeError, ValueError):  # torn down, or nothing plotted yet
            pass
        traces = [t.name for t in self._traces]
        rows = []
        for index, level in enumerate(levels):
            near = (
                positions[index]
                if "v" in self._axes_mode and index < len(positions) else centre
            )
            cells = [_fmt(level, 1)]
            for at in range(len(traces)):
                x = self._crossing_near(at, level, near)
                # A trace that never reaches this level says so. A blank cell reads as a number
                # nobody filled in; "—" is an answer.
                cells.append(_NO_CROSSING if x is None else _fmt(x, digits))
            rows.append(_TableRow(self._marker_label(index), self._marker_token(index),
                                  cells, False))
        if len(levels) >= 2:
            # The levels' own difference, and nothing per trace: two crossings of two different
            # levels on one curve are not a Δ anybody asked for.
            rows.append(_TableRow("Δ", "", [_fmt(levels[1] - levels[0], 1)], True))
        return _MarkerTable(traces, self._y_unit, self._unit, rows)

    @staticmethod
    def _table_text(table: "_MarkerTable") -> str:
        """One block as plain text: a clause per marker, then the Δ clause. This is what the model
        reads, so nothing here is markup and nothing is a layout."""
        clauses = []
        for row in table.rows:
            head = " ".join(part for part in (
                row.label, "" if row.delta else i18n.t("curveAt"), row.cells[0], table.head_unit
            ) if part)
            body = ", ".join(
                " ".join(bit for bit in (
                    name, "Δ" if row.delta else "", value,
                    # No unit after "this curve never gets there": a unit turns the answer back
                    # into something that looks like a measurement.
                    "" if value == _NO_CROSSING else table.cell_unit,
                ) if bit)
                for name, value in zip(table.traces, row.cells[1:])
            )
            clauses.append(f"{head}{'; ' if row.delta else ': '}{body}" if body else head)
        return "; ".join(clauses)

    @staticmethod
    def _table_html(table: "_MarkerTable") -> str:
        """The same block as a table, each marker's row in the MARKER's colour and each trace's
        column in the TRACE's colour.

        The user's ask, 2026-08-19, is two things at once: "щоб була чітка структура щоб зразу
        бачити де що пересікається" — which is a table, not a sentence — "і колір показників
        співпадав з кольором маркерів" — which is why the row label carries the marker's own
        colour rather than being grey type beside a coloured line.

        The values themselves stay in the ordinary text colour. They are the answer, and a number
        printed in the colour of the line it was read off is a number competing with its own
        label; the two colours in a cell's row and column already say which marker and which curve
        it belongs to.
        """
        theme = current_theme()
        head_cells = ["<td></td>", _cell(table.head_unit, theme.muted)]
        for at, name in enumerate(table.traces):
            unit = (
                f'<br><span style="color: {theme.muted}">{html.escape(table.cell_unit)}</span>'
                if table.cell_unit else ""
            )
            head_cells.append(
                f'<td style="color: {colour_of(trace_token(at)).name()}">'
                f"{html.escape(name)}{unit}</td>"
            )
        rows = ["<tr>" + "".join(head_cells) + "</tr>"]
        for row in table.rows:
            colour = colour_of(row.token).name() if row.token else theme.muted
            cells = [f'<td style="color: {colour}"><b>{html.escape(row.label)}</b></td>']
            cells.extend(_cell(value, theme.text) for value in row.cells)
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return f'<table cellspacing="0" cellpadding="4">{"".join(rows)}</table>'

    def _readout_html(self, warn: bool) -> str:
        """What stands behind the Markers button: the table, then the proposals as prose.

        Two shapes on purpose. What the markers cross is a grid of numbers and belongs in a table;
        a delay set and an all-pass are SENTENCES with a caveat in them ("proposed, not applied"),
        and a caveat chopped into cells is a caveat nobody reads. The warning colour goes on that
        prose, where the below-zero total actually is, and on the button — see `_render_readout`.
        """
        theme = current_theme()
        digits = 3 if self._unit == "ms" else 1
        blocks: list[str] = []
        if self._markers and self._axes_mode in _CROSS_MODES:
            # A cross mode has one line and one Δ — a sentence, not a grid. `_cross_reading` is
            # that sentence, and it is what leaves the window too.
            blocks.append(_wrapped_html(self._cross_reading(digits)))
        else:
            blocks.extend(self._table_html(table) for table in self._marker_tables(digits))
        clauses = self._proposal_clauses()
        if clauses:
            blocks.append(_wrapped_html("; ".join(clauses), theme.warn if warn else ""))
        if not any(block.strip() for block in blocks):
            blocks = [_wrapped_html(i18n.t("curveNoMarkers"))]
        head = f'<b>{html.escape(i18n.t("curveReadoutBtn"))}</b>'
        return (
            f'<div style="font-size: {_TIP_FONT_PX}px; color: {theme.text}">'
            f'{head}{"".join(blocks)}</div>'
        )

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
        totals = [self.total_delay_ms(i) for i in range(len(self._traces) or 1)]
        # The one reading in this panel that is not merely a number but a claim the hardware will
        # reject. It colours the BUTTON, not a word inside the sentence: a warning inside a
        # sentence made of numbers is read last, and this sentence is now behind a hover.
        impossible = any(total is not None and total < 0 for total in totals)
        if getattr(self._readout_btn, "hover_tip", None) is not None:
            self._readout_btn.hover_tip.set_text(self._readout_html(impossible))
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
        self._apf_label.setText(i18n.t("curveApfLabel"))
        self._apf_kind.setItemText(0, i18n.t("curveApfNone"))
        for widget, key in (
            (self._apf_label, "curveApfTip"), (self._apf_kind, "curveApfKindTip"),
            (self._apf_f0, "curveApfF0Tip"), (self._apf_q, "curveApfQTip"),
        ):
            if getattr(widget, "hover_tip", None) is not None:
                widget.hover_tip.set_text(tip_html(i18n.t(key)))
        for combo in getattr(self, "_cross_combos", []):
            if getattr(combo, "hover_tip", None) is not None:
                combo.hover_tip.set_text(i18n.t("curveCrossPairTip"))
        for button, mode in self._axes_buttons:
            if getattr(button, "hover_tip", None) is not None:
                button.hover_tip.set_text(i18n.t(f"curveAxes_{mode}"))
        if getattr(self._guides_btn, "hover_tip", None) is not None:
            self._guides_btn.hover_tip.set_text(tip_html(i18n.t("curveGuidesTip")))
        if getattr(self._link_btn, "hover_tip", None) is not None:
            self._link_btn.hover_tip.set_text(tip_html(i18n.t("curveStripLinkTip")))
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
