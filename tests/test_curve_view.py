"""The curve panel is an input device, not a viewer.

What has to hold is that a marker produces a NUMBER — the thing a screenshot could never give
back, and the reason a disagreement about an impulse onset had nowhere to be settled.
"""

from __future__ import annotations

import math
import os
import pathlib
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.curve_dialog import CurveDialog, _CurveWorker  # noqa: E402
from autosound_tcc.ui.tcc.curve_view import CurveView, Trace  # noqa: E402
from autosound_tcc.ui.tcc.theme import current_theme  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _impulse(peak_ms: float, n: int = 200, span: float = 8.0):
    xs = [i * span / n for i in range(n)]
    ys = [math.exp(-abs(x - peak_ms) * 3.0) * math.cos((x - peak_ms) * 25.0) for x in xs]
    return xs, ys


#: Widgets built by the current test. pyqtgraph's `PlotItem` constructs parentless QMenus and
#: QWidgetActions on every instance, and letting Python collect them at a moment of its choosing
#: segfaults the process — PySide's SignalManager asks a half-freed wrapper for its metaobject
#: while Qt is still connecting the menu's actions.
#:
#: Holding them for the whole run was the first answer and it traded one crash for another: 44
#: live PlotItems accumulate, and the process then dies inside a LATER `PlotItem.__init__`
#: instead. Both directions were reproduced; the second at roughly one run in ten, caught by
#: macOS's own crash reporter on 2026-08-13 with the stack ending in
#: `QMenu::actionEvent → QObject::connect → SignalManager::retrieveMetaObject`.
#:
#: Neither leaking nor collecting is the fix. Deterministic destruction is: `_drain_widgets`
#: below hands each widget to Qt at the end of the test that made it, in order, while nothing is
#: mid-construction. No random GC pass, and nothing accumulates.
_KEEP: list = []
#
#: Destroying them at the end of each test instead — through Qt, with the
#: DeferredDelete flush that `processEvents()` alone does not perform — was tried on
#: 2026-08-13 and MEASURED WORSE: 2 crashes in 5 full runs against a baseline of about
#: 1 in 10, and it added a second signature, a recursive ~QBoxLayout at interpreter
#: exit. Reverted. It was not wasted: it surfaced a real i18n bug, a retranslate
#: listener calling into a widget whose C++ half was already freed.



def _dialog(*args, **kwargs) -> CurveDialog:
    """Build a dialog and keep it alive for the run — see `_KEEP`.

    `_app()` first: a QWidget built before the QApplication aborts the process, and which test
    happens to run first is decided by `-k`, not by this file (found by running the bank tests
    alone, 2026-08-19).
    """
    _app()
    made = CurveDialog(*args, **kwargs)
    _KEEP.append(made)
    return made


def _tip(widget) -> str:
    """A hover tip as the plain sentence it is made of.

    The tips are rich text now — a bold head, a font size, and line breaks put in by hand because
    the shared tip label does not wrap — so a test that asks whether the tip says something has to
    take the markup back off first, or it is testing where the breaks landed.
    """
    import html as html_module
    import re

    text = re.sub(r"<[^>]+>", "", widget.hover_tip.text().replace("<br>", " "))
    return " ".join(html_module.unescape(text).split())


def _chips(dialog) -> list:
    """The chips actually on the row, in order. The pool keeps hidden spares — see
    `CurveDialog._render_chips` — and a spare is not part of the selection."""
    return [chip for chip in dialog._chips if not chip.isHidden()]


def _chip_colour(chip) -> str:
    """The colour a chip is wearing, out of the per-widget stylesheet it is written into."""
    import re

    found = re.search(r"color:\s*(#[0-9a-fA-F]{6})", chip._name.styleSheet())
    return found.group(1).lower() if found else ""


def _view() -> CurveView:
    _app()
    view = CurveView()
    _KEEP.append(view)
    xl, yl = _impulse(4.52)
    xr, yr = _impulse(4.78)
    view.set_traces([Trace("w-L_01 (sw)", xl, yl), Trace("w-R_01 (sw)", xr, yr)])
    return view


def test_a_marker_reads_back_as_a_number_with_the_measurement_it_is_on():
    view = _view()
    view.set_markers([4.52, 4.78])

    reading = view.reading()

    assert "w-L_01 (sw)" in reading and "w-R_01 (sw)" in reading
    assert "4.520 ms" in reading and "4.780 ms" in reading


def test_the_delta_is_the_answer_the_question_was_actually_about():
    """"How far apart are these two arrivals" is what keeps being asked, so it is not left as
    arithmetic for the reader."""
    view = _view()
    view.set_markers([4.52, 4.78])

    assert "Δ 0.260 ms" in view.reading()


def test_dragging_a_marker_changes_the_reading_and_says_so():
    view = _view()
    view.set_markers([4.52, 4.52])
    changed = []
    view.markersChanged.connect(lambda: changed.append(view.reading()))

    view._markers[1].setValue(5.14)

    assert changed, "moving a marker has to announce itself — the readout is live"
    assert "Δ 0.620 ms" in view.reading()
    assert view.positions() == [4.52, 5.14]


def test_the_model_and_the_arbiter_are_never_the_same_marker():
    """Two numbers shown as one colour is a panel that lets them be confused, which is the whole
    failure it exists to end."""
    view = _view()
    view.set_markers([4.52, 4.78])

    pens = [line.pen.color().name() for line in view._markers]
    labels = view._marker_names

    assert pens[0] != pens[1]
    assert labels == [i18n.t("curveMarkerModel"), i18n.t("curveMarkerYou")]


def test_with_no_markers_there_is_nothing_to_send():
    view = _view()

    assert view.reading() == ""
    assert not view._send_btn.isEnabled()
    assert i18n.t("curveNoMarkers") in _tip(view._readout_btn)


def test_re_setting_traces_does_not_stack_up_legend_rows():
    """`addLegend` hands back the same item across `clear()`, so its rows survive unless dropped."""
    view = _view()
    before = len(view._legend.items)

    view.set_traces([Trace("sub_01 (sw)", *_impulse(9.6))])

    assert len(view._legend.items) == 1 <= before


class _FakeBridge:
    def __init__(self, raises: Exception | None = None) -> None:
        self._raises = raises
        self.asked: list[str] = []

    def find_id(self, name, exact: bool = True):
        if self._raises:
            raise self._raises
        self.asked.append(name)
        return name

    def by_name(self, name, exact: bool = True):
        """REW's own shape: ONE `GET /measurements` answers both "which id" and "what is on it",
        which is why the worker resolves this way — the timing reference comes out of the second
        half for no extra call."""
        return self.find_id(name, exact=exact), {"timeOfIRStartSeconds": 0.00518}

    def impulse_response(self, mid):
        xs, ys = _impulse(4.6)
        return [x / 1000.0 for x in xs], ys  # REW reports seconds; the panel plots ms


class _AnsweringBridge(_FakeBridge):
    """A REW that is IN THE MIDDLE of answering — the state every other fake here skips.

    `_FakeBridge` returns instantly, so a worker built on it is finished before anything can
    close over it, and F-027 could not be written down as a test. This one stops inside the call
    until the test lets it go, which is what a real `GET /measurements` does for as long as REW
    takes to reply.
    """

    def __init__(self) -> None:
        super().__init__()
        self.inside = threading.Event()
        self.release = threading.Event()

    def by_name(self, name, exact: bool = True):
        self.inside.set()
        self.release.wait(10)
        return super().by_name(name, exact=exact)


class _FrBridge(_FakeBridge):
    """REW's own answer shapes on the frequency-response endpoint: a sweep carries a phase, an
    MMM capture's comes back null (`rew-api-quirks.md`)."""

    def frequency_response(self, mid):
        freqs = [20.0 * (2 ** (i / 12.0)) for i in range(120)]
        return freqs, [80.0 - 0.001 * f for f in freqs], (None if "rta" in mid else [0.0] * 120)


def test_the_dialog_plots_what_rew_holds_in_milliseconds():
    _app()
    bridge = _FakeBridge()
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], markers=[4.6], bridge=bridge)
    dialog._worker.wait(4000)
    dialog._worker.run()  # synchronously, so the result is in hand rather than raced

    assert bridge.asked[-2:] == ["w-L_01 (sw)", "w-R_01 (sw)"]


def test_a_single_model_marker_gets_a_second_one_to_drag():
    """The Arbiter's marker starts ON the model's: dragging away from it IS the disagreement, so
    every millimetre of movement is deliberate."""
    _app()
    dialog = _dialog(["w-L_01 (sw)"], markers=[4.52], bridge=_FakeBridge())
    dialog._worker.wait(4000)

    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52))])

    assert dialog._view.positions() == [4.52, 4.52]


def test_rew_being_unreachable_is_a_message_not_a_crash():
    _app()
    dialog = _dialog(["w-L_01 (sw)"], bridge=_FakeBridge(ConnectionRefusedError("no REW")))
    dialog._worker.wait(4000)
    dialog._worker.run()

    assert "ConnectionRefusedError" in dialog._status.text()
    assert dialog._status.isVisibleTo(dialog)


def test_without_a_model_reading_the_markers_start_on_the_first_two_peaks():
    """The Arbiter can open this themselves, with nothing to argue against yet. Two markers parked
    at zero say nothing; markers on the peaks are a crude reading of the arrivals, which makes the
    delta meaningful before anything is touched — and an obvious guess invites correction.

    Numbered, not named after the curves: they are two PLACES the tuner is pointing at, and since
    2026-08-19 there are two of them whatever is plotted (`test_two_markers_whatever_the_trace_
    count`)."""
    _app()
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)

    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])

    positions = dialog._view.positions()
    assert abs(positions[0] - 4.52) < 0.05 and abs(positions[1] - 4.78) < 0.05
    assert dialog._view._marker_names == [i18n.t("curveMarkerOne"), i18n.t("curveMarkerTwo")]


def test_a_restored_delay_moves_the_opening_marker_with_the_curve_it_points_at():
    """The markers open on the peaks AS DRAWN. A driver that comes back with its banked delay is
    drawn where that delay put it, and a marker left on the raw arrival would point at the empty
    space the curve moved out of — with its level line, which reads the drawn curve, then starting
    off the peak (2026-08-19)."""
    from autosound_tcc.core import delay_bank

    delay_bank.put("w-R_01 (sw)", 0.4)
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)

    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])

    positions = dialog._view.positions()
    assert abs(positions[0] - 4.52) < 0.05, "the undelayed driver's peak, as before"
    assert abs(positions[1] - (4.78 + 0.4)) < 0.05, "the delayed driver's peak, where it is drawn"
    # ...and the Δ read between them is the DRAWN spread (the fixture samples every 0.04 ms, so
    # the second peak sits at 4.80 + 0.40).
    assert f"Δ {positions[1] - positions[0]:.3f} ms" in dialog._view.reading()
    assert "Δ 0.680 ms" in dialog._view.reading()


def test_on_a_frequency_view_the_pair_opens_inside_the_band_not_at_its_edges():
    """Max |y| of a response or a phase curve is a band edge — 20 Hz or 20 kHz — which is the one
    place nobody is pointing. So on the FR and the phase the pair opens at the geometric thirds of
    the band the view opens on: 200 Hz and 2 kHz, where a car's joints live (2026-08-19)."""
    _app()
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], kind="fr", bridge=_FrBridge())
    dialog._worker.wait(4000)

    dialog._on_curves([_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)")])

    positions = dialog._view.positions()
    assert positions[0] == pytest.approx(200.0, rel=0.01)
    assert positions[1] == pytest.approx(2000.0, rel=0.01)
    assert dialog._view._marker_names == [i18n.t("curveMarkerOne"), i18n.t("curveMarkerTwo")]


def test_the_choose_menu_moves_the_argument_to_another_measurement():
    """The two pair pickers are gone (user, 2026-08-18: "ці вибори не потрібні"); every single
    measurement goes on and off through the one checklist."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)", "m-L_01 (sw)"]
    dialog = _dialog(every[:2], bridge=_FakeBridge(), available=every)
    dialog._worker.wait(4000)

    dialog._choose_actions["w-R_01 (sw)"].setChecked(False)
    dialog._choose_actions["m-L_01 (sw)"].setChecked(True)
    dialog._worker.wait(4000)

    assert dialog._chosen() == ["w-L_01 (sw)", "m-L_01 (sw)"]


def test_one_curve_is_a_legitimate_thing_to_argue_about():
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FakeBridge(), available=every)
    dialog._worker.wait(4000)

    _chips(dialog)[1]._x.click()
    dialog._worker.wait(4000)

    assert dialog._chosen() == ["w-L_01 (sw)"]


# ---- what a measurement can actually show (user, 2026-08-11) ----------------------------------


def test_an_rta_capture_is_plotted_as_frequency_response_not_asked_for_an_impulse():
    """An MMM/RTA capture has no impulse response — REW answers HTTP 400 — and no phase — the
    field comes back null. The method suffix already says which kind a measurement is."""
    from autosound_tcc.ui.tcc.curve_dialog import kind_for

    assert kind_for(["w-L_01 (rta)", "w-R_01 (rta)"]) == "fr"
    assert kind_for(["w-L_01 (sw)", "w-R_01 (sw)"]) == "impulse"
    # An explicit `impulse` over an all-RTA selection is a request that cannot be honoured.
    assert kind_for(["w-L_01 (rta)"], "impulse") == "fr"
    # ...and neither can a MIXED one. One kind is plotted on one pair of axes, so the RTA half
    # decides for both -- this is the case the first fix missed (user: "in phase and impulse
    # mode, do not show RTA").
    assert kind_for(["w-L_01 (sw)", "w-R_01 (rta)"], "impulse") == "fr"
    assert kind_for(["w-L_01 (sw)", "w-R_01 (rta)"], "phase") == "fr"
    # A capture tagged with an experiment in flight is still an MMM capture: the suffix is not
    # always the last thing in the title.
    assert kind_for(["w-L_02 (rta) INV"], "impulse") == "fr"


def test_a_mixed_pair_shows_the_magnitude_instead_of_failing_on_the_rta_half():
    """One sweep and one MMM capture, opened on an impulse: the window used to fetch both, fail on
    the RTA half, and reach the Arbiter as "no phase in this measurement"."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (rta)"]
    dialog = _dialog(every, bridge=_FrBridge(), kind="impulse", available=every)
    dialog._worker.wait(4000)
    dialog._worker.run()

    assert dialog._kind == "fr"
    assert dialog._kind_combo.currentData() == "fr", "a picker reading `impulse` over an FR lies"
    assert dialog._chosen() == every, "the measurement the Arbiter chose is not dropped for it"
    assert "w-R_01 (rta)" in dialog._status.text(), "and the window says which one is the reason"
    assert dialog._status.isVisibleTo(dialog)


def test_two_mmm_captures_open_on_the_magnitude_which_is_all_they_hold():
    _app()
    every = ["w-L_01 (rta)", "w-R_01 (rta)"]
    dialog = _dialog(every, bridge=_FrBridge(), kind="impulse", available=every)
    dialog._worker.wait(4000)
    dialog._worker.run()

    assert dialog._kind == "fr"
    assert [t.name for t in dialog._view._traces] == every, "both are plotted, neither is dropped"
    assert all(title in dialog._status.text() for title in every)


def test_asking_for_phase_with_an_mmm_capture_on_screen_is_refused_in_words():
    """The kind switch has to do something explainable. It stays on the magnitude and names the
    measurement that decided it — the alternatives were a REW 400 and a silently dropped curve."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (rta)"]
    dialog = _dialog(every, bridge=_FrBridge(), available=every)
    dialog._worker.wait(4000)

    dialog._kind_combo.setCurrentIndex(dialog._kind_combo.findData("phase"))
    dialog._worker.wait(4000)
    dialog._worker.run()

    assert dialog._kind == "fr" and dialog._kind_combo.currentData() == "fr"
    assert dialog._chosen() == every
    assert "w-R_01 (rta)" in dialog._status.text()


def test_an_rta_row_is_absent_from_the_choose_menu_in_impulse_and_phase():
    """User, 2026-08-18, overruling this window's grey-out habit for THIS list: with an MMM
    capture chosen the window is on the magnitude by construction (`kind_for`), so in impulse or
    phase no MMM row can ever be the chosen one — and a row that can never be chosen is noise in
    a list holding a sweep and an MMM capture for every channel."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)", "w-R_01 (rta)"]
    dialog = _dialog(every[:2], bridge=_FrBridge(), kind="impulse", available=every)
    dialog._worker.wait(4000)

    assert "w-R_01 (rta)" not in dialog._choose_actions, "gone, not greyed"
    assert "w-L_01 (sw)" in dialog._choose_actions, "and the sweeps are all still there"

    dialog._kind_combo.setCurrentIndex(dialog._kind_combo.findData("phase"))
    dialog._worker.wait(4000)

    assert dialog._kind == "phase"
    assert "w-R_01 (rta)" not in dialog._choose_actions, "phase has none either"

    dialog._kind_combo.setCurrentIndex(dialog._kind_combo.findData("fr"))
    dialog._worker.wait(4000)

    action = dialog._choose_actions.get("w-R_01 (rta)")
    assert action is not None, "the magnitude is the one thing every capture holds, so it comes back"
    assert action.isEnabled()


