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


def test_one_parameter_across_both_tiers_in_one_table():
    """"Three buttons — Gain, Delay, Phase — that show the table for every channel, and it works
    for the physical ones as well as the virtual" (user, 2026-08-23). The per-group table answers
    what a tier is set to; this answers how the rig compares, which is the actual question about
    a delay."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    pane = DetailPane()
    pane.set_view(_rig_view())

    pane.open_param("ta_ms")

    table = pane._scroll.widget()
    assert table.columnCount() == 3
    read = [[table.item(r, c).text() if table.item(r, c) else "" for c in range(3)]
            for r in range(table.rowCount())]
    # A heading per tier, then its channels, in the view's order.
    assert read[0][0] and read[0][1] == "", "the first row is a tier heading"
    names = [row[1] for row in read if row[1]]
    assert names == ["VFL", "w-L", "sw"], names
    assert [row[2] for row in read if row[1] == "w-L"] == ["5.22"]


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


def test_a_tier_heading_is_not_a_channel_to_click():
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    _app()
    pane = DetailPane()
    pane.set_view(_rig_view())
    pane.open_param("gain_db")

    activated = []
    pane.tableRowActivated.connect(lambda gid, rid: activated.append((gid, rid)))
    table = pane._scroll.widget()
    table.cellClicked.emit(0, 0)  # the heading row
    assert activated == []

    table.cellClicked.emit(1, 1)  # the first real channel
    assert activated == [("virtual_channels", "VFL")]


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
    monkeypatch.setattr(
        eq_export, "format_bank",
        lambda rows: eq_export.Bank(text="BANK-TEXT", format_name="Audiotec-Fischer",
                                    left_out=("APF2 4386 Hz",)),
    )
    said = []
    pane.bankCopied.connect(said.append)
    pane.open_eq(group, row)

    pane._on_copy_eq_bank()

    assert QGuiApplication.clipboard().text() == "BANK-TEXT"
    assert len(said) == 1
    assert "Audiotec-Fischer" in said[0] and "APF2 4386 Hz" in said[0]

    # And when there is no format, nothing plausible is put on the clipboard instead.
    monkeypatch.setattr(eq_export, "format_bank", lambda rows: None)
    QGuiApplication.clipboard().setText("untouched")
    pane._on_copy_eq_bank()
    assert QGuiApplication.clipboard().text() == "untouched"
    assert said[-1] == i18n.t("copyEqNoFormat")

