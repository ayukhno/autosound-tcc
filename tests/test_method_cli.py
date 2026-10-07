"""`core.method_cli` — the one place a method script is started (#169, #171).

What is tested here is what its callers no longer do for themselves: a child that runs out of time
is cut and said to have timed out — never «busy», which promises that nothing was written — and a
lock wait the caller names is the one spent. The lock itself is `test_project_lock.py`'s, a read
that takes none is `test_handoff.py`'s, a write that takes it is `test_title_fixes.py`'s.
"""

from __future__ import annotations

import shutil
import threading
import time

import pytest

from autosound_tcc.core import method_cli, process_writer, project_lock, vendor_loader


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
    """Every `except process_writer.ProcessWriterError` (or `.Busy`) has to catch what `method_cli`
    raises: one class under two names, not two classes that look alike."""
    assert process_writer.ProcessWriterError is method_cli.ProcessWriterError
    assert process_writer.Busy is method_cli.Busy


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