def test_choosing_an_mmm_capture_brings_its_family_back_and_keeps_the_choice():
    """The list can only shorten itself safely if choosing FROM the short list still works. On the
    frequency response the MMM rows are there; ticking one must leave the window on it."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)", "w-R_01 (rta)"]
    dialog = _dialog(every[:2], bridge=_FrBridge(), kind="fr", available=every)
    dialog._worker.wait(4000)

    dialog._choose_actions["w-R_01 (sw)"].setChecked(False)
    dialog._choose_actions["w-R_01 (rta)"].setChecked(True)
    dialog._worker.wait(4000)

    assert dialog._kind == "fr", "an MMM capture decides the kind for the whole selection"
    assert dialog._choose_actions["w-R_01 (rta)"].isChecked(), "and the tick survives the refill"
    assert dialog._chosen() == ["w-L_01 (sw)", "w-R_01 (rta)"]


def test_the_kind_picker_shuts_impulse_and_phase_while_an_mmm_capture_is_in_the_pair():
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (rta)"]
    dialog = _dialog(every, bridge=_FrBridge(), available=every)
    dialog._worker.wait(4000)
    kinds = dialog._kind_combo

    shut = {str(kinds.itemData(row)) for row in range(kinds.count())
            if not kinds.model().item(row).isEnabled()}

    assert shut == {"impulse", "phase"}
    tip = kinds.itemData(kinds.findData("impulse"), Qt.ItemDataRole.ToolTipRole)
    assert tip == i18n.t("curveKindRtaTip")


def test_swapping_the_mmm_capture_for_a_sweep_puts_the_impulse_back_on_offer():
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)", "w-R_01 (rta)"]
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (rta)"], bridge=_FrBridge(), available=every)
    dialog._worker.wait(4000)

    dialog._choose_actions["w-R_01 (rta)"].setChecked(False)
    dialog._choose_actions["w-R_01 (sw)"].setChecked(True)
    dialog._worker.wait(4000)
    dialog._worker.run()

    kinds = dialog._kind_combo
    assert all(kinds.model().item(row).isEnabled() for row in range(kinds.count()))
    # Still on the magnitude, because that is where the Arbiter is: the kind does not jump back
    # on its own, it only stops being refused.
    assert dialog._kind == "fr" and not dialog._status.text()


def test_marker_positions_are_hz_not_log_hz():
    """pyqtgraph's log mode transforms the DATA and leaves markers in view coordinates, so a
    marker placed at 96.6 Hz landed at 10^96.6 and the axis ran to 1e+27 (seen on the first RTA
    plot)."""
    view = _view()
    view.set_unit("Hz")
    view.set_log_x(True)
    view.set_markers([100.0, 1000.0])

    assert view.positions() == pytest.approx([100.0, 1000.0], rel=1e-6)
    assert "100.0 Hz" in view.reading() and "Δ 900.0 Hz" in view.reading()


def test_one_curve_rew_cannot_produce_does_not_take_the_other_off_the_screen():
    """Tested on the worker rather than through the dialog: the dialog no longer ASKS for an
    impulse over a pair with an MMM capture in it, but REW can still refuse any single curve for
    its own reasons, and the one it can produce must reach the screen anyway."""
    _app()

    class _HalfBroken(_FakeBridge):
        def impulse_response(self, mid):
            if "rta" in mid:
                raise RuntimeError("HTTP Error 400: Bad Request")
            return super().impulse_response(mid)

    worker = _CurveWorker(_HalfBroken(), ["w-L_01 (sw)", "w-R_01 (rta)"], "impulse")
    got = []
    worker.done.connect(got.append)
    worker.run()

    assert [t.name for t in got[-1]] == ["w-L_01 (sw)"]


def test_the_impulse_opens_on_the_arrival_not_on_three_seconds_of_room():
    """A REW impulse spans −995 ms to +1735 ms. Auto-ranged, the two millimetres the argument is
    about are a vertical line."""
    _app()
    dialog = _dialog(["w-L_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)

    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52, n=4000, span=200.0))])

    low, high = dialog._view._plot.viewRange()[0]
    assert high - low < 12, "the view must open on the peak, not on the whole capture"
    assert low < 4.52 < high


# ---- reading the axis, and reading levels off it (user, 2026-08-11) ---------------------------


def test_the_frequency_axis_speaks_the_trade_s_own_numbers():
    """pyqtgraph's log axis prints `2·10¹`, `3·10¹`, `4·10¹` … which at audio widths collide into
    a smear. Nobody says "the null at four times ten to the second"."""
    from autosound_tcc.ui.tcc.curve_view import LogHzAxis

    axis = LogHzAxis(orientation="bottom")
    axis.tickValues(math.log10(20), math.log10(20000), 1400)  # decides which values get a label

    strings = axis.tickStrings([math.log10(v) for v in (20, 100, 1000, 2000, 20000)], 1, 1)

    assert strings == ["20", "100", "1k", "2k", "20k"]


def test_the_axis_thins_labels_and_never_the_grid_lines():
    """User, 2026-08-18, with REW's axis beside ours: a grid is what lets a frequency be read
    without a label under it. Crowding is a problem for TEXT — a 1-pixel line has room at any
    width — so the two used to thin together and the picture lost its ruler exactly when the
    window got narrow enough to need one."""
    from autosound_tcc.ui.tcc.curve_view import LogHzAxis

    axis = LogHzAxis(orientation="bottom")
    lo, hi = math.log10(20), math.log10(20000)

    def lines_and_labels(size):
        levels = axis.tickValues(lo, hi, size)
        lines = sum(len(group) for _, group in levels)
        labels = sum(
            1 for _step, group in levels for text in axis.tickStrings(group, 1, 1) if text
        )
        return lines, labels

    roomy_lines, roomy_labels = lines_and_labels(1400)
    cramped_lines, cramped_labels = lines_and_labels(200)

    assert cramped_labels < roomy_labels, "a label with no room overprints the one that had room"
    assert cramped_lines == roomy_lines, "the grid is the same ruler at either width"
    assert cramped_labels >= 3, "and something is still named, or the ruler has no origin"


def test_the_grid_has_two_weights_the_way_rews_does():
    """Decades heavier, the 2-3-4-5-6-8 ladder between them fainter but present — that ladder is
    what makes 300 Hz findable on a picture whose labels stop at 100 and 1k."""
    from autosound_tcc.ui.tcc.curve_view import LogHzAxis

    axis = LogHzAxis(orientation="bottom")

    levels = dict(axis.tickValues(math.log10(20), math.log10(20000), 900))

    assert [round(10 ** v) for v in levels[0]] == [100, 1000, 10000], "the decades, alone"
    ladder = [round(10 ** v) for v in levels[1]]
    for hz in (20, 30, 50, 200, 500, 2000, 5000, 20000):
        assert hz in ladder, f"{hz} Hz has no grid line"


def test_horizontal_markers_read_the_level_and_start_on_the_curve():
    """On an FR the question is as often "how many dB is that dip" as "at what frequency"."""
    view = _view()
    view.set_unit("Hz")
    view.set_y_unit("dB")
    view.set_markers([4.52, 4.78], tokens=["accent", "info"])

    view.set_axes_mode("vh")

    assert len(view.levels()) == 2
    # Each one sits on ITS OWN curve's value at that x — a line parked at zero answers nothing.
    assert view.levels()[0] == pytest.approx(view._y_at(0, 4.52), abs=1e-9)
    reading = view.reading()
    assert "Hz" in reading and "dB" in reading


def test_switching_to_levels_only_keeps_the_positions_already_placed():
    view = _view()
    view.set_markers([4.52, 4.78], tokens=["accent", "info"])

    view.set_axes_mode("h")
    view.set_axes_mode("vh")

    assert view.positions() == pytest.approx([4.52, 4.78])


def test_in_sync_mode_one_point_gives_both_coordinates():
    """VHs: the level is not a second thing to place — it IS the curve's value where the vertical
    marker stands, and it follows when that marker moves."""
    view = _view()
    view.set_unit("Hz")
    view.set_y_unit("dB")
    view.set_markers([4.52, 4.78], tokens=["accent", "info"])

    view.set_axes_mode("vhs")
    view._markers[0].setValue(5.30)

    assert view.levels()[0] == pytest.approx(view._y_at(0, 5.30), abs=1e-9)
    # ...and it cannot be dragged apart from its own vertical, which would let one reading
    # disagree with itself.
    assert view._h_markers[0].movable is False


def test_plain_vh_still_places_the_two_halves_independently():
    view = _view()
    view.set_markers([4.52, 4.78], tokens=["accent", "info"])
    view.set_axes_mode("vh")

    view._h_markers[0].setValue(0.25)
    view._markers[0].setValue(5.30)

    assert view.levels()[0] == pytest.approx(0.25), "VH must not follow the curve"
    assert view._h_markers[0].movable is True


def test_the_unit_sits_with_the_numbers_not_under_the_axis():
    """A whole row of window was going on one centred word; the readout wanted it."""
    view = _view()
    view.set_unit("Hz")
    view.set_y_unit("dB")
    view.set_markers([100.0, 200.0], tokens=["accent", "info"])

    view.set_axes_mode("v")
    assert view._unit_label.text() == "Hz"
    view.set_axes_mode("vh")
    assert view._unit_label.text() == "Hz/dB"
    view.set_axes_mode("h")
    assert view._unit_label.text() == "dB"


def test_the_plot_repaints_when_the_theme_changes():
    """Everything else in the app repaints from the stylesheet; a plot draws with explicit pens
    and keeps the colours it was built with — a light plot sitting in a dark window (user,
    2026-08-11)."""
    from autosound_tcc.ui.tcc.theme import apply_theme

    app = _app()
    apply_theme(app, "light")
    view = _view()
    view.set_markers([4.52, 4.78], tokens=["accent", "info"])
    light_bg = view._plot.backgroundBrush().color().name()
    light_pen = view._markers[0].pen.color().name()

    apply_theme(app, "dark")
    view.apply_theme()

    assert view._plot.backgroundBrush().color().name() != light_bg
    assert view._markers[0].pen.color().name() != light_pen
    # ...and the reading survives the repaint: a theme switch must not move a marker.
    assert view.positions() == pytest.approx([4.52, 4.78])
    apply_theme(app, "light")


def test_pyqtgraphs_own_context_menu_is_not_offered():
    """It is a native QMenu of unstyled spin boxes — white-on-white in the dark theme — and it
    offers nothing the A/D/−/+ buttons do not."""
    view = _view()

    assert view._plot.getPlotItem().vb.menuEnabled() is False


def test_the_reading_that_is_sent_carries_no_markup():
    """It goes into a chat message. `<br>` in one is markup the model has to see through — the
    label does its own conversion."""
    view = _view()
    view.set_y_unit("dB")
    view.set_markers([4.52, 4.78], tokens=["accent", "info"])
    view.set_axes_mode("vh")

    sent = view.reading()

    assert "<br>" not in sent and "<" not in sent
    assert "\n" not in sent, "one line: the row is full width now, and there is room"


def test_pyqtgraphs_plot_options_menu_is_never_filled_in():
    """The segfault, in test form.

    Every `PlotItem` used to add six `QWidgetAction`s to six submenus, and adding a
    Python-created action to a QMenu is where the process died — 5 crashes in 40 runs of the
    plot-heavy files, 0 in 40 once the submenus stopped being built (measured 2026-08-13, see
    `_do_not_build_the_plot_options_menu`). The menu is disabled twice over and never shown, so
    an empty one costs nothing; what must keep working is `ctrl`, which the plot itself reads.
    """
    view = _view()
    item = view._plot.getPlotItem()

    assert item.ctrlMenu.actions() == [], "a filled menu means the patch stopped applying"
    # ...and the control form the plot actually uses is untouched: these four calls read it.
    view._plot.showGrid(x=True, y=True, alpha=0.18)
    view._plot.setDownsampling(auto=True, mode="peak")
    view._plot.setClipToView(True)
    view.set_log_x(True)
    assert item.ctrl.gridAlphaSlider is not None
    assert view._plot.getPlotItem().vb.menuEnabled() is False


def test_pyqtgraphs_own_auto_range_button_is_not_offered_either():
    """It parks an unlabelled "A" square on top of the data whenever the view is not auto-ranged,
    beside our own A button that says what it does."""
    view = _view()

    assert view._plot.getPlotItem().autoBtn.isVisible() is False


# ---- one line, both curves (user, 2026-08-12) -------------------------------------------------


def test_vx_reads_both_curves_at_one_x_and_the_gap_between_them():
    """"At 2.5 kHz the channels are 6 dB apart" is a single fact about a PAIR, and the per-curve
    markers cannot state it — there the two markers are in different places."""
    view = _view()
    view.set_y_unit("dB")
    view.set_markers([4.52, 4.78], tokens=["accent", "info"])

    view.set_axes_mode("vx")

    crossings = view.crossings()
    assert [x for x, _y in crossings] == [4.52, 4.52], "one x, read on both curves"
    assert crossings[0][1] == pytest.approx(view._y_at(0, 4.52))
    assert crossings[1][1] == pytest.approx(view._y_at(1, 4.52))
    assert "Δ" in view.reading() and "dB" in view.reading()
    # One vertical line, not two: a second would be a second question.
    assert [line.isVisible() for line in view._markers] == [True, False]


def test_hx_reads_where_each_curve_reaches_one_level():
    view = _view()
    view.set_y_unit("dB")
    view.set_markers([4.52, 4.78], tokens=["accent", "info"])

    view.set_axes_mode("hx")
    view._h_markers[0].setValue(0.0)

    crossings = view.crossings()
    assert len(crossings) == 2
    assert all(abs(y) < 1e-9 for _x, y in crossings), "both readings are AT the level"
    assert crossings[0][0] != crossings[1][0], "each curve reaches it somewhere else"
    assert view.reading().startswith(i18n.t("curveAt"))
    assert not any(line.isVisible() for line in view._markers), "no vertical line in Hx"


def test_a_level_no_curve_ever_reaches_reads_as_nothing_rather_than_a_wrong_number():
    view = _view()
    view.set_markers([4.52], tokens=["accent"])
    view.set_axes_mode("hx")

    view._h_markers[0].setValue(50.0)  # far above any sample

    assert view.crossings() == []
    assert view.reading() == ""


def test_double_click_fetches_strayed_markers_back_into_view():
    """After a zoom the markers are usually off-screen, and hunting for them costs more than the
    zoom was worth (user, 2026-08-12)."""
    view = _view()
    view.set_markers([4.52, 4.78], tokens=["accent", "info"])
    view.focus_x(20.0, 30.0)  # zoomed somewhere else entirely

    view.bring_markers_into_view()

    low, high = view._plot.viewRange()[0]
    assert all(low <= p <= high for p in view.positions()), view.positions()
    assert view.positions()[0] != view.positions()[1], "two strays must not land on each other"


def test_a_marker_already_in_view_is_not_moved():
    """Moving a reading nobody asked to move would destroy the answer being read."""
    view = _view()
    view.set_markers([4.52, 4.78], tokens=["accent", "info"])
    view.focus_x(4.0, 5.0)

    view.bring_markers_into_view()

    assert view.positions() == pytest.approx([4.52, 4.78])


def test_the_guides_are_drawn_heavier_than_the_traces():
    """At trace weight a guide vanishes into a dense impulse — 262 144 points is a solid block of
    pixels, and a 1 px line over it is not a line."""
    view = _view()
    view.set_markers([4.52], tokens=["accent"])

    assert view._markers[0].pen.widthF() > 1.4


# ---- delaying one trace to meet the other (user, 2026-08-12) ----------------------------------


def test_every_driver_carries_its_own_delay():
    """The pair is not the unit of alignment; the car is. Each driver is placed against the same
    origin (x = 0), and only then do the numbers agree with each other (user, 2026-08-12)."""
    view = _view()
    view.set_unit("ms")
    view.set_delay_target(1)

    view.set_delay(0.198)

    x0, _ = view._shifted(0, view._traces[0])
    x1, _ = view._shifted(1, view._traces[1])
    assert x0[0] == pytest.approx(view._traces[0].x[0]), "the other curve does not move"
    assert x1[0] == pytest.approx(view._traces[1].x[0] + 0.198)

    view.set_delay_target(0)
    view.set_delay(0.5)

    x0, _ = view._shifted(0, view._traces[0])
    x1, _ = view._shifted(1, view._traces[1])
    assert x0[0] == pytest.approx(view._traces[0].x[0] + 0.5)
    assert x1[0] == pytest.approx(view._traces[1].x[0] + 0.198), "and keeps its own"
    assert view.delays() == pytest.approx([0.5, 0.198])


def test_switching_driver_moves_nothing_and_shows_that_driver_s_number():
    """The bug in the picture: 1.200 ms on tw-L, click the radio, and the two curves were suddenly
    2.4 ms apart — the amount had been carried across instead of each driver keeping its own."""
    view = _view()
    view.set_unit("ms")
    view.set_delay_target(1)
    view.set_delay(1.2)
    before = view._shifted(1, view._traces[1])[0][0]

    view.set_delay_target(0)

    assert view._shift_box.value() == pytest.approx(0.0), "driver 0 has no delay of its own"
    assert view._shifted(1, view._traces[1])[0][0] == pytest.approx(before), "nothing moved"
    assert view._shifted(0, view._traces[0])[0][0] == pytest.approx(view._traces[0].x[0])


def test_a_negative_delay_is_a_correction_not_an_error():
    """User, 2026-08-12: "давай відʼємні залишимо — буває дуже корисно, коли підправляєш на
    наступних кроках". On a later pass the channel already carries a delay; taking time back off
    it is an ordinary move. The limit is on the SUM, not on this number."""
    view = _view()
    view.set_unit("ms")

    view.set_delay(-0.15)

    assert view._shift_ms == pytest.approx(-0.15)
    assert view._shift_box.minimum() < 0
    x0, _ = view._shifted(0, view._traces[0])
    assert x0[0] == pytest.approx(view._traces[0].x[0] - 0.15), "and it moves the curve earlier"


def test_the_total_is_checked_against_what_the_channel_already_has():
    """"головне щоб загалом не йшло менш нуля" — and only the caller knows what is in there.

    On ONE curve, because that is the only place a negative proposal survives now: with two or
    more, the set is stated from its own minimum (`proposed_delays`), so it can never ask a
    channel to give back time it does not have. That is a consequence worth knowing, and
    `test_taking_the_common_part_off_is_what_makes_a_set_applicable` is where it is asserted.
    """
    view = _view()
    view.set_traces([Trace("w-L_01 (sw)", *_impulse(4.52))])
    view.set_unit("ms")
    view.set_markers([4.52], tokens=["accent"])
    view.set_channel_delay(1.2)

    view.set_delay(-0.15)

    assert view.total_delay_ms() == pytest.approx(1.05)
    assert "1.050" in view.reading()
    assert i18n.t("curveDelayBelowZero") not in view.reading()

    view.set_delay(-2.0)

    assert i18n.t("curveDelayBelowZero") in view.reading(), "stated, not silently prevented"


def test_an_unknown_current_delay_is_not_reported_as_zero():
    """"this channel sits at 0.0" and "nobody told me" lead to opposite conclusions about a
    −0.15 ms proposal, so the panel states a total only when it has one."""
    view = _view()
    view.set_unit("ms")
    view.set_markers([4.52], tokens=["accent"])

    view.set_delay(-0.15)

    assert view.total_delay_ms() is None
    assert i18n.t("curveDelayBelowZero") not in view.reading()
    assert "ms" in view.reading(), "the reading itself is still there"


def test_the_delay_starts_on_whichever_trace_arrives_first():
    """The only one a DSP can actually hold back."""
    view = _view()
    view.set_unit("ms")

    assert view.delay_target() == 0, "w-L peaks at 4.52 ms, w-R at 4.78"

    xl, yl = _impulse(5.9)
    xr, yr = _impulse(4.3)
    view.set_traces([Trace("late", xl, yl), Trace("early", xr, yr)])

    assert view.delay_target() == 1


def test_a_new_pair_starts_the_argument_over():
    """Carrying 0.198 ms onto two curves it was never measured from would be the panel inventing a
    proposal nobody made."""
    view = _view()
    view.set_unit("ms")
    view.set_delay(0.198)

    xl, yl = _impulse(2.0)
    xr, yr = _impulse(3.0)
    view.set_traces([Trace("m-L_02", xl, yl), Trace("m-R_02", xr, yr)])

    assert view._shift_ms == 0.0
    assert view._shift_box.value() == pytest.approx(0.0)


def test_on_a_phase_plot_the_same_delay_is_a_ramp():
    """A pure delay is φ = −360·f·Δt, exactly. That direction is arithmetic; reading a delay off a
    wrapped phase curve is the hard one, and this does not attempt it."""
    view = _view()
    view.set_unit("Hz")
    view.set_y_unit("°")
    view.set_traces([Trace("a", [100.0, 1000.0], [0.0, 0.0]),
                     Trace("b", [100.0, 1000.0], [0.0, 0.0])])
    view.set_delay_target(1)

    view.set_delay(1.0)  # 1 ms

    _x, y = view._shifted(1, view._traces[1])
    # −360 × 100 Hz × 0.001 s = −36°, and −360° at 1 kHz wraps to 0°.
    assert y[0] == pytest.approx(-36.0, abs=1e-6)
    assert y[1] == pytest.approx(0.0, abs=1e-6)


def test_a_magnitude_response_does_not_move_when_you_delay_it():
    view = _view()
    view.set_unit("Hz")
    view.set_y_unit("dB")
    view.set_delay_target(1)
    before = list(view._traces[1].y)

    view.set_delay(2.0)

    _x, y = view._shifted(1, view._traces[1])
    assert list(y) == pytest.approx(before)


def test_the_delay_is_read_in_milliseconds_and_in_samples():
    """Helix takes 0.01 ms in its box but resolves samples, so consecutive typed steps sometimes
    land on the same sample and sometimes skip one (user, 2026-08-12). Stating both is what makes
    that visible instead of mysterious."""
    view = _view()
    view.set_unit("ms")
    view.set_resolution(0.01, 96000)
    view.set_delay_target(1)

    view.set_delay(0.198)
    reading = view.reading()

    assert "w-R_01 (sw)" in reading and "0.198" in reading
    assert "19 smp" in reading
    assert view._shift_box.singleStep() == pytest.approx(0.01)


def test_without_a_processing_rate_the_reading_is_milliseconds_alone():
    """MUSWAY's own box goes to thousandths on a step nobody here has confirmed. A samples figure
    invented from a guessed rate would be a number the Arbiter could act on and shouldn't."""
    view = _view()
    view.set_unit("ms")
    view.set_resolution(0.001, None)
    view.set_delay_target(1)

    view.set_delay(0.198)

    assert view.samples(0.198) is None
    assert "smp" not in view.reading()


def test_closing_the_window_while_rew_is_answering_does_not_take_the_process_with_it(monkeypatch):
    """F-027. The window used to wait four seconds for its worker and then close ANYWAY — and Qt
    answers a QThread destroyed while running with `qFatal`, which is `abort()`, not an exception.
    So the failure needed REW to be genuinely answering, which is the ORDINARY case in the car:
    two `exit=134` in one day with REW up, none at all with it down.

    The third option is the one `qt_shutdown` already found at application exit: let it go. The
    window closes now, the worker finishes its one call into a set nothing reads, and drops itself.
    """
    from autosound_tcc.ui.tcc import curve_dialog as cd
    from autosound_tcc.ui.tcc import qt_shutdown

    monkeypatch.setattr(cd, "_WORKER_WAIT_MS", 50)  # the wait is bounded; here it is just short
    bridge = _AnsweringBridge()
    dialog = _dialog(["w-L_01 (sw)"], bridge=bridge)
    assert bridge.inside.wait(5), "the worker has to be INSIDE the call, or this proves nothing"
    worker = dialog._worker

    dialog.close()

    assert worker.isRunning(), "still answering — this is the case that used to abort()"
    assert dialog._worker is None, "the window no longer holds it"
    assert worker in qt_shutdown.detached(), "and qt_shutdown does, so Qt never destroys it"

    bridge.release.set()
    assert worker.wait(5000), "it finishes on its own time"
    _app().processEvents()  # `finished` comes back queued, like every cross-thread signal here
    assert worker not in qt_shutdown.detached(), "and is forgotten once it has"


@pytest.mark.parametrize("key", ["dsp_processing_rate_hz", "sample_rate_hz"])
def test_the_processing_rate_is_read_under_either_of_its_two_names(key):
    """The rename of 2026-08-25 arrives with the method, not with us.

    The panel used to read `profile.get("sample_rate_hz")`. A profile written after the rename
    carries only `dsp_processing_rate_hz`, so that `get` would answer `None` — and `None` here is
    not an error, it is the documented "no rate on record" state: the samples simply stop being
    printed beside the milliseconds. Nothing raises, no test fails, and the Arbiter loses a column
    without being told. This is the test that would have caught it, and it takes both names
    because the legacy one is still what an older installed skill writes.
    """
    import json

    from autosound_tcc.core import config

    config.dsp_profile_path().write_text(
        json.dumps({"dsp_profile": {"delay": {"step_ms": 0.01}, key: 96000}}), encoding="utf-8"
    )
    dialog = _dialog(["w-L_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)

    dialog._apply_delay_resolution()

    assert dialog._processing_rate_hz() == 96000.0
    assert dialog._view.samples(0.198) == 19


def test_the_delay_is_sent_as_a_proposal_not_as_a_change():
    """The panel changes nothing. The sentence goes to the composer, the Arbiter sends it, and the
    delta is banked 🟡 like every other proposed change."""
    view = _view()
    view.set_unit("ms")
    view.set_markers([4.52, 4.78], tokens=["accent", "info"])

    view.set_delay(0.198)
    reading = view.reading()

    assert "w-L_01 (sw)" in reading, "the earlier arrival is the one being held back"
    assert "proposed" in reading or "пропозиц" in reading


def test_no_delay_says_nothing_about_delaying():
    view = _view()
    view.set_markers([4.52], tokens=["accent"])

    assert "delay" not in view.reading().lower()


def test_a_delay_set_in_code_shows_in_the_control():
    """The model can open this window with a proposal of its own. A box reading 0.000 beside a
    curve that has visibly moved is the panel disagreeing with itself."""
    view = _view()
    view.set_unit("ms")

    view.set_delay(0.198)

    assert view._shift_box.value() == pytest.approx(0.198)
    # ...and setting it again from the control must not recurse through the same setter.
    view._shift_box.setValue(0.25)
    assert view._shift_ms == pytest.approx(0.25)


# ---- the delay bank (user, 2026-08-12) --------------------------------------------------------


def test_a_delay_is_kept_against_the_measurement_it_was_read_on():
    """Aligning a car is six pairs, not one, and this window used to drop each reading as the next
    pair loaded — "було б здорово мати збереження затримки по кожному каналу"."""
    from autosound_tcc.core import delay_bank

    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])

    dialog._view.set_delay(0.26)

    assert delay_bank.load() == {"w-L_01 (sw)": 0.26}, "banked against the trace being held back"


