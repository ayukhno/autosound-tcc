"""`core.process_writer` — TCC driving the skill's own journal writer.

The writer itself is the skill's (`rew_tool/state/process.py`); what is tested here is the part
TCC owns: getting one call at a time to it.
"""

from __future__ import annotations



def test_concurrent_writes_do_not_corrupt_the_process_state(tmp_path):
    """omp starts tool calls concurrently. A real run fired `enter_phase` and two `add_step`s
    before any returned: two came back with a traceback out of `process.py` and the third left
    `active_phase: null` with one nameless step in the plan. The model had done everything right —
    `process.py` is a read-modify-write over one JSON file and nothing serialised it."""
    import json
    import threading

    from autosound_tcc.core import process_writer

    if not process_writer.is_available():
        import pytest

        pytest.skip("skill submodule not checked out")

    errors: list[str] = []

    def call(fn):
        try:
            fn()
        except process_writer.ProcessWriterError as exc:
            errors.append(str(exc))

    threads = [
        threading.Thread(target=call, args=(lambda: process_writer.enter_phase(tmp_path, "-1"),)),
        threading.Thread(target=call, args=(lambda: process_writer.add_step(tmp_path, "a", "A"),)),
        threading.Thread(target=call, args=(lambda: process_writer.add_step(tmp_path, "b", "B"),)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # What the lock guarantees is that no write lands on top of another. It does NOT decide the
    # order, and it must not: an `add_step` that wins the race against `enter_phase` has no phase
    # to name, and since the phase validation landed the skill REFUSES it (2026-08-12). That
    # refusal is the writer working, so it is allowed here — a traceback or a mangled file is not.
    # Asserting `errors == []` made this test fail about one run in twelve on ordering alone.
    for error in errors:
        assert "names phase None" in error, f"a refusal is fine; this is not: {error}"
    state = json.loads((tmp_path / "process" / "process-state.json").read_text())
    assert state["active_phase"] == "-1"
    landed = {step["id"] for step in state["plan"]}
    assert landed <= {"a", "b"} and len(landed) == 2 - len(errors)
    assert all(step.get("phase") == "-1" for step in state["plan"]), "no phaseless step written"
