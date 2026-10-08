"""`core.process_writer` — TCC driving the skill's own journal writer.

The writer itself is the skill's (`rew_tool/state/process.py`); what is tested here is the part
TCC owns: getting one call at a time to it.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from autosound_tcc.core import method_binding, method_cli, process_writer, project_lock, vendor_loader

from tests import _intake
from tests._method_copies import copy_of_the_method, entry as _entry
from tests._method_copies import linked_and_approved as _linked_and_approved


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

    Built the same way `test_process_view` builds one — through the skill's own writers
    (`_intake.planned_project`) — because what is under test here is the CLI call, and a fixture
    that fakes the project would fake the refusal too.
    """
    if not process_writer.is_available():
        pytest.skip("skill submodule not checked out")
    return _intake.planned_project(
        tmp_path,
        ("2.3", "target-match"),
        ("2.4", "target-match, second try"),
        ("2.5", "a step nobody got to"),
    )


def test_a_write_off_the_gui_thread_waits_lock_wait_s_not_the_gui_s(project, monkeypatch):
    """#171: the GUI thread gives up after `GUI_LOCK_WAIT_S`, so the window never freezes behind a
    `capture-check`; any other thread — an MCP call, a QThread worker — waits `LOCK_WAIT_S`. Both
    are read when the call runs, which is what lets this test move them: had the worker taken the
    GUI's 30 s, it would have outwaited the holder and written."""
    monkeypatch.setattr(method_cli, "GUI_LOCK_WAIT_S", 30.0)
    monkeypatch.setattr(method_cli, "LOCK_WAIT_S", 0.3)
    held, release = threading.Event(), threading.Event()

    def holder():
        with project_lock.hold(project, timeout_s=5):
            held.set()
            release.wait(5)

    threading.Thread(target=holder, daemon=True).start()
    assert held.wait(5)
    answered: list[Exception] = []

    def write():
        try:
            process_writer.enter_phase(project, "1")
        except process_writer.ProcessWriterError as exc:
            answered.append(exc)

    started = time.monotonic()
    worker = threading.Thread(target=write)
    worker.start()
    worker.join(10)
    release.set()

    assert time.monotonic() - started < 2.0
    assert [type(exc) for exc in answered] == [process_writer.Busy], answered


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


def test_a_crashed_stop_is_a_failure_and_not_a_report_of_open_work(tmp_path, monkeypatch):
    """#169 review I1: `session-close` exits 1 over open work with its report on stdout — that is
    its answer. Python exits 1 for an exception nothing caught as well, and the traceback went to
    the model as «what is still open» (`recorded: false` with a report is the normal answer, the
    MCP tool tells it), sending it after open work that does not exist — the 3.0.8 failure
    `_refuse_if_too_old` was written against. A crash is raised now, in its own last line, even
    when the report had begun on stdout before it."""
    crashing = copy_of_the_method(tmp_path / "method", changes={
        "rew_tool/state/process.py":
            lambda _text: "print('nothing open in the process record')\nraise KeyError('closed_at')\n"})
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(crashing))
    car = tmp_path / "car"
    car.mkdir()

    with pytest.raises(process_writer.ProcessWriterError) as failed:
        process_writer.close_session(car)

    said = str(failed.value)
    assert "KeyError: 'closed_at'" in said and "Traceback" not in said, said


def test_a_stop_the_method_refuses_is_raised_in_its_words_not_reported_as_open_work(
        tmp_path, monkeypatch):
    """The method's own refusal — `error: …`, exit 1, nothing on stdout — is no report of open work
    either: it is raised with the method's sentence, as `_run` raises every other refusal."""
    monkeypatch.setattr(process_writer, "_spawn",
                        lambda project_dir, args, timeout_s=None, **_kw:
                        (1, "", "error: process-state.json is not a process record"))

    with pytest.raises(process_writer.ProcessWriterError) as failed:
        process_writer.close_session(tmp_path)

    assert str(failed.value) == "error: process-state.json is not a process record"


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
    (lambda p: process_writer.supersede_capture(p, "a", "b"), "capture-supersede", "3.0.60"),
    (lambda p: process_writer.handoff_json(p), "handoff", "3.0.60"),
])
def test_every_command_on_a_method_too_old_for_it_says_so(project, monkeypatch, call, command, since):
    """tcc#26 covered `session-close` only, and every other command could meet the same old method
    and hand the model the same usage dump. Each one now names itself and the method version that
    has it — the two whose exit code is an answer too (Task 2 M4): without it a rename's status
    line would carry the usage dump as its reason, tcc#26 again."""
    def _usage(project_dir, args, timeout_s=None, **_kw):  # `handoff_json` passes `lock=False`
        return 2, "usage: process.py <process-dir> <command> [args]\n  show\n  plan [phase]", ""

    monkeypatch.setattr(process_writer, "_spawn", _usage)

    with pytest.raises(process_writer.ProcessWriterError) as stopped:
        call(project)

    said = str(stopped.value)
    assert f"`{command}`" in said and f"v{since}" in said, said
    assert "usage: process.py" not in said, "the dump itself is what misled the model"


