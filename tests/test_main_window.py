"""Headless smoke test of the Qt app shell (brief §9: tests must run without a display).

Forces the offscreen QPA platform if nothing else already set one, so this runs the same way in
CI as it does locally without a real screen.
"""

from __future__ import annotations

import json
import os
import subprocess

from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QCloseEvent, QFont  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFrame,
    QLabel,
    QPushButton,
    QSplitter,
    QWidget,
)

from autosound_tcc.core import config  # noqa: E402

from tests import _intake  # noqa: E402
from autosound_tcc.ui.tcc import i18n, main_window  # noqa: E402
from autosound_tcc.ui.tcc.main_window import MainWindow, _force_project_dir_env  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


#: Windows that have built a CurveDialog, held until the end of the test that made them.
#: pyqtgraph's `PlotItem` builds parentless QMenus and QWidgetActions on every instance, and
#: letting Python collect them mid-construction segfaults the process from inside a LATER
#: `PlotItem.__init__` — reproduced here the moment these tests were added (2026-08-12).
#:
#: Keeping them for the whole run was the first answer and it swapped one crash for another:
#: nothing is collected, so nothing crashes that way, but the live PlotItems pile up and the
#: process dies on a later construction instead. Measured cause, 2026-08-13: a destroyed-looking
#: window leaves 7 live QMenus behind, because `deleteLater()` needs a DeferredDelete flush that
#: `processEvents()` does not perform. With the flush below, the count is 0 and nothing piles up.
_KEEP_WINDOWS: list = []
#
#: Destroying them at the end of each test instead — through Qt, with the
#: DeferredDelete flush that `processEvents()` alone does not perform — was tried on
#: 2026-08-13 and MEASURED WORSE: 2 crashes in 5 full runs against a baseline of about
#: 1 in 10, and it added a second signature, a recursive ~QBoxLayout at interpreter
#: exit. Reverted. It was not wasted: it surfaced a real i18n bug, a retranslate
#: listener calling into a widget whose C++ half was already freed.



def _control_only_widgets(window: MainWindow) -> list:
    return [
        window._session_btn,
        window._terminal_btn,
        window._ai_main_lbl,
        window._ai_main_combo,
        window._ai_critic_lbl,
        window._ai_critic_combo,
        window._critic_status,
    ]


def test_main_window_builds_five_regions():
    _app()
    window = MainWindow()
    splitter = window.findChild(QSplitter)
    assert splitter is not None
    assert splitter.count() == 3  # left, center, right
    assert window._left is not None
    assert window._center is not None
    assert window._right is not None


def test_theme_toggle_switches_and_persists_in_memory(monkeypatch):
    from tests import _windows

    _app()
    window = MainWindow()
    # The switch styles this window, not every window the run has left alive (F-065).
    _windows.theme_on_the_window(monkeypatch, window)
    start = window._mode
    window._toggle_theme()
    assert window._mode != start
    window._toggle_theme()
    assert window._mode == start


def _click_queued(button) -> None:
    """A click the OS queued: posted, so it reaches `button` only when the event loop next runs."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    centre = QPointF(button.rect().center())
    for kind, held in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                       (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        QApplication.postEvent(button, QMouseEvent(kind, centre, centre, Qt.MouseButton.LeftButton,
                                                   held, Qt.KeyboardModifier.NoModifier))


def test_the_theme_switch_wears_the_wait_cursor_and_takes_no_second_click(monkeypatch):
    """VM-12: on Windows the switch takes 1–2 s with no sign, and a second click lands. The
    Arbiter: «добре мати значок очікування і не давати нажати ще раз до зміни теми». The wait
    cursor while the sheet applies; a click during the switch — made again, or queued by the OS
    behind the busy one — is dropped, not switched back afterwards."""
    from tests import _windows

    _app()
    window = MainWindow()
    _windows.theme_on_the_window(monkeypatch, window)
    applying, seen = main_window.apply_theme, []

    def slow(app, mode, scale=1.0):
        cursor = QApplication.overrideCursor()
        seen.append((mode, cursor.shape() if cursor else None, window._theme_btn.isEnabled()))
        if len(seen) == 1:
            window._toggle_theme()
            _click_queued(window._theme_btn)
        return applying(app, mode, scale)

    monkeypatch.setattr(main_window, "apply_theme", slow)
    start = window._mode
    other = "light" if start == "dark" else "dark"
    window._theme_btn.click()
    QApplication.processEvents()

    assert seen == [(other, Qt.CursorShape.WaitCursor, False)]
    assert window._mode == other
    assert QApplication.overrideCursor() is None and window._theme_btn.isEnabled()
    # Once the new theme is on, a click switches again.
    window._theme_btn.click()
    QApplication.processEvents()
    assert window._mode == start and len(seen) == 2


def _shown_row(section, key: str) -> str:
    """The value a section's `key → value` row shows (`_kv_row`), whole."""
    from autosound_tcc.ui.tcc import copy_menu
    from autosound_tcc.ui.tcc.labels import ElidedLabel

    for row in section.findChildren(QWidget):
        if row.property("class") == "paramrow":
            key_label, value = row.findChildren(ElidedLabel)[:2]
            if copy_menu.full_text(key_label) == key:
                return copy_menu.full_text(value)
    raise AssertionError(f"no «{key}» row in the section")


def test_the_project_params_theme_row_follows_every_switch(monkeypatch):
    """VM-8: after ◐ to dark the Project params «Theme» row still said «light» — the row was
    written when the section was built and never again. Through the switch itself (◐, the wait
    cursor and all), both ways."""
    from tests import _windows

    _app()
    window = MainWindow()
    _windows.theme_on_the_window(monkeypatch, window)
    word = {"dark": i18n.t("cfgThemeDark"), "light": i18n.t("cfgThemeLight")}
    assert _shown_row(window._project_section, i18n.t("cfgTheme")) == word[window._mode]
    for _ in range(2):
        window._theme_btn.click()
        QApplication.processEvents()
        assert _shown_row(window._project_section, i18n.t("cfgTheme")) == word[window._mode], (
            f"the theme is {window._mode}")


def test_the_language_switch_wears_the_wait_cursor_and_takes_no_second_pick(monkeypatch):
    """VM-14: the Arbiter saw the theme switch's wait cursor (VM-12) and asked for the same on the
    language. The wait cursor while the window re-translates, the select off; a second pick during
    the switch -- the select's or the menu's -- is dropped, and the select names the language the
    window is in; the cursor and the select come back on every path, a failed switch's too."""
    _app()
    window = MainWindow()
    combo = window._lang_combo
    retranslating, seen = window._retranslate, []

    def slow() -> None:
        cursor = QApplication.overrideCursor()
        seen.append((i18n.current_language(), cursor.shape() if cursor else None,
                     combo.isEnabled()))
        if len(seen) == 1:
            combo.setCurrentIndex(combo.findData("pl"))  # picked again in the select
            window._on_language_selected("uk")  # and from the menu
        retranslating()

    def broken() -> None:
        raise RuntimeError("the re-translation failed")

    monkeypatch.setattr(window, "_retranslate", slow)
    try:
        combo.setCurrentIndex(combo.findData("de"))
        QApplication.processEvents()
        assert seen == [("de", Qt.CursorShape.WaitCursor, False)], seen
        assert i18n.current_language() == "de" and combo.currentData() == "de"
        assert QApplication.overrideCursor() is None and combo.isEnabled()

        monkeypatch.setattr(window, "_retranslate", broken)
        with pytest.raises(RuntimeError):
            window._on_language_selected("pl")
        assert QApplication.overrideCursor() is None and combo.isEnabled()
        assert combo.currentData() == i18n.current_language()

        monkeypatch.setattr(window, "_retranslate", retranslating)
        window._on_language_selected("en")
        assert i18n.current_language() == "en" and combo.currentData() == "en"
    finally:
        i18n.set_language("en")


def test_tree_renders_when_a_profile_and_ledger_are_present(tmp_path, monkeypatch):
    """Same profile+ledger shape used in test_dsp_state.py's MUSWAY-style regression test,
    routed through the real MainWindow load path instead of ProjectView directly."""
    import json

    profile = {
        "dsp_profile": {
            "name": "M6V4", "vendor": "Musway",
            "groups": [
                {"id": "physical_outputs", "label": "Output channels",
                 "fields": ["hp", "lp", "gain_db"]},
            ],
        }
    }
    (tmp_path / "dsp_profile.json").write_text(json.dumps(profile))
    preset_dir = tmp_path / "TESTPRESET"
    preset_dir.mkdir()
    ledger = {"preset": "TESTPRESET", "sample_rate": 48000,
              "channels": {"w_L": {"hp": {"f": 80}, "lp": {"f": 4000}, "gain_db": -2.0}}}
    (preset_dir / "v_001.json").write_text(json.dumps(ledger))
    (preset_dir / "HEAD").write_text("v_001")

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path))

    _app()
    window = MainWindow()
    assert window._dsp_section.sub_text() == "Musway M6V4"
    assert not window._tree.isHidden()
    assert window._left_status.isHidden()


def test_switching_preset_does_not_duplicate_tree_sections(tmp_path, monkeypatch):
    """Regression: DspTreeWidget.set_view() clearing old sections with deleteLater() alone (no
    setParent(None) first) leaves them as real children until the event loop next spins --
    switching presets synchronously (exactly what the header combo's currentTextChanged does)
    never triggers that, so the old groups would still count via findChildren() without the fix.
    """
    import json

    from autosound_tcc.ui.tcc.dsp_tree import TreeGroupSection

    profile = {
        "dsp_profile": {
            "name": "M6V4", "vendor": "Musway",
            "groups": [{"id": "physical_outputs", "label": "Output channels",
                        "fields": ["hp", "lp", "gain_db"]}],
        }
    }
    (tmp_path / "dsp_profile.json").write_text(json.dumps(profile))
    for name in ("PRESET_A", "PRESET_B"):
        preset_dir = tmp_path / name
        preset_dir.mkdir()
        ledger = {"preset": name, "sample_rate": 48000, "target": f"target-{name}",
                  "channels": {"w_L": {"hp": {"f": 80}, "lp": {"f": 4000}, "gain_db": -2.0}}}
        (preset_dir / "v_001.json").write_text(json.dumps(ledger))
        (preset_dir / "HEAD").write_text("v_001")

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_TCC_PRESET", "PRESET_A")

    _app()
    window = MainWindow()
    assert len(window._tree._layout.parentWidget().findChildren(TreeGroupSection)) == 1

    window._preset_combo.setCurrentIndex(window._preset_combo.findData("PRESET_B"))
    assert window._target_label.text() == "target-PRESET_B ↗"
    sections = window._tree._layout.parentWidget().findChildren(TreeGroupSection)
    assert len(sections) == 1, f"expected exactly 1 section, found {len(sections)} (stale ones?)"


def test_preset_switch_refreshes_an_already_open_table(tmp_path, monkeypatch):
    """Regression (user report 2026-07-28): a table left open across a preset switch kept
    showing the OLD preset's frozen MUTE (and everything else) since `ProfileGroup`/`GroupRow`
    are immutable snapshots and nothing told the open `DetailPane` a new version had loaded."""
    import json

    profile = {
        "dsp_profile": {
            "name": "M6V4", "vendor": "Musway",
            "groups": [{"id": "physical_outputs", "label": "Output channels",
                        "fields": ["hp", "lp", "gain_db", "mute"]}],
        }
    }
    (tmp_path / "dsp_profile.json").write_text(json.dumps(profile))
    for name, muted in (("PRESET_A", False), ("PRESET_B", True)):
        preset_dir = tmp_path / name
        preset_dir.mkdir()
        ledger = {"preset": name, "sample_rate": 48000,
                  "channels": {"w_L": {"hp": {"f": 80}, "lp": {"f": 4000}, "gain_db": -2.0,
                                        "mute": muted}}}
        (preset_dir / "v_001.json").write_text(json.dumps(ledger))
        (preset_dir / "HEAD").write_text("v_001")

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_TCC_PRESET", "PRESET_A")

    def _mute_column(table):
        for c in range(table.columnCount()):
            if table.horizontalHeaderItem(c).text() == "Mute":
                return c
        raise AssertionError("no Mute column found")

    _app()
    window = MainWindow()
    window._on_table_requested("physical_outputs")
    table = window._detail._scroll.widget()
    mute_col = _mute_column(table)
    assert table.item(0, mute_col).text() == "—"

    window._preset_combo.setCurrentIndex(window._preset_combo.findData("PRESET_B"))

    assert window._detail.current_group_id() == "physical_outputs"
    table = window._detail._scroll.widget()
    assert table.item(0, _mute_column(table)).text() == "MUTE"


def _kv_texts(section) -> dict[str, str]:
    """(key, value) pairs from every `_kv_row` in a `SidebarSection`'s body — reads the widget
    tree by the `.pk`/`.pv` label classes `_kv_row` stamps, since those rows have no object name."""
    keys = [w.text() for w in section.findChildren(QLabel) if w.property("class") == "pk"]
    values = [w.text() for w in section.findChildren(QLabel) if w.property("class") == "pv"]
    return dict(zip(keys, values))


def test_project_json_feeds_system_params_and_channel_summary(tmp_path, monkeypatch):
    """SCR-015/016 (`state/project_view.py`): System params renders `project.json`'s car, DSP, amp
    and mic facts plus the channel-tier summary, and Project params keeps the open-question chips
    -- none of this is re-derived from the ledger, all of it comes straight from the file.

    The channel summary moved here from Project params on 2026-09-06 (tcc#11): SCR-016 put it
    there because it is not part of the DSP ledger, which is true and is not the same claim as
    "not part of the rig"."""
    import json

    profile = {
        "dsp_profile": {
            "name": "M6V4", "vendor": "Musway",
            "groups": [{"id": "physical_outputs", "label": "Output channels",
                        "fields": ["hp", "lp", "gain_db"]}],
        }
    }
    (tmp_path / "dsp_profile.json").write_text(json.dumps(profile))
    (tmp_path / "project.json").write_text(json.dumps({
        "car": {"make": "VW", "model": "Passat", "generation": "B8", "body": "sedan"},
        "dsp": {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"},
        "amps": [{"role": "front", "make": "Helix", "model": "P Six DSP"}],
        "mic": {"model": "UMIK-1"},
        "channel_summary": {"virtual_channels": {"total": 8, "off": 1}},
        "_open_questions": ["mic.calibration_file"],
    }))
    preset_dir = tmp_path / "TESTPRESET"
    preset_dir.mkdir()
    ledger = {"preset": "TESTPRESET", "sample_rate": 48000,
              "channels": {"w_L": {"hp": {"f": 80}, "lp": {"f": 4000}, "gain_db": -2.0}}}
    (preset_dir / "v_001.json").write_text(json.dumps(ledger))
    (preset_dir / "HEAD").write_text("v_001")

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path))

    _app()
    window = MainWindow()

    system_kv = _kv_texts(window._system_section)
    assert system_kv["DSP"] == "Audiotec-Fischer Helix DSP Ultra S"
    assert system_kv["Amp (front)"] == "Helix P Six DSP"
    assert system_kv["Mic"] == "UMIK-1"
    # The cabin all of the above is installed in, and the first row of the section.
    assert system_kv[i18n.t("carLabel")] == "VW Passat B8 sedan"
    # Translated through i18n, not prettified out of the JSON key (F-006).
    assert system_kv["Virtual channels"] == "8 (1 off)"

    # The open questions live in a collapsible group of their own, with a count on its header, so
    # they stop reading as a footnote to the channel-summary row above them (F-005).
    from autosound_tcc.ui.tcc.sidebar_section import CollapsibleGroup

    group = next(g for g in window._project_section.findChildren(CollapsibleGroup)
                 if g._id == "open_questions")
    chip_texts = [
        w.text() for w in group.findChildren(QLabel)
        if "open-q" in str(w.property("class") or "")
    ]
    assert any("mic.calibration_file" in t for t in chip_texts)
    # Accented and copyable: these are the only rows in the panel asking for something, and the
    # answer to one usually gets pasted somewhere else (F-018).
    asking = next(w for w in group.findChildren(QLabel)
                  if "open-q" in str(w.property("class") or ""))
    assert asking.hasSelectedText() is False and asking.textInteractionFlags() != \
        Qt.TextInteractionFlag.NoTextInteraction
    assert any(w.text() == "1" for w in group.findChildren(QLabel)
               if w.property("class") == "cnt"), "the header counts them"


def test_a_project_with_no_body_recorded_says_so_rather_than_showing_nothing(tmp_path, monkeypatch):
    """`save_car` calls an unrecorded body a SILENT loss — "nothing breaks today, and the material
    is simply not there tomorrow". A blank row is exactly how silence stays silent (tcc#11)."""
    import json

    from autosound_tcc.ui.tcc.labels import ElidedLabel

    (tmp_path / "project.json").write_text(json.dumps({
        "car": {"make": "VW", "model": "Passat", "generation": "B8"},  # no body
        "dsp": {"vendor": "Musway", "model": "M6V4"},
    }))
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path))

    _app()
    window = MainWindow()

    kv = _kv_texts(window._system_section)
    assert kv[i18n.t("carLabel")] == "VW Passat B8", "what IS recorded still shows"
    asking = [
        w.text() for w in window._system_section.findChildren(QLabel)
        if "open-q" in str(w.property("class") or "") and not isinstance(w, ElidedLabel)
    ]
    assert any(i18n.t("carNoBody") in t for t in asking), asking


def test_the_composer_is_the_way_in():
    """The view/control switch is out of v1 (2026-08-05), so nothing is hidden by mode. What is
    hidden is hidden for its own reason: starting a session is what sending the first message
    does, and front-end B is not in the workflow being built."""
    _app()
    window = MainWindow()

    assert not window._dialog._composer.isHidden()
    assert window._session_btn.isHidden()   # appears only to offer a restart
    assert window._terminal_btn.isHidden()  # front-end B, deliberately out of the way


def test_no_project_clears_every_mock_panel():
    """A folder with no dsp_profile.json at all must not look like a live tuning session --
    the AI dialog, plan, and measurement panels all default to prototype mock content, and
    MainWindow is the only thing that knows whether a real project backs any of it."""
    _app()
    window = MainWindow()

    # "which project" lives in the header menu now; two controls for one act were what made
    # "create" and "open" look like different things.
    assert window._create_project_btn.isHidden()
    assert len(window._dialog._bubbles) == 0
    assert window._plan_panel.plan == ()
    assert not window._meas_panel._no_project_label.isHidden()
    assert window._meas_panel._legend.isHidden()


def test_a_broken_profile_clears_panels_but_does_not_offer_create(tmp_path, monkeypatch):
    """A profile that exists but fails to load is a project that's there, just broken -- offering
    "create new" would overwrite/duplicate it, so only the true no-file-at-all case gets that
    button (still no mock content, though -- there's nothing real to show either way)."""
    (tmp_path / "dsp_profile.json").write_text("{ not valid json")
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path))

    _app()
    window = MainWindow()

    assert window._create_project_btn.isHidden()
    assert len(window._dialog._bubbles) == 0
    assert window._plan_panel.plan == ()


def test_found_profile_hides_create_button_and_says_there_is_no_capture_task_yet(tmp_path, monkeypatch):
    """The success path must not accidentally clear panels meant to stay on their mock/real
    content -- this mirrors test_tree_renders_when_a_profile_and_ledger_are_present's fixture."""
    import json

    profile = {
        "dsp_profile": {
            "name": "M6V4", "vendor": "Musway",
            "groups": [{"id": "physical_outputs", "label": "Output channels",
                        "fields": ["hp", "lp", "gain_db"]}],
        }
    }
    (tmp_path / "dsp_profile.json").write_text(json.dumps(profile))
    preset_dir = tmp_path / "TESTPRESET"
    preset_dir.mkdir()
    ledger = {"preset": "TESTPRESET", "sample_rate": 48000,
              "channels": {"w_L": {"hp": {"f": 80}, "lp": {"f": 4000}, "gain_db": -2.0}}}
    (preset_dir / "v_001.json").write_text(json.dumps(ledger))
    (preset_dir / "HEAD").write_text("v_001")
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path))

    _app()
    window = MainWindow()

    assert window._create_project_btn.isHidden()
    # A profile and a ledger are not a capture task: that is derived from the phase, the glossary
    # and the ledger version, and saying so beats the invented "capture series v10" that used to
    # greet anyone opening a project.
    assert not window._meas_panel._no_project_label.isHidden()
    assert i18n.t("measNoTask") in window._meas_panel._no_project_label.text()


def test_language_switch_does_not_bring_the_mock_grid_back():
    """Regression: MeasurementPanel.retranslate() unconditionally rebuilt the grid via
    show_session(), silently undoing set_no_project() on every language switch.

    i18n.set_language() is process-global, not per-window -- reset back to "en" (the suite's
    implicit default, since nothing else in this file touches language) so this test can't leak
    "uk" into whichever test happens to run next.
    """
    _app()
    window = MainWindow()
    try:
        assert window._meas_panel._no_project_label.isHidden() is False

        window._on_language_selected("en")

        assert window._meas_panel._legend.isHidden()
        assert len(window._meas_panel._rows) == 0
        assert window._meas_panel._no_project_label.isHidden() is False
        assert window._meas_panel._no_project_label.text() == "No project — nothing to capture yet."

        window._on_language_selected("uk")
        assert window._meas_panel._no_project_label.text() == "Немає проєкту — знімати поки нічого."
    finally:
        window._on_language_selected("en")


def test_force_project_dir_env_overrides_a_pre_set_env_var(tmp_path, monkeypatch):
    """Regression: config.set_project_dir() only writes QSettings, which AUTOSOUND_PROJECT_DIR
    always outranks. The isolated-test fixture always sets that env var (matching a real, common
    launch pattern -- see the user's own `AUTOSOUND_PROJECT_DIR=... .venv/bin/autosound-tcc`) --
    without this override, a fresh MainWindow built after "Create new project" in the SAME process
    would silently reopen the OLD folder instead of the one just created."""
    new_dir = tmp_path / "brand_new_project"
    new_dir.mkdir()
    # Registers the current value with monkeypatch so its teardown reverts _force_project_dir_env's
    # raw os.environ write below, regardless of what set it originally.
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", os.environ.get("AUTOSOUND_PROJECT_DIR", ""))

    _force_project_dir_env(new_dir)

    assert config.project_dir() == new_dir


def test_stale_preset_override_from_a_different_project_is_ignored(tmp_path, monkeypatch):
    """Regression (2026-07-29, found live): "ui/preset" is a GLOBAL QSettings value, not scoped
    per project -- a preset name left over from an EARLIER, unrelated project (e.g. "FULL") must
    not be force-applied to a brand-new project that has no such preset, or _load_project() tries
    to load a ledger that was never there and shows a raw load error instead of the clean
    "no preset ledger found" state."""
    import json

    from autosound_tcc.ui.tcc.app_settings import get_settings

    profile = {
        "dsp_profile": {
            "name": "Helix DSP Ultra S", "vendor": "Audiotec-Fischer",
            "groups": [{"id": "physical_outputs", "label": "Output channels",
                        "fields": ["hp", "lp", "gain_db"]}],
        }
    }
    (tmp_path / "dsp_profile.json").write_text(json.dumps(profile))
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path / "state"))  # no presets here
    get_settings().setValue("ui/preset", "FULL")  # stale, from a different project entirely

    _app()
    window = MainWindow()

    # The profile is known, the ledger is not — the panel names the DSP and says what is still
    # missing, in the user's language rather than as a path.
    assert window._left_status.text().startswith("Audiotec-Fischer Helix DSP Ultra S")
    assert i18n.t("leftNoLedger") in window._left_status.text()


def test_diagnostics_button_opens_the_panel_with_the_last_report():
    """The header's ⚕ is the one always-reachable way to the disk-state report (TCC-TZ.md §8)."""
    from autosound_tcc.core.contract_check import ContractReport

    _app()
    window = MainWindow()
    report = ContractReport(ok=True, project_dir="/tmp/proj", checked_at="2026-07-31T12:00:00+00:00")
    window._on_contract_result(report)

    window._diag_btn.click()

    assert window._diag_dialog is not None
    assert window._diag_dialog.isVisible()
    assert window._diag_dialog._report is report


class _Worker:
    """A session worker as far as the window asks: has its thread finished (QThread's own)."""

    def __init__(self) -> None:
        self.finished = False

    def isFinished(self) -> bool:  # noqa: N802 — QThread's name
        return self.finished


def test_a_session_that_has_ended_no_longer_holds_the_tool_rows(monkeypatch):
    """omp and Claude Code are what a session runs on, so their update rows wait while one runs
    (ruling 21, tcc#98) — and only while it RUNS. The dialog panel keeps its worker after a session
    ends, so asking it held the rows until TCC quit: after omp died (#97), where updating omp is
    the remedy. The window's own worker is the answer — finished, or dropped, is not running."""
    from autosound_tcc.core import updates

    monkeypatch.setattr(updates, "tools_status", lambda: updates.ToolsStatus(
        True, (updates.Tool("omp", "17.3.8", "18.2.4", True),)))
    _app()
    window = MainWindow()
    window._diag_btn.click()
    dialog = window._diag_dialog
    dialog._tabs.setCurrentWidget(dialog._updates_tab)
    for _ in range(5):
        if dialog._tools_job is None:
            break
        dialog._tools_job.join(timeout=10)
        dialog._poll_tools_job()
    omp = dialog._tool_rows["omp"][1]

    assert dialog._session_live() is False and omp.isEnabled()
    worker = _Worker()
    window._agent_worker = worker
    try:
        dialog._read_session()
        assert dialog._session_live() is True and not omp.isEnabled(), "a running session holds it"
        worker.finished = True  # omp died, the thread ended — the window still holds the worker
        dialog._read_session()
        assert dialog._session_live() is False and omp.isEnabled(), "an ended one does not"
        worker.finished = False
        window._dialog._worker = worker  # what the dialog panel keeps after any session
        window._agent_worker = None  # ...and the window drops on Save, restart, fresh
        dialog._read_session()
        assert dialog._session_live() is False and omp.isEnabled()
    finally:
        window._agent_worker = None
        window._dialog._worker = None


def test_a_failing_contract_check_lands_in_the_status_strip_not_the_dialog():
    """§8's whole point: disk-state facts are not chat bubbles. A problem the user hasn't opened
    the panel for still has to be visible somewhere that isn't the conversation."""
    from autosound_tcc.core.contract_check import ContractReport

    _app()
    window = MainWindow()
    bubbles_before = len(window._dialog._bubbles)

    window._on_contract_result(
        ContractReport(
            ok=False,
            project_dir="/tmp/proj",
            files=({"file": "project.json", "exists": True, "valid": False,
                    "issues": ["bad schema_version"]},),
        )
    )

    # `isVisible()` is False for any child of a window that was never shown; `isHidden()` is what
    # actually reflects this widget's own setVisible state.
    assert not window._status_strip.isHidden()
    assert "1" in window._status_strip.text()
    assert len(window._dialog._bubbles) == bubbles_before


def test_no_contract_subprocess_is_spawned_under_the_test_escape_hatch(monkeypatch):
    """`AUTOSOUND_TCC_MCP=0` (set by conftest) is the suite's "no background side-effects" switch —
    a Python subprocess per constructed window belongs behind it, like the MCP server and REW ping.
    """
    from autosound_tcc.core import contract_check

    calls = []
    monkeypatch.setattr(contract_check, "run", lambda *a, **k: calls.append(1))

    _app()
    window = MainWindow()
    window._start_contract_check()

    assert calls == []
    assert window._contract_worker is None


def test_a_config_change_reaches_the_status_strip(tmp_path, monkeypatch):
    """SCR-014 says "never silently". A tuner who hasn't opened the plan still has to learn that
    the car changed under their measurements."""
    from autosound_tcc.core import vendor_loader

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    # A real session reaches phase 2 through intake and phase 0, and both now hold: the machine
    # files have to exist (2026-08-12) and a target has to be recorded (SCR-036). This test starts
    # mid-tune, so it seeds what a real one would have produced by then.
    _intake.seed(tmp_path)
    process = vendor_loader.load_process().Process(str(tmp_path / "process"))
    _intake.open_phases(process)
    process.enter_phase("2")
    proj = vendor_loader.load_project().Project(str(tmp_path))
    proj.save(proj.load())
    proj.record_change(process, "project.json", "driver replaced",
                       impact="remeasure: [w-L, w-R]")

    _app()
    window = MainWindow()

    assert not window._status_strip.isHidden()
    text = window._status_strip.text()
    assert "driver replaced" in text and "w-L" in text and "w-R" in text


# ---- the generator picker is also the harness picker ------------------------


def _catalogue(monkeypatch, models):
    import json
    import subprocess

    from autosound_tcc.core import model_choices

    monkeypatch.setattr(model_choices, "omp_available", lambda: True)
    monkeypatch.setattr(
        model_choices.child,
        "run_bounded",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps({"models": models}), ""),
    )


def test_the_picker_offers_claudes_models_out_of_the_box():
    """Nothing marked, no omp needed: TCC is usable on a machine that only has the Claude CLI."""
    _app()
    window = MainWindow()

    keys = [window._ai_main_combo.itemData(i) for i in range(window._ai_main_combo.count())]

    # Opus 5.5 and Fable 5.1 beside their predecessors, which are still served (finding 48, tcc#64).
    assert keys[1:] == ["sdk:claude-opus-5-5", "sdk:claude-opus-5", "sdk:claude-sonnet-5",
                        "sdk:claude-fable-5-1", "sdk:claude-fable-5"]


def test_a_row_from_the_shipped_list_says_when_the_list_was_checked():
    """Finding 48: «the newest Claude models cannot be picked, and nothing says the list is old».
    With no key to ask the Models API, the rows are TCC's own list — and the hover says so, dated."""
    from PySide6.QtCore import Qt

    from autosound_tcc.core import model_choices

    _app()
    window = MainWindow()
    combo = window._ai_main_combo
    row = combo.findData("sdk:claude-opus-5-5")
    tip = str(combo.itemData(row, Qt.ItemDataRole.ToolTipRole))
    assert model_choices.SDK_MODELS_VERIFIED in tip


def test_nothing_is_chosen_until_someone_chooses_it():
    """Pre-selecting the first entry makes a session startable by someone who never noticed a
    default -- and starting one costs a turn."""
    _app()
    window = MainWindow()

    assert window._generator_choice() is None
    assert window._ai_main_combo.itemData(0) == ""


def test_choosing_a_model_arms_the_button_without_starting_anything():
    _app()
    window = MainWindow()

    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-opus-5"))

    assert getattr(window, "_agent_worker", None) is None
    assert "not started" in window._dialog._session_chip.text().lower()


def test_the_placeholder_disappears_once_a_model_is_chosen(tmp_path, monkeypatch):
    """It goes *after* the signal has been delivered: removing an item from a combo inside that
    combo's own `currentIndexChanged` frees the view's internals mid-walk, which segfaulted."""
    _app()
    window = MainWindow()
    combo = window._ai_main_combo
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("— choose —", "")
    combo.addItem("Claude Sonnet 5", "sdk:claude-sonnet-5")
    combo.setCurrentIndex(1)
    combo.blockSignals(False)

    window._on_generator_model_changed(1)
    window._drop_model_placeholder()

    assert combo.findData("") < 0

def test_a_marked_omp_model_joins_the_picker_and_selects_its_harness(monkeypatch):
    """The user picks a model; which adapter carries it follows from that, not from inference."""
    _catalogue(monkeypatch, [{
        "provider": "google", "selector": "google/gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro", "cost": {"input": 1.25, "output": 10.0},
    }])
    _app()
    window = MainWindow()
    window._settings.setValue("ai/active_omp", "google/gemini-3.1-pro-preview")
    window._reload_model_choices()

    index = window._ai_main_combo.findData("omp:google/gemini-3.1-pro-preview")
    assert index >= 0
    window._ai_main_combo.setCurrentIndex(index)

    choice = window._generator_choice()
    assert choice.harness == "omp"
    assert choice.model == "google/gemini-3.1-pro-preview"


def test_a_free_model_says_so_in_the_picker(monkeypatch):
    """Cost is the axis the harness was chosen on; it belongs where the model is chosen."""
    _catalogue(monkeypatch, [{
        "provider": "opencode", "selector": "opencode/nemotron-3-ultra-free",
        "name": "Nemotron 3 Ultra", "cost": {"input": 0, "output": 0},
    }])
    _app()
    window = MainWindow()
    window._settings.setValue("ai/active_omp", "opencode/nemotron-3-ultra-free")
    window._reload_model_choices()

    index = window._ai_main_combo.findData("omp:opencode/nemotron-3-ultra-free")
    assert "free" in window._ai_main_combo.itemText(index)


def test_the_picked_model_survives_a_restart(monkeypatch):
    _catalogue(monkeypatch, [{
        "provider": "google", "selector": "google/gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro", "cost": {"input": 1.0, "output": 1.0},
    }])
    _app()
    window = MainWindow()
    window._settings.setValue("ai/active_omp", "google/gemini-3.1-pro-preview")
    window._reload_model_choices()
    window._ai_main_combo.setCurrentIndex(
        window._ai_main_combo.findData("omp:google/gemini-3.1-pro-preview")
    )
    window._on_generator_model_changed(0)

    again = MainWindow()

    assert again._generator_choice().model == "google/gemini-3.1-pro-preview"


def test_the_critic_picker_carries_the_generator_list_plus_local_clis(monkeypatch):
    """One registry, and then the routes only a reviewer can use — a one-shot CLI call is
    something the skill's script can already make, a Generator session is not."""
    from autosound_tcc.core import model_choices as mc

    _catalogue(monkeypatch, [{
        "provider": "google", "selector": "google/gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro", "cost": {"input": 1.0, "output": 1.0},
    }])
    monkeypatch.setattr(mc, "_CLI_CACHE", {"agy": [
        mc.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro (High)",
                  provider="google")
    ]})
    monkeypatch.setattr(mc, "cli_available", lambda harness: False)
    _app()
    window = MainWindow()
    window._settings.setValue("ai/active_omp", "google/gemini-3.1-pro-preview")
    window._reload_model_choices()

    generator = {window._ai_main_combo.itemData(i) for i in range(window._ai_main_combo.count())}
    reviewer = {window._ai_critic_combo.itemData(i) for i in range(window._ai_critic_combo.count())}

    assert "agy:gemini-3.1-pro-high" in reviewer
    assert "agy:gemini-3.1-pro-high" not in generator
    assert generator - {""} <= reviewer  # everything the Generator offers, the Critic offers too


def test_every_entry_says_which_route_it_takes(monkeypatch):
    """The pain this fixes: an API balance gone negative next to an unused subscription, because
    two rows with the same model name were two different accounts."""
    from autosound_tcc.core import model_choices as mc

    _catalogue(monkeypatch, [{
        "provider": "google", "selector": "google/gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro", "cost": {"input": 1.0, "output": 1.0},
    }])
    monkeypatch.setattr(mc, "_CLI_CACHE", {})
    monkeypatch.setattr(mc, "cli_available", lambda harness: False)
    _app()
    window = MainWindow()
    window._settings.setValue("ai/active_omp", "google/gemini-3.1-pro-preview")
    window._reload_model_choices()

    labels = [
        window._ai_main_combo.itemText(i)
        for i in range(window._ai_main_combo.count())
        if window._ai_main_combo.itemData(i)
    ]
    assert labels, "the picker should have entries to label"
    assert all(label.split(" · ")[0] in ("SDK", "OMP", "AGY", "CODEX") for label in labels), labels
    assert any(label.startswith("OMP · ") for label in labels)
    # The recommendation is WEIGHT now, not words: the badge repeated what the bold already said
    # (user, 2026-08-12), so the assertion moved to the font role.
    from PySide6.QtCore import Qt as _Qt

    fonts = [window._ai_main_combo.itemData(i, _Qt.ItemDataRole.FontRole)
             for i in range(window._ai_main_combo.count())]
    assert any(font is not None and font.bold() for font in fonts)


def test_a_reviewer_whose_vendor_is_configured_is_not_marked(monkeypatch, real_critic_reaches):
    """The same Claude entry, on a machine that has the key — the label follows the transport."""
    from autosound_tcc.core import model_choices as mc

    _catalogue(monkeypatch, [])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(mc.shutil, "which", lambda _binary: None)
    _app()
    window = MainWindow()

    claude = window._ai_critic_combo.findData("sdk:claude-opus-5")
    assert "clipboard" not in window._ai_critic_combo.itemText(claude).lower()


def test_a_gemini_reviewer_is_not_marked(monkeypatch, real_critic_reaches):
    from autosound_tcc.core import model_choices as mc

    _catalogue(monkeypatch, [{
        "provider": "google", "selector": "google/gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro", "cost": {"input": 1.0, "output": 1.0},
    }])
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setattr(mc.shutil, "which", lambda binary: "/usr/bin/omp" if binary == "omp" else None)
    _app()
    window = MainWindow()
    window._settings.setValue("ai/active_omp", "google/gemini-3.1-pro-preview")
    window._reload_model_choices()

    # Through the key (tcc#74) and through omp, where the method has the route and omp is here.
    for key in ("api:gemini-pro-latest", "omp:google/gemini-3.1-pro-preview"):
        index = window._ai_critic_combo.findData(key)
        assert index >= 0, key
        assert "clipboard" not in window._ai_critic_combo.itemText(index).lower(), key


def test_the_reviewer_model_reaches_the_subprocess_by_name(monkeypatch):
    """`critic.run` steers the script through its env var and knows nothing about model names, so
    what the picker publishes has to be the model, not the label."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    window._ai_critic_combo.setCurrentIndex(window._ai_critic_combo.findData("sdk:claude-sonnet-5"))

    assert window._bridge.snapshot()["critic_model"] == "claude-sonnet-5"


def test_the_terminal_opens_on_the_cli_that_carries_the_picked_model(monkeypatch):
    """Two front-ends that disagree about which model is running would make the picker a lie in
    one of them."""
    _catalogue(monkeypatch, [{
        "provider": "google", "selector": "google/gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro", "cost": {"input": 1.0, "output": 1.0},
    }])
    _app()
    window = MainWindow()
    window._settings.setValue("ai/active_omp", "google/gemini-3.1-pro-preview")
    window._reload_model_choices()
    window._ai_main_combo.setCurrentIndex(
        window._ai_main_combo.findData("omp:google/gemini-3.1-pro-preview")
    )
    seen = {}
    monkeypatch.setattr(
        main_window.terminal_launcher,
        "launch",
        lambda project_dir, **kw: seen.update(kw) or kw["cli"],
    )

    window._open_terminal()

    assert seen["cli"] == "omp"
    assert seen["model"] == "google/gemini-3.1-pro-preview"
    # Without the overlay TCC's tools stay behind xd:// and the terminal is quietly weaker.
    assert "--config" in seen["extra"]


def test_a_claude_pick_opens_claude(monkeypatch):
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-sonnet-5"))
    seen = {}
    monkeypatch.setattr(
        main_window.terminal_launcher,
        "launch",
        lambda project_dir, **kw: seen.update(kw) or kw["cli"],
    )

    window._open_terminal()

    assert seen["cli"] == "claude"
    assert seen["model"] == "claude-sonnet-5"
    assert seen["extra"] == ()


def test_the_terminal_session_carries_the_reviewers_route(monkeypatch):
    """hub #236, tcc#134 (task 9 review, I1): the terminal is the other front-end, and its own run
    of the method follows the footer's route as the in-app session does."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-sonnet-5"))
    monkeypatch.setattr(main_window.critic, "session_env",
                        lambda project_dir: {"AUTOSOUND_CRITIC_MODEL": "m", "AUTOSOUND_CRITIC_VIA": "cli"})
    seen = {}
    monkeypatch.setattr(
        main_window.terminal_launcher,
        "launch",
        lambda project_dir, **kw: seen.update(kw) or kw["cli"],
    )

    window._open_terminal()

    assert seen["env"] == {"AUTOSOUND_CRITIC_MODEL": "m", "AUTOSOUND_CRITIC_VIA": "cli"}


