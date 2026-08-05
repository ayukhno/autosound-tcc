"""DialogPanel's live-agent mode, the Qt bridge, and the worker thread (W4).

The mock-rendering path is covered by `test_dialog_panel.py` and must keep working untouched --
one test here pins that, because "attaching an agent" silently breaking the design surface would
be easy to miss.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import Future

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from autosound_tcc.core import signal_bus  # noqa: E402
from autosound_tcc.core.agent_events import (  # noqa: E402
    Question,
    QuestionOption,
    TextDelta,
    ToolCall,
)
from autosound_tcc.core.mcp_server import ConfirmRequest  # noqa: E402
from autosound_tcc.core.signal_bus import SignalBus  # noqa: E402
from autosound_tcc.ui.tcc.agent_worker import AgentWorker  # noqa: E402
from autosound_tcc.ui.tcc.dialog_panel import DialogPanel  # noqa: E402
from autosound_tcc.ui.tcc.qt_bridge import QtUiBridge  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


class FakeWorker(QObject):
    chunk = Signal(object)
    turn_done = Signal()
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.sent: list[str] = []
        self.interrupted = False

    def send(self, text):
        self.sent.append(text)

    def interrupt(self):
        self.interrupted = True


def _attached(tmp_path):
    panel = DialogPanel()
    worker = FakeWorker()
    bus = SignalBus(tmp_path)
    panel.attach_agent(worker, bus, resumed=True, phase="2")
    return panel, worker, bus


def test_mock_transcript_still_renders_without_an_agent():
    panel = DialogPanel()

    assert len(panel._bubbles) == 4  # the four mock DIALOG messages
    assert panel._not_visible_btn.isHidden()


def test_attaching_an_agent_clears_the_mock_transcript(tmp_path):
    """Leaving demo bubbles above live output is how a tuner acts on a number nobody measured."""
    panel, _, _ = _attached(tmp_path)

    assert panel._bubbles == []
    assert not panel._not_visible_btn.isHidden()
    assert panel._session_chip.text().startswith("2 ·")


def test_streamed_deltas_grow_a_single_bubble(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(TextDelta("Phase 2, "))
    worker.chunk.emit(TextDelta("step 2.3."))

    assert len(panel._bubbles) == 1
    assert panel._live_text == "Phase 2, step 2.3."


def test_a_tool_call_is_a_pulse_not_a_transcript_entry(tmp_path):
    """Their whole value is "the thing is still working". Eight of them was most of a screen, and
    the process record is `process/journal.jsonl`, not this."""
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(ToolCall(name="mcp__tcc__get_tcc_state"))

    assert panel._bubbles == []
    assert not panel._activity.isHidden()
    assert "get_tcc_state" in panel._activity.text()
    assert "mcp__tcc__" not in panel._activity.text()
    assert panel._activity_timer.isActive()  # a moving line is what says "still running"


def test_text_after_a_tool_call_starts_a_new_bubble(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(TextDelta("Reading state"))
    worker.chunk.emit(ToolCall(name="get_ledger"))
    worker.chunk.emit(TextDelta("Done."))

    assert len(panel._bubbles) == 2
    assert panel._live_text == "Done."


def test_a_question_is_rendered_rather_than_swallowed(tmp_path):
    """Nothing can answer one yet, but a blocked turn must not read as a finished turn -- that is
    exactly how an unanswered question looked during the spike: a window that had hung."""
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(
        Question(
            id="q1",
            header="Reference seat",
            question="Reference seat for this tune?",
            options=(
                QuestionOption("Driver", "one point, sharpest image"),
                QuestionOption("Both front"),
            ),
        )
    )

    body = panel._bubbles[0]._body.text()
    assert "Reference seat for this tune?" in body
    assert "Driver" in body and "Both front" in body
    assert "one point, sharpest image" in body


def test_text_after_a_question_starts_a_new_bubble(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(TextDelta("Before"))
    worker.chunk.emit(Question(id="q1", question="Which seat?"))
    worker.chunk.emit(TextDelta("After"))

    assert len(panel._bubbles) == 3
    assert panel._live_text == "After"


def test_busy_state_swaps_send_for_stop(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    assert panel._send_btn.isHidden() and not panel._stop_btn.isHidden()

    worker.turn_done.emit()

    assert not panel._send_btn.isHidden() and panel._stop_btn.isHidden()
    assert panel._input.isEnabled()


def test_stop_asks_the_worker_to_interrupt(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    panel._stop_btn.click()

    assert worker.interrupted


def test_sending_shows_the_users_message_and_hands_it_to_the_worker(tmp_path):
    panel, worker, _ = _attached(tmp_path)
    worker.turn_done.emit()  # leave the busy state
    panel._input.setText("apply it")

    panel._send_btn.click()

    assert worker.sent == ["apply it"]
    assert panel._input.text() == ""
    assert panel._bubbles[-1]._body.text() == "apply it"


def test_a_failed_session_is_reported_in_the_transcript(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    worker.failed.emit("CLINotFoundError: no claude binary")

    assert "no claude binary" in panel._bubbles[-1]._body.text()
    assert not panel._send_btn.isHidden()  # usable again, not wedged in busy


def test_not_visible_button_raises_a_signal_for_the_agent(tmp_path):
    panel, _, bus = _attached(tmp_path)
    panel._input.setText("EQ band 3")

    panel._not_visible_btn.click()

    signals = bus.drain()
    assert [s.kind for s in signals] == [signal_bus.NOT_VISIBLE]
    assert signals[0].payload["note"] == "EQ band 3"


def test_param_edit_mode_reaches_the_bus_so_both_front_ends_see_it(tmp_path):
    panel, _, bus = _attached(tmp_path)

    panel._start_editing("forgot")
    panel._finish_editing()

    kinds = [(s.kind, s.payload["on"]) for s in bus.drain()]
    assert kinds == [(signal_bus.PARAM_EDIT_MODE, True), (signal_bus.PARAM_EDIT_MODE, False)]


def test_param_edit_without_an_agent_does_not_crash():
    """The mock surface has no bus; toggling the chip there must stay a no-op, not an exception."""
    panel = DialogPanel()

    panel._start_editing("manual")

    assert panel.is_editing


def test_confirmation_verdicts_are_written_into_the_transcript(tmp_path):
    panel, _, _ = _attached(tmp_path)

    panel.confirm_bar.enqueue(
        ConfirmRequest(tool="copy_helix_eq", title="t", detail="d"), Future()
    )
    panel.confirm_bar._deny.click()

    assert "copy_helix_eq" in panel._bubbles[-1]._body.text()


# ---- QtUiBridge -------------------------------------------------------------


def test_bridge_snapshot_merges_rather_than_replaces():
    """Each widget reports its own slice without knowing the whole shape."""
    bridge = QtUiBridge()

    bridge.set_snapshot(preset="FULL")
    bridge.set_snapshot(selected="m_L")

    assert bridge.snapshot() == {"preset": "FULL", "selected": "m_L"}


def test_bridge_snapshot_is_a_copy():
    bridge = QtUiBridge()
    bridge.set_snapshot(preset="FULL")

    bridge.snapshot()["preset"] = "mutated"

    assert bridge.snapshot()["preset"] == "FULL"


def test_bridge_confirmation_reaches_the_bar_and_resolves(tmp_path):
    panel, _, _ = _attached(tmp_path)
    bridge = QtUiBridge()
    bridge.confirmationRequested.connect(panel.confirm_bar.enqueue)

    future = bridge.request_confirmation(ConfirmRequest(tool="write_rew_filters", title="t", detail="d"))
    panel.confirm_bar._allow.click()

    assert future.result(timeout=1) is True


# ---- AgentWorker ------------------------------------------------------------


class FakeSession:
    def __init__(self):
        self.closed = False

    async def start(self, prompt=None):
        yield "opening"

    async def send(self, text):
        yield f"echo:{text}"

    async def close(self):
        self.closed = True


class StuckSession:
    """A turn that never ends and ignores interrupts -- the worst case shutdown has to survive."""

    def __init__(self):
        self.closed = False

    async def start(self, prompt=None):
        import asyncio

        while True:
            await asyncio.sleep(0.01)
        yield "never reached"  # noqa: B007 - makes this an async generator

    async def send(self, text):
        yield text

    async def close(self):
        self.closed = True


def test_shutdown_ends_a_worker_stuck_mid_turn():
    """Regression: on a real close this printed "QThread: Destroyed while thread is still
    running" -- the stop sentinel is only read *between* turns, so a worker in the middle of one
    never saw it and Qt tore down a live thread.

    This session ignores interrupts entirely, so it also pins the last-resort path: cancelling the
    coroutine. That must still run the session's `close()`, and must not use QThread.terminate(),
    which wedges the interpreter."""
    session = StuckSession()
    worker = AgentWorker(session_factory=lambda: session)
    worker.start()
    deadline = time.monotonic() + 5
    while worker._loop is None and time.monotonic() < deadline:
        time.sleep(0.01)

    assert worker.shutdown(timeout_ms=4000) is True
    assert not worker.isRunning()
    assert session.closed


def test_shutdown_on_a_worker_that_never_started_is_a_noop():
    assert AgentWorker(session_factory=lambda: FakeSession()).shutdown() is True


def test_worker_streams_a_turn_and_closes_the_session(qtbot_timeout=5.0):
    from PySide6.QtCore import QEventLoop, QTimer

    session = FakeSession()
    worker = AgentWorker(session_factory=lambda: session)
    received: list[object] = []
    worker.chunk.connect(received.append)

    loop = QEventLoop()
    worker.closed.connect(loop.quit)
    QTimer.singleShot(int(qtbot_timeout * 1000), loop.quit)
    worker.turn_done.connect(lambda: worker.stop())
    worker.start()
    loop.exec()
    worker.wait(3000)

    assert received == ["opening"]
    assert session.closed


# ---- Critic rendering -------------------------------------------------------


def test_an_answered_critique_becomes_a_critic_bubble(tmp_path):
    panel, _, _ = _attached(tmp_path)

    panel.add_critique(
        {"mode": "answered", "text": "Revert if #13 bloats.", "model": "Gemini 3.1 Pro"}
    )

    bubble = panel._bubbles[-1]
    assert "Revert if #13 bloats." in bubble._body.text()
    assert bubble.property("class") == "msg msg-crit"


def test_clipboard_mode_is_never_rendered_as_an_empty_critique(tmp_path):
    """The loop's value is that somebody pushed back; showing nothing as a critique hides that
    nobody has yet."""
    panel, _, _ = _attached(tmp_path)

    panel.add_critique({"mode": "clipboard", "text": "", "model": None})

    body = panel._bubbles[-1]._body.text()
    assert panel._bubbles[-1].property("class") == "msg msg-sys"
    assert "clipboard" in body.lower() or "буфер" in body.lower()


def test_a_failed_reviewer_call_shows_why(tmp_path):
    panel, _, _ = _attached(tmp_path)

    panel.add_critique({"mode": "error", "text": "", "detail": "reviewer timed out after 600s"})

    assert "timed out" in panel._bubbles[-1]._body.text()


def test_a_tool_chip_hides_the_harness_that_produced_it(tmp_path):
    """The SDK spells TCC's tools `mcp__tcc__x` and omp spells them `mcp__tcc_x`. Showing the raw
    name leaks which harness is running into every line of the transcript."""
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(ToolCall(name="mcp__tcc__get_tcc_state"))
    worker.chunk.emit(ToolCall(name="mcp__tcc_get_tcc_state"))

    for bubble in panel._bubbles:
        assert "get_tcc_state" in bubble._body.text()
        assert "mcp__" not in bubble._body.text()


def test_typing_the_first_message_asks_for_a_session(tmp_path):
    """A live composer that swallows what you type is worse than a disabled one — observed in use:
    the first message went nowhere and nothing said why."""
    panel = DialogPanel()
    asked: list[str] = []
    panel.startRequested.connect(asked.append)

    panel._input.setText("привіт")
    panel._on_send()

    assert asked == ["привіт"]
    # The text is not thrown away in favour of a canned opener; it IS the opening prompt.
    assert any("привіт" in b._body.text() for b in panel._bubbles)


def test_the_bubble_names_the_model_that_is_answering(tmp_path):
    """The mock transcript's Claude caption was still on live bubbles produced by a Gemini model,
    contradicting the footer two inches below it."""
    panel = DialogPanel()
    worker = FakeWorker()
    panel.attach_agent(worker, SignalBus(tmp_path), model="Gemini 3.1 Flash Lite")

    worker.chunk.emit(TextDelta("Phase 0."))

    assert "Gemini 3.1 Flash Lite" in panel._bubbles[-1].findChild(QLabel).text()


def test_markdown_from_the_model_is_rendered_not_shown(tmp_path):
    """Models write `**bold**` and `### heads` whether or not anyone asked, and a bubble that
    shows the asterisks makes a correct answer look like a broken one."""
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(TextDelta("### Next\n- **Phase 0** with `baseline.mdat`"))

    body = panel._bubbles[-1]._body.text()
    assert "<b>Next</b>" in body and "<b>Phase 0</b>" in body
    assert "<code>baseline.mdat</code>" in body
    assert "**" not in body and "###" not in body


def test_markup_in_the_models_text_cannot_become_markup(tmp_path):
    """A stray `<` in a filter string is text, not an element."""
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(TextDelta("HP <script>alert(1)</script> 80 Hz"))

    assert "&lt;script&gt;" in panel._bubbles[-1]._body.text()


def test_a_run_of_the_same_tool_is_counted_rather_than_repeated(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    for _ in range(6):
        worker.chunk.emit(ToolCall(name="glob"))

    assert panel._activity_label == "glob ×6"
    assert "glob ×6" in panel._activity.text()


def test_a_different_tool_replaces_the_line(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(ToolCall(name="glob"))
    worker.chunk.emit(ToolCall(name="read"))

    assert panel._activity_label == "read"


def test_the_line_clears_when_the_turn_ends(tmp_path):
    """A stale tool name under the composer would say "working" about a finished turn."""
    panel, worker, _ = _attached(tmp_path)
    worker.chunk.emit(ToolCall(name="glob"))

    worker.turn_done.emit()

    assert panel._activity.isHidden()


class _AnsweringWorker(FakeWorker):
    def __init__(self):
        super().__init__()
        self.answers: list[tuple[str, str]] = []

    def answer(self, question_id, value):
        self.answers.append((question_id, value))


def _asked(tmp_path):
    panel = DialogPanel()
    worker = _AnsweringWorker()
    panel.attach_agent(worker, SignalBus(tmp_path))
    worker.chunk.emit(
        Question(
            id="q1",
            question="Reference seat?",
            options=(QuestionOption("Driver", "one point"), QuestionOption("Both front")),
        )
    )
    return panel, worker


def test_a_question_offers_its_options_as_buttons(tmp_path):
    """The turn is parked inside the harness until it is answered, so this is not a message to
    reply to later — it is the only thing that moves the session forward."""
    panel, _ = _asked(tmp_path)

    labels = [b.text() for b in panel._question_widgets.findChildren(QPushButton)]
    assert labels == ["Driver", "Both front"]


def test_choosing_an_option_answers_through_the_same_channel(tmp_path):
    """Not `send()`: the harness is blocked inside the question, and a new user message is not
    what it is waiting for."""
    panel, worker = _asked(tmp_path)

    next(b for b in panel._question_widgets.findChildren(QPushButton) if b.text() == "Driver").click()

    assert worker.answers == [("q1", "Driver")]
    assert worker.sent == []
    assert any("Driver" in b._body.text() for b in panel._bubbles)


def test_the_buttons_go_away_once_answered(tmp_path):
    panel, _ = _asked(tmp_path)

    panel._answer_question("Driver")

    assert panel._question_widgets is None
    assert panel._pending_question is None


def test_typing_answers_the_question_rather_than_queueing_a_message(tmp_path):
    """Both harnesses append "Other (type your own)" to every question and take the typed value."""
    panel, worker = _asked(tmp_path)

    panel._input.setText("Helix DSP Ultra S")
    panel._on_send()

    assert worker.answers == [("q1", "Helix DSP Ultra S")]
    assert worker.sent == []


def test_after_answering_the_composer_sends_messages_again(tmp_path):
    panel, worker = _asked(tmp_path)
    panel._answer_question("Driver")

    panel._input.setText("what next?")
    panel._on_send()

    assert worker.sent == ["what next?"]


def test_a_live_transcript_is_not_wiped_when_the_project_looks_unfinished(tmp_path):
    """`enter_phase` writes to disk, the bridge asks the window to reload, and a project whose
    profile does not exist yet takes the "no project" branch — which used to clear the bubbles of
    a running session and leave `_live_bubble` pointing at a destroyed widget, so the next chunk
    raised inside the slot and the turn froze mid-answer."""
    panel, worker, _ = _attached(tmp_path)
    worker.chunk.emit(TextDelta("Phase −1. "))

    panel.clear_for_no_project()
    worker.chunk.emit(TextDelta("Still going."))

    assert panel._live_text == "Phase −1. Still going."
    assert len(panel._bubbles) == 1


def test_clearing_with_no_session_still_clears(tmp_path):
    panel = DialogPanel()

    panel.clear_for_no_project()

    assert panel._bubbles == []
    assert panel._live_bubble is None
