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
    ProjectView,
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


def test_a_tier_nobody_enumerated_is_not_a_tier_with_no_controls():
    """The method made `groups[].fields` null-until-confirmed on 2026-08-23, and the two states
    must not collapse: absence of the whole GROUP says the DSP has no such tier, `fields: null`
    says the tier exists and its controls are an open question. It matters beyond rendering --
    the method's `missing_facts` derives its checklist FROM these tokens, so a profile forced to
    name a field in order to validate deletes the questions about the ones it left out.

    Before this, `tuple(g.get("fields", ()))` raised TypeError on the null and took the whole
    project view down with it -- on the first genuinely new DSP somebody onboards, which is the
    worst possible moment.
    """
    ledger = {"preset": "x", "sample_rate": 96000, "channels": {"a": {"gain_db": 0}}}
    unknown = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "physical_outputs", "label": "Output", "fields": None}]}}
    absent = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "physical_outputs", "label": "Output"}]}}
    empty = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "physical_outputs", "label": "Output", "fields": []}]}}

    for profile in (unknown, absent):
        group = ProjectView.from_dict(ledger, profile).groups[0]
        assert group.fields is None and group.fields_unknown
        assert group.known_fields == ()  # safe to iterate, and says nothing it does not know

    stated = ProjectView.from_dict(ledger, empty).groups[0]
    assert stated.fields == () and not stated.fields_unknown


def test_rows_are_ordered_by_the_hardware_slot_whatever_order_says():
    """The slot is the channel's ID badge and the order the processor's own software shows. A real
    rig came out `G, H, E, F, C, D, B, I, J, K` once `project.json` started carrying `order` — the
    skill's logical grouping (tweeters, mids, woofers, …), which nobody can scan for a slot
    (user, 2026-08-07)."""
    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "physical_outputs", "label": "Output", "fields": ["gain_db"]}]}}
    ledger = {
        "preset": "x", "sample_rate": 96000,
        "channels": {
            "tw-L": {"gain_db": 0}, "tw-R": {"gain_db": 0}, "w-L": {"gain_db": 0},
            "c": {"gain_db": 0}, "sw": {"gain_db": 0},
        },
    }
    channels = {  # the slots the skill really wrote, with its own `order` on top
        "tw-L": {"code": "tw-L", "slot": "G", "order": 1},
        "tw-R": {"code": "tw-R", "slot": "H", "order": 2},
        "w-L": {"code": "w-L", "slot": "C", "order": 5},
        "c": {"code": "c", "slot": "B", "order": 7},
        "sw": {"code": "sw", "slot": "K", "order": 10},
    }
    view = ProjectView.from_dict(ledger, profile, channels=channels)

    assert [r.name for r in view.groups[0].rows_ordered()] == ["c", "w-L", "tw-L", "tw-R", "sw"]


def test_a_numbered_processor_sorts_by_number_not_by_text():
    """Different DSPs number their slots instead of lettering them, and `10` sorts before `2` as
    text — a MUSWAY-style rig would read 1, 10, 11, 2."""
    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "physical_outputs", "label": "Output", "fields": ["gain_db"]}]}}
    ledger = {"preset": "x", "sample_rate": 96000,
              "channels": {name: {"gain_db": 0} for name in ("a", "b", "c", "d")}}
    channels = {name: {"code": name, "slot": slot}
                for name, slot in (("a", "10"), ("b", "2"), ("c", "1"), ("d", "11"))}

    view = ProjectView.from_dict(ledger, profile, channels=channels)

    assert [r.slot for r in view.groups[0].rows_ordered()] == ["1", "2", "10", "11"]


def test_a_channel_with_no_slot_sorts_last_rather_than_first():
    """An unlabelled channel is the exception; putting the exceptions on top pushes the rig down."""
    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "physical_outputs", "label": "Output", "fields": ["gain_db"]}]}}
    ledger = {"preset": "x", "sample_rate": 96000,
              "channels": {"nameless": {"gain_db": 0}, "sub": {"gain_db": 0}}}
    channels = {"sub": {"code": "sub", "slot": "K"}}

    view = ProjectView.from_dict(ledger, profile, channels=channels)

    assert [r.name for r in view.groups[0].rows_ordered()] == ["sub", "nameless"]


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


