"""Reading the skill's process state into the plan panel's shapes (state/process_view.py, SCR-004).

TCC is a consumer here: the skill owns `process/process-state.json` and is its only writer. What's
worth pinning is the mapping — that a phase the project never entered still appears, that a
skipped step stays visible, and that "no process state yet" keeps the mock rather than rendering
an empty plan that looks like a finished one.
"""

from __future__ import annotations

import pytest

from autosound_tcc.core import vendor_loader
from autosound_tcc.state import process_view

from tests import _intake

pytestmark = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out"
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def process(project):
    """A real `Process` writing into the project, so the test exercises the actual file format.

    The target is recorded up front because the skill now refuses a forward move out of phase 0
    without one (SCR-036) — these tests jump straight to a mid-tune phase, which a real session
    only reaches through phase 0.

    The ledger snapshot exists for the same class of reason (SCR-035): a step cannot be closed
    against `v_003` unless `v_003` is on disk. Writing the file is what these tests were always
    claiming had happened.
    """
    snapshot = project / "state" / "FULL" / "v_003.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("{}", encoding="utf-8")
    module = vendor_loader.load_process()
    _intake.seed(project)  # the phase -1 gate is real: a fixture passes it like anyone else
    process = module.Process(str(process_view.process_dir(project)))
    _intake.open_phases(process)
    process.set_target("FULL", "EPY")
    return process


def test_no_process_state_reads_as_none_so_the_mock_stays(project):
    assert process_view.has_process_state(project) is False
    assert process_view.load_state(project) is None
    assert process_view.load_plan(project) is None


def test_every_phase_appears_even_the_ones_never_entered(process, project):
    process.enter_phase("2")

    plan = process_view.load_plan(project)

    assert len(plan) == 7  # the skill's -1..5 skeleton, not the mock's 0..6
    assert [p.status for p in plan] == ["todo", "todo", "todo", "cur", "todo", "todo", "todo"]
    assert sum(p.current for p in plan) == 1


def test_phase_titles_come_from_the_skill(process, project):
    process.enter_phase("2")

    plan = process_view.load_plan(project)
    current = next(p for p in plan if p.current)

    assert "EQ & acoustic alignment" in current.name["en"]
    assert current.name["uk"].startswith("Фаза 2")
    # The skeleton is the method's, the same in every project, so its titles are translated here
    # rather than written translated into the file -- where the intake's language would stick.
    assert "EQ та акустичне узгодження" in current.name["uk"]


def test_a_phase_title_someone_wrote_themselves_is_left_alone(process, project):
    """Only the skill's own skeleton has a translation. A title this version has not seen is
    somebody's decision, and inventing a translation for it would be inventing content."""
    process.enter_phase("2")
    state = process.load()
    state["phases"]["2"]["title"] = "EQ, but only above 300 Hz (see the notes)"
    process._write(state)

    current = next(p for p in process_view.load_plan(project) if p.current)

    assert current.name["uk"] == "Фаза 2 · EQ, but only above 300 Hz (see the notes)"


def test_steps_land_under_their_phase(process, project):
    process.enter_phase("1")
    process.add_step("1.1", "crossovers")
    process.enter_phase("2")
    process.add_step("2.1", "per-driver EQ")

    plan = process_view.load_plan(project)
    by_phase = {p.name["en"].split(" · ")[0]: p for p in plan}

    assert [s.id for s in by_phase["Phase 1"].steps] == ["1.1"]
    assert [s.id for s in by_phase["Phase 2"].steps] == ["2.1"]


def test_a_skipped_step_stays_visible_and_marked(process, project):
    """SCR-004: steps are never deleted -- a superseded one is dimmed, not gone."""
    process.enter_phase("2")
    process.add_step("2.3", "target-match")
    process.skip_step("2.3", superseded_by="2.4")

    plan = process_view.load_plan(project)
    step = next(s for p in plan for s in p.steps if s.id == "2.3")

    assert step.skip is True


