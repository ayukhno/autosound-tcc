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

import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from autosound_tcc.core import (
    method_cli, method_lock, process_writer, project_lock, vendor_loader,
)

from tests import _intake
from tests._lock_holders import WRITE_LOCK, method_lock_held, tccs_flock_held
from tests._method_copies import copy_of_the_method

#: The vendored method's lock module: read as text here, and run by the holder process.
_WRITE_LOCK = WRITE_LOCK


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


# ---- the seam: what TCC holds around a child that locks itself ------------------------------------


@pytest.fixture
def project(tmp_path):
    """A project at phase 2, built by the skill's own writers (`_intake.planned_project`)."""
    _vendored()
    return _intake.planned_project(tmp_path / "car", ("2.3", "target-match"))


@pytest.fixture
def legacy(monkeypatch):
    """Every copy read as one that does not lock itself — a project pinned to a method older than
    v3.1.3 — so TCC's whole legacy lock runs around its child (T4)."""
    monkeypatch.setattr(method_lock, "locks_itself", lambda _skill_dir: False)


def _files(folder: Path) -> dict[str, bytes]:
    """Every file under `folder` but git's own, as {relative path: bytes}."""
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(folder.rglob("*"))
            if path.is_file() and ".git" not in path.relative_to(folder).parts}


def _plan(project_dir: Path) -> list[str]:
    state = json.loads((project_dir / "process" / "process-state.json").read_text(encoding="utf-8"))
    return [step["id"] for step in state["plan"]]


