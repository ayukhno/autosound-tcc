"""What the import dialog decides — tested without a window, because none of it needs one.

The numbers and shapes here are not invented: they are the four measurements taken against the
user's live REW on 2026-09-02 (`docs/CAPTURE-IMPORT-PLAN.md`), including the two that surprised us
— a UI filter that reaches the API, and an ordinal that is a position in a view rather than a
property of a measurement.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from autosound_tcc.core import capture_import as ci
from autosound_tcc.core import vendor_loader


def _rew(*rows) -> dict:
    """REW's own answer shape: `{ordinal: {title, uuid, date}}`, ordinals as strings."""
    return {str(i): {"title": t, "uuid": u, "date": d} for i, (t, u, d) in enumerate(rows, start=1)}


#: Straight out of the live file, ordinals 47-49 under the sweeps-only filter.
_LIVE = (
    ("w-L p1_49 (sw)", "4f81d739", "2026-Aug-25 20:20:38"),
    ("w-L p2_49 (sw)", "c716f1e4", "2026-Aug-25 20:20:48"),
    ("w-L p3_49 (sw)", "7868f377", "2026-Aug-25 20:20:58"),
)


# ---- the date, which is a display string ------------------------------------------------


def test_rews_own_date_format_is_read():
    assert ci.parse_date("2026-Jun-22 12:10:35") == datetime(2026, 6, 22, 12, 10, 35)


def test_an_iso_date_is_read_too():
    """If REW ever starts answering properly, nothing here has to change."""
    assert ci.parse_date("2026-06-22T12:10:35") == datetime(2026, 6, 22, 12, 10, 35)


def test_a_month_this_module_does_not_know_is_not_a_crash():
    """`date` is formatted by REW's own (Java) locale. The machine this was written on says `Jun`;
    the machine it runs on may not, and the answer to that is a fallback plus a log line — not an
    exception, and not a wrong order that looks right."""
    assert ci.parse_date("2026-чер-22 12:10:35") is None
    assert ci.parse_date("whenever") is None
    assert ci.parse_date("") is None and ci.parse_date(None) is None


def test_an_unreadable_date_is_logged_once_with_the_raw_string(caplog):
    """The first machine that produces a new format tells us what it is."""
    import logging

    from autosound_tcc.core import app_log

    ci._unparsed_seen.discard("2026-жов-01 10:00:00")
    with caplog.at_level(logging.INFO, logger=app_log.LOGGER_NAME):
        ci.parse_date("2026-жов-01 10:00:00")
        ci.parse_date("2026-жов-01 10:00:00")

    said = [r.getMessage() for r in caplog.records if "rew date" in r.getMessage()]
    assert len(said) == 1, "one line per unknown format, not one per row"
    assert "2026-жов-01 10:00:00" in said[0]


# ---- the order --------------------------------------------------------------------------


def test_the_rows_come_back_in_capture_order_not_rews_order(tmp_path):
    """REW's list order is not capture order — measured: rows captured at 13:25 were served after
    rows captured at 20:11."""
    answer = _rew(
        ("late in the list, early in the day", "aaa", "2026-Aug-25 13:25:16"),
        ("first in the list, late in the day", "bbb", "2026-Aug-25 20:11:31"),
    )
    # REW hands them back in ITS order; flip the keys so the list order is the opposite of time.
    answer = {"1": answer["2"], "2": answer["1"]}

    rows = ci.candidates(answer, tmp_path)

    assert [row.uuid for row in rows] == ["aaa", "bbb"]
    assert ci.ordered_by_date(rows)


def test_one_unreadable_date_leaves_the_whole_list_in_rews_order(tmp_path):
    """Never half and half: a list sorted by whatever parsed, with the rest swept to one end, is
    the shape that looks ordered and is not."""
    answer = _rew(
        ("second", "bbb", "2026-Aug-25 20:11:31"),
        ("first", "aaa", "2026-Aug-25 13:25:16"),
        ("unreadable", "ccc", "2026-жов-01 10:00:00"),
    )

    rows = ci.candidates(answer, tmp_path)

    assert [row.uuid for row in rows] == ["bbb", "aaa", "ccc"], "REW's own order, untouched"
    assert not ci.ordered_by_date(rows), "and the dialog is told, so it can say so"


def test_a_retake_is_marked_and_nothing_is_refused(tmp_path):
    """Straight from the live file: `tw-L p8_49` is timed 20:17:29 and `tw-L p9_49` 20:17:02 — p8
    was taken again after p9. Read by name that pair is in order; read by time it is not.

    The user's instruction on this (2026-09-02): worth attention, not a stopper."""
    rows = ci.candidates(_rew(
        ("tw-L p7_49 (sw)", "ee82f988", "2026-Aug-25 20:16:42"),
        ("tw-L p8_49 (sw)", "ea6e71d9", "2026-Aug-25 20:17:29"),
        ("tw-L p9_49 (sw)", "762f9191", "2026-Aug-25 20:17:02"),
    ), tmp_path)
    # Read in the order the LIST has them (by name), which is how "Give names" will fill.
    by_name = sorted(rows, key=lambda row: row.title)

    assert ci.out_of_sequence(by_name) == {"762f9191"}
    assert ci.out_of_sequence(rows) == set(), "in capture order there is nothing to flag"


# ---- the window and the filter -----------------------------------------------------------


def test_the_window_opens_on_what_the_round_is_waiting_for(tmp_path):
    rows = ci.candidates(_rew(*[(f"m_{n}", f"u{n}", f"2026-Aug-25 20:{n:02d}:00")
                                for n in range(1, 41)]), tmp_path)

    assert len(ci.window(rows, waiting=14)) == 14
    assert [row.uuid for row in ci.window(rows, waiting=14)][0] == "u27", "the TAIL: the newest"


def test_a_small_round_still_shows_enough_to_see_what_came_before(tmp_path):
    """A window of three hides the measurement taken just before the three."""
    rows = ci.candidates(_rew(*[(f"m_{n}", f"u{n}", f"2026-Aug-25 20:{n:02d}:00")
                                for n in range(1, 41)]), tmp_path)

    assert len(ci.window(rows, waiting=3)) == ci.MIN_WINDOW


def test_plus_ten_reaches_further_back_a_portion_at_a_time(tmp_path):
    rows = ci.candidates(_rew(*[(f"m_{n}", f"u{n}", f"2026-Aug-25 20:{n:02d}:00")
                                for n in range(1, 41)]), tmp_path)

    assert len(ci.window(rows, waiting=14, pages=1)) == 24
    assert len(ci.window(rows, waiting=14, pages=99)) == 40, "and never past what REW gave"


