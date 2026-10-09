"""Deriving the capture task from glossary + REW (state/measurement_view.py, SCR-008).

The point of the module is that the series is *derived*, not hard-coded. What's worth pinning is
that the derivation respects the car: a disabled centre and absent rears must not appear as tasks,
because a checklist with impossible rows in it stops being read.
"""

from __future__ import annotations

import json

import pytest

from autosound_tcc.core import vendor_loader
from autosound_tcc.state import measurement_view, process_view

from tests import _intake, _rew_fakes, _rounds
from autosound_tcc.state import measurement_view as mv

pytestmark = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out"
)

GLOSSARY = {
    "schema_version": 1,
    "channels": [
        {"code": "sw", "active": True},
        {"code": "w-L", "active": True},
        {"code": "w-R", "active": True},
        {"code": "c", "active": False},  # present in the car, disconnected for this preset
    ],
    "pairs": {"Ws": ["w-L", "w-R"]},
    "combos": {"ALL": []},
    "joints": {"SW+Ws": []},
    "sides": {"L": [], "R": []},
}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    (tmp_path / "glossary.json").write_text(json.dumps(GLOSSARY), encoding="utf-8")
    return tmp_path


def _bank_next_version(project):
    """Write one more ledger snapshot, through the skill's own writer for the reason `_intake`
    gives: a hand-written `v_00N` goes stale the day the schema moves."""
    state = vendor_loader.load_dsp_state()
    history = state.PresetHistory(str(project / "state"), "FULL", project_dir=str(project))
    history.snapshot({
        "preset": "FULL",
        "sample_rate": 96000,
        "channels": {"w-L": {"hp": None, "lp": None, "gain_db": 0.0, "ta_ms": 0.0,
                             "polarity": "NORM"}},
    }, note="fixture: a second banked configuration")


def _names(session):
    return [item.name for group in session.groups for item in group.items]


def test_no_glossary_means_no_derived_task_so_the_mock_stays(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))

    assert mv.has_glossary(tmp_path) is False
    assert mv.build_session("0", 1, [], tmp_path) is None


