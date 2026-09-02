"""The import table: what it shows, what survives a redraw, and what Apply writes down.

The decisions are `core/capture_import`'s and are tested there. What is tested here is the part a
person touches — the tick that has to survive `+10`, the filter that has to run before the window,
and the line that stops the dialog claiming to show everything REW holds.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from autosound_tcc.core import capture_import  # noqa: E402
from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.capture_import_dialog import CaptureImportDialog  # noqa: E402

_KEEP: list = []


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _rew(count: int, first: int = 1) -> dict:
    """`count` sweeps, ten seconds apart, in REW's own answer shape."""
    return {
        str(n): {"title": f"m_{n} (sw)", "uuid": f"u{n}",
                 "date": f"2026-Aug-25 20:{n % 60:02d}:{(n * 10) % 60:02d}"}
        for n in range(first, first + count)
    }


def _dialog(measurements, tmp_path, **kwargs) -> CaptureImportDialog:
    _app()
    dialog = CaptureImportDialog(measurements, project_dir=tmp_path, **kwargs)
    _KEEP.append(dialog)
    return dialog


def _titles(dialog) -> list[str]:
    return [dialog._table.item(row, 1).text() for row in range(dialog._table.rowCount())]


def cid_uuid():
    from autosound_tcc.ui.tcc import capture_import_dialog as cid

    return cid._UUID


def _tick_state(dialog, row: int) -> bool:
    return dialog._table.item(row, 0).checkState() == Qt.CheckState.Checked


def test_it_opens_on_what_the_round_is_waiting_for_and_ticks_that_much(tmp_path):
    dialog = _dialog(_rew(30), tmp_path, waiting=6)

    assert len(_titles(dialog)) == 10, "a window of six would hide what was taken just before six"
    ticked = dialog.ticked_rows()
    assert len(ticked) == 6, "and only the batch the round is waiting for is pre-ticked"
    assert [row.uuid for row in ticked] == [f"u{n}" for n in range(25, 31)], "the newest six"
    assert not any(_tick_state(dialog, index) for index in range(4)), "the older four are context"


def test_the_filter_runs_before_the_window(tmp_path):
    """Windowing first and filtering after gives a window of ten that shows three: the tuner asked
    for as many as they can act on, not ten of which seven are already in."""
    rows = capture_import.candidates(_rew(30), tmp_path)
    capture_import.record_imported(rows[-8:], project_dir=tmp_path)

    dialog = _dialog(_rew(30), tmp_path, waiting=10)

    assert len(_titles(dialog)) == 10
    assert not any(row.imported for row in dialog.visible_rows())


def test_already_taken_rows_come_back_when_asked_for_and_come_back_unticked(tmp_path):
    rows = capture_import.candidates(_rew(12), tmp_path)
    capture_import.record_imported(rows[:4], project_dir=tmp_path)
    dialog = _dialog(_rew(12), tmp_path, waiting=8)

    assert len(_titles(dialog)) == 8

    dialog._only_new.setChecked(False)

    shown = dialog.visible_rows()
    assert len(shown) == 10, "the window is the window; the box decides what may fill it"
    already = [index for index, row in enumerate(shown) if row.imported]
    assert already and not any(_tick_state(dialog, index) for index in already)


def test_plus_ten_reaches_back_without_losing_a_tick(tmp_path):
    """`+10` and the filter both redraw the table underneath the tuner. A tick that survives only
    until the next redraw is a tick nobody can trust."""
    dialog = _dialog(_rew(40), tmp_path, waiting=10)
    assert len(dialog.ticked_rows()) == 10
    dialog._table.item(9, 0).setCheckState(Qt.CheckState.Unchecked)
    kept = {row.uuid for row in dialog.ticked_rows()}
    assert len(kept) == 9

    dialog._more_btn.click()

    assert len(_titles(dialog)) == 20
    assert {row.uuid for row in dialog.ticked_rows()} == kept
    assert not any(_tick_state(dialog, index) for index in range(10)), "the older ten are context"


