"""The Qt end of `core.mcp_server.UiBridge` — the only place the agent's world touches widgets.

Two threads meet here and neither may reach into the other. The MCP server runs its own asyncio
loop on a background thread and calls these methods from there; Qt widgets may only be touched on
the GUI thread. Every crossing therefore goes one of two ways:

* **agent → GUI**: emit a Qt signal. Emitting is thread-safe, and because this object lives on the
  GUI thread the connection is automatically queued, so the slot runs where the widgets are.
* **GUI → agent**: the GUI writes into a plain dict/`Future` under a lock, which the server thread
  reads. Nothing on that path is a widget.

`snapshot()` deliberately returns a *cached* dict rather than reading widgets live: the caller is
on the server thread, and walking the widget tree from there is exactly the use-after-free class
of bug this project has already been bitten by.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future
from typing import Any

from PySide6.QtCore import QObject, Signal

from autosound_tcc.core.mcp_server import ConfirmRequest


class QtUiBridge(QObject):
    """Implements `UiBridge` for the running application."""

    # (ConfirmRequest, Future[bool]) — the panel resolves the future when the Arbiter answers.
    confirmationRequested = Signal(object, object)
    clipboardRequested = Signal(str)
    proposalReceived = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] = {}

    # ---- GUI side ----------------------------------------------------------

    def set_snapshot(self, **fields: Any) -> None:
        """Publish what the Arbiter currently has on screen. Called from the GUI thread.

        Merges rather than replaces so each widget can report only its own slice (the tree its
        selection, the header its preset) without having to know the whole shape.
        """
        with self._lock:
            self._snapshot.update(fields)

    # ---- agent side (called on the MCP server thread) ----------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._snapshot)

    def request_confirmation(self, request: ConfirmRequest) -> "Future[bool]":
        future: "Future[bool]" = Future()
        self.confirmationRequested.emit(request, future)
        return future

    def copy_to_clipboard(self, text: str) -> None:
        self.clipboardRequested.emit(text)

    def show_proposal(self, proposal: dict[str, Any]) -> None:
        self.proposalReceived.emit(proposal)