def test_a_redone_step_reports_its_attempt(process, project):
    process.enter_phase("2")
    process.add_step("2.3", "target-match")
    process.start_attempt("2.3")
    process.finish_step("2.3", ["m-L_10 (rta)"])  # the method suffix is what makes it a capture
    process.start_attempt("2.3")  # redo

    step = next(s for p in process_view.load_plan(project) for s in p.steps if s.id == "2.3")

    assert step.attempt == 2


def test_status_becomes_the_chip_the_panel_already_styles(process, project):
    process.enter_phase("2")
    process.add_step("2.1", "a")
    process.add_step("2.2", "b")
    process.start_attempt("2.1")
    process.finish_step("2.2", ["v_003"])

    steps = {s.id: s for p in process_view.load_plan(project) for s in p.steps}

    assert steps["2.1"].tag_class == "wait"
    assert steps["2.2"].tag_class == "ok"


def test_a_situational_step_keeps_its_project_source(process, project):
    """The source is what lets the panel show which steps this car needed."""
    module = vendor_loader.load_process()
    process.enter_phase("1")
    process.add_step("1.4", "B-pillar rattle", source=module.SOURCE_PROJECT)

    step = next(s for p in process_view.load_plan(project) for s in p.steps if s.id == "1.4")

    assert step.source == "project"


def test_real_step_names_are_plain_strings_not_fake_translations(process, project):
    """`i18n.tx` passes plain strings through; wrapping them per-language would imply a
    translation that does not exist."""
    process.enter_phase("2")
    process.add_step("2.1", "per-driver EQ (v4.5)")

    step = next(s for p in process_view.load_plan(project) for s in p.steps if s.id == "2.1")

    # Since method v3.0.62 a step's name leads with its id (skill #72: one label in the text and on
    # the panel), and the panel shows the name alone, so the id is said once.
    assert step.name == "2.1 per-driver EQ (v4.5)"


def test_done_ids_and_reviewer_are_exposed_for_the_panel_and_footer(process, project):
    process.enter_phase("2")
    process.add_step("2.1", "a")
    process.finish_step("2.1", ["v_003"])
    process.record_reviewer("Gemini", "Gemini 3.1 Pro (High)", step="2.1")

    state = process_view.load_state(project)

    assert process_view.done_step_ids(state) == {"2.1"}
    assert process_view.reviewer(state)["model"] == "Gemini 3.1 Pro (High)"


def test_evidence_rule_is_the_skills_not_reimplemented_here(process):
    """The reader must not paper over a refusal the writer makes."""
    module = vendor_loader.load_process()
    process.enter_phase("2")
    process.add_step("2.1", "a")

    with pytest.raises(module.ProcessError, match="evidence"):
        process.finish_step("2.1", [])


# ---- SCR-014: what a config change invalidated ------------------------------


def _record_change(project, process, impact, what="driver swapped", why=None):
    """Log a `config_change` the way the skill does — through `project.py`, not by hand."""
    proj_module = vendor_loader.load_project()
    proj = proj_module.Project(str(project))
    proj.save(proj.load())  # the file has to exist for a change to be recorded against it
    return proj.record_change(process, "project.json", what, why=why, impact=impact)


def test_a_remeasure_change_flags_exactly_its_channels(project, process):
    """The SCR's whole promise: name the affected captures, never flag everything and never stay
    silent."""
    process.enter_phase("2")
    _record_change(project, process, "remeasure: [w-L, w-R]", why="blown voice coil")

    stale = process_view.stale_channels(project)

    assert set(stale) == {"w-L", "w-R"}
    assert stale["w-L"]["why"] == "blown voice coil"


def test_a_capture_recorded_after_the_change_clears_it(project, process):
    """"Stale" means the skill has recorded no capture since the change — so a later `step_done`
    whose evidence names the channel clears it, and one naming a different channel does not."""
    process.enter_phase("2")
    process.add_step("2.1", "sweep the fronts")
    _record_change(project, process, "remeasure: [w-L, w-R]")
    process.finish_step("2.1", ["w-L_10 (sw)"])

    stale = process_view.stale_channels(project)

    assert set(stale) == {"w-R"}


