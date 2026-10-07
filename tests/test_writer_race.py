"""The race TCC's lock cannot close: the skill's CLI, run bare, writing over TCC (#171, G8 phase 0).

`project_lock.hold` orders TCC's own writers — its threads, and a second TCC — and nothing else.
The method's `process.py` run by a person or another agent takes no lock: it loads the state, and
when TCC's write lands before it saves, it saves what it loaded over it — the step TCC added is gone
from the plan. That holds until the method locks itself (G8 phase 1, W-11), so the test saying so is
an expected failure until then. On a copy whose `rew_tool/write_lock.py` declares `PROTOCOL = 1`
the mark's condition is False and the test runs as a plain one; a copy that closes the race some
other way passes it under the mark, and `strict` turns that into a red. Either way the mark comes
off in that commit.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

import pytest

from autosound_tcc.core import process_writer, project_lock, vendor_loader

from tests import _intake

#: The two writes: each adds one step to phase 2.
TCC_STEP = ("2.6", "added by TCC")
BARE_STEP = ("2.7", "added by the bare CLI")

#: How long TCC's write may take to land while the bare one is held. Today nothing it waits for is
#: held by the bare writer, so «go» follows the moment it lands. A method that locks itself holds
#: its lock across load → write → append, so there TCC's write cannot land until the bare one lets
#: go: this is when it is let go, and it stays short of the 10 s a locking child waits for its lock
#: (PLAN-AUDIT-2026-10 §5.4).
TCC_LANDS_S = 5.0

#: The bare CLI as a person or another agent runs it — `python process.py <process-dir> add-step
#: <id> <name>`, from the copy TCC runs — held at the one point that decides the race: its first
#: `Process.load` has read the state, says «loaded», and waits for «go» before handing it back.
#: Imported by path, because `runpy` leaves no moment between the module's definitions and its
#: `__main__` guard to wrap `load` in; the guard's own lines are repeated at the end instead. A
#: «go» that never comes ends it with nothing written, so a broken harness cannot hang a run.
_BARE_WRITE = """\
import importlib.util, os, pathlib, sys, time

script, loaded, go, *argv = sys.argv[1:]
spec = importlib.util.spec_from_file_location("bare_process", script)
process = importlib.util.module_from_spec(spec)
spec.loader.exec_module(process)
load = process.Process.load


def load_then_wait(self):
    state = load(self)
    process.Process.load = load  # only the first load is held
    pathlib.Path(loaded).touch()
    deadline = time.monotonic() + 30
    while not os.path.exists(go):
        if time.monotonic() > deadline:
            sys.exit("the bare write: no go within 30 s, nothing written")
        time.sleep(0.01)
    return state


process.Process.load = load_then_wait
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(script))))
import console
console.install()
sys.argv = [script, *argv]
sys.exit(process._main(sys.argv))
"""


@pytest.fixture
def project(tmp_path):
    """A project at phase 2, built by the skill's own writers (`_intake.planned_project`)."""
    if not process_writer.is_available():
        pytest.skip("skill submodule not checked out")
    return _intake.planned_project(tmp_path / "car", ("2.3", "target-match"))


