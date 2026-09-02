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
    QuestionWithdrawn,
    TextDelta,
    ToolCall,
)
from autosound_tcc.core.mcp_server import ConfirmRequest  # noqa: E402
from autosound_tcc.core.signal_bus import SignalBus  # noqa: E402
from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.agent_worker import AgentWorker  # noqa: E402
from autosound_tcc.ui.tcc.dialog_panel import DialogPanel, MessageBubble  # noqa: E402
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
    # The label that explains itself keeps its line; the bare one is left to its button.
    assert "one point, sharpest image" in body
    assert "Both front" not in body


def test_text_after_a_question_starts_a_new_bubble(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(TextDelta("Before"))
    worker.chunk.emit(Question(id="q1", question="Which seat?"))
    worker.chunk.emit(TextDelta("After"))

    assert len(panel._bubbles) == 3
    assert panel._live_text == "After"


def test_stop_appears_beside_send_rather_than_replacing_it(tmp_path):
    """Send used to be hidden for the length of the turn, which left Enter as the only way to say
    anything and nothing on screen saying so. It stays: mid-turn it queues."""
    panel, worker, _ = _attached(tmp_path)

    assert not panel._send_btn.isHidden() and not panel._stop_btn.isHidden()

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

    signals = bus.deliver()
    assert [s.kind for s in signals] == [signal_bus.NOT_VISIBLE]
    assert signals[0].payload["note"] == "EQ band 3"


def test_param_edit_mode_reaches_the_bus_so_both_front_ends_see_it(tmp_path):
    panel, _, bus = _attached(tmp_path)

    panel._start_editing("forgot")
    panel._finish_editing()

    kinds = [(s.kind, s.payload["on"]) for s in bus.deliver()]
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


def test_attaching_an_agent_gives_the_worker_the_bus(tmp_path):
    """F-009: the bus has to reach the session so un-acked signals ride into every turn, and the
    panel is the one place that holds both the worker and the bus."""
    panel, worker, bus = _attached(tmp_path)

    assert worker.bus is bus


def test_the_worker_hands_the_bus_to_the_session_it_builds(tmp_path, qtbot_timeout=5.0):
    """The other half of the F-009 wiring: the session only exists on the worker's own thread,
    so the hand-off happens there -- attach before start, inject after construction."""
    from PySide6.QtCore import QEventLoop, QTimer

    class BusSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.bus = None  # the attribute both real sessions expose for injection

    session = BusSession()
    worker = AgentWorker(session_factory=lambda: session)
    bus = SignalBus(tmp_path)
    worker.bus = bus

    loop = QEventLoop()
    worker.closed.connect(loop.quit)
    QTimer.singleShot(int(qtbot_timeout * 1000), loop.quit)
    worker.turn_done.connect(lambda: worker.stop())
    worker.start()
    loop.exec()
    worker.wait(3000)

    assert session.bus is bus


# ---- Critic rendering -------------------------------------------------------


def test_an_answered_critique_becomes_a_critic_bubble(tmp_path):
    panel, _, _ = _attached(tmp_path)

    panel.add_critique(
        {"mode": "answered", "text": "Revert if #13 bloats.", "model": "Gemini 3.1 Pro"}
    )

    bubble = panel._bubbles[-1]
    assert "Revert if #13 bloats." in bubble._body.text()
    assert bubble.property("class") == "msg msg-crit"


def test_a_critique_is_rendered_as_markdown_like_every_other_bubble(tmp_path):
    """User, 2026-08-11: a structured three-page critique arrived as one flat paragraph with its
    asterisks showing. `add_critique` was the one call site passing raw model output in as rich
    text — so newlines collapsed, `**bold**` stayed literal, and a `<` would have been markup."""
    panel, _, _ = _attached(tmp_path)

    panel.add_critique({
        "mode": "answered",
        "model": "Gemini 3.1 Pro",
        "text": "**Strongest objection:** the 9.67 ms peak\n- anchor on `tw-L`\n- a < b",
    })

    body = panel._bubbles[-1]._body.text()
    assert "<b>Strongest objection:</b>" in body
    assert "**" not in body
    assert "<br>" in body            # the line structure survived
    assert "<code>tw-L</code>" in body
    assert "a &lt; b" in body        # ...and nothing in the reply can become markup


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
    """Not as an answer to the question that is gone. The turn is still running, so it goes out at
    the boundary — see `test_typing_mid_turn_is_queued_rather_than_refused`."""
    panel, worker = _asked(tmp_path)
    panel._answer_question("Driver")

    panel._input.setText("what next?")
    panel._on_send()
    panel._on_turn_done()

    assert worker.sent == ["what next?"]
    assert worker.answers == [("q1", "Driver")]


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


def test_a_pasted_list_keeps_its_lines(tmp_path):
    """It was a QLineEdit, which silently flattens a paste: an equipment list arrived as one
    run-on paragraph and the structure the model needed was gone."""
    panel, worker, _ = _attached(tmp_path)
    panel._on_turn_done()  # the opening turn is over; this one goes straight out
    pasted = "DSP:\n    Helix DSP Ultra S\n    Helix BT HD\nСаб:\n    Закритий ящик 35л"

    panel._input.setText(pasted)
    panel._on_send()

    assert worker.sent == [pasted]
    body = panel._bubbles[-1]._body.text()
    assert body.count("<br>") == 4
    assert "&nbsp;" in body  # the indentation is what carries the nesting


def test_shift_enter_makes_a_line_instead_of_sending(tmp_path):
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QKeyEvent

    panel, worker, _ = _attached(tmp_path)
    panel._input.setText("first")

    panel._input.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, _Qt.Key.Key_Return,
                  _Qt.KeyboardModifier.ShiftModifier, "\n")
    )

    assert worker.sent == []