def _rename(project, was, now):
    """Rename a channel the way the skill does — `project.py`, not a hand-edited file."""
    proj_module = vendor_loader.load_project()
    proj = proj_module.Project(str(project))
    proj.set_channel(was, slot="C")
    proj.rename_channel(was, now)


def test_a_capture_under_the_old_name_clears_a_change_that_named_the_new_one(project, process):
    """SCR-039. The change says `wf-L` (what the session calls it) and the capture that answers it
    says `w-L` (what it was called when the title was typed). Matching those literally would leave
    a channel stale forever — no capture could ever clear it, because the title is not editable."""
    process.enter_phase("2")
    process.add_step("2.1", "sweep the fronts")
    _rename(project, "w-L", "wf-L")
    _record_change(project, process, "remeasure: [wf-L]")
    process.finish_step("2.1", ["w-L_10 (sw)"])

    assert process_view.stale_channels(project) == {}


def test_a_done_step_evidenced_under_the_old_name_is_still_re_chipped(project, process):
    """The same two names meeting in the plan panel instead of the checklist: a step closed with a
    capture taken before the rename must still go "recheck" when that channel is invalidated."""
    process.enter_phase("2")
    process.add_step("2.1", "sweep the fronts")
    process.finish_step("2.1", ["w-L_10 (sw)"])
    _rename(project, "w-L", "wf-L")
    _record_change(project, process, "remeasure: [wf-L]")

    stale = process_view.stale_channels(project)
    plan = process_view.to_plan(process_view.load_state(project), stale)
    step = next(s for phase in plan for s in phase.steps if s.id == "2.1")

    assert set(stale) == {"wf-L"}
    assert step.tag["en"] == "recheck", step


def _change_then_capture(project, process, codes, said, title):
    """A project whose channels are `codes` as written, a change naming `said`, then a step closed
    with the capture `title` -- what is still stale after it."""
    process.enter_phase("2")
    process.add_step("2.1", "sweep the fronts")
    proj = vendor_loader.load_project().Project(str(project))
    data = proj.load()
    data["channels"] = [{"code": code} for code in codes]  # as written, an older session's `_` too
    proj.save(data)
    _record_change(project, process, f"remeasure: [{said}]")
    process.finish_step("2.1", [title])
    return process_view.stale_channels(project)


@pytest.mark.parametrize("said, title", [
    ("w-L", "w-L_10 (sw)"),  # the change in the one notation, the capture too
    ("w_L", "w-L_10 (sw)"),  # the change as the project writes it, the capture renamed (S-079)
    ("w-L", "w_L_10 (sw)"),  # the capture as typed, read by the method as `w-L`
    ("w_L", "w_L_10 (sw)"),  # both as the project writes them
])
def test_a_channel_written_with_underscore_answers_to_both_notations(project, process, said, title):
    """#126: a channel `project.json` writes `w_L` answers to `w-L` too (`load_channels`, the
    method's one notation), so a change and the capture that answers it meet whichever of the two
    each was written in. The first case cleared before `w-L` had a channel behind it and must
    still clear now that it has one."""
    assert _change_then_capture(project, process, ["w_L", "tw_L"], said, title) == {}


@pytest.mark.parametrize("codes, said, title", [
    (["w-L", "w-L-x"], "w-L", "w-L-ctl1_3 (sw)"),  # the first control of a series is the channel's
    (["w-L"], "w-L", "w-L_3rep (sw)"),  # and so is its repeat
    (["w-L", "w-R"], "w-L", "w-L low_cut_3 (sw)"),  # a modifier after the code
    (["sw", "w-L"], "sw", "sw+w-L_3 (sw)"),  # a joint names each of its members
    (["sr-LH", "sr-L"], "sr-LH", "sr-LH_3 (rta)"),  # a variation of any length (the Arbiter, 2026-10-02)
    (["sw-r2", "sw"], "sw-r2", "sw-r2_3 (sw)"),
])
def test_a_capture_clears_its_own_channel_whatever_follows_the_code(project, process, codes, said,
                                                                     title):
    assert _change_then_capture(project, process, codes, said, title) == {}


