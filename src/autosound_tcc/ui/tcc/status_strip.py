"""Read-only "what TCC found on disk" strip (TCC-TZ.md §8).

MCP-server-down, terminal-launch results and similar facts used to land as chat bubbles in the
dialog (`main_window._add_system_message`), mixed in with actual AI conversation. §8 calls that
out as wrong in *any* mode: this widget is the fix -- a single-line, single-message notice, shown
regardless of view/control mode, that holds the latest fact and nothing else (not a log).
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtWidgets import QLabel

Level = Literal["info", "warn"]


class StatusStrip(QLabel):
    def __init__(self) -> None:
        super().__init__("")
        self.setProperty("class", "status-strip")
        self.setWordWrap(True)
        self.setVisible(False)

    def notify(self, text: str, level: Level = "info") -> None:
        self.setText(text)
        self.setProperty("class", f"status-strip status-{level}" if level == "warn" else "status-strip")
        self.style().unpolish(self)
        self.style().polish(self)
        self.setVisible(True)

    def clear(self) -> None:
        self.setText("")
        self.setVisible(False)
