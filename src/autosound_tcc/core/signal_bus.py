"""One-way notice board: things the *user* did in TCC's UI that the AI needs to know about.

This is the answer to "can TCC push something to the skill?" (the plan's W1). The agent is the
only party that can act, and it only acts when it calls a tool -- so TCC never interrupts it.
Instead the UI drops a signal here and the agent picks it up, either by polling
(`get_pending_signals`) or by parking on `wait_for_signal`, which Claude Code turns into a real
push by backgrounding any MCP call that outlives two minutes.

Two independent consumers, deliberately:

* the **queue** is delivery -- drained exactly once, so a signal is acted on by one turn;
* `.tcc/signals.jsonl` is the **audit log** -- append-only, never drained, so "why did the agent
  suddenly re-check m_L" stays answerable after the fact (same store-facts/derive-views principle
  the ledger and journal follow, TCC-TZ.md §3).

Thread model: `push()` is called from the Qt GUI thread, `drain()`/`wait()` from the MCP server's
own thread. Everything here is guarded by one `Condition`; nothing in this module touches Qt.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# Signal kinds. Kept as plain strings (not an Enum) because they cross a JSON boundary into a
# model's context -- the value the agent reads should be the value written here, with no mapping
# step where the two can drift.
PARAM_EDIT_MODE = "param_edit_mode"  # the ✎ chip: user is correcting ledger values by hand
NOT_VISIBLE = "not_visible"  # "I don't see this in the UI" -- re-check, something didn't land
SELECTION = "selection"  # user moved attention: channel / preset / measurement session
NOTE = "note"  # free-text aside typed into the panel


@dataclass(frozen=True)
class Signal:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SignalBus:
    """Thread-safe queue of pending user signals, mirrored to an append-only log."""

    def __init__(self, tcc_dir: Optional[Path] = None) -> None:
        self._cond = threading.Condition()
        self._pending: list[Signal] = []
        self._log_path = Path(tcc_dir) / "signals.jsonl" if tcc_dir else None

    def push(self, kind: str, **payload: Any) -> Signal:
        """Record a user signal. Safe to call from the GUI thread."""
        signal = Signal(kind=kind, payload=payload)
        with self._cond:
            self._pending.append(signal)
            self._cond.notify_all()
        self._append_log(signal)
        return signal

    def drain(self) -> list[Signal]:
        """Take every pending signal, leaving the queue empty."""
        with self._cond:
            taken, self._pending = self._pending, []
        return taken

    def wait(self, timeout: float) -> list[Signal]:
        """Block up to `timeout` seconds for at least one signal, then drain.

        Returns an empty list on timeout. Callers slice a long wait into several short ones so
        they can emit progress between slices -- an MCP call that goes quiet for the client's idle
        window is aborted, so a single long block would be killed rather than answered.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while not self._pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._cond.wait(remaining)
            taken, self._pending = self._pending, []
        return taken

    @property
    def pending_count(self) -> int:
        with self._cond:
            return len(self._pending)

    def _append_log(self, signal: Signal) -> None:
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(signal.as_dict(), ensure_ascii=False) + "\n")
        except OSError:
            # The log is an audit convenience; a read-only or missing project folder must not take
            # the UI down mid-click. Delivery still works -- it lives in the queue, not the file.
            pass
