"""Headless smoke test of the Qt app shell (brief §9: tests must run without a display).

Forces the offscreen QPA platform if nothing else already set one, so this runs the same way in
CI as it does locally without a real screen.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSplitter  # noqa: E402

from autosound_tcc.core import config, ui_mode  # noqa: E402
from autosound_tcc.ui.tcc.main_window import MainWindow, _force_project_dir_env  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


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


def test_theme_toggle_switches_and_persists_in_memory():
    _app()
    window = MainWindow()
    start = window._mode
    window._toggle_theme()
    assert window._mode != start
    window._toggle_theme()
    assert window._mode == start


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
    monkeypatch.setenv("AUTOSOUND_TCC_STATE_ROOT", str(tmp_path))

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
    monkeypatch.setenv("AUTOSOUND_TCC_STATE_ROOT", str(tmp_path))
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
    monkeypatch.setenv("AUTOSOUND_TCC_STATE_ROOT", str(tmp_path))
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


def test_project_profile_renders_extra_param_sections(tmp_path, monkeypatch):
    """Item 2, 2026-07-27 (moved to the top-level "Project params" section 2026-07-28):
    project_profile.json's `param_sections` each render as their own collapsible ParamsSection,
    under the sidebar's Project params section -- not inside the DSP tree, since this is
    project-level config rather than ledger-driven DSP state."""
    import json

    from autosound_tcc.ui.tcc.dsp_tree import ParamsSection

    profile = {
        "dsp_profile": {
            "name": "M6V4", "vendor": "Musway",
            "groups": [{"id": "physical_outputs", "label": "Output channels",
                        "fields": ["hp", "lp", "gain_db"]}],
        }
    }
    (tmp_path / "dsp_profile.json").write_text(json.dumps(profile))
    (tmp_path / "project_profile.json").write_text(json.dumps({
        "param_sections": [
            {"id": "car", "label": "Car setup", "params": [["Make", "VW"]]},
            {"id": "chassis", "label": "Body / chassis", "params": [["Doors", "4"]]},
        ]
    }))
    preset_dir = tmp_path / "TESTPRESET"
    preset_dir.mkdir()
    ledger = {"preset": "TESTPRESET", "sample_rate": 48000,
              "channels": {"w_L": {"hp": {"f": 80}, "lp": {"f": 4000}, "gain_db": -2.0}}}
    (preset_dir / "v_001.json").write_text(json.dumps(ledger))
    (preset_dir / "HEAD").write_text("v_001")

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSOUND_TCC_STATE_ROOT", str(tmp_path))

    _app()
    window = MainWindow()
    sections = window._project_section.findChildren(ParamsSection)
    assert len(sections) == 2
    assert {s._gid for s in sections} == {"car", "chassis"}


def test_view_mode_is_the_default_and_hides_control_only_affordances():
    """TCC-TZ.md §8: default is `view`, a read-only reader -- no AI, no Start Session/Open
    Terminal/model pickers."""
    _app()
    window = MainWindow()
    assert window._ui_mode == "view"
    for widget in _control_only_widgets(window):
        assert widget.isHidden(), widget
    assert window._dialog._composer.isHidden()


def test_switching_to_control_mode_reveals_the_ai_affordances_and_persists():
    _app()
    window = MainWindow()

    window._on_mode_selected("control")

    assert window._ui_mode == "control"
    for widget in _control_only_widgets(window):
        assert not widget.isHidden(), widget
    assert not window._dialog._composer.isHidden()
    assert ui_mode.get_mode(config.tcc_dir()) == "control"

    # A fresh window against the same project dir picks up the persisted choice on launch.
    window2 = MainWindow()
    assert window2._ui_mode == "control"
    for widget in _control_only_widgets(window2):
        assert not widget.isHidden(), widget


def test_mode_switch_is_independent_of_whether_a_profile_was_found():
    """§8: "is there a project" and "which mode" are two independent questions -- switching to
    control mode must not depend on (or be blocked by) a DSP profile ever having loaded."""
    _app()
    window = MainWindow()
    assert window._left_status.isHidden() is False  # no profile in the isolated tmp project dir

    window._on_mode_selected("control")

    assert window._ui_mode == "control"
    assert not window._session_btn.isHidden()


def test_no_project_shows_create_button_and_clears_every_mock_panel():
    """A folder with no dsp_profile.json at all must not look like a live tuning session --
    the AI dialog, plan, and measurement panels all default to prototype mock content, and
    MainWindow is the only thing that knows whether a real project backs any of it."""
    _app()
    window = MainWindow()

    assert not window._create_project_btn.isHidden()
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
    monkeypatch.setenv("AUTOSOUND_TCC_STATE_ROOT", str(tmp_path))

    _app()
    window = MainWindow()

    assert window._create_project_btn.isHidden()
    assert len(window._dialog._bubbles) == 0
    assert window._plan_panel.plan == ()


def test_found_profile_hides_create_button_and_leaves_mock_untouched(tmp_path, monkeypatch):
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
    monkeypatch.setenv("AUTOSOUND_TCC_STATE_ROOT", str(tmp_path))

    _app()
    window = MainWindow()

    assert window._create_project_btn.isHidden()
    assert window._meas_panel._no_project_label.isHidden()


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
    monkeypatch.setenv("AUTOSOUND_TCC_STATE_ROOT", str(tmp_path / "state"))  # no presets here
    get_settings().setValue("ui/preset", "FULL")  # stale, from a different project entirely

    _app()
    window = MainWindow()

    assert window._left_status.text() == (
        "Audiotec-Fischer Helix DSP Ultra S\n\n"
        f"No preset ledger found under {tmp_path / 'state'}."
    )
