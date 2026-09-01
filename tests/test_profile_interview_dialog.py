"""The onboarding window: what it shows while a turn runs, and what it leaves behind.

Both defects it is asserted against were watched happening on Windows on 2026-09-01 (`SKL-008`,
`SKL-009`): a completed interview that the window never rendered, and a model's Markdown printed
with its asterisks, its options glued into one paragraph, and answers typed into a one-line field.

The real `_AgentWorker` spins up a Claude Agent SDK session, which has no place in a test — it is
replaced by a fake carrying the same four signals, so everything below exercises the window's own
half of the contract.
"""

from __future__ import annotations

import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import app_log  # noqa: E402
from autosound_tcc.ui.tcc import i18n, profile_interview_dialog as pid  # noqa: E402
from autosound_tcc.ui.tcc.chat_text import ComposerInput  # noqa: E402

#: Windows built by the current test, kept alive for the same reason `test_curve_view` keeps its
#: own: PySide collects parentless Qt objects at a moment of its choosing.
_KEEP: list = []


class _FakeWorker(QObject):
    """The four signals the dialog listens to, and nothing behind them."""

    chunk = Signal(str)
    turn_done = Signal()
    profile_saved = Signal(str)
    failed = Signal(str)

    def __init__(self, *_args, **_kwargs) -> None:
        super().__init__()
        self.sent: list[str] = []
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def send(self, text: str) -> None:
        self.sent.append(text)

    def stop(self) -> None:
        self.stopped = True

    def wait(self, _ms: int = 0) -> bool:
        return True


@pytest.fixture
def dialog(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(pid, "_AgentWorker", _FakeWorker)
    window = pid.ProfileInterviewDialog(tmp_path, "Musway", "M6V4")
    _KEEP.append(window)
    return window


def _text(window) -> str:
    return window._transcript.toPlainText()


def test_a_turn_is_visible_while_it_is_still_being_spoken(dialog):
    """The whole of SKL-009 in one assertion. `_on_chunk` used to only accumulate, and the bubble
    was appended from `_on_turn_done` alone — so a turn whose stream never finished left NO trace,
    and the window looked exactly as it does while thinking. A completed interview was lost that
    way: profile written 15:17:36, closing summary produced 15:17:59, never rendered."""
    dialog._worker.chunk.emit("Питання 1. ")
    dialog._worker.chunk.emit("Скільки каналів?")

    assert "Питання 1. Скільки каналів?" in _text(dialog), "before the turn is over"
    assert i18n.t("generator") in _text(dialog), "and under a byline"

    dialog._worker.turn_done.emit()
    assert "Питання 1. Скільки каналів?" in _text(dialog), "and it is still there afterwards"


def test_markdown_is_rendered_and_the_options_do_not_glue_together(dialog):
    """SKL-008: the text went into `QTextEdit.append` as HTML, so `**bold**` kept its asterisks
    and the newlines between a question's options were not line breaks at all — three choices
    arrived as one paragraph, in an interview whose questions ARE their options."""
    dialog._worker.chunk.emit("**Питання 1 — рівні:**\n- (a) базовий\n- (b) повний\n- (c) свій")
    dialog._worker.turn_done.emit()

    shown = _text(dialog)
    assert "**" not in shown, "the asterisks are markup, not text"
    assert "Питання 1 — рівні:" in shown
    lines = [line.strip() for line in shown.splitlines() if "(" in line]
    assert len(lines) == 3, f"one line per option, got: {lines}"


def test_a_half_streamed_bold_run_is_not_printed_as_asterisks(dialog):
    """Markdown does not survive being cut into chunks: `**bold**` arrives as `**bo` + `ld**`."""
    dialog._worker.chunk.emit("це **ва")
    dialog._worker.chunk.emit("жливо**, запиши")
    dialog._worker.turn_done.emit()

    assert "це важливо, запиши" in _text(dialog)


def test_the_written_profile_is_said_in_the_conversation(dialog, tmp_path):
    """It used to be the status label alone — the one part of the window a tuner reading the
    transcript is not looking at. Eighty-nine seconds after the profile was written, the tuner was
    in another window asking whether one existed."""
    path = str(tmp_path / "dsp_profile.json")

    dialog._worker.profile_saved.emit(path)

    shown = _text(dialog)
    assert path in shown, "where it was written, in the transcript"
    assert i18n.t("interviewDone") in shown, "and that the interview is over"


def test_the_answer_box_is_the_same_one_the_main_dialog_uses(dialog):
    """A `QLineEdit` flattens a paste, and an equipment list pasted into the interview arrived as
    one run-on line — the structure the model needed to read it was gone."""
    assert isinstance(dialog._composer, ComposerInput)

    dialog._composer.setText("m-L: 6.5\nm-R: 6.5")
    assert "\n" in dialog._composer.text(), "the newlines survive"


def test_an_answer_leaves_the_window_and_lands_in_the_transcript(dialog):
    dialog._set_input_enabled(True)
    dialog._composer.setText("13. матриця all_inputs × all_outputs")

    dialog._on_send()

    assert dialog._worker.sent == ["13. матриця all_inputs × all_outputs"]
    assert "матриця all_inputs × all_outputs" in _text(dialog)
    assert dialog._composer.text() == "", "and the box is empty for the next one"


def test_the_interview_writes_its_own_trail_at_info(tmp_path, monkeypatch, caplog):
    """SKL-009's second half. The run left 88 log lines, 34 of them Qt's own, and not one record
    that a half-hour interview had happened: level and rotation were configured, the calls were
    missing."""
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(pid, "_AgentWorker", _FakeWorker)

    with caplog.at_level(logging.INFO, logger=app_log.LOGGER_NAME):
        window = pid.ProfileInterviewDialog(tmp_path, "Musway", "M6V4")
        _KEEP.append(window)
        window._worker.chunk.emit("двадцять символів!!")
        window._worker.turn_done.emit()
        window._worker.profile_saved.emit(str(tmp_path / "dsp_profile.json"))

    lines = [record.getMessage() for record in caplog.records]
    assert any(line.startswith("onboarding window opened") for line in lines), lines
    assert any(line.startswith("onboarding turn delivered") for line in lines), lines
    assert any(line.startswith("onboarding profile written") for line in lines), lines
