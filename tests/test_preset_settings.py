"""The «Пресет» tab and the DSP tree's «ПРЕСЕТ» section (#256, hub #324): what the person reads, from
a ledger the method itself wrote (`PresetHistory.snapshot`, `apply.propose`, `apply.attest`)."""

from __future__ import annotations

import html
import importlib.util
import json
import logging
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPalette, QTextDocumentFragment  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QTableWidget  # noqa: E402

import pytest  # noqa: E402

from autosound_tcc.core import config, vendor_loader  # noqa: E402
from autosound_tcc.state import ledger_line  # noqa: E402
from autosound_tcc.state.dsp_state import ProjectView, load_project_view  # noqa: E402
from autosound_tcc.ui.tcc import dsp_check, dsp_tree, i18n, setting_status, theme  # noqa: E402
from autosound_tcc.ui.tcc import detail_pane as detail_pane_module  # noqa: E402
from autosound_tcc.ui.tcc.detail_pane import DetailPane  # noqa: E402
from tests import _intake  # noqa: E402

GROUPS = [{"id": "physical_outputs", "label": "Output channels",
           "fields": ["hp", "lp", "gain_db", "ta_ms", "polarity", "eq"]}]
HELIX = {"dsp_profile": {"vendor": "Audiotec-Fischer", "name": "Helix DSP Ultra S", "groups": GROUPS}}
OTHER = {"dsp_profile": {"vendor": "Musway", "name": "M6V4", "groups": GROUPS}}
FULL = {"input_gain_db": -0.3, "sources": {"main": 0.0, "hec": -2.0, "digital": 1.5},
        "fx": {"realcenter": True, "dynamic_bass": False, "subxpander": True},
        "rtc": {"on": True, "curve": {"gstart0": -3.0, "fstart0": 800}},
        "bt": {"source": "AUX", "auto_switch": True}, "conductor": {"sub_lamps": 7},
        "status": "applied"}
SOURCE = {"name": "5S.pct6", "path": "/presets/5S.pct6", "md5": "46f99511aa" + "0" * 22,
          "saved": "291020261232", "pctool": "5.4.1", "device": "Helix DSP Ultra S",
          "read_at": "2026-10-29T14:03:00", "compared": "no difference"}
ROW = {"hp": None, "lp": None, "gain_db": -1.5, "ta_ms": 1.5, "polarity": "NORM", "status": "applied"}


def _app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _english():
    _app()
    i18n.set_language("en")


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """One history through the method's writer, read back the way the window reads it."""
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    _intake.seed(tmp_path)
    return vendor_loader.load_dsp_state().PresetHistory(str(tmp_path / "state"), "FULL", project_dir=str(tmp_path))


