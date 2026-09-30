"""Sibling-name matching for the EQ pair (⇄ L+R) view — the two real naming conventions found in
actual ledgers: a bare trailing letter with no delimiter (`FrontL`/`FrontR`, the real virtual-
channel names) and a standalone word (`Front L Full`, the prototype's own convention)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from autosound_tcc.state.dsp_state import EqBand  # noqa: E402
from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.detail_pane import EqBandCard, _band_flow, _is_left, _sibling_name  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_sibling_name_bare_suffix():
    assert _sibling_name("FrontL") == "FrontR"
    assert _sibling_name("FrontR") == "FrontL"
    assert _sibling_name("w_L") == "w_R"
    assert _sibling_name("w_R") == "w_L"


def test_sibling_name_standalone_word():
    assert _sibling_name("Front L Full") == "Front R Full"
    assert _sibling_name("Front R Full") == "Front L Full"


def test_sibling_name_none_for_unpaired_channels():
    assert _sibling_name("Center") is None
    assert _sibling_name("Subwoofer") is None
    assert _sibling_name("RearATT") is None


def test_is_left():
    assert _is_left("FrontL") and not _is_left("FrontR")
    assert _is_left("w_L") and not _is_left("w_R")
    assert _is_left("Front L Full") and not _is_left("Front R Full")


def test_gain_mismatch_flags_the_gain_value_only():
    _app()
    band = EqBand(type="PK", freq_hz=8800.0, gain_db=1.0, q=1.4)
    card = EqBandCard(band, match_color="#5aa9e6", gain_mismatch=True)
    from PySide6.QtWidgets import QLabel

    labels = card.findChildren(QLabel)
    fv_labels = [lab for lab in labels if "band-fv" in (lab.property("class") or "")]
    # 3 value rows (Freq/Q/Gain) -- only Gain's gets the mismatch class.
    mismatch_labels = [lab for lab in fv_labels if lab.property("class") == "band-fv-mismatch"]
    assert len(mismatch_labels) == 1
    assert "1.0" in mismatch_labels[0].text()


def test_no_mismatch_uses_plain_gain_class():
    _app()
    band = EqBand(type="PK", freq_hz=8800.0, gain_db=1.0, q=1.4)
    card = EqBandCard(band, match_color="#5aa9e6", gain_mismatch=False)
    from PySide6.QtWidgets import QLabel

    assert not any(
        lab.property("class") == "band-fv-mismatch" for lab in card.findChildren(QLabel)
    )


def test_band_flow_marks_only_bands_at_mismatched_frequencies():
    _app()
    bands = (
        EqBand(type="PK", freq_hz=8800.0, gain_db=1.0, q=1.4),
        EqBand(type="PK", freq_hz=4050.0, gain_db=-2.0, q=2.0),
    )
    widget = _band_flow(bands, match_map={8800.0: "#5aa9e6", 4050.0: "#4bbf87"}, gain_mismatch_freqs={8800.0})
    cards = widget.findChildren(EqBandCard)
    assert len(cards) == 2


def test_the_pane_speaks_the_window_s_language():
    """"Table", "close ✕", "Channel" and "shared frequencies:" were English literals while both
    translations sat unused in the table — the pane had simply never registered for the language
    switch (found 2026-08-12)."""
    from PySide6.QtWidgets import QPushButton

    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup
    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    pane = DetailPane()
    group = ProfileGroup(
        id="virtual_channels", label="Virtual channels", fields=("gain_db",),
        rows=(GroupRow(id="v1", name="FrontL", raw={"gain_db": -1.0}, slot="A"),),
    )
    pane.open_table(group)
    try:
        i18n.set_language("uk")

        assert pane._tab_table.text() == i18n.t("tabTable")
        close = next(b for b in pane.findChildren(QPushButton)
                     if b.property("class") == "d-close")
        assert close.text() == i18n.t("close")
        table = pane._scroll.widget()
        assert table.horizontalHeaderItem(1).text() == i18n.t("colChan")
    finally:
        i18n.set_language("en")
    assert pane._tab_table.text() == "Table", "and back again"


def test_every_panel_survives_a_tier_whose_controls_nobody_enumerated():
    """`groups[].fields: null` is a state the method's schema added on 2026-08-23, and three
    widgets read that list directly. `"hp" in None` and `for f in None` both raise, so the first
    genuinely new DSP somebody onboards would have taken down the params table, the tree row and
    the group table at once -- weeks later, in a dialog, far from the profile that caused it.

    The group table also SAYS which state it is in: "—" means this channel has nothing set, and a
    tier nobody has enumerated is a different sentence.
    """
    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup
    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc.detail_pane import DetailPane
    from autosound_tcc.ui.tcc.group_table import GroupTable

    _app()
    group = ProfileGroup(
        id="physical_outputs", label="Output", fields=None,
        rows=(GroupRow(id="o1", name="w-L", raw={"gain_db": -1.0}, slot="C"),),
    )

    pane = DetailPane()
    pane.open_table(group)  # would have raised on `for f in group.fields`

    table = GroupTable()
    table.set_group(group)
    assert table.item(0, 2).text() == i18n.t("groupFieldsUnknown")

    stated = ProfileGroup(id="physical_outputs", label="Output", fields=(), rows=group.rows)
    table.set_group(stated)
    assert table.item(0, 2).text() == "—", "a channel with nothing set is not an unasked question"


def _rig_view():
    """A view with both tiers: virtual channels have no crossover, outputs have everything."""
    from autosound_tcc.state.dsp_state import ProjectView

    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "virtual_channels", "label": "Virtual channels",
         "fields": ["gain_db", "ta_ms", "phase_deg", "eq"]},
        {"id": "physical_outputs", "label": "Output channels",
         "fields": ["hp", "lp", "gain_db", "ta_ms", "phase_deg", "eq"]},
    ]}}
    ledger = {"preset": "FULL", "sample_rate": 96000,
              "channels": {"w-L": {"gain_db": -1.0, "ta_ms": 5.22},
                           "sw": {"gain_db": 0.0, "ta_ms": 0.0}},
              "virtual_channels": {"VFL": {"gain_db": 0.0, "ta_ms": 0.0}}}
    identities = {"w-L": {"code": "w-L", "slot": "C", "tier": "channels"},
                  "sw": {"code": "sw", "slot": "K", "tier": "channels"},
                  "VFL": {"code": "VFL", "slot": "A", "tier": "virtual_channels"}}
    return ProjectView.from_dict(ledger, profile, channels=identities)


def _param_columns(pane):
    """The per-tier tables of the parameter view, left to right."""
    from PySide6.QtWidgets import QTableWidget

    return pane._scroll.widget().findChildren(QTableWidget)


def test_one_parameter_across_both_tiers_side_by_side():
    """"Three buttons — Gain, Delay, Phase — that show the table for every channel, and it works
    for the physical ones as well as the virtual" (user, 2026-08-23), and then: "two columns,
    virtual beside output". Stacked, the second tier's heading was off screen by the time you
    reached it; the comparison the view exists for should be one glance."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    pane = DetailPane()
    pane.set_view(_rig_view())

    pane.open_param("ta_ms")

    tables = _param_columns(pane)
    assert len(tables) == 2, "one column per tier"
    read = [[[t.item(r, c).text() if t.item(r, c) else "" for c in range(3)]
             for r in range(t.rowCount())] for t in tables]
    assert [row[1] for row in read[0]] == ["VFL"]
    assert [row[1] for row in read[1]] == ["w-L", "sw"]
    assert [row[2] for row in read[1] if row[1] == "w-L"] == ["5.22"]


def test_a_control_no_tier_declares_is_not_offered():
    """A processor without phase does not get a Phase tab over an empty table."""
    from autosound_tcc.state.dsp_state import ProjectView
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "physical_outputs", "label": "Output", "fields": ["gain_db"]},
    ]}}
    view = ProjectView.from_dict(
        {"channels": {"w-L": {"gain_db": 0.0}}}, profile,
        channels={"w-L": {"code": "w-L", "slot": "C", "tier": "channels"}},
    )

    _app()
    pane = DetailPane()
    pane.set_view(view)

    assert pane._param_tabs["gain_db"].isVisibleTo(pane)
    assert not pane._param_tabs["phase_deg"].isVisibleTo(pane)
    pane.open_param("phase_deg")  # must not raise, and must not open anything
    assert pane._mode != "param"


def test_a_click_in_either_column_opens_that_column_s_channel():
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    pane = DetailPane()
    pane.set_view(_rig_view())
    pane.open_param("gain_db")

    activated = []
    pane.tableRowActivated.connect(lambda gid, rid: activated.append((gid, rid)))
    virtual, outputs = _param_columns(pane)
    virtual.cellClicked.emit(0, 1)
    outputs.cellClicked.emit(1, 1)

    assert activated == [("virtual_channels", "VFL"), ("physical_outputs", "sw")]


def test_a_nought_is_not_a_boost():
    """A column of green `+0.0` next to the two channels that actually carry gain read as if
    every channel had been lifted (user, 2026-08-23: "colours — nought in grey")."""
    from PySide6.QtGui import QColor

    from autosound_tcc.ui.tcc.detail_pane import DetailPane
    from autosound_tcc.ui.tcc.theme import current_theme

    _app()
    pane = DetailPane()
    pane.set_view(_rig_view())
    pane.open_param("gain_db")

    t = current_theme()
    outputs = _param_columns(pane)[1]
    by_name = {outputs.item(r, 1).text(): outputs.item(r, 2) for r in range(outputs.rowCount())}
    assert by_name["sw"].foreground().color() == QColor(t.faint), "0.0 dB is nothing set"
    assert by_name["w-L"].foreground().color() == QColor(t.accent), "-1.0 dB still reads as a cut"


def test_the_eq_copy_is_offered_only_when_a_format_exists(monkeypatch):
    """A button that copies nothing -- or something nobody can identify -- is worse than no
    button. The formats live in the method (user: "це повинно бути в скілі"), so when this
    installation has no exporter, the copy is not offered at all."""
    from autosound_tcc.core import eq_export
    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    pane = DetailPane()
    group = ProfileGroup(id="physical_outputs", label="Output", fields=("eq",),
                         rows=(GroupRow(id="w-L", name="w-L", slot="C",
                                        raw={"eq": [{"type": "PK", "f": 100,
                                                     "gain_db": -3.0, "q": 2.0}]}),))
    row = group.rows[0]

    monkeypatch.setattr(eq_export, "available", lambda: False)
    pane.open_eq(group, row)
    assert not pane._eq_copy.isVisibleTo(pane)

    monkeypatch.setattr(eq_export, "available", lambda: True)
    pane.open_eq(group, row)
    assert pane._eq_copy.isVisibleTo(pane)


def test_copying_a_bank_says_which_format_it_was_and_what_was_left_out(monkeypatch):
    """A band quietly dropped on the way to a processor is the kind of loss nobody notices until
    the tune sounds wrong, and a clipboard whose format cannot be named is a trap."""
    from PySide6.QtGui import QGuiApplication

    from autosound_tcc.core import eq_export
    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup
    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    pane = DetailPane()
    group = ProfileGroup(id="physical_outputs", label="Output", fields=("eq",),
                         rows=(GroupRow(id="w-L", name="w-L", slot="C",
                                        raw={"eq": [{"type": "PK", "f": 100,
                                                     "gain_db": -3.0, "q": 2.0}]}),))
    row = group.rows[0]
    monkeypatch.setattr(eq_export, "available", lambda: True)
    asked = {}

    def _fake(rows, **kw):
        asked.update(kw)
        return eq_export.Bank(text="BANK-TEXT", format_name="Audiotec-Fischer", written=8,
                              bank_size=30, left_out=("AP2 4386 Hz — this bank is EQ only",))

    monkeypatch.setattr(eq_export, "format_bank", _fake)
    said = []
    pane.bankCopied.connect(said.append)
    pane.open_eq(group, row)

    pane._on_copy_eq_bank()

    assert QGuiApplication.clipboard().text() == "BANK-TEXT"
    assert len(said) == 1
    assert "Audiotec-Fischer" in said[0] and "AP2 4386 Hz" in said[0]
    # The count and the bank size travel together: pasting a fixed-size bank writes its empty rows
    # over whatever those slots held, and "copied" does not say that.
    assert "8" in said[0] and "30" in said[0]
    # The tier and the channel's own crossovers go with the request -- whether a crossover belongs
    # in the block is the method's call, per tier, from the profile.
    assert asked["group_id"] == "physical_outputs"
    assert asked["channel"] == "w-L"
    assert set(asked["crossovers"]) == {"hp", "lp"}

    # And when there is no format, nothing plausible is put on the clipboard instead.
    monkeypatch.setattr(eq_export, "format_bank", lambda rows, **kw: None)
    QGuiApplication.clipboard().setText("untouched")
    pane._on_copy_eq_bank()
    assert QGuiApplication.clipboard().text() == "untouched"
    assert said[-1] == i18n.t("copyEqNoFormat")


