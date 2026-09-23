"""The next phase in a clean session: the method's `handoff`, offered at a phase's end (hub #201)."""

from __future__ import annotations

import os
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from autosound_tcc.core import config, handoff, process_writer  # noqa: E402
from autosound_tcc.state import process_view  # noqa: E402


def _state(*statuses, phase="1"):
    return {"active_phase": phase,
            "plan": [{"id": f"s{i}", "phase": phase, "status": s} for i, s in enumerate(statuses)]}


def test_a_phase_is_finished_when_no_step_is_left_open():
    assert process_view.phase_finished(_state("done", "skipped", "blocked")) == "1"
    assert process_view.phase_finished(_state("done", "todo")) is None
    assert process_view.phase_finished(_state("in_progress")) is None
    assert process_view.phase_finished(_state()) is None, "just entered: nothing planned yet"


def test_the_methods_answer_is_read_as_it_prints_it(tmp_path, monkeypatch):
    script = tmp_path / "process.py"
    answer = {"ok": False, "missing": ["open round: process.py <dir> round-close"],
              "phase": "1", "resume": "", "next_message": "продовжуй"}
    script.write_text(f"import json,sys; print(json.dumps({answer!r})); sys.exit(1)",
                      encoding="utf-8")
    monkeypatch.setattr(process_writer, "script_path", lambda: script)
    got = handoff.check(tmp_path)
    assert got["ok"] is False and got["missing"] == answer["missing"]


def test_an_older_method_is_said_as_such(tmp_path, monkeypatch):
    monkeypatch.setattr(handoff.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(
        argv, 2, "", "process.py: error: unrecognized arguments: --json"))
    monkeypatch.setattr(process_writer, "script_path", lambda: tmp_path / "process.py")
    (tmp_path / "process.py").write_text("", encoding="utf-8")
    assert handoff.check(tmp_path) is None


def _window(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc.main_window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    return MainWindow()


def test_the_offer_comes_once_per_phase(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **k: said.append(k))
    window._offer_handoff(_state("done"))
    window._offer_handoff(_state("done"))
    assert len(said) == 1 and said[0]["action"] is not None
    window._offer_handoff(_state("done", phase="2"))
    assert len(said) == 2


def test_a_ready_handoff_opens_the_next_session_with_its_first_message(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    monkeypatch.setattr(handoff, "check", lambda p: {
        "ok": True, "missing": [], "phase": "1", "resume": "the REW session", "next_message": "продовжуй"})
    opened = []
    monkeypatch.setattr(window, "_open_terminal", lambda: opened.append(1))
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: self.setProperty("_clicked", 0) or 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self.buttons()[0]
                        if self.buttons() else None)
    window._on_handoff()
    assert opened == [1]
    assert QApplication.clipboard().text() == "продовжуй"


def test_a_refused_handoff_shows_what_is_missing(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    monkeypatch.setattr(handoff, "check", lambda p: {
        "ok": False, "missing": ["a step left todo: s3"], "phase": "1", "resume": "", "next_message": ""})
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    opened = []
    monkeypatch.setattr(window, "_open_terminal", lambda: opened.append(1))
    window._on_handoff()
    assert shown and "a step left todo: s3" in shown[0]
    assert opened == []