@pytest.fixture
def apply_module(monkeypatch):
    """The method's `apply.py`, whose sibling imports the vendor loader does not register."""
    monkeypatch.setitem(sys.modules, "state", vendor_loader.load_dsp_state())
    monkeypatch.setitem(sys.modules, "naming", vendor_loader.load_naming())
    spec = importlib.util.spec_from_file_location(
        "autosound_apply_for_test", vendor_loader.rew_tool_dir() / "state" / "apply.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bank(history, preset_settings=None, **extra):
    state = {"preset": "FULL", "sample_rate": 96000, "channels": {"w-L": dict(ROW)}, **extra}
    if preset_settings is not None:
        state["preset_settings"] = preset_settings
    return history.snapshot(state, note="fixture")


def _read(history, version=None, profile=HELIX):
    return load_project_view(history.root, "FULL", profile, version=version)


def _pane(view, compared=None, said="v_001"):
    pane = DetailPane()
    pane.set_view(view)
    if compared is not None:
        pane.use_compare("v_001", compared, said)
    pane.open_preset()
    return pane


def _cells(pane) -> dict:
    """`{the row's first cell: its value cell}`, as the table on screen has them."""
    table = pane._scroll.widget().findChild(QTableWidget)
    return {table.item(r, 0).text(): table.item(r, 1) for r in range(table.rowCount())
            if table.item(r, 0) is not None and table.item(r, 1) is not None}


def _label(key: str) -> str:
    return i18n.t(key)


def _colour(item) -> str:
    return item.foreground().color().name().lower()


def _is_changed(item) -> bool:
    return item.font().bold() and _colour(item) == QColor(theme.current_theme().info).name().lower()


def _grey(item) -> bool:
    return _colour(item) == QColor(theme.current_theme().faint).name().lower()


# ---- the shape, and what a missing field means ---------------------------------------------------


def test_the_field_table_is_the_method_s_own():
    """A second copy of the table drifts; this one is compared to the method's, path by path."""
    from autosound_tcc.state import preset_settings

    method = vendor_loader.load_dsp_state()._PRESET_FIELDS
    assert set(preset_settings.FIELDS) == set(method), "every field, and only those"
    for path, (kind, default, _label_text) in method.items():
        assert preset_settings.FIELDS[path] == (kind, default), path


def test_a_version_the_method_wrote_is_read_field_by_field(ledger):
    version = _bank(ledger, dict(FULL))
    view = _read(ledger, version)
    settings = {s.path: s for s in view.preset_settings.settings}
    assert settings["input_gain_db"].reading == "stated" and settings["input_gain_db"].value == -0.3
    assert settings["sources.hec"].value == -2.0 and settings["conductor.sub_lamps"].value == 7
    assert settings["bt.source"].value == "AUX" and settings["rtc.curve"].value == {"gstart0": -3.0, "fstart0": 800}
    assert settings["fx.realcenter"].value is True and settings["fx.dynamic_bass"].value is False
    assert view.preset_settings.status == "applied"


def test_a_field_not_stated_reads_as_the_method_says(ledger):
    """0 dB or off where nothing is said, unknown for two switches, a dash for three fields."""
    version = _bank(ledger, {"input_gain_db": -0.3, "status": "applied"})
    settings = {s.path: s for s in _read(ledger, version).preset_settings.settings}
    assert settings["sources.main"].reading == "default" and settings["sources.main"].value == 0.0
    assert settings["fx.realcenter"].reading == "default" and settings["fx.realcenter"].value is False
    assert settings["fx.dynamic_bass"].reading == "unknown" and settings["fx.subxpander"].reading == "unknown"
    assert settings["rtc.curve"].reading == "dash" and settings["bt.source"].reading == "dash"
    assert settings["conductor.sub_lamps"].reading == "dash"


def test_a_version_with_no_settings_is_read_as_nothing_stated(ledger):
    view = _read(ledger, _bank(ledger))
    assert view.preset_settings is not None, "a version without the field is valid"
    assert all(s.reading in ("default", "unknown", "dash") for s in view.preset_settings.settings)
    assert not view.preset_settings.any_stated, "nothing is stated"


def test_a_rig_with_no_ledger_has_no_settings_at_all():
    """The rig alone (`rig_view`): no version, so nothing to show for one."""
    assert ProjectView.from_dict({}, HELIX).preset_settings is None


def test_a_dsp_that_is_not_an_audiotec_has_only_the_input_gain(ledger):
    version = _bank(ledger, {"input_gain_db": -1.0, "status": "applied"})
    settings = _read(ledger, version, profile=OTHER).preset_settings.settings
    assert [s.path for s in settings] == ["input_gain_db"]


# ---- the dot of a trim-only proposal -----------------------------------------------------------


def test_a_trim_only_proposal_reads_proposed_until_it_is_attested(ledger, apply_module):
    _bank(ledger)
    apply_module.propose(ledger, {"preset_settings": {"input_gain_db": -0.3}}, note="a trim")
    assert _read(ledger).state == "proposed", "every channel row is applied; the trim is not entered"
    apply_module.attest(ledger)
    assert _read(ledger).state == "applied"


@pytest.mark.parametrize(("status", "said"), [
    ("candidate", "proposed"), ("proposed", "proposed"), ("applied", "applied"), ("measured", "applied"),
])
def test_the_header_s_state_follows_the_settings_status(ledger, status, said):
    version = _bank(ledger, {"input_gain_db": -0.3, "status": status})
    assert _read(ledger, version).state == said


def test_settings_with_no_status_make_no_claim(ledger):
    """Hand-written settings carry no status: nothing here says they wait."""
    version = _bank(ledger, {"input_gain_db": -0.3})
    assert _read(ledger, version).state == "applied"


def test_the_header_dot_waits_on_a_trim_and_its_hover_says_why(ledger, apply_module):
    _bank(ledger)
    apply_module.propose(ledger, {"preset_settings": {"input_gain_db": -0.3}}, note="a trim")
    view = _read(ledger)
    dot, tip = dsp_check.header(ledger.root, view, HELIX, "base", "FULL")
    assert dot == "wait"
    assert i18n.t("presetWaitingTip") in html.unescape(tip)


def test_a_proposed_trim_takes_the_checked_tick_away(ledger, tmp_path):
    with_file = {"file": "presets/a.pct6 (md5 ee627ad6…)"}
    trimmed = _bank(ledger, {"input_gain_db": -0.3, "status": "proposed"}, provenance=with_file)
    entered = _bank(ledger, {"input_gain_db": -0.3, "status": "applied"}, provenance=with_file)
    root = tmp_path / "state"
    assert ledger_line.checked_files(root, "FULL", entered), "the control: entered, with a file, is checked"
    assert not ledger_line.checked_files(root, "FULL", trimmed), "the trim waits, so the version is not checked"


# ---- the tab: greyed defaults, what it says ------------------------------------------------------


def test_the_pane_title_does_not_repeat_the_tab_beside_it(ledger):
    pane = _pane(_read(ledger, _bank(ledger, dict(FULL))))
    assert pane._title.text() != pane._tab_preset.text()


def test_the_tab_is_offered_with_a_version_and_named_preset(ledger):
    pane = _pane(_read(ledger, _bank(ledger, dict(FULL))))
    assert pane._tab_preset.text() == i18n.t("preset") and not pane._tab_preset.isHidden()
    assert pane._tab_preset.way() is not None


def test_a_rig_with_no_version_offers_no_tab():
    pane = DetailPane()
    pane.set_view(ProjectView.from_dict({}, HELIX))
    assert pane._tab_preset.isHidden()


def test_the_tab_shows_each_setting_the_method_stated(ledger):
    cells = _cells(_pane(_read(ledger, _bank(ledger, dict(FULL)))))
    assert cells[_label("presetInputGain")].text() == "-0.3 dB"
    assert cells[_label("presetHec")].text() == "-2 dB"
    assert cells[_label("presetRealcenter")].text() == i18n.t("presetOn")
    assert cells[_label("presetDynBass")].text() == i18n.t("presetOff"), "stated off, not unknown"
    assert cells[_label("presetRtc")].text() == i18n.t("presetOn")
    assert cells[_label("presetRtcCurve")].text() == "fstart0 800 · gstart0 -3", "as the method wrote it: sorted"
    assert cells[_label("presetBtSource")].text() == "AUX"
    assert cells[_label("presetConductor")].text() == "7"
    for key in ("presetInputGain", "presetDynBass", "presetBtSource"):
        assert not _grey(cells[_label(key)]), key


def test_a_setting_stated_at_its_default_is_a_fact_not_grey(ledger):
    version = _bank(ledger, {"input_gain_db": 0.0, "fx": {"realcenter": False}, "status": "applied"})
    cells = _cells(_pane(_read(ledger, version)))
    assert not _grey(cells[_label("presetInputGain")]) and cells[_label("presetInputGain")].text() == "0 dB"
    assert not _grey(cells[_label("presetRealcenter")])


def test_a_field_not_stated_is_grey_and_its_hover_says_why(ledger):
    cells = _cells(_pane(_read(ledger, _bank(ledger, {"input_gain_db": -0.3, "status": "applied"}))))
    main = cells[_label("presetMain")]
    assert main.text() == "0 dB" and _grey(main)
    assert main.toolTip() == i18n.t("presetDefaultTip")
    bass = cells[_label("presetDynBass")]
    assert bass.text() == i18n.t("presetUnknown") and _grey(bass)
    assert bass.toolTip() == i18n.t("presetUnknownTip")
    source = cells[_label("presetBtSource")]
    assert source.text() == "—" and _grey(source) and source.toolTip() == i18n.t("presetDashTip")


def test_a_version_with_no_settings_says_so_over_the_greyed_defaults(ledger):
    pane = _pane(_read(ledger, _bank(ledger)))
    from PySide6.QtWidgets import QLabel

    said = " ".join(lbl.text() for lbl in pane._scroll.widget().findChildren(QLabel))
    assert i18n.t("presetNothingStated") in said
    assert all(_grey(item) for key, item in _cells(pane).items()
               if key not in (_label("presetFile"),)), "every value is a default, greyed"


def test_a_dsp_that_is_not_an_audiotec_shows_only_its_input_gain_and_no_file(ledger):
    version = _bank(ledger, {"input_gain_db": -1.0, "status": "applied"})
    cells = _cells(_pane(_read(ledger, version, profile=OTHER)))
    assert set(cells) == {_label("presetInputGain")}, "no FX, RTC, BT, Conductor or file for it"


def test_the_status_of_the_settings_is_said(ledger):
    pane = _pane(_read(ledger, _bank(ledger, dict(FULL, status="proposed"))))
    from PySide6.QtWidgets import QLabel

    said = " ".join(lbl.text() for lbl in pane._scroll.widget().findChildren(QLabel))
    assert i18n.t("presetStatus_proposed") in said


# ---- the source file ---------------------------------------------------------------------------


def test_the_source_file_shape_is_one_reader_for_the_mark_and_the_tab():
    """`ledger_line` read this shape for the mark; the tab reads the same record."""
    read = ledger_line.source_file(SOURCE)
    saved = ledger_line._saved_file(SOURCE, None)
    assert (read.name, read.md5) == (saved.name, saved.md5) == ("5S.pct6", SOURCE["md5"])
    assert read.saved == "29.10.2026 12:32" and read.read_at == "29.10.2026 14:03"
    assert read.pctool == "5.4.1" and read.device == "Helix DSP Ultra S"
    assert read.compared and read.differences == ()


def test_a_comparison_that_found_something_is_listed():
    read = ledger_line.source_file(dict(SOURCE, compared=["w-L gain differs", "sub off"]))
    assert read.differences == ("w-L gain differs", "sub off")
    assert ledger_line.source_file({"name": "a.pct6"}).compared is False, "nothing written is nothing compared"


def test_the_tab_says_the_source_file_with_its_md5(ledger, apply_module):
    _bank(ledger, {"input_gain_db": -0.3, "status": "applied"})
    apply_module.attest(ledger, source_file=SOURCE)
    cells = _cells(_pane(_read(ledger)))
    item = cells[_label("presetFile")]
    assert item.text() == "5S.pct6" and item.toolTip() == "5S.pct6"
    assert cells[_label("presetMd5")].text() == "46f99511"
    assert cells[_label("presetSaved")].text() == "29.10.2026 12:32"
    assert cells[_label("presetReadAt")].text() == "29.10.2026 14:03"
    assert cells[_label("presetPctool")].text() == "5.4.1"
    assert cells[_label("presetDevice")].text() == "Helix DSP Ultra S"
    assert cells[_label("presetCompared")].text() == i18n.t("presetNoDifference")


def test_a_difference_from_the_file_is_said_in_warning_colour(ledger):
    bad = dict(SOURCE, compared=["w-L gain differs", "sub off"])
    pane = _pane(_read(ledger, _bank(ledger, {"input_gain_db": -0.3, "status": "applied", "source_file": bad})))
    cell = _cells(pane)[_label("presetCompared")]
    assert "w-L gain differs" in cell.text() and "sub off" in cell.text()
    assert _colour(cell) == QColor(theme.current_theme().warn).name().lower()


def test_a_version_not_read_from_a_file_says_so(ledger):
    cells = _cells(_pane(_read(ledger, _bank(ledger, {"input_gain_db": -0.3, "status": "proposed"}))))
    assert cells[_label("presetFile")].text() == i18n.t("presetNotFromFile")
    assert _label("presetMd5") not in cells


def test_a_file_name_cannot_inject_markup_into_a_hover(ledger):
    hostile = dict(SOURCE, name="<b>y.pct6")
    pane = _pane(_read(ledger, _bank(ledger, {"input_gain_db": -1.0, "status": "applied", "source_file": hostile})))
    tip = _cells(pane)[_label("presetFile")].toolTip()
    assert "<b>y" not in tip and "&lt;b&gt;" in tip, tip


# ---- the compare -------------------------------------------------------------------------------


def _compared(history, now, was, profile=HELIX):
    was_v, now_v = _bank(history, was), _bank(history, now)
    view, old = _read(history, now_v, profile), _read(history, was_v, profile)
    return _pane(view, compared=old), view, old


def test_a_changed_setting_is_blue_and_bold_with_what_it_was(ledger):
    pane, _view, _old = _compared(ledger, {"input_gain_db": -0.3, "status": "applied"},
                                  {"input_gain_db": -1.0, "status": "applied"})
    cell = _cells(pane)[_label("presetInputGain")]
    assert _is_changed(cell) and cell.data(detail_pane_module.CHANGED_ROLE) is True
    assert "-1 dB" in cell.toolTip()
    same = _cells(pane)[_label("presetMain")]
    assert not same.font().bold() and same.data(detail_pane_module.CHANGED_ROLE) is not True


def test_a_setting_against_a_version_with_no_settings_compares_by_the_defaults(ledger):
    pane, _view, _old = _compared(ledger, dict(FULL), None)
    cells = _cells(pane)
    assert _is_changed(cells[_label("presetInputGain")]) and "0 dB" in cells[_label("presetInputGain")].toolTip()
    assert not _is_changed(cells[_label("presetMain")]), "0 dB and missing are the same setting"
    assert not cells[_label("presetDynBass")].font().bold(), "stated off against nothing is no change"


def test_a_switch_turned_on_against_unknown_is_a_change(ledger):
    pane, _view, _old = _compared(ledger, {"fx": {"subxpander": True}, "status": "applied"}, None)
    cell = _cells(pane)[_label("presetSubxpander")]
    assert _is_changed(cell) and i18n.t("presetUnknown") in cell.toolTip()


@pytest.mark.parametrize(("now", "was"), [
    ({"fx": {"dynamic_bass": False}, "status": "applied"}, {"status": "applied", "input_gain_db": 0.0}),
    ({"status": "applied", "input_gain_db": 0.0}, {"fx": {"dynamic_bass": False}, "status": "applied"}),
])
def test_off_against_unknown_is_not_a_change_either_way(ledger, now, was):
    pane, _view, _old = _compared(ledger, now, was)
    cell = _cells(pane)[_label("presetDynBass")]
    assert not cell.font().bold() and cell.data(detail_pane_module.CHANGED_ROLE) is not True
    assert i18n.t("presetUnknownSideTip") in cell.toolTip()


def test_a_settings_status_or_source_file_alone_is_no_change(ledger):
    a = {"input_gain_db": -0.3, "status": "proposed"}
    b = {"input_gain_db": -0.3, "status": "applied", "source_file": SOURCE}
    pane, _view, _old = _compared(ledger, b, a)
    assert not _is_changed(_cells(pane)[_label("presetInputGain")])


# ---- the dot -----------------------------------------------------------------------------------


def test_the_dot_says_none_set_and_changed(ledger):
    bare, set_ = _read(ledger, _bank(ledger)), _read(ledger, _bank(ledger, {"input_gain_db": -0.3, "status": "applied"}))
    assert setting_status.preset_status(bare, None, False) == "none"
    assert setting_status.preset_status(set_, None, False) == "set"
    assert setting_status.preset_status(set_, bare, True) == "chg"
    assert setting_status.preset_status(set_, bare, False) == "set", "not blue with nothing compared"


def test_the_dot_of_off_against_unknown_is_no_change_and_other_dots_stand(ledger):
    bare = _read(ledger, _bank(ledger))
    stated = _read(ledger, _bank(ledger, {"fx": {"dynamic_bass": False}, "status": "applied"}))
    assert setting_status.preset_status(stated, bare, True) == "set", "off against unknown moved nothing"
    # The channel tabs' dots read the channels: a settings-only difference does not touch them.
    output = stated.groups[0]
    assert setting_status.group_status(output, bare.groups[0], True) == setting_status.group_status(output)


def test_the_dot_is_absent_with_no_settings_object():
    assert setting_status.preset_status(ProjectView.from_dict({}, HELIX), None, False) is None


# ---- malformed fields ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [
    {"input_gain_db": "loud"},
    {"input_gain_db": True},
    {"input_gain_db": float("nan")},
    {"fx": "RC"},
    {"fx": {"realcenter": "yes"}},
    {"rtc": {"curve": ["a"]}},
    {"rtc": {"curve": {"a": "x"}}},
    {"conductor": {"sub_lamps": -1}},
    {"bt": {"source": 3}},
    {"status": "maybe"},
    {"source_file": "5S.pct6"},
    {"source_file": {"name": 5, "md5": 5, "compared": {"odd": 1}}},
    "a string where an object should be",
])
def test_a_malformed_field_is_a_word_in_the_log_never_a_crash(bad, caplog, monkeypatch):
    raw = {"version": "v_001", "preset": "FULL", "channels": {"w-L": dict(ROW)}, "preset_settings": bad}
    monkeypatch.setattr(logging.getLogger("autosound_tcc"), "propagate", True)
    with caplog.at_level(logging.WARNING, logger="autosound_tcc"):
        view = ProjectView.from_dict(raw, HELIX)
        pane = _pane(view)
    _cells(pane)  # drawn
    assert any("preset_settings" in r.getMessage() for r in caplog.records), caplog.text
    assert setting_status.preset_status(view, view, True) in ("none", "set")


