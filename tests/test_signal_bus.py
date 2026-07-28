"""SignalBus: the UI→agent notice board (core/signal_bus.py)."""

from __future__ import annotations

import json
import threading
import time

from autosound_tcc.core.signal_bus import NOT_VISIBLE, PARAM_EDIT_MODE, SignalBus


def test_push_then_drain_empties_the_queue(tmp_path):
    bus = SignalBus(tmp_path)
    bus.push(PARAM_EDIT_MODE, on=True, reason="forgot")
    bus.push(NOT_VISIBLE, note="band 3 missing")

    drained = bus.drain()

    assert [s.kind for s in drained] == [PARAM_EDIT_MODE, NOT_VISIBLE]
    assert drained[0].payload == {"on": True, "reason": "forgot"}
    # Delivery is exactly-once: a second turn must not re-act on signals already handled.
    assert bus.drain() == []
    assert bus.pending_count == 0


def test_every_signal_is_mirrored_to_the_append_only_log(tmp_path):
    bus = SignalBus(tmp_path)
    bus.push(PARAM_EDIT_MODE, on=True)
    bus.drain()  # draining is delivery, and must not touch the audit trail
    bus.push(NOT_VISIBLE, note="x")

    lines = (tmp_path / "signals.jsonl").read_text(encoding="utf-8").splitlines()

    assert [json.loads(line)["kind"] for line in lines] == [PARAM_EDIT_MODE, NOT_VISIBLE]


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


def test_log_failure_never_breaks_delivery(tmp_path):
    """A read-only or missing project folder must not take the UI down on a click."""
    bus = SignalBus(tmp_path / "nope" / "deeper")
    (tmp_path / "nope").write_text("i am a file, not a directory", encoding="utf-8")

    bus.push(PARAM_EDIT_MODE, on=False)

    assert [s.kind for s in bus.drain()] == [PARAM_EDIT_MODE]
