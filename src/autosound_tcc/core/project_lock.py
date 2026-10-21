"""One write to a project at a time — from any thread here and from any other process — under ONE
deadline (#171, G8 phase 0; #218, G8 phase 1).

`process.py` is a read-modify-write over a single JSON file, and nothing used to serialise it. That
was not theoretical: omp starts tool calls concurrently, and a real run fired `enter_phase` and two
`add_step`s before any of them returned — two came back with a traceback and the third with
`active_phase: null`, leaving a plan with one nameless step in it. The model had done everything
right.

Two locks, taken in this order. The project's thread lock, for this process's own threads; then, on
POSIX, a flock on `process/.process-write.lock`, because the other front-end is a separate process:
the user's own CLI can be driving the same project through the same skill (that is what
`signal_bus` exists for), and a lock only TCC's threads respect would not see it. Windows has no
flock here, and the thread lock is all there is.

From v3.1.3 the method locks itself (`method_lock`): every writer of it holds
`<project>/.autosound/write.lock`, the bare CLI's included, which closes what the flock only
narrowed. Around a child of such a copy `method_cli.spawn` asks for the thread lock alone
(`cross_process=False`): no flock, and so no `process/` made ahead of the method. The thread lock
stays — it keeps TCC's own round guard and its own writes apart, and on a folder the OS cannot lock
the method writes without its lock. The flock is the legacy half, for a copy that does not lock
itself.

ONE deadline over both. The thread lock used to wait without bound, so a write queued behind a
120 s `capture-check` — or `close_session` at quit, behind a queue of them — waited for all of it,
and the flock's only deadline was the child's own `timeout_s`. Now the wait has one budget, spent
across both locks; past it `hold` raises `LockTimeout` having taken nothing, and the caller answers
«busy» instead of freezing a window. A thread that asks again while it holds the lock is answered
at once (`_held_here`): the lock is not re-entrant, and that wait could only end at its deadline.

Qt-free. No other module imports `fcntl` or holds the writer lock.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from autosound_tcc.core import method_lock

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

#: Whether a copy of the method takes its own writer lock: `method_lock`'s, named here too because
#: the method's own docs name it here (its `write_lock.py`, `CONTRACT.md`).
locks_itself = method_lock.locks_itself

#: One per project folder: by its identity, `(st_dev, st_ino)`, or by its resolved path where it has
#: none (`_folder`).
_THREAD_LOCKS: dict[tuple[int, int] | Path, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()

#: A folder's identity -> the path it was keyed by before it was made (`_key`): a folder made while
#: its lock was held by path keeps that key for the life of the process.
_ALIASES: dict[tuple[int, int], Path] = {}

#: The folders this thread holds the lock on now (`hold`), by `_key`'s key.
_HELD = threading.local()


class LockTimeout(RuntimeError):
    """The project's writer lock was still held when the deadline passed. Nothing was taken."""


def lock_file(project_dir: Path | str) -> Path:
    """The file the cross-process half locks: `process/.process-write.lock` in the project."""
    return Path(project_dir) / _PROCESS_DIR / _LOCK_NAME


def _key(project_dir: Path | str) -> tuple[int, int] | Path:
    """The one key of `project_dir`'s folder for the life of this process: `_folder`'s answer, except
    for a folder made while its lock was held by path — not there when the hold began, made inside
    it by the legacy flock's `mkdir` or by the method's first write. Its identity then names the
    path it was keyed by, so a second writer, or the same thread asking again, meets the same lock
    (#218 review). Found by the folder's identity among the path-keyed locks held now, and kept.

    A kept alias is used only while its path is still that folder: renamed, or deleted and another
    folder made reusing its inode (APFS and ext4 do), it names another folder, and is dropped. The
    held path is looked for before the identity's own lock, so a folder deleted and made again
    inside a hold, on an inode an earlier folder's lock still keys, stays the one lock."""
    key = _folder(project_dir)
    if isinstance(key, Path):
        return key
    with _THREAD_LOCKS_GUARD:
        alias = _ALIASES.get(key)
        if alias is not None:
            if _identity(alias) == key:
                return alias
            del _ALIASES[key]
        for other, lock in _THREAD_LOCKS.items():
            if isinstance(other, Path) and lock.locked() and _identity(other) == key:
                _ALIASES[key] = other
                return other
    return key