def test_a_bound_copy_too_old_for_a_command_is_told_to_update_that_copy(tmp_path, monkeypatch):
    """M28: «Update the method (TCC's own update row offers it)» is the remedy for TCC's own copy.
    For a copy approved on this machine that row updates nothing of it: the sentence names the
    copy the project runs, and its two remedies."""
    other = copy_of_the_method(tmp_path / "other")
    car = tmp_path / "car"
    _linked_and_approved(car, other)

    def _usage(project_dir, args, timeout_s=None, **_kw):
        return 2, "usage: process.py <process-dir> <command> [args]\n  show\n  plan [phase]", ""

    monkeypatch.setattr(process_writer, "_spawn", _usage)

    with pytest.raises(process_writer.TooOld) as stopped:
        process_writer.enter_phase(car, "0")

    said = str(stopped.value)
    assert "`enter-phase`" in said and "v2.8.0" in said, said
    assert str(other) in said and str(_entry(car)) in said and "re-link" in said, said
    assert "update row offers it" not in said, said


def test_every_command_tcc_sends_has_the_method_version_that_has_it():
    """A command added to `process_writer` without its version would answer an old method with the
    usage dump again. The versions are the first method tags whose `process.py` carries the command,
    read from the skill's history on 2026-09-14 — a guess here would be worse than no version.

    `capture-supersede` and `handoff` were started past this module by launchers of their own,
    where this scan could not see them (#169, N1); they are sent from here now, so it does."""
    import inspect
    import re

    source = inspect.getsource(process_writer)
    sent = set(re.findall(r'(?:_run\(project_dir, |_spawn\(project_dir, |args = |^\s*)\["([a-z-]+)"',
                          source, re.M))

    assert sent, "the pattern found no commands — it no longer matches how they are written"
    assert {"capture-supersede", "handoff"} <= sent, f"sent from elsewhere: {sorted(sent)}"
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


def test_a_round_can_be_opened_from_the_methods_plan(tmp_path, monkeypatch):
    """SKL-054 (hub #214, tcc#77): every request to measure is a round whose list the METHOD gives
    — `capture-start <N> --plan` — with its optional captures and the method it starts with."""
    from autosound_tcc.core import process_writer

    seen = {}
    monkeypatch.setattr(process_writer, "_run", lambda d, args, **kw: seen.setdefault("args", args))
    process_writer.start_capture(tmp_path, "61", [], plan=True, optional=["Ws_61 (sw)"],
                                 start_method="rta")

    assert seen["args"][:2] == ["capture-start", "61"]
    assert "--plan" in seen["args"]
    assert seen["args"][seen["args"].index("--optional") + 1] == "Ws_61 (sw)"
    assert seen["args"][seen["args"].index("--start") + 1] == "rta"


# ---- which copy a write runs (#169, G5 S1) ------------------------------------------------------
# Every write started TCC's own `process.py`, whatever the project linked at
# `.claude/skills/autosound-tuning` — so a session could advise from one copy while the writers wrote
# with another. A write now runs the copy `method_binding` binds the project to, and is told which.


def _method_copy(root: Path, change) -> Path:
    """A copy of the method of the test's own (`copy_of_the_method`), its `process.py`'s text passed
    through `change`. `vendor/` itself is never touched."""
    return copy_of_the_method(root, changes={"rew_tool/state/process.py": change})


