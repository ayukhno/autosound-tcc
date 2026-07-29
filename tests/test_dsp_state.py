"""Headless test of the generic, profile-driven DSP-state model — fixtures only, no
submodule/REW. Covers the two properties that matter for processor-agnosticism: a group only
ever shows its OWN declared fields (the Center-crossover-on-virtual bug class), and a DSP profile
that declares no `virtual_channels` group produces no such group (the MUSWAY case)."""

from __future__ import annotations

import json
from pathlib import Path

from autosound_tcc.state.dsp_state import (
    CrossoverLeg,
    EqBand,
    ParamSection,
    ProjectView,
    load_param_sections,
    parse_eq_bands,
)

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
    assert "HP: 80 LR4" in fl
    assert "LP: 3200 LR2" in fl
    assert "Gain: -2.5 dB" in fl
    assert "Delay: 3.1 ms" in fl
    assert "Pol: NORM" in fl
    assert "EQ: 1 band" in fl


def test_disabled_leg_and_inverted_polarity():
    view = _view()
    sub = {r.name: r for r in view.groups[0].rows}["SUB"]
    params = sub.params(view.groups[0].fields)
    assert "HP: OFF" in params
    assert "LP: 80 LR4" in params
    assert "Pol: INV" in params
    assert not any(p.startswith("EQ") for p in params)  # no eq key at all -> no EQ chip


def test_crossover_leg_labels():
    # space between freq and filter; filter ORDER (slope / 6), not the raw dB/oct slope
    assert CrossoverLeg.from_raw({"f": 80, "type": "LR", "slope": 24}).label == "80 LR4"
    assert CrossoverLeg.from_raw({"f": 620, "type": "LR", "slope": 36}).label == "620 LR6"
    assert CrossoverLeg.from_raw({"f": 88, "type": "BW", "slope": 12}).label == "88 BW2"
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
            "Optic": {"gain_db": -3.0, "eq": [{"type": "PK", "f": 1000, "gain_db": -2, "q": 2}],
                      "ta_ms": 0.5},
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


def test_parse_eq_bands_real_formats():
    bands = parse_eq_bands([
        {"type": "PK", "f": 1000, "gain_db": -9, "q": 2},
        {"type": "LSH", "f": 150, "gain_db": 2.5, "q": 0.71},
        {"type": "PK", "f": 2800, "gain_db": 1.2, "q": 1.8, "bypass": True, "i": 3},
    ])
    assert bands[0] == EqBand(type="PK", freq_hz=1000.0, gain_db=-9.0, q=2.0)
    assert bands[1] == EqBand(type="LSH", freq_hz=150.0, gain_db=2.5, q=0.71)
    assert bands[2].bypass is True and bands[2].index == 3


def test_parse_eq_bands_no_gain_allpass():
    """An all-pass band has no gain — must parse, not raise."""
    band = EqBand.from_dict({"type": "APF2", "f": 2177, "q": 1.5})
    assert band.type == "APF2" and band.freq_hz == 2177.0 and band.gain_db is None and band.q == 1.5


def test_parse_eq_bands_absent_or_empty():
    assert parse_eq_bands(None) == ()
    assert parse_eq_bands([]) == ()
    assert parse_eq_bands("not a list") == ()


def test_group_row_eq_bands_method():
    view = _view()
    fl = {r.name: r for r in view.groups[0].rows}["FL"]
    bands = fl.eq_bands()
    assert len(bands) == 1 and bands[0].type == "PK"


def test_slot_order_descr_and_tag_read_from_ledger():
    """`tag` (WHICH control affects this row) stays on the ledger row -- structural. `tag_value`
    (the control's dialled position) is resolved from `hardware_controls` (SCR-017: a DSP-level
    fact, not per-preset ledger state), not from the ledger row any more."""
    profile = {"dsp_profile": {"groups": [
        {"id": "virtual_channels", "label": "Virtual channels", "max_count": 8,
         "fields": ["gain_db", "polarity", "eq"]},
    ]}}
    ledger = {"virtual_channels": {
        "VFL": {"slot": "A", "order": 0, "descr": "Front L Full", "polarity": "NORM",
                "eq": [{"type": "LSH", "f": 150, "gain_db": 2.5, "q": 0.71}]},
        "VRL": {"slot": "C", "order": 2, "descr": "Rear L Full", "tag": "RearRC",
                "polarity": "NORM", "eq": []},
    }}
    hardware_controls = {"RearRC": {"value": "3/4", "source": "user", "at": "…"}}
    group = ProjectView.from_dict(ledger, profile, hardware_controls=hardware_controls).groups[0]
    assert group.max_count == 8
    rows = {r.name: r for r in group.rows}
    assert (rows["VFL"].slot, rows["VFL"].order, rows["VFL"].descr) == ("A", 0, "Front L Full")
    assert rows["VFL"].tag is None
    assert rows["VFL"].tag_value is None
    assert (rows["VRL"].slot, rows["VRL"].tag, rows["VRL"].tag_value) == ("C", "RearRC", "3/4")


