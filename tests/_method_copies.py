"""Copies of the method, and projects bound to them — the one set of these for every test (#169).

A test that needs another copy of the method builds one from the vendored tree, with the files it
needs changed (`copy_of_the_method`); `vendor/` itself is never touched. A copy is 8 MB, so the ones
no test changes are made once per pytest process — once per xdist worker — as the session fixtures
below. `tests/conftest.py` registers them, and must stay the only place that does: a session fixture
imported into a test module is a fixture of that module, and runs once for each module importing it.

    entry(project)                      where a project links its copy of the method
    same_path(a, b)                     one folder, however it is spelled
    copy_of_the_method(root, ...)       a copy of its own, changed as a test needs: made per test
    linked_and_approved(project, skill) the entry linked to `skill`, approved on this machine

    own_copy_is_the_submodule           TCC's own copy is the vendored one, whatever the shell says
    other_copy                          a second copy, in a repository with the plugin manifest
    bare_copy                           a copy in no repository: no manifest, no `.git`
    git_only_copy                       a copy in a git checkout that has no plugin manifest
    newer_copy                          a copy on a contract newer than this TCC drives
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable, Mapping, Optional

import pytest

from autosound_tcc.core import method_binding, vendor_loader

#: TCC's own copy in a checkout. Every copy is made from it.
SKILL = vendor_loader._SUBMODULE_DIR


def checked_out() -> bool:
    """Whether the vendored method is there to copy."""
    return vendor_loader._looks_like_the_skill(SKILL)


def entry(project: Path) -> Path:
    """Where a project links its copy of the method — the path both session adapters read."""
    return project / ".claude" / "skills" / vendor_loader.SKILL_NAME


def same_path(a, b) -> bool:
    """Whether two paths name one folder, through every link on the way."""
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def copy_of_the_method(root: Path, *, changes: Optional[Mapping[str, Callable[[str], str]]] = None,
                       manifest: bool = False, git: bool = False) -> Path:
    """The vendored skill folder copied to `root/skills/autosound-tuning`, the layout of its own
    repository; the skill folder is answered.

    `changes` maps a file under the skill folder (`rew_tool/state/process.py`) to what its text
    becomes. `manifest` puts the plugin manifest at `root`, where the method's repository has it,
    and `git` a `.git` there. With neither the copy is in no repository: a skill folder unpacked on
    its own. A test that changes a copy makes its own; only an unchanged one is shared (below).
    """
    if not checked_out():
        pytest.skip("the vendored method is not checked out (git submodule update --init)")
    skill = root / "skills" / vendor_loader.SKILL_NAME
    shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for rel, change in (changes or {}).items():
        path = skill / rel
        path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")
    if manifest:
        (root / ".claude-plugin").mkdir()
        shutil.copy2(SKILL.parents[1] / ".claude-plugin" / "plugin.json",
                     root / ".claude-plugin" / "plugin.json")
    if git:
        (root / ".git").mkdir()
    return skill


def linked_and_approved(project: Path, skill: Path) -> method_binding.Binding:
    """`project`'s entry linked to `skill`, and the link approved on this machine: the real
    `method_binding.approve`, on the settings store each test is given its own of (conftest)."""
    entry(project).parent.mkdir(parents=True)
    entry(project).symlink_to(skill, target_is_directory=True)
    binding = method_binding.approve(method_binding.for_project(project))
    assert binding.state == method_binding.APPROVED, binding.reason
    return binding


# ---- fixtures: registered once, in tests/conftest.py ------------------------------------------


@pytest.fixture
def own_copy_is_the_submodule(monkeypatch):
    """TCC's own copy is the vendored one, whatever the developer's shell points the override at,
    and a child hears of a copy only from TCC — not from a variable left in that shell."""
    monkeypatch.delenv(vendor_loader.SKILL_DIR_ENV, raising=False)
    monkeypatch.delenv(method_binding.SKILL_ROOT_ENV, raising=False)
    if not checked_out():
        pytest.skip("skill submodule not checked out")
    assert vendor_loader.skill_dir() == SKILL


@pytest.fixture(scope="session")
def other_copy(tmp_path_factory) -> Path:
    """A second copy of the method in a repository of its own, the plugin manifest beside
    `skills/`."""
    return copy_of_the_method(tmp_path_factory.mktemp("other-method") / "autosound-tuning-skill",
                              manifest=True)


@pytest.fixture(scope="session")
def bare_copy(tmp_path_factory) -> Path:
    """A copy with no manifest and no `.git` above it: a skill folder unpacked on its own."""
    return copy_of_the_method(tmp_path_factory.mktemp("bare-method"))


@pytest.fixture(scope="session")
def git_only_copy(tmp_path_factory) -> Path:
    """A copy in a git checkout with no plugin manifest — dotfiles kept under git, an old clone:
    `Binding.plugin_root()` finds its repository by the `.git` alone."""
    return copy_of_the_method(tmp_path_factory.mktemp("git-only-method"), git=True)


@pytest.fixture(scope="session")
def newer_copy(tmp_path_factory) -> Path:
    """A copy whose `contract.py` speaks a contract this TCC does not. No released copy carries a
    number yet (v3.1.1's `contract.py` has none), so the one file is changed by hand (Ruling 3)."""
    return copy_of_the_method(tmp_path_factory.mktemp("newer-method"), changes={
        "rew_tool/contract.py": lambda text: text + "\nCONTRACT_VERSION = 1\n"})