def test_glossary_embedded_in_project_json_is_found(tmp_path, monkeypatch):
    """SCR-011 folds the glossary into project.json; both homes must work."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    (tmp_path / "project.json").write_text(json.dumps({"glossary": GLOSSARY}), encoding="utf-8")

    assert mv.has_glossary(tmp_path) is True
    assert mv.build_session("0", 1, [], tmp_path) is not None


def test_an_inactive_channel_never_becomes_a_task(project):
    """The bug this whole module exists to remove: the mock asked for c_* and r-L/r-R_* on a car
    with a disconnected centre and no rear speakers."""
    session = mv.build_session("0", 1, [], project)

    assert not any(name.startswith("c_") for name in _names(session))
    assert not any(name.startswith("r-") for name in _names(session))


def test_phase_0_wants_both_methods_per_active_driver(project):
    session = mv.build_session("0", 1, [], project)

    assert sorted(_names(session)) == sorted(
        [f"{ch}_1 ({m})" for ch in ("sw", "w-L", "w-R") for m in ("sw", "rta")]
    )


def test_a_phase_that_captures_nothing_says_so(project):
    """Phase 1 analyses `_1` and takes no new measurements -- an empty task is the answer."""
    session = mv.build_session("1", 1, [], project)

    assert session.groups == ()
    assert "no capture" in session.version["en"]


def test_captured_measurements_are_marked_done(project):
    session = mv.build_session("0", 1, ["sw_1 (sw)", "sw_1 (rta)"], project)

    statuses = {item.name: item.status for g in session.groups for item in g.items}
    assert statuses["sw_1 (sw)"] == "done"
    assert statuses["w-L_1 (sw)"] == "wait"


def test_a_title_rew_is_showing_is_not_a_capture_this_project_took(project):
    """User, 2026-09-06: "я ще нічого не зробив, тільки відкрив вікно, а криві замірів вже зелені".

    REW's open list is another application's window — it decides what can be OFFERED. What this
    project took in is what colours a row, and the two are passed in separately for that reason.
    Not green, then — but blue, "it is there, load it" (F-056, the Arbiter 2026-09-16).
    """
    showing = ["sw_1 (sw)", "w-L_1 (sw)"]

    nothing_taken = mv.build_session("0", 1, showing, project, taken=[])
    statuses = {item.name: item.status for g in nothing_taken.groups for item in g.items}
    assert statuses["sw_1 (sw)"] == mv.STATUS_FOUND
    assert statuses["w-L_1 (sw)"] == mv.STATUS_FOUND
    assert statuses["w-R_1 (sw)"] == mv.STATUS_WAIT, "not in REW either: yellow"

    one_taken = mv.build_session("0", 1, showing, project, taken=["sw_1 (sw)"])
    statuses = {item.name: item.status for g in one_taken.groups for item in g.items}
    assert statuses["sw_1 (sw)"] == mv.STATUS_DONE
    assert statuses["w-L_1 (sw)"] == mv.STATUS_FOUND


def test_an_extra_rew_holds_is_green_only_once_it_was_taken(project):
    """The same rule for the off-checklist column: a graph REW is holding is an offer."""
    session = mv.build_session("0", 1, ["w-L INV_1 (sw)"], project, taken=[])

    extras = [item for g in session.groups for item in g.items if item.additional]
    assert extras and extras[0].status == mv.STATUS_FOUND

    session = mv.build_session("0", 1, ["w-L INV_1 (sw)"], project, taken=["w-L INV_1 (sw)"])
    extras = [item for g in session.groups for item in g.items if item.additional]
    assert extras and extras[0].status == mv.STATUS_DONE


def test_zero_padded_versions_count_as_captured(project):
    """REW titles are hand-typed; `sw_01` and `sw_1` are the same DSP config version, and
    reporting the first as missing is the checker crying wolf."""
    session = mv.build_session("0", 1, ["sw_01 (sw)"], project)

    statuses = {item.name: item.status for g in session.groups for item in g.items}
    assert statuses["sw_1 (sw)"] == "done"


def _renamed_glossary(project, was, now):
    """The glossary after `was` was renamed to `now` — what `project.py rename_channel` writes."""
    channels = [
        {**c, "code": now, "previous_names": [was]} if c["code"] == was else c
        for c in GLOSSARY["channels"]
    ]
    (project / "glossary.json").write_text(
        json.dumps({**GLOSSARY, "channels": channels}), encoding="utf-8"
    )


def test_a_capture_taken_before_a_rename_still_counts_as_taken(project):
    """SCR-039. A REW title is typed by hand and cannot be rewritten, so a channel renamed
    mid-project keeps its captures under the old name — and they are still that channel's, at that
    DSP config version. Asking for them again would be the checker sending somebody back into the
    car for a measurement already on disk."""
    _renamed_glossary(project, "w-L", "wf-L")

    session = mv.build_session("0", 1, ["w-L_1 (sw)"], project)
    statuses = {item.name: item.status for g in session.groups for item in g.items}

    assert statuses["wf-L_1 (sw)"] == mv.STATUS_DONE
    # and it is not ALSO reported as an off-checklist extra: one capture, one row.
    assert not any(i.additional for g in session.groups for i in g.items)


def test_a_config_change_naming_the_new_code_still_invalidates_the_old_capture(project):
    """The two names meet here: the journal event says `wf-L` (what the session was calling it)
    and the capture's title says `w-L` (what it was called when it was taken). Matching on one
    side only lets a measurement of a driver that is no longer in the car read as done."""
    _renamed_glossary(project, "w-L", "wf-L")
    _record_change(project, "remeasure: [wf-L]", what="blown voice coil")

    session = mv.build_session("0", 1, ["w-L_1 (sw)", "w-R_1 (sw)"], project)
    by_name = {item.name: item.status for group in session.groups for item in group.items}

    assert by_name["wf-L_1 (sw)"] == mv.STATUS_STALE
    assert by_name["w-R_1 (sw)"] == mv.STATUS_DONE


def test_ours_but_unasked_for_shows_as_additional_not_dropped(project):
    """An experiment tag or an off-checklist channel is information, not noise."""
    session = mv.build_session("0", 1, ["w-L INV_1 (sw)"], project)

    extras = [i for g in session.groups for i in g.items if i.additional]
    assert [i.name for i in extras] == ["w-L INV_1 (sw)"]
    assert extras[0].extra == "INV"


def test_a_different_version_is_not_pulled_into_this_task(project):
    session = mv.build_session("0", 1, ["sw_7 (sw)"], project)

    assert not any(i.additional for g in session.groups for i in g.items)


def test_phase_2_adds_the_group_pass(project):
    session = mv.build_session("2", 2, [], project)
    labels = [g.type for g in session.groups]

    # The method's columns since v3.0.62 (skill #79): Solo and Group per method; pairs, sides and
    # joints are the Group pass.
    assert "Solo (sw)" in labels and "Solo (rta)" in labels
    assert "Group (rta)" in labels


def test_off_convention_titles_are_reported_separately(project):
    """No analysis will ever find these by name -- they're invisible, not merely uncaptured.

    Since the method's v3.0.53 a clarification after the method is in the grammar: `c_01 (sw) noXO`
    is another measurement of series 1 (hub #153), no longer off-convention. A sweep with no `_N`
    still is."""
    titles = ["sw_1 (sw)", "Room EQ result", "c_01 (sw) noXO", "w-L (sw)"]

    assert mv.off_convention(titles, project) == ["Room EQ result", "w-L (sw)"]


def test_off_convention_is_empty_without_a_glossary(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))

    assert mv.off_convention(["anything"], tmp_path) == []


def _record_change(project, impact, what="driver swapped"):
    """A `config_change` written the way the skill writes it, through its own modules."""
    process_module = vendor_loader.load_process()
    _intake.seed(project)
    proc = process_module.Process(str(project / "process"))
    proc.enter_phase("0")
    proj_module = vendor_loader.load_project()
    proj = proj_module.Project(str(project))
    proj.save(proj.load())
    proj.record_change(proc, "project.json", what, impact=impact)
    return proc


def test_a_capture_invalidated_by_a_config_change_is_unusable_not_done(project):
    """SCR-014: the graph exists, so "missing" would be a lie — and "done" would be worse, because
    the next step would tune on a measurement of a driver that is no longer in the car."""
    titles = ["w-L_1 (sw)", "w-R_1 (sw)"]
    _record_change(project, "remeasure: [w-L]", what="blown voice coil")

    session = mv.build_session("0", 1, titles, project)
    by_name = {item.name: item.status for group in session.groups for item in group.items}

    assert by_name["w-L_1 (sw)"] == mv.STATUS_STALE
    assert by_name["w-R_1 (sw)"] == mv.STATUS_DONE   # untouched channel keeps its capture
    assert by_name["sw_1 (sw)"] == mv.STATUS_WAIT    # never captured -- still just missing


def test_a_recapture_after_the_change_makes_it_done_again(project):
    titles = ["w-L_1 (sw)"]
    proc = _record_change(project, "remeasure: [w-L]")
    proc.add_step("0.9", "re-sweep w-L")
    proc.finish_step("0.9", ["w-L_1 (sw)"])

    session = mv.build_session("0", 1, titles, project)
    by_name = {item.name: item.status for group in session.groups for item in group.items}

    assert by_name["w-L_1 (sw)"] == mv.STATUS_DONE


#: The round fixtures live in `tests/_rounds.py` since #175, shared with the panel's tests.
_as_typed = _rounds.as_typed
_round = _rounds.write_round


def test_a_recorded_capture_survives_rew_being_closed(project):
    """Every status used to be recomputed from REW's open measurements, so quitting REW turned a
    finished round back into an empty checklist."""
    _round(project, version=1, expected=["sw_1 (sw)"], taken=["sw_1 (sw)"])

    session = mv.build_session("0", 1, [], project)  # REW holds nothing

    statuses = {item.name: item.status for group in session.groups for item in group.items}
    assert statuses["sw_1 (sw)"] == mv.STATUS_DONE
    # The open round lists what it asked for, not phase 0's plan (finding 64).
    assert "sw_1 (rta)" not in statuses


def test_a_capture_decided_against_is_not_a_capture_still_waiting(project):
    """Both rendered as `wait` before the round was recorded, so the next session proposed the one
    the tuner had ruled out."""
    _round(project, version=1, expected=["sw_1 (sw)"], skipped={"sw_1 (sw)": "sub disconnected"})

    session = mv.build_session("0", 1, [], project)

    statuses = {item.name: item.status for group in session.groups for item in group.items}
    assert statuses["sw_1 (sw)"] == mv.STATUS_SKIPPED


def test_the_open_round_names_the_task_rather_than_the_ledger_version(project):
    """Two passes at the same config were the same key; "this session's task" is what gets asked
    about."""
    _round(project, version=1, expected=["sw_1 (sw)"])

    session = mv.build_session("0", 1, [], project)

    assert session.id == "cap_001"
    assert "cap_001" in session.version["en"]


def test_a_closed_round_stops_being_the_live_task(project):
    process = _round(project, version=1, expected=["sw_1 (sw)"], taken=["sw_1 (sw)"])
    process.close_capture("session ended")

    session = mv.build_session("0", 1, [], project)

    assert session.id == "v1"  # back to the version, since no round is open
    statuses = {item.name: item.status for group in session.groups for item in group.items}
    # The next round is a new pass (finding 57); what cap_001 produced is on its own entry.
    assert statuses["sw_1 (sw)"] == mv.STATUS_WAIT
    past = mv.build_sessions("0", 1, [], project)[1]  # a past round keeps its titles as typed
    assert {i.name: i.status for g in past.groups for i in g.items}[_as_typed("sw_1 (sw)")] \
        == mv.STATUS_DONE


def test_a_capture_that_failed_the_check_is_not_done(project):
    """A sweep that never finished and a muted channel both leave a title behind. Before the
    verdict was recorded, both read as captured and every later phase computed on them."""
    from autosound_tcc.state import process_view

    module = vendor_loader.load_process()
    _intake.seed(project)
    process = module.Process(str(process_view.process_dir(project)))
    process.enter_phase("0")
    process.start_capture(1, expected=["sw_1 (sw)"], step="0.1")
    process.record_capture("sw_1 (sw)")
    state = process.load()
    state["capture"]["taken"]["sw_1 (sw)"]["verified"] = {
        "ok": False, "exists": True, "uuid": "9ff4deb9",
        "issues": ["in-band mean -94.0 dB — silence, not a sweep"],
    }
    process._write(state)

    session = mv.build_session("0", 1, ["sw_1 (sw)"], project)  # REW holds the title

    item = next(i for g in session.groups for i in g.items if i.name == "sw_1 (sw)")
    assert item.status == mv.STATUS_STALE  # the legend's "taken, unusable"
    assert "silence" in (item.extra or "")  # and the reason travels with it


def test_a_capture_that_passed_reads_as_done(project):
    from autosound_tcc.state import process_view

    module = vendor_loader.load_process()
    _intake.seed(project)
    process = module.Process(str(process_view.process_dir(project)))
    process.enter_phase("0")
    process.start_capture(1, expected=["sw_1 (sw)"], step="0.1")
    process.record_capture("sw_1 (sw)")
    state = process.load()
    state["capture"]["taken"]["sw_1 (sw)"]["verified"] = {"ok": True, "exists": True, "issues": []}
    process._write(state)

    session = mv.build_session("0", 1, [], project)  # and REW need not even be open

    item = next(i for g in session.groups for i in g.items if i.name == "sw_1 (sw)")
    assert item.status == mv.STATUS_DONE


# ---- capture history (user, 2026-08-11) -------------------------------------


def _journal(project, events):
    process = project / "process"
    process.mkdir(parents=True, exist_ok=True)
    (process / "journal.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )


def _round_events(rid="cap_001", phase="0", version="v_003"):
    return [
        {"at": "2026-08-11T15:48:06+00:00", "type": "capture_task_issued", "capture": rid,
         "phase": phase, "version": version,
         "expected": ["w-L_01 (sw)", "w-L_01 (rta)", "r-L_01 (sw)"]},
        {"at": "2026-08-11T15:48:08+00:00", "type": "capture_taken", "capture": rid,
         "title": "w-L_01 (sw)", "planned": True},
        {"at": "2026-08-11T15:48:09+00:00", "type": "capture_taken", "capture": rid,
         "title": "w-L_01 (rta)", "planned": True},
        {"at": "2026-08-11T15:48:21+00:00", "type": "capture_skipped", "capture": rid,
         "title": "r-L_01 (sw)", "reason": "Rear deferred by the Arbiter for this pass"},
        {"at": "2026-08-11T15:48:29+00:00", "type": "capture_verified", "capture": rid,
         "ok": ["w-L_01 (sw)"], "bad": ["w-L_01 (rta)"]},
        {"at": "2026-08-11T15:48:34+00:00", "type": "capture_round_closed", "capture": rid},
    ]


def test_rounds_are_folded_back_out_of_the_journal(tmp_path):
    """`process-state.json` keeps only the OPEN round; every round that ever ran is in the journal,
    and nothing read it — so the panel's history had no supplier at all."""
    _journal(tmp_path, _round_events())

    rounds = process_view.capture_rounds(tmp_path)

    assert len(rounds) == 1
    round_ = rounds[0]
    assert round_["id"] == "cap_001" and round_["phase"] == "0"
    assert round_["closed"]
    assert set(round_["taken"]) == {"w-L_01 (sw)", "w-L_01 (rta)"}
    assert round_["taken"]["w-L_01 (rta)"]["verified"] == {"ok": False}
    assert "Rear deferred" in round_["skipped"]["r-L_01 (sw)"]["reason"]


def test_a_past_round_becomes_a_read_only_session_with_its_own_verdicts(tmp_path):
    _journal(tmp_path, _round_events())

    session = measurement_view._session_for_round(
        process_view.capture_rounds(tmp_path)[0], None
    )

    by_name = {i.name: i for g in session.groups for i in g.items}
    assert session.id == "cap_001"
    assert by_name["w-L_01 (sw)"].status == measurement_view.STATUS_DONE
    # The checker said no, and that outranks "a title of that name exists" here too.
    assert by_name["w-L_01 (rta)"].status == measurement_view.STATUS_STALE
    assert by_name["r-L_01 (sw)"].status == measurement_view.STATUS_SKIPPED
    # Why a human decided against it, not the checker's "no measurement titled ..." — a skipped
    # capture is always also missing, and only one of those two facts is worth reading.
    assert "Rear deferred" in by_name["r-L_01 (sw)"].extra
    assert [g.method for g in session.groups] == ["sw", "rta"]


def test_a_title_ending_in_something_other_than_the_method_still_sorts_by_it(tmp_path):
    """tcc#101 (finding 111), round `cap_016`: `L m+tw_55 (rta) inv` ends with `inv`, not `(rta)`,
    so sorting by the title's last word put it under SW. The grammar's own `parse_name` already
    reads `method: rta` for it; sort by that instead, and fall back to the suffix only for a title
    the grammar does not read at all."""
    groups = measurement_view.groups_from_titles(
        ["L m+tw_55 (rta) inv", "off-convention title (sw)"]
    )

    by_method = {g["method"]: g["names"] for g in groups}
    assert by_method["rta"] == ["L m+tw_55 (rta) inv"]
    # Not in the grammar (no `_N`) -- still sorts by its own suffix.
    assert by_method["sw"] == ["off-convention title (sw)"]


# ---- a title the grammar refuses still sorts by its method tag (tcc#109, finding 117) -----------
# `testAgy-auto`, rounds `cap_010` and `cap_013`: the notes after the tag are the grammar's own
# clarification (naming.py `_TAGGED_RE`, `params`) -- what it refuses is the `D_` before the code
# (S-042: `_` only begins the series). Refused, the title fell to its last word and to SW. The
# method's v3.0.65 read them, `D_L` as a channel `D-L` the car does not have (S-079); v3.0.66
# refuses them again, the `D_` named as an old configuration prefix (hub #232 TCC-044).
_CAP_013_TAKEN = {
    "D_SW+Ws_9 (rta)": {"at": "2026-09-24T14:41:01+00:00", "planned": True},
    "D_ALL_9 (rta)": {"at": "2026-09-24T14:41:02+00:00", "planned": True},
    "D_L w+m_9 (rta)": {"at": "2026-09-24T14:41:02+00:00", "planned": False},
    "D_L w+m_9 (rta) inv": {"at": "2026-09-24T14:41:02+00:00", "planned": False},
    "D_R w+m_9 (rta)": {"at": "2026-09-24T14:41:03+00:00", "planned": False},
    "D_R w+m_9 (rta) inv": {"at": "2026-09-24T14:41:03+00:00", "planned": False},
}
_CAP_010_TITLE = "D_L_7 (rta) m-L: lev=-4.5, PK=-2"


def test_a_title_the_grammar_refuses_sorts_by_its_method_tag_not_its_last_word():
    groups = measurement_view.groups_from_titles([*_CAP_013_TAKEN, _CAP_010_TITLE])

    assert [g["method"] for g in groups] == ["rta"]
    assert groups[0]["names"] == [*_CAP_013_TAKEN, _CAP_010_TITLE]


def test_a_past_round_puts_its_unplanned_rta_captures_under_rta():
    """`cap_013` as the project holds it: two asked for, four captured though nobody asked
    (`planned: false`). The two `… (rta) inv` were the ones under SWEEP."""
    round_ = {"id": "cap_013", "n": 13, "phase": "2", "version": "12", "version_kind": "series",
              "expected": ["D_SW+Ws_9 (rta)", "D_ALL_9 (rta)"], "taken": _CAP_013_TAKEN,
              "skipped": {}, "closed": "2026-09-24T14:41:03+00:00"}

    session = measurement_view._session_for_round(round_, None)

    assert [g.method for g in session.groups] == ["rta"]
    assert [i.name for i in session.groups[0].items] == list(_CAP_013_TAKEN)


def test_an_open_round_puts_an_rta_with_a_note_under_rta(project):
    """`cap_010` while open: the round's own list, grouped by `groups_from_titles`. The names come
    back as typed: the method refuses the `D_` again since v3.0.66 (hub #232), so there is no one
    notation to bring them to (v3.0.65 brought them to `D-L`)."""
    process_view.process_dir(project).mkdir(parents=True, exist_ok=True)
    (process_view.process_dir(project) / "process-state.json").write_text(
        json.dumps({"schema_version": 1, "active_phase": "2", "plan": [],
                    "capture": {"id": "cap_010", "phase": "2", "version": "7",
                                "expected": [_CAP_010_TITLE, "D_L w+m_7 (rta) inv"],
                                "taken": {}}}),
        encoding="utf-8",
    )

    session = mv.build_session("2", 7, [], project)

    assert [g.method for g in session.groups] == ["rta"]
    assert _names(session) == [_CAP_010_TITLE, "D_L w+m_7 (rta) inv"]


@pytest.mark.parametrize("title", [
    *_CAP_013_TAKEN, _CAP_010_TITLE,
    "D_R_7 (sw) m-R: lev=-4.5, PK=-2",  # a sweep with a note stays a sweep
    "D_R_7 (sw) vs (rta)",  # the tag glued to `_N` is the method; a bracket in the note is not
    "D_ALL_9 (RTA)",  # the grammar lowercases the tag
    "D_w-L (imp) case35l",  # the one method with no `_N`
    # a tag glued to the word after it is not a tag to the grammar (tcc#123, W-4 review of #109)
    "D_L_7 (rta) x_8 (sw)y",
])
def test_the_fallback_reads_the_tag_where_the_grammar_would(title):
    """Mirrors the method rather than guessing: the same title without its `D_` is one the grammar
    reads, and both land in the same column."""
    naming = vendor_loader.load_naming()
    method = naming.parse_name(title.removeprefix("D_"))["method"]

    groups = measurement_view.groups_from_titles([title])

    assert [(g["method"], g["names"]) for g in groups] == [(method, [title])]


@pytest.mark.parametrize("title", ["Baseline solo", "D_L_7 m-L: lev=-4.5", "D_L_7 (x0) note"])
def test_a_title_with_no_method_tag_keeps_the_sweep_default(title):
    groups = measurement_view.groups_from_titles([title])

    assert [g["method"] for g in groups] == ["sw"]


def test_every_method_the_grammar_knows_heads_its_column_with_a_name():
    """tcc#122 (W-4's review of #109): `(imp)` had no entry beside «sweep (sw)» and «MMM RTA
    (rta)», so its column was headed with the bare tag, «imp». Every method `naming` knows has
    its name before its tag."""
    naming = vendor_loader.load_naming()
    for method in naming.METHODS:
        title = "w-L (imp)" if method == "imp" else f"w-L_1 ({method})"
        [group] = measurement_view.groups_from_titles([title])
        label = group["label"]
        assert label.endswith(f" ({method})") and label != f" ({method})", (method, label)


def test_an_open_round_shows_an_unplanned_take_the_grammar_cannot_read(project):
    """tcc#122 (W-4's review of #109): an open round lists what it asks for, and REW's extras
    where the grammar reads them; a take captured though nobody asked, with a title the grammar
    refuses — `D_` before the code (S-042, and again since the method's v3.0.66, hub #232) — was
    on neither list and never showed until the round closed. It shows among the extras, as typed,
    marked unread for the panel to say «не розібрано»; one the grammar reads is not marked."""
    process_view.process_dir(project).mkdir(parents=True, exist_ok=True)
    (process_view.process_dir(project) / "process-state.json").write_text(
        json.dumps({"schema_version": 1, "active_phase": "2", "plan": [],
                    "capture": {"id": "cap_010", "phase": "2", "version": "7",
                                "expected": ["w-L_7 (rta)"],
                                "taken": {"w-L_7 (rta)": {"planned": True},
                                          "D_L w+m_7 (rta) inv": {"planned": False}}}}),
        encoding="utf-8",
    )

    session = mv.build_session("2", 7, ["w-R_7 (rta)"], project)

    items = {i.name: i for g in session.groups for i in g.items}
    unread = items.get("D_L w+m_7 (rta) inv")
    assert unread is not None, _names(session)
    assert unread.additional and unread.unread, unread
    assert unread.status == mv.STATUS_DONE, "the round took it in"
    assert not items["w-R_7 (rta)"].unread, "REW's extra the grammar reads is not marked"
    assert not items["w-L_7 (rta)"].unread


def test_a_round_is_linked_to_the_steps_whose_evidence_names_its_captures(tmp_path):
    """No field records that link — but SCR-035 makes every closed step cite something real, and a
    capture is cited by its REW title."""
    _journal(tmp_path, _round_events())
    state = {"plan": [
        {"id": "m0-w-L", "evidence": ["w-L_01 (sw) captured and verified"]},
        {"id": "lang", "evidence": ["autosound_context.md"]},
    ]}

    session = measurement_view._session_for_round(
        process_view.capture_rounds(tmp_path)[0], state
    )

    assert session.used_in_steps == ("m0-w-L",)


def test_a_phase_whose_plan_captures_nothing_still_shows_a_round_the_session_opened(project):
    """The skill's `_CAPTURE_PLAN["1"]` is literally `[]`, and `build_session` used to return on
    that before ever looking at the record. A round is a fact; a phase plan is a prediction about
    one, and the fact has to win."""
    (project / "process").mkdir(exist_ok=True)
    (project / "process" / "process-state.json").write_text(
        json.dumps({
            "schema_version": 1,
            "active_phase": "1",
            "plan": [],
            "capture": {"id": "cap_002", "phase": "1", "version": "v_004",
                        "expected": ["w-L_04 (sw)", "w-R_04 (sw)"],
                        "taken": {"w-L_04 (sw)": {"planned": True}}},
        }),
        encoding="utf-8",
    )

    session = mv.build_session("1", 4, ["w-L_04 (sw)"], project)

    # In the derived spelling, as every other row (tcc#60).
    assert _names(session) == ["w-L_4 (sw)", "w-R_4 (sw)"]
    assert session.id == "cap_002"


def test_a_phase_that_really_captures_nothing_still_says_so(project):
    session = mv.build_session("1", 4, [], project)

    assert session.groups == ()
    assert "no capture" in session.version["en"]


def test_the_round_says_what_was_in_each_channel_chain(project):
    """The record is per channel and per pass, and until now nothing rendered it: a capture taken
    behind a protective high-pass looked exactly like one taken clean (tcc#15)."""
    process = _round(project, expected=["w-L_1 (sw)", "w-R_1 (sw)"])
    process.set_protective("w-L", {"hp": {"f": 100, "type": "LR", "slope": 24}})

    session = mv.build_session("0", 1, ["w-L_1 (sw)"], project, taken=["w-L_1 (sw)"])
    by_name = {item.name: item for group in session.groups for item in group.items}

    assert by_name["w-L_1 (sw)"].protective == "HP 100 LR24"
    assert by_name["w-R_1 (sw)"].protective == "", "a channel nobody recorded says nothing"


def test_off_reads_the_same_as_nothing_recorded(project):
    """Two states, not three (2026-09-06): both mean "read the curve as measured"."""
    process = _round(project, expected=["w-L_1 (sw)"])
    process.set_protective("w-L", "OFF")

    session = mv.build_session("0", 1, ["w-L_1 (sw)"], project, taken=["w-L_1 (sw)"])
    by_name = {item.name: item for group in session.groups for item in group.items}

    assert by_name["w-L_1 (sw)"].protective == ""


def test_a_round_that_closed_did_not_un_take_its_measurements(project):
    """Watched on the live project (`testTCC8`, 2026-09-06): `cap_002` held fourteen captures,
    every one verified `ok`, the round was closed — and the checklist above it said "waiting" for
    all fourteen. Two causes, both here: only the OPEN round was consulted, and the comparison was
    raw strings, so the round's `tw-L_01 (sw)` never met the checklist's `tw-L_1 (sw)`."""
    process = _round(project, version=1, expected=["w-L_01 (sw)", "w-R_01 (sw)"],
                     taken=["w-L_01 (sw)"])
    process.close_capture("зроблено")

    # Since finding 57 the closed round's results are on ITS OWN entry, not the next round's.
    past = mv.build_sessions("0", 1, [], project, taken=[])[1]
    statuses = {item.name: item.status for g in past.groups for item in g.items}

    assert statuses["w-L_01 (sw)"] == mv.STATUS_DONE, "the record says it was taken"
    assert statuses["w-R_01 (sw)"] != mv.STATUS_DONE, "and the one nobody took is not done"


def test_the_round_fixture_writes_titles_the_way_a_person_types_them(project):
    """The fixture's own promise, pinned. A tidy-up that writes `sw_1 (sw)` into the round would
    leave every test in this file passing for the wrong reason — which is exactly the state it was
    in until 2026-09-06."""
    process = _round(project, version=1,
                     expected=["sw_1 (sw)", "w-L_1 (sw)"], taken=["sw_1 (sw)"],
                     skipped={"w-L_1 (sw)": "саб відключений"})

    round_ = process.load()["capture"]

    assert round_["expected"] == ["sw_01 (sw)", "w-L_01 (sw)"]
    assert list(round_["taken"]) == ["sw_01 (sw)"]
    assert list(round_["skipped"]) == ["w-L_01 (sw)"]

    # ...and the checklist, which derives the unpadded name, still reads all three facts.
    session = mv.build_session("0", 1, [], project, taken=[])
    statuses = {item.name: item.status for g in session.groups for item in g.items}
    assert statuses["sw_1 (sw)"] == mv.STATUS_DONE
    assert statuses["w-L_1 (sw)"] == mv.STATUS_SKIPPED


def test_a_new_round_does_not_inherit_what_an_earlier_round_took(project):
    """tcc#39 (and #38), on a live project 2026-09-14: `cap_002` closed with fourteen taken, a new
    round opened expecting the same fourteen — and read fourteen `done` before anything was taken,
    so the import window said the round expected nothing and offered no names, and the round list
    painted an empty pass green. A round that asks for a capture asks for it AGAIN: what an earlier
    pass took is history, not this pass's progress. The import store is history too — it holds the
    earlier pass's titles, and the window hands them in as `taken`."""
    process = _round(project, version=1, expected=["w-L_1 (sw)", "w-R_1 (sw)", "sw_1 (sw)"],
                     taken=["w-L_1 (sw)", "w-R_1 (sw)", "sw_1 (sw)"])
    process.close_capture("done")
    process.start_capture(1, expected=[_as_typed("w-L_1 (sw)"), _as_typed("w-R_1 (sw)")])
    store = [_as_typed("w-L_1 (sw)"), _as_typed("w-R_1 (sw)"), _as_typed("sw_1 (sw)")]

    session = mv.build_session("0", 1, [], project, taken=store)
    statuses = {item.name: item.status for g in session.groups for item in g.items}

    assert statuses["w-L_1 (sw)"] == mv.STATUS_WAIT, "asked for again, not taken again yet"
    assert statuses["w-R_1 (sw)"] == mv.STATUS_WAIT
    assert "sw_1 (sw)" not in statuses, "not asked for by this pass: not on its list (finding 64)"

    process.record_capture(_as_typed("w-L_1 (sw)"))

    session = mv.build_session("0", 1, [], project, taken=store)
    statuses = {item.name: item.status for g in session.groups for item in g.items}
    assert statuses["w-L_1 (sw)"] == mv.STATUS_DONE, "taken in this pass"
    assert statuses["w-R_1 (sw)"] == mv.STATUS_WAIT


def test_a_capture_the_open_round_asks_for_again_is_blue_while_rew_holds_it(project):
    process = _round(project, version=1, expected=["w-L_1 (sw)"], taken=["w-L_1 (sw)"])
    process.close_capture("done")
    process.start_capture(1, expected=[_as_typed("w-L_1 (sw)")])

    session = mv.build_session("0", 1, ["w-L_01 (sw)"], project, taken=[])
    statuses = {item.name: item.status for g in session.groups for item in g.items}

    assert statuses["w-L_1 (sw)"] == mv.STATUS_FOUND


def test_an_old_round_opened_with_the_ledger_version_counts_by_the_series_of_its_titles(project):
    """hub #153 C. A round opened as `capture-start v_001` holding `_49` titles was skipped for
    series 49, because only its `version` was compared, and its captures read as not taken. The
    ledger version and `_N` are different counters; the method finds a round by either."""
    process = _round(project, version="v_001", expected=["w-L_49 (sw)"], taken=["w-L_49 (sw)"])
    process.close_capture("done")
    # A later round open, so the old one reaches the checklist only as a past round. `v_002` is
    # BANKED first: since method `v3.0.59` a `v_NNN` round whose snapshot is not on disk is
    # refused (TCC-022, which TCC asked for), and this test is deliberately about a round opened
    # at a LEDGER version — so the honest fixture is one where that version exists.
    _bank_next_version(project)
    process.start_capture("v_002", expected=["w-R_49 (sw)"])

    # Not on the open round's list (finding 64), so it reaches the task as an extra REW holds —
    # green because the old round, found by the series of its titles, took it.
    session = mv.build_session("0", 49, ["w-L_49 (sw)"], project, taken=[])
    extras = {i.name: i.status for g in session.groups if g.type == "additional" for i in g.items}

    assert extras["w-L_49 (sw)"] == mv.STATUS_DONE


def test_the_series_is_read_by_the_grammar(project):
    """hub #153 A: one reader of a title. Padding is the grammar's business too."""
    assert mv.series_of(["Baseline solo", " w-L_07 (sw) "], project) == 7
    assert mv.series_of(["not a title"], project) is None


def test_the_highest_series_among_the_rounds(project):
    """The second round is `_2`, not `_3`: since method `v3.0.59` a project's series numbers are
    its OWN and consecutive, and a foreign one is refused unless `--origin` says where it came
    from (S-048). The jump to `_3` here was incidental — what is asserted is that the highest of
    several rounds is found, and `_2` says that as well as `_3` did."""
    process = _round(project, version=1, expected=["w-L_1 (sw)"], taken=["w-L_1 (sw)"])
    process.close_capture("done")
    process.start_capture(2, expected=[_as_typed("w-L_2 (sw)")])

    assert mv.highest_series(project) == 2


def test_an_rta_the_check_does_not_apply_to_is_taken_not_unusable(project):
    """hub #154 §1 (method v3.0.53, skill #29): the capture check keeps `applicable`, false for a
    non-swept capture. Reading `ok` alone put every RTA of a phase-0 round in "taken, unusable"."""
    from autosound_tcc.state import process_view

    module = vendor_loader.load_process()
    _intake.seed(project)
    process = module.Process(str(process_view.process_dir(project)))
    process.enter_phase("0")
    process.start_capture(1, expected=["sw_1 (rta)"], step="0.1")
    process.record_capture("sw_1 (rta)")
    state = process.load()
    state["capture"]["taken"]["sw_1 (rta)"]["verified"] = {
        "ok": False, "applicable": False, "exists": True}
    process._write(state)

    session = mv.build_session("0", 1, ["sw_1 (rta)"], project)

    item = next(i for g in session.groups for i in g.items if i.name == "sw_1 (rta)")
    assert item.status == mv.STATUS_DONE


def test_a_past_round_folds_not_applicable_captures_as_taken(tmp_path):
    """The journal's `capture_verified` lists an RTA under `not_applicable` now, and no longer under
    `bad` (hub #154 §1)."""
    events = _round_events()
    events[4] = {**events[4], "ok": ["w-L_01 (sw)"], "bad": [], "not_applicable": ["w-L_01 (rta)"]}
    _journal(tmp_path, events)

    round_ = process_view.capture_rounds(tmp_path)[0]
    assert round_["taken"]["w-L_01 (rta)"]["verified"] == {"ok": False, "applicable": False}

    session = measurement_view._session_for_round(round_, None)
    by_name = {i.name: i for g in session.groups for i in g.items}
    assert by_name["w-L_01 (rta)"].status == measurement_view.STATUS_DONE


def test_an_impedance_sweep_is_shown_with_whatever_series_is_on_screen(project):
    """`(imp)` is the one method with no `_N` (method v3.0.53, hub #153 D). The Arbiter, 2026-09-17:
    which series it belongs to does not matter — it sits with the series current when it is taken.
    Filtered by series like every other extra, it was on no checklist at all."""
    session = mv.build_session("0", 1, ["w-L (imp)"], project, taken=[])

    extras = [item for g in session.groups for item in g.items if item.additional]
    assert [item.name for item in extras] == ["w-L (imp)"]
    assert extras[0].status == mv.STATUS_FOUND, "in REW, not taken in yet"



def test_an_rta_the_check_does_not_apply_to_carries_no_explanation_on_its_row():
    """Finding 30: «this check does not apply…» trailed every RTA row, cut off."""
    round_ = {"id": "cap_001", "version": "1", "phase": "0", "expected": ["c_1 (rta)"],
              "taken": {"c_1 (rta)": {"verified": {"ok": False, "applicable": False,
                                                   "issues": ["this check does not apply to an RTA"]}}},
              "skipped": {}, "protective": {}}
    session = measurement_view._session_for_round(round_, None)
    item = session.groups[0].items[0]
    assert item.extra is None
    assert item.status == measurement_view.STATUS_DONE


# ---- an open round is the task; the next round is a new pass (findings 64, 57; tcc#60) ----------

def test_an_open_round_shows_its_own_list_not_the_phase_plan(project):
    """Finding 64: round `cap_016` was issued with six positions and the panel showed phase 2's
    plan — 24, in five columns. TCC read the plan first and the round only when the plan was
    empty. A round is a fact, a phase plan is a prediction about it."""
    _round(project, version=1, expected=["sw_1 (sw)", "w-L_1 (rta)"])

    session = mv.build_session("2", 1, [], project)

    assert sorted(_names(session)) == ["sw_1 (sw)", "w-L_1 (rta)"]


def test_an_open_round_s_own_groups_are_its_columns(project):
    """skill #83 (hub #205): the round stores `groups` (label, method, names) beside `expected`,
    and TCC draws those rather than grouping by itself."""
    process = _round(project, version=1, expected=["sw_1 (sw)", "w-L_1 (sw)"], pad=False)
    state_path = process_view.process_dir(project) / "process-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["capture"]["groups"] = [{"label": "Solo (sw)", "method": "sw", "names": ["sw_1 (sw)"]},
                      {"label": "Group (sw)", "method": "sw", "names": ["w-L_1 (sw)"]}]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    del process

    session = mv.build_session("2", 1, [], project)

    assert [g.type for g in session.groups] == ["Solo (sw)", "Group (sw)"]