def test_enter_sends(tmp_path):
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QKeyEvent

    panel, worker, _ = _attached(tmp_path)
    panel._on_turn_done()
    panel._input.setText("go")

    panel._input.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, _Qt.Key.Key_Return,
                  _Qt.KeyboardModifier.NoModifier, "\r")
    )

    assert worker.sent == ["go"]


def test_options_without_a_description_are_not_printed_twice(tmp_path):
    """omp's question frame carries labels only, so listing them above buttons that say the same
    words is the same words twice."""
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(
        Question(id="q", question="Which language?",
                 options=(QuestionOption("English (EN)"), QuestionOption("Українська (UK)")))
    )

    body = panel._bubbles[-1]._body.text()
    assert "Which language?" in body
    assert "English (EN)" not in body  # the button says it
    labels = [b.text() for b in panel._question_widgets.findChildren(QPushButton)]
    assert labels == ["English (EN)", "Українська (UK)"]


def test_an_option_that_explains_itself_keeps_its_line(tmp_path):
    """A description is worth its line and a button cannot hold it."""
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(
        Question(id="q", question="Reference seat?",
                 options=(QuestionOption("Driver", "one point, sharpest image"),
                          QuestionOption("Both front")))
    )

    body = panel._bubbles[-1]._body.text()
    assert "one point, sharpest image" in body
    assert "Both front" not in body  # no description: the button is enough


def test_a_question_with_no_options_is_answered_by_typing(tmp_path):
    """omp asks free-text questions; the composer is the answer, and it must not queue a message
    the blocked harness will never read."""
    panel = DialogPanel()
    worker = _AnsweringWorker()
    panel.attach_agent(worker, SignalBus(tmp_path))
    worker.chunk.emit(Question(id="q9", question="Which car?"))

    assert panel._question_widgets.findChildren(QPushButton) == []

    panel._input.setText("VW Passat B8 LHD")
    panel._on_send()

    assert worker.answers == [("q9", "VW Passat B8 LHD")]
    assert worker.sent == []


def test_the_field_is_never_switched_off(tmp_path):
    """It used to grey out for the length of the turn, and a turn is minutes long. The agent asks
    for things in prose as often as through `ask` — "share your preferences and system details"
    arrives as a paragraph — so the field was off exactly when there was something to say."""
    panel, worker, _ = _attached(tmp_path)
    panel._set_busy(True)
    assert panel._input.isEnabled()

    worker.chunk.emit(Question(id="q", question="Which car?"))

    assert panel._input.isEnabled()


def test_stop_withdraws_the_question_because_abort_does_not_reach_it(tmp_path):
    """omp is blocked inside `ask`, so Stop did nothing at all — reported that way."""
    panel = DialogPanel()
    worker = _AnsweringWorker()
    worker.cancelled = []
    worker.cancel_question = worker.cancelled.append
    panel.attach_agent(worker, SignalBus(tmp_path))
    worker.chunk.emit(Question(id="q7", question="Which car?"))

    panel._on_stop()

    assert worker.cancelled == ["q7"]
    assert panel._pending_question is None
    assert panel._question_widgets is None