def test_a_channel_with_nothing_to_export_is_not_offered_a_copy(tmp_path, monkeypatch):
    """`{"hp": None, "lp": None}` is what a virtual channel hands over, and a dict of empty legs
    is truthy — which would have produced a bank of thirty empty rows for a channel that has
    nothing in it, offered from the menu as if it did."""
    from autosound_tcc.core import eq_export

    monkeypatch.setattr(eq_export, "_profile", lambda: {"dsp_profile": {"vendor": "X"}})
    assert eq_export.format_bank([], crossovers={"hp": None, "lp": None}) is None
    assert eq_export.format_bank(None, crossovers=None) is None


def test_a_left_out_crossover_is_shown_as_a_filter_not_as_a_dict():
    """The method reports a refused crossover as the ledger structure it would not carry, which is
    right for it to hand over and wrong to show a person: the status line read
    `{'hp': {'f': 350.0, 'family': 'LinkwitzRiley', …}} — the Audiotec-Fischer bank is EQ only`."""
    from autosound_tcc.core import eq_export

    said = eq_export._said({
        "item": {"hp": {"f": 350.0, "type": "LR", "slope": 36, "family": "LinkwitzRiley"}},
        "why": "this bank is EQ only",
    })

    assert said.startswith("HP 350 LR36 —")
    assert "family" not in said and "{" not in said


def test_right_clicking_a_value_copies_it_with_no_menu_and_a_receipt():
    """"Right-click copies the one value, no question, with a hint saying what was copied"
    (user, 2026-08-23). A one-item menu is a question with one answer; and a copy with no feedback
    leaves you pressing again to be sure, which is how the number you wanted gets replaced by the
    one under it."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication

    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc.detail_pane import DetailPane
    from autosound_tcc.ui.tcc.rounded_tooltip import RoundedTooltip

    _app()
    pane = DetailPane()
    pane.set_view(_rig_view())
    pane.open_param("ta_ms")
    outputs = _param_columns(pane)[1]

    QGuiApplication.clipboard().setText("untouched")
    cell = outputs.visualItemRect(outputs.item(0, 2)).center()
    outputs.customContextMenuRequested.emit(cell)

    assert QGuiApplication.clipboard().text() == "5.22"
    assert RoundedTooltip.instance().text() == i18n.t("copiedValue").format(value="5.22")

    # An empty cell is not a copy, and does not clear what is already on the clipboard.
    outputs.customContextMenuRequested.emit(QPoint(-10, -10))
    assert QGuiApplication.clipboard().text() == "5.22"


def _pair_view():
    """A group with an L/R pair, each carrying its own bands."""
    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup

    return ProfileGroup(
        id="physical_outputs", label="Output", fields=("eq",),
        rows=(
            GroupRow(id="m-L", name="m-L", slot="E",
                     raw={"eq": [{"type": "PK", "f": 2551, "gain_db": -14.1, "q": 1.5}]}),
            GroupRow(id="m-R", name="m-R", slot="F",
                     raw={"eq": [{"type": "PK", "f": 215, "gain_db": -12.1, "q": 2.1}]}),
        ),
    )


def test_with_both_channels_on_screen_each_heading_carries_its_own_copy(monkeypatch):
    """"When the EQ of both channels is shown, remove the top button and add one after each
    channel's name" (user, 2026-08-23). One button over two banks names one of them."""
    from PySide6.QtGui import QGuiApplication

    from autosound_tcc.core import eq_export
    from autosound_tcc.ui.tcc.detail_pane import DetailPane, _DTab

    _app()
    monkeypatch.setattr(eq_export, "available", lambda: True)
    copied = []
    monkeypatch.setattr(
        eq_export, "format_bank",
        lambda rows, **kw: copied.append(kw["channel"]) or eq_export.Bank(
            text=f"BANK {kw['channel']}", format_name="Audiotec-Fischer", written=1),
    )
    pane = DetailPane()
    group = _pair_view()
    pane.open_eq(group, group.rows[0])
    assert pane._eq_copy.isVisibleTo(pane), "single channel: the header carries it"

    pane._on_pair_toggle()

    # Gone in pair mode (the Arbiter, 2026-09-25, on the passive one: «дублює сірим»): the copy is
    # beside each name.
    assert not pane._eq_copy.isVisibleTo(pane), "two channels: the header would name one of them"
    per_heading = [b for b in pane._scroll.widget().findChildren(_DTab)]
    assert len(per_heading) == 2
    per_heading[1].clicked.emit()
    assert QGuiApplication.clipboard().text() == "BANK m-R"
    assert copied[-1] == "m-R"


def test_the_eq_tab_says_whose_bank_is_on_screen(monkeypatch):
    """In the single view nothing on the left of the header named the channel: the only name was
    on the copy button, and the title that carries it sits greyed at the far end of the row."""
    from autosound_tcc.core import eq_export
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    monkeypatch.setattr(eq_export, "available", lambda: False)
    pane = DetailPane()
    group = _pair_view()

    pane.open_eq(group, group.rows[0])
    assert pane._tab_eq.text() == "EQ m-L"

    pane._on_pair_toggle()
    assert pane._tab_eq.text() == "EQ", "in pair mode each heading names its own"

    pane.open_table(group)
    assert pane._tab_eq.text() == "EQ", "and it is a plain tab when it is a way IN"


def test_a_copied_value_is_what_you_would_type():
    """"Copying a crossover should not carry the type — only the frequency, because the type does
    not paste" (user, 2026-08-23). It is a dropdown in the DSP's software, not a number field. The
    same rule settles the rest: no leading `+`, no degree sign, no units."""
    from autosound_tcc.state.dsp_state import GroupRow
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    row = GroupRow(id="m-L", name="m-L", slot="E", raw={
        "hp": {"f": 350.0, "type": "LR", "slope": 36},
        "lp": None,
        "gain_db": -1.0,
        "ta_ms": 6.3,
        "phase_deg": 180,
    })

    assert DetailPane._cell_text("hp", row).startswith("350 "), "the screen still reads the type"
    assert DetailPane._copy_value("hp", row) == "350"
    assert DetailPane._copy_value("lp", row) == "", "a disabled leg has no value to paste"
    assert DetailPane._copy_value("gain_db", row) == "-1"
    assert DetailPane._copy_value("ta_ms", row) == "6.3"
    assert DetailPane._copy_value("phase_deg", row) == "180"
    assert "°" not in DetailPane._copy_value("phase_deg", row)


def test_the_crossover_cell_copies_its_frequency_alone():
    from PySide6.QtGui import QGuiApplication

    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    group = ProfileGroup(
        id="physical_outputs", label="Output", fields=("hp", "lp", "gain_db"),
        rows=(GroupRow(id="m-L", name="m-L", slot="E",
                       raw={"hp": {"f": 350.0, "type": "LR", "slope": 36}, "gain_db": 0.0}),),
    )
    pane = DetailPane()
    pane.open_table(group)
    table = pane._scroll.widget()

    QGuiApplication.clipboard().setText("untouched")
    hp_cell = table.visualItemRect(table.item(0, 2)).center()
    table.customContextMenuRequested.emit(hp_cell)

    assert QGuiApplication.clipboard().text() == "350"



def _rig_view_changed():
    """`_rig_view` one version later: w-L's delay moved, sw's gain moved, VFL unchanged."""
    from autosound_tcc.state.dsp_state import ProjectView

    base = _rig_view()
    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": [
        {"id": "virtual_channels", "label": "Virtual channels",
         "fields": ["gain_db", "ta_ms", "phase_deg", "eq"]},
        {"id": "physical_outputs", "label": "Output channels",
         "fields": ["hp", "lp", "gain_db", "ta_ms", "phase_deg", "eq"]},
    ]}}
    ledger = {"preset": "FULL", "sample_rate": 96000,
              "channels": {"w-L": {"gain_db": -1.0, "ta_ms": 4.80},
                           "sw": {"gain_db": -2.0, "ta_ms": 0.0}},
              "virtual_channels": {"VFL": {"gain_db": 0.0, "ta_ms": 0.0}}}
    identities = {"w-L": {"code": "w-L", "slot": "C", "tier": "channels"},
                  "sw": {"code": "sw", "slot": "K", "tier": "channels"},
                  "VFL": {"code": "VFL", "slot": "A", "tier": "virtual_channels"}}
    assert base is not None
    return ProjectView.from_dict(ledger, profile, channels=identities)


def test_a_value_that_changed_since_the_compared_version_is_marked_with_what_it_was():
    """The Arbiter, 2026-09-23: the channel table offers «порівняти з» (the previous version by
    default), and what changed is visible."""
    from autosound_tcc.ui.tcc import detail_pane
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    pane = DetailPane()
    pane.set_view(_rig_view_changed())
    pane.set_compare_choices(["v_006", "v_005"], "v_006", lambda version: _rig_view())
    pane.open_param("ta_ms")

    outputs = _param_columns(pane)[1]
    cells = {outputs.item(r, 1).text(): outputs.item(r, 2) for r in range(outputs.rowCount())}
    assert cells["w-L"].data(detail_pane.CHANGED_ROLE) is True
    assert i18n.t("cmpWas").format(value="5.22") in cells["w-L"].toolTip()
    assert cells["sw"].data(detail_pane.CHANGED_ROLE) is not True, "its delay did not move"
    assert pane._compare_combo.currentData() == "v_006"

    pane._compare_combo.setCurrentIndex(pane._compare_combo.findData(None))
    outputs = _param_columns(pane)[1]
    assert all(outputs.item(r, 2).data(detail_pane.CHANGED_ROLE) is not True
               for r in range(outputs.rowCount())), "no comparison, nothing marked"


# ---- «Режим контролю» and the EQ view (the Arbiter, 2026-09-25: findings 47, 65, 66; tcc#51) ----

_PK = {"type": "PK", "f": 482, "gain_db": -1.7, "q": 3.0}


def _rig_with_eq(inputs: bool = False, empty_inputs: bool = False):
    """Both tiers (and inputs, when asked), EQ on VFL, c, m-L and m-R; m-L/m-R a pair, c alone."""
    from autosound_tcc.state.dsp_state import ProjectView

    groups = [
        {"id": "virtual_channels", "label": "Virtual channels",
         "fields": ["gain_db", "ta_ms", "phase_deg", "eq"]},
        {"id": "physical_outputs", "label": "Output channels",
         "fields": ["hp", "lp", "gain_db", "ta_ms", "phase_deg", "eq"]},
    ]
    ledger = {"preset": "FULL", "sample_rate": 96000,
              "channels": {"c": {"gain_db": -8.5, "eq": [_PK]},
                           "m-L": {"gain_db": -3.5, "eq": [_PK, dict(_PK, f=1250)]},
                           "m-R": {"gain_db": 0.9, "eq": [dict(_PK, f=320)]},
                           "sw": {"gain_db": 0.0}},
              "virtual_channels": {"VFL": {"gain_db": 0.0, "eq": [dict(_PK, f=100)]}}}
    identities = {"c": {"code": "c", "slot": "B", "tier": "channels"},
                  "m-L": {"code": "m-L", "slot": "E", "tier": "channels"},
                  "m-R": {"code": "m-R", "slot": "F", "tier": "channels"},
                  "sw": {"code": "sw", "slot": "K", "tier": "channels"},
                  "VFL": {"code": "VFL", "slot": "A", "tier": "virtual_channels"}}
    if inputs or empty_inputs:
        groups.append({"id": "inputs", "label": "Inputs", "fields": ["gain_db", "ta_ms"]})
    if inputs:
        ledger["inputs"] = {"IN1": {"gain_db": -2.0}}
        identities["IN1"] = {"code": "IN1", "slot": "1", "tier": "inputs"}
    profile = {"dsp_profile": {"name": "X", "vendor": "Y", "groups": groups}}
    return ProjectView.from_dict(ledger, profile, channels=identities)