def _added(project_dir: Path) -> list[str]:
    lines = (project_dir / "process" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    return [e["step"] for e in map(json.loads, lines) if e.get("type") == "step_added"]


def test_t1_a_write_the_methods_lock_holds_answers_busy_and_changes_nothing(project, monkeypatch):
    """T1 (PLAN-AUDIT §5.4): another process holds the method's lock — a bare CLI writer between
    its load and its save. TCC's write is told the wait (here the GUI thread's, 0.5 s), its child
    waits that long and exits 75: `Busy` in the method's own words, every file as it was, and the
    lock's folder ignores itself — `git add -A` stages nothing from `.autosound/`."""
    monkeypatch.setattr(method_cli, "GUI_LOCK_WAIT_S", 0.5)
    subprocess.run(["git", "init", "-q", str(project)], check=True)

    with method_lock_held(project):
        before = _files(project)
        with pytest.raises(process_writer.Busy) as busy:
            process_writer.enter_phase(project, "1")
        after = _files(project)

    assert str(busy.value).startswith("busy: ") and "write.lock" in str(busy.value), busy.value
    assert after == before, "a busy write changed a file"
    subprocess.run(["git", "-C", str(project), "add", "-A"], check=True)
    staged = subprocess.run(["git", "-C", str(project), "diff", "--cached", "--name-only"],
                            check=True, capture_output=True, text=True).stdout.splitlines()
    assert staged and not [name for name in staged if name.startswith(".autosound/")], staged


@pytest.mark.skipif(sys.platform == "win32", reason="TCC's legacy flock is POSIX only")
def test_a_copy_that_locks_itself_is_run_with_no_flock_of_tccs_around_it(project, monkeypatch):
    """The seam's point: a child that takes the method's lock is not also made to wait on TCC's
    `process/.process-write.lock`. Another TCC — an older build — holding that flock no longer
    blocks this write, which lands; the method's own lock is what orders the two."""
    monkeypatch.setattr(method_cli, "GUI_LOCK_WAIT_S", 0.5)

    with tccs_flock_held(project):
        process_writer.add_step(project, "2.4", "added past an old TCC's flock")

    assert "2.4" in _plan(project)


@pytest.mark.parametrize("verb", ["add-step", "start", "decision"])
def test_a_folder_with_no_project_refuses_a_first_write_and_gets_no_process_folder(
        tmp_path, verb):
    """F-100's item, one behaviour on every system: TCC no longer makes `process/` ahead of a
    method that locks itself (its flock did, on macOS and Linux and not on Windows), so the
    method's own check sees a folder with no project — and refuses any first write but the two
    that start one, with nothing made."""
    _vendored()
    car = tmp_path / "car"
    car.mkdir()
    call = {"add-step": lambda: process_writer.add_step(car, "1.1", "a step"),
            "start": lambda: process_writer.start_step(car, "1.1"),
            "decision": lambda: process_writer.record_decision(car, "keep 45 degrees?", "yes")}[verb]

    with pytest.raises(process_writer.ProcessWriterError) as refused:
        call()

    assert "not a project yet" in str(refused.value), refused.value
    assert not (car / "process").exists(), "a folder with no project got a process/"


@pytest.mark.parametrize("verb", ["enter-phase -1", "session-start"])
def test_a_folder_with_no_project_takes_the_two_writes_that_start_one(tmp_path, verb):
    """The intake's `enter-phase -1`, and TCC's own `session-start` on a folder that is there,
    start a project where there is none: the method makes `process/` for them itself."""
    _vendored()
    car = tmp_path / "car"
    car.mkdir()

    if verb == "session-start":
        process_writer.record_session(car, "tcc", "opus")
    else:
        process_writer.enter_phase(car, "-1")

    assert (car / "process" / "journal.jsonl").is_file()


def test_t3_a_write_asked_inside_tccs_own_hold_refuses_at_once(project, monkeypatch):
    """T3: TCC's lock is not re-entrant, so a write asked on a thread that already holds it used to
    wait out its own deadline and answer busy — every time. It refuses at once, as `Busy`, naming
    why, and starts nothing."""
    monkeypatch.setattr(method_cli, "GUI_LOCK_WAIT_S", 10.0)

    with project_lock.hold(project, 5):
        before = _files(project)
        started = time.monotonic()
        with pytest.raises(process_writer.Busy) as busy:
            process_writer.enter_phase(project, "1")
        elapsed = time.monotonic() - started

    assert "this thread already holds" in str(busy.value.__cause__), busy.value.__cause__
    assert elapsed < 5, f"{elapsed:.1f}s of a 10 s wait: it waited for itself"
    assert _files(project) == before


def test_t4_a_copy_that_does_not_lock_itself_keeps_tccs_whole_lock(project, monkeypatch, legacy):
    """T4: `locks_itself` forced False — a project pinned to a method before v3.1.3. TCC's legacy
    lock runs whole: the write lands, under the flock on `process/.process-write.lock` where there
    is one (POSIX), and a holder of TCC's lock — another thread here, and on POSIX another process
    holding the flock — makes the next write `Busy` with nothing changed."""
    monkeypatch.setattr(method_cli, "GUI_LOCK_WAIT_S", 0.3)

    process_writer.add_step(project, "2.4", "on the legacy path")
    assert "2.4" in _plan(project)
    assert (project / "process" / ".process-write.lock").exists() == (project_lock.fcntl is not None)

    before = _files(project)
    held, release = threading.Event(), threading.Event()

    def holder():
        with project_lock.hold(project, timeout_s=5):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    assert held.wait(5)
    try:
        with pytest.raises(process_writer.Busy):
            process_writer.add_step(project, "2.5", "past a held thread lock")
    finally:
        release.set()
        thread.join(5)
    if project_lock.fcntl is not None:
        with tccs_flock_held(project):
            with pytest.raises(process_writer.Busy, match="nothing was written"):
                process_writer.add_step(project, "2.5", "past another process's flock")
    assert _files(project) == before


#: Inserted into a copy's `process.py`: `add-step`'s own load holds what it read for a second
#: before handing it back — the window in which a second writer that is not kept out loads the
#: same state and saves over the first.
_A_WINDOW_IN_ADD_STEP = """
import time as _tcc_time

_tcc_real_load, _tcc_real_add_step = Process.load, Process.add_step


def _tcc_load_then_wait(self, *args, **kwargs):
    state = _tcc_real_load(self, *args, **kwargs)
    Process.load = _tcc_real_load
    _tcc_time.sleep(1.0)
    return state


def _tcc_add_step(self, *args, **kwargs):
    Process.load = _tcc_load_then_wait
    return _tcc_real_add_step(self, *args, **kwargs)


Process.add_step = _tcc_add_step

"""

#: Appended to a copy's `write_lock.py`: an OS that refuses every lock (a network share, the
#: Mac<->VM shared folder). The method writes without its lock there, and says so in a `note:`.
_NO_OS_LOCK = """

def _os_lock(fd):
    raise OSError(errno.ENOLCK, "No locks available")
"""


def test_on_a_folder_the_os_cannot_lock_tccs_thread_lock_keeps_two_writes_apart(
        tmp_path, monkeypatch):
    """The plan's decision on TCC's own lock: where the OS lock is not available the method writes
    WITHOUT its lock, and TCC's in-process thread lock is what keeps two of its own writes — two
    MCP calls on their own threads — from saving over each other. Each `add-step` holds what it
    loaded for a second; both land, in the state and in the journal."""
    _vendored()
    project = _intake.planned_project(tmp_path / "car", ("2.3", "target-match"))
    guard = '\nif __name__ == "__main__":'
    copy = copy_of_the_method(tmp_path / "repo", changes={
        "rew_tool/state/process.py": lambda text: text.replace(guard, _A_WINDOW_IN_ADD_STEP + guard),
        "rew_tool/write_lock.py": lambda text: text + _NO_OS_LOCK,
    })
    assert method_lock.locks_itself(copy)
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(copy))
    failed: list = []

    def add(step_id: str) -> None:
        try:
            process_writer.add_step(project, step_id, f"step {step_id}")
        except process_writer.ProcessWriterError as exc:
            failed.append(exc)

    writers = [threading.Thread(target=add, args=(sid,)) for sid in ("2.4", "2.5")]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(60)

    assert failed == []
    assert {"2.4", "2.5"} <= set(_plan(project)), _plan(project)
    assert _added(project).count("2.4") == 1 and _added(project).count("2.5") == 1


