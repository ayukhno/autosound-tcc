"""SignalBus: the UI→agent notice board (core/signal_bus.py).

Delivery here is peek + ack (F-009): reading marks a signal delivered, only `ack()` closes it,
and a signal delivered but never acked is restored at the end of the turn. The tests below pin
the property the whole design exists for -- a signal cannot be lost silently.
"""

from __future__ import annotations

import json
import threading
import time

from autosound_tcc.core.signal_bus import (
    ACK_APPLIED,
    ACK_EVENT,
    ACK_REFUSED,
    CHANNEL_TOGGLE,
    NOT_VISIBLE,
    PARAM_EDIT_MODE,
    RESTORE_WINDOW_S,
    Signal,
    SignalBus,
    with_pending_brief,
)


def _log_lines(tmp_path):
    return (tmp_path / "signals.jsonl").read_text(encoding="utf-8").splitlines()


# ---- delivery: peek + ack --------------------------------------------------


def test_deliver_marks_signals_delivered_without_losing_them(tmp_path):
    """F-009: reading is not handling. A drain here is how four channel_toggle signals vanished
    into a turn that did nothing with them."""
    bus = SignalBus(tmp_path)
    bus.push(PARAM_EDIT_MODE, on=True, reason="forgot")
    bus.push(NOT_VISIBLE, note="band 3 missing")

    first = bus.deliver()
    second = bus.deliver()

    assert [s.kind for s in first] == [PARAM_EDIT_MODE, NOT_VISIBLE]
    assert first[0].payload == {"on": True, "reason": "forgot"}
    # Un-acked signals stay on the books: a second read sees the same open requests.
    assert [s.id for s in second] == [s.id for s in first]
    assert bus.pending_count == 2  # delivered, but still open


def test_ack_closes_a_signal_for_good(tmp_path):
    bus = SignalBus(tmp_path)
    signal = bus.push(NOT_VISIBLE, note="x")
    bus.deliver()

    acked, unknown = bus.ack([signal.id], ACK_APPLIED, note="re-checked against disk")

    assert (acked, unknown) == ([signal.id], [])
    assert bus.deliver() == []
    assert bus.pending_count == 0


def test_ack_works_on_a_signal_that_was_never_delivered(tmp_path):
    """The per-turn preamble names ids, so the agent may close a signal it never read through a
    tool call."""
    bus = SignalBus(tmp_path)
    signal = bus.push(CHANNEL_TOGGLE, group="rear", channel="r-L", on=False)

    acked, unknown = bus.ack([signal.id], ACK_APPLIED)

    assert (acked, unknown) == ([signal.id], [])
    assert bus.pending_count == 0


def test_an_unknown_id_is_reported_not_swallowed(tmp_path):
    bus = SignalBus(tmp_path)
    signal = bus.push(NOT_VISIBLE, note="x")

    acked, unknown = bus.ack([signal.id, "not-an-id"], ACK_APPLIED)

    assert acked == [signal.id]
    assert unknown == ["not-an-id"]


def test_restore_returns_delivered_signals_to_pending(tmp_path):
    """The end-of-turn rule: delivered-but-unacked must not die with the turn."""
    bus = SignalBus(tmp_path)
    bus.push(CHANNEL_TOGGLE, group="rear", channel="r-L", on=False)
    bus.deliver()

    bus.restore_delivered()

    # `wait` only sees *pending* signals, so returning here proves the restore.
    assert [s.kind for s in bus.wait(timeout=0.05)] == [CHANNEL_TOGGLE]


def test_restore_wakes_a_parked_waiter(tmp_path):
    """An agent that peeked and parked without acking still owes the Arbiter an outcome, so the
    restored signal must reach it as a push, not wait for the next poll."""
    bus = SignalBus(tmp_path)
    bus.push(NOT_VISIBLE, note="late")
    bus.deliver()
    threading.Timer(0.05, bus.restore_delivered).start()

    started = time.monotonic()
    signals = bus.wait(timeout=5.0)

    assert [s.kind for s in signals] == [NOT_VISIBLE]
    assert time.monotonic() - started < 2.0  # woke on the notify, didn't sit out the timeout


# ---- wait ------------------------------------------------------------------


def test_wait_returns_as_soon_as_the_ui_pushes(tmp_path):
    """The push path: an agent parked on wait() wakes on the GUI thread's push, not on a poll."""
    bus = SignalBus(tmp_path)
    threading.Timer(0.05, lambda: bus.push(NOT_VISIBLE, note="late")).start()

    started = time.monotonic()
    signals = bus.wait(timeout=5.0)

    assert [s.kind for s in signals] == [NOT_VISIBLE]
    assert time.monotonic() - started < 2.0  # woke on the notify, didn't sit out the timeout


def test_wait_times_out_to_an_empty_list(tmp_path):
    assert SignalBus(tmp_path).wait(timeout=0.05) == []


