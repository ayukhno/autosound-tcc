"""The status dots on the DSP tree's groups and on the tabs (the Arbiter, 2026-09-25, finding 65):
grey — nothing is set there, green — something is, blue — it differs from «порівняти з»."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup  # noqa: E402
from autosound_tcc.ui.tcc import i18n, setting_status  # noqa: E402

_FIELDS = ("hp", "lp", "gain_db", "ta_ms", "phase_deg", "polarity", "eq")


def _outputs(**by_name):
    rows = tuple(GroupRow(id=name, name=name, slot=chr(66 + i), raw=raw)
                 for i, (name, raw) in enumerate(by_name.items()))
    return ProfileGroup(id="physical_outputs", label="Output", fields=_FIELDS, rows=rows)


_PK = {"type": "PK", "f": 482, "gain_db": -1.7, "q": 3.0}


def test_a_group_with_nothing_set_is_grey():
    group = _outputs(**{"w-L": {"gain_db": 0.0, "ta_ms": 0.0, "polarity": "NORM"}})
    assert setting_status.group_status(group) == "none"


def test_a_group_with_any_setting_is_green():
    assert setting_status.group_status(_outputs(**{"w-L": {"gain_db": -0.3}})) == "set"
    assert setting_status.group_status(_outputs(**{"w-L": {"eq": [_PK]}})) == "set"
    assert setting_status.group_status(_outputs(**{"m-L": {"polarity": "INV"}})) == "set"


def test_a_change_is_blue_only_while_something_is_compared():
    now = _outputs(**{"w-L": {"gain_db": -0.3}})
    before = _outputs(**{"w-L": {"gain_db": -0.8}})
    assert setting_status.group_status(now, before, compared=True) == "chg"
    assert setting_status.group_status(now, now, compared=True) == "set"
    assert setting_status.group_status(now) == "set", "nothing compared, nothing blue"


def test_a_moved_eq_band_is_a_change_even_with_the_same_number_of_bands():
    now = _outputs(**{"m-L": {"eq": [_PK]}})
    before = _outputs(**{"m-L": {"eq": [dict(_PK, gain_db=-2.7)]}})
    assert setting_status.group_status(now, before, compared=True) == "chg"


def test_a_parameter_reads_every_tier():
    quiet = _outputs(**{"w-L": {"ta_ms": 0.0}})
    virtual = ProfileGroup(id="virtual_channels", label="Virtual", fields=_FIELDS,
                           rows=(GroupRow(id="VFL", name="VFL", slot="A", raw={"ta_ms": 1.2}),))
    assert setting_status.field_status([quiet, virtual], "ta_ms") == "set"
    assert setting_status.field_status([quiet], "ta_ms") == "none"
    assert setting_status.field_status([quiet], "phase_deg") == "none"
    moved = ProfileGroup(id="virtual_channels", label="Virtual", fields=_FIELDS,
                         rows=(GroupRow(id="VFL", name="VFL", slot="A", raw={"ta_ms": 1.0}),))
    assert setting_status.field_status([quiet, virtual], "ta_ms", [quiet, moved], True) == "chg"
    assert setting_status.field_status([quiet, virtual], "gain_db", [quiet, moved], True) == "none"


def test_the_dot_is_a_bigger_target_than_its_paint():
    """«Можна зробити зону спрацювання трохи більше, бо важко попасти» (the Arbiter, 2026-09-25)."""
    QApplication.instance() or QApplication([])
    dot = setting_status.StatusDot()
    dot.set_status("chg", "v_006")
    assert dot.width() >= 18 and dot.height() >= 18
    assert setting_status.DOT_DIAMETER <= 10
    assert dot.status() == "chg"
    assert "v_006" in dot.tip_text()
    dot.set_status(None)
    assert dot.isHidden()
    dot.set_status("none")
    assert dot.tip_text() == i18n.t("dotNone")
