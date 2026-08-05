"""Headless smoke test of the Qt app shell (brief §9: tests must run without a display).

Forces the offscreen QPA platform if nothing else already set one, so this runs the same way in
CI as it does locally without a real screen.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QSplitter  # noqa: E402

from autosound_tcc.core import config  # noqa: E402
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
    """SCR-015/016 (`state/project_view.py`): System params renders `project.json`'s DSP/amp/mic
    facts, and Project params gets an extra channel-tier-summary row plus an open-question chip --
    none of this is re-derived from the ledger, all of it comes straight from the file."""
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

    project_kv = _kv_texts(window._project_section)
    assert project_kv["Virtual channels"] == "8 (1 off)"

    chip_texts = [
        w.text() for w in window._project_section.findChildren(QLabel)
        if w.property("class") == "phead-sub"
    ]
    assert any("mic.calibration_file" in t for t in chip_texts)


def test_every_affordance_is_present_because_v1_has_one_mode():
    """The view/control switch is out of v1 (2026-08-05). It was meant to be the free tier's face
    -- a reader over a project the skill drives from a terminal -- but it hid the terminal button
    it existed for, and left "create project" visible even though the intake is an AI interview.
    One mode until the free tier is a real product; `git log` has the switch if it comes back."""
    _app()
    window = MainWindow()

    for widget in _control_only_widgets(window):
        assert not widget.isHidden(), widget
    assert not window._dialog._composer.isHidden()


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
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path))

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
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path))

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
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(tmp_path / "state"))  # no presets here
    get_settings().setValue("ui/preset", "FULL")  # stale, from a different project entirely

    _app()
    window = MainWindow()

    assert window._left_status.text() == (
        "Audiotec-Fischer Helix DSP Ultra S\n\n"
        f"No preset ledger found under {tmp_path / 'state'}."
    )


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
    process = vendor_loader.load_process().Process(str(tmp_path / "process"))
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
        model_choices.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps({"models": models}), ""),
    )


def test_the_picker_offers_claudes_models_out_of_the_box():
    """Nothing marked, no omp needed: TCC is usable on a machine that only has the Claude CLI."""
    _app()
    window = MainWindow()

    keys = [window._ai_main_combo.itemData(i) for i in range(window._ai_main_combo.count())]

    assert keys == ["sdk:claude-opus-5", "sdk:claude-sonnet-5", "sdk:claude-fable-5"]
    assert window._generator_choice().harness == "sdk"


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


def test_the_critic_picker_comes_from_the_same_registry(monkeypatch):
    """One list, one place to configure — the Critic used to have its own hard-coded strings."""
    _catalogue(monkeypatch, [{
        "provider": "google", "selector": "google/gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro", "cost": {"input": 1.0, "output": 1.0},
    }])
    _app()
    window = MainWindow()
    window._settings.setValue("ai/active_omp", "google/gemini-3.1-pro-preview")
    window._reload_model_choices()

    generator = {window._ai_main_combo.itemData(i) for i in range(window._ai_main_combo.count())}
    reviewer = {window._ai_critic_combo.itemData(i) for i in range(window._ai_critic_combo.count())}

    assert generator == reviewer
    assert "omp:google/gemini-3.1-pro-preview" in reviewer


def test_a_reviewer_the_script_cannot_call_is_marked_clipboard_only(monkeypatch):
    """The reviewer script is Gemini-shaped (SCR-033). Everything else lands in clipboard mode,
    which the user should learn before picking rather than after waiting."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    claude = window._ai_critic_combo.findData("sdk:claude-opus-5")
    assert "clipboard" in window._ai_critic_combo.itemText(claude).lower()


def test_a_gemini_reviewer_is_not_marked(monkeypatch):
    _catalogue(monkeypatch, [{
        "provider": "google", "selector": "google/gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro", "cost": {"input": 1.0, "output": 1.0},
    }])
    _app()
    window = MainWindow()
    window._settings.setValue("ai/active_omp", "google/gemini-3.1-pro-preview")
    window._reload_model_choices()

    index = window._ai_critic_combo.findData("omp:google/gemini-3.1-pro-preview")
    assert "clipboard" not in window._ai_critic_combo.itemText(index).lower()


def test_the_reviewer_model_reaches_the_subprocess_by_name(monkeypatch):
    """`critic.run` steers the script through its env var and knows nothing about model names, so
    what the picker publishes has to be the model, not the label."""
    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    window._ai_critic_combo.setCurrentIndex(window._ai_critic_combo.findData("sdk:claude-sonnet-5"))

    assert window._bridge.snapshot()["critic_model"] == "claude-sonnet-5"