def test_the_sdk_is_named_in_the_generator_picker(monkeypatch):
    """Which harness carries the model is the licensing split; it is named, not inferred."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    index = window._ai_main_combo.findData("sdk:claude-opus-5")
    assert window._ai_main_combo.itemText(index).startswith("SDK · ")


def test_changing_the_model_mid_session_offers_a_restart_not_a_silent_swap(monkeypatch):
    """Neither harness can change model in a live conversation — the SDK takes it at connect, omp
    as `--model` when the process starts. So the button says restart rather than letting someone
    find out afterwards."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-opus-5"))
    window._running_model = "sdk:claude-opus-5"

    class _Worker:
        def shutdown(self, *a, **kw):
            return True

    window._agent_worker = _Worker()
    window._update_session_button()
    assert window._session_btn.isHidden()  # same model, nothing to offer

    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-sonnet-5"))

    assert not window._session_btn.isHidden()
    assert "sonnet" in window._session_btn.text().lower()
    assert "restart" in window._session_btn.text().lower()


class _HandoffWorker:
    """Enough of AgentWorker to drive the handoff: it records what it was asked to save."""

    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class _Signals(QObject):
            turn_done = Signal()
            failed = Signal(str)

        self._signals = _Signals()
        self.turn_done = self._signals.turn_done
        self.failed = self._signals.failed
        self.sent: list[str] = []
        self.shutdowns = 0
        self.finished = False

    def isFinished(self):  # noqa: N802 (QThread's name)
        return self.finished

    def send(self, text):
        self.sent.append(text)

    def shutdown(self, *a, **kw):
        self.shutdowns += 1
        return True


def test_the_outgoing_model_is_asked_to_write_the_state_down_before_it_ends(monkeypatch):
    """A conversation is disposable; the files are the record. Killing the session first throws
    away the one thing that makes the restart cheap."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-opus-5"))
    window._running_model = "sdk:claude-opus-5"
    worker = _HandoffWorker()
    window._agent_worker = worker
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-sonnet-5"))

    window._start_tuning_session()

    assert worker.shutdowns == 0  # still alive: it is being asked to save
    assert len(worker.sent) == 1
    assert "finish_step" in worker.sent[0] and "autosound_context.md" in worker.sent[0]
    assert not window._session_btn.isEnabled()


def test_the_swap_happens_once_the_state_is_saved(monkeypatch):
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-opus-5"))
    window._running_model = "sdk:claude-opus-5"
    worker = _HandoffWorker()
    window._agent_worker = worker
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-sonnet-5"))
    launched = []
    monkeypatch.setattr(MainWindow, "_launch_session", lambda self, *a, **kw: launched.append(True))

    window._start_tuning_session()
    worker.turn_done.emit()

    assert worker.shutdowns == 1
    assert launched == [True]


def test_a_second_click_does_not_start_a_second_handoff(monkeypatch):
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-opus-5"))
    window._running_model = "sdk:claude-opus-5"
    worker = _HandoffWorker()
    window._agent_worker = worker
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-sonnet-5"))

    window._start_tuning_session()
    window._start_tuning_session()

    assert len(worker.sent) == 1


def test_a_failed_handoff_still_restarts(monkeypatch):
    """The handoff saves what can be saved; it does not make the swap conditional on saving it."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-opus-5"))
    window._running_model = "sdk:claude-opus-5"
    worker = _HandoffWorker()
    window._agent_worker = worker
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-sonnet-5"))
    launched = []
    monkeypatch.setattr(MainWindow, "_launch_session", lambda self, *a, **kw: launched.append(True))

    window._start_tuning_session()
    worker.failed.emit("provider refused")

    assert worker.shutdowns == 1
    assert launched == [True]


def _record_stops(monkeypatch) -> list:
    """Spy on the one call under test. The skill's writer is exercised for real in
    `test_process_writer`; what is worth pinning here is that the window calls it at all, and
    exactly once — a stop written twice is a lie about the session as much as one never written."""
    from autosound_tcc.core import process_writer

    stops: list = []
    monkeypatch.setattr(
        process_writer,
        "close_session",
        lambda project_dir: stops.append(project_dir) or (True, ""),
    )
    return stops


def test_a_restart_writes_the_stop_before_the_next_session_starts(monkeypatch):
    """SKL-029: `session_started` had no counterpart, so a session that ended in order and one
    whose process was killed left the same journal — it just stopped. The break this catches is a
    handoff that swaps models without saying the old session ended."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    stops = _record_stops(monkeypatch)
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-opus-5"))
    window._running_model = "sdk:claude-opus-5"
    worker = _HandoffWorker()
    window._agent_worker = worker
    window._session_open = True
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-sonnet-5"))
    monkeypatch.setattr(MainWindow, "_launch_session", lambda self, *a, **kw: None)

    window._start_tuning_session()
    worker.turn_done.emit()

    assert len(stops) == 1


def test_a_save_is_not_a_stop(monkeypatch):
    """The plain Save exists to get the project onto disk mid-session; the conversation carries on.
    Writing `session_closed` there would make the journal say the session ended and then kept
    recording, which is worse than saying nothing."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    stops = _record_stops(monkeypatch)
    worker = _HandoffWorker()
    window._agent_worker = worker
    window._session_open = True

    window._hand_off(worker, "save")
    worker.turn_done.emit()

    assert stops == []


def test_quitting_writes_the_stop_once_not_once_per_close(monkeypatch):
    """`_finish_handoff("quit")` closes the window, and `closeEvent` runs again on the way out.
    Both are on the stop path, so the guard is what keeps the journal from carrying two
    `session_closed` events for one session."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`
    stops = _record_stops(monkeypatch)
    worker = _HandoffWorker()
    window._agent_worker = worker
    window._session_open = True
    # As the real path does: `closeEvent` sets this before handing off, and it is what stops the
    # close that follows the turn from asking the save question all over again.
    window._quitting = True

    window._hand_off(worker, "quit")
    worker.turn_done.emit()

    assert len(stops) == 1


def test_what_is_still_open_at_a_stop_is_shown_not_swallowed(monkeypatch):
    """SKL-025: an open capture round after TCC exits is lost state — its status lives in REW's
    measurement list and goes when REW does. The report exists; the break this catches is TCC
    reading it and saying nothing, which leaves the person with no idea anything was open."""
    from autosound_tcc.core import process_writer

    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    monkeypatch.setattr(
        process_writer,
        "close_session",
        lambda project_dir: (False, "OPEN ROUND r3 at v_004: 2 taken, 1 still expected (w-R_2)"),
    )
    window._session_open = True
    before = len(window._dialog._bubbles)

    window._record_session_stop()

    said = " ".join(
        label.text()
        for bubble in window._dialog._bubbles[before:]
        for label in bubble.findChildren(QLabel)
    )
    assert "OPEN ROUND r3" in said, "the report has to reach the person, not just the log"
    assert "w-R_2" in said, "and it must carry WHICH measurement is missing"


def test_a_grant_the_project_folder_makes_is_said_before_the_session_runs_in_orange(monkeypatch):
    """HUB-050, narrowed by the Arbiter on 2026-09-27 (finding 83, tcc#75): a folder's own hooks
    are not announced any more — the car project's logging hook came up on every start and meant
    nothing to him — and what is shown is a problem, as a warning: a folder granting tools without
    asking, past TCC's own permission choice.

    The break this catches: a session starting silently on a folder that grants `Bash(rm:*)`."""
    from autosound_tcc.core import project_trust

    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    monkeypatch.setattr(project_trust, "warnings",
                        lambda project_dir: project_trust.Warnings(allows=["Bash(rm:*)"]))
    before = len(window._dialog._bubbles)

    window._say_what_the_project_applies()

    bubbles = window._dialog._bubbles[before:]
    said = " ".join(label.text() for bubble in bubbles for label in bubble.findChildren(QLabel))
    assert "Bash(rm:*)" in said
    assert "msg-sys-warn" in bubbles[0].property("class")
    assert "LEDGER" not in said.upper()


def test_a_project_that_applies_nothing_is_not_announced(monkeypatch):
    """A line on every start would be noise, and noise is how a real one gets scrolled past."""
    from autosound_tcc.core import project_trust

    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    monkeypatch.setattr(project_trust, "warnings", lambda project_dir: project_trust.Warnings())
    before = len(window._dialog._bubbles)

    window._say_what_the_project_applies()

    assert len(window._dialog._bubbles) == before


def test_the_machine_is_asked_about_agent_commands_once_and_only_once(monkeypatch):
    """HUB-028, the user's ruling of 2026-09-06: do not ask by default, but ask ONCE after
    installing and remember the answer. Until now the default was a constant nobody had chosen —
    a decision made in a source file rather than by the person it protects."""
    from autosound_tcc.core import omp_session
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    window._settings.remove(main_window._MACHINE_GATE_KEY)  # a machine nobody has answered on
    asked = []
    monkeypatch.setattr(
        MainWindow, "_ask_machine_gate",
        lambda self: asked.append(True) or omp_session.GATE_FOREIGN,
    )

    # Reading never asks — that is the whole reason the two are separate methods.
    assert window._effective_gate() == omp_session.GATE_DEFAULT
    assert asked == []

    window._ensure_machine_gate_answered()
    window._ensure_machine_gate_answered()

    assert len(asked) == 1, "asked once; the answer is remembered, not re-asked"
    assert window._effective_gate() == omp_session.GATE_FOREIGN


def test_the_answer_outlives_the_window(monkeypatch):
    """QSettings UserScope — the machine, not the project and not this process."""
    from autosound_tcc.core import omp_session
    _catalogue(monkeypatch, [])
    _app()
    first = MainWindow()
    first._settings.remove(main_window._MACHINE_GATE_KEY)
    monkeypatch.setattr(MainWindow, "_ask_machine_gate", lambda self: omp_session.GATE_WRITES)
    first._ensure_machine_gate_answered()

    second = MainWindow()
    monkeypatch.setattr(
        MainWindow, "_ask_machine_gate",
        lambda self: pytest.fail("a second window must not ask again"),
    )

    assert second._effective_gate() == omp_session.GATE_WRITES


def test_a_project_that_set_its_own_mode_wins_over_the_machine(monkeypatch, tmp_path):
    """The machine answer is a DEFAULT for new projects. A project that was set deliberately keeps
    what it was set to — otherwise answering the install question would silently retune every car
    already in progress."""
    from autosound_tcc.core import omp_session
    from autosound_tcc.core import config, project_settings

    _catalogue(monkeypatch, [])
    _app()
    _force_project_dir_env(tmp_path)
    window = MainWindow()
    window._settings.setValue(main_window._MACHINE_GATE_KEY, omp_session.GATE_AUTO)
    project_settings.set_value(config.tcc_dir(tmp_path), "gate", omp_session.GATE_WRITES)
    monkeypatch.setattr(
        MainWindow, "_ask_machine_gate", lambda self: pytest.fail("nothing to ask: both are set")
    )

    assert window._effective_gate() == omp_session.GATE_WRITES


def test_the_model_choice_belongs_to_the_project_not_the_person(monkeypatch, tmp_path):
    """Remembering it globally means opening a second folder silently re-points the first."""
    from autosound_tcc.core import project_settings

    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-sonnet-5"))

    assert project_settings.get(config.tcc_dir(), "generator") == "sdk:claude-sonnet-5"


def test_the_project_menu_names_the_open_folder(monkeypatch):
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    assert config.chosen_project_dir().name in window._project_label.text()


def test_saving_and_starting_over_need_a_running_session(monkeypatch):
    """Both act on what the model currently knows; with nothing running there is nothing to save."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    assert not window._save_state_action.isEnabled()
    assert not window._fresh_session_action.isEnabled()


def test_saving_writes_the_state_and_keeps_talking(monkeypatch):
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    worker = _HandoffWorker()
    window._agent_worker = worker
    launched = []
    monkeypatch.setattr(MainWindow, "_launch_session", lambda self, *a, **kw: launched.append(True))

    window._save_project_state()
    worker.turn_done.emit()

    assert worker.sent  # the model was asked to write it down
    assert worker.shutdowns == 0  # ...and the conversation is still open
    assert launched == []


def test_a_fresh_session_saves_first_then_clears_the_context(monkeypatch):
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    worker = _HandoffWorker()
    window._agent_worker = worker
    launched = []
    monkeypatch.setattr(
        MainWindow, "_launch_session", lambda self, *a, **kw: launched.append(kw.get("fresh"))
    )

    window._start_fresh_session()
    worker.turn_done.emit()

    assert worker.sent
    assert worker.shutdowns == 1
    assert launched == [True]  # not resumed: the project state is on disk to be re-read


def test_the_menu_explains_what_the_labels_cannot(monkeypatch):
    """"Start a new session" and "restart on a different model" are different acts, and the
    difference is the whole reason the third action exists."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    tip = window._fresh_session_action.toolTip().lower()
    assert "same model" in tip or "тій самій" in tip
    assert window._save_state_action.toolTip()
    assert window._open_project_action.toolTip()

    # Shown through the app's own rounded popup, not the platform tooltip whose window frame
    # stays square on macOS regardless of QSS (user report 2026-07-28).
    from autosound_tcc.ui.tcc import rounded_tooltip

    window._show_action_tip(window._fresh_session_action)
    assert rounded_tooltip.RoundedTooltip.instance().isVisible()
    assert window._menu_btn.menu().property("class") == "support-menu"


def test_choosing_a_different_folder_relaunches_rather_than_pretending(monkeypatch, tmp_path):
    """"Remembered for next time" is not what anyone means by choosing a folder — reported as
    "even after Open folder it stayed where it was"."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    target = tmp_path / "other-car"
    target.mkdir()
    monkeypatch.setattr(
        main_window.QFileDialog, "getExistingDirectory", lambda *a, **kw: str(target)
    )
    monkeypatch.setattr(MainWindow, "_confirm_switch", lambda self, folder: True)
    started = {}
    monkeypatch.setattr(
        main_window.QProcess, "startDetached",
        lambda program, argv: started.update(program=program, argv=argv) or True,
    )
    monkeypatch.setattr(MainWindow, "close", lambda self: started.update(closed=True))

    window._choose_project_folder()

    assert "--project-dir" in started["argv"]
    assert str(target) in started["argv"]
    assert started.get("closed") is True


def test_a_refused_switch_changes_nothing(monkeypatch, tmp_path):
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    before = config.chosen_project_dir()
    target = tmp_path / "not-this-one"
    target.mkdir()
    monkeypatch.setattr(
        main_window.QFileDialog, "getExistingDirectory", lambda *a, **kw: str(target)
    )
    monkeypatch.setattr(MainWindow, "_confirm_switch", lambda self, folder: False)
    monkeypatch.setattr(
        main_window.QProcess, "startDetached", lambda *a, **kw: pytest.fail("must not relaunch")
    )

    window._choose_project_folder()

    assert config.chosen_project_dir() == before


def test_picking_the_folder_already_open_is_a_no_op(monkeypatch):
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    current = config.chosen_project_dir()
    monkeypatch.setattr(
        main_window.QFileDialog, "getExistingDirectory", lambda *a, **kw: str(current)
    )
    monkeypatch.setattr(
        MainWindow, "_confirm_switch", lambda self, folder: pytest.fail("nothing to confirm")
    )

    window._choose_project_folder()


def test_chip_buttons_actually_render_rounded(monkeypatch):
    """QSS said `border-radius: 12px` and Qt drew square corners, because 12 is more than half of
    the 22px these render at — an out-of-range radius is silently ignored. Declaring it is not
    the same as getting it, so this measures the pixels.

    The catalogue is stubbed: this test processes events, and the window's catalogue worker
    answers then. Unstubbed it ran this machine's `omp models`, and in a plain `-n 4` run its
    answer reached a model pick an earlier test's window had written here -- the «model gone»
    box, 24 minutes of a worker waiting (2026-09-30)."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    QApplication.processEvents()

    for button in (window._dialog._not_visible_btn, window._dialog._edit_chip, window._session_btn):
        button.setHidden(False)
        QApplication.processEvents()
        image = button.grab().toImage()
        assert image.width() > 8, button.text()
        corner = image.pixelColor(0, 0)
        edge = image.pixelColor(image.width() // 2, 0)
        assert corner != edge, f"square corner on {button.property('class')}: {button.text()!r}"


def test_a_project_mid_interview_keeps_its_plan(tmp_path, monkeypatch):
    """"No `dsp_profile.json` yet" is not "no project". A folder mid-interview has a plan, a
    journal and a process state and no profile — and pressing ↻ used to replace the plan on screen
    with "no project open", while every `enter_phase`/`add_step` did the same invisibly."""
    process = tmp_path / "process"
    process.mkdir()
    (process / "process-state.json").write_text(
        json.dumps({
            "schema_version": 3,
            "active_phase": "-1",
            "phases": {"-1": {"status": "cur", "title": "Project intake"}},
            "plan": [{"id": "lang", "name": "Set session language", "status": "done",
                      "phase": "-1", "source": "skill"}],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    _app()
    window = MainWindow()

    assert window._has_project is False  # no DSP profile: the tree genuinely has nothing
    assert window._plan_panel.plan  # ...but the plan is real and stays

    window._reload_from_disk()

    assert window._plan_panel.plan
    assert any("Set session language" in s.name for p in window._plan_panel.plan for s in p.steps)


def test_a_half_written_process_file_does_not_erase_the_plan(tmp_path, monkeypatch):
    """The skill rewrites `process-state.json` on every step, and the watcher can read it mid-
    write. Blanking then turns half a second of writing into "the phases disappeared" — reported
    exactly that way, with them coming back on the next turn."""
    process = tmp_path / "process"
    process.mkdir()
    (process / "process-state.json").write_text(
        json.dumps({
            "schema_version": 3,
            "active_phase": "1",
            "phases": {"1": {"status": "cur", "title": "Crossovers"}},
            "plan": [{"id": "xo", "name": "Choose crossovers", "status": "done", "phase": "1"}],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    _app()
    window = MainWindow()
    assert window._plan_panel.plan

    (process / "process-state.json").write_text("{ half-writ", encoding="utf-8")
    window._refresh_process()

    assert window._plan_panel.plan  # the last thing known to be true stays on screen


def test_a_phase_closed_on_prose_is_flagged_in_the_panel(tmp_path, monkeypatch):
    """The observed case: a free model closed four phases and reported a finished tune — delays,
    EQ, a listening verdict — with `dsp_profile.json` alone on disk. Every step passed the skill's
    evidence gate, which counts evidence and cannot read it (SCR-035)."""
    (tmp_path / "dsp_profile.json").write_text("{}", encoding="utf-8")
    process = tmp_path / "process"
    process.mkdir()
    (process / "process-state.json").write_text(
        json.dumps({
            "schema_version": 3,
            "active_phase": "1",
            "phases": {"1": {"status": "cur", "title": "Crossovers"}},
            "plan": [
                {"id": "profile", "name": "Adopt DSP profile", "status": "done", "phase": "1",
                 "evidence": ["dsp_profile.json (schema 3)"]},
                {"id": "delays", "name": "Set time delays", "status": "done", "phase": "1",
                 "evidence": ["delays aligned to the sub as 0 ms reference"]},
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    _app()
    window = MainWindow()

    steps = {s.id: s for p in window._plan_panel.plan for s in p.steps}
    assert steps["profile"].tag_class == "ok"      # the file it names is really there
    assert steps["delays"].tag_class == "bad"      # the sentence it names is not
    assert i18n.tx(steps["delays"].tag) in ("unproven", "без доказу")


def test_the_left_column_is_one_scroll_and_the_tree_does_not_have_its_own(tmp_path, monkeypatch):
    """User, 2026-08-21: "скрол в лівому вікні - зажимає останню DSP секцію, а хотілось би просто
    скролити".

    The tree used to be a QScrollArea inside the column's QScrollArea, handed `stretch=1`: it got
    whatever height was left in the viewport and scrolled the rest privately -- so the DSP section
    showed two rows at the bottom of the panel and ate the wheel that was meant to move the column.
    Now the tree is a plain widget, as tall as its rows, and the column scrolls.
    """
    import json

    from PySide6.QtWidgets import QScrollArea

    from autosound_tcc.ui.tcc.dsp_tree import TreeGroupSection

    # Enough rows that the column MUST scroll on any platform's metrics. Eleven was enough on
    # macOS and not on Windows, where the same rows are shorter — so the first assertion below
    # ("the column is what scrolls") failed for having nothing to scroll, which says nothing about
    # the behaviour under test (Windows CI, 2026-09-07).
    channels = {f"ch_{i}": {"slot": chr(65 + i), "hp": {"f": 80}, "lp": {"f": 4000}}
                for i in range(24)}
    (tmp_path / "dsp_profile.json").write_text(json.dumps({"dsp_profile": {
        "name": "M6V4", "vendor": "Musway",
        "groups": [{"id": "physical_outputs", "label": "Output channels",
                    "fields": ["hp", "lp"]}]}}))
    (tmp_path / "project.json").write_text(json.dumps({"dsp": {"vendor": "X", "model": "Y"}}))
    preset = tmp_path / "P"
    preset.mkdir()
    (preset / "v_001.json").write_text(
        json.dumps({"preset": "P", "sample_rate": 48000, "channels": channels})
    )
    (preset / "HEAD").write_text("v_001")
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path))

    app = _app()
    _catalogue(monkeypatch, [])
    window = MainWindow()
    window.resize(1400, 700)
    window.show()

    def settle() -> None:
        for _ in range(6):
            app.processEvents()
            app.sendPostedEvents()

    settle()

    tree = window._tree
    column = next(area for area in window.findChildren(QScrollArea) if area.isAncestorOf(tree))

    def content_bottom(widget) -> int:
        """One past the lowest pixel anything visible is drawn at, in `widget`'s coordinates."""
        return max((c.geometry().bottom() + 1 for c in widget.children()
                    if c.isWidgetType() and not c.isHidden()), default=0)

    assert not isinstance(tree, QScrollArea), "the tree has no scrolling of its own to steal"
    assert tree.height() >= content_bottom(tree), "the tree is as tall as its rows"
    assert column.verticalScrollBar().maximum() > 0, "the column is what scrolls"

    # And it scrolls the content, not a claim about it. A word-wrapping QLabel asks for the height
    # of two lines and draws one, so every channel row donated 14px that nothing was drawn in:
    # 196px of scroll running past the end of the tree into empty panel (user, 2026-08-22, with
    # the screenshot). What the column scrolls has to END where the drawing ends.
    inner = column.widget()

    def scrolls_exactly_its_content() -> bool:
        """The scrolled widget ends where the drawing ends -- or fills the viewport when the
        column has more room than content, which is the trailing stretch doing its job."""
        return inner.height() == max(column.viewport().height(), content_bottom(inner))

    assert scrolls_exactly_its_content(), "no scrollable emptiness under the last row"

    # Folding a group has to reach the column too. The tree announced its height by hand after a
    # rebuild, and a fold is not a rebuild -- so the column kept the height it had computed before:
    # 66px of tree given the room for 886, rows sliced off with free space under them (same
    # report). A widget whose own layout holds the rows says so by itself.
    group = tree.findChildren(TreeGroupSection)[0]
    tall = tree.height()
    group._on_header_clicked(None)
    settle()
    folded = tree.height()
    assert folded < tall, "folding a group gives its rows' room back"
    assert scrolls_exactly_its_content()
    group._on_header_clicked(None)
    settle()
    assert tree.height() == tall, "and unfolding takes it again"
    assert scrolls_exactly_its_content()

    # It stays that way across a RELOAD, which is where this first broke: a widget added to a
    # layout is not shown until Qt gets to it, a layout does not count hidden items, so the height
    # announced on the spot was 18px of margins over a tree of thirty rows -- the last row sliced
    # in half with free space under it (user, 2026-08-21).
    (preset / "v_001.json").write_text(json.dumps({
        "preset": "P", "sample_rate": 48000,
        "channels": {f"ch_{i}": {"slot": chr(65 + i), "hp": {"f": 80}, "lp": {"f": 4000}}
                     for i in range(30)},
    }))
    window._safe_load_project()
    settle()
    assert tree.height() >= content_bottom(tree), "a reload that grows the tree grows the widget"

    (preset / "v_001.json").write_text(json.dumps({
        "preset": "P", "sample_rate": 48000,
        "channels": {"ch_0": {"slot": "A", "hp": {"f": 80}, "lp": {"f": 4000}}},
    }))
    window._safe_load_project()
    settle()
    assert tree.height() >= content_bottom(tree)
    assert tree.height() < 400, "and one that shrinks it gives the room back"
    window.close()


def test_the_gate_mode_is_a_project_setting_and_defaults_to_not_asking(monkeypatch):
    """`auto` first (user, 2026-08-21). "Every write" was the default on the argument that a
    strict gate teaches; what it taught was clicking through, and the writes that reach the car
    confirm inside TCC's own tools whatever this is set to. Narrowing it is now the choice
    someone makes deliberately.

    The default is asserted through `GATE_DEFAULT` and not by naming a mode, because the point of
    the constant is that six call sites cannot drift apart again."""
    from autosound_tcc.core import omp_session, project_settings

    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    assert omp_session.GATE_DEFAULT == omp_session.GATE_AUTO
    assert window._gate_actions[omp_session.GATE_DEFAULT].isChecked()
    assert not window._gate_actions[omp_session.GATE_WRITES].isChecked()

    window._set_gate_mode(omp_session.GATE_FOREIGN)

    assert project_settings.get(config.tcc_dir(), "gate") == omp_session.GATE_FOREIGN
    assert window._gate_actions[omp_session.GATE_FOREIGN].isChecked()
    assert not window._gate_actions[omp_session.GATE_AUTO].isChecked()


def test_the_gate_menu_has_a_fourth_choice_that_asks_about_nothing(monkeypatch):
    """The Arbiter, 2026-10-01: «для нього треба додати пункт вибору "взагалі не питати"» (tcc#115).
    It sits after `auto`, says by its name what it lifts, and its tooltip names the delete or
    overwrite outside the project that now goes unasked. Kept per project like the other three,
    and shown in the system params under its own name."""
    from autosound_tcc.core import omp_session, project_settings
    from autosound_tcc.ui.tcc import i18n

    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    assert list(window._gate_actions) == [omp_session.GATE_WRITES, omp_session.GATE_FOREIGN,
                                          omp_session.GATE_AUTO, omp_session.GATE_NEVER]
    never = window._gate_actions[omp_session.GATE_NEVER]
    assert never.text() == i18n.t("gateNever")
    assert never.toolTip() == i18n.t("gateNeverTip")
    assert window._gate_actions[omp_session.GATE_AUTO].toolTip() == i18n.t("gateAutoTip")

    window._set_gate_mode(omp_session.GATE_NEVER)

    assert project_settings.get(config.tcc_dir(), "gate") == omp_session.GATE_NEVER
    assert window._effective_gate() == omp_session.GATE_NEVER
    assert never.isChecked()
    assert not window._gate_actions[omp_session.GATE_AUTO].isChecked()
    assert dict(window._app_config_rows())[i18n.t("cfgGate")] == i18n.t("gateNever")


def test_the_effort_picker_offers_three_levels_and_none_of_them_is_cheap(monkeypatch):
    """The Arbiter's rule (2026-08-07): below `high` is not a tuning setting. `max` is on the list
    because nothing escalates on its own — the model varies its own depth, but only under the level
    the session was started with, so a hard step is a choice made before it starts."""
    from autosound_tcc.core import model_choices, project_settings

    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    combo = window._ai_effort_combo

    levels = [combo.itemData(i) for i in range(combo.count())]
    assert levels == ["high", "xhigh", "max"]
    assert combo.currentData() == model_choices.EFFORT_DEFAULT

    combo.setCurrentIndex(levels.index("max"))

    assert project_settings.get(config.tcc_dir(), "effort") == "max"


def test_system_params_shows_what_tcc_itself_is_set_to():
    """Language, the two models, theme and the permission mode were only visible in the footer and
    the menus, so "which model is answering me" meant hunting for the control that sets it. They
    are system params in the same sense the mic is: chosen once, then relied on."""
    from autosound_tcc.ui.tcc import i18n

    _app()
    window = MainWindow()
    labels = [label for label, _ in window._app_config_rows()]

    assert labels == [i18n.t("cfgLanguage"), i18n.t("cfgGenerator"), i18n.t("cfgEffort"),
                      i18n.t("cfgCritic"), i18n.t("cfgTheme"), i18n.t("cfgGate")]
    # Effort sits beside the model because it is half of the same fact: naming the model without
    # saying how hard it was asked to think does not describe what ran (2026-08-07).
    rows = dict(window._app_config_rows())
    assert rows[i18n.t("cfgEffort")] == i18n.t("effort_xhigh")


def test_system_params_name_the_route_beside_each_model(monkeypatch):
    """Finding 84 (tcc#75): «ШІ генератор anthropic/claude-opus-5» with no word of omp — the
    Arbiter wants the route there as the picker shows it («OMP · …»), known model or not."""
    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc import main_window as mw

    _app()
    window = MainWindow()
    picked = {mw._GENERATOR_KEY: "omp:anthropic/claude-opus-5",
              mw._CRITIC_KEY: "agy:gemini-3.8-flash-low"}
    monkeypatch.setattr(window, "_project_setting", lambda key: picked.get(key, ""))
    rows = dict(window._app_config_rows())

    assert rows[i18n.t("cfgGenerator")].startswith("OMP · "), rows
    assert "claude-opus-5" in rows[i18n.t("cfgGenerator")].lower().replace(" ", "-")
    assert rows[i18n.t("cfgCritic")].startswith("AGY · "), rows


def test_the_project_section_comes_before_the_system_one():
    """The car in front of you first; the rig and the app's own settings after (user, 2026-08-06)."""
    _app()
    window = MainWindow()
    panel = window._left
    sections = [w for w in panel.findChildren(type(window._project_section))]
    order = [s for s in sections if s in (window._project_section, window._system_section)]

    assert order.index(window._project_section) < order.index(window._system_section)


def test_a_long_key_gives_up_its_own_text_rather_than_the_value():
    """`Amp (midbass (front) + center; 1 channel spare)` widened the panel, the panel widened the
    window, and a maximised window went past the screen edge."""
    from autosound_tcc.ui.tcc.labels import ElidedLabel
    from autosound_tcc.ui.tcc.main_window import _kv_row

    _app()
    row = _kv_row("Amp (midbass (front) + center; 1 channel spare)", "Ground Zero GZA 125.4")
    row.resize(240, 30)
    row.show()
    key = row.findChild(ElidedLabel)
    key.resize(90, 20)

    assert key.text().endswith("…")
    assert key.toolTip().startswith("Amp (midbass")


def test_neither_side_of_a_row_can_widen_the_panel():
    """The value used to refuse to shrink, so one model id made the whole left column scroll
    sideways and put the channel ON/OFF switches past the visible edge."""
    from autosound_tcc.ui.tcc.labels import ElidedLabel
    from autosound_tcc.ui.tcc.main_window import _kv_row

    _app()
    row = _kv_row("AI generator", "google/deep-research-preview-04-2026")
    row.resize(190, 30)
    row.show()
    row.layout().activate()

    labels = row.findChildren(ElidedLabel)
    assert row.minimumSizeHint().width() <= 190
    value = labels[-1]
    assert value.text().endswith("…")
    assert value.toolTip() == "google/deep-research-preview-04-2026"  # nothing is lost


def test_the_left_column_catches_up_when_the_skill_writes(tmp_path, monkeypatch):
    """Only the plan was watched, so the left column said "no data yet" beside a `project.json`
    the session had just written — it caught up on the next launch. Reported after a completed
    phase −1: the car, the amps and the open questions were all on disk and none on screen."""
    import json

    from autosound_tcc.core import config

    _app()
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    window = MainWindow()

    (tmp_path / "project.json").write_text(json.dumps({"schema_version": 3, "car": {"make": "VW"}}))
    window._arm_project_watcher()

    assert str(tmp_path / "project.json") in window._project_watcher.files()


def test_closing_the_window_stops_the_contract_worker(tmp_path, monkeypatch):
    """Qt destroying a still-running QThread is a `qFatal`, not a warning: the process aborts.
    Observed as a macOS crash report with `_ContractWorker` blocked in `poll` (2026-08-06)."""
    from autosound_tcc.core import contract_check
    from autosound_tcc.ui.tcc import main_window as mw

    _app()
    slow = tmp_path / "slow_contract.py"
    slow.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    monkeypatch.setattr(contract_check, "script_path", lambda: slow)
    monkeypatch.setenv("AUTOSOUND_TCC_MCP", "1")  # the switch the launch-time check is gated on

    window = mw.MainWindow()
    assert window._contract_worker is not None and window._contract_worker.isRunning()

    worker = window._contract_worker
    mcp = window._mcp_server
    window.stop_workers()

    assert not worker.isRunning()  # cancelled, not waited out for 30 s
    # ...and so does the MCP server. It used to come down only in `closeEvent`, so quitting
    # without closing a window (Cmd-Q, a signal) left a daemon thread running uvicorn's asyncio
    # loop into interpreter shutdown — where the process died. A macOS crash report with
    # `mcp_server._serve` on the stack, and one suite run in five (2026-08-12).
    if mcp is not None:
        assert mcp._thread is None, "a daemon asyncio thread outliving the window is the crash"


def _agy_reading_held(monkeypatch):
    """A window whose contract check answers at once and whose agy reading waits for the test.
    The window is built under the suite's switch, which is then lifted for its own check."""
    import threading

    from autosound_tcc.core import contract_check, critic, model_choices
    from autosound_tcc.core.contract_check import ContractReport

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    monkeypatch.setenv("AUTOSOUND_TCC_MCP", "1")
    monkeypatch.setattr(contract_check, "is_available", lambda: True)
    runs: list = []
    monkeypatch.setattr(contract_check, "run", lambda *a, **k: runs.append(1) or ContractReport(
        ok=True, project_dir="/tmp/proj", checked_at="2026-10-03T12:00:00+00:00"))
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")
    reading, release = threading.Event(), threading.Event()
    monkeypatch.setattr(critic, "agy_sign_in", lambda project_dir=None, register=None: (
        reading.set(), release.wait(10), ("adc", "ADC (Google Cloud), /x/adc.json"))[-1])
    return window, runs, reading, release


def _pump_until(done, seconds: float = 10.0) -> bool:
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if done():
            return True
        time.sleep(0.01)
    return False


def test_the_report_reaches_the_window_before_agys_reading_and_its_row_follows(monkeypatch):
    """Final review M2: the panel, the strip and the REW dot of every check waited for agy's
    sign-in reading. The report shows at once; the agy row joins the open panel when its reading
    comes back."""
    window, _runs, reading, release = _agy_reading_held(monkeypatch)
    try:
        window._diag_btn.click()  # no report yet: opening the panel starts the check
        dialog = window._diag_dialog
        assert reading.wait(10)

        assert _pump_until(lambda: dialog._report is not None), "the report waited for agy"
        assert "agy_sign_in" not in {check.id for check in dialog._checks}
    finally:
        release.set()
    worker = window._contract_worker
    assert worker.wait(10_000)

    assert _pump_until(lambda: "agy_sign_in" in {check.id for check in dialog._checks}), \
        "the reading came back and the open panel did not show it"


def test_a_recheck_asked_during_agys_reading_runs_when_it_ends(monkeypatch):
    """With the report out first, the worker still runs while it reads agy's sign-in. A Re-check
    pressed then was dropped as «a check is already running», and the panel stayed on «Checking…»
    with its button off. It runs when the reading ends."""
    window, runs, reading, release = _agy_reading_held(monkeypatch)
    try:
        window._start_contract_check()
        assert reading.wait(10)
        assert _pump_until(lambda: window._contract_report is not None), "the report waited"
        window._diag_btn.click()
        window._diag_dialog._on_refresh()  # Re-check: the panel says «Checking…»
        assert window._diag_dialog._report is None
    finally:
        release.set()

    assert _pump_until(lambda: len(runs) == 2 and window._diag_dialog._report is not None), \
        f"the Re-check never ran ({len(runs)} check(s)); the panel waits for nothing"
    assert window._contract_worker.wait(10_000)


def test_a_new_ledger_snapshot_does_not_need_the_reload_button(tmp_path, monkeypatch):
    """A snapshot committed from a terminal is the most visible thing a session does — a channel
    gains a crossover, the header's version moves — and the only way to see it was ↻."""
    from autosound_tcc.core import config

    _app()
    state = tmp_path / "state" / "FULL"
    state.mkdir(parents=True)
    (state / "HEAD").write_text("v_001")
    (state / "v_001.json").write_text("{}")
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "state_root", lambda: tmp_path / "state")
    window = MainWindow()
    window._arm_project_watcher()

    assert str(state / "HEAD") in window._project_watcher.files()
    # The preset dir too: `v_002.json` does not exist when the watcher is armed, so only a
    # directory watch can catch it appearing.
    assert str(state) in window._project_watcher.directories()

    reloaded: list = []
    monkeypatch.setattr(window, "_safe_load_project", lambda: reloaded.append(1))
    window._on_project_file_changed(str(state))
    window._project_reload.stop()
    window._reload_project_files()

    assert reloaded == [1]


def test_a_project_write_reloads_rather_than_rebuilding_per_file(tmp_path, monkeypatch):
    """The skill writes several files in a row; each one must not cost a full rebuild of the tree."""
    from autosound_tcc.core import config

    _app()
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    window = MainWindow()

    window._on_project_file_changed()
    window._on_project_file_changed()

    assert window._project_reload.isActive()  # one pending reload, not two rebuilds


def test_a_decision_that_was_never_written_down_reaches_the_strip(tmp_path, monkeypatch):
    """The supervisor's second rule has to be visible, not just true: the target curve was chosen
    out loud and `process-state.json` still read `"targets": {}`."""
    _app()
    window = MainWindow()
    said: list[str] = []
    monkeypatch.setattr(window._status_strip, "notify", said.append)

    window._notify_missing_records({"active_phase": "0", "targets": {}})
    window._notify_missing_records({"active_phase": "0", "targets": {}})

    assert len(said) == 1  # said once per fact; the file is polled, the Arbiter is not
    assert i18n.t("recordTargetCurve") in said[0]


def test_the_line_goes_away_once_the_record_exists(tmp_path, monkeypatch):
    """A warning that outlives its cause teaches people to ignore the strip."""
    _app()
    window = MainWindow()
    cleared: list[bool] = []
    monkeypatch.setattr(window._status_strip, "notify", lambda *_: None)
    monkeypatch.setattr(window._status_strip, "clear", lambda: cleared.append(True))

    window._notify_missing_records({"active_phase": "0", "targets": {}})
    window._notify_missing_records({"active_phase": "0", "targets": {"FULL": "EPY"}})

    assert cleared == [True]


def test_changing_the_permission_mode_reaches_the_running_session(tmp_path, monkeypatch):
    """Both dials were read once, when the session was built. The Arbiter switched to "do not ask",
    ticked "stop asking about Bash", and was asked about Bash again — a setting that only takes
    effect next launch is a setting that does not work."""
    from autosound_tcc.core import config, omp_session, project_settings

    _app()
    window = MainWindow()

    class Session:
        gate = omp_session.GATE_WRITES
        always_allowed = frozenset()

    class Worker:
        session = Session()

    window._agent_worker = Worker()
    monkeypatch.setattr(config, "tcc_dir", lambda *_a, **_k: tmp_path)
    project_settings.set_value(tmp_path, "always_allowed", "Bash")

    window._set_gate_mode(omp_session.GATE_AUTO)

    assert Worker.session.gate == omp_session.GATE_AUTO
    assert "Bash" in Worker.session.always_allowed