def _grp(view, gid):
    return next(g for g in view.groups if g.id == gid)


def _row(group, name):
    return next(r for r in group.rows if r.name == name)


def _menu(pane):
    return [pane._tab_table, pane._tab_eq, pane._close_btn, pane._compare_combo,
            pane._compare_label, *pane._param_tabs.values()]


def test_an_embedded_pane_carries_no_menu_of_its_own():
    """Finding 47, 1 and 3: in control mode the tabs above ARE the navigation; the pane's own
    Table · EQ · Level · Delays · Phases row and its «Закрити ✕» came back on every render."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    view = _rig_with_eq()
    outputs = _grp(view, "physical_outputs")
    pane = DetailPane()
    pane.set_embedded(True)
    pane.set_view(view)
    for show in (lambda: pane.open_table(outputs), lambda: pane.open_param("gain_db"),
                 lambda: pane.open_eq(outputs, _row(outputs, "m-L"))):
        show()
        assert not [w for w in _menu(pane) if w.isVisibleTo(pane)], "no menu inside a tab"


def test_an_embedded_table_asks_for_the_eq_tab_instead_of_turning_into_it():
    """Finding 47, 5: «1 band ▸» turned the table tab into the EQ view with no way back."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    view = _rig_with_eq()
    outputs = _grp(view, "physical_outputs")
    pane = DetailPane()
    pane.set_embedded(True)
    pane.set_view(view)
    pane.open_table(outputs)
    asked = []
    pane.eqRequested.connect(lambda gid, rid: asked.append((gid, rid)))
    names = [r.name for r in outputs.rows_visible()]
    pane._scroll.widget().cellClicked.emit(names.index("m-L"), 1)
    QApplication.processEvents()
    assert asked == [("physical_outputs", "m-L")]
    assert pane._mode == "table", "the table stays a table"


def test_the_full_window_s_way_back_is_its_table_tab_not_a_second_button():
    """The control tabs name the way back («← Таблиця-О»); the full window's pane has «Таблиця»
    right beside the EQ, and its head has no room for the same way twice."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    view = _rig_with_eq()
    outputs = _grp(view, "physical_outputs")
    pane = DetailPane()
    pane.set_view(view)
    pane.open_table(outputs)
    names = [r.name for r in outputs.rows_visible()]
    pane._scroll.widget().cellClicked.emit(names.index("m-L"), 1)
    QApplication.processEvents()
    assert pane._mode == "eq" and pane._row.name == "m-L"
    assert not pane._back_btn.isVisibleTo(pane)
    assert pane._tab_table.isVisibleTo(pane)
    pane._tab_table.clicked.emit()
    assert pane._mode == "table"


def test_the_back_button_says_where_it_leads_and_goes_there():
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    view = _rig_with_eq()
    outputs = _grp(view, "physical_outputs")
    pane = DetailPane()
    pane.set_embedded(True)
    pane.set_view(view)
    went = []
    pane.set_back("← Таблиця-О", lambda: went.append(1))
    pane.open_eq(outputs, _row(outputs, "m-L"))
    assert pane._back_btn.isVisibleTo(pane) and pane._back_btn.text() == "← Таблиця-О"
    pane._back_btn.clicked.emit()
    assert went == [1]
    assert not pane._back_btn.isVisibleTo(pane)


def test_the_tiers_are_pickers_in_the_eq_header():
    """Finding 71, 6, and the Arbiter's look at it: «Virtual: / Output: / Input:» written out, wide
    fields that do not jump, the actions at the end of the row, no grey doubles."""
    from PySide6.QtCore import Qt

    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    view = _rig_with_eq(inputs=True)
    outputs = _grp(view, "physical_outputs")
    pane = DetailPane()
    pane.set_embedded(True)
    pane.set_view(view)
    pane.open_eq(outputs, _row(outputs, "m-L"))
    texts = {gid: p.text() for gid, p in pane._tier_pickers.items()}
    assert texts == {"virtual_channels": "Virtual: VFL", "physical_outputs": "Output: m-L",
                     "inputs": "Input: -"}, "single: one name"
    picker = pane._tier_pickers["physical_outputs"]
    assert picker.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon, \
        "the name shows beside the dot (an icon alone hid it)"
    assert pane._head.isAncestorOf(picker), "in the header row"
    assert "on" in picker.property("class").split()
    assert pane._tier_status["virtual_channels"] == "set"
    checked = [a.text() for a in picker.menu().actions() if a.isChecked()]
    assert checked == ["m-L (2/2)"], "single: one channel marked, not the pair"
    head = pane._head.layout()
    assert head.indexOf(pane._pick_holder) < head.indexOf(pane._eq_copy) < \
        head.indexOf(pane._pair_btn) < head.indexOf(pane._eq_help), \
        "the actions close the row; copy before the pair, so the pair does not move when copy goes"
    assert not pane._title.isVisibleTo(pane), "the lit field already says which EQ"
    # The row's ASKED width, not the assigned `.width()` (tcc#96, finding 105): the picker can
    # now genuinely shrink when the header has no room to spare, which changes what it is GIVEN
    # -- «nothing jumps» means it does not ask for more or less depending on which channel is
    # picked, and `sizeHint` is where that is decided (`_TierPickButton.set_preferred_width`).
    width = picker.sizeHint().width()

    pane._on_pair_toggle()
    picker = pane._tier_pickers["physical_outputs"]
    assert picker.text() == "Output: m-L/m-R"
    assert picker.sizeHint().width() == width, "the field asks for its width: nothing jumps"
    assert pane._tier_pickers["inputs"].text() == "Input: -/-"

    menu = pane._tier_pickers["virtual_channels"].menu()
    pick = next(a for a in menu.actions() if a.text().startswith("VFL"))
    pick.trigger()
    QApplication.processEvents()
    assert pane._row.name == "VFL"
    assert "on" in pane._tier_pickers["virtual_channels"].property("class").split()
    assert pane._tier_pickers["physical_outputs"].text() == "Output: m-L/m-R", "each keeps its pick"
    pane.open_eq(outputs, _row(outputs, "m-R"))
    assert pane._tier_pickers["physical_outputs"].text() == "Output: m-L/m-R", "L first"


def test_pair_mode_survives_a_channel_that_has_no_pair():
    """«Коли включив парний режим і вибрав не парний драйвер, то повертаючись до парного — знову
    бачу пару» (the Arbiter, 2026-09-25): it used to switch itself off."""
    from PySide6.QtWidgets import QLabel

    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    view = _rig_with_eq()
    outputs = _grp(view, "physical_outputs")
    pane = DetailPane()
    pane.set_view(view)

    def headings():
        return [w for w in pane._scroll.widget().findChildren(QLabel)
                if w.property("class") == "eq-rowlab"]

    pane.open_eq(outputs, _row(outputs, "m-L"))
    pane._on_pair_toggle()
    assert len(headings()) == 2
    pane.open_eq(outputs, _row(outputs, "c"))
    assert not pane._pair_btn.isVisibleTo(pane) and not headings()
    pane.open_eq(outputs, _row(outputs, "m-L"))
    assert len(headings()) == 2, "back on a pair, the pair is shown again"


def test_a_moved_band_marks_the_eq_cell_even_with_the_same_count():
    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup
    from autosound_tcc.ui.tcc import detail_pane
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()

    def outputs(gain):
        return ProfileGroup(id="physical_outputs", label="Output", fields=("eq",), rows=(
            GroupRow(id="m-L", name="m-L", slot="E", raw={"eq": [dict(_PK, gain_db=gain)]}),))

    before = type("V", (), {"groups": (outputs(-2.7),)})()
    pane = DetailPane()
    pane.set_compare_choices(["v_006"], "v_006", lambda _v: before)
    pane.open_table(outputs(-1.7))
    cell = pane._scroll.widget().item(0, 2)
    assert cell.data(detail_pane.CHANGED_ROLE) is True


def test_level_delays_and_phases_take_a_third_column_for_the_inputs():
    """«Рівень, затримки, фази можуть мати 3 стовпчики (ще Вхідні), коли вони всі є»."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    pane = DetailPane()
    pane.set_view(_rig_with_eq(inputs=True))
    pane.open_param("gain_db")
    assert len(_param_columns(pane)) == 3



# ---- the band card, second pass (hub #211 PAS-011, #209 PAS-009, findings 68, 69; tcc#52) ------

def test_the_card_names_its_dsp_band_in_brackets():
    from autosound_tcc.ui.tcc.detail_pane import EqBandCard

    _app()
    numbered = EqBandCard(EqBand(type="PK", freq_hz=114.0, gain_db=-10, q=5, index=4))
    bare = EqBandCard(EqBand(type="PK", freq_hz=114.0))
    assert numbered._title.text() == "PK (4)"
    assert bare._title.text() == "PK", "no number, none"


def test_the_filter_type_has_a_colour_of_its_own():
    """Finding 69: green a shelf, blue PK, yellow APF."""
    from autosound_tcc.ui.tcc.detail_pane import EqBandCard

    _app()
    cards = {t: EqBandCard(EqBand(type=t, freq_hz=100.0)) for t in ("LSH", "HSH", "PK", "APF")}
    kinds = {t: card._title.property("class") for t, card in cards.items()}
    assert kinds == {"LSH": "band-id band-shelf", "HSH": "band-id band-shelf",
                     "PK": "band-id band-pk", "APF": "band-id band-apf"}


def test_a_bypassed_band_says_so_and_an_old_band_without_the_field_is_on():
    """PAS-009: the card drew the same «○ ByPass» on every band. And (the Arbiter, the same day):
    old files carry no `bypass` on some bands; there the band is on."""
    from autosound_tcc.ui.tcc.detail_pane import EqBandCard

    _app()
    off = EqBandCard(EqBand.from_dict({"type": "PK", "f": 100, "bypass": True, "i": 2}))
    old = EqBandCard(EqBand.from_dict({"type": "PK", "f": 100, "i": 3}))
    assert "on" in off._byp.property("class").split() and off._byp.text().startswith("●")
    assert "on" not in old._byp.property("class").split() and old._byp.text().startswith("○")


def test_the_fields_follow_the_processor_s_own_order():
    """Finding 68: a Helix reads Freq · Gain · Q (PC-Tool), a MUSWAY Freq · Q · Gain."""
    from autosound_tcc.ui.tcc.detail_pane import EqBandCard, eq_field_order

    _app()
    band = EqBand(type="PK", freq_hz=114.0, gain_db=-10, q=5)
    helix = EqBandCard(band, order=eq_field_order("Audiotec-Fischer", "Helix DSP Ultra S"))
    musway = EqBandCard(band, order=eq_field_order("MUSWAY", "M6v8"))
    assert helix.field_names() == ["Freq", "Gain", "Q"]
    assert musway.field_names() == ["Freq", "Q", "Gain"]


def test_cards_follow_the_band_numbers_and_an_empty_slot_draws_nothing():
    """PAS-011: ordered by the DSP's band number; a gap shows in the numbering, not as a card."""
    from autosound_tcc.ui.tcc.detail_pane import EqBandCard

    _app()
    flow = _band_flow((EqBand(type="PK", freq_hz=700.0, gain_db=-1.0, q=2.0, index=7),
                       EqBand(type="PK", freq_hz=100.0, gain_db=-1.0, q=2.0, index=1),
                       EqBand(type="OFF", freq_hz=0.0, index=2),
                       EqBand(type="LSH", freq_hz=60.0, gain_db=2.0, q=0.7, index=3)))
    assert [c._title.text() for c in flow.findChildren(EqBandCard)] == ["PK (1)", "LSH (3)", "PK (7)"]


