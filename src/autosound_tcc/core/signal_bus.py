"""One-way notice board: things the *user* did in TCC's UI that the AI needs to know about.

This is the answer to "can TCC push something to the skill?" (the plan's W1). The agent is the
only party that can act, and it only acts when it calls a tool -- so TCC never interrupts it.
Instead the UI drops a signal here and the agent picks it up: polled (`get_pending_signals`),
parked on (`wait_for_signal`), or -- the F-009 fix -- prepended to the next user turn by the
session adapters (`with_pending_brief`), so a turn in which the agent calls no tool at all still
learns what the Arbiter asked for.

Delivery used to be a drain: read once, gone. That is how four `channel_toggle` signals sat for
seven minutes and then vanished into a turn that did nothing with them (F-009, 2026-08-21). Now
reading only marks a signal *delivered*; it leaves the books when the agent closes it with
`ack()`, and a signal delivered but not acked by the end of the turn is restored to pending, so
the next turn raises it again. A signal is either closed with an outcome or still waiting --
there is no third state where it is silently gone.

Two independent consumers, deliberately:

* the **queue** is delivery -- pending, delivered, acked, as above;
* `.tcc/signals.jsonl` is the **audit log** -- append-only, never drained, so "why did the agent
  suddenly re-check m_L" stays answerable after the fact (same store-facts/derive-views principle
  the ledger and journal follow, TCC-TZ.md §3). Every raise is one line; since F-009 every ack is
  one line too, which is what lets a fresh bus restore the still-open signals of a crashed
  session (`_restore_from_log`).

Thread model: `push()` is called from the Qt GUI thread, `deliver()`/`wait()`/`ack()` from the
MCP server's own thread, and `restore_delivered()` from the session adapters' worker thread.
Everything here is guarded by one `Condition`; nothing in this module touches Qt.
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
# The Arbiter flipped a channel on or off in the tree. An INTENT, not a write: enabling a channel
# changes the ledger, and the ledger is the skill's to write (D-6). TCC says what was asked for and
# the model records it, the same way the ✎ chip works -- which is why every channel is now shown,
# including the ones nobody is using. You cannot switch on what the panel refuses to draw.
CHANNEL_TOGGLE = "channel_toggle"

# Ack outcomes. Plain strings for the same reason the kinds are: they cross the JSON boundary,
# and the value the agent writes should be the value the audit log keeps.
ACK_APPLIED = "applied"  # the request was carried out (recorded, proposed, executed)
ACK_REFUSED = "refused"  # deliberately not done -- the note must say why
ACK_SUPERSEDED = "superseded"  # a later signal or event made this one moot
ACK_OUTCOMES = frozenset({ACK_APPLIED, ACK_REFUSED, ACK_SUPERSEDED})

# The audit log's second record shape (the first is a raised Signal's own dict). Distinguished by
# this key so the raise lines stay byte-compatible with every log written before acks existed.
ACK_EVENT = "signal_acked"

# How far back `_restore_from_log` reaches. Bounded for two reasons: logs written before acks
# existed hold every signal ever raised, all of them un-acked, and resurrecting weeks of already-
# handled clicks into turn one would be its own F-009; and a signal is an in-session request --
# yesterday's "switch off r-L" re-raised into today's tune is noise, not delivery. One hour covers
# the real case, a crash and a relaunch minutes later, with room to spare.
RESTORE_WINDOW_S = 3600.0


@dataclass(frozen=True)
class Signal:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"


class SignalBus:
    """Thread-safe queue of open user signals, mirrored to an append-only log.

    A signal is *pending* (raised, not yet read), *delivered* (read by the agent, still open), or
    gone because `ack()` closed it with an outcome. Construction replays the log, so the open
    signals of a session that crashed are pending again when TCC comes back up.
    """

    def __init__(self, tcc_dir: Optional[Path] = None) -> None:
        self._cond = threading.Condition()
        self._pending: list[Signal] = []
        # Delivered-but-open signals, kept whole rather than as ids so restoring them needs no
        # lookup. The queue's own order is by `at`, re-imposed on every way back out.
        self._delivered: dict[str, Signal] = {}
        self._log_path = Path(tcc_dir) / "signals.jsonl" if tcc_dir else None
        self._restore_from_log()

    def push(self, kind: str, **payload: Any) -> Signal:
        """Record a user signal. Safe to call from the GUI thread."""
        signal = Signal(kind=kind, payload=payload)
        with self._cond:
            self._pending.append(signal)
            self._cond.notify_all()
        self._append_line(signal.as_dict())
        return signal

    def deliver(self) -> list[Signal]:
        """Every open signal, marked delivered rather than removed.

        Includes signals a previous read already delivered: hiding an open signal because it was
        shown once is a quieter version of the drain this replaced. Nothing leaves the books here
        -- only `ack()` closes a signal.
        """
        with self._cond:
            for signal in self._pending:
                self._delivered[signal.id] = signal
            self._pending = []
            return sorted(self._delivered.values(), key=lambda s: s.at)

    def wait(self, timeout: float) -> list[Signal]:
        """Block up to `timeout` seconds for a newly raised signal, then deliver it.

        Returns an empty list on timeout, and only newly *pending* signals otherwise -- a parked
        agent has already seen the delivered set, and waking it for that would make every park
        return instantly. Callers slice a long wait into several short ones so they can emit
        progress between slices -- an MCP call that goes quiet for the client's idle window is
        aborted, so a single long block would be killed rather than answered.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while not self._pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._cond.wait(remaining)
            taken, self._pending = self._pending, []
            for signal in taken:
                self._delivered[signal.id] = signal
        return taken

    def ack(self, ids: list[str], outcome: str, note: str = "") -> tuple[list[str], list[str]]:
        """Close signals with an outcome; returns `(acked_ids, unknown_ids)`.

        Works on pending signals too, not only delivered ones: the per-turn preamble names ids,
        so the agent may legitimately close a signal it never read through a tool. An unknown id
        is reported back rather than raised -- it is usually a signal acked twice, and a second
        ack arriving late is not worth ending a turn over.

        Each closed signal becomes one `signal_acked` line in the audit log, which is both the
        "what happened to what the Arbiter asked" half of the record and what stops
        `_restore_from_log` resurrecting it.
        """
        acked: list[str] = []
        unknown: list[str] = []
        now = time.time()
        with self._cond:
            for signal_id in ids:
                if self._delivered.pop(signal_id, None) is not None:
                    acked.append(signal_id)
                    continue
                kept = [s for s in self._pending if s.id != signal_id]
                if len(kept) != len(self._pending):
                    self._pending = kept
                    acked.append(signal_id)
                else:
                    unknown.append(signal_id)
        for signal_id in acked:
            self._append_line(
                {"event": ACK_EVENT, "id": signal_id, "outcome": outcome, "note": note, "at": now}
            )
        return acked, unknown

    def restore_delivered(self) -> None:
        """Put every delivered-but-open signal back into pending. Called at the end of a turn.

        This is what makes losing a signal impossible: a turn that read the queue and acked
        nothing has changed nothing, and the next turn's preamble raises the same signals again.
        Waiters are notified because a restored signal is a raised signal as far as a parked
        `wait_for_signal` is concerned -- the agent that peeked and parked without acking is
        exactly the one that still owes the Arbiter an outcome.
        """
        with self._cond:
            if not self._delivered:
                return
            self._pending = sorted(
                [*self._pending, *self._delivered.values()], key=lambda s: s.at
            )
            self._delivered.clear()
            self._cond.notify_all()

    @property
    def pending_count(self) -> int:
        """Open signals: still pending plus delivered-but-unacked.

        A delivered signal is not a handled signal, and counting only the undelivered ones would
        make `get_tcc_state` go quiet mid-turn while the Arbiter's requests are still open.
        """
        with self._cond:
            return len(self._pending) + len(self._delivered)

    def unacked_brief(self) -> str:
        """The per-turn preamble: every open signal, or "" when there is nothing to say.

        Prepended to the outgoing user turn by both session adapters (F-009). The system prompt's
        "call get_pending_signals first" is discipline, not a mechanism -- the turn that skips it
        is exactly the turn this block exists for. It is spent context on every turn it appears
        in, so it stays short, factual, and absent when the queue is empty.
        """
        with self._cond:
            signals = sorted([*self._pending, *self._delivered.values()], key=lambda s: s.at)
        if not signals:
            return ""
        now = time.time()
        lines = [
            f"[TCC] {len(signals)} un-acknowledged signal(s) from the Arbiter -- direct requests "
            "from the human. Handle them before anything else in this turn, then close each with "
            "the tcc `ack_signals` tool:"
        ]
        for signal in signals:
            payload = json.dumps(signal.payload, ensure_ascii=False)
            if len(payload) > 200:
                payload = payload[:200] + "…"
            lines.append(
                f"- {signal.kind} {payload} (raised {_age(now - signal.at)} ago, id {signal.id})"
            )
        return "\n".join(lines)

    def _restore_from_log(self) -> None:
        """Put the log's still-open recent signals back into pending, on construction.

        Replay, not state: the log is the one record that survives a crash, and an Arbiter whose
        click was in flight when TCC died should not have to know to click again. Reads are as
        tolerant as `_append_line` is -- a torn last line or a missing file restores what can be
        read and never blocks construction.
        """
        if self._log_path is None:
            return
        try:
            text = self._log_path.read_text(encoding="utf-8")
        except OSError:
            return
        open_signals: dict[str, Signal] = {}
        for line in text.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("event") == ACK_EVENT:
                open_signals.pop(str(record.get("id")), None)
                continue
            try:
                signal = Signal(
                    kind=str(record["kind"]),
                    payload=dict(record.get("payload") or {}),
                    at=float(record.get("at") or 0.0),
                    id=str(record.get("id") or ""),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if signal.id:
                open_signals[signal.id] = signal
        cutoff = time.time() - RESTORE_WINDOW_S
        self._pending = sorted(
            (s for s in open_signals.values() if s.at >= cutoff), key=lambda s: s.at
        )

    def _append_line(self, record: dict[str, Any]) -> None:
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            # The log is an audit convenience; a read-only or missing project folder must not take
            # the UI down mid-click. Delivery still works -- it lives in the queue, not the file.
            pass


def with_pending_brief(bus: Optional[SignalBus], text: str) -> str:
    """The F-009 injection: prepend the open-signals preamble to an outgoing user turn.

    Shared by both session adapters so "the turn learns about signals" cannot be true on one
    front-end and false on the other. A session without a bus (headless runs, the gate tests, the
    spike) sends its text untouched.
    """
    if bus is None:
        return text
    brief = bus.unacked_brief()
    return f"{brief}\n\n{text}" if brief else text