def test_the_next_round_is_a_new_pass_not_the_last_one_s_results(project):
    """Finding 57: «next round ●» listed every capture of the round, all green «done», before
    anything was captured — the closed pass's takes credited the next one. They stay on that
    round's own entry in the picker."""
    process = _round(project, version=1, expected=["sw_1 (sw)"], taken=["sw_1 (sw)"])
    process.close_capture("session ended")

    session = mv.build_session("0", 1, [], project)

    statuses = {item.name: item.status for group in session.groups for item in group.items}
    assert statuses["sw_1 (sw)"] == mv.STATUS_WAIT


# ---- the card follows the import window's answer (finding 147, tcc#21) ------------------------

_TRUNCATED = "covers 20-1001 Hz, asked for 20-20000 — truncated"


def _as_is_round(project, uuid="u-sw"):
    """The Arbiter's VM case, 2026-10-03: `sw_7 (sw)` taken «as it is», `sw_7 (rta)` left on
    «Re-take». The round took the first, and the method's check judged it — its own verdict,
    pinned to the capture's uuid, which stays as the method wrote it."""
    from autosound_tcc.core import capture_import

    process = _round(project, version=7, expected=["sw_7 (sw)", "sw_7 (rta)"],
                     taken=["sw_7 (sw)"])
    sw = _as_typed("sw_7 (sw)")
    state = process.load()
    state["capture"]["taken"][sw]["verified"] = {
        "ok": False, "exists": True, "applicable": True, "uuid": uuid, "issues": [_TRUNCATED]}
    process._write(state)
    capture_import.record_imported([capture_import.Candidate(
        ordinal="1", title=sw, uuid="u-sw", date="", when=None, imported=False, as_is=True)],
        project_dir=project)
    return process, sw


