"""The tree's channels against «порівняти з»: the EQ legend's dots with their counts, left of the
channel's EQ chip (the Arbiter, 2026-09-26, finding 74, tcc#55)."""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
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


# ---- every value the table marks, the tree marks too (the Arbiter, 2026-09-28, finding 113, tcc#104)

_HP20 = {"f": 20, "type": "BW", "slope": 24}  # «20 BW4»
_OUT_FIELDS = ("hp", "lp", "gain_db", "ta_ms", "polarity", "eq")
_VIRT_FIELDS = ("gain_db", "ta_ms", "phase_deg", "eq")


def _tier(group_id, fields, **by_name):
    rows = tuple(GroupRow(id=name, name=name, slot=chr(65 + i), raw=raw)
                 for i, (name, raw) in enumerate(by_name.items()))
    return ProfileGroup(id=group_id, label=group_id, fields=fields, rows=rows)


def _rig(sw_hp, right_delay, right_pol, vfl_gain, vfl_phase):
    """sw with an HP; m-R and tw-R with a delay and a polarity; w-L that never moves; VFL above."""
    right = {"ta_ms": right_delay, "polarity": right_pol, "gain_db": -1.0,
             "hp": {"f": 350, "type": "LR", "slope": 24}}
    outputs = _tier("physical_outputs", _OUT_FIELDS,
                    **{"w-L": {"hp": {"f": 60, "type": "LR", "slope": 24}, "gain_db": -2.0,
                               "ta_ms": 5.2, "polarity": "NORM"},
                       "m-R": dict(right), "tw-R": dict(right, hp={"f": 3500, "type": "LR",
                                                                   "slope": 24}),
                       "sw": {"hp": sw_hp, "lp": {"f": 80, "type": "LR", "slope": 24},
                              "gain_db": 0.0, "ta_ms": 0.0, "polarity": "NORM"}})
    virtual = _tier("virtual_channels", _VIRT_FIELDS,
                    VFL={"gain_db": vfl_gain, "ta_ms": 0.5, "phase_deg": vfl_phase})
    return type("V", (), {"groups": (virtual, outputs), "features": None})()


def _right_now():
    """`6.R-right`: m-R's and tw-R's delay 4.19 and polarity NORM, sw's HPF 20 BW4."""
    return _rig(_HP20, 4.19, "NORM", vfl_gain=-3.0, vfl_phase=90)


def _v_006():
    return _rig({"f": 25, "type": "BW", "slope": 24}, 0.0, "INV", vfl_gain=-1.0, vfl_phase=90)


def _compared_tree():
    tree = DspTreeWidget()
    tree.set_view(_right_now())
    tree.set_compared(list(_v_006().groups))
    return tree


def _row_of(tree, group_id, name):
    return tree._sections[group_id]._rows[name]


def _marked(chan):
    """The line-2 texts drawn as changed."""
    return [text for text, changed in chan._line2.parts() if changed]


def test_sw_s_changed_high_pass_is_marked_on_its_line_not_only_its_eq():
    from autosound_tcc.ui.tcc.detail_pane import mark_colour

    _app()
    tree = _compared_tree()
    sw = _row_of(tree, "physical_outputs", "sw")
    assert "hp" in sw.changed_fields()
    assert _marked(sw) == ["HP 20 BW4"], "the HP, and nothing that did not move"
    # The whole line, not what an unlaid-out row has room for. A hidden widget gets its resize
    # event only when shown, so the line is asked to re-cut itself here.
    sw._line2.resize(2000, 20)
    sw._line2._elide()
    assert sw._line2.text().startswith(
        f'<span style="color:{mark_colour("chg")};font-weight:700">HP 20 BW4</span>')
    assert sw._line2.text().count("<span") == 1


