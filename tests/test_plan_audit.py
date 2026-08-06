"""Does the plan agree with the disk? The "факт" half of ПЛАН — ФАКТ.

The case these exist for, watched end to end 2026-08-05: a free model closed four phases and
reported a finished tune — crossovers, delays, EQ, a listening verdict — with `dsp_profile.json`
alone on disk. Every step passed the skill's evidence gate, because the gate counts evidence and
cannot read it.
"""

from __future__ import annotations

import json

from autosound_tcc.state import plan_audit


def _state(*steps):
    return {"schema_version": 3, "plan": list(steps)}


def _step(id_, evidence, status="done", **extra):
    return {"id": id_, "name": id_, "phase": "0", "status": status, "evidence": evidence, **extra}


def test_prose_evidence_is_not_evidence(tmp_path):
    """"baseline measurements analysed" is a description of work, not a trace of it."""
    state = _state(_step("baseline", ["baseline measurements analysed"]))

    unbacked = plan_audit.unbacked_steps(state, tmp_path)

    assert [u.step_id for u in unbacked] == ["baseline"]


def test_a_named_file_that_exists_backs_the_step(tmp_path):
    (tmp_path / "dsp_profile.json").write_text("{}", encoding="utf-8")
    state = _state(_step("profile", ["dsp_profile.json (schema 3, contract-valid)"]))

    assert plan_audit.unbacked_steps(state, tmp_path) == ()


def test_a_named_file_that_does_not_exist_does_not(tmp_path):
    state = _state(_step("profile", ["dsp_profile.json (schema 3, contract-valid)"]))

    assert [u.step_id for u in plan_audit.unbacked_steps(state, tmp_path)] == ["profile"]


def test_a_ledger_version_backs_the_step_when_the_snapshot_is_there(tmp_path):
    preset = tmp_path / "state" / "FULL"
    preset.mkdir(parents=True)
    (preset / "v_007.json").write_text("{}", encoding="utf-8")
    state = _state(_step("xo", ["crossovers banked as v_007"]))

    assert plan_audit.unbacked_steps(state, tmp_path) == ()


def test_a_ledger_version_nobody_wrote_does_not(tmp_path):
    (tmp_path / "state").mkdir()
    state = _state(_step("xo", ["crossovers banked as v_007"]))

    assert [u.step_id for u in plan_audit.unbacked_steps(state, tmp_path)] == ["xo"]


def test_a_rew_title_backs_the_step(tmp_path):
    """REW is not talked to here — the titles come from the panel that already owns that worker."""
    state = _state(_step("capture", ["swept w-L_10 (sw) and w-R_10 (sw)"]))

    assert plan_audit.unbacked_steps(state, tmp_path, rew_titles=["w-L_10 (sw)"]) == ()


def test_steps_that_are_not_done_are_not_audited(tmp_path):
    state = _state(
        _step("a", [], status="todo"),
        _step("b", ["nothing real"], status="in_progress"),
        _step("c", ["nothing real"], status="done", skip=True),
    )

    assert plan_audit.unbacked_steps(state, tmp_path) == ()


def test_no_evidence_at_all_is_unbacked(tmp_path):
    """The skill refuses these, so one that exists came from around the gate."""
    state = _state(_step("x", []))

    assert [u.step_id for u in plan_audit.unbacked_steps(state, tmp_path)] == ["x"]


def test_the_whole_fabricated_tune_is_caught(tmp_path):
    """The observed case: a profile written, everything else narrated."""
    (tmp_path / "dsp_profile.json").write_text("{}", encoding="utf-8")
    state = _state(
        _step("dspprofile", ["dsp_profile.json (schema 3)"]),
        _step("baseline", ["baseline measurements analysed, polarity verified"]),
        _step("xo", ["crossovers set: LR 24 dB/oct across all four ways"]),
        _step("delays", ["delays aligned to the sub as 0 ms reference"]),
        _step("eq", ["EQ within ±0.5 dB in the passband"]),
    )

    unbacked = plan_audit.unbacked_steps(state, tmp_path)

    assert [u.step_id for u in unbacked] == ["baseline", "xo", "delays", "eq"]


# ---- the second rule: decisions that were never written down ----------------


def test_phase_zero_without_a_target_is_flagged():
    """Watched happening: the Arbiter named "EPY", the model repeated it back and wrote it into a
    free-text profile field, and `process-state.json` still read `"targets": {}`. The choice lived
    in the transcript, and a transcript does not survive `/clear`."""
    from autosound_tcc.state.plan_audit import missing_records

    found = missing_records({"active_phase": "0", "targets": {}})

    assert [record.what for record in found] == ["target curve"]


def test_a_recorded_target_is_not_flagged():
    from autosound_tcc.state.plan_audit import missing_records

    assert missing_records({"active_phase": "0", "targets": {"curve": "EPY"}}) == ()


def test_intake_is_not_expected_to_have_a_target_yet():
    """Phase −1 is where the car is described; the curve is chosen in phase 0."""
    from autosound_tcc.state.plan_audit import missing_records

    assert missing_records({"active_phase": "-1", "targets": {}}) == ()


def test_a_phase_that_does_not_parse_is_left_alone():
    from autosound_tcc.state.plan_audit import missing_records

    assert missing_records({"active_phase": None}) == ()