def test_a_channel_toggle_goes_on_the_bus_and_writes_nothing(tmp_path, monkeypatch):
    """Enabling a channel changes the ledger, and the ledger is the skill's to write (D-6). TCC
    says what was asked for; the model records it and the tree follows."""
    from autosound_tcc.core import signal_bus

    _app()
    window = MainWindow()

    class Server:
        # The real bus, not a hand-written stand-in. A double is a second copy of the protocol and
        # it drifts in silence: `SignalBus` grew `pending_count`, the double here did not, and the
        # AttributeError died inside a Qt slot with the run still green (HUB-046, 2026-09-07). The
        # real one needs a directory and nothing else.
        bus = signal_bus.SignalBus(tmp_path)

        def stop(self, timeout: float = 5.0) -> None:
            """A stand-in for the real server has to answer what the real one is asked. Since
            2026-08-12 that includes `stop()`, called from `stop_workers()` on the way out."""

    server = Server()
    window._mcp_server = server

    window._on_channel_toggle("virtual", "VRR", True)

    # `deliver()` is how the model reads the queue, and reading does not close anything -- so it
    # is also how a test sees what was raised.
    assert [(s.kind, s.payload) for s in server.bus.deliver()] == [
        (signal_bus.CHANNEL_TOGGLE, {"group": "virtual", "channel": "VRR", "on": True})
    ]

    # The row is now waiting on an answer, and asking again while it waits must not raise a
    # second signal -- four of them piled up that way (F-009 point 4, 2026-08-21).
    assert ("virtual", "VRR") in window._pending_toggles
    window._on_channel_toggle("virtual", "VRR", True)
    assert len(server.bus.deliver()) == 1, "the same request twice is one request"

    # The opposite request IS a new one: the Arbiter changed their mind, and the model has to
    # hear the thing they now want.
    window._on_channel_toggle("virtual", "VRR", False)
    assert len(server.bus.deliver()) == 2
    assert window._pending_toggles[("virtual", "VRR")]["on"] is False

    # Closed on the bus -- acknowledged, however it was answered -- and the wait is over.
    server.bus.ack([s.id for s in server.bus.deliver()], signal_bus.ACK_APPLIED)
    window._tick_pending_toggles()
    assert window._pending_toggles == {}
    assert not window._pending_timer.isActive()


def test_a_waiting_channel_row_says_it_is_waiting_and_then_says_it_is_late(tmp_path, monkeypatch):
    """Between the click and the model's answer the row used to look untouched, which reads as
    "nothing happened" -- and the Arbiter clicked again (2026-08-21). A minute of silence is a
    different fact from four seconds of it, so the button says which."""
    import time as _time

    from autosound_tcc.core import signal_bus
    from autosound_tcc.ui.tcc import main_window as mw

    _app()
    window = MainWindow()

    class Server:
        # A real bus with nothing acked is exactly "the model has not answered yet", which is the
        # state this test is about -- and it cannot fall behind the protocol the way a hand-written
        # double did (HUB-046).
        bus = signal_bus.SignalBus(tmp_path)

        def stop(self, timeout: float = 5.0) -> None:
            pass

    window._mcp_server = Server()
    button = QPushButton()
    window._toggle_buttons[("virtual", "VRR")] = button

    window._on_channel_toggle("virtual", "VRR", True)
    assert "…" in button.text() or button.text() != ""
    assert "chan-toggle-wait" in button.property("class")

    window._pending_toggles[("virtual", "VRR")]["at"] = _time.time() - mw._TOGGLE_LATE_S - 1
    window._tick_pending_toggles()
    assert "chan-toggle-late" in button.property("class"), "silence past a minute is flagged"


def test_a_toggle_with_no_session_says_so_instead_of_vanishing(tmp_path):
    _app()
    window = MainWindow()
    window._mcp_server = None

    window._on_channel_toggle("virtual", "VRR", True)  # must not raise

    assert window._dialog._bubbles  # the Arbiter is told, not ignored


def test_every_channel_including_the_spare_ones_is_listed_in_system_params(tmp_path):
    """The working tree shows what is being worked on; here the point is the whole rig at once —
    which slots are in play and which are spare (user, 2026-08-06)."""
    from PySide6.QtWidgets import QPushButton

    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup

    _app()
    window = MainWindow()
    live = GroupRow(id="VFL", name="VFL", raw={"gain_db": 0.0}, identity={})
    spare = GroupRow(id="VRR", name="VRR", raw={"hidden": True}, identity={})
    group = ProfileGroup(id="virtual", label="VIRTUAL", fields=("gain_db",),
                         rows=(live, spare))

    from autosound_tcc.ui.tcc import i18n

    on_row = window._channel_switch_row(group.id, live)
    off_row = window._channel_switch_row(group.id, spare)

    # The button offers the action, not the state (user, 2026-08-07): a live channel used to carry
    # a green "ON", which reads as a badge right up until pressing it asks to switch it off.
    assert on_row.findChild(QPushButton).text() == i18n.t("chanTurnOff")
    assert off_row.findChild(QPushButton).text() == i18n.t("chanTurnOn")


def test_a_channel_group_in_system_params_folds_and_says_how_many_are_in_play(tmp_path):
    """Every slot of every tier is forty-odd rows on a Helix Ultra, which pushed the REW port and
    the equipment facts off the panel. Folded, the header still answers how much of the tier is
    live."""
    from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup, ProjectView
    from autosound_tcc.ui.tcc.sidebar_section import CollapsibleGroup

    _app()
    window = MainWindow()
    live = GroupRow(id="VFL", name="VFL", raw={"gain_db": 0.0}, identity={})
    spare = GroupRow(id="VRR", name="VRR", raw={"hidden": True}, identity={})
    window._view = ProjectView(
        preset="FULL",
        sample_rate=None,
        groups=(
            ProfileGroup(
                id="virtual", label="VIRTUAL", fields=("gain_db",), rows=(live, spare)
            ),
        ),
    )
    window._rebuild_system_params()

    groups = window._system_section.findChildren(CollapsibleGroup)
    assert len(groups) == 1
    labels = [lbl.text() for lbl in groups[0].findChildren(QLabel)]
    assert "1/2" in labels  # one of two slots in play
    assert groups[0].is_collapsed()  # folded until asked for

    groups[0]._on_header_clicked(None)
    assert not groups[0].is_collapsed()


def test_folding_a_group_in_system_params_does_not_fold_the_same_group_in_the_tree(tmp_path):
    """`physical_outputs` appears in both panels and they are looked at for different reasons —
    the tree is the working surface, System params is the whole rig."""
    from PySide6.QtCore import QSettings

    from autosound_tcc.ui.tcc import dsp_tree, sidebar_section

    _app()
    settings = QSettings("autosound-tcc-test", "collapse-keys")
    settings.clear()
    group = sidebar_section.CollapsibleGroup(
        "sys/physical_outputs", "OUTPUT", settings, default_collapsed=True
    )
    group._on_header_clicked(None)  # opened here

    assert settings.value(
        dsp_tree._collapsed_key("physical_outputs"), None
    ) is None  # the tree's own key was never touched
    settings.clear()


def test_switching_a_channel_asks_first(tmp_path, monkeypatch):
    """Off can cost its EQ, crossover and delay; on is a structural change. Neither is a toggle you
    want on a mis-click, and TCC cannot undo either — the ledger is the skill's."""
    _app()
    window = MainWindow()
    sent: list = []
    monkeypatch.setattr(window, "_on_channel_toggle", lambda *a: sent.append(a))

    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel)
    window._ask_channel_toggle("virtual", "VRR", True)
    assert sent == []  # cancelled means nothing was asked for

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    window._ask_channel_toggle("virtual", "VRR", True)
    assert sent == [("virtual", "VRR", True)]


def test_the_capture_series_comes_from_the_plan_not_the_ledger(monkeypatch):
    """Naming the virtual-channel tier bumped the ledger `v_001 → v_002`, and the checklist jumped
    to series 2 before series 1 had been captured — watched twice, on two projects. The skill's own
    phase-0 steps say which round they mean: "Baseline solo: tw-L_1 (sw) + tw-L_1 (rta)"."""
    from autosound_tcc.state import process_view

    monkeypatch.setattr(process_view, "capture_round", lambda *a, **k: None)
    _app()
    window = MainWindow()
    window._view = None
    state = {
        "active_phase": "0",
        "plan": [
            {"id": "m0-tw-L", "phase": "0", "name": "Baseline solo: tw-L_1 (sw) + tw-L_1 (rta)"},
        ],
    }

    assert window._capture_version(state) == 1


def test_the_ledger_version_never_becomes_the_series(monkeypatch):
    """hub #153 A. The ledger's `v_NNN` also moves for changes that are not DSP changes, and a
    project can start with the two apart (`v_001` measured as `_49`). With no round and no plan
    step naming a series, the answer is "not known", not the ledger."""
    from autosound_tcc.state import process_view

    _app()
    window = MainWindow()

    class View:
        version = "v_003"

    window._view = View()
    monkeypatch.setattr(process_view, "capture_round", lambda *a, **k: None)
    monkeypatch.setattr(process_view, "capture_rounds", lambda *a, **k: [])

    assert window._capture_version({"active_phase": "0", "plan": []}) is None


def test_the_open_round_names_the_series_before_the_plan(monkeypatch):
    """A pass taken again after a DSP change is the round's series, whatever the plan said first."""
    from autosound_tcc.state import process_view

    _app()
    window = MainWindow()
    window._view = None
    monkeypatch.setattr(process_view, "capture_round",
                        lambda *a, **k: {"id": "cap_002", "expected": ["w-L_07 (sw)"]})
    state = {"active_phase": "0",
             "plan": [{"id": "m0", "phase": "0", "name": "Baseline solo: tw-L_1 (sw)"}]}

    assert window._capture_version(state) == 7


def test_with_no_round_open_the_highest_series_among_the_rounds(monkeypatch):
    from autosound_tcc.state import process_view

    _app()
    window = MainWindow()
    window._view = None
    monkeypatch.setattr(process_view, "capture_round", lambda *a, **k: {"closed": True})
    monkeypatch.setattr(process_view, "capture_rounds", lambda *a, **k: [
        {"id": "cap_001", "expected": ["w-L_48 (sw)"], "taken": {}},
        {"id": "cap_002", "expected": ["w-L_49 (sw)"], "taken": {"w-L_49 (sw)": {}}},
    ])

    assert window._capture_version({"active_phase": "0", "plan": []}) == 49


def test_a_project_that_cannot_be_drawn_does_not_end_the_session(monkeypatch):
    """A rendering fault used to abort the process, because an exception in a Qt slot does not
    propagate. The last good view stays on screen and the strip says what happened — TCC does not
    repair the file either; it does not write project data."""
    _app()
    window = MainWindow()
    said: list[str] = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, level="info": said.append(text))
    monkeypatch.setattr(window, "_load_project",
                        lambda: (_ for _ in ()).throw(TypeError("QLabel called with int")))

    window._safe_load_project()  # must not raise

    assert said and "QLabel" in said[0]