def test_a_cut_line_keeps_the_colour_on_what_is_left():
    _app()
    tree = _compared_tree()
    chan = _row_of(tree, "physical_outputs", "m-R")
    line = chan._line2
    line.resize(line.fontMetrics().horizontalAdvance("HP 350 LR4 · LP OFF · -1.0dB · Del…"), 20)
    line._elide()
    said = line.text()
    assert said.endswith("</span>…") and "Delay 4.19ms" not in said and "<span" in said


def test_6_r_right_against_v_006_marks_m_r_and_tw_r_for_delay_and_polarity():
    _app()
    tree = _compared_tree()
    for name in ("m-R", "tw-R"):
        chan = _row_of(tree, "physical_outputs", name)
        assert {"ta_ms", "polarity"} <= chan.changed_fields(), name
        # The output line did not show the delay at all: now it does, because it differs.
        assert "Delay 4.19ms" in _marked(chan), name
        assert chan._pill.text().upper() == "NORM" and chan._pill.isVisibleTo(chan), name
        assert "chg" in chan._pill.property("class").split(), name


def test_an_unchanged_field_is_not_marked():
    _app()
    tree = _compared_tree()
    w_l = _row_of(tree, "physical_outputs", "w-L")
    assert w_l.changed_fields() == frozenset()
    assert _marked(w_l) == []
    assert "Delay" not in " ".join(text for text, _ in w_l._line2.parts()), \
        "an output's delay shows only when it differs"
    assert not w_l._pill.isVisibleTo(w_l), "NORM that did not move is noise, as before"


def test_a_tier_other_than_the_outputs_marks_the_same_way():
    _app()
    tree = _compared_tree()
    vfl = _row_of(tree, "virtual_channels", "VFL")
    assert vfl.changed_fields() == frozenset({"gain_db"})
    assert _marked(vfl) == ["Gain -3.0dB"]


def test_nothing_compared_clears_every_field_mark():
    _app()
    tree = _compared_tree()
    tree.set_compared(None)
    chan = _row_of(tree, "physical_outputs", "m-R")
    assert chan.changed_fields() == frozenset() and _marked(chan) == []
    assert "Delay" not in " ".join(text for text, _ in chan._line2.parts())
    assert not chan._pill.isVisibleTo(chan)


# ---- bold as well as blue, as the table's changed cells (the Arbiter, 2026-09-29, finding 116, tcc#108)


def _drawn(line):
    """`([(text, bold)], width)`: the line's rich text as Qt lays it out, in the line's own font."""
    from PySide6.QtGui import QTextDocument

    doc = QTextDocument()
    doc.setDefaultFont(line.font())
    doc.setDocumentMargin(0)
    doc.setHtml(line.text())
    runs = []
    it = doc.begin().begin()
    while not it.atEnd():
        fragment = it.fragment()
        runs.append((fragment.text(), fragment.charFormat().fontWeight() >= 700))
        it += 1
    return runs, doc.idealWidth()


def _themed(tree):
    """The window's own stylesheet on the tree, so the line wears the font the app gives it."""
    from autosound_tcc.ui.tcc.theme import build_qss, current_theme

    tree.setStyleSheet(build_qss(current_theme()))
    return tree


def test_a_changed_value_reads_bold_as_well_as_blue_and_nothing_else_does():
    _app()
    tree = _compared_tree()
    for name, bold in (("sw", "HP 20 BW4"), ("m-R", "Delay 4.19ms"), ("w-L", "")):
        line = _row_of(tree, "physical_outputs", name)._line2
        line.resize(2000, 20)
        line._elide()
        runs, _width = _drawn(line)
        assert "".join(text for text, heavy in runs if heavy) == bold, (name, runs)
        assert "".join(text for text, _ in runs) == " · ".join(t for t, _ in line.parts()), name