def _second_copy(root: Path, marker: Path) -> Path:
    """`_method_copy` whose `process.py`, run as a CLI, also appends one line to `marker` — the
    `AUTOSOUND_SKILL_ROOT` it was started with."""
    guard = 'if __name__ == "__main__":\n'
    marked = (f"    with open({str(marker)!r}, 'a', encoding='utf-8') as _marker:\n"
              f"        _marker.write(os.environ.get({method_binding.SKILL_ROOT_ENV!r}, '-') + '\\n')\n")

    def mark(text: str) -> str:
        assert text.count(guard) == 1, "the CLI's guard moved: the marker has nowhere to go"
        return text.replace(guard, guard + marked)

    return _method_copy(root, mark)


def test_a_write_runs_the_copy_the_project_is_bound_to(tmp_path, own_copy_is_the_submodule):
    """The issue's first: a project linked to a copy approved on this machine has its writes run by
    THAT copy, and the child is told which one it is — `AUTOSOUND_SKILL_ROOT`, the skill folder,
    which the method reads as «the copy this session runs» (`deployment.py`)."""
    marker = tmp_path / "second-copy-ran.txt"
    second = _second_copy(tmp_path / "second-method", marker)
    project = tmp_path / "car"
    binding = _linked_and_approved(project, second)

    process_writer.enter_phase(project, "-1")

    assert marker.is_file(), "TCC's own copy wrote, not the one the project is bound to"
    assert marker.read_text(encoding="utf-8").splitlines() == [str(binding.skill_dir)]
    state = json.loads((project / "process" / "process-state.json").read_text(encoding="utf-8"))
    assert state["active_phase"] == "-1", "and the bound copy did the write"


@pytest.mark.parametrize("call", [
    pytest.param(lambda p: process_writer.enter_phase(p, "1"), id="a write"),
    pytest.param(lambda p: process_writer.handoff_json(p), id="a read, which takes no lock"),
])
def test_a_refused_binding_answers_refused_with_its_sentence_and_starts_nothing(
        tmp_path, monkeypatch, call):
    """A project whose copy TCC will not run — here a real folder at the entry: a copy inside the
    project travels with it, from a backup or a clone (HUB-050) — is answered with the binding's own
    sentence, before the lock is taken and before any child starts. Retrying cannot help, and the
    sentence says what does."""
    project = tmp_path / "car"
    _entry(project).mkdir(parents=True)
    binding = method_binding.for_project(project)
    assert binding.state == "refused" and binding.reason, binding
    started, locked = [], []
    monkeypatch.setattr(method_cli.child, "run_bounded",
                        lambda argv, **_kw: started.append(argv) or pytest.fail("a child started"))
    monkeypatch.setattr(project_lock, "hold",
                        lambda *a, **_k: locked.append(a) or contextlib.nullcontext())

    with pytest.raises(process_writer.Refused) as refused:
        call(project)

    assert str(refused.value) == binding.reason
    assert (started, locked) == ([], []), "nothing started and no lock taken"
    assert not (project / "process").exists(), "nothing written either"


def test_a_project_with_no_entry_runs_tccs_own_copy_and_says_so(tmp_path, monkeypatch,
                                                                own_copy_is_the_submodule):
    """No entry is `same`: TCC's own copy runs, as before #169 — the copy the bare CLI runs too
    (`script_path`) — and the child is now told which one it is, as a bound copy is."""
    project = tmp_path / "car"
    project.mkdir()
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs["env"]))
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(method_cli.child, "run_bounded", run)

    process_writer.enter_phase(project, "-1")

    [(argv, env)] = seen
    own = vendor_loader.skill_dir()
    assert argv[1] == str(own / "rew_tool" / "state" / "process.py") == str(process_writer.script_path())
    assert env[method_binding.SKILL_ROOT_ENV] == str(own)


def test_the_copy_with_no_project_is_the_one_a_project_with_no_entry_runs(tmp_path, monkeypatch):
    """`script_path` and `is_available` answer for a caller with no project — the race test's bare
    CLI, the import's «is there a method at all». They used to find TCC's copy by a lookup of their
    own, beside the resolver; they ask the binding's answer now, so the two cannot drift apart."""
    elsewhere = tmp_path / "tccs-own"
    monkeypatch.setattr(method_binding, "own_copy", lambda: elsewhere)

    script = elsewhere / "rew_tool" / "state" / "process.py"
    assert method_binding.for_project(tmp_path / "car").script("state/process.py") == script
    assert process_writer.script_path() == script
    assert process_writer.is_available() is False
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    assert process_writer.is_available() is True


