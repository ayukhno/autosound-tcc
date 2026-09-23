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


def test_the_import_form_fills_found_names_and_leaves_them_unticked(tmp_path):
    """«Нове ім'я після пошуку і ідентифікації збіжності попадає в колонку "нове ім'я" … галочку
    треба поставити користувачу свідомо, бо це автоматичний підбір» (the Arbiter, 2026-09-23)."""
    from autosound_tcc.core import capture_import

    rows = [capture_import.Candidate(ordinal=str(i), title=t, uuid=u, date="", when=None,
                                     imported=False)
            for i, (t, u) in enumerate((("m-L_1 (sw)", "a"), ("sw_01 (sw)", "b"),
                                        ("r-R_1 (se)", "c")))]
    picked = capture_import.preselect(rows, ["m-L_1 (sw)", "sw_1 (sw)", "r-R_1 (sw)"], tmp_path)
    assert picked.ticked == frozenset({"a"}), "only a title that is already right comes ticked"
    assert picked.names["b"] == "sw_1 (sw)" and picked.names["c"] == "r-R_1 (sw)"
    assert picked.proposed == frozenset({"b", "c"})


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
    assert said[0][1]["action"][1] == window._meas_panel.open_import, \
        "the fix is made in the import form"


def test_a_curve_that_is_not_there_is_waiting_not_bad():
    """«Червона — тільки для тих кривих, які є, але браковані; якщо кривої немає — жовта»."""
    from autosound_tcc.state import measurement_view

    assert measurement_view.absent({"ok": False, "issues": ["No measurement titled 'sw_1 (sw)'"]})
    assert not measurement_view.absent({"ok": False, "issues": ["silence in band 20-80 Hz"]})


def test_the_strip_does_not_call_an_absent_curve_unusable(tmp_path, monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc.main_window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    window = MainWindow()
    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **k: said.append(text))
    window._on_capture_check_done("UNUSABLE sw_1 (sw) — No measurement titled 'sw_1 (sw)'")
    assert said == []
    window._on_capture_check_done("UNUSABLE m-L_1 (sw) — silence in band")
    assert said and "m-L_1 (sw)" in said[0]