@pytest.mark.parametrize("themed", [False, True], ids=["app-face", "theme-face"])
def test_a_cut_line_with_a_bold_part_still_fits_its_width(themed):
    """The cut measured the line as plain text, and bold is wider than plain in most faces: the
    line would run past its edge by what the bold part gained (the #104 review). The theme's
    monospace keeps bold as wide as plain where it is installed; the app's own face does not, and
    a machine without the theme's faces draws the line in another. Every width, both faces."""
    from PySide6.QtGui import QFont, QFontMetricsF

    _app()
    tree = _compared_tree()
    if themed:
        _themed(tree)
    line = _row_of(tree, "physical_outputs", "m-R")._line2
    line.ensurePolished()
    line.resize(2000, 20)
    line._elide()
    full = math.ceil(_drawn(line)[1])
    heavy = QFont(line.font())
    heavy.setBold(True)
    said = " · ".join(text for text, _ in line.parts()) + "…"
    widest = max(QFontMetricsF(heavy).horizontalAdvance(c) for c in said)
    for width in range(40, full + 1):
        line.resize(width, 20)
        line._elide()
        runs, drawn = _drawn(line)
        assert drawn <= width, (width, drawn, line.text())
        cut = line.text().endswith("…")
        assert cut == (width < full), (width, line.text())
        if cut:
            # Cut where the next letter would not fit, not sooner.
            assert width - drawn < widest, (width, drawn, line.text())
    line.resize(full - 1, 20)
    line._elide()
    assert any(heavy for _text, heavy in _drawn(line)[0]), "the cut kept the bold on what is left"


def test_a_changed_pill_is_bold_as_well_as_blue():
    """Every pill is drawn bold (`QLabel[class~="pill"]`), so a changed NORM is bold already; this
    holds it there beside the line's bold (tcc#108)."""
    from autosound_tcc.ui.tcc.theme import current_theme

    _app()
    tree = _themed(_compared_tree())
    pill = _row_of(tree, "physical_outputs", "m-R")._pill
    pill.ensurePolished()
    assert "chg" in pill.property("class").split()
    assert pill.font().bold()
    assert pill.palette().windowText().color().name() == current_theme().info


def test_the_tree_marks_exactly_the_cells_the_table_marks():
    """One comparison, two views: the tree reads the table's own rule, so they cannot disagree."""
    from autosound_tcc.ui.tcc import detail_pane
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    tree = _compared_tree()
    pane = DetailPane()
    pane.set_compare_choices(["v_006"], "v_006", lambda _v: _v_006())
    for group in _right_now().groups:
        pane.open_table(group)
        table = pane._scroll.widget()
        columns = detail_pane.table_fields(group)  # what `_build_table` draws, in its order
        for r in range(table.rowCount()):
            chan = _row_of(tree, group.id, table.item(r, 1).text())
            by_table = {f for c, f in enumerate(columns, start=2)
                        if table.item(r, c).data(detail_pane.CHANGED_ROLE) is True}
            assert chan.changed_fields() == by_table, (group.id, chan._row.name)


def test_a_changed_value_follows_a_theme_switch(monkeypatch):
    """tcc#122 (W-4's reviews of #104 and #108): the line writes the change's blue into its rich
    text, and a theme switch left it in the old theme's blue — on the light ground, the dark
    theme's pale azure — until the next resize or compare. The switch the window makes, on the
    application, re-cuts it."""
    from PySide6.QtGui import QPalette

    from autosound_tcc.ui.tcc import theme

    app = _app()
    monkeypatch.setattr(theme, "_CURRENT", theme._CURRENT)
    sheet, palette = app.styleSheet(), QPalette(app.palette())
    try:
        theme.apply_theme(app, "dark")
        tree = _compared_tree()
        line = _row_of(tree, "physical_outputs", "m-R")._line2
        line.resize(2000, 20)
        line._elide()
        dark, light = theme.get_theme("dark").info, theme.get_theme("light").info
        assert dark in line.text()

        theme.apply_theme(app, "light")
        assert light in line.text() and dark not in line.text(), line.text()
    finally:
        app.setStyleSheet(sheet)
        app.setPalette(palette)
