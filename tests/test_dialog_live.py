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
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import signal_bus  # noqa: E402
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


class FakeStreamEvent:
    def __init__(self, text):
        self.event = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}


class FakeBlock:
    def __init__(self, text=None, name=None):
        if text is not None:
            self.text = text
        if name is not None:
            self.name = name


class FakeMessage:
    def __init__(self, *blocks):
        self.content = list(blocks)


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

    worker.chunk.emit(FakeStreamEvent("Phase 2, "))
    worker.chunk.emit(FakeStreamEvent("step 2.3."))

    assert len(panel._bubbles) == 1
    assert panel._live_text == "Phase 2, step 2.3."


def test_a_tool_call_renders_as_a_process_chip_not_raw_json(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(FakeMessage(FakeBlock(name="mcp__tcc__get_tcc_state")))

    assert len(panel._bubbles) == 1
    assert "get_tcc_state" in panel._bubbles[0]._body.text()
    assert "mcp__tcc__" not in panel._bubbles[0]._body.text()


def test_text_after_a_tool_call_starts_a_new_bubble(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(FakeStreamEvent("Reading state"))
    worker.chunk.emit(FakeMessage(FakeBlock(name="get_ledger")))
    worker.chunk.emit(FakeStreamEvent("Done."))

    assert len(panel._bubbles) == 3
    assert panel._live_text == "Done."


def test_a_turn_that_never_streamed_still_renders(tmp_path):
    """Partial messages can be off, or the turn can be non-text -- silence is not an option."""
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(FakeMessage(FakeBlock(text="Complete answer.")))

    assert panel._live_text == "Complete answer."


def test_streamed_text_is_not_duplicated_by_the_final_message(tmp_path):
    panel, worker, _ = _attached(tmp_path)

    worker.chunk.emit(FakeStreamEvent("Hello"))
    worker.chunk.emit(FakeMessage(FakeBlock(text="Hello")))

    assert panel._live_text == "Hello"


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