def test_the_supervisor_speaks_up_at_the_end_of_a_turn(tmp_path, monkeypatch):
    """The panels follow the files, but a watcher only fires when something is WRITTEN, and the
    failure this exists for is the opposite: a turn that talked and recorded nothing."""
    import json as _json

    from autosound_tcc.core import config

    _app()
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    window = MainWindow()
    process = tmp_path / "process"
    process.mkdir(exist_ok=True)
    (process / "process-state.json").write_text(
        _json.dumps(
            {
                "schema_version": 3,
                "active_phase": "0",
                "plan": [
                    {
                        "id": "0.1",
                        "name": "Baseline solo",
                        "status": "done",
                        "phase": "0",
                        "evidence": ["baseline measurements analysed"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    before = len(window._dialog._bubbles)
    window._supervise_turn()

    assert len(window._dialog._bubbles) == before + 1
    said = " ".join(w.text() for w in window._dialog._bubbles[-1].findChildren(QLabel))
    assert "Baseline solo" in said  # named, so the Arbiter knows which step to look at

    # Said once per step: a warning repeated every turn is a warning nobody reads.
    window._supervise_turn()
    assert len(window._dialog._bubbles) == before + 1


def test_a_session_is_on_the_record_before_its_first_token(tmp_path, monkeypatch):
    """A journal that starts at whatever the model wrote first cannot tell a session that recorded
    nothing from a session that never happened."""
    from autosound_tcc.core import process_writer

    _app()
    calls: list = []
    monkeypatch.setattr(
        process_writer,
        "record_session",
        lambda project_dir, harness, model, resumed=False: calls.append(
            (harness, model, resumed)
        ),
    )

    process_writer.record_session(tmp_path, "omp", "gemini-2.5-pro", resumed=True)

    assert calls == [("omp", "gemini-2.5-pro", True)]


def test_an_answer_clicked_in_the_dialog_reaches_the_journal(tmp_path, monkeypatch):
    """TCC is where the answer is machine-readable — the option the Arbiter clicked, against the
    question as put. That form existed at the moment of the answer and was discarded (SCR-030)."""
    from autosound_tcc.core import config, process_writer

    _app()
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    window = MainWindow()
    written: list = []
    monkeypatch.setattr(
        process_writer,
        "record_decision",
        lambda project, question, answer, step="", invalidates="": written.append(
            (question, answer)
        ),
    )

    window._record_decision("Reference seat?", "driver only")
    window._record_decision("", "an answer to nothing")  # not a ruling, nothing to record

    assert written == [("Reference seat?", "driver only")]


def test_a_journal_that_cannot_be_written_does_not_eat_the_answer(tmp_path, monkeypatch):
    """The session is waiting on that answer; a failed record is a warning, not a dropped turn."""
    from autosound_tcc.core import config, process_writer

    _app()
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    window = MainWindow()

    def _boom(*_a, **_k):
        raise process_writer.ProcessWriterError("no skill vendored")

    monkeypatch.setattr(process_writer, "record_decision", _boom)

    window._record_decision("Reference seat?", "driver only")  # must not raise


def test_the_flaw_map_renders_with_its_verdict(tmp_path, monkeypatch):
    """The map's point is the second half of every row — not "there is a dip at 250 Hz" but "and
    you must never EQ it up" (SCR-015)."""
    import json as _json

    from autosound_tcc.core import config

    _app()
    (tmp_path / "project.json").write_text(
        _json.dumps({
            "schema_version": 3,
            "acoustics": {"flaws": [
                {"f_hz": 250, "level_db": -12, "kind": "cabin_null", "action": "no_boost",
                 "channels": ["w-R"], "why": "interference, not min-phase",
                 "evidence": ["w-R_1 (sw)"]},
            ]},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    window = MainWindow()

    texts = " ".join(w.text() for w in window._audio_section.findChildren(QLabel))
    assert "250 Hz" in texts and "-12 dB" in texts
    assert i18n.t("flawAction_no_boost") in texts  # the verdict, in words as well as colour
    assert i18n.t("flawKind_cabin_null") in texts


def test_a_flaw_row_says_on_hover_why_it_was_called_that_and_what_it_was_read_off(
    tmp_path, monkeypatch
):
    """The row is a headline; the tip is the substance, and it used to be the reasoning and the
    file names glued into one grey paragraph (user, 2026-08-18). Head, reason and captures are
    three things and read as three."""
    import json as _json
    import re

    from autosound_tcc.core import config

    _app()
    (tmp_path / "project.json").write_text(
        _json.dumps({
            "schema_version": 3,
            "acoustics": {"flaws": [
                {"f_hz": 152, "level_db": -12, "bw_oct": 0.17, "kind": "cabin_null",
                 "action": "no_boost", "channels": ["w-L"],
                 "why": "Interference, not a panel: the harmonics do not rise with it.",
                 "evidence": ["w-L_01 (sw)", "w-L_01 (rta)"]},
            ]},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    window = MainWindow()

    rows = [w for w in window._audio_section.findChildren(QWidget)
            if getattr(w, "hover_tip", None) is not None]
    assert rows, "the flaw row carries a tip"
    tip = rows[0].hover_tip.text()
    plain = re.sub(r"<[^>]+>", " ", tip.replace("<br>", "\n"))
    # The head names the flaw the way a person would say it: what, where, and the verdict.
    assert "152 Hz" in plain and i18n.t("flawKind_cabin_null") in plain
    assert "w-L" in plain and i18n.t("flawAction_no_boost") in plain
    assert "harmonics do not rise" in plain, "the reasoning is there in full"
    # ...and the captures are under a label of their own rather than trailing the sentence.
    assert i18n.t("flawEvidenceHead") in plain
    assert plain.index(i18n.t("flawEvidenceHead")) > plain.index("harmonics do not rise")
    assert "font-size" in tip, "laid out to be read, not at the default tooltip size"


def test_a_project_with_no_flaw_map_says_so_rather_than_showing_nothing(tmp_path, monkeypatch):
    from autosound_tcc.core import config

    _app()
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    window = MainWindow()

    texts = " ".join(w.text() for w in window._audio_section.findChildren(QLabel))
    assert i18n.t("acousticsNone")[:20] in texts


def _window_with_flaws(tmp_path, monkeypatch, flaws) -> MainWindow:
    """A window whose project holds exactly these flaw rows."""
    import json as _json

    from autosound_tcc.core import config

    _app()
    (tmp_path / "project.json").write_text(
        _json.dumps({"schema_version": 3, "acoustics": {"flaws": flaws}}), encoding="utf-8"
    )
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    return MainWindow()


def _flaw_rows(window) -> list:
    return [w for w in window._audio_section.findChildren(QWidget)
            if getattr(w, "hover_tip", None) is not None]


def test_the_flaw_map_shows_the_owner_only_what_outlives_the_tune(tmp_path, monkeypatch):
    """The section stands next to "project parameters" and answers the same question — what this
    car IS. Cuts and crossover points are the tuner's working plan and will not exist afterwards;
    on the Passat's live map they were 8 rows of 18, at the same weight as two that ask the owner
    for money (owner, 2026-09-02, SKL-015).

    The count stays visible: rows a person read yesterday vanishing without a word reads as a
    fault, not as a decision.
    """
    window = _window_with_flaws(tmp_path, monkeypatch, [
        {"f_hz": 73, "level_db": 9, "kind": "driver_resonance", "action": "notch"},
        {"f_hz": 160, "level_db": -12, "kind": "sbir", "action": "geometry"},
        {"f_hz": 400, "level_db": -5, "kind": "pair_suckout", "action": "crossover"},
        {"f_hz": 5500, "level_db": -6, "kind": "driver_resonance", "action": "leave"},
    ])

    texts = " ".join(w.text() for w in window._audio_section.findChildren(QLabel))
    assert "160 Hz" in texts and "5500 Hz" in texts
    assert "73 Hz" not in texts and "400 Hz" not in texts, "the plan is not the owner's page"
    assert i18n.t("acousticsPlanHidden").format(n=2) in texts, "said, not silently dropped"


def test_the_flaw_map_header_says_how_many_of_how_many_it_shows(tmp_path, monkeypatch):
    """tcc#37. The line saying rows were withheld sits INSIDE a section that opens collapsed, under
    the rows: a tuner who had just recorded eight rows counted seven and asked where the eighth
    went. "7 of 8" in the header is seen without opening anything, and "all of them" reads
    differently from "the owner's view"."""
    window = _window_with_flaws(tmp_path, monkeypatch, [
        {"f_hz": 73, "level_db": 9, "kind": "driver_resonance", "action": "notch"},
        {"f_hz": 160, "level_db": -12, "kind": "sbir", "action": "geometry"},
        {"f_hz": 400, "level_db": -5, "kind": "pair_suckout", "action": "crossover"},
        {"f_hz": 5500, "level_db": -6, "kind": "driver_resonance", "action": "leave"},
    ])

    assert window._audio_section.sub_text() == i18n.t("acousticsShownOf").format(shown=2, total=4)


def test_a_flaw_map_that_withholds_nothing_does_not_count_in_the_header(tmp_path, monkeypatch):
    window = _window_with_flaws(tmp_path, monkeypatch, [
        {"f_hz": 160, "level_db": -12, "kind": "sbir", "action": "geometry"},
    ])

    assert window._audio_section.sub_text() == ""


def test_a_map_that_is_all_tuning_plan_does_not_claim_there_is_no_map(tmp_path, monkeypatch):
    """"No flaw map yet" would be false, and a panel that lies about the state of the work is
    worse than one that shows too much. Phase 0 has run; what it recorded is simply all plan."""
    window = _window_with_flaws(tmp_path, monkeypatch, [
        {"f_hz": 73, "level_db": 9, "kind": "driver_resonance", "action": "notch"},
        {"f_hz": 400, "level_db": -5, "kind": "pair_suckout", "action": "crossover"},
    ])

    texts = " ".join(w.text() for w in window._audio_section.findChildren(QLabel))
    assert i18n.t("acousticsNone")[:20] not in texts
    assert i18n.t("acousticsOnlyPlan").format(n=2) in texts


def test_the_value_and_the_status_do_not_share_a_line_with_the_verdict(tmp_path, monkeypatch):
    """The owner's screenshot read `32 Hz · −4....` and `не підтвер` — the number, its unit and
    the status all cut, which is everything the row is read for.

    Cause, measured at the panel's real width (260 px, 222 usable): three items on the top line,
    and the value's size policy is `Ignored`, so the layout reserves nothing for it and hands it
    what the tags leave — about 53 px. Asserted structurally rather than in pixels: the fix is
    that the status is no longer up there, and that is what must not come back.
    """
    window = _window_with_flaws(tmp_path, monkeypatch, [
        {"f_hz": 32, "level_db": -4, "kind": "cabin_null", "action": "no_boost",
         "status": "hypothesis"},
    ])

    rows = _flaw_rows(window)
    assert rows, "the flaw row is there"
    outer = rows[0].layout()
    top = next(outer.itemAt(i).layout() for i in range(outer.count())
               if outer.itemAt(i).layout() is not None)
    on_top = [w.text() for i in range(top.count())
              if (w := top.itemAt(i).widget()) is not None and isinstance(w, QLabel)]
    everywhere = [w.text() for w in rows[0].findChildren(QLabel)]

    assert "32 Hz · -4 dB" in on_top, "the value stays on the first line"
    assert i18n.t("flawAction_no_boost") in on_top, "so does the verdict"
    assert i18n.t("flawHypothesis") not in on_top, "the status is what moved down"
    assert i18n.t("flawHypothesis") in everywhere, "moved, not dropped"


def test_the_owners_sentence_takes_the_second_line_when_the_method_wrote_one(
    tmp_path, monkeypatch
):
    """14 rows of 18 carried a token only the method knows — `MMM`, `§26`, `еліпсоїд`,
    `ILL-POSED`. When the method writes a plain sentence (SKL-016) it takes the second line; the
    kind and the channels do not vanish, the hover tip has carried both since this row existed."""
    import re

    window = _window_with_flaws(tmp_path, monkeypatch, [
        {"f_hz": 160, "level_db": -12, "kind": "sbir", "action": "geometry",
         "channels": ["m-FL"], "plain": "Тут бас глухне через стійку, а не через налаштування."},
    ])

    rows = _flaw_rows(window)
    texts = [w.text() for w in rows[0].findChildren(QLabel)]
    assert any(t.startswith("Тут бас глухне") for t in texts)
    assert i18n.t("flawKind_sbir") not in " ".join(texts), "the method's word left the row"
    plain_tip = re.sub(r"<[^>]+>", " ", rows[0].hover_tip.text())
    assert i18n.t("flawKind_sbir") in plain_tip and "m-FL" in plain_tip, "both still on hover"


def test_a_project_whose_model_retired_is_offered_a_replacement(tmp_path, monkeypatch):
    """Models retire and the name in a project's settings outlives them. Silence here is a Start
    button that does nothing; picking the first row silently is a reviewer nobody chose."""
    from PySide6.QtWidgets import QMessageBox

    from autosound_tcc.core import config, model_choices as mc, model_overrides, project_settings

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(mc, "_CLI_CACHE", {})
    monkeypatch.setattr(mc, "cli_available", lambda harness: False)
    project_settings.set_value(config.tcc_dir(tmp_path), "generator", "sdk:claude-opus-4-1")
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)

    _app()
    window = MainWindow()

    alias = model_overrides.load()["aliases"].get("sdk:claude-opus-4-1")
    assert alias, "the replacement should be recorded as an alias, not by editing this project"
    # And the alias reaches the key everywhere it appears, not just in this project's settings.
    assert mc.resolve(window._model_choices, "sdk:claude-opus-4-1").ok


def test_the_replacement_list_holds_its_models_whole(tmp_path, monkeypatch):
    """tcc#145's review, I1: every combo's list has `.mini-select`'s room for the check mark, and a
    plain box's list is only as wide as the box. The retired model's replacement list is read
    whole, row by row, as the window builds it."""
    from PySide6.QtWidgets import QComboBox, QMessageBox

    from autosound_tcc.core import config, model_choices as mc, project_settings
    from tests import _windows

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(mc, "_CLI_CACHE", {})
    monkeypatch.setattr(mc, "cli_available", lambda harness: False)
    project_settings.set_value(config.tcc_dir(tmp_path), "generator", "sdk:claude-opus-4-1")
    seen = []

    def look(box):
        _windows.theme_on(monkeypatch, box, "dark")
        box.show()
        _app().processEvents()
        for combo in box.findChildren(QComboBox):
            seen.append((combo.count(), _windows.cut_rows(combo)))
        box.hide()
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "exec", look)

    _app()
    MainWindow()

    assert seen and seen[0][0] >= 1, "the replacement box was asked"
    assert seen[0][1] == [], seen


def test_the_nudge_can_fire_while_the_window_is_still_being_built(tmp_path, monkeypatch):
    """The replacement question is asked inside the constructor, and its event loop can fire the
    nudge timer before `_start_mcp` has run: CI on W-7's version commit, an AttributeError on
    `_mcp_server` escaped from the slot. The nudge finds no server and does nothing."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    from autosound_tcc.core import config, model_choices as mc, project_settings

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(mc, "_CLI_CACHE", {})
    monkeypatch.setattr(mc, "cli_available", lambda harness: False)
    project_settings.set_value(config.tcc_dir(tmp_path), "generator", "sdk:claude-opus-4-1")
    fired = []

    def asked(box):
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, MainWindow):
                widget._nudge_for_open_signals()  # what the timer does mid-question
                fired.append(widget)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "exec", asked)

    _app()
    MainWindow()

    assert fired, "the replacement question was asked while the window was being built"


def test_declining_the_replacement_writes_nothing(tmp_path, monkeypatch):
    """The model may come back, or the Arbiter may want to choose deliberately later."""
    from PySide6.QtWidgets import QMessageBox

    from autosound_tcc.core import config, model_choices as mc, model_overrides, project_settings

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(mc, "_CLI_CACHE", {})
    monkeypatch.setattr(mc, "cli_available", lambda harness: False)
    project_settings.set_value(config.tcc_dir(tmp_path), "generator", "sdk:claude-opus-4-1")
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel)

    _app()
    MainWindow()

    assert model_overrides.load()["aliases"] == {}


def test_save_writes_tccs_own_settings_even_with_no_session(monkeypatch, tmp_path):
    """Save used to be nothing but the model handoff, so with no session running it did nothing at
    all — no write, no message, no way to tell "saved" from "ignored" (user, 2026-08-07)."""
    from autosound_tcc.core import project_settings

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    combo = window._ai_main_combo
    pick = next(i for i in range(combo.count()) if combo.itemData(i))
    combo.setCurrentIndex(pick)
    project_settings.set_value(config.tcc_dir(), "generator", "")  # as if the write was missed

    window._save_project_state()

    assert project_settings.get(config.tcc_dir(), "generator") == combo.itemData(pick)


def test_save_does_not_record_a_model_nobody_picked(monkeypatch, tmp_path):
    """The empty entry is the "not chosen yet" placeholder. Writing it would turn "I have not
    picked a model" into "I picked no model", and the Start button reads that setting."""
    from autosound_tcc.core import project_settings

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    window._save_project_state()

    assert project_settings.get(config.tcc_dir(), "generator") is None


def test_closing_with_a_live_session_asks_instead_of_dropping_the_turn(monkeypatch, tmp_path):
    """Quitting shut the session down mid-thought without a word: whatever the model had not yet
    written was gone, and nothing said so. Asking rather than saving unprompted is deliberate — the
    save costs a model turn, and a quit that silently blocks on one reads as a hang."""
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    class _Worker:
        def __init__(self) -> None:
            self.shut = False

        def shutdown(self) -> None:
            self.shut = True

    window._agent_worker = _Worker()
    asked: list[bool] = []
    handed: list[str] = []
    monkeypatch.setattr(window, "_hand_off", lambda w, mode: handed.append(mode))

    # Cancel keeps the window open and touches nothing.
    monkeypatch.setattr(window, "_ask_save_before_quit",
                        lambda: (asked.append(True), QMessageBox.StandardButton.Cancel)[1])
    event = QCloseEvent()
    window.closeEvent(event)
    assert asked and not event.isAccepted() and handed == []

    # Save defers the close until the handoff lands, rather than quitting first and saving never.
    monkeypatch.setattr(window, "_ask_save_before_quit",
                        lambda: QMessageBox.StandardButton.Save)
    event = QCloseEvent()
    window.closeEvent(event)
    assert handed == ["quit"] and not event.isAccepted()


def test_rew_dot_is_shown_in_both_places_and_they_never_disagree():
    """User request 2026-08-11: the REW indicator also sits at the right end of the measurement
    card's header. It is the SAME status in two places, so the test that matters is that they move
    together -- a second dot that could lag behind the first would be worse than no second dot."""
    _app()
    window = MainWindow()
    dots = list(window._rew_dots())
    assert len(dots) == 2  # System params, and the "IN FOCUS NOW" header

    assert {d.property("class") for d in dots} == {"tl tl-wait"}  # not probed yet
    window._set_rew_online(True)
    assert {d.property("class") for d in dots} == {"tl tl-done"}
    window._set_rew_online(False)
    assert {d.property("class") for d in dots} == {"tl tl-bad"}
    assert all(d.toolTip() == i18n.t("rewOfflineTip") for d in dots)

    # A language switch rebuilds System params from scratch (a new dot object) -- the header's is
    # not rebuilt, and both must still say the same thing afterwards.
    before = i18n.current_language()
    try:
        i18n.set_language("en" if before == "uk" else "uk")
        window._retranslate()
        rebuilt = list(window._rew_dots())
        assert {d.property("class") for d in rebuilt} == {"tl tl-bad"}
        assert all(d.toolTip() == i18n.t("rewOfflineTip") for d in rebuilt)
    finally:
        i18n.set_language(before)
        window._retranslate()


def _pick(combo, key: str) -> None:
    index = combo.findData(key)
    assert index >= 0, f"{key} is not in the picker"
    combo.setCurrentIndex(index)


def test_the_footer_says_when_the_reviewer_is_not_what_it_appears_to_be(tmp_path, monkeypatch):
    """Live tune, 2026-08-11: the footer read "AGY · Gemini 3.1 Pro (High) · recommended pair"
    while the channel had degraded to the Generator's own model. TCC knew — `resolve()` carries the
    substitution and `get_tcc_state` reports it, which is how the model found out — and the one
    surface a human looks at said nothing. Silent degradation of the review channel is SCR-041's
    failure mode exactly: it agrees with you instead of erroring."""
    from autosound_tcc.core import config, model_choices as mc, model_overrides

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(mc, "_CLI_CACHE", {})
    # This test needs a SECOND vendor to exist, so it says so rather than depending on what the
    # developer happens to have installed (conftest forces the probe off for exactly that reason).
    monkeypatch.setattr(mc, "cli_available", lambda harness: harness == "codex")
    # ...and a reviewer this machine CAN reach, for the same reason: the subject here is a
    # substituted model, and an unreachable one would raise its own warning and hide the one under
    # test. `conftest` says no by default so the answer never comes from the developer's PATH.
    monkeypatch.setattr(mc, "critic_reaches", lambda choice: True)
    _app()
    window = MainWindow()

    # Whichever two vendors are on offer -- the point is only that they differ.
    generator = next(c for c in window._model_choices if mc.vendor_of(c) == "anthropic")
    critic = next(
        c for c in window._critic_choices if mc.vendor_of(c) not in ("", "anthropic")
    )
    _pick(window._ai_main_combo, generator.key)
    _pick(window._ai_critic_combo, critic.key)
    window._refresh_critic_warning()
    # `isHidden`, not `isVisible`: the window is never shown in these tests, so every child
    # reports invisible regardless of its own flag.
    assert window._critic_warn.isHidden()  # a different vendor, nothing substituted
    assert "is-warn" not in str(window._ai_critic_combo.property("class"))

    # The machine now sends the chosen reviewer somewhere else — and that somewhere is the
    # Generator's own vendor, so both warnings apply at once.
    model_overrides.set_alias(critic.key, generator.key, "no longer available on this machine")
    window._reload_model_choices()
    _pick(window._ai_critic_combo, critic.key)
    window._refresh_critic_warning()

    assert not window._critic_warn.isHidden()
    # A mark, not a sentence: the row has no width for one, and elided to fit it was unreadable.
    assert window._critic_warn.text() == "!"
    assert i18n.t("criticSubstituted") in window._critic_warn_tip._text
    # Substituted by the Generator's OWN model — said as that since tcc#85, which is more than
    # "the same vendor", and red: that pick cannot review.
    assert i18n.t("criticRowSelf") in window._critic_warn_tip._text
    assert "warn-mark-soft" not in str(window._critic_warn.property("class"))
    # ...and the click has the room the row does not, including what actually runs.
    assert generator.key in window._critic_warn_detail
    # The warnings are the «!», not the field's colour: a red field said "broken" about a model
    # that works (the Arbiter, finding 55, tcc#58 — reverses the tint of 2026-08-23).
    assert "is-warn" not in str(window._ai_critic_combo.property("class"))


def test_a_claude_route_with_no_claude_login_says_so_on_the_generator(tmp_path, monkeypatch):
    """`available()` asks whether the SDK package is installed and stays true forever; only the
    login says whether it can answer. A fresh Mac offered three Claude models with nobody signed
    in, and nothing on screen said a word about it (2026-08-13)."""
    from autosound_tcc.core import claude_sdk, config, model_choices as mc

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(mc, "_CLI_CACHE", {})
    _app()
    window = MainWindow()
    generator = next(c for c in window._model_choices if c.harness == "sdk")
    _pick(window._ai_main_combo, generator.key)

    # "Could not tell" is not an accusation: no CLI to ask, a timeout, an output shape we do not
    # know — all of them must leave the picker alone rather than send someone to redo a good login.
    monkeypatch.setattr(claude_sdk, "_SIGNED_IN", None)
    window._refresh_main_warning()
    assert window._main_warn.isHidden()
    assert "is-warn" not in str(window._ai_main_combo.property("class"))

    monkeypatch.setattr(claude_sdk, "_SIGNED_IN", False)
    window._refresh_main_warning()

    assert not window._main_warn.isHidden()
    assert i18n.t("sdkNoLogin") in window._main_warn_tip._text
    assert claude_sdk.LOGIN_HINT in window._main_warn_detail
    assert "is-warn" in str(window._ai_main_combo.property("class"))

    # And it goes quiet the moment there is a login, without rebuilding anything.
    monkeypatch.setattr(claude_sdk, "_SIGNED_IN", True)
    window._refresh_main_warning()
    assert window._main_warn.isHidden()


def test_two_unknown_models_are_not_reported_as_a_matched_pair(tmp_path, monkeypatch):
    """`critic_vendor` falls back to google for a name it does not recognise, which is right for
    picking a transport and wrong for "are these the same vendor" — it would warn about a pair it
    knows nothing about."""
    from autosound_tcc.core import model_choices as mc

    unknown = mc.Choice(harness="omp", model="mistral-large", label="Mistral", provider="mistral")
    assert mc.vendor_of(unknown) == ""
    assert mc.critic_vendor(unknown) == "google"


def test_the_critic_warning_does_not_widen_the_window_off_the_screen(tmp_path, monkeypatch):
    """The warning added yesterday was a plain QLabel, so it asked for its full natural width and
    Qt gave it — the window jumped past the right edge of the screen (user, 2026-08-11). Same
    failure `ElidedLabel` was written for, in a row that had not needed it yet."""
    from autosound_tcc.core import config

    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    _app()
    window = MainWindow()
    footer = window._critic_warn.parentWidget()

    window._critic_warn.setVisible(False)
    quiet = footer.minimumSizeHint().width()
    window._critic_warn.setVisible(True)

    # A fixed 18px mark plus spacing, whatever the reason turns out to say.
    assert footer.minimumSizeHint().width() - quiet < 40
    # And the wheel beside it while the pick's check runs (tcc#140): another fixed 18 px.
    window._critic_spinner.start()
    try:
        assert footer.minimumSizeHint().width() - quiet < 2 * 40
    finally:
        window._critic_spinner.stop()


def test_a_replacement_is_offered_from_the_same_vendor_first(tmp_path, monkeypatch):
    """A replacement is meant to be the nearest thing that still runs. The list was ordered by
    route, so the default selection was whatever sorted first — which is how a Gemini reviewer
    became a Claude one, ending cross-vendor review by combo box (user, 2026-08-11)."""
    from autosound_tcc.core import model_choices as mc
    from autosound_tcc.ui.tcc.main_window import _replacements_for

    entries = [
        mc.Choice(harness="sdk", model="claude-opus-5", label="Opus 5", provider="anthropic"),
        mc.Choice(harness="codex", model="gpt-5.2", label="GPT-5.2", provider="openai"),
        mc.Choice(harness="agy", model="gemini-3.6-flash-high", label="Flash", provider="google"),
    ]

    ordered = _replacements_for("agy:gemini-3.1-pro-high", entries)

    assert ordered[0].key == "agy:gemini-3.6-flash-high"
    assert {c.key for c in ordered} == {c.key for c in entries}, "nothing is dropped, only ordered"


def test_an_unrecognised_key_leaves_the_replacement_list_as_it_was(tmp_path):
    """No marker matched means we know nothing about the vendor — and guessing an order would be
    presenting a preference we do not have."""
    from autosound_tcc.core import model_choices as mc
    from autosound_tcc.ui.tcc.main_window import _replacements_for

    entries = [mc.Choice(harness="omp", model="mistral-large", label="M", provider="mistral")]

    assert _replacements_for("omp:something-unknown", entries) == entries


def test_a_model_this_machine_lacks_stays_selected_and_turns_red(tmp_path, monkeypatch):
    """A picker that silently moves to another row is how a project came to be reviewed by a model
    nobody chose, and how three permanent aliases got written (user, 2026-08-12)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QComboBox
    from autosound_tcc.core import model_choices as mc

    _app()
    combo = QComboBox()
    entries = [mc.Choice(harness="sdk", model="claude-opus-5", label="Opus 5",
                         provider="anthropic")]

    MainWindow._fill_combo(combo, entries, "agy:gemini-3.1-pro-high", critic=True)

    assert combo.currentData() == "agy:gemini-3.1-pro-high", "the choice is not moved"
    assert "agy:gemini-3.1-pro-high" in combo.currentText()
    assert isinstance(combo.itemData(0, Qt.ItemDataRole.ForegroundRole), QColor)
    assert "is-missing" in str(combo.property("class"))


def test_the_recommended_class_is_bold_and_a_new_version_of_it_too(tmp_path):
    """Bold by class, so an Opus 6 or a Pro 3.5 is marked the day it appears with no release."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox
    from autosound_tcc.core import model_choices as mc

    _app()
    combo = QComboBox()
    entries = [
        mc.Choice(harness="agy", model="gemini-3.6-flash-high", label="Flash", provider="google"),
        mc.Choice(harness="agy", model="gemini-9-pro-high", label="Gemini 9 Pro (High)",
                  provider="google"),
    ]

    MainWindow._fill_combo(combo, entries, "", critic=True)

    bold = [combo.itemData(i, Qt.ItemDataRole.FontRole) for i in range(combo.count())]
    assert bold[0] is None, "Flash is not the recommended class"
    assert bold[1] is not None and bold[1].bold()


def test_the_red_field_clears_when_a_real_model_is_picked(tmp_path):
    """It was set once at fill time, so a combo that had ever been red STAYED red through every
    later pick — the Arbiter chose a model that exists and the field went on saying it did not
    (user, 2026-08-12)."""
    from PySide6.QtWidgets import QComboBox
    from autosound_tcc.core import model_choices as mc
    from autosound_tcc.ui.tcc.main_window import _mark_missing

    _app()
    combo = QComboBox()
    entries = [mc.Choice(harness="sdk", model="claude-opus-5", label="Opus 5",
                         provider="anthropic")]
    MainWindow._fill_combo(combo, entries, "agy:gemini-3.1-pro-high", critic=True)
    assert "is-missing" in str(combo.property("class"))

    combo.setCurrentIndex(combo.findData("sdk:claude-opus-5"))
    _mark_missing(combo, entries)

    assert "is-missing" not in str(combo.property("class"))


def test_no_row_repeats_what_the_row_already_says(monkeypatch):
    """Bold says "recommended"; the label already ends in "(Low)". Both badges were dropped —
    "там є Low і хто знає на скільки він лоу" (user, 2026-08-12): a note that neither adds a fact
    nor quantifies one is width spent on nothing."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox
    from autosound_tcc.core import model_choices as mc

    # The subject is which badges a row carries. "Clipboard only" is a badge that DOES add a fact,
    # so it is not one of the two under test — but it appears whenever the machine cannot reach the
    # reviewer, which on CI is always. Said out loud here rather than inherited from a PATH.
    monkeypatch.setattr(mc, "critic_reaches", lambda choice: True)
    # Said out loud for the same reason, and it is the same kind of leak: which badges a row
    # carries is not a question about what this machine happens to be reading right now.
    # `_fill_combo` asks `availability.status`, and a MainWindow another test left alive keeps a
    # catalogue read on a thread -- "agy" then sits in `availability._reading` for as long as that
    # thread lives, and these rows come back "· not checked". Measured on this file, 2026-09-18:
    # 1 run in 10 before the footer work of TODO F-060, 4 in 9 after it -- the race was always
    # there, and a layout change that shifts timing by a few milliseconds is enough to find it.
    # The availability word has its own tests (`test_availability.py`, and line ~2931 here).
    from autosound_tcc.core import availability
    monkeypatch.setattr(availability, "status", lambda choice, **_: availability.Status(True))
    _app()
    combo = QComboBox()
    entries = [
        mc.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro (High)",
                  provider="google"),
        mc.Choice(harness="agy", model="gemini-3.1-pro-low", label="Gemini 3.1 Pro (Low)",
                  provider="google"),
    ]

    MainWindow._fill_combo(combo, entries, "", critic=True)

    assert i18n.t("modelRecommended") not in combo.itemText(0), "bold says it; words repeat it"
    assert combo.itemText(1).endswith("Gemini 3.1 Pro (Low)"), "no badge after the label"
    assert combo.itemData(0, Qt.ItemDataRole.FontRole).bold(), "the high one is still marked"
    # ...and a badge that DOES carry a fact stays: "free" is not on the label.
    free = QComboBox()
    MainWindow._fill_combo(free, [
        mc.Choice(harness="agy", model="gemini-3.1-flash", label="Gemini 3.1 Flash",
                  provider="google", free=True),
    ], "", critic=True)
    assert i18n.t("modelFree") in free.itemText(0)


def test_opening_the_curve_window_wires_it_to_the_ledger_and_the_series():
    """`_open_curves` had no test at all, and it is where the curve window is handed the two facts
    it cannot get for itself: what each channel is set to now, and which capture series the panel
    is showing. A typo in either would only have surfaced on the first click during a real tune
    (found before packaging, 2026-08-12)."""
    from autosound_tcc.core import delay_bank

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    window._open_curves(["w-L_01 (sw)", "w-R_01 (sw)"])

    dialog = window._curve_dialog
    assert dialog is not None
    assert dialog._delays_provider is not None and dialog._session_provider is not None
    # Both are callable right now, on a window with no project loaded — the degraded path is the
    # one a first launch takes.
    assert dialog._delays_provider() == {}, "no project loaded is an empty ledger, not a crash"
    assert dialog._session() == (window._meas_panel.viewing_session_id() or None)
    assert delay_bank.load(session=dialog._session()) == {}

    # ...and switching series in the panel reaches the open window rather than raising.
    window._meas_panel.sessionChanged.emit("cap_001")

    dialog.close()  # closed, not dropped — the window holding it stays in `_KEEP_WINDOWS`


def test_the_curve_window_is_reused_not_rebuilt():
    """pyqtgraph builds parentless QMenus on every PlotItem; enough construct/destroy cycles
    segfault the process from inside its own `__init__`."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    window._open_curves(["w-L_01 (sw)"])
    first = window._curve_dialog
    window._open_curves(["m-L_01 (sw)", "m-R_01 (sw)"])

    assert window._curve_dialog is first
    first.close()


def test_every_title_asked_for_reaches_the_curve_window_not_the_first_two():
    """The last pair-shaped slice on the path: the window held two pickers once, and `[:2]` here
    outlived them. The model names as many measurements as it wants looked at (a whole side is
    four), and the chip row is where a tuner takes one off again."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`
    three = ["w-L_01 (sw)", "m-L_01 (sw)", "tw-L_01 (sw)"]

    window._open_curves(three)
    assert window._curve_dialog._chosen() == three

    window._open_curves(three[::-1])  # re-pointed, same window, still all of them
    assert window._curve_dialog._chosen() == three[::-1]
    window._curve_dialog.close()


def test_the_panels_curves_button_opens_on_one_curve_and_then_on_the_last_set():
    """User, 2026-08-19: "при відкритті вікна показувати одну першу (перший раз для нового сету) чи
    ті що були попереднього разу (в поточній сесії роботи), а НЕ ВСІ". A series is nine or eighteen
    measurements, and plotting all of them is a picture of nothing — one REW call each, and then
    a chip to remove for every driver before any question can be asked.

    Everything else stays one tick away: `_open_curves` hands the window every title REW holds as
    the choose menu's options, which is what makes opening narrow safe rather than limiting."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`
    series = ["w-L_01 (sw)", "w-R_01 (sw)", "m-L_01 (sw)", "m-R_01 (sw)"]

    window._meas_panel.curvesRequested.emit(series)

    dialog = window._curve_dialog
    assert dialog._chosen() == ["w-L_01 (sw)"], "a series never opened: the first title, alone"
    assert set(series) <= set(dialog._options), "and all of it is one tick away in the menu"

    # What the tuner then chose is what the button reopens on.
    dialog._set_selection(["m-L_01 (sw)", "m-R_01 (sw)"])
    dialog.close()
    window._meas_panel.curvesRequested.emit(series)

    assert window._curve_dialog._chosen() == ["m-L_01 (sw)", "m-R_01 (sw)"]
    window._curve_dialog.close()


def test_a_remembered_title_rew_no_longer_holds_is_dropped_not_asked_for():
    """A re-measured round renames its captures. A remembered set is filtered against what the
    panel is offering NOW, or the window would open asking REW for a curve nobody has — and with
    nothing left of the memory it falls back to the first title, the same as a fresh series."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    window._curve_last[window._curve_series_key()] = ["w-L_01 (sw)", "gone_01 (sw)"]
    window._meas_panel.curvesRequested.emit(["w-L_01 (sw)", "w-R_01 (sw)"])

    assert window._curve_dialog._chosen() == ["w-L_01 (sw)"], "the survivor, and only it"

    window._curve_last[window._curve_series_key()] = ["gone_01 (sw)"]
    window._meas_panel.curvesRequested.emit(["w-L_01 (sw)", "w-R_01 (sw)"])

    assert window._curve_dialog._chosen() == ["w-L_01 (sw)"], "nothing left: the first title"
    window._curve_dialog.close()


def test_the_models_own_request_is_not_narrowed_by_what_was_looked_at_last():
    """`show_curves` names the measurements it wants looked at, out loud, and gets exactly those.
    The memory is about the PANEL's button, which offers a whole series and has to choose."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`
    window._curve_last[window._curve_series_key()] = ["w-L_01 (sw)"]

    window._on_curves_requested({
        "titles": ["m-L_01 (sw)", "m-R_01 (sw)", "tw-L_01 (sw)"], "kind": "phase",
    })

    assert window._curve_dialog._chosen() == ["m-L_01 (sw)", "m-R_01 (sw)", "tw-L_01 (sw)"]
    window._curve_dialog.close()


def test_a_route_whose_cli_is_missing_is_greyed_and_says_what_it_needs():
    """User, 2026-08-19: Codex was nowhere in the picker, so it read as something the app cannot
    do — when what was missing was one CLI. The row is there now, disabled, naming what it wants;
    and the field still counts it as missing, because a chosen route that cannot run has to say
    so."""
    from autosound_tcc.core import model_choices

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`
    combo = window._ai_critic_combo
    here = model_choices.Choice(harness="sdk", model="claude-opus-5", label="Claude Opus 5")
    gone = model_choices.Choice(
        harness="codex", model="gpt-5.2-codex", label="gpt-5.2-codex", available=False
    )

    MainWindow._fill_combo(combo, [here, gone], here.key, critic=True)

    rows = [combo.itemText(i) for i in range(combo.count())]
    assert rows[0].startswith("SDK · Claude Opus 5")
    assert "CODEX · gpt-5.2-codex" in rows[1]
    assert i18n.t("availNotInstalled") in rows[1]
    assert i18n.t("modelInstallCli").format(cli="codex") in combo.itemData(1, Qt.ItemDataRole.ToolTipRole)
    assert combo.model().item(0).isEnabled() is True
    assert combo.model().item(1).isEnabled() is False, "not selectable, and looks it"


def test_a_drop_down_is_as_wide_as_its_widest_row_whatever_the_box():
    """User, on Windows 11, 2026-08-19: the lists came back elided — "AGY · Gem...sh (High)",
    "x...h", and in the narrowest one nothing but "...". Qt sizes a popup to the CLOSED box, and
    these combos are narrow on purpose; the stylesheet then spends 28 px of the row on the check
    mark. The closed box may elide. The list may not."""
    from autosound_tcc.ui.tcc.theme import mini_combo

    _app()
    combo = mini_combo()
    combo.addItem("AGY · Gemini 3.7 Flash (High)", "a")
    combo.addItem("SDK · Claude Opus 5", "b")
    combo.setFixedWidth(60)  # as tight as the narrowest row in the app

    combo.showPopup()
    combo.hidePopup()

    widest = combo.fontMetrics().horizontalAdvance("AGY · Gemini 3.7 Flash (High)")
    assert combo.view().minimumWidth() >= widest, "the longest label fits, uncut"
    assert combo.view().minimumWidth() > combo.width(), "and the popup is free of the box's width"


def test_the_popup_width_follows_the_contents_it_is_opened_with():
    """Computed at showPopup, not once at build time: a catalogue arrives, a language switches, a
    project is loaded — a width measured once goes stale without anybody noticing."""
    from autosound_tcc.ui.tcc.theme import mini_combo

    _app()
    combo = mini_combo()
    combo.addItem("EN", "en")
    combo.showPopup()
    combo.hidePopup()
    narrow = combo.view().minimumWidth()

    combo.addItem("AGY · Gemini 3.7 Flash (Medium)", "x")
    combo.showPopup()
    combo.hidePopup()

    assert combo.view().minimumWidth() > narrow


def test_the_title_bar_carries_both_versions():
    """The title bar is in every screenshot anybody sends, so it is the cheapest place a version
    can live — and a bug is against a PAIR, the app and the method, so one alone leaves the other
    to be guessed (user, 2026-08-19)."""
    from autosound_tcc.core import install_report

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    title = window.windowTitle()

    assert "Tuning Command Center" in title
    if install_report.app_version():
        assert f"TCC {install_report.app_version()}" in title
    if install_report.skill_version():
        assert f"skill {install_report.skill_version()}" in title
    # And NOT the method's commit. It was here from HUB-001, on the argument that the title is on
    # every screenshot; live on Windows the brackets read as noise in the one line a person reads
    # without being asked, and F-036 narrowed the identifier to the installation report, which is
    # the artefact that gets pasted into a chat. Held here so it cannot drift back in unnoticed.
    if install_report.skill_sha():
        assert install_report.skill_sha()[:12] not in title


def test_the_title_says_when_something_newer_exists(monkeypatch):
    """The versions are already in the title, so that is where "there is a newer one" belongs —
    it is the line a person reads without being asked to (user, 2026-08-19)."""

    _app()
    window = MainWindow()
    before = window.windowTitle()
    assert i18n.t("titleUpdate") not in before

    window._title_note = i18n.t("titleUpdate")
    window._set_title()

    assert i18n.t("titleUpdate") in window.windowTitle()
    assert str(config.project_dir()) in window.windowTitle(), "and the project stays first"


def test_the_title_follows_what_the_diagnostics_window_learns(monkeypatch):
    """VM-3: the method was updated in TCC, its row said «Скіл 3.0.65 — актуальна», and the title
    kept «skill 3.0.65 · є оновлення» — through Re-check, through ↻ — until TCC restarted. The
    title now says what the last answer for each half says: either newer keeps the word, both
    current drop it, and a half nobody could ask about changes nothing."""
    from autosound_tcc.core import updates

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    window._diag_btn.click()
    dialog = window._diag_dialog
    word = i18n.t("titleUpdate")

    dialog._show_update(updates.Status("skill", "3.0.64", "3.0.65", True))
    assert word in window.windowTitle(), "gains it when an answer says available"
    dialog._show_update(updates.Status("tcc", "0.1.45", "0.1.45", False))
    assert word in window.windowTitle(), "TCC current, the method still newer"
    dialog._show_update(updates.Status("skill", "3.0.64", "", False, "no_network"))
    assert word in window.windowTitle(), "could not ask is not up to date"
    dialog._show_update(updates.Status("skill", "3.0.65", "3.0.65", False))
    assert word not in window.windowTitle(), "both current: the word goes"
    assert "skill" in window.windowTitle() and str(config.project_dir()) in window.windowTitle()


def test_the_title_drops_the_word_when_the_method_is_updated_in_tcc(monkeypatch):
    """VM-3, the case the Arbiter met: no Re-check needed — the update's own receipt is an answer."""
    from autosound_tcc.core import updates

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    window._diag_btn.click()
    dialog = window._diag_dialog
    dialog._show_update(updates.Status("skill", "3.0.64", "3.0.65", True))
    assert i18n.t("titleUpdate") in window.windowTitle()
    monkeypatch.setattr(updates, "local_changes", lambda tag="": updates.LocalChanges(True, ()))
    monkeypatch.setattr(updates, "apply_skill", lambda tag="", keep_local=False, send=False:
                        updates.SkillUpdate(True, version="v3.0.65", libs_ok=True))
    # Not the real re-read (#126): it would undo the suite's dead REW port (conftest).
    from autosound_tcc.core import vendor_loader

    monkeypatch.setattr(vendor_loader, "reload_loaded", lambda: True)

    dialog._update_skill()
    for _ in range(5):
        if dialog._skill_job is None:
            break
        dialog._skill_job.join(timeout=10)
        dialog._poll_skill_job()

    assert i18n.t("titleUpdate") not in window.windowTitle()


def test_the_header_reload_asks_again_for_the_title(monkeypatch):
    """VM-3: ↻ is «what changed since I looked», and an update installed since is one of those
    things. A press asks GitHub again, off the GUI thread, and the title follows the answer both
    ways. The session's `report_phase` reloads the project the same way and asks nothing: a phase
    move is no reason to go to the network. Behind the launch-time question's switch."""
    from PySide6.QtTest import QTest

    from autosound_tcc.core import updates

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    monkeypatch.setattr(MainWindow, "_safe_load_project", lambda self: None)
    monkeypatch.setattr(MainWindow, "_start_contract_check", lambda self: None)
    monkeypatch.setattr(MainWindow, "_ping_rew", lambda self: None)
    monkeypatch.setattr(MainWindow, "_refresh_cli_catalogue", lambda self, force=False: None)
    answer, asked = [True], []
    monkeypatch.setattr(updates, "check_all", lambda channel="stable": asked.append(channel) or (
        updates.Status("tcc", "0.1.45", "0.1.45", False),
        updates.Status("skill", "3.0.64", "3.0.65", answer[0])))
    word = i18n.t("titleUpdate")

    def settle(want: bool) -> None:
        for _ in range(60):
            if (word in window.windowTitle()) is want:
                return
            QTest.qWait(50)
        raise AssertionError(f"the title never {'gained' if want else 'dropped'} it")

    window._header_refresh_btn.click()
    assert asked == [], "the switch is off in tests: nothing was asked"

    monkeypatch.setenv("AUTOSOUND_TCC_MCP", "1")  # past the launch-time escape hatch (conftest)
    window._bridge.refresh_from_disk()  # what the session's report_phase sends
    QTest.qWait(50)
    assert asked == [], "a phase report asks GitHub nothing"
    window._header_refresh_btn.click()
    settle(True)
    answer[0] = False
    window._reload_action.trigger()
    settle(False)
    assert len(asked) == 2


def test_the_project_menu_can_reach_the_new_project_dialog(monkeypatch):
    """The dialog behind it is the only path to the DSP-profile interview and to seeding a project
    from an existing one -- and its button in the left column has been hidden ever since "which
    project" moved into this menu, which had no "new project" item. So the feature shipped with no
    door: found by the user asking where it was."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    labels = [action.text() for action in window._menu_btn.menu().actions()]
    assert i18n.t("projectNew") in labels
    assert window._new_project_action.toolTip()

    opened = []
    monkeypatch.setattr(window, "_open_new_project_dialog",
                        lambda *a, **k: opened.append(True))
    window._new_project_action.trigger()
    assert opened == [True]


def test_the_resonalyze_import_is_reachable_before_there_is_a_ledger():
    """A project seeded an hour ago has facts, a profile and no ledger at all -- and a plan from
    somebody else in hand is exactly why. As a button above the DSP tree it followed the tree's
    visibility, so it was hidden in the one state it exists for; in the main menu it is reachable
    whatever the project holds, and the dialog says plainly when there is no profile to check
    against."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    window._show_left_status("no profile here yet")

    assert not window._tree.isVisible(), "the precondition: no DSP view"
    assert window._import_action.isEnabled()
    assert window._import_action.text() == i18n.t("riImport")




def test_the_main_menu_gathers_the_whole_window_in_sections():
    """"Let us make this the main menu and gather everything there logically" (user, 2026-08-23).
    Before it, the same window's vocabulary was spread over a header, a footer, a hidden button in
    the left column and two popups -- so a person looking for a thing had four places to look and
    no way to know which.

    The sections are DISABLED actions, which is also why they are asserted here: `addSection`
    draws no text under a stylesheet, and the failure is invisible rather than loud.
    """
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    actions = window._menu_btn.menu().actions()
    labels = [a.text() for a in actions]
    for key in ("menuProject", "menuSession", "menuTools", "menuHelp"):
        assert i18n.t(key).upper() in labels, key
    headings = [a for a in actions if a.text() in {i18n.t(k).upper() for k in
                ("menuProject", "menuSession", "menuTools", "menuHelp")}]
    assert all(not a.isEnabled() for a in headings), "a heading is not a thing you can press"

    # Every act the chrome no longer carries has a home here.
    for key in ("projectOpen", "projectNew", "menuCopyCar", "riImport", "menuReload",
                "menuStartSession", "menuTerminal",
                "menuDiagnostics", "menuTargetTool", "supportGithub", "supportMonobank"):
        assert any(i18n.t(key) in label for label in labels), key
    # The technical settings in one submenu (finding 70, tcc#67).
    settings = next(a.menu() for a in actions if a.menu() and i18n.t("menuSettings") in a.text())
    inside = settings.actions()
    inner = [a.text() for a in inside]
    for key in ("menuModels", "menuReviewerKey", "menuTheme", "menuZoomIn", "menuZoomOut"):
        assert any(i18n.t(key) in label for label in inner), key
    for key in ("eqOrderMenu", "gateMode", "menuLanguage"):
        assert any(a.menu() and a.text() == i18n.t(key) for a in inside), key
    # The last line of TOOLS, right above HELP (the Arbiter, 2026-09-27: «перенеси … в наступний
    # розділ в кінець»); it closed SESSION before.
    help_at = labels.index(i18n.t("menuHelp").upper())
    visible = [a for a in actions[:help_at] if not a.isSeparator()]
    assert visible[-1].menu() is settings
    # Bold, so it reads as a submenu (the Arbiter, finding 91, tcc#81).
    assert settings.menuAction().font().bold()
    assert labels.index(i18n.t("menuTools").upper()) < actions.index(visible[-1])


def test_the_guides_submenu_is_bold_and_opens_the_three_guides_at_the_installed_version(
        monkeypatch):
    """Help → «Посібники», a bold submenu holding the quick guide, the full one and the
    target-curve page (the Arbiter, finding 134, tcc#120: «підменю (жирним), в середині квік-гайд,
    фул-гайд і цільова крива гайд»). Each on GitHub at this build's own tag (tcc #49, hub #202
    SKL-053): `docs/` is not in the installed package, so the menu opens the page, not a file."""
    from PySide6.QtGui import QDesktopServices

    from autosound_tcc.core import guide

    _app()
    monkeypatch.setattr(guide, "installed_guide_url", lambda page=guide.QUICK_GUIDE:
                        f"https://example.invalid/v9.9.9/{page}")
    opened: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    actions = window._menu_btn.menu().actions()
    help_at = next(i for i, a in enumerate(actions) if a.text() == i18n.t("menuHelp").upper())
    guides = next(a.menu() for a in actions[help_at:]
                  if a.menu() and i18n.t("menuGuides") in a.text())
    assert guides.menuAction().font().bold()
    inside = guides.actions()
    assert [a.text() for a in inside] == [i18n.t(key) for key in
                                          ("menuGuideQuick", "menuGuideFull", "menuGuideCurve")]
    for action in inside:
        action.trigger()

    assert opened == ["https://example.invalid/v9.9.9/QUICK-GUIDE.md",
                      "https://example.invalid/v9.9.9/REFERENCE.md",
                      "https://example.invalid/v9.9.9/HOUSE-CURVE.md"]


def test_the_question_mark_after_the_target_curve_opens_the_methods_guide(monkeypatch):
    """«пряме посилання … знак питання після посилання» (the Arbiter, finding 134, tcc#120): the
    curve's name opens the tool, the «?» right after it the method's guide to target curves."""
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtTest import QTest

    from autosound_tcc.core import guide

    _app()
    monkeypatch.setattr(guide, "method_target_guide_url",
                        lambda: "https://example.invalid/v3.0.64/target_curves_guide.md")
    opened: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    mark = window._target_guide_lbl
    layout = window._target_label.parentWidget().layout()
    assert layout.indexOf(mark) == layout.indexOf(window._target_label) + 1
    assert mark.text() == "?"
    assert mark.hover_tip.text() == i18n.t("targetGuideTip")

    QTest.mouseClick(mark, Qt.MouseButton.LeftButton)
    assert opened == ["https://example.invalid/v3.0.64/target_curves_guide.md"]

    # The hint follows a language switch, as the curve's own does.
    window._on_language_selected("uk")
    try:
        assert mark.hover_tip.text() == i18n.t("targetGuideTip")
        assert mark.hover_tip.text() != i18n.T["en"]["targetGuideTip"]
    finally:
        window._on_language_selected("en")


def test_the_main_menu_follows_a_language_switch():
    """A menu item's label is set once, at construction -- so before this the menu kept the
    language it was born in while the window changed around it. It is rebuilt now, which is also
    what makes the language check marks show the choice that was just made."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`
    try:
        window._on_language_selected("uk")
        labels = [a.text() for a in window._menu_btn.menu().actions()]
        assert i18n.t("projectNew") in labels and "Новий проєкт…" in labels

        settings = next(a.menu() for a in window._menu_btn.menu().actions()
                        if a.menu() and i18n.t("menuSettings") in a.text())
        lang_menu = next(a.menu() for a in settings.actions()
                         if a.menu() and a.text() == i18n.t("menuLanguage"))
        checked = [a.text() for a in lang_menu.actions() if a.isChecked()]
        assert checked == [i18n.t("langNameUk")]
    finally:
        window._on_language_selected("en")


def test_copy_the_car_opens_the_dialog_already_copying(monkeypatch):
    """Its own act, not a second button for "new project": starting from a car somebody has
    already described is a different intent from starting from nothing, and the menu says so in
    the words the user chose."""
    from autosound_tcc.ui.tcc import new_project_dialog as npd

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    dialog = npd.NewProjectDialog(seed_first=True)
    assert dialog._seed_combo.currentData() == "copy"
    assert dialog._seed_edit.isVisible() or dialog._seed_edit.isVisibleTo(dialog)

    plain = npd.NewProjectDialog()
    assert plain._seed_combo.currentData() is None, "the plain path still starts from nothing"

    seeds = []
    monkeypatch.setattr(window, "_open_new_project_dialog", lambda seed=False: seeds.append(seed))
    window._copy_car_action.trigger()
    window._new_project_action.trigger()
    assert seeds == [True, False]


def test_the_footer_s_omp_button_reads_omp_in_every_language(monkeypatch):
    """VM-16: the footer's «models…» read on the VM as a word cut short. The Arbiter: «OMP», the
    same in all four languages -- what it opens is omp's catalogue. Drawn whole: the window's
    own button, as wide as its word."""
    assert {lang: i18n.T[lang]["configureModels"] for lang in ("en", "uk", "pl", "de")} == {
        "en": "OMP", "uk": "OMP", "pl": "OMP", "de": "OMP"}
    app = _app()
    window = MainWindow()
    # Shown, a window reads omp's catalogue on a thread that outlives the test (the review, M4).
    monkeypatch.setattr(window, "_refresh_cli_catalogue", lambda force=False: None)
    window.show()
    try:
        app.processEvents()
        assert window._models_btn.text() == "OMP"
        assert window._models_btn.width() >= window._models_btn.sizeHint().width()
        # Three letters say nothing to whoever does not know omp: the hover names what it opens
        # (the review, M6), in the window's language.
        assert window._models_btn.hover_tip.text() == i18n.t("configureModelsTitle")
        window._on_language_selected("uk")
        assert window._models_btn.hover_tip.text() == i18n.t("configureModelsTitle")
    finally:
        i18n.set_language("en")
        window.hide()


def test_the_thanks_and_feedback_buttons_are_in_the_footer_and_in_the_menu():
    """Both, on purpose (user, 2026-08-23). Saying thank you and reporting a bug are the two
    things somebody does on impulse, and an impulse does not open a menu -- but the menu is where
    a person LOOKS for a thing they have not pressed before."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    assert window._coffee_btn.text() == i18n.t("coffeeBtn")
    assert i18n.t("fbBig") in window._feedback_btn.text()

    labels = [a.text() for a in window._menu_btn.menu().actions()]
    assert any(i18n.t("fbBig") in label for label in labels)
    assert i18n.t("supportGithub") in labels and i18n.t("supportMonobank") in labels


def _row_width_report(window, footer) -> str:
    """Every row of the window that could be holding its minimum width, and who in each refuses
    to give up a pixel.

    These rows are checked on three platforms and their width is a property of the UI FONT, so
    the run that fails is routinely one nobody can open: the author's machine passes and a CI
    runner does not (TODO F-060, Windows). A message naming only the widget drawn past the edge
    says which control was LAST in the row, never which one held it, and those are different
    controls -- and the row that holds the window need not be the row the test was looking at.
    So the message carries all of them: what each item asks for, what it will come down to, and
    the sum of the ones that will not move at all.
    """
    rows = [frame for frame in window.findChildren(QFrame)
            if str(frame.property("class") or "") == "panel phead"]
    if footer not in rows:
        rows.append(footer)
    lines = [f"window min {window.minimumSizeHint().width()} px, and it is {window.width()} px"]
    for row in sorted(rows, key=lambda r: -r.minimumSizeHint().width()):
        layout = row.layout()
        which = "footer" if row is footer else "row"
        lines.append(f"  {which}: min {row.minimumSizeHint().width()} px, "
                     f"hint {row.sizeHint().width()} px, actual {row.width()} px")
        unmovable = 0
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget()
            if widget is None or not widget.isVisible():
                continue
            floor, wanted = item.minimumSize().width(), item.sizeHint().width()
            if floor >= wanted:
                unmovable += floor
            text = widget.currentText() if hasattr(widget, "currentText") else (
                widget.text() if hasattr(widget, "text") else "")
            lines.append(
                f"    {'FIXED  ' if floor >= wanted else 'shrinks'} {type(widget).__name__:12s} "
                f"min={floor:4d} hint={wanted:4d} actual={widget.width():4d}  {text[:28]!r}")
        lines.append(f"    un-shrinkable total: {unmovable} px")
    return "\n".join(lines)


def test_a_narrow_window_squeezes_the_footer_instead_of_pushing_its_buttons_off_the_edge():
    """TODO F-045 (user, Windows, v0.1.28): the bottom-right element goes off to the right and hides
    the icons -- "the field could be made smaller" instead.

    No control in the footer would give up a pixel, so the row's natural width was the WINDOW's
    minimum. Asked for 1280 px -- the width this window opens at, and a 1920 px screen at 150% -- it
    stayed 1314 px wide (measured 2026-09-17), and the two buttons at the right end sat past the
    edge.

    Measured the way the user meets it. At a roomy width every control keeps its natural size;
    narrowed, the whole row stays inside the window, left to right with no control drawn over the
    next, and none is squeezed below the width the layout promises it.
    """
    app = _app()
    window = MainWindow()
    window.show()
    footer = window._coffee_btn.parentWidget()
    layout = footer.layout()

    def name(widget) -> str:
        text = widget.currentText() if hasattr(widget, "currentText") else widget.text()
        return f"{type(widget).__name__} {text!r}"

    # What "roomy" is, is the LAYOUT's number and not a screen size: the same row needs more
    # window where the text is wider, and 1600 px was roomy on macOS and Linux while the Windows
    # runner already squeezed at it (CI on PR #41, 2026-09-17, where the picker came out 143 px
    # against the 260 it asks for). The frame around the row is what the window has beyond it.
    window.resize(1600, 820)
    for _ in range(4):
        app.processEvents()
        app.sendPostedEvents()
    roomy_width = max(1600, footer.sizeHint().width() + window.width() - footer.width())

    for width, roomy in ((roomy_width, True), (1280, False)):
        window.resize(width, 820)
        for _ in range(4):
            app.processEvents()
            app.sendPostedEvents()
        # First, and separately from the per-control checks below: a control drawn past the edge
        # is the SYMPTOM of a window that could not be made this narrow, and naming the symptom
        # sends the reader to the last widget in the row instead of the one holding the width --
        # which may not even be in this row.
        assert window.width() <= width, (
            f"the window could not be made {width} px wide (it is {window.width()}). "
            f"The rows below are what a narrow window comes down to:\n"
            f"{_row_width_report(window, footer)}")
        items = [layout.itemAt(i) for i in range(layout.count())]
        shown = [(item, item.widget()) for item in items
                 if item.widget() is not None and item.widget().isVisible()]

        for item, widget in shown:
            last = widget.mapTo(window, widget.rect().topRight()).x()
            assert last < width, (
                f"{name(widget)} is drawn up to x={last} in a window asked to be {width} px wide "
                f"(it is {window.width()})")
            promised = (item.sizeHint() if roomy else item.minimumSize()).width()
            assert widget.width() >= promised, (
                f"{name(widget)} is {widget.width()} px wide at {width}, below the {promised} px "
                f"the layout promises it")
        for (_, left), (_, right) in zip(shown, shown[1:]):
            drawn, next_from = left.geometry(), right.geometry().left()
            assert drawn.right() < next_from, (
                f"at {width} px {name(left)} (x {drawn.left()}..{drawn.right()}) is drawn over "
                f"{name(right)} (from x {next_from})")


def test_a_roomy_footer_shows_the_reviewer_whole_and_a_narrow_one_keeps_its_floors(monkeypatch):
    """VM-9 (the Windows VM, a full-screen window): the footer kept «API · gemini-3.1-pr…» beside
    a wide empty gap. A model picker asked for sixteen letters and could not be given more, and the
    gap took the rest. Where the row has room, each picker widens to its pick whole -- and no
    further -- and the room comes out of the gap, every other control keeping its own width;
    narrowed, the row lays out as it did, from the same asks and floors (the Arbiter: «обрізання в
    такому форматі - ОК»).

    «Roomy» is room for BOTH pickers' picks: on CI's wider fonts «— choose a model —» is longer
    than the Generator's sixteen letters too, and room made for the reviewer alone was shared
    between them (the first run on Windows: 455 px against the 615 the reviewer's pick takes)."""
    import math

    from PySide6.QtGui import QFontMetricsF
    from PySide6.QtWidgets import QStyle, QStyleOptionComboBox

    from autosound_tcc.core import model_choices
    from autosound_tcc.ui.tcc import copy_menu
    from autosound_tcc.ui.tcc.theme import drawn_width

    app = _app()
    window = MainWindow()
    monkeypatch.setattr(window, "_refresh_cli_catalogue", lambda force=False: None)
    combo = window._ai_critic_combo
    pickers = (window._ai_main_combo, combo)
    footer = combo.parentWidget()
    layout = footer.layout()

    def settle() -> None:
        for _ in range(4):
            app.processEvents()
            app.sendPostedEvents()

    def whole(box) -> int:
        """The box's width with its pick drawn whole: how far its text is drawn (`theme.
        drawn_width`), and the chrome around the edit field."""
        option = QStyleOptionComboBox()
        box.initStyleOption(option)
        field = box.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                           QStyle.SubControl.SC_ComboBoxEditField, box).width()
        metrics, text = QFontMetricsF(box.font()), box.currentText()
        return math.ceil(drawn_width(metrics, text)) + box.width() - field

    def own_asks() -> int:
        """What the row's controls ask for of themselves, before a picker is lent anything."""
        return footer.sizeHint().width() - sum(p.lent() for p in pickers)

    window.show()
    settle()
    floor = footer.minimumSizeHint().width()
    pick = model_choices.Choice(harness="api", model="gemini-3.1-pro-preview",
                                label="gemini-3.1-pro-preview")
    window._critic_choices = [pick]
    MainWindow._fill_combo(combo, [pick], pick.key, critic=True)
    settle()
    text = combo.currentText()
    assert text.startswith("API · gemini-3.1-pro-preview"), text
    assert footer.minimumSizeHint().width() == floor, "a pick never moves the footer's floor"
    asks = combo.sizeHint().width() - combo.lent()  # the picker's own ask, sixteen letters
    assert whole(combo) > asks, "the pick is longer than the picker asks for: nothing to test"

    short = sum(p.short_of_pick() for p in pickers)
    window.resize(window.width() - footer.width() + own_asks() + short + 40, 820)
    settle()
    for box in pickers:
        assert box.fit_text() == box.currentText(), (
            f"at {window.width()} px a picker reads «{box.fit_text()}», {box.width()} px wide "
            f"against the {whole(box)} its pick takes\n{_row_width_report(window, footer)}")
    assert combo.width() <= whole(combo) + 1, "as wide as the pick, not wider"
    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget()
        if widget is not None and widget not in pickers and widget.isVisible():
            assert widget.width() >= item.sizeHint().width(), (
                f"{type(widget).__name__} gave up room to a picker\n"
                f"{_row_width_report(window, footer)}")

    # The reviewer's status grows (#113's note of a pin set aside): it takes its whole width
    # before a picker is lent a pixel. With room for every control's own ask and half of what the
    # pickers are short, the note is whole and the pickers share the rest.
    status = window._critic_status
    status.setText(f"{copy_menu.full_text(status)} · {i18n.t('criticPinsShortBoth')}")
    settle()
    window.resize(window.width() - footer.width() + own_asks() + short // 2, 820)
    settle()
    assert status.text() == copy_menu.full_text(status), (
        f"at {window.width()} px the note reads «{status.text()}» while the pickers are lent "
        f"{[p.lent() for p in pickers]}\n{_row_width_report(window, footer)}")
    assert 0 < sum(p.lent() for p in pickers) < short

    # Narrowed to the window's own floor, where the row has nothing to spare on any font.
    window.resize(window.minimumSizeHint().width(), 820)
    settle()
    assert own_asks() > footer.contentsRect().width(), _row_width_report(window, footer)
    assert combo.width() <= asks and combo.sizeHint().width() == asks, (
        f"narrowed, the picker is {combo.width()} px and asks {combo.sizeHint().width()} against "
        f"its own {asks}: the room came out of the row\n{_row_width_report(window, footer)}")


@pytest.mark.parametrize("stretch", [100, 141])
def test_a_narrow_german_footer_keeps_the_effort_box_whole(monkeypatch, stretch):
    """VM-13 (the Windows VM): in a narrow German window the effort box read «…» — «KI MAIN»,
    «AUFWAND» and «KI CRITIC» are longer than the English, and the box gave way with the rest
    down to its 62-px floor. The Arbiter: the effort box is never narrower than its widest value
    («x-high», the same in all four languages); the model pickers give way instead, and may elide.
    Under the window's sheet, at the window's own floor and at 1280 px, in the Mac's font and
    stretched about as wide as the Windows runner's (the wide-font emulation's `WIDE_STRETCH`;
    once, F-065: an application-wide font is a write to every live widget), the box draws
    «x-high» whole -- and at the floor it is the reviewer picker that is cut."""
    from PySide6.QtGui import QFont, QFontDatabase

    app = _app()
    was = QFont(app.font())
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setStretch(stretch)
    if app.font() != font:
        app.setFont(font)
    try:
        window = MainWindow()
        monkeypatch.setattr(window, "_refresh_cli_catalogue", lambda force=False: None)
        window.show()
        _let_it_settle()
        window._on_language_selected("de")
        _let_it_settle()
        effort = window._ai_effort_combo
        widest = max((effort.itemText(i) for i in range(effort.count())),
                     key=effort.fontMetrics().horizontalAdvance)
        assert widest == "x-high", widest
        footer = effort.parentWidget()
        floor = window.minimumSizeHint().width()
        for width in (floor, 1280):
            window.resize(width, 820)
            _let_it_settle()
            for index in range(effort.count()):
                effort.setCurrentIndex(index)
                assert effort.fit_text() == effort.itemText(index), (
                    f"at {window.width()} px the effort box reads «{effort.fit_text()}», "
                    f"{effort.width()} px wide\n{_row_width_report(window, footer)}")
            if width == floor:
                critic = window._ai_critic_combo
                assert critic.width() < critic.sizeHint().width(), (
                    f"the pickers give way instead: at the floor ({window.width()} px) the "
                    f"reviewer is the one cut\n{_row_width_report(window, footer)}")
    finally:
        i18n.set_language("en")
        if app.font() != was:
            app.setFont(was)


#: The output table's columns that read whole at the full window's minimum (tcc#106, finding 114:
#: «300 …», «NO…», «GAIN DE», «ELAY M» on the Arbiter's screenshot): the crossovers, the gain, the
#: delay and the polarity.
_WHOLE_AT_THE_MINIMUM = ("HPF", "LPF", "Gain dB", "Delay ms", "Pol")


def _write_the_arbiters_rig(folder) -> None:
    """The Arbiter's rig -- a Helix, ten columns in the output table -- every crossover as wide as
    one gets («3500 LR4»), and a version before it with every value different, so that with
    «порівняти з» on it every value in the table is a CHANGED one: drawn bold, its widest look."""
    profile = {"dsp_profile": {"name": "DSP Ultra S", "vendor": "Helix", "groups": [
        {"id": "virtual_channels", "label": "Virtual channels",
         "fields": ["gain_db", "ta_ms", "polarity", "phase_deg", "mute", "eq_bypass", "eq"]},
        {"id": "physical_outputs", "label": "Output channels",
         "fields": ["hp", "lp", "gain_db", "ta_ms", "polarity", "phase_deg", "mute", "eq"]}]}}
    (folder / "dsp_profile.json").write_text(json.dumps(profile))
    codes = ("tw-L", "tw-R", "m-L", "m-R", "c", "w-L", "w-R", "r-L", "r-R", "sw")
    preset = folder / "FULL"
    preset.mkdir()
    for version, (freq, gain, delay, polarity) in (("v_001", (350, -3.5, 2.09, "INV")),
                                                   ("v_002", (3500, -12.5, 15.75, "NORM"))):
        leg = {"f": freq, "type": "LR", "slope": 24}
        channels = {code: {"slot": slot, "hp": leg, "lp": leg, "gain_db": gain, "ta_ms": delay,
                           "polarity": polarity, "phase_deg": 180}
                    for slot, code in zip("ABCDEFGHIJ", codes)}
        (preset / f"{version}.json").write_text(json.dumps(
            {"preset": "FULL", "sample_rate": 96000, "channels": channels}))
    (preset / "HEAD").write_text("v_002")


def _window_on_a_screen(tmp_path, monkeypatch, screen):
    """A full window on the project in `tmp_path`, stood on a screen `screen` px wide: the
    offscreen platform's own is 800, narrower than any window these tests are about."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(main_window, "_screen_room", lambda _widget: QRect(0, 0, screen, 1080))
    _app()
    return MainWindow()


def _open_the_arbiters_rig(tmp_path, monkeypatch, screen=10_000):
    """A full window on the Arbiter's rig, the output table open, on a screen `screen` px wide."""
    _write_the_arbiters_rig(tmp_path)
    window = _window_on_a_screen(tmp_path, monkeypatch, screen)
    window._on_table_requested("physical_outputs")
    window.show()
    return window


def _settle_at(window, width) -> None:
    window.resize(width, 900)
    for _ in range(4):
        QApplication.processEvents()
        QApplication.sendPostedEvents()


def _let_it_settle() -> None:
    for _ in range(4):
        QApplication.processEvents()
        QApplication.sendPostedEvents()


def _floor_part(window) -> int:
    """The window width the three columns ask for: the splitter's minimum, which carries the
    centre's floor, and the margins round it."""
    margins = window.centralWidget().layout().contentsMargins()
    return window._main_splitter.minimumSizeHint().width() + margins.left() + margins.right()


def _other_rows(window) -> int:
    """The window width the rows above and below the columns ask for -- the header and the
    footer have floors of their own, which are not the centre's."""
    layout = window.centralWidget().layout()
    margins = layout.contentsMargins()
    return margins.left() + margins.right() + max(
        layout.itemAt(i).minimumSize().width() for i in range(layout.count())
        if layout.itemAt(i).widget() is not window._main_splitter)


def _what_does_not_read(window) -> list[str]:
    """Everything tcc#106 wants whole that is not, at the window's width now: a named column
    narrower than its cells or its heading ask for, a tab word or «закрити» elided. Asked of the
    widgets themselves -- the table's own size hints, the tab's own fit -- so no pixel count of
    any one platform's font is written here."""
    table = window._detail._scroll.widget()
    header = table.horizontalHeader()
    cut = []
    for column in range(table.columnCount()):
        title = table.horizontalHeaderItem(column).text()
        if title not in _WHOLE_AT_THE_MINIMUM:
            continue
        need = max(table.sizeHintForColumn(column), header.sectionSizeHint(column))
        if table.columnWidth(column) < need:
            cut.append(f"{title}: {table.columnWidth(column)} px of the {need} it needs "
                       f"({table.item(0, column).text()!r})")
    pane = window._detail
    for word in (pane._tab_table, pane._tab_eq, *pane._param_tabs.values(), pane._close_btn):
        if word.fit_text() != word.text():
            cut.append(f"{word.text()!r} reads {word.fit_text()!r}")
    return cut


# The stretched font once, in the longer words: there it only checks that the floor sits at the
# cap and says so, which the language does not change (F-065).
@pytest.mark.parametrize(("stretch", "lang"), [(100, "en"), (100, "uk"), (141, "uk")])
def test_the_full_window_at_its_minimum_reads_the_output_table_and_its_tabs(
        tmp_path, monkeypatch, stretch, lang):
    """tcc#106 (TEST-FINDINGS 114): at the full window's minimum the Arbiter's output table read
    «300 …», «NO…», «GAIN DE», «ELAY M», and the pane's tabs had no words -- «може збільшити
    мінімальну ширину трохи?». The minimum now holds the table's named columns and the tabs whole,
    wherever that fits under two thirds of the screen; where it does not, it sits at two thirds.

    The need is measured off the table and the tabs in the window's own font, so no number here is
    a number of Mac pixels: a stretch of 141 stands in for the Windows runner's offscreen text,
    about twice as wide (Qt finds no fonts there). On a 1920-px screen the Mac's offscreen font
    fits under the cap and is read; the stretched one does not, and the test says so."""
    app = _app()
    before = QFont(app.font())
    if stretch != 100:
        wide = QFont(before)
        wide.setStretch(stretch)
        app.setFont(wide)
    try:
        window = _open_the_arbiters_rig(tmp_path, monkeypatch, screen=1920)
        window._on_language_selected(lang)
        # Roomy is the window's own measure, not a screen size: three times its minimum.
        roomy = 3 * max(window.minimumSizeHint().width(), window._centre_need())
        _settle_at(window, roomy)
        table = window._detail._scroll.widget()
        assert table.item(0, 2).text() == "3500 LR4" and table.item(0, 2).font().bold(), \
            "the widest crossover, drawn as a changed one"
        assert not _what_does_not_read(window), "roomy, everything reads"

        _settle_at(window, 200)
        assert window.width() == window.minimumSizeHint().width() < roomy, "at the minimum"
        cap, need = 1920 * 2 // 3, window._centre_need()
        around = _floor_part(window) - window._center.minimumWidth()
        if need + around > cap:
            assert _floor_part(window) == cap, "the floor sits at two thirds of the screen"
            pytest.skip(f"in this font the table and the tabs need {need + around} px of window, "
                        f"more than two thirds of a 1920-px screen ({cap}): the minimum sits at "
                        f"the cap, and the columns elide there")
        assert window._center.minimumWidth() == max(320, need), "the measured need, not capped"
        assert not _what_does_not_read(window), (
            f"at the full window's minimum ({window.width()} px, the centre "
            f"{window._center.width()} px): {_what_does_not_read(window)}")
    finally:
        app.setFont(before)
        i18n.set_language("en")


# The stretched font in both languages: there the header holds the window's floor (1317-1328 px),
# so two thirds do not bind and only the rounds and the row are checked, and the run says so with a
# skip (tcc#132; tcc#106's own test skips that font; its tabs elide at the header's floor with the
# flat 200-px column too).
# An older journal's series-only rounds in the Mac's font, where the cap binds (Ruling 31).
@pytest.mark.parametrize(("stretch", "lang", "shape"), [
    (100, "uk", "round-open"), (100, "de", "round-open"), (141, "uk", "round-open"),
    (141, "de", "round-open"), (100, "uk", "series-only"), (100, "de", "series-only")])
def test_a_round_open_on_two_thirds_of_a_1512_screen_leaves_the_centre_its_tabs(
        tmp_path, monkeypatch, stretch, lang, shape):
    """VM-15's re-review (N1): the right column's floor follows the measurement panel's head row,
    and on a 1512 screen the window's floor sits at two thirds of it (tcc#106), so every pixel the
    column gained came out of the centre: 588 -> 499-536 px, and the detail tabs read «Табли…»,
    «Ріве…» at the width the Arbiter signed off on (finding 114). Ruling 30 (c): only the round
    ids are held whole, the live phrase may give way, and the row gives up the room it did not
    use. With the Arbiter's rig open and a round open in the capture task -- or an older
    journal's series-only rounds, «серія 2», which held as no id read «сері…» (Ruling 31) -- at
    the window's own floor: the floor is still two thirds of the screen, the tabs read whole,
    every round reads whole, and nothing in the panel's head row overlaps."""
    from tests.test_measurement_panel import _head_row, _is_round_id, _rounds

    app = _app()
    before = QFont(app.font())
    if stretch != 100:
        wide = QFont(before)
        wide.setStretch(stretch)
        app.setFont(wide)
    try:
        window = _open_the_arbiters_rig(tmp_path, monkeypatch, screen=1512)
        monkeypatch.setattr(window, "_refresh_cli_catalogue", lambda force=False: None)
        window._on_language_selected(lang)
        panel = window._meas_panel
        panel.set_sessions(_rounds(shape))
        _settle_at(window, 200)
        assert window.width() == window.minimumSizeHint().width(), "at the window's floor"
        said = f"{lang} at {stretch}: window {window.width()} px, centre {window._center.width()}"
        # The premise, read off the window rather than the font: two thirds of the screen bind
        # only where the header and the footer ask for less. Where one of them asks for more --
        # the stretched font here, and the Windows runner's font-less text (CI on 0277e21) --
        # it holds the window's floor and the centre has the room it leaves.
        cap = 1512 * 2 // 3
        assert _floor_part(window) <= cap, f"{said}: the columns' floor past two thirds"
        rows = _other_rows(window)
        if rows <= cap:
            assert window.width() <= cap, said
            tabs = [cut for cut in _what_does_not_read(window) if " reads " in cut]
            assert not tabs, f"{said}: {tabs}"
        combo = panel._session_combo
        for index in range(combo.count()):
            if _is_round_id(combo.itemText(index)):
                combo.setCurrentIndex(index)
                assert combo.fit_text() == combo.itemText(index), (said, combo.fit_text())
        row = _head_row(panel)
        for left, right in zip(row, row[1:]):
            assert left.geometry().right() < right.geometry().left(), (
                f"{said}: {type(left).__name__} runs into {type(right).__name__}")
        if rows > cap:
            # Said, not passed: a green run here checked the rounds and the row and not the tabs
            # (tcc#132). Last, so what this font does check is checked first.
            pytest.skip(f"{said}: the header and the footer hold the window at {rows} px, past two "
                        f"thirds of the 1512 screen ({cap}), so the tabs are not checked here; the "
                        f"rounds and the head row are")
    finally:
        app.setFont(before)
        i18n.set_language("en")


def test_control_mode_leaves_the_full_window_its_own_minimum(tmp_path, monkeypatch):
    """tcc#106: the full window's floor belongs to the full window. Control mode (a layout of its
    own, #107) is not held to it, and coming back gives the full window its floor again."""
    from autosound_tcc.ui.tcc import control_layout

    monkeypatch.setattr(control_layout, "place_terminal_left", lambda *a, **k: None)
    monkeypatch.setattr(control_layout.MonitorFeed, "refresh", lambda self: None)
    window = _open_the_arbiters_rig(tmp_path, monkeypatch)
    _settle_at(window, 200)
    full = window.minimumSizeHint().width()
    assert full == window.width()

    window._control_layout.enter()
    _settle_at(window, 200)
    assert window.minimumSizeHint().width() < full, "control mode is not held to the full floor"

    window._control_layout.leave()
    _settle_at(window, 200)
    assert window.minimumSizeHint().width() == window.width() == full
    assert not _what_does_not_read(window)
    window._control_layout.toggle()
    window._control_layout.toggle()
    assert window.minimumSizeHint().width() == full


# Both sides of `min(cap, need)` on the Mac's font: the cap on 1512 (1008 of the 1124 needed), the
# need on 1920 (its cap 1280). The stretched font only landed on the cap again (F-065).
@pytest.mark.parametrize("stretch", [100])
@pytest.mark.parametrize("screen", [1512, 1920])
def test_the_full_window_s_floor_stays_under_two_thirds_of_its_screen(
        tmp_path, monkeypatch, screen, stretch):
    """tcc#106, the coordinator's ruling: the Arbiter's widths for the full window are «full
    screen -- a huge margin; half -- problems; 2/3 -- all fine», and at 2/3 of his 1512-pt screen
    his screenshot has the output table whole. Measured in the offscreen fonts the need came out
    1254 px there, and a floor that high would forbid the width he says works. So the floor is
    never more than two thirds of the window's screen, whatever the font, and never less than the
    centre's old 320 px.

    The header and the footer have floors of their own (#96, F-045); where one of them is wider
    than two thirds -- the stretched font's header is -- that is theirs, not this floor's."""
    app = _app()
    before = QFont(app.font())
    if stretch != 100:
        wide = QFont(before)
        wide.setStretch(stretch)
        app.setFont(wide)
    try:
        window = _open_the_arbiters_rig(tmp_path, monkeypatch, screen=screen)
        _settle_at(window, 200)
        cap, need = screen * 2 // 3, window._centre_need()
        around = _floor_part(window) - window._center.minimumWidth()
        assert need > 0, "the rig's tables were measured"
        assert _floor_part(window) == min(cap, need + around), (
            f"the columns ask {_floor_part(window)} px of a {screen}-px screen: the need is "
            f"{need + around}, the cap {cap}")
        assert window.minimumSizeHint().width() <= max(cap, _other_rows(window))
        assert window._center.minimumWidth() >= 320
    finally:
        app.setFont(before)


def test_moving_to_another_screen_refits_the_floor(tmp_path, monkeypatch):
    """The cap is two thirds of THE WINDOW'S screen: moved from a wide one to the Arbiter's
    1512-pt one, the floor comes down with it."""
    window = _open_the_arbiters_rig(tmp_path, monkeypatch, screen=10_000)
    _settle_at(window, 200)
    wide = _floor_part(window)
    monkeypatch.setattr(main_window, "_screen_room", lambda _widget: QRect(0, 0, 1512, 1080))
    window.windowHandle().screenChanged.emit(window.screen())
    assert _floor_part(window) <= 1512 * 2 // 3 < wide


def _at_the_right_edge(window, width, screen=1920, past=0) -> int:
    """The window `width` px wide (or its own minimum, if more) with its right edge `past` px
    beyond the screen's (negative: inside it); its width."""
    window.resize(width, 900)
    _let_it_settle()
    window.move(screen - window.frameGeometry().width() + past, 0)
    _let_it_settle()
    assert window.frameGeometry().right() == screen - 1 + past
    return window.width()


@pytest.mark.parametrize("past", [-50, 0, 100])
def test_a_floor_that_rises_on_a_shown_window_keeps_it_on_its_screen(
        tmp_path, monkeypatch, past):
    """The review of tcc#106 (probe A): a 1920 screen, the window 960 px wide against its right
    edge, no project; a project opens and the floor rises to its tables -- Qt grew the window to
    the right where it stood, 293 px past the screen. It is moved back inside, never past the
    left edge. The same path runs on a reload, a zoom, a language and a screen change.

    By its overflow, and never by more than it grew (the second review): a window that stood
    50 px inside the edge moves by what the growth pushed past it, and one parked 100 px beyond
    the edge -- onto a second monitor -- keeps its 100 px and moves by the growth alone."""
    window = _window_on_a_screen(tmp_path, monkeypatch, 1920)
    window.show()
    before_width = _at_the_right_edge(window, 960, past=past)
    before = window.frameGeometry()
    _write_the_arbiters_rig(tmp_path)
    window._load_project()
    _let_it_settle()
    if _floor_part(window) <= before_width:
        pytest.skip(f"in this font the window was {before_width} px before the project, no "
                    f"narrower than the floor it gets ({_floor_part(window)}): nothing grew")
    after = window.frameGeometry()
    grew = after.width() - before.width()
    assert window.width() >= _floor_part(window) and grew > 0, "the floor rose, the window grew"
    moved = min(max(0, before.right() + grew - 1919), grew)
    assert after.left() == before.left() - moved and after.left() >= 0, (
        f"x {before.left()}..{before.right()} grew by {grew} to {after.left()}..{after.right()}, "
        f"not moved by {moved}")
    assert after.right() == max(1919, before.right())


def test_a_reload_that_does_not_raise_the_floor_leaves_the_window_where_it_is(
        tmp_path, monkeypatch):
    """The second review of tcc#106: the check moved a window whose floor had NOT risen. The
    project is reloaded on every file the skill writes, and a window left 100 px past a 1920
    screen's right edge -- on its way to a second monitor -- was pulled back inside on each."""
    window = _open_the_arbiters_rig(tmp_path, monkeypatch, screen=1920)
    _let_it_settle()
    _at_the_right_edge(window, window.width(), past=100)
    parked, floor = window.frameGeometry(), window._center.minimumWidth()
    window._load_project()
    _let_it_settle()
    assert window._center.minimumWidth() == floor, "the same floor"
    assert window.frameGeometry() == parked, "and the window where it was left"


def test_leaving_control_mode_after_the_floor_rose_keeps_the_window_on_its_screen(
        tmp_path, monkeypatch):
    """The review of tcc#106 (probe B): the floor rose while control mode was on (a project
    opened), and leaving it restored the full window's saved geometry -- 1010 px -- which Qt then
    grew to the new floor to the right, past the screen. It is moved back inside."""
    from autosound_tcc.ui.tcc import control_layout

    monkeypatch.setattr(control_layout, "place_terminal_left", lambda *a, **k: None)
    monkeypatch.setattr(control_layout.MonitorFeed, "refresh", lambda self: None)
    window = _window_on_a_screen(tmp_path, monkeypatch, 1920)
    window.show()
    before = _at_the_right_edge(window, 1010)
    window._on_layout_toggle()
    assert window._control_layout.active
    _write_the_arbiters_rig(tmp_path)
    window._load_project()
    _let_it_settle()
    window._on_layout_toggle()
    assert not window._control_layout.active
    _let_it_settle()
    if _floor_part(window) <= before:
        pytest.skip(f"in this font the window was {before} px before the project, no narrower "
                    f"than the floor it gets ({_floor_part(window)}): nothing grew")
    frame = window.frameGeometry()
    assert window.width() >= _floor_part(window), "back with the floor that rose meanwhile"
    assert frame.left() >= 0 and frame.right() <= 1919, (
        f"the window is at x {frame.left()}..{frame.right()} on a 1920-px screen")


# German alone: Polish widened the header the same way, by 3 px less (F-065).
@pytest.mark.parametrize("lang", ["de"])
def test_leaving_control_mode_after_a_language_switch_keeps_the_window_on_its_screen(
        tmp_path, monkeypatch, lang):
    """The second review of tcc#106: the header widened while control mode was on -- the
    reviewer zoomed in -- and on leaving at a 1920 screen's right edge the window's right edge
    came to 1927. The check ran before the layout button's label changed, and the label's growth
    landed after it. It runs last now, and once more on the next pass of the event loop.

    A language switch widens the header the same way (1935 in German and 1932 in Polish against
    the first round's code), and costs no restyle of every live widget in the process, which
    the zoom's does: forty seconds a run in this file."""
    from autosound_tcc.ui.tcc import control_layout

    monkeypatch.setattr(control_layout, "place_terminal_left", lambda *a, **k: None)
    monkeypatch.setattr(control_layout.MonitorFeed, "refresh", lambda self: None)
    window = _window_on_a_screen(tmp_path, monkeypatch, 1920)
    window.show()
    try:
        _let_it_settle()
        _at_the_right_edge(window, 200)  # at its minimum, which the new words will raise
        before = window.frameGeometry()
        window._on_layout_toggle()
        window._on_language_selected(lang)
        _let_it_settle()
        window._on_layout_toggle()
        _let_it_settle()
        after = window.frameGeometry()
        assert after.width() > before.width(), "the new words widened the full window"
        assert after.left() >= 0 and after.right() <= 1919, (
            f"the window is at x {after.left()}..{after.right()} on a 1920-px screen")
    finally:
        i18n.set_language("en")


@pytest.mark.parametrize("lang", ["de", "pl"])
def test_a_language_switch_at_the_right_edge_keeps_the_full_window_on_its_screen(
        tmp_path, monkeypatch, lang):
    """tcc#122 (W-4's review of tcc#106): in the full window at a 1920 screen's right edge a switch
    to German left it past the edge (1935; Polish 1933): the floor was checked mid-switch, and the
    header and the footer grew with the words set after it. Checked once the words are all set,
    and once more on the event loop's next pass, as leaving control mode is."""
    window = _window_on_a_screen(tmp_path, monkeypatch, 1920)
    window.show()
    try:
        _let_it_settle()
        _at_the_right_edge(window, 200)  # at its minimum, which the new words will raise
        before = window.frameGeometry()
        window._on_language_selected(lang)
        _let_it_settle()
        after = window.frameGeometry()
        if after.width() <= before.width():
            pytest.skip(f"in this font the {lang} words did not widen the window "
                        f"({before.width()} -> {after.width()} px)")
        assert after.left() >= 0 and after.right() <= 1919, (
            f"the window is at x {after.left()}..{after.right()} on a 1920-px screen")
    finally:
        i18n.set_language("en")


@pytest.mark.parametrize("seconds, key, n", [(30, "diagAgoNow", None), (600, "diagAgoMin", 10),
                                             (7200, "diagAgoHours", 2),
                                             (3 * 86400, "diagAgoDays", 3)])
def test_how_long_ago_the_reviewer_answered_is_in_the_reader_s_language(seconds, key, n):
    """Finding 132 (tcc#122): «Критик · gemini-3.1-pro-preview · just now» in a Ukrainian window."""
    from datetime import datetime, timedelta, timezone

    at = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    try:
        i18n.set_language("uk")
        assert main_window._ago(at) == i18n.t(key).format(n=n)
        assert main_window._ago("not a time") == "not a time", "unreadable: the stamp as it is"
    finally:
        i18n.set_language("en")


def _write_a_small_rig(folder) -> None:
    """Three controls in the one tier -- a table narrower than its pane's head -- and a second
    configuration, SQ, to compare with."""
    profile = {"dsp_profile": {"name": "M6V4", "vendor": "Musway", "groups": [
        {"id": "physical_outputs", "label": "Output channels",
         "fields": ["hp", "lp", "gain_db"]}]}}
    (folder / "dsp_profile.json").write_text(json.dumps(profile))
    for name, versions in (("FULL", ("v_001", "v_002")), ("SQ", ("v_001",))):
        preset = folder / name
        preset.mkdir()
        for gain, version in enumerate(versions):
            channels = {code: {"slot": slot, "hp": {"f": 80 + gain}, "lp": {"f": 4000},
                               "gain_db": -2.0 - gain}
                        for slot, code in zip("AB", ("w-L", "w-R"))}
            (preset / f"{version}.json").write_text(json.dumps(
                {"preset": name, "sample_rate": 48000, "channels": channels}))
        (preset / "HEAD").write_text(versions[-1])


# Ukrainian, the Arbiter's and the longer words: the refit does not depend on the language (F-065).
@pytest.mark.parametrize("lang", ["uk"])
def test_picking_another_configuration_refits_the_floor_to_the_head(tmp_path, monkeypatch, lang):
    """The second review of tcc#106: the floor was measured before «порівняти з» came into the
    head, and picking another configuration's version showed «інша конфігурація» with no refit --
    on a three-control rig, whose table is narrower than the head, a floor of 549 px under a head
    that needs 697. The floor follows the head now, and at the minimum the head reads whole."""
    monkeypatch.setenv("AUTOSOUND_TCC_PRESET", "FULL")
    _write_a_small_rig(tmp_path)
    window = _window_on_a_screen(tmp_path, monkeypatch, 10_000)
    try:
        window._on_language_selected(lang)
        window._on_table_requested("physical_outputs")
        window.show()
        pane = window._detail
        combo = pane._compare_combo
        assert pane._compare_label.isVisibleTo(pane), "«порівняти з» is in the head"
        combo.setCurrentIndex(combo.findData("SQ/v_001"))
        assert pane._compare_other.isVisibleTo(pane), "another configuration is picked"
        _settle_at(window, 200)
        assert window._center.minimumWidth() == window._centre_need() > window._tables_need()
        cut = [f"{word.text()!r} reads {word.fit_text()!r}"
               for word in (pane._compare_label, pane._compare_other)
               if word.fit_text() != word.text()] + _what_does_not_read(window)
        assert not cut, f"at the minimum ({window.width()} px): {cut}"
    finally:
        i18n.set_language("en")


def test_a_copied_project_stores_a_model_key_the_registry_can_resolve(tmp_path, monkeypatch):
    """The dialog names a MODEL (`claude-opus-5`); a project setting holds a CHOICE key, which
    also says the harness (`sdk:claude-opus-5`). Writing the bare id stored something nothing
    could resolve, and the window met it as a RETIRED model — "there is nothing on this machine to
    run it with" — on the first copy that carried a model at all (user, 2026-08-23)."""
    from autosound_tcc.core import model_choices
    from autosound_tcc.ui.tcc.mock_data import AI_MODEL_IDS

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    written = {}
    monkeypatch.setattr(main_window.project_settings, "set_value",
                        lambda _dir, key, value: written.__setitem__(key, value))

    dialog = SimpleNamespace(open_terminal_cli=None, onboarding_ai_model=None,
                             in_app_model=AI_MODEL_IDS["Claude Opus 5"])
    window._adopt_choices_from_new_project(dialog)

    stored = written.get("generator")
    assert stored == "sdk:claude-opus-5", stored
    assert model_choices.resolve(model_choices.choices([]), stored).ok


def test_a_terminal_model_name_is_not_written_as_a_registry_key(monkeypatch):
    """A CLI was handed its own `--model`, in that CLI's vocabulary. It is not a key here."""

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`

    written = {}
    monkeypatch.setattr(main_window.project_settings, "set_value",
                        lambda _dir, key, value: written.__setitem__(key, value))

    dialog = SimpleNamespace(open_terminal_cli="claude", onboarding_ai_model="opus",
                             in_app_model=None)
    window._adopt_choices_from_new_project(dialog)

    assert written == {}


def test_both_channel_tiers_are_counted_the_same_way():
    """Two tiers listed one under the other read as two different formats when only one of them
    carries a parenthetical: "12 (2 off)" over a bare "8" (user, 2026-08-23). `(0 off)` is still
    not printed -- the tier says it in words instead, and the shape stays one shape."""
    from autosound_tcc.ui.tcc.main_window import _tier_count

    assert _tier_count(12, 2) == i18n.t("chanSumOff").format(total=12, off=2)
    assert _tier_count(8, 0) == i18n.t("chanSumAllOn").format(total=8, off=0)
    for said in (_tier_count(12, 2), _tier_count(8, 0)):
        assert said.startswith(("12", "8")) and said.endswith(")")
    assert "0" not in _tier_count(8, 0).split("(", 1)[1], "no (0 off) anywhere"


def test_a_quit_save_counts_out_loud_instead_of_looking_frozen(monkeypatch):
    """"The command was sent and I cannot tell whether it is running, hung, or already done"
    (user, 2026-08-23). A three-minute wait behind a static line looks exactly like a hang."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`
    worker = _HandoffWorker()
    window._agent_worker = worker
    # As the real path does: `closeEvent` sets this before handing off, and it is what stops the
    # close that follows the turn from asking the save question all over again.
    window._quitting = True

    window._hand_off(worker, "quit")

    assert window._quit_tick is not None and window._quit_tick.isActive()
    window._tick_quit_saving()
    said = window._status_strip.text()
    assert said.startswith(i18n.t("quitSavingElapsed").split("{")[0])

    worker.turn_done.emit()
    assert getattr(window, "_quit_tick", None) is None, "the count stops when the turn lands"


def test_closing_again_mid_save_asks_before_throwing_the_turn_away(monkeypatch):
    """He pressed close a second time precisely because nothing said what was happening, and the
    app shut down mid-turn without a word: `_quitting` was set, so the save question was skipped
    and the second close went straight through. Abandoning the wait stays allowed; abandoning it
    SILENTLY does not."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`
    worker = _HandoffWorker()
    window._agent_worker = worker
    window._quitting = True
    window._hand_off(worker, "quit")
    assert window._handoff_timer is not None, "the precondition: a save in flight"

    asked = []

    class _Event(QCloseEvent):
        """A real QCloseEvent: `super().closeEvent(event)` hands it to Qt, which type-checks."""

        def __init__(self):
            super().__init__()
            self.ignored = False

        def ignore(self):
            self.ignored = True
            super().ignore()

    # "Keep waiting" leaves everything running.
    monkeypatch.setattr(MainWindow, "_ask_abandon_save", lambda self: asked.append("wait") or False)
    event = _Event()
    window.closeEvent(event)
    assert event.ignored and window._handoff_timer is not None
    assert asked == ["wait"]

    # "Close without saving" goes through, and stops the wait it is abandoning.
    monkeypatch.setattr(MainWindow, "_ask_abandon_save", lambda self: asked.append("close") or True)
    monkeypatch.setattr(MainWindow, "stop_workers", lambda self: None)
    event = _Event()
    window.closeEvent(event)
    assert not event.ignored
    assert window._handoff_timer is None and getattr(window, "_quit_tick", None) is None



def test_a_language_switch_survives_a_project_that_has_a_flaw_map(tmp_path, monkeypatch):
    """The user's own crash, 2026-08-25: switching language threw `AttributeError:
    '_audio_placeholder'` and the window's error strip caught it.

    `_audio_placeholder` is built ONLY on the branch of `_rebuild_acoustics` where there are no
    flaws — it is the "nothing measured yet" sentence. `_retranslate` then set its text
    unconditionally, so any project with a measured flaw map crashed on every switch. It was wrong
    where it did not crash, too: `_rebuild_acoustics` had just written the explanatory sentence in
    the new language and the next line replaced it with a bare "no data yet".

    The suite missed it because every window it built had an EMPTY project, which is exactly the
    branch that happens to create the attribute.

    `action` matters to this fixture since SKL-015: the row has to be one the owner's panel
    actually draws, or the map is "all tuning plan" and the placeholder legitimately comes back —
    which is a different branch from the one this test is about.
    """
    (tmp_path / "project.json").write_text(json.dumps({
        "schema_version": 3,
        "acoustics": {"flaws": [{"f_hz": 73, "level_db": 9, "kind": "driver_resonance",
                                 "action": "leave"}]},
    }), encoding="utf-8")
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    _app()
    window = MainWindow()
    before = i18n.current_language()
    try:
        window._rebuild_acoustics()
        assert not hasattr(window, "_audio_placeholder"), "a flaw map means no placeholder"
        i18n.set_language("uk" if before != "uk" else "en")
        window._retranslate()  # this is what threw
    finally:
        i18n.set_language(before)
        window._retranslate()


def test_the_empty_flaw_map_keeps_its_sentence_across_a_language_switch(tmp_path, monkeypatch):
    """The other half of the same line: the placeholder must still say what the section is FOR
    after a switch, not degrade to "no data yet"."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    _app()
    window = MainWindow()
    before = i18n.current_language()
    try:
        i18n.set_language("uk" if before != "uk" else "en")
        window._retranslate()
        assert window._audio_placeholder.text() == i18n.t("acousticsNone")
    finally:
        i18n.set_language(before)
        window._retranslate()


def test_every_label_in_the_ai_row_follows_a_language_switch():
    """User, 2026-08-26, with a screenshot: an English window with «зусилля» still in it.

    `_ai_effort_lbl` was built from i18n and never re-set in `_retranslate`, while the two labels
    either side of it were. For somebody whose window always opens in Ukrainian that reads as "this
    field is never translated" — the string was there all along, the retranslate was missing it.
    Second one in two days; the listening panel's two word buttons were the first, and were also a
    row covered except for one widget.

    Driven through `_on_language_selected`, the window's own handler: the labels do not follow a
    bare `i18n.set_language`, so a test using that would prove nothing while passing.

    Asserted FORWARD — switch to a language, expect that language — not by hunting leftovers. A
    label that is never re-set keeps the language the window was BUILT in, which here is English,
    so looking for stale foreign text finds nothing however broken the retranslate is.
    """
    from autosound_tcc.ui.tcc import i18n

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`
    row = {"aiMain": window._ai_main_lbl,
           "aiEffort": window._ai_effort_lbl,
           "aiCritic": window._ai_critic_lbl}
    before = i18n.current_language()
    try:
        for lang, *_ in i18n.LANGS:
            window._on_language_selected(lang)
            for key, label in row.items():
                assert label.text() == i18n.T[lang][key], (
                    f"{key} shows {label.text()!r} after switching to {lang}"
                )
    finally:
        window._on_language_selected(before)


def test_no_label_in_the_window_is_left_in_the_language_it_was_built_in():
    """F-033. The wider walk that found the four labels F-034's narrow guard could not see.

    Every label the window owns, after switching to each language: nothing may still be showing an
    English string whose translation in that language is a different word. The four it caught were
    all the same shape — a label written by an EVENT (`criticNever` when the critic has not run,
    `dialogNoModel` before a model is picked, `leftNoProfile` while there is no profile,
    `copyEqBank` while the pane is closed) and never written again by `_retranslate`, so each kept
    the language its window was BUILT in until its own event happened to fire.

    **The filter is not cosmetic.** A word English uses anywhere is not evidence, whatever else it
    also spells: German's `curveShift` is "Delay" where English's is "delay", so an English tab
    reading "Delay" looked German until this existed. A label carries TEXT, not the key it came
    from, and two keys can land on one word — case-folded, since case is all that separates those
    two.

    Forward, not by hunting leftovers: a label that is never re-set keeps the BUILD language, which
    in this harness is English, so looking for stale foreign text finds nothing however broken the
    retranslate is.
    """
    from autosound_tcc.ui.tcc import i18n

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)  # see `_KEEP_WINDOWS`
    before = i18n.current_language()
    try:
        for lang, *_ in i18n.LANGS:
            if lang == "en":
                continue
            window._on_language_selected(lang)
            theirs = {v.casefold() for v in i18n.T[lang].values() if isinstance(v, str)}
            english_only = {
                text: key
                for key, text in i18n.T["en"].items()
                if isinstance(text, str) and text
                and i18n.T[lang].get(key) not in (None, text)
                and text.casefold() not in theirs
            }
            left = {
                english_only[lbl.text().strip()]: lbl.text().strip()
                for lbl in window.findChildren(QLabel)
                if lbl.text().strip() in english_only
            }
            assert left == {}, f"still English after switching to {lang}: {left}"
    finally:
        window._on_language_selected(before)


def test_the_protection_button_answers_where_it_was_pressed(tmp_path, monkeypatch):
    """F-041, reported as "нажимаю кнопку «Захист» ... і нічого не відбувається" (Windows,
    2026-09-01).

    Two things made that true, and this is the second one: the refusal was written to the status
    strip, which sits under the header, while the button is at the bottom of the right column —
    and on that run the bottom of the column was off the screen entirely (F-040). A click gets its
    answer next to the click; the strip stays what it is, the place for what TCC found on disk by
    itself.
    """
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)  # a folder with no project in it
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    said: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: said.append(self.text()) or QMessageBox.StandardButton.Ok)

    _app()
    window = MainWindow()
    window._open_protective()

    assert said, "a press that produces nothing at all is what was reported"
    assert i18n.t("protNoChannels") in said[0]


def test_protection_on_a_closed_round_on_screen_opens_as_a_correction(tmp_path, monkeypatch):
    """Review of finding 147, M5 — 147's own fault in another reader: the method keeps the last
    round in its state with `closed` set, and Protection took that id for the OPEN round. Viewing
    the closed round, the press opened the ordinary path, whose write the method refuses («no
    capture round is open»). A closed round is none: the press corrects the round on screen."""
    from PySide6.QtWidgets import QMessageBox

    from autosound_tcc.state import process_view
    from autosound_tcc.ui.tcc import protective_dialog

    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(process_view, "capture_round", lambda *_a, **_k: {
        "id": "cap_001", "closed": "2026-10-03T12:00:00+00:00"})
    asked = []
    monkeypatch.setattr(protective_dialog, "open_for",
                        lambda *a, capture_id="", **k: asked.append(capture_id) or None)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    monkeypatch.setattr(window._meas_panel, "viewing_session_id", lambda: "cap_001")
    window._open_protective()

    assert asked == ["cap_001"]


def test_the_capture_list_scrolls_and_the_picker_above_it_stays(tmp_path, monkeypatch):
    """The Arbiter, 2026-09-23: with many columns the WHOLE right column scrolled, taking the
    picker, the buttons and the legend with the list. Now the list scrolls on its own, both ways,
    and everything above it stays put.

    F-040 is still held: a round of 102 captures once made a card 1864 px tall in a 778 px column,
    with the plan above squeezed to 62 px. The border between the two cards holds its place and
    the plan keeps its floor.
    """
    from autosound_tcc.ui.tcc.mock_data import MeasGroup, MeasItem, MeasSession

    # An empty folder and no reload: windows left alive by earlier tests still run their deferred
    # work, and a reload re-renders the capture card from disk — i.e. empties the one this test
    # fills by hand (seen 2026-09-14, 1 in 3 full-file runs).
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(MainWindow, "_reload_project_files", lambda self: None)

    _app()
    window = MainWindow()
    window.resize(1440, 900)
    window.show()
    names = [f"{code}_{n:02d}" for n in range(1, 18)
             for code in ("sw", "w-L", "w-R", "m-L", "m-R", "tw-L")]
    panel = window._meas_panel
    panel.set_sessions((MeasSession(
        id="v1", version={"en": "Series 1", "uk": "серія 1"},
        groups=(MeasGroup(type="sw (LB)", items=tuple(MeasItem(n, "done", 1) for n in names)),),
    ),))
    QApplication.processEvents()
    window.resize(1441, 901)
    QApplication.processEvents()

    assert not window._right_split.childrenCollapsible()
    assert window._plan_panel.height() >= 160, "the plan card is not crushed by the one below it"

    # Forced rather than hoped for: whether 102 rows overrun depends on the platform's fonts, and
    # on the Windows runner the same list once FIT. What is tested is that the list scrolls when
    # it is taller than its place — so make it taller.
    area = panel._cols_scroll
    area.widget().setMinimumHeight(area.viewport().height() * 3)
    area.widget().setMinimumWidth(area.viewport().width() * 2)
    QApplication.processEvents()
    picker_at = panel._session_combo.mapTo(window, panel._session_combo.rect().topLeft())
    bar = area.verticalScrollBar()
    assert bar.maximum() > 0, "the list that overflowed can be scrolled"
    assert area.horizontalScrollBar().maximum() > 0, "and sideways, when the columns are wide"
    bar.setValue(bar.maximum())
    QApplication.processEvents()
    assert panel._session_combo.mapTo(window, panel._session_combo.rect().topLeft()) == picker_at, \
        "the picker does not move with the list"

    window.hide()


def test_the_border_between_plan_and_captures_is_remembered(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    store: dict = {}
    _app()
    window = MainWindow()
    monkeypatch.setattr(window._settings, "setValue", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(window._settings, "value", lambda k, d=None, **kw: store.get(k, d))
    window.resize(1400, 900)
    window.show()
    QApplication.processEvents()
    window._right_split.setSizes([500, 300])
    QApplication.processEvents()
    held = window._right_split.sizes()
    window._remember_right_split()
    assert window._read_right_split() == held
    window.hide()


def test_the_first_ledger_snapshot_is_watched_for_before_state_exists(tmp_path, monkeypatch):
    """autosound-tcc#3: on a new project `ui.preset` stayed `null` for the whole session — DSP
    panel blank, target curve blank with it — and only reopening the project brought them back.

    The directory watch that exists to catch the first `v_001.json` was switched off by the very
    condition it exists for: `state/` does not exist until that file is written, and the guard
    returned `[]` when it was missing. That is the NORMAL first run, not an edge case: the ledger
    is always the last artefact to appear, always into a folder nobody was watching.
    """
    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("AUTOSOUND_STATE_ROOT", raising=False)
    monkeypatch.delenv("AUTOSOUND_TCC_PRESET", raising=False)
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    _intake.seed(tmp_path)
    ledger = tmp_path / "state"
    ledger.rename(tmp_path / "state.later")  # a project that has not been tuned yet

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)

    assert not (tmp_path / "state").is_dir(), "the situation this is about"
    assert str(tmp_path) in window._watched_project_dirs(), (
        "the folder the ledger will appear in is what has to be watched")

    # ...and once it appears, the re-arm reaches it and the preset resolves without reopening.
    (tmp_path / "state.later").rename(ledger)
    window._on_project_file_changed()
    window._reload_project_files()

    watched = window._watched_project_dirs()
    # Where the next version appears: `state/versions/` on the per-project line the method seeds
    # since v3.0.60 (hub #195), `state/<preset>/` before it.
    from autosound_tcc.state import ledger_line

    grows = ledger / "versions" if ledger_line.is_project_line(ledger) else ledger / "FULL"
    assert str(ledger) in watched and str(grows) in watched
    assert window._preset_combo.currentData() == "FULL"


def test_the_ear_button_follows_the_active_phase(tmp_path, monkeypatch):
    """One place decides it: the process state's own `active_phase`. Phase 4 is the ear's
    (`core/listening.py`), and in every other phase the button is not there to be looked past."""
    from autosound_tcc.state import process_view

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(process_view, "capture_round", lambda *_a, **_k: None)

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)

    window._refresh_capture_task({"active_phase": "0"})
    assert window._dialog._listen_btn.isHidden()

    window._refresh_capture_task({"active_phase": "4"})
    assert not window._dialog._listen_btn.isHidden()

    window._refresh_capture_task({"active_phase": "-1"})
    assert window._dialog._listen_btn.isHidden()


def test_the_card_hears_which_titles_were_left_for_a_retake(tmp_path, monkeypatch):
    """Finding 147: the card is built here, and a title the import window left on «Re-take» is
    the panel's to name — passed in beside what REW shows and what the project took."""
    from autosound_tcc.state import measurement_view, process_view

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(process_view, "capture_round", lambda *_a, **_k: None)

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    asked = {}
    monkeypatch.setattr(window._meas_panel, "retake_titles", lambda: ["sw_7 (rta)"])
    monkeypatch.setattr(window, "_capture_version", lambda state=None: 7)
    monkeypatch.setattr(measurement_view, "build_sessions",
                        lambda *a, **k: asked.update(k) or None)

    window._refresh_capture_task({"active_phase": "0"})

    assert asked["retake"] == ["sw_7 (rta)"]


def test_a_refusal_naming_a_long_path_does_not_widen_the_left_column(tmp_path, monkeypatch):
    """A word-wrapping label's minimum is its longest unbreakable token, and an exception's own
    words are full of Windows paths. The method's refusal for a non-UTF-8 ledger (v3.0.46) named
    two of them (a plain wrapping label measured 361 px at 100%), the column followed, and every row in it — car, DSP,
    mic — was cut at the visible edge (user, 2026-09-06, with the picture)."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path))
    _app()
    window = MainWindow()
    path = r"C:\Users\o.yukhno\_autosound\testTCC8\state\FULL\v_001.json"
    message = (f"Could not load ledger: SnapshotError: {path}: not UTF-8 -- byte 0xa7 at position "
               f"2201. `python3 C:\\Users\\o.yukhno\\.claude\\skills\\autosound-tuning\\rew_tool"
               f"\\state\\state.py --root <project>/state repair-encoding` rewrites it as UTF-8.")

    window._show_left_status(message)

    label = window._left_status
    token = label.fontMetrics().horizontalAdvance(path)
    assert label.minimumSizeHint().width() < token / 2, "the path no longer sets the width"
    assert "\u200b" in label.text(), "and it has somewhere to wrap"


def test_a_card_header_gives_up_its_subtitle_before_it_widens_the_column():
    """The capture card's header — title, subtitle, "REW" and a dot — was the widest thing in the
    right column at 110% on Windows fonts, and a plain subtitle never shrinks. So the column laid
    itself out past the window's edge and was cut there, dot and buttons included."""
    from autosound_tcc.ui.tcc.labels import ElidedLabel

    _app()
    row, title, sub = main_window._phead("focus", "measSub")

    assert isinstance(sub, ElidedLabel), "the subtitle is the one that gives ground"
    natural = title.sizeHint().width() + sub.sizeHint().width()
    assert row.minimumSizeHint().width() < natural, "the row can be narrower than its two texts"


def test_a_stored_zoom_can_never_make_the_app_font_zero():
    """`theme._scale_font_sizes` multiplies EVERY `font-size` in the stylesheet by this number, so
    a zoom of 0 is not "slightly small" — it is the whole application at `font-size: 0.0px`, which
    Qt reports as "QFont::setPointSize: Point size <= 0 (-1)". That line is in the user's Windows
    log, twice on 2026-09-09, next to a startup that showed a narrow tall window.

    `_set_zoom` clamped; reading from the store did not, and the store is the registry on Windows,
    which hands back strings written by any version that ever ran."""
    from autosound_tcc.ui.tcc.main_window import _ZOOM_MAX, _ZOOM_MIN, _sane_zoom

    for bad in ("", "0", "-1", "abc", None, float("nan"), 0.0, -3.2):
        assert _sane_zoom(bad) == 1.0, bad
    assert _sane_zoom("1.2") == 1.2
    assert _sane_zoom(99) == _ZOOM_MAX
    assert _sane_zoom(0.1) == _ZOOM_MIN


def test_coming_back_to_the_window_re_asks_which_models_are_reachable(monkeypatch):
    """The Arbiter logs in where a login happens — in a terminal — and comes back to a window that
    still says the model is unreachable, with a red border and (!) on both pickers. TCC asks
    `claude auth status` ONCE, while it is starting, and cached the answer; nothing re-asked it,
    so the only way to see a login was to restart the app (user's screenshot, 2026-09-09).

    Activation is already the moment TCC re-asks REW, for exactly the same reason: the other
    application is the one being alt-tabbed to. A login is that, with a different program."""
    from PySide6.QtCore import QEvent

    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    asked = []
    monkeypatch.setattr(MainWindow, "_refresh_cli_catalogue", lambda self: asked.append(True))
    monkeypatch.setattr(MainWindow, "isActiveWindow", lambda self: True)

    window.changeEvent(QEvent(QEvent.Type.ActivationChange))

    assert asked == [True]


def test_alt_tabbing_in_and_out_does_not_start_a_probe_each_time(monkeypatch):
    """`claude auth status` is a subprocess. Someone moving between windows would otherwise spawn
    one per switch, which is both the console-flash problem and a pointless load."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    started = []
    monkeypatch.setattr(
        main_window._CliCatalogueWorker, "start", lambda self: started.append(True)
    )

    window._refresh_cli_catalogue()
    window._refresh_cli_catalogue()

    assert len(started) == 1, "the second one is inside the quiet period"


def test_the_reload_button_also_re_asks_which_models_answer(monkeypatch):
    """The header's ↻ re-read the project, the contract and REW — and not the one thing the person
    had just changed. They logged in, pressed Reload, and nothing moved (user, 2026-09-09).

    Its own docstring already made this argument once, for REW: "the other half of what changed
    since I looked". A login in a terminal is a third half."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    asked = []
    monkeypatch.setattr(
        MainWindow, "_refresh_cli_catalogue", lambda self, force=False: asked.append(force)
    )
    monkeypatch.setattr(MainWindow, "_safe_load_project", lambda self: None)
    monkeypatch.setattr(MainWindow, "_start_contract_check", lambda self: None)
    monkeypatch.setattr(MainWindow, "_ping_rew", lambda self: None)

    window._reload_from_disk()

    assert asked == [True], "a press means ask NOW — the quiet period is for alt-tabbing"


def test_the_catalogue_worker_forces_agy_only_when_asked(monkeypatch):
    """The startup worker must NOT relaunch agy — that is the Windows startup flash (TCC-006). The
    ↻ worker must, because the user pressing it is saying something changed. `force` tells them
    apart, and the worker has to carry it down to `refresh_cli_catalogue`."""
    _app()
    seen = []
    monkeypatch.setattr(
        main_window.model_choices, "refresh_cli_catalogue",
        lambda *, force=False, active_omp=None: seen.append((force, active_omp)) or {},
    )
    monkeypatch.setattr(main_window.claude_sdk, "probe_signed_in",
                        lambda *, force=False: None)

    main_window._CliCatalogueWorker().run()
    main_window._CliCatalogueWorker(force=True).run()
    main_window._CliCatalogueWorker(active_omp=["google/x"]).run()

    # The marked list travels with it: `omp models` is asked for exactly one purpose, labelling
    # models the user chose, so with nothing chosen it must not be asked at all (probe30).
    assert seen == [(False, []), (True, []), (False, ["google/x"])]


def test_a_catalogue_worker_waiting_on_the_start_stops_when_asked(monkeypatch):
    """Quitting during the start's read left this worker in an unbounded wait, and `stop_workers`
    waited five seconds and then left a RUNNING QThread for Qt to destroy — `qFatal` (final review,
    Important 5)."""
    import threading
    import time

    _app()
    asked = []
    monkeypatch.setattr(main_window.model_choices, "refresh_cli_catalogue",
                        lambda **kw: asked.append(kw) or {})
    never = SimpleNamespace(done=threading.Event())
    worker = main_window._CliCatalogueWorker(wait_for=never)
    worker.start()
    try:
        started = time.monotonic()
        worker.requestInterruption()
        stopped = worker.wait(2000)
        took = time.monotonic() - started
    finally:
        never.done.set()  # releases a worker that did not listen, so no thread outlives the test
        worker.wait(5000)

    assert stopped, "it returns once asked, though the start's reading never finished"
    assert took < 1.5
    assert asked == [], "an interrupted wait asks nothing afterwards"


def test_the_reload_press_settles_what_a_failed_start_left_unchecked(monkeypatch):
    """A start whose read raised leaves agy and Claude "not checked" — red, and rightly: nothing
    answered. The ↻ press is a read too, and when it succeeds nothing may stay red for the rest of
    the launch (final review, Important 6)."""
    from autosound_tcc.core import availability, model_choices

    _app()

    def boom(**_kw):
        raise RuntimeError("agy exploded")

    monkeypatch.setattr(main_window.model_choices, "refresh_cli_catalogue", boom)
    monkeypatch.setattr(main_window.claude_sdk, "probe_signed_in", lambda *, force=False: None)
    assert availability.StartupReading().start().wait(2.0)
    agy = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="x")
    sdk = model_choices.Choice(harness="sdk", model="claude-opus-5", label="y")

    def state(choice):
        return availability.status(choice, signed_in=lambda: None, unconfirmed=lambda _c: False)

    assert state(agy).reason == state(sdk).reason == availability.NOT_CHECKED

    monkeypatch.setattr(main_window.model_choices, "refresh_cli_catalogue", lambda **kw: {})
    main_window._CliCatalogueWorker(force=True).run()

    assert state(agy).ready and state(sdk).ready


def test_quitting_lets_go_of_a_worker_that_will_not_stop_and_cuts_its_signal(monkeypatch):
    """A probe is a real model call and the catalogue can be mid-read. `stop_workers` must hand a
    still-running one to `qt_shutdown` rather than let Qt destroy it, and cut its `done` first — a
    probe finishing after the window closed called `_on_reviewer_probed` on it (final review,
    Important 5 and Minor 1)."""
    from PySide6.QtCore import QObject, Signal

    from autosound_tcc.ui.tcc import qt_shutdown

    class _Stuck(QObject):
        done = Signal(str)
        finished = Signal()

        def isRunning(self) -> bool:  # noqa: N802 (QThread's name)
            return True

        def requestInterruption(self) -> None:  # noqa: N802 (QThread's name)
            pass

        def wait(self, _ms: int = 0) -> bool:
            return False

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    probe, catalogue = _Stuck(), _Stuck()
    arrived: list = []
    probe.done.connect(arrived.append)
    catalogue.done.connect(arrived.append)
    window._reviewer_probe, window._cli_catalogue = probe, catalogue
    try:
        window.stop_workers()
        detached = qt_shutdown.detached()
        probe.done.emit("clipboard")
        catalogue.done.emit("")
    finally:
        window._reviewer_probe = window._cli_catalogue = None
        qt_shutdown._DETACHED.discard(probe)
        qt_shutdown._DETACHED.discard(catalogue)

    assert probe in detached and catalogue in detached, "let go of, not destroyed running"
    assert arrived == [], "nothing a let-go worker says reaches the window"


def test_the_capture_panel_is_not_rebuilt_once_per_write(tmp_path, monkeypatch):
    """A process-state redraw re-reads the state, recomputes the plan, and DELETES AND REBUILDS
    the capture grid. Its watcher fired straight into that — and the watcher fires more than once
    per commit, while the skill records steps mid-turn. So a reload landed in the middle of a test
    that had just filled the capture panel and wiped it. Its sibling `_project_reload` has been
    coalesced all along; this one was connected raw."""
    window = _window_with_flaws(tmp_path, monkeypatch, [])
    drawn: list = []
    monkeypatch.setattr(window, "_refresh_process", lambda *a: drawn.append(1))

    for _ in range(8):                                 # one commit, several fileChanged
        window._process_watcher.fileChanged.emit("process-state.json")

    assert drawn == [], "a burst of writes buys no rebuilds while it is still arriving"
    assert window._process_reload.isActive(), "the redraw is pending, not dropped"

    window._process_reload.timeout.emit()              # what the timer does when the burst ends
    assert drawn == [1], "one rebuild for the burst"


def test_claude_is_asked_for_its_login_once_not_once_per_alt_tab(monkeypatch):
    """It said "once" in its own docstring and did not do it: nothing checked what it remembered,
    so every caller ran the CLI again — and the caller runs every time the window becomes active.
    On Windows that is a console window per alt-tab, and `claude` putting visible consoles on
    screen is an upstream bug closed as not planned (anthropics/claude-code #58606). Asking less
    often is the only lever we hold."""
    from autosound_tcc.core import claude_sdk

    ran: list = []
    monkeypatch.setattr(claude_sdk, "_ASKED", False, raising=False)
    monkeypatch.setattr(claude_sdk, "_SIGNED_IN", None, raising=False)
    monkeypatch.setattr(claude_sdk, "cli_path", lambda: "/usr/bin/claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        claude_sdk.child, "run_bounded",
        lambda *a, **k: ran.append(1) or subprocess.CompletedProcess(a, 0, '{"loggedIn": true}', ""))

    for _ in range(6):                       # six alt-tabs
        assert claude_sdk.probe_signed_in() is True
    assert ran == [1], "asked once, then remembered"

    claude_sdk.probe_signed_in(force=True)   # the press: somebody just logged in
    assert len(ran) == 2, "a press re-asks; that is what the press is for"


def test_a_model_that_cannot_run_is_red_with_one_word_and_the_rest_stay_plain():
    """The Arbiter, 2026-09-13: "models must be red when they are not available". Two colours:
    plain is ready, red is everything else, with one word for why."""
    from PySide6.QtGui import QColor

    from autosound_tcc.core import availability, model_choices
    from autosound_tcc.ui.tcc.theme import current_theme

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    combo = window._ai_critic_combo
    fine = model_choices.Choice(harness="agy", model="gemini-3.1-flash", label="Gemini 3.1 Flash")
    refused = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro")
    availability.reset()
    availability.refused(refused.key, availability.LOCATION, "selected location")
    try:
        MainWindow._fill_combo(combo, [fine, refused], fine.key, critic=True)
    finally:
        availability.reset()

    assert combo.itemData(0, Qt.ItemDataRole.ForegroundRole) is None
    assert combo.itemData(1, Qt.ItemDataRole.ForegroundRole) == QColor(current_theme().warn)
    assert i18n.t("availLocation") in combo.itemText(1)
    assert combo.model().item(1).isEnabled() is True, "a refused model can still be chosen"


def test_a_red_reviewer_says_why_in_the_footer_and_the_reload_button_forgets_it(monkeypatch):
    """"A short answer, so the person understands at once" (the Arbiter, 2026-09-13)."""
    from autosound_tcc.core import availability, model_choices

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    chosen = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro")
    window._critic_choices = [chosen]
    MainWindow._fill_combo(window._ai_critic_combo, [chosen], chosen.key, critic=True)
    monkeypatch.setattr(window, "_refresh_cli_catalogue", lambda force=False: None)
    monkeypatch.setattr(window, "_ping_rew", lambda: None)
    availability.reset()
    availability.refused(chosen.key, availability.LOCATION, "not supported in the selected location")
    try:
        window._refresh_critic_status()
        assert i18n.t("availPhraseLocation") in window._critic_status.text()
        assert "selected location" in window._critic_status.toolTip()

        window._reload_from_disk()
        assert availability.status(chosen).ready

        # The re-read lands: the footer must follow it, not keep the phrase until the next critique
        # (final review, Important 1 — it only refreshed at construction, critique, probe, retranslate).
        monkeypatch.setattr(window, "_project_setting", _reviewer_only)
        monkeypatch.setattr(model_choices, "choices", lambda _active: [])
        monkeypatch.setattr(model_choices, "critic_choices", lambda _active: [chosen])
        window._on_cli_catalogue_ready()
        assert window._critic_status.text() == i18n.t("criticNever")
        assert window._critic_status.toolTip() == ""
    finally:
        availability.reset()


def test_picking_another_reviewer_repaints_the_footer_for_it(monkeypatch):
    """The footer kept the OLD reviewer in red after the picker moved to a ready one: changing the
    reviewer refreshed only the warning mark, never the footer (final review, Important 1)."""
    from autosound_tcc.core import availability, critic, model_choices

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    refused = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro")
    ready = model_choices.Choice(harness="agy", model="gemini-3.1-flash", label="Gemini 3.1 Flash")
    window._critic_choices = [refused, ready]
    MainWindow._fill_combo(window._ai_critic_combo, [refused, ready], refused.key, critic=True)
    # A real call on record, so the plain footer has a model to name.
    critic.log_call(critic.CriticResult(critic.MODE_API_OR_CLI, "ok", ready.model, "critic", "",
                                        1.0, "2026-09-13T00:00:00+00:00"), None)
    availability.refused(refused.key, availability.LOCATION, "not supported in the selected location")
    try:
        window._refresh_critic_status()
        assert refused.label in window._critic_status.text()

        window._ai_critic_combo.setCurrentIndex(window._ai_critic_combo.findData(ready.key))

        text = window._critic_status.text()
        assert ready.model in text
        assert refused.label not in text
        assert i18n.t("availPhraseLocation") not in text
        assert window._critic_status.toolTip() == ""
    finally:
        availability.reset()


def test_the_reviewer_probe_turns_a_refused_model_red(monkeypatch):
    from autosound_tcc.core import availability, critic, model_choices
    from autosound_tcc.ui.tcc.main_window import _ReviewerProbeWorker

    _app()
    key = "agy:gemini-3.1-pro-high"
    calls = []
    monkeypatch.setattr(critic, "run", lambda package, **kw: calls.append(kw) or critic.CriticResult(
        critic.MODE_CLIPBOARD, "", None, "ask", "not supported in the selected location", 1.0, "t"))
    monkeypatch.setattr(model_choices, "critic_reaches", lambda _c: True)
    availability.reset()
    try:
        _ReviewerProbeWorker(key, config.project_dir()).run()
        state = availability.status(model_choices.Choice(harness="agy", model="gemini-3.1-pro-high",
                                                         label="x"))
    finally:
        availability.reset()

    assert calls and calls[0]["role"] == "ask" and calls[0]["model"] == "gemini-3.1-pro-high"
    assert state.reason == availability.LOCATION


def test_the_probe_asks_the_model_an_alias_sends_to_and_files_its_refusal_there(monkeypatch):
    """A real call goes to the alias target and every reader looks a refusal up under it; the probe
    read the stored key, sent ITS model, and filed the answer where nobody looks (final review,
    Important 2)."""
    from autosound_tcc.core import availability, critic, model_choices, model_overrides
    from autosound_tcc.ui.tcc.main_window import _ReviewerProbeWorker

    _app()
    old, new = "agy:gemini-3.0-pro", "agy:gemini-3.1-pro-high"
    model_overrides.set_alias(old, new)
    calls = []
    monkeypatch.setattr(critic, "run", lambda package, **kw: calls.append(kw) or critic.CriticResult(
        critic.MODE_CLIPBOARD, "", None, "ask", "not supported in the selected location", 1.0, "t"))
    monkeypatch.setattr(model_choices, "critic_reaches", lambda _c: True)
    availability.reset()
    try:
        _ReviewerProbeWorker(old, config.project_dir()).run()
        resolved = availability.status(
            model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="x"))
    finally:
        availability.reset()

    assert calls and (calls[0]["model"], calls[0]["harness"]) == ("gemini-3.1-pro-high", "agy")
    assert resolved.reason == availability.LOCATION


def test_no_reviewer_chosen_means_no_probe(monkeypatch):
    """A fresh install has no reviewer — nothing to probe and nothing to turn red (the Arbiter)."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    monkeypatch.setattr(window, "_project_setting", lambda key: "")
    started = []
    monkeypatch.setattr("autosound_tcc.ui.tcc.main_window._ReviewerProbeWorker.start",
                        lambda self: started.append(self))

    window._probe_reviewer()

    assert started == []


def test_a_reviewer_no_transport_reaches_is_not_probed(monkeypatch):
    """With no key and no CLI for its vendor the method script can only compile a clipboard
    package: nothing to record, and a prompt on the clipboard at session start (final review,
    Minor 3). What is asked is whether the RESOLVED reviewer can be reached."""
    from autosound_tcc.core import model_choices, model_overrides

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    monkeypatch.setenv("AUTOSOUND_TCC_MCP", "1")  # past the launch-time escape hatch (conftest)
    monkeypatch.setattr(window, "_project_setting", _reviewer_only)
    started = []
    monkeypatch.setattr("autosound_tcc.ui.tcc.main_window._ReviewerProbeWorker.start",
                        lambda self: started.append(self))
    asked = []
    monkeypatch.setattr(model_choices, "critic_reaches",
                        lambda choice: asked.append(choice.key) or False)

    window._probe_reviewer()
    assert started == [], "no transport, no probe"

    model_overrides.set_alias("agy:gemini-3.1-pro-high", "agy:gemini-3.5-pro")
    monkeypatch.setattr(model_choices, "critic_reaches",
                        lambda choice: asked.append(choice.key) or True)
    window._probe_reviewer()

    assert len(started) == 1, "a reviewer that can be reached is probed"
    assert asked == ["agy:gemini-3.1-pro-high", "agy:gemini-3.5-pro"]


def test_the_probe_writes_nothing_into_the_project(tmp_path, monkeypatch):
    """The probe runs FROM the real project — the cwd a real review has, so a CLI that checks folder
    trust against its cwd answers the probe as it answers a review (final review, Important 4) — and
    every write the method script makes goes to a throwaway folder: its answer under
    AUTOSOUND_PROJECT_DIR, its clipboard package and audit trail under PROJECT_MIRROR. A probe at
    session start must leave the project exactly as it found it."""
    from pathlib import Path

    from autosound_tcc.core import critic
    from autosound_tcc.ui.tcc.main_window import _ReviewerProbeWorker

    # `tests/conftest.py`'s autouse `_isolated_project_dir` already made this the real project
    # (AUTOSOUND_PROJECT_DIR) and it starts empty -- exactly the folder a probe must not touch.
    real_project = tmp_path / "project"
    recorded = {}

    # Recorded here and asserted below: an assertion raised INSIDE the probe is caught by its own
    # guard and logged, and the test would pass over it.
    def fake_run(package, project_dir=None, extra_env=None, timeout_s=None, **_kw):
        env = dict(extra_env or {})
        scratch = Path(env["AUTOSOUND_PROJECT_DIR"])
        mirror = Path(env["PROJECT_MIRROR"])
        recorded.update(project_dir=Path(project_dir), scratch=scratch, mirror=mirror,
                        timeout_s=timeout_s, package=Path(package),
                        stub_context=(mirror / "autosound_context.md").is_file())
        # Imitate what the method script itself does: file the answer under the project it was
        # told about, and write the clipboard package and the audit line under the mirror.
        reviews = scratch / "process" / "reviews"
        reviews.mkdir(parents=True)
        (reviews / "x-ask.md").write_text("answer", encoding="utf-8")
        (mirror / "combined_prompt.md").write_text("pkg", encoding="utf-8")
        (mirror / "audit-trail.md").write_text("line", encoding="utf-8")
        return critic.CriticResult(critic.MODE_CLIPBOARD, "", None, "ask", "", 0.1, "t")

    monkeypatch.setattr(critic, "run", fake_run)

    _ReviewerProbeWorker("agy:gemini-3.1-pro-high", real_project).run()

    assert recorded, "the probe called the reviewer"
    assert recorded["project_dir"] == real_project, "cwd stays the project, as for a real review"
    assert recorded["mirror"] == recorded["scratch"] / "rew_analitic"
    assert recorded["stub_context"], "the stub context is where the script looks first"
    assert recorded["package"].parent == recorded["scratch"]
    assert recorded["timeout_s"] == 180.0
    assert not recorded["scratch"].exists(), "the throwaway folder is gone with the probe"
    assert list(real_project.iterdir()) == [], "the real project is untouched"


def test_a_launch_failure_is_logged_and_still_reports_done(monkeypatch, caplog):
    import logging

    from autosound_tcc.core import app_log, availability, critic, model_choices
    from autosound_tcc.ui.tcc.main_window import _ReviewerProbeWorker

    monkeypatch.setattr(
        critic, "run",
        lambda *_a, **_kw: critic.CriticResult(
            critic.MODE_ERROR, "", None, "ask", "reviewer script not found", 0.0, "t"))
    availability.reset()
    done = []
    worker = _ReviewerProbeWorker("agy:gemini-3.1-pro-high", config.project_dir())
    worker.done.connect(done.append)
    try:
        with caplog.at_level(logging.WARNING, logger=app_log.LOGGER_NAME):
            worker.run()
        assert "reviewer script not found" in caplog.text
        choice = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="x")
        assert availability.status(choice).ready, "an error is not a refusal recorded in state"
    finally:
        availability.reset()

    assert done == [critic.MODE_ERROR]


def test_an_exception_inside_the_probe_is_logged_and_done_still_emits_empty(monkeypatch, caplog):
    import logging

    from autosound_tcc.core import app_log, availability, critic
    from autosound_tcc.ui.tcc.main_window import _ReviewerProbeWorker

    def blow_up(*_a, **_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(critic, "run", blow_up)
    availability.reset()
    done = []
    worker = _ReviewerProbeWorker("agy:gemini-3.1-pro-high", config.project_dir())
    worker.done.connect(done.append)
    try:
        with caplog.at_level(logging.WARNING, logger=app_log.LOGGER_NAME):
            worker.run()  # must not raise
    finally:
        availability.reset()

    assert done == [""]


def _reviewer_only(key: str) -> str:
    """`_project_setting` stub for the probe tests: only the reviewer is set, so `_reload_model_
    choices` does not also treat the same string as a dead GENERATOR choice and pop the (modal,
    test-hanging) "model gone" dialog for it."""
    return "agy:gemini-3.1-pro-high" if key == main_window._CRITIC_KEY else ""


def _stub_resolvable_reviewer(monkeypatch) -> None:
    """`_on_reviewer_probed` calls `_reload_model_choices`, which resolves the project's reviewer
    setting against a freshly-built list and pops a MODAL "model gone" dialog (hangs a headless
    test) for anything that does not resolve -- so the probe tests give it one that does."""
    from autosound_tcc.core import model_choices

    chosen = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="x")
    monkeypatch.setattr(model_choices, "choices", lambda _active: [])
    monkeypatch.setattr(model_choices, "critic_choices", lambda _active: [chosen])


def test_a_running_probe_is_not_replaced(monkeypatch):
    """Replacing a running QThread is the probe30 crash."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    monkeypatch.setenv("AUTOSOUND_TCC_MCP", "1")  # past the launch-time escape hatch (conftest)
    monkeypatch.setattr(window, "_project_setting", _reviewer_only)
    stub = SimpleNamespace(isRunning=lambda: True)
    window._reviewer_probe = stub
    started = []
    monkeypatch.setattr("autosound_tcc.ui.tcc.main_window._ReviewerProbeWorker.start",
                        lambda self: started.append(self))

    window._probe_reviewer()

    assert started == []
    assert window._reviewer_probe is stub


def test_the_clipboard_comes_back_after_a_clipboard_mode_probe(monkeypatch):
    from PySide6.QtGui import QGuiApplication

    from autosound_tcc.core import critic
    from autosound_tcc.ui.tcc.main_window import _REVIEWER_PROBE_QUESTION

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    monkeypatch.setenv("AUTOSOUND_TCC_MCP", "1")  # past the launch-time escape hatch (conftest)
    monkeypatch.setattr(window, "_project_setting", _reviewer_only)
    _stub_resolvable_reviewer(monkeypatch)
    # Reachable, or `_probe_reviewer` starts nothing and takes no snapshot to give back.
    monkeypatch.setattr("autosound_tcc.core.model_choices.critic_reaches", lambda _c: True)
    monkeypatch.setattr("autosound_tcc.ui.tcc.main_window._ReviewerProbeWorker.start",
                        lambda self: None)
    QGuiApplication.clipboard().setText("mine")

    window._probe_reviewer()  # takes the snapshot before start (stubbed to do nothing)
    QGuiApplication.clipboard().setText(f"...{_REVIEWER_PROBE_QUESTION}...")
    window._on_reviewer_probed(critic.MODE_CLIPBOARD)

    assert QGuiApplication.clipboard().text() == "mine"


def test_the_clipboard_is_left_alone_otherwise(monkeypatch):
    from PySide6.QtGui import QGuiApplication

    from autosound_tcc.core import critic
    from autosound_tcc.ui.tcc.main_window import _REVIEWER_PROBE_QUESTION

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    monkeypatch.setenv("AUTOSOUND_TCC_MCP", "1")  # past the launch-time escape hatch (conftest)
    monkeypatch.setattr(window, "_project_setting", _reviewer_only)
    _stub_resolvable_reviewer(monkeypatch)
    # Reachable, or `_probe_reviewer` starts nothing and takes no snapshot to give back.
    monkeypatch.setattr("autosound_tcc.core.model_choices.critic_reaches", lambda _c: True)
    monkeypatch.setattr("autosound_tcc.ui.tcc.main_window._ReviewerProbeWorker.start",
                        lambda self: None)

    # (a) something else was copied since the probe started -- the snapshot is stale, leave it.
    QGuiApplication.clipboard().setText("mine")
    window._probe_reviewer()
    QGuiApplication.clipboard().setText("copied later")
    window._on_reviewer_probed(critic.MODE_CLIPBOARD)
    assert QGuiApplication.clipboard().text() == "copied later"

    # (b) the mode is not clipboard -- the question sitting on the clipboard is not ours to touch.
    QGuiApplication.clipboard().setText("mine")
    window._probe_reviewer()
    QGuiApplication.clipboard().setText(f"...{_REVIEWER_PROBE_QUESTION}...")
    window._on_reviewer_probed(critic.MODE_API_OR_CLI)
    assert QGuiApplication.clipboard().text() == f"...{_REVIEWER_PROBE_QUESTION}..."


def test_giving_the_clipboard_back_does_not_crash_the_interpreter_on_exit(tmp_path):
    """A QMimeData built in Python and handed to the clipboard is destroyed in QtGui's static
    teardown after Python has finalised: SIGSEGV at exit, code 139 (macOS crash report, 2026-09-13;
    a targeted run of this file died on its way out, the full suite only hid it). In a child
    process, so the crash has a process of its own to take, and through the real helpers: snapshot,
    the probe's overwrite, the restore, a normal exit."""
    import sys
    import textwrap

    script = textwrap.dedent("""
        from types import SimpleNamespace

        from PySide6.QtWidgets import QApplication

        app = QApplication([])

        from autosound_tcc.core import critic
        from autosound_tcc.ui.tcc import main_window

        clipboard = app.clipboard()
        clipboard.setText("mine")
        snapshot = main_window._clipboard_snapshot()
        clipboard.setText("..." + main_window._REVIEWER_PROBE_QUESTION + "...")
        owner = SimpleNamespace(_clipboard_before_probe=snapshot,
                                _reload_model_choices=lambda: None,
                                _refresh_critic_status=lambda: None)
        main_window.MainWindow._on_reviewer_probed(owner, critic.MODE_CLIPBOARD)
        print(clipboard.text())
    """)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}

    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          env=env, cwd=str(tmp_path), timeout=120)

    assert done.returncode == 0, f"exit {done.returncode}: {done.stderr[-2000:]}"
    assert done.stdout.strip().splitlines()[-1] == "mine", "and what was there came back"


def test_an_rta_the_check_does_not_apply_to_is_not_checked_again(monkeypatch):
    """hub #154 §1: its verdict is `ok: false, applicable: false` for good, so treating it as
    unchecked started a capture check on every scan of REW."""
    from autosound_tcc.state import process_view
    from autosound_tcc.ui.tcc import main_window as mw

    _app()
    window = MainWindow()
    monkeypatch.setattr(process_view, "load_state", lambda *a, **k: None)
    monkeypatch.setattr(process_view, "capture_round", lambda *a, **k: {
        "id": "cap_001", "expected": ["sw_1 (rta)"],
        "taken": {"sw_1 (rta)": {"verified": {"ok": False, "applicable": False}}}})
    monkeypatch.setattr(window._meas_panel, "known_titles", lambda: ["sw_1 (rta)"])
    started = []
    monkeypatch.setattr(mw, "_CaptureCheckWorker", lambda *a, **k: started.append(1))

    window._on_rew_titles_changed()

    assert started == []


def _round_check_started(monkeypatch, round_: dict, known: list) -> list:
    """What `_on_rew_titles_changed` hands the capture check, with the round and REW faked."""
    from types import SimpleNamespace

    from autosound_tcc.state import process_view
    from autosound_tcc.ui.tcc import main_window as mw

    _app()
    window = MainWindow()
    monkeypatch.setattr(process_view, "load_state", lambda *a, **k: None)
    monkeypatch.setattr(process_view, "capture_round", lambda *a, **k: round_)
    monkeypatch.setattr(window._meas_panel, "known_titles", lambda: list(known))
    started: list = []

    class _Worker:
        def __init__(self, project_dir, titles=None):
            started.append(titles)
            self.result = SimpleNamespace(connect=lambda *_a: None)
            self.finished = SimpleNamespace(connect=lambda *_a: None)

        def start(self) -> None:
            pass

        def isRunning(self) -> bool:  # noqa: N802 — Qt's name
            return False

        def isFinished(self) -> bool:  # noqa: N802 — Qt's name
            return True

    monkeypatch.setattr(mw, "_CaptureCheckWorker", _Worker)
    window._on_rew_titles_changed()
    window._capture_check = None
    return started


def test_the_after_import_check_asks_only_about_what_the_round_took(monkeypatch):
    """tcc#21, review I3. The method's `check_captures` writes a `taken` entry for EVERY title it
    checks, so checking all expected titles REW shows made them taken: a dud the import window left
    for a re-take read «брак — знятий», and a good sweep nobody ticked turned green (the Arbiter,
    2026-09-06: a title in REW's list is not this project taking it in). Only what the round took
    is checked, and the titles are handed over, not left for the method to fill in."""
    started = _round_check_started(monkeypatch, {
        "id": "cap_001", "expected": ["m-L_1 (sw)", "m-R_1 (sw)", "sw_1 (sw)"],
        "taken": {"m-L_1 (sw)": {"at": "2026-10-03T20:01:00", "planned": True}},
    }, ["m-L_1 (sw)", "m-R_1 (sw)", "sw_1 (sw)"])

    assert started == [["m-L_1 (sw)"]]


def test_an_expected_title_in_rew_that_nobody_took_is_not_checked(monkeypatch):
    started = _round_check_started(monkeypatch, {
        "id": "cap_001", "expected": ["m-L_1 (sw)"], "taken": {},
    }, ["m-L_1 (sw)"])

    assert started == []


def test_the_strip_counts_only_the_titles_the_check_was_handed(monkeypatch):
    """Review I5 (tcc#21): the method's `capture-check` prints a line for EVERY expected title, and
    one it was not handed — not taken, so not checked — prints `UNUSABLE <title> — не перевірено`.
    After an import in a round still waiting for two, the strip said «Непридатних замірів: 2 —
    w-R_1 (sw) — не перевірено» about two captures nobody had taken. A curve not taken is waiting,
    not unusable (the Arbiter, 2026-09-23). Through the real worker, so the titles travel with the
    answer the way they do in the app."""
    from autosound_tcc.core import process_writer
    from autosound_tcc.state import process_view

    _app()
    window = MainWindow()
    monkeypatch.setattr(process_view, "load_state", lambda *a, **k: None)
    monkeypatch.setattr(process_view, "capture_round", lambda *a, **k: {
        "id": "cap_001", "expected": ["w-L_1 (sw)", "w-R_1 (sw)", "sw_1 (sw)"],
        "taken": {"w-L_1 (sw)": {"at": "2026-10-03T20:01:00", "planned": True}}})
    monkeypatch.setattr(window._meas_panel, "known_titles",
                        lambda: ["w-L_1 (sw)", "w-R_1 (sw)", "sw_1 (sw)"])
    # What the method prints for `capture-check w-L_1 (sw)` in that round (process.py's CLI loop).
    monkeypatch.setattr(process_writer, "check_captures", lambda project, titles=None, session=False: (
        "UNUSABLE w-L_1 (sw) — in-band mean -96.1 dB — silence, not a sweep\n"
        "UNUSABLE w-R_1 (sw) — не перевірено\n"
        "UNUSABLE sw_1 (sw) — не перевірено\n"
        "0/3 придатні"))
    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **k: said.append(text))

    window._on_rew_titles_changed()
    window._capture_check.wait(5000)
    _app().processEvents()

    assert said == [i18n.t("unusableSummary").format(
        n=1, first="w-L_1 (sw) — in-band mean -96.1 dB — silence, not a sweep")], said


def test_a_check_asked_for_while_one_runs_is_run_when_that_one_ends(monkeypatch):
    """Review M10 (tcc#21): the ledger write asks for a check of what it just recorded while the
    check the import itself set off is still running. "The next title change re-triggers it" held
    while every check covered every expected title; one covering only what was taken loses the
    rest, which then reads unchecked until something else changes."""
    from types import SimpleNamespace

    from autosound_tcc.state import process_view
    from autosound_tcc.ui.tcc import main_window as mw

    _app()
    window = MainWindow()
    round_ = {"id": "cap_001", "expected": ["w-L_1 (sw)", "w-R_1 (sw)"],
              "taken": {"w-L_1 (sw)": {"at": "x"}}}
    monkeypatch.setattr(process_view, "load_state", lambda *a, **k: None)
    monkeypatch.setattr(process_view, "capture_round", lambda *a, **k: round_)
    monkeypatch.setattr(window._meas_panel, "known_titles", lambda: ["w-L_1 (sw)", "w-R_1 (sw)"])
    started: list = []
    ended: list = []

    class _Worker:
        def __init__(self, project_dir, titles=None):
            started.append(titles)
            self.running = True
            self.result = SimpleNamespace(connect=lambda *_a: None)
            self.finished = SimpleNamespace(connect=ended.append)

        def start(self) -> None:
            pass

        def isRunning(self) -> bool:  # noqa: N802 — Qt's name
            return self.running

        def isFinished(self) -> bool:  # noqa: N802 — Qt's name
            return not self.running

    monkeypatch.setattr(mw, "_CaptureCheckWorker", _Worker)
    try:
        window._on_rew_titles_changed()            # the import's own check: w-L_1
        round_["taken"]["w-R_1 (sw)"] = {"at": "y"}
        window._on_rew_titles_changed()            # the ledger wrote w-R_1: asked while it runs
        assert started == [["w-L_1 (sw)"]]

        window._capture_check.running = False
        for callback in list(ended):
            callback()

        assert started == [["w-L_1 (sw)"], ["w-L_1 (sw)", "w-R_1 (sw)"]]
    finally:
        window._capture_check = None


def test_the_capture_check_worker_hands_the_method_its_titles(monkeypatch, tmp_path):
    """An empty title list is the method's "every expected title" — so the titles go over as given."""
    from autosound_tcc.core import process_writer
    from autosound_tcc.ui.tcc import workers

    asked = []
    monkeypatch.setattr(process_writer, "check_captures",
                        lambda project, titles=None, session=False: asked.append((project, titles))
                        or "")

    workers._CaptureCheckWorker(tmp_path, titles=["m-L_1 (sw)"]).run()

    assert asked == [(tmp_path, ["m-L_1 (sw)"])]


def test_a_session_that_closed_itself_is_not_asked_to_save_on_quit(monkeypatch, tmp_path):
    """TEST-FINDINGS 26: the session wrote everything and closed in order, and quitting still asked
    to spend a turn saving. The close marks it saved; a write after the close takes the mark back."""
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    class _Worker:
        def shutdown(self) -> None:
            pass

    window._agent_worker = _Worker()
    asked: list[bool] = []
    monkeypatch.setattr(window, "_ask_save_before_quit",
                        lambda: (asked.append(True), QMessageBox.StandardButton.Cancel)[1])

    window._bridge.session_closed()
    window._bridge.session_changed()
    event = QCloseEvent()
    window.closeEvent(event)
    assert asked == [True], "a write after the close: there may be something to save again"

    window._bridge.session_closed()
    event = QCloseEvent()
    window.closeEvent(event)
    assert asked == [True], "closed and nothing written since: nothing to ask"


def test_a_close_the_method_took_back_is_asked_about_on_quit(monkeypatch, tmp_path):
    """hub #227 (skill #107): `session-reopen` takes a close back. The session runs it as a shell
    command, past TCC's tools, so nothing tells the window — only the journal says it: a
    `session_reopened` after the last `session_closed` means the session is open again, and a
    quit asks to save as it would have before the close."""
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    class _Worker:
        def shutdown(self) -> None:
            pass

    window._agent_worker = _Worker()
    asked: list[bool] = []
    monkeypatch.setattr(window, "_ask_save_before_quit",
                        lambda: (asked.append(True), QMessageBox.StandardButton.Cancel)[1])
    journal = tmp_path / "process" / "journal.jsonl"
    journal.parent.mkdir(parents=True)

    def _written(*kinds):
        journal.write_text("".join(json.dumps({"at": "2026-10-01T18:00:00+00:00", "type": k}) + "\n"
                                   for k in kinds), encoding="utf-8")

    window._bridge.session_closed()
    _written("session_started", "session_closed", "session_reopened")
    window.closeEvent(QCloseEvent())
    assert asked == [True], "the close was taken back: the session is open again"

    _written("session_started", "session_closed", "session_reopened", "session_closed")
    window.closeEvent(QCloseEvent())
    assert asked == [True], "closed again after the reopening: nothing to ask"


def test_a_window_left_behind_by_a_test_writes_nothing_into_the_next_test_s_folder(
        tmp_path, monkeypatch):
    """TODO F-053: a window left alive by one test resolved the next test's folder through `config`
    and wrote into it — `.tcc/` from its model picker, an emptied capture card from its project
    watcher. Quieted at teardown, it does neither."""
    from PySide6.QtCore import QFileSystemWatcher, QTimer

    from autosound_tcc.core import config
    from tests import _windows

    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.setattr(config, "project_dir", lambda *a, **k: first)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *a, **k: first)
    _app()
    window = MainWindow()
    combo = window._ai_main_combo
    combo.setCurrentIndex(combo.findData("sdk:claude-sonnet-5"))

    _windows.quiet(window)
    monkeypatch.setattr(config, "project_dir", lambda *a, **k: second)  # the next test's folder
    window._on_generator_model_changed(combo.currentIndex())
    window._reload_project_files()

    assert not (second / ".tcc").exists(), "the picker wrote into a folder that is not its test's"
    assert not any(timer.isActive() for timer in window.findChildren(QTimer))
    assert not any(w.files() or w.directories() for w in window.findChildren(QFileSystemWatcher))



def test_message_the_developer_offers_the_form_for_people_without_github(monkeypatch):
    """TODO F-042: the form route was switched off by an empty constant on 27.07, so a person
    without a GitHub account had nowhere to write from the window."""
    from autosound_tcc.core import form_report
    from autosound_tcc.ui.tcc import main_window as mw

    made = []

    class _Dialog:
        def __init__(self, github_url, form_url, parent=None, **kwargs):
            made.append(form_url)

        def exec(self):
            return 0

    monkeypatch.setattr(mw, "FeedbackDialog", _Dialog)
    _app()
    window = MainWindow()

    window._open_feedback()

    assert made == [form_report.post_url()]


def test_a_project_with_no_ledger_offers_the_route_to_the_first_snapshot(tmp_path, monkeypatch):
    """A copied car has a profile and no ledger, and the panel has to say where the step lives.

    Found live (`#43`): a project made through Copy car has no `state/` at all -- `project_seed.py`
    carries system parameters and never the tune -- so `ui.preset` stays `null` and the settings
    sheet cannot be produced, because `apply.propose` needs a ledger history. The note explained
    the empty VALUES and said nothing about the sheet, and the only route to a first snapshot in
    the window was buried inside the Resonalyze import dialog. The Arbiter, verbatim: "why can't I
    call up the Load form?"

    The banking itself stays behind the method's gate -- the button writes a request into the
    composer, the same path the Resonalyze rows take, and nothing is recorded behind the Arbiter.
    """
    profile = {
        "dsp_profile": {
            "name": "Helix DSP Ultra S", "vendor": "Audiotec-Fischer",
            "groups": [{"id": "physical_outputs", "label": "Output channels",
                        "fields": ["hp", "lp", "gain_db"]}],
        }
    }
    (tmp_path / "dsp_profile.json").write_text(json.dumps(profile))
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path / "state"))  # never written

    _app()
    window = MainWindow()

    # Said: the missing sheet is named, not only the missing values.
    assert i18n.t("leftNoLedgerSheet") in window._left_status.text()
    # And offered: the route is a button on the panel, not knowledge of another dialog.
    assert not window._bank_first_btn.isHidden()

    window._bank_first_btn.click()

    composed = window._dialog._input.text()
    assert i18n.t("leftBankFirst") not in composed  # the label is not the request
    assert "FULL" in composed  # the method's default name for a first preset
    assert composed.startswith(i18n.t("leftBankFirstAsk").split("{")[0][:40])