def test_a_renamed_channel_shows_its_new_name_and_keeps_its_ledger_key():
    """SCR-039. The snapshot below was written when the channel was called `m-L` and is immutable,
    so its row key stays `m-L` forever. What the tree must show is the name the channel goes by
    today, and what every delta/proposal must keep addressing is the key — hence `id` and `name`
    are separate fields on the row.
    """
    profile = {"dsp_profile": {"groups": [
        {"id": "physical_outputs", "label": "Outputs", "fields": ["gain_db"]},
    ]}}
    ledger = {"channels": {"m-L": {"gain_db": -3.0}}}
    channels = {  # what project_view.load_channels returns after a rename: three keys, one entry
        "m-L": {"code": "w-L", "id": "m-L", "previous_names": ["m-L"], "slot": "C",
                "descr": "Front L Woofer", "role": "woofer"},
    }
    channels["w-L"] = channels["m-L"]

    row = ProjectView.from_dict(ledger, profile, channels=channels).groups[0].rows[0]

    assert row.name == "w-L", "the tree shows what the channel is called now"
    assert row.id == "m-L", "the ledger key is what a proposal still addresses"
    assert (row.slot, row.descr, row.role) == ("C", "Front L Woofer", "woofer")


def test_a_row_with_no_project_entry_still_shows_its_ledger_key_as_the_name():
    """Mid-intake, or a tier whose codes were never declared in `project.json`. The key is the only
    name there is, and rendering nothing would hide a channel that exists."""
    profile = {"dsp_profile": {"groups": [
        {"id": "physical_outputs", "label": "Outputs", "fields": ["gain_db"]},
    ]}}
    row = ProjectView.from_dict({"channels": {"w-R": {"gain_db": 0}}}, profile).groups[0].rows[0]
    assert (row.id, row.name) == ("w-R", "w-R")


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



# ---- SCR-001: identity from project.json, tunable state from the ledger --------------------

_IDENTITY = {
    "FL": {
        "code": "FL",
        "slot": "C",
        "descr": "Front L Woofer",
        "role": "woofer",
        "order": 1,
        "driver": {"make": "Audiofrog", "model": "GB25"},
        "fs_hz": {"value": 62, "source": "datasheet", "at": "2026-07-30T10:00:00+00:00"},
        "impedance_ohm": 4,
    }
}


def test_identity_fields_are_joined_onto_the_ledger_row_by_code():
    """The defect SCR-001 names: the tooltip read `driver`/`fs` off the ledger row, where the
    skill never wrote them, so it rendered empty and nothing raised."""
    view = ProjectView.from_dict(LEDGER, PROFILE, channels=_IDENTITY)
    row = {r.name: r for r in view.groups[0].rows}["FL"]

    assert row.driver == "Audiofrog GB25"
    assert row.role == "woofer"
    assert row.fs_hz == 62  # unwrapped from its fact() envelope
    assert row.impedance_ohm == 4
    assert row.slot == "C"
    assert row.descr == "Front L Woofer"
    assert row.order == 1


def test_a_channel_with_no_project_entry_still_renders():
    """SUB has no `channels[]` row here. Absence is "not captured", never an error — half-done
    intake is the normal state of a project, not a broken one."""
    view = ProjectView.from_dict(LEDGER, PROFILE, channels=_IDENTITY)
    row = {r.name: r for r in view.groups[0].rows}["SUB"]

    assert row.driver is None
    assert row.fs_hz is None
    assert row.params(("gain_db", "polarity"))  # tunable state is unaffected


def test_project_json_wins_over_the_deprecated_ledger_copies():
    """`slot`/`descr`/`role`/`order` exist in both files. The rule (SCR-001) is identity-first;
    the ledger's copies stay readable only for snapshots taken before the split."""
    ledger = json.loads(json.dumps(LEDGER))
    ledger["channels"]["FL"].update({"slot": "STALE", "descr": "stale name", "role": "tweeter",
                                     "order": 9})

    view = ProjectView.from_dict(ledger, PROFILE, channels=_IDENTITY)
    row = {r.name: r for r in view.groups[0].rows}["FL"]

    assert (row.slot, row.descr, row.role, row.order) == ("C", "Front L Woofer", "woofer", 1)


