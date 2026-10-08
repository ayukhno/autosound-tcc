"""`core.project_lock` — one write per project at a time, under ONE deadline (#171, G8 phase 0).

The writer lock used to wait without bound: `_THREAD_LOCK.acquire()` had no timeout, so a write
queued behind a 120 s `capture-check` — or `close_session` at quit, behind a queue of them — waited
for all of it, and the flock's only deadline was the child's own `timeout_s`. What is tested here:
one deadline over the thread lock and the flock, nothing left held past it, and a write that cannot
get the lock in time answering «busy» instead of waiting — with nothing written.
"""

from __future__ import annotations

import errno
import logging
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from autosound_tcc.core import method_cli, process_writer, project_lock

from tests import _intake

#: Windows has no flock in phase 0: the thread lock is all `hold` takes there, so a holder in
#: another process is a POSIX-only scene.
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="no flock on Windows in phase 0")

#: Another process holding the project's flock — the user's own CLI, or a second TCC. It says
#: `held` once it has the lock and keeps it until its stdin closes.
_FLOCK_HOLDER = (
    "import fcntl, sys\n"
    "handle = open(sys.argv[1], 'a+', encoding='utf-8')\n"
    "fcntl.flock(handle.fileno(), fcntl.LOCK_EX)\n"
    "print('held', flush=True)\n"
    "sys.stdin.read()\n"
)


@pytest.fixture
def project(tmp_path):
    """A project the skill's own writers built, so an `enter_phase` there really would write.

    The one `test_process_writer.py` builds (`_intake.planned_project`): a fixture that faked
    `process/` would fake the very bytes a busy answer has to leave alone.
    """
    if not process_writer.is_available():
        pytest.skip("skill submodule not checked out")
    return _intake.planned_project(tmp_path, ("2.3", "target-match"))


@pytest.fixture
def holder_process(tmp_path):
    """Another process holding `process/.process-write.lock` until `let_go()` or the test's end.

    The file's name is spelled out rather than borrowed from the module: every TCC on the machine,
    an older build included, has to agree on it, so a test that moved with a rename would miss
    exactly the break that matters.
    """
    lock_file = tmp_path / "process" / ".process-write.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    child = subprocess.Popen(
        [sys.executable, "-c", _FLOCK_HOLDER, str(lock_file)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
    )

    def let_go():
        if not child.stdin.closed:
            child.stdin.close()  # its `read()` returns, it exits, and the flock goes with it
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()

    try:
        assert child.stdout.readline().strip() == "held", "the holder never took the flock"
        yield SimpleNamespace(let_go=let_go)
    finally:
        let_go()
        child.stdout.close()


@contextmanager
def _held_by_another_thread(lock):
    """`lock` — a `hold(...)`, or a bare thread lock — held by another thread for the block."""
    held, release = threading.Event(), threading.Event()

    def holder():
        with lock:
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    assert held.wait(5)
    try:
        yield
    finally:
        release.set()
        thread.join(5)


def _bytes_of(folder: Path) -> dict[str, bytes]:
    """Every file under `folder`, as {relative path: bytes}.

    Not the lock file: that IS the lock. The holder makes it on taking the flock, and nothing is
    ever written into it.
    """
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != ".process-write.lock"
    }


def test_a_held_lock_answers_busy_within_the_deadline_and_writes_nothing(project, monkeypatch):
    monkeypatch.setattr(method_cli, "GUI_LOCK_WAIT_S", 0.3)
    before = _bytes_of(project / "process")          # {relative path: bytes}
    held, release = threading.Event(), threading.Event()

    def holder():
        with project_lock.hold(project, timeout_s=5):
            held.set()
            release.wait(5)

    threading.Thread(target=holder, daemon=True).start()
    assert held.wait(5)
    started = time.monotonic()
    with pytest.raises(process_writer.Busy, match="nothing was written"):
        process_writer.enter_phase(project, "1")
    release.set()
    assert time.monotonic() - started < 2.0
    assert _bytes_of(project / "process") == before


def test_a_free_lock_is_taken_at_once(tmp_path):
    """No time to wait at all, and none needed: a free lock is tried before the deadline is."""
    with project_lock.hold(tmp_path, timeout_s=0):
        pass


