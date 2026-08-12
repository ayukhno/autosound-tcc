"""The car's acoustic flaw map (state/acoustics_view.py, SCR-015).

The map's load-bearing half is not "there is a peak at 73 Hz" but "this one you cut, that one you
must never boost". TCC reads and colours by that verdict; the skill writes it and refuses the one
combination physics forbids.
"""

from __future__ import annotations

import json

import pytest

from autosound_tcc.state import acoustics_view


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    return tmp_path


def _write(project, flaws):
    (project / "project.json").write_text(
        json.dumps({"schema_version": 3, "acoustics": {"flaws": flaws}}), encoding="utf-8"
    )


def test_no_project_json_is_an_empty_map_not_an_error(project):
    """Before phase 0 there is nothing measured, and that is a new project's ordinary state."""
    assert acoustics_view.load_flaws(project) == ()


def test_rows_arrive_lowest_frequency_first(project):
    _write(project, [
        {"f_hz": 645, "level_db": -14, "kind": "sbir", "action": "geometry"},
        {"f_hz": 73, "level_db": 9, "kind": "driver_resonance", "action": "notch"},
    ])

    flaws = acoustics_view.load_flaws(project)

    assert [f.f_hz for f in flaws] == [73, 645]


def test_the_verdict_decides_the_colour(project):
    """A reader scanning the column must see "correctable" and "never touch" without reading."""
    _write(project, [
        {"f_hz": 73, "level_db": 9, "kind": "driver_resonance", "action": "notch"},
        {"f_hz": 250, "level_db": -12, "kind": "cabin_null", "action": "no_boost"},
        {"f_hz": 5500, "level_db": -6, "kind": "driver_resonance", "action": "leave"},
        {"f_hz": 645, "level_db": -14, "kind": "sbir", "action": "geometry"},
    ])

    tones = {f.f_hz: f.tone for f in acoustics_view.load_flaws(project)}

    assert tones[73] == "done"      # correctable
    assert tones[250] == "bad"      # the boost this map exists to forbid
    assert tones[5500] == "off"     # a fact of the car
    assert tones[645] == "info"     # fixable, but not with EQ


def test_the_headline_is_frequency_width_and_the_feature_itself(project):
    _write(project, [
        {"f_hz": 188, "q": 5.0, "level_db": 5.5, "kind": "modal_peak", "action": "notch"},
        {"f_hz": 40, "bw_oct": 1.5, "level_db": 12, "kind": "room_gain", "action": "leave"},
        {"f_hz": 250, "level_db": -12, "kind": "cabin_null", "action": "no_boost"},
    ])

    heads = [f.headline for f in acoustics_view.load_flaws(project)]

    assert heads == ["40 Hz · 1.5 oct · +12 dB", "188 Hz · Q5 · +5.5 dB", "250 Hz · -12 dB"]


def test_a_row_tcc_cannot_read_does_not_take_the_map_down(project):
    """A malformed row is the skill's to fix; refusing to draw the rest would hide a map that is
    otherwise fine."""
    _write(project, [
        {"f_hz": "not a number", "level_db": 1, "kind": "modal_peak", "action": "notch"},
        {"f_hz": 73, "level_db": 9, "kind": "driver_resonance", "action": "notch"},
    ])

    assert [f.f_hz for f in acoustics_view.load_flaws(project)] == [73]


def test_a_hypothesis_is_not_shown_as_a_verdict(tmp_path):
    """A tune generates suspicions constantly and they had nowhere to go: the pair-coherence
    findings sat in prose for a week, explicitly marked "measured before TA, re-check after",
    because recording them as fact would have been a lie and there was no third option
    (user, 2026-08-12)."""
    _write(tmp_path, [
        {"f_hz": 175, "level_db": -31.7, "kind": "pair_suckout", "action": "leave",
         "status": "hypothesis", "channels": ["w-L", "w-R"], "why": "raw _01, before any TA",
         "evidence": ["Ws pair coherence"]},
    ])

    flaw = acoustics_view.load_flaws(tmp_path)[0]

    assert flaw.is_hypothesis
    # Not the action's colour: showing "leave it alone" as settled is the map claiming more than
    # it knows, which is exactly what the field exists to stop.
    assert flaw.tone == "wait"


def test_a_map_written_before_the_field_existed_still_reads_as_fact(tmp_path):
    """Every entry written before `status` was written as a verdict. Re-labelling history would be
    its own lie."""
    _write(tmp_path, [
        {"f_hz": 152, "level_db": -12, "kind": "cabin_null", "action": "no_boost",
         "why": "settled", "evidence": ["w-L_01 (sw)"]},
    ])

    flaw = acoustics_view.load_flaws(tmp_path)[0]

    assert flaw.status == "confirmed" and not flaw.is_hypothesis
    assert flaw.tone == "bad", "a confirmed no_boost keeps the verdict colour"