def test_the_ledger_copies_are_still_read_when_the_project_has_no_entry():
    ledger = json.loads(json.dumps(LEDGER))
    ledger["channels"]["SUB"].update({"slot": "H", "descr": "Sub", "role": "sub", "order": 5,
                                      "hidden": True})

    view = ProjectView.from_dict(ledger, PROFILE, channels=_IDENTITY)
    row = {r.name: r for r in view.groups[0].rows}["SUB"]

    assert (row.slot, row.descr, row.role, row.order) == ("H", "Sub", "sub", 5)
    assert row.hidden is True


def test_hidden_is_identity_first():
    """Whether a slot has a driver assigned is a project fact (SCR-003), not something that varies
    between snapshots of the same install."""
    ledger = json.loads(json.dumps(LEDGER))
    ledger["channels"]["FL"]["hidden"] = True

    view = ProjectView.from_dict(ledger, PROFILE, channels={"FL": {"code": "FL", "hidden": False}})

    assert {r.name: r for r in view.groups[0].rows}["FL"].hidden is False


def test_a_numeric_slot_is_rendered_as_text():
    """A model wrote `slot: 1` where the schema says a letter. `QLabel(int)` raised inside a Qt
    slot — which does not propagate, it aborts the process — and the app went down mid-session
    after eight measurements. The ledger is written by a language model; nothing read from it may
    be trusted to have the type this code expects."""
    from autosound_tcc.state.dsp_state import _as_text

    assert _as_text(1) == "1"
    assert _as_text("A") == "A"
    assert _as_text(None) is None
    assert _as_text("") is None
    assert _as_text({"nested": "object"}) is None  # not a label, and not a crash either


def test_a_spare_slot_appears_even_though_it_has_no_ledger_row():
    """A slot with nothing wired to it has no tuning state, so the ledger has no row for it — and
    building rows from the ledger alone made every spare slot vanish from the panel whose job is
    showing the rig entire (user, 2026-08-07). `project.json` records them; TCC renders them."""
    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "physical_outputs", "label": "Output", "fields": ["gain_db"]}]}}
    ledger = {"preset": "x", "sample_rate": 96000, "channels": {"sw": {"gain_db": 0}}}
    channels = {
        "sw": {"code": "sw", "slot": "K", "tier": "channels"},
        "off-out-A": {"code": "off-out-A", "slot": "A", "tier": "channels",
                      "hidden": True, "role": "unused"},
    }

    rows = ProjectView.from_dict(ledger, profile, channels=channels).groups[0].rows_ordered()

    assert [r.name for r in rows] == ["off-out-A", "sw"]  # slot A before slot K
    assert rows[0].hidden is True and rows[1].hidden is False


def test_a_channel_that_does_not_name_its_tier_is_left_out_rather_than_guessed_into_one():
    """Slot letters repeat across tiers — a Helix uses A..H for virtual and B..K for outputs — so
    there is nothing in a bare `role: unused` entry that says where it belongs. Until the skill
    says (SCR-042), inventing a tier would put a spare output among the virtual channels."""
    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "physical_outputs", "label": "Output", "fields": ["gain_db"]}]}}
    ledger = {"preset": "x", "sample_rate": 96000, "channels": {"sw": {"gain_db": 0}}}
    channels = {
        "sw": {"code": "sw", "slot": "K"},
        "off-virt-F": {"code": "off-virt-F", "slot": "F", "hidden": True, "role": "unused"},
    }

    rows = ProjectView.from_dict(ledger, profile, channels=channels).groups[0].rows_ordered()

    assert [r.name for r in rows] == ["sw"]


def test_slots_order_the_same_whether_the_processor_labels_them_letters_or_numbers():
    """Helix labels its outputs A…L; other processors number them, and the counts run 12, 14, 16,
    20 and up (user, 2026-08-12). Compared as text, `10` sorts before `2`, so a numbered rig would
    read 1, 10, 11, 2 — the settings sheet out of order is the Arbiter typing into the wrong
    output."""
    from autosound_tcc.state.dsp_state import slot_key

    assert sorted(["L", "A", "K", "B"], key=slot_key) == ["A", "B", "K", "L"]
    assert sorted(["10", "2", "1", "20", "16"], key=slot_key) == ["1", "2", "10", "16", "20"]
    # mixed labels, and a processor that combines them
    assert sorted(["A2", "A10", "A1"], key=slot_key) == ["A1", "A2", "A10"]
    # a channel with no slot goes last: the exceptions must not push the rig down the page
    assert sorted(["B", None, "A"], key=slot_key) == ["A", "B", None]