def test_a_capture_taken_as_it_is_reads_done_and_the_methods_verdict_stays(project):
    """Finding 147: «чому (sw) не зелений?» The tuner answered for that capture in the import
    window; the card says what he chose. The method's verdict is its own and is not rewritten."""
    process, sw = _as_is_round(project)

    session = mv.build_session("0", 7, [sw, _as_typed("sw_7 (rta)")], project, taken=[sw])
    item = {i.name: i for g in session.groups for i in g.items}["sw_7 (sw)"]

    assert item.status == mv.STATUS_DONE
    assert item.as_is, "the card says why it is green: taken as it is"
    assert item.extra is None, "not the method's reasons trailing a green row"
    assert process.load()["capture"]["taken"][sw]["verified"]["ok"] is False


def test_a_retake_under_the_same_title_is_judged_on_its_own(project):
    """«Take it as it is» belongs to one capture, by its uuid: a re-take under the same title that
    the check calls unusable is red, whatever was answered for the capture before it."""
    _process, sw = _as_is_round(project, uuid="u-retaken")

    session = mv.build_session("0", 7, [sw], project, taken=[sw])
    item = {i.name: i for g in session.groups for i in g.items}["sw_7 (sw)"]

    assert item.status == mv.STATUS_STALE
    assert not item.as_is