def test_the_copies_beside_the_names_look_active(monkeypatch):
    """Finding 67, 4, then «дублює сірим»: the header's copy is gone in pair mode, and the ones
    beside each name are accent buttons."""
    from autosound_tcc.core import eq_export
    from autosound_tcc.ui.tcc.detail_pane import DetailPane, _DTab

    _app()
    monkeypatch.setattr(eq_export, "available", lambda: True)
    pane = DetailPane()
    group = _pair_view()
    pane.open_eq(group, group.rows[0])
    pane._on_pair_toggle()
    beside = pane._scroll.widget().findChildren(_DTab)
    assert beside and all("d-copy" in b.property("class").split() and b.isEnabled() for b in beside)
    assert not pane._eq_copy.isVisibleTo(pane)


def test_the_compare_list_is_wide_enough_for_whole_lines():
    """Finding 67, 2: the open list wrapped «2.S-shelf — інший пресет» / «v_001»."""
    from PySide6.QtWidgets import QComboBox

    from autosound_tcc.ui.tcc.detail_pane import fill_compare_combo

    _app()
    combo = QComboBox()
    fill_compare_combo(combo, ["v_006"], {"v_006": "v_006 · FULL-2"},
                       [("2.S-shelf", [("2.S-shelf/v_001", "v_001 · 2.S-shelf")])])
    view = combo.view()
    assert view.minimumWidth() >= view.sizeHintForColumn(0)


# ---- narrow-window head chips (tcc#96, finding 105) ----------------------------------------------

def test_a_dtab_elides_instead_of_relying_on_a_width_it_never_had():
    """tcc#96, finding 105: in a small control-mode window the head's own tabs and chips -- «⇅
    Порівняти», «Копіювати EQ …» (both `_DTab`s) -- came back cut mid-word, no «…» anywhere
    («⇅ П», «Копі», the Arbiter's screenshot). Given real room, nothing is touched at all; given
    none, it ends in «…», never a bare cut. `.text()` stays the real string either way -- only
    `fit_text()` (what `paintEvent` actually draws) shortens."""
    from autosound_tcc.ui.tcc.detail_pane import _DTab

    _app()
    long = "Копіювати EQ m-Left-Tweeter-Front"
    tab = _DTab(long)
    # Room for «…» and two letters past the tab's own padding (`_squeezed`), not 40 px: the room
    # is judged inside the chrome now, and 40 px held less than «К…» in the runner's wide text.
    tab.resize(_squeezed(tab), 22)
    shown = tab.fit_text()
    assert shown != long and shown.endswith("…"), shown
    # And never nothing, whatever the room (CI at 467c655: the runner's fontless text handed
    # back «» here): the floor's «К…», clipped if it must be.
    tab.resize(4, 22)
    assert tab.fit_text() == long[:1] + "…", tab.fit_text()
    assert not long.startswith(shown[:-1]) or len(shown) < len(long), "genuinely shortened"
    assert tab.text() == long, "the real text never changes -- only what is painted"

    tab.resize(2000, 22)
    assert tab.fit_text() == long, "with room to spare nothing is cut at all"


def _squeezed(widget) -> int:
    """A width that leaves the widget room for «…» and two letters past its own chrome: narrow
    in any font. A fixed 40 or 60 px was narrow on the Mac and below the chrome on the Windows
    runner, whose offscreen text is twice as wide (Qt's FreeType font database finds no fonts
    there and draws every glyph as wide as the pixel size), where `fit_text()` came back empty
    (fix round 5, CI run 36623891341)."""
    from autosound_tcc.ui.tcc.detail_pane import _TierPickButton

    metrics = widget.fontMetrics()
    if isinstance(widget, _TierPickButton):
        return widget.minimumSizeHint().width() + metrics.horizontalAdvance("xx")
    chrome = widget.sizeHint().width() - metrics.horizontalAdvance(widget.text())
    return chrome + metrics.horizontalAdvance("…xx")


def test_the_tier_chip_elides_instead_of_getting_clipped_past_its_row():
    """tcc#96, finding 105: «Output: c» -- the tier picker's chip (`_fill_pickers`) used to be a
    FIXED-width `QToolButton` the layout could never shrink; a header with no room for it just
    ran it past its own edge and clipped it there, which read as the text itself failing to fit.
    Given a width narrower than its own preferred one, its text elides instead."""
    from autosound_tcc.ui.tcc.detail_pane import _TierPickButton

    _app()
    button = _TierPickButton()
    button.setText("Output: m-Left-Tweeter-Front")
    button.set_preferred_width(button.width_for(button.text()))
    button.resize(_squeezed(button), 22)
    shown = button.fit_text()
    assert shown != button.text() and shown.endswith("…"), shown

    button.resize(button.sizeHint().width(), 22)
    assert button.fit_text() == button.text(), "at its own preferred width, nothing is cut"


def test_the_tier_chip_s_preferred_width_holds_its_text_whatever_it_was_given():
    """CI at f9d3a9e, windows-latest: at its own preferred width the chip read
    «Output: m-Left-Tweeter-Fro…». The width it was given was the text's width plus a guessed 60
    px of chrome (40 in `_fill_pickers`), and on the runner's fontless offscreen text the chrome
    is more than that. Its preferred width now holds its own text whole -- the chrome measured,
    the text's width rounded up from its fractions -- however little it was told, so it never
    elides at its own size on any font engine. Given too little on purpose here: the text's width
    alone, no chrome at all."""
    from autosound_tcc.ui.tcc.detail_pane import _TierPickButton

    _app()
    button = _TierPickButton()
    button.setText("Output: m-Left-Tweeter-Front")
    button.set_preferred_width(button.fontMetrics().horizontalAdvance(button.text()))
    button.resize(button.sizeHint().width(), 22)
    assert button.fit_text() == button.text(), (button.sizeHint().width(), button.fit_text())


def test_a_real_pane_s_chips_elide_the_same_way_when_squeezed():
    """The mechanism above, wired up in `DetailPane` itself: `_cmp_btn`, `_eq_copy` and the tier
    picker (`_fill_pickers`) all reachable through the pane the Arbiter actually saw, not just the
    classes in isolation."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    view = _rig_with_eq(inputs=True)
    outputs = _grp(view, "physical_outputs")
    pane = DetailPane()
    pane.set_embedded(True)
    pane.set_view(view)
    pane.open_eq(outputs, _row(outputs, "m-L"))

    for widget in (pane._cmp_btn, pane._eq_copy, pane._tier_pickers["physical_outputs"]):
        full = widget.text()
        widget.resize(_squeezed(widget), widget.height() or 22)
        shown = widget.fit_text()
        # The EQ's actions come down to their glyph (the review of the follow-up): «⇅» where
        # Qt's elision would have drawn «…» alone.
        assert shown == full or shown.endswith("…") or shown == full[:1], (widget, full, shown)
        assert widget.text() == full, "resizing alone never rewrites the real text"


def _combo_shows_whole(combo) -> bool:
    """Whether a closed list draws its current text whole: the style's edit field holds it."""
    from PySide6.QtGui import QFontMetricsF
    from PySide6.QtWidgets import QStyle, QStyleOptionComboBox

    option = QStyleOptionComboBox()
    combo.initStyleOption(option)
    field = combo.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                         QStyle.SubControl.SC_ComboBoxEditField, combo)
    return QFontMetricsF(combo.font()).horizontalAdvance(combo.currentText()) <= field.width() - 2


def _at_its_floor(label) -> bool:
    """Whether a `_FitLabel` has been given its floor, and shows a glyph or two and «…» there
    (the whole of a text no wider than that). Judged by the width, not the glyphs: a bordered
    label's contents rect is a little wider than its text's room, and «ін…» fits where «і…»
    was measured."""
    shown = label.fit_text()
    return label.width() == label.floor_width() and (
        shown == label.text() or (shown.endswith("…") and len(shown) <= 3))


def _arbiter_head(window, view: str):
    """The Arbiter's head over `view` -- "table", "eq_single" or "eq_pair": «порівняти з», the
    list and the «інша конфігурація» tag up (another configuration's version picked); the EQ
    views over m-L, one channel with «⇅ Порівняти» and «Копіювати EQ m-L» shown, or the pair
    with «⇄ L + R» on (finding 105's second screenshot was the EQ view). Returns the pane."""
    from tests import test_control_layout as tcl

    rig = tcl._with_rig(window)
    pane = window._detail
    pane.set_view(rig)
    window._on_table_requested("physical_outputs")
    pane.set_compare_choices(["v_002", "v_001"], "3.S-shelf/v_002", lambda _k: tcl._older(),
                             {"v_002": "v_002", "v_001": "v_001"},
                             [(p, [(f"{p}/v_002", "v_002")]) for p in tcl._OTHERS],
                             "4.C-cut", "v_002")
    if view != "table":
        outputs = _grp(rig, "physical_outputs")
        pane.open_eq(outputs, _row(outputs, "m-L"))
        if view == "eq_pair":
            pane._on_pair_toggle()
    return pane


def _head_words(pane) -> list:
    """The head's words the owner shows: the tabs, the EQ's actions, the title, the «?», the
    compare label and tag, «закрити ✕» -- what `fit_text` is asked of."""
    from autosound_tcc.ui.tcc.detail_pane import _FitLabel

    layout = pane._head.layout()
    words = [layout.itemAt(i).widget() for i in range(layout.count())]
    return [w for w in words if isinstance(w, _FitLabel) and w.wanted()
            or w is pane._close_btn and w.isVisibleTo(pane._head)]


def _reads(widget) -> bool:
    """Whole, elided to «…», or -- a chip with a glyph floor -- its glyph: never nothing."""
    shown = widget.fit_text()
    return bool(shown) and (shown == widget.text() or shown.endswith("…")
                            or (getattr(widget, "_floor", "") == "glyph"
                                and shown == widget.text()[:1]))


def _floors_hold(pane) -> None:
    box, close = pane._compare_combo, pane._close_btn
    assert box.width() >= box.minimumSizeHint().width() and _combo_shows_whole(box), \
        (box.width(), box.minimumSizeHint().width(), box.currentText())
    assert close.fit_text() == close.text(), close.fit_text()