#: Inserted into a copy's `dsp_profile.py`: `set-field`'s read of the draft holds what it read for a
#: second before handing it back — the window in which a second writer that is not kept out reads
#: the same draft and saves over the first.
_A_WINDOW_IN_SET_FIELD = """
import time as _tcc_time

_tcc_real_set_field, _tcc_real_load_draft = set_field, load_draft


def _tcc_load_draft_then_wait(*args, **kwargs):
    global load_draft
    data = _tcc_real_load_draft(*args, **kwargs)
    load_draft = _tcc_real_load_draft
    _tcc_time.sleep(1.0)
    return data


def set_field(*args, **kwargs):
    global load_draft
    load_draft = _tcc_load_draft_then_wait
    return _tcc_real_set_field(*args, **kwargs)

"""


def test_on_a_folder_the_os_cannot_lock_two_profile_answers_both_land(tmp_path, monkeypatch):
    """The same for the profile's writer (#218 review): it took no lock of TCC's at all, so on a
    folder the OS cannot lock two of the interview's answers, saved at once from two threads, read
    the same draft and the second saved over the first. TCC's thread lock keeps them apart."""
    from autosound_tcc.core import profile_writer

    _vendored()
    project = tmp_path / "car"
    project.mkdir()
    guard = '\nif __name__ == "__main__":'
    copy = copy_of_the_method(tmp_path / "repo", changes={
        "rew_tool/dsp_profile.py": lambda text: text.replace(guard, _A_WINDOW_IN_SET_FIELD + guard),
        "rew_tool/write_lock.py": lambda text: text + _NO_OS_LOCK,
    })
    monkeypatch.setenv(vendor_loader.SKILL_DIR_ENV, str(copy))
    profile_writer.start(project, "Musway", "M6")
    failed: list = []

    def answer(field: str, value: int) -> None:
        try:
            profile_writer.set_field(project, field, value)
        except profile_writer.ProfileWriterError as exc:
            failed.append(exc)

    writers = [threading.Thread(target=answer, args=("delay.max_ms", 20)),
               threading.Thread(target=answer, args=("dsp_processing_rate_hz", 96000))]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(60)

    assert failed == []
    draft = json.loads((project / "dsp_profile.draft.json").read_text(encoding="utf-8"))
    profile = draft.get("dsp_profile", draft)
    assert profile.get("delay", {}).get("max_ms") == 20, profile
    assert profile.get("dsp_processing_rate_hz") == 96000, profile