def test_a_row_that_was_ticked_by_name_is_kept_in_the_window(tmp_path):
    """The tail is where a round usually ends — but a measurement matched by name can be anywhere,
    and one the dialog decided for the person has to be one the person can see."""
    rows = ci.candidates(_rew(*[(f"m_{n}", f"u{n}", f"2026-Aug-25 20:{n:02d}:00")
                                for n in range(1, 41)]), tmp_path)

    shown = ci.window(rows, waiting=3, keep={"u2"})

    assert [row.uuid for row in shown][0] == "u2", "in its own place in the list, not appended"
    assert len(shown) == ci.MIN_WINDOW + 1


# ---- which rows open ticked --------------------------------------------------------------


def test_the_tick_follows_the_name_the_round_is_waiting_for(tmp_path):
    rows = ci.candidates(_rew(*[("w-L_1 (sw)", "u1", "2026-Aug-25 20:01:00"),
                                ("stray", "u2", "2026-Aug-25 20:02:00"),
                                ("w-R_1 (sw)", "u3", "2026-Aug-25 20:03:00")]), tmp_path)

    picked = ci.preselect(rows, ["w-L_1 (sw)", "w-R_1 (sw)"], tmp_path)

    assert picked.ticked == {"u1", "u3"}
    assert picked.ambiguous == frozenset()


def test_one_name_on_two_measurements_ticks_neither(tmp_path):
    """Which of the two came out is the person's question — and a rule that picks one of them
    silently takes the wrong graph into the round half the time."""
    rows = ci.candidates(_rew(*[("w-L_1 (sw)", "u1", "2026-Aug-25 20:01:00"),
                                ("w-L_1 (sw)", "u2", "2026-Aug-25 20:02:00")]), tmp_path)

    picked = ci.preselect(rows, ["w-L_1 (sw)"], tmp_path)

    assert picked.ticked == frozenset()
    assert picked.ambiguous == {"u1", "u2"}
    assert ci.repeated_titles(rows) == {"u1", "u2"}


def test_what_this_project_already_took_is_not_offered_again(tmp_path):
    rows = ci.candidates(_rew(*[("w-L_1 (sw)", "u1", "2026-Aug-25 20:01:00")]), tmp_path)
    ci.record_imported(rows, round_id="cap_001", project_dir=tmp_path)

    again = ci.candidates(_rew(*[("w-L_1 (sw)", "u1", "2026-Aug-25 20:01:00")]), tmp_path)

    assert ci.preselect(again, ["w-L_1 (sw)"], tmp_path).ticked == frozenset()


def test_nothing_is_ticked_when_the_round_waits_for_nothing(tmp_path):
    rows = ci.candidates(_rew(*_LIVE), tmp_path)

    assert ci.preselect(rows, [], tmp_path).ticked == frozenset()


def test_what_this_project_already_imported_is_marked_and_can_be_filtered(tmp_path):
    rows = ci.candidates(_rew(*_LIVE), tmp_path)
    ci.record_imported(rows[:2], round_id="cap_001", project_dir=tmp_path)

    again = ci.candidates(_rew(*_LIVE), tmp_path)

    assert [row.imported for row in again] == [True, True, False]
    assert [row.uuid for row in ci.unprocessed(again)] == ["7868f377"]


# ---- the store --------------------------------------------------------------------------


def test_the_store_is_the_projects_and_survives_a_reread(tmp_path):
    rows = ci.candidates(_rew(*_LIVE), tmp_path)

    assert ci.record_imported(rows, round_id="cap_002", project_dir=tmp_path) == 3

    saved = json.loads((tmp_path / ".tcc" / ci.FILENAME).read_text(encoding="utf-8"))
    assert saved["schema"] == ci.SCHEMA
    assert set(saved["measurements"]) == {"4f81d739", "c716f1e4", "7868f377"}
    assert saved["measurements"]["4f81d739"]["round"] == "cap_002"
    assert ci.load_imported(tmp_path / "elsewhere") == {}, "another project has its own"


def test_the_checklist_survives_rew_being_closed(tmp_path):
    """The whole reason the store exists. "Captured" used to mean "REW is showing a title like that
    RIGHT NOW", so the checklist emptied itself when REW was shut — or filtered."""
    ci.record_imported(ci.candidates(_rew(*_LIVE), tmp_path), project_dir=tmp_path)

    assert ci.imported_titles(tmp_path) == ["w-L p1_49 (sw)", "w-L p2_49 (sw)", "w-L p3_49 (sw)"]


def test_a_measurement_with_no_uuid_is_listed_but_not_recorded(tmp_path):
    """A REW old enough to answer without one is not broken, but nothing this module promises holds
    for it: after a rename there is no way to know it again."""
    rows = ci.candidates(_rew(("nameless", "", "2026-Aug-25 20:20:38")), tmp_path)

    assert len(rows) == 1 and not rows[0].identified
    assert ci.record_imported(rows, project_dir=tmp_path) == 0
    assert ci.load_imported(tmp_path) == {}


def test_a_corrupt_store_reads_as_nothing_imported(tmp_path):
    (tmp_path / ".tcc").mkdir()
    (tmp_path / ".tcc" / ci.FILENAME).write_text("{ not json", encoding="utf-8")

    assert ci.load_imported(tmp_path) == {}, "the worst that follows is rows shown twice"


def test_the_title_written_down_can_be_the_one_the_rename_gave(tmp_path):
    """Step 2 renames on Apply; what the store must remember is what the measurement is called
    AFTER that — without this module knowing anything about renaming."""
    rows = ci.candidates(_rew(("Measurement 7", "abc", "2026-Aug-25 20:20:38")), tmp_path)

    ci.record_imported(rows, project_dir=tmp_path, titles={"abc": "w-L_02 (sw)"})

    assert ci.imported_titles(tmp_path) == ["w-L_02 (sw)"]


# ---- the two things worth saying out loud -------------------------------------------------


def test_imported_measurements_rew_is_not_showing_are_counted(tmp_path):
    """Either they were deleted or a filter is hiding them — and the tuner is the only one who can
    tell which. They cannot tell at all unless somebody counts: the filter's state is not on the
    wire, and a filtered answer is renumbered `1..N` with no gaps."""
    ci.record_imported(ci.candidates(_rew(*_LIVE), tmp_path), project_dir=tmp_path)

    still_shown = _rew(_LIVE[0])

    assert ci.missing_imported(still_shown, tmp_path) == ["w-L p2_49 (sw)", "w-L p3_49 (sw)"]
    assert ci.missing_imported(_rew(*_LIVE), tmp_path) == []


