"""`core.method_cli` — the one place that says which script of the method runs and in what
environment (#169, #171), and where all but two launchers start theirs.

What is tested here is what its callers no longer do for themselves: a child that runs out of time
is cut and said to have timed out — never «busy», which promises that nothing was written — and a
lock wait the caller names is the one spent. The lock itself is `test_project_lock.py`'s, a read
that takes none is `test_handoff.py`'s, a write that takes it is `test_title_fixes.py`'s. And the
five launchers that are not `process.py`'s run the copy the project is bound to, or say why not.
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from autosound_tcc.core import (
    app_log, config, config_writer, contract_check, intake_form, method_binding, method_cli,
    process_writer, profile_writer, project_lock, project_repo, vendor_loader,
)


@pytest.fixture
def method_copy(tmp_path, monkeypatch):
    """A copy of the vendored method that TCC then runs (the env override). A test changes the
    one file it needs in it; the vendored tree is never touched."""
    if not vendor_loader.is_available():
        pytest.skip("skill submodule not checked out")
    copy = tmp_path / "skill"
    shutil.copytree(vendor_loader.skill_dir(), copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(copy))
    return copy


def test_process_writer_raises_and_catches_the_same_classes():
    """Every `except process_writer.ProcessWriterError` (or `.Busy`, `.Refused`) has to catch what
    `method_cli` raises: one class under two names, not two classes that look alike. A refusal of
    the project's copy is a `ProcessWriterError`, so every caller that shows one shows it — and not
    a `Busy`, whose promise is that the same call will work in a moment."""
    assert process_writer.ProcessWriterError is method_cli.ProcessWriterError
    assert process_writer.Busy is method_cli.Busy
    assert process_writer.Refused is method_cli.Refused
    assert process_writer.UnknownFlag is method_cli.UnknownFlag
    assert issubclass(method_cli.Refused, method_cli.ProcessWriterError)
    assert not issubclass(method_cli.Refused, method_cli.Busy)
    assert issubclass(method_cli.UnknownFlag, method_cli.Refused)


def test_a_child_past_its_timeout_is_cut_and_answered_timed_out_not_busy(tmp_path, method_copy):
    """`timeout_s` bounds the child alone. A child cut at its timeout may have written half of
    something, so its answer is a failure that says it timed out — not «busy», whose whole
    promise is that nothing was written and the same call will work in a moment."""
    (method_copy / "rew_tool" / "state" / "process.py").write_text(
        "import time\ntime.sleep(60)\n", encoding="utf-8")
    car = tmp_path / "car"
    car.mkdir()

    started = time.monotonic()
    with pytest.raises(method_cli.ProcessWriterError) as cut:
        method_cli.spawn(car, "state/process.py", [str(car / "process"), "show"], timeout_s=0.5)
    elapsed = time.monotonic() - started

    assert type(cut.value) is method_cli.ProcessWriterError, f"answered busy: {cut.value!r}"
    assert "timed out" in str(cut.value), str(cut.value)
    assert elapsed < 10, f"{elapsed:.1f}s: the child was waited out, not cut at 0.5 s"


def test_the_lock_wait_a_caller_names_is_the_one_spent(tmp_path, monkeypatch):
    """`lock_wait_s` overrides the thread's own wait. Off the GUI thread that wait is
    `LOCK_WAIT_S` — 30 s here — and the caller's 0.2 s is what is spent before `Busy`."""
    if not process_writer.is_available():
        pytest.skip("skill submodule not checked out")
    monkeypatch.setattr(method_cli, "LOCK_WAIT_S", 30.0)
    held, release = threading.Event(), threading.Event()

    def holder():
        with project_lock.hold(tmp_path, timeout_s=5):
            held.set()
            release.wait(10)

    threading.Thread(target=holder, daemon=True).start()
    assert held.wait(5)
    answered: list[Exception] = []

    def call():
        try:
            method_cli.spawn(tmp_path, "state/process.py", [str(tmp_path / "process"), "show"],
                             timeout_s=20, lock_wait_s=0.2)
        except method_cli.ProcessWriterError as exc:
            answered.append(exc)

    started = time.monotonic()
    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(10)
    release.set()

    assert [type(exc) for exc in answered] == [method_cli.Busy], answered
    assert time.monotonic() - started < 2.0


