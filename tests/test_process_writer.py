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

    assert errors == []
    state = json.loads((tmp_path / "process" / "process-state.json").read_text())
    assert state["active_phase"] == "-1"
    assert {step["id"] for step in state["plan"]} >= {"a", "b"}