@pytest.mark.parametrize("codes, said, title", [
    (["w_L", "tw_L"], "w_L", "tw-L_10 (sw)"),  # the tweeter's capture, renamed to the hyphen
    (["w_L", "tw_L"], "w-L", "tw_L_10 (sw)"),  # the tweeter's capture as typed
    (["w_L", "tw_L"], "w_L", "tw_L_10 (sw)"),
    (["w-L", "tw-L"], "w-L", "tw-L_10 (sw)"),  # the same, all in the one notation
    (["sw", "w-L"], "sw", "w-L_10 (sw)"),  # `(sw)` is the method, not the channel `sw`
    (["sr-LH", "xsr-LH"], "sr-LH", "xsr-LH_3 (rta)"),  # a longer driver type ending the same way
    (["sr-L", "sr-LH"], "sr-L", "sr-LH_3 (rta)"),  # a longer variation of the same driver
    (["sw", "sw-r2"], "sw", "sw-r2_3 (sw)"),  # a variation is another channel
])
def test_another_channels_capture_never_clears_a_change(project, process, codes, said, title):
    """#126's review, Important 1: the evidence was matched as a substring, so `w-L` was found in
    `tw-L_10 (sw)` and a tweeter-only step cleared a woofer swap without a word -- the silence
    SCR-014 exists to prevent. Since the one-notation names, also across spellings (`w_L` by
    `tw-L_10`). A name counts only as a whole code: a channel is `<driver type>-<its variation>`
    (the Arbiter, 2026-10-02), so a letter or digit on either side, or a `-` that starts another
    variation, makes it another channel's."""
    stale = _change_then_capture(project, process, codes, said, title)

    assert set(stale) == {said}, stale


def test_a_step_evidenced_by_another_channel_is_not_re_chipped(project, process):
    """The plan's half of the same match: a stale woofer does not put «recheck» on a step whose
    only capture is the tweeter's (`w-L` is in `tw-L_10 (sw)` as text, not as a code)."""
    process.enter_phase("2")
    process.add_step("2.1", "sweep the tweeter")
    process.add_step("2.2", "sweep the woofer")
    process.finish_step("2.1", ["tw-L_10 (sw)"])
    process.finish_step("2.2", ["w-L_10 (sw)"])
    _record_change(project, process, "remeasure: [w-L]")

    stale = process_view.stale_channels(project)
    plan = process_view.to_plan(process_view.load_state(project), stale)
    tags = {s.id: s.tag["en"] for phase in plan for s in phase.steps}

    assert set(stale) == {"w-L"}
    assert tags["2.2"] == "recheck" and tags["2.1"] != "recheck", tags


def test_a_capture_from_before_the_change_does_not_clear_it(project, process):
    process.enter_phase("2")
    process.add_step("2.1", "sweep the fronts")
    process.finish_step("2.1", ["w-L_10 (sw)"])
    _record_change(project, process, "remeasure: [w-L]")

    assert set(process_view.stale_channels(project)) == {"w-L"}


def test_full_rebaseline_flags_every_active_channel(project, process):
    """"Everything" is the glossary's active channels — the same list the capture checklist is
    built from, not a guess."""
    import json

    (project / "glossary.json").write_text(json.dumps({
        "channels": [{"code": "w-L", "active": True}, {"code": "w-R", "active": True},
                     {"code": "c", "active": False}],
    }), encoding="utf-8")
    process.enter_phase("2")
    _record_change(project, process, "full_rebaseline", what="mic recalibrated")

    stale = process_view.stale_channels(project)

    assert set(stale) == {"w-L", "w-R"}  # the inactive centre is not a capture anyone owes


