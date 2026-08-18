"""The glossary's groups, resolved to the titles REW holds.

What has to hold is that a group is what the CAR says it is, spelled the way REW spells it, and
that a member REW has no sweep for comes back named rather than dropped — the sum cannot notice a
missing driver, so this is the only layer that can.
"""

from __future__ import annotations

import json

import pytest

from autosound_tcc.core import curve_groups

#: One car, in the shape `naming.Glossary` reads (SCR-008). The centre and the rears are absent on
#: purpose: a glossary is per car, and inventing codes is exactly what SCR-008 exists to stop.
GLOSSARY = {
    "channels": [{"code": c} for c in ("sw", "w-L", "w-R", "m-L", "m-R", "tw-L", "tw-R")],
    "pairs": {"Ws": ["w-L", "w-R"], "Ms": ["m-L", "m-R"], "TWs": ["tw-L", "tw-R"]},
    "joints": {"SW+Ws": ["sw", "w-L", "w-R"], "L w+m": ["w-L", "m-L"]},
    "sides": {"L": ["tw-L", "m-L", "w-L"], "R": ["tw-R", "m-R", "w-R"]},
    "combos": {"ALL": ["tw-L", "tw-R", "m-L", "m-R", "w-L", "w-R"]},
}


@pytest.fixture
def project(tmp_path):
    """A project folder with a glossary in it. Never the developer's own — see `tests/conftest`."""
    (tmp_path / "glossary.json").write_text(json.dumps(GLOSSARY), encoding="utf-8")
    return tmp_path


@pytest.fixture
def groups(project):
    return curve_groups.GlossaryGroups.load(project)


def _group(groups, name):
    return next(g for g in groups.groups() if g.name == name)


def test_the_groups_are_the_cars_own_and_carry_which_kind_they_are(groups):
    """`Ws` is a pair and `L` is a side; a caller offering them in one list has to be able to say
    which, or the tuner is choosing between names that mean different shapes of question."""
    by_name = {g.name: g for g in groups.groups()}

    assert by_name["Ws"].kind == "pairs" and by_name["Ws"].members == ("w-L", "w-R")
    assert by_name["SW+Ws"].kind == "joints"
    assert by_name["L"].kind == "sides" and by_name["L"].members == ("tw-L", "m-L", "w-L")
    assert by_name["ALL"].kind == "combos"
    assert [g.name for g in groups.groups()][:3] == ["Ws", "Ms", "TWs"], "pairs first"


def test_a_group_resolves_to_its_members_sweeps_at_one_version(groups):
    """The `(sw)` capture, and only that: a sum needs phase, and an MMM/RTA capture has none."""
    found = groups.resolve(
        _group(groups, "Ws"), "2",
        ["w-L_2 (sw)", "w-R_2 (sw)", "w-L_2 (rta)", "m-L_2 (sw)", "w-L_1 (sw)"],
    )

    assert found.titles == ("w-L_2 (sw)", "w-R_2 (sw)")
    assert found.complete is True


def test_a_zero_padded_title_is_the_same_measurement(groups):
    """REW titles are typed by hand and `_02` for `_2` is the commonest thing a person types. The
    skill's parser reports `version_n` precisely so a checker does not cry wolf over padding."""
    found = groups.resolve(_group(groups, "Ws"), "2", ["w-L_02 (sw)", "w-R_2 (sw)"])

    assert found.titles == ("w-L_02 (sw)", "w-R_2 (sw)"), "as REW spells them, not as we do"
    assert found.complete is True


def test_a_member_rew_has_no_sweep_for_comes_back_named(groups):
    """`curve_sum` sees only the inputs it is handed, so a sum of two thirds of a joint is
    indistinguishable there from a sum of the joint. The name is generated with the skill's own
    grammar, because that is what the tuner will be reading in REW."""
    found = groups.resolve(
        _group(groups, "SW+Ws"), "02", ["w-L_02 (sw)", "w-R_02 (sw)", "sw_01 (sw)"],
    )

    assert found.titles == ("w-L_02 (sw)", "w-R_02 (sw)")
    assert found.missing == ("sw_02 (sw)",)
    assert found.complete is False