def test_tag_value_missing_from_hardware_controls_is_none():
    """A row that names a `tag` no `hardware.controls` entry has yet -- renders bare, not an
    error (same "lenient on absent facts" convention as everywhere else)."""
    profile = {"dsp_profile": {"groups": [
        {"id": "virtual_channels", "label": "Virtual channels", "fields": ["gain_db"]},
    ]}}
    ledger = {"virtual_channels": {"VRR": {"tag": "SubRC"}}}
    row = ProjectView.from_dict(ledger, profile).groups[0].rows[0]
    assert row.tag == "SubRC" and row.tag_value is None


def test_muted_and_off_flags():
    profile = {"dsp_profile": {"groups": [
        {"id": "virtual_channels", "label": "V", "fields": ["eq"]},
    ]}}
    ledger = {"virtual_channels": {
        "A": {"mute": True, "eq": []}, "B": {"off": True, "eq": []}, "C": {"eq": []},
    }}
    rows = {r.name: r for r in ProjectView.from_dict(ledger, profile).groups[0].rows}
    assert rows["A"].muted and not rows["A"].off
    assert rows["B"].off and not rows["B"].muted
    assert not rows["C"].muted and not rows["C"].off


def test_features_and_header_metadata_parsed():
    profile = {"dsp_profile": {"groups": []}}
    ledger = {"features": [["RealCenter", "ON"], ["SubRC", "-4 dB (judging)"]],
              "slot_label": "DSP #01", "save": "B8_EMMA_v10_Finish"}
    view = ProjectView.from_dict(ledger, profile)
    assert view.features == (("RealCenter", "ON"), ("SubRC", "-4 dB (judging)"))
    assert view.slot_label == "DSP #01"
    assert view.save == "B8_EMMA_v10_Finish"


def test_features_absent_is_empty_tuple():
    view = _view()
    assert view.features == ()
    assert view.slot_label is None and view.save is None


def test_hidden_flag():
    profile = {"dsp_profile": {"groups": [
        {"id": "virtual_channels", "label": "V", "fields": ["eq"]},
    ]}}
    ledger = {"virtual_channels": {
        "VRF": {"hidden": True, "eq": []}, "VFL": {"eq": []},
    }}
    rows = {r.name: r for r in ProjectView.from_dict(ledger, profile).groups[0].rows}
    assert rows["VRF"].hidden and not rows["VFL"].hidden


def test_param_sections_passthrough_in_from_dict():
    sections = (ParamSection(id="car", label="Car setup", params=(("Make", "VW"),)),)
    view = ProjectView.from_dict({"channels": {}}, {"dsp_profile": {"groups": []}}, param_sections=sections)
    assert view.param_sections == sections


def test_param_sections_absent_is_empty_tuple():
    view = _view()
    assert view.param_sections == ()


def test_load_param_sections_reads_project_json(tmp_path):
    data = {
        "param_sections": [
            {"id": "car", "label": "Car setup", "params": [["Make", "VW"], ["Model", "Passat B8"]]},
            {"id": "chassis", "label": "Body / chassis", "params": [["Doors", "4"]]},
        ]
    }
    (tmp_path / "project.json").write_text(json.dumps(data))
    sections = load_param_sections(tmp_path)
    assert sections == (
        ParamSection(id="car", label="Car setup", params=(("Make", "VW"), ("Model", "Passat B8"))),
        ParamSection(id="chassis", label="Body / chassis", params=(("Doors", "4"),)),
    )


def test_load_param_sections_absent_file_returns_empty(tmp_path):
    assert load_param_sections(tmp_path) == ()
