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


def test_an_unused_channel_still_gets_a_row_and_says_it_is_off(tmp_path):
    """"Not shown" and "off" were indistinguishable, and neither could be undone from here — you
    cannot switch on what the panel refuses to draw (user, 2026-08-06)."""
    from autosound_tcc.state.dsp_state import ProfileGroup
    from autosound_tcc.ui.tcc import i18n

    _app()
    group = ProfileGroup(id="virtual", label="VIRTUAL", fields=("gain_db",))
    unused = GroupRow(id="VRR", name="VRR", raw={"hidden": True}, identity={})

    row = ChannelRow(group, unused)

    assert row._toggle.text() == i18n.t("chanOff")


def test_a_channel_in_use_reads_on(tmp_path):
    from autosound_tcc.state.dsp_state import ProfileGroup
    from autosound_tcc.ui.tcc import i18n

    _app()
    group = ProfileGroup(id="virtual", label="VIRTUAL", fields=("gain_db",))
    live = GroupRow(id="VFL", name="VFL", raw={"gain_db": 0.0}, identity={})

    row = ChannelRow(group, live)

    assert row._toggle.text() == i18n.t("chanOn")


def test_flipping_a_channel_asks_rather_than_writes(tmp_path):
    """The ledger is the skill's to write (D-6). TCC says what was asked for; the model records it."""
    from autosound_tcc.state.dsp_state import ProfileGroup

    _app()
    group = ProfileGroup(id="virtual", label="VIRTUAL", fields=("gain_db",))
    row = ChannelRow(group, GroupRow(id="VRR", name="VRR", raw={"hidden": True}, identity={}))
    asked: list[tuple[str, bool]] = []
    row.toggleRequested.connect(lambda name, on: asked.append((name, on)))

    row._toggle.click()

    assert asked == [("VRR", True)]  # off -> the request is to turn it on
