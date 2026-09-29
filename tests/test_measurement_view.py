"""Deriving the capture task from glossary + REW (state/measurement_view.py, SCR-008).

The point of the module is that the series is *derived*, not hard-coded. What's worth pinning is
that the derivation respects the car: a disabled centre and absent rears must not appear as tasks,
because a checklist with impossible rows in it stops being read.
"""

from __future__ import annotations

import json
import re

import pytest

from autosound_tcc.core import vendor_loader
from autosound_tcc.state import measurement_view, process_view

from tests import _intake
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


def _as_typed(title: str) -> str:
    """A title the way a PERSON types it in REW: `sw_1 (sw)` -> `sw_01 (sw)`.

    Zero-padding is what REW titles carry in the field, and the checklist derives the unpadded
    form — `naming.name_key` exists precisely because those two are one name. A fixture that
    writes both sides in the same spelling cannot tell whether the code compares keys or strings.
    """
    return re.sub(r"_(\d)(?=\D|$)", r"_0\1", str(title))


def _round(project, **fields):
    """Write a capture round the way the skill would (SCR-034), through the skill's own writer.

    **The awkward shape is the default** (2026-09-06). Titles go in ZERO-PADDED, as typed in REW,
    while every assertion is written against the derived name — because that is the shape a real
    project has and the shape no fixture here had. It cost a regression that reached a tag's door:
    a closed pass holding fourteen verified captures read as fourteen rows still waiting, and
    every test passed, because every fixture wrote the round in the checklist's own spelling.

    `pad=False` for a fixture that is deliberately about the tidy case.
    """
    from autosound_tcc.state import process_view

    pad = fields.pop("pad", True)
    typed = _as_typed if pad else (lambda title: str(title))
    module = vendor_loader.load_process()
    _intake.seed(project)
    process = module.Process(str(process_view.process_dir(project)))
    process.enter_phase("0")
    process.start_capture(fields.pop("version", 1),
                          expected=[typed(t) for t in fields.pop("expected", ())])
    for title in fields.pop("taken", ()):
        process.record_capture(typed(title))
    for title, reason in (fields.pop("skipped", {}) or {}).items():
        process.skip_capture(typed(title), reason)
    return process


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
# (S-042: `_` only begins the series). Refused, the title fell to its last word and to SW.
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
    """`cap_010` while open: the round's own list, grouped by `groups_from_titles`."""
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