def test_an_unreadable_value_is_a_sign_with_what_the_ledger_holds_on_hover():
    raw = {"version": "v_001", "preset": "FULL", "channels": {"w-L": dict(ROW)},
           "preset_settings": {"input_gain_db": "<b>loud</b>"}}
    cell = _cells(_pane(ProjectView.from_dict(raw, HELIX)))[_label("presetInputGain")]
    assert cell.text() == "?" and _colour(cell) == QColor(theme.current_theme().warn).name().lower()
    assert "loud" in cell.toolTip() and "<b>" not in cell.toolTip()


# ---- language, theme, looks ----------------------------------------------------------------------


def test_the_tab_and_its_rows_follow_the_language(ledger):
    pane = _pane(_read(ledger, _bank(ledger, dict(FULL))))
    try:
        i18n.set_language("uk")
        assert pane._tab_preset.text() == "Пресет"
        assert _cells(pane)[i18n.t("presetInputGain")].text() == "-0.3 dB"
    finally:
        i18n.set_language("en")


def test_a_changed_value_follows_a_theme_switch(ledger, monkeypatch):
    app = _app()
    monkeypatch.setattr(theme, "_CURRENT", theme._CURRENT)
    sheet, palette = app.styleSheet(), QPalette(app.palette())
    try:
        theme.apply_theme(app, "dark")
        pane, _view, _old = _compared(ledger, {"input_gain_db": -0.3, "status": "applied"},
                                      {"input_gain_db": -1.0, "status": "applied"})
        cell = _cells(pane)[_label("presetInputGain")]
        assert _colour(cell) == QColor(theme.get_theme("dark").info).name().lower()
        theme.apply_theme(app, "light")
        QApplication.processEvents()
        assert _colour(cell) == QColor(theme.get_theme("light").info).name().lower()
    finally:
        app.setStyleSheet(sheet)
        app.setPalette(palette)


