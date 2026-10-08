"""`core.method_cli` — the one place a method script is started (#169, #171).

What is tested here is what its callers no longer do for themselves: a child that runs out of time
is cut and said to have timed out — never «busy», which promises that nothing was written — and a
lock wait the caller names is the one spent. The lock itself is `test_project_lock.py`'s, a read
that takes none is `test_handoff.py`'s, a write that takes it is `test_title_fixes.py`'s.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from autosound_tcc.core import (
    app_log, method_binding, method_cli, process_writer, project_lock, vendor_loader,
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
    assert issubclass(method_cli.Refused, method_cli.ProcessWriterError)
    assert not issubclass(method_cli.Refused, method_cli.Busy)


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
    """A flag refusal is a `Refused`, and the log hears it as it hears a refused binding: once, in
    the busy line's form. The flag is named as the copy would have to know it — `--review=<path>`
    is `--review`, cut at the `=`."""
    _without(method_copy, "--review")
    _no_child(monkeypatch)
    car = tmp_path / "car"
    car.mkdir()
    app_log_warnings.clear()

    with pytest.raises(method_cli.Refused) as refused:
        process_writer.record_reviewer(car, "gemini", "flash", review="critiques/2.3.md")

    sentence = ("this project's method does not know --review; update it, or re-link the project "
                "to TCC's copy")
    assert str(refused.value) == sentence
    said = [record.getMessage() for record in app_log_warnings]
    assert said == [f"refused: `reviewer` on {car} was not run: {sentence}"], said


def test_the_bound_process_py_is_read_once_until_it_changes(tmp_path, method_copy, monkeypatch):
    """What a copy's `process.py` knows is read from its text once per path, mtime and size — every
    write asks, and the file is 240 KB — and read again once it changes: an update in place is seen
    on the next call, which is what «update it» promises."""
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
