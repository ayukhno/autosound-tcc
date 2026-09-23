"""A17: a capture under a wrong title is fixed, not refused."""

from __future__ import annotations

import subprocess

from autosound_tcc.core import process_writer, title_fixes


def test_a_grammar_difference_is_the_methods_rename_and_ticked():
    fixes = title_fixes.proposals(["sw_01 (sw)", "m-L_1 (sw)"], ["sw_1 (sw)", "m-L_1 (sw)"])
    assert fixes == [title_fixes.TitleFix("sw_01 (sw)", "sw_1 (sw)", "grammar")]


def test_a_typo_gets_the_nearest_missing_name_to_confirm():
    fixes = title_fixes.proposals(["r-R_1 (se)"], ["r-R_1 (sw)", "r-L_1 (sw)"])
    assert fixes == [title_fixes.TitleFix("r-R_1 (se)", "r-R_1 (sw)", "typo")]


def test_a_measurement_that_is_simply_absent_gets_no_fix():
    assert title_fixes.proposals(["m-L_1 (sw)"], ["m-L_1 (sw)", "sw_1 (sw)"]) == []


def test_a_fix_counts_only_when_rew_shows_it_done():
    fix = title_fixes.TitleFix("sw_01 (sw)", "sw_1 (sw)", "grammar")
    assert title_fixes.confirmed([fix], ["sw_1 (sw)"]) == [fix]
    assert title_fixes.confirmed([fix], ["sw_1 (sw)", "sw_01 (sw)"]) == []
    assert title_fixes.confirmed([fix], ["sw_01 (sw)"]) == []


def test_supersede_calls_the_method_and_a_round_without_the_title_is_fine(tmp_path, monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "the round never took 'sw_01 (sw)'")

    monkeypatch.setattr(title_fixes.subprocess, "run", fake_run)
    monkeypatch.setattr(process_writer, "script_path", lambda: tmp_path / "process.py")
    done, said = title_fixes.supersede(tmp_path, "sw_01 (sw)", "sw_1 (sw)")
    assert done and "never took" in said
    argv = seen[0]
    assert argv[argv.index("capture-supersede"):] == [
        "capture-supersede", "sw_01 (sw)", "sw_1 (sw)", title_fixes.REASON]


def test_the_worker_renames_reads_back_then_records(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc.title_fix_dialog import TitleFixWorker

    class _Rew:
        def __init__(self):
            self.titles = {"1": "sw_01 (sw)", "2": "m-L_1 (sw)"}

        def find_id(self, title):
            return next(k for k, v in self.titles.items() if v == title)

        def rename_measurement(self, mid, title):
            self.titles[mid] = title

        def measurements(self):
            return {k: {"title": v} for k, v in self.titles.items()}

    recorded = []
    monkeypatch.setattr(title_fixes, "supersede",
                        lambda p, w, r: recorded.append((w, r)) or (True, "superseded"))
    fix = title_fixes.TitleFix("sw_01 (sw)", "sw_1 (sw)", "grammar")
    worker = TitleFixWorker(_Rew(), [fix], tmp_path)
    got = []
    worker.done.connect(lambda good, said: got.append((good, said)))
    worker.run()
    assert got and got[0][0] == [fix]
    assert recorded == [("sw_01 (sw)", "sw_1 (sw)")], "REW first, then the round"


def test_a_typo_is_offered_unticked(monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.title_fix_dialog import TitleFixDialog

    QApplication.instance() or QApplication([])
    fixes = [title_fixes.TitleFix("sw_01 (sw)", "sw_1 (sw)", "grammar"),
             title_fixes.TitleFix("r-R_1 (se)", "r-R_1 (sw)", "typo")]
    dialog = TitleFixDialog(fixes)
    assert dialog.chosen() == [fixes[0]]


def test_the_window_offers_the_fix_once_for_the_same_list(tmp_path, monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc.main_window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    window = MainWindow()
    monkeypatch.setattr(window._meas_panel, "rew_titles", lambda: ["sw_01 (sw)"])
    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **k: said.append((text, k)))
    window._offer_title_fixes({"expected": ["sw_1 (sw)"]})
    window._offer_title_fixes({"expected": ["sw_1 (sw)"]})
    assert len(said) == 1 and "sw_01 (sw) → sw_1 (sw)" in said[0][0]
    assert said[0][1]["action"] is not None
