"""A17: a capture under a wrong title is fixed, not refused."""

from __future__ import annotations

import subprocess
import threading
import time

import pytest

from autosound_tcc.core import method_cli, process_writer, project_lock, title_fixes, vendor_loader


def test_a_grammar_difference_is_the_methods_rename_and_ticked():
    fixes = title_fixes.proposals(["sw_01 (sw)", "m-L_1 (sw)"], ["sw_1 (sw)", "m-L_1 (sw)"])
    assert fixes == [title_fixes.TitleFix("sw_01 (sw)", "sw_1 (sw)", "grammar")]


def test_a_typo_gets_the_nearest_missing_name_to_confirm():
    fixes = title_fixes.proposals(["r-R_1 (se)"], ["r-R_1 (sw)", "r-L_1 (sw)"])
    assert fixes == [title_fixes.TitleFix("r-R_1 (se)", "r-R_1 (sw)", "typo")]


def test_a_measurement_that_is_simply_absent_gets_no_fix():
    assert title_fixes.proposals(["m-L_1 (sw)"], ["m-L_1 (sw)", "sw_1 (sw)"]) == []


def test_another_series_is_no_typo_and_the_closest_name_wins():
    """tcc#114, finding 122: the live REW of 2026-10-01. The strip's pass took titles one by one
    and offered `sw_B1 (sw) → sw_3 (sw)` and `sw+w-L_B1 (sw) → sw+w-R_3 (sw)`: an older series is
    a measurement of its own, and only the real typo gets a name."""
    titles = ["sw_B1 (sw)", "sw+w-L_B1 (sw)", "sw+w-R_B1 (sw)", "sw+w-L_3 (se)"]
    fixes = title_fixes.proposals(titles, ["sw_3 (sw)", "sw+w-L_3 (sw)", "sw+w-R_3 (sw)"])
    assert fixes == [title_fixes.TitleFix("sw+w-L_3 (se)", "sw+w-L_3 (sw)", "typo")]


def test_supersede_calls_the_method_and_a_round_without_the_title_is_fine(tmp_path, monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "the round never took 'sw_01 (sw)'")

    monkeypatch.setattr(method_cli.child, "run_bounded", fake_run)
    done, said = title_fixes.supersede(tmp_path, "sw_01 (sw)", "sw_1 (sw)")
    assert done and "never took" in said
    argv = seen[0]
    assert argv[argv.index("capture-supersede"):] == [
        "capture-supersede", "sw_01 (sw)", "sw_1 (sw)", title_fixes.REASON]


def _bytes_of(folder) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(folder.rglob("*")) if path.is_file()}


def test_a_supersede_behind_another_write_answers_busy_and_writes_nothing(tmp_path, monkeypatch):
    """#169 N1: `capture-supersede` rewrites the open round, and it ran with no lock at all — so a
    write already under way could have its round saved over. Now it waits as every write on the
    GUI thread does (the import form calls it from the window), and past that wait it answers
    busy, with the round exactly as it was."""
    if not vendor_loader.is_available():
        pytest.skip("rew_tool submodule not checked out")
    monkeypatch.setattr(method_cli, "GUI_LOCK_WAIT_S", 0.3)
    (tmp_path / "project.json").write_text('{"schema_version": 3, "project_rev": 1}',
                                           encoding="utf-8")
    process = vendor_loader.load_process().Process(str(tmp_path / "process"))
    process.start_capture("1", ["sw_1 (sw)"])
    process.record_capture("sw_01 (sw)")  # taken under the wrong title: there is a row to fix
    held, release = threading.Event(), threading.Event()

    def holder():
        with project_lock.hold(tmp_path, timeout_s=5):
            held.set()
            release.wait(10)

    threading.Thread(target=holder, daemon=True).start()
    assert held.wait(5)
    before = _bytes_of(tmp_path / "process")
    started = time.monotonic()
    try:
        done, said = title_fixes.supersede(tmp_path, "sw_01 (sw)", "sw_1 (sw)")
    finally:
        release.set()

    assert done is False and said.startswith("busy:") and "nothing was written" in said, said
    assert time.monotonic() - started < 2.0, "it waited longer than the GUI's wait"
    assert _bytes_of(tmp_path / "process") == before


def test_each_rename_is_asked_until_a_busy_answer_and_none_after_it(tmp_path, monkeypatch):
    """`supersede_each`, which the import uses: a refusal of one title leaves the next to be asked,
    and exit 1 (the round never took it) is done, as in `supersede`. A busy answer is the one that
    stops it — every next one would wait the same wait for the same answer — and what is left is
    handed back unasked, to be named."""
    old = "this project's method does not have `capture-supersede`"
    answers = iter([process_writer.ProcessWriterError(old),
                    (1, "", "error: round r1 never took 'b'"),
                    process_writer.Busy("busy: nothing was written")])
    asked = []

    def supersede_capture(project_dir, wrong, right):
        asked.append(wrong)
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(process_writer, "supersede_capture", supersede_capture)
    refused, not_asked = title_fixes.supersede_each(
        tmp_path, [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")])

    assert asked == ["a", "b", "c"]
    assert refused == [("a", "A", old), ("c", "C", "busy: nothing was written")]
    assert not_asked == [("d", "D")]


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
