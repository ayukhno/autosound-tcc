"""Headless smoke test of the Qt app shell (brief §9: tests must run without a display).

Forces the offscreen QPA platform if nothing else already set one, so this runs the same way in
CI as it does locally without a real screen.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QSplitter  # noqa: E402

from autosound_tcc.core import config  # noqa: E402
from autosound_tcc.ui.tcc import i18n, main_window  # noqa: E402
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

    assert keys[1:] == ["sdk:claude-opus-5", "sdk:claude-sonnet-5", "sdk:claude-fable-5"]


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


def test_the_placeholder_disappears_once_a_model_is_chosen():
    _app()
    window = MainWindow()

    window._ai_main_combo.setCurrentIndex(window._ai_main_combo.findData("sdk:claude-opus-5"))

    assert window._ai_main_combo.findData("") < 0


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

    # The generator carries an extra "nothing chosen yet" entry; the reviewer has a working
    # default because picking one never starts anything on its own.
    assert generator - {""} == reviewer
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

    assert config.chosen_project_dir().name in window._project_btn.text()


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
    assert window._project_btn.menu().property("class") == "support-menu"


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


def test_chip_buttons_actually_render_rounded():
    """QSS said `border-radius: 12px` and Qt drew square corners, because 12 is more than half of
    the 22px these render at — an out-of-range radius is silently ignored. Declaring it is not
    the same as getting it, so this measures the pixels."""
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


def test_the_gate_mode_is_a_project_setting_and_defaults_to_asking(monkeypatch):
    """"Every write" first: narrowing it is a choice someone makes after it gets in the way, not
    a default they never saw."""
    from autosound_tcc.core import omp_session, project_settings

    _catalogue(monkeypatch, [])
    _app()
    window = MainWindow()

    assert window._gate_actions[omp_session.GATE_WRITES].isChecked()

    window._set_gate_mode(omp_session.GATE_FOREIGN)

    assert project_settings.get(config.tcc_dir(), "gate") == omp_session.GATE_FOREIGN
    assert window._gate_actions[omp_session.GATE_FOREIGN].isChecked()
    assert not window._gate_actions[omp_session.GATE_WRITES].isChecked()


def test_system_params_shows_what_tcc_itself_is_set_to():
    """Language, the two models, theme and the permission mode were only visible in the footer and
    the menus, so "which model is answering me" meant hunting for the control that sets it. They
    are system params in the same sense the mic is: chosen once, then relied on."""
    from autosound_tcc.ui.tcc import i18n

    _app()
    window = MainWindow()
    labels = [label for label, _ in window._app_config_rows()]

    assert labels == [i18n.t("cfgLanguage"), i18n.t("cfgGenerator"), i18n.t("cfgCritic"),
                      i18n.t("cfgTheme"), i18n.t("cfgGate")]


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
    from autosound_tcc.ui.tcc.main_window import _ElidedLabel, _kv_row

    _app()
    row = _kv_row("Amp (midbass (front) + center; 1 channel spare)", "Ground Zero GZA 125.4")
    row.resize(240, 30)
    row.show()
    key = row.findChild(_ElidedLabel)
    key.resize(90, 20)

    assert key.text().endswith("…")
    assert key.toolTip().startswith("Amp (midbass")


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
    assert "target curve" in said[0]