def test_a_driver_brings_its_delay_with_it_wherever_it_is_plotted():
    """The bank is per driver, so a channel already placed keeps its position when it turns up
    against a different partner — which is what makes the whole set consistent."""
    from autosound_tcc.core import delay_bank

    delay_bank.put("w-R_01 (sw)", 0.4)
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)

    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])

    assert dialog._view.delays() == pytest.approx([0.0, 0.4])
    x1, _ = dialog._view._shifted(1, dialog._view._traces[1])
    assert x1[0] == pytest.approx(dialog._view._traces[1].x[0] + 0.4), "drawn where it belongs"
    assert delay_bank.load() == {"w-R_01 (sw)": 0.4}, "and restoring banked nothing new"


def test_the_choose_menu_shows_what_each_measurement_already_carries():
    """Where the Arbiter chooses what to look at next is where they need to see that this channel
    has already been read once."""
    from autosound_tcc.core import delay_bank

    delay_bank.put("w-R_01 (sw)", 0.4)
    every = ["w-L_01 (sw)", "w-R_01 (sw)", "m-L_01 (sw)"]
    dialog = _dialog(every[:2], bridge=_FakeBridge(), available=every)
    dialog._worker.wait(4000)
    dialog._render_bank()

    assert "+0.400 ms" in dialog._choose_actions["w-R_01 (sw)"].text()
    assert dialog._choose_actions["m-L_01 (sw)"].text() == "m-L_01 (sw)", "untouched stays plain"


def test_zero_forgets_the_entry_rather_than_banking_a_zero():
    """"needs no delay" and "not looked at yet" are different claims, and only the second is
    honest about a curve nobody opened."""
    from autosound_tcc.core import delay_bank

    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])
    dialog._view.set_delay(0.26)

    dialog._view.set_delay(0.0)

    assert delay_bank.load() == {}


def test_the_whole_set_goes_out_for_analysis_and_says_it_is_not_a_change():
    """User, 2026-08-12: "відправити на аналіз ШІ (не для запису)". Two more gates stand between
    a reading and any hardware, and this is not one of them."""
    from autosound_tcc.core import delay_bank

    delay_bank.put("w-L_01 (sw)", 0.198)
    delay_bank.put("m-L_01 (sw)", 1.25)
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog._view.set_resolution(0.01, 96000)
    dialog._render_bank()
    sent: list[str] = []
    dialog.readingSent.connect(sent.append)

    dialog._bank_ask_btn.click()

    assert len(sent) == 1
    # Banked at +0.198 and +1.250, PROPOSED with the common part off: only the 1.052 ms between
    # them was ever measured. See `curve_view.proposed_delays`.
    assert "w-L_01 (sw): +0.000 ms (+0 smp)" in sent[0]
    assert "m-L_01 (sw): +1.052 ms (+101 smp)" in sent[0]
    assert i18n.t("curveDelayRelative").format(name="w-L_01 (sw)") in sent[0]
    assert i18n.t("curveBankNotForWriting") in sent[0], "it says it is not to be written"


def test_with_nothing_banked_there_is_nothing_to_analyse():
    dialog = _dialog(["w-L_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog._render_bank()

    assert not dialog._bank_ask_btn.isEnabled()
    assert i18n.t("curveBankEmpty") in _tip(dialog._bank_btn)
    assert dialog._bank_btn.text() == i18n.t("curveBankBtn").format(n=0)


def test_both_drivers_on_screen_are_banked_each_with_its_own():
    from autosound_tcc.core import delay_bank

    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])

    dialog._view.set_delay(0.26)
    dialog._view.set_delay_target(1)
    dialog._view.set_delay(0.1)

    assert delay_bank.load() == {"w-L_01 (sw)": 0.26, "w-R_01 (sw)": 0.1}


def test_a_delay_banked_on_another_pair_is_left_alone():
    """Two alignments are two independent facts. w-L waiting 0.198 for the midbass and w-R waiting
    0.26 for w-L can both be true, and the window must not tidy one of them away."""
    from autosound_tcc.core import delay_bank

    delay_bank.put("m-L_01 (sw)", 1.1)
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])

    dialog._view.set_delay(0.26)
    dialog._view.set_delay_target(1)

    assert delay_bank.load() == {"m-L_01 (sw)": 1.1, "w-L_01 (sw)": 0.26}


def test_the_ledger_join_is_a_split_not_a_guess():
    """`w-L_02 (sw)` → `w-L`, which is the key a real snapshot uses for its channels."""
    from autosound_tcc.core import delay_bank
    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup

    assert delay_bank.code_of("w-L_02 (sw)") == "w-L"
    assert delay_bank.code_of("tw-R_01") == "tw-R"

    class _View:
        groups = (
            ProfileGroup(id="physical_outputs", label="Outputs", fields=("ta_ms",), rows=(
                GroupRow(id="m-L", name="m-L", raw={"ta_ms": 1.266}, slot="E"),
                GroupRow(id="w-L", name="w-L", raw={"ta_ms": 0.0}, slot="C"),
                GroupRow(id="c", name="c", raw={}, slot="A"),
            )),
        )

    delays = delay_bank.current_delays(_View())
    assert delays == {"m-L": 1.266, "w-L": 0.0}
    assert "c" not in delays, "no delay field is 'unknown', not zero"


def test_taking_the_common_part_off_is_what_makes_a_set_applicable():
    """The same alignment, stated from its own earliest driver, is always enterable — which is the
    point of normalising rather than a side effect of it.

    Raw, this set asked w-L to give back half a millisecond it did not have (0.100 − 0.500 = −0.400
    on the channel) and would have been refused. Every difference in it is preserved: the two
    drivers are 0.750 ms apart before and after.
    """
    from autosound_tcc.core import delay_bank

    text = delay_bank.as_sentence(
        {"w-L_01 (sw)": -0.5, "m-L_01 (sw)": 0.25},
        processing_rate_hz=96000,
        lang_t=i18n.t,
        current=lambda title: {"w-L_01 (sw)": 0.1, "m-L_01 (sw)": 1.0}.get(title),
    )

    assert "w-L_01 (sw): +0.000 ms (+0 smp) | channel 0.100 → 0.100 ms" in text
    assert "m-L_01 (sw): +0.750 ms (+72 smp) | channel 1.000 → 1.750 ms" in text, "0.750 apart"
    assert i18n.t("curveDelayBelowZero") not in text, "nothing is being asked for that it cannot do"
    assert i18n.t("curveBankImpossible") not in text
    assert i18n.t("curveDelayRelative").format(name="w-L_01 (sw)") in text


def test_a_set_that_cannot_be_applied_still_says_so_before_the_model_has_to_notice():
    """The guard stays, and one driver is where it can still fire: with nothing to be relative to
    there is no common part to take off, so a negative reading reaches the channel as it was read."""
    from autosound_tcc.core import delay_bank

    text = delay_bank.as_sentence(
        {"w-L_01 (sw)": -0.5},
        processing_rate_hz=96000,
        lang_t=i18n.t,
        current=lambda title: {"w-L_01 (sw)": 0.1}.get(title),
    )

    assert "w-L_01 (sw): -0.500 ms (-48 smp) | channel 0.100 → -0.400 ms" in text
    assert i18n.t("curveDelayBelowZero") in text
    assert i18n.t("curveBankImpossible") in text


def test_with_no_ledger_the_lines_are_readings_alone():
    """Honest about what TCC knows: no invented totals for a project whose ledger is not loaded."""
    from autosound_tcc.core import delay_bank

    text = delay_bank.as_sentence({"w-L_01 (sw)": -0.5}, lang_t=i18n.t)

    assert "w-L_01 (sw): -0.500 ms" in text
    assert "→" not in text
    assert i18n.t("curveBankImpossible") not in text


def test_the_window_reads_the_ledger_fresh_every_time_it_is_asked():
    """The window is open across a whole pass; a snapshot taken when it opened would be checking
    tonight's proposal against an hour-old ledger."""
    from autosound_tcc.core import delay_bank

    ledger = {"w-L": 1.0}
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog.set_delays_provider(lambda: dict(ledger))
    # One curve: a negative proposal is rebased away the moment there are two of them to be
    # relative to, and what this test is about is the ledger being re-read, not the sign.
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52))])

    dialog._view.set_delay(-0.2)
    assert dialog._view.total_delay_ms() == pytest.approx(0.8)

    ledger["w-L"] = 0.1
    dialog._sync_channel_delay()

    assert dialog._view.total_delay_ms() == pytest.approx(-0.1)
    assert i18n.t("curveDelayBelowZero") in dialog._view.reading()


def test_an_impossible_total_is_coloured_not_just_worded():
    """A warning inside a sentence made of numbers is read last — and since 2026-08-18 the
    sentence is behind a hover, so the colour has to be on the BUTTON as well as in the text.

    One curve, for the reason `test_the_total_is_checked_against_what_the_channel_already_has`
    gives: a set of two or more is always stated from its own minimum and cannot go below zero.
    """
    view = _view()
    view.set_traces([Trace("w-L_01 (sw)", *_impulse(4.52))])
    view.set_unit("ms")
    view.set_markers([4.52], tokens=["accent"])
    view.set_channel_delay(0.1)

    warn = current_theme().warn

    view.set_delay(-0.5)

    assert warn in view._readout_btn.styleSheet(), "on the button, where it is seen unhovered"
    assert warn in view._readout_btn.hover_tip.text(), "and in the sentence it belongs to"

    view.set_delay(0.5)

    assert view._readout_btn.styleSheet() == ""
    assert warn not in view._readout_btn.hover_tip.text()


def test_the_set_states_what_the_numbers_are_measured_from():
    """User, 2026-08-12: "привʼязка повинна бути до 0 осі Х, а затримка відносно позиції як було
    знято при змірі". A set of deltas with no origin cannot be checked, and being checkable is the
    only reason it is sent."""
    from autosound_tcc.core import delay_bank

    text = delay_bank.as_sentence(
        {"tw-L_01 (sw)": 1.2, "m-R_01 (sw)": 1.18},
        processing_rate_hz=96000,
        lang_t=i18n.t,
        at={"tw-L_01 (sw)": 2.95, "m-R_01 (sw)": 4.12},
    )

    assert i18n.t("curveBankConvention") in text
    # Both banked around 1.19 ms; proposed with the common 1.18 removed, so the landings move down
    # by exactly that and the SPREAD — the number the set is judged on — does not move at all.
    assert "arrival 2.950 → 2.970 ms" in text
    assert "arrival 4.120 → 4.120 ms" in text
    assert "1.150 ms" in text, "and how far from aligned that leaves them"


def test_the_arrival_is_banked_with_the_delay_and_survives_a_reload():
    from autosound_tcc.core import delay_bank

    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])

    dialog._view.set_delay(0.26)

    assert delay_bank.arrivals()["w-L_01 (sw)"] == pytest.approx(4.52, abs=0.05)


def test_an_older_bank_of_bare_numbers_still_reads():
    """The first version wrote `{"w-L_01 (sw)": 0.198}`. A schema change that silently emptied a
    tuner's afternoon would be worse than the feature is worth."""
    from autosound_tcc.core import config, delay_bank, project_settings

    project_settings.set_value(config.tcc_dir(), delay_bank.KEY, {"w-L_01 (sw)": 0.198})

    assert delay_bank.load() == {"w-L_01 (sw)": 0.198}
    assert delay_bank.arrivals() == {}


def test_each_capture_series_keeps_its_own_corrections():
    """User, 2026-08-12: switching back to an earlier series shows its own curves, so it has to
    show its own corrections — "там все своє і криві і корекції"."""
    from autosound_tcc.core import delay_bank

    series = ["cap_002"]
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog.set_session_provider(lambda: series[0])
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])
    dialog._view.set_delay(0.26)

    series[0] = "cap_001"

    assert delay_bank.load(session="cap_001") == {}, "another series, another answer"
    assert delay_bank.load(session="cap_002") == {"w-L_01 (sw)": 0.26}
    dialog._render_bank()
    tip = _tip(dialog._bank_btn)
    assert "cap_001" in tip or i18n.t("curveBankEmpty") in tip


def test_clearing_one_series_leaves_the_others_alone():
    from autosound_tcc.core import delay_bank

    delay_bank.put("w-L_01 (sw)", 0.26, session="cap_001")
    delay_bank.put("w-L_02 (sw)", 0.31, session="cap_002")

    delay_bank.clear(session="cap_002")

    assert delay_bank.load() == {"w-L_01 (sw)": 0.26}


def test_a_reading_banked_before_series_scoping_shows_under_every_series():
    """It was somebody's afternoon. Hiding it from all of them would be worse than showing it in
    one too many."""
    from autosound_tcc.core import config, delay_bank, project_settings

    project_settings.set_value(config.tcc_dir(), delay_bank.KEY, {"w-L_01 (sw)": 0.198})

    assert delay_bank.load(session="cap_001") == {"w-L_01 (sw)": 0.198}
    assert delay_bank.load(session="cap_009") == {"w-L_01 (sw)": 0.198}

    delay_bank.put("w-L_01 (sw)", 0.2, session="cap_001")

    assert delay_bank.load(session="cap_009") == {}, "touching it settles which series it is in"


def test_switching_series_in_the_panel_re_reads_the_bank_but_keeps_the_plot():
    """The Arbiter may be switching in order to compare; yanking the curves away would be the
    window deciding what they are doing."""
    from autosound_tcc.core import delay_bank

    delay_bank.put("w-L_01 (sw)", 0.26, session="cap_001")
    series = ["cap_002"]
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog.set_session_provider(lambda: series[0])
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])
    plotted = [t.name for t in dialog._view._traces]
    assert i18n.t("curveBankEmpty") in _tip(dialog._bank_btn)

    series[0] = "cap_001"
    dialog.session_switched()

    tip = _tip(dialog._bank_btn)
    assert "cap_001" in tip and "+0.260" in tip
    assert dialog._bank_btn.text() == i18n.t("curveBankBtn").format(n=1), "the count is on it"
    assert [t.name for t in dialog._view._traces] == plotted


def test_a_driver_with_no_reading_is_named_not_assumed_to_be_at_zero():
    """The user's first real set left w-R, both rears, the centre and the sub off it entirely,
    with nothing saying so — a fragment that reads as a plan (2026-08-12)."""
    from autosound_tcc.core import delay_bank

    text = delay_bank.as_sentence(
        {"m-L_01 (sw)": 1.93}, lang_t=i18n.t, unplaced=["w-R_01 (sw)", "sw_01 (sw)"]
    )

    assert "w-R_01 (sw)" in text and "sw_01 (sw)" in text
    assert i18n.t("curveBankUnplaced").partition("{")[0].strip() in text


def test_the_set_is_listed_by_where_each_driver_lands():
    """Sorted by delay, the outlier sat in the middle of the list. It is the whole point."""
    from autosound_tcc.core import delay_bank

    text = delay_bank.as_sentence(
        {"m-L": 1.93, "w-L": 1.09, "m-R": 0.71},
        lang_t=i18n.t,
        at={"m-L": 2.907, "w-L": 4.781, "m-R": 4.124},
    )

    order = [line.split(":")[0].strip() for line in text.splitlines() if line.startswith("  ")]
    assert order == ["m-R", "m-L", "w-L"], "4.834, 4.837, 5.871"


def test_only_the_family_under_discussion_counts_as_unplaced():
    """The pickers hold the sweep and the RTA of every channel; an RTA capture has no arrival at
    all, so listing one as an unplaced driver would be noise."""
    dialog = _dialog(
        ["w-L_01 (sw)"], bridge=_FakeBridge(),
        available=["w-L_01 (sw)", "w-R_01 (sw)", "w-R_01 (rta)", "sw_01 (sw)"],
    )
    dialog._worker.wait(4000)

    unplaced = dialog._unplaced({"w-L_01 (sw)": 1.0})

    assert unplaced == ["w-R_01 (sw)", "sw_01 (sw)"]
    assert "w-R_01 (rta)" not in unplaced


def test_clearing_leaves_nothing_behind_not_even_the_curve_on_screen():
    """The bug in the picture: Clear, and one value survived — the OTHER curve in the pair, put
    straight back by the handler that banks both whenever a delay changes (user, 2026-08-12)."""
    from autosound_tcc.core import delay_bank

    dialog = _dialog(["tw-L_01 (sw)", "tw-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog._on_curves([Trace("tw-L_01 (sw)", *_impulse(2.98)),
                       Trace("tw-R_01 (sw)", *_impulse(4.17))])
    dialog._view.set_delay(1.89)
    dialog._view.set_delay_target(1)
    dialog._view.set_delay(0.69)
    delay_bank.put("m-L_01 (sw)", 1.93, session=dialog._session())
    assert len(delay_bank.load()) == 3

    dialog._bank_clear_btn.click()

    assert delay_bank.load() == {}
    assert dialog._view.delays() == pytest.approx([0.0, 0.0]), "and the curves went back too"
    assert dialog._view.delay_target() == 1, "without moving which driver you were editing"


def test_clearing_the_markers_recentres_them_even_when_they_are_in_view():
    """"очистка Маркери це повинно бути як дабл-клік — поставити по центру з зміщенням" (user,
    2026-08-12). The double-click leaves visible markers alone on purpose; the button must not,
    or pressing it on a screen where both are visible would do nothing at all."""
    view = _view()
    view.set_unit("ms")
    view.focus_x(0.0, 10.0)
    view.set_markers([4.0, 4.1], tokens=["accent", "info"])

    view.bring_markers_into_view(force=True)

    placed = view.positions()
    assert placed != pytest.approx([4.0, 4.1]), "both were in view and both moved"
    assert placed[0] < placed[1], "in their own order, spread apart"
    (low, high), _ = view._plot.getViewBox().viewRange()
    assert all(low < value < high for value in placed)


def test_a_driver_left_at_zero_is_stated_never_interpreted():
    """Two users' facts, one message: "w-R немає, бо він був нулем" AND "нуль може бути ще те, до
    чого руки не дійшли" (2026-08-12). Nothing here separates the reference from the driver
    nobody has reached, so the sentence says what is true and stops."""
    from autosound_tcc.core import delay_bank

    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge(),
                     available=["w-L_01 (sw)", "w-R_01 (sw)", "sw_01 (sw)"])
    dialog._worker.wait(4000)
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.78)),
                       Trace("w-R_01 (sw)", *_impulse(4.98))])

    dialog._view.set_delay(1.09)

    assert delay_bank.load() == {"w-L_01 (sw)": 1.09}, "only the moved one is a delay"
    assert delay_bank.references() == ["w-R_01 (sw)"], "and the other is the reference"
    assert dialog._unplaced(delay_bank.seen()) == ["sw_01 (sw)"], "never opened, so unplaced"

    sent = []
    dialog.readingSent.connect(sent.append)
    dialog._bank_ask_btn.click()

    assert "w-R_01 (sw)" in sent[0] and i18n.t("curveBankAtZero").partition("{")[0][:20] in sent[0]
    assert "sw_01 (sw)" in sent[0], "and the one never opened is named separately"
    for claim in ("REFERENCE", "ОПОРА", "deliberately", "свідомо"):
        assert claim not in sent[0], "the panel reports; the model concludes"


def test_the_window_has_two_verbs_and_each_appears_twice():
    """User, 2026-08-12: "кнопки називаються однаково і ті що відправляють і ті що в секції
    очистки". Each group of controls ends with the action it produces, named after the group, and
    the Clear section repeats the same two names. Nothing is called "this is my reading".

    "Markers" is on a THIRD button since 2026-08-19 — the readout, renamed at the user's word
    ("назвати кнопку і хінт «Маркери»"). It is not a fourth verb: it reports what the markers say,
    and it is named after them for the same reason the other two are named after their groups."""
    from PySide6.QtWidgets import QPushButton

    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)

    labels = [b.text() for b in dialog.findChildren(QPushButton)]
    assert labels.count(i18n.t("curveSendDelays")) == 2, "send delays, clear delays"
    assert labels.count(i18n.t("curveSendMarkers")) == 3, "send, clear, and the readout"
    assert dialog._view._readout_btn.text() == i18n.t("curveSendMarkers"), "the third one"
    assert "This is my reading" not in labels and "Ось моє прочитання" not in labels


def _widgets(row) -> list:
    """A row's widgets in order, stretches dropped — `itemAt(i).widget()` is None for a spacer."""
    return [row.itemAt(i).widget() for i in range(row.count()) if row.itemAt(i).widget()]


def test_each_action_sits_beside_the_controls_that_produce_it():
    """Parked at the far end of a row, the delay action reads as a second opinion about the
    markers. Since 2026-08-19 that means the SETTINGS row — the delay box, this button and the
    all-pass are one line about one driver — while the markers' own action ends the row of
    controls that place them."""
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    view = dialog._view

    settings = _widgets(view._settings_row)
    assert settings.index(view._shift_box) < settings.index(dialog._bank_ask_btn)
    assert settings.index(dialog._bank_ask_btn) < settings.index(view._apf_kind), \
        "the delay group ends before the all-pass begins"

    actions = _widgets(view._action_row)
    assert actions[-1] is view._send_btn, "the markers group ends the row"
    assert dialog._bank_ask_btn not in actions, "and the delay action is not in it any more"


# ---- the predicted sum (CURVE-ANALYSIS-PLAN.md step 2, user 2026-08-18) -----------------------


def _fr_trace(name: str, level_db: float = 90.0, version: str = "1", method: str = "sw",
              phase: bool = True, points: int = 240) -> Trace:
    """One driver as REW hands it over on the frequency-response endpoint.

    Flat magnitude and flat phase, so every dB the sum shows is interference and nothing else —
    the same reason `test_curve_sum` builds its inputs this way. `phase=False` is the MMM/RTA
    shape: a magnitude and a null where the phase would be.
    """
    freqs = [20.0 * (2 ** (i / 24.0)) for i in range(points)]
    magnitude = [level_db] * points
    return Trace(
        name, freqs, magnitude,
        magnitude_db=magnitude,
        phase_deg=([0.0] * points) if phase else None,
        config_version=version, method=method, start_time_s=0.00518,
    )


