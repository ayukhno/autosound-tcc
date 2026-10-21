"""`core.method_lock` — what TCC knows of the method's own writer lock (#218, G8 phase 1), and the
seam it changes: a child that locks itself is run with no flock of TCC's around it.

From v3.1.3 every method writer takes `<project>/.autosound/write.lock` (its `rew_tool/write_lock.py`,
`PROTOCOL = 1`), waits `AUTOSOUND_LOCK_TIMEOUT_S` and exits 75 when another writer holds it. What is
tested here is TCC's half: the probe of the copy the child runs, the wait TCC hands the child and the
bound it gives it, the busy answer, and what TCC no longer does around such a child — take its flock
on `process/.process-write.lock`, and so make `process/` ahead of the method. TCC's in-process thread
lock stays (the plan's «decision on TCC's own lock»), and so does the whole legacy lock for a copy
that does not lock itself.

«The other writer» is the method's own lock, held by another process through the vendored
`write_lock.hold` — what a bare CLI session holds — never a stand-in that only looks like it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from autosound_tcc.core import method_cli, method_lock, process_writer, project_lock

from tests._method_copies import SKILL, copy_of_the_method

#: The vendored method's lock module: read as text here, and run by the holder process.
_WRITE_LOCK = SKILL / "rew_tool" / "write_lock.py"

#: Another process holding the METHOD's lock on a project — what a bare CLI writer holds from its
#: load to its save. It says `held` once it has the lock and keeps it until its stdin closes. The
#: vendored module, loaded by its path as the method's own writers load it.
_METHOD_LOCK_HOLDER = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('write_lock', sys.argv[1])\n"
    "lock = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(lock)\n"
    "with lock.hold(sys.argv[2], 5):\n"
    "    print('held', flush=True)\n"
    "    sys.stdin.read()\n"
)


def _vendored() -> None:
    if not process_writer.is_available():
        pytest.skip("skill submodule not checked out")


# ---- what TCC knows of the method's lock ----------------------------------------------------------


def test_the_names_tcc_speaks_are_the_methods_own():
    """The exit code and the wait's variable are the method's, read off its text rather than
    trusted: a stub nobody compares to the real thing is how a green suite starts lying."""
    _vendored()
    text = _WRITE_LOCK.read_text(encoding="utf-8")

    assert re.search(rf'^ENV_TIMEOUT = "{method_lock.WAIT_ENV}"$', text, re.MULTILINE)
    assert re.search(rf"^    exit_code = {method_lock.BUSY_EXIT}$", text, re.MULTILINE)
    assert method_lock.BUSY_SAID.startswith("busy: ") and "nothing was written" in method_lock.BUSY_SAID


def test_the_old_names_are_the_same_objects():
    """`method_cli`'s names and `project_lock.locks_itself` stay, as the same objects: the method's
    own docs name `core/project_lock.py`'s `locks_itself` (`write_lock.py`, `CONTRACT.md`)."""
    assert project_lock.locks_itself is method_lock.locks_itself
    assert method_cli.EXIT_BUSY == method_lock.BUSY_EXIT
    assert method_cli.METHOD_LOCK_WAIT_ENV == method_lock.WAIT_ENV
    assert method_cli.BUSY_SAID == method_lock.BUSY_SAID


def test_a_copy_s_answer_is_read_once_until_its_file_changes(tmp_path, monkeypatch):
    """Every spawn asks, so the answer is kept per file, by its mtime and size, and read again once
    the file changes: an update in place is seen on the next call."""
    skill = copy_of_the_method(tmp_path / "repo")
    write_lock = skill / "rew_tool" / "write_lock.py"
    real_read_text = Path.read_text
    reads: list = []

    def read_text(self, *args, **kwargs):
        if self.name == "write_lock.py":
            reads.append(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)

    assert [method_lock.locks_itself(skill) for _ in range(3)] == [True] * 3
    assert len(reads) == 1, reads

    write_lock.write_text("PROTOCOL = 2\n", encoding="utf-8")
    assert method_lock.locks_itself(skill) is False
    assert len(reads) == 2, "read again once it changed"
    write_lock.unlink()
    assert method_lock.locks_itself(skill) is False
