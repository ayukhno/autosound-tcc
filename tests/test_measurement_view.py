"""Deriving the capture task from glossary + REW (state/measurement_view.py, SCR-008).

The point of the module is that the series is *derived*, not hard-coded. What's worth pinning is
that the derivation respects the car: a disabled centre and absent rears must not appear as tasks,
because a checklist with impossible rows in it stops being read.
"""

from __future__ import annotations

import json

import pytest

from autosound_tcc.core import vendor_loader
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


def test_zero_padded_versions_count_as_captured(project):
    """REW titles are hand-typed; `sw_01` and `sw_1` are the same DSP config version, and
    reporting the first as missing is the checker crying wolf."""
    session = mv.build_session("0", 1, ["sw_01 (sw)"], project)

    statuses = {item.name: item.status for g in session.groups for item in g.items}
    assert statuses["sw_1 (sw)"] == "done"


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

    assert "solo (sw)" in labels and "solo (rta)" in labels
    assert "pairs (rta)" in labels and "sides (rta)" in labels and "joints (rta)" in labels


def test_off_convention_titles_are_reported_separately(project):
    """No analysis will ever find these by name -- they're invisible, not merely uncaptured."""
    titles = ["sw_1 (sw)", "Room EQ result", "c_01 (sw) noXO"]

    assert mv.off_convention(titles, project) == ["Room EQ result", "c_01 (sw) noXO"]


def test_off_convention_is_empty_without_a_glossary(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))

    assert mv.off_convention(["anything"], tmp_path) == []


def _record_change(project, impact, what="driver swapped"):
    """A `config_change` written the way the skill writes it, through its own modules."""
    process_module = vendor_loader.load_process()
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