def test_a_capture_with_a_modifier_is_not_the_members_sweep(groups):
    """`w-L FX_2 (sw)` was measured with something else going on. Summing it quietly would be a
    sum of a car nobody configured."""
    found = groups.resolve(_group(groups, "Ws"), "2", ["w-L FX_2 (sw)", "w-R_2 (sw)"])

    assert found.titles == ("w-R_2 (sw)",)
    assert found.missing == ("w-L_2 (sw)",)


def test_a_renamed_channel_still_finds_its_own_captures(project):
    """SCR-039: a REW title cannot be rewritten, so a channel renamed mid-project keeps its old
    captures under the old name. They are still that channel's, at that config version."""
    glossary = json.loads(json.dumps(GLOSSARY))
    glossary["channels"][1] = {"code": "w-L", "previous_names": ["m-L2"]}
    (project / "glossary.json").write_text(json.dumps(glossary), encoding="utf-8")
    groups = curve_groups.GlossaryGroups.load(project)

    found = groups.resolve(_group(groups, "Ws"), "2", ["m-L2_2 (sw)", "w-R_2 (sw)"])

    assert found.titles == ("m-L2_2 (sw)", "w-R_2 (sw)")


def test_the_versions_offered_are_the_ones_rew_holds_for_those_drivers(groups):
    """A car whose sub was re-measured at `_04` while the tweeters stopped at `_02` has no single
    newest version. Offering `_04` for a group of tweeters offers a round none of them is in."""
    titles = ["tw-L_02 (sw)", "tw-R_02 (sw)", "sw_04 (sw)", "sw_02 (sw)", "w-L_01 (rta)"]

    assert groups.versions_in(titles) == ("02", "04"), "oldest first"
    assert groups.versions_in(titles, ["tw-L", "tw-R"]) == ("02",)


def test_one_version_spelled_two_ways_is_offered_once(groups):
    """Both spellings resolve to the same measurement, so offering both would let a tuner pick the
    one that happens not to match the other driver."""
    assert groups.versions_in(["w-L_2 (sw)", "w-R_02 (sw)"]) == ("2",)


def test_final_sorts_after_every_number(groups):
    """`final` is a legal version (phase 3). As a string it would file between `_1` and `_2`."""
    assert groups.versions_in(
        ["w-L_1 (sw)", "w-L_final (sw)", "w-L_9 (sw)"]
    ) == ("1", "9", "final")


def test_the_version_of_a_selection_is_the_one_they_all_share(groups):
    assert groups.version_of(["w-L_02 (sw)", "w-R_2 (sw)"]) == "02", "padding is not disagreement"
    assert groups.version_of(["w-L_01 (sw)", "w-R_02 (sw)"]) is None
    assert groups.version_of(["w-L_02 (sw)", "some import"]) is None, "not ours: no answer"
    assert groups.version_of([]) is None


def test_a_project_with_no_glossary_offers_no_groups_and_does_not_complain(tmp_path):
    """TCC is pointed at folders that were never through intake, and a curve window that cannot
    open without a project file is worse than one offering a control fewer."""
    groups = curve_groups.GlossaryGroups.load(tmp_path)

    assert groups.available is False
    assert groups.groups() == ()
    assert groups.version_of(["w-L_02 (sw)"]) == "02", "the grammar still parses without codes"


def test_without_the_skill_there_is_nothing_to_ask_and_that_is_not_an_error(monkeypatch):
    """The skill owns the grammar and the glossary both. Without it the window loses the group
    picker and keeps everything else."""
    from autosound_tcc.core import vendor_loader

    monkeypatch.setattr(
        curve_groups.vendor_loader, "load_naming",
        lambda: (_ for _ in ()).throw(vendor_loader.VendorNotInitializedError("no skill")),
    )

    groups = curve_groups.GlossaryGroups.load()

    assert groups.available is False
    assert groups.facts("w-L_02 (sw)") is None
    assert groups.title_for("sw", "02") == "sw_02 (sw)", "a name can still be spelled"