def test_ordinals_are_resolved_from_a_fresh_answer_because_a_hand_can_move_them(tmp_path):
    """Measured on 2026-09-02: the user swapped two rows in REW by hand, and the API returned the
    same 102 measurements with those two ordinals exchanged — every uuid, title and date unchanged.
    So a pair built when the list was drawn would rename the wrong measurement."""
    drawn = _rew(("m-L_49rep (sw) x0", "76bc75cf", "2026-Aug-25 13:28:01"),
                 ("r-R_49 (sw) x0", "702253b5", "2026-Aug-25 13:27:20"))
    after_the_swap = {"1": drawn["2"], "2": drawn["1"]}

    now = ci.resolve_ordinals(after_the_swap, ["76bc75cf", "702253b5"])

    assert now == {"76bc75cf": "2", "702253b5": "1"}
    assert ci.resolve_ordinals(after_the_swap, ["gone"]) == {}, "deleted since: no pair, no rename"


# ---- laying names onto measurements -------------------------------------------------------


def test_names_are_laid_down_from_the_row_the_tuner_picked(tmp_path):
    """The user's own description of the flow (2026-09-02): "я стаю в перший замір, нажимаю кнопку
    «Дати назву»". Downwards from a row a person chose, not onto "the newest N" — they know which
    measurement starts the batch, and a heuristic does not."""
    rows = ci.candidates(_rew(("old", "u0", "2026-Aug-25 20:00:00"),
                              ("Measurement 1", "u1", "2026-Aug-25 20:10:00"),
                              ("Measurement 2", "u2", "2026-Aug-25 20:10:10")), tmp_path)

    plan = ci.plan_renames(rows, ["w-L_02 (sw)", "w-R_02 (sw)"], start=1)

    assert plan.pairs == (("u1", "w-L_02 (sw)"), ("u2", "w-R_02 (sw)"))
    assert plan.lines_up


def test_a_retake_shows_up_as_a_count_that_does_not_line_up(tmp_path):
    """The way this goes wrong in a car, and the reason `leftover`/`unnamed` exist. The tuner
    captures a declared sequence; one sweep does not come out and is taken again. Now there are
    three measurements for two names, and filling downwards would put the second name on the
    re-take. The DATES cannot reveal it — a re-take is later, so the list is in perfect capture
    order — and the names cannot either, because they have not been given yet. The count can."""
    rows = ci.candidates(_rew(("Measurement 1", "u1", "2026-Aug-25 20:10:00"),
                              ("Measurement 2", "u2", "2026-Aug-25 20:10:10"),
                              ("Measurement 3", "u3", "2026-Aug-25 20:10:20")), tmp_path)

    plan = ci.plan_renames(rows, ["w-L_02 (sw)", "w-R_02 (sw)"])

    assert plan.pairs == (("u1", "w-L_02 (sw)"), ("u2", "w-R_02 (sw)"))
    assert plan.unnamed == ("u3",) and not plan.leftover
    assert not plan.lines_up, "and the dialog says so before anything is renamed"


def test_more_names_than_measurements_is_the_same_answer_from_the_other_end(tmp_path):
    rows = ci.candidates(_rew(("Measurement 1", "u1", "2026-Aug-25 20:10:00")), tmp_path)

    plan = ci.plan_renames(rows, ["w-L_02 (sw)", "w-R_02 (sw)"])

    assert plan.leftover == ("w-R_02 (sw)",) and not plan.unnamed
    assert not plan.lines_up


def test_a_measurement_with_no_uuid_is_not_given_a_name(tmp_path):
    """It cannot be recognised again after the rename, so renaming it is a name nobody can trace
    back to a measurement."""
    rows = ci.candidates(_rew(("nameless", "", "2026-Aug-25 20:10:00"),
                              ("Measurement 2", "u2", "2026-Aug-25 20:10:10")), tmp_path)

    plan = ci.plan_renames(rows, ["w-L_02 (sw)"])

    assert plan.pairs == (("u2", "w-L_02 (sw)"),)


# ---- and not letting two graphs answer to one name ----------------------------------------


def test_two_rows_asking_for_the_same_name_are_caught_before_anything_is_sent(tmp_path):
    answer = _rew(("Measurement 1", "u1", "2026-Aug-25 20:10:00"),
                  ("Measurement 2", "u2", "2026-Aug-25 20:10:10"))

    clashes = ci.duplicate_targets([("u1", "w-L_02 (sw)"), ("u2", "w-L_02 (sw)")], answer)

    assert clashes == ["w-L_02 (sw)"]


def test_a_name_rew_already_holds_is_caught_too(tmp_path):
    """The method's identity model rests on a title being one measurement's name — two graphs
    called `m-L_02 (sw)` are a channel that cannot be resolved afterwards."""
    answer = _rew(("m-L_02 (sw)", "u1", "2026-Aug-25 20:10:00"),
                  ("Measurement 2", "u2", "2026-Aug-25 20:10:10"))

    assert ci.duplicate_targets([("u2", "m-L_02 (sw)")], answer) == ["m-L_02 (sw)"]


def test_a_batch_that_shuffles_names_among_its_own_members_is_not_a_clash(tmp_path):
    """It passes through a moment where two titles collide and comes out fine, so checking against
    the measurements being renamed would refuse a rename that is perfectly good."""
    answer = _rew(("m-L_02 (sw)", "u1", "2026-Aug-25 20:10:00"),
                  ("m-R_02 (sw)", "u2", "2026-Aug-25 20:10:10"))

    assert ci.duplicate_targets([("u1", "m-R_02 (sw)"), ("u2", "m-L_02 (sw)")], answer) == []


def _swept(*records) -> list[bool]:
    """What the import rows say about each record, in order — the answer the dialog acts on."""
    rows = ci.candidates({str(i): r for i, r in enumerate(records, start=1)}, imported={})
    return [row.swept for row in rows]


needs_the_method = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out")


@needs_the_method
def test_a_sweep_is_told_from_an_rta_by_rews_data_and_not_by_its_title():
    """The title says `(sw)`, and the title is a convention a person types at 1 a.m. in a car park.

    Whether a capture is swept is knowledge about REW, so it is the method's answer
    (`rew_api.is_swept`, autosound-hub#110, method v3.0.47) and no longer a guess of ours (tcc#20).
    What these two tests pin survives the change of owner: a title cannot decide it.
    """
    rta = {"title": "ALL_60 (rta)", "uuid": "u1",
           "notes": "65536-point 1/48 octave RTA using Hann window"}
    sweep = {"title": "w-L_60 (sw)", "uuid": "u2", "notes": "DELAY 11.5702 ms (3.969 m)",
             "timeOfIRPeakSeconds": 0.0116, "delay": 0.0115, "signalToNoisedB": 51.2}

    assert _swept(rta, sweep) == [False, True]


