"""Sibling-name matching for the EQ pair (⇄ L+R) view — the two real naming conventions found in
actual ledgers: a bare trailing letter with no delimiter (`FrontL`/`FrontR`, the real virtual-
channel names) and a standalone word (`Front L Full`, the prototype's own convention)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.state.dsp_state import EqBand  # noqa: E402
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
    fv_labels = [l for l in labels if "band-fv" in (l.property("class") or "")]
    # 3 value rows (Freq/Q/Gain) -- only Gain's gets the mismatch class.
    mismatch_labels = [l for l in fv_labels if l.property("class") == "band-fv-mismatch"]
    assert len(mismatch_labels) == 1
    assert "1.0" in mismatch_labels[0].text()


def test_no_mismatch_uses_plain_gain_class():
    _app()
    band = EqBand(type="PK", freq_hz=8800.0, gain_db=1.0, q=1.4)
    card = EqBandCard(band, match_color="#5aa9e6", gain_mismatch=False)
    from PySide6.QtWidgets import QLabel

    assert not any(
        l.property("class") == "band-fv-mismatch" for l in card.findChildren(QLabel)
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