def test_a_hold_past_its_deadline_raises_lock_timeout_and_leaves_nothing_held(tmp_path):
    with _held_by_another_thread(project_lock.hold(tmp_path, timeout_s=5)):
        started = time.monotonic()
        with pytest.raises(project_lock.LockTimeout):
            with project_lock.hold(tmp_path, timeout_s=0.2):
                pass
        assert time.monotonic() - started < 2.0, "it gave up at its deadline, not at the release"

    with project_lock.hold(tmp_path, timeout_s=0):  # the second hold takes it at once
        pass


def test_a_timeout_on_a_project_with_no_process_folder_creates_nothing(tmp_path):
    """`process/` is made only on taking the flock, so a write that never got the lock leaves a
    project with none exactly as it was — no folder for the skill to read as a started project."""
    car = tmp_path / "car"
    car.mkdir()
    # The holder takes only the thread lock: a full `hold` takes the flock, which makes `process/`.
    with _held_by_another_thread(project_lock._thread_lock(car)):
        with pytest.raises(project_lock.LockTimeout):
            with project_lock.hold(car, timeout_s=0.2):
                pass

    assert list(car.iterdir()) == []


def _waits_on_the_thread_lock(project_dir: Path) -> bool:
    """Whether a write to `project_dir` waits — on this process's thread lock — rather than taking
    the writer lock within 0.2 s."""
    try:
        with project_lock.hold(project_dir, timeout_s=0.2):
            return False
    except project_lock.LockTimeout as exc:
        assert "thread lock" in str(exc), f"it waited on another stage: {exc}"
        return True


def test_a_project_reached_through_a_link_waits_on_the_same_thread_lock(tmp_path):
    """#171 on Windows, where the thread lock is the whole lock (no flock in phase 0): a project
    opened by two spellings — a linked folder, a mapped parent — must be one lock, or two writes to
    it run at once. `_thread_lock` keys by the resolved path, so a link and its target are one key;
    the holder takes the thread lock alone, so only that can make the second spelling wait."""
    real = tmp_path / "real" / "car"
    real.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "real", target_is_directory=True)

    with _held_by_another_thread(project_lock._thread_lock(real)):
        assert _waits_on_the_thread_lock(alias / "car"), "the linked spelling took a lock of its own"


@pytest.mark.xfail(sys.platform == "darwin", strict=True, raises=AssertionError,
                   reason="macOS keeps the typed case in `Path.resolve()`, so `_thread_lock` keys "
                          "CAR and Car apart (the flock still makes them wait there)")
def test_a_project_spelled_in_another_case_waits_on_the_same_thread_lock(tmp_path):
    """The same on a disk that ignores case — Windows' NTFS, where `resolve()` answers the case on
    disk. A disk that tells CAR from Car has two folders there, and two projects."""
    real = tmp_path / "Car"
    real.mkdir()
    if not os.path.isdir(tmp_path / "CAR"):
        pytest.skip("this disk tells CAR from Car")

    with _held_by_another_thread(project_lock._thread_lock(real)):
        assert _waits_on_the_thread_lock(tmp_path / "CAR"), "CAR took a lock of its own"


@posix_only
def test_a_lock_another_process_holds_answers_busy_within_the_same_deadline(
    project, holder_process, monkeypatch
):
    """The twin with a holder PROCESS, which no thread lock here can see. The flock used to wait
    out the child's own `timeout_s` (20 s for `enter_phase`); now it spends the same deadline the
    thread lock does."""
    monkeypatch.setattr(method_cli, "GUI_LOCK_WAIT_S", 0.3)
    before = _bytes_of(project / "process")

    started = time.monotonic()
    with pytest.raises(process_writer.Busy, match="nothing was written"):
        process_writer.enter_phase(project, "1")

    assert time.monotonic() - started < 2.0
    assert _bytes_of(project / "process") == before


def test_a_busy_answer_leaves_one_warning_naming_the_command_and_the_thread_lock(
    project, monkeypatch, app_log_warnings
):
    """A write refused as busy may have nobody left to tell: `close_session` at quit posts its
    refusal to a status strip whose window is closing, and `session_closed` was gone without a
    trace. So the log says it — once, with the command, the project and the lock that was held —
    and `Busy` keeps the `LockTimeout` as its cause."""
    monkeypatch.setattr(method_cli, "GUI_LOCK_WAIT_S", 0.2)

    with _held_by_another_thread(project_lock.hold(project, timeout_s=5)):
        app_log_warnings.clear()
        with pytest.raises(process_writer.Busy) as busy:
            process_writer.close_session(project)

    said = [record.getMessage() for record in app_log_warnings]
    assert len(said) == 1, said
    assert app_log_warnings[0].levelno == logging.WARNING
    assert "session-close" in said[0] and str(project) in said[0], said[0]
    assert "thread lock" in said[0], f"which lock was held, this process's own: {said[0]}"
    assert isinstance(busy.value.__cause__, project_lock.LockTimeout)


