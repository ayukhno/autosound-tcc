"""The next phase in a clean session: the method's `handoff`, offered at a phase's end (hub #201)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from autosound_tcc.core import (  # noqa: E402
    config, handoff, method_binding, method_cli, process_writer, project_lock, vendor_loader,
)
from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.state import process_view  # noqa: E402


def _state(*statuses, phase="1"):
    return {"active_phase": phase,
            "plan": [{"id": f"s{i}", "phase": phase, "status": s} for i, s in enumerate(statuses)]}


def test_a_phase_is_finished_when_no_step_is_left_open():
    assert process_view.phase_finished(_state("done", "skipped", "blocked")) == "1"
    assert process_view.phase_finished(_state("done", "todo")) is None
    assert process_view.phase_finished(_state("in_progress")) is None
    assert process_view.phase_finished(_state()) is None, "just entered: nothing planned yet"


def _the_method_answers(monkeypatch, code: int, out: str = "", err: str = "") -> None:
    """The method's child, as `method_cli` runs it, exiting `code` having printed `out`/`err`."""
    monkeypatch.setattr(method_cli.child, "run_bounded", lambda argv, **k: subprocess.CompletedProcess(
        argv, code, out, err))


def test_the_methods_answer_is_read_as_it_prints_it(tmp_path, monkeypatch):
    answer = {"ok": False, "missing": ["open round: process.py <dir> round-close"],
              "phase": "1", "resume": "", "next_message": "продовжуй"}
    _the_method_answers(monkeypatch, 1, json.dumps(answer, ensure_ascii=False))
    got, why = handoff.ask(tmp_path)
    assert got["ok"] is False and got["missing"] == answer["missing"]
    assert why is None


def test_an_older_method_is_said_as_such(tmp_path, monkeypatch):
    """A method older than `handoff` answers with its usage text (`process_writer.TooOld`): no
    answer and no sentence of its own, so the window says «update the method» — the one case
    where that is the fix."""
    _the_method_answers(monkeypatch, 2, err="usage: process.py <process-dir> <command> [args]")
    assert handoff.ask(tmp_path) == (None, None)


def test_a_copy_older_than_json_is_said_as_too_old(tmp_path, monkeypatch):
    """A copy whose `process.py` does not know `--json` is refused the flag before it starts
    (`UnknownFlag`, N19): too old as well, so «update the method»."""
    from tests._method_copies import copy_of_the_method

    older = copy_of_the_method(tmp_path / "older", changes={
        "rew_tool/state/process.py": lambda text: text.replace("--json", "")})
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(older))
    monkeypatch.setattr(method_cli.child, "run_bounded",
                        lambda argv, **_k: pytest.fail(f"a child started: {argv}"))
    assert handoff.ask(tmp_path) == (None, None)


_CRASH = ("Traceback (most recent call last):\n  File \"process.py\", line 3990, in _main\n"
          "AttributeError: 'list' object has no attribute 'get'")


@pytest.mark.parametrize("child, named", [
    pytest.param(lambda argv, **_k: subprocess.CompletedProcess(argv, 1, "", _CRASH),
                 "AttributeError: 'list' object has no attribute 'get'", id="crashed"),
    pytest.param(lambda argv, **_k: subprocess.CompletedProcess(argv, 0, "ready", ""),
                 "ready", id="no JSON"),
    pytest.param(lambda argv, **_k: (_ for _ in ()).throw(subprocess.TimeoutExpired(argv, 30)),
                 "timed out", id="timed out"),
    pytest.param(lambda argv, **_k: (_ for _ in ()).throw(OSError(8, "Exec format error")),
                 "Exec format error", id="could not start"),
    pytest.param(lambda argv, **_k: subprocess.CompletedProcess(
        argv, 1, "", "error: process-state.json is not a process record"),
                 "error: process-state.json is not a process record", id="refused by the method"),
])
def test_a_handoff_that_got_no_answer_says_why_and_not_update_the_method(
        tmp_path, monkeypatch, child, named):
    """#169 review I4: a crash, a timeout, an interpreter that would not start, output that is no
    answer — each read as None, and the window said «Update the method» to a method that was
    current, which updating cannot fix. Each says what happened now, in the method's or TCC's
    words; only a method too old for the check is left to «update the method»."""
    monkeypatch.setattr(method_cli.child, "run_bounded", child)

    answer, why = handoff.ask(tmp_path)

    assert answer is None
    assert why and named in why, why
    assert "Traceback" not in why and "update the method" not in why.lower(), why


def test_a_refused_copy_of_the_method_is_said_with_its_sentence_not_as_too_old(tmp_path):
    """#169: a project whose copy of the method TCC will not run — here a real folder at its entry,
    a copy that travels with the project — is refused before any child, so `check` has no answer,
    as for a method too old for `handoff --json`. Said as «update the method», that is the wrong
    fix: the binding's sentence (re-link it, or approve it) is the one, and `refusal` answers it. A
    project the binding does not refuse has none, so a method too old is still said as such."""
    car = tmp_path / "car"
    (car / ".claude" / "skills" / vendor_loader.SKILL_NAME).mkdir(parents=True)
    binding = method_binding.for_project(car)
    assert binding.state == "refused", binding

    assert handoff.ask(car) == (None, binding.reason)