def test_plus_ten_is_an_action_not_a_switch(tmp_path):
    """Each press reaches another portion further back, and the button goes out when there is
    nothing further to reach (user asked outright, 2026-09-02)."""
    dialog = _dialog(_rew(28), tmp_path, waiting=6)
    assert len(_titles(dialog)) == 10

    dialog._more_btn.click()
    assert len(_titles(dialog)) == 20
    dialog._more_btn.click()

    assert len(_titles(dialog)) == 28, "the third portion runs out of list, not out of presses"
    assert not dialog._more_btn.isEnabled()


def test_apply_hands_over_exactly_what_was_ticked(tmp_path):
    dialog = _dialog(_rew(12), tmp_path, waiting=3, round_id="cap_007")
    assert len(dialog.ticked_rows()) == 3
    dialog._table.item(9, 0).setCheckState(Qt.CheckState.Unchecked)  # the newest of the three

    dialog._on_apply()

    assert [row.uuid for row in dialog.taken()] == ["u10", "u11"]
    assert dialog.result() == int(dialog.DialogCode.Accepted)


# ---- names -------------------------------------------------------------------------------


_SETS = {"sw": [("w-L_02", "w-L_02 (sw)"), ("w-R_02", "w-R_02 (sw)"), ("m-L_02", "m-L_02 (sw)")]}


def _give_names(dialog, monkeypatch, order=None, method="sw", accept=True):
    """Drive `ChannelOrderDialog` without opening it — it has its own tests."""
    from autosound_tcc.ui.tcc import capture_import_dialog as cid

    class _Picker:
        def __init__(self, *_a, **_k):
            pass

        def exec(self):
            return (QDialog.DialogCode.Accepted if accept else QDialog.DialogCode.Rejected)

        def get_method(self):
            return method

        def get_order(self):
            return order if order is not None else [code for code, _label in _SETS["sw"]]

    monkeypatch.setattr(cid, "ChannelOrderDialog", _Picker)
    dialog._on_give_names()


def test_names_are_filled_downwards_from_the_row_that_is_selected(tmp_path, monkeypatch):
    """The user's own flow: "я стаю в перший замір, нажимаю кнопку «Дати назву»"."""
    dialog = _dialog(_rew(5), tmp_path, waiting=5, name_sets=_SETS)
    dialog._table.setCurrentCell(2, 0)

    _give_names(dialog, monkeypatch)

    assert dialog.renames() == [("u3", "w-L_02 (sw)"), ("u4", "w-R_02 (sw)"),
                                ("u5", "m-L_02 (sw)")]
    assert dialog._table.item(2, 3).text() == "w-L_02 (sw)"


def test_a_count_that_does_not_line_up_is_said_before_anything_is_sent(tmp_path, monkeypatch):
    """Three names onto four measurements: the fourth is usually a re-take, and filling blindly
    would put every name after it on the wrong graph."""
    dialog = _dialog(_rew(4), tmp_path, waiting=4, name_sets=_SETS)
    dialog._table.setCurrentCell(0, 0)

    _give_names(dialog, monkeypatch)

    assert len(dialog.renames()) == 3, "what lines up is still filled in"
    assert i18n.t("capImportUneven").format(rows=1, names=0) in dialog._note.text()


def test_typing_a_name_takes_the_row_with_it(tmp_path):
    """A rename nobody takes in is a rename for nothing."""
    dialog = _dialog(_rew(12), tmp_path, waiting=1)
    row = 0
    uuid = dialog._table.item(row, 0).data(cid_uuid())
    assert uuid not in dialog._ticked

    dialog._table.item(row, 3).setText("m-L_02 (sw)")

    assert uuid in dialog._ticked
    assert (uuid, "m-L_02 (sw)") in dialog.renames()


def test_a_name_that_is_already_the_title_is_not_a_rename(tmp_path):
    dialog = _dialog(_rew(3), tmp_path, waiting=3)

    dialog._table.item(0, 3).setText("m_1 (sw)")

    assert dialog.renames() == [], "REW is not asked to rename a measurement to what it is called"