def _fr_view(*traces: Trace) -> CurveView:
    """A view on the frequency response, which is where a sum can be drawn at all."""
    _app()
    view = CurveView(x_label="Hz")
    _KEEP.append(view)
    view.set_unit("Hz")
    view.set_y_unit("dB")
    view.set_log_x(True)
    view.set_traces(list(traces))
    return view


def _at(result, hz: float) -> float:
    """The sum's level at the grid point nearest `hz`."""
    freqs = np.asarray(result.freqs_hz, dtype=float)
    return float(np.asarray(result.magnitude_db, dtype=float)[int(np.abs(freqs - hz).argmin())])


def test_the_worker_keeps_the_magnitude_and_the_phase_from_the_one_call_that_returns_both():
    """A curve carried only what it drew, so a sum needed a second round trip to REW to exist at
    all — and REW returns both halves from `get_fr` anyway."""
    _app()

    worker = _CurveWorker(_FrBridge(), ["w-L_01 (sw)"], "phase")
    got: list = []
    worker.done.connect(got.append)
    worker.run()

    trace = got[-1][0]
    assert list(trace.y) == [0.0] * 120, "the phase view still draws the phase"
    assert trace.phase_deg is not None and trace.magnitude_db is not None
    assert list(trace.magnitude_db)[:1] == [80.0 - 0.001 * 20.0], "and the magnitude came too"


def test_a_trace_carries_the_facts_the_summability_rule_is_written_against():
    """`_N` and the method suffix decide whether these captures are one round of one car, and
    REW's own `startTime` travels with them so the sum can report it (`curve_sum`)."""
    _app()

    worker = _CurveWorker(_FrBridge(), ["w-L_01 (sw)"], "fr")
    got: list = []
    worker.done.connect(got.append)
    worker.run()

    trace = got[-1][0]
    assert trace.config_version == "01" and trace.method == "sw", "read with the skill's grammar"
    assert trace.start_time_s == pytest.approx(0.00518), "out of the measurement, at no extra call"


def test_an_impulse_carries_no_magnitude_or_phase_because_it_has_none():
    _app()

    worker = _CurveWorker(_FakeBridge(), ["w-L_01 (sw)"], "impulse")
    got: list = []
    worker.done.connect(got.append)
    worker.run()

    trace = got[-1][0]
    assert trace.magnitude_db is None and trace.phase_deg is None
    assert trace.method == "sw", "the title still says what the capture was"


def test_the_sum_is_off_until_it_is_asked_for():
    """This window is opened to compare two measured curves at least as often as to predict their
    joint, and a prediction nobody asked for is a claim nobody checked."""
    view = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))

    assert view.sum_shown() is False
    assert view.sum_result() is None and view.sum_text() == ""
    assert view._plot.getPlotItem().getAxis("right").isVisible() is False


def test_the_second_axis_is_not_built_until_a_sum_is_actually_drawn():
    """Off by default has to mean off. A window that never shows a sum should not be carrying the
    graphics items for one — this file's crash history is entirely about how many graphics objects
    get constructed and destroyed (`_do_not_build_the_plot_options_menu`)."""
    view = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))

    assert view._sum_vb is None, "nothing extra in the scene until it is asked for"

    view.set_sum_shown(True)

    assert view._sum_vb is not None, "and exactly one, built once"
    built = view._sum_vb
    view.set_sum_shown(False)
    view.set_sum_shown(True)
    assert view._sum_vb is built, "never rebuilt: construct/destroy cycles are what crash here"


def test_two_identical_drivers_sum_six_db_up_on_a_second_axis_in_db():
    """The one number this whole feature has to get right before any of the rest matters."""
    view = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))

    view.set_sum_shown(True)

    result = view.sum_result()
    assert _at(result, 1000.0) == pytest.approx(90.0 + 20.0 * math.log10(2.0), abs=1e-6)
    assert view._plot.getPlotItem().getAxis("right").isVisible(), "and it has a scale of its own"


def test_the_sum_follows_the_delay_without_going_back_to_rew():
    """The entire point of drawing it: dragging or typing a delay is a guess, and the joint has to
    answer while the guess is being made. Two identical drivers 0.5 ms apart cancel at 1 kHz —
    read off `|2A cos(pi f tau)|`, not off a previous run of this code."""
    view = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))
    view.set_sum_shown(True)
    assert _at(view.sum_result(), 1000.0) == pytest.approx(96.02, abs=0.01)

    view.set_delay_target(1)
    view.set_delay(0.5)

    assert _at(view.sum_result(), 1000.0) < 70.0, "a half cycle at 1 kHz is a cancellation"
    assert _at(view.sum_result(), 2000.0) == pytest.approx(96.02, abs=0.01), "a whole cycle adds"


def test_the_drawn_sum_is_in_the_plots_own_x_and_secondary_to_the_measurements():
    """It is a prediction standing among measurements. Dashed, thinner, and neutral rather than a
    third accent colour — and on a log plot its x has to be log10(Hz) like everything else, since
    pyqtgraph's log mode only transforms the items the PlotItem itself owns."""
    view = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))

    view.set_sum_shown(True)

    xs, _ys = view._sum_curve.getData()
    assert xs[0] == pytest.approx(math.log10(20.0))
    pen = view._sum_curve.opts["pen"]
    assert pen.style() == Qt.PenStyle.DashLine
    assert pen.color().alpha() < 255, "faded: it is not a measurement"


def test_the_sum_never_takes_the_mouse_off_a_marker():
    """The markers are this panel's whole output. A second ViewBox laid over the plot that
    swallowed a press would trade the feature for the reason the window exists."""
    view = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))
    view.set_markers([100.0, 1000.0], tokens=["accent", "info"])
    view.set_sum_shown(True)

    view._markers[1].setValue(math.log10(2000.0))

    assert view.positions() == pytest.approx([100.0, 2000.0], rel=1e-6)
    assert view._sum_vb.acceptedMouseButtons() == Qt.MouseButton.NoButton
    assert view._sum_curve.acceptedMouseButtons() == Qt.MouseButton.NoButton


def test_a_set_that_cannot_be_summed_draws_nothing_and_says_which_one_and_why():
    """An MMM capture has a magnitude and nothing to interfere with. Refusing quietly would leave
    the tuner waiting for a curve; refusing in the engine's own words says which measurement."""
    view = _fr_view(_fr_trace("w-L_01 (sw)"),
                    _fr_trace("w-R_01 (rta)", method="rta", phase=False))

    view.set_sum_shown(True)

    assert view.sum_result() is None and view._sum_curve is None
    assert view._plot.getPlotItem().getAxis("right").isVisible() is False
    assert i18n.t("curveSumNone") in view.sum_text()
    assert "w-R_01 (rta)" in view.sum_text(), "it names the measurement that decided it"
    assert view._sum_note_btn.isVisibleTo(view)
    assert "w-R_01 (rta)" in _tip(view._sum_note_btn), "and the tip carries all of it"
    assert current_theme().warn in view._sum_note_btn.styleSheet(), "a refusal is not read last"


def test_a_mixed_config_version_is_drawn_and_labelled_two_different_cars():
    """A bumped `_N` means the DSP configuration changed between the captures, so those drivers
    never played together at any one setting. It is computed anyway — the comparison is worth
    looking at — and the label says what it is not."""
    view = _fr_view(_fr_trace("w-L_01 (sw)", version="1"),
                    _fr_trace("w-R_02 (sw)", version="2"))

    view.set_sum_shown(True)

    assert view.sum_result() is not None and view._sum_curve is not None, "drawn"
    assert view.sum_result().summability.status == "mixed_config"
    assert "DIFFERENT DSP config versions" in view.sum_text()
    assert current_theme().warn in view._sum_note_btn.styleSheet(), "and it does not look believed"


def test_the_timing_assumption_is_printed_with_every_sum_that_is_drawn():
    """Half the precondition cannot be checked from the numbers at all (`rew-api-quirks.md`), so
    it is stated instead — wherever the sum is shown, not in a tooltip somebody may not open."""
    view = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))

    view.set_sum_shown(True)

    assert "ASSUMED, NOT CHECKED" in view.sum_text()
    assert "one shared timing reference" in view.sum_text()


def test_one_curve_is_not_a_sum_and_says_so():
    view = _fr_view(_fr_trace("w-L_01 (sw)"))

    view.set_sum_shown(True)

    assert view.sum_result() is None
    assert i18n.t("curveSumTooFew") in view.sum_text()


def test_an_impulse_with_no_spectrum_says_it_has_nothing_to_add_up():
    """An impulse whose capture REW would not give a response for still plots — the trace is the
    payload of that view — and the sum then says the honest thing rather than drawing a strip over
    no data. The engine's own wording: these curves carry no magnitude and phase."""
    view = _view()  # the impulse view: x in ms, and no `freqs_hz` on either trace

    view.set_sum_shown(True)

    assert view.sum_result() is None
    assert i18n.t("curveSumNoData") in view.sum_text()
    assert view.strip_shown() is False, "no strip over a sum that does not exist"


def test_the_sum_survives_a_new_pair_and_a_reset_of_the_window():
    """A tuner who has asked to see joints is working through a whole car. Asking again for every
    pair is how a feature stops being used."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)", "m-L_01 (sw)"]
    dialog = _dialog(every[:2], bridge=_FrBridge(), kind="fr", available=every)
    dialog._worker.wait(4000)
    dialog._worker.run()
    dialog._view.set_sum_shown(True)
    assert dialog._view.sum_result() is not None

    dialog.reset(["w-L_01 (sw)", "m-L_01 (sw)"], kind="fr", available=every)
    dialog._worker.wait(4000)
    dialog._worker.run()

    assert dialog._view.sum_shown() is True
    assert dialog._view.sum_result() is not None, "and it is drawn for the new pair too"
    assert [c.name for c in dialog._view.sum_result().contributions] == [
        "w-L_01 (sw)", "m-L_01 (sw)"
    ]


def test_the_sum_goes_to_the_model_with_its_verdict_and_its_assumption_attached():
    """A drawn sum ends an argument, so the one that reaches the model must carry what it does not
    show. `SumResult.as_sentence()` puts them there, which is why nothing downstream has to
    remember to."""
    _app()
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FrBridge(), kind="fr")
    dialog._worker.wait(4000)
    dialog._worker.run()
    dialog._view.set_sum_shown(True)
    sent: list[str] = []
    dialog.readingSent.connect(sent.append)

    dialog._view._send_btn.click()

    assert len(sent) == 1
    assert "Predicted acoustic sum of 2 measurement(s)" in sent[0]
    assert "ASSUMED, NOT CHECKED" in sent[0], "the precondition travels with it"
    assert "one capture round" in sent[0], "and so does the verdict"
    assert "startTime" in sent[0], "with the timing facts it was judged on"


def test_with_the_sum_off_nothing_about_it_reaches_the_model():
    _app()
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FrBridge(), kind="fr")
    dialog._worker.wait(4000)
    dialog._worker.run()
    dialog._view.set_markers([100.0, 1000.0], tokens=["accent", "info"])

    assert "ASSUMED" not in dialog._view.statement()
    assert dialog._view.statement() == dialog._view.reading()


def test_a_sum_on_screen_is_worth_sending_with_no_marker_placed():
    """It is a statement about the pair whether or not anybody has pointed at a frequency yet."""
    view = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))

    view.set_sum_shown(True)

    assert view.reading() == "", "no markers, no delay: nothing to read"
    assert view._send_btn.isEnabled()
    assert "Predicted acoustic sum" in view.statement()


# ---- the window the user reviewed on 2026-08-18 -----------------------------------------------


def _phase_view(*traces: Trace) -> CurveView:
    """A view on the phase, which is the kind the Σ toggle is offered on and a sum is drawn on."""
    _app()
    view = CurveView(x_label="Hz")
    _KEEP.append(view)
    view.set_unit("Hz")
    view.set_y_unit("°")
    view.set_log_x(True)
    view.set_traces(list(traces))
    return view


def test_the_sum_toggle_floats_in_the_plots_own_top_left_corner():
    """User, 2026-08-18, with the screenshot: it belongs to the picture it changes, not to the row
    of eight square buttons under it. Inside the axes, and at the end furthest from the legend —
    which is anchored top RIGHT, so the pill naming each driver and its delay is never covered."""
    view = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))
    view.resize(880, 460)
    view.show()
    _app().processEvents()

    assert view._sum_btn.parent() is view._plot, "a control ON the chart, not beside it"
    area = view._plot.getPlotItem().vb.sceneBoundingRect()
    corner = view._plot.mapFromScene(area.topLeft())
    button = view._sum_btn.geometry()
    assert corner.x() <= button.left() <= corner.x() + 16, "inside the data, not over the axis"
    assert corner.y() <= button.top() <= corner.y() + 16
    legend = view._legend.sceneBoundingRect()
    assert not legend.intersects(
        view._plot.mapToScene(button).boundingRect()
    ), "and it does not sit on the delay pill"


def test_the_sum_toggle_is_offered_on_every_kind_including_the_magnitude():
    """It was kept off the frequency response for a day on the user's own rule (2026-08-18: that
    is where MMM/RTA captures are compared, and those cannot be summed, so the control would mostly
    refuse). **The user reversed it on 2026-08-19 after using the window** — "десь ділась кнопка
    суми", on the FR — and the reversal is the point: the sweeps a joint is argued about are
    compared there too, and hunting for a toggle that exists on two views out of three is worse
    than a refusal that says why."""
    phase = _phase_view(_fr_trace("w-L_01 (sw)"))
    assert phase._sum_btn.isVisibleTo(phase) is True

    impulse = _view()
    assert impulse._sum_btn.isVisibleTo(impulse) is True, "the impulse offers it..."
    assert impulse._sum_btn.isEnabled() is True, "...and it works now: the strip is under the plot"

    fr = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))

    assert fr._sum_btn.isVisibleTo(fr) is True, "and the magnitude offers it again"
    fr.set_sum_shown(True)
    assert fr.sum_result() is not None, "with the same sum behind it as ever"


def test_the_toggle_survives_the_kind_the_window_switches_to():
    """The kind changes under the same view — `_apply_kind` re-points units, it does not rebuild
    the widget — and the toggle now has to be there on all three of them (user, 2026-08-19). It
    used to come and go with the kind, which is exactly what the user could not find."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FrBridge(), kind="fr", available=every)
    dialog._worker.wait(4000)
    dialog._worker.run()

    assert dialog._view._sum_btn.isVisibleTo(dialog._view) is True

    for kind in ("phase", "impulse", "fr"):
        dialog._kind_combo.setCurrentIndex(dialog._kind_combo.findData(kind))
        dialog._worker.wait(4000)
        assert dialog._view._sum_btn.isVisibleTo(dialog._view) is True, kind


def test_the_predicted_sum_is_drawn_to_be_followed_across_the_plot():
    """It came out as a thin grey dash nobody could read (user, 2026-08-18). Bolder than a trace,
    near-full alpha, still dashed — and in a colour that is neither of the two trace colours, so
    the eye does not have to work out which of three orange-ish lines is the prediction."""
    view = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))

    from autosound_tcc.ui.tcc.theme import apply_theme

    app = _app()
    view.set_sum_shown(True)

    # Both themes, because the palette swaps under it and a colour that reads in one can vanish
    # in the other — which is how the first one ended up grey on grey.
    for mode in ("dark", "light"):
        apply_theme(app, mode)
        view.apply_theme()
        pen = view._sum_curve.opts["pen"]
        theme = current_theme()
        assert pen.style() == Qt.PenStyle.DashLine, f"{mode}: a prediction, not a measurement"
        assert pen.widthF() >= 2.0, f"{mode}: thicker than the 1.0 px traces it is drawn from"
        assert pen.color().alpha() >= 230, f"{mode}: not faded away"
        drawn = pen.color().name()
        assert drawn not in (theme.accent, theme.info), f"{mode}: not either driver's colour"
        assert drawn not in (theme.border2, theme.muted, theme.faint), f"{mode}: nor the grid's"
    apply_theme(app, "light")


def test_the_delay_box_follows_the_theme_like_the_combos_beside_it():
    """It stayed white with light text on it in the dark theme (user, 2026-08-18): every
    `.mini-select` rule was written `QComboBox[...]`, so not one of them reached the spin box, and
    the palette does not cover for it — the native style paints the field itself.

    Asserted on the EFFECTIVE palette after a live switch, not on the sheet alone: the fault was
    never that the sheet was wrong, it was that nothing in it applied here."""
    from PySide6.QtGui import QPalette

    from autosound_tcc.ui.tcc.theme import PALETTE_DARK, PALETTE_LIGHT, apply_theme

    app = _app()
    view = _view()
    box = view._shift_box
    assert box.property("class") == "mini-select", "it wears the class the combos wear"

    apply_theme(app, "dark")
    box.ensurePolished()
    dark = box.palette().color(QPalette.ColorRole.Window).name()

    apply_theme(app, "light")
    box.ensurePolished()
    light = box.palette().color(QPalette.ColorRole.Window).name()

    assert dark == PALETTE_DARK["panel3"], "the dark theme reaches it..."
    assert light == PALETTE_LIGHT["panel3"], "...and so does the light one"
    assert dark != light, "and a live switch moves it, not only construction"


def test_the_three_paragraphs_under_the_plot_are_buttons_with_the_text_in_the_tip():
    """User, 2026-08-18: "займають місце і не читаються". Each one names what stands behind it —
    and what leaves the window is unchanged, which is the half of this that must not break."""
    _app()
    from autosound_tcc.core import delay_bank

    delay_bank.put("w-L_01 (sw)", 0.198)
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FrBridge(), kind="phase", available=every)
    dialog._worker.wait(4000)
    dialog._worker.run()
    view = dialog._view
    view.set_markers([100.0, 1000.0], tokens=["accent", "info"])
    view.set_sum_shown(True)

    assert view._sum_note_btn.text() == i18n.t("curveSumNoteBtn")
    assert view._readout_btn.text() == i18n.t("curveReadoutBtn")
    assert dialog._bank_btn.text() == i18n.t("curveBankBtn").format(n=1), "with the count on it"
    # Each tip carries the whole of what its paragraph used to say, laid out to be read.
    assert view.sum_text().split("\n")[0] in _tip(view._sum_note_btn)
    assert "ASSUMED, NOT CHECKED" in _tip(view._sum_note_btn)
    # The readout's is a TABLE since 2026-08-19 rather than the sentence verbatim (the sentence is
    # still what LEAVES the window — `reading()`), so it is checked by what is in it.
    readout = _tip(view._readout_btn)
    assert i18n.t("curveMarkerModel") in readout and "100.0" in readout
    assert i18n.t("curveDelayHead") in readout, "and the proposal is under the table, in words"
    assert "w-L_01 (sw) +0.198" in _tip(dialog._bank_btn)
    for button in (view._sum_note_btn, view._readout_btn, dialog._bank_btn):
        assert "font-size: 15px" in button.hover_tip.text(), "large enough to read"
        assert "<b>" in button.hover_tip.text(), "and it says what it is answering about"
        # `.clear-btn` is this window's low family, pinned to 20 px in the stylesheet: these
        # report a set, they do not offer to do anything, and four lines of prose became one row.
        assert button.property("class") == "clear-btn"
        button.ensurePolished()
        assert button.sizeHint().height() <= 24, "one row of window, not four"


def test_what_leaves_the_window_is_the_same_sentence_it_always_was():
    """The paragraphs moved into tips; the model gets exactly what it got before. `statement()`
    and the bank's own sentence are built from the plain strings, and no markup may reach them."""
    _app()
    from autosound_tcc.core import delay_bank

    delay_bank.put("w-L_01 (sw)", 0.198)
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FrBridge(), kind="fr")
    dialog._worker.wait(4000)
    dialog._worker.run()
    dialog._view.set_sum_shown(True)
    sent: list[str] = []
    dialog.readingSent.connect(sent.append)

    dialog._bank_ask_btn.click()
    dialog._view._send_btn.click()

    assert len(sent) == 2
    for text in sent:
        assert "<" not in text and "font-size" not in text
    assert "Predicted acoustic sum" in sent[1]


# ---- more than two curves, and the groups a tune is argued about ------------------------------
# CURVE-ANALYSIS-PLAN.md step 3, and the user's own list (2026-08-18): "Ws, Ms, TWs, SW+Ws, L, R,
# ALL — до налаштувань та повторних зйомів".


#: One car's glossary, in the shape the skill writes it (`naming.Glossary`, SCR-008). Written into
#: the project the conftest points every test at, so nothing here can reach a real one.
_GLOSSARY = {
    "channels": [{"code": c} for c in
                 ("sw", "w-L", "w-R", "m-L", "m-R", "tw-L", "tw-R")],
    "pairs": {"Ws": ["w-L", "w-R"], "Ms": ["m-L", "m-R"], "TWs": ["tw-L", "tw-R"]},
    "joints": {"SW+Ws": ["sw", "w-L", "w-R"]},
    "sides": {"L": ["tw-L", "m-L", "w-L"], "R": ["tw-R", "m-R", "w-R"]},
    "combos": {"ALL": ["tw-L", "tw-R", "m-L", "m-R", "w-L", "w-R"]},
}

#: What REW holds in these tests: every driver as a sweep at `_02`, the woofers also at `_01`, and
#: one MMM capture — the mixture the pickers and the kind rule are written against.
_IN_REW = [
    "sw_02 (sw)", "w-L_02 (sw)", "w-R_02 (sw)", "m-L_02 (sw)", "m-R_02 (sw)",
    "tw-L_02 (sw)", "tw-R_02 (sw)",
    "w-L_01 (sw)", "w-R_01 (sw)", "w-L_01 (rta)",
]


