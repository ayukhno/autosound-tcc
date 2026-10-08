"""`core.method_cli` — the one place that says which script of the method's `rew_tool/` runs and in
what environment (#169, #171), and where all but two of its launchers start theirs.

What is tested here is what its callers no longer do for themselves: a child that runs out of time
is cut and said to have timed out — never «busy», which promises that nothing was written — and a
lock wait the caller names is the one spent. The lock itself is `test_project_lock.py`'s, a read
that takes none is `test_handoff.py`'s, a write that takes it is `test_title_fixes.py`'s. And the
six launchers that are not `process.py`'s run the copy the project is bound to, or say why not.
"""

from __future__ import annotations

import ast
import errno
import io
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from autosound_tcc.core import (
    car_library, config, config_writer, contract_check, intake_form, method_binding, method_cli,
    process_writer, profile_writer, project_lock, project_repo, vendor_loader,
)

from tests._method_copies import copy_of_the_method, entry as _entry
from tests._method_copies import linked_and_approved as _linked_and_approved


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


def _flock_cannot_lock(monkeypatch) -> None:
    """A filesystem whose flock answers ENOLCK — a network share — for every exclusive lock."""
    real = project_lock.fcntl.flock

    def flock(fd, op):
        if op & project_lock.fcntl.LOCK_EX:
            raise OSError(errno.ENOLCK, "No locks available")
        return real(fd, op)

    monkeypatch.setattr(project_lock.fcntl, "flock", flock)


_STDERR = "\n".join(f"reading capture {n}" for n in range(1, 13))


@pytest.mark.parametrize("fails", ["timed out", "could not start", "could not lock"])
def test_a_timeout_or_a_run_that_could_not_start_leaves_one_warning_in_the_busy_lines_form(
        tmp_path, monkeypatch, app_log_warnings, fails):
    """#169 review I6: a busy or refused answer leaves its line in the log, because the caller may
    have nobody left to tell — `close_session` at quit, `record_reviewer` dropped by the MCP tool.
    A timeout left nothing, though a child cut halfway may have written, and what it had said on
    stderr went with it; so did an OSError — an interpreter that would not start, a filesystem
    whose flock answers ENOLCK. Each leaves one line now, in the busy line's form: the command and
    the project, the timeout's with the tail of what the child had printed, the lock's with the
    lock file."""
    if not process_writer.is_available():
        pytest.skip("skill submodule not checked out")
    if fails == "could not lock" and project_lock.fcntl is None:
        pytest.skip("POSIX flock")
    car = tmp_path / "car"
    car.mkdir()
    if fails == "timed out":
        def run(argv, **kw):
            raise subprocess.TimeoutExpired(argv, kw["timeout"], output="", stderr=_STDERR)
        monkeypatch.setattr(method_cli.child, "run_bounded", run)
    elif fails == "could not start":
        def run(argv, **_kw):
            raise OSError(errno.ENOEXEC, "Exec format error")
        monkeypatch.setattr(method_cli.child, "run_bounded", run)
    else:
        _flock_cannot_lock(monkeypatch)
        _no_child(monkeypatch)
    app_log_warnings.clear()

    with pytest.raises(method_cli.ProcessWriterError) as failed:
        method_cli.spawn(car, "state/process.py", [str(car / "process"), "show"], timeout_s=0.5)

    assert type(failed.value) is method_cli.ProcessWriterError, repr(failed.value)
    said = [record.getMessage() for record in app_log_warnings]
    assert len(said) == 1 and app_log_warnings[0].levelno == logging.WARNING, said
    tail = "\n".join(_STDERR.splitlines()[-8:])
    assert said[0] == {
        "timed out": f"timed out: `show` on {car} after 0.5s: {tail}",
        "could not start": f"failed: `show` on {car} was not run: [Errno {errno.ENOEXEC}] Exec "
                           f"format error",
        "could not lock": f"failed: `show` on {car} was not run (taking the lock "
                          f"{project_lock.lock_file(car)}): [Errno {errno.ENOLCK}] No locks "
                          f"available",
    }[fails], said[0]


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
# `car_library` wrote `project.json` in-process with TCC's own `Project`; it runs the bound copy's
# `intake.py set-car` through `spawn` now (N9).


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
    """Every child the six launchers start, as `(argv, env)`, and none of them run. Every door is
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


def _car_library(project: Path, launches: _Launches):
    try:
        car_library.record(project, "VW", "Passat", "B8", "sedan")
    except car_library.CarLibraryError as exc:
        return str(exc)
    return None


#: `(launcher, its script under rew_tool/, what the refused line calls the run)`.
LAUNCHERS = [
    pytest.param(_profile_writer, "dsp_profile.py", "draft", id="profile_writer"),
    pytest.param(_config_writer, "state/state.py", "config", id="config_writer"),
    pytest.param(_project_repo, "project_repo.py", "init", id="project_repo"),
    pytest.param(_contract_check, "contract.py", "check", id="contract_check"),
    pytest.param(_intake_form, "intake_form.py", "serve", id="intake_form"),
    pytest.param(_car_library, "intake.py", "set-car", id="car_library"),
]


@pytest.mark.parametrize("launch, script, named", LAUNCHERS)
def test_every_other_launcher_runs_the_copy_the_project_is_bound_to(
        monkeypatch, own_copy_is_the_submodule, other_copy, launch, script, named):
    """The issue's first, for the six that are not `process.py`: the current project linked to a
    copy approved on this machine has the script of THAT copy started, and the child is told which
    copy it runs (`AUTOSOUND_SKILL_ROOT`) — not TCC's own, whatever the project linked."""
    launches = _Launches(monkeypatch)
    project = config.project_dir()
    binding = _linked_and_approved(project, other_copy)

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


