"""The next phase in a clean session: the method's `handoff`, offered at a phase's end (hub #201)."""

from __future__ import annotations

import os
import subprocess

import pytest

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


# ---- the method's warnings (#126; S-084, hub #227) -----------------------------------------------
# `handoff --json` carries `warnings` since the method's v3.0.65: a ▶️ CONTINUE block naming a HEAD
# the ledger is not at. They never move `ok`, and TCC showed none of them.

_STALE = ("`tuning-changelog`'s ▶️ CONTINUE block names HEAD v_009, and the ledger's HEAD is v_001 "
          "(FULL) — the block was written before the ledger moved. The ledger is what resume "
          "trusts; bring the block up to it")


def test_the_methods_warnings_come_with_its_answer(tmp_path):
    """The real method, not a fake: its `warnings` key, as TCC reads it."""
    from autosound_tcc.core import vendor_loader
    from tests import _intake

    if not vendor_loader.is_available():
        pytest.skip("rew_tool submodule not checked out")
    _intake.seed(tmp_path)
    (tmp_path / "tuning-changelog.md").write_text(
        "# Tuning changelog\n\n## ▶️ CONTINUE\n- HEAD: v_009 (FULL)\n", encoding="utf-8")

    got = handoff.check(tmp_path)

    assert got is not None and len(got["warnings"]) == 1, got
    assert "HEAD v_009" in got["warnings"][0] and "v_001 (FULL)" in got["warnings"][0]


def test_an_answer_with_no_warnings_key_reads_as_none(tmp_path, monkeypatch):
    """A method before v3.0.65 says nothing of warnings: none, not an error."""
    script = tmp_path / "process.py"
    answer = {"ok": True, "missing": [], "phase": "1", "resume": "", "next_message": "продовжуй"}
    script.write_text(f"import json; print(json.dumps({answer!r}))", encoding="utf-8")
    monkeypatch.setattr(process_writer, "script_path", lambda: script)

    assert handoff.check(tmp_path)["warnings"] == []



@pytest.mark.parametrize("ok", [True, False])
def test_the_handoff_box_names_the_methods_warnings(tmp_path, monkeypatch, ok):
    """Said either way, as the method prints it either way: on a ready answer and on a refusal."""
    from autosound_tcc.ui.tcc import i18n

    window = _window(tmp_path, monkeypatch)
    monkeypatch.setattr(handoff, "check", lambda p: {
        "ok": ok, "missing": [] if ok else ["a step left todo: s3"], "phase": "1",
        "resume": "the REW session", "next_message": "продовжуй" if ok else None,
        "warnings": [_STALE]})
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    monkeypatch.setattr(window, "_open_terminal", lambda: None)

    window._on_handoff()

    lead = i18n.t("hoWarnings").split("{warnings}")[0].strip()
    assert shown and lead in shown[0] and _STALE in shown[0], shown


def test_a_handoff_with_no_warnings_says_nothing_of_them(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc import i18n

    window = _window(tmp_path, monkeypatch)
    monkeypatch.setattr(handoff, "check", lambda p: {
        "ok": False, "missing": ["a step left todo: s3"], "phase": "1", "resume": "",
        "next_message": None, "warnings": []})
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)

    window._on_handoff()

    assert shown and i18n.t("hoWarnings").split("{warnings}")[0].strip() not in shown[0]
