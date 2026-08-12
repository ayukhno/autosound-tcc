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