def _identity(path: Path) -> tuple[int, int] | None:
    """`path`'s device and inode, or None where it has none to read."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_dev, info.st_ino) if info.st_ino else None


def _thread_lock(project_dir: Path | str, key=None) -> threading.Lock:
    """This process's lock for one project: one per project folder, so two spellings of a project
    share it and two projects never wait on each other. `key` is `_key`'s, when already read."""
    key = _key(project_dir) if key is None else key
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = _THREAD_LOCKS[key] = threading.Lock()
        return lock


def _held_here() -> set:
    """The folders this thread holds the lock on now, by `_key`'s key."""
    held = getattr(_HELD, "folders", None)
    if held is None:
        held = _HELD.folders = set()
    return held


def _left(deadline: float) -> float:
    """Seconds until `deadline`: never negative, and never more than a lock wait accepts."""
    return min(max(0.0, deadline - time.monotonic()), threading.TIMEOUT_MAX)


def _folder(project_dir: Path | str) -> tuple[int, int] | Path:
    """Which folder `project_dir` is (R-bb): the device and inode of its resolved path, one answer
    for every spelling that reaches it — a link, a mapped parent, another case on a disk that
    ignores case. The resolved path alone is not that: `resolve()` keeps the case it is given on
    macOS, so `CAR` and `Car` were two locks for one folder. Where there is no flock (Windows) the
    thread lock is the whole lock, and two locks for one folder are two writes at once.

    The resolved path where there is no identity to read: a folder not made yet, one that cannot be
    read, or a disk that numbers every folder 0 (a network share, a FUSE mount), where by number
    every folder on it would be one project (`method_binding._inside`, M24). And the path as given,
    made absolute, where it cannot even be resolved: a symlink loop, which Python 3.12's `resolve()`
    answers with `RuntimeError` — not an error `hold` may raise (Fable m3)."""
    try:
        resolved = Path(project_dir).resolve()
    except (OSError, RuntimeError):
        resolved = Path(os.path.abspath(project_dir))
    try:
        info = os.stat(resolved)
    except OSError:
        return resolved
    return (info.st_dev, info.st_ino) if info.st_ino else resolved


@contextmanager
def hold(project_dir: Path | str, timeout_s: float, *, cross_process: bool = True) -> Iterator[None]:
    """Hold the project's writer lock for the block, or raise `LockTimeout` once `timeout_s` is out.

    The thread lock first, then (POSIX) the flock, under one deadline: what the first wait spent
    comes off the second. A free lock is taken at once, even with `timeout_s=0`. Past the deadline
    nothing is left held, and `process/` is made only when the flock is about to be taken — a
    timeout on a project that has no `process/` creates nothing. Of its own it raises two things
    only, both answered by `method_cli.spawn`: `LockTimeout`, and the `OSError` itself of a lock the
    filesystem cannot take or a `process/` that cannot be made — the thread lock given back.

    `cross_process=False` is the thread lock alone: no flock, nothing made. What `spawn` asks around
    a child that takes the method's own lock (#218).

    Not re-entrant, and so a thread that holds it and asks again is answered `LockTimeout` at once,
    having waited for nothing: that wait could only end at its own deadline (#218, T3).
    """
    project_dir = Path(project_dir)
    deadline = time.monotonic() + timeout_s
    key = _key(project_dir)
    held_here = _held_here()
    if key in held_here:
        raise LockTimeout(
            f"this thread already holds the lock for {project_dir}: a write asked inside another "
            "write would wait for itself"
        )
    thread_lock = _thread_lock(project_dir, key)
    if not thread_lock.acquire(timeout=_left(deadline)):
        raise LockTimeout(
            f"this process's thread lock for {project_dir} was still held after {timeout_s:g}s "
            "(another write from this app)"
        )
    held_here.add(key)
    try:
        if cross_process:
            with _flock(project_dir, deadline, timeout_s):
                yield
        else:
            yield
    finally:
        held_here.discard(key)
        thread_lock.release()


@contextmanager
def _flock(project_dir: Path, deadline: float, timeout_s: float) -> Iterator[None]:
    """The cross-process half: an exclusive flock on `process/.process-write.lock` by `deadline`."""
    if fcntl is None:  # no flock here; this process's threads are still one at a time
        yield
        return
    path = lock_file(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Nothing is written into it, but it is opened in text mode, and a text handle with no encoding
    # is the same defect as the one that emptied the DSP panel on a Ukrainian Windows. One rule, no
    # exceptions to remember.
    handle = path.open("a+", encoding="utf-8")
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
                        f"the flock on {path} was still held after "
                        f"{timeout_s:g}s (another process is writing)"
                    ) from None
                time.sleep(min(_POLL_S, _left(deadline)))
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