@needs_the_method
def test_a_mistyped_title_does_not_change_what_gets_checked():
    """The convention broken both ways: an RTA named like a sweep and a sweep named like an RTA.
    A check skipped because of a typo is a measurement the tuner discovers at home."""
    lying_rta = {"title": "w-L_60 (sw)", "uuid": "u3", "notes": "RTA, 150 averages"}
    lying_sweep = {"title": "ALL_60 (rta)", "uuid": "u4", "notes": "DELAY 6.1 ms",
                   "timeOfIRPeakSeconds": 0.0061}

    assert _swept(lying_rta, lying_sweep) == [False, True]


@needs_the_method
def test_a_capture_nothing_can_tell_apart_is_still_checked():
    """The method's direction, and the reason it owns this now: a record that says nothing either
    way is CHECKED. A missed verdict is the tuner finding out at home; a wrongly included RTA is
    one confusing row. Ours answered the other way — no impulse fields, no check."""
    silent = {"title": "w-L_60 (sw)", "uuid": "u5", "notes": ""}

    assert _swept(silent) == [True]


def test_a_method_too_old_to_answer_leaves_every_row_checked(monkeypatch):
    """`is_swept` arrived in the method's v3.0.47. An older one on the machine must not take the
    import window down; it degrades to the same safe direction."""
    monkeypatch.setattr(vendor_loader, "load_rew_api", lambda: object())

    assert _swept({"title": "ALL (rta)", "uuid": "a", "notes": "1/48 octave RTA"}) == [True]


@needs_the_method
def test_the_rows_carry_whether_there_is_anything_to_check():
    rows = ci.candidates({
        "1": {"title": "ALL (rta)", "uuid": "a", "date": "2026-Sep-04 11:11:07",
              "notes": "65536-point 1/48 octave RTA using Hann window"},
        "2": {"title": "w-L (sw)", "uuid": "b", "date": "2026-Sep-04 11:12:07",
              "notes": "DELAY 11.5702 ms (3.969 m)", "timeOfIRPeakSeconds": 0.01},
    }, imported={})

    assert [(row.title, row.swept) for row in rows] == [
        ("ALL (rta)", False), ("w-L (sw)", True),
    ]


@needs_the_method
def test_a_renamed_channel_s_old_titles_answer_to_its_current_code(tmp_path):
    """hub #153 B. `channel_from_title` asked the grammar for a key it never returned (`channel`),
    so every title fell through to the string split: `m-L_2 (sw)`, taken before `m-L` was renamed
    `w-L` (SCR-039), read as `m-L` and missed the channel's protective record."""
    (tmp_path / "glossary.json").write_text(json.dumps({
        "schema_version": 1,
        "channels": [{"code": "w-L", "active": True, "previous_names": ["m-L"]}],
        "pairs": {}, "combos": {}, "joints": {}, "sides": {},
    }), encoding="utf-8")

    assert ci.channel_from_title("m-L_2 (sw)", tmp_path) == "w-L"


@needs_the_method
def test_a_name_outside_the_grammar_comes_with_the_method_s_reason(tmp_path):
    """hub #153 E: `explain_name` says why a title is not in the grammar (method v3.0.53)."""
    explain = ci.name_explainer(tmp_path)

    assert "_N" in explain("w-L (sw)"), "no `_N` before `(sw)`"
    assert explain("w-L_2 (sw) noXO") == "", "a clarification after the method is in the grammar"
    assert explain("w-L (imp)") == "", "and so is an impedance sweep without `_N`"


def test_a_method_without_explain_name_explains_nothing(monkeypatch, tmp_path):
    from autosound_tcc.core import vendor_loader

    class _Old:
        pass

    monkeypatch.setattr(vendor_loader, "load_naming", lambda: _Old())

    assert ci.name_explainer(tmp_path)("w-L (sw)") == ""



def test_a_ticked_row_knows_the_name_the_round_gave_it(tmp_path):
    """Finding 28: the New name column was empty on every row although the match was already
    made — by name. The round's own spelling is the name the row is filed under."""
    rows = ci.candidates(_rew(*[("w-L_01 (sw)", "u1", "2026-Aug-25 20:01:00"),
                                ("w-R_1 (sw)", "u3", "2026-Aug-25 20:03:00")]), tmp_path)

    picked = ci.preselect(rows, ["w-L_1 (sw)", "w-R_1 (sw)"], tmp_path)

    assert picked.names == {"u1": "w-L_1 (sw)", "u3": "w-R_1 (sw)"}


# ---- a likely typo: the closest missing name, never another series (tcc#114) -------------


#: The live REW of 2026-10-01 (finding 122), in REW's order: an older series of three, then the
#: round's own `sw+w-L_3 (sw)` typed `(se)`.
_SERIES_B1_AND_A_TYPO = (
    ("sw_B1 (sw)", "u1", "2026-Oct-01 12:01:00"),
    ("sw+w-L_B1 (sw)", "u2", "2026-Oct-01 12:02:00"),
    ("sw+w-R_B1 (sw)", "u3", "2026-Oct-01 12:03:00"),
    ("sw+w-L_3 (se)", "u4", "2026-Oct-01 13:04:00"),
)


@needs_the_method
@pytest.mark.parametrize("rows, expected", [
    (_SERIES_B1_AND_A_TYPO, ["sw_3 (sw)", "sw+w-L_3 (sw)", "sw+w-R_3 (sw)"]),
    (tuple(row for row in _SERIES_B1_AND_A_TYPO if row[1] != "u3"), ["sw_3 (sw)", "sw+w-L_3 (sw)"]),
], ids=["live", "plan"])
def test_another_series_is_not_a_typo_and_the_real_typo_gets_its_name(tmp_path, rows, expected):
    """Finding 122: the typo pass walked REW's order and gave each missing name to the first row
    past the cutoff — `sw_B1 (sw)` took `sw_3 (sw)` at 0.84, and `sw+w-L_3 (se)` (0.92) got
    nothing. A row of another series of the round's driver is a measurement of its own, for every
    name: `sw+w-L_B1 (sw)` reads 0.82 like `sw+w-R_3 (sw)` and is no typo of that either."""
    picked = ci.preselect(ci.candidates(_rew(*rows), tmp_path), expected, tmp_path)

    assert picked.names == {"u4": "sw+w-L_3 (sw)"}
    assert picked.proposed == {"u4"}, "proposed, so it opens unticked"
    assert picked.ticked == frozenset()