def test_quitting_also_lets_go_of_the_ping_the_contract_check_and_the_capture_check():
    """The same rule, for the three workers in `stop_workers` that only WAITED (finding 35).

    The block's own comment says it: "Qt destroying a still-running QThread is a `qFatal`, which
    aborts the process". The answer written under it was a bounded wait — and a wait is not the
    guard. A worker that outlasts it is left in the attribute, the attribute dies with the window,
    and the destructor runs against a running thread. Probed on 2026-09-20: dropping the last
    reference to a running worker aborts the process with exit 134, and the destructor runs on the
    WORKER's own thread as `run()` unwinds, which is exactly the stack in the crash report.

    The contract check keeps its `cancel()` — killing the child is the only lever that reaches a
    thread blocked reading it — and the hand-over is what covers the case where even that does not
    land in time.
    """
    from PySide6.QtCore import QObject, Signal

    from autosound_tcc.ui.tcc import qt_shutdown

    class _Stuck(QObject):
        finished = Signal()
        cancelled = False

        def isRunning(self) -> bool:  # noqa: N802 (QThread's name)
            return True

        def requestInterruption(self) -> None:  # noqa: N802 (QThread's name)
            pass

        def wait(self, _ms: int = 0) -> bool:
            return False

        def cancel(self) -> None:
            self.cancelled = True

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    ping, contract, check = _Stuck(), _Stuck(), _Stuck()
    window._rew_ping, window._contract_worker, window._capture_check = ping, contract, check
    try:
        window.stop_workers()
        detached = qt_shutdown.detached()
    finally:
        window._rew_ping = window._contract_worker = window._capture_check = None
        for worker in (ping, contract, check):
            qt_shutdown._DETACHED.discard(worker)

    assert ping in detached, "the REW ping"
    assert contract in detached, "the contract check"
    assert check in detached, "the capture check"
    assert contract.cancelled, "and the child is still killed first — that is the lever"