@pytest.mark.parametrize("look", ["normal", "light", "rounded", "typewriter"])
def test_the_table_is_drawn_in_every_font_look(ledger, look, monkeypatch):
    app = _app()
    monkeypatch.setattr(theme, "_CURRENT", theme._CURRENT)
    sheet, palette = app.styleSheet(), QPalette(app.palette())
    try:
        theme.apply_theme(app, "dark", font=look)
        pane, _view, _old = _compared(ledger, {"input_gain_db": -0.3, "status": "applied"},
                                      {"input_gain_db": -1.0, "status": "applied"})
        pane.resize(900, 500)
        pane.grab()
        assert _is_changed(_cells(pane)[_label("presetInputGain")])
    finally:
        app.setStyleSheet(sheet)
        app.setPalette(palette)


# ---- the DSP tree's section ----------------------------------------------------------------------


def _tree(view, compared=None, said="v_001"):
    tree = dsp_tree.DspTreeWidget()
    tree.set_view(view)
    tree.set_status({}, said)
    tree.set_compared(None if compared is None else list(compared.groups), compared)
    return tree


def _drawn(section, label: str) -> tuple:
    """`(the text, blue and bold, grey)`, read off the row's label as it is painted: wide enough to
    hold the line, so nothing is cut."""
    value = section._row_named(label)._value
    value.resize(2000, 30)
    value._elide()
    rich = value.text()
    t = theme.current_theme()
    return (QTextDocumentFragment.fromHtml(rich).toPlainText(),
            f"color:{t.info};font-weight:700" in rich, f"color:{t.faint}" in rich)


