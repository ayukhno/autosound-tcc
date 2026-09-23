"""Both layouts of the register (hub #195), and saved configurations (hub #198, SKL-052)."""

from __future__ import annotations

import json
import os
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import config_writer  # noqa: E402
from autosound_tcc.state import ledger_line  # noqa: E402


def _arbiter_example(root):
    """The Arbiter's own example (2026-09-23): v_003 saved into preset 1 as SQ-1; FULL-1 into
    preset 2 as v_004, its rear changed into v_005; back on SQ-1, refined into SQ-2 = v_006."""
    versions = root / "versions"
    versions.mkdir(parents=True)
    parents = {"v_001": None, "v_002": "v_001", "v_003": "v_002", "v_004": "v_003",
               "v_005": "v_004", "v_006": "v_003"}
    presets = {"v_004": "FULL", "v_005": "FULL"}
    for version, parent in parents.items():
        (versions / f"{version}.json").write_text(json.dumps(
            {"version": version, "preset": presets.get(version, "SQ"), "parent": parent}),
            encoding="utf-8")
    (root / "slots.json").write_text(json.dumps({
        "active": "SQ", "layout": "project-numbered",
        "slots": {"SQ": {"version": "v_006", "dsp_preset": 1},
                  "FULL": {"version": "v_005", "dsp_preset": 2}},
        "configs": {
            "SQ-1": {"version": "v_003", "slot": "SQ", "saved": "2026-09-20T10:00:00",
                     "previous": None, "history": [{"version": "v_003", "saved": "2026-09-20"}]},
            "FULL-1": {"version": "v_004", "slot": "FULL", "saved": "2026-09-21T10:00:00",
                       "purpose": "the whole car", "previous": {"code": "SQ-1", "version": "v_003"},
                       "history": [{"version": "v_004", "saved": "2026-09-21"}]},
            "SQ-2": {"version": "v_006", "slot": "SQ", "saved": "2026-09-22T10:00:00",
                     "purpose": "sound quality", "previous": {"code": "SQ-1", "version": "v_003"},
                     "history": [{"version": "v_006", "saved": "2026-09-22"}]},
        },
    }), encoding="utf-8")


def _old_layout(root):
    for preset, numbers in (("SQ", (1, 2, 3)), ("FULL", (1, 2))):
        folder = root / preset
        folder.mkdir(parents=True)
        for n in numbers:
            (folder / f"v_{n:03d}.json").write_text("{}", encoding="utf-8")
        (folder / "HEAD").write_text(f"v_{numbers[-1]:03d}\n", encoding="utf-8")


def test_the_previous_configuration_is_its_ancestry_not_the_number_below(tmp_path):
    """«Показ порівняння з попереднім має брати v_003, а не v_005» (the Arbiter, 2026-09-23)."""
    _arbiter_example(tmp_path)
    assert ledger_line.previous_of(tmp_path, "SQ", "v_006") == "v_003"


def test_a_version_never_saved_is_compared_with_its_parent(tmp_path):
    _arbiter_example(tmp_path)
    assert ledger_line.previous_of(tmp_path, "FULL", "v_005") == "v_004"


def test_the_old_layout_keeps_the_number_below_in_its_own_preset(tmp_path):
    _old_layout(tmp_path)
    assert not ledger_line.is_project_line(tmp_path)
    assert ledger_line.previous_of(tmp_path, "SQ", "v_003") == "v_002"
    assert ledger_line.previous_of(tmp_path, "SQ", "v_001") is None
    assert ledger_line.configs(tmp_path) == {}


def test_presets_watches_and_proposals_follow_the_layout(tmp_path):
    new, old = tmp_path / "new", tmp_path / "old"
    _arbiter_example(new)
    _old_layout(old)
    assert ledger_line.presets(new) == ["FULL", "SQ"]
    assert ledger_line.presets(old) == ["FULL", "SQ"]
    assert ledger_line.watched_files(new, ["SQ"]) == [str(new / "slots.json")]
    assert ledger_line.watched_files(old, ["SQ"]) == [str(old / "SQ" / "HEAD")]
    assert str(new / "versions") in ledger_line.watched_dirs(new, ["SQ"])
    assert ledger_line.proposals_dir(new, "SQ") == new / "proposals"
    assert ledger_line.proposals_dir(old, "SQ") == old / "SQ" / "proposals"
    assert ledger_line.versions(new, "SQ") == [f"v_{n:03d}" for n in range(1, 7)], \
        "on the project line every version is offered: a previous may be another slot's"


