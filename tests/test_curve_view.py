"""The curve panel is an input device, not a viewer.

What has to hold is that a marker produces a NUMBER — the thing a screenshot could never give
back, and the reason a disagreement about an impulse onset had nowhere to be settled.
"""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.curve_dialog import CurveDialog  # noqa: E402
from autosound_tcc.ui.tcc.curve_view import CurveView, Trace  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _impulse(peak_ms: float, n: int = 200, span: float = 8.0):
    xs = [i * span / n for i in range(n)]
    ys = [math.exp(-abs(x - peak_ms) * 3.0) * math.cos((x - peak_ms) * 25.0) for x in xs]
    return xs, ys


#: Every view this module builds, kept alive for the run. pyqtgraph's `PlotItem` constructs
#: parentless QMenus and QWidgetActions on every instance, and letting enough of them be collected
#: segfaults the process from inside a LATER `PlotItem.__init__` — reproduced here, and the reason
#: the app now reuses one curve window instead of building a second. Holding them is not tidiness;
#: it is the only thing that makes this file's ~20 widgets safe to create.
_KEEP: list = []


def _dialog(*args, **kwargs) -> CurveDialog:
    """Build a dialog and keep it alive for the run — see `_KEEP`."""
    made = CurveDialog(*args, **kwargs)
    _KEEP.append(made)
    return made


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
    assert view._readout.text() == i18n.t("curveNoMarkers")


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

    def impulse_response(self, mid):
        xs, ys = _impulse(4.6)
        return [x / 1000.0 for x in xs], ys  # REW reports seconds; the panel plots ms


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


def test_without_a_model_reading_the_markers_start_on_each_traces_own_peak():
    """The Arbiter can open this themselves, with nothing to argue against yet. Two markers parked
    at zero say nothing; markers on the peaks are a crude reading of the arrivals, which makes the
    delta meaningful before anything is touched — and an obvious guess invites correction."""
    _app()
    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)

    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])

    positions = dialog._view.positions()
    assert abs(positions[0] - 4.52) < 0.05 and abs(positions[1] - 4.78) < 0.05
    assert dialog._view._marker_names == ["w-L_01 (sw)", "w-R_01 (sw)"]


def test_the_pickers_let_the_argument_move_to_another_pair():
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)", "m-L_01 (sw)"]
    dialog = _dialog(every[:2], bridge=_FakeBridge(), available=every)
    dialog._worker.wait(4000)

    dialog._pickers[1].setCurrentIndex(dialog._pickers[1].findData("m-L_01 (sw)"))
    dialog._worker.wait(4000)

    assert dialog._chosen() == ["w-L_01 (sw)", "m-L_01 (sw)"]


def test_one_curve_is_a_legitimate_thing_to_argue_about():
    _app()
    every = ["w-L_01 (sw)", "w-R_01 (sw)"]
    dialog = _dialog(every, bridge=_FakeBridge(), available=every)
    dialog._worker.wait(4000)

    dialog._pickers[1].setCurrentIndex(0)  # the "— none —" row
    dialog._worker.wait(4000)

    assert dialog._chosen() == ["w-L_01 (sw)"]


# ---- what a measurement can actually show (user, 2026-08-11) ----------------------------------


def test_an_rta_capture_is_plotted_as_frequency_response_not_asked_for_an_impulse():
    """An MMM/RTA capture has no impulse response — REW answers HTTP 400 — so asking for one is a
    broken window. The method suffix already says which kind a measurement is."""
    from autosound_tcc.ui.tcc.curve_dialog import kind_for

    assert kind_for(["w-L_01 (rta)", "w-R_01 (rta)"]) == "fr"
    assert kind_for(["w-L_01 (sw)", "w-R_01 (sw)"]) == "impulse"
    # A mixed pair keeps the impulse: the sweep can provide one, and the caller asked.
    assert kind_for(["w-L_01 (sw)", "w-R_01 (rta)"], "impulse") == "impulse"
    # ...but an explicit `impulse` over an all-RTA selection is a request that cannot be honoured.
    assert kind_for(["w-L_01 (rta)"], "impulse") == "fr"


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
    _app()

    class _HalfBroken(_FakeBridge):
        def impulse_response(self, mid):
            if "rta" in mid:
                raise RuntimeError("HTTP Error 400: Bad Request")
            return super().impulse_response(mid)

    dialog = _dialog(["w-L_01 (sw)", "w-R_01 (rta)"], bridge=_HalfBroken(), kind="impulse")
    dialog._worker.wait(4000)
    got = []
    dialog._worker.done.connect(got.append)
    dialog._worker.run()

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

    strings = axis.tickStrings([math.log10(v) for v in (20, 100, 1000, 2000, 20000)], 1, 1)

    assert strings == ["20", "100", "1k", "2k", "20k"]


def test_the_axis_thins_ticks_rather_than_overprinting_them():
    from autosound_tcc.ui.tcc.curve_view import LogHzAxis

    axis = LogHzAxis(orientation="bottom")
    lo, hi = math.log10(20), math.log10(20000)

    roomy = sum(len(group) for _, group in axis.tickValues(lo, hi, 1400))
    cramped = sum(len(group) for _, group in axis.tickValues(lo, hi, 200))

    assert cramped < roomy, "a tick with no room overprints the one that had room"


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
    """"головне щоб загалом не йшло менш нуля" — and only the caller knows what is in there."""
    view = _view()
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