@pytest.fixture
def app_log_warnings():
    """What TCC's own logger was warned about, heard on that logger itself (the idiom of
    `test_mcp_server.py`): after `app_log.setup()` it does not propagate, so caplog on the root
    would hear nothing."""
    records: list[logging.LogRecord] = []

    class _Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    log = app_log.logger()
    handler = _Keep(level=logging.WARNING)
    level = log.level
    log.addHandler(handler)
    if level == logging.NOTSET or level > logging.WARNING:
        log.setLevel(logging.WARNING)
    try:
        yield records
    finally:
        log.removeHandler(handler)
        log.setLevel(level)


def test_a_refused_binding_leaves_one_warning_naming_the_command_and_the_sentence(
        tmp_path, app_log_warnings):
    """A write the project's binding refuses may have nobody left to see it, as a busy one may:
    `close_session` at quit posts to a closing window's strip, and `mcp_server` drops
    `record_reviewer`'s error on purpose. So the log says it — once, in the busy line's form, with
    the command, the project and the binding's sentence."""
    car = tmp_path / "car"
    (car / ".claude" / "skills" / vendor_loader.SKILL_NAME).mkdir(parents=True)
    reason = method_binding.for_project(car).reason
    app_log_warnings.clear()

    with pytest.raises(method_cli.Refused):
        process_writer.close_session(car)

    said = [record.getMessage() for record in app_log_warnings]
    assert len(said) == 1, said
    assert app_log_warnings[0].levelno == logging.WARNING
    assert said[0] == f"refused: `session-close` on {car} was not run: {reason}", said[0]


# ---- a flag the copy does not know (#169, N19) --------------------------------------------------


def _without(copy, flag: str) -> None:
    """Every `flag` taken out of the copy's `process.py`: a copy from before the flag landed."""
    script = copy / "rew_tool" / "state" / "process.py"
    script.write_text(script.read_text(encoding="utf-8").replace(flag, ""), encoding="utf-8")


def _no_child(monkeypatch) -> None:
    monkeypatch.setattr(method_cli.child, "run_bounded",
                        lambda argv, **_kw: pytest.fail(f"a child started: {argv}"))


def _a_child_that_answers(monkeypatch) -> list:
    started: list = []

    def run(argv, **_kw):
        started.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(method_cli.child, "run_bounded", run)
    return started


def test_a_flag_the_copy_does_not_know_leaves_one_warning_and_is_named_without_its_value(
        tmp_path, method_copy, monkeypatch, app_log_warnings):
    """A flag refusal is an `UnknownFlag`, a `Refused`, and the log hears it as it hears a refused
    binding: once, in the busy line's form. The flag is named, and carried, as the copy would have
    to know it — `--review=<path>` is `--review`, cut at the `=`."""
    _without(method_copy, "--review")
    _no_child(monkeypatch)
    car = tmp_path / "car"
    car.mkdir()
    app_log_warnings.clear()

    with pytest.raises(method_cli.UnknownFlag) as refused:
        process_writer.record_reviewer(car, "gemini", "flash", review="critiques/2.3.md")

    sentence = ("this project's method does not know --review; update it, or re-link the project "
                "to TCC's copy")
    assert refused.value.flag == "--review"
    assert str(refused.value) == sentence
    said = [record.getMessage() for record in app_log_warnings]
    assert said == [f"refused: `reviewer` on {car} was not run: {sentence}"], said