def test_a_version_is_named_by_what_it_was_saved_under(tmp_path):
    _arbiter_example(tmp_path)
    assert ledger_line.label(tmp_path, "v_003") == "v_003 · SQ-1"
    assert ledger_line.label(tmp_path, "v_005") == "v_005"
    code, rec = ledger_line.config_of(tmp_path, "v_006")
    assert code == "SQ-2" and rec["purpose"] == "sound quality"
    assert ledger_line.dsp_preset(tmp_path, "SQ") == "1"


def test_the_window_compares_with_the_previous_configuration_by_default(tmp_path, monkeypatch):
    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc.main_window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    root = tmp_path / "ledger"
    _arbiter_example(root)
    window = MainWindow()
    window._offer_compare(root, "SQ", {}, "v_006")
    combo = window._detail._compare_combo
    assert combo.currentData() == "v_003", "SQ-2 continues SQ-1, not v_005"
    assert "SQ-1" in combo.currentText()


def test_a_save_goes_through_the_method_with_its_arguments(tmp_path, monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "SQ-2 = v_006 in slot SQ (DSP preset 1)\n", "")

    monkeypatch.setattr(config_writer.subprocess, "run", fake_run)
    result = config_writer.save(tmp_path, "v_006", "SQ-2", slot="SQ", dsp_preset="1",
                                purpose="sound quality")
    assert result.saved and result.said.startswith("SQ-2 = v_006")
    argv = seen[0]
    assert argv[argv.index("--root") + 1] == str(tmp_path)
    assert argv[argv.index("config"):argv.index("config") + 4] == ["config", "save", "v_006", "SQ-2"]
    assert argv[argv.index("--dsp-preset") + 1] == "1"


def test_a_method_without_config_is_said_as_too_old(tmp_path, monkeypatch):
    monkeypatch.setattr(config_writer.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(
        argv, 2, "", "state.py: error: argument cmd: invalid choice: 'config' (choose from ...)"))
    result = config_writer.save(tmp_path, "v_006", "SQ-2")
    assert not result.saved and result.too_old


def test_the_form_offers_the_device_preset_it_was_last_saved_to(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc.save_config_dialog import SaveConfigDialog

    QApplication.instance() or QApplication([])
    _arbiter_example(tmp_path)
    calls = []
    monkeypatch.setattr(config_writer, "save", lambda *a, **k: calls.append((a, k)) or
                        config_writer.SaveResult(True, "SQ-2 = v_006 in slot SQ"))
    dialog = SaveConfigDialog(tmp_path, "v_006", "SQ", ["FULL", "SQ"])
    assert dialog._name.text() == "SQ-2", "a version already saved opens with its name"
    assert dialog._dsp_preset.text() == "1"
    dialog._on_save()
    assert calls and calls[0][1]["slot"] == "SQ" and calls[0][1]["dsp_preset"] == "1"
    assert dialog.said == "SQ-2 = v_006 in slot SQ"


def test_the_dsp_header_names_the_configuration_in_the_processor(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc.main_window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    root = tmp_path / "ledger"
    _arbiter_example(root)
    monkeypatch.setattr(config, "state_root", lambda *_a, **_k: root)
    window = MainWindow()
    view = SimpleNamespace(version="v_006", state="applied", status_counts=(), preset="SQ")
    window._show_version(view, {"dsp_profile": {"vendor": "Audiotec", "name": "Helix"}})
    assert window._dsp_section.sub_text() == "SQ-2 · v_006"
    assert not window._cfg_btn.isHidden(), "the save is offered on the per-project line"