def _project_glossary(glossary: dict = None) -> None:
    """Give the test's project a glossary, and REFUSE to write anywhere but a temp folder.

    `config.project_dir()` is the conftest's tmp folder while `_isolated_project_dir` is in
    effect, and that fixture is autouse -- so under pytest this is safe. It is not safe when this
    module is imported OUTSIDE pytest, which is a thing that happens: an offscreen probe that
    reuses these helpers to build a dialog gets no fixtures, `AUTOSOUND_PROJECT_DIR` is unset, and
    `project_dir()` falls back to the developer's REAL car. Then this line writes a seven-channel
    test glossary over it, and `glossary.json` standing beside a full `project.json` shadows it --
    which is exactly what happened on 2026-08-21 and took an expert reading the live project to
    find, because nothing here complained.

    The guard is the invariant rather than a promise: a test glossary goes into a temp directory
    or it goes nowhere.
    """
    import json
    import tempfile

    from autosound_tcc.core import config

    target = config.project_dir().resolve()
    if not str(target).startswith(str(pathlib.Path(tempfile.gettempdir()).resolve())):
        raise RuntimeError(
            f"refusing to write a test glossary into {target} -- that is not a temp directory. "
            "Set AUTOSOUND_PROJECT_DIR to a scratch folder before importing these helpers "
            "outside pytest."
        )
    (target / "glossary.json").write_text(
        json.dumps(glossary if glossary is not None else _GLOSSARY), encoding="utf-8"
    )


def _group_dialog(chosen=("w-L_02 (sw)", "w-R_02 (sw)"), kind="fr", glossary=_GLOSSARY):
    """A window over a car with a glossary, on everything REW holds."""
    _app()
    _project_glossary(glossary)
    return _dialog(list(chosen), bridge=_FrBridge(), kind=kind, available=_IN_REW)


def _fetch(dialog) -> None:
    """Run the in-flight worker synchronously, so the traces are in hand rather than raced."""
    dialog._worker.wait(4000)
    dialog._worker.run()


def _pick_group(dialog, name: str) -> None:
    at = next(i for i in range(dialog._group_combo.count())
              if str(dialog._group_combo.itemText(i)).startswith(name + " "))
    dialog._group_combo.setCurrentIndex(at)


def test_a_group_is_its_members_sweeps_at_one_config_version():
    """The ask that started step 3: see what the woofers do together before touching the DSP. The
    names are the car's own glossary, and what gets fetched is each member's `(sw)` capture — the
    only method that carries a phase, which is what a sum is made of."""
    dialog = _group_dialog()
    _fetch(dialog)

    _pick_group(dialog, "Ws")
    _fetch(dialog)

    assert dialog._chosen() == ["w-L_02 (sw)", "w-R_02 (sw)"]
    _pick_group(dialog, "ALL")
    _fetch(dialog)
    assert dialog._chosen() == [
        "tw-L_02 (sw)", "tw-R_02 (sw)", "m-L_02 (sw)", "m-R_02 (sw)",
        "w-L_02 (sw)", "w-R_02 (sw)",
    ], "in the glossary's own member order, six of them"
    assert [t.name for t in dialog._view._traces] == dialog._chosen()


def test_the_group_picker_says_which_kind_of_group_each_row_is():
    """`Ws` is a pair and `L` is a side. A list of bare names does not say which, and choosing the
    wrong one is a different question, not a typo."""
    dialog = _group_dialog()
    _fetch(dialog)

    rows = [dialog._group_combo.itemText(i) for i in range(dialog._group_combo.count())]

    assert f"Ws · {i18n.t('curveGroupKind_pairs')}" in rows
    assert f"SW+Ws · {i18n.t('curveGroupKind_joints')}" in rows
    assert f"L · {i18n.t('curveGroupKind_sides')}" in rows
    assert f"ALL · {i18n.t('curveGroupKind_combos')}" in rows


def test_the_version_starts_on_the_one_the_chosen_curves_already_share():
    """That is the round the tuner is working in. Moving them to another version unasked would
    answer a different question than the one on screen."""
    dialog = _group_dialog(chosen=("w-L_01 (sw)", "w-R_01 (sw)"))
    _fetch(dialog)

    assert str(dialog._version_combo.currentData()) == "01"

    _pick_group(dialog, "Ws")
    _fetch(dialog)

    assert dialog._chosen() == ["w-L_01 (sw)", "w-R_01 (sw)"], "the group at THAT version"


def test_with_the_curves_on_different_versions_the_group_takes_the_newest_rew_holds():
    """No agreed version means no round to stay in, and the newest is the one the car is at."""
    dialog = _group_dialog(chosen=("w-L_01 (sw)", "w-R_02 (sw)"))
    _fetch(dialog)

    assert str(dialog._version_combo.currentData()) == "02"


def test_the_version_can_be_moved_and_the_group_follows_it():
    """A tuner comparing rounds says which round. The control is beside the group for that."""
    dialog = _group_dialog()
    _fetch(dialog)
    _pick_group(dialog, "Ws")
    _fetch(dialog)

    dialog._version_combo.setCurrentIndex(dialog._version_combo.findData("01"))
    _fetch(dialog)

    assert dialog._chosen() == ["w-L_01 (sw)", "w-R_01 (sw)"]


def test_a_member_rew_has_no_sweep_for_is_named_on_screen_not_skipped():
    """`curve_sum` sees only what it is handed, so it cannot tell the sum of a joint from the sum
    of the two thirds of it that happened to be in REW. This sentence is the only place in the
    whole path that can — so it is on screen, not in a log."""
    dialog = _group_dialog()
    _fetch(dialog)

    # At `_01` REW holds the two woofers of this joint and not the sub.
    _pick_group(dialog, "SW+Ws")
    dialog._version_combo.setCurrentIndex(dialog._version_combo.findData("01"))
    _fetch(dialog)

    assert dialog._chosen() == ["w-L_01 (sw)", "w-R_01 (sw)"], "what REW does have"
    assert dialog._status.isVisibleTo(dialog)
    assert "sw_01 (sw)" in dialog._status.text(), "named, in the title it would have had"
    assert "SW+Ws" in dialog._status.text() and "_01" in dialog._status.text()


def test_a_group_with_nothing_in_rew_changes_nothing_and_says_so():
    """Better than an empty plot: the selection that was being looked at stays on screen.

    Reached the way it happens in a car: the curves on screen are a round the tweeters were not
    captured in, so the group starts on that round and there is nothing of it to find.
    """
    dialog = _group_dialog(chosen=("w-L_01 (sw)", "w-R_01 (sw)"))
    _fetch(dialog)
    before = list(dialog._chosen())

    _pick_group(dialog, "TWs")

    assert dialog._chosen() == before
    assert "TWs" in dialog._status.text() and dialog._status.isVisibleTo(dialog)
    assert "_01" in dialog._status.text(), "and says which round it looked in"


def test_without_a_glossary_the_group_picker_says_so_and_the_checklist_still_works():
    """A curve window that cannot open without a project file is worse than one offering a control
    fewer — TCC is pointed at folders that were never through intake."""
    dialog = _group_dialog(glossary={})
    _fetch(dialog)

    assert dialog._group_combo.isEnabled() is False
    assert dialog._group_combo.itemText(0) == i18n.t("curveGroupNoGlossary")

    dialog._choose_actions["m-L_02 (sw)"].setChecked(True)
    _fetch(dialog)

    assert "m-L_02 (sw)" in dialog._chosen(), "the checkbox list is untouched by any of it"


def test_the_checklist_takes_any_set_and_everything_downstream_follows_it():
    """Three drivers, then six. Traces, delays, the bank and the reading are all per trace — the
    `[:2]` slices were the work, not the model (CURVE-ANALYSIS-PLAN.md)."""
    from autosound_tcc.core import delay_bank

    dialog = _group_dialog()
    _fetch(dialog)

    for title in ("w-L_02 (sw)", "m-L_02 (sw)", "tw-L_02 (sw)"):
        dialog._choose_actions[title].setChecked(True)
    for title in ("w-R_02 (sw)",):
        dialog._choose_actions[title].setChecked(False)
    _fetch(dialog)

    assert len(dialog._view._traces) == 3
    assert len(dialog._view.delays()) == 3, "one delay per trace, not per pair"
    # Every one of the three is addressable, and each keeps its own number.
    for index, ms in enumerate((0.1, 0.2, 0.3)):
        dialog._view.set_delay_target(index)
        dialog._view.set_delay(ms)
    assert dialog._view.delays() == pytest.approx([0.1, 0.2, 0.3])
    banked = delay_bank.load()
    assert set(banked) == {"w-L_02 (sw)", "m-L_02 (sw)", "tw-L_02 (sw)"}, "all three banked"
    reading = dialog._view.reading()
    assert all(name in reading for name in banked), "and the sentence names all three"

    for title in ("w-R_02 (sw)", "m-R_02 (sw)", "tw-R_02 (sw)"):
        dialog._choose_actions[title].setChecked(True)
    _fetch(dialog)

    assert len(dialog._view._traces) == 6
    assert len(dialog._view.delays()) == 6
    assert len(dialog._view._markers) == 2, "the markers are a constant pair, whatever is plotted"


def test_the_chips_and_the_checklist_are_one_selection():
    """Two controls each holding part of the truth is how a window comes to draw one set of curves
    and report another. Whichever was used last is what `_chosen()` says, and both show it."""
    dialog = _group_dialog()
    _fetch(dialog)

    _pick_group(dialog, "L")
    _fetch(dialog)

    assert len(dialog._chosen()) == 3
    assert [chip.title() for chip in _chips(dialog)] == dialog._chosen(), \
        "the chips name all of it, in the order it is plotted"
    ticked = {t for t, a in dialog._choose_actions.items() if a.isChecked()}
    assert ticked == set(dialog._chosen()), "and the list ticks all of it"
    assert dialog._choose_btn.text() == i18n.t("curveChooseBtn").format(n=3)

    # And back the other way: a × on a chip unticks the same row in the menu.
    dropped = _chips(dialog)[1].title()
    _chips(dialog)[1]._x.click()
    _fetch(dialog)

    assert dropped not in dialog._chosen()
    assert dialog._choose_actions[dropped].isChecked() is False, "the menu followed the chip"
    assert [chip.title() for chip in _chips(dialog)] == dialog._chosen()
    assert dialog._group_combo.currentIndex() == 0, "and it lets go of the group it is not"


def test_seven_traces_each_get_a_colour_of_their_own():
    """A whole side is four drivers and ALL+C is seven. Two colours cycling would paint driver
    three exactly like driver one, on a plot whose whole job is telling drivers apart."""
    from autosound_tcc.ui.tcc.curve_view import colour_of, trace_token

    names = [colour_of(trace_token(i)).name() for i in range(8)]

    assert len(set(names)) == 8, "eight curves, eight colours"
    theme = current_theme()
    reserved = {theme.yellow, theme.warn, theme.ok, theme.muted, theme.faint}
    assert not (set(names) & reserved), "and none of them is a colour that already MEANS something"


def test_the_delay_radios_grow_with_the_selection():
    """The radio is how a driver is chosen to be held back. With two of them, four of six drivers
    were unreachable."""
    view = _view()
    assert sum(1 for b in view._target_buttons if b.isVisibleTo(view)) == 2

    view.set_traces([Trace(f"d{i}_02 (sw)", *_impulse(4.0 + i * 0.1)) for i in range(6)])

    live = [b for b in view._target_buttons if b.isVisibleTo(view)]
    assert len(live) == 6
    view.set_delay_target(5)
    view.set_delay(0.42)
    assert view.delays()[5] == pytest.approx(0.42)
    assert view.delays()[:5] == pytest.approx([0.0] * 5), "and only that one moved"


def test_the_delay_starts_on_the_earliest_arrival_of_however_many_there_are():
    """It is the only driver a DSP can hold back — over a whole side as much as over a pair."""
    view = _view()

    view.set_traces([
        Trace("a_02 (sw)", *_impulse(5.2)),
        Trace("b_02 (sw)", *_impulse(4.9)),
        Trace("c_02 (sw)", *_impulse(4.4)),
        Trace("d_02 (sw)", *_impulse(5.6)),
    ])

    assert view.delay_target() == 2, "c arrives first"


# ---- the cross modes stay pairwise (CURVE-ANALYSIS-PLAN.md, "Markers are pair-shaped") --------


def test_the_cross_modes_read_the_two_curves_the_tuner_names():
    """Vx answers "how far apart are THESE TWO at this x", and over six drivers there is no
    N-curve form of that: fifteen pairwise gaps are not a reading. So the pair is chosen, and it
    defaults to the first two."""
    view = _fr_view(_fr_trace("w-L_01 (sw)", level_db=90.0),
                    _fr_trace("w-R_01 (sw)", level_db=84.0),
                    _fr_trace("m-L_01 (sw)", level_db=70.0))
    view.set_markers([1000.0], ["one"], ["accent"])
    view.set_axes_mode("vx")

    assert view.cross_pair() == (0, 1)
    assert len(view.crossings()) == 2, "two curves, not three"
    assert "Δ 6.0 dB" in view.reading()

    view.set_cross_pair(0, 2)

    assert [round(y) for _x, y in view.crossings()] == [90, 70]
    assert "Δ 20.0 dB" in view.reading()
    assert "m-L_01 (sw)" in view.reading() and "w-R_01 (sw)" not in view.reading(), \
        "the sentence names the two that were compared"


def test_the_pair_pickers_appear_only_where_there_is_a_pair_to_choose():
    """With two curves the pair IS the selection; outside a cross mode there is no pairwise
    question on screen at all."""
    view = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))
    view.set_axes_mode("vx")
    assert view._cross_combos[0].isVisibleTo(view) is False

    view.set_traces([_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"),
                     _fr_trace("m-L_01 (sw)")])

    assert view._cross_combos[0].isVisibleTo(view) is True
    assert [view._cross_combos[i].currentData() for i in (0, 1)] == [0, 1]

    view.set_axes_mode("vh")

    assert view._cross_combos[0].isVisibleTo(view) is False, "no cross mode, no pair to choose"


def test_the_per_curve_markers_still_answer_for_every_curve():
    """The half of the decision that is easy to lose: the cross modes narrow to two, and the
    ordinary markers keep reading all of them, one number each."""
    view = _fr_view(*[_fr_trace(f"d{i}_01 (sw)", level_db=90.0 - i) for i in range(5)])
    view.set_markers([100.0, 200.0, 400.0, 800.0, 1600.0],
                     [f"d{i}_01 (sw)" for i in range(5)],
                     [f"trace#{i}" if i > 1 else ("accent", "info")[i] for i in range(5)])

    view.set_axes_mode("v")

    reading = view.reading()
    assert all(f"d{i}_01 (sw)" in reading for i in range(5))
    assert len(view.positions()) == 5


# ---- the sum's own strip, under the impulse (user, 2026-08-18) --------------------------------


def _impulse_with_spectrum(name: str, peak_ms: float, points: int = 240) -> Trace:
    """An impulse trace as the worker now builds one: the time domain to DRAW, and the frequency
    domain from the same measurement, which is what the strip under it adds up."""
    xs, ys = _impulse(peak_ms)
    freqs = [20.0 * (2 ** (i / 24.0)) for i in range(points)]
    return Trace(
        name, xs, ys,
        magnitude_db=[90.0] * points, phase_deg=[0.0] * points, freqs_hz=freqs,
        config_version="1", method="sw", start_time_s=0.00518,
    )


def _impulse_sum_view() -> CurveView:
    _app()
    view = CurveView(x_label="ms")
    _KEEP.append(view)
    view.set_traces([_impulse_with_spectrum("w-L_01 (sw)", 4.52),
                     _impulse_with_spectrum("w-R_01 (sw)", 4.52)])
    return view


def test_the_strip_is_where_the_sum_goes_on_an_impulse():
    """Decided by the user, 2026-08-18: not a second Y axis, because the impulse's x is TIME and
    the sum's is frequency, so there is no pair of axes they can share. It is under the plot rather
    than on another view because the delay is dragged HERE."""
    view = _impulse_sum_view()

    view.set_sum_shown(True)

    assert view.strip_shown() is True
    assert view._plot.getPlotItem().getAxis("right").isVisible() is False, "not on the time axis"
    # Through the splitter now, which is what makes the boundary draggable -- but still inside
    # this view's own object tree, which is the property that matters: Qt destroys it with the
    # view, in order, and nothing is left parked on a PlotItem to outlive it.
    assert view._strip.parent() is view._split
    assert view._split.parent() is view, "the splitter is the view's, so the strip dies with it"
    assert view._strip.plotItem.vb.menuEnabled() is False, "and it builds no ViewBox menu"
    xs, _ys = view._strip_curve.getData()
    # `getData()` answers in DISPLAY coordinates, so a strip in log mode reports log10(Hz) even
    # though it was handed raw hertz -- the transform is pyqtgraph's, not ours. That is the whole
    # difference between the two drawing surfaces: the strip owns its items and log-modes them,
    # while the right-hand ViewBox above owns nothing pyqtgraph will transform, so THAT curve is
    # given log10 computed by hand. `getOriginalDataset` is what shows the hertz we passed.
    assert xs[0] == pytest.approx(math.log10(20.0), rel=0.05), "log10 hertz, in display coordinates"
    raw_x, _raw_y = view._strip_curve.getOriginalDataset()
    assert raw_x[0] == pytest.approx(20.0, rel=0.05), "and plain hertz underneath"
    pen = view._strip_curve.opts["pen"]
    assert pen.style() == Qt.PenStyle.DashLine and pen.widthF() >= 2.0, "the sum's own pen"


def test_the_strip_is_not_built_until_a_sum_is_drawn_on_an_impulse():
    """A whole second PlotWidget, in the file whose crash history is how many of them get built —
    so a window that never asks for one carries the graphics items it always carried."""
    view = _impulse_sum_view()
    assert view._strip is None

    view.set_sum_shown(True)
    built = view._strip
    view.set_sum_shown(False)
    view.set_sum_shown(True)

    assert view._strip is built, "never rebuilt: construct/destroy cycles are what crash here"


def test_with_the_sum_off_there_is_no_strip():
    view = _impulse_sum_view()

    assert view.strip_shown() is False
    view.set_sum_shown(True)
    assert view.strip_shown() is True
    view.set_sum_shown(False)
    assert view.strip_shown() is False, "and it leaves with the toggle, not just the curve"


def test_the_strip_takes_the_phase_too_and_the_frequency_response_keeps_its_axis():
    """The user's verdict after using it (2026-08-18): the phase reads better with the sum in a
    band of its own, with the drivers thin under it, than squeezed onto a second scale over a plot
    in degrees. The frequency response is already in dB, so there the sum stays over the curves it
    was computed from and only got heavier."""
    phase = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))
    phase.set_sum_shown(True)
    assert phase.strip_shown() is True
    assert phase._plot.getPlotItem().getAxis("right").isVisible() is False

    fr = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))
    fr.set_sum_shown(True)
    assert fr.strip_shown() is False
    assert fr._plot.getPlotItem().getAxis("right").isVisible() is True


def test_the_phase_strip_follows_the_plot_until_it_is_unlinked():
    """Asked for in both directions (user, 2026-08-18): the two pictures over one another while a
    joint is read, and the strip on its own while a null is zoomed into.

    Asserted as SPANS rather than as `linkedView`. pyqtgraph's own link is not used any more — it
    is two-way, and the strip's half of it put a range of 615 log-decades on the plot (see
    `_follow_plot_x`) — so what has to hold is the behaviour, not the object.
    """
    def strip_span(view):
        return tuple(view._strip.getPlotItem().vb.viewRange()[0])

    def plot_span(view):
        return tuple(view._plot.getPlotItem().vb.viewRange()[0])

    phase = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))
    phase.set_sum_shown(True)
    phase.focus_x(20.0, 20000.0)
    assert phase.strip_linked() is True
    assert strip_span(phase) == pytest.approx(plot_span(phase), abs=0.001)

    phase.set_strip_linked(False)
    assert phase.strip_linked() is False
    phase.focus_x(100.0, 1000.0)
    assert strip_span(phase) != pytest.approx(plot_span(phase), abs=0.001), \
        "unlinked, the plot moves alone"
    assert strip_span(phase)[0] == pytest.approx(math.log10(20.0), abs=0.05), "on its own band"

    phase.set_strip_linked(True)
    assert strip_span(phase) == pytest.approx(plot_span(phase), abs=0.001)
    phase.focus_x(30.0, 3000.0)
    assert strip_span(phase) == pytest.approx(plot_span(phase), abs=0.001), \
        "and it keeps following after that, not only at the moment of relinking"


def test_the_impulse_strip_is_never_linked_because_that_x_is_time():
    """Linking hertz to milliseconds would be two quantities forced onto one scale, so the impulse
    strip opens on the audible band instead and the toggle is not offered."""
    view = _impulse_sum_view()
    view.set_sum_shown(True)

    assert view.strip_linked() is False
    assert view._strip.getPlotItem().vb.linkedView(0) is None
    assert view._link_btn.isVisible() is False


def test_the_strip_follows_the_delay_being_dragged_on_the_impulse():
    """The whole point of putting it there. Two identical drivers 0.5 ms apart cancel at 1 kHz —
    read off `|2A cos(pi f tau)|`, not off a previous run of this code — and the strip has to show
    that while the drag is happening, without a switch to another view."""
    view = _impulse_sum_view()
    view.set_sum_shown(True)
    assert _at(view.sum_result(), 1000.0) == pytest.approx(96.02, abs=0.01)
    _xs, before = view._strip_curve.getData()

    view.set_delay_target(1)
    view.set_delay(0.5)

    assert _at(view.sum_result(), 1000.0) < 70.0, "a half cycle at 1 kHz is a cancellation"
    _xs, after = view._strip_curve.getData()
    assert before[len(before) // 2] != pytest.approx(after[len(after) // 2]), \
        "and the drawn curve moved with it, not only the number behind it"
    assert view.strip_shown() is True


def test_the_impulse_sum_is_the_same_sum_the_phase_view_draws():
    """One engine, one set of inputs, two places to draw it. A strip computing its own answer is
    how two views of one window come to disagree about what the drivers do together."""
    strip = _impulse_sum_view()
    strip.set_sum_shown(True)

    phase = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))
    phase.set_sum_shown(True)

    assert _at(strip.sum_result(), 1000.0) == pytest.approx(_at(phase.sum_result(), 1000.0))
    assert "ASSUMED, NOT CHECKED" in strip.sum_text(), "with the precondition still attached"