def _hover(section, label: str) -> str:
    return section._row_named(label).hover_tip.text()


def test_the_tree_has_a_preset_section_with_the_settings_and_the_dot(ledger):
    view = _read(ledger, _bank(ledger, dict(FULL)))
    tree = _tree(view)
    section = tree._preset
    assert section.title() == "ПРЕСЕТ" or section.title().upper() == i18n.t("preset").upper()
    assert _drawn(section, _label("presetInputGain"))[0] == "-0.3 dB"
    assert _drawn(section, _label("presetRealcenter"))[0] == i18n.t("presetOn")
    assert tree.status_dots()["preset"].status() == "set"


def test_a_tree_with_no_settings_shows_the_defaults_greyed(ledger):
    tree = _tree(_read(ledger, _bank(ledger)))
    section = tree._preset
    assert _drawn(section, _label("presetMain")) == ("0 dB", False, True), "the default, greyed"
    assert tree.status_dots()["preset"].status() == "none"


def test_a_rig_with_no_version_has_no_section():
    tree = _tree(ProjectView.from_dict({}, HELIX))
    assert tree._preset is None and "preset" not in tree.status_dots()


def test_the_tree_marks_a_changed_setting_and_turns_the_dot_blue(ledger):
    was = _bank(ledger, {"input_gain_db": -1.0, "status": "applied"})
    now = _bank(ledger, {"input_gain_db": -0.3, "status": "applied"})
    tree = _tree(_read(ledger, now), compared=_read(ledger, was))
    assert _drawn(tree._preset, _label("presetInputGain")) == ("-0.3 dB", True, False)
    assert not _drawn(tree._preset, _label("presetMain"))[1]
    assert tree.status_dots()["preset"].status() == "chg"
    tree.set_compared(None)
    assert _drawn(tree._preset, _label("presetInputGain")) == ("-0.3 dB", False, False)
    assert tree.status_dots()["preset"].status() == "set"


def test_the_section_can_be_rebuilt_and_its_row_opens_the_tab(ledger):
    view = _read(ledger, _bank(ledger, dict(FULL)))
    tree = _tree(view)
    first = tree._preset
    tree.set_view(view)
    assert tree._preset is not first, "a rebuild makes a new section"
    asked = []
    tree.tableRequested.connect(asked.append)
    tree._preset._params_row.clicked.emit()
    assert asked == ["preset"]


def test_the_section_survives_a_language_switch_before_its_rebuild(ledger):
    """`_sync_status_dots` may run between a language switch and the rebuild; rows go by the
    field, not by the label in the language they were built in."""
    view = _read(ledger, _bank(ledger, dict(FULL)))
    tree = _tree(view)
    try:
        i18n.set_language("uk")
        tree.set_compared(None)
    finally:
        i18n.set_language("en")
    assert tree.status_dots()["preset"].status() == "set"


def test_a_long_value_is_cut_with_an_ellipsis_inside_its_row(ledger):
    """The left column is narrow: a value runs out of room as a cut word, not off the edge."""
    version = _bank(ledger, {"input_gain_db": -0.3, "status": "applied", "source_file": SOURCE})
    tree = _tree(_read(ledger, version))
    tree._preset._set_collapsed(False)
    row = tree._preset._row_named(_label("presetFile"))
    label = row._value
    full = label.fontMetrics().horizontalAdvance(row.line.text)
    assert row.minimumSizeHint().width() < full, "the row asks less than the whole value"
    label.resize(40, 20)
    label._elide()
    assert "…" in label.text(), label.text()


def test_the_section_is_folded_by_default(ledger):
    tree = _tree(_read(ledger, _bank(ledger, dict(FULL))))
    assert tree._preset._children.isHidden(), "the third section stays closed until asked for"


