"""Read-only "what TCC found on disk" strip (TCC-TZ.md §8).

MCP-server-down, terminal-launch results and similar facts used to land as chat bubbles in the
dialog (`main_window._add_system_message`), mixed in with actual AI conversation. §8 calls that
out as wrong in *any* mode: this widget is the fix -- a single-line, single-message notice, shown
regardless of view/control mode, that holds the latest fact and nothing else (not a log).
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel

Level = Literal["info", "warn"]

#: How long a passing FACT stays. Long enough to read twice, short enough that it is gone before
#: it becomes furniture. A warning is not on this clock — see `notify`.
_INFO_SECONDS = 30


class StatusStrip(QLabel):
    def __init__(self) -> None:
        super().__init__("")
        self.setProperty("class", "status-strip")
        self.setWordWrap(True)
        self.setVisible(False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._expire)

    def notify(self, text: str, level: Level = "info") -> None:
        """Show the latest fact — and, when it is an EVENT, let go of it after a while.

        The difference is not decoration. `info` says something HAPPENED ("opened a terminal
        running claude"); it was true for a second, and a minute later it is words sitting under
        whatever the person is doing now — which is what the user met on 2026-09-09, the line
        still there long after the terminal had been opened, used and answered.

        `warn` says something IS: the MCP config could not be written, a route answered with
        nothing. That is as true in a minute as it is now, and timing it out would hide a problem
        rather than tidy a screen. So warnings stay until something replaces them.
        """
        self._timer.stop()
        if level != "warn":
            self._timer.start(_INFO_SECONDS * 1000)
        self.setText(text)
        self.setProperty("class", f"status-strip status-{level}" if level == "warn" else "status-strip")
        self.style().unpolish(self)
        self.style().polish(self)
        self.setVisible(True)

    def clear(self) -> None:
        self._timer.stop()
        self.setText("")
        self.setVisible(False)

    def timer_is_running(self) -> bool:
        """For the test, and for anybody wondering whether this line is on a clock."""
        return self._timer.isActive()

    def _expire(self) -> None:
        """The clock ran out. Nothing else changed, so nothing else is touched."""
        self.clear()
