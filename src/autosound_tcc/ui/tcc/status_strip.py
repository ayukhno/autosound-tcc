"""Read-only "what TCC found on disk" strip (TCC-TZ.md §8).

MCP-server-down, terminal-launch results and similar facts used to land as chat bubbles in the
dialog (`main_window._add_system_message`), mixed in with actual AI conversation. §8 calls that
out as wrong in *any* mode: this widget is the fix -- a single-line, single-message notice, shown
regardless of view/control mode, that holds the latest fact and nothing else (not a log).

A long message scrolls inside three lines instead of pushing the window down, and a warning can
always be closed (the Arbiter, 2026-09-23, about sixteen lines that took half the window).
"""

from __future__ import annotations

import html
from typing import Callable, Literal, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QToolButton

Level = Literal["info", "warn"]

#: How long a passing FACT stays. Long enough to read twice, short enough that it is gone before
#: it becomes furniture. A warning is not on this clock — see `notify`.
_INFO_SECONDS = 30
#: How many lines the strip may take before it scrolls.
_MAX_LINES = 3


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
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(0)
        row.addWidget(self._scroll, 1)
        row.addWidget(self._close, 0, Qt.AlignmentFlag.AlignTop)
        self._fit_height()
        self.setVisible(False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._expire)
        self._action: Optional[Callable[[], None]] = None
        self._on_dismiss: Optional[Callable[[], None]] = None
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
               on_dismiss: Optional[Callable[[], None]] = None) -> None:
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
        """
        self._timer.stop()
        self._action = action[1] if action else None
        self._on_dismiss = on_dismiss
        dismissible = dismissible or level == "warn"
        if level != "warn" and action is None:
            self._timer.start(_INFO_SECONDS * 1000)
        if action is None:
            self._label.setTextFormat(Qt.TextFormat.AutoText)
            self._label.setText(text)
        else:
            self._label.setTextFormat(Qt.TextFormat.RichText)
            # Plain text, escaped — with its line breaks kept as breaks.
            body = html.escape(text).replace("\n", "<br>")
            self._label.setText(f'{body} &nbsp;<a href="action">{html.escape(action[0])}</a>')
        self._close.setVisible(dismissible)
        warn = " status-warn" if level == "warn" else ""
        self.setProperty("class", "status-strip" + warn)
        self._label.setProperty("class", "status-strip-text" + warn)
        for widget in (self, self._label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._fit_height()
        self._scroll.verticalScrollBar().setValue(0)
        self.setVisible(True)

    def clear(self) -> None:
        self._timer.stop()
        self._action = None
        self._on_dismiss = None
        self._label.setText("")
        self._close.setVisible(False)
        self.setVisible(False)

    def timer_is_running(self) -> bool:
        """For the test, and for anybody wondering whether this line is on a clock."""
        return self._timer.isActive()

    def _expire(self) -> None:
        """The clock ran out. Nothing else changed, so nothing else is touched."""
        self.clear()

    def _on_link(self, href: str) -> None:
        callback = self._on_dismiss if href == "close" else self._action
        self.clear()
        if callback is not None:
            callback()