# ---- the one door, as a rule (#169) -------------------------------------------------------------
# The launchers above are pinned one by one, and `LAUNCHERS` knows only today's six. A seventh — a new
# writer, or a revert of one of these — that put TCC's own script in an argv would write with TCC's
# copy while the session runs the project's: the split #169 closed. So the rule is read off the
# source, the way `test_model_choices.py` reads where a model id may be written.

_SRC = Path(__file__).resolve().parents[1] / "src"

#: The one door. The scan reads it for what its functions answer and start, and reports none of
#: its own starts: starting the method's scripts is what it is for.
_THE_DOOR = "autosound_tcc/core/method_cli.py"

#: Every module that starts a script of the method's `rew_tool/` with a `Popen` of its own, and why
#: it may. Both take the script and its environment from `method_cli.resolve` — what `spawn` runs,
#: refused and logged the same way — so neither can start another copy than `spawn` would; and
#: neither child can be `spawn`'s bounded run. Only ever shorter: an entry that starts none any
#: more fails the scan until it is taken off.
_OWN_POPEN = {
    "autosound_tcc/core/contract_check.py":
        "its child is handed to a caller that may end it early (`register`), which a bounded run "
        "cannot be",
    "autosound_tcc/core/intake_form.py":
        "the form is a server that runs until the project closes, which a bounded run cannot be",
}

#: What feeds a start: TCC's own copy's `rew_tool/` — `REW_TOOL_DIR`, `rew_tool_dir()`, a
#: `"rew_tool"` joined onto a folder, and so every `script_path()` built from one — or
#: `method_cli.resolve`'s answer, the project's bound copy.
OWN, RESOLVED = "TCC's own copy", "method_cli.resolve"

#: `subprocess`'s own starts, called on the module; and the calls that start a child whatever they
#: are called on: `Popen` itself, `child.run_bounded`, asyncio's, the `popen` a launcher is handed.
_ON_SUBPROCESS = {"run", "Popen", "call", "check_call", "check_output"}
_STARTERS = {"Popen", "run_bounded", "create_subprocess_exec", "create_subprocess_shell", "_popen"}
#: Calls whose answer is still the path, or the command line, they were handed.
_KEEPS_IT = {"str", "fspath", "Path", "PurePath", "PurePosixPath", "PureWindowsPath", "join",
             "abspath", "realpath", "normpath", "expanduser", "list", "tuple"}
#: The same, called on the path itself.
_PATH_METHODS = {"resolve", "absolute", "joinpath", "with_name", "with_suffix", "as_posix",
                 "expanduser"}
#: Read on their own, never as part of the code around them.
_NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_BINDS = (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr, ast.For, ast.AsyncFor,
          ast.comprehension, ast.withitem)
_PARAM = "param:"


def _called(func: ast.AST) -> str:
    """The name a call calls: `f` of `f(…)` and of `a.b.f(…)`."""
    return getattr(func, "id", None) or getattr(func, "attr", "")


