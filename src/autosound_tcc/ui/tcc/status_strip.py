"""Read-only "what TCC found on disk" strip (TCC-TZ.md §8).

MCP-server-down, terminal-launch results and similar facts used to land as chat bubbles in the
dialog (`main_window._add_system_message`), mixed in with actual AI conversation. §8 calls that
out as wrong in *any* mode: this widget is the fix -- a single-line, single-message notice, shown
regardless of view/control mode, that holds the latest fact and nothing else (not a log).

A long message scrolls inside three lines instead of pushing the window down, and a warning can
always be closed (the Arbiter, 2026-09-23, about sixteen lines that took half the window).

One line is "the latest" except for what `app_log` reports, which stands until its ✕ (#173, I1):
a store set aside at launch was said and, in the same `__init__`, written over before anyone read
it. The latest of the other lines waits behind it, counted beside the ✕.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Callable, Literal, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QToolButton

from autosound_tcc.ui.tcc import i18n

Level = Literal["info", "warn"]

#: How long a passing FACT stays. Long enough to read twice, short enough that it is gone before
#: it becomes furniture. A warning is not on this clock — see `notify`.
_INFO_SECONDS = 30
#: How many lines the strip may take before it scrolls.
_MAX_LINES = 3
#: How many standing lines are kept, the one shown among them — `app_log`'s own bound on what it
#: holds for a window. Each is said once per state of its file; this is for what is not.
_STANDING_MAX = 20


@dataclass(eq=False)
class _Line:
    """One `notify`, as it was asked for: shown now, or waiting its turn."""

    text: str
    level: Level
    action: Optional[tuple[str, Callable[[], None]]]
    dismissible: bool
    on_dismiss: Optional[Callable[[], None]]


class StatusStrip(QFrame):
    #: A link in the line was clicked — `action` (the offer) or `close` (the ✕).
    linkActivated = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("class", "status-strip")
        self._label = QLabel("")
        self._label.setProperty("class", "status-strip-text")
        self._label.setWordWrap(True)
        self._label.setOpenExternalLinks(False)
        self._label.linkActivated.connect(self.linkActivated.emit)
        self._scroll = QScrollArea()
        self._scroll.setProperty("class", "status-strip-scroll")
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setWidget(self._label)
        # The ✕ sits beside the text, not at its end: at the end of sixteen lines it scrolled out
        # of sight together with them.
        self._close = QToolButton()
        self._close.setText("✕")
        self._close.setProperty("class", "status-strip-close")
        self._close.setAutoRaise(True)
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.clicked.connect(lambda: self.linkActivated.emit("close"))
        self._close.setVisible(False)
        # How many lines wait behind a standing one: beside the ✕ that brings the next (I1).
        self._more = QLabel("")
        self._more.setProperty("class", "status-strip-more")
        self._more.setVisible(False)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(0)
        row.addWidget(self._scroll, 1)
        row.addWidget(self._more, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._close, 0, Qt.AlignmentFlag.AlignTop)
        self._fit_height()
        self.setVisible(False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._expire)
        #: The lines that stand until their ✕, oldest first; the first is the one shown.
        self._standing: list[_Line] = []
        #: The latest of every other line: shown, or waiting behind a standing one. Its clock runs
        #: only while it is shown (the re-review, N2).
        self._line: Optional[_Line] = None
        self._shown: Optional[_Line] = None
        self.linkActivated.connect(self._on_link)

    def _fit_height(self) -> None:
        """As tall as the text, up to three whole lines of its own font — beyond that, it scrolls.

        A scroll area does not follow its content's height by itself: one line stood in a box
        sized for three."""
        self._label.ensurePolished()
        margins = self._label.contentsMargins()
        padding = margins.top() + margins.bottom()
        most = self._label.fontMetrics().lineSpacing() * _MAX_LINES + padding
        width = self._scroll.viewport().width()
        needed = self._label.heightForWidth(width) if width > 0 else -1
        height = most if needed < 0 else min(needed, most)
        self._scroll.setFixedHeight(height)
        self.setFixedHeight(height + 1)  # and the border under it

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt's name
        super().resizeEvent(event)
        self._fit_height()

    def can_close(self) -> bool:
        """Whether the ✕ is offered for the line now shown."""
        return not self._close.isHidden()

    def text(self) -> str:
        return self._label.text()

    def notify(self, text: str, level: Level = "info",
               action: Optional[tuple[str, Callable[[], None]]] = None,
               dismissible: bool = False,
               on_dismiss: Optional[Callable[[], None]] = None,
               sticky: bool = False) -> None:
        """Show the latest fact — and, when it is an EVENT, let go of it after a while.

        The difference is not decoration. `info` says something HAPPENED ("opened a terminal
        running claude"); it was true for a second, and a minute later it is words sitting under
        whatever the person is doing now — which is what the user met on 2026-09-09, the line
        still there long after the terminal had been opened, used and answered.

        `warn` says something IS: the MCP config could not be written, a route answered with
        nothing. That is as true in a minute as it is now, and timing it out would hide a problem
        rather than tidy a screen. So warnings stay until something replaces them — or until the
        Arbiter closes them: every warning carries a ✕.

        An `action` is an OFFER -- one link at the end of the line, taken with one click. It is
        not on the clock either: an offer that expires while the Arbiter reads the form it
        follows was never made.

        `dismissible` offers the ✕ for a message that is not a warning; `on_dismiss` hears it.

        `sticky` is a line nothing replaces: it stands until its own ✕ (#173, I1). What `app_log`
        reports comes this way — a store set aside at launch was said, then written over in the
        same `__init__` by the process's own lines, and its memo kept it from being said again.
        Later lines do not replace it: the latest of them waits behind it, counted beside the ✕,
        and comes when it is closed. Several stand in the order they came; the same sentence
        stands once. A fact's thirty seconds start when it is shown, not while it waits: one said
        once — «Not written down: …» — ran out behind the report unseen (the re-review, N2).
        """
        line = _Line(text, level, action, dismissible or level == "warn" or sticky, on_dismiss)
        if sticky:
            if any(standing.text == text for standing in self._standing):
                return
            self._standing.append(line)
            if len(self._standing) > _STANDING_MAX:
                del self._standing[1]  # the oldest of those waiting, never the one being read
        else:
            self._timer.stop()
            self._line = line
        self._show()

    def _show(self) -> None:
        """Put the line whose turn it is on screen — the first standing one, else the latest — and
        the count of what waits behind it."""
        line = self._standing[0] if self._standing else self._line
        if line is not self._line:
            self._timer.stop()  # waiting behind a standing line, a fact is off its clock (N2)
        behind = len(self._standing) - 1 + (self._line is not None) if self._standing else 0
        self._more.setText(i18n.t("stripMore").format(n=behind) if behind else "")
        self._more.setToolTip(i18n.t("stripMoreTip") if behind else "")
        self._more.setVisible(behind > 0)
        if line is self._shown:
            self._fit_height()
            return
        self._shown = line
        if line is None:
            self._label.setText("")
            self._close.setVisible(False)
            self.setVisible(False)
            return
        if line.action is None:
            self._label.setTextFormat(Qt.TextFormat.AutoText)
            self._label.setText(line.text)
        else:
            self._label.setTextFormat(Qt.TextFormat.RichText)
            # Plain text, escaped — with its line breaks kept as breaks.
            body = html.escape(line.text).replace("\n", "<br>")
            self._label.setText(f'{body} &nbsp;<a href="action">{html.escape(line.action[0])}</a>')
        self._close.setVisible(line.dismissible)
        warn = " status-warn" if line.level == "warn" else ""
        self.setProperty("class", "status-strip" + warn)
        self._label.setProperty("class", "status-strip-text" + warn)
        for widget in (self, self._label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._fit_height()
        self._scroll.verticalScrollBar().setValue(0)
        self.setVisible(True)
        if line is self._line and line.level != "warn" and line.action is None:
            self._timer.start(_INFO_SECONDS * 1000)  # shown now: its thirty seconds start

    def clear(self) -> None:
        """Let go of the latest line, shown or waiting. A standing line stays until its own ✕: what
        a caller clears is its own cause — the record that has now been written — not a report."""
        self._timer.stop()
        self._line = None
        self._show()

    def withdraw(self, text: Optional[str]) -> bool:
        """Let go of the latest line if it says `text`, shown or waiting behind a standing one: a
        caller takes back its own line once its cause has ended, never a report or a line that came
        after it. Taken back only while shown, a line waiting behind a report came back at the
        report's ✕ — false, and a warning has no clock (the review of #175 TA-8, I1). Whether it
        took the line back: the slot is then the caller's again, and not before (G6+G7, M1)."""
        if text and self._line is not None and self._line.text == text:
            self.clear()
            return True
        return False

    def waiting(self) -> list[str]:
        """The lines behind the one shown, in the order its ✕ brings them — for the test, and for
        anybody wondering what the count beside it counts."""
        if not self._standing:
            return []
        rest = [line.text for line in self._standing[1:]]
        return rest + ([self._line.text] if self._line is not None else [])

    def timer_is_running(self) -> bool:
        """For the test, and for anybody wondering whether this line is on a clock."""
        return self._timer.isActive()

    def _expire(self) -> None:
        """The latest line's clock ran out. Nothing else changed, so nothing else is touched."""
        self._line = None
        self._show()

    def _on_link(self, href: str) -> None:
        line = self._shown
        if line is None or (href != "close" and line.action is None):
            return
        if self._standing and line is self._standing[0]:
            self._standing.pop(0)
        else:
            self._timer.stop()
            self._line = None
        self._show()
        callback = line.on_dismiss if href == "close" else line.action[1]
        if callback is not None:
            callback()
