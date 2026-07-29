"""Minimal chat-style dialog for the DSP-profile onboarding interview.

Scoped to exactly this one interview (docs/TCC-TZ.md §4a's first concrete slice of the "AI
dialog" — the larger Generator/Critic/Arbiter tuning dialog from the prototype is a separate,
bigger initiative, not built here). Runs `core.agent_session.OnboardingSession` on a background
thread with its own asyncio loop (Qt's event loop isn't asyncio-compatible) and talks to it only
through Qt signals — the GUI thread never touches the SDK client directly.
"""

from __future__ import annotations

import asyncio
import queue
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from autosound_tcc.core.agent_session import OnboardingSession


class _AgentWorker(QThread):
    """Owns the asyncio event loop + OnboardingSession. `send(text)` is safe to call from the
    GUI thread; everything else (the SDK client, the queue consumer loop) lives here."""

    chunk = Signal(str)
    turn_done = Signal()
    profile_saved = Signal(str)  # emits the on-disk path once finalize_profile actually wrote it
    failed = Signal(str)

    def __init__(
        self,
        project_dir: Path,
        vendor: str,
        model: str,
        ai_model: Optional[str] = None,
        language: str = "en",
    ) -> None:
        super().__init__()
        self._project_dir = project_dir
        self._vendor = vendor
        self._model = model
        self._ai_model = ai_model
        self._language = language
        self._inbox: "queue.Queue[Optional[str]]" = queue.Queue()
        self._session: Optional[OnboardingSession] = None

    def send(self, text: str) -> None:
        """Enqueue a user message for the worker loop to consume. Thread-safe."""
        self._inbox.put(text)

    def stop(self) -> None:
        self._inbox.put(None)  # sentinel: end the session

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as exc:  # surface to the GUI instead of dying silently in the thread
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    async def _main(self) -> None:
        self._session = OnboardingSession(
            self._project_dir, self._vendor, self._model, self._ai_model, self._language
        )
        try:
            async for text in self._session.start():
                self.chunk.emit(text)
            self.turn_done.emit()
            loop = asyncio.get_running_loop()
            while True:
                user_text = await loop.run_in_executor(None, self._inbox.get)
                if user_text is None:
                    break
                async for text in self._session.send(user_text):
                    self.chunk.emit(text)
                self.turn_done.emit()
                profile_path = self._session.project_dir / "dsp_profile.json"
                if profile_path.is_file():
                    self.profile_saved.emit(str(profile_path))
        finally:
            await self._session.close()


class ProfileInterviewDialog(QDialog):
    """Chat panel: message list + composer, same shape as the HTML prototype's `.msg`/
    `.composer`, streaming the onboarding agent's turns from a background thread."""

    # Re-emitted (not just shown in `self._status`) so a caller -- e.g. the "Create new project"
    # flow in main_window.py -- can react to a finished onboarding without reaching into this
    # dialog's own worker.
    profile_saved = Signal(str)

    def __init__(
        self,
        project_dir: Path,
        vendor: str,
        model: str,
        ai_model: Optional[str] = None,
        language: str = "en",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"DSP profile onboarding — {vendor} {model}")
        self.resize(560, 640)

        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        self._composer = QLineEdit()
        self._composer.setPlaceholderText("Type your answer…")
        self._send_btn = QPushButton("Send")
        self._status = QLabel("Connecting…")
        self._status.setStyleSheet("color: #888;")

        composer_row = QHBoxLayout()
        composer_row.addWidget(self._composer, stretch=1)
        composer_row.addWidget(self._send_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._transcript, stretch=1)
        layout.addLayout(composer_row)
        layout.addWidget(self._status)

        self._pending_line = ""  # accumulates streamed chunks for the current agent turn
        self._send_btn.clicked.connect(self._on_send)
        self._composer.returnPressed.connect(self._on_send)
        self._set_input_enabled(False)

        self._worker = _AgentWorker(project_dir, vendor, model, ai_model, language)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.turn_done.connect(self._on_turn_done)
        self._worker.profile_saved.connect(self._on_profile_saved)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _set_input_enabled(self, enabled: bool) -> None:
        self._composer.setEnabled(enabled)
        self._send_btn.setEnabled(enabled)

    def _append_bubble(self, who: str, text: str) -> None:
        self._transcript.append(f"<b>{who}</b><br>{text}<br>")

    def _on_chunk(self, text: str) -> None:
        self._pending_line += text

    def _on_turn_done(self) -> None:
        if self._pending_line:
            self._append_bubble("Generator", self._pending_line)
            self._pending_line = ""
        self._status.setText("Your turn.")
        self._set_input_enabled(True)
        self._composer.setFocus()

    def _on_send(self) -> None:
        text = self._composer.text().strip()
        if not text:
            return
        self._append_bubble("You", text)
        self._composer.clear()
        self._set_input_enabled(False)
        self._status.setText("Thinking…")
        self._worker.send(text)

    def _on_profile_saved(self, path: str) -> None:
        self._status.setText(f"Profile saved: {path}")
        self.profile_saved.emit(path)

    def _on_failed(self, message: str) -> None:
        self._append_bubble("System", f"⚠️ {message}")
        self._status.setText("Session error.")
        self._set_input_enabled(False)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._worker.stop()
        self._worker.wait(3000)
        super().closeEvent(event)