def test_both_routes_are_given_the_project_language(monkeypatch, tmp_path):
    """tcc#56, finding 53. «TypeError: OmpSession.__init__() got an unexpected keyword argument
    'language'» on every omp start: the language (wave 2.1, 2026-09-11) was put into the omp
    factory, and the SDK factory beside it — the one it was meant for — never got it, so the SDK
    session's prompt said the project's language was English."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    server = SimpleNamespace(project_dir=tmp_path, url="http://127.0.0.1:1/mcp", token="t")
    was = i18n.current_language()
    i18n.set_language("uk")
    try:
        for harness in ("omp", "sdk"):
            choice = SimpleNamespace(harness=harness, model="some-model")
            session = window._session_factory(choice, server, resumed=False, effort=None)()
            assert session.language == "uk", harness
    finally:
        i18n.set_language(was)


def test_a_session_that_never_started_is_not_asked_to_save_before_the_swap(monkeypatch):
    """tcc#56, finding 54: omp died in its constructor, the worker's thread ended, and switching
    the model still said «Зберігаю стан проєкту перед зміною моделі…» and sent the save turn to a
    thread that would never read it — then waited the handoff's timeout out."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-opus-5"))
    window._running_model = "sdk:claude-opus-5"
    worker = _HandoffWorker()
    worker.finished = True
    window._agent_worker = worker
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-sonnet-5"))
    launched, said = [], []
    monkeypatch.setattr(MainWindow, "_launch_session", lambda self, *a, **kw: launched.append(True))
    monkeypatch.setattr(window._dialog, "_add_system_message", lambda text, *a, **kw: said.append(text))

    window._start_tuning_session()

    assert worker.sent == [], "nothing to ask a session that is not there"
    assert i18n.t("sessionHandoff") not in said
    assert launched == [True], "the new model starts at once"
    assert getattr(window, "_handoff_timer", None) is None