def test_the_closest_row_gets_the_missing_name_not_the_first_close_one(tmp_path):
    """`r-L_1 (se)` comes first in REW's list and passes the cutoff (0.80); `r-R_1 (se)` is the
    closer (0.90) and gets the name."""
    rows = ci.candidates(_rew(*[("r-L_1 (se)", "u1", "2026-Oct-01 12:01:00"),
                                ("r-R_1 (se)", "u2", "2026-Oct-01 12:02:00")]), tmp_path)

    picked = ci.preselect(rows, ["r-R_1 (sw)"], tmp_path)

    assert picked.names == {"u2": "r-R_1 (sw)"}
    assert picked.proposed == {"u2"}


@needs_the_method
def test_a_series_the_grammar_reads_is_not_a_typo_either(tmp_path):
    """`sw_4 (sw)` reads 0.89 like `sw_3 (sw)`, and the grammar says what it is: series 4."""
    rows = ci.candidates(_rew(*[("sw_4 (sw)", "u1", "2026-Oct-01 12:01:00")]), tmp_path)

    picked = ci.preselect(rows, ["sw_3 (sw)"], tmp_path)

    assert picked.names == {} and picked.proposed == frozenset()


# ---- one title REW already holds twice: said, nothing more (tcc#94) ---------------------


@needs_the_method
def test_a_title_rew_holds_twice_is_named_and_distinct_titles_are_not():
    """tcc#94, the Arbiter 2026-10-02: «якщо є однакові назви … попереджати користувача і все».
    The rule is the method's own `rew_api.duplicate_titles`, so the warning names exactly what the
    method's check names — compared with the real function, not with a copy of it."""
    twice = _rew(("m-L_02 (sw)", "u1", "2026-Aug-25 20:10:00"),
                 ("m-R_02 (sw)", "u2", "2026-Aug-25 20:10:10"),
                 ("m-L_02 (sw)", "u3", "2026-Aug-25 20:10:20"))
    once = _rew(("m-L_02 (sw)", "u1", "2026-Aug-25 20:10:00"),
                ("m-R_02 (sw)", "u2", "2026-Aug-25 20:10:10"))

    assert ci.duplicate_titles(twice) == ["m-L_02 (sw)"]
    assert ci.duplicate_titles(twice) == sorted(
        vendor_loader.load_rew_api().duplicate_titles(twice))
    assert ci.duplicate_titles(once) == []


def test_a_rename_already_sent_is_read_over_rews_answer():
    """A rename made in the import window can be what settles a pair: the answer was read before
    it, and a warning about a name REW no longer holds twice is a warning about nothing."""
    answer = _rew(("m-L_02 (sw)", "u1", "2026-Aug-25 20:10:00"),
                  ("m-L_02 (sw)", "u2", "2026-Aug-25 20:10:10"))

    assert ci.duplicate_titles(answer, renamed={"u2": "m-R_02 (sw)"}) == []
    assert ci.duplicate_titles(answer) == ["m-L_02 (sw)"], "REW's answer itself is not edited"


def test_without_the_method_the_same_rule_still_names_the_title(monkeypatch):
    """No method on the machine (or one too old to have the function) must not silence the
    warning: the rule is one line, and it is the method's line."""
    monkeypatch.setattr(vendor_loader, "load_rew_api", lambda: object())
    answer = _rew(("m-L_02 (sw)", "u1", "2026-Aug-25 20:10:00"),
                  ("m-L_02 (sw)", "u2", "2026-Aug-25 20:10:10"),
                  ("", "u3", "2026-Aug-25 20:10:20"),
                  ("", "u4", "2026-Aug-25 20:10:30"))

    assert ci.duplicate_titles(answer) == ["m-L_02 (sw)"], "and an empty title is no name"


def test_the_method_s_own_function_is_the_one_asked(monkeypatch):
    """Not a local copy that happens to agree with it: whatever the method's `duplicate_titles`
    answers is what the warning names."""
    class _Method:
        @staticmethod
        def duplicate_titles(measurements):
            return {"from-the-method": ["1", "2"]}

    monkeypatch.setattr(vendor_loader, "load_rew_api", lambda: _Method())

    assert ci.duplicate_titles(_rew(("m-L_02 (sw)", "u1", "2026-Aug-25 20:10:00"))) == [
        "from-the-method"]


def test_a_method_that_raises_falls_back_to_the_same_rule(monkeypatch):
    """The line is advice, and ⤓ must not lose its import window over it: a method
    that is there but fails is counted past, the way a missing one is."""
    class _Broken:
        @staticmethod
        def duplicate_titles(measurements):
            raise RuntimeError("a method caught mid-update")

    monkeypatch.setattr(vendor_loader, "load_rew_api", lambda: _Broken())
    answer = _rew(("m-L_02 (sw)", "u1", "2026-Aug-25 20:10:00"),
                  ("m-L_02 (sw)", "u2", "2026-Aug-25 20:10:10"))

    assert ci.duplicate_titles(answer) == ["m-L_02 (sw)"]


# ---- the capture check at import (tcc#21) ---------------------------------------------------


_RTA_NOTES = "65536-point 1/48 octave RTA using Hann window, no smoothing and 150 averages"


def _verdict(valid=True, exists=True, applicable=True, issues=()):
    """The method's verdict shape (`verify.verdict`): `{name, exists, applicable, valid, issues,
    stats}`, `stats.uuid` pinned (SCR-040)."""
    return {"name": "", "exists": exists, "applicable": applicable, "valid": valid,
            "issues": list(issues), "stats": {}}


def _asking(answer=None):
    """A stand-in for the method's `verdict`, writing down each question it was asked."""
    asked = []

    def verdict(name, measurements=None, **_kwargs):
        asked.append((name, dict(measurements or {})))
        return dict(answer or _verdict(), name=name)

    return verdict, asked


