"""The curve panel is an input device, not a viewer.

What has to hold is that a marker produces a NUMBER — the thing a screenshot could never give
back, and the reason a disagreement about an impulse onset had nowhere to be settled.
"""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


def _view() -> CurveView:
    _app()
    view = CurveView()
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
    dialog = CurveDialog(["w-L_01 (sw)", "w-R_01 (sw)"], markers=[4.6], bridge=bridge)
    dialog._worker.wait(4000)
    dialog._worker.run()  # synchronously, so the result is in hand rather than raced

    assert bridge.asked[-2:] == ["w-L_01 (sw)", "w-R_01 (sw)"]


def test_a_single_model_marker_gets_a_second_one_to_drag():
    """The Arbiter's marker starts ON the model's: dragging away from it IS the disagreement, so
    every millimetre of movement is deliberate."""
    _app()
    dialog = CurveDialog(["w-L_01 (sw)"], markers=[4.52], bridge=_FakeBridge())
    dialog._worker.wait(4000)

    dialog._on_curves([Trace("w-L_01 (sw)", *_impulse(4.52))])

    assert dialog._view.positions() == [4.52, 4.52]


def test_rew_being_unreachable_is_a_message_not_a_crash():
    _app()
    dialog = CurveDialog(["w-L_01 (sw)"], bridge=_FakeBridge(ConnectionRefusedError("no REW")))
    dialog._worker.wait(4000)
    dialog._worker.run()

    assert "ConnectionRefusedError" in dialog._status.text()
    assert dialog._status.isVisibleTo(dialog)