def test_without_a_sample_rate_the_reading_is_milliseconds_alone():
    """MUSWAY's own box goes to thousandths on a step nobody here has confirmed. A samples figure
    invented from a guessed rate would be a number the Arbiter could act on and shouldn't."""
    view = _view()
    view.set_unit("ms")
    view.set_resolution(0.001, None)
    view.set_delay_target(1)

    view.set_delay(0.198)

    assert view.samples(0.198) is None
    assert "smp" not in view.reading()


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


def test_the_pickers_show_what_each_measurement_already_carries():
    """Where the Arbiter chooses the next pair is where they need to see that this channel has
    already been read once."""
    from autosound_tcc.core import delay_bank

    delay_bank.put("w-R_01 (sw)", 0.4)
    every = ["w-L_01 (sw)", "w-R_01 (sw)", "m-L_01 (sw)"]
    dialog = _dialog(every[:2], bridge=_FakeBridge(), available=every)
    dialog._worker.wait(4000)
    dialog._render_bank()

    combo = dialog._pickers[0]
    at = combo.findData("w-R_01 (sw)")
    assert "+0.400 ms" in combo.itemText(at)
    assert combo.itemText(combo.findData("m-L_01 (sw)")) == "m-L_01 (sw)", "untouched stays plain"


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
    assert "w-L_01 (sw): +0.198 ms (+19 smp)" in sent[0]
    assert "m-L_01 (sw): +1.250 ms (+120 smp)" in sent[0]
    assert i18n.t("curveBankNotForWriting") in sent[0], "it says it is not to be written"


def test_with_nothing_banked_there_is_nothing_to_analyse():
    dialog = _dialog(["w-L_01 (sw)"], bridge=_FakeBridge())
    dialog._worker.wait(4000)
    dialog._render_bank()

    assert not dialog._bank_ask_btn.isEnabled()
    assert i18n.t("curveBankEmpty") in dialog._bank_label.text()


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


def test_a_set_that_cannot_be_applied_says_so_before_the_model_has_to_notice():
    from autosound_tcc.core import delay_bank

    text = delay_bank.as_sentence(
        {"w-L_01 (sw)": -0.5, "m-L_01 (sw)": 0.25},
        sample_rate_hz=96000,
        lang_t=i18n.t,
        current=lambda title: {"w-L_01 (sw)": 0.1, "m-L_01 (sw)": 1.0}.get(title),
    )

    assert "w-L_01 (sw): -0.500 ms (-48 smp) | channel 0.100 → -0.400 ms" in text
    assert i18n.t("curveDelayBelowZero") in text
    assert i18n.t("curveBankImpossible") in text
    assert "m-L_01 (sw): +0.250 ms (+24 smp) | channel 1.000 → 1.250 ms" in text


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
    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52)),
                       Trace("w-R_01 (sw)", *_impulse(4.78))])

    dialog._view.set_delay(-0.2)
    assert dialog._view.total_delay_ms() == pytest.approx(0.8)

    ledger["w-L"] = 0.1
    dialog._sync_channel_delay()

    assert dialog._view.total_delay_ms() == pytest.approx(-0.1)
    assert i18n.t("curveDelayBelowZero") in dialog._view.reading()


def test_an_impossible_total_is_coloured_not_just_worded():
    """A warning inside a sentence made of numbers is read last."""
    view = _view()
    view.set_unit("ms")
    view.set_markers([4.52], tokens=["accent"])
    view.set_channel_delay(0.1)

    view.set_delay(-0.5)

    assert "color:" in view._readout.text()

    view.set_delay(0.5)

    assert "color:" not in view._readout.text()


def test_the_set_states_what_the_numbers_are_measured_from():
    """User, 2026-08-12: "привʼязка повинна бути до 0 осі Х, а затримка відносно позиції як було
    знято при змірі". A set of deltas with no origin cannot be checked, and being checkable is the
    only reason it is sent."""
    from autosound_tcc.core import delay_bank

    text = delay_bank.as_sentence(
        {"tw-L_01 (sw)": 1.2, "m-R_01 (sw)": 1.18},
        sample_rate_hz=96000,
        lang_t=i18n.t,
        at={"tw-L_01 (sw)": 2.95, "m-R_01 (sw)": 4.12},
    )

    assert i18n.t("curveBankConvention") in text
    assert "arrival 2.950 → 4.150 ms" in text
    assert "arrival 4.120 → 5.300 ms" in text
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
    assert "cap_001" in dialog._bank_label.text() or i18n.t("curveBankEmpty") in \
        dialog._bank_label.text()


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
    assert i18n.t("curveBankEmpty") in dialog._bank_label.text()

    series[0] = "cap_001"
    dialog.session_switched()

    assert "cap_001" in dialog._bank_label.text() and "+0.260" in dialog._bank_label.text()
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


def test_clearing_the_markers_puts_them_back_on_the_peaks():
    """"Clear" for a marker is undoing the dragging. Removing them would leave the panel with no
    reading and no way to get one back short of reloading the pair."""
    view = _view()
    view.set_unit("ms")
    view.set_markers([1.0, 7.0], tokens=["accent", "info"])

    view.reset_markers()

    assert view.positions() == pytest.approx([4.52, 4.78], abs=0.05)


def test_a_driver_left_at_zero_is_the_reference_not_an_omission():
    """User, 2026-08-12: "w-R немає, бо він був нулем. як би додавав сабвуфер — то саб був би
    нулем". The zero is the choice everything else is measured from."""
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

    assert "w-R_01 (sw)" in sent[0] and i18n.t("curveBankReference").partition("{")[0][:20] in sent[0]
    assert "sw_01 (sw)" in sent[0]