def test_a_handoff_takes_no_lock_and_makes_no_process_folder(tmp_path, monkeypatch):
    """#171: `handoff` is a READ, asked on the GUI thread, and it writes nothing either way. Behind
    the writer lock it would wait out the GUI's wait behind somebody else's write and then answer
    nothing; and the lock's flock would make `process/` in a project that has none. So it never
    asks for the lock, and `project_lock.hold` fails the test if it is called — no clock, which two
    real children on a cold runner could not keep inside the GUI's wait. The real method, so an
    answer means it ran."""
    if not vendor_loader.is_available():
        pytest.skip("rew_tool submodule not checked out")
    monkeypatch.setattr(project_lock, "hold",
                        lambda *_a, **_k: pytest.fail("the handoff read asked for the writer lock"))
    car = tmp_path / "car"
    car.mkdir()

    got, _why = handoff.ask(car)

    assert got is not None and got["ok"] is False, got  # an empty project is not ready, and it said so
    assert not (car / "process").exists()


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
    monkeypatch.setattr(handoff, "ask", lambda p: ({
        "ok": True, "missing": [], "phase": "1", "resume": "the REW session",
        "next_message": "продовжуй"}, None))
    opened = []
    monkeypatch.setattr(window, "_open_terminal", lambda: opened.append(1))
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: self.setProperty("_clicked", 0) or 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self.buttons()[0]
                        if self.buttons() else None)
    window._on_handoff()
    assert opened == [1]
    assert QApplication.clipboard().text() == "продовжуй"


def test_a_refused_handoff_shows_what_fixes_it(tmp_path, monkeypatch):
    """The method's refusal shows what is missing, item by item. A copy of the method TCC will not
    run (#169) has no answer to show, and «update the method» fixes nothing there: the window says
    the binding's sentence instead — and a method that crashed says the crash (#169 review I4),
    where «update the method» fixes nothing either. One window for all, as the ratchet asks."""
    ask = handoff.ask
    window = _window(tmp_path, monkeypatch)
    monkeypatch.setattr(handoff, "ask", lambda p: ({
        "ok": False, "missing": ["a step left todo: s3"], "phase": "1", "resume": "",
        "next_message": ""}, None))
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    opened = []
    monkeypatch.setattr(window, "_open_terminal", lambda: opened.append(1))
    window._on_handoff()
    assert shown and "a step left todo: s3" in shown[0]
    assert opened == []

    monkeypatch.setattr(handoff, "ask", ask)  # the real one, on a project the binding refuses
    (tmp_path / ".claude" / "skills" / vendor_loader.SKILL_NAME).mkdir(parents=True)
    said = []
    monkeypatch.setattr(window._status_strip, "notify", lambda text, **k: said.append((text, k)))
    window._on_handoff()
    assert said == [(method_binding.for_project(tmp_path).reason, {"level": "warn"})], said
    assert len(shown) == 1, "no box: there was no answer to show"

    shutil.rmtree(tmp_path / ".claude")  # TCC's own copy again, and it crashes
    monkeypatch.setattr(process_writer, "handoff_json", lambda p: (1, "", _CRASH))
    said.clear()
    window._on_handoff()
    [(text, how)] = said
    assert "AttributeError: 'list' object has no attribute 'get'" in text and how == {"level": "warn"}
    assert text != i18n.t("hoTooOld"), "updating the method does not mend a crash"
    assert len(shown) == 1


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

    got, _why = handoff.ask(tmp_path)

    assert got is not None and len(got["warnings"]) == 1, got
    assert "HEAD v_009" in got["warnings"][0] and "v_001 (FULL)" in got["warnings"][0]


def test_an_answer_with_no_warnings_key_reads_as_none(tmp_path, monkeypatch):
    """A method before v3.0.65 says nothing of warnings: none, not an error."""
    answer = {"ok": True, "missing": [], "phase": "1", "resume": "", "next_message": "продовжуй"}
    _the_method_answers(monkeypatch, 0, json.dumps(answer, ensure_ascii=False))

    assert handoff.ask(tmp_path)[0]["warnings"] == []


@pytest.mark.parametrize("ok", [True, False])
def test_the_handoff_box_names_the_methods_warnings(tmp_path, monkeypatch, ok):
    """Said either way, as the method prints it either way: on a ready answer and on a refusal."""
    from autosound_tcc.ui.tcc import i18n

    window = _window(tmp_path, monkeypatch)
    monkeypatch.setattr(handoff, "ask", lambda p: ({
        "ok": ok, "missing": [] if ok else ["a step left todo: s3"], "phase": "1",
        "resume": "the REW session", "next_message": "продовжуй" if ok else None,
        "warnings": [_STALE]}, None))
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    monkeypatch.setattr(window, "_open_terminal", lambda: None)

    window._on_handoff()

    lead = i18n.t("hoWarnings").split("{warnings}")[0].strip()
    assert shown and lead in shown[0] and _STALE in shown[0], shown


def test_a_handoff_with_no_warnings_says_nothing_of_them(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc import i18n

    window = _window(tmp_path, monkeypatch)
    monkeypatch.setattr(handoff, "ask", lambda p: ({
        "ok": False, "missing": ["a step left todo: s3"], "phase": "1", "resume": "",
        "next_message": None, "warnings": []}, None))
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)

    window._on_handoff()

    assert shown and i18n.t("hoWarnings").split("{warnings}")[0].strip() not in shown[0]