def test_only_the_sweeps_handed_in_are_put_to_the_method():
    """The selected rows, and of those only the swept: an RTA has no verdict to give (TCC-008), and
    a row with no uuid cannot be told apart from a re-take under its title."""
    rows = ci.candidates({
        "1": {"title": "w-L_1 (sw)", "uuid": "a", "date": "", "notes": "DELAY 11.5 ms"},
        "2": {"title": "ALL_1 (rta)", "uuid": "b", "date": "", "notes": _RTA_NOTES},
        "3": {"title": "nameless", "uuid": "", "date": ""},
    }, imported={})
    verdict, asked = _asking()
    listing = {str(i): {"title": r.title, "uuid": r.uuid, "notes": ""} for i, r in
               enumerate(rows, start=1)}

    found = ci.check_sweeps(rows, listing=lambda: listing, verdict=verdict)

    assert [name for name, _ in asked] == ["w-L_1 (sw)"]
    assert set(found) == {"a"}


def test_each_sweep_is_judged_by_its_uuid_from_a_fresh_answer():
    """Two graphs under one title are a normal state of REW (a re-take before the dud is deleted),
    and the method resolves a title, which is ambiguous there. So it is handed the one record whose
    uuid the row carries — at the ordinal REW gives it NOW, since a hand can have moved it since
    the list was drawn (`resolve_ordinals`)."""
    rows = ci.candidates(_rew(("m-L_2 (sw)", "old", "2026-Aug-25 20:10:00"),
                              ("m-L_2 (sw)", "new", "2026-Aug-25 20:10:10")), imported={})
    fresh = {"7": {"title": "m-L_2 (sw)", "uuid": "new"},
             "9": {"title": "m-L_2 (sw)", "uuid": "old"}}
    verdict, asked = _asking()

    ci.check_sweeps([row for row in rows if row.uuid == "new"], listing=lambda: fresh,
                    verdict=verdict)

    assert asked == [("m-L_2 (sw)", {"7": {"title": "m-L_2 (sw)", "uuid": "new"}})]


def test_a_sweep_rew_no_longer_shows_gets_no_verdict():
    """Deleted, or hidden by a filter since the list was drawn: there is nothing to judge, and a
    verdict about nothing would be a red mark on a row that did nothing wrong."""
    rows = ci.candidates(_rew(("m-L_2 (sw)", "gone", "2026-Aug-25 20:10:00")), imported={})
    verdict, asked = _asking()

    assert ci.check_sweeps(rows, listing=lambda: {}, verdict=verdict) == {}
    assert asked == []


def test_a_method_without_the_verdict_checks_nothing(monkeypatch):
    """No method on this machine, or one too old to have `verify.verdict`: no marks, and REW is not
    asked for anything — the import window works as it did before the check existed."""
    monkeypatch.setattr(vendor_loader, "load_verify", lambda: object(), raising=False)
    rows = ci.candidates(_rew(("m-L_2 (sw)", "u", "2026-Aug-25 20:10:00")), imported={})

    def listing():
        raise AssertionError("REW was asked with nothing to judge the answer")

    assert ci.check_sweeps(rows, listing=listing) == {}


def test_unusable_is_measured_and_failed_and_nothing_else():
    """The one verdict the import window paints red. Not a curve that is not there (`exists:
    false` is a different conversation, verify.py's docstring), not an RTA the check does not apply
    to (TCC-008), and not a pass."""
    assert ci.unusable(_verdict(valid=False, issues=["in-band mean -95.0 dB — silence"]))
    assert not ci.unusable(_verdict(valid=True))
    assert not ci.unusable(_verdict(valid=False, exists=False))
    assert not ci.unusable(_verdict(valid=False, applicable=False))
    assert not ci.unusable(None) and not ci.unusable({})


@needs_the_method
def test_the_method_s_own_verdict_takes_the_question_the_check_asks():
    """The stand-in above is only worth what its likeness to the real one is (`test_ship.py`'s
    header). An RTA is the one record the real verdict answers with no HTTP at all: the call shape
    is the method's, the uuid is pinned, and `unusable` reads its answer as not red."""
    verdict = ci._verdict_by_the_method()
    record = {"title": "ALL_60 (rta)", "uuid": "u1", "notes": _RTA_NOTES}

    answer = verdict("ALL_60 (rta)", measurements={"4": record})

    assert answer["exists"] is True and answer["applicable"] is False, answer
    assert answer["stats"]["uuid"] == "u1"
    assert not ci.unusable(answer)


def test_taken_as_it_is_is_remembered_for_that_capture_and_not_for_its_title(tmp_path):
    """«Take it as it is» is asked once per capture (the Arbiter, 2026-10-02): remembered by uuid
    beside what the store already pins, so a re-take under the same title — a new uuid — is checked
    afresh (SCR-040). A later import of the same capture does not forget it."""
    from dataclasses import replace

    first = ci.candidates(_rew(("m-L_2 (sw)", "dud", "2026-Aug-25 20:10:00")), tmp_path)
    ci.record_imported([replace(first[0], as_is=True)], round_id="cap_001", project_dir=tmp_path)
    ci.record_imported(ci.candidates(_rew(("m-L_2 (sw)", "dud", "2026-Aug-25 20:10:00")),
                                     tmp_path), round_id="cap_001", project_dir=tmp_path)

    again = ci.candidates(_rew(("m-L_2 (sw)", "dud", "2026-Aug-25 20:10:00"),
                               ("m-L_2 (sw)", "retake", "2026-Aug-25 20:12:00")), tmp_path)

    assert [(row.uuid, row.as_is) for row in again] == [("dud", True), ("retake", False)]
    verdict, asked = _asking()
    listing = {"1": {"title": "m-L_2 (sw)", "uuid": "dud"},
               "2": {"title": "m-L_2 (sw)", "uuid": "retake"}}
    assert set(ci.check_sweeps(again, listing=lambda: listing, verdict=verdict)) == {"retake"}


def test_a_check_told_to_stop_asks_about_no_further_sweep():
    """Review M4: the window closed, so the rest of the batch is pulled for nobody — up to five
    seconds a sweep against a hung REW. `stop` is asked between two sweeps."""
    rows = ci.candidates(_rew(("m-L_1 (sw)", "a", "2026-Aug-25 20:10:00"),
                              ("m-R_1 (sw)", "b", "2026-Aug-25 20:10:10"),
                              ("sw_1 (sw)", "c", "2026-Aug-25 20:10:20")), imported={})
    listing = {str(i): {"title": r.title, "uuid": r.uuid} for i, r in enumerate(rows, start=1)}
    verdict, asked = _asking()

    found = ci.check_sweeps(rows, listing=lambda: listing, verdict=verdict,
                            stop=lambda: len(asked) >= 1)

    assert [name for name, _ in asked] == ["m-L_1 (sw)"]
    assert set(found) == {"a"}


