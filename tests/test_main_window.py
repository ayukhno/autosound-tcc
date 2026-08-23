"""Headless smoke test of the Qt app shell (brief §9: tests must run without a display).

Forces the offscreen QPA platform if nothing else already set one, so this runs the same way in
CI as it does locally without a real screen.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
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
    # Translated through i18n, not prettified out of the JSON key (F-006).
    assert project_kv["Virtual channels"] == "8 (1 off)"

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


def test_a_reviewer_whose_vendor_is_configured_is_not_marked(monkeypatch):
    """The same Claude entry, on a machine that has the key — the label follows the transport."""
    from autosound_tcc.core import model_choices as mc

    _catalogue(monkeypatch, [])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(mc.shutil, "which", lambda _binary: None)
    _app()
    window = MainWindow()

    claude = window._ai_critic_combo.findData("sdk:claude-opus-5")
    assert "clipboard" not in window._ai_critic_combo.itemText(claude).lower()


def test_a_gemini_reviewer_is_not_marked(monkeypatch):
    from autosound_tcc.core import model_choices as mc

    _catalogue(monkeypatch, [{
        "provider": "google", "selector": "google/gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro", "cost": {"input": 1.0, "output": 1.0},
    }])
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setattr(mc.shutil, "which", lambda _binary: None)
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

    channels = {f"ch_{i}": {"slot": chr(65 + i), "hp": {"f": 80}, "lp": {"f": 4000}}
                for i in range(11)}
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
    pushed: list[tuple] = []

    class Bus:
        open_ids: set = set()

        def push(self, kind, **payload):
            pushed.append((kind, payload))
            signal = signal_bus.Signal(kind=kind, payload=payload)
            self.open_ids.add(signal.id)
            return signal

        def is_open(self, signal_id):
            return signal_id in self.open_ids

    class Server:
        bus = Bus()

        def stop(self, timeout: float = 5.0) -> None:
            """A stand-in for the real server has to answer what the real one is asked. Since
            2026-08-12 that includes `stop()`, called from `stop_workers()` on the way out."""

    server = Server()
    window._mcp_server = server

    window._on_channel_toggle("virtual", "VRR", True)

    assert pushed == [(signal_bus.CHANNEL_TOGGLE,
                       {"group": "virtual", "channel": "VRR", "on": True})]

    # The row is now waiting on an answer, and asking again while it waits must not raise a
    # second signal -- four of them piled up that way (F-009 point 4, 2026-08-21).
    assert ("virtual", "VRR") in window._pending_toggles
    window._on_channel_toggle("virtual", "VRR", True)
    assert len(pushed) == 1, "the same request twice is one request"

    # The opposite request IS a new one: the Arbiter changed their mind, and the model has to
    # hear the thing they now want.
    window._on_channel_toggle("virtual", "VRR", False)
    assert len(pushed) == 2
    assert window._pending_toggles[("virtual", "VRR")]["on"] is False

    # Closed on the bus -- acknowledged, however it was answered -- and the wait is over.
    server.bus.open_ids.clear()
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

    class Bus:
        def push(self, kind, **payload):
            return signal_bus.Signal(kind=kind, payload=payload)

        def is_open(self, signal_id):
            return True

    class Server:
        bus = Bus()

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


def test_the_capture_series_comes_from_the_plan_not_the_ledger():
    """Naming the virtual-channel tier bumped the ledger `v_001 → v_002`, and the checklist jumped
    to series 2 before series 1 had been captured — watched twice, on two projects. The skill's own
    phase-0 steps say which round they mean: "Baseline solo: tw-L_1 (sw) + tw-L_1 (rta)"."""
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


def test_a_plan_that_names_no_series_falls_back_to_the_ledger():
    _app()
    window = MainWindow()

    class View:
        version = "v_003"

    window._view = View()

    assert window._capture_version({"active_phase": "0", "plan": []}) == 3


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
    assert i18n.t("criticSameVendor") in window._critic_warn_tip._text
    # ...and the click has the room the row does not, including what actually runs.
    assert generator.key in window._critic_warn_detail
    # The field itself is tinted, so the thing that is wrong is the thing that looks wrong.
    assert "is-warn" in str(window._ai_critic_combo.property("class"))


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


def test_no_row_repeats_what_the_row_already_says():
    """Bold says "recommended"; the label already ends in "(Low)". Both badges were dropped —
    "там є Low і хто знає на скільки він лоу" (user, 2026-08-12): a note that neither adds a fact
    nor quantifies one is width spent on nothing."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox
    from autosound_tcc.core import model_choices as mc

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
    assert i18n.t("modelInstallCli").format(cli="codex") in rows[1]
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


def test_the_title_says_when_something_newer_exists(monkeypatch):
    """The versions are already in the title, so that is where "there is a newer one" belongs —
    it is the line a person reads without being asked to (user, 2026-08-19)."""
    from autosound_tcc.core import updates

    _app()
    window = MainWindow()
    before = window.windowTitle()
    assert i18n.t("titleUpdate") not in before

    window._title_note = i18n.t("titleUpdate")
    window._set_title()

    assert i18n.t("titleUpdate") in window.windowTitle()
    assert str(config.project_dir()) in window.windowTitle(), "and the project stays first"


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
    for key in ("menuProject", "menuSession", "menuView", "menuTools", "menuHelp"):
        assert i18n.t(key).upper() in labels, key
    headings = [a for a in actions if a.text() in {i18n.t(k).upper() for k in
                ("menuProject", "menuSession", "menuView", "menuTools", "menuHelp")}]
    assert all(not a.isEnabled() for a in headings), "a heading is not a thing you can press"

    # Every act the chrome no longer carries has a home here.
    for key in ("projectOpen", "projectNew", "menuCopyCar", "riImport", "menuReload",
                "menuStartSession", "menuTerminal", "menuModels", "menuTheme",
                "menuDiagnostics", "menuTargetTool", "supportGithub", "supportMonobank"):
        assert any(i18n.t(key) in label for label in labels), key
    assert any(a.menu() and a.text() == i18n.t("gateMode") for a in actions)
    assert any(a.menu() and a.text() == i18n.t("menuLanguage") for a in actions)


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

        lang_menu = next(a.menu() for a in window._menu_btn.menu().actions()
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

