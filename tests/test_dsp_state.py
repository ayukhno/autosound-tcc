"""Headless test of the DSP-state model — fixture only, no submodule/REW."""

from __future__ import annotations

import json
from pathlib import Path

from autosound_tcc.state.dsp_state import DspSnapshot

FIXTURE = Path(__file__).parent / "fixtures" / "sample_snapshot.json"


def _load() -> DspSnapshot:
    raw = json.loads(FIXTURE.read_text())
    return DspSnapshot.from_dict(raw)


def test_snapshot_top_level():
    snap = _load()
    assert snap.preset == "demo"
    assert snap.sample_rate == 48000
    assert snap.version == "v_001"
    assert set(snap.channels) == {"FL", "SUB"}


def test_channel_crossovers_and_fields():
    fl = _load().channels["FL"]
    assert fl.helix_ch == 1
    assert fl.hp.enabled and fl.hp.freq_hz == 80 and fl.hp.slope == 24
    assert fl.lp.enabled and fl.lp.freq_hz == 3200
    assert fl.gain_db == -2.5
    assert fl.ta_ms == 3.10
    assert fl.polarity == "NORM"
    assert fl.status == "measured"


def test_disabled_leg_and_inverted_polarity():
    sub = _load().channels["SUB"]
    assert sub.hp.enabled is False  # "OFF"
    assert sub.hp.freq_hz is None
    assert sub.lp.enabled and sub.lp.freq_hz == 80
    assert sub.polarity == "INV"
    assert sub.eq_ptr is None


def test_samples_derived_from_ms():
    snap = _load()
    # 3.10 ms at 48 kHz -> round(148.8) = 149 samples.
    assert snap.samples_for(3.10) == 149
    assert snap.samples_for(0.0) == 0