def test_wait_does_not_return_what_is_already_delivered(tmp_path):
    """A parked agent has seen the delivered set; waking it for that would make every park
    return instantly."""
    bus = SignalBus(tmp_path)
    bus.push(NOT_VISIBLE, note="seen")
    bus.deliver()

    assert bus.wait(timeout=0.05) == []
    assert bus.pending_count == 1  # still open, just not news


# ---- the audit log ---------------------------------------------------------


def test_every_signal_is_mirrored_to_the_append_only_log(tmp_path):
    bus = SignalBus(tmp_path)
    bus.push(PARAM_EDIT_MODE, on=True)
    bus.deliver()  # delivery must not touch the audit trail
    bus.push(NOT_VISIBLE, note="x")

    lines = _log_lines(tmp_path)

    assert [json.loads(line)["kind"] for line in lines] == [PARAM_EDIT_MODE, NOT_VISIBLE]


def test_an_ack_is_the_logs_second_half(tmp_path):
    """The raise says what the Arbiter asked; the ack says what came of it. Both survive the
    process, which is what makes the question answerable after a restart."""
    bus = SignalBus(tmp_path)
    signal = bus.push(CHANNEL_TOGGLE, group="rear", channel="r-L", on=False)

    bus.ack([signal.id], ACK_REFUSED, note="r-L is the sub feed; muting it needs D-2")

    record = json.loads(_log_lines(tmp_path)[-1])
    assert record["event"] == ACK_EVENT
    assert record["id"] == signal.id
    assert record["outcome"] == ACK_REFUSED
    assert "D-2" in record["note"]
    assert record["at"] > 0


def test_log_failure_never_breaks_delivery(tmp_path):
    """A read-only or missing project folder must not take the UI down on a click."""
    bus = SignalBus(tmp_path / "nope" / "deeper")
    (tmp_path / "nope").write_text("i am a file, not a directory", encoding="utf-8")

    bus.push(PARAM_EDIT_MODE, on=False)

    assert [s.kind for s in bus.deliver()] == [PARAM_EDIT_MODE]


# ---- resume ----------------------------------------------------------------


def test_a_new_bus_restores_the_logs_open_signals(tmp_path):
    """A crash with a click in flight must not mean the Arbiter has to know to click again."""
    first = SignalBus(tmp_path)
    open_signal = first.push(CHANNEL_TOGGLE, group="rear", channel="r-L", on=False)
    closed = first.push(NOT_VISIBLE, note="handled")
    first.ack([closed.id], ACK_APPLIED)

    resumed = SignalBus(tmp_path)

    restored = resumed.deliver()
    assert [s.id for s in restored] == [open_signal.id]
    assert restored[0].payload == open_signal.payload


def test_restore_does_not_resurrect_ancient_history(tmp_path):
    """Logs written before acks existed hold every signal ever raised, all of them un-acked;
    replaying weeks of already-handled clicks into turn one would be its own F-009."""
    stale = Signal(kind=NOT_VISIBLE, payload={"note": "old"}, at=time.time() - RESTORE_WINDOW_S - 60)
    (tmp_path / "signals.jsonl").write_text(
        json.dumps(stale.as_dict()) + "\n", encoding="utf-8"
    )

    assert SignalBus(tmp_path).pending_count == 0


def test_a_torn_log_line_restores_what_can_be_read(tmp_path):
    fresh = Signal(kind=PARAM_EDIT_MODE, payload={"on": True})
    (tmp_path / "signals.jsonl").write_text(
        json.dumps(fresh.as_dict()) + "\n" + '{"kind": "not_visible", "payl',  # torn mid-write
        encoding="utf-8",
    )

    bus = SignalBus(tmp_path)

    assert [s.id for s in bus.deliver()] == [fresh.id]


# ---- the per-turn preamble -------------------------------------------------


def test_the_brief_is_silent_when_nothing_is_open(tmp_path):
    """It is spent context on every turn it appears in, so an empty queue must cost nothing."""
    bus = SignalBus(tmp_path)
    assert bus.unacked_brief() == ""
    assert with_pending_brief(bus, "hello") == "hello"
    assert with_pending_brief(None, "hello") == "hello"


def test_the_brief_names_every_open_signal_delivered_or_not(tmp_path):
    bus = SignalBus(tmp_path)
    seen = bus.push(CHANNEL_TOGGLE, group="rear", channel="r-L", on=False)
    bus.deliver()  # read once, not acked -- still the Arbiter's open request
    fresh = bus.push(NOT_VISIBLE, note="band 3 missing")

    brief = bus.unacked_brief()

    assert "2 un-acknowledged" in brief
    assert seen.id in brief and fresh.id in brief
    assert CHANNEL_TOGGLE in brief and '"r-L"' in brief
    assert "ack_signals" in brief  # the way out is named where the debt is stated


def test_the_brief_is_prepended_to_the_turn_not_appended(tmp_path):
    """First thing in the turn: the block frames what follows, it does not trail it."""
    bus = SignalBus(tmp_path)
    bus.push(NOT_VISIBLE, note="x")

    text = with_pending_brief(bus, "what next?")

    assert text.startswith("[TCC]")
    assert text.endswith("what next?")
