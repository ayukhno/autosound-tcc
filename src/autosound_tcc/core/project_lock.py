"""One write to a project at a time — from any thread here and from any other process — under ONE
deadline (#171, G8 phase 0).

`process.py` is a read-modify-write over a single JSON file, and nothing used to serialise it. That
was not theoretical: omp starts tool calls concurrently, and a real run fired `enter_phase` and two
`add_step`s before any of them returned — two came back with a traceback and the third with
`active_phase: null`, leaving a plan with one nameless step in it. The model had done everything
right.

Two locks, taken in this order. The project's thread lock, for this process's own threads; then, on
POSIX, a flock on `process/.process-write.lock`, because the other front-end is a separate process:
the user's own CLI can be driving the same project through the same skill (that is what
`signal_bus` exists for), and a lock only TCC's threads respect would not see it. The skill's own
CLI does not take this lock, so this narrows the window rather than closing it — closing it belongs
in the method, as a change request. Windows has no flock here, and the thread lock is all there is.

ONE deadline over both. The thread lock used to wait without bound, so a write queued behind a
120 s `capture-check` — or `close_session` at quit, behind a queue of them — waited for all of it,
and the flock's only deadline was the child's own `timeout_s`. Now the wait has one budget, spent
across both locks; past it `hold` raises `LockTimeout` having taken nothing, and the caller answers
«busy» instead of freezing a window.

Qt-free. No other module imports `fcntl` or holds the writer lock.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:  # POSIX only; Windows falls back to the thread lock alone.
    import fcntl
except ImportError:  # pragma: no cover - not exercised on macOS/Linux
    fcntl = None  # type: ignore[assignment]

# The skill's process folder, and the lock file in it. Nothing is ever written into the file — the
# file IS the lock — and every TCC on the machine, an older build included, locks this same name.
_PROCESS_DIR = "process"
_LOCK_NAME = ".process-write.lock"

# flock has no timed wait, so a held one is tried again this often until the deadline.
_POLL_S = 0.05

_THREAD_LOCKS: dict[Path, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class LockTimeout(RuntimeError):
    """The project's writer lock was still held when the deadline passed. Nothing was taken."""


def _thread_lock(project_dir: Path | str) -> threading.Lock:
    """This process's lock for one project: one per resolved path, so two spellings of a project
    share it and two projects never wait on each other."""
    key = Path(project_dir).resolve()
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = _THREAD_LOCKS[key] = threading.Lock()
        return lock


def _left(deadline: float) -> float:
    """Seconds until `deadline`: never negative, and never more than a lock wait accepts."""
    return min(max(0.0, deadline - time.monotonic()), threading.TIMEOUT_MAX)


@contextmanager
def hold(project_dir: Path | str, timeout_s: float) -> Iterator[None]:
    """Hold the project's writer lock for the block, or raise `LockTimeout` once `timeout_s` is out.

    The thread lock first, then (POSIX) the flock, under one deadline: what the first wait spent
    comes off the second. A free lock is taken at once, even with `timeout_s=0`. Past the deadline
    nothing is left held, and `process/` is made only when the flock is about to be taken — a
    timeout on a project that has no `process/` creates nothing.

    Not re-entrant: a thread that holds it and asks again waits out its own deadline.
    """
    project_dir = Path(project_dir)
    deadline = time.monotonic() + timeout_s
    thread_lock = _thread_lock(project_dir)
    if not thread_lock.acquire(timeout=_left(deadline)):
        raise LockTimeout(f"another write to {project_dir} held the lock past {timeout_s:g}s")
    try:
        with _flock(project_dir, deadline, timeout_s):
            yield
    finally:
        thread_lock.release()


@contextmanager
def _flock(project_dir: Path, deadline: float, timeout_s: float) -> Iterator[None]:
    """The cross-process half: an exclusive flock on `process/.process-write.lock` by `deadline`."""
    if fcntl is None:  # no flock here; this process's threads are still one at a time
        yield
        return
    folder = project_dir / _PROCESS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    # Nothing is written into it, but it is opened in text mode, and a text handle with no encoding
    # is the same defect as the one that emptied the DSP panel on a Ukrainian Windows. One rule, no
    # exceptions to remember.
    handle = (folder / _LOCK_NAME).open("a+", encoding="utf-8")
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                # Held by another writer. Only this error is: a filesystem that cannot lock at all
                # raises something else, and that goes up as itself — «busy, try again» would be
                # a sentence no retry could ever make true.
                if time.monotonic() >= deadline:
                    raise LockTimeout(
                        f"another writer held {folder / _LOCK_NAME} past {timeout_s:g}s"
                    ) from None
                time.sleep(min(_POLL_S, _left(deadline)))
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
