"""`core.process_writer` — TCC driving the skill's own journal writer.

The writer itself is the skill's (`rew_tool/state/process.py`); what is tested here is the part
TCC owns: getting one call at a time to it.
"""

from __future__ import annotations

import json

import pytest

from autosound_tcc.core import process_writer, vendor_loader

from tests import _intake


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


@pytest.fixture
def project(tmp_path):
    """A project that passes the phase −1 gate, with a plan to skip steps out of.

    Built the same way `test_process_view` builds one — through the skill's own writers — because
    what is under test here is the CLI call, and a fixture that fakes the project would fake the
    refusal too.
    """
    if not process_writer.is_available():
        pytest.skip("skill submodule not checked out")
    snapshot = tmp_path / "state" / "FULL" / "v_003.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("{}", encoding="utf-8")
    module = vendor_loader.load_process()
    _intake.seed(tmp_path)
    process = module.Process(str(tmp_path / "process"))
    _intake.open_phases(process)
    process.set_target("FULL", "EPY")
    process.enter_phase("2")
    process.add_step("2.3", "target-match")
    process.add_step("2.4", "target-match, second try")
    process.add_step("2.5", "a step nobody got to")
    return tmp_path


def _skips(project_dir) -> list[dict]:
    lines = (project_dir / "process" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    return [e for e in (json.loads(line) for line in lines) if e.get("type") == "step_skipped"]


def test_a_superseding_step_lands_as_superseded_by_not_as_the_reason(project):
    """The id went to the CLI positionally, and v3.0.47 reads position 2 onward as a sentence.

    Measured on the pin bump: `skip 2.3 2.4` wrote `{"reason": "2.4"}` and no `superseded_by` at
    all — the link "replaced by step 2.4" silently became a reason whose text happens to be "2.4".
    Green tests missed it because every other test drives `Process` in-process, where the keyword
    still arrives as a keyword; this is the only path the app actually uses.
    """
    process_writer.skip_step(project, "2.3", superseded_by="2.4")

    event = _skips(project)[-1]
    assert event["superseded_by"] == "2.4"
    assert not event.get("reason"), "the id is a link, not a sentence"


def test_a_skip_can_carry_a_sentence_instead_of_a_superseding_step(project):
    process_writer.skip_step(project, "2.4", reason="the car left before we got to it")

    event = _skips(project)[-1]
    assert event["reason"] == "the car left before we got to it"
    assert not event.get("superseded_by")


def test_a_skip_with_neither_is_refused_here_rather_than_by_a_subprocess(project, monkeypatch):
    """Same shape as `finish_step` with no evidence: the skill refuses it, so TCC does not spend a
    subprocess learning that. The subprocess is stubbed to blow up, which is what makes this a test
    of TCC's refusal rather than of the skill's — the two are worth telling apart, because only one
    of them still holds if the pin moves back."""
    monkeypatch.setattr(
        process_writer, "_run", lambda *a, **k: pytest.fail("process.py was spawned anyway")
    )

    with pytest.raises(process_writer.ProcessWriterError):
        process_writer.skip_step(project, "2.5")

    assert _skips(project) == []


def _events(project_dir, kind: str) -> list[dict]:
    lines = (project_dir / "process" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    return [e for e in (json.loads(line) for line in lines) if e.get("type") == kind]


def test_a_clean_stop_is_written_down_as_an_event(project):
    """SKL-029, third ask: an orderly stop used to leave NO trace, so it read exactly like a killed
    process. The skill writes `session_closed` on a clean `session-close`; what TCC owns is calling
    it. The break this catches: a quit path that shuts the window without the call."""
    recorded, report = process_writer.close_session(project)

    assert recorded is True, report
    assert len(_events(project, "session_closed")) == 1


def test_a_stop_over_open_work_reports_instead_of_recording(project):
    """`session-close` exits 1 while anything is open — deliberately, so "we stopped" cannot be
    said over a step still in progress. TCC must read that as a REPORT, not as a failed command:
    treating exit 1 as an error is how the report ends up in an exception nobody shows."""
    process_writer.start_step(project, "2.3")

    recorded, report = process_writer.close_session(project)

    assert recorded is False
    assert "2.3" in report, report
    assert _events(project, "session_closed") == []