def test_an_impact_the_parser_cannot_act_on_flags_nothing(project, process):
    """`voicing` (written by the skill's own set_target) and free prose are real impacts a human
    should read — but guessing which channels a sentence meant is how a checklist starts lying."""
    process.enter_phase("2")
    before = len(process_view.config_changes(project))
    _record_change(project, process, "voicing")
    _record_change(project, process, "check the sub once the amp is back")

    assert process_view.stale_channels(project) == {}
    # Counted as a delta: recording the target is itself a `voicing` change, so the fixture starts
    # with one. Both of these are still visible as events, which is the point.
    assert len(process_view.config_changes(project)) == before + 2


def test_no_journal_reads_as_nothing_stale(project):
    assert process_view.config_changes(project) == ()
    assert process_view.stale_channels(project) == {}


def test_a_done_step_whose_evidence_went_stale_is_re_chipped(project, process):
    """The step stays done in the file — the skill owns that — but the panel must not keep showing
    a green "ok" for work whose result no longer describes the car."""
    process.enter_phase("2")
    process.add_step("2.1", "sweep the fronts")
    process.finish_step("2.1", ["w-L_10 (sw)", "w-R_10 (sw)"])
    process.add_step("2.2", "set delays")
    process.finish_step("2.2", ["v_003"])
    _record_change(project, process, "remeasure: [w-L]")

    stale = process_view.stale_channels(project)
    plan = process_view.to_plan(process.load(), stale)
    steps = {s.id: s for phase in plan for s in phase.steps}

    assert steps["2.1"].tag_class == "wait" and steps["2.1"].tag["en"] == "recheck"
    assert steps["2.2"].tag["en"] == "ok"  # evidence is a ledger version, no channel involved


def test_without_the_stale_map_the_plan_is_unchanged(project, process):
    """`to_plan(state)` alone still works — the mock, the tests and any caller that doesn't care
    about staleness keep the old behaviour."""
    process.enter_phase("2")
    process.add_step("2.1", "sweep the fronts")
    process.finish_step("2.1", ["w-L_10 (sw)"])

    steps = {s.id: s for phase in process_view.to_plan(process.load()) for s in phase.steps}

    assert steps["2.1"].tag["en"] == "ok"


def test_a_round_carries_the_counter_it_named_and_whether_a_skip_was_planned(project):
    """Method `TCC-022` (hub #190) added two facts to the journal, and a reader that drops them
    puts the panel back to guessing.

    `version_kind` — `ledger` or `series` — is the round saying WHICH counter its `version` is.
    They are different counters and neither is derived from the other, so reading it off the
    spelling was always a guess; the method now records it instead.

    `planned` on a skip mirrors `record_capture`'s: `expected[]` is not a closed set, and a reader
    of a round cannot assume everything in `skipped` was ever asked for.

    Written as journal lines rather than through `Process`, on purpose: the checked-out method is
    still `v3.0.58` (the pin moves when the method tags), so the fixture cannot produce the new
    shape yet. What is pinned here is OUR mapping of a documented event, which is the thing this
    module owns.
    """
    import json

    journal = process_view.journal_file(project)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("\n".join(json.dumps(e) for e in [
        {"type": "capture_task_issued", "capture": "cap_001", "at": "t0", "phase": "0",
         "version": "_1", "version_kind": "series", "expected": ["w-L_1 (sw)"]},
        {"type": "capture_skipped", "capture": "cap_001", "at": "t1",
         "title": "r-R_1 (sw)", "reason": "rears not wired", "planned": False},
        {"type": "capture_skipped", "capture": "cap_001", "at": "t2",
         "title": "w-L_1 (sw)", "reason": "not today", "planned": True},
    ]) + "\n", encoding="utf-8")

    round_ = process_view.capture_rounds(project)[0]

    assert round_["version_kind"] == "series"
    assert round_["skipped"]["r-R_1 (sw)"]["planned"] is False
    assert round_["skipped"]["w-L_1 (sw)"]["planned"] is True
    # The reason is still there: the new field is carried BESIDE it, not instead of it.
    assert round_["skipped"]["r-R_1 (sw)"]["reason"] == "rears not wired"