def test_the_worker_brings_the_spectrum_back_with_the_impulse():
    """The strip needs the frequency domain of a capture the impulse view draws in time. REW
    returns both halves from one extra call, and the toggle is flipped while the window is open —
    a strip that needed a re-fetch to appear would answer a second later than the question."""
    _app()

    worker = _CurveWorker(_FrBridge(), ["w-L_01 (sw)"], "impulse")
    got: list = []
    worker.done.connect(got.append)
    worker.run()

    trace = got[-1][0]
    assert len(trace.x) == 200, "the impulse is still what is drawn"
    assert trace.freqs_hz is not None and trace.magnitude_db is not None
    assert trace.phase_deg is not None, "and a sum needs both halves of it"


def test_an_impulse_still_plots_when_rew_has_no_response_for_it():
    """The trace is the payload of that view. Losing the sum's inputs costs the strip; losing the
    trace would cost the curve the window was opened for."""
    _app()

    worker = _CurveWorker(_FakeBridge(), ["w-L_01 (sw)"], "impulse")  # no `frequency_response`
    got: list = []
    worker.done.connect(got.append)
    worker.run()

    trace = got[-1][0]
    assert len(trace.x) == 200
    assert trace.freqs_hz is None and trace.magnitude_db is None


# ---- ONE visible selection: the chip row (Advisor, 2026-08-18; user, same day) ----------------
# "the tuner must always know exactly which physical measurements are contributing to the
# predicted sum on the screen ... Saying '(3)' while only listing two names, or tucking active
# curves inside a closed checklist, breaks trust."


def test_the_chips_name_every_plotted_curve_in_that_curve_s_own_colour():
    """The row IS the legend. A chip whose colour is not its trace's would be a legend that lies,
    which is worse than none — the delay a tuner commits is read off the plot beside it."""
    from autosound_tcc.ui.tcc.curve_view import trace_colour

    dialog = _group_dialog()
    _fetch(dialog)
    _pick_group(dialog, "L")
    _fetch(dialog)

    chips = _chips(dialog)

    assert [chip.title() for chip in chips] == dialog._chosen()
    assert [t.name for t in dialog._view._traces] == dialog._chosen(), "and that IS what is drawn"
    assert [_chip_colour(chip) for chip in chips] == [
        trace_colour(index).name().lower() for index in range(len(chips))
    ]


def test_the_x_on_a_chip_takes_that_driver_off_and_the_plot_follows():
    """The Advisor's own workflow: load a group, look at the sum, then isolate a problem by
    removing one driver to hear what its absence does to the joint."""
    dialog = _group_dialog()
    _fetch(dialog)
    _pick_group(dialog, "L")
    _fetch(dialog)
    dropped = _chips(dialog)[0].title()

    _chips(dialog)[0]._x.click()
    _fetch(dialog)

    assert dropped not in dialog._chosen()
    assert len(dialog._chosen()) == 2
    assert [t.name for t in dialog._view._traces] == dialog._chosen(), "the plot lost it too"
    assert dropped not in [chip.title() for chip in _chips(dialog)]


def test_a_group_fills_the_chips_and_taking_one_off_does_not_refill_it():
    """A FILL, not a claim of ownership. If the group re-asserted itself the Advisor's workflow
    would be impossible: the driver you just removed would come straight back."""
    dialog = _group_dialog()
    _fetch(dialog)

    _pick_group(dialog, "ALL")
    _fetch(dialog)
    assert len(_chips(dialog)) == 6

    _chips(dialog)[2]._x.click()
    _fetch(dialog)

    assert len(_chips(dialog)) == 5, "five, and it stays five"
    assert dialog._group is None
    assert dialog._group_combo.currentIndex() == 0, "— no group —: these chips are not ALL any more"

    # ...and touching the version, which used to re-resolve the group, changes nothing now.
    before = list(dialog._chosen())
    dialog._version_combo.setCurrentIndex(dialog._version_combo.findData("01"))
    _fetch(dialog)

    assert dialog._chosen() == before


def test_seven_chips_wrap_onto_a_second_line_rather_than_squeezing_the_window():
    """A whole side plus the sub is seven names, and a name squeezed to an ellipsis is not the
    evidence this row exists to be."""
    dialog = _group_dialog(chosen=_IN_REW[:7], kind="fr")
    _fetch(dialog)

    assert len(_chips(dialog)) == 7
    row = dialog._chip_row
    one_line = row.heightForWidth(4000)
    at_window_width = row.heightForWidth(760)

    assert at_window_width > one_line, "seven names do not fit one line of this window"
    assert at_window_width >= 2 * one_line, "so they take at least two"
    assert all(chip.sizeHint().width() > 40 for chip in _chips(dialog)), "and none is squeezed"


def test_the_last_chip_cannot_be_taken_off():
    """With nothing selected `_reload` has nothing to fetch, so the previous curves would stay on
    the plot beside an empty row — the window drawing one thing while its selection says another."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FakeBridge(), available=every)
    dialog._worker.wait(4000)

    _chips(dialog)[1]._x.click()
    dialog._worker.wait(4000)

    chips = _chips(dialog)
    assert len(chips) == 1
    assert chips[0]._x.isEnabled() is False
    chips[0]._x.click()
    assert dialog._chosen() == ["w-L_01 (sw)"], "and clicking it anyway changes nothing"
    # The same rule from the other control: the last tick cannot be taken off either.
    dialog._choose_actions["w-L_01 (sw)"].trigger()
    assert dialog._chosen() == ["w-L_01 (sw)"]
    assert dialog._choose_actions["w-L_01 (sw)"].isChecked() is True, "the tick goes back on"


def test_a_measurement_rew_could_not_draw_is_faint_and_does_not_shift_the_others_colours():
    """The worker keeps going when one curve fails, so the traces are shorter than the selection
    from that point on. Colouring the chips by POSITION would then name the wrong driver for the
    whole tail of the row — in the one case where the tuner most needs to know what fed the sum."""
    from autosound_tcc.ui.tcc.curve_view import trace_colour

    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)", "m-L_01 (sw)"]
    dialog = _dialog(every, bridge=_FakeBridge(), available=every)
    dialog._worker.wait(4000)

    # REW answered for the first and the last; the middle one is missing from the traces.
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("m-L_01 (sw)", *_impulse(4.78))])

    chips = _chips(dialog)
    assert [chip.title() for chip in chips] == every
    assert _chip_colour(chips[0]) == trace_colour(0).name().lower()
    assert _chip_colour(chips[2]) == trace_colour(1).name().lower(), "m-L is trace TWO on the plot"
    assert _chip_colour(chips[1]) == current_theme().faint.lower(), "and the absent one is faint"
    assert i18n.t("curveChipMissingTip").format(title="w-R_01 (sw)") in _tip(chips[1]._x)


def test_the_chips_are_repainted_when_the_theme_changes():
    """A chip's colour is a PEN's colour, written per widget — nothing about a stylesheet switch
    reaches it, which is the same reason the plot itself has to be told."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FakeBridge(), available=every)
    dialog._worker.wait(4000)
    before = [_chip_colour(chip) for chip in _chips(dialog)]

    from autosound_tcc.ui.tcc.theme import apply_theme

    # To the OTHER palette, whichever this run happens to be standing on: tests before this one
    # switch the theme and leave it switched, and "to light" is not a change when it is light.
    was = current_theme().mode
    try:
        apply_theme(_app(), "light" if was == "dark" else "dark")
        dialog.apply_theme()
        after = [_chip_colour(chip) for chip in _chips(dialog)]
    finally:
        apply_theme(_app(), was)
        dialog.apply_theme()

    assert after != before, "the two palettes do not paint a trace the same"
    assert all(colour for colour in after), "and every chip still carries one"
    assert [_chip_colour(chip) for chip in _chips(dialog)] == before, "and back again"


def test_reset_re_points_the_chip_row_at_the_new_question():
    """The window is re-pointed rather than rebuilt (pyqtgraph's PlotItem segfaults on enough
    construct/destroy cycles), so every control has to come with it — this row included."""
    _app()
    first = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(first, bridge=_FakeBridge(), available=first)
    dialog._worker.wait(4000)

    second = ["m-L_01 (sw)", "m-R_01 (sw)", "tw-L_01 (sw)"]
    dialog.reset(second, available=second)
    dialog._worker.wait(4000)

    assert [chip.title() for chip in _chips(dialog)] == second
    assert dialog._chosen() == second
    assert {t for t, a in dialog._choose_actions.items() if a.isChecked()} == set(second)


def test_the_selection_has_exactly_one_writer_and_one_reader():
    """The invariant the whole row rests on, checked in the source rather than through the UI: a
    second path that writes `_selection` would put the window back where it started — two controls
    each holding part of the truth, drawing one set of curves and reporting another.

    `__init__` and `reset` seed it (they run before the widgets exist, or before the project has
    been re-read); every other change goes through `_set_selection`, and every reader asks
    `_chosen()`.
    """
    import ast
    import inspect

    from autosound_tcc.ui.tcc import curve_dialog as module

    tree = ast.parse(inspect.getsource(module))
    writers, readers = set(), set()
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            # `AnnAssign` as well as `Assign`: the seed in `__init__` carries its type annotation
            # (`self._selection: list[str] = ...`), and a check that missed it would be a check
            # that passes because it is looking at the wrong node.
            targets = (
                node.targets if isinstance(node, ast.Assign)
                else [node.target] if isinstance(node, ast.AnnAssign)
                else []
            )
            for target in targets:
                if (isinstance(target, ast.Attribute) and target.attr == "_selection"
                        and isinstance(target.value, ast.Name) and target.value.id == "self"):
                    writers.add(function.name)
            if (isinstance(node, ast.Attribute) and node.attr == "_selection"
                    and isinstance(node.ctx, ast.Load)
                    and isinstance(node.value, ast.Name) and node.value.id == "self"):
                readers.add(function.name)

    assert writers == {"__init__", "reset", "_set_selection"}
    assert readers == {"_chosen"}, "everything else asks `_chosen()`"


def test_the_choose_menu_stays_open_across_a_tick():
    """Qt closes a menu on every activation, which for a checklist is one opening per driver.
    A whole side is four ticks; four trips through a twenty-row list is why nobody would use it."""
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QMouseEvent

    dialog = _group_dialog()
    _fetch(dialog)
    menu = dialog._choose_menu
    action = dialog._choose_actions["m-L_02 (sw)"]
    menu.popup(QPoint(0, 0))
    menu.setActiveAction(action)

    menu.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(1.0, 1.0), QPointF(1.0, 1.0),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    ))
    _fetch(dialog)

    assert action.isChecked() is True, "the row toggled"
    assert "m-L_02 (sw)" in dialog._chosen(), "and the selection took it"
    assert menu.isVisible() is True, "and the menu is still standing, ready for the next one"
    assert dialog._choose_actions["m-L_02 (sw)"] is action, \
        "the actions were not rebuilt under it — destroying one mid-`toggled` ends the process"
    menu.close()


def test_every_picker_on_the_chip_row_stays_visible_through_the_sum():
    """User, 2026-08-21: "вибір груп показуй завжди … логіка проста — швидкий вибір, а групи це
    розумні комбінації".

    This reverses 2026-08-18 ("поки я не включив суму немає сенсу показувати ось ці групи"), and
    the reversal is the point of the test: version and group say WHAT IS DRAWN, which is not a
    question about sums, so Σ must not decide whether they are on screen. Σ draws the sum.
    """
    dialog = _group_dialog()
    _fetch(dialog)
    row = (dialog._group_combo, dialog._version_combo,
           dialog._choose_btn, dialog._kind_combo)

    assert dialog._view.sum_shown() is False
    assert all(widget.isVisibleTo(dialog) for widget in row)

    dialog._view.set_sum_shown(True)
    assert all(widget.isVisibleTo(dialog) for widget in row)

    dialog._view.set_sum_shown(False)
    assert all(widget.isVisibleTo(dialog) for widget in row)
    assert all(chip.isVisibleTo(dialog) for chip in _chips(dialog))

def test_the_guides_button_is_red_and_big_from_the_moment_the_window_opens():
    """It opened grey: its look was an inline stylesheet written only by `_update_guides_button`,
    and nothing called that at construction. The font was set as a QFont, which a QSS `font-size`
    on `.zoom-btn` beat outright — so the "big red X" that was asked for was neither."""
    from autosound_tcc.ui.tcc.theme import build_qss

    view = _view()

    assert view._guides_btn.property("class") == "guides-btn"
    assert view._guides_btn.styleSheet() == "", "the class paints it, not a sheet written by hand"
    qss = build_qss(current_theme())
    rule = qss.split('QPushButton[class~="guides-btn"]')[1]
    assert current_theme().warn in rule, "red at rest"
    assert "font-size: 17px" in rule, "and bigger than the 12px zoom buttons beside it"
    assert 'QPushButton[class~="guides-btn"]:checked' in qss, "filled while the guides are off"


def test_the_link_button_wears_an_orange_ring_in_both_states():
    """User, 2026-08-18: "ободок помаранчевого кольору, щоб на неї звертали увагу". `accent` IS
    this palette's orange; `warn` means "wrong" and `yellow` is the predicted sum's own colour."""
    from autosound_tcc.ui.tcc.theme import build_qss, get_theme

    view = _view()

    assert view._link_btn.property("class") == "link-btn"
    assert view._link_btn.styleSheet() == ""
    for mode in ("dark", "light"):
        theme = get_theme(mode)
        rule = build_qss(theme).split('QPushButton[class~="link-btn"]')[1]
        assert f"border: 2px solid {theme.accent}" in rule, f"the ring, in {mode}"
        assert theme.warn not in rule, "and it must not read as an error"
    assert view._link_btn.isVisibleTo(view) is False, "still not offered on an impulse"


def test_pressing_a_marker_control_puts_the_guides_back():
    """User: "коли нажав любу іншу то Х скинувся". With the guides hidden the mode buttons place
    lines nothing draws, so they look broken — pressing one means the tuner wants the guides."""
    view = _view()
    view.set_markers([4.52, 4.78])
    view.set_guides_hidden(True)
    assert view.guides_hidden() is True

    button = next(b for b, mode in view._axes_buttons if mode == "vh")
    button.click()

    assert view.guides_hidden() is False
    assert view._axes_mode == "vh", "and it did what it says as well"
    assert view._guides_btn.isChecked() is False, "the ✕ says so too"

    # The markers' own action does it as well: fetching invisible lines back answers nothing.
    view.set_guides_hidden(True)
    view.bring_markers_into_view(force=True)
    assert view.guides_hidden() is False


def test_the_view_controls_leave_the_hide_alone():
    """The other half of the rule. A tuner who took every line off in order to LOOK at the traces
    would lose that the moment they zoomed in, and the Σ and link toggles are not about guides."""
    view = _view()
    view.set_markers([4.52, 4.78])
    view.set_guides_hidden(True)

    for button, _key in view._zoom_buttons:
        button.click()
        assert view.guides_hidden() is True, "a zoom is about the view, not about the guides"
    view.set_sum_shown(True)
    view.set_strip_linked(False)

    assert view.guides_hidden() is True


def test_the_kind_switching_under_the_window_does_not_put_the_guides_back():
    """`set_axes_mode` is called by the dialog on every kind switch, so the release cannot live in
    the setter: it would put the guides back behind a tuner who is reading a curve."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FrBridge(), kind="impulse", available=every)
    dialog._worker.wait(4000)
    dialog._view.set_guides_hidden(True)

    dialog._kind_combo.setCurrentIndex(dialog._kind_combo.findData("fr"))
    dialog._worker.wait(4000)

    assert dialog._view.guides_hidden() is True


# ---- where the level markers start (user, 2026-08-18) ----------------------------------------


def test_two_levels_that_would_land_on_top_of_each_other_are_spread_out():
    """User: "коли вибираю горизонтальні маркери, вони в самому низу — зручно було, коли вони по
    середині рознесені між собою". Two drivers at the same level put both lines in one place, and
    on an impulse — where the trace is at ~0 almost everywhere — that place is the bottom edge."""
    view = _fr_view(_fr_trace("w-L_01 (sw)", level_db=90.0),
                    _fr_trace("w-R_01 (sw)", level_db=90.0))
    view.set_markers([1000.0, 1000.0], tokens=["accent", "info"])

    view.set_axes_mode("vh")

    low, high = view._visible_y()
    levels = view.levels()
    assert len(levels) == 2
    assert abs(levels[0] - levels[1]) > (high - low) * 0.05, "two lines, not one"
    assert all(low <= level <= high for level in levels), "and both inside the picture"
    # Still just a starting point: they drag anywhere afterwards.
    view._h_markers[1].setValue(low + (high - low) * 0.1)
    assert view.levels()[1] == pytest.approx(low + (high - low) * 0.1)


def test_levels_far_enough_apart_still_start_on_their_own_curves():
    """The on-curve start is right where it works, and that is most of the frequency response:
    "what is this trace doing here" is the first thing anybody asks of a level marker."""
    view = _fr_view(_fr_trace("w-L_01 (sw)", level_db=90.0),
                    _fr_trace("w-R_01 (sw)", level_db=70.0))
    view.set_markers([1000.0, 1000.0], tokens=["accent", "info"])

    view.set_axes_mode("vh")

    assert view.levels()[0] == pytest.approx(90.0, abs=0.01)
    assert view.levels()[1] == pytest.approx(70.0, abs=0.01)


def test_a_level_that_would_start_off_screen_is_brought_into_the_picture():
    """The other half of unreadable: a line outside the visible span is a reading nobody can see,
    and the phase reaches −180 at the very bottom of its own axis."""
    view = _fr_view(_fr_trace("w-L_01 (sw)", level_db=90.0),
                    _fr_trace("w-R_01 (sw)", level_db=89.0))
    view.set_markers([1000.0, 1000.0], tokens=["accent", "info"])
    view._plot.getViewBox().setYRange(0.0, 10.0, padding=0)

    view.set_axes_mode("vh")

    assert all(0.0 <= level <= 10.0 for level in view.levels())


# ---- one row at the bottom instead of three (user, 2026-08-18) --------------------------------


def test_the_notes_and_the_delay_bank_share_one_row():
    """User, with the screenshot of three stacked lines: "ось ці кнопки всі стануть в ряд в самому
    низу, щоб не займати простір". They belonged to two widgets, which is why they were stacked.

    On 2026-08-19 that row also took the delay radios, at its left end and in front of the stretch
    — see `test_the_bottom_rows_are_driver_then_settings_then_view`."""
    _app()
    from autosound_tcc.core import delay_bank

    delay_bank.put("w-L_01 (sw)", 0.198)
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FrBridge(), kind="fr", available=every)
    dialog._worker.wait(4000)
    dialog._worker.run()
    view = dialog._view

    order = _widgets(view._notes_row)

    for button in (view._sum_note_btn, view._readout_btn, dialog._bank_btn,
                   dialog._bank_clear_btn, dialog._markers_clear_btn):
        assert button in order, "one row, both widgets' buttons on it"
    assert order.index(view._sum_note_btn) < order.index(view._readout_btn)
    assert order.index(view._readout_btn) < order.index(dialog._bank_btn)
    assert order.index(dialog._bank_btn) < order.index(dialog._bank_clear_btn), \
        "notes on the left, the actions that undo them on the right"
    # Nothing regressed on the way: the count, the tip and the warning colour are what these are.
    assert dialog._bank_btn.text() == i18n.t("curveBankBtn").format(n=1)
    assert "w-L_01 (sw) +0.198" in _tip(dialog._bank_btn)
    assert i18n.t("curveDelayHead") in _tip(view._readout_btn)


# ---- the x range stays the one the window stated (user, 2026-08-18: ticks to 500000k) ---------


def _log_span(view) -> tuple:
    return tuple(view._plot.getPlotItem().vb.viewRange()[0])


def test_a_kind_switch_cannot_run_the_frequency_axis_away():
    """`PlotItem.updateLogMode` ends with a bare `enableAutoRange()` — both axes — so after every
    `set_log_x` the x range was at the mercy of any item added or removed, in whatever coordinates
    it carried. On a kind switch those coordinates change underneath it (ms above, log-hertz
    below), and the axis ran out past 10^8 Hz with the curves crushed into the left third."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FrBridge(), kind="impulse", available=every)
    dialog._worker.wait(4000)
    dialog._worker.run()

    for kind in ("phase", "fr", "impulse", "phase"):
        dialog._kind_combo.setCurrentIndex(dialog._kind_combo.findData(kind))
        dialog._worker.wait(4000)
        dialog._worker.run()
        low, high = _log_span(dialog._view)
        if kind == "impulse":
            continue  # milliseconds; the band below is a statement about frequency
        # Inside a decade either side of the band this window opens a frequency view on.
        assert 0.3 <= low <= 1.4, f"{kind}: left edge at 10^{low:.2f} Hz"
        assert 4.3 <= high <= 5.3, f"{kind}: right edge at 10^{high:.2f} Hz"
        assert dialog._view._plot.getPlotItem().vb.autoRangeEnabled()[0] is False, \
            "and the x range is this window's to state, never pyqtgraph's to guess"


def test_the_sum_going_on_does_not_move_the_frequency_axis():
    """The strip appears, the window relays out, and everything that follows a resize gets a say.
    None of them may move the span the tuner is reading."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FrBridge(), kind="phase", available=every)
    dialog._worker.wait(4000)
    dialog._worker.run()
    before = _log_span(dialog._view)

    dialog._view.set_sum_shown(True)
    dialog._view.set_sum_shown(False)
    dialog._view.set_sum_shown(True)

    assert _log_span(dialog._view) == pytest.approx(before, abs=0.01)


def test_the_linked_strip_reads_the_same_frequencies_as_the_plot_above():
    """"той самий масштаб і позиціювання, що і фаза" — and the two boxes have different left-axis
    widths, so pyqtgraph aligns them in SCREEN x rather than copying the numbers. What must hold
    is that the strip is looking at the same octaves, not at its own data bounds."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FrBridge(), kind="phase", available=every)
    dialog.show()  # a link is lined up in SCREEN x, so both boxes need a geometry
    dialog._worker.wait(4000)
    dialog._worker.run()
    dialog._view.set_sum_shown(True)
    _app().processEvents()

    assert dialog._view.strip_linked() is True
    plot_low, plot_high = _log_span(dialog._view)
    strip_low, strip_high = dialog._view._strip.getPlotItem().vb.viewRange()[0]

    assert abs(strip_low - plot_low) < 0.2 and abs(strip_high - plot_high) < 0.2


