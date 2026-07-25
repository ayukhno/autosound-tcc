"""Headless test of the generic, profile-driven DSP-state model — fixtures only, no
submodule/REW. Covers the two properties that matter for processor-agnosticism: a group only
ever shows its OWN declared fields (the Center-crossover-on-virtual bug class), and a DSP profile
that declares no `virtual_channels` group produces no such group (the MUSWAY case)."""

from __future__ import annotations

import json
from pathlib import Path

from autosound_tcc.state.dsp_state import CrossoverLeg, ProjectView

FIXTURES = Path(__file__).parent / "fixtures"
LEDGER = json.loads((FIXTURES / "sample_snapshot.json").read_text())
PROFILE = json.loads((FIXTURES / "sample_profile.json").read_text())


def _view(ledger=LEDGER, profile=PROFILE) -> ProjectView:
    return ProjectView.from_dict(ledger, profile)


def test_project_view_top_level():
    view = _view()
    assert view.preset == "demo"
    assert view.sample_rate == 48000
    assert view.version == "v_001"
    assert [g.id for g in view.groups] == ["physical_outputs"]


def test_group_row_params_render_declared_fields():
    view = _view()
    group = view.groups[0]
    rows = {r.name: r for r in group.rows}
    fl = rows["FL"].params(group.fields)
    assert "HP: 80 Hz LR24" in fl
    assert "LP: 3200 Hz LR12" in fl
    assert "Gain: -2.5 dB" in fl
    assert "Delay: 3.1 ms" in fl
    assert "Pol: NORM" in fl
    assert "EQ: 1 band" in fl


def test_disabled_leg_and_inverted_polarity():
    view = _view()
    sub = {r.name: r for r in view.groups[0].rows}["SUB"]
    params = sub.params(view.groups[0].fields)
    assert "HP: OFF" in params
    assert "LP: 80 Hz LR24" in params
    assert "Pol: INV" in params
    assert not any(p.startswith("EQ") for p in params)  # no eq key at all -> no EQ chip


def test_crossover_leg_labels():
    assert CrossoverLeg.from_raw({"f": 80, "type": "LR", "slope": 24}).label == "80 Hz LR24"
    assert CrossoverLeg.from_raw("OFF").label == "OFF"
    assert CrossoverLeg.from_raw(None).label == "OFF"


def test_group_hides_fields_it_does_not_declare():
    """The Center-has-a-crossover pilot bug, generalized: a virtual_channels group that does NOT
    declare hp/lp must never show a crossover, even if a legacy ledger row still has one."""
    profile = {
        "dsp_profile": {
            "name": "X", "vendor": "Y",
            "groups": [
                {"id": "virtual_channels", "label": "Virtual",
                 "fields": ["gain_db", "polarity"]},  # deliberately no hp/lp
            ],
        }
    }
    ledger = {
        "preset": "x", "sample_rate": 96000,
        "channels": {},
        "virtual_channels": {
            "Center": {"hp": {"f": 620, "type": "LR", "slope": 36}, "lp": {"f": 2330},
                       "gain_db": 3.5, "polarity": "INV"},
        },
    }
    view = ProjectView.from_dict(ledger, profile)
    center = view.groups[0].rows[0]
    params = center.params(view.groups[0].fields)
    assert not any(p.startswith(("HP", "LP")) for p in params), params
    assert "Gain: +3.5 dB" in params and "Pol: INV" in params


def test_no_virtual_tier_when_profile_does_not_declare_one():
    """The MUSWAY case: a profile with no virtual_channels group produces no such group, and an
    `inputs` group (a different tier entirely — no crossover, per-input gain/EQ/delay) renders
    with the same generic code, zero per-DSP special-casing."""
    profile = {
        "dsp_profile": {
            "name": "M6V4", "vendor": "Musway",
            "groups": [
                {"id": "physical_outputs", "label": "Output channels",
                 "fields": ["hp", "lp", "gain_db"]},
                {"id": "inputs", "label": "Inputs",
                 "fields": ["gain_db", "eq", "ta_ms"]},
            ],
        }
    }
    ledger = {
        "preset": "musway-test", "sample_rate": 48000,
        "channels": {"w-L": {"hp": {"f": 80}, "lp": {"f": 4000}, "gain_db": -2.0}},
        "inputs": {
            "Optic": {"gain_db": -3.0, "eq": ["PK 1000 -2 Q2"], "ta_ms": 0.5},
            "USB": {"gain_db": 0.0},
        },
    }
    view = ProjectView.from_dict(ledger, profile)
    ids = [g.id for g in view.groups]
    assert ids == ["physical_outputs", "inputs"]
    assert "virtual_channels" not in ids
    inputs = next(g for g in view.groups if g.id == "inputs")
    assert {r.name for r in inputs.rows} == {"Optic", "USB"}
    optic_params = next(r for r in inputs.rows if r.name == "Optic").params(inputs.fields)
    assert "Gain: -3.0 dB" in optic_params
    assert "EQ: 1 band" in optic_params
    assert "Delay: 0.5 ms" in optic_params
    usb_params = next(r for r in inputs.rows if r.name == "USB").params(inputs.fields)
    assert usb_params == ["Gain: +0.0 dB"]  # no eq/ta_ms present -> not shown, not an error


def test_rows_ordered_by_declared_order_then_name():
    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "physical_outputs", "label": "Output", "fields": ["gain_db"]}]}}
    ledger = {
        "preset": "x", "sample_rate": 96000,
        "channels": {
            "tw_R": {"gain_db": 0}, "sub": {"gain_db": 0, "order": 0},
            "w_L": {"gain_db": 0, "order": 1}, "tw_L": {"gain_db": 0},
            "w_R": {"gain_db": 0, "order": 1},
        },
    }
    view = ProjectView.from_dict(ledger, profile)
    order = [r.name for r in view.groups[0].rows_ordered()]
    # order-tagged rows come first (0, then 1/1 tied -> alphabetical), untagged (99) rows last.
    assert order == ["sub", "w_L", "w_R", "tw_L", "tw_R"]
