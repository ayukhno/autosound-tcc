"""The other writer, as another process: what holds a project's lock while a test asks TCC to write.

    method_lock_held(project)   the METHOD's lock (`.autosound/write.lock`), held through the vendored
                                `write_lock.hold` — what a bare CLI writer holds from its load to its
                                save; on every platform
    tccs_flock_held(project)    TCC's legacy flock on `process/.process-write.lock` — an older TCC, or
                                this one around a copy that does not lock itself; POSIX only

Each says `held` once it has the lock and keeps it until the block ends.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
from pathlib import Path
from typing import Iterator

from autosound_tcc.core import vendor_loader

from tests._method_copies import SKILL

#: The vendored method's lock module, run by the holder by its path, as the method's writers load it.
WRITE_LOCK = SKILL / "rew_tool" / "write_lock.py"

_METHOD_LOCK_HOLDER = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('write_lock', sys.argv[1])\n"
    "lock = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(lock)\n"
    "with lock.hold(sys.argv[2], 5):\n"
    "    print('held', flush=True)\n"
    "    sys.stdin.read()\n"
)

#: The file's name spelled out rather than borrowed from `project_lock`: every TCC on the machine,
#: an older build included, has to agree on it.
_FLOCK_HOLDER = (
    "import fcntl, sys\n"
    "handle = open(sys.argv[1], 'a+', encoding='utf-8')\n"
    "fcntl.flock(handle.fileno(), fcntl.LOCK_EX)\n"
    "print('held', flush=True)\n"
    "sys.stdin.read()\n"
)


@contextlib.contextmanager
def _held(argv: list[str], what: str) -> Iterator[None]:
    holder = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                              encoding="utf-8", env=vendor_loader.child_env())
    try:
        assert holder.stdout.readline().strip() == "held", f"the holder never took {what}"
        yield
    finally:
        holder.stdin.close()  # its `read()` returns, it exits, and the lock goes with it
        try:
            holder.wait(timeout=10)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.wait()
        holder.stdout.close()


def method_lock_held(project_dir: Path) -> contextlib.AbstractContextManager:
    """The method's lock on `project_dir`, held by another process for the block."""
    return _held([sys.executable, "-c", _METHOD_LOCK_HOLDER, str(WRITE_LOCK), str(project_dir)],
                 "the method's lock")


def tccs_flock_held(project_dir: Path) -> contextlib.AbstractContextManager:
    """TCC's legacy flock on `project_dir/process/.process-write.lock`, held by another process."""
    lock_file = Path(project_dir) / "process" / ".process-write.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    return _held([sys.executable, "-c", _FLOCK_HOLDER, str(lock_file)], "the flock")