def test_stop_without_a_question_still_interrupts(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    panel._on_stop()

    assert worker.interrupted


def test_a_question_with_no_options_says_it_wants_typing(tmp_path):
    """The card for a free-text question has no buttons, so without a line saying so it is a grey
    bubble like any other and the only cue is a placeholder in the composer. That is the question
    a live session sat on for eight minutes before the Arbiter gave up and hit Stop — the frame
    log has the 471-second gap."""
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(Question(id="q9", question="Which car and DSP?"))

    body = panel._bubbles[-1]._body.text()
    assert i18n.t("questionFreeText") in body
    assert panel._input.isEnabled()


def test_a_question_with_options_does_not_repeat_the_typing_hint(tmp_path):
    """There are buttons to click; "type your answer" would be telling them to do the long thing."""
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(
        Question(id="q", question="Reference seat?",
                 options=(QuestionOption(label="Driver"), QuestionOption(label="Both front")))
    )

    assert i18n.t("questionFreeText") not in panel._bubbles[-1]._body.text()


def test_a_parked_question_says_who_is_being_waited_on(tmp_path):
    """"Working…" while the harness is blocked inside `ask` is the window blaming the model for
    its own silence — and "it is working" is exactly what the Arbiter reads as a hang."""
    panel, worker, _ = _attached(tmp_path)
    panel._set_busy(True)
    assert panel._sub_label.text() == i18n.t("agentThinking")

    worker.chunk.emit(Question(id="q", question="Which car?"))

    assert panel._sub_label.text() == i18n.t("questionWaiting")

    panel._answer_question("VW Passat")

    assert panel._sub_label.text() == i18n.t("agentThinking")


def test_a_question_the_harness_takes_back_stops_asking(tmp_path):
    """omp withdraws its own frames (`method: "cancel"`, `targetId`), and it does so on every
    abort. Buttons that answer a frame omp has moved past are worse than no buttons: the answer is
    taken, dropped, and the turn looks like it ignored the Arbiter."""
    panel = DialogPanel()
    worker = _AnsweringWorker()
    panel.attach_agent(worker, SignalBus(tmp_path))
    worker.chunk.emit(Question(id="q7", question="Which car?"))

    worker.chunk.emit(QuestionWithdrawn(id="q7"))

    assert panel._pending_question is None
    assert panel._question_widgets is None
    assert i18n.t("questionWithdrawn") in panel._bubbles[-1]._body.text()
    panel._input.setText("VW Passat")
    panel._on_send()
    assert worker.answers == []  # nothing is answered against a withdrawn frame


def test_withdrawing_a_question_that_is_not_the_live_one_changes_nothing(tmp_path):
    """A second question replaces the first, so a late withdrawal of the first must not take the
    card for the second with it."""
    panel = DialogPanel()
    worker = _AnsweringWorker()
    panel.attach_agent(worker, SignalBus(tmp_path))
    worker.chunk.emit(Question(id="q1", question="First?"))
    worker.chunk.emit(Question(id="q2", question="Second?"))

    worker.chunk.emit(QuestionWithdrawn(id="q1"))

    assert panel._pending_question == "q2"


def test_typing_mid_turn_is_queued_rather_than_refused(tmp_path):
    """The harness takes one prompt at a time, so a message typed mid-turn waits for the boundary.

    The waiting is a row that stays up, not a `SYSTEM · ledger` bubble: announced once in the
    transcript it read as something that had happened, while the message was still sitting there.
    """
    panel, worker, _ = _attached(tmp_path)  # attaching starts the opening turn

    panel._input.setText("the sub is out of phase")
    panel._on_send()

    assert worker.sent == []
    assert panel._input.text() == ""
    assert panel._bubbles[-1]._body.text() == "the sub is out of phase"  # said, not narrated
    assert not panel._queue_row.isHidden()

    worker.turn_done.emit()

    assert worker.sent == ["the sub is out of phase"]
    assert panel._queue_row.isHidden()  # the promise was kept, so it stops being made


def test_several_queued_messages_go_out_as_one_prompt(tmp_path):
    """Sent one after another, the second lands on a harness already busy with the first and
    queues again behind it — the same wait with more steps."""
    panel, worker, _ = _attached(tmp_path)

    for text in ("first", "second"):
        panel._input.setText(text)
        panel._on_send()
    worker.turn_done.emit()

    assert worker.sent == ["first\n\nsecond"]


def test_the_placeholder_says_the_message_will_wait(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    assert panel._input.placeholderText() == i18n.t("composerQueue")

    worker.turn_done.emit()

    assert panel._input.placeholderText() == i18n.t("composer")


def test_a_parked_question_beats_the_queue_for_the_field(tmp_path):
    """Both are mid-turn, and the question is the one thing that unblocks the harness, so typing
    answers it rather than queueing behind it."""
    panel = DialogPanel()
    worker = _AnsweringWorker()
    panel.attach_agent(worker, SignalBus(tmp_path))
    worker.chunk.emit(Question(id="q3", question="Which car?"))

    assert panel._input.placeholderText() == i18n.t("composerAnswer")
    panel._input.setText("VW Passat B8")
    panel._on_send()

    assert worker.answers == [("q3", "VW Passat B8")]
    assert panel._queued == []


def test_a_queued_message_is_handed_back_when_the_session_stops(tmp_path):
    """There is no turn boundary coming, and dropping the words into a dead session loses them."""
    panel, worker, _ = _attached(tmp_path)
    panel._input.setText("recheck the delays")
    panel._on_send()

    worker.failed.emit("CLINotFoundError: no binary")

    assert panel._input.text() == "recheck the delays"
    assert panel._queued == []
    assert worker.sent == []


def test_the_queue_row_counts_what_is_waiting(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    for text in ("first", "second"):
        panel._input.setText(text)
        panel._on_send()

    assert "2" in panel._queue_label.text()


def test_a_turn_that_produced_nothing_still_releases_the_queue(tmp_path):
    """CAR-004, the panel's half. The credits ran out mid-turn, omp retried ten times and said
    "this turn produced nothing" — and the window went on saying "thinking" while a queued message
    promised to go "the moment this turn ends". Nothing was going to end it; `Send now` was the
    only way out, which is a button for a state the app should not reach.

    What closes that turn is `omp_session` (`test_omp_replay`: a give-up is a finished round).
    Everything below is what already happens once a boundary does arrive — asserted here because
    that is the promise the queue makes, and it is the one that was broken."""
    from autosound_tcc.core.agent_events import Notice

    panel, worker, _ = _attached(tmp_path)
    panel._input.setText("тоді спробуй ще раз")
    panel._on_send()
    worker.chunk.emit(
        Notice("omp gave up after 10 attempts — this turn produced nothing. "
               "Google API error (429): credits depleted.")
    )

    assert panel._busy, "the notice lands mid-turn; it is not itself an ending"
    assert worker.sent == []

    worker.turn_done.emit()

    assert worker.sent == ["тоді спробуй ще раз"], "no hand on the button"
    assert panel._queue_row.isHidden(), "the promise was kept, so it stops being made"
    assert panel._busy, "and busy again for the turn that message just started"


def test_send_now_interrupts_the_turn_that_is_holding_the_queue(tmp_path):
    """The queue's promise depends on a turn boundary arriving, and a turn silent for minutes may
    never produce one — the state this button was added under, with "[120s with no output]" as the
    last thing in the transcript. Interrupting makes the boundary the queue is waiting for."""
    panel, worker, _ = _attached(tmp_path)
    panel._input.setText("recheck the delays")
    panel._on_send()

    panel._queue_now_btn.click()

    assert worker.interrupted
    assert worker.sent == []  # nothing is pushed into a harness still running

    worker.turn_done.emit()  # the interrupt produced the boundary

    assert worker.sent == ["recheck the delays"]


def test_send_now_with_a_parked_question_withdraws_it_instead(tmp_path):
    """`abort` does not reach a harness blocked inside `ask`. Withdrawing the question is what
    unblocks the turn, which is what ends it."""
    panel = DialogPanel()
    worker = _AnsweringWorker()
    worker.cancelled = []
    worker.cancel_question = worker.cancelled.append
    panel.attach_agent(worker, SignalBus(tmp_path))
    worker.chunk.emit(Question(id="q5", question="Which car?", options=(QuestionOption("Sedan"),)))
    panel._queued.append("meanwhile, the sub is out of phase")
    panel._show_queue_row()

    panel._on_send_queued_now()

    assert worker.cancelled == ["q5"]


def test_send_now_does_nothing_with_an_empty_queue(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    panel._on_send_queued_now()

    assert not worker.interrupted


def test_the_adapter_speaking_is_not_the_model_speaking(tmp_path):
    """"[120s with no output. omp has said nothing.]" arrived under GENERATOR · GEMINI 3.5 FLASH
    LITE, in the same bubble style as its analysis — a sentence about the harness attributed to the
    model, at the one moment the difference matters."""
    from autosound_tcc.core.agent_events import Notice

    panel, worker, _ = _attached(tmp_path)
    worker.chunk.emit(TextDelta("Reading the ledger"))

    worker.chunk.emit(Notice("120s with no output. omp has said nothing."))
    worker.chunk.emit(TextDelta("Back."))

    roles = [b.findChild(QLabel).text() for b in panel._bubbles]
    assert roles[1].lower().startswith("system")
    assert "omp has said nothing" in panel._bubbles[1]._body.text()
    assert panel._bubbles[2]._body.text() == "Back."  # a new bubble, not appended above the notice


def test_the_activity_line_stops_moving_when_the_tool_returns(tmp_path):
    """A static line says a tool ran, a moving one says it is still running — that difference is
    the only reason the line exists, and nothing ever stopped the dots."""
    from autosound_tcc.core.agent_events import ToolEnd

    panel, worker, _ = _attached(tmp_path)
    worker.chunk.emit(ToolCall(name="read"))
    assert panel._activity_timer.isActive()

    worker.chunk.emit(ToolEnd(name="read"))

    assert not panel._activity_timer.isActive()
    assert "⟳" not in panel._activity.text()
    assert "read" in panel._activity.text()


def test_the_next_tool_starts_the_line_moving_again(tmp_path):
    from autosound_tcc.core.agent_events import ToolEnd

    panel, worker, _ = _attached(tmp_path)
    worker.chunk.emit(ToolCall(name="read"))
    worker.chunk.emit(ToolEnd(name="read"))

    worker.chunk.emit(ToolCall(name="glob"))

    assert panel._activity_timer.isActive()
    assert "⟳" in panel._activity.text()


def test_the_demo_transcript_goes_when_a_real_project_opens(tmp_path):
    """It is invented tuning advice — "PK 1120 -2.5 Q2.2", a Critic verdict, an Arbiter reply. In a
    window with a real project open it is indistinguishable from history, and acting on a number
    nobody measured is the failure this whole application exists to prevent."""
    panel = DialogPanel()
    assert panel._bubbles  # the mock is there before anything real is

    panel.clear_mock()

    assert panel._bubbles == []


def test_clearing_the_mock_never_touches_a_live_transcript(tmp_path):
    """A running session re-reads the project constantly; wiping its bubbles there would destroy
    real history and leave `_live_bubble` pointing at a freed object."""
    panel, worker, _ = _attached(tmp_path)
    worker.chunk.emit(TextDelta("Phase 0 baseline"))

    panel.clear_mock()

    assert panel._bubbles  # still there


# ---- reading history (F-008) ------------------------------------------------


def _settled():
    """Let deferred scrolls and the second layout pass land -- bubble heights settle late."""
    app = QApplication.instance()
    for _ in range(5):
        app.processEvents()


def _reading(tmp_path, height=260):
    """An attached panel with real geometry and enough transcript that there is history to
    scroll into -- the reading tests measure positions, so a zero-range scrollbar proves
    nothing."""
    panel, worker, _ = _attached(tmp_path)
    panel.resize(420, height)
    panel.show()
    for i in range(12):
        panel._add_system_message(f"line {i}: the measurement was read and the delay recorded")
    _settled()
    assert panel._scroll.verticalScrollBar().maximum() > 0
    return panel, worker


def test_arriving_output_no_longer_rearms_the_chase(tmp_path):
    """The F-008 bug itself: `_scroll_to_end` set `_stick_to_bottom = True` on every new bubble,
    overruling the scroll-up the Arbiter had just made -- two places disagreeing about who
    decides. Arriving text does not decide."""
    panel, worker = _reading(tmp_path)
    bar = panel._scroll.verticalScrollBar()

    bar.setValue(0)  # scrolled up by hand: reading
    assert panel._stick_to_bottom is False

    worker.chunk.emit(TextDelta("a fresh answer lands below"))
    _settled()

    assert panel._stick_to_bottom is False
    assert bar.value() < bar.maximum()  # no jump under the reader


def test_the_reading_position_holds_while_output_arrives(tmp_path):
    """The position is held relative to the CONTENT -- "this bubble, this many pixels in" --
    because a new bubble wraps and settles its height a layout pass late, and an absolute
    scrollbar value through that shows different lines under the same eyes."""
    panel, worker = _reading(tmp_path)
    bar = panel._scroll.verticalScrollBar()

    bar.setValue(bar.maximum() // 2)  # reading the middle of history
    _settled()
    read = panel._reading_bubble
    assert read is not None
    offset = bar.value() - read.y()

    worker.chunk.emit(TextDelta(
        "a long answer that wraps into several lines once the label folds it at the "
        "bubble cap and settles its height on the second layout pass " * 3))
    _settled()

    assert bar.value() - read.y() == offset  # the same line is under the eyes
    assert panel._stick_to_bottom is False


def test_a_reflow_above_the_reader_does_not_move_the_text(tmp_path):
    """Point 4's real threat: when a bubble ABOVE the viewport grows taller, holding the
    scrollbar's absolute value still moves the text, with no jump to blame. The bar must move
    so the text does not -- both directions of that are asserted."""
    panel, _ = _reading(tmp_path)
    bar = panel._scroll.verticalScrollBar()

    bar.setValue(bar.maximum() // 2)
    _settled()
    read = panel._reading_bubble
    offset = bar.value() - read.y()
    value_before = bar.value()

    first = panel._bubbles[0]
    assert first.y() + first.height() < value_before  # wholly above the viewport
    first.set_html("grown: " + "wraps and wraps and wraps " * 20)
    panel._fit(first)
    _settled()

    assert bar.value() != value_before          # the bar moved...
    assert bar.value() - read.y() == offset     # ...so the text did not


def test_the_marker_appears_on_arrival_and_goes_when_read(tmp_path):
    """Scrolling up alone is not "new below" -- the marker means something arrived past the
    anchor. Coming back to the bottom by hand reads it all, so the marker goes."""
    panel, worker = _reading(tmp_path)
    bar = panel._scroll.verticalScrollBar()

    bar.setValue(0)
    assert panel._new_below_btn.isHidden()

    worker.chunk.emit(TextDelta("fresh"))
    _settled()

    assert not panel._new_below_btn.isHidden()
    assert "1" in panel._new_below_btn.text()

    bar.setValue(bar.maximum())  # scrolled back down by hand
    _settled()

    assert panel._new_below_btn.isHidden()
    assert panel._unread_anchor is None
    assert panel._stick_to_bottom is True


def test_the_marker_first_click_lands_on_the_start_of_the_new_text(tmp_path):
    """First click: where the new text starts -- the first bubble added after the stick was
    dropped, not the latest one. Second click: the very bottom, and the chase is re-armed."""
    panel, worker = _reading(tmp_path)
    bar = panel._scroll.verticalScrollBar()
    bar.setValue(0)

    # Enough new text that its start is a real scroll position rather than already the bottom.
    for i in range(6):
        worker.chunk.emit(ToolCall(name="glob"))  # a boundary: the next delta is its own bubble
        worker.chunk.emit(TextDelta(
            f"answer {i}: long enough to wrap into a few lines inside the bubble " * 3))
    _settled()

    anchor = panel._unread_anchor
    assert anchor is panel._bubbles[-6]
    assert "6" in panel._new_below_btn.text()

    panel._new_below_btn.click()
    _settled()

    assert bar.value() == anchor.y() - panel._chat_layout.spacing()
    assert panel._stick_to_bottom is False  # the start of the new text, still reading

    panel._new_below_btn.click()
    _settled()

    assert bar.value() == bar.maximum()
    assert panel._stick_to_bottom is True
    assert panel._new_below_btn.isHidden()


def test_sending_a_message_rearms_the_chase(tmp_path):
    """The stick is armed by the user's own actions only -- and sending is one: whoever just
    said something wants to see the answer land."""
    panel, worker = _reading(tmp_path)
    bar = panel._scroll.verticalScrollBar()
    bar.setValue(0)
    worker.chunk.emit(TextDelta("meanwhile, below"))
    _settled()
    assert not panel._new_below_btn.isHidden()

    panel._input.setText("done reading -- go on")
    panel._on_send()
    _settled()

    assert panel._stick_to_bottom is True
    assert bar.value() == bar.maximum()
    assert panel._new_below_btn.isHidden()
    assert panel._unread_anchor is None


def test_the_first_thing_the_arbiter_says_survives_the_session_starting(tmp_path):
    """User, 2026-08-21: "після Привіт робота пішла (але сам Привіт пропав)".

    The bubble was added and then swept away: `attach_agent` clears the transcript so demo
    numbers cannot be read as measurements, and it was taking the Arbiter's own first line with
    it — the line that started the session.
    """
    app = QApplication.instance()
    panel = DialogPanel()
    panel._input.setText("Привіт")
    started: list[str] = []
    panel.startRequested.connect(started.append)
    panel._on_send()
    app.processEvents()

    assert started == ["Привіт"]

    panel.attach_agent(FakeWorker(), SignalBus(tmp_path))
    app.processEvents()

    said = [b.plain_text() for b in panel._chat.findChildren(MessageBubble)
            if "msg-user" in str(b.property("class") or "")]
    assert said == ["Привіт"], "the line that started the session is still in the record"


def test_tcc_starts_a_turn_for_a_signal_nobody_was_around_to_carry(tmp_path):
    """F-020. Delivery rides into the next turn, and a click used to have to wait for the Arbiter
    to say something unrelated before one existed (user, 2026-08-21).

    Refused while a turn is running, with no session, and while the composer holds unsent text —
    someone mid-sentence owns the next turn, not a machine.
    """
    app = QApplication.instance()
    panel = DialogPanel()
    worker = FakeWorker()

    assert panel.nudge_for_signals(1, "look") is False, "no session, no turn"

    panel.attach_agent(worker, SignalBus(tmp_path))
    app.processEvents()
    assert panel.nudge_for_signals(2, "look") is False, "the opening turn is running"

    panel._on_turn_done()
    app.processEvents()
    sent_before = list(worker.sent)

    assert panel.nudge_for_signals(2, "look") is True
    assert worker.sent == [*sent_before, "look"]
    assert panel._busy is True

    assert panel.nudge_for_signals(2, "look again") is False, "a turn is already running"

    panel._on_turn_done()
    app.processEvents()
    panel._input.setText("half a thought")
    assert panel.nudge_for_signals(2, "look again") is False, "the Arbiter is mid-sentence"


def test_copying_a_message_gives_back_the_table_and_not_a_column_of_cells(tmp_path):
    """User, 2026-08-21, with the paste: a Markdown table came off the clipboard one cell per
    line, so the answer that made sense on screen made none anywhere else.

    `_markdown` turns a pipe table into a real `<table>`, and Qt's HTML-to-text converter lays
    that out cell by cell. The source is a readable plain-text table already, so copy hands back
    what the model actually wrote.
    """
    app = QApplication.instance()
    panel = DialogPanel()
    written = (
        "Результат\n\n"
        "| пара | Δφ набіг | вердикт |\n"
        "|------|----------|---------|\n"
        "| Ws | 116° | у межах одного оберту |\n"
        "| Ms | 3636° | MULTIPATH |\n"
    )
    panel.attach_agent(FakeWorker(), SignalBus(tmp_path))
    panel._on_chunk(TextDelta(text=written))
    panel._on_turn_done()
    app.processEvents()

    bubble = [b for b in panel._chat.findChildren(MessageBubble)
              if "msg-gen" in str(b.property("class") or "")][-1]
    copied = bubble.plain_text()

    assert "| Ws | 116° | у межах одного оберту |" in copied, "the row survives as a row"
    assert copied.count("\n") < written.count("\n") + 2, "and not one line per cell"


def test_the_ear_gets_a_button_in_the_composer_and_only_in_its_own_phase(tmp_path):
    """User, 2026-09-02: "кнопка «Слухання» іде до рядка діалога біля загрузки фото і зʼявляється
    тільки в фазі коли йде прослуховування".

    It used to sit on the capture card permanently — a card about sweeps, carrying a button for a
    thing that happens with a track playing, in one phase out of six."""
    panel = DialogPanel()
    assert panel._listen_btn.isHidden()

    panel.set_listening_available(True)
    assert not panel._listen_btn.isHidden()
    assert panel._listen_btn.text() == i18n.t("lsnBtn")

    asked = []
    panel.listeningRequested.connect(lambda: asked.append(True))
    panel._listen_btn.click()
    assert asked == [True], "the panel asks; the window owns the dialog"

    panel.set_listening_available(False)
    assert panel._listen_btn.isHidden()