def test_the_impulse_strip_opens_on_the_audible_band_and_stays_there():
    """There is nothing to link to — the plot above is in milliseconds — so the strip states its
    own band, and no auto-range over its contents is allowed to drift it off."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FrBridge(), kind="impulse", available=every)
    dialog._worker.wait(4000)
    dialog._worker.run()

    dialog._view.set_sum_shown(True)

    assert dialog._view.strip_linked() is False
    low, high = dialog._view._strip.getPlotItem().vb.viewRange()[0]
    assert low == pytest.approx(math.log10(20.0), abs=0.05)
    assert high == pytest.approx(math.log10(20000.0), abs=0.05)


# ---- the grid, which REW has and this window did not (user, 2026-08-18) -----------------------


def test_both_axes_keep_a_grid_through_every_kind_switch():
    """The grid belongs to the axis ITEM, and `set_log_x` installs a NEW bottom axis on every kind
    switch. `showGrid` cannot put it back: it only ticks pyqtgraph's own checkbox, which is already
    ticked, so nothing emits and `updateGrid` never runs. Measured before the fix on a frequency
    view: `bottom.grid` False while `left.grid` was 255 — one direction of the same picture had
    lines and the other had none, which is exactly what the screenshot showed."""
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FrBridge(), kind="impulse", available=every)
    dialog._worker.wait(4000)
    dialog._worker.run()

    for kind in ("fr", "phase", "impulse", "fr"):
        dialog._kind_combo.setCurrentIndex(dialog._kind_combo.findData(kind))
        dialog._worker.wait(4000)
        dialog._worker.run()
        item = dialog._view._plot.getPlotItem()
        assert item.getAxis("bottom").grid, f"{kind}: nothing to measure frequency against"
        assert item.getAxis("left").grid, f"{kind}: nothing to measure level against"


def test_the_delay_radios_can_be_counted_at_a_glance():
    """User, 2026-08-18: "сорі, я не побачив що їх вже три". An unstyled radio indicator is a dark
    circle on this dark ground, so a row of three read as one control and two smudges.

    Asserted through the CLASS and the rule that paints it rather than through pixels: a test that
    pinned hex values would break on every palette tweak and tell nobody anything."""
    from autosound_tcc.ui.tcc.curve_view import colour_of, trace_token
    from autosound_tcc.ui.tcc.theme import build_qss, get_theme

    view = _view()

    assert [b.property("class") for b in view._target_buttons[:2]] == ["delay-radio"] * 2
    for mode in ("dark", "light"):
        theme = get_theme(mode)
        qss = build_qss(theme)
        ring = qss.split('QRadioButton[class~="delay-radio"]::indicator')[1].split("}")[0]
        assert f"border: 2px solid {theme.muted}" in ring, f"{mode}: an unselected ring to count"
        checked = qss.split('QRadioButton[class~="delay-radio"]::indicator:checked')[1]
        assert theme.accent in checked.split("}")[0], f"{mode}: and the chosen one still fills"
    # The NAME keeps its trace's colour, which is how a radio is matched to a curve without words.
    assert colour_of(trace_token(1)).name() in view._target_buttons[1].styleSheet()


# ---- a delay set is only defined up to a common offset (user, 2026-08-18) ---------------------


def test_the_proposal_is_the_differences_not_where_the_curves_were_dropped():
    """The user's own bank, checked against their project file: three drivers dragged onto a common
    ~14.8 ms and proposed as +10.690 / +10.670 / +10.000 ("затримки виходять значно більшими, ніж
    вони там є"). Nothing was miscomputed — they dragged there and the window recorded it — but a
    delay set is only defined up to a common offset, and 10.69 ms of delay on a driver is both
    physically meaningless and past what most processors will take.

    Relative, the same three are 0 / +0.67 / +0.69, and 0.69 ms is 23 cm: a real car.
    """
    view = _view()
    arrivals = {"m-R_01 (sw)": 4.124, "tw-R_01 (sw)": 4.173, "w-R_01 (sw)": 4.979}
    view.set_traces([Trace(name, *_impulse(ms)) for name, ms in arrivals.items()])
    view.set_resolution(0.01, 96000)
    for index, ms in enumerate((10.690, 10.670, 10.000)):  # dragged onto a common ~14.8 ms
        view.set_delay_target(index)
        view.set_delay(ms)

    assert view.delays() == pytest.approx([10.690, 10.670, 10.000]), \
        "the drag itself is untouched — that is the tuner's handle on the picture"
    assert view.proposed_delays() == pytest.approx([0.690, 0.670, 0.0], abs=1e-9)
    assert view.delay_reference_name() == "w-R_01 (sw)", "the latest arrival needs no delay"

    reading = view.reading()

    assert "m-R_01 (sw) +0.690" in reading and "tw-R_01 (sw) +0.670" in reading
    assert "w-R_01 (sw) +0.000" in reading, "the origin is IN the set, at rest, not left out of it"
    assert "+10.690" not in reading and "+10.000" not in reading
    assert i18n.t("curveDelayRelative").format(name="w-R_01 (sw)") in reading, \
        "and the sentence says what it is measured from"


def test_normalising_moves_every_landing_by_one_number_and_no_difference():
    """The property that makes it safe: a constant comes off all of them, so what the set SAYS
    about the car — how far apart the drivers land — is bit for bit what it said before."""
    view = _view()
    view.set_traces([Trace(f"d{i}_01 (sw)", *_impulse(4.0 + i * 0.4)) for i in range(3)])
    for index, ms in enumerate((10.690, 10.670, 10.000)):
        view.set_delay_target(index)
        view.set_delay(ms)

    raw, proposed = view.delays(), view.proposed_delays()

    gaps_raw = [raw[i] - raw[0] for i in range(3)]
    gaps_proposed = [proposed[i] - proposed[0] for i in range(3)]
    assert gaps_raw == pytest.approx(gaps_proposed, abs=1e-9)
    assert min(proposed) == 0.0, "and the set now starts from zero, where a DSP can take it"


def test_one_driver_alone_is_left_exactly_as_it_was_read():
    """There is nothing to be relative TO, and zeroing the only proposal would erase the tuner's
    work while putting nothing in its place."""
    view = _view()
    view.set_traces([Trace("w-L_01 (sw)", *_impulse(4.52))])
    view.set_delay(1.75)

    assert view.proposed_delays()[0] == pytest.approx(1.75)
    assert view.delay_reference_name() == "", "and no origin is claimed for a set of one"
    assert "+1.750" in view.reading()
    assert i18n.t("curveDelayRelative").format(name="w-L_01 (sw)") not in view.reading()


def test_a_set_already_stated_from_zero_is_not_touched_again():
    """Idempotence, and the reason the minimum is taken over every trace and not only the dragged
    ones. A driver at 0 is as often the reference the others were aligned TO as one nobody has
    reached, and this window cannot tell — so it counts. Skipping the zeros re-based a set that
    already had an origin: 0 / +0.67 / +0.69 came back as 0 / 0 / +0.02, which is a different car.
    """
    view = _view()
    view.set_traces([Trace(f"d{i}_01 (sw)", *_impulse(4.0 + i * 0.3)) for i in range(3)])
    for index, ms in enumerate((0.0, 0.67, 0.69)):
        view.set_delay_target(index)
        view.set_delay(ms)

    assert view.proposed_delays()[:3] == pytest.approx([0.0, 0.67, 0.69]), "already relative"
    assert view.delay_reference_name() == "d0_01 (sw)", "the zero IS the origin here"
    # And the origin is in the list even though nobody dragged it, or the caveat would name a
    # driver the numbers never mention.
    assert "d0_01 (sw) +0.000" in view.reading()


def test_the_below_zero_check_reads_the_number_a_dsp_would_receive():
    """`total_delay_ms` is the channel's ledger delay plus the PROPOSAL, and the proposal is the
    normalised one — checking the raw drag warned about a number nobody would ever be asked for."""
    view = _view()
    view.set_traces([Trace("w-L_01 (sw)", *_impulse(4.5)), Trace("w-R_01 (sw)", *_impulse(4.9))])
    view.set_channel_delay(0.100, 0)
    view.set_channel_delay(1.000, 1)
    view.set_delay_target(0)
    view.set_delay(-0.5)
    view.set_delay_target(1)
    view.set_delay(0.25)

    # Raw, w-L would have been 0.100 − 0.500 = −0.400 and refused. Normalised it is asked for
    # nothing, and w-R carries the whole 0.750 that was actually measured between them.
    assert view.total_delay_ms(0) == pytest.approx(0.100)
    assert view.total_delay_ms(1) == pytest.approx(1.750)
    assert i18n.t("curveDelayBelowZero") not in view.reading()


def test_the_ledger_delays_are_a_different_quantity_and_are_left_alone():
    """`_channel_delays` come from the project and are already absolute per channel. Normalising a
    PROPOSAL must not reach into them, or the totals would be computed against a moved ledger."""
    view = _view()
    view.set_traces([Trace("w-L_01 (sw)", *_impulse(4.5)), Trace("w-R_01 (sw)", *_impulse(4.9))])
    view.set_channel_delay(1.266, 0)
    view.set_channel_delay(0.500, 1)
    view.set_delay_target(0)
    view.set_delay(10.69)
    view.set_delay_target(1)
    view.set_delay(10.00)

    assert view._channel_delays[:2] == pytest.approx([1.266, 0.500]), "untouched by any of it"
    assert view.total_delay_ms(0) == pytest.approx(1.266 + 0.69)
    assert view.total_delay_ms(1) == pytest.approx(0.500)


# ---- an all-pass per driver (CURVE-ANALYSIS-PLAN.md step 4, SCR-050) ---------------------------
#
# The filter is the skill's (`core/allpass.py` → `dsp_math`), so everything below needs the
# submodule; what is tested HERE is what the view does with one — which driver it lands on, what
# moves and what does not, what the legend and the reading say — not the filter's own physics,
# which `test_allpass.py` and `test_curve_sum.py` pin.

_needs_skill = pytest.mark.skipif(
    not __import__("autosound_tcc.core.vendor_loader", fromlist=["x"]).is_available(),
    reason="rew_tool submodule not checked out",
)


def _pick_apf(view: CurveView, order: int, f0: float, q: float = 0.71) -> None:
    """Dial an all-pass the way the tuner does: the combo, then the boxes."""
    view._apf_kind.setCurrentIndex(view._apf_kind.findData(order))
    view._apf_f0.setValue(f0)
    if order == 2:
        view._apf_q.setValue(q)


@_needs_skill
def test_the_all_pass_row_edits_the_driver_the_radio_chose():
    """Same editing model as the delay: the radio picks WHICH driver, and both rows edit that one —
    so "which driver am I changing" has one answer, not two."""
    from autosound_tcc.core.allpass import Allpass

    view = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("m-L_01 (sw)"))
    assert view._apf_f0.isEnabled() is False and view._apf_q.isEnabled() is False, "nothing chosen"
    view.set_delay_target(1)

    _pick_apf(view, 2, 1000.0, 0.71)

    assert view.allpass(1) == Allpass(2, 1000.0, 0.71)
    assert view.allpass(0) is None, "the other driver is untouched"
    assert view._apf_f0.isEnabled() and view._apf_q.isEnabled()
    assert view._apf_target_label.text() == "m-L_01", "the row names whose filter this is"

    view.set_delay_target(0)
    assert view._apf_kind.currentData() == 0 and view._apf_q.isEnabled() is False, "driver 0: none"
    view.set_delay_target(1)
    assert view._apf_kind.currentData() == 2 and view._apf_f0.value() == pytest.approx(1000.0)


@_needs_skill
def test_a_first_order_all_pass_has_no_q_box_to_offer():
    view = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("m-L_01 (sw)"))

    _pick_apf(view, 1, 80.0)

    assert view.allpass().kind == "APF1" and view.allpass().q is None
    assert view._apf_f0.isEnabled() and view._apf_q.isEnabled() is False


@_needs_skill
def test_on_the_phase_plot_an_all_pass_rotates_the_curve_and_on_the_magnitude_it_does_not():
    """Unit magnitude is what makes it an all-pass: −180° exactly at f0 on the phase, and not a
    hair of movement on the frequency response."""
    phase = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("m-L_01 (sw)"))
    phase.set_delay_target(1)
    _pick_apf(phase, 2, 1000.0, 0.71)
    x, y = phase._shifted(1, phase._traces[1])
    # Against the trace's OWN curve (the fixture's y is not zero), wrapped the way the plot wraps.
    turned = (np.asarray(y) - np.asarray(phase._traces[1].y, dtype=float) + 180.0) % 360.0 - 180.0
    at_f0 = int(np.abs(np.asarray(x) - 1000.0).argmin())
    assert abs(abs(float(turned[at_f0])) - 180.0) < 6.0, "half a turn at f0 (the grid is 1/24 oct)"
    assert abs(float(turned[0])) < 6.0, "and almost nothing two decades below it"
    _x0, y0 = phase._shifted(0, phase._traces[0])
    assert list(y0) == pytest.approx(list(phase._traces[0].y)), "the other driver did not move"

    magnitude = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("m-L_01 (sw)"))
    magnitude.set_delay_target(1)
    _pick_apf(magnitude, 2, 1000.0, 0.71)
    _x1, y1 = magnitude._shifted(1, magnitude._traces[1])
    assert list(y1) == pytest.approx(list(magnitude._traces[1].y))


@_needs_skill
def test_on_the_impulse_the_drawn_trace_stays_as_captured_and_the_strips_sum_carries_the_all_pass():
    """An all-pass smears an impulse, and re-filtering the time series is a round trip through the
    FFT this window does not make. The strip is where the joint is read, and it carries it."""
    view = _impulse_sum_view()
    view.set_delay_target(1)
    before = view._shifted(1, view._traces[1])

    _pick_apf(view, 2, 1000.0, 0.71)
    view.set_sum_shown(True)

    x, y = view._shifted(1, view._traces[1])
    assert list(x) == pytest.approx(list(before[0])) and list(y) == pytest.approx(list(before[1]))
    result = view.sum_result()
    assert result.contributions[1].allpass is not None
    assert result.contributions[1].allpass.label() == "APF2 1000 Hz Q 0.71"
    at_f0 = int(np.abs(np.asarray(result.freqs_hz) - 1000.0).argmin())
    assert result.magnitude_db[at_f0] < 80.0, "two identical drivers, one turned half round: a null"


@_needs_skill
def test_the_sum_follows_the_all_pass_without_going_back_to_rew():
    """The point of the row: the joint answers while the number is being typed. Two identical
    drivers sum +6 dB; turn one of them −180° at 1 kHz and they cancel there and only there."""
    view = _fr_view(_fr_trace("w-L_01 (sw)"), _fr_trace("m-L_01 (sw)"))
    view.set_sum_shown(True)
    assert _at(view.sum_result(), 1000.0) == pytest.approx(96.02, abs=0.01)
    view.set_delay_target(1)

    _pick_apf(view, 2, 1000.0, 0.71)

    assert _at(view.sum_result(), 1000.0) < 75.0, "half a turn at f0 is a cancellation"
    assert _at(view.sum_result(), 20.0) == pytest.approx(96.02, abs=0.05), "and nothing far away"

    view._apf_kind.setCurrentIndex(0)
    assert _at(view.sum_result(), 1000.0) == pytest.approx(96.02, abs=0.01), "off again"


@_needs_skill
def test_the_reading_names_the_all_pass_as_a_proposal_in_the_ledgers_words():
    """A rotation with no filter named is a picture nobody can re-enter. Its own clause, not folded
    into the delay's: `ta_ms` and an EQ band are typed in two different places."""
    view = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("m-L_01 (sw)"))
    assert "all-pass" not in view.reading()
    view.set_delay_target(1)

    _pick_apf(view, 2, 250.0, 0.71)
    reading = view.reading()

    assert "m-L_01 (sw): APF2 250 Hz Q 0.71" in reading
    assert "proposed" in reading or "пропозиц" in reading
    assert "w-L_01" not in reading.split("APF2")[0].split(":")[-1], "the other driver is not named"
    assert view._send_btn.isEnabled(), "worth sending on its own, no marker placed"
    assert "APF2 250 Hz Q 0.71" in view.statement()


@_needs_skill
def test_the_all_pass_and_the_delay_are_two_clauses_on_the_same_driver():
    view = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("m-L_01 (sw)"))
    view.set_delay_target(1)
    view.set_delay(0.25)
    _pick_apf(view, 1, 80.0)

    reading = view.reading()

    assert i18n.t("curveDelayHead") in reading and i18n.t("curveApfHead") in reading
    assert "+0.250" in reading and "APF1 80 Hz" in reading


@_needs_skill
def test_the_legend_names_the_rotation_with_the_driver():
    """A curve that has been rotated and a legend that says only the name would be a plot nobody
    can read back into a DSP setting."""
    view = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("m-L_01 (sw)"))
    view.set_delay_target(1)
    view.set_delay(0.25)
    _pick_apf(view, 2, 250.0, 0.71)

    labels = [label.text for _sample, label in view._legend.items]

    assert any("m-L_01 (sw)" in t and "+0.250 ms" in t and "APF2 250 Hz Q 0.71" in t for t in labels)
    assert any(t.strip() == "w-L_01 (sw)" for t in labels), "the untouched driver is just its name"


@_needs_skill
def test_a_new_selection_takes_every_all_pass_off():
    """A new selection is a new question, exactly as for the delays. (The window's bank puts a
    driver's own filter back the moment it recognises the title; the view keeps nothing.)"""
    view = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("m-L_01 (sw)"))
    view.set_delay_target(1)
    _pick_apf(view, 2, 250.0, 0.71)

    view.set_traces([_fr_trace("tw-L_01 (sw)"), _fr_trace("tw-R_01 (sw)")])

    assert view.allpasses()[:2] == [None, None]
    assert view._apf_kind.currentData() == 0 and view._apf_f0.isEnabled() is False


@_needs_skill
def test_the_all_pass_has_its_own_signal_and_does_not_pose_as_a_delay():
    """The window banks the two side by side per measurement; a handler that could not tell which
    one moved would have to re-bank both on every change."""
    view = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("m-L_01 (sw)"))
    apf_fired, delay_fired = [], []
    view.allpassChanged.connect(lambda: apf_fired.append(1))
    view.delayChanged.connect(lambda: delay_fired.append(1))

    _pick_apf(view, 1, 80.0)

    assert apf_fired and not delay_fired
    assert view.delays() == pytest.approx([0.0, 0.0]), "no delay was invented"


def test_an_all_pass_the_skill_cannot_compute_is_refused_on_the_row_and_the_boxes_go_back(
    monkeypatch,
):
    """A filter that cannot be computed must not be accepted as if it could, or the legend would
    name a rotation the plot does not show. The row says why, and returns to none."""
    from autosound_tcc.core.allpass import Allpass

    def _no_skill(self, freqs):
        raise RuntimeError("no skill on this machine")

    monkeypatch.setattr(Allpass, "response", _no_skill)
    view = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("m-L_01 (sw)"))

    _pick_apf(view, 2, 250.0, 0.71)

    assert view.allpass() is None
    assert view._apf_kind.currentData() == 0
    assert view._apf_note.isVisibleTo(view) and "no skill on this machine" in view._apf_note.text()
    assert "all-pass" not in view.reading()


@_needs_skill
def test_the_all_pass_row_survives_a_language_switch():
    """`retranslate` rewrites the label, the none item and the tips, and nothing else moves."""
    view = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("m-L_01 (sw)"))
    _pick_apf(view, 2, 250.0, 0.71)
    was = i18n.current_language()
    try:
        i18n.set_language("uk" if was != "uk" else "en")
        view.retranslate()
        assert view._apf_label.text() == i18n.t("curveApfLabel")
        assert view._apf_kind.itemText(0) == i18n.t("curveApfNone")
        assert view.allpass().label() == "APF2 250 Hz Q 0.71", "the filter itself is not translated"
        assert i18n.t("curveApfHead") in view.reading()
    finally:
        i18n.set_language(was)
        view.retranslate()


# ---- the all-pass in the bank, beside the delay -----------------------------------------------