def _rew_tool_dir(node: ast.AST) -> bool:
    """TCC's own copy's `rew_tool/` itself: `REW_TOOL_DIR`, or a call of `rew_tool_dir()`."""
    if isinstance(node, ast.Call):
        return _called(node.func) == "rew_tool_dir"
    return isinstance(node, (ast.Name, ast.Attribute)) and _called(node) == "REW_TOOL_DIR"


def _own(scope: ast.AST) -> list:
    """Every node of `scope`'s own code — not of the functions and classes inside it."""
    found, todo = [], list(ast.iter_child_nodes(scope))
    while todo:
        node = todo.pop()
        if not isinstance(node, _NESTED):
            found.append(node)
            todo.extend(ast.iter_child_nodes(node))
    return found


def _grow(kept: set, more) -> bool:
    new = set(more) - kept
    kept |= new
    return bool(new)


def _params(kinds: set) -> set:
    return {kind[len(_PARAM):] for kind in kinds if kind.startswith(_PARAM)}


def _doors(kinds: set) -> set:
    return {kind for kind in kinds if not kind.startswith(_PARAM)}


@dataclass
class _Function:
    """What one function says of a method script: its parameters, what its answer holds (a door,
    or a parameter it hands back), and which parameters reach a start."""

    params: list
    vararg: str = ""
    kwarg: str = ""
    returns: set = field(default_factory=set)
    starts_via: set = field(default_factory=set)