def test_the_section_says_the_file_with_its_md5(ledger):
    version = _bank(ledger, {"input_gain_db": -0.3, "status": "applied", "source_file": SOURCE})
    tree = _tree(_read(ledger, version))
    assert _drawn(tree._preset, _label("presetFile"))[0] == "5S.pct6 · 46f99511"


# ---- the window: what is looked at, control mode, the tab's dot ------------------------------------


@pytest.fixture
def window(tmp_path, monkeypatch):
    from tests.test_control_layout import _window as build

    _intake.seed(tmp_path)
    profile = vendor_loader.load_dsp_profile()
    prof = {"dsp_profile": {"schema_version": profile.SCHEMA_VERSION if hasattr(profile, "SCHEMA_VERSION") else 3,
                            **HELIX["dsp_profile"]}}
    (tmp_path / "dsp_profile.json").write_text(json.dumps(prof), encoding="utf-8")
    state = vendor_loader.load_dsp_state()
    full = state.PresetHistory(str(tmp_path / "state"), "FULL", project_dir=str(tmp_path))
    channels = {"w-L": dict(ROW)}
    full.snapshot({"preset": "FULL", "sample_rate": 96000, "channels": channels}, note="one")
    second = full.snapshot({"preset": "FULL", "sample_rate": 96000, "channels": channels,
                            "preset_settings": {"input_gain_db": -1.0, "status": "applied"}}, note="two")
    third = full.snapshot({"preset": "FULL", "sample_rate": 96000, "channels": channels,
                           "preset_settings": dict(FULL, status="proposed")}, note="three")
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path / "state"))
    win = build(tmp_path, monkeypatch)
    assert win._view.version == third, "the fixture opens"
    win._test_older = second  # a string: what the tests name, not a widget
    yield win
    if win._control_layout.active:
        win._control_layout.leave()


def test_the_full_window_shows_head_s_settings_and_the_header_waits(window):
    window._on_table_requested("preset")
    assert window._detail._mode == "preset"
    assert _cells(window._detail)[_label("presetInputGain")].text() == "-0.3 dB"
    assert window._tree._preset is not None
    assert window._view.state == "proposed"
    assert window._dsp_section.dot_status() == "wait"


def test_a_looked_at_version_draws_its_own_settings_and_head_stays(window):
    from autosound_tcc.ui.tcc import shown_version

    head = window._view.version
    shown_version.show(window, window._test_older)
    window._on_table_requested("preset")
    assert _cells(window._detail)[_label("presetInputGain")].text() == "-1 dB"
    assert _drawn(window._tree._preset, _label("presetInputGain"))[0] == "-1 dB"
    assert window._view.version == head, "`window._view` stays HEAD"


def test_control_mode_has_the_tab_with_the_dot_and_the_compare(window):
    layout = window._control_layout
    layout.enter()
    index = next(i for i in range(layout.tabs.count()) if layout.tabs.tabText(i) == i18n.t("preset"))
    layout.tabs.setCurrentIndex(index)
    assert layout.tabs.tabBar().dot(index) == "chg"
    page = layout.tabs.widget(index)
    assert page._mode == "preset" and page._embedded
    assert page._head.isHidden(), "the tabs above are the navigation"
    cell = _cells(page)[_label("presetInputGain")]
    assert _is_changed(cell) and "-1 dB" in cell.toolTip()
    assert window._tree.active() == ("preset", "params"), "the tree lights the tab that shows it"


def test_control_mode_opens_the_tab_from_the_tree(window):
    layout = window._control_layout
    layout.enter()
    window._on_table_requested("preset")
    assert layout.tabs.tabText(layout.tabs.currentIndex()) == i18n.t("preset")


def test_the_tab_keeps_up_with_a_reload(window, tmp_path):
    window._on_table_requested("preset")
    state = vendor_loader.load_dsp_state()
    full = state.PresetHistory(str(tmp_path / "state"), "FULL", project_dir=str(tmp_path))
    full.snapshot({"preset": "FULL", "sample_rate": 96000, "channels": {"w-L": dict(ROW)},
                   "preset_settings": {"input_gain_db": -5.0, "status": "applied"}}, note="four")
    window._safe_load_project()
    assert _cells(window._detail)[_label("presetInputGain")].text() == "-5 dB"


def test_the_pane_keeps_the_tab_through_a_language_switch(window):
    window._on_table_requested("preset")
    try:
        i18n.set_language("uk")
        assert window._detail._mode == "preset"
        assert _cells(window._detail)[i18n.t("presetInputGain")].text() == "-0.3 dB"
    finally:
        i18n.set_language("en")


# ---- what the review found (the fix round) -----------------------------------------------------


APPLIED = {"input_gain_db": -0.3, "status": "applied"}


def _raw(settings):
    """A version the method would refuse to write, so read straight from the dict."""
    return ProjectView.from_dict({"version": "v_001", "preset": "FULL", "channels": {"w-L": dict(ROW)},
                                  "preset_settings": settings}, HELIX)


def _said(pane) -> str:
    return " ".join(lbl.text() for lbl in pane._scroll.widget().findChildren(QLabel))


@pytest.mark.parametrize(("key", "now", "was", "said", "tip"), [
    ("presetInputGain", {"bt": {"auto_switch": False}}, {"input_gain_db": -1.0}, "-1 dB", "presetDefaultTip"),
    ("presetSubxpander", {"bt": {"auto_switch": False}}, {"fx": {"subxpander": True}}, "was: on", "presetUnknownTip"),
    ("presetBtSource", {"bt": {"auto_switch": False}}, {"bt": {"source": "AUX"}}, "AUX", "presetDashTip"),
])
def test_a_value_not_stated_that_differs_is_blue_and_its_hover_says_both(ledger, key, now, was, said, tip):
    """Blue and bold, as every table's change; the hover keeps that this side is no reading."""
    pane, view, old = _compared(ledger, dict(now, status="applied"), dict(was, status="applied"))
    cell = _cells(pane)[_label(key)]
    assert _is_changed(cell), "changed is blue, greyed reading or not"
    assert said in cell.toolTip() and i18n.t(tip) in cell.toolTip(), cell.toolTip()
    tree = _tree(view, compared=old)
    assert _drawn(tree._preset, _label(key))[1], "blue in the tree too"
    assert said in _hover(tree._preset, _label(key)) and i18n.t(tip) in _hover(tree._preset, _label(key))