def test_two_rows_asking_for_one_name_stop_apply(tmp_path):
    """Caught where the names were typed, before anything is sent: the method's identity model
    rests on a title being one measurement's name."""
    dialog = _dialog(_rew(3), tmp_path, waiting=3)
    dialog._table.item(0, 3).setText("w-L_02 (sw)")
    dialog._table.item(1, 3).setText("w-L_02 (sw)")

    dialog._on_apply()

    assert dialog.result() != int(dialog.DialogCode.Accepted), "nothing left the dialog"
    assert "w-L_02 (sw)" in dialog._note.text()
    assert i18n.t("capImportClash").split("{")[0].strip() in dialog._note.text()


def test_a_retake_out_of_time_order_is_marked_when_the_list_is_rews_own(tmp_path):
    """In capture order there is nothing to mark. When a date could not be read the list falls back
    to REW's order, and there a re-take sits among its neighbours with an earlier time."""
    answer = _rew(3)
    answer["1"]["date"] = "2026-Aug-25 20:10:00"
    answer["2"]["date"] = "2026-Aug-25 20:09:00"
    answer["3"]["date"] = "2026-жов-01 10:00:00"

    dialog = _dialog(answer, tmp_path, waiting=3)

    assert "↻" in dialog._table.item(1, 2).text()
    assert "↻" not in dialog._table.item(0, 2).text()


def test_the_dialog_does_not_claim_to_show_everything_rew_holds(tmp_path):
    """Measured 2026-09-02: a filter switched on in REW's own window changes what the API answers —
    17, then 85, then 102 from one file — and a filtered answer is renumbered with no gaps, so
    nothing in it reveals what is missing. The dialog cannot see the filter; it can refuse to claim
    more than it knows."""
    dialog = _dialog(_rew(4), tmp_path, waiting=4)

    assert i18n.t("capImportShowing") in dialog._note.text()


def test_imported_measurements_rew_is_not_showing_are_counted_on_screen(tmp_path):
    capture_import.record_imported(
        capture_import.candidates(_rew(6), tmp_path), project_dir=tmp_path)

    dialog = _dialog(_rew(2), tmp_path, waiting=2)

    assert i18n.t("capImportMissing").format(n=4) in dialog._note.text()


def test_an_unreadable_date_is_said_out_loud_rather_than_sorted_around(tmp_path):
    answer = _rew(3)
    answer["2"]["date"] = "2026-жов-01 10:00:00"

    dialog = _dialog(answer, tmp_path, waiting=3)

    assert i18n.t("capImportRewOrder") in dialog._note.text()
    assert _titles(dialog) == ["m_1 (sw)", "m_2 (sw)", "m_3 (sw)"], "REW's own order, untouched"


def test_a_measurement_with_no_uuid_is_listed_and_cannot_be_ticked(tmp_path):
    """Nothing this dialog promises holds for it: after a rename there is no way to know it again,
    so it must not be written into a store keyed by uuid."""
    answer = _rew(2)
    answer["1"]["uuid"] = ""

    dialog = _dialog(answer, tmp_path, waiting=2)

    assert len(_titles(dialog)) == 2
    assert not (dialog._table.item(0, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable)
    assert {row.uuid for row in dialog.ticked_rows()} == {"u2"}


def test_a_round_that_expects_nothing_still_opens_and_says_so(tmp_path):
    dialog = _dialog(_rew(3), tmp_path, waiting=0, has_task=False)

    assert len(_titles(dialog)) == 3
    heads = [w.text() for w in dialog.findChildren(type(dialog._note))]
    assert any(i18n.t("capImportNoTask") in text for text in heads)


def test_rew_holding_nothing_shows_a_line_rather_than_an_empty_table(tmp_path):
    dialog = _dialog({}, tmp_path, waiting=4)

    assert _titles(dialog) == []
    assert i18n.t("capImportEmpty") in dialog._note.text()