def test_a_title_left_for_a_retake_waits_rather_than_reading_in_rew(project):
    """Finding 147: «чому (rta) не жовтий?» REW still holds the curve left for a re-take, and
    «in REW — import it» is exactly what the tuner just decided not to do. It waits, as a title
    nothing was captured for yet does."""
    _process, sw = _as_is_round(project)
    rta = _as_typed("sw_7 (rta)")

    session = mv.build_session("0", 7, [sw, rta], project, taken=[sw], retake=[rta])
    statuses = {i.name: i.status for g in session.groups for i in g.items}

    assert statuses["sw_7 (rta)"] == mv.STATUS_WAIT
    without = mv.build_session("0", 7, [sw, rta], project, taken=[sw])
    assert {i.name: i.status for g in without.groups for i in g.items}["sw_7 (rta)"] \
        == mv.STATUS_FOUND, "a curve nobody answered for is still blue"


def test_a_past_round_reads_a_capture_taken_as_it_is_as_done(project):
    """The same answer once the round has closed: history does not turn it red."""
    process, _sw = _as_is_round(project)
    process.close_capture("done")

    past = mv.build_sessions("0", 7, [], project, taken=[])[1]
    item = {i.name: i for g in past.groups for i in g.items}[_as_typed("sw_7 (sw)")]

    assert item.status == mv.STATUS_DONE
    assert item.as_is


def test_taken_as_it_is_is_said_only_on_a_row_that_reads_done(project):
    """Review of finding 147, M3: a capture taken as it is and then decided against — or made
    stale by a change — showed «взято як є» beside a grey or red dot. The words explain a green
    row; on any other row the row's own reason stands."""
    process, sw = _as_is_round(project)
    state = process.load()
    state["capture"]["skipped"][sw] = {"reason": "sub disconnected"}
    process._write(state)

    live = mv.build_session("0", 7, [sw], project, taken=[sw])
    item = {i.name: i for g in live.groups for i in g.items}["sw_7 (sw)"]
    assert (item.status, item.as_is) == (mv.STATUS_SKIPPED, False)

    past = mv._session_for_round({
        "id": "cap_001", "version": "7", "phase": "0", "expected": [sw],
        "taken": {sw: {"verified": process.load()["capture"]["taken"][sw]["verified"]}},
        "skipped": {sw: {"reason": "sub disconnected"}}, "protective": {}},
        None, mv.taken_as_is(project))
    item = past.groups[0].items[0]
    assert (item.status, item.as_is, item.extra) == (mv.STATUS_SKIPPED, False, "sub disconnected")


# ---- the card agrees with the import window until hub #247 (tcc#149) ---------------------------


def _methods_truncated_line(monkeypatch) -> str:
    """The method's own «covers … — truncated», as its real `verify.verdict` words it for a sub
    swept over 20-1001 Hz and judged over its default 20-20000 — REW faked at the method's edge.
    REW keeps no impulse for it, and says so as REW does (`_rew_fakes.no_impulse`)."""
    import math

    verify = vendor_loader.load_verify()
    freqs = [20.0 * 2 ** (i / 12) for i in range(int(math.log2(1001 / 20) * 12) + 1)]
    listing = {"1": {"title": "sw_7 (sw)", "uuid": "u-sw", "notes": "DELAY 6.1 ms"}}
    monkeypatch.setattr(verify._api, "get_fr",
                        lambda mid, smoothing=None: (freqs, [85.0 - i * 0.2 for i in range(len(freqs))],
                                                     None))
    monkeypatch.setattr(verify._api, "get_impulse_response",
                        _rew_fakes.no_impulse(verify._api, listing))
    issues = verify.verdict("sw_7 (sw)", measurements=listing)["issues"]
    assert len(issues) == 1 and "truncated" in issues[0], issues
    return issues[0]


def _own_range_round(project, monkeypatch, *, uuid="u-sw", also=None, checked="usable"):
    """A sub sweep the import window judged usable over its own range (tcc#148), taken in
    normally, and the method's own check judging it over 20-20000 Hz after the import: its verdict,
    pinned to the capture's uuid, as the method writes it."""
    from autosound_tcc.core import capture_import

    line = _methods_truncated_line(monkeypatch)
    process = _round(project, version=7, expected=["sw_7 (sw)"], taken=["sw_7 (sw)"])
    sw = _as_typed("sw_7 (sw)")
    state = process.load()
    state["capture"]["taken"][sw]["verified"] = {
        "ok": False, "exists": True, "applicable": True, "uuid": uuid,
        "issues": [line] + ([also] if also else [])}
    process._write(state)
    capture_import.record_imported([capture_import.Candidate(
        ordinal="1", title=sw, uuid="u-sw", date="", when=None, imported=False, checked=checked)],
        project_dir=project)
    return process, sw, line


def _item(session, name):
    return {i.name: i for g in session.groups for i in g.items}[name]


def test_a_sweep_the_window_judged_over_its_own_range_is_not_red_on_the_card(project, monkeypatch):
    """tcc#149 (the W-7 review of #148, I2): the window passed a sub swept over 20-1001 Hz; the
    method's own check, over 20-20000 Hz, called it «truncated» and the card painted it red. Until
    the method reads the sweep's range (hub #247), a verdict failing for that line alone, on a
    capture the window judged usable over its own range, is done on the card — said so, with the
    method's verdict left as the method wrote it."""
    process, sw, _line = _own_range_round(project, monkeypatch)

    item = _item(mv.build_session("0", 7, [sw], project, taken=[sw]), "sw_7 (sw)")

    assert item.status == mv.STATUS_DONE
    assert item.own_range, "the row says why: usable over its own range, until hub #247"
    assert item.extra is None and not item.as_is
    assert process.load()["capture"]["taken"][sw]["verified"]["ok"] is False


@pytest.mark.parametrize("case", [{"uuid": "u-retaken"}, {"checked": ""},
                                  {"also": "in-band mean -96.1 dB — silence, not a sweep"}])
