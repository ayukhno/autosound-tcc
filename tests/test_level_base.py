"""The round on the method's level base: the card's line and the strip's news (`core/level_base.py`,
tcc#220, hub #285).

The method's `capture-check` writes `capture.level_base` into `process-state.json` (the skill's
#176/#177). TCC reads that field and nothing else for a copy that writes it: the method's numbers as
it gives them, no record of TCC's own, no REW listing, no arithmetic. Every round here is written and
checked by the method itself (`tests/_rounds.write_round` + `Process.check_captures` with a verifier
stub carrying REW's `splOffsetdB`); only the control's verdict, which needs REW's curves, is put into
the state the method wrote, in the shape its schema gives (`process-schema.md`).
"""

from __future__ import annotations

import json

import pytest

from autosound_tcc.core import level_base, vendor_loader
from autosound_tcc.state import process_view

from tests import _rounds

pytestmark = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out"
)

GLOSSARY = {
    "schema_version": 1,
    "channels": [{"code": code, "active": True} for code in ("sw", "w-L", "w-R")],
    "pairs": {"Ws": ["w-L", "w-R"]},
}


class Heard:
    """The method's `verify.verify` for good sweeps REW holds, each with REW's SPL calibration —
    `offsets[title]`, or one offset for every title; None is a capture REW lists no calibration
    for."""

    def __init__(self, offsets) -> None:
        self.offsets = offsets

    def verify(self, wanted):
        return [{"name": title, "valid": True, "exists": True, "applicable": True,
                 "reachable": True, "issues": [],
                 "stats": {"uuid": f"u-{title}",
                           "spl_offset_db": (self.offsets.get(title) if isinstance(self.offsets, dict)
                                             else self.offsets)}}
                for title in wanted]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    (tmp_path / "glossary.json").write_text(json.dumps(GLOSSARY), encoding="utf-8")
    return tmp_path


def checked(project, version, titles, offsets):
    """A round at `version` taking `titles`, checked by the method with REW's `offsets`."""
    process = _rounds.write_round(project, version=version, expected=titles, taken=titles,
                                  pad=False)
    process.check_captures(verifier=Heard(offsets))
    return process


def said(project):
    return level_base.notes(process_view.capture_round(project))


def note(key, round_id, **values):
    return level_base.Note(key, tuple(values.items()), round_id)


def test_a_round_not_checked_yet_says_nothing(project):
    _rounds.write_round(project, version=3, expected=["w-L_3 (sw)"], taken=["w-L_3 (sw)"],
                        pad=False)

    assert said(project) == []


def test_the_first_round_is_the_level_base_said_neutrally_and_not_news(project):
    checked(project, 3, ["w-L_3 (sw)"], 103.35)
    assert process_view.capture_round(project)["level_base"]["status"] == "no_base"

    notes = said(project)

    assert notes == [note(level_base.IS_BASE, "cap_001", offset="103.35")]
    assert level_base.news(notes) == []


def test_a_round_on_the_base_names_it_and_is_not_news(project):
    checked(project, 3, ["w-L_3 (sw)"], 103.35)
    checked(project, 4, ["w-L_4 (sw)"], 103.35)
    assert process_view.capture_round(project)["level_base"]["status"] == "ok"

    notes = said(project)

    assert notes == [note(level_base.ON_BASE, "cap_002", base="cap_001", offset="103.35")]
    assert level_base.news(notes) == []


def test_a_move_against_the_previous_round_is_said_with_the_shift_the_method_applies(project):
    """08.10: REW reset its calibration, 103.35 → 120.0. The method's `to_base_db` is +16.65, the
    shift it SUBTRACTS — so the levels are brought to the base by -16.65, as its own line says;
    the sign is the method's, never flipped by TCC."""
    checked(project, 3, ["w-L_3 (sw)"], 103.35)
    checked(project, 4, ["w-L_4 (sw)"], 120.0)
    lb = process_view.capture_round(project)["level_base"]
    assert (lb["status"], lb["titles"]["w-L_4 (sw)"]["to_base_db"]) == ("ok", 16.65)

    notes = said(project)

    moved = note(level_base.MOVED, "cap_002", delta="+16.65", previous="cap_001",
                 before="103.35", after="120.0", base="cap_001", shift="-16.65")
    assert notes == [moved]
    assert level_base.news(notes) == [moved]


def test_captures_that_disagree_inside_a_round_are_mixed_news(project):
    checked(project, 3, ["w-L_3 (sw)"], 103.35)
    checked(project, 4, ["w-L_4 (sw)", "w-R_4 (sw)"], {"w-L_4 (sw)": 120.0, "w-R_4 (sw)": 103.35})
    assert process_view.capture_round(project)["level_base"]["status"] == "mixed"

    notes = said(project)

    mixed = note(level_base.MIXED, "cap_002", jumps="w-L_4 (sw) +16.65 dB, w-R_4 (sw) +0.0 dB",
                 base="cap_001")
    assert notes == [mixed]
    assert level_base.news(notes) == [mixed]


