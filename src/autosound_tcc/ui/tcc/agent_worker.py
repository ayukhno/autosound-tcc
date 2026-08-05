"""Run an async agent session on a background thread, talk to it only through Qt signals.

Qt's event loop is not asyncio-compatible, so an agent session cannot live on the GUI thread. This
owns a thread with its own asyncio loop, keeps the session inside it, and exposes exactly two safe
operations to the GUI: `send()` and `stop()`. Everything coming back is a signal.

Generalised from the pattern proven in `profile_interview_dialog` so the DSP-profile interview and
the tuning dialog share one implementation. It is deliberately agnostic about what a session
*yields*: the onboarding session yields text chunks, the tuning session yields SDK message
objects, and both arrive on `chunk` for the caller to render.
"""

from __future__ import annotations

import asyncio
import queue
from typing import Any, Callable, Optional, Protocol

from PySide6.QtCore import QThread, Signal


class AgentSession(Protocol):
    """The shape `AgentWorker` drives: two async generators and a closer."""

    def start(self, *args: Any) -> Any: ...

    def send(self, text: str) -> Any: ...

    async def close(self) -> None: ...


class AgentWorker(QThread):
    """Owns the asyncio loop and the session. `send()` is safe to call from the GUI thread."""

    chunk = Signal(object)  # whatever the session yields: str, or an SDK message
    turn_done = Signal()
    failed = Signal(str)
    closed = Signal()

    def __init__(
        self,
        session_factory: Callable[[], AgentSession],
        opening_prompt: Optional[str] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._opening_prompt = opening_prompt
        self._inbox: "queue.Queue[Optional[str]]" = queue.Queue()
        self._session: Optional[AgentSession] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._task: Optional[asyncio.Task] = None

    @property
    def session(self) -> Optional[AgentSession]:
        """The live session, for reading attributes like `session_id` after a turn.

        Read-only in practice: calling its async methods from the GUI thread would run them on the
        wrong loop.
        """
        return self._session

    def send(self, text: str) -> None:
        """Queue a user message. Thread-safe."""
        self._inbox.put(text)

    def stop(self) -> None:
        """Ask the worker to close the session and finish. Thread-safe."""
        self._inbox.put(None)

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Wind the session down and wait for the thread to actually finish. Returns success.

        `stop()` alone is not enough on exit: the sentinel is only read *between* turns, so a
        worker in the middle of an agent turn never sees it, `wait()` expires, and Qt destroys a
        running QThread — undefined behaviour, and the exact warning this method exists to stop
        ("QThread: Destroyed while thread is still running", seen on a real close).

        Escalation, gentlest first: ask the session to interrupt, post the sentinel, and only then
        cancel the coroutine outright. Cancelling unwinds the `async for` and still runs the
        `finally` that closes the session, so even the last resort shuts down cleanly.

        Notably *not* `QThread.terminate()`: killing a thread that holds the GIL mid-interpreter
        wedges the whole process — it hung the test suite when tried.
        """
        if not self.isRunning():
            return True
        self.interrupt()
        self.stop()
        if self.wait(timeout_ms // 2):
            return True
        self._cancel_task()
        return self.wait(timeout_ms // 2)

    def _cancel_task(self) -> None:
        task, loop = self._task, self._loop
        if task is None or loop is None:
            return
        try:
            loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            pass  # loop already closed: nothing left to cancel

    def interrupt(self) -> None:
        """Interrupt the turn in flight, if the session supports it. Thread-safe.

        The session's `interrupt()` is a coroutine belonging to *this* worker's loop, so it has to
        be scheduled onto that loop rather than awaited from the GUI thread.
        """
        session, loop = self._session, self._loop
        if session is None or loop is None or not hasattr(session, "interrupt"):
            return
        try:
            asyncio.run_coroutine_threadsafe(session.interrupt(), loop)
        except RuntimeError:
            pass  # loop already closing: the turn is ending anyway

    def answer(self, question_id: str, value: str) -> None:
        """Deliver the Arbiter's answer to a parked question. Thread-safe.

        Not `send()`: a question blocks the turn inside the harness, so the answer has to go back
        through the same channel it came from rather than arriving as the next user message. Same
        scheduling as `interrupt()` -- the session's coroutine belongs to this worker's loop.
        """
        session, loop = self._session, self._loop
        if session is None or loop is None or not hasattr(session, "answer"):
            return
        try:
            asyncio.run_coroutine_threadsafe(session.answer(question_id, value), loop)
        except RuntimeError:
            pass  # loop already closing: the turn is ending anyway

    def cancel_question(self, question_id: str) -> None:
        """Withdraw a question the Arbiter will not answer. Thread-safe, same route as `answer`."""
        session, loop = self._session, self._loop
        if session is None or loop is None or not hasattr(session, "cancel_question"):
            return
        try:
            asyncio.run_coroutine_threadsafe(session.cancel_question(question_id), loop)
        except RuntimeError:
            pass

    def run(self) -> None:  # noqa: D102 - QThread override
        try:
            asyncio.run(self._main())
        except asyncio.CancelledError:
            pass  # shutdown() cancelled us on purpose; not a failure to report
        except Exception as exc:  # surface it instead of dying silently on a background thread
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.closed.emit()

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        self._session = self._session_factory()
        try:
            start = (
                self._session.start(self._opening_prompt)
                if self._opening_prompt is not None
                else self._session.start()
            )
            async for item in start:
                self.chunk.emit(item)
            self.turn_done.emit()

            loop = asyncio.get_running_loop()
            while True:
                # `input`-style blocking get, moved off the loop so the session's own tasks (MCP
                # calls, streaming) keep running while we wait for the user.
                user_text = await loop.run_in_executor(None, self._inbox.get)
                if user_text is None:
                    break
                async for item in self._session.send(user_text):
                    self.chunk.emit(item)
                self.turn_done.emit()
        finally:
            # Best-effort: when we get here via cancellation, this await can be cancelled again
            # before the session finishes closing. A half-closed session on the way out is
            # tolerable; an exception escaping the finally and masking the real reason is not.
            if self._session is not None:
                try:
                    await self._session.close()
                except Exception:
                    pass