def test_a_round_written_by_a_method_without_those_fields_still_reads(project):
    """The pin is `v3.0.58` until the method tags, and journals written before it never go back:
    absent is `None`, and a caller can tell that from `False` if it needs to."""
    import json

    journal = process_view.journal_file(project)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("\n".join(json.dumps(e) for e in [
        {"type": "capture_task_issued", "capture": "cap_001", "at": "t0", "phase": "0",
         "version": "v_001", "expected": ["w-L_1 (sw)"]},
        {"type": "capture_skipped", "capture": "cap_001", "at": "t1",
         "title": "w-L_1 (sw)", "reason": "not today"},
    ]) + "\n", encoding="utf-8")

    round_ = process_view.capture_rounds(project)[0]

    assert round_["version_kind"] is None
    assert round_["skipped"]["w-L_1 (sw)"] == {"reason": "not today", "planned": None}


def test_a_step_carries_the_facts_it_covers(project, process):
    """Method `SKL-047` (hub #189): a step says WHICH facts it closes, as dotted paths.

    The Arbiter read `Закрити відкриті поля: project.json (8) і dsp_profile.json (5)` and said it
    meant nothing to him — thirteen facts named nowhere he could see, in the one artefact he acts
    on. The names existed all along (`project.py open-questions`); the step had no field for them.

    Read-only here, and absent-tolerant: `covers` is written when the step is added, steps are
    never rewritten (SCR-004), and every step written before the field has none.
    """
    covers = ["project.json:sources.sweep_input", "dsp_profile.json:eq.bands_total"]
    state = {
        "active_phase": "-1",
        "phases": {},
        "plan": [
            {"id": "-1.2", "phase": "-1", "name": "Закрити відкриті поля: … +1",
             "status": "todo", "covers": covers},
            {"id": "-1.3", "phase": "-1", "name": "written before the field", "status": "todo"},
        ],
    }
    phases = {p.name["en"]: p for p in process_view.to_plan(state)}
    steps = {s.id: s for s in phases["Phase -1 · Intake"].steps} if \
        "Phase -1 · Intake" in phases else {
            s.id: s for phase in phases.values() for s in phase.steps}

    assert steps["-1.2"].covers == tuple(covers)
    assert steps["-1.3"].covers == ()


# ---- a close taken back (skill #107, hub #227) --------------------------------------------------


def test_a_close_taken_back_reads_as_an_open_session(project, process):
    """hub #227: a session reconciling state ran `session-close` to look, and it wrote the close.
    The method's `session-reopen <reason>` takes it back without erasing it: a `session_reopened`
    after the last `session_closed` means the session is open again — and a close after that is a
    close again. Read through the method's own reader, the one place it reads the close."""
    module = vendor_loader.load_process()

    process.record_session("sdk", "claude-opus-5")
    assert process_view.session_closed(project) is False
    process._append(module.EV_SESSION_CLOSED)  # what `session-close` writes on a clean stop
    assert process_view.session_closed(project) is True
    process.reopen_session("session-close was run as a check")
    assert process_view.session_closed(project) is False
    process._append(module.EV_SESSION_CLOSED)
    assert process_view.session_closed(project) is True


def test_no_journal_or_no_reader_has_no_opinion(project, process, monkeypatch, tmp_path):
    """None, not False: with no journal, or a method older than v3.0.65 (no reopening, no reader),
    the journal says nothing either way and the caller keeps what it knew."""
    module = vendor_loader.load_process()

    assert process_view.session_closed(tmp_path / "elsewhere") is None
    process._append(module.EV_SESSION_CLOSED)
    monkeypatch.delattr(module.Process, "session_closed")
    assert process_view.session_closed(project) is None
