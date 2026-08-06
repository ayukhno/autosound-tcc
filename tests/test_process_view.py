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
    """
    module = vendor_loader.load_process()
    process = module.Process(str(process_view.process_dir(project)))
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
    process.finish_step("2.3", ["m-L_10"])
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

    assert step.name == "per-driver EQ (v4.5)"


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