@posix_only
def test_a_busy_answer_behind_another_process_names_the_flock_file(
    project, holder_process, monkeypatch, app_log_warnings
):
    """The same one warning when the holder is another PROCESS: the stage it names is the flock,
    on the file that process holds."""
    monkeypatch.setattr(method_cli, "GUI_LOCK_WAIT_S", 0.2)
    app_log_warnings.clear()

    with pytest.raises(process_writer.Busy):
        process_writer.close_session(project)

    said = [record.getMessage() for record in app_log_warnings]
    assert len(said) == 1, said
    assert "session-close" in said[0] and str(project) in said[0], said[0]
    assert "flock" in said[0] and ".process-write.lock" in said[0], said[0]


@posix_only
def test_a_timeout_on_the_flock_gives_the_thread_lock_back(tmp_path, holder_process):
    """Past the deadline on the FLOCK, the thread lock already taken goes back with it: once the
    other process lets go, the next hold takes both at once."""
    with pytest.raises(project_lock.LockTimeout):
        with project_lock.hold(tmp_path, timeout_s=0.2):
            pass

    holder_process.let_go()
    with project_lock.hold(tmp_path, timeout_s=0):
        pass


@posix_only
def test_a_filesystem_that_cannot_flock_fails_at_once_and_gives_the_thread_lock_back(
        tmp_path, monkeypatch):
    """A network share answers ENOLCK however long it is asked. Only `BlockingIOError` means
    «another writer holds it»; anything else goes up as itself, at once — the old `_exclusive`
    caught every OSError, tried again to the deadline and answered «busy, try again», which no
    retry can make true — and the thread lock already taken goes back with it."""
    real = project_lock.fcntl.flock

    def flock(fd, operation):
        if operation & project_lock.fcntl.LOCK_EX:
            raise OSError(errno.ENOLCK, "No locks available")
        return real(fd, operation)

    monkeypatch.setattr(project_lock.fcntl, "flock", flock)

    started = time.monotonic()
    with pytest.raises(OSError) as failed:
        with project_lock.hold(tmp_path, timeout_s=3):
            pass
    elapsed = time.monotonic() - started

    assert not isinstance(failed.value, project_lock.LockTimeout), repr(failed.value)
    assert failed.value.errno == errno.ENOLCK, repr(failed.value)
    assert elapsed < 1.0, f"{elapsed:.2f}s of a 3 s budget: it waited for a lock nobody holds"
    thread_lock = project_lock._thread_lock(tmp_path)
    assert thread_lock.acquire(blocking=False), "the thread lock was left held"
    thread_lock.release()


@posix_only
def test_one_deadline_covers_both_locks_rather_than_one_each(tmp_path, holder_process):
    """What the wait for the thread lock spent comes off the flock's. A deadline per lock would
    let a write on the GUI thread freeze the window for twice its budget — here at least 3 s
    (1 s for the thread lock, then the whole 2 s again for the flock), so the bound below cannot
    pass it however fast the machine is, and a slow machine still has 0.8 s of slack.

    The timeout is the flock's, named by its file (M2): with no stage asked, a timer late under
    load let the thread-lock stage time out instead, and that passed a deadline per lock too. A
    timer up to a second late still frees the thread lock inside the budget."""
    thread_lock = project_lock._thread_lock(tmp_path)
    thread_lock.acquire()
    frees = threading.Timer(1.0, thread_lock.release)  # free at 1 s of a 2 s budget...
    frees.daemon = True
    frees.start()

    started = time.monotonic()
    with pytest.raises(project_lock.LockTimeout, match=r"\.process-write\.lock"):
        with project_lock.hold(tmp_path, timeout_s=2.0):  # ...so the flock gets what is left
            pass
    elapsed = time.monotonic() - started
    frees.join(5)

    assert elapsed < 2.8, f"{elapsed:.2f}s on a 2 s deadline: one deadline per lock"
