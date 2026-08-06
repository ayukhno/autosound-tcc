"""The Arbiter's gate, rendered — one bar in the dialog panel that says what wants to happen.

Every mutation the agent asks for lands here: a `write_rew_filters` call, a clipboard write, a
Bash command that isn't on the read-only allowlist. This is the 🟡→🟢 attest step from
`TCC-TZ.md §4a.2` made into a widget, so the answer to "did a human agree to this" is always a
click and never a convention.

Requests queue rather than stack: two dialogs fighting for the same screen is how people learn to
click through prompts without reading them. One at a time, with the remaining count visible.

Reuses the existing `edit-reasons` / `reason-btn` styling so it reads as part of the dialog panel
rather than as a foreign alert.
"""

from __future__ import annotations

from concurrent.futures import Future
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core.mcp_server import ConfirmRequest
from autosound_tcc.ui.tcc import i18n


class ConfirmBar(QWidget):
    """Shows pending confirmations one at a time and resolves each request's future."""

    resolved = Signal(str, bool)  # (tool, allowed) — for the transcript
    # The Arbiter said "and stop asking about this one". Carries the tool the decision covers, so
    # the caller can remember it per project. Claude Code's own prompt works this way, and the
    # reason is the one measured here all day: a gate that fires constantly is a gate that gets
    # clicked through, so the way to keep it meaningful is to let it be narrowed deliberately.
    alwaysAllowed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._queue: list[tuple[ConfirmRequest, "Future[bool]"]] = []
        self._current: Optional[tuple[ConfirmRequest, "Future[bool]"]] = None

        self.setProperty("class", "edit-reasons")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(4)

        self._title = QLabel()
        self._title.setProperty("class", "phead-title")
        self._title.setWordWrap(True)
        outer.addWidget(self._title)

        self._detail = QLabel()
        self._detail.setProperty("class", "phead-sub")
        self._detail.setWordWrap(True)
        self._detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self._detail)

        self._always = QCheckBox(i18n.t("confirmAlways"))
        self._always.setCursor(Qt.CursorShape.PointingHandCursor)
        outer.addWidget(self._always)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._allow = QPushButton("✓ Дозволити")
        self._allow.setProperty("class", "composer-send")
        self._allow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._allow.clicked.connect(lambda: self._answer(True))
        row.addWidget(self._allow)

        self._deny = QPushButton("✕ Відхилити")
        self._deny.setProperty("class", "reason-btn")
        self._deny.setCursor(Qt.CursorShape.PointingHandCursor)
        self._deny.clicked.connect(lambda: self._answer(False))
        row.addWidget(self._deny)

        self._remaining = QLabel()
        self._remaining.setProperty("class", "phead-sub")
        row.addWidget(self._remaining)
        row.addStretch(1)
        outer.addLayout(row)

        self.setHidden(True)

    # ---- API ---------------------------------------------------------------

    def enqueue(self, request: ConfirmRequest, future: "Future[bool]") -> None:
        """Queue a confirmation. Safe to call for a request whose caller already gave up."""
        if future.done():  # the tool timed out or was cancelled while we were busy
            return
        self._queue.append((request, future))
        if self._current is None:
            self._advance()
        else:
            self._update_remaining()

    def reject_all(self, reason: str = "TCC closed") -> None:
        """Deny everything outstanding — used on shutdown so no tool call hangs forever."""
        pending = ([self._current] if self._current else []) + self._queue
        self._current, self._queue = None, []
        for request, future in pending:
            if not future.done():
                future.set_result(False)
        self.setHidden(True)

    @property
    def pending_count(self) -> int:
        return len(self._queue) + (1 if self._current else 0)

    # ---- internals ---------------------------------------------------------

    def _answer(self, allowed: bool) -> None:
        if self._current is None:
            return
        request, future = self._current
        if allowed and self._always.isChecked():
            self.alwaysAllowed.emit(request.tool)
        self._always.setChecked(False)  # a decision covers one kind, not the next one by accident
        self._current = None
        if not future.done():
            future.set_result(allowed)
        self.resolved.emit(request.tool, allowed)
        self._advance()

    def _advance(self) -> None:
        while self._queue:
            request, future = self._queue.pop(0)
            if future.done():  # gave up while queued behind another request
                continue
            self._current = (request, future)
            self._title.setText(request.title)
            self._detail.setText(request.detail)
            self._update_remaining()
            self.setHidden(False)
            return
        self._current = None
        self.setHidden(True)

    def _update_remaining(self) -> None:
        extra = len(self._queue)
        self._remaining.setText(f"ще {extra} у черзі" if extra else "")
