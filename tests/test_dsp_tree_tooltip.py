"""The channel tooltip renders identity from `project.json`, not from the ledger row (SCR-001).

This is the exact defect the SCR names: `_tooltip_html` read `raw["driver"]` / `raw["fs"]`, keys
the skill never writes to a ledger row, so the block rendered empty and nothing raised. Testing the
static renderer directly keeps it a text assertion rather than a widget one.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.state.dsp_state import GroupRow  # noqa: E402
from autosound_tcc.ui.tcc.dsp_tree import ChannelRow  # noqa: E402

_LEDGER_ROW = {
    "hp": {"f": 80, "type": "LR", "slope": 24},
    "lp": {"f": 3200, "type": "LR", "slope": 12},
    "gain_db": -2.5,
    "polarity": "NORM",
}
_IDENTITY = {
    "code": "FL",
    "role": "woofer",
    "driver": {"make": "Audiofrog", "model": "GB25"},
    "fs_hz": {"value": 62, "source": "datasheet", "at": "2026-07-30T10:00:00+00:00"},
}


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _html(identity: dict) -> str:
    _app()  # current_theme() needs an application object for its palette
    row = GroupRow(id="FL", name="FL", raw=_LEDGER_ROW, identity=identity)
    return ChannelRow._tooltip_html(row, _LEDGER_ROW, is_output=True)


def test_driver_role_and_fs_come_from_the_project_join():
    html = _html(_IDENTITY)

    assert "Audiofrog GB25" in html
    assert "woofer" in html
    assert "Fs&nbsp;62&nbsp;Hz" in html  # unwrapped from fact(), not printed as a dict


def test_a_channel_with_no_identity_renders_the_tunable_state_alone():
    html = _html({})

    assert "Audiofrog" not in html
    assert "Fs" not in html
    assert "HP" in html and "LP" in html  # ledger-owned state is untouched


def test_a_fact_wrapper_never_leaks_into_the_markup():
    """A regression guard with teeth: printing the envelope instead of its value would put
    "source"/"datasheet" on screen, which looks like data but is provenance."""
    html = _html(_IDENTITY)

    assert "datasheet" not in html
    assert "'value'" not in html