@pytest.mark.parametrize("view", ["table", "eq_single"])
def test_the_full_window_s_head_gives_way_in_stages(tmp_path, monkeypatch, view):
    """tcc#96, fix round 5 -- the Arbiter on the Windows VM (wave-0.1.45 at 1ee915b): the full
    window's head at full screen width read «Табл…», an empty «EQ», «Рів…», «Затри…», «Ф…» and
    «закрит…» with the pane 840 px wide, and «порівняти з», the box and «інша конфігурація»
    whole beside them; at two thirds of the screen every tab was empty. The first pass gave
    each tab a 24-px floor, and a box layout takes what it is short of equally from the items
    that can shrink -- the tabs were the only ones, down to nothing to draw.

    The re-review (finding 119): holding the tabs and the labels raised the head's minimum to
    803 px, and a pane narrower than that had Qt trim the widest items to one width: the compare
    box came down to 63 of its 121 px and read «v_», then nothing. The head gives way in an
    order now (`DetailPane._fit_head`, `head_asks`): the title first; then «порівняти з», the
    tag and the EQ's «?», whole or hidden (the review of the follow-up: «п…» said nothing and
    cost 64 px); then the tabs and the list, each to its floor -- a tab to a glyph and «…», an
    EQ action to its glyph, the list to «v_NNN» -- with the row's gaps tightened, never to
    nothing; «закрити ✕» keeps its floor throughout. The pane is put at each width by the
    splitter's handle, as the Arbiter would; the widths are the head's own asks, so no number
    here is a Mac pixel. Over the table and over one channel's EQ."""
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.detail_pane import _HEAD_SPACING, _HEAD_SPACING_TIGHT
    from tests import test_control_layout as tcl

    window = tcl._window(tmp_path, monkeypatch)
    i18n.set_language("uk")
    try:
        window.show()
        pane = _arbiter_head(window, view)
        head, box, close = pane._head, pane._compare_combo, pane._close_btn
        tabs = [pane._tab_table, pane._tab_eq, *pane._param_tabs.values()]
        labels = [pane._compare_label, pane._compare_other]
        hidden_when_short = [*labels] + ([pane._eq_help] if view != "table" else [])
        actions = [a for a in (pane._cmp_btn, pane._eq_copy, pane._pair_btn) if a.wanted()]
        assert all(w.wanted() for w in (*tabs, *hidden_when_short))
        assert (len(actions) == 3) == (view == "eq_single"), [a.text() for a in actions]

        def settle(width):
            window.resize(width, 900)
            for _ in range(5):
                QApplication.processEvents()

        def centre(width):
            """The pane `width` px wide by the splitter's handle, the window as it is."""
            splitter = window._main_splitter
            sizes = splitter.sizes()
            splitter.setSizes([sizes[0], width, sum(sizes) - sizes[0] - width])
            for _ in range(5):
                QApplication.processEvents()
            assert pane.width() == width, (pane.width(), width, splitter.sizes())

        def cut():
            return [(w.text(), w.fit_text()) for w in _head_words(pane)
                    if w.isVisibleTo(head) and w.fit_text() != w.text()]

        def shown(widgets):
            return [w.isVisibleTo(head) for w in widgets]

        whole, title_gone, labels_gone, least = pane.head_asks()
        frame = pane.width() - head.width()
        roomy = 2000
        settle(roomy)
        while pane.width() < whole + frame + 40 and roomy < 8000:
            roomy += 200
            settle(roomy)
        assert pane.width() >= whole + frame, (pane.width(), whole)
        assert cut() == [] and all(shown(hidden_when_short)), "roomy: everything whole"
        assert head.layout().spacing() == _HEAD_SPACING
        if view == "table":
            # A pane a little short of the head's ask: the title gives way, nothing else does.
            centre((whole + title_gone) // 2 + frame)
            title = pane._title.fit_text()
            assert title != pane._title.text() and title.endswith("…"), title
            assert cut() == [(pane._title.text(), title)], cut()
            assert all(shown(hidden_when_short))
            _floors_hold(pane)
        # Shorter: the title has given all it had; the labels and the «?» go, whole or hidden.
        centre((title_gone + labels_gone) // 2 + frame)
        assert not any(shown(hidden_when_short)) and all(w.wanted() for w in hidden_when_short)
        if view == "table":
            assert _at_its_floor(pane._title), (pane._title.fit_text(), pane._title.width())
        assert all(w.fit_text() == w.text() for w in (*tabs, *actions)), cut()
        _floors_hold(pane)
        # Shorter still: the tabs, the actions and the list give, the gaps tighten -- never to
        # nothing, and the list and «закрити ✕» whole.
        centre((labels_gone + least) // 2 + frame)
        assert any(t.fit_text() != t.text() for t in tabs), cut()
        assert all(_reads(w) for w in (*tabs, *actions)), cut()
        assert head.layout().spacing() == _HEAD_SPACING_TIGHT
        assert box.width() >= box.floor_width() and _combo_shows_whole(box), box.width()
        assert close.fit_text() == close.text()
        assert head.minimumSizeHint().width() == least, "the head's minimum: all three giving"
        settle(roomy)
        centre(whole + frame + 40)
        assert cut() == [] and all(shown(hidden_when_short)), "roomy again: everything whole"
    finally:
        i18n.set_language("en")


# Every view on the Arbiter's screen; on the VM's, the EQ views its finding was about -- the
# table's head was sound there, and on 1920 it has more room still (F-065).
@pytest.mark.parametrize(("view", "screen"), [("table", 1512), ("eq_single", 1512),
                                              ("eq_pair", 1512), ("eq_single", 1920),
                                              ("eq_pair", 1920)])
def test_the_head_reads_at_the_full_window_s_floor(tmp_path, monkeypatch, view, screen):
    """The review of the follow-up (CRITICAL): the head's stages were sound over a table, and
    the EQ view's head -- «EQ m-L», «⇄ L + R», «⇅ Порівняти», «Копіювати EQ m-L» -- had a
    minimum of 717 px against the centre's floor of 588 on the Arbiter's 1512-px screen (two
    thirds of it, less the sides, tcc#106), so at the full window's floor Qt trimmed the widest
    items: the box got 42 of 121 px and drew empty, «закрити ✕» read «за…» -- finding 105's
    second screenshot exactly; the pair view 611 against 588; at the Windows VM's twice-as-wide
    text 1039 against 860 on 1920. The head's minimum is inside the centre's floor now: the
    compare labels and the «?» whole or hidden, the EQ's actions down to their glyph and their
    hover, the list's floor «v_NNN» (its real shortest content, not six letters), the gaps
    tightened. At the window's floor on the Arbiter's screen and on the VM's: nothing empty,
    nothing clipped, the list and «закрити ✕» whole. A font too wide for a screen -- the
    runner's twice-as-wide text on 1512 -- says so in its numbers."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc import main_window
    from tests import test_control_layout as tcl

    window = tcl._window(tmp_path, monkeypatch)
    i18n.set_language("uk")
    try:
        monkeypatch.setattr(main_window, "_screen_room", lambda _w: QRect(0, 0, screen, 982))
        window.show()
        pane = _arbiter_head(window, view)
        head, box, close = pane._head, pane._compare_combo, pane._close_btn
        window._fit_centre_floor()
        for _ in range(4):
            window.resize(window.minimumWidth(), 900)
            for _ in range(4):
                QApplication.processEvents()
            if window.width() == window.minimumWidth():
                break
        least = pane.head_asks()[-1]
        if head.width() < least:
            pytest.skip(f"in this font the head's minimum over {view} ({least} px) is more than "
                        f"the centre's floor on a {screen}-px screen "
                        f"({window._center.minimumWidth()}): Qt trims the head there")
        assert head.minimumSizeHint().width() <= head.width(), "nothing for Qt to trim"
        words = [w for w in _head_words(pane) if w.isVisibleTo(head)]
        assert words, "the head has words"
        for widget in words:
            assert _reads(widget), (widget.text(), widget.fit_text(), widget.width())
        assert close.fontMetrics().horizontalAdvance(close.fit_text()) <= \
            close.width() - close._chrome(), (close.fit_text(), close.width())
        _floors_hold(pane)
        assert box.currentText() == "v_002" and box.fit_text() == "v_002"
    finally:
        i18n.set_language("en")


def test_a_head_label_reads_whole_at_its_hint_and_never_nothing_at_its_floor():
    """`_FitLabel` (tcc#96, fix round 5): its hint is rounded UP from the text's fractional width
    and the fit judged in fractions (F-045: a whole-pixel hint one fraction short read «Control
    mo…» with room to spare), and its floor is its first glyph and «…» -- never nothing, as the
    old 24-px floor gave. The re-review found both unguarded: reverting either left every test
    green. Every UI string on a tab, at its own hint: whole; at its floor: a glyph and «…». And
    the three ways a label meets a short row (`set_way`): the hint and the floor each way."""
    from autosound_tcc.ui.tcc.detail_pane import _DTab

    _app()
    texts = sorted({text for lang in ("en", "uk") for text in i18n.T[lang].values()
                    if 1 < len(text) <= 40 and "\n" not in text and "{" not in text})
    tab = _DTab("x")
    tab.show()
    cut, nothing = [], []
    try:
        for text in texts:
            tab.setText(text)
            whole, floor = tab.whole_width(), tab.floor_width()
            assert 0 < floor <= whole
            for way, hint, least in (("holds", whole, whole), ("gives", whole, floor),
                                     ("floor", floor, floor)):
                tab.set_way(way)
                assert (tab.sizeHint().width(), tab.minimumSizeHint().width()) == (hint, least), \
                    (text, way)
            tab.set_way("gives")
            tab.resize(whole, 22)
            if tab.fit_text() != text:
                cut.append(f"{text!r} -> {tab.fit_text()!r}")
            tab.resize(floor, 22)
            shown = tab.fit_text()
            if not shown or not (shown == text or shown.endswith("…")):
                nothing.append(f"{text!r} -> {shown!r}")
    finally:
        tab.close()
    assert not cut, f"{len(cut)} of {len(texts)} cut at their own hint, e.g. " + "; ".join(cut[:3])
    assert not nothing, f"{len(nothing)} read nothing at their floor, e.g. " + "; ".join(nothing[:3])

    # A chip with a glyph floor («⇄ L + R», the EQ's actions): the glyph at its floor, with the
    # whole text in its hover; and the hidden way keeps the owner's wish apart from the fit's.
    chip = _DTab("⇄ L + R", floor="glyph")
    chip.show()
    try:
        chip.set_way("gives")
        chip.resize(chip.floor_width(), 22)
        assert chip.fit_text() == "⇄" and chip.toolTip() == "⇄ L + R", chip.fit_text()
        dotted = _DTab("⇄ L + R")
        dotted.show()  # polished like the chip: the same sheet's margins in both floors
        try:
            assert chip.floor_width() < dotted.floor_width(), "narrower than «⇄…»"
        finally:
            dotted.close()
        chip.set_way("hidden")
        assert not chip.isVisible() and chip.wanted()
        chip.setVisible(True)
        assert not chip.isVisible() and chip.wanted(), "the owner's wish waits for the fit"
        chip.set_way("gives")
        assert chip.isVisible()
        chip.setVisible(False)
        chip.set_way("holds")
        assert not chip.isVisible() and not chip.wanted(), "the owner's own hiding stands"
    finally:
        chip.close()


def test_a_control_mode_tab_s_chips_give_way_where_the_full_window_s_tabs_hold():
    """Finding 105 (a chip «Копі» cut in control mode) against finding 119 (the tabs cut in the
    full window): inside a control-mode tab every chip gives way, down to a glyph and «…»; in
    the full window with the room for them the tabs hold their words as their floor. The
    re-review found the embedded half unguarded: `set_embedded` could stop releasing the chips
    and every test stayed green."""
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.detail_pane import DetailPane, _DTab

    _app()
    view = _rig_with_eq(inputs=True)
    outputs = _grp(view, "physical_outputs")
    embedded = DetailPane()
    embedded.set_embedded(True)
    embedded.set_view(view)
    embedded.open_eq(outputs, _row(outputs, "m-L"))
    chips = [c for c in embedded._head.findChildren(_DTab) if c.isVisibleTo(embedded)]
    assert embedded._eq_copy in chips and embedded._cmp_btn in chips
    for chip in chips:
        assert chip.way() == "gives", (chip.text(), chip.way())
        assert chip.minimumSizeHint().width() == chip.floor_width() <= chip.sizeHint().width()
    assert embedded._eq_copy.minimumSizeHint().width() < embedded._eq_copy.sizeHint().width()

    full = DetailPane()
    full.set_view(view)
    full.open_table(outputs)
    full.show()
    try:
        full.resize(full.head_asks()[0] + 100, 300)
        for _ in range(5):
            QApplication.processEvents()
        tabs = [full._tab_table, full._tab_eq, *full._param_tabs.values()]
        for tab in tabs:
            assert tab.way() == "holds", (tab.text(), tab.way())
            assert tab.minimumSizeHint().width() == tab.sizeHint().width() == tab.whole_width()
    finally:
        full.close()


def test_the_table_s_columns_are_sized_to_their_content_and_share_the_rest():
    """tcc#106 and tcc#107 both named the same lever: every column but the ID stretched to one
    equal share, so a table's width whole was the widest column's need times the count -- ~1254
    px of the full window and ~854 of control mode for the Arbiter's rig, where the content
    needs ~1115 and ~761. Each column is as wide as its heading or its widest cell now (Qt's own
    measure, a changed cell's bold included), the ID one keeps to that, and what a wide pane
    has to spare the other columns share equally. Short of the content every column gives in
    proportion, and the table still fills the pane -- no horizontal scroll bar."""
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.detail_pane import DetailPane, _ContentTable

    _app()
    view = _rig_view()
    pane = DetailPane()
    pane.set_view(view)
    pane.set_compare_choices(["v_001"], "v_001", lambda _k: _rig_view_changed())
    outputs = _grp(view, "physical_outputs")
    pane.open_table(outputs)
    assert isinstance(pane._scroll.widget(), _ContentTable), "the pane's table is the one"
    # On its own, so it can be made narrower than its content: the pane's head has a floor.
    table = pane._build_table(outputs)
    table.show()
    try:
        needs = table.column_needs()
        table.resize(sum(needs) + 400, 200)
        for _ in range(5):
            QApplication.processEvents()
        assert table.item(1, 4).font().bold(), "sw's gain changed: drawn bold, and measured so"
        widths = [table.columnWidth(c) for c in range(table.columnCount())]
        assert sum(widths) == table.viewport().width(), (widths, table.viewport().width())
        assert widths[0] == needs[0], "the ID column keeps to its content"
        spare = [width - need for width, need in zip(widths[1:], needs[1:])]
        assert min(spare) >= 0 and max(spare) - min(spare) <= 1, (widths, needs)
        assert not table.horizontalScrollBar().isVisible()

        chrome = table.width() - table.viewport().width()
        table.resize(sum(needs) - 40 + chrome, 200)
        for _ in range(5):
            QApplication.processEvents()
        widths = [table.columnWidth(c) for c in range(table.columnCount())]
        assert sum(widths) == table.viewport().width() < sum(needs), (widths, needs)
        assert all(width <= need for width, need in zip(widths, needs)), (widths, needs)
        assert not table.horizontalScrollBar().isVisible()
    finally:
        table.close()


def test_the_compare_row_tooltip_survives_a_paint():
    """tcc#96, finding 105 -- IMPORTANT 2, an opus reviewer's pass on the first fix:
    `_DTab.paintEvent` used to call `setToolTip` on every single paint -- `""` when the text fit,
    the full text when it did not -- silently erasing `_sync_tabs`'s tcc#54 hint on `_cmp_btn`
    («Pick a version in «compare with» first», measured after `open_eq`, gone after the first
    paint). A paint, elided or not, must not touch a tooltip the owner set.

    The pane is SHOWN and the tab repainted before each check, and the paints are counted: a
    widget never shown is never painted, so the previous version of this test passed against the
    very paint-time `setToolTip` it was written to catch."""
    from PySide6.QtCore import QEvent, QObject

    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    class _Paints(QObject):
        count = 0

        def eventFilter(self, _watched, event):  # noqa: N802 (Qt override)
            if event.type() == QEvent.Type.Paint:
                self.count += 1
            return False

    _app()
    view = _rig_with_eq(inputs=True)
    outputs = _grp(view, "physical_outputs")
    pane = DetailPane()
    pane.set_embedded(True)
    pane.set_view(view)
    pane.open_eq(outputs, _row(outputs, "m-L"))
    pane.show()
    QApplication.processEvents()
    button = pane._cmp_btn
    owner_tip = button.toolTip()
    assert owner_tip == i18n.t("cmpRowOff"), owner_tip
    paints = _Paints()
    button.installEventFilter(paints)

    button.resize(20, 22)  # narrow enough to elide
    QApplication.processEvents()
    button.repaint()
    assert paints.count > 0 and button.fit_text() != button.text(), "painted, and elided"
    assert button.toolTip() == owner_tip, "the owner's hint survives being elided"

    painted = paints.count
    button.resize(400, 22)  # roomy again
    QApplication.processEvents()
    button.repaint()
    assert paints.count > painted and button.fit_text() == button.text(), "painted, whole"
    assert button.toolTip() == owner_tip, "and survives not being elided either"


def test_a_tab_with_no_owner_tooltip_falls_back_to_its_full_text_when_elided():
    """The fallback `_DTab` gives itself when NOBODY else named a hint -- so an elided tab is
    never silently unexplained, the other half of IMPORTANT 2's fix. `show()`d: `resizeEvent`
    (where the fallback is synced) does not fire on a bare, never-shown top-level widget at all."""
    from autosound_tcc.ui.tcc.detail_pane import _DTab

    _app()
    long = "Копіювати EQ m-Left-Tweeter-Front"
    tab = _DTab(long)
    tab.show()
    # Roomy is the whole text's width, set: a bare top-level's first size is capped at a share
    # of the screen, and at a stretch of 200 the whole text is past it (elided, with a hint).
    tab.resize(tab.whole_width(), 22)
    for _ in range(3):
        QApplication.processEvents()
    assert tab.toolTip() == "", "roomy: nothing to explain"
    tab.resize(40, 22)
    for _ in range(3):
        QApplication.processEvents()
    assert tab.toolTip() == long, "elided, and nobody else said anything: the full text stands in"
    tab.resize(2000, 22)
    for _ in range(3):
        QApplication.processEvents()
    assert tab.toolTip() == "", "roomy again: the fallback clears itself"
    tab.close()


def test_the_own_group_is_headed_too_and_its_current_version_is_greyed_out():
    """tcc#103, finding 112: with «4.C-cut» open, «порівняти з» showed «—», a lone `v_001`, then
    every OTHER preset under its own heading — the open configuration's own versions had none, and
    its current one (v_002, HEAD) had simply vanished. Wanted: the same heading form the other
    groups use, for this one too, and the current version shown but greyed, not selectable."""
    from PySide6.QtWidgets import QComboBox

    from autosound_tcc.ui.tcc.detail_pane import fill_compare_combo

    _app()
    combo = QComboBox()
    fill_compare_combo(combo, ["v_002", "v_001"], None, None, preset="4.C-cut", current="v_002")
    texts = [combo.itemText(i) for i in range(combo.count())]
    keys = [combo.itemData(i) for i in range(combo.count())]
    assert texts == ["—", i18n.t("cmpOwnPreset").format(preset="4.C-cut"),
                     i18n.t("cmpCurrentVersion").format(version="v_002"), "v_001"]
    assert keys == [None, None, None, "v_001"], "the heading and the current row carry no key"
    assert not combo.model().item(1).isEnabled(), "the heading is not a version to pick"
    assert not combo.model().item(2).isEnabled(), "the current version is not selectable (#103)"
    assert combo.model().item(3).isEnabled()


def test_nothing_that_reads_the_combo_can_land_on_the_current_version():
    """The current row carries no key (`None`, like «—» and every other heading) -- nothing that
    reads `combo.currentData()` after picking it can end up "comparing" a version with itself."""
    from PySide6.QtWidgets import QComboBox

    from autosound_tcc.ui.tcc.detail_pane import fill_compare_combo

    _app()
    combo = QComboBox()
    fill_compare_combo(combo, ["v_002", "v_001"], None, None, preset="SQ", current="v_002")
    current_row = next(i for i in range(combo.count())
                       if "v_002" in combo.itemText(i) and i != 0)
    combo.setCurrentIndex(current_row)
    assert combo.currentData() is None


# ---- third pass (finding 71; tcc#53) ------------------------------------------------------------

def test_an_empty_band_is_skipped_and_a_bypassed_one_with_settings_is_shown():
    """Finding 71, 5: PC-Tool's white slot (a frequency, no gain, no Q) is not a band."""
    from PySide6.QtWidgets import QHBoxLayout

    from autosound_tcc.ui.tcc.detail_pane import EqBandCard

    _app()
    flow = _band_flow((EqBand(type="PK", freq_hz=50.0, bypass=True, index=4),
                       EqBand(type="PK", freq_hz=420.0, gain_db=-3.0, q=1.0, bypass=True, index=9),
                       EqBand(type="PK", freq_hz=100.0, gain_db=-1.0, q=2.0, index=1)))
    assert [c._title.text() for c in flow.findChildren(EqBandCard)] == ["PK (1)", "PK (9)"]
    assert isinstance(flow.layout(), QHBoxLayout), "one row and a scroll, not a wrap (71, 2)"


def test_the_band_count_reads_active_of_configured():
    """Finding 71, 3 and 5: «(8/12)» — 8 active of 12 configured, the empty ones not counted."""
    from autosound_tcc.ui.tcc.detail_pane import band_count

    bands = tuple(EqBand(type="PK", freq_hz=100.0 + i, gain_db=-1.0, q=1.0, bypass=i < 4, index=i)
                  for i in range(12))
    empty = (EqBand(type="PK", freq_hz=50.0, bypass=True, index=13),)
    assert band_count(bands + empty) == "(8/12)"
    assert band_count(()) == ""


def test_the_table_and_the_tree_count_bands_as_the_pickers_do():
    """The Arbiter, 2026-09-25: the virtual table read «15 bands ▸» where the picker read
    «VFR (10/12)» — the table counted the empty slots. The fraction there too, and in the tree."""
    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup
    from autosound_tcc.ui.tcc.detail_pane import DetailPane
    from autosound_tcc.ui.tcc.dsp_tree import ChannelRow

    _app()
    row = GroupRow(id="VFR", name="VFR", slot="B", raw={"eq": [
        {"type": "PK", "f": 100, "gain_db": -1.0, "q": 2.0, "i": 1},
        {"type": "PK", "f": 200, "gain_db": -2.0, "q": 2.0, "bypass": True, "i": 2},
        {"type": "PK", "f": 50, "bypass": True, "i": 3},
    ]})
    assert DetailPane._cell_text("eq", row) == "(1/2) ▸"
    group = ProfileGroup(id="virtual_channels", label="Virtual", fields=("eq",), rows=(row,))
    chan = ChannelRow(group, row)
    assert chan._eq_chip.text() == "EQ 1/2"


def test_the_full_window_s_eq_actions_close_the_row_and_the_close_button_elides():
    """The Arbiter, 2026-09-25: in the full window «⇄ L + R · ? · Копіювати EQ» sat between
    «EQ» and «Рівень», and the tabs jumped as they came and went; to the row's end. And a squeezed
    «закрити ×» was cut on both sides («(риті»): shorten from the end instead."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane
    from autosound_tcc.ui.tcc.labels import ElidedButton

    _app()
    pane = DetailPane()
    head = pane._head.layout()
    # After «Фази», before «порівняти з» (the Arbiter, 2026-09-25: «ти мене не зрозумів»).
    order = [head.indexOf(w) for w in (pane._tab_eq, pane._param_tabs["phase_deg"],
                                       pane._eq_copy, pane._pair_btn, pane._eq_help,
                                       pane._compare_label, pane._compare_combo, pane._close_btn)]
    assert order == sorted(order), order
    assert isinstance(pane._close_btn, ElidedButton)
    group = _pair_view()
    pane.open_eq(group, group.rows[0])
    assert not pane._title.isVisibleTo(pane), "the «EQ m-L» tab already says it"
    pane.open_table(group)
    assert pane._title.isVisibleTo(pane), "a table keeps its title"


def test_a_squeezed_close_button_keeps_its_start_like_copy():
    """The Arbiter, 2026-09-25: «закрити» stayed centred and cut on both sides («‹рі»); left, as
    «Копіювати» is."""
    import re

    from autosound_tcc.ui.tcc import theme

    qss = theme.build_qss(theme.get_theme("dark"))
    block = re.search(r'QPushButton\[class~="d-close"\] \{([^}]*)\}', qss).group(1)
    assert "text-align: left" in block


# ---- the compared version's EQ row and the band marks (finding 73, tcc#54) ----------------------

def _eq_versions():
    """m-L now: 100 Hz same, 1000 Hz gain moved, 4000 Hz new; before: 2500 Hz, gone since."""
    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup

    def outputs(bands):
        return ProfileGroup(id="physical_outputs", label="Output", fields=("eq",), rows=(
            GroupRow(id="m-L", name="m-L", slot="E", raw={"eq": bands}),
            GroupRow(id="m-R", name="m-R", slot="F", raw={"eq": [dict(_PK, f=320)]}),))

    now = outputs([dict(_PK, f=100, i=1), dict(_PK, f=1000, gain_db=-4.0, i=2),
                   dict(_PK, f=4000, i=4)])
    was = outputs([dict(_PK, f=100, i=1), dict(_PK, f=1000, i=2), dict(_PK, f=2500, i=3)])
    return now, type("V", (), {"groups": (was,)})()


def _card_rows(pane):
    from autosound_tcc.ui.tcc.detail_pane import EqBandCard

    rows = []
    for widget in pane._scroll.widget().findChildren(QWidget):
        cards = [c for c in widget.children() if isinstance(c, EqBandCard)]
        if cards:
            rows.append(cards)
    return rows


def test_the_compare_button_is_passive_with_nothing_chosen_and_gone_in_pair_mode():
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    now, before = _eq_versions()
    pane = DetailPane()
    pane.set_compare_choices(["v_005"], None, lambda _v: before)
    pane.open_eq(now, now.rows[0])
    assert pane._cmp_btn.isVisibleTo(pane) and not pane._cmp_btn.isEnabled()

    pane.select_compare("v_005")
    assert pane._cmp_btn.isEnabled()

    pane._on_pair_toggle()
    assert not pane._cmp_btn.isVisibleTo(pane), "two channels on screen: no compared row"


def test_the_marks_stand_whenever_a_version_is_chosen():
    """«в шапці EQ band кольоровий маркер — завжди, якщо є сет для порівняння»: new and changed
    on the current row; removed has no card to stand on until the compared row is shown."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    now, before = _eq_versions()
    pane = DetailPane()
    pane.set_compare_choices(["v_005"], "v_005", lambda _v: before)
    pane.open_eq(now, now.rows[0])
    rows = _card_rows(pane)
    assert len(rows) == 1
    assert [c.mark for c in rows[0]] == [None, "chg", "new"]
    assert rows[0][1].changed_fields() == [], "the values are coloured with the compared row only"

    pane.select_compare(None)
    assert [c.mark for c in _card_rows(pane)[0]] == [None, None, None]


def test_pressed_the_compared_version_s_row_stands_under_the_current_one():
    """«показується рядок EQ нижче поточного і підписується v_xxx; цвітова показує, що
    змінилося; копіювання залишається вверху»."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    now, before = _eq_versions()
    pane = DetailPane()
    pane.set_compare_choices(["v_005"], "v_005", lambda _v: before)
    pane.open_eq(now, now.rows[0])
    pane._cmp_btn.clicked.emit()

    top, lower = _card_rows(pane)
    assert [c.mark for c in top] == [None, "chg", "new"]
    assert [c.mark for c in lower] == [None, None, "removed"], "removed only below"
    assert top[1].changed_fields() == ["Gain"]
    # Red only where it is to be entered, the current row (the Arbiter, 2026-09-26: «не виділяти
    # червоним, як було, а тільки там, де треба вводити»); the pair colour ties the two.
    assert lower[1].changed_fields() == []
    labels = [w.text() for w in pane._scroll.widget().findChildren(QLabel)]
    assert any(t.startswith("v_005") for t in labels), "the lower row names its version"
    assert pane._cmp_btn.property("class") == "d-tab on"

    pane._cmp_btn.clicked.emit()
    assert len(_card_rows(pane)) == 1


def test_the_legend_names_all_three_and_the_frequencies_of_what_differs():
    """The Arbiter, 2026-09-26: «видалена» in the legend always; the same bands by count, without
    their frequencies; the new, changed and removed ones with theirs."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    now, before = _eq_versions()
    pane = DetailPane()
    pane.set_compare_choices(["v_005"], "v_005", lambda _v: before)
    pane.open_eq(now, now.rows[0])
    said = [w.text() for w in pane._scroll.widget().findChildren(QLabel)]
    assert f"{i18n.t('bandSame')} (1)" in said
    assert f"● {i18n.t('bandNew')} (1): 4000 Hz" in said
    assert f"● {i18n.t('bandChg')} (1): 1000 Hz" in said
    assert f"● {i18n.t('bandGone')} (1): 2500 Hz" in said, "removed, with the compared row off"

    pane.open_eq(now, now.rows[1])  # m-R: the same in both
    said = [w.text() for w in pane._scroll.widget().findChildren(QLabel)]
    assert f"● {i18n.t('bandGone')} (0)" in said, "all three, even with none"


def test_a_changed_band_and_what_it_was_share_a_colour_as_the_pair_mode_does():
    """The Arbiter, 2026-09-26: «кольорово однаковими "змінені", як у нас правий-лівий»: each
    changed band and its compared self get one colour of the pair palette; the rest none."""
    from autosound_tcc.ui.tcc.detail_pane import _CMP_PALETTE, DetailPane

    _app()
    now, before = _eq_versions()
    pane = DetailPane()
    pane.set_compare_choices(["v_005"], "v_005", lambda _v: before)
    pane.open_eq(now, now.rows[0])
    assert _card_rows(pane)[0][1].match_color is None, "with no row below, no pairs"

    pane._cmp_btn.clicked.emit()
    top, lower = _card_rows(pane)
    assert top[1].match_color == lower[1].match_color == _CMP_PALETTE[0]
    assert [c.match_color for c in (top[0], lower[0])] == [None, None], "the same: none"
    said = [w.text() for w in pane._scroll.widget().findChildren(QLabel)]
    assert "⬤ 1000 Hz" in said, "the legend names the pair in its colour, as «спільні» does"


def test_the_pair_colours_are_not_the_new_and_removed_marks():
    """«кольори, відмінні від зеленого і червоного (як у точок) — синій ок»: a pair must not read
    as a new or a removed band."""
    from typing import get_args

    from autosound_tcc.ui.tcc.detail_pane import _CMP_PALETTE
    from autosound_tcc.ui.tcc.theme import Mode, get_theme

    for mode in get_args(Mode):
        t = get_theme(mode)
        assert not {t.ok.lower(), t.warn.lower()} & {c.lower() for c in _CMP_PALETTE}


def test_a_new_or_removed_band_carries_its_colour_on_the_card_top_too():
    """«там, де точки зелена чи червона, малювати і в шапці колір — щоб краще було видно»."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane
    from autosound_tcc.ui.tcc.theme import current_theme

    _app()
    t = current_theme()
    now, before = _eq_versions()
    pane = DetailPane()
    pane.set_compare_choices(["v_005"], "v_005", lambda _v: before)
    pane.open_eq(now, now.rows[0])
    assert [c.match_color for c in _card_rows(pane)[0]] == [None, None, t.ok], \
        "new: green on top, with the compared row off too"

    pane._cmp_btn.clicked.emit()
    top, lower = _card_rows(pane)
    assert top[2].match_color == t.ok and lower[2].match_color == t.warn


def test_a_compare_pick_never_moves_the_table_s_columns():
    """The review of the follow-up: a compared change is drawn bold, and a column's need
    followed it -- «3500 LR4» bold or plain moved every column 1-3 px at panes of 760-1060 px on
    a pick. Every cell is measured bold now, the widest it can be drawn, so two tables of the
    same rows -- one compared with a version that changed them, one with nothing -- ask the same
    and lay out the same."""
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    view = _rig_view()
    outputs = _grp(view, "physical_outputs")
    compared, plain = DetailPane(), DetailPane()
    compared.set_view(view)
    compared.set_compare_choices(["v_001"], "v_001", lambda _k: _rig_view_changed())
    plain.set_view(view)
    tables = (compared._build_table(outputs), plain._build_table(outputs))
    assert tables[0].item(1, 4).font().bold() and not tables[1].item(1, 4).font().bold(), \
        "sw's gain changed in the compared table only"
    try:
        for table in tables:
            table.show()
        assert tables[0].column_needs() == tables[1].column_needs()
        for width in (720, 760, 900, 1060):
            widths = []
            for table in tables:
                table.resize(width, 200)
                for _ in range(5):
                    QApplication.processEvents()
                widths.append([table.columnWidth(c) for c in range(table.columnCount())])
            assert widths[0] == widths[1], (width, widths)
    finally:
        for table in tables:
            table.close()


def _ink(widget) -> tuple:
    """The painted text's ink inside the label's own text rect, from a grab of the widget:
    `(inked columns, the rightmost inked column from the rect's left, the rect's width)`. The
    background is the rect's most common colour (a lit tab's fill included), ink whatever
    differs from it. No number here is a pixel of any one font: what is asserted is that the
    ink reaches where the text `fit_text` names ends, and no further."""
    from collections import Counter

    image = widget.grab().toImage()
    rect = widget._text_rect()
    pixels = {(x, y): image.pixel(x, y)
              for x in range(rect.left(), rect.right() + 1)
              for y in range(rect.top(), rect.bottom() + 1)}
    background = Counter(pixels.values()).most_common(1)[0][0]
    columns = sorted({x for (x, _y), colour in pixels.items() if colour != background})
    return len(columns), (columns[-1] - rect.left() + 1) if columns else 0, rect.width()


def _no_real_font(font) -> str:
    """Why a grab in this font says nothing about a real font's ink, or "" where it does. The
    Windows runner's offscreen Qt has no font files (CI at 9bb37b7): every glyph is drawn as one
    and the same box, a stretch is ignored, and where that box's ink ends is no font's («←…» inked
    to 18 px of an advance that ends at 22). Measured, not named by platform: the database lists
    no family, or «i» and «W» -- a narrow and a wide letter in any real font, a monospace one
    included -- draw the same ink box."""
    from PySide6.QtGui import QFontDatabase, QFontMetricsF

    if not QFontDatabase.families():
        return "the font database lists no family"
    metrics = QFontMetricsF(font)
    narrow, wide = metrics.tightBoundingRect("i"), metrics.tightBoundingRect("W")
    if narrow == wide:
        return f"«i» and «W» draw one ink box ({wide.width():.1f} px wide): a box font"
    return ""


#: The Mac's offscreen font, as the font itself measures: its family, and the advance of a head's
#: words at the head's 11 px. The numbers the head's guards pin were measured in it.
_MAC_FONT_TEXT = "Таблиця-О ⇅ Copy EQ"
_MAC_FONT = (".AppleSystemUIFont", 127.61)


def _not_the_mac_font() -> str:
    """"" where the app's font is the Mac's offscreen one the head's numbers were pinned in, or
    why not. Fingerprinted by what the font measures, never by a number the product works out
    -- the re-review of the CI fix: gated on the head's ask, the guards skipped themselves on
    the very regression they exist for (round 2's hint put back: ask 757 > room 734, and the
    zoom pins' reference 513 -> 565).

    Skipped quietly only where the font is plainly another: an engine without real fonts,
    another family, or a stretch (the wide-font emulation). The Mac's own family unstretched
    that measures otherwise -- a new macOS image, another weight, a changed Cyrillic fallback --
    still skips, but WARNS, and `pytest -q` prints the warning: CI runs without `-rs`, so a
    quiet skip there would switch the five guards off with no trace but a skip count. Not a
    failure: a font the runner changed is not a regression in this code, and the warning says
    to re-measure and re-pin (the round-4 re-review's advisory)."""
    import warnings

    from PySide6.QtGui import QFont, QFontInfo, QFontMetricsF

    font = QFont(QApplication.font())
    fontless = _no_real_font(font)
    if fontless:
        return fontless
    if font.stretch() not in (0, 100):
        return f"a stretched font ({font.stretch()}), not the Mac's offscreen font"
    font.setPixelSize(11)
    family = QFontInfo(font).family()
    if family != _MAC_FONT[0]:
        return f"not the Mac's offscreen font: {family!r}, where the Mac's is {_MAC_FONT[0]!r}"
    advance = QFontMetricsF(font).horizontalAdvance(_MAC_FONT_TEXT)
    if abs(advance - _MAC_FONT[1]) > 0.05:
        why = (f"the Mac's offscreen family {family!r} measures «{_MAC_FONT_TEXT}» {advance:.2f} "
               f"px at 11 px, not the {_MAC_FONT[1]} the head's guards were pinned in")
        warnings.warn(f"{why}: the pins and the whole-check skip -- re-measure and re-pin "
                      f"_MAC_FONT, _EQ_HEAD_LEAST_MAC and _EQ_HEAD_LEAST_AT in "
                      f"tests/test_detail_pane.py", stacklevel=2)
        return why
    return ""


def _paints_what_it_says(widget) -> str:
    """The label's ink is the text `fit_text` names -- present, ending where that text's advance
    ends (a glyph's side bearing of slack), inside the room -- so nothing is drawn cut and
    nothing is left undrawn. The fit's own rule holds in any engine and is asserted first: never
    empty, the label's own first character, «…» where it is cut (the Arbiter: half a button is
    fine if its beginning shows). The ink is checked only where the font is real; elsewhere this
    returns why not, for the test to say once its other checks have passed."""
    from PySide6.QtGui import QFontMetricsF

    shown = widget.fit_text()
    assert shown and _reads(widget), (widget.text(), shown)
    assert shown[0] == widget.text()[0], (widget.text(), shown)
    fontless = _no_real_font(widget.font())
    if fontless:
        return fontless
    columns, right, room = _ink(widget)
    metrics = QFontMetricsF(widget.font())
    advance = metrics.horizontalAdvance(shown)
    # Where the last glyph's ink ends: the text's advance less that glyph's right bearing --
    # the font's own numbers, so the bound follows the font (the re-review of fix round 2: at
    # twice the width a fixed 4 px was too tight, and at the Mac's font it let a 3-px cut, the
    # last dot of «…», through). The slack past that is anti-aliasing: two pixels, or a third
    # of an «x» in a wider font.
    ends = advance - metrics.rightBearing(shown[-1])
    slack = max(1.0, metrics.horizontalAdvance("x") / 6)
    assert columns > 0, f"{widget.text()!r} shows {shown!r} and draws no ink"
    assert advance < room + 1, (widget.text(), shown, advance, room)
    assert ends - slack <= right <= advance + 2, (
        f"{widget.text()!r} says {shown!r} (its ink should end at {ends:.1f} px, slack "
        f"{slack:.1f}) but its ink ends at {right} px of a {room}-px room")
    return ""


def test_the_head_paints_what_its_fit_says(tmp_path, monkeypatch, app_ground):
    """The re-review of fix round 1 (N1, CRITICAL): the measurement was right and the paint was
    not. `_FitLabel.paintEvent` built its rect from `contentsRect()` less the chrome -- but the
    contents rect already excludes the style sheet's border and padding, so an elided tab drew
    into width - 46 where the native text has width - 23: at the full window at two thirds of
    the Arbiter's screen over one channel's EQ every elided tab drew NOTHING («Т…», «E…», «Р…»,
    «З…», «Ф…», «⇅», «⇄» -- 0 px of ink) and «Копіювати EQ m-L» drew «Копі», a word cut with no
    «…». No test looked at pixels. This one grabs each head label at that width and checks its
    ink is the text `fit_text` names: present, ending where that text ends, inside the room.
    The window is 1008 px wide (two thirds of 1512) and the head is below its ask, so the
    elided paint path is what is grabbed."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc import main_window
    from autosound_tcc.ui.tcc.detail_pane import _FitLabel
    from tests import test_control_layout as tcl

    window = tcl._window(tmp_path, monkeypatch)
    i18n.set_language("uk")
    try:
        monkeypatch.setattr(main_window, "_screen_room", lambda _w: QRect(0, 0, 1512, 982))
        window.show()
        pane = _arbiter_head(window, "eq_single")
        window._fit_centre_floor()
        # 1008 px, or the window's own floor where this font puts it higher (the runner's
        # twice-as-wide text): the head is short of its ask either way.
        for _ in range(4):
            width = max(1008, window.minimumWidth())
            window.resize(width, 900)
            for _ in range(4):
                QApplication.processEvents()
            if window.width() == width:
                break
        assert window.width() == max(1008, window.minimumWidth()), window.width()
        head = pane._head
        labels = [w for w in _head_words(pane) if isinstance(w, _FitLabel) and w.isVisibleTo(head)]
        assert head.width() < pane.head_asks()[0] and any(w.fit_text() != w.text() for w in labels), \
            "the head is short of its ask: the elided paint is what is grabbed"
        fontless = {_paints_what_it_says(widget) for widget in labels} - {""}
    finally:
        i18n.set_language("en")
    if fontless:
        pytest.skip(f"the fit's rule held for every label; the ink is not checked: "
                    f"{', '.join(sorted(fontless))}")


def test_an_on_chip_s_fill_is_drawn_once():
    """The re-review of the CI fix (IMPORTANT, seen on the Arbiter's screen size): `_FitLabel`
    has `WA_StyledBackground`, so Qt draws its QSS box before `paintEvent` -- and round 3's
    paint drew `PE_Widget` again, for every label now and not only the elided ones. Every "on"
    chip -- the active tab, «← Table-O», «⇄ L + R» and «⇅» on -- laid its translucent accent
    twice: «Таблиця» 0x28231c at 467c655, 0x3e3120 after (about 12 % of the accent, then 22 %).
    The chip's box -- its border and its fill, left of the text -- is a plain QLabel's of the
    same class, in the same sheet, on the same ground. No font in it: the pixels compared are
    the box's, so it holds on the runner's fontless engine too."""
    from autosound_tcc.ui.tcc import theme
    from autosound_tcc.ui.tcc.detail_pane import _DTab

    _app()
    host = QWidget()
    host.setStyleSheet(theme.build_qss(theme.get_theme("dark")))
    chip = _DTab("Таблиця")
    chip.setParent(host)
    chip.set_on(True)
    plain = QLabel("Таблиця", host)
    plain.setProperty("class", "d-tab on")
    for row, label in enumerate((chip, plain)):
        label.setGeometry(10, 10 + 40 * row, 90, 24)
    host.resize(120, 90)
    host.show()
    try:
        for _ in range(3):
            QApplication.processEvents()
        image = host.grab().toImage()

        def box(label) -> list:
            # Left of the text: the border (x 0) and the padding's fill (x 1-8), mid-height.
            g = label.geometry()
            return [image.pixelColor(g.left() + x, g.center().y()).name() for x in range(9)]

        ground = image.pixelColor(2, 2).name()
        assert box(plain)[4] != ground, "the sheet gives an on chip a fill of its own"
        assert box(chip) == box(plain), (
            f"the on chip's box is {box(chip)}, a plain label's of its class {box(plain)}: "
            f"a fill drawn twice is twice as strong")
    finally:
        host.close()


def test_the_list_s_floor_keeps_the_version_whole_before_a_saved_name():
    """The re-review of fix round 1 (b): the list's floor was measured on «v_000» alone, so a
    version saved under a name -- «v_001 · P3» -- read «v_0…» at the floor. The floor holds
    «v_NNN» and the «…» that says a name follows: «v_001…»; with the room, the whole row."""
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    pane = DetailPane()
    pane.set_compare_choices(["v_001", "v_002"], "v_001", lambda _k: _rig_view(),
                             {"v_001": "v_001 · P3", "v_002": "v_002"}, [], "4.C-cut", "v_002")
    box = pane._compare_combo
    assert box.currentText() == "v_001 · P3"
    box.show()
    try:
        box.set_way("floor")
        box.resize(box.floor_width(), 24)
        QApplication.processEvents()
        assert box.fit_text() == "v_001…", box.fit_text()
        box.set_way("holds")
        box.resize(box.whole_width() + 60, 24)
        QApplication.processEvents()
        assert box.fit_text() == "v_001 · P3", box.fit_text()
    finally:
        box.close()


def test_a_hidden_label_s_words_go_into_the_list_s_hover(tmp_path, monkeypatch, app_ground):
    """The re-review of fix round 1 (c): at two thirds of the screen «інша конфігурація» hides
    over the table too, and the list had no hover, so another configuration's «v_002» read as
    this configuration's own. As control mode's corner does, a hidden label's words go into the
    list's hover: «порівняти з», and «інша конфігурація: 3.S-shelf · v_002»; with the room, the
    labels are back and the hover empty."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc import main_window
    from tests import test_control_layout as tcl

    window = tcl._window(tmp_path, monkeypatch)
    i18n.set_language("uk")
    try:
        monkeypatch.setattr(main_window, "_screen_room", lambda _w: QRect(0, 0, 1512, 982))
        window.show()
        pane = _arbiter_head(window, "table")
        window._fit_centre_floor()
        for _ in range(4):
            window.resize(1008, 900)
            for _ in range(4):
                QApplication.processEvents()
        head, box = pane._head, pane._compare_combo
        assert not pane._compare_other.isVisibleTo(head) and pane._compare_other.wanted()
        assert box.toolTip() == "порівняти з\nінша конфігурація: 3.S-shelf · v_002", box.toolTip()

        # Roomy: wide enough for the pane's share to hold the head's ask -- measured, since the
        # ask is the font's (at twice the width it is 2656 px, past a 2600-px window).
        splitter = window._main_splitter
        want = pane.head_asks()[0] + 40
        roomy = 2600
        window.resize(roomy, 900)
        for _ in range(4):
            QApplication.processEvents()
        while sum(splitter.sizes()) < want + 2 * 200 + 40 and roomy < 8000:
            roomy += 400
            window.resize(roomy, 900)
            for _ in range(4):
                QApplication.processEvents()
        sizes = splitter.sizes()
        splitter.setSizes([200, want, sum(sizes) - 200 - want])
        for _ in range(4):
            QApplication.processEvents()
        assert pane.width() == want, (pane.width(), want, splitter.sizes())
        assert pane._compare_other.isVisibleTo(head) and box.toolTip() == "", box.toolTip()
    finally:
        i18n.set_language("en")


#: The EQ head's minimum over one channel, uk, in the Mac's offscreen font at the default zoom --
#: the reference that says the numbers below are this font's -- and at the zoom's steps and a
#: stretch of 110, all pinned (the re-review of fix round 2): a fix or a worse regression shows.
#: The zoom's first and last steps; 130 % (563) sat between them and went (F-065).
_EQ_HEAD_LEAST_MAC = 513
_EQ_HEAD_LEAST_AT = {"zoom120": ("zoom", 1.2, 546), "zoom140": ("zoom", 1.4, 579),
                     "stretch110": ("stretch", 110, 562)}


@pytest.mark.parametrize("case", sorted(_EQ_HEAD_LEAST_AT))
def test_the_eq_head_against_the_arbiter_s_floor_at_a_zoom(tmp_path, monkeypatch, case,
                                                           app_ground):
    """The residual, stated with its numbers pinned (the re-review of fix round 1, d, and of
    round 2): over one channel's EQ the head's minimum against the centre's floor of 586 on the
    Arbiter's 1512-px screen. Before round 3 the head's hint carried a full «x» of indent per
    label and the fit judged a strict advance: 606 / 623 / 650 / 623 at zoom 120 / 130 / 140 %
    and a stretch of 110 -- all over the floor. With the hint, the fit and the paint one rule
    (`_FitLabel._text_rect`) they are 546 / 563 / 579 / 562, all inside it, and pinned here so
    a regression past 586 -- or a fix that brings them lower -- is visible. The numbers are the
    Mac's offscreen font's (513 at the default zoom, pinned too): on that font they are asserted;
    another font -- `_not_the_mac_font`, by what the font measures -- says what it measured and
    skips."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc import main_window
    from tests import _windows
    from tests import test_control_layout as tcl

    kind, value, pinned = _EQ_HEAD_LEAST_AT[case]
    app = _app()
    before = QFont(app.font())
    # The font decides whether the pins apply -- measured before the zoom or the stretch, and
    # never by the minimum they pin.
    not_mac = _not_the_mac_font()
    window = tcl._window(tmp_path, monkeypatch)
    # The zoom styles this window, not every window the run has left alive (F-065).
    _windows.theme_on_the_window(monkeypatch, window)
    i18n.set_language("uk")
    try:
        monkeypatch.setattr(main_window, "_screen_room", lambda _w: QRect(0, 0, 1512, 982))
        window.show()
        pane = _arbiter_head(window, "eq_single")
        window._fit_centre_floor()
        reference = pane.head_asks()[-1]
        if kind == "zoom":
            window._set_zoom(value)
        else:
            wide = QFont(before)
            wide.setStretch(value)
            app.setFont(wide)
            # The sheet's fonts were resolved when the window was polished: re-polish, as the
            # zoom does, or the head keeps the default font's widths (513 at «stretch 110»).
            window._repolish_all()
        for _ in range(4):
            QApplication.processEvents()
        window._fit_centre_floor()
        least = pane.head_asks()[-1]
        floor = window._center.minimumWidth() - (pane.width() - pane._head.width())
        if not_mac:
            pytest.skip(f"{not_mac}: at {kind} {value} the EQ head's minimum is {least} (at the "
                        f"default {reference}) against the floor {floor}")
        assert reference == _EQ_HEAD_LEAST_MAC, (
            f"at the default the EQ head's minimum is {reference} px, pinned at "
            f"{_EQ_HEAD_LEAST_MAC}: a regression or a fix -- re-pin it")
        assert least == pinned, (
            f"at {kind} {value} the EQ head's minimum is {least} px, pinned at {pinned} "
            f"(the floor {floor}): a regression or a fix -- re-pin it")
        assert least <= floor, (least, floor)
    finally:
        if kind == "zoom":
            window._set_zoom(1.0)
        app.setFont(before)
        i18n.set_language("en")