def test_a_was_with_markup_keeps_its_two_lines_on_the_hover():
    """`<qt>` is rich text, where a bare line break is a space."""
    now, was = _raw({"status": "applied"}), _raw({"bt": {"source": "<AUX>"}, "status": "applied"})
    tip = _cells(_pane(now, compared=was))[_label("presetBtSource")].toolTip()
    assert "&lt;AUX&gt;<br>" in tip and tip.startswith("<qt>"), tip


def test_an_unreadable_switch_keeps_its_hover_against_off():
    now, was = _raw({"fx": {"realcenter": "yes"}}), _raw({"fx": {"realcenter": False}})
    cell = _cells(_pane(now, compared=was))[_label("presetRealcenter")]
    assert cell.text() == "?" and "yes" in cell.toolTip(), cell.toolTip()


def test_off_against_an_unreadable_switch_is_not_said_to_be_unknown():
    now, was = _raw({"fx": {"realcenter": False}}), _raw({"fx": {"realcenter": "yes"}})
    tip = _cells(_pane(now, compared=was))[_label("presetRealcenter")].toolTip()
    assert i18n.t("presetUnknownSideTip") not in tip, tip


def test_a_version_whose_only_setting_is_unreadable_is_not_said_to_have_nothing():
    view = _raw({"input_gain_db": "loud", "status": "applied"})
    assert setting_status.preset_status(view, None, False) == "set"


def test_a_stated_value_against_an_unread_one_says_what_the_other_side_holds():
    now, was = _raw({"input_gain_db": -0.3}), _raw({"input_gain_db": "loud"})
    cell = _cells(_pane(now, compared=was))[_label("presetInputGain")]
    assert not _is_changed(cell), "nothing can be said to have moved"
    assert i18n.t("presetComparedUnreadTip").format(value=repr("loud")) in cell.toolTip()
    assert setting_status.preset_status(now, was, True) == "set"


def test_a_default_against_an_unread_one_keeps_its_own_hover_too():
    now, was = _raw({"status": "applied"}), _raw({"input_gain_db": "loud"})
    tip = _cells(_pane(now, compared=was))[_label("presetInputGain")].toolTip()
    assert i18n.t("presetDefaultTip") in tip and repr("loud") in tip, tip


def test_no_hover_shows_a_full_path(ledger):
    home = dict(SOURCE, path="/Users/someone/presets/5S.pct6")
    view = _read(ledger, _bank(ledger, dict(APPLIED, source_file=home)))
    tip = _cells(_pane(view))[_label("presetFile")].toolTip()
    tree = _tree(view)
    in_tree = _hover(tree._preset, _label("presetFile"))
    for said in (tip, in_tree):
        assert "/Users" not in said and "someone" not in said and "5S.pct6" in said, said


def test_a_string_source_file_gives_no_tick_as_the_tab_gives_no_file(ledger, tmp_path):
    version = _bank(ledger, dict(APPLIED))
    path = ledger_line.version_path(tmp_path / "state", "FULL", version)
    data = json.loads(path.read_text(encoding="utf-8"))
    # By hand: the method's writer refuses it, and a ledger is a file somebody can edit.
    data["preset_settings"]["source_file"] = "presets/a.pct6 (md5 ee627ad6…)"
    path.write_text(json.dumps(data), encoding="utf-8")
    view = _read(ledger, version)
    assert view.preset_settings.source_unread, "the control: the tab refuses it"
    assert not ledger_line.checked_files(tmp_path / "state", "FULL", version), "and the tick refuses it too"


@pytest.mark.parametrize("settings", [
    {"input_gain_db": 10 ** 400},
    {"rtc": {"curve": {"gstart0": 10 ** 400}}},
])
def test_a_number_too_big_for_a_float_is_unreadable_and_the_version_still_loads(settings):
    view = _raw(dict(settings, status="applied"))
    assert any(s.reading == "unread" for s in view.preset_settings.settings)
    _cells(_pane(view))  # drawn


def test_the_tab_is_marked_against_the_new_compare_after_a_reload(window, tmp_path):
    """The reload redraws the open tab, and only then is the new compare loaded."""
    window._on_table_requested("preset")
    assert "-1 dB" in _cells(window._detail)[_label("presetInputGain")].toolTip(), "the control"
    state = vendor_loader.load_dsp_state()
    full = state.PresetHistory(str(tmp_path / "state"), "FULL", project_dir=str(tmp_path))
    full.snapshot({"preset": "FULL", "sample_rate": 96000, "channels": {"w-L": dict(ROW)},
                   "preset_settings": {"input_gain_db": -5.0, "status": "applied"}}, note="four")
    window._safe_load_project()
    assert "-0.3 dB" in _cells(window._detail)[_label("presetInputGain")].toolTip()


# ---- what a person sees, that the first pass read off the stored line ------------------------------


def test_the_tree_s_grey_follows_a_theme_switch(ledger, monkeypatch):
    app = _app()
    monkeypatch.setattr(theme, "_CURRENT", theme._CURRENT)
    sheet, palette = app.styleSheet(), QPalette(app.palette())
    try:
        theme.apply_theme(app, "dark")
        tree = _tree(_read(ledger, _bank(ledger)))
        label = _label("presetMain")
        assert _drawn(tree._preset, label)[2], "greyed in dark"
        theme.apply_theme(app, "light")
        QApplication.processEvents()
        assert _drawn(tree._preset, label)[2], "greyed in light, the repainted row's own colour"
    finally:
        app.setStyleSheet(sheet)
        app.setPalette(palette)


