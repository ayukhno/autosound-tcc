"""The tree's channels against «порівняти з»: the EQ legend's dots with their counts, left of the
channel's EQ chip (the Arbiter, 2026-09-26, finding 74, tcc#55)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup  # noqa: E402
from autosound_tcc.ui.tcc.dsp_tree import DspTreeWidget  # noqa: E402

_PK = {"type": "PK", "f": 482, "gain_db": -1.7, "q": 3.0}


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _outputs(**by_name):
    rows = tuple(GroupRow(id=name, name=name, slot=chr(66 + i), raw={"eq": bands})
                 for i, (name, bands) in enumerate(by_name.items()))
    return ProfileGroup(id="physical_outputs", label="Output", fields=("eq",), rows=rows)


def _tree():
    """w-L: 100 Hz same, 1000 Hz gain moved, 4000 Hz new, 2500 Hz gone; m-R the same."""
    now = _outputs(**{"w-L": [dict(_PK, f=100), dict(_PK, f=1000, gain_db=-4.0),
                              dict(_PK, f=4000)],
                      "m-R": [dict(_PK, f=320)]})
    was = _outputs(**{"w-L": [dict(_PK, f=100), dict(_PK, f=1000), dict(_PK, f=2500)],
                      "m-R": [dict(_PK, f=320)]})
    tree = DspTreeWidget()
    tree.set_view(type("V", (), {"groups": (now,), "features": None})())
    return tree, was


def _chan(tree, name):
    return tree._sections["physical_outputs"]._rows[name]


def test_a_channel_shows_its_band_changes_as_dots_with_counts_and_no_names():
    _app()
    tree, was = _tree()
    tree.set_compared([was])
    chan = _chan(tree, "w-L")
    assert chan.band_changes() == {"new": 1, "chg": 1, "removed": 1}
    said = chan._cmp.text()
    assert said.count("●") == 3 and said.count("(1)") == 3
    assert chan._cmp.isVisibleTo(chan)


def test_the_dots_stand_left_of_the_eq_chip():
    _app()
    tree, was = _tree()
    tree.set_compared([was])
    chan = _chan(tree, "w-L")
    layout = chan.layout().itemAt(0).layout()
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert widgets.index(chan._cmp) == widgets.index(chan._eq_chip) - 1


def test_nothing_moved_or_nothing_compared_says_nothing():
    _app()
    tree, was = _tree()
    tree.set_compared([was])
    assert not _chan(tree, "m-R")._cmp.isVisibleTo(_chan(tree, "m-R")), "the same: no dots"
    tree.set_compared(None)
    assert not _chan(tree, "w-L")._cmp.isVisibleTo(_chan(tree, "w-L"))


def test_a_channel_the_compared_version_lacks_is_all_new():
    _app()
    tree, _was = _tree()
    tree.set_compared([])
    assert _chan(tree, "w-L").band_changes() == {"new": 3, "chg": 0, "removed": 0}
