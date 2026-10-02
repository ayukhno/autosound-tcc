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
    return [dialog._table.item(row, 2).text() for row in range(dialog._table.rowCount())]


def cid_uuid():
    from autosound_tcc.ui.tcc import capture_import_dialog as cid

    return cid._UUID


def _tick_state(dialog, row: int) -> bool:
    return dialog._table.item(row, 0).checkState() == Qt.CheckState.Checked


def test_it_ticks_what_answers_to_a_name_the_round_is_waiting_for(tmp_path):
    """Not the newest N. The measurements a round waits for are not always the last ones taken —
    on the user's own list they were not (2026-09-06), and a positional guess ticks the wrong ones
    while the right ones sit further up, out of the window."""
    dialog = _dialog(_rew(30), tmp_path, expected=["m_3 (sw)", "m_27 (sw)"])

    assert [row.uuid for row in dialog.ticked_rows()] == ["u3", "u27"]
    assert "m_3 (sw)" in _titles(dialog), "a ticked row outside the tail is still put on screen"
    assert i18n.t("capImportPicked").format(n=2) in dialog._note.text()


def test_the_window_is_still_wider_than_the_round_and_ticks_nothing_by_position(tmp_path):
    """The window is deliberately wider than the round (a window of six hides what was taken just
    before the six) — but width is context, not a tick."""
    dialog = _dialog(_rew(30), tmp_path, waiting=6)

    assert len(_titles(dialog)) == 10
    assert dialog.ticked_rows() == [], "with no names to match against, nothing is guessed at"


def test_two_measurements_under_one_name_tick_neither(tmp_path):
    """Which of two graphs with one name is the one that came out is the person's question. The
    dialog marks the pair, says so, and ticks neither (user, 2026-09-06)."""
    answer = _rew(3)
    answer["2"]["title"] = "m_3 (sw)"

    dialog = _dialog(answer, tmp_path, expected=["m_3 (sw)"])

    assert dialog.ticked_rows() == [], "neither of the two is chosen for the tuner"
    assert dialog._ambiguous == {"u2", "u3"}
    assert "⧉" in dialog._table.item(1, 2).text(), "and both are marked in the row"
    # Said once, by the warning (tcc#94): the ambiguous-tick line names only what the warning does
    # not — two spellings the grammar reads alike — and the mark's hover says why neither is ticked.
    assert i18n.t("capImportDupWarn").format(names="m_3 (sw)") in dialog._note.text()
    assert dialog._note.text().count("m_3 (sw)") == 1, dialog._note.text()


def test_a_title_rew_holds_twice_is_named_with_what_to_do_about_it(tmp_path):
    """tcc#94 (the Arbiter, 2026-10-02): two measurements under one title are warned about, and
    nothing more. Said whether or not the round waits for that name — the curve window and the
    method read every title, not only the round's. Distinct titles say nothing."""
    answer = _rew(3)
    answer["2"]["title"] = "m_3 (sw)"

    twice = _dialog(answer, tmp_path)
    once = _dialog(_rew(3), tmp_path)

    assert i18n.t("capImportDupWarn").format(names="m_3 (sw)") in twice._note.text()
    assert i18n.t("capImportDupWarn").split("{")[0] not in once._note.text()


def test_the_row_carries_rews_own_number(tmp_path):
    """For finding the row in REW's own window — navigation, never an identity (`capture_import`
    module docstring: the ordinal is the index of a view)."""
    dialog = _dialog(_rew(3), tmp_path, waiting=3)

    assert [dialog._table.item(row, 1).text() for row in range(3)] == ["1", "2", "3"]


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
    dialog = _dialog(_rew(40), tmp_path, expected=[f"m_{n} (sw)" for n in range(31, 41)])
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
    dialog = _dialog(_rew(12), tmp_path, round_id="cap_007",
                     expected=["m_10 (sw)", "m_11 (sw)", "m_12 (sw)"])
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
    assert dialog._table.item(2, 4).text() == "w-L_02 (sw)"


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

    dialog._table.item(row, 4).setText("m-L_02 (sw)")

    assert uuid in dialog._ticked
    assert (uuid, "m-L_02 (sw)") in dialog.renames()