# ---- a flag the bound copy does not know (#169, N19) -------------------------------------------
# `process.py` parses its flags by hand and takes one it does not know for data: an older copy reads
# `capture-start 49 … --origin X` as two more expected titles, `skip 2.3 --superseded-by 2.4` as a
# reason. Nothing comes back as usage text, so `_refuse_if_too_old` cannot see it; the flag is
# refused before the copy is started instead.


@pytest.mark.parametrize("rewrite", [
    pytest.param("", id="taken-out"),
    # The text still holds `--origin` as a substring, so a substring test would pass the copy.
    pytest.param("--origin-x", id="only-inside-a-longer-flag"),
])
def test_a_flag_the_bound_copy_does_not_know_is_refused_before_anything_starts(
        tmp_path, monkeypatch, own_copy_is_the_submodule, rewrite):
    """The issue's: a project bound to an approved copy that predates `--origin` — the vendored
    method with every `--origin` in its `process.py` taken out, or rewritten into a longer flag
    (`--origin-x`) — is refused `start_capture(…, origin=…)` with `UnknownFlag` naming the flag,
    before the lock and before any child. Known is a whole word in the copy's text, not a piece of
    one. Started, that copy opens the round with `--origin` and its value as two more titles."""
    older = _method_copy(tmp_path / "older-method", lambda text: text.replace("--origin", rewrite))
    project = tmp_path / "car"
    _linked_and_approved(project, older)
    started, locked = [], []
    monkeypatch.setattr(method_cli.child, "run_bounded",
                        lambda argv, **_kw: started.append(argv) or pytest.fail("a child started"))
    monkeypatch.setattr(project_lock, "hold",
                        lambda *a, **_k: locked.append(a) or contextlib.nullcontext())

    with pytest.raises(process_writer.UnknownFlag) as refused:
        process_writer.start_capture(project, "49", ["m-L p1_49 (sw)"], origin="import")

    assert refused.value.flag == "--origin"
    assert str(refused.value) == ("this project's method does not know --origin; update it, or "
                                  "re-link the project to TCC's copy")
    assert (started, locked) == ([], []), "nothing started and no lock taken"
    assert not (project / "process").exists(), "nothing written either"


#: Every flag TCC sends to `process.py`: the 23 the map lists (W-9, #169 N19), and `--json`.
_FLAGS_TCC_SENDS = {
    "--project",                         # add_step(situational=True)
    "--superseded-by",                   # skip_step
    # record_reviewer, assembled when the call runs: f"--review={review}", f"--mode={mode}"
    "--review", "--mode",
    # set_protective and amend_protective, assembled in `_protective_legs`: f"--{kind}"
    "--hp", "--lp",
    "--source",                          # set_protective, amend_protective: a source not "user"
    "--amend", "--reason",               # amend_protective
    "--pair", "--text", "--route", "--note",  # record_listening_verdict
    "--ledger-version",                  # record_listening_verdict, listening_verdicts
    "--track", "--characteristic",       # listening_verdicts
    # record_decision, assembled when the call runs: f"--invalidates={invalidates}"
    "--invalidates",
    "--plan", "--optional", "--start", "--step", "--origin",  # start_capture
    "--session",                         # check_captures
    # handoff_json: `handoff --json`, sent from here since #169 N1 — the one the map's 23 left out
    "--json",
}


