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


def test_a_time_domain_flaw_is_kept_and_reads_as_time(tmp_path, monkeypatch):
    """Skill v3.0.17 added a class of finding that is a property of TIME, not of frequency:
    `energy_lag`, `ringing`, `decay_asymmetry` carry `t_ms` instead of `level_db`, and `f_hz` is
    optional because a lag can be broadband.

    This file used to require both numbers on every row — and its `except` clause turned that into
    the quiet kind of failure: the row was dropped and the panel drew a map with a whole class
    missing, saying nothing. Asserted here because nothing else would notice.
    """
    import json

    from autosound_tcc.state import acoustics_view

    (tmp_path / "project.json").write_text(json.dumps({"acoustics": {"flaws": [
        {"f_hz": 188, "level_db": 5.5, "kind": "modal_peak", "action": "notch", "q": 5},
        {"t_ms": 3.2, "kind": "energy_lag", "action": "delay", "channels": ["w-L"]},
        {"f_hz": 63, "t_ms": -1.8, "kind": "ringing", "action": "geometry"},
    ]}}))
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))

    flaws = acoustics_view.load_flaws(tmp_path)
    assert len(flaws) == 3, "a time-domain row must not be dropped"

    by_kind = {flaw.kind: flaw for flaw in flaws}
    assert by_kind["modal_peak"].headline == "188 Hz · Q5 · +5.5 dB", "unchanged for a frequency row"
    assert by_kind["energy_lag"].headline == "energy lag · +3.2 ms"
    assert by_kind["ringing"].headline == "ringing · 63 Hz · -1.8 ms"
    # Frequency order first; the row that has no frequency cannot join it, so it comes last.
    assert [flaw.kind for flaw in flaws] == ["ringing", "modal_peak", "energy_lag"]


def test_a_time_domain_kind_the_method_adds_later_still_shows(tmp_path, monkeypatch):
    """By SHAPE, not only by name: a row carrying `t_ms` and no `level_db` is a time row whatever
    it is called. Our copy of the method's kind list is one more copy of a rule that lives there —
    this is what keeps it from costing a whole class of finding when it falls behind."""
    import json

    from autosound_tcc.state import acoustics_view

    (tmp_path / "project.json").write_text(json.dumps({"acoustics": {"flaws": [
        {"t_ms": 4.0, "kind": "group_delay_step", "action": "crossover"},
    ]}}))
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))

    flaws = acoustics_view.load_flaws(tmp_path)
    assert [flaw.headline for flaw in flaws] == ["group delay step · +4 ms"]
