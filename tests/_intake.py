"""Seed the machine files phase −1 is supposed to produce.

A test that drives `enter_phase` past −1 now has to pass the same gate a real project does: the
skill refuses to leave intake without `project.json`, `dsp_profile.json` and a glossary
(2026-08-12 — it had been documented and enforced by nothing, so an empty folder walked to phase 1).

Written through the skill's own writers rather than as literal JSON, deliberately. A fixture built
from literals goes stale the day the schema moves and then tests a shape nobody ships; one built
through `project.save()` and `save_profile()` fails at the same moment the real writers do, which
is the only way a fixture stays honest.
"""

from __future__ import annotations

from pathlib import Path

from autosound_tcc.core import vendor_loader


def seed(project_dir) -> Path:
    """Write a minimal, valid intake into `project_dir` and return it.

    Minimal on purpose: one channel, one tier, no captures. Every test that needs more builds it
    on top; nothing here should be mistaken for a realistic project.
    """
    root = Path(project_dir)
    root.mkdir(parents=True, exist_ok=True)
    project = vendor_loader.load_project()
    profile = vendor_loader.load_dsp_profile()

    proj = project.Project(str(root))
    proj.save({
        "schema_version": project.SCHEMA_VERSION,
        "channels": [{"code": "w-L", "tier": "channels"}],
        "glossary": {"schema_version": 1, "channels": [{"code": "w-L", "active": True}]},
    })
    # One flaw, because phase 0 does not end without a map (SCR-044) and `action="leave"` is the
    # honest entry for a feature nobody is going to correct — which is what a fixture's is.
    proj.add_flaw(
        f_hz=160, level_db=-12, kind="cabin_null", action="leave",
        why="fixture: a decision to leave it alone is still a decision",
        evidence=["w-L_01 (sw)"],
    )
    profile.save_profile(str(root / "dsp_profile.json"), {"dsp_profile": {
        "name": "Fixture DSP",
        "vendor": "Fixture",
        "sample_rate_hz": 96000,
        "delay": {"step_ms": 0.01},
        "polarity": {"scope": ["per driver output"]},
        "groups": [{
            "id": "physical_outputs",
            "label": "Output channels",
            "max_count": 2,
            "fields": ["hp", "lp", "gain_db", "ta_ms", "polarity"],
            "crossover_filters": {"types": {"LR": {"orders_db_per_oct": [24]}}},
        }],
    }})
    # ...and the first ledger snapshot, the fourth artefact the gate names. Through
    # `PresetHistory` for the same reason as the rest: a hand-written v_001 would go stale.
    state = vendor_loader.load_dsp_state()
    history = state.PresetHistory(str(root / "state"), "FULL", project_dir=str(root))
    if history.head() is None:
        history.snapshot({
            "preset": "FULL",
            "sample_rate": 96000,
            "channels": {"w-L": {"hp": None, "lp": None, "gain_db": 0.0, "ta_ms": 0.0,
                                 "polarity": "NORM"}},
        }, note="fixture intake")
    return root


def open_phases(process) -> None:
    """Satisfy the gates that live in the process file rather than on disk.

    Just the target curve today (SCR-036). Separate from `seed` because it needs the `Process`
    object, and because a test that only reads state should not have to build one.
    """
    process.set_target("FULL", "EPY")