# ---- the reviewer picker's own three colours, and the params following it (tcc#58) --------------

def _reviewer_window(monkeypatch, *entries):
    from autosound_tcc.core import availability, model_choices

    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    window._critic_choices = list(entries)
    MainWindow._fill_combo(window._ai_critic_combo, list(entries), entries[0].key, critic=True)
    # And the registry, which every refill reads: with only the picker faked, a refill while the
    # test pumps events found the stored pick gone and opened «model gone» (the #140 flake's
    # carrier, re-review of fix round 2 of #21).
    monkeypatch.setattr(model_choices, "critic_choices", lambda active_omp: list(entries))
    availability.reset()
    return window


def test_the_reviewer_picker_is_grey_until_known_green_once_it_answered_red_when_refused(monkeypatch):
    """Finding 55, the Arbiter's proposal: the picker's own three colours — grey, not known yet;
    green, it works; red, it does not."""
    from autosound_tcc.core import availability, model_choices

    pro = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro")
    window = _reviewer_window(monkeypatch, pro)
    combo = window._ai_critic_combo
    try:
        window._refresh_critic_status()
        assert not {"is-ok", "is-missing", "is-warn"} & set(str(combo.property("class")).split())

        availability.succeeded(pro.key)
        window._refresh_critic_status()
        assert "is-ok" in str(combo.property("class"))

        availability.refused(pro.key, availability.LOCATION, "selected location")
        window._refresh_critic_status()
        assert "is-missing" in str(combo.property("class"))
        assert "is-ok" not in str(combo.property("class"))
    finally:
        availability.reset()


def test_the_status_is_red_when_the_last_review_came_from_another_model(monkeypatch):
    """Finding 55: «gemini-3.8-flash-medium · 6 d ago» with a red «!» beside a picker holding
    another model. The Arbiter: if the red belongs to the status, let the status be red."""
    from autosound_tcc.core import availability, critic, model_choices

    pro = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro")
    window = _reviewer_window(monkeypatch, pro)
    try:
        critic.log_call(critic.CriticResult(critic.MODE_API_OR_CLI, "ok", "gemini-3.8-flash-medium",
                                            "critic", "", 1.0, "2026-09-20T00:00:00+00:00"), None)
        window._refresh_critic_status()
        assert "kv-warn" in str(window._critic_status.property("class"))

        critic.log_call(critic.CriticResult(critic.MODE_API_OR_CLI, "ok", "gemini-3.1-pro-high",
                                            "critic", "", 1.0, "2026-09-21T00:00:00+00:00"), None)
        window._refresh_critic_status()
        assert "kv-warn" not in str(window._critic_status.property("class"))
    finally:
        availability.reset()


def test_a_model_not_checked_yet_is_grey_in_the_list_not_red(monkeypatch):
    """Finding 62: after one cut-off call every row went red, Anthropic's too, then black again —
    the one state that paints every row at once is "not checked yet" while the catalogues are
    read. Not known is not broken: grey, with its word."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QComboBox

    from autosound_tcc.core import availability, model_choices
    from autosound_tcc.ui.tcc.theme import current_theme

    _app()
    combo = QComboBox()
    sdk = model_choices.Choice(harness="sdk", model="claude-opus-5", label="Opus 5",
                               provider="anthropic")
    availability.reset()
    availability.begin_reading(["sdk"])
    try:
        MainWindow._fill_combo(combo, [sdk], sdk.key, critic=True)
    finally:
        availability.reset()
    assert combo.itemData(0, Qt.ItemDataRole.ForegroundRole) != QColor(current_theme().warn)


def test_picking_a_reviewer_puts_it_in_the_project_params_at_once(monkeypatch):
    """Finding 59: the footer read one critic, «PROJECT PARAMS» another. The Generator, the effort
    and the gate refreshed the panel; the reviewer did not."""
    from autosound_tcc.core import model_choices

    pro = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro")
    flash = model_choices.Choice(harness="agy", model="gemini-3.1-flash", label="Gemini 3.1 Flash")
    window = _reviewer_window(monkeypatch, pro, flash)
    refreshed = []
    monkeypatch.setattr(window, "_set_project_params", lambda view: refreshed.append(view))

    window._ai_critic_combo.setCurrentIndex(window._ai_critic_combo.findData(flash.key))
    QApplication.processEvents()

    assert refreshed, "the panel names the reviewer, so it must not lag the picker"


def test_a_picker_refill_after_a_pick_keeps_it_without_asking(monkeypatch):
    """Re-review of fix round 2 (#21), on the #140 flake: `_reviewer_window` filled the window's
    picker and not the registry, so a refill while a test pumped events — a catalogue answer, a
    probe's, a late one from an earlier test's window — found the stored pick gone and opened
    «model gone». The registry holds what the picker holds; a refill asks nothing."""
    from autosound_tcc.core import model_choices

    pro = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro")
    flash = model_choices.Choice(harness="agy", model="gemini-3.1-flash", label="Gemini 3.1 Flash")
    window = _reviewer_window(monkeypatch, pro, flash)
    window._ai_critic_combo.setCurrentIndex(window._ai_critic_combo.findData(flash.key))
    QApplication.processEvents()

    window._reload_model_choices()

    assert window._ai_critic_combo.currentData() == flash.key


def test_a_running_session_is_told_the_reviewer_changed(monkeypatch):
    """Finding 59: the Generator named a third reviewer — the one its shell was started with. A
    live session learns of the change through the signal queue, and the dialog says it waits."""
    from autosound_tcc.core import model_choices, signal_bus

    pro = model_choices.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro")
    flash = model_choices.Choice(harness="omp", model="google-antigravity/gemini-3.5-flash-lite",
                                 label="Gemini 3.5 Flash Lite")
    window = _reviewer_window(monkeypatch, pro, flash)
    bus = signal_bus.SignalBus()
    window._mcp_server = SimpleNamespace(bus=bus, project_dir=None)
    worker = _HandoffWorker()
    worker.isRunning = lambda: True
    window._agent_worker = worker
    said = []
    monkeypatch.setattr(window._dialog, "_add_system_message", lambda text, *a, **kw: said.append(text))

    window._ai_critic_combo.setCurrentIndex(window._ai_critic_combo.findData(flash.key))

    sent = [s for s in bus.deliver() if s.kind == signal_bus.REVIEWER]
    # omp's full selector since tcc#74: an OMP pick goes through omp, which reads it.
    assert sent and sent[0].payload["model"] == "google-antigravity/gemini-3.5-flash-lite"
    assert any("Gemini 3.5 Flash Lite" in text for text in said)
    window._mcp_server = None
    window._agent_worker = None


def test_the_theme_button_is_its_icon_alone():
    """Finding 50 (tcc#65): «◐ theme» — the icon alone is enough; the word is the hover."""
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    assert window._theme_btn.text() == "◐"
    assert window._theme_btn.toolTip() == i18n.t("theme")


def test_a_state_whose_file_and_version_disagree_is_said_in_the_header_and_the_strip():
    """tcc#50: the header read the file's field, the comparison the file's name, and nothing on
    screen said they disagreed."""
    from autosound_tcc.state.dsp_state import ProjectView

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    view = ProjectView(preset="FULL", sample_rate=None, groups=(), version="v_012",
                       file_version="v_011")
    window._show_version(view, {"dsp_profile": {"vendor": "X", "name": "Y"}})

    said = i18n.t("stateVersionMismatch").format(file="v_011", inner="v_012")
    assert window._status_strip.text() == said


def test_a_state_file_the_method_refuses_by_its_version_is_said_in_the_arbiter_s_language(
        tmp_path, monkeypatch):
    """tcc#50 under method v3.0.64 (skill #89, tcc#95): the method now refuses a file whose
    `version` field names another, and the window showed that refusal bare -- English, absolute
    paths, a shell command, and nothing a language switch would re-say. The Arbiter's line comes
    first, in his language, with the method's sentence under it for a report; the header names
    both versions as the tcc#50 warning did."""
    from pathlib import Path

    from autosound_tcc.core import vendor_loader

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("AUTOSOUND_STATE_ROOT", raising=False)
    monkeypatch.delenv("AUTOSOUND_TCC_PRESET", raising=False)
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    _intake.seed(tmp_path)
    history = vendor_loader.load_dsp_state().PresetHistory(
        str(tmp_path / "state"), "FULL", project_dir=str(tmp_path))
    head = history.head()
    path = Path(history._path(head))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = "v_012"
    path.write_text(json.dumps(data), encoding="utf-8")

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)

    def shown() -> tuple[str, str]:
        text = window._left_status.text().replace("​", "")
        head_line, _, under = text.partition("\n\n")
        return head_line, under

    try:
        window._on_language_selected("uk")
        line, under = shown()
        assert line == i18n.t("stateVersionRefused").format(file=head, inner="v_012")
        assert "назва і вміст розходяться" in line
        assert f"repair-version {head}" in under and "'v_012'" in under, under
        assert window._dsp_section.sub_text() == f"{head} ≠ v_012"

        window._on_language_selected("en")
        line, under = shown()
        assert line == i18n.t("stateVersionRefused").format(file=head, inner="v_012")
        assert "its name and its content disagree" in line
        assert f"repair-version {head}" in under
        assert window._dsp_section.sub_text() == f"{head} ≠ v_012", "a switch keeps both names"
    finally:
        window._on_language_selected("en")


def _a_refused_state(tmp_path, monkeypatch):
    """A seeded project whose HEAD snapshot's `version` field names another (`v_012`), which the
    method refuses; returns the HEAD's name, the file, and its original content for a repair."""
    from pathlib import Path

    from autosound_tcc.core import vendor_loader

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("AUTOSOUND_STATE_ROOT", raising=False)
    monkeypatch.delenv("AUTOSOUND_TCC_PRESET", raising=False)
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    _intake.seed(tmp_path)
    history = vendor_loader.load_dsp_state().PresetHistory(
        str(tmp_path / "state"), "FULL", project_dir=str(tmp_path))
    head = history.head()
    path = Path(history._path(head))
    original = path.read_text(encoding="utf-8")
    data = json.loads(original)
    data["version"] = "v_012"
    path.write_text(json.dumps(data), encoding="utf-8")
    return head, path, original


def test_the_refused_version_s_hover_is_there_on_first_show_not_after_a_switch(
        tmp_path, monkeypatch):
    """Final W-4 review (tcc#95): the refusal set the header's hover and then its sub, and the
    elided sub resets a native tip it does not need -- so the hover was empty until a language
    switch put it back."""
    head, _path, _original = _a_refused_state(tmp_path, monkeypatch)
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)

    line = i18n.t("stateVersionRefused").format(file=head, inner="v_012")
    assert window._dsp_section.sub_text() == f"{head} ≠ v_012"
    assert window._dsp_section._sub_label.toolTip() == line
    assert window._dsp_section._dot.toolTip() == line


def test_a_repaired_file_s_version_keeps_its_hover_through_a_language_switch(
        tmp_path, monkeypatch):
    """Final W-4 review (tcc#95): the refusal's `again` stayed kept after a repaired file loaded,
    and the next language switch re-said the refusal over the good version's hover."""
    head, path, original = _a_refused_state(tmp_path, monkeypatch)
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    header_tip = window._dsp_section._sub_label.toolTip
    assert window._dsp_section.sub_text() == f"{head} ≠ v_012", "refused first"

    path.write_text(original, encoding="utf-8")
    window._load_project()
    good = header_tip()
    assert head in good, good
    assert good != i18n.t("stateVersionRefused").format(file=head, inner="v_012")

    try:
        window._on_language_selected("uk")
        tip = header_tip()
        assert tip != i18n.t("stateVersionRefused").format(file=head, inner="v_012"), tip
        assert head in tip, tip
        window._on_language_selected("en")
        assert header_tip() == good, "the switch put back the good version's hover"
    finally:
        window._on_language_selected("en")


def test_the_eq_card_order_is_a_setting_the_processor_s_by_default(monkeypatch):
    """Finding 70 (tcc#67): the field order as a TCC setting, not only the vendor's rule (68)."""
    from autosound_tcc.ui.tcc import main_window as mw

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    window._eq_order_vendor = ("freq", "gain", "q")  # a Helix
    try:
        window._set_eq_order_pref("q_first")
        assert window._detail._eq_order == ("freq", "q", "gain")
        assert window._eq_order_actions["q_first"].isChecked()

        window._set_eq_order_pref("auto")
        assert window._detail._eq_order == ("freq", "gain", "q"), "back to the processor's"
    finally:
        mw.get_settings().remove(mw._EQ_ORDER_KEY)


def test_a_red_pick_does_not_paint_every_row_of_its_list_red():
    """Findings 62, 76 (tcc#58): after one refused reviewer every row of the open list was red,
    Claude's too. The combo's own delegate drew the rows with the combo's palette, so the pick's red
    filled the list and a row's own red was never drawn. Measured on the pixels of each row."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor

    from autosound_tcc.ui.tcc.theme import current_theme

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    combo = window._ai_critic_combo
    combo.clear()
    for text in ("SDK · Claude Opus 5", "AGY · Gemini 3.8 Flash (High)", "OMP · GPT-OSS 120B"):
        combo.addItem(text)
    combo.setItemData(2, QColor(current_theme().warn), Qt.ItemDataRole.ForegroundRole)
    combo.setProperty("class", "mini-select is-missing")
    combo.style().unpolish(combo)
    combo.style().polish(combo)
    combo.resize(360, 30)
    combo.show()
    combo.showPopup()
    QApplication.processEvents()
    try:
        view = combo.view()
        image = view.grab().toImage()

        def red(row):
            rect = view.visualRect(view.model().index(row, 0))
            count = 0
            for x in range(rect.left(), min(rect.right(), image.width() - 1), 2):
                for y in range(rect.top(), min(rect.bottom(), image.height() - 1), 2):
                    c = QColor(image.pixel(x, y))
                    count += c.red() > 150 and c.green() < 110 and c.blue() < 110
            return count

        refused = red(2)
        assert refused > 0, "the refused row keeps its own red"
        # Relative, not zero: the fault painted EVERY row as red as the refused one. Linux CI
        # finds ~5 red samples in the current row (against ~75 in the refused one) that macOS and
        # Windows do not — a platform's current-row mark, not a row painted red (the wave's PR,
        # 2026-09-27).
        assert red(0) * 4 < refused and red(1) * 4 < refused, (
            f"rows that work are not red: {red(0)}, {red(1)} against {refused}")
    finally:
        combo.hidePopup()
        combo.hide()



def test_a_session_whose_model_never_spoke_is_not_asked_to_save(monkeypatch):
    """Finding 77 (tcc#56): omp refused the prompt (no kimi-code key) and stayed up; switching the
    model sent it «save state» anyway. A model that has not said a word has nothing to write down."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-opus-5"))
    window._running_model = "sdk:claude-opus-5"
    worker = _HandoffWorker()
    worker.spoke = False
    window._agent_worker = worker
    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-sonnet-5"))
    launched, said = [], []
    monkeypatch.setattr(MainWindow, "_launch_session", lambda self, *a, **kw: launched.append(True))
    monkeypatch.setattr(window._dialog, "_add_system_message", lambda text, *a, **kw: said.append(text))

    window._start_tuning_session()

    assert worker.sent == [] and i18n.t("sessionHandoff") not in said
    assert worker.shutdowns == 1, "the silent session is closed, not left running"
    assert launched == [True]


def test_a_worker_stuck_in_its_turn_is_handed_over_not_left_for_qt_to_destroy():
    """Finding 81 (tcc#73): quitting with an omp session hung in a tool ended in SIGABRT —
    `shutdown()` came back False, nobody looked, and Qt destroyed the running QThread at exit."""
    import threading

    from PySide6.QtCore import QThread

    from autosound_tcc.ui.tcc import qt_shutdown

    release = threading.Event()

    class _Stuck(QThread):
        session = None

        def run(self):
            release.wait(10)

        def shutdown(self, *a, **kw):
            return False

    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    worker = _Stuck()
    worker.start()
    window._agent_worker = worker
    try:
        window._stop_agent_worker()
        assert worker in qt_shutdown.detached(), "handed over, so the exit path does not destroy it"
    finally:
        release.set()
        worker.wait(5000)
        window._agent_worker = None