class _Scan:
    """Every start of a child a method script feeds, by module: `starts` is `{module: [(line,
    what)]}`, `what` holding `OWN` and/or `RESOLVED`.

    «Feeds» follows the path as it is built and handed on: joined (`/`, `os.path.join`, an
    f-string), put in a list, made a `str` or a `Path`; held in a local, a module's top-level name
    or a `self.` attribute; answered by a function of the source — such as a `script_path()` — or
    handed to one whose parameter reaches a start. A call it does not know answers nothing, so a
    bool or a report computed from a script's path is not that path. `REW_TOOL_DIR.parent` is the
    skill's folder, and what is under it outside `rew_tool/` — the reviewer's
    `scripts/autosound_ai.py` — is not the method's script. Read to a fixpoint, since a function's
    answer feeds its callers'. The `door` is read like the rest, for what its functions answer and
    start; its own starts are not reported.
    """

    def __init__(self, sources: dict[str, str], door: str = "") -> None:
        self.door = door
        self.trees = {rel: ast.parse(text) for rel, text in sources.items()}
        self.stems: dict[str, list[str]] = {}
        for rel in self.trees:
            self.stems.setdefault(Path(rel).stem, []).append(rel)
        self.packages = {rel.rpartition("/")[0].replace("/", ".") for rel in self.trees}
        self.aliases: dict[str, dict[str, tuple]] = {}
        self.popen_classes: dict[str, set] = {}
        self.functions: dict[str, dict[str, _Function]] = {}
        self.attrs: dict[str, dict[str, set]] = {rel: {} for rel in self.trees}
        #: Each module's scopes — its top level, then every function — with their own code sorted
        #: once: what binds a name, what answers, what calls.
        self.scopes: dict[str, list] = {}
        for rel, tree in self.trees.items():
            aliases, classes, functions, scopes = {}, set(), {}, [(tree, None)]
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    aliases.update(self._aliases(node))
                elif isinstance(node, ast.ClassDef):
                    if any(_called(base) == "Popen" for base in node.bases):
                        classes.add(node.name)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = node.args
                    function = functions.setdefault(node.name, _Function(
                        [arg.arg for arg in args.posonlyargs + args.args],
                        args.vararg.arg if args.vararg else "",
                        args.kwarg.arg if args.kwarg else ""))
                    scopes.append((node, function))
            self.aliases[rel], self.popen_classes[rel], self.functions[rel] = \
                aliases, classes, functions
            self.scopes[rel] = [(scope, function, *self._sorted(scope)) for scope, function in scopes]
        for _ in range(50):
            self.starts: dict[str, list[tuple[int, frozenset]]] = {}
            self.grew = False
            for rel in self.trees:
                self._read_module(rel)
            if not self.grew:
                return
        raise AssertionError("the scan found no fixpoint in 50 passes")

    @staticmethod
    def _sorted(scope: ast.AST) -> tuple[list, list, list]:
        nodes = _own(scope)
        binds = [node for node in nodes if isinstance(node, _BINDS) or (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("append", "extend", "insert"))]
        answers = [node for node in nodes if isinstance(node, ast.Return) and node.value is not None]
        calls = [node for node in nodes if isinstance(node, ast.Call)]
        return binds, answers, calls

    def _aliases(self, node: ast.AST) -> dict[str, tuple]:
        """What one import names: local name → `(module, None)` for a module, `(module, name)` for
        a function."""
        found = {}
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    found[alias.asname] = (alias.name.split(".")[-1], None)
                else:
                    found[alias.name.split(".")[0]] = (alias.name.split(".")[0], None)
        elif node.module:
            # From a package of the source (`from autosound_tcc.core import child`), a module.
            of_a_package = node.module in self.packages
            for alias in node.names:
                module = of_a_package or alias.name in self.stems or alias.name == "subprocess"
                found[alias.asname or alias.name] = (
                    (alias.name, None) if module else (node.module.split(".")[-1], alias.name))
        return found

    def _module_of(self, rel: str, name: str) -> tuple:
        return self.aliases[rel].get(name, (name, None))

    def _callees(self, rel: str, func: ast.AST) -> list[tuple[_Function, int]]:
        """The functions of the source a call may call, each with how many of its parameters the
        call does not pass (`self`)."""
        own = self.functions[rel]
        if isinstance(func, ast.Name):
            if func.id in own:
                return [(own[func.id], 0)]
            module, name = self._module_of(rel, func.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in ("self", "cls"):
                found = own.get(func.attr)
                return [(found, int(found.params[:1] in (["self"], ["cls"])))] if found else []
            module, name = self._module_of(rel, func.value.id)
            if name is not None:
                return []
            name = func.attr
        else:
            return []
        return [(self.functions[other][name], 0) for other in self.stems.get(module, ())
                if name in self.functions[other]]

    def _resolves(self, rel: str, func: ast.AST) -> bool:
        """`method_cli.resolve`, however it was imported."""
        if isinstance(func, ast.Name):
            return self._module_of(rel, func.id) == ("method_cli", "resolve")
        return (isinstance(func, ast.Attribute) and func.attr == "resolve"
                and isinstance(func.value, ast.Name)
                and self._module_of(rel, func.value.id) == ("method_cli", None))

    def _starts(self, rel: str, call: ast.Call) -> bool:
        name = _called(call.func)
        if name in _STARTERS or name in self.popen_classes[rel]:
            return True
        if name not in _ON_SUBPROCESS:
            return False
        if isinstance(call.func, ast.Name):
            return self._module_of(rel, name) == ("subprocess", name)
        owner = getattr(call.func, "value", None)
        return isinstance(owner, ast.Name) and self._module_of(rel, owner.id) == ("subprocess", None)

    def _read_module(self, rel: str) -> None:
        top = None
        for scope, function, binds, answers, calls in self.scopes[rel]:
            held = self._read(rel, scope, function, top or {}, binds, answers, calls)
            if top is None:
                top = held  # what the module's top level holds, every function starts from

    def _read(self, rel, scope, function, seed, binds, answers, calls) -> dict:
        """One function's code (or the module's top level) read to its own fixpoint; what its names
        hold is answered."""
        attrs = self.attrs[rel]
        held = {name: set(kinds) for name, kinds in seed.items()}
        if function is not None:
            args = scope.args
            for arg in args.posonlyargs + args.args + args.kwonlyargs + [
                    arg for arg in (args.vararg, args.kwarg) if arg is not None]:
                if arg.arg not in ("self", "cls"):
                    held[arg.arg] = {_PARAM + arg.arg}

        def passed(call: ast.Call, callee: _Function, skipped: int, names: set) -> set:
            """What `call` hands the parameters `names` of `callee`."""
            found = set()
            if not names:
                return found
            for at, arg in enumerate(call.args, start=skipped):
                if isinstance(arg, ast.Starred):  # `*argv`: any parameter from here on
                    reached, arg = {*callee.params[at:], callee.vararg}, arg.value
                else:
                    reached = {callee.params[at] if at < len(callee.params) else callee.vararg}
                if names & reached:
                    found |= kinds(arg)
            for keyword in call.keywords:
                if keyword.arg is None or keyword.arg in names or (
                        callee.kwarg in names and keyword.arg not in callee.params):
                    found |= kinds(keyword.value)
            return found

        def called(call: ast.Call) -> set:
            func, name = call.func, _called(call.func)
            if self._resolves(rel, func):
                return {RESOLVED}
            found = set()
            for callee, skipped in self._callees(rel, func):
                found |= _doors(callee.returns) | passed(call, callee, skipped,
                                                          _params(callee.returns))
            if name in _KEEPS_IT or (name in _PATH_METHODS and isinstance(func, ast.Attribute)):
                found |= set().union(*map(kinds, call.args))
                if name in _PATH_METHODS:
                    found |= kinds(func.value)
            return found

        def kinds(node: ast.AST) -> set:
            if _rew_tool_dir(node):
                return {OWN}
            if isinstance(node, ast.Constant):
                return {OWN} if node.value == "rew_tool" else set()
            if isinstance(node, ast.Name):
                return set(held.get(node.id, ()))
            if isinstance(node, ast.Attribute):
                if node.attr == "parent" and _rew_tool_dir(node.value):
                    return set()  # the skill's folder: `scripts/` there is not `rew_tool/`
                if isinstance(node.value, ast.Name) and node.value.id == "self":
                    return set(attrs.get(node.attr, ()))
                return kinds(node.value)
            if isinstance(node, ast.Call):
                return called(node)
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
                return kinds(node.elt)
            if isinstance(node, ast.DictComp):
                return kinds(node.value)
            if isinstance(node, (ast.Compare, ast.Lambda)):
                return set()  # a bool, a function: not the path
            return set().union(*(kinds(child) for child in ast.iter_child_nodes(node)
                                 if isinstance(child, ast.expr)))

        def bind(target: ast.AST, found: set) -> bool:
            if not found:
                return False
            if isinstance(target, ast.Name):
                return _grow(held.setdefault(target.id, set()), found)
            if isinstance(target, (ast.Tuple, ast.List)):
                return any([bind(element, found) for element in target.elts])
            if isinstance(target, (ast.Starred, ast.Subscript)):
                return bind(target.value, found)
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                    and target.value.id == "self":
                if _grow(attrs.setdefault(target.attr, set()), _doors(found)):
                    self.grew = True
                    return True
            return False

        def assigned(node: ast.AST) -> bool:
            if isinstance(node, ast.Assign):
                found = kinds(node.value)
                return any([bind(target, found) for target in node.targets])
            if isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                return node.value is not None and bind(node.target, kinds(node.value))
            if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                return bind(node.target, kinds(node.iter))
            if isinstance(node, ast.withitem):
                return node.optional_vars is not None and bind(node.optional_vars,
                                                               kinds(node.context_expr))
            return bind(node.func.value, set().union(*map(kinds, node.args)))  # `argv.append(…)`

        while any([assigned(node) for node in binds]):
            pass
        if function is not None:
            for node in answers:
                if _grow(function.returns, kinds(node.value)):
                    self.grew = True
        for node in calls:
            if self._starts(rel, node):
                found = set().union(*map(kinds, node.args),
                                    *(kinds(keyword.value) for keyword in node.keywords))
            else:  # handed to a function of the source whose parameter reaches a start
                found = set()
                for callee, skipped in self._callees(rel, node.func):
                    found |= passed(node, callee, skipped, callee.starts_via)
            if _doors(found) and rel != self.door:
                self.starts.setdefault(rel, []).append((node.lineno, frozenset(_doors(found))))
            if function is not None and _grow(function.starts_via, _params(found)):
                self.grew = True
        return held


def _method_script_starts(sources: dict[str, str], door: str = "") -> dict[str, list]:
    return _Scan(sources, door).starts


def test_no_module_but_method_cli_starts_a_script_of_the_methods_rew_tool():
    """#169's one door, as a rule rather than six cases: outside `core/method_cli.py`, nothing
    starts a script of TCC's own copy's `rew_tool/` — that copy is not the one the project may be
    bound to — and only the two launchers on `_OWN_POPEN` start `method_cli.resolve`'s answer with a
    `Popen` of their own. Read off the source with `ast`, so a revert or a new writer fails here
    before any test of its own exists. Outside `rew_tool/`, the reviewer's `autosound_ai.py`
    (`critic`, `reviewer_key`) and an update's `upkeep.py` (`updates`) are TCC's own by design, and
    no business of this scan."""
    sources = {path.relative_to(_SRC).as_posix(): path.read_text(encoding="utf-8")
               for path in sorted(_SRC.rglob("*.py"))}
    assert _THE_DOOR in sources, "the door moved: this scan reads past it"

    starts = _method_script_starts(sources, _THE_DOOR)

    own = [f"{rel}:{line}" for rel, found in sorted(starts.items())
           for line, what in found if OWN in what]
    assert own == [], f"TCC's own copy is started past `method_cli.spawn`: {own}"
    resolved = {rel for rel, found in starts.items() for _line, what in found if RESOLVED in what}
    assert sorted(resolved - set(_OWN_POPEN)) == [], \
        "a Popen of its own on `method_cli.resolve`'s answer: run it through `method_cli.spawn`, " \
        "or say on `_OWN_POPEN` why it cannot be a bounded run"
    assert sorted(set(_OWN_POPEN) - resolved) == [], \
        "on `_OWN_POPEN` and starting no script any more: take it off the list"


_A_WRITER = ("import subprocess, sys\n"
             "from autosound_tcc.core import child, vendor_loader\n"
             "_STATE = vendor_loader.rew_tool_dir() / 'state' / 'state.py'\n"
             "def script_path():\n"
             "    return vendor_loader.REW_TOOL_DIR / 'dsp_profile.py'\n")


@pytest.mark.parametrize("body", [
    pytest.param("def save():\n"
                 "    subprocess.run([sys.executable, str(script_path()), 'save'])\n",
                 id="in the argv"),
    pytest.param("def save():\n"
                 "    argv = [sys.executable]\n"
                 "    argv.append(str(script_path()))\n"
                 "    return child.run_bounded(argv, timeout=5)\n",
                 id="through a local"),
    pytest.param("def save():\n"
                 "    subprocess.Popen([sys.executable, str(_STATE), 'save'])\n",
                 id="a module's name for it"),
    pytest.param("def _go(script, *args):\n"
                 "    return subprocess.run([sys.executable, str(script), *args])\n"
                 "def save():\n"
                 "    return _go(script_path(), 'save')\n",
                 id="handed to a helper that starts it"),
    pytest.param("class Form:\n"
                 "    def __init__(self):\n"
                 "        self._script = script_path()\n"
                 "    def open(self):\n"
                 "        self._popen([sys.executable, str(self._script)])\n",
                 id="kept on self"),
])
def test_the_scan_goes_red_on_tccs_own_script_started_past_the_door(body):
    """The scan is only worth something if it fails, so it is shown failing: on each way an argv
    can carry TCC's own script to a start."""
    starts = _method_script_starts({"autosound_tcc/core/writer.py": _A_WRITER + body})

    assert [OWN in what for _line, what in starts.get("autosound_tcc/core/writer.py", [])] == [True]


def test_the_scan_leaves_the_reviewers_script_and_a_resolved_one_apart():
    """`scripts/autosound_ai.py` sits under the skill's folder, above `rew_tool/`: not the method's
    script. `method_cli.resolve`'s answer is said as such, for `_OWN_POPEN` to judge."""
    source = ("import subprocess, sys\n"
              "from autosound_tcc.core import method_cli, vendor_loader\n"
              "def script_path():\n"
              "    return vendor_loader.REW_TOOL_DIR.parent / 'scripts' / 'autosound_ai.py'\n"
              "def doctor():\n"
              "    subprocess.run([sys.executable, str(script_path()), 'doctor'])\n"
              "def check(project):\n"
              "    script, env = method_cli.resolve(project, 'contract.py')\n"
              "    subprocess.Popen([sys.executable, str(script)], env=env)\n")

    starts = _method_script_starts({"autosound_tcc/core/reviewer.py": source})

    assert starts == {"autosound_tcc/core/reviewer.py": [(9, frozenset({RESOLVED}))]}


# ---- the fix-it words, for the copy the project runs (M28) --------------------------------------


def test_a_script_missing_from_a_bound_copy_names_that_copy_and_its_remedy(tmp_path):
    """M28: `ScriptMissing` said «Run: git submodule update --init --recursive» — TCC's own checkout's
    remedy — for whichever copy the project runs. For a copy approved on this machine, a submodule
    update in TCC's tree mends nothing: the sentence names that copy, and its remedies."""
    other = copy_of_the_method(tmp_path / "other")
    (other / "rew_tool" / "state" / "process.py").unlink()  # a copy with files missing
    car = tmp_path / "car"
    _linked_and_approved(car, other)

    with pytest.raises(method_cli.ScriptMissing) as missing:
        process_writer.enter_phase(car, "-1")

    said = str(missing.value)
    assert str(other) in said and "re-link" in said and str(_entry(car)) in said, said
    assert "submodule" not in said, said

