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
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core.mcp_server import ConfirmRequest
from autosound_tcc.ui.tcc import i18n

#: The reason a question is about what cannot be undone (`shell_gate.judge_action`'s key).
IRREVERSIBLE = "gateIrreversible"


#: How many lines of a request show before it scrolls. Enough to read an ordinary command whole; a
#: heredoc with an issue body in it scrolls instead of pushing the answer off the window.
#:
#: It bounds the TITLE and the command together (the user, 2026-09-19). Bounding only the command
#: left the other half free to grow: a wrapped title of ten lines moved Allow down by ten lines,
#: and the buttons went past the window again — the very thing the bound was added to stop.
_QUESTION_LINES = 12

#: …and never more than this much of the panel it sits in, whatever the line count says. On a short
#: window twelve lines is most of the height, and a question that eats the transcript is the same
#: failure one size down.
_QUESTION_SHARE = 0.5


class ConfirmBar(QWidget):
    """Shows pending confirmations one at a time and resolves each request's future."""

    resolved = Signal(str, bool)  # (tool, allowed) — for the transcript
    # The Arbiter said "and stop asking about this one". Carries the tool the decision covers, so
    # the caller can remember it per project. Claude Code's own prompt works this way, and the
    # reason is the one measured here all day: a gate that fires constantly is a gate that gets
    # clicked through, so the way to keep it meaningful is to let it be narrowed deliberately.
    alwaysAllowed = Signal(str)
    # Asked, then given up on before an answer — the tool's clock ran out, or its session ended:
    # either way it was not run. Said instead of `resolved`, so a click after it is never recorded
    # as a verdict (G1 review), and worded for both (the branch review).
    expired = Signal(str)
    #: A request's future finished — from the session's thread, so it arrives here queued.
    _gave_up = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._gave_up.connect(self._on_gave_up)
        self._queue: list[tuple[ConfirmRequest, "Future[bool]"]] = []
        self._current: Optional[tuple[ConfirmRequest, "Future[bool]"]] = None

        self.setProperty("class", "edit-reasons confirm-bar")
        # Qt draws a stylesheet background on a plain `QWidget` subclass only when it is told to —
        # a top-level window gets one anyway, a CHILD does not. The bar is a child of the dialog
        # panel, so the attention tint and its border were simply not painted in the app while a
        # standalone widget in a test showed them (the user, with the screenshot, 2026-09-19).
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(4)

        # The question — what wants to happen and the command that would do it — is ONE scrolled
        # block (TEST-FINDINGS 24, and the user 2026-09-19). Whatever its length, the answer below
        # it keeps its place: the block scrolls, the buttons do not move.
        self._question = QWidget()
        self._question.setProperty("class", "confirm-question")
        question = QVBoxLayout(self._question)
        question.setContentsMargins(0, 0, 0, 0)
        question.setSpacing(4)

        self._title = QLabel()
        self._title.setProperty("class", "phead-title")
        self._title.setWordWrap(True)
        question.addWidget(self._title)

        self._detail = QLabel()
        self._detail.setProperty("class", "phead-sub")
        self._detail.setWordWrap(True)
        self._detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._detail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        question.addWidget(self._detail)
        question.addStretch(1)

        self._question_scroll = QScrollArea()
        self._question_scroll.setProperty("class", "confirm-question")
        self._question_scroll.setWidgetResizable(True)
        self._question_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._question_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._question_scroll.setWidget(self._question)
        # A scroll area and its viewport paint the window colour of their own accord, and the
        # stylesheet's `transparent` alone does not stop the viewport doing it — so the attention
        # tint used to FRAME the question with a dark block where the request itself is. Said here
        # as well as in the stylesheet because this is the half the stylesheet cannot reach.
        self._question_scroll.viewport().setAutoFillBackground(False)
        self._question.setAutoFillBackground(False)
        outer.addWidget(self._question_scroll)

        self._always = QCheckBox()
        self._always.setCursor(Qt.CursorShape.PointingHandCursor)
        outer.addWidget(self._always)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._allow = QPushButton()
        self._allow.setProperty("class", "composer-send")
        self._allow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._allow.clicked.connect(lambda: self._answer(True))
        row.addWidget(self._allow)

        self._deny = QPushButton()
        self._deny.setProperty("class", "reason-btn")
        self._deny.setCursor(Qt.CursorShape.PointingHandCursor)
        self._deny.clicked.connect(lambda: self._answer(False))
        row.addWidget(self._deny)

        self._remaining = QLabel()
        self._remaining.setProperty("class", "phead-sub")
        row.addWidget(self._remaining)
        row.addStretch(1)
        outer.addLayout(row)

        # Every text of the bar in the window's language, and again when it changes: the title and
        # the buttons were Ukrainian literals under an English body (the Arbiter's VM, W-10).
        self._retranslate()
        i18n.on_language_changed(self._retranslate)
        self.setHidden(True)

    # ---- API ---------------------------------------------------------------

    def enqueue(self, request: ConfirmRequest, future: "Future[bool]") -> None:
        """Queue a confirmation. Safe to call for a request whose caller already gave up."""
        if future.done():  # the tool timed out or was cancelled while we were busy
            return

        def finished(done, tell=self._gave_up.emit) -> None:
            try:
                tell(done)
            except RuntimeError:  # the bar is gone: TCC is closing
                pass

        future.add_done_callback(finished)
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
        # Only where the tick is offered: on a question about what cannot be undone it is not.
        always = allowed and not self._always.isHidden() and self._always.isChecked()
        self._always.setChecked(False)  # a decision covers one kind, not the next one by accident
        self._current = None
        if future.done():  # given up on before this click: denied then, and said as that
            self.expired.emit(request.tool)
        else:
            if always:
                self.alwaysAllowed.emit(request.tool)
            future.set_result(allowed)
            self.resolved.emit(request.tool, allowed)
        self._advance()

    def _on_gave_up(self, future) -> None:
        """The request on screen was given up on by its caller: take it down and say so."""
        if self._current is None or self._current[1] is not future:
            return  # answered here, or still queued (`_advance` skips a done one)
        request, _future = self._current
        self._current = None
        self._always.setChecked(False)
        self.expired.emit(request.tool)
        self._advance()

    def _advance(self) -> None:
        while self._queue:
            request, future = self._queue.pop(0)
            if future.done():  # gave up while queued behind another request
                continue
            self._current = (request, future)
            self._show_question()
            self.setHidden(False)
            return
        self._current = None
        self.setHidden(True)

    def _retranslate(self) -> None:
        self._always.setText(i18n.t("confirmAlways"))
        self._allow.setText(i18n.t("confirmAllow"))
        self._deny.setText(i18n.t("confirmDeny"))
        if self._current is not None:
            self._show_question()

    def _show_question(self) -> None:
        """The request on screen, worded now: its title and reason are i18n keys (core is
        language-free), so a language switch rewords the question already up."""
        request = self._current[0]
        self._title.setText(_title(request))
        reason = getattr(request, "reason", "")
        # A tick never outranks «cannot be undone» (the Arbiter, 2026-10-14), so on that question
        # it answered nothing asked — and remembered the tool for the whole project: a later
        # ordinary write passed unasked (the Arbiter's VM, W-10). Not offered there.
        self._always.setHidden(reason == IRREVERSIBLE)
        self._detail.setText(f"{i18n.t(reason)}: {request.detail}" if reason else request.detail)
        self._fit_question()
        self._update_remaining()

    def _fit_question(self) -> None:
        """As tall as the question at this width, up to `_QUESTION_LINES` — then it scrolls.

        Set by hand: a scroll area reports a height of several lines until it is shown, so left to
        its own hint a one-line `ls` came out in a block 70 px taller than before (TEST-FINDINGS 24).
        """
        line = self._detail.fontMetrics().lineSpacing()
        width = max(self.width() - 24, 200)
        wanted = self._question.layout().heightForWidth(width)
        if wanted < 0:
            wanted = self._question.sizeHint().height()
        ceiling = line * _QUESTION_LINES + 8
        panel = self.parentWidget()
        if panel is not None and panel.height() > 0:
            ceiling = min(ceiling, max(line * 3, int(panel.height() * _QUESTION_SHARE)))
        self._question_scroll.setFixedHeight(max(line, min(wanted + 2, ceiling)))

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        if self._current is not None:
            self._fit_question()  # rewrapped at the new width, so the height changes with it

    def _update_remaining(self) -> None:
        extra = len(self._queue)
        self._remaining.setText(i18n.t("confirmMore").format(n=extra) if extra else "")


def _title(request: ConfirmRequest) -> str:
    """The request's title in the window's language: its key filled from `title_args`. A title that
    is not a key — or that its values do not fit — shows as it came."""
    text = i18n.t(request.title)
    args = getattr(request, "title_args", None) or {}
    try:
        return text.format(**args) if args else text
    except (KeyError, IndexError, ValueError):
        return text