def test_a_capture_the_window_did_not_pass_stays_red_on_the_card(project, monkeypatch, case):
    """Only what the window passed, by the uuid the method's verdict pins: a re-take under the
    same title is another capture; a capture the window had nothing to say about is the method's;
    a verdict with anything beside «truncated» is the method's too."""
    _process, sw, _line = _own_range_round(project, monkeypatch, **case)

    item = _item(mv.build_session("0", 7, [sw], project, taken=[sw]), "sw_7 (sw)")

    assert (item.status, item.own_range) == (mv.STATUS_STALE, False), case


def test_a_past_round_reads_the_window_s_verdict_the_same_way(project, monkeypatch):
    process, _sw, _line = _own_range_round(project, monkeypatch)
    process.close_capture("done")

    item = _item(mv.build_sessions("0", 7, [], project, taken=[])[1], _as_typed("sw_7 (sw)"))

    assert (item.status, item.own_range) == (mv.STATUS_DONE, True)


def test_a_capture_the_window_flagged_for_its_kind_reads_as_in_the_window(project):
    """tcc#149: a sweep titled `(rta)` — fine by the method, which reads no titles — and an RTA
    titled `(sw)` — which the method does not judge at all — were red in the window and taken
    there «as it is». The card says the same, not a plain green."""
    from autosound_tcc.core import capture_import

    process = _round(project, version=7, expected=["sw_7 (rta)", "w-L_7 (sw)"],
                     taken=["sw_7 (rta)", "w-L_7 (sw)"])
    rta, wl = _as_typed("sw_7 (rta)"), _as_typed("w-L_7 (sw)")
    state = process.load()
    state["capture"]["taken"][rta]["verified"] = {
        "ok": True, "exists": True, "applicable": True, "uuid": "u-rta", "issues": []}
    state["capture"]["taken"][wl]["verified"] = {
        "ok": False, "exists": True, "applicable": False, "uuid": "u-wl",
        "issues": ["this check is for swept captures; REW says this one is rta — nothing here "
                   "was checked"]}
    process._write(state)
    capture_import.record_imported([
        capture_import.Candidate(ordinal="1", title=rta, uuid="u-rta", date="", when=None,
                                 imported=False, as_is=True, checked="sweep_named_rta"),
        capture_import.Candidate(ordinal="2", title=wl, uuid="u-wl", date="", when=None,
                                 imported=False, as_is=True, checked="rta_named_sweep")],
        project_dir=project)

    session = mv.build_session("0", 7, [rta, wl], project, taken=[rta, wl])

    for name in ("sw_7 (rta)", "w-L_7 (sw)"):
        item = _item(session, name)
        assert (item.status, item.as_is) == (mv.STATUS_DONE, True), name


def test_a_capture_the_window_flagged_for_its_driver_reads_as_in_the_window(project):
    """tcc#149, the review's m4: a tweeter title whose sweep peaks in a sub's range was red in the window
    and taken there «as it is»; the method, which reads no titles, passes it. The card says what
    the window said, as for a title of the wrong kind."""
    from autosound_tcc.core import capture_import

    process = _round(project, version=7, expected=["tw-L_7 (sw)"], taken=["tw-L_7 (sw)"])
    tw = _as_typed("tw-L_7 (sw)")
    state = process.load()
    state["capture"]["taken"][tw]["verified"] = {
        "ok": True, "exists": True, "applicable": True, "uuid": "u-tw", "issues": []}
    process._write(state)
    capture_import.record_imported([capture_import.Candidate(
        ordinal="1", title=tw, uuid="u-tw", date="", when=None, imported=False, as_is=True,
        checked="tweeter_plays_low")], project_dir=project)

    item = _item(mv.build_session("0", 7, [tw], project, taken=[tw]), "tw-L_7 (sw)")

    assert (item.status, item.as_is) == (mv.STATUS_DONE, True)


# ---- a superseded capture is not done (#175, F6 N16) ------------------------------------------
# Parity with the method: what a round still waits for is the method's own list — the open round's
# `capture_outstanding()`, a closed round's closing event. Compared by `name_key`, because the rows
# are the derived names and the round holds titles as typed. No `optional` titles in these rounds:
# TCC does not read them, and the method leaves them out of `outstanding`.


def _key(project):
    naming = vendor_loader.load_naming()
    glossary = naming.Glossary.for_project(str(project))

    def key(title):
        entry = naming.parse_name(str(title), glossary)
        return naming.name_key(entry) if entry else str(title)

    return key


def _rows(session, key, *statuses) -> set:
    return {key(i.name) for g in session.groups for i in g.items
            if i.status in statuses and not i.additional}


def _closing(process, rid: str) -> dict:
    """The method's own closing event for round `rid`, read from its journal."""
    return [e for e in process.events() if e.get("type") == "capture_round_closed"
            and e.get("capture") == rid][-1]


def _past(project, rid: str):
    return next(s for s in mv.build_sessions("0", 1, [], project, taken=[]) if s.id == rid)


def _folded(project, rid: str) -> dict:
    return next(r for r in process_view.capture_rounds(project) if r["id"] == rid)


class _Silent:
    """The method's `verify.verify` for a check that heard silence under every title: held by
    REW, judged unusable, pinned to a uuid — what `Process.check_captures` records."""

    def verify(self, wanted):
        return [{"name": title, "valid": False, "exists": True, "applicable": True,
                 "reachable": True, "stats": {"uuid": f"u-{index}"},
                 "issues": ["in-band mean -94.0 dB — silence, not a sweep"]}
                for index, title in enumerate(wanted)]


_THREE = ["w-L_1 (sw)", "w-R_1 (sw)", "sw_1 (sw)"]


def test_the_open_round_waits_for_what_the_method_waits_for_after_a_supersede(project):
    """#175, F6 (the issue's first): `w-R_1` taken, then superseded — the sweep under that title
    was the left driver. The method asks for `w-R_1` again (`capture_outstanding()`); the card
    showed it green, because no reader in TCC knew `superseded_by`. The rows the card waits on are
    the method's list."""
    process = _round(project, version=1, expected=_THREE, taken=["w-R_1 (sw)"],
                     superseded={"w-R_1 (sw)": "w-L_1 (sw)"})
    key = _key(project)
    outstanding = process.capture_outstanding()
    assert outstanding == [_as_typed("w-R_1 (sw)"), _as_typed("sw_1 (sw)")], outstanding

    session = mv.build_session("0", 1, [], project, taken=[])

    assert _rows(session, key, mv.STATUS_WAIT, mv.STATUS_FOUND) == {key(t) for t in outstanding}
    assert _item(session, "w-L_1 (sw)").status == mv.STATUS_DONE, "the corrected title is taken"


@pytest.mark.parametrize("pad", [False, True], ids=["by-raw-title", "by-key"])
def test_a_same_key_supersede_never_colours_the_corrected_row(project, pad):
    """#175 (`measurement_view.py:465-471`): `w-R_1 (sw)` taken, then a second sweep typed
    `w_R_1 (sw)` — the older notation, the same `name_key` — judged silent by the check, then
    superseded by `w-R_1 (sw)`. The verdicts were built over every row, and the one by key is the
    last row of that key: the superseded one, so the corrected row came up red with a typo's
    verdict. Looked up by the raw title (the tidy spelling) and by key (as typed), live and once
    the round is history, where the superseded row was a red row of its own."""
    typed = _as_typed if pad else str
    process = _round(project, version=1, expected=["w-R_1 (sw)"],
                     taken=["w-R_1 (sw)", "w_R_1 (sw)"], pad=pad)
    process.check_captures([typed("w_R_1 (sw)")], verifier=_Silent())
    process.supersede_capture(typed("w_R_1 (sw)"), typed("w-R_1 (sw)"), "typed with an underscore")
    assert process.capture_outstanding() == []

    live = _item(mv.build_session("0", 1, [], project, taken=[]), "w-R_1 (sw)")
    assert (live.status, live.extra) == (mv.STATUS_DONE, None)

    process.start_capture(1, expected=[typed("sw_1 (sw)")])  # closes cap_001: history now
    past = _past(project, "cap_001")
    assert {i.name: i.status for g in past.groups for i in g.items} == {
        typed("w-R_1 (sw)"): mv.STATUS_DONE}, "the typo's trace is no row, and nothing is red"


def test_an_older_round_after_a_supersede_waits_for_what_its_close_named(project):
    """#175: the last round is read from `process-state.json`, which carries `superseded_by`; an
    OLDER one only from the journal, whose fold had no `capture_superseded`. Two rounds, so the
    superseded one is history: its waiting rows are its closing event's `outstanding`, and the
    typo's row stays in the fold, marked, as the method keeps it."""
    process = _round(project, version=1, expected=_THREE, taken=["w-R_1 (sw)"],
                     superseded={"w-R_1 (sw)": "w-L_1 (sw)"})
    process.start_capture(1, expected=[_as_typed("w-L_1 (sw)")])  # closes cap_001 as superseded
    key = _key(project)
    closed = _closing(process, "cap_001")

    past = _past(project, "cap_001")

    assert _rows(past, key, mv.STATUS_WAIT, mv.STATUS_FOUND) == {key(t) for t in closed["outstanding"]}
    assert _rows(past, key, mv.STATUS_DONE) == {key("w-L_1 (sw)")}
    folded = _folded(project, "cap_001")
    assert folded["taken"][_as_typed("w-R_1 (sw)")]["superseded_by"] == _as_typed("w-L_1 (sw)")
    assert _as_typed("w-R_1 (sw)") not in process_view.standing(folded)