def test_a_name_that_is_already_the_title_is_not_a_rename(tmp_path):
    dialog = _dialog(_rew(3), tmp_path, waiting=3)

    dialog._table.item(0, 4).setText("m_1 (sw)")

    assert dialog.renames() == [], "REW is not asked to rename a measurement to what it is called"


def test_two_rows_asking_for_one_name_stop_apply(tmp_path):
    """Caught where the names were typed, before anything is sent: the method's identity model
    rests on a title being one measurement's name."""
    dialog = _dialog(_rew(3), tmp_path, waiting=3)
    dialog._table.item(0, 4).setText("w-L_02 (sw)")
    dialog._table.item(1, 4).setText("w-L_02 (sw)")

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

    assert "↻" in dialog._table.item(1, 3).text()
    assert "↻" not in dialog._table.item(0, 3).text()


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

    dialog = _dialog(answer, tmp_path, expected=["m_1 (sw)", "m_2 (sw)"])

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


# ---- what was in the signal path, entered for the row -----------------------------------------

_LR24_80 = {"hp": {"f": 80.0, "type": "LR", "slope": 24}}


def test_the_row_s_filters_are_the_whole_statement(tmp_path):
    """What the row says was in its chain is recorded for its channel — entered with the Protection
    form's own fields now (F-056, the Arbiter 2026-09-16), not a bare frequency with LR24 implied."""
    dialog = _dialog(_rew(2), tmp_path, waiting=2)
    dialog._table.item(0, 4).setText("w-L_02 (sw)")

    dialog.set_legs(dialog.uuid_at(0), {"hp": {"f": 80.0, "type": "BW", "slope": 12}})

    assert dialog.protective() == {"w-L": {"hp": {"f": 80.0, "type": "BW", "slope": 12}}}


def test_the_cell_says_what_is_in_the_chain(tmp_path):
    dialog = _dialog(_rew(1), tmp_path, waiting=1)
    assert dialog._table.item(0, 5).text() == "—"

    dialog.set_legs(dialog.uuid_at(0), {"hp": {"f": 80.0, "type": "LR", "slope": 24},
                                        "lp": {"f": 3500.0, "type": "LR", "slope": 24}})

    hp, lp = i18n.t("capImportHp"), i18n.t("capImportLp")
    assert dialog._table.item(0, 5).text() == f"{hp} LR24 80 · {lp} LR24 3500"