def test_a_sweep_left_for_a_retake_is_remembered_by_its_uuid_until_it_is_taken(tmp_path):
    """Finding 147: «Re-take» was an answer only the import window knew, so the card read the
    curve REW still holds as one to import (blue). Kept beside «Take it as it is», by uuid; it is
    not an import, and taking that capture in after all ends it."""
    from dataclasses import replace

    rows = ci.candidates(_rew(("sw_7 (sw)", "u-sw", "2026-Oct-03 12:00:00"),
                              ("sw_7 (rta)", "u-rta", "2026-Oct-03 12:00:10")), tmp_path)
    ci.record_retakes([rows[1]], project_dir=tmp_path)
    ci.record_imported([replace(rows[0], as_is=True)], project_dir=tmp_path)

    assert ci.retakes(tmp_path) == {"u-rta": "sw_7 (rta)"}, "another capture's import keeps it"
    assert not ci.candidates(_rew(("sw_7 (rta)", "u-rta", "")), tmp_path)[0].imported
    assert ci.imported_titles(tmp_path) == ["sw_7 (sw)"]

    ci.record_imported([replace(rows[1], as_is=True)], project_dir=tmp_path)
    assert ci.retakes(tmp_path) == {}


def test_a_title_waits_for_its_retake_until_rew_holds_another_curve_under_it(tmp_path):
    """The dud stays in REW under the name; a new sweep under the same name is a new uuid, and
    from then on the title is there to be imported again."""
    rows = ci.candidates(_rew(("sw_7 (rta)", "u-rta", "2026-Oct-03 12:00:10")), tmp_path)
    ci.record_retakes(rows, project_dir=tmp_path)

    assert ci.retake_titles(_rew(("sw_7 (rta)", "u-rta", "")), tmp_path) == ["sw_7 (rta)"]
    assert ci.retake_titles({}, tmp_path) == ["sw_7 (rta)"], "REW not read: still waiting"
    assert ci.retake_titles(_rew(("sw_7 (rta)", "u-rta", ""), ("sw_7 (rta)", "u-new", "")),
                            tmp_path) == []


# ---- a sweep read over its own range, and a title that says the wrong thing (tcc#148) ---------


_SWEEP_NOTES = "DELAY 6.1250 ms (2.101 m)"


def _listed(title, uuid, notes=_SWEEP_NOTES, **range_) -> dict:
    """One record of REW's `/measurements` listing: `startFreq` / `endFreq` are among its fields
    (`rew_api.py`'s field list, measured on a live REW V5.40)."""
    return {"title": title, "uuid": uuid, "date": "2026-Oct-03 12:00:00", "notes": notes, **range_}


def test_a_sweep_is_asked_about_over_the_range_rew_holds_for_it():
    """Finding 146 (tcc#148): the verdict was asked over 20-20000 Hz, so a sub swept over 20-1001
    read «covers 20-1001 Hz, asked for 20-20000 — truncated». It is asked over the range REW holds
    for that measurement — its own `startFreq`-`endFreq`."""
    listing = {"1": _listed("sw_7 (sw)", "u1", startFreq=20.0, endFreq=1001.0)}
    asked = []

    def verdict(name, measurements=None, **band):
        asked.append((name, band))
        return _verdict()

    ci.check_sweeps(ci.candidates(listing, imported={}), listing=lambda: listing, verdict=verdict)

    assert asked == [("sw_7 (sw)", {"f_low": 20.0, "f_high": 1001.0})]


@pytest.mark.parametrize("range_", [{}, {"startFreq": 0, "endFreq": 1001.0},
                                    {"startFreq": 900.0, "endFreq": 100.0},
                                    {"startFreq": "?", "endFreq": None}])
def test_where_rew_holds_no_range_none_is_made_up(range_):
    """No range, no truncation check (the Arbiter, 2026-10-03: «Якщо немає діапазону, то і не
    перевіряємо»): nothing is passed for a band REW did not give — or gave as nothing a sweep can
    be set to — so the method's own defaults read the rest."""
    listing = {"1": _listed("sw_7 (sw)", "u1", **range_)}
    asked = []

    def verdict(name, measurements=None, **band):
        asked.append(band)
        return _verdict()

    ci.check_sweeps(ci.candidates(listing, imported={}), listing=lambda: listing, verdict=verdict)

    assert asked == [{}]


def _rew_fr(monkeypatch, low, high, level=85.0, slope=True):
    """REW faked at the method's own boundary (`verify._api`), no HTTP: an FR from `low` to `high`
    Hz at 1/12 octave, falling 12 dB an octave above a third of the way if `slope`, and no
    impulse."""
    import math

    verify = vendor_loader.load_verify()
    n = int(math.log2(high / low) * 12) + 1
    freqs = [low * 2 ** (i / 12) for i in range(n)]
    knee = low * (high / low) ** (1 / 3)
    mag = [level - (12 * math.log2(f / knee) if slope and f > knee else 0) for f in freqs]

    def no_impulse(*_args, **_kwargs):
        raise RuntimeError("no impulse in this fake")

    monkeypatch.setattr(verify._api, "get_fr", lambda mid, smoothing=None: (freqs, mag, None))
    monkeypatch.setattr(verify._api, "get_impulse_response", no_impulse)


@needs_the_method
def test_a_band_limited_sweep_is_usable_by_the_method_s_own_verdict(monkeypatch):
    """The real verdict, REW faked at its edge: the sub sweep of finding 146 (20-1001 Hz) is usable
    over its own range, and over none when REW gives none — the method's other verdicts still
    stand there (a silent capture is still red). A sweep that stops short of the range REW holds
    for it is still «truncated»: that is what the word means now."""
    rows = lambda listing: ci.candidates(listing, imported={})  # noqa: E731
    _rew_fr(monkeypatch, 20.0, 1001.0)

    held = {"1": _listed("sw_7 (sw)", "u1", startFreq=20.0, endFreq=1001.0)}
    found = ci.check_sweeps(rows(held), listing=lambda: held)
    assert not ci.unusable(found["u1"]), found["u1"]["issues"]

    bare = {"1": _listed("sw_7 (sw)", "u1")}
    found = ci.check_sweeps(rows(bare), listing=lambda: bare)
    assert not ci.unusable(found["u1"]), found["u1"]["issues"]

    _rew_fr(monkeypatch, 20.0, 1001.0, level=-95.0)
    found = ci.check_sweeps(rows(bare), listing=lambda: bare)
    assert ci.unusable(found["u1"]) and "silence" in " ".join(found["u1"]["issues"])
    assert not any("truncated" in issue for issue in found["u1"]["issues"])

    _rew_fr(monkeypatch, 20.0, 300.0)
    full = {"1": _listed("w-L_7 (sw)", "u1", startFreq=20.0, endFreq=20000.0)}
    found = ci.check_sweeps(rows(full), listing=lambda: full)
    assert ci.unusable(found["u1"]) and "truncated" in " ".join(found["u1"]["issues"])