def test_an_older_round_after_a_skip_then_a_take_reads_taken(project):
    """#175, N16: a capture skipped and then taken after all — the method pops the skip when it
    takes (`record_capture`); the fold did not, so history kept the round's grey «skipped» over a
    capture it had."""
    process = _round(project, version=1, expected=_THREE, skipped={"w-R_1 (sw)": "rears later"})
    process.record_capture(_as_typed("w-R_1 (sw)"))  # taken after all
    process.start_capture(1, expected=[_as_typed("w-L_1 (sw)")])
    key = _key(project)
    closed = _closing(process, "cap_001")
    assert closed["skipped"] == []

    past = _past(project, "cap_001")

    assert _item(past, _as_typed("w-R_1 (sw)")).status == mv.STATUS_DONE
    assert _rows(past, key, mv.STATUS_SKIPPED) == set()
    assert _rows(past, key, mv.STATUS_WAIT, mv.STATUS_FOUND) == {key(t) for t in closed["outstanding"]}
    assert _folded(project, "cap_001")["skipped"] == {}


def test_an_older_round_reads_what_its_close_said_was_still_outstanding(project):
    """#175: the read against REW (`reconcile_captures`, which `capture-close` runs) takes what REW
    holds and takes back a skip with no `capture_taken` of its own, so a past round's lines never
    hear of it — only its closing event does. Its `outstanding` and `skipped` are the round's truth:
    what neither names nor skips was taken. Its `taken` is not read (N17)."""
    process = _round(project, version=1, expected=_THREE, skipped={"sw_1 (sw)": "sub later"})
    process.reconcile_captures([_as_typed("w-L_1 (sw)"), _as_typed("sw_1 (sw)")])
    process.start_capture(1, expected=[_as_typed("w-R_1 (sw)")])
    key = _key(project)
    closed = _closing(process, "cap_001")
    assert not [e for e in process.events() if e.get("type") == "capture_taken"], \
        "the round's takes are the read's, with no line of their own"
    assert closed["outstanding"] == [_as_typed("w-R_1 (sw)")] and closed["skipped"] == []

    past = _past(project, "cap_001")

    assert _rows(past, key, mv.STATUS_WAIT, mv.STATUS_FOUND) == {key(t) for t in closed["outstanding"]}
    assert _rows(past, key, mv.STATUS_DONE) == {key("w-L_1 (sw)"), key("sw_1 (sw)")}
    folded = _folded(project, "cap_001")
    assert folded["outstanding"] == closed["outstanding"]
    assert folded["skipped"] == {}


def _as_an_older_method_closed_it(project, rid: str, *keys: str) -> None:
    """Drop `keys` from round `rid`'s closing event in the journal the method wrote: the event as a
    method before those fields wrote it. Every other line stays as the method wrote it."""
    journal = process_view.journal_file(project)
    lines = journal.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        event = json.loads(line) if line.strip() else {}
        if event.get("type") == "capture_round_closed" and event.get("capture") == rid:
            lines[index] = json.dumps({k: v for k, v in event.items() if k not in keys}) + "\n"
    journal.write_text("".join(lines), encoding="utf-8")


def test_a_close_without_outstanding_leaves_the_round_as_its_lines_folded_it(project):
    """#175: a journal older than the closing event's `outstanding` is read by its lines — the
    supersede and the take after a skip — and the key's absence is not `[]`: read as an empty
    list, every capture the round asked for and nobody took would have read as taken."""
    process = _round(project, version=1, expected=_THREE + ["sw_1 (rta)"],
                     taken=["w-R_1 (sw)"], superseded={"w-R_1 (sw)": "w-L_1 (sw)"},
                     skipped={"sw_1 (sw)": "sub later"})
    process.record_capture(_as_typed("sw_1 (sw)"))  # taken after all
    process.start_capture(1, expected=[_as_typed("w-L_1 (sw)")])
    key = _key(project)
    said = _closing(process, "cap_001")["outstanding"]
    _as_an_older_method_closed_it(project, "cap_001", "outstanding", "outstanding_optional",
                                  "skipped")

    past = _past(project, "cap_001")

    assert "outstanding" not in _folded(project, "cap_001")
    assert _rows(past, key, mv.STATUS_WAIT, mv.STATUS_FOUND) == {key(t) for t in said} == {
        key("w-R_1 (sw)"), key("sw_1 (rta)")}
    assert _rows(past, key, mv.STATUS_DONE) == {key("w-L_1 (sw)"), key("sw_1 (sw)")}


# ---- «settled» is decided once, from the recorded verdicts (#175, TA-8) ------------------------
# Three places decided whether a capture's verdict needs the Arbiter: the window's check loop, the
# strip's parse of the check's text, and the card. Each is `verdict_state` now, read off a round
# the method recorded: its own `check_captures`, with `verify` answered here instead of by REW.

_SILENCE = "in-band mean -94.0 dB — silence, not a sweep"
_NOT_SWEPT = "this check is for swept captures; REW says this one is rta — nothing here was checked"


class _Answers:
    """The method's `verify.verify`, answering each title what `answers` holds for it — so the
    method's own `Process.check_captures` records the verdict, pinned to the uuid given."""

    def __init__(self, answers: dict):
        self.answers = answers

    def verify(self, wanted):
        return [{"name": title, "reachable": True, "applicable": True, **self.answers[title]}
                for title in wanted]


def _held(uuid: str, *issues: str, applicable: bool = True) -> dict:
    """REW holds the curve, under `uuid`: fine with no issue, failing with any."""
    return {"valid": applicable and not issues, "exists": True, "applicable": applicable,
            "stats": {"uuid": uuid}, "issues": list(issues)}


def _not_held(title: str) -> dict:
    """REW holds nothing under `title`, in REW's own words (`rew_api.find_measurement_id`)."""
    return {"valid": False, "exists": False, "stats": {},
            "issues": [f"No measurement titled {title!r} (REW holds 3)"]}


def _check(process, answers: dict) -> dict:
    """The method checks `answers`' titles (as typed) and records the verdicts; the round after."""
    typed = {_as_typed(title): answer for title, answer in answers.items()}
    process.check_captures(list(typed), verifier=_Answers(typed))
    return process.load()["capture"]


def _state(project, round_: dict, title: str) -> str:
    typed = _as_typed(title)
    verdict = process_view.standing(round_)[typed].get("verified") or {}
    return mv.verdict_state(verdict, typed, mv.taken_as_is(project), mv.window_checked(project))


def _imported(project, title: str, uuid: str, **said) -> None:
    """The import window took `title` in, as REW's `uuid`: `as_is=True`, or what it `checked`."""
    from autosound_tcc.core import capture_import

    capture_import.record_imported([capture_import.Candidate(
        ordinal="1", title=_as_typed(title), uuid=uuid, date="", when=None, imported=False,
        **said)], project_dir=project)


def test_a_capture_that_passed_or_that_the_check_does_not_apply_to_is_fine(project):
    """hub #154 §1: an RTA's verdict is `ok: false, applicable: false` — not bad, not judged."""
    process = _round(project, version=7, expected=["w-L_7 (sw)", "sw_7 (rta)"],
                     taken=["w-L_7 (sw)", "sw_7 (rta)"])
    round_ = _check(process, {"w-L_7 (sw)": _held("u-wl"),
                              "sw_7 (rta)": _held("u-rta", _NOT_SWEPT, applicable=False)})

    assert _state(project, round_, "w-L_7 (sw)") == mv.VERDICT_FINE
    assert _state(project, round_, "sw_7 (rta)") == mv.VERDICT_FINE


def test_a_capture_taken_as_it_is_is_as_is_and_a_retake_under_its_title_is_bad(project):
    """Finding 147: the tuner answered for that verdict in the import window — by its uuid, so a
    re-take under the same title is another capture, judged on its own."""
    process = _round(project, version=7, expected=["sw_7 (sw)"], taken=["sw_7 (sw)"])
    _imported(project, "sw_7 (sw)", "u-sw", as_is=True)

    assert _state(project, _check(process, {"sw_7 (sw)": _held("u-sw", _TRUNCATED)}),
                  "sw_7 (sw)") == mv.VERDICT_AS_IS
    assert _state(project, _check(process, {"sw_7 (sw)": _held("u-retaken", _TRUNCATED)}),
                  "sw_7 (sw)") == mv.VERDICT_BAD


def test_a_sweep_the_window_passed_over_its_own_range_is_own_range_and_nothing_more(project):
    """tcc#149, until hub #247: «truncated» alone, on the uuid the window passed. Anything beside
    it is the method's verdict, and so is a re-take."""
    process = _round(project, version=7, expected=["sw_7 (sw)"], taken=["sw_7 (sw)"])
    _imported(project, "sw_7 (sw)", "u-sw", checked="usable")

    assert _state(project, _check(process, {"sw_7 (sw)": _held("u-sw", _TRUNCATED)}),
                  "sw_7 (sw)") == mv.VERDICT_OWN_RANGE
    assert _state(project, _check(process, {"sw_7 (sw)": _held("u-sw", _TRUNCATED, _SILENCE)}),
                  "sw_7 (sw)") == mv.VERDICT_BAD
    assert _state(project, _check(process, {"sw_7 (sw)": _held("u-retaken", _TRUNCATED)}),
                  "sw_7 (sw)") == mv.VERDICT_BAD


def test_a_curve_rew_does_not_hold_is_absent_not_bad(project):
    """The Arbiter, 2026-09-23: red is for a curve that is there and fails; one not there waits."""
    process = _round(project, version=7, expected=["w-R_7 (sw)"], taken=["w-R_7 (sw)"])
    round_ = _check(process, {"w-R_7 (sw)": _not_held(_as_typed("w-R_7 (sw)"))})

    assert _state(project, round_, "w-R_7 (sw)") == mv.VERDICT_ABSENT


def test_a_failing_capture_is_bad_and_so_is_one_never_checked(project):
    """A capture taken and never checked is not usable yet, as the method's own gate reads it
    (`unusable_captures`): `bad` too, so the window's check asks about it."""
    process = _round(project, version=7, expected=["w-L_7 (sw)", "w-R_7 (sw)"],
                     taken=["w-L_7 (sw)", "w-R_7 (sw)"])
    round_ = _check(process, {"w-L_7 (sw)": _held("u-wl", _SILENCE)})

    assert _state(project, round_, "w-L_7 (sw)") == mv.VERDICT_BAD
    assert "verified" not in round_["taken"][_as_typed("w-R_7 (sw)")]
    assert _state(project, round_, "w-R_7 (sw)") == mv.VERDICT_BAD