def test_clicking_the_cell_opens_the_form_and_keeps_its_answer(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc import capture_import_dialog as cid

    class _Form:
        def __init__(self, legs=None, parent=None):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def legs(self):
            return _LR24_80

    monkeypatch.setattr(cid, "ProtectiveLegsDialog", _Form)
    dialog = _dialog(_rew(1), tmp_path, waiting=1)
    dialog._table.item(0, 4).setText("w-L_02 (sw)")

    dialog._on_cell_clicked(0, 5)

    assert dialog.protective() == {"w-L": _LR24_80}


def test_an_empty_row_says_nothing_at_all(tmp_path):
    """Empty means "read this curve as measured" — not a claim that the chain was empty. There is
    nearly always something in it, the DSP's own working crossovers, and they belong there."""
    dialog = _dialog(_rew(3), tmp_path, waiting=3)

    assert dialog.protective() == {}


def test_the_channel_comes_from_the_name_the_row_is_being_given(tmp_path):
    """"Імʼя або є, або буде в цій таблиці" — so the row knows its channel by the time it matters."""
    answer = _rew(1)
    answer["1"]["title"] = "tw-R_02 (sw)"  # already named in REW
    dialog = _dialog(answer, tmp_path, waiting=1)

    dialog.set_legs(dialog.uuid_at(0), {"hp": {"f": 2500.0, "type": "LR", "slope": 24}})

    assert list(dialog.protective()) == ["tw-R"]


def test_entering_a_filter_takes_the_row_with_it(tmp_path):
    dialog = _dialog(_rew(12), tmp_path, waiting=1)
    uuid = dialog.uuid_at(0)
    assert uuid not in dialog._ticked

    dialog.set_legs(uuid, _LR24_80)

    assert uuid in dialog._ticked


def test_one_channel_described_two_ways_is_a_question_not_a_merge(tmp_path):
    """The same channel captured with two methods is two rows and one signal path. Two rows that
    disagree are not silently merged — that is a question for the person."""
    dialog = _dialog(_rew(2), tmp_path, waiting=2)
    dialog._table.item(0, 4).setText("w-L_02 (sw)")
    dialog._table.item(1, 4).setText("w-L_02 (rta)")
    dialog.set_legs(dialog.uuid_at(0), _LR24_80)
    dialog.set_legs(dialog.uuid_at(1), {"hp": {"f": 100.0, "type": "LR", "slope": 24}})

    dialog._on_apply()

    assert dialog.result() != int(dialog.DialogCode.Accepted), "nothing left the dialog"
    assert "w-L" in dialog._note.text()


def test_the_same_chain_on_two_rows_of_one_channel_is_fine(tmp_path):
    dialog = _dialog(_rew(2), tmp_path, waiting=2)
    dialog._table.item(0, 4).setText("w-L_02 (sw)")
    dialog._table.item(1, 4).setText("w-L_02 (rta)")
    dialog.set_legs(dialog.uuid_at(0), _LR24_80)
    dialog.set_legs(dialog.uuid_at(1), _LR24_80)

    assert list(dialog.protective()) == ["w-L"]
    assert dialog.protective_conflicts == []


# ---- the new name, chosen from what the round still waits for -----------------------------------

def _name_editor(dialog, row: int):
    return dialog._table.indexWidget(dialog._table.model().index(row, 4))


def test_the_new_name_offers_what_the_round_still_waits_for(tmp_path):
    """F-056, the Arbiter 2026-09-16: the import window lacked a field chosen from the list of what
    still has to be captured."""
    dialog = _dialog(_rew(2), tmp_path, expected=["w-L_02 (sw)", "w-R_02 (sw)"])

    assert dialog.name_choices(dialog.uuid_at(0)) == ["w-L_02 (sw)", "w-R_02 (sw)"]
    editor = _name_editor(dialog, 0)
    assert [editor.itemText(i) for i in range(editor.count())] == ["w-L_02 (sw)", "w-R_02 (sw)"]


def test_a_name_chosen_in_one_row_leaves_the_other_rows_lists(tmp_path):
    dialog = _dialog(_rew(2), tmp_path, expected=["w-L_02 (sw)", "w-R_02 (sw)"])
    first, second = dialog.uuid_at(0), dialog.uuid_at(1)

    dialog._table.item(0, 4).setText("w-L_02 (sw)")

    assert dialog.name_choices(second) == ["w-R_02 (sw)"]
    assert dialog.name_choices(first) == ["w-L_02 (sw)", "w-R_02 (sw)"], "a row keeps its own"


def test_choosing_from_the_list_takes_the_row_and_renames_it(tmp_path):
    dialog = _dialog(_rew(1), tmp_path, expected=["w-L_02 (sw)"])
    uuid = dialog.uuid_at(0)
    editor = _name_editor(dialog, 0)

    editor.setCurrentIndex(0)
    editor.activated.emit(0)

    assert uuid in dialog._ticked
    assert (uuid, "w-L_02 (sw)") in dialog.renames()


def test_a_name_nobody_planned_can_still_be_typed(tmp_path):
    """An extra measurement names itself — what it is and what it is for (hub #153)."""
    dialog = _dialog(_rew(1), tmp_path, expected=["w-L_02 (sw)"])
    uuid = dialog.uuid_at(0)

    dialog._table.item(0, 4).setText("r-L_17 (sw) noXO")

    assert (uuid, "r-L_17 (sw) noXO") in dialog.renames()


def test_a_typed_name_outside_the_grammar_says_why_under_the_table(tmp_path):
    """hub #153 E: a name the analysis will never find by its title is said at the moment it is
    typed, in the method's own words — not refused: the person may know better."""
    from autosound_tcc.core import vendor_loader

    if not vendor_loader.is_available():
        import pytest

        pytest.skip("rew_tool submodule not checked out")
    dialog = _dialog(_rew(1), tmp_path, expected=["w-L_02 (sw)"])

    dialog._table.item(0, 4).setText("w-L (sw)")

    assert "w-L (sw)" in dialog._note.text() and "_N" in dialog._note.text()



def test_the_new_name_opens_filled_with_the_round_s_own_spelling(tmp_path):
    """Finding 28: the name is the point of the form, and it was the one column left empty."""
    dialog = _dialog(_rew(5), tmp_path, expected=["m_2 (sw)", "m_4 (sw)"])
    names = {dialog.uuid_at(r): dialog._table.item(r, 4).text() for r in range(dialog._table.rowCount())}
    assert names["u2"] == "m_2 (sw)" and names["u4"] == "m_4 (sw)"
    assert names["u1"] == "", "a row nothing matched is left for the person"
    assert dialog.renames() == [], "the same spelling is not a rename"


def test_the_columns_can_be_dragged_wider(tmp_path):
    from PySide6.QtWidgets import QHeaderView

    dialog = _dialog(_rew(3), tmp_path)
    header = dialog._table.horizontalHeader()
    for column in (2, 3, 4):
        assert header.sectionResizeMode(column) == QHeaderView.ResizeMode.Interactive


def test_select_all_and_clear_at_the_foot_act_on_what_is_shown(tmp_path):
    dialog = _dialog(_rew(8), tmp_path)
    dialog._select_all_btn.click()
    shown = {dialog.uuid_at(r) for r in range(dialog._table.rowCount())}
    assert {row.uuid for row in dialog.ticked_rows()} == shown
    assert all(_tick_state(dialog, r) for r in range(dialog._table.rowCount()))
    dialog._clear_btn.click()
    assert dialog.ticked_rows() == []


# ---- the capture check, while the microphone is still in place (tcc#21) -------------------------

_COL_CHECK = 6

_USABLE = {"exists": True, "applicable": True, "valid": True, "issues": [], "stats": {}}


def _unusable(*issues) -> dict:
    """The method's verdict for a sweep that is there and cannot be used (`verify.verdict`)."""
    return {"exists": True, "applicable": True, "valid": False, "issues": list(issues),
            "stats": {}}


def _checker(verdicts: dict, gate=None, fail: str = ""):
    """A stand-in for the check the panel hands over: which rows it was asked about, and the
    method's answers by uuid. The method itself is faked in `test_capture_import.py`; REW nowhere."""
    asked: list = []

    def check(rows):
        asked.extend(row.uuid for row in rows)
        if gate is not None:
            gate.wait(10)
        if fail:
            raise RuntimeError(fail)
        return {row.uuid: verdicts[row.uuid] for row in rows if row.uuid in verdicts}

    return check, asked


def _settle(dialog) -> None:
    """Let the check's worker answer and the window take the answer in."""
    for _ in range(100):
        _app().processEvents()
        worker = dialog._check_worker
        if worker is not None:
            worker.wait(5000)
        _app().processEvents()
        if not dialog.checking():
            return
    raise AssertionError("the check never settled")


def _row_of(dialog, uuid: str) -> int:
    return next(r for r in range(dialog._table.rowCount()) if dialog.uuid_at(r) == uuid)


def _answer_buttons(dialog, uuid: str) -> dict:
    from PySide6.QtWidgets import QPushButton

    box = dialog._table.cellWidget(_row_of(dialog, uuid), _COL_CHECK)
    assert box is not None, "an unusable sweep has its answer in the row"
    return {button.text(): button for button in box.findChildren(QPushButton)}


def test_only_the_ticked_sweeps_are_checked(tmp_path):
    """Selected only (the Arbiter, 2026-10-02): REW held 90 measurements in the session this was
    measured against, and a verdict per row is an FR and an impulse pulled for rows nobody chose."""
    check, asked = _checker({"u3": _USABLE, "u27": _USABLE})
    dialog = _dialog(_rew(30), tmp_path, expected=["m_3 (sw)", "m_27 (sw)"], check=check)

    _settle(dialog)

    assert sorted(asked) == ["u27", "u3"]
    assert dialog._table.item(_row_of(dialog, "u3"), _COL_CHECK).text() == "✓"


def test_an_rta_row_is_not_put_to_the_check(tmp_path):
    """An RTA has no verdict to give, and marking it would be a verdict about nothing (TCC-008)."""
    from autosound_tcc.core import vendor_loader

    if not vendor_loader.is_available():
        import pytest

        pytest.skip("rew_tool submodule not checked out")
    answer = _rew(3)
    answer["2"]["notes"] = "65536-point 1/48 octave RTA using Hann window"
    check, asked = _checker({})
    dialog = _dialog(answer, tmp_path, expected=["m_2 (sw)", "m_3 (sw)"], check=check)

    _settle(dialog)

    assert asked == ["u3"]


def test_an_unusable_sweep_is_marked_with_the_method_s_reason_on_hover(tmp_path):
    from PySide6.QtWidgets import QLabel

    check, _asked = _checker({"u2": _USABLE, "u3": _unusable("in-band mean -96.1 dB — silence, "
                                                             "not a sweep")})
    dialog = _dialog(_rew(3), tmp_path, expected=["m_2 (sw)", "m_3 (sw)"], check=check)

    _settle(dialog)

    box = dialog._table.cellWidget(_row_of(dialog, "u3"), _COL_CHECK)
    assert box is not None
    assert "in-band mean -96.1 dB" in box.hover_tip.text()
    marks = [label for label in box.findChildren(QLabel) if "tl-bad" in str(label.property("class"))]
    assert marks, "the card's own red dot for «taken, unusable»"
    assert dialog._table.cellWidget(_row_of(dialog, "u2"), _COL_CHECK) is None


def test_an_unusable_sweep_is_left_for_a_retake_unless_taken_as_it_is(tmp_path):
    """The Arbiter, 2026-10-02: TCC recommends a re-take — the capture is not taken — or the tuner
    takes it as it is, and it is taken like any other. Apply is never refused for it."""
    check, _asked = _checker({"u2": _USABLE, "u3": _unusable("flat to 0.4 dB across the band")})
    dialog = _dialog(_rew(3), tmp_path, expected=["m_2 (sw)", "m_3 (sw)"], check=check)
    _settle(dialog)
    retake, as_is = i18n.t("capCheckRetake"), i18n.t("capCheckAsIs")

    assert [row.uuid for row in dialog.taken()] == ["u2"], "the recommendation: not taken"
    assert _answer_buttons(dialog, "u3")[retake].isChecked()
    assert i18n.t("capCheckRetakeList").format(names="m_3 (sw)") in dialog._note.text()

    _answer_buttons(dialog, "u3")[as_is].click()
    _app().processEvents()

    assert [(row.uuid, row.as_is) for row in dialog.taken()] == [("u2", False), ("u3", True)]
    assert _answer_buttons(dialog, "u3")[as_is].isChecked()
    assert "m_3 (sw)" not in dialog._note.text()

    _answer_buttons(dialog, "u3")[retake].click()
    _app().processEvents()

    assert [row.uuid for row in dialog.taken()] == ["u2"]


def test_a_tick_on_a_red_row_is_taking_it_as_it_is(tmp_path):
    """The tick and the answer are one decision: a tick by hand on a row the check marked is the
    tuner taking it knowingly, and Select all does not answer red rows for them."""
    check, _asked = _checker({"u3": _unusable("no clear arrival")})
    dialog = _dialog(_rew(3), tmp_path, expected=["m_3 (sw)"], check=check)
    _settle(dialog)

    dialog._select_all_btn.click()
    _settle(dialog)
    assert "u3" not in {row.uuid for row in dialog.taken()}

    dialog._table.item(_row_of(dialog, "u3"), 0).setCheckState(Qt.CheckState.Checked)
    _app().processEvents()

    assert ("u3", True) in [(row.uuid, row.as_is) for row in dialog.taken()]
    assert _answer_buttons(dialog, "u3")[i18n.t("capCheckAsIs")].isChecked()


def test_a_capture_taken_as_it_is_is_not_asked_about_again_and_its_retake_is(tmp_path):
    """Remembered by the capture's uuid (SCR-040): not asked again — and a re-take under the same
    title is another capture, checked afresh."""
    from dataclasses import replace

    first = capture_import.candidates(_rew(4), tmp_path)
    capture_import.record_imported([replace(first[3], as_is=True)], project_dir=tmp_path)
    answer = _rew(4)
    answer["5"] = {"title": "m_4 (sw)", "uuid": "u5", "date": "2026-Aug-25 20:05:50"}
    check, asked = _checker({"u5": _USABLE})
    dialog = _dialog(answer, tmp_path, check=check)
    dialog._only_new.setChecked(False)

    for uuid in ("u4", "u5"):
        dialog._table.item(_row_of(dialog, uuid), 0).setCheckState(Qt.CheckState.Checked)
    _settle(dialog)

    assert asked == ["u5"]
    assert dialog._table.item(_row_of(dialog, "u4"), _COL_CHECK).text() == i18n.t(
        "capCheckAsIsDone")
    assert [(row.uuid, row.as_is) for row in dialog.taken()] == [("u4", True), ("u5", False)]


def test_apply_waits_for_the_check_and_goes_when_all_is_well(tmp_path):
    """Opened, Apply — the common way through — must not walk past the check that is the point."""
    import threading

    gate = threading.Event()
    check, _asked = _checker({"u3": _USABLE}, gate=gate)
    dialog = _dialog(_rew(3), tmp_path, expected=["m_3 (sw)"], check=check)
    _app().processEvents()

    dialog._on_apply()
    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert i18n.t("capCheckWaiting") in dialog._note.text()

    gate.set()
    _settle(dialog)

    assert dialog.result() == int(QDialog.DialogCode.Accepted)


def test_apply_that_waited_stays_open_for_an_unusable_sweep(tmp_path):
    import threading

    gate = threading.Event()
    check, _asked = _checker({"u2": _USABLE, "u3": _unusable("no clear arrival")}, gate=gate)
    dialog = _dialog(_rew(3), tmp_path, expected=["m_2 (sw)", "m_3 (sw)"], check=check)
    _app().processEvents()

    dialog._on_apply()
    gate.set()
    _settle(dialog)

    assert dialog.result() != int(QDialog.DialogCode.Accepted), "the tuner sees it once"
    assert i18n.t("capCheckRetakeList").format(names="m_3 (sw)") in dialog._note.text()

    dialog._on_apply()

    assert dialog.result() == int(QDialog.DialogCode.Accepted), "and is never held"
    assert [row.uuid for row in dialog.taken()] == ["u2"]


def test_apply_pressed_again_does_not_wait(tmp_path):
    import threading

    gate = threading.Event()
    check, _asked = _checker({"u3": _USABLE}, gate=gate)
    dialog = _dialog(_rew(3), tmp_path, expected=["m_3 (sw)"], check=check)
    _app().processEvents()

    dialog._on_apply()
    dialog._on_apply()

    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    gate.set()
    dialog._check_worker.wait(5000)


def test_a_check_that_cannot_run_is_said_and_holds_nothing(tmp_path):
    check, _asked = _checker({}, fail="URLError: <urlopen error [Errno 61] Connection refused>")
    dialog = _dialog(_rew(3), tmp_path, expected=["m_3 (sw)"], check=check)
    _settle(dialog)

    assert i18n.t("capCheckFailed").format(
        error="RuntimeError: URLError: <urlopen error [Errno 61] Connection refused>") \
        in dialog._note.text()

    dialog._on_apply()

    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    assert [row.uuid for row in dialog.taken()] == ["u3"]


def test_a_sweep_left_for_a_retake_stays_on_screen(tmp_path):
    """Ticked by name far up the list, it was on screen only because it was ticked; the check
    unticks it, and the next redraw must not take it — and its «Take it as it is» — out of view."""
    check, _asked = _checker({"u3": _unusable("no clear arrival")})
    dialog = _dialog(_rew(30), tmp_path, expected=["m_3 (sw)"], check=check)
    _settle(dialog)

    dialog._only_new.setChecked(False)
    dialog._only_new.setChecked(True)

    assert "m_3 (sw)" in _titles(dialog)


def test_the_pair_of_answers_is_drawn_whole_in_its_cell(tmp_path):
    """Themed, «Взяти як є» came out cut: the column was sized before the sheet styled the buttons,
    and the cell's widget was put inside the item's padding. Measured against the widget's own
    size hint, so the fonts a machine has do not decide it. The sheet is the dialog's own here —
    the application's is every other test's."""
    from autosound_tcc.ui.tcc import theme

    check, _asked = _checker({"u3": _unusable("no clear arrival")})
    dialog = _dialog(_rew(3), tmp_path, expected=["m_3 (sw)"], check=check)
    dialog.setStyleSheet(theme.build_qss(theme.get_theme("dark")))
    dialog.show()
    _settle(dialog)
    _app().processEvents()

    box = dialog._table.cellWidget(_row_of(dialog, "u3"), _COL_CHECK)
    assert box.width() >= box.sizeHint().width(), (box.width(), box.sizeHint().width())
    dialog.hide()