def test_a_real_click_on_the_tab_opens_it(ledger):
    pane = DetailPane()
    pane.set_view(_read(ledger, _bank(ledger, dict(FULL))))
    assert pane._mode != "preset"
    pane._tab_preset.clicked.emit()
    assert pane._mode == "preset" and _cells(pane)[_label("presetInputGain")].text() == "-0.3 dB"


def test_the_compare_reaches_the_tree_in_the_real_window(window):
    window._control_layout.enter()
    window._sync_status_dots()
    assert window._tree.status_dots()["preset"].status() == "chg"
    assert _drawn(window._tree._preset, _label("presetInputGain"))[1], "blue in the window's own tree"


def test_a_compare_chosen_with_the_tab_open_redraws_it(ledger):
    was, now = _bank(ledger, {"input_gain_db": -1.0, "status": "applied"}), _bank(ledger, APPLIED)
    pane = _pane(_read(ledger, now))
    assert not _is_changed(_cells(pane)[_label("presetInputGain")])
    pane.use_compare(was, _read(ledger, was), was)
    assert _is_changed(_cells(pane)[_label("presetInputGain")])


def test_refresh_with_stays_on_the_tab_after_a_table(ledger):
    view = _read(ledger, _bank(ledger, dict(FULL)))
    pane = DetailPane()
    pane.set_view(view)
    pane.open_table(view.groups[0])
    pane.open_preset()
    pane.refresh_with(view.groups[0])
    assert pane._mode == "preset"


def _control_preset_page(layout):
    index = next(i for i in range(layout.tabs.count()) if layout.tabs.tabText(i) == i18n.t("preset"))
    return index, layout.tabs.widget(index)


def test_control_tab_draws_the_looked_at_version(window):
    from autosound_tcc.ui.tcc import shown_version

    shown_version.show(window, window._test_older)
    layout = window._control_layout
    layout.enter()
    _index, page = _control_preset_page(layout)
    assert _cells(page)[_label("presetInputGain")].text() == "-1 dB"


def test_control_dot_reads_the_looked_at_version(window):
    """The first version has no settings, and HEAD has: the dot on the tab is the looked-at one's."""
    from autosound_tcc.ui.tcc import shown_version

    shown_version.show(window, "v_001")
    layout = window._control_layout
    layout.enter()
    if window._detail._compare_version:
        window._detail.select_compare(None)
    index, _page = _control_preset_page(layout)
    layout.sync_dots()
    assert layout.tabs.tabBar().dot(index) == "none"


def test_a_setting_stated_only_at_its_default_gives_no_set_dot(ledger):
    view = _read(ledger, _bank(ledger, {"input_gain_db": 0.0, "status": "applied"}))
    assert setting_status.preset_status(view, None, False) == "none"


def test_a_setting_taken_back_to_its_default_is_a_change(ledger):
    pane, _view, _old = _compared(ledger, {"status": "applied", "bt": {"auto_switch": False}},
                                  {"input_gain_db": -1.0, "status": "applied"})
    assert _is_changed(_cells(pane)[_label("presetInputGain")])


def test_nothing_stated_does_not_stand_over_real_settings(ledger):
    assert i18n.t("presetNothingStated") not in _said(_pane(_read(ledger, _bank(ledger, dict(FULL)))))
    at_default = _read(ledger, _bank(ledger, {"input_gain_db": 0.0, "status": "applied"}))
    assert i18n.t("presetNothingStated") not in _said(_pane(at_default))


def test_the_header_says_no_wait_when_nothing_waits(ledger):
    view = _read(ledger, _bank(ledger, APPLIED))
    _dot, tip = dsp_check.header(ledger.root, view, HELIX, "base", "FULL")
    assert i18n.t("presetWaitingTip") not in html.unescape(tip)


def test_the_header_keeps_the_sentence_the_window_passes(ledger, apply_module):
    """`now` is `now_in_dsp`'s plain sentence, as `MainWindow` passes it; the hover is markup."""
    _bank(ledger)
    apply_module.propose(ledger, {"preset_settings": {"input_gain_db": -0.3}}, note="a trim")
    _dot, tip = dsp_check.header(ledger.root, _read(ledger), HELIX, "base", "FULL", now="the sentence")
    assert "the sentence" in tip and "&lt;br" not in tip, tip


def test_an_applied_trim_over_a_proposed_row_keeps_the_dot_waiting(ledger):
    version = _bank(ledger, APPLIED, channels={"w-L": dict(ROW, status="proposed")})
    assert _read(ledger, version).state == "proposed"


def test_the_state_of_a_version_with_no_settings_is_what_it_was(ledger):
    assert _read(ledger, _bank(ledger)).state == "applied"


def test_a_candidate_with_a_file_has_no_tick(ledger, tmp_path):
    version = _bank(ledger, {"input_gain_db": -0.3, "status": "candidate"},
                    provenance={"file": "presets/a.pct6 (md5 ee627ad6…)"})
    assert not ledger_line.checked_files(tmp_path / "state", "FULL", version)


def test_a_difference_written_as_a_string_is_said(ledger):
    bad = dict(SOURCE, compared="w-L gain differs")
    pane = _pane(_read(ledger, _bank(ledger, dict(APPLIED, source_file=bad))))
    assert "w-L gain differs" in _cells(pane)[_label("presetCompared")].text()


def test_the_statuses_are_the_method_s():
    from autosound_tcc.state import preset_settings

    assert set(preset_settings._STATUSES) == set(vendor_loader.load_dsp_state().STATUSES)


def test_a_dsp_named_only_helix_is_an_audiotec():
    from autosound_tcc.state import preset_settings

    assert preset_settings.is_audiotec(None, "Helix DSP Pro") and preset_settings.is_audiotec("Helix", None)