# The window's check loop: what it asks the method about (`to_check`).


def test_the_window_checks_only_what_the_round_took_and_rew_holds(project):
    """tcc#21, review I3: a title in REW's list is not this project taking it in (the Arbiter,
    2026-09-06) — checking whatever REW showed made a dud left for a re-take «брак — знятий» and a
    good sweep nobody ticked green. Only what the round took, and only while REW holds it."""
    three = [_as_typed(t) for t in ("m-L_1 (sw)", "m-R_1 (sw)", "sw_1 (sw)")]
    _round(project, version=1, expected=["m-L_1 (sw)", "m-R_1 (sw)", "sw_1 (sw)"],
           taken=["m-L_1 (sw)"])
    round_ = process_view.capture_round(project)

    assert mv.to_check(round_, three, project) == [_as_typed("m-L_1 (sw)")]
    assert mv.to_check(round_, three[1:], project) == []


def test_an_expected_title_in_rew_that_nobody_took_is_not_checked(project):
    _round(project, version=1, expected=["m-L_1 (sw)"])

    assert mv.to_check(process_view.capture_round(project), [_as_typed("m-L_1 (sw)")],
                       project) == []


def test_a_settled_capture_is_not_checked_again_and_one_that_is_not_is(project):
    """hub #154 §1: an RTA's verdict will not change, and treating it as unchecked started a check
    on every scan of REW. Nor will one taken as it is (finding 147), or one the window passed over
    its own range until hub #247 (tcc#149) — each a pull from REW and a journal event for nothing.
    A re-take under the same title is another uuid and is checked; so are a bad one and an absent
    one, whose curve may be there now."""
    titles = ["sw_7 (rta)", "sw_7 (sw)", "w-L_7 (sw)", "w-R_7 (sw)", "m-L_7 (sw)"]
    process = _round(project, version=7, expected=titles, taken=titles)
    _imported(project, "sw_7 (sw)", "u-sw", as_is=True)
    _imported(project, "w-L_7 (sw)", "u-wl", checked="usable")
    held = [_as_typed(t) for t in titles]
    answers = {"sw_7 (rta)": _held("u-rta", _NOT_SWEPT, applicable=False),
               "sw_7 (sw)": _held("u-sw", _TRUNCATED), "w-L_7 (sw)": _held("u-wl", _TRUNCATED),
               "w-R_7 (sw)": _held("u-wr", _SILENCE),
               "m-L_7 (sw)": _not_held(_as_typed("m-L_7 (sw)"))}

    assert mv.to_check(_check(process, answers), held, project) == [
        _as_typed("w-R_7 (sw)"), _as_typed("m-L_7 (sw)")]
    retaken = _check(process, {"sw_7 (sw)": _held("u-sw2", _TRUNCATED),
                               "w-L_7 (sw)": _held("u-wl2", _TRUNCATED)})
    assert mv.to_check(retaken, held, project) == [
        _as_typed("sw_7 (sw)"), _as_typed("w-L_7 (sw)"), _as_typed("w-R_7 (sw)"),
        _as_typed("m-L_7 (sw)")]


# The strip after a check that ran: a line for each recorded `bad` verdict (`unusable_lines`).


def test_the_strip_says_each_bad_capture_and_none_taken_as_it_is_held_or_absent(project):
    """Review of finding 147, I1: «1 unusable: sw_7 (sw) — … truncated» beside a row the card read
    green «taken as it is». tcc#149: the same for a sub the window had just passed over its own
    range. The Arbiter, 2026-09-23: a curve that is not there is waiting, not unusable. Another
    capture's failure still is a line — the method's issues, joined."""
    titles = ["sw_7 (sw)", "w-L_7 (sw)", "w-R_7 (sw)", "m-L_7 (sw)"]
    process = _round(project, version=7, expected=titles, taken=titles)
    _imported(project, "sw_7 (sw)", "u-sw", as_is=True)
    _imported(project, "w-L_7 (sw)", "u-wl", checked="usable")
    round_ = _check(process, {
        "sw_7 (sw)": _held("u-sw", _TRUNCATED), "w-L_7 (sw)": _held("u-wl", _TRUNCATED),
        "w-R_7 (sw)": _not_held(_as_typed("w-R_7 (sw)")),
        "m-L_7 (sw)": _held("u-ml", _TRUNCATED, _SILENCE)})

    assert mv.unusable_lines(round_, [_as_typed(t) for t in titles], project) == [
        f"{_as_typed('m-L_7 (sw)')} — {_TRUNCATED}; {_SILENCE}"]


def test_the_strip_names_only_the_titles_the_check_was_handed(project):
    """Review I5 (tcc#21): the method's text has a line for every expected title, and the strip
    once counted «w-R_1 (sw) — не перевірено» about captures nobody had taken. What the check was
    handed is what it answered — in the order handed — whatever an earlier check recorded."""
    titles = ["w-L_1 (sw)", "w-R_1 (sw)", "sw_1 (sw)"]
    process = _round(project, version=1, expected=titles, taken=titles)
    _check(process, {title: _held(f"u-{n}", _SILENCE) for n, title in enumerate(titles)})
    round_ = _check(process, {"sw_1 (sw)": _held("u-sw", _SILENCE),
                              "w-L_1 (sw)": _held("u-wl", _SILENCE)})

    assert mv.unusable_lines(round_, [_as_typed("sw_1 (sw)"), _as_typed("w-L_1 (sw)")],
                             project) == [f"{_as_typed('sw_1 (sw)')} — {_SILENCE}",
                                          f"{_as_typed('w-L_1 (sw)')} — {_SILENCE}"]


def test_a_title_the_check_recorded_nothing_for_is_never_said_bad(project):
    """Never «everything is bad»: a title the round holds no verdict for — a check that did not
    reach it — is no line, though it reads `bad` to the check loop."""
    process = _round(project, version=1, expected=["w-L_1 (sw)", "w-R_1 (sw)"],
                     taken=["w-L_1 (sw)", "w-R_1 (sw)"])

    assert mv.unusable_lines(process.load()["capture"], [_as_typed("w-L_1 (sw)"),
                                                         _as_typed("w-R_1 (sw)")], project) == []


# `verdict_state`'s fallback for a verdict that pins no uuid (the review of TA-8, M2).


def test_a_verdict_with_no_uuid_is_matched_as_is_by_its_title_or_the_cards_name_key(project):
    """With no uuid on the verdict — an older method's — «as it is» is matched by the capture's
    title; on the live card, whose rows are derived names (`sw_7 (sw)`) while the round, the
    import store and the verdict hold the title as typed (`sw_07 (sw)`), by its name key."""
    process = _round(project, version=7, expected=["sw_7 (sw)"], taken=["sw_7 (sw)"])
    _imported(project, "sw_7 (sw)", "u-sw", as_is=True)
    sw = _as_typed("sw_7 (sw)")
    verdict = _check(process, {"sw_7 (sw)": {**_held("u-sw", _SILENCE), "stats": {}}})[
        "taken"][sw]["verified"]
    assert verdict["uuid"] is None
    as_is, window, key = mv.taken_as_is(project), mv.window_checked(project), _key(project)

    assert mv.verdict_state(verdict, sw, as_is, window) == mv.VERDICT_AS_IS, "by its title"
    assert mv.verdict_state(verdict, "sw_7 (sw)", as_is, window) == mv.VERDICT_BAD
    assert mv.verdict_state(verdict, "sw_7 (sw)", as_is, window, key=key("sw_7 (sw)"),
                            keys={key(sw)}) == mv.VERDICT_AS_IS, "by the name key"
    item = _item(mv.build_session("0", 7, [sw], project, taken=[sw]), "sw_7 (sw)")
    assert (item.status, item.as_is) == (mv.STATUS_DONE, True), "the card matches by key"


def _ambiguous(title: str) -> dict:
    """REW holds `title` twice: `verify`'s verdict (H I-8) — there, unusable until renamed, and
    with no one curve's uuid to pin."""
    return {"valid": False, "exists": True, "stats": {}, "ambiguous": 2,
            "issues": [f"Ambiguous: 2 measurements titled {title!r} → ['3', '4']; rename so "
                       "titles are unique"]}


def test_an_ambiguous_verdict_is_bad_and_says_so_in_the_methods_words(project):
    process = _round(project, version=7, expected=["sw_7 (sw)"], taken=["sw_7 (sw)"])
    sw = _as_typed("sw_7 (sw)")
    round_ = _check(process, {"sw_7 (sw)": _ambiguous(sw)})

    assert round_["taken"][sw]["verified"]["uuid"] is None
    assert _state(project, round_, "sw_7 (sw)") == mv.VERDICT_BAD
    assert mv.unusable_lines(round_, [sw], project) == [
        f"{sw} — {_ambiguous(sw)['issues'][0]}"]


@pytest.mark.xfail(strict=True, reason="the uuid-less fallback reads an AMBIGUOUS verdict as the "
                   "tuner's «as it is» (the review of TA-8, M2); a follow-up")
def test_an_ambiguous_verdict_under_a_title_taken_as_it_is_is_still_bad(project):
    """By the method (v3.1.2, H I-8) a title REW holds twice is unusable until renamed:
    `capture-check` says `UNUSABLE … AMBIGUOUS`, `unusable_captures` counts it. Its verdict pins
    no uuid, so the title fallback takes the «as it is» answered for ONE curve under that title as
    an answer for this one: `as_is` — green on the card, no strip line, never checked again. Strict
    until the fallback leaves `ambiguous` verdicts out."""
    process = _round(project, version=7, expected=["sw_7 (sw)"], taken=["sw_7 (sw)"])
    _imported(project, "sw_7 (sw)", "u-sw", as_is=True)
    sw = _as_typed("sw_7 (sw)")

    assert _state(project, _check(process, {"sw_7 (sw)": _ambiguous(sw)}), "sw_7 (sw)") \
        == mv.VERDICT_BAD