def test_the_models_window_is_modal_to_tcc_not_to_every_app(monkeypatch):
    """Finding 79 (tcc#71): an application-modal dialog sits above every app's windows on macOS,
    so the terminal «Налаштувати omp…» opens came up behind it. Window-modal, and what it
    answers is taken when it closes."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog

    from autosound_tcc.ui.tcc import main_window as mw

    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    reloaded = []
    monkeypatch.setattr(window, "_reload_after_model_config", lambda: reloaded.append(True))
    window._open_model_config()
    dialog = window._model_config_dialog
    try:
        assert dialog.windowModality() == Qt.WindowModality.WindowModal
        dialog.active = ["google/gemini-3.1-pro-preview"]
        dialog.done(QDialog.DialogCode.Accepted)
        QApplication.processEvents()
        assert window._settings.value(mw._ACTIVE_OMP_KEY) == "google/gemini-3.1-pro-preview"
        assert reloaded == [True]
    finally:
        window._settings.remove(mw._ACTIVE_OMP_KEY)


def test_an_omp_row_is_greyed_in_the_reviewer_picker_with_why_and_stays_if_picked(monkeypatch):
    """tcc#74: an OMP pick goes through omp only, and the reviewer script has no omp route yet. The
    row says so and cannot be picked — and one that IS the current pick stays selected, as every
    other row that cannot run does."""
    from autosound_tcc.core import critic
    from autosound_tcc.core import model_choices as mc
    from autosound_tcc.ui.tcc import i18n
    from PySide6.QtWidgets import QComboBox

    monkeypatch.setattr(critic, "omp_route_available", lambda: False)  # a method before v3.0.63
    _app()
    combo = QComboBox()
    omp = mc.Choice(harness="omp", model="google-antigravity/gemini-3.1-pro-high",
                    label="Gemini 3.1 Pro (High)", provider="google-antigravity")
    pro = mc.Choice(harness="api", model="gemini-pro-latest", label="gemini-pro-latest",
                    provider="google")

    MainWindow._fill_combo(combo, [omp, pro], omp.key, critic=True)

    rows = {combo.itemData(i): i for i in range(combo.count())}
    model = combo.model()
    assert i18n.t("criticRowViaOmp") in combo.itemText(rows[omp.key])
    assert not model.item(rows[omp.key]).isEnabled()
    assert model.item(rows[pro.key]).isEnabled()
    assert combo.currentData() == omp.key, "the current pick is not moved"

    # In the generator's picker the same OMP row is an ordinary one.
    MainWindow._fill_combo(combo, [omp], omp.key)
    assert combo.model().item(0).isEnabled()


def test_a_flash_row_can_be_picked_as_the_reviewer_and_says_not_recommended(monkeypatch):
    """Finding 129 (tcc#118), the Arbiter: «"не рекомендується" це одна справа, але вибрати — хай
    користувач вирішує». tcc#74 greyed the Flash rows; now they are picked like any other, with
    «не рекомендується» on the row and the method's reason on hover. OMP and self stay refusals."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox

    from autosound_tcc.core import critic
    from autosound_tcc.core import model_choices as mc
    from autosound_tcc.ui.tcc import i18n

    monkeypatch.setattr(critic, "omp_route_available", lambda: False)  # a method before v3.0.63
    _app()
    combo = QComboBox()
    omp = mc.Choice(harness="omp", model="google-antigravity/gemini-3.1-pro-high",
                    label="Gemini 3.1 Pro (High)", provider="google-antigravity")
    flash = mc.Choice(harness="agy", model="gemini-3.8-flash-low",
                      label="Gemini 3.8 Flash (Low)", provider="google")
    pro = mc.Choice(harness="api", model="gemini-pro-latest", label="gemini-pro-latest",
                    provider="google")
    own = mc.Choice(harness="sdk", model="claude-opus-5", label="Opus 5", provider="anthropic")

    MainWindow._fill_combo(combo, [omp, flash, pro, own], flash.key, critic=True, generator=own)

    rows = {combo.itemData(i): i for i in range(combo.count())}
    model = combo.model()
    assert model.item(rows[flash.key]).isEnabled(), "a Flash reviewer is the Arbiter's call"
    assert i18n.t("criticRowNotRecommended") in combo.itemText(rows[flash.key])
    assert i18n.t("criticNotFlashTip") in combo.itemData(rows[flash.key],
                                                         Qt.ItemDataRole.ToolTipRole)
    assert i18n.t("criticRowNotRecommended") not in combo.itemText(rows[pro.key])
    assert not model.item(rows[omp.key]).isEnabled()
    assert not model.item(rows[own.key]).isEnabled()
    assert combo.currentData() == flash.key


def test_a_flash_reviewer_pick_keeps_its_warning_beside_the_picker(monkeypatch):
    """Finding 129 (tcc#118): a Flash pick is allowed, and the «!» beside the picker still says it
    is not recommended — a warning, not a refusal (tcc#74 called it «не для рецензента»)."""
    from autosound_tcc.core import model_choices as mc
    from autosound_tcc.ui.tcc import i18n

    monkeypatch.setattr(mc, "critic_reaches", lambda choice: True)
    flash = mc.Choice(harness="agy", model="gemini-3.8-flash-low",
                      label="Gemini 3.8 Flash (Low)", provider="google")
    pro = mc.Choice(harness="agy", model="gemini-3.1-pro-high", label="Gemini 3.1 Pro")
    window = _reviewer_window(monkeypatch, flash, pro)
    monkeypatch.setattr(window, "_generator_choice", lambda: None)

    pairs, hard = window._critic_notes()

    assert (i18n.t("criticRowNotRecommended"), i18n.t("criticNotFlashTip")) in pairs
    assert hard is False, "a Flash pick reviews; the mark is the soft one"


def test_picking_another_reviewer_checks_it_at_once(monkeypatch):
    """The Arbiter: «було б добре з'ясовувати це до запуску» (tcc#74). A new pick is asked at once,
    and one picked while a check is running is asked when that one ends."""
    _app()
    window = MainWindow()
    asked = []
    monkeypatch.setattr(window, "_probe_reviewer", lambda: asked.append(True))
    combo = window._ai_critic_combo
    keys = [combo.itemData(i) for i in range(combo.count())
            if combo.model().item(i).isEnabled() and combo.itemData(i)]
    assert len(keys) >= 2
    current = combo.currentData()
    other = next(k for k in keys if k != current)
    combo.setCurrentIndex(combo.findData(other))

    assert asked, "a changed pick is checked before any session"


def test_the_dialog_names_the_generator_with_its_route():
    """Finding 90 (tcc#80): «Генератор без признаку що то ОМР» — the dialog said «Запускаю Claude
    Opus 5» and GENERATOR · CLAUDE OPUS 5 on the omp route. It says the route as the picker does."""
    from autosound_tcc.core import model_choices as mc
    from autosound_tcc.ui.tcc.main_window import _session_title

    omp = mc.Choice(harness="omp", model="anthropic/claude-opus-5", label="Claude Opus 5")
    assert _session_title(omp) == "OMP · Claude Opus 5"


def test_a_new_reviewer_that_answered_its_check_is_what_the_status_names(monkeypatch):
    """Finding 92 (tcc#82): the pick went green and beside it stayed «! gpt-5.6-terra · 2 h ago»
    in red — the previous reviewer's last review. Once the pick has answered its check, the status
    names it, not someone else's review from hours ago."""
    from autosound_tcc.core import availability, critic

    _app()
    window = MainWindow()
    combo = window._ai_critic_combo
    key = "api:gemini-pro-latest"
    combo.setCurrentIndex(combo.findData(key))
    monkeypatch.setattr(critic, "last_call", lambda _p=None: {
        "model": "gpt-5.6-terra", "at": "2026-09-27T08:00:00+00:00", "mode": "answered"})
    availability.succeeded(key)
    try:
        window._refresh_critic_status()
        text = window._critic_status.text()
        assert "gemini-pro-latest" in text and "gpt-5.6-terra" not in text, text
        assert "kv-warn" not in str(window._critic_status.property("class"))
    finally:
        availability.reset()


def test_a_bold_row_is_measured_in_bold_so_its_note_is_not_cut():
    """Finding 95 (tcc#84): «OMP · Gemini 3.1 Pro · через …— з наступним оновленням методу» — the
    recommended row is bold and wider than the regular font it was measured in, so it alone came
    back cut in the middle."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontMetrics

    from autosound_tcc.ui.tcc.theme import mini_combo

    _app()
    combo = mini_combo()
    text = "OMP · Gemini 3.1 Pro  ·  через omp — з наступним оновленням методу"
    combo.addItem(text, "a")
    combo.addItem("SDK · Claude Opus 5", "b")
    bold = combo.font()
    bold.setBold(True)
    # Twice the size too: offscreen, bold and regular can measure the same, and the rule under
    # test is "each row in its own font", whatever makes it wider.
    bold.setPointSizeF(combo.font().pointSizeF() * 2)
    combo.setItemData(0, bold, Qt.ItemDataRole.FontRole)
    combo.setFixedWidth(60)

    combo.showPopup()
    combo.hidePopup()

    assert combo.view().minimumWidth() >= QFontMetrics(bold).horizontalAdvance(text)


def test_the_title_names_the_projects_own_method_when_it_is_another(monkeypatch):
    """Finding 94 (tcc#83): the title said «skill 3.0.62» while the project ran its own 3.0.61."""
    from autosound_tcc.core import install_report

    _app()
    window = MainWindow()
    monkeypatch.setattr(install_report, "skill_version", lambda: "3.0.62")
    monkeypatch.setattr(install_report, "project_method_version", lambda _p: "3.0.61")
    window._set_title()
    assert "skill 3.0.62" in window.windowTitle() and "project 3.0.61" in window.windowTitle()

    monkeypatch.setattr(install_report, "project_method_version", lambda _p: "3.0.62")
    window._set_title()
    assert "project 3.0" not in window.windowTitle(), "the same method is said once"


def test_the_generators_own_model_is_greyed_in_the_reviewer_list_and_follows_the_generator(
        monkeypatch):
    """Finding 99 (tcc#85): «OMP · Claude Opus 5» reviewing a Claude Opus 5 session hung twice."""
    from autosound_tcc.core import critic
    from autosound_tcc.core import model_choices as mc
    from autosound_tcc.ui.tcc import i18n
    from PySide6.QtWidgets import QComboBox

    monkeypatch.setattr(critic, "omp_route_available", lambda: True)
    _app()
    combo = QComboBox()
    opus = mc.Choice(harness="omp", model="anthropic/claude-opus-5", label="Claude Opus 5")
    sonnet = mc.Choice(harness="omp", model="anthropic/claude-sonnet-5", label="Claude Sonnet 5")

    MainWindow._fill_combo(combo, [opus, sonnet], sonnet.key, critic=True, generator=opus)

    assert i18n.t("criticRowSelf") in combo.itemText(combo.findData(opus.key))
    assert not combo.model().item(combo.findData(opus.key)).isEnabled()
    assert combo.model().item(combo.findData(sonnet.key)).isEnabled()


def test_the_reviewer_marks_a_warning_yellow_and_an_answered_row_green(monkeypatch):
    """Findings 100 and 101 (tcc#86): «зроби жовтим не червоним» — the same-vendor «!» is a warning,
    not a refusal; and «покрасити зеленим ті моделі що запрацювали» in the list."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox

    from autosound_tcc.core import availability, critic
    from autosound_tcc.core import model_choices as mc
    from autosound_tcc.ui.tcc.theme import current_theme

    monkeypatch.setattr(critic, "omp_route_available", lambda: True)
    _app()
    combo = QComboBox()
    sonnet = mc.Choice(harness="omp", model="anthropic/claude-sonnet-5", label="Claude Sonnet 5")
    availability.succeeded(sonnet.key)
    try:
        MainWindow._fill_combo(combo, [sonnet], sonnet.key, critic=True)
        colour = combo.itemData(0, Qt.ItemDataRole.ForegroundRole)
        assert colour is not None and colour.name().lower() == current_theme().ok.lower()
    finally:
        availability.reset()

    window = MainWindow()
    monkeypatch.setattr(window, "_critic_notes", lambda: ([("same vendor", "tip")], False))
    window._refresh_critic_warning()
    assert "warn-mark-soft" in str(window._critic_warn.property("class"))
    monkeypatch.setattr(window, "_critic_notes", lambda: ([("clipboard only", "tip")], True))
    window._refresh_critic_warning()
    assert "warn-mark-soft" not in str(window._critic_warn.property("class"))


def test_a_banked_change_read_from_disk_shows_no_time_and_one_banked_now_does(monkeypatch, tmp_path):
    """tcc#100: the time on a message is when it was said. The banked-change card a project opens
    on is a record read from `proposals/<v>.json` — banked yesterday, maybe — and it came up as
    «SYSTEM · LEDGER 09:14:02», the moment TCC was opened. That card shows no time; a version
    banked while the window watches is news, and says when it arrived."""
    import time

    from autosound_tcc.state import proposal_view

    _app()
    window = MainWindow()
    monkeypatch.setattr(proposal_view, "load_delta",
                        lambda version, preset, project_dir=None: {"version": version})
    monkeypatch.setattr(proposal_view, "to_html", lambda delta: f"{delta['version']} banked")
    now = 1_790_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    before = len(window._dialog._bubbles)

    window._show_banked_delta("v_904", "tune", tmp_path)   # the project opens on v_904
    window._show_banked_delta("v_905", "tune", tmp_path)   # v_905 is banked mid-session
    window._show_banked_delta("v_302", "other", tmp_path)  # another preset opens on v_302

    opened, banked, switched = window._dialog._bubbles[before:]
    assert "v_904" in opened.plain_text() and "v_905" in banked.plain_text()
    for from_disk in (opened, switched):
        assert from_disk._time_label.isHidden() and not from_disk._time_label.text()
    assert banked._time_label.text() == time.strftime("%H:%M:%S", time.localtime(now))


def test_a_same_name_version_of_another_preset_gets_its_card_and_the_next_bank_its_time(
        monkeypatch, tmp_path):
    """tcc#123 (W-4 review of tcc#100): the card was remembered by its version NAME alone, and the
    early return came before the window noted which preset it was on. A switch to another preset
    standing on the same `v_003` drew no card; the bank that followed on that preset was then
    compared with the preset before the switch, and read as one opened from disk -- no time."""
    import time

    from autosound_tcc.state import proposal_view

    _app()
    window = MainWindow()
    monkeypatch.setattr(proposal_view, "load_delta",
                        lambda version, preset, project_dir=None: {"version": f"{preset}/{version}"})
    monkeypatch.setattr(proposal_view, "to_html", lambda delta: f"{delta['version']} banked")
    monkeypatch.setattr(proposal_view, "delta_path",
                        lambda version, preset, project_dir=None: tmp_path / f"{preset}-{version}")
    for name in ("tune-v_003", "other-v_003", "other-v_004"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    now = 1_790_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    before = len(window._dialog._bubbles)

    window._show_banked_delta("v_003", "tune", tmp_path)   # the project opens on tune's v_003
    window._show_banked_delta("v_003", "other", tmp_path)  # a switch to other, also on v_003
    window._show_banked_delta("v_003", "other", tmp_path)  # the watcher fires again: no repeat
    window._show_banked_delta("v_004", "other", tmp_path)  # v_004 is banked on other

    cards = window._dialog._bubbles[before:]
    assert len(cards) == 3, [card.plain_text() for card in cards]
    for card, said in zip(cards, ("tune/v_003", "other/v_003", "other/v_004")):
        assert said in card.plain_text()
    switched, banked = cards[1], cards[2]
    assert switched._time_label.isHidden() and not switched._time_label.text()
    assert banked._time_label.text() == time.strftime("%H:%M:%S", time.localtime(now))

    # The same version written again -- a bank redone under its name -- is a new card.
    os.utime(tmp_path / "other-v_004", (1_700_000_000, 1_700_000_000))
    window._show_banked_delta("v_004", "other", tmp_path)
    assert len(window._dialog._bubbles[before:]) == 4


def test_the_footer_names_a_pin_the_last_run_set_aside(monkeypatch):
    """Finding 130 (tcc#113): the footer said «API · gemini-3.1-pro-preview» while a pin in a
    critic-env sent the run elsewhere. The run now goes as the pick, and the footer names the pin
    it set aside, as the method reported it — a stale pin found, not obeyed. A run that set
    nothing aside clears it."""
    from autosound_tcc.core import availability, model_choices
    from autosound_tcc.ui.tcc import copy_menu

    pick = model_choices.Choice(harness="api", model="gemini-3.1-pro-preview",
                                label="gemini-3.1-pro-preview", provider="google")
    window = _reviewer_window(monkeypatch, pick)
    machine = r"C:\Users\Tuner\AppData\Roaming\autosound\critic-env"
    try:
        availability.succeeded(pick.key)
        availability.set_aside(pick.key, [
            {"variable": "AUTOSOUND_CRITIC_MODEL", "value": "gpt-5.6-terra", "file": machine,
             "line": 1},
            {"variable": "GEMINI_CRITIC_MODEL", "value": "gemini-2.5-pro", "file": None,
             "line": None},
        ])
        window._refresh_critic_status()
        # The whole note, as the label holds it to draw and to copy: drawn, it is elided to
        # whatever room the footer has (CI's wider fonts cut it in this unshown window's 640 px).
        assert i18n.t("criticPinsShortBoth") in copy_menu.full_text(window._critic_status)
        tip = window._critic_status.toolTip()
        assert i18n.t("criticPinInFile").format(
            var="AUTOSOUND_CRITIC_MODEL", value="gpt-5.6-terra", file=machine, line=1) in tip
        assert i18n.t("criticPinInEnv").format(
            var="GEMINI_CRITIC_MODEL", value="gemini-2.5-pro") in tip
        assert "kv-warn" not in str(window._critic_status.property("class")), \
            "the run went as picked: nothing is wrong with it"

        availability.set_aside(pick.key, [])
        window._refresh_critic_status()
        assert copy_menu.full_text(window._critic_status) == i18n.t(
            "criticCheckAnswered").format(label=pick.label)
        # No pin left in the tip: at most the whole text, where the label is cut.
        assert window._critic_status.toolTip() in ("", copy_menu.full_text(window._critic_status))
    finally:
        availability.reset()


def test_where_a_set_aside_pin_lives_stays_in_the_tip_through_a_relayout(monkeypatch):
    """tcc#113, found checking CI's elided footer: in a shown window the status's tip — where the
    pin the run set aside lives — was gone the moment the window laid the longer text out. The
    label's own eliding wrote the full text or nothing over it on every resize. Through a narrow
    window and a wide one, the tip still says where the pin is."""
    from autosound_tcc.core import availability, model_choices

    app = _app()
    window = MainWindow()
    monkeypatch.setattr(window, "_refresh_cli_catalogue", lambda force=False: None)
    window.show()

    def settle() -> None:
        for _ in range(4):
            app.processEvents()
            app.sendPostedEvents()

    settle()
    pick = model_choices.Choice(harness="api", model="gemini-3.1-pro-preview",
                                label="gemini-3.1-pro-preview", provider="google")
    window._critic_choices = [pick]
    MainWindow._fill_combo(window._ai_critic_combo, [pick], pick.key, critic=True)
    availability.reset()
    where = i18n.t("criticPinInEnv").format(var="GEMINI_CRITIC_MODEL", value="gemini-2.5-pro")
    try:
        availability.succeeded(pick.key)
        availability.set_aside(pick.key, [{"variable": "GEMINI_CRITIC_MODEL",
                                           "value": "gemini-2.5-pro", "file": None, "line": None}])
        window._refresh_critic_status()
        for width in (window.width(), 1280, 3000):
            window.resize(width, 820)
            settle()
            assert where in window._critic_status.toolTip(), (
                f"at {window.width()} px the tip reads {window._critic_status.toolTip()!r}")
    finally:
        availability.reset()


def test_a_process_state_refresh_takes_the_pin_tip_with_its_text(tmp_path, monkeypatch):
    """tcc#129: the process state names the last reviewer, and its refresh wrote that line over
    the footer's status — under the pin tip of the line before, a tip about a pin set aside under
    a text that says nothing of one. The tip describes the text it sits on."""
    from autosound_tcc.core import availability, model_choices
    from autosound_tcc.ui.tcc import copy_menu

    process = tmp_path / "process"
    process.mkdir()
    (process / "process-state.json").write_text(json.dumps({
        "schema_version": 3, "active_phase": "1",
        "phases": {"1": {"status": "cur", "title": "Crossovers"}},
        "plan": [{"id": "xo", "name": "Choose crossovers", "status": "cur", "phase": "1"}],
        "reviewer": {"vendor": "google", "model": "gemini-3.1-pro-preview",
                     "at": "2026-10-02T10:00:00Z"},
    }), encoding="utf-8")
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    pick = model_choices.Choice(harness="api", model="gemini-3.1-pro-preview",
                                label="gemini-3.1-pro-preview", provider="google")
    window = _reviewer_window(monkeypatch, pick)
    where = i18n.t("criticPinInEnv").format(var="GEMINI_CRITIC_MODEL", value="gemini-2.5-pro")
    try:
        availability.succeeded(pick.key)
        availability.set_aside(pick.key, [{"variable": "GEMINI_CRITIC_MODEL",
                                           "value": "gemini-2.5-pro", "file": None, "line": None}])
        window._refresh_critic_status()
        assert where in window._critic_status.toolTip()

        window._refresh_process()
        assert i18n.t("criticStatus").split("{")[0] in copy_menu.full_text(window._critic_status)
        assert where not in window._critic_status.toolTip()
    finally:
        availability.reset()


def _process_names_reviewer(tmp_path, monkeypatch, model: str) -> None:
    """A project whose process state names `model` as its last reviewer."""
    process = tmp_path / "process"
    process.mkdir(exist_ok=True)
    (process / "process-state.json").write_text(json.dumps({
        "schema_version": 3, "active_phase": "1",
        "phases": {"1": {"status": "cur", "title": "Crossovers"}},
        "plan": [{"id": "xo", "name": "Choose crossovers", "status": "cur", "phase": "1"}],
        "reviewer": {"vendor": "google", "model": model, "at": "2026-10-02T10:00:00Z"},
    }), encoding="utf-8")
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))


def test_a_process_state_write_keeps_the_picks_refusal(tmp_path, monkeypatch):
    """Review of #129, Minor 4: the pick refused, and the footer said so in red with why in its
    tip. A process-state write then put «Critic · model · ago» over it — the red stayed with
    nothing to say what it was, and the refusal was gone. The pick's refusal stays, whole."""
    from autosound_tcc.core import availability, model_choices
    from autosound_tcc.ui.tcc import copy_menu

    _process_names_reviewer(tmp_path, monkeypatch, "gemini-3.1-pro-preview")
    pick = model_choices.Choice(harness="api", model="gemini-3.1-pro-preview",
                                label="gemini-3.1-pro-preview", provider="google")
    window = _reviewer_window(monkeypatch, pick)
    try:
        availability.refused(pick.key, availability.REFUSED, "HTTP 429: quota exhausted")
        window._refresh_critic_status()
        refused = copy_menu.full_text(window._critic_status)
        assert "kv-warn" in str(window._critic_status.property("class"))
        assert "quota exhausted" in window._critic_status.toolTip()

        window._refresh_process()
        assert copy_menu.full_text(window._critic_status) == refused
        assert "quota exhausted" in window._critic_status.toolTip()
        assert "kv-warn" in str(window._critic_status.property("class"))
    finally:
        availability.reset()


@pytest.mark.parametrize("named,red", [("gemini-3.1-pro-preview", False), ("gpt-5.5", True)])
def test_a_process_state_write_paints_by_its_own_line(tmp_path, monkeypatch, named, red):
    """The red follows the line on screen (finding 55): another model than the pick named by the
    process state is red; the pick's own is not — whatever the footer was painted before."""
    from autosound_tcc.core import availability, model_choices
    from autosound_tcc.ui.tcc import copy_menu

    _process_names_reviewer(tmp_path, monkeypatch, named)
    pick = model_choices.Choice(harness="api", model="gemini-3.1-pro-preview",
                                label="gemini-3.1-pro-preview", provider="google")
    window = _reviewer_window(monkeypatch, pick)
    try:
        availability.succeeded(pick.key)
        for before in (True, False):
            window._paint_critic_status(before)
            window._refresh_process()
            assert named in copy_menu.full_text(window._critic_status)
            assert ("kv-warn" in str(window._critic_status.property("class"))) == red, before
    finally:
        availability.reset()


def test_the_start_up_probe_does_not_clear_a_pin_it_cannot_see(monkeypatch):
    """tcc#113 review, Minor 2: the probe runs with a scratch `PROJECT_MIRROR`, so the method never
    reads the project's `rew_analitic/.critic-env` for it. Its list of pins is not the whole story:
    an empty one cleared a pin a real review had named, at every start. The probe records none."""
    from autosound_tcc.core import availability, critic, model_choices
    from autosound_tcc.ui.tcc.main_window import _ReviewerProbeWorker

    _app()
    key = "agy:gemini-3.1-pro-high"
    named = [{"variable": "AUTOSOUND_CRITIC_MODEL", "value": "gpt-5.6-terra",
              "file": "/p/rew_analitic/.critic-env", "line": 1}]
    monkeypatch.setattr(model_choices, "critic_reaches", lambda _c: True)
    availability.reset()
    try:
        for seen in ([], [{"variable": "GEMINI_CRITIC_MODEL", "value": "x", "file": None,
                           "line": None}]):
            availability.set_aside(key, named)
            monkeypatch.setattr(critic, "run", lambda package, seen=seen, **kw: critic.CriticResult(
                critic.MODE_API_OR_CLI, "pong", "gemini-3.1-pro-high", "ask", "", 1.0, "t",
                pins_set_aside=seen))
            _ReviewerProbeWorker(key, config.project_dir()).run()
            assert availability.pins_set_aside(key) == named, seen
        assert availability.answered(key), "the rest of the probe's answer is still recorded"
    finally:
        availability.reset()


def test_the_footer_note_says_what_kind_of_pin_was_set_aside(monkeypatch):
    """tcc#113 review, Minor 4: «a pin in a file» stood beside a run whose only lost pin was an
    environment variable. The note says what was lost: a file, the environment, or both."""
    from autosound_tcc.core import availability, model_choices
    from autosound_tcc.ui.tcc import copy_menu

    pick = model_choices.Choice(harness="api", model="gemini-3.1-pro-preview",
                                label="gemini-3.1-pro-preview", provider="google")
    window = _reviewer_window(monkeypatch, pick)
    in_file = {"variable": "AUTOSOUND_CRITIC_MODEL", "value": "gpt-5.6-terra",
               "file": "/m/critic-env", "line": 1}
    in_env = {"variable": "GEMINI_CRITIC_MODEL", "value": "gemini-2.5-pro", "file": None,
              "line": None}
    keys = ("criticPinsShort", "criticPinsShortEnv", "criticPinsShortBoth")
    try:
        availability.succeeded(pick.key)
        for pins, want in (([in_file], "criticPinsShort"), ([in_env], "criticPinsShortEnv"),
                           ([in_env, in_file], "criticPinsShortBoth")):
            availability.set_aside(pick.key, pins)
            window._refresh_critic_status()
            text = copy_menu.full_text(window._critic_status)  # whole, as drawn where it fits
            assert text.endswith(f" · {i18n.t(want)}"), (want, text)
            assert [k for k in keys if i18n.t(k) in text] == [want], (want, text)
    finally:
        availability.reset()


def _a_reviewer_picked_in_the_footer(monkeypatch):
    """Finding 142 (tcc#140), as the Arbiter met it on the VM: «gemini-3.1-pro-preview» reviewed
    last, 23 h ago, asked for and answered by itself, and «AGY · Gemini 3.8 Flash (Low)» is about
    to be picked in the footer. A probe asked for is recorded and never runs, so its check does not
    answer until a test says so."""
    from datetime import datetime, timedelta, timezone

    from autosound_tcc.core import critic, model_choices

    before = model_choices.Choice(harness="agy", model="gemini-3.1-pro-preview",
                                  label="Gemini 3.1 Pro (Preview)", provider="google")
    flash = model_choices.Choice(harness="agy", model="gemini-3.8-flash-low",
                                 label="Gemini 3.8 Flash (Low)", provider="google")
    window = _reviewer_window(monkeypatch, before, flash)
    monkeypatch.setenv("AUTOSOUND_TCC_MCP", "1")  # past the launch-time escape hatch (conftest)
    monkeypatch.setattr(model_choices, "critic_reaches", lambda _c: True)
    # `_on_reviewer_probed` refills the pickers: both rows resolve, so no modal «model gone» box.
    monkeypatch.setattr(model_choices, "choices", lambda _active: [])
    monkeypatch.setattr(model_choices, "critic_choices", lambda _active: [before, flash])
    at = (datetime.now(timezone.utc) - timedelta(hours=23)).isoformat()
    monkeypatch.setattr(critic, "last_call", lambda _p=None: {
        "asked": before.model, "model": before.model, "at": at, "mode": "answered"})
    window._set_project_setting(main_window._CRITIC_KEY, before.key)
    started: list = []
    running: set = set()

    def start(worker) -> None:
        started.append(worker)
        running.add(worker)

    monkeypatch.setattr(main_window._ReviewerProbeWorker, "start", start)
    monkeypatch.setattr(main_window._ReviewerProbeWorker, "isRunning",
                        lambda worker: worker in running)
    return window, before, flash, started, running


def _pick_reviewer(window, choice) -> None:
    window._ai_critic_combo.setCurrentIndex(window._ai_critic_combo.findData(choice.key))


def test_a_new_reviewer_pick_spins_while_its_check_runs_and_names_no_old_reviewer(monkeypatch):
    """Finding 142 (tcc#140): for about a minute after the pick the footer read the previous
    reviewer in red, «gemini-3.1-pro-preview · 23 h ago», and then «… answered the check». The
    Arbiter: «на місці чи поруч зі знаком питання крутити колесико поки іде перевірка». From the
    pick until its check answers, the footer says the new pick is being checked, with a turning
    wheel beside the «!» — and no line from the old pick, there or in the «!»."""
    from autosound_tcc.core import availability, critic
    from autosound_tcc.ui.tcc import copy_menu

    window, before, flash, started, running = _a_reviewer_picked_in_the_footer(monkeypatch)
    _pick_reviewer(window, flash)

    status = window._critic_status
    text = copy_menu.full_text(status)
    assert before.model not in text and before.model not in status.toolTip(), text
    assert text == i18n.t("criticChecking").format(label=flash.label), text
    assert "kv-warn" not in str(status.property("class")), "nothing is wrong yet: it is asked"
    assert [worker._key for worker in started] == [flash.key], "the new pick is the one asked"
    spinner = window._critic_spinner
    assert spinner.is_spinning() and not spinner.isHidden()

    # The check answers: the wheel stops and goes, and the status says so (finding 92, tcc#82).
    running.clear()
    availability.succeeded(flash.key)
    window._on_reviewer_probed(critic.MODE_API_OR_CLI)

    assert not spinner.is_spinning() and spinner.isHidden()
    assert copy_menu.full_text(status) == i18n.t("criticCheckAnswered").format(label=flash.label)
    # Nor does the «!» claim a fallback: the last review asked for the old pick and got it, which
    # says nothing about this one (review of tcc#140, I-1).
    assert before.model not in window._critic_warn_detail, window._critic_warn_detail


def test_a_pick_made_while_the_previous_check_runs_spins_until_its_own_answers(monkeypatch):
    """One check at a time (the probe30 crash), so a pick made during the launch's check is asked
    when that one ends (tcc#74). It is being checked all that time: the wheel turns from the pick,
    the end of the other check does not stop it, and only its own answer does."""
    from autosound_tcc.core import availability, critic
    from autosound_tcc.ui.tcc import copy_menu

    window, before, flash, started, running = _a_reviewer_picked_in_the_footer(monkeypatch)
    window._probe_reviewer()  # the launch's check, of the reviewer picked before
    assert [worker._key for worker in started] == [before.key]
    _pick_reviewer(window, flash)

    status, spinner = window._critic_status, window._critic_spinner
    checking = i18n.t("criticChecking").format(label=flash.label)
    assert copy_menu.full_text(status) == checking
    assert spinner.is_spinning()

    running.clear()  # the previous pick's check answers
    availability.succeeded(before.key)
    window._on_reviewer_probed(critic.MODE_API_OR_CLI)
    assert copy_menu.full_text(status) == checking, "the new pick is still to be asked"
    assert spinner.is_spinning()
    # The «!» was asked anew with the pickers' refill: the last review asked for the old pick,
    # and «answered by gemini-3.1-pro-preview» would be that pick's line, not a fallback.
    assert before.model not in window._critic_warn_detail, window._critic_warn_detail

    window._on_reviewer_probe_finished()  # its thread has ended: the new pick is asked now
    assert [worker._key for worker in started] == [before.key, flash.key]
    assert spinner.is_spinning()

    running.clear()
    availability.succeeded(flash.key)
    window._on_reviewer_probed(critic.MODE_API_OR_CLI)
    assert not spinner.is_spinning() and spinner.isHidden()
    assert copy_menu.full_text(status) == i18n.t("criticCheckAnswered").format(label=flash.label)


def test_a_process_state_write_during_the_check_names_no_old_reviewer(tmp_path, monkeypatch):
    """The process state names the last reviewer, and its refresh writes that line over the
    footer's (tcc#129). During the new pick's check that line is the old pick's: the footer keeps
    saying the new one is being checked."""
    from autosound_tcc.ui.tcc import copy_menu

    _process_names_reviewer(tmp_path, monkeypatch, "gemini-3.1-pro-preview")
    window, before, flash, started, running = _a_reviewer_picked_in_the_footer(monkeypatch)
    _pick_reviewer(window, flash)

    window._refresh_process()

    text = copy_menu.full_text(window._critic_status)
    assert before.model not in text, text
    assert text == i18n.t("criticChecking").format(label=flash.label)
    assert window._critic_spinner.is_spinning()


@pytest.mark.parametrize("why", ["no transport", "no MCP"])
def test_a_reviewer_that_is_never_asked_shows_no_wheel(monkeypatch, why):
    """No transport for the pick, so the method can only compile a clipboard package and nothing
    asks it (final review, Minor 3) — or TCC runs with its MCP off, and asks nothing at all. No
    check runs, and nothing turns as though one did."""
    from autosound_tcc.core import model_choices
    from autosound_tcc.ui.tcc import copy_menu

    window, before, flash, started, running = _a_reviewer_picked_in_the_footer(monkeypatch)
    if why == "no transport":
        monkeypatch.setattr(model_choices, "critic_reaches", lambda _c: False)
    else:
        monkeypatch.setenv("AUTOSOUND_TCC_MCP", "0")
    _pick_reviewer(window, flash)

    assert started == []
    assert not window._critic_spinner.is_spinning() and window._critic_spinner.isHidden()
    assert copy_menu.full_text(window._critic_status) != i18n.t("criticChecking").format(
        label=flash.label)


def test_the_check_wheel_turns_in_each_themes_own_colour(monkeypatch):
    """The wheel paints itself, so no style sheet colours it: it reads the theme it is drawn in —
    the Critic's own blue in each palette — and a switch moves it with the rest. And it turns."""
    from autosound_tcc.ui.tcc.theme import PALETTE_DARK, PALETTE_LIGHT
    from tests import _windows

    window, before, flash, started, running = _a_reviewer_picked_in_the_footer(monkeypatch)
    _pick_reviewer(window, flash)
    spinner = window._critic_spinner

    def drawn() -> set:
        image = spinner.grab().toImage()
        return {image.pixelColor(x, y).name() for x in range(image.width())
                for y in range(image.height()) if image.pixelColor(x, y).alpha() == 255}

    for mode, palette in (("dark", PALETTE_DARK), ("light", PALETTE_LIGHT)):
        _windows.theme_on(monkeypatch, window, mode)
        colours = drawn()
        assert palette["info"] in colours, (mode, sorted(colours))
        other = PALETTE_LIGHT if palette is PALETTE_DARK else PALETTE_DARK
        assert other["info"] not in colours, mode

    # One tick of its own timer, not a wait on the clock (the flaky waits of #141): that the
    # timer runs is `is_spinning`, and what a tick does is this.
    first = spinner.grab().toImage()
    spinner._timer.timeout.emit()
    assert spinner.grab().toImage() != first, "a wheel that does not turn says nothing is running"


def test_a_pin_the_last_run_set_aside_is_still_named_while_the_pick_is_checked(monkeypatch):
    """tcc#113 and #129: the footer names a pin the pick's last run set aside, and where it lives
    is in the tip. The check says nothing about that pin, so it stays named beside «checking»."""
    from autosound_tcc.core import availability
    from autosound_tcc.ui.tcc import copy_menu

    window, before, flash, started, running = _a_reviewer_picked_in_the_footer(monkeypatch)
    pin = {"variable": "GEMINI_CRITIC_MODEL", "value": "gemini-2.5-pro", "file": None, "line": None}
    availability.set_aside(flash.key, [pin])
    _pick_reviewer(window, flash)

    status = window._critic_status
    checking = i18n.t("criticChecking").format(label=flash.label)
    assert copy_menu.full_text(status) == f"{checking} · {i18n.t('criticPinsShortEnv')}"
    assert i18n.t("criticPinInEnv").format(var="GEMINI_CRITIC_MODEL",
                                           value="gemini-2.5-pro") in status.toolTip()
    assert window._critic_spinner.is_spinning()


def test_a_refused_pick_asked_again_keeps_its_refusal_with_the_wheel_beside_it(monkeypatch):
    """#129: a refused pick keeps its line, its tip and its red. Picked again, it is asked again —
    the wheel turns beside the refusal, and the refusal stays until the check answers otherwise."""
    from autosound_tcc.core import availability
    from autosound_tcc.ui.tcc import copy_menu

    window, before, flash, started, running = _a_reviewer_picked_in_the_footer(monkeypatch)
    availability.refused(flash.key, availability.REFUSED, "HTTP 429: quota exhausted")
    _pick_reviewer(window, flash)

    status = window._critic_status
    assert [worker._key for worker in started] == [flash.key]
    assert window._critic_spinner.is_spinning()
    assert copy_menu.full_text(status).startswith(f"{flash.label} · ")
    assert "quota exhausted" in status.toolTip()
    assert "kv-warn" in str(status.property("class"))


def test_a_fallback_of_the_unchanged_pick_stays_on_the_mark_while_its_launch_check_runs(
        monkeypatch):
    """Review of tcc#140, I-1: hiding «answered by» for the length of a check rested on "the last
    review is the previous pick's", which holds only after a change of pick. At launch the pick is
    the one that reviewed last, and when that review asked for it and another model answered, the
    «!» says so — the one claim on it backed by evidence — check or no check."""
    from autosound_tcc.core import critic

    window, before, flash, started, running = _a_reviewer_picked_in_the_footer(monkeypatch)
    monkeypatch.setattr(critic, "last_call", lambda _p=None: {
        "asked": before.model, "model": "gemini-2.5-flash", "at": "2026-10-02T08:00:00+00:00",
        "mode": "answered"})

    window._probe_reviewer()  # the launch's check, of the pick as it was
    window._refresh_critic_status()  # as `_on_cli_catalogue_ready` does right after it

    assert [worker._key for worker in started] == [before.key]
    assert window._critic_spinner.is_spinning()
    assert i18n.t("criticAnswered").format(model="gemini-2.5-flash") in window._critic_warn_detail


def test_a_pick_waiting_behind_a_check_is_asked_when_that_checks_thread_has_ended(monkeypatch):
    """Review of tcc#140, I-2: `done` is emitted inside `run()`, so the thread can still be
    unwinding when it arrives. The re-probe queued from it met the one-check-at-a-time guard, the
    pick that waited was never asked, and the wheel said it was being checked until the next
    session. It is asked on the thread's own `finished`."""
    from autosound_tcc.core import availability, critic
    from autosound_tcc.ui.tcc import copy_menu

    window, before, flash, started, running = _a_reviewer_picked_in_the_footer(monkeypatch)
    window._probe_reviewer()  # the launch's check, of the reviewer picked before
    _pick_reviewer(window, flash)  # waits for it
    spinner = window._critic_spinner

    availability.succeeded(before.key)
    window._on_reviewer_probed(critic.MODE_API_OR_CLI)  # `done`: its thread is still in `run()`
    _app().processEvents()  # anything queued on `done` runs while the thread unwinds
    assert [worker._key for worker in started] == [before.key], "one check at a time"
    assert spinner.is_spinning(), "the new pick still waits to be asked"

    running.clear()
    started[0].finished.emit()  # the thread has ended
    assert [worker._key for worker in started] == [before.key, flash.key]
    assert spinner.is_spinning()

    running.clear()
    availability.succeeded(flash.key)
    window._on_reviewer_probed(critic.MODE_API_OR_CLI)
    started[1].finished.emit()
    assert [worker._key for worker in started] == [before.key, flash.key], "asked once"
    assert not spinner.is_spinning() and spinner.isHidden()
    assert copy_menu.full_text(window._critic_status) == i18n.t("criticCheckAnswered").format(
        label=flash.label)


def test_closing_the_window_during_a_check_stops_the_wheel(monkeypatch):
    """Review of tcc#140, M-1: a close lets the running probe go with its `done` cut, so nothing
    that stops the wheel would ever run, and its timer ticked on until the window object died."""
    window, before, flash, started, running = _a_reviewer_picked_in_the_footer(monkeypatch)
    _pick_reviewer(window, flash)
    assert window._critic_spinner.is_spinning()

    window.closeEvent(QCloseEvent())

    assert not window._critic_spinner.is_spinning()


# ---- a capture taken as it is: the strip agrees with the card (review of finding 147, I1) -------

_AS_IS_VERDICT = {"ok": False, "exists": True, "applicable": True, "uuid": "u-sw",
                  "issues": ["covers 20-1001 Hz, asked for 20-20000 — truncated"]}


def test_a_capture_taken_as_it_is_is_not_checked_again(monkeypatch):
    """The tuner answered for that verdict in the import window: checking it again on every title
    change pulled the curve from REW and repeated «unusable» beside a green row. A re-take under
    the same title is another capture (another uuid) and is checked."""
    from autosound_tcc.state import measurement_view

    monkeypatch.setattr(measurement_view, "taken_as_is", lambda *a, **k: {"u-sw": "sw_7 (sw)"})
    round_ = {"id": "cap_002", "expected": ["sw_7 (sw)"],
              "taken": {"sw_7 (sw)": {"at": "x", "verified": dict(_AS_IS_VERDICT)}}}

    assert _round_check_started(monkeypatch, round_, ["sw_7 (sw)"]) == []

    round_["taken"]["sw_7 (sw)"]["verified"]["uuid"] = "u-retaken"
    assert _round_check_started(monkeypatch, round_, ["sw_7 (sw)"]) == [["sw_7 (sw)"]]


def test_a_sweep_the_import_window_passed_is_not_checked_again(monkeypatch):
    """tcc#149, the review's m1: a capture the window passed over its own range, which the method's
    check calls «truncated» alone, was checked again on every change to REW's list — a pull from
    REW and a journal event each time, for a verdict that will not change until hub #247. Settled,
    as one taken as it is is; a re-take under the same title is another uuid and is checked."""
    from autosound_tcc.core import capture_import, config

    capture_import.record_imported([capture_import.Candidate(
        ordinal="1", title="sw_7 (sw)", uuid="u-sw", date="", when=None, imported=False,
        checked="usable")], project_dir=config.project_dir())
    round_ = {"id": "cap_002", "expected": ["sw_7 (sw)"],
              "taken": {"sw_7 (sw)": {"at": "x", "verified": dict(_AS_IS_VERDICT)}}}

    assert _round_check_started(monkeypatch, round_, ["sw_7 (sw)"]) == []

    round_["taken"]["sw_7 (sw)"]["verified"]["uuid"] = "u-retaken"
    assert _round_check_started(monkeypatch, round_, ["sw_7 (sw)"]) == [["sw_7 (sw)"]]


def test_the_strip_leaves_out_a_sweep_the_import_window_passed_over_its_own_range(monkeypatch):
    """tcc#149: after Apply the strip said «1 unusable: sw_7 (sw) — covers 20-1001 Hz, asked for
    20-20000 — truncated» for a sub the import window had just passed over its own range. Until
    the method reads the sweep's range (hub #247) that line alone, on that capture, is not a
    warning — read from TCC's own store by the uuid the method's verdict pins. Another capture's
    failure still is."""
    from autosound_tcc.core import capture_import, config
    from autosound_tcc.state import process_view

    _app()
    window = MainWindow()
    monkeypatch.setattr(process_view, "load_state", lambda *a, **k: None)
    capture_import.record_imported([capture_import.Candidate(
        ordinal="1", title="sw_7 (sw)", uuid="u-sw", date="", when=None, imported=False,
        checked="usable")], project_dir=config.project_dir())
    silence = {"ok": False, "exists": True, "applicable": True, "uuid": "u-wl",
               "issues": ["in-band mean -96.1 dB — silence, not a sweep"]}
    monkeypatch.setattr(process_view, "capture_round", lambda *a, **k: {
        "id": "cap_002", "expected": ["sw_7 (sw)", "w-L_7 (sw)"],
        "taken": {"sw_7 (sw)": {"verified": dict(_AS_IS_VERDICT)},
                  "w-L_7 (sw)": {"verified": silence}}})
    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **k: said.append(text))
    own_range = "UNUSABLE sw_7 (sw) — " + _AS_IS_VERDICT["issues"][0]

    window._on_capture_check_done(own_range + "\n0/1 придатні", ["sw_7 (sw)"])
    assert said == []

    window._on_capture_check_done(
        own_range + "\nUNUSABLE w-L_7 (sw) — in-band mean -96.1 dB — silence, not a sweep\n"
        "0/2 придатні", ["sw_7 (sw)", "w-L_7 (sw)"])
    assert said == [i18n.t("unusableSummary").format(
        n=1, first="w-L_7 (sw) — in-band mean -96.1 dB — silence, not a sweep")], said


def test_the_strip_does_not_call_a_capture_taken_as_it_is_unusable(monkeypatch):
    """Review I1: right after Apply the strip said «1 unusable: sw_7 (sw) — … truncated» while the
    card's row read green «взято як є». The method's verdict stays recorded as it is; the strip
    does not warn about a capture the tuner already answered for — and still warns about another."""
    from autosound_tcc.state import measurement_view, process_view

    _app()
    window = MainWindow()
    monkeypatch.setattr(process_view, "load_state", lambda *a, **k: None)
    monkeypatch.setattr(measurement_view, "taken_as_is", lambda *a, **k: {"u-sw": "sw_7 (sw)"})
    silence = {"ok": False, "exists": True, "applicable": True, "uuid": "u-wl",
               "issues": ["in-band mean -96.1 dB — silence, not a sweep"]}
    monkeypatch.setattr(process_view, "capture_round", lambda *a, **k: {
        "id": "cap_002", "expected": ["sw_7 (sw)", "w-L_7 (sw)"],
        "taken": {"sw_7 (sw)": {"verified": dict(_AS_IS_VERDICT)},
                  "w-L_7 (sw)": {"verified": silence}}})
    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **k: said.append(text))
    as_is_line = "UNUSABLE sw_7 (sw) — covers 20-1001 Hz, asked for 20-20000 — truncated"

    window._on_capture_check_done(as_is_line + "\n0/1 придатні", ["sw_7 (sw)"])
    assert said == []

    window._on_capture_check_done(
        as_is_line + "\nUNUSABLE w-L_7 (sw) — in-band mean -96.1 dB — silence, not a sweep\n"
        "0/2 придатні", ["sw_7 (sw)", "w-L_7 (sw)"])
    assert said == [i18n.t("unusableSummary").format(
        n=1, first="w-L_7 (sw) — in-band mean -96.1 dB — silence, not a sweep")], said


def _two_presets(tmp_path, monkeypatch):
    """A seeded project with two presets and no AUTOSOUND_TCC_PRESET — the case every preset test
    hid by setting it (TA-5)."""
    from autosound_tcc.core import vendor_loader

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("AUTOSOUND_STATE_ROOT", raising=False)
    monkeypatch.delenv("AUTOSOUND_TCC_PRESET", raising=False)
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    _intake.seed(tmp_path)
    vendor_loader.load_dsp_state().PresetHistory(
        str(tmp_path / "state"), "SECOND", project_dir=str(tmp_path)).snapshot({
            "preset": "SECOND", "sample_rate": 96000,
            "channels": {"w-L": {"hp": None, "lp": None, "gain_db": 0.0, "ta_ms": 0.0,
                                 "polarity": "NORM"}},
        }, note="fixture: a second preset")
    assert config.available_presets() == ["FULL", "SECOND"], "the situation this is about"
    assert config.resolve_preset() is None


def test_the_agent_is_told_the_preset_on_screen_when_there_are_two(tmp_path, monkeypatch):
    """TA-5: with two presets `resolve_preset` is None while the window shows the first, so the
    model was told no preset at all about a screen that had one."""
    _two_presets(tmp_path, monkeypatch)
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)

    assert window._preset_combo.currentData() == "FULL"
    assert window._bridge.snapshot()["preset"] == window._preset_combo.currentData()


def test_a_preset_switch_reaches_the_agent(tmp_path, monkeypatch):
    _two_presets(tmp_path, monkeypatch)
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)

    window._preset_combo.setCurrentIndex(window._preset_combo.findData("SECOND"))

    assert window._bridge.snapshot()["preset"] == "SECOND"


def test_a_preset_left_by_another_project_is_not_reported(tmp_path, monkeypatch):
    """`ui/preset` is global; the load ignores a name this project does not have, and the
    snapshot reported it anyway."""
    _two_presets(tmp_path, monkeypatch)
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)

    window._preset_override = "GONE"
    window._load_project()

    assert window._bridge.snapshot()["preset"] == "FULL"


def test_edit_mode_reaches_the_agent(tmp_path, monkeypatch):
    _two_presets(tmp_path, monkeypatch)
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)

    window._dialog._start_editing("manual")
    assert window._bridge.snapshot()["param_edit_mode"] is True
    window._dialog._finish_editing()
    assert window._bridge.snapshot()["param_edit_mode"] is False


def test_an_agent_write_rereads_the_project_without_the_full_recheck(monkeypatch):
    """TA-3: every `report_phase` ran the header's ↻ — REW, the models, the refusals — and a
    session that wrote five files ran it five times. The agent's signal re-reads the project and
    the contract once the writes settle; ↻ stays the explicit full re-check."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()
    _KEEP_WINDOWS.append(window)
    loads, checks, pings, catalogues, forgets = [], [], [], [], []
    monkeypatch.setattr(MainWindow, "_safe_load_project", lambda self: loads.append(1))
    monkeypatch.setattr(MainWindow, "_start_contract_check", lambda self: checks.append(1))
    monkeypatch.setattr(MainWindow, "_ping_rew", lambda self: pings.append(1))
    monkeypatch.setattr(MainWindow, "_refresh_cli_catalogue",
                        lambda self, force=False: catalogues.append(force))
    monkeypatch.setattr(main_window.availability, "forget_refusals", lambda: forgets.append(1))

    for _ in range(5):
        window._bridge.refresh_from_disk()

    assert _pump_until(lambda: bool(loads), seconds=5), "the re-read comes once the writes settle"
    _pump_until(lambda: False, seconds=0.6)  # and no second one after it
    assert loads == [1] and checks == [1]
    assert pings == [] and catalogues == [] and forgets == []
