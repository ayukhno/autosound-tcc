"""Sibling-name matching for the EQ pair (⇄ L+R) view — the two real naming conventions found in
actual ledgers: a bare trailing letter with no delimiter (`FrontL`/`FrontR`, the real virtual-
channel names) and a standalone word (`Front L Full`, the prototype's own convention)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

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
    width = picker.width()

    pane._on_pair_toggle()
    picker = pane._tier_pickers["physical_outputs"]
    assert picker.text() == "Output: m-L/m-R"
    assert picker.width() == width, "the field keeps its width: nothing jumps"
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