def _held_until_loaded(marker: Path, bare: subprocess.Popen) -> bool:
    """Whether the bare writer reached its pause — False the moment it ends first, or after 30 s."""
    deadline = time.monotonic() + 30
    while not marker.exists():
        if bare.poll() is not None or time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def _tcc_writes_while_the_bare_cli_is_held(project: Path, harness: Path) -> None:
    """TCC's `add_step` runs while the bare CLI's own `add-step` sits between its load and its save.

    The order is forced, not hoped for: the race test in `test_process_writer.py` lost its race
    about one run in twelve, and under `strict` a race that happens not to lose is a red. The bare
    writer loads and says «loaded»; TCC's write lands; «go»; the bare writer saves what it loaded.
    TCC's write runs on a worker so that a method that locks itself can make it wait rather than
    deadlock the test — see `TCC_LANDS_S`.

    A harness that breaks fails as itself — a RuntimeError, or TCC's own exception — never as the
    AssertionError the expected failure is about.
    """
    harness.mkdir()
    loaded, go = harness / "loaded", harness / "go"
    wrapper = harness / "bare_write.py"
    wrapper.write_text(_BARE_WRITE, encoding="utf-8")
    bare = subprocess.Popen(
        [sys.executable, str(wrapper), str(process_writer.script_path()), str(loaded), str(go),
         str(project / "process"), "add-step", *BARE_STEP],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        env=vendor_loader.child_env(),
    )
    said_loaded = False
    try:
        said_loaded = _held_until_loaded(loaded, bare)
        if said_loaded:
            with ThreadPoolExecutor(max_workers=1) as pool:
                tcc = pool.submit(process_writer.add_step, project, *TCC_STEP)
                wait([tcc], timeout=TCC_LANDS_S)
                go.touch()
                tcc.result()  # TCC's own failure, raised as itself
    finally:
        go.touch()  # whatever happened above, the bare writer is not left waiting
        try:
            out, err = bare.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            bare.kill()
            out, err = bare.communicate()
    if not said_loaded:
        raise RuntimeError(
            f"the bare write never said «loaded» (exit {bare.returncode}): {err or out}")
    if bare.returncode != 0:
        raise RuntimeError(f"the bare write failed (exit {bare.returncode}): {err or out}")


def _plan(project: Path) -> list[str]:
    state = json.loads((project / "process" / "process-state.json").read_text(encoding="utf-8"))
    return [step["id"] for step in state["plan"]]


def _added(project: Path) -> list[str]:
    lines = (project / "process" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    return [e["step"] for e in map(json.loads, lines) if e.get("type") == "step_added"]


@pytest.mark.xfail(
    not project_lock.locks_itself(vendor_loader.skill_dir()),
    strict=True,
    raises=AssertionError,
    reason="TCC's lock does not bind the skill's own CLI until the skill locks itself "
           "(G8 phase 1, W-11)",
)
def test_a_bare_cli_write_keeps_the_step_tcc_added_meanwhile(project, tmp_path):
    """Today it does not: the bare writer saves the plan it loaded, and TCC's step is gone."""
    _tcc_writes_while_the_bare_cli_is_held(project, tmp_path / "race")

    plan = _plan(project)
    missing = [sid for sid in (TCC_STEP[0], BARE_STEP[0]) if sid not in plan]
    assert not missing, f"one write saved over the other: {missing} not in the plan {plan}"


def test_the_journal_holds_both_writes_through_the_race(project, tmp_path):
    """The journal is appended to, never rewritten from what a writer loaded (`process.py`: history
    append-only, the slice derived), so the race costs the plan a step and the history nothing.
    Not an expected failure: it holds today, and `strict` would turn a check that holds into a red.
    """
    _tcc_writes_while_the_bare_cli_is_held(project, tmp_path / "race")

    added = _added(project)
    assert added.count(TCC_STEP[0]) == 1 and added.count(BARE_STEP[0]) == 1, added


def test_only_a_copy_whose_write_lock_declares_protocol_1_locks_itself(tmp_path):
    """The vendored v3.1.1 has no `rew_tool/write_lock.py`. A copy of it with one that declares
    `PROTOCOL = 1` locks itself; one that declares another protocol, or cannot be read as text,
    does not — and the answer is read from the text, never by importing the method."""
    vendored = vendor_loader._SUBMODULE_DIR
    if not (vendored / "rew_tool" / "state" / "process.py").is_file():
        pytest.skip("skill submodule not checked out")
    assert project_lock.locks_itself(vendored) is False, (
        "the vendored method locks itself: the re-pin that brought it takes the race test's "
        "xfail off, and this line with it")

    copy = tmp_path / "skill"
    shutil.copytree(vendored, copy, ignore=shutil.ignore_patterns("__pycache__"))
    write_lock = copy / "rew_tool" / "write_lock.py"
    write_lock.write_text('"""The skill\'s own writer lock."""\n\nPROTOCOL = 1\n', encoding="utf-8")
    assert project_lock.locks_itself(copy) is True

    write_lock.write_text("PROTOCOL = 2\n", encoding="utf-8")
    assert project_lock.locks_itself(copy) is False
    write_lock.write_bytes(b"PROTOCOL = 1\n# \xff\xfe\n")  # not UTF-8
    assert project_lock.locks_itself(copy) is False