def _every_writer_with_every_option() -> list:
    """`(writer, args, kwargs)` for every function here that runs `process.py`, each optional
    argument given a value other than its default — so whatever flag a writer can send, it sends."""
    legs = {"hp": {"f": 100, "type": "LR", "slope": 24},
            "lp": {"f": 1000, "type": "LR", "slope": 24}}
    pw = process_writer
    return [
        (pw.enter_phase, ("2",), {}),
        (pw.add_step, ("2.9", "a step this car needed"), {"situational": True}),
        (pw.start_step, ("2.9",), {}),
        (pw.finish_step, ("2.9", ["m-L p1_49 (sw)"]), {}),
        (pw.skip_step, ("2.9",), {"reason": "the car left", "superseded_by": "2.10"}),
        (pw.block_step, ("2.9", "no REW on this machine"), {}),
        (pw.record_reviewer, ("gemini", "flash"),
         {"step": "2.9", "review": "critiques/2.9.md", "mode": "clipboard"}),
        (pw.set_protective, ("m-L", legs), {"source": "front_end"}),
        (pw.amend_protective, ("cap-1", "m-L", legs, "filed OFF by mistake"),
         {"source": "default"}),
        (pw.record_listening_verdict, ([("t1", "bass", True)],),
         {"text": "tight", "route": "car", "ledger_version": "v_003", "note": "first pass"}),
        (pw.listening_verdicts, (),
         {"track": "t1", "characteristic": "bass", "ledger_version": "v_003"}),
        (pw.set_target, ("P1", "harman"), {}),
        (pw.record_decision, ("which slope?", "LR24"), {"step": "2.9", "invalidates": "2.3"}),
        (pw.record_session, ("claude", "opus"), {"resumed": True}),
        (pw.close_session, (), {}),
        (pw.supersede_capture, ("m-L p1_49 (sw)", "m-R p1_49 (sw)"), {}),
        (pw.handoff_json, (), {}),
        (pw.start_capture, ("49", ["m-L p1_49 (sw)"]),
         {"step": "2.9", "origin": "passat-b8-2026:49", "plan": True, "optional": ["Ws_49 (sw)"],
          "start_method": "rta"}),
        (pw.capture_knobs, ({"SubRC": "4/4"},), {}),
        (pw.check_captures, (), {"titles": ["m-L p1_49 (sw)"], "session": True}),
        (pw.record_capture, ("m-L p1_49 (sw)",), {}),
        (pw.skip_capture, ("m-R p1_49 (sw)", "the tweeter is out"), {}),
        (pw.close_capture, (), {"reason": "done"}),
        (pw.check, (), {}),
        (pw.plan, (), {"phase": "2"}),
        (pw.state, (), {}),
    ]


def test_every_flag_tcc_sends_is_pinned_and_the_vendored_copy_knows_each(
        tmp_path, monkeypatch, own_copy_is_the_submodule):
    """N19's behaviour pin. Every writer here, called with every optional argument, through the real
    `spawn` — the flag check included — to the vendored copy, and what reached the child read back.
    A scan of this module's source cannot do it: five of the flags are assembled when the call runs.

    The flags sent are exactly `_FLAGS_TCC_SENDS`, and the check refused none: the vendored v3.1.1
    knows every one. A writer added, or a flag, fails here until it is pinned."""
    import inspect
    import re

    project = tmp_path / "car"
    project.mkdir()
    sent = []

    def run(argv, **_kw):
        sent.append(argv)
        return subprocess.CompletedProcess(argv, 0, "{}", "")  # `state` reads JSON back

    monkeypatch.setattr(method_cli.child, "run_bounded", run)
    calls = _every_writer_with_every_option()
    writers = {name for name, fn in vars(process_writer).items()
               if inspect.isfunction(fn) and fn.__module__ == process_writer.__name__
               and not name.startswith("_")
               and next(iter(inspect.signature(fn).parameters), "") == "project_dir"}
    assert sorted(fn.__name__ for fn, _args, _kw in calls) == sorted(writers), "a writer left out"

    for fn, args, kwargs in calls:
        parameters = inspect.signature(fn).parameters
        optional = {name for name, param in parameters.items()
                    if param.default is not inspect.Parameter.empty}
        assert optional <= set(kwargs), f"{fn.__name__}: {sorted(optional - set(kwargs))} not set"
        # Given, and not as its default (M33): an option at its default sends nothing, and the flag
        # it would send can still reach the set below from another writer — `--source` does.
        idle = sorted(name for name in optional if kwargs[name] == parameters[name].default)
        assert not idle, f"{fn.__name__}: {idle} given their defaults"
        fn(project, *args, **kwargs)

    assert len(sent) == len(calls), "every writer reached its child: the check refused none"
    assert {argv[1] for argv in sent} == {str(process_writer.script_path())}, "the vendored copy"
    words = {word.split("=", 1)[0] for argv in sent for word in argv[2:]}
    assert {word for word in words if re.fullmatch(r"--[a-z][a-z0-9-]*", word)} == _FLAGS_TCC_SENDS


def test_a_free_text_value_that_starts_with_dashes_is_a_value_not_a_flag(
        own_copy_is_the_submodule, project):
    """A word is a flag when what comes before any `=` is `--` and a lowercase name. A reason, a
    note or a title that happens to start with `--` is a value — not checked, and the method is
    started and takes it as it was typed."""
    process_writer.skip_step(project, "2.5", reason="-- not needed")

    assert _skips(project)[-1]["reason"] == "-- not needed"
