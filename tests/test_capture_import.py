"""What the import dialog decides — tested without a window, because none of it needs one.

The numbers and shapes here are not invented: they are the four measurements taken against the
user's live REW on 2026-09-02 (`docs/CAPTURE-IMPORT-PLAN.md`), including the two that surprised us
— a UI filter that reaches the API, and an ordinal that is a position in a view rather than a
property of a measurement.
"""

from __future__ import annotations

import json
from datetime import datetime

from autosound_tcc.core import capture_import as ci


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
