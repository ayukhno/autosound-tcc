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


def test_a_method_too_old_for_a_command_says_so_instead_of_dumping_usage(project, monkeypatch):
    """Measured on the user's Windows VM, 2026-09-09: TCC ran `session_close`, the installed
    method was **3.0.8**, and `process.py` answered by printing its own usage text. What the model
    saw was `{"recorded": false, "error": "usage: process.py <process-dir> <comm..."}` — from which
    it concluded the stopping ritual was broken and started inventing work to close.

    `session-close` is in the method from v3.0.43 (the first tag whose `process.py` has the command;
    this test said v3.0.47 until 2026-09-14, which was the flag `--superseded-by`, not the command).
    TCC shipping a tool that needs it is fine; TCC failing to say so is not. An old method is a fact
    about the machine, and a fact has to be reported as itself."""
    def _usage(project_dir, args, timeout_s=None):
        return 2, "usage: process.py <process-dir> <command> [args]\n  show\n  plan [phase]", ""

    monkeypatch.setattr(process_writer, "_spawn", _usage)

    with pytest.raises(process_writer.ProcessWriterError) as stopped:
        process_writer.close_session(project)

    said = str(stopped.value)
    assert "session-close" in said
    assert "3.0.43" in said, "the version that has it, so the answer is actionable"


@pytest.mark.parametrize("call, command, since", [
    (lambda p: process_writer.enter_phase(p, "0"), "enter-phase", "2.8.0"),
    (lambda p: process_writer.listening_verdicts(p), "listening-verdicts", "3.0.29"),
    (lambda p: process_writer.start_capture(p, "v_001", ["m-L_0 (sw)"]), "capture-start", "3.0.0"),
])
def test_every_command_on_a_method_too_old_for_it_says_so(project, monkeypatch, call, command, since):
    """tcc#26 covered `session-close` only, and every other command could meet the same old method
    and hand the model the same usage dump. Each one now names itself and the method version that
    has it."""
    def _usage(project_dir, args, timeout_s=None):
        return 2, "usage: process.py <process-dir> <command> [args]\n  show\n  plan [phase]", ""

    monkeypatch.setattr(process_writer, "_spawn", _usage)

    with pytest.raises(process_writer.ProcessWriterError) as stopped:
        call(project)

    said = str(stopped.value)
    assert f"`{command}`" in said and f"v{since}" in said, said
    assert "usage: process.py" not in said, "the dump itself is what misled the model"


def test_every_command_tcc_sends_has_the_method_version_that_has_it():
    """A command added to `process_writer` without its version would answer an old method with the
    usage dump again. The versions are the first method tags whose `process.py` carries the command,
    read from the skill's history on 2026-09-14 — a guess here would be worse than no version."""
    import inspect
    import re

    source = inspect.getsource(process_writer)
    sent = set(re.findall(r'(?:_run\(project_dir, |_spawn\(project_dir, |args = |^\s*)\["([a-z-]+)"',
                          source, re.M))

    assert sent, "the pattern found no commands — it no longer matches how they are written"
    missing = sorted(sent - set(process_writer.LANDED_IN))
    assert not missing, f"commands with no method version: {missing}"


def test_a_round_can_say_which_project_its_measurements_came_from(tmp_path):
    """S-048, method `v3.0.59`: `_N` numbers ONE project's series, and a foreign number is refused
    unless the round records where it came from.

    Not an edge case — the Arbiter, 2026-09-20: *"то не рідкість, а база всіх після першого тюна
    на одному авто"*. A second tune of the same car starts from the first one's measurements, so
    the foreign number is the ordinary path and the window has to be able to say it.

    Two projects both have a `_49` and they mean different DSP states on different days; a foreign
    number joined to this project's flaw map is another build's data wearing this build's label.
    """
    from autosound_tcc.core import process_writer, vendor_loader

    (tmp_path / "project.json").write_text('{"schema_version": 3, "project_rev": 1}',
                                           encoding="utf-8")
    proc = vendor_loader.load_process().Process(str(tmp_path / "process"))
    proc.start_capture("1", ["w-L_1 (sw)"])
    proc.close_capture("done")

    # Without it the gate refuses, and the refusal is the one a person has to read.
    with pytest.raises(process_writer.ProcessWriterError) as refused:
        process_writer.start_capture(tmp_path, "49", ["m-L p1_49 (sw)"])
    assert "--origin" in str(refused.value)

    process_writer.start_capture(tmp_path, "49", ["m-L p1_49 (sw)"],
                                 origin="passat-b8-2026:49")

    round_ = proc.load()["capture"]
    assert round_["origin"] == {"project": "passat-b8-2026", "series": "49"}


def test_a_closed_rounds_protective_record_can_be_corrected_with_a_reason(tmp_path):
    """Skill `#48` / S-036, method `v3.0.59`: the round most likely to need a correction is the one
    somebody has already read, and `set_protective` needs an OPEN round.

    The case is live, not hypothetical: a nine-position series was captured with 100 Hz LR24 on
    the mids and 1 kHz LR24 on the tweeters, and the round recorded `OFF` for all ten channels.
    The measurements themselves show the roll-off. Until now the only way to say so was to open a
    NEW round on the same version and close it with a reason saying nothing was measured in it —
    which makes "capture round" mean two things and misleads the next reader twice.

    The reason is required, and that is the point: a correction with no why is indistinguishable
    from a second opinion.
    """
    from autosound_tcc.core import process_writer, vendor_loader

    (tmp_path / "project.json").write_text('{"schema_version": 3, "project_rev": 1}',
                                           encoding="utf-8")
    proc = vendor_loader.load_process().Process(str(tmp_path / "process"))
    proc.start_capture("1", ["m-L_1 (sw)"])
    proc.set_protective("m-L", "OFF")
    cap_id = proc.load()["capture"]["id"]
    proc.close_capture("done")

    with pytest.raises(process_writer.ProcessWriterError) as no_reason:
        process_writer.amend_protective(tmp_path, cap_id, "m-L", "OFF", "")
    assert "reason" in str(no_reason.value)

    process_writer.amend_protective(
        tmp_path, cap_id, "m-L",
        {"hp": {"f": 100, "type": "LR", "slope": 24}},
        "the sweep shows the roll-off; the round was filed OFF by mistake",
    )

    # Asked by the round's VERSION, which is what `protective_record_for` matches on — the
    # round id is what the amendment carries, the version is how a reader finds the round.
    record = proc.protective_record_for("1")
    assert record["channels"]["m-L"] == {"hp": {"f": 100, "type": "LR", "slope": 24}}