def test_a_twenty_output_rig_orders_in_slot_order():
    """Nothing caps the channel count — `max_count` is a fact from the profile, not a limit in the
    code. Helix alone runs 12, 14, 16 and 20; other processors go further."""
    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup

    rows = tuple(
        GroupRow(id=f"ch{n}", name=f"ch{n}", raw={"gain_db": -1.0 * n}, slot=str(n))
        for n in range(1, 21)
    )
    group = ProfileGroup(id="physical_outputs", label="Outputs", fields=("gain_db",),
                         rows=rows, max_count=20)

    assert [r.slot for r in group.rows_ordered()] == [str(n) for n in range(1, 21)]


def test_the_rig_can_be_drawn_before_the_first_ledger_snapshot():
    """A project can be fully described and not yet tuned -- which is what a project seeded from
    another car IS, an hour before the first measurement ("after copying the car I do not see the
    processor's data", user, 2026-08-23).

    Nothing is invented: `from_dict` already fills a tier from `project.json`'s channel identity
    for any channel the ledger has no row for, which is how spare slots appear. An EMPTY ledger
    asks for identity alone.
    """
    from autosound_tcc.state.dsp_state import rig_view

    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "virtual_channels", "label": "Virtual", "fields": ["gain_db"]},
        {"id": "physical_outputs", "label": "Output", "fields": ["gain_db", "hp", "lp"]},
    ]}}
    channels = {
        "w-L": {"code": "w-L", "slot": "C", "tier": "channels", "role": "woofer"},
        "sw": {"code": "sw", "slot": "K", "tier": "channels", "role": "sub"},
        "VFL": {"code": "VFL", "slot": "A", "tier": "virtual_channels", "role": "virtual"},
        "off-out-A": {"code": "off-out-A", "slot": "A", "tier": "channels", "hidden": True},
    }

    view = ProjectView.from_dict({}, profile, channels=channels)

    outputs = next(g for g in view.groups if g.id == "physical_outputs")
    virtual = next(g for g in view.groups if g.id == "virtual_channels")
    assert [r.name for r in outputs.rows_visible()] == ["w-L", "sw"], "by slot, spares excluded"
    assert [r.name for r in virtual.rows_visible()] == ["VFL"]
    # Identity only: there is no tuning state to show, and none is invented.
    assert all(not r.params(outputs.known_fields) for r in outputs.rows_visible())


def test_a_channel_that_names_no_tier_is_left_out_rather_than_guessed():
    """The window must not become a second guesser. Today `project.json` writes `tier` on the
    SPARE slots only -- for a working channel the ledger is what says which tier it is in -- so a
    ledger-less rig comes out empty rather than sorted by role, and the panel keeps its note."""
    from autosound_tcc.state.dsp_state import rig_view  # noqa: F401  (import shape check)

    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "physical_outputs", "label": "Output", "fields": ["gain_db"]},
    ]}}
    channels = {"w-L": {"code": "w-L", "slot": "C", "role": "woofer"}}  # no tier

    view = ProjectView.from_dict({}, profile, channels=channels)

    assert view.groups[0].rows == ()


def test_a_renamed_channel_is_one_row_in_the_rig_not_three():
    """`load_channels` keys a channel by EVERY name a ledger row might use -- its id, its current
    code, and each name it went by (SCR-039) -- so the identity fallback walked past the same
    channel two or three times and added a row each time.

    Invisible until the rig could be drawn without a ledger, because before that the fallback only
    ever ran for spare slots, and a spare has never been renamed. The Passat's real file drew
    fourteen outputs for a car with eight: `c, w-L, w-L, w-R, w-R, m-L, m-L, …`.
    """
    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "physical_outputs", "label": "Output", "fields": ["gain_db"]},
    ]}}
    renamed = {"code": "w-L", "id": "m-L", "previous_names": ["m-L"], "slot": "C",
               "tier": "channels", "role": "woofer"}
    identities = {"w-L": renamed, "m-L": renamed}  # what load_channels() really returns

    view = ProjectView.from_dict({}, profile, channels=identities)

    rows = view.groups[0].rows
    assert [r.name for r in rows] == ["w-L"], "one channel, under the name it goes by now"