@_needs_skill
def test_an_all_pass_is_banked_with_the_driver_and_comes_back_with_it():
    """The workflow the Advisor described — load a group, look at the sum, isolate a driver with
    its × — loses a filter on the first × unless the bank keeps it: a driver taken off the plot and
    put back is a new selection to the view, and the view keeps nothing across a selection."""
    from autosound_tcc.core import delay_bank
    from autosound_tcc.core.allpass import Allpass

    dialog = _dialog(["w-L_01 (sw)", "m-L_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)), Trace("m-L_01 (sw)", *_impulse(4.78))])
    dialog._view.set_delay_target(1)

    _pick_apf(dialog._view, 2, 250.0, 0.71)

    assert delay_bank.allpasses() == {"m-L_01 (sw)": Allpass(2, 250.0, 0.71)}
    assert delay_bank.load() == {}, "no delay was invented alongside it"

    # m-L comes back against a different partner: the filter is on it before anybody touches it.
    dialog._on_curves([Trace("m-L_01 (sw)", *_impulse(4.78)), Trace("tw-L_01 (sw)", *_impulse(4.30))])

    assert dialog._view.allpass(0) == Allpass(2, 250.0, 0.71), "restored onto m-L, now trace 0"
    assert dialog._view.allpass(1) is None
    assert delay_bank.allpasses() == {"m-L_01 (sw)": Allpass(2, 250.0, 0.71)}, "restoring banked nothing new"


@_needs_skill
def test_moving_a_delay_does_not_wipe_the_all_pass_and_dialling_an_all_pass_keeps_the_delay():
    """One entry, two fields, and every write goes through the same handler — which re-banks the
    driver's whole current state rather than one field over the other."""
    from autosound_tcc.core import delay_bank
    from autosound_tcc.core.allpass import Allpass

    dialog = _dialog(["w-L_01 (sw)", "m-L_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)), Trace("m-L_01 (sw)", *_impulse(4.78))])
    dialog._view.set_delay_target(1)
    _pick_apf(dialog._view, 1, 80.0)

    dialog._view.set_delay(0.26)

    assert delay_bank.load() == {"m-L_01 (sw)": 0.26}
    assert delay_bank.allpasses() == {"m-L_01 (sw)": Allpass(1, 80.0)}, "the delay did not wipe it"

    _pick_apf(dialog._view, 2, 250.0, 0.71)

    assert delay_bank.load() == {"m-L_01 (sw)": 0.26}, "and the filter did not wipe the delay"
    assert delay_bank.allpasses() == {"m-L_01 (sw)": Allpass(2, 250.0, 0.71)}


@_needs_skill
def test_the_bank_button_counts_a_driver_once_whatever_it_carries_and_the_tip_names_the_filter():
    from autosound_tcc.core import delay_bank
    from autosound_tcc.core.allpass import Allpass

    delay_bank.put("w-L_01 (sw)", 0.4, allpass=Allpass(2, 250.0, 0.71))
    delay_bank.put("m-L_01 (sw)", 0.0, allpass=Allpass(1, 80.0))
    every = ["w-L_01 (sw)", "m-L_01 (sw)", "tw-L_01 (sw)"]
    dialog = _dialog(every[:2], bridge=_FakeBridge(), available=every)
    dialog._worker.wait(4000)

    dialog._render_bank()

    assert dialog._bank_btn.text() == i18n.t("curveBankBtn").format(n=2)
    tip = _tip(dialog._bank_btn)
    assert "w-L_01 (sw) +0.400 APF2 250 Hz Q 0.71" in tip
    assert "m-L_01 (sw) APF1 80 Hz" in tip
    assert dialog._bank_ask_btn.isEnabled() and dialog._bank_clear_btn.isEnabled()
    assert "APF1 80 Hz" in dialog._choose_actions["m-L_01 (sw)"].text()
    assert "+0.400 ms" in dialog._choose_actions["w-L_01 (sw)"].text()
    assert "APF2 250 Hz Q 0.71" in dialog._choose_actions["w-L_01 (sw)"].text()
    assert dialog._choose_actions["tw-L_01 (sw)"].text() == "tw-L_01 (sw)", "untouched stays plain"


def test_the_whole_set_goes_out_with_the_all_pass_block_and_its_own_caveat():
    """After the delays and before the zeros: part of the proposal, in the ledger's words, with
    the caveat that is this block's own — simulated, never checked against a summation sweep."""
    from autosound_tcc.core import delay_bank
    from autosound_tcc.core.allpass import Allpass

    text = delay_bank.as_sentence(
        {"w-L_01 (sw)": 0.4}, 96000, i18n.t,
        allpasses={"m-L_01 (sw)": Allpass(2, 250.0, 0.71), "w-L_01 (sw)": Allpass(1, 80.0)},
    )

    assert i18n.t("curveBankAsk") in text, "the delay head, because there is a delay"
    assert i18n.t("curveBankApf") in text
    assert "  m-L_01 (sw): APF2 250 Hz Q 0.71" in text and "  w-L_01 (sw): APF1 80 Hz" in text
    assert i18n.t("curveBankApfCaveat") in text
    assert text.index("+0.400") < text.index("APF2"), "delays first, then the all-passes"
    assert text.rstrip().endswith(i18n.t("curveBankNotForWriting"))

    delays_only = delay_bank.as_sentence({"w-L_01 (sw)": 0.4}, 96000, i18n.t)
    assert "APF" not in delays_only and i18n.t("curveBankApf") not in delays_only

    apf_only = delay_bank.as_sentence({}, 96000, i18n.t, allpasses={"m-L_01 (sw)": Allpass(1, 80.0)})
    assert apf_only.startswith(i18n.t("curveBankAskApfOnly")), "no delay head over an empty list"
    assert i18n.t("curveBankAsk") not in apf_only and "m-L_01 (sw): APF1 80 Hz" in apf_only
    assert i18n.t("curveBankNotForWriting") in apf_only


@_needs_skill
def test_clearing_the_delays_clears_the_all_pass_too():
    """One set, one clear (user, 2026-08-12, on why the delays and the markers clear separately:
    the delays are a set being built up over an afternoon — and the all-pass is part of it)."""
    from autosound_tcc.core import delay_bank

    dialog = _dialog(["w-L_01 (sw)", "m-L_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)), Trace("m-L_01 (sw)", *_impulse(4.78))])
    dialog._view.set_delay_target(1)
    _pick_apf(dialog._view, 2, 250.0, 0.71)
    dialog._view.set_delay(0.26)
    assert delay_bank.allpasses() and delay_bank.load()

    dialog._on_clear_bank()

    assert delay_bank.allpasses() == {} and delay_bank.load() == {}
    assert dialog._view.allpasses()[:2] == [None, None], "off the plot as well as out of the store"
    assert dialog._view._apf_kind.currentData() == 0


def test_a_zero_delay_with_an_all_pass_is_a_proposal_and_not_a_reference():
    """`references()` names drivers on screen with no shift — the reference on some passes, an
    untouched driver on others. A driver carrying an all-pass is neither: it has a proposal."""
    from autosound_tcc.core import delay_bank
    from autosound_tcc.core.allpass import Allpass

    delay_bank.put("m-L_01 (sw)", 0.0, allpass=Allpass(1, 80.0))
    delay_bank.put("w-L_01 (sw)", 0.0)

    assert delay_bank.references() == ["w-L_01 (sw)"]
    assert delay_bank.allpasses() == {"m-L_01 (sw)": Allpass(1, 80.0)}
    assert delay_bank.seen() == {"m-L_01 (sw)", "w-L_01 (sw)"}, "both were on screen"


def test_taking_the_all_pass_off_leaves_the_delay_and_the_entry():
    from autosound_tcc.core import delay_bank
    from autosound_tcc.core.allpass import Allpass

    delay_bank.put("m-L_01 (sw)", 0.3, allpass=Allpass(1, 80.0))
    delay_bank.put("m-L_01 (sw)", 0.3, allpass=None)

    assert delay_bank.allpasses() == {} and delay_bank.load() == {"m-L_01 (sw)": 0.3}


def test_an_entry_from_before_the_field_existed_reads_back_with_no_all_pass_and_survives_a_write():
    from autosound_tcc.core import config, delay_bank, project_settings

    project_settings.set_value(
        config.tcc_dir(), delay_bank.KEY,
        {"w-L_01 (sw)": 0.26, "m-L_01 (sw)": {"ms": 0.4, "at": 4.78}, "sw_01 (sw)": {"ms": 0.1, "apf": "junk"}},
    )

    assert delay_bank.allpasses() == {}
    assert delay_bank.load() == {"w-L_01 (sw)": 0.26, "m-L_01 (sw)": 0.4, "sw_01 (sw)": 0.1}
    delay_bank.put("m-L_01 (sw)", 0.5)
    assert delay_bank.load()["m-L_01 (sw)"] == 0.5 and delay_bank.allpasses() == {}
    stored = project_settings.load(config.tcc_dir())[delay_bank.KEY]
    assert "apf" not in stored["m-L_01 (sw)"], "the key is absent, not null, when there is none"


def test_the_bank_refuses_an_all_pass_that_is_not_one():
    from autosound_tcc.core import delay_bank

    with pytest.raises(TypeError):
        delay_bank.put("m-L_01 (sw)", 0.3, allpass={"type": "APF2", "f": 250.0, "q": 0.7})


# ---- the round of 2026-08-19: two markers, a structured reading, three rows -------------------
#
# Six asks in one sitting, with screenshots. What they have in common is that the window had grown
# per-curve where the QUESTION is not per curve: a marker is a place the tuner points at, a reading
# is a table of what the curves do there, and the controls are three lines about three different
# things (which driver, its settings, the view).


def test_two_markers_whatever_the_trace_count():
    """User, 2026-08-19: "число маркерів збільшується зі збільшенням числа кривих — а вони у нас
    постійні". One marker per curve made a whole side six dashed verticals over six curves, and it
    made a marker mean something it does not — a marker is a PLACE, a curve is what it is pointed
    at."""
    _app()
    for count in (1, 2, 4):
        dialog = _dialog([f"d{i}_01 (sw)" for i in range(count)], bridge=_FakeBridge())
        dialog._worker.wait(4000)

        dialog._on_curves([Trace(f"d{i}_01 (sw)", *_impulse(4.0 + 0.3 * i)) for i in range(count)])

        view = dialog._view
        assert len(view._markers) == 2, f"{count} traces, still a pair"
        assert view._marker_names == [i18n.t("curveMarkerOne"), i18n.t("curveMarkerTwo")]
        positions = view.positions()
        assert abs(positions[0] - 4.0) < 0.05, f"{count}: marker 1 on the first trace's peak"
        # With one curve both land on it, exactly as the model's own pair stacks; with two or more
        # the second marker takes the second trace's peak.
        assert abs(positions[1] - (4.0 + 0.3 * min(1, count - 1))) < 0.05


def test_the_markers_wear_their_own_colours_and_not_a_curves():
    """They are not tied to a curve any more, so wearing one's colour would be the picture claiming
    an ownership that is not there. The view's own two — muted for the first, ok for the second —
    are what says "these are the two places you are pointing at"."""
    from autosound_tcc.ui.tcc.curve_view import (
        _ARBITER_TOKEN, _MODEL_TOKEN, colour_of, trace_token,
    )

    _app()
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)

    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])

    view = dialog._view
    assert view._marker_tokens == [], "no tokens: the view's own marker colours"
    pens = [line.pen.color().name() for line in view._markers]
    assert pens == [colour_of(_MODEL_TOKEN).name(), colour_of(_ARBITER_TOKEN).name()]
    assert pens[0] != pens[1], "and never the same two"
    assert colour_of(trace_token(0)).name() not in pens, "nor a curve's"


def test_a_reading_from_the_model_is_still_the_pair_it_always_was():
    """The half that must not break: when the model HAS named a number, the two markers are its
    reading and the Arbiter's, named and coloured apart, stacked so every millimetre of movement
    is deliberate."""
    _app()
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], markers=[4.6], bridge=_FakeBridge())
    dialog._worker.wait(4000)

    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])

    view = dialog._view
    assert view.positions() == pytest.approx([4.6, 4.6])
    assert view._marker_names == [i18n.t("curveMarkerModel"), i18n.t("curveMarkerYou")]


def test_the_marker_reads_the_drawn_curve_not_the_captured_one():
    """`_y_at` is what places a level line "on its curve" and what the reading states. Read off the
    raw measurement, both went stale the moment a driver was held back: the line landed beside the
    curve it was supposed to be on, and the sentence quoted a value the picture does not show."""
    view = _view()
    view.set_markers([4.52, 4.78])
    at_peak = view._y_at(0, 4.52)

    view.set_delay_target(0)
    view.set_delay(1.0)

    assert view._y_at(0, 5.52) == pytest.approx(at_peak, abs=1e-9), "the peak moved with the curve"
    assert abs(view._y_at(0, 4.52)) < abs(at_peak), "and 4.52 is no longer where it arrives"


def test_the_marker_reads_a_rotated_phase_where_it_crosses_it():
    """The same rule on the phase, where a delay is a ramp: what the marker crosses is the DRAWN
    curve, so a driver rotated by its delay reads rotated."""
    view = _phase_view(_fr_trace("w-L_01 (sw)"), _fr_trace("w-R_01 (sw)"))
    before = view._y_at(1, 1000.0)
    view.set_delay_target(1)

    view.set_delay(0.5)

    x, y = view._shifted(1, view._traces[1])
    at = int(np.abs(np.asarray(x) - 1000.0).argmin())
    assert view._y_at(1, 1000.0) == pytest.approx(float(np.asarray(y)[at]), abs=1e-9)
    assert view._y_at(1, 1000.0) != pytest.approx(before), "half a millisecond is a rotation"


def test_the_index_is_clamped_so_marker_two_over_one_curve_still_reads():
    """Two markers and one trace is an ordinary picture now. Marker 2 has no curve of its own, so
    it reads the last one — which is the same curve the eye reads it against."""
    view = _view()
    view.set_traces([Trace("w-L_01 (sw)", *_impulse(4.52))])

    assert view._y_at(1, 4.52) == pytest.approx(view._y_at(0, 4.52))
    assert view._y_at(9, 4.52) == pytest.approx(view._y_at(0, 4.52))


def test_the_reading_states_every_trace_at_every_marker_then_the_deltas():
    """User, 2026-08-19: "додати поточні показники пересічення маркерів більш структуровано… щоб
    зразу бачити де що пересікається". Per MARKER, not per axis: it used to print every frequency
    in one clause and every level in another, which is two lists the reader has to zip together —
    and which said nothing at all about the curves once there were more than two of them."""
    view = _fr_view(_fr_trace("w-L_01 (sw)", level_db=90.0),
                    _fr_trace("m-L_01 (sw)", level_db=84.0),
                    _fr_trace("tw-L_01 (sw)", level_db=70.0))
    view.set_markers([100.0, 1000.0], ["1", "2"], [])

    reading = view.reading()

    one, two, delta = reading.split("; ", 2)
    assert one == "marker 1 at 100.0 Hz: w-L_01 (sw) 90.0 dB, m-L_01 (sw) 84.0 dB, " \
                  "tw-L_01 (sw) 70.0 dB"
    assert two.startswith("marker 2 at 1000.0 Hz:"), two
    assert delta.startswith("Δ 900.0 Hz; w-L_01 (sw) Δ 0.0 dB"), delta
    assert "tw-L_01 (sw) Δ 0.0 dB" in delta, "the Δ block covers every trace too"


def test_the_impulse_reading_is_positions_and_nothing_else():
    """A sample value is not a reading anybody takes off an impulse — the ARRIVAL is the question —
    so that block stays positions-only, and the curves are named once at the head instead."""
    view = _view()

    view.set_markers([4.52, 4.78], ["1", "2"], [])

    assert view.reading() == (
        "w-L_01 (sw) / w-R_01 (sw) — marker 1 at 4.520 ms; marker 2 at 4.780 ms; Δ 0.260 ms"
    )


def test_the_level_block_says_where_each_curve_reaches_that_level():
    """The mirror of the vertical block: a level per row, and where every trace gets there. The
    crossing chosen is the one nearest the vertical marker of the same number (`vh`), which is what
    makes the two halves of one reading read at the same place."""
    # One driver falling 10 dB a decade (95 dB at 20 Hz, so it passes 90 at 63.2 Hz) and one flat
    # at 70, which never reaches 90 at all.
    freqs = [20.0 * (2 ** (i / 24.0)) for i in range(240)]
    falling = Trace("w-L_01 (sw)", freqs, [95.0 - 10.0 * math.log10(f / 20.0) for f in freqs])
    view = _fr_view(falling, _fr_trace("m-L_01 (sw)", level_db=70.0))
    view.set_markers([100.0, 1000.0], ["1", "2"], [])

    view.set_axes_mode("vh")
    view._h_markers[0].setValue(90.0)
    view._h_markers[1].setValue(70.0)

    levels = view.reading().split("; ")[-3:]
    assert levels[0].startswith("marker 1 at 90.0 dB: w-L_01 (sw) 63."), levels[0]
    # A flat 70 dB curve never reaches 90: "—" is an answer, and a blank cell would read as a
    # number somebody forgot to fill in. No unit after it either — a unit would turn it back into
    # something that looks like a measurement.
    assert levels[0].endswith("m-L_01 (sw) —"), levels[0]
    assert levels[2] == "Δ -20.0 dB", "the levels' own difference, signed"


def test_the_readout_tip_is_a_table_in_the_markers_and_the_curves_own_colours():
    """The other half of the same ask: "колір показників співпадав з кольором маркерів". A row per
    marker in the MARKER's colour, a column per trace in the TRACE's, and the values in ordinary
    text — a number printed in the colour of the line it came off competes with its own label."""
    from autosound_tcc.ui.tcc.curve_view import _ARBITER_TOKEN, _MODEL_TOKEN, colour_of, trace_token

    view = _fr_view(_fr_trace("w-L_01 (sw)", level_db=90.0),
                    _fr_trace("m-L_01 (sw)", level_db=84.0))
    view.set_markers([100.0, 1000.0], ["1", "2"], [])

    html_text = view._readout_btn.hover_tip.text()

    assert "<table" in html_text, "a grid, not a sentence"
    assert i18n.t("curveReadoutBtn") in html_text, "and it says what it is answering about"
    for token in (_MODEL_TOKEN, _ARBITER_TOKEN):
        assert colour_of(token).name() in html_text, "each marker's row in the marker's colour"
    for index in (0, 1):
        assert colour_of(trace_token(index)).name() in html_text, "each column in the curve's"
    assert f"font-size: {15}px" in html_text, "large enough to read (user, 2026-08-18)"
    assert current_theme().text in html_text, "and the values in the ordinary text colour"


def test_the_bottom_rows_are_driver_then_settings_then_view():
    """User, 2026-08-19, with the screenshot: the three counters and the Clear pair to the right,
    the driver radios in their place, and all of the chosen driver's settings on ONE line."""
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    view = dialog._view

    notes = _widgets(view._notes_row)
    settings = _widgets(view._settings_row)
    actions = _widgets(view._action_row)

    # Row A: which driver, then everything that has been read of it.
    assert notes[:2] == view._target_buttons[:2], "the radios lead the row"
    assert notes.index(view._target_buttons[0]) < notes.index(view._sum_note_btn)
    assert notes[-1] is dialog._markers_clear_btn, "and the Clear pair ends it"
    # Row B: one line, one driver — named, delayed, filtered, and the action it produces.
    assert settings[0] is view._apf_target_label, "the row opens with whose settings these are"
    for control in (view._shift_box, dialog._bank_ask_btn, view._apf_kind,
                    view._apf_f0, view._apf_q):
        assert control in settings
    assert not any(radio in settings for radio in view._target_buttons)
    # Row C: how the markers read and what the view shows. Nothing about a driver on it.
    for control in ([b for b, _m in view._axes_buttons] + [view._guides_btn, view._link_btn]
                    + [b for b, _k in view._zoom_buttons] + view._cross_combos):
        assert control in actions
    assert view._shift_box not in actions and view._apf_kind not in actions


def test_the_top_is_one_wrapping_row_in_the_order_the_user_asked_for():
    """User, 2026-08-19: "порядок, починаючи з першого рядку: сети, режими, групи, «Обрати», далі
    вибрані криві — коли їх мало, все в одну строчку, як стане більше перенесеться на дві"."""
    dialog = _group_dialog(chosen=("w-L_02 (sw)", "w-R_02 (sw)"))
    _fetch(dialog)
    dialog._view.set_sum_shown(True)

    row = dialog._chip_row
    order = [row.itemAt(i).widget() for i in range(row.count())]

    assert order[:4] == [dialog._version_combo, dialog._kind_combo,
                         dialog._group_combo, dialog._choose_btn]
    assert [w.title() for w in order[4:4 + 2]] == dialog._chosen(), "then the chips, in plot order"
    # ...and a bigger selection still lands after the four controls rather than among them.
    _pick_group(dialog, "ALL")
    _fetch(dialog)
    grown = [row.itemAt(i).widget() for i in range(row.count())]
    assert grown[:4] == order[:4]
    assert [chip.title() for chip in _chips(dialog)] == dialog._chosen()


def test_the_y_grid_has_two_levels_of_line_and_not_three():
    """User, 2026-08-19: "сітка по вертикалі дуже густа". pyqtgraph's linear axis offers THREE tick
    levels, and on a phase plot ranged ±180° the third is a line every 5° — a hatch pattern with
    the curves inside it. Two, which is what the frequency axis and REW's own both draw."""
    view = _impulse_sum_view()

    assert view._plot.getAxis("left").style["maxTickLevel"] == 1

    view.set_sum_shown(True)

    assert view._strip is not None
    assert view._strip.getAxis("left").style["maxTickLevel"] == 1, "the strip too — it is shorter"


def test_the_picker_offers_the_capture_rounds_and_narrows_to_what_one_took(tmp_path,
                                                                           monkeypatch):
    """User, 2026-08-21: "я не бачу два сета які є внизу, хоч і вибрано АЧХ, і вони є в обох
    сетах".

    A series is the DSP config the sweeps were taken under and comes out of REW's own titles; a
    round is one pass at that config and lives in the journal (SCR-034). This window only ever
    read the first, so the sets listed in the capture panel right below it could not be picked at
    all. Choosing one narrows the rows to what that pass took.
    """
    from autosound_tcc.ui.tcc import curve_dialog as cd

    rounds = [
        {"id": "cap_002", "expected": ["w-L_02 (sw)"], "taken": {"w-L_02 (sw)": {}}},
        {"id": "cap_001", "expected": ["w-L_02 (sw)", "w-R_02 (sw)"],
         "taken": {"w-R_02 (sw)": {}}},
        {"id": "cap_000", "expected": ["gone_09 (sw)"], "taken": {}},
    ]
    monkeypatch.setattr(cd.process_view, "capture_rounds", lambda *a, **k: rounds)

    dialog = _group_dialog()
    _fetch(dialog)
    combo = dialog._version_combo
    offered = [combo.itemData(i) for i in range(combo.count())]

    assert "round:cap_001" in offered and "round:cap_002" in offered, "both sets are offered"
    assert any(not str(d).startswith("round:") for d in offered), "and the series stay"

    combo.setCurrentIndex(offered.index("round:cap_002"))
    assert dialog._chosen_round() == "cap_002"
    assert dialog._selectable() == ["w-L_02 (sw)"], "only what that pass took"

    combo.setCurrentIndex(offered.index("round:cap_001"))
    assert sorted(dialog._selectable()) == ["w-L_02 (sw)", "w-R_02 (sw)"]

    # A round names a pass, not a config, and a group still resolves at a version -- taken from
    # the titles the round itself holds.
    assert dialog._chosen_version() == "02"

    # A round whose measurements REW no longer holds is a real state and has to say so, rather
    # than showing an empty list of things to pick.
    combo.setCurrentIndex(offered.index("round:cap_000"))
    assert dialog._selectable() == []
    assert dialog._group_note, "and the window says where it looked"