def test_the_bound_process_py_is_read_once_until_it_changes(tmp_path, method_copy, monkeypatch):
    """What a copy's `process.py` knows is read from its text once per path, mtime and size — every
    call that sends a flag asks, and the file is 240 KB — and read again once it changes: an update
    in place is seen on the next call, which is what «update it» promises."""
    real_read_text = Path.read_text
    reads = []

    def read_text(self, *args, **kwargs):
        if self.name == "process.py":
            reads.append(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    _a_child_that_answers(monkeypatch)
    car = tmp_path / "car"
    car.mkdir()
    session_check = [str(car / "process"), "capture-check", "--session"]

    for _ in range(3):
        method_cli.spawn(car, "state/process.py", session_check, timeout_s=5)
    assert len(reads) == 1, reads

    _without(method_copy, "--session")
    reads.clear()
    with pytest.raises(method_cli.Refused, match="does not know --session;"):
        method_cli.spawn(car, "state/process.py", session_check, timeout_s=5)
    assert len(reads) == 1, "read again once it changed"


def test_only_process_py_is_held_to_the_flags_in_its_text(tmp_path, method_copy, monkeypatch):
    """The check is `state/process.py`'s, whose parser takes a flag it does not know for data.
    Another of the method's scripts is started with whatever its caller sends — `state.py`, here,
    whose argparse refuses a flag it does not know by itself."""
    started = _a_child_that_answers(monkeypatch)
    car = tmp_path / "car"
    car.mkdir()

    method_cli.spawn(car, "state/state.py", ["save", "--no-such-flag"], timeout_s=5)

    assert len(started) == 1


# ---- the other launchers (#169) -----------------------------------------------------------------
# `profile_writer`, `config_writer`, `project_repo`, `contract_check` and `intake_form` each started a
# script of TCC's own copy with a bare `subprocess.run` or `Popen`, whatever the project linked. They
# run the copy the project is bound to now: the first three through `spawn`, and the two whose child
# a bounded run cannot be — a check a caller cancels, a server — through `resolve`, its resolver.


def _entry(project: Path) -> Path:
    return project / ".claude" / "skills" / vendor_loader.SKILL_NAME


@pytest.fixture(scope="session")
def second_copy(tmp_path_factory) -> Path:
    """A second copy of the method: the vendored tree copied to `<tmp>/skills/autosound-tuning`, the
    layout of its own repository. One per session — it is 8 MB — while each test links it and
    approves it on its own settings store. `vendor/` itself is never touched."""
    if not vendor_loader._looks_like_the_skill(vendor_loader._SUBMODULE_DIR):
        pytest.skip("skill submodule not checked out")
    skill = tmp_path_factory.mktemp("second-method") / "skills" / vendor_loader.SKILL_NAME
    shutil.copytree(vendor_loader._SUBMODULE_DIR, skill,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return skill


def _linked_and_approved(project: Path, skill: Path) -> method_binding.Binding:
    """`project`'s entry linked to `skill`, and the link approved on this machine: the real
    `method_binding.approve`, on the settings store each test is given its own of — as
    `test_process_writer.py`'s second copy is."""
    _entry(project).parent.mkdir(parents=True)
    _entry(project).symlink_to(skill, target_is_directory=True)
    binding = method_binding.approve(method_binding.for_project(project))
    assert binding.state == method_binding.APPROVED, binding.reason
    return binding


class _Answered:
    """A child that has already answered `out` and exited 0: what `_Launches` hands back instead of
    starting one."""

    cancelled = False
    returncode = 0

    def __init__(self, out: str = "") -> None:
        self.stdout, self.stderr = io.StringIO(out), io.StringIO("")

    def poll(self) -> int:
        return self.returncode

    def communicate(self, input=None, timeout=None) -> tuple[str, str]:
        return self.stdout.read(), self.stderr.read()

    def wait(self, timeout=None) -> int:
        return self.returncode

    def kill(self) -> None:
        pass

    terminate = kill


class _Launches:
    """Every child the five launchers start, as `(argv, env)`, and none of them run. Every door is
    watched: `method_cli`'s bounded run, `contract_check`'s cancellable `Popen`, the bare
    `subprocess.run` each of them used before #169 — so a launcher still on it is caught, not run —
    and `popen`, which `intake_form` is handed."""

    def __init__(self, monkeypatch) -> None:
        self.started: list = []
        launches = self

        def run(argv, **kwargs):
            launches.started.append((list(argv), kwargs.get("env")))
            return subprocess.CompletedProcess(argv, 0, "{}", "")

        class _Check(_Answered):
            def __init__(self, argv, **kwargs):
                launches.started.append((list(argv), kwargs.get("env")))
                super().__init__('{"ok": true, "files": []}')

        monkeypatch.setattr(method_cli.child, "run_bounded", run)
        monkeypatch.setattr(subprocess, "run", run)
        monkeypatch.setattr(contract_check, "_Cancellable", _Check)

    def popen(self, argv, **kwargs) -> _Answered:
        """`intake_form`'s: a form that prints its address at once."""
        self.started.append((list(argv), kwargs.get("env")))
        return _Answered(f"{intake_form.URL_PREFIX}http://127.0.0.1:1/\n")


# Each launcher on a project, by its own way of answering: None when it went through, else the
# sentence it answered with — raised, or carried in its result.


def _profile_writer(project: Path, launches: _Launches):
    try:
        profile_writer.draft(project)
    except profile_writer.ProfileWriterError as exc:
        return str(exc)
    return None


def _config_writer(project: Path, launches: _Launches):
    # The save dialog's own call: the current project's ledger, and no project named (R-h).
    result = config_writer.save(config.state_root(), "v_001", "SQ-1")
    return None if result.saved else result.said


def _project_repo(project: Path, launches: _Launches):
    result = project_repo.init(project)
    return None if result.ok else result.said


def _contract_check(project: Path, launches: _Launches):
    return contract_check.run(project, skip_rew=True).error or None


def _intake_form(project: Path, launches: _Launches):
    form = intake_form.IntakeForm(project, "uk", popen=launches.popen)
    try:
        form.open_url()
    except intake_form.IntakeFormError as exc:
        return exc.detail
    finally:
        form.stop()
    return None


#: `(launcher, its script under rew_tool/, what the refused line calls the run)`.
LAUNCHERS = [
    pytest.param(_profile_writer, "dsp_profile.py", "draft", id="profile_writer"),
    pytest.param(_config_writer, "state/state.py", "config", id="config_writer"),
    pytest.param(_project_repo, "project_repo.py", "init", id="project_repo"),
    pytest.param(_contract_check, "contract.py", "check", id="contract_check"),
    pytest.param(_intake_form, "intake_form.py", "serve", id="intake_form"),
]


@pytest.mark.parametrize("launch, script, named", LAUNCHERS)
def test_every_other_launcher_runs_the_copy_the_project_is_bound_to(
        monkeypatch, second_copy, launch, script, named):
    """The issue's first, for the five that are not `process.py`: the current project linked to a
    copy approved on this machine has the script of THAT copy started, and the child is told which
    copy it runs (`AUTOSOUND_SKILL_ROOT`) — not TCC's own, whatever the project linked."""
    monkeypatch.delenv(vendor_loader.SKILL_DIR_ENV, raising=False)
    monkeypatch.delenv(method_binding.SKILL_ROOT_ENV, raising=False)
    launches = _Launches(monkeypatch)
    project = config.project_dir()
    binding = _linked_and_approved(project, second_copy)

    assert launch(project, launches) is None

    [(argv, env)] = launches.started
    assert argv[1] == str(binding.script(script)), "TCC's own copy ran, not the project's"
    assert env[method_binding.SKILL_ROOT_ENV] == str(binding.skill_dir)


@pytest.mark.parametrize("launch, script, named", LAUNCHERS)
def test_every_other_launcher_answers_a_refused_binding_with_its_sentence_and_starts_nothing(
        monkeypatch, app_log_warnings, launch, script, named):
    """A project whose copy TCC will not run — a real folder at the entry: a copy inside the project
    travels with it (HUB-050) — is answered by each launcher in its own kind of answer, with the
    binding's sentence verbatim, and nothing is started. The log hears it once, in `spawn`'s own
    line: the two launchers with a `Popen` of their own ask the resolver `spawn` asks."""
    monkeypatch.delenv("AUTOSOUND_STATE_ROOT", raising=False)
    launches = _Launches(monkeypatch)
    project = config.project_dir()
    _entry(project).mkdir(parents=True)
    reason = method_binding.for_project(project).reason
    assert reason
    app_log_warnings.clear()

    assert launch(project, launches) == reason

    assert launches.started == [], "nothing started"
    said = [record.getMessage() for record in app_log_warnings]
    assert said == [f"refused: `{named}` on {project} was not run: {reason}"], said


def test_spawn_runs_what_resolve_answers(tmp_path, monkeypatch):
    """`spawn` takes its script and its environment from `resolve` — the resolver `contract_check`
    and `intake_form` ask for theirs — so a launcher that keeps a `Popen` of its own cannot run
    another copy than `spawn` would (#169)."""
    script = tmp_path / "copy" / "rew_tool" / "contract.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    asked, started = [], []

    def resolve(project_dir, script_rel, args=()):
        asked.append((Path(project_dir), script_rel, list(args)))
        return script, {"FROM": "resolve"}

    def run(argv, **kwargs):
        started.append((argv[1:], kwargs["env"]))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(method_cli, "resolve", resolve)
    monkeypatch.setattr(method_cli.child, "run_bounded", run)
    car = tmp_path / "car"

    method_cli.spawn(car, "contract.py", ["check", car], timeout_s=5, lock=False)

    assert asked == [(car, "contract.py", ["check", str(car)])]
    assert started == [([str(script), "check", str(car)], {"FROM": "resolve"})]