def test_a_capture_rew_lists_no_calibration_for_is_missing_news(project):
    checked(project, 3, ["w-L_3 (sw)"], 103.35)
    checked(project, 4, ["w-L_4 (sw)", "w-R_4 (sw)"], {"w-L_4 (sw)": 103.35, "w-R_4 (sw)": None})
    assert process_view.capture_round(project)["level_base"]["status"] == "missing"

    notes = said(project)

    missing = note(level_base.MISSING, "cap_002", titles="w-R_4 (sw)", base="cap_001")
    assert notes == [missing]
    assert level_base.news(notes) == [missing]


def test_a_base_rew_lists_no_calibration_for_is_said_on_the_card_not_as_news(project):
    """A REW that lists no `splOffsetdB` at all (an older one): the round is `missing` with no base
    offset — nothing to bring it to. Said on the card; no capture is «not brought», so no news."""
    checked(project, 3, ["w-L_3 (sw)"], None)
    lb = process_view.capture_round(project)["level_base"]
    assert (lb["status"], lb["base_offset_db"]) == ("missing", None)

    notes = said(project)

    assert notes == [note(level_base.NO_BASE_OFFSET, "cap_001", base="cap_001")]
    assert level_base.news(notes) == []


def _with_control(process, **control) -> None:
    """The control's verdict the method writes from REW's curves, put into its own state."""
    state = process.load()
    state["capture"]["level_base"]["control"] = {"title": "ALL_4 (rta)", "taken": True,
                                                 "bands": {}, "reason": None, **control}
    process._write(state)


def test_a_chain_change_the_control_names_is_news_with_the_methods_numbers(project):
    checked(project, 3, ["w-L_3 (sw)"], 103.35)
    process = checked(project, 4, ["w-L_4 (sw)"], 103.35)
    _with_control(process, verdict="chain_change", common_db=1.2, align_db=-1.2,
                  bands={"low": {"mean_db": 1.21, "spread_db": 0.3, "used": True},
                         "mid": {"mean_db": -0.9, "spread_db": 1.5, "used": False}},
                  why="the chain moved")

    notes = said(project)

    chain = note(level_base.CHAIN, "cap_002", title="ALL_4 (rta)", common="+1.2", bands="low",
                 align="-1.2")
    assert notes == [note(level_base.ON_BASE, "cap_002", base="cap_001", offset="103.35"), chain]
    assert level_base.news(notes) == [chain]


@pytest.mark.parametrize("control, key, values", [
    pytest.param({"verdict": "unattributed", "reason": "disagree",
                  "why": "the bands disagree -- 1.9 dB of spread"},
                 "CONTROL_UNSURE", {"why": "the bands disagree -- 1.9 dB of spread"},
                 id="unattributed-its-why-verbatim"),
    pytest.param({"verdict": "same_chain", "common_db": 0.1, "why": "x"}, "CONTROL_SAME", {},
                 id="same-chain"),
    pytest.param({"verdict": "same_chain", "common_db": 0.0, "reference": True, "why": "x"},
                 "CONTROL_REFERENCE", {}, id="the-reference"),
    pytest.param({"verdict": "not_taken", "taken": False, "common_db": None,
                  "why": "not taken: chain change not checked"}, "CONTROL_NOT_TAKEN", {},
                 id="not-taken"),
])
def test_what_the_control_says_otherwise_is_on_the_card_and_not_news(project, control, key,
                                                                     values):
    checked(project, 3, ["w-L_3 (sw)"], 103.35)
    process = checked(project, 4, ["w-L_4 (sw)"], 103.35)
    _with_control(process, **control)

    notes = said(project)

    assert notes[1:] == [note(getattr(level_base, key), "cap_002", title="ALL_4 (rta)", **values)]
    assert level_base.news(notes) == []


def test_no_control_on_the_round_says_nothing_of_one(project):
    """`verdict: none` (`title: null`): the round has no control; its why is the record's."""
    checked(project, 3, ["w-L_3 (sw)"], 103.35)
    assert process_view.capture_round(project)["level_base"]["control"]["verdict"] == "none"

    assert [n.key for n in said(project)] == [level_base.IS_BASE]


def test_tccs_own_copy_writes_the_level_base(tmp_path, own_copy_is_the_submodule):
    from autosound_tcc.core import method_features

    assert method_features.has(method_features.LEVEL_BASE, tmp_path)
    assert level_base.applies(tmp_path)