def _judged(verdict, title, project_dir=None):
    return ci.verdict_reader(project_dir)(verdict, title)


@needs_the_method
def test_a_title_of_the_other_kind_reads_red_with_what_to_do(tmp_path):
    """Finding 146's second half: the same sub sweep named `sw_7 (rta)` is right to stop — the
    title names an RTA and REW holds a sweep (the Arbiter: «перше брати не можна, а друге можна»).
    Red, with that reason; and an RTA under a sweep's title the same, the other way round. Read off
    REW's definite kind (the verdict's `kind`, `rew_api.measurement_kind`): a capture whose notes
    say nothing either way is not called the wrong kind."""
    sweep = dict(_verdict(), kind="sweep")
    rta = dict(_verdict(valid=False, applicable=False,
                        issues=["this check is for swept captures; REW says this one is rta"]),
               kind="rta")
    unknown = dict(_verdict(), kind="unknown")

    named_rta = _judged(sweep, "sw_7 (rta)", tmp_path)
    assert ci.unusable(named_rta)
    assert named_rta["clashes"] == [{"why": "sweep_named_rta"}]
    assert not ci.unusable(_judged(sweep, "sw_7 (sw)", tmp_path))

    named_sweep = _judged(rta, "w-L_3 (sw)", tmp_path)
    assert ci.unusable(named_sweep)
    assert named_sweep["clashes"] == [{"why": "rta_named_sweep", "kind": "rta"}]
    assert named_sweep["issues"] == [], "the method judged nothing here; the clash is the reason"
    assert not ci.unusable(_judged(rta, "w-L_3 (rta)", tmp_path))

    assert not ci.unusable(_judged(unknown, "w-L_3 (rta)", tmp_path))
    assert not ci.unusable(_judged(sweep, "not in the grammar", tmp_path))


@needs_the_method
def test_a_sweep_s_title_on_an_rta_is_put_to_the_check(tmp_path):
    """An RTA is not put to the check (TCC-008) — unless its title names a sweep: that clash is the
    check's to say, and the method answers an RTA with no HTTP at all. A name being given in the
    window counts as the title it will carry."""
    rows = ci.candidates({
        "1": _listed("w-L_3 (sw)", "a", notes=_RTA_NOTES),
        "2": _listed("w-L_3 (rta)", "b", notes=_RTA_NOTES),
        "3": _listed("tw-L_3 (rta)", "c", notes=_RTA_NOTES),
    }, imported={})

    assert [row.uuid for row in ci.to_check(rows)] == ["a"]
    assert [row.uuid for row in ci.to_check(rows, names={"a": "w-L_3 (rta)",
                                                         "c": "tw-L_3 (sw)"})] == ["c"]


@needs_the_method
@pytest.mark.parametrize(("title", "peak", "why"), [
    ("tw-L_7 (sw)", 80.0, "tweeter_plays_low"),
    ("tw-R_7 (sw)", 3150.0, None),
    ("sw_7 (sw)", 4000.0, "sub_plays_high"),
    ("sw_7 (sw)", 45.0, None),
    ("m-L_7 (sw)", 80.0, None),
    ("w-L_7 (sw)", 8000.0, None),
    ("w-L_7 (sw)", 60.0, None),
])
def test_a_driver_whose_data_is_plainly_another_s_reads_red(tmp_path, title, peak, why):
    """The Arbiter, 2026-10-03: «якщо треба твітер, а там саб — добре б знаходити». Only the clear
    extremes, by where the sweep peaks (the verdict's `max_freq`, read at the method's 1/6): a
    tweeter whose peak is in a sub's or a woofer's range, a sub whose peak is in a tweeter's. A
    midrange, a woofer or a mid-bass is never judged by it."""
    verdict = dict(_verdict(), kind="sweep", stats={"max_freq": peak})

    judged = _judged(verdict, title, tmp_path)

    if why is None:
        assert not ci.unusable(judged), judged
    else:
        assert ci.unusable(judged)
        assert judged["clashes"] == [{"why": why, "peak": peak}]


@needs_the_method
def test_a_driver_s_role_is_the_project_s_where_it_names_one(tmp_path):
    """The channel's role in `project.json` first (the method's own vocabulary — `tweeter`,
    `sub`, …), the code's convention (`tw`, `sw`) only where the project names none."""
    (tmp_path / "project.json").write_text(json.dumps({"channels": [
        {"code": "hi-L", "role": "tweeter"}, {"code": "tw-L", "role": "midrange"}]}),
        encoding="utf-8")
    verdict = dict(_verdict(), kind="sweep", stats={"max_freq": 80.0})

    assert ci.unusable(_judged(verdict, "hi-L_7 (sw)", tmp_path))
    assert not ci.unusable(_judged(verdict, "tw-L_7 (sw)", tmp_path))


@needs_the_method
def test_finding_146_as_the_arbiter_met_it(monkeypatch, tmp_path):
    """One sub sweep at 20-1001 Hz, taken twice: `sw_7 (sw)` and `sw_7 (rta)`. Before, both read
    red, «truncated». His rule: «перше брати не можна, а друге можна» — the first is usable, the
    second is not, for its title alone. The method's real verdict, REW faked at its edge."""
    _rew_fr(monkeypatch, 20.0, 1001.0)
    listing = {"1": _listed("sw_7 (sw)", "u-sw", startFreq=20.0, endFreq=1001.0),
               "2": _listed("sw_7 (rta)", "u-rta", startFreq=20.0, endFreq=1001.0)}
    judge = ci.verdict_reader(tmp_path)

    titles = {raw["uuid"]: raw["title"] for raw in listing.values()}
    found = ci.check_sweeps(ci.candidates(listing, imported={}), listing=lambda: listing)
    shown = {uuid: judge(verdict, titles[uuid]) for uuid, verdict in found.items()}

    assert not ci.unusable(shown["u-sw"]), shown["u-sw"]
    assert ci.unusable(shown["u-rta"])
    assert shown["u-rta"]["clashes"] == [{"why": "sweep_named_rta"}]
    assert not any("truncated" in issue for issue in shown["u-rta"]["issues"])
