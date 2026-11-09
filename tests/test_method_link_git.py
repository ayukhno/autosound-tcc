"""The method's link stays out of the project's git (#255).

`.claude/skills/autosound-tuning` is an absolute link to one machine's folder. Once git carried it, a
clone on a second Mac opened with the first Mac's method. The Arbiter's decision (2026-11-09): TCC
ignores the link, takes a tracked one out of the index once, and commits exactly that itself.

Every test runs a real git in `tmp_path` and reads what landed in the index and in `git log`. A POSIX
symlink stands for the link; a Windows junction, which git reads as a folder, is patched in.
"""

from __future__ import annotations

import importlib
import logging
import os
import subprocess
from pathlib import Path

import pytest

from autosound_tcc.core import (
    child,
    mcp_key,
    mcp_server,
    method_binding,
    method_link_git,
    self_check,
    vendor_loader,
)
from autosound_tcc.ui.tcc import i18n

LINK = method_link_git.LINK

_POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="a real symlink, a hook script, file modes")
_NOT_ROOT = pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0,
                               reason="root writes past a file's mode")


def _git(project: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, check=check)


def _commits(project: Path) -> int:
    return int(_git(project, "rev-list", "--count", "HEAD").stdout.strip())


def _index(project: Path) -> list[str]:
    return _git(project, "ls-files").stdout.splitlines()


def _last_commit_paths(project: Path) -> set[str]:
    return set(_git(project, "show", "--name-status", "--format=", "HEAD").stdout.splitlines())


@pytest.fixture
def isolated_git(tmp_path, monkeypatch) -> None:
    """This machine's own git settings cannot speak for a project here."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-xdg"))


@pytest.fixture
def repo(tmp_path, isolated_git) -> Path:
    """A repository with an identity and one commit, and no link in it."""
    project = tmp_path / "car"
    project.mkdir()
    _git(project, "init", "-q", check=True)
    _git(project, "config", "user.name", "Someone", check=True)
    _git(project, "config", "user.email", "someone@example.invalid", check=True)
    (project / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (project / "notes.txt").write_text("first\n", encoding="utf-8")
    _git(project, "add", "-A", check=True)
    _git(project, "commit", "-q", "-m", "base", check=True)
    return project


def _make_link(project: Path, target: Path) -> Path:
    link = project / LINK
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    return link


@pytest.fixture
def tracked(repo, tmp_path) -> Path:
    """`repo` with the method's absolute link committed, as the first Mac left it."""
    target = tmp_path / "first-mac-copy"
    target.mkdir()
    _make_link(repo, target)
    _git(repo, "add", "-A", check=True)
    _git(repo, "commit", "-q", "-m", "with the link", check=True)
    assert LINK in _index(repo)
    return repo


def _untouched(project: Path, commits: int) -> None:
    """Git as it stood: no new commit, the link still tracked in the index and at HEAD."""
    assert _commits(project) == commits
    assert LINK in _index(project)
    assert _git(project, "cat-file", "-e", f"HEAD:{LINK}").returncode == 0


def _stage_work(project: Path) -> None:
    """Work of the person's that every failure below has to leave exactly where it was."""
    (project / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(project, "add", "staged.txt", check=True)


def _state(project: Path) -> tuple[str, str, bytes]:
    """The index, what `status` says, and `.gitignore`'s bytes."""
    ignore = project / ".gitignore"
    return (_git(project, "ls-files", "-s").stdout, _git(project, "status", "--porcelain").stdout,
            ignore.read_bytes() if ignore.is_file() else b"")


def _ready_to_fail(project: Path) -> tuple[str, str, bytes]:
    """Staged work and TCC's lines already in `.gitignore`: what a failure must not change. A run
    that was not blocked before the write adds those lines, and that is said and not undone."""
    _stage_work(project)
    mcp_key.teach_git_to_ignore(project)
    return _state(project)


def _nothing_changed(project: Path, commits: int, before: tuple[str, str, bytes]) -> None:
    _untouched(project, commits)
    assert _state(project) == before


def _diverge(project: Path, path: str = "notes.txt") -> str:
    """A branch `other` and the first branch, each changing `path` differently; on the first."""
    first = _git(project, "symbolic-ref", "--short", "HEAD", check=True).stdout.strip()
    _git(project, "checkout", "-q", "-b", "other", check=True)
    (project / path).write_text("theirs\n", encoding="utf-8")
    _git(project, "commit", "-qam", "theirs", check=True)
    _git(project, "checkout", "-q", first, check=True)
    (project / path).write_text("ours\n", encoding="utf-8")
    _git(project, "commit", "-qam", "ours", check=True)
    return first




# ---- the commit: exactly the two paths ----------------------------------------------------------


@_POSIX_ONLY
def test_a_tracked_link_leaves_git_in_one_commit_of_the_two_paths(tracked):
    before = _commits(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.COMMITTED
    assert _commits(tracked) == before + 1
    assert _last_commit_paths(tracked) == {f"D\t{LINK}", "M\t.gitignore"}
    assert LINK not in _index(tracked)
    assert (tracked / LINK).is_symlink(), "the link itself left the folder"
    assert outcome.commit == _git(tracked, "rev-parse", "--short", "HEAD").stdout.strip()
    assert _git(tracked, "status", "--porcelain").stdout == "", "the tree is not clean after it"


@_POSIX_ONLY
def test_the_commit_message_is_one_plain_english_line(tracked):
    method_link_git.keep_out(tracked)

    message = _git(tracked, "log", "-1", "--format=%B").stdout.strip()

    assert "\n" not in message and message.isascii()
    assert "TCC" in message and LINK in message


@_POSIX_ONLY
def test_what_the_person_staged_or_left_unfinished_stays_out_and_stays_as_it_was(tracked):
    """The trap: `git commit -- <paths>` takes a path back from the disk after `git rm --cached`,
    and a commit of the whole index would take the staged file along."""
    (tracked / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(tracked, "add", "staged.txt", check=True)
    (tracked / "notes.txt").write_text("first\nunfinished\n", encoding="utf-8")

    method_link_git.keep_out(tracked)

    assert _last_commit_paths(tracked) == {f"D\t{LINK}", "M\t.gitignore"}
    assert _git(tracked, "diff", "--cached", "--name-status").stdout.splitlines() == ["A\tstaged.txt"]
    assert _git(tracked, "diff", "--name-only").stdout.splitlines() == ["notes.txt"]
    assert (tracked / "notes.txt").read_text(encoding="utf-8") == "first\nunfinished\n"


@_POSIX_ONLY
def test_a_gitignore_with_the_person_s_uncommitted_edits_goes_in_whole_and_is_said(tracked):
    (tracked / ".gitignore").write_text("*.log\nmy-own-line/\n", encoding="utf-8")

    outcome = method_link_git.keep_out(tracked)

    committed = _git(tracked, "show", "HEAD:.gitignore").stdout
    assert "my-own-line/" in committed and LINK in committed
    assert "my-own-line/" in (tracked / ".gitignore").read_text(encoding="utf-8")
    assert outcome.args.get("edits") is True


@_POSIX_ONLY
def test_a_gitignore_with_only_tcc_s_lines_says_nothing_about_edits(tracked):
    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.COMMITTED and outcome.args.get("edits") is False


@_POSIX_ONLY
def test_a_gitignore_git_never_held_goes_in_with_the_link(repo, tmp_path):
    """The first start wrote `.gitignore` and nobody committed it: `git commit -- .gitignore` would
    refuse a path git does not know."""
    _git(repo, "rm", "-q", "--cached", ".gitignore", check=True)
    (repo / ".gitignore").unlink()
    _git(repo, "commit", "-q", "-m", "no ignore file", check=True)
    target = tmp_path / "elsewhere"
    target.mkdir()
    _make_link(repo, target)
    _git(repo, "add", "-A", check=True)
    _git(repo, "commit", "-q", "-m", "with the link", check=True)

    outcome = method_link_git.keep_out(repo)

    assert outcome.state == method_link_git.COMMITTED
    assert _last_commit_paths(repo) == {f"D\t{LINK}", "A\t.gitignore"}


# ---- once ---------------------------------------------------------------------------------------


@_POSIX_ONLY
def test_it_runs_once_no_second_commit_on_the_next_start(tracked):
    assert method_link_git.keep_out(tracked).state == method_link_git.COMMITTED
    after_first = _commits(tracked)

    again = method_link_git.keep_out(tracked)

    assert again.state == method_link_git.NOTHING and _commits(tracked) == after_first


# ---- the method's own commands ------------------------------------------------------------------


@_POSIX_ONLY
def test_the_link_stays_out_after_a_git_add_all(tracked):
    """`project_repo.py save` and `init` go through `git add -A`."""
    method_link_git.keep_out(tracked)
    _git(tracked, "add", "-A", check=True)

    assert LINK not in _index(tracked)


@_POSIX_ONLY
def test_the_method_s_init_leaves_the_link_out(tracked):
    if not vendor_loader.is_available():
        pytest.skip("the vendored skill is not checked out")
    method_link_git.keep_out(tracked)
    vendor_loader.load_project_seed()  # puts `rew_tool/` on `sys.path`
    repo_module = importlib.import_module("project_repo")

    ok, said = repo_module.init(str(tracked))

    assert ok, said
    assert LINK not in _index(tracked)


@_POSIX_ONLY
def test_the_ignore_line_matches_the_symlink_with_no_trailing_slash(repo, tmp_path):
    """`.claude/skills/autosound-tuning/` would match a folder only, and a symlink is not one."""
    (tmp_path / "elsewhere").mkdir()
    _make_link(repo, tmp_path / "elsewhere")

    mcp_key.teach_git_to_ignore(repo)

    assert LINK in (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert _git(repo, "check-ignore", "-q", LINK).returncode == 0


# ---- where it fires -----------------------------------------------------------------------------


@_POSIX_ONLY
def test_starting_a_session_on_a_tracked_link_takes_it_out(tracked):
    before = _commits(tracked)

    assert vendor_loader.link_skill_into(tracked) == tracked / LINK

    assert LINK not in _index(tracked)
    assert _commits(tracked) == before + 1
    assert f"D\t{LINK}" in _last_commit_paths(tracked), "a staged deletion is not a commit"


def test_making_a_link_in_a_git_project_ignores_it_with_no_commit(repo, own_copy_is_the_submodule):
    before = _commits(repo)

    assert vendor_loader.link_skill_into(repo) == repo / LINK

    assert LINK in (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert _commits(repo) == before and LINK not in _index(repo)


@_POSIX_ONLY
def test_re_linking_on_the_second_mac_takes_the_old_link_out(tracked, tmp_path, own_copy_is_the_submodule):
    """A clone holds the first Mac's link, broken here: «Re-link» is the one way out."""
    (tracked / LINK).unlink()
    (tracked / LINK).symlink_to(tmp_path / "gone", target_is_directory=True)
    before = _commits(tracked)

    method_binding.relink(method_binding.for_project(tracked))

    assert LINK not in _index(tracked)
    assert (tracked / LINK).is_symlink()
    assert _commits(tracked) == before + 1
    assert f"D\t{LINK}" in _last_commit_paths(tracked), "a staged deletion is not a commit"


def test_a_folder_with_no_git_is_left_alone(tmp_path, isolated_git):
    (tmp_path / ".claude" / "skills").mkdir(parents=True)

    outcome = method_link_git.keep_out(tmp_path)

    assert outcome.state == method_link_git.NOTHING
    assert not (tmp_path / ".gitignore").exists()


# ---- staged, never committed --------------------------------------------------------------------


@_POSIX_ONLY
def test_a_link_only_staged_is_unstaged_with_no_commit(repo, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    _make_link(repo, tmp_path / "elsewhere")
    _git(repo, "add", "-f", LINK, check=True)
    _stage_work(repo)
    before = _commits(repo)

    outcome = method_link_git.keep_out(repo)

    assert outcome.state == method_link_git.UNSTAGED
    assert _commits(repo) == before and LINK not in _index(repo)
    assert _git(repo, "diff", "--cached", "--name-status").stdout.splitlines() == ["A\tstaged.txt"]


@_POSIX_ONLY
def test_a_link_staged_before_the_first_commit_makes_no_first_commit(tmp_path, isolated_git):
    project = tmp_path / "car"
    project.mkdir()
    _git(project, "init", "-q", check=True)
    (tmp_path / "elsewhere").mkdir()
    _make_link(project, tmp_path / "elsewhere")
    _git(project, "add", "-f", LINK, check=True)
    _stage_work(project)

    outcome = method_link_git.keep_out(project)

    assert outcome.state == method_link_git.UNSTAGED
    assert LINK not in _index(project)
    assert "staged.txt" in _index(project)
    assert _git(project, "rev-parse", "-q", "--verify", "HEAD").returncode != 0


# ---- when a commit must not be made, or cannot be ------------------------------------------------


@_POSIX_ONLY
@pytest.mark.parametrize("marker, operation, is_folder", [
    ("MERGE_HEAD", "merge", False), ("CHERRY_PICK_HEAD", "cherry-pick", False),
    ("REVERT_HEAD", "revert", False), ("BISECT_LOG", "bisect", False),
    ("rebase-merge", "rebase", True), ("rebase-apply", "rebase", True),
    ("sequencer", "cherry-pick or revert", True),
])
def test_nothing_happens_while_git_is_in_the_middle_of_something(tracked, marker, operation, is_folder):
    """The real shapes: `rebase-merge`, `rebase-apply` and `sequencer` are folders."""
    commits = _commits(tracked)
    _stage_work(tracked)
    (tracked / ".gitignore").write_text("*.log\nmine/\n", encoding="utf-8")  # unstaged: `add` would show
    if is_folder:
        (tracked / ".git" / marker).mkdir()
    else:
        (tracked / ".git" / marker).write_text("", encoding="utf-8")
    before = _state(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkMidOperation"
    assert outcome.args["operation"] == operation
    _nothing_changed(tracked, commits, before)


@_POSIX_ONLY
def test_a_real_merge_conflict_is_left_alone(tracked):
    branch = _git(tracked, "symbolic-ref", "--short", "HEAD").stdout.strip()
    _git(tracked, "checkout", "-q", "-b", "other", check=True)
    (tracked / "notes.txt").write_text("theirs\n", encoding="utf-8")
    _git(tracked, "commit", "-qam", "theirs", check=True)
    _git(tracked, "checkout", "-q", branch, check=True)
    (tracked / "notes.txt").write_text("ours\n", encoding="utf-8")
    _git(tracked, "commit", "-qam", "ours", check=True)
    assert _git(tracked, "merge", "-q", "other").returncode != 0
    commits = _commits(tracked)
    before = _state(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.key == "methodLinkMidOperation" and outcome.args["operation"] == "merge"
    _nothing_changed(tracked, commits, before)
    assert (tracked / ".git" / "MERGE_HEAD").exists()


@_POSIX_ONLY
def test_a_rebase_stopped_on_a_conflict_keeps_gitignore_and_can_continue(tracked):
    """The blocker: a `.gitignore` written mid-rebase is ` M .gitignore`, and `rebase --continue` refuses."""
    first = _diverge(tracked)
    _git(tracked, "checkout", "-q", "other", check=True)
    assert _git(tracked, "rebase", first).returncode != 0
    assert (tracked / ".git" / "rebase-merge").is_dir(), "the premise"
    bytes_before = (tracked / ".gitignore").read_bytes()

    outcome = method_link_git.keep_out(tracked)

    assert outcome.key == "methodLinkMidOperation" and outcome.args["operation"] == "rebase"
    assert (tracked / ".gitignore").read_bytes() == bytes_before
    (tracked / "notes.txt").write_text("merged\n", encoding="utf-8")
    _git(tracked, "add", "notes.txt", check=True)
    continued = _git(tracked, "-c", "core.editor=true", "rebase", "--continue")
    assert continued.returncode == 0, continued.stderr
    assert not (tracked / ".git" / "rebase-merge").exists()


@_POSIX_ONLY
def test_a_merge_conflicting_on_gitignore_keeps_tcc_out_of_the_conflict(tracked):
    """TCC's block used to land after the `>>>>>>>` marker."""
    first = _diverge(tracked, ".gitignore")
    assert _git(tracked, "merge", "-q", "other").returncode != 0
    assert first and "<<<<<<<" in (tracked / ".gitignore").read_text(encoding="utf-8"), "the premise"
    bytes_before = (tracked / ".gitignore").read_bytes()

    outcome = method_link_git.keep_out(tracked)

    assert outcome.key == "methodLinkMidOperation"
    assert (tracked / ".gitignore").read_bytes() == bytes_before


@_POSIX_ONLY
def test_a_git_am_stopped_on_a_conflict_keeps_gitignore(tracked, tmp_path):
    _diverge(tracked)
    patch = _git(tracked, "format-patch", "-1", "--stdout", "other", check=True).stdout
    (tmp_path / "the.patch").write_text(patch, encoding="utf-8")
    assert _git(tracked, "am", str(tmp_path / "the.patch")).returncode != 0
    assert (tracked / ".git" / "rebase-apply").is_dir(), "the premise"
    commits = _commits(tracked)
    before = _state(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.key == "methodLinkMidOperation"
    _nothing_changed(tracked, commits, before)


@_POSIX_ONLY
def test_a_paused_multi_commit_cherry_pick_is_seen_after_a_step_is_resolved(tracked):
    """`cherry-pick A B`: with A committed by hand no `CHERRY_PICK_HEAD` is left, only `sequencer/`."""
    first = _diverge(tracked)
    _git(tracked, "checkout", "-q", "other", check=True)
    (tracked / "more.txt").write_text("more\n", encoding="utf-8")
    _git(tracked, "add", "more.txt", check=True)
    _git(tracked, "commit", "-qm", "more", check=True)
    _git(tracked, "checkout", "-q", first, check=True)
    assert _git(tracked, "cherry-pick", "other~1", "other").returncode != 0
    (tracked / "notes.txt").write_text("resolved\n", encoding="utf-8")
    _git(tracked, "add", "notes.txt", check=True)
    _git(tracked, "commit", "-qm", "resolved by hand", check=True)
    assert not (tracked / ".git" / "CHERRY_PICK_HEAD").exists(), "the premise"
    assert (tracked / ".git" / "sequencer").is_dir(), "the premise"
    commits = _commits(tracked)
    before = _state(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.key == "methodLinkMidOperation"
    _nothing_changed(tracked, commits, before)


@_POSIX_ONLY
def test_a_linked_worktree_in_a_real_merge_conflict_is_blocked(tracked, tmp_path):
    """Its `.git` is a file: only git can say where the worktree's MERGE_HEAD lives."""
    first = _diverge(tracked)
    tree = tmp_path / "second-tree"
    _git(tracked, "worktree", "add", "-q", "-b", "side", str(tree), first, check=True)
    assert _git(tree, "merge", "-q", "other").returncode != 0
    commits = _commits(tree)
    before = _state(tree)

    outcome = method_link_git.keep_out(tree)

    assert outcome.key == "methodLinkMidOperation" and outcome.args["operation"] == "merge"
    _nothing_changed(tree, commits, before)


@_POSIX_ONLY
def test_an_empty_git_folder_nested_in_a_repository_commits_nothing_in_the_parent(repo, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    car = repo / "car"
    car.mkdir()
    _make_link(car, tmp_path / "elsewhere")
    _git(repo, "add", "-A", check=True)
    _git(repo, "commit", "-q", "-m", "with a nested link", check=True)
    (car / ".git").mkdir()
    commits = _commits(repo)

    outcome = method_link_git.keep_out(car)

    assert outcome.state == method_link_git.NOTHING
    assert _commits(repo) == commits
    assert _git(repo, "log", "-1", "--format=%s").stdout.strip() == "with a nested link"


@_POSIX_ONLY
@pytest.mark.parametrize("ask", ["teach", "key"])
def test_teaching_writes_nothing_during_an_operation_for_any_caller(tracked, ask):
    first = _diverge(tracked)
    _git(tracked, "checkout", "-q", "other", check=True)
    assert _git(tracked, "rebase", first).returncode != 0
    bytes_before = (tracked / ".gitignore").read_bytes()

    if ask == "teach":
        mcp_key.teach_git_to_ignore(tracked)
    else:
        mcp_key.keep_out_of_git(tracked)

    assert (tracked / ".gitignore").read_bytes() == bytes_before


@_POSIX_ONLY
def test_writing_the_mcp_config_writes_no_ignore_line_during_an_operation(tracked):
    first = _diverge(tracked)
    _git(tracked, "checkout", "-q", "other", check=True)
    assert _git(tracked, "rebase", first).returncode != 0
    bytes_before = (tracked / ".gitignore").read_bytes()

    mcp_server.write_mcp_config(tracked, 55555, "not-a-real-key")

    assert (tracked / ".gitignore").read_bytes() == bytes_before


@_POSIX_ONLY
def test_teaching_in_a_linked_worktree_mid_merge_writes_nothing(tracked, tmp_path):
    first = _diverge(tracked)
    tree = tmp_path / "second-tree"
    _git(tracked, "worktree", "add", "-q", "-b", "side", str(tree), first, check=True)
    assert _git(tree, "merge", "-q", "other").returncode != 0
    bytes_before = (tree / ".gitignore").read_bytes()

    mcp_key.teach_git_to_ignore(tree)

    assert (tree / ".gitignore").read_bytes() == bytes_before


@_POSIX_ONLY
def test_a_detached_head_is_left_alone_and_said(tracked):
    _git(tracked, "checkout", "-q", "--detach", check=True)
    commits = _commits(tracked)
    before = _ready_to_fail(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkDetached"
    _nothing_changed(tracked, commits, before)


@_POSIX_ONLY
def test_no_git_identity_is_left_alone_and_said(tracked):
    _git(tracked, "config", "--unset", "user.name", check=True)
    _git(tracked, "config", "--unset", "user.email", check=True)
    _git(tracked, "config", "user.useConfigOnly", "true", check=True)
    commits = _commits(tracked)
    before = _ready_to_fail(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkNoIdentity"
    _nothing_changed(tracked, commits, before)


@_POSIX_ONLY
def test_a_locked_index_is_left_alone_and_said(tracked):
    commits = _commits(tracked)
    before = _ready_to_fail(tracked)
    lock = tracked / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkLocked"
    assert lock.exists(), "the lock is whoever made it's own"
    lock.unlink()
    _nothing_changed(tracked, commits, before)


def _hook(project: Path, script: str) -> None:
    hook = project / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    hook.chmod(0o755)


@_POSIX_ONLY
def test_a_pre_commit_hook_that_refuses_leaves_the_index_as_it_was_and_says_why(tracked):
    """Never `--no-verify`: the hook is the person's rule."""
    _hook(tracked, "echo 'the hook says no' >&2; exit 1")
    (tracked / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(tracked, "add", "staged.txt", check=True)
    before = _commits(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkCommitFailed"
    assert "the hook says no" in outcome.args["why"]
    _untouched(tracked, before)
    assert _git(tracked, "diff", "--cached", "--name-status").stdout.splitlines() == ["A\tstaged.txt"]


@_POSIX_ONLY
def test_a_pre_commit_hook_runs_on_the_commit_tcc_makes(tracked):
    marker = tracked.parent / "the-hook-ran"
    _hook(tracked, f"touch '{marker}'")

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.COMMITTED and marker.exists()


@_POSIX_ONLY
def test_a_git_that_does_not_answer_leaves_the_index_as_it_was(tracked, monkeypatch):
    real = child.run_bounded

    def stuck(args, **kwargs):
        if "commit" in args:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return real(args, **kwargs)

    monkeypatch.setattr(method_link_git.child, "run_bounded", stuck)
    commits = _commits(tracked)
    before = _ready_to_fail(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkTimedOut"
    _nothing_changed(tracked, commits, before)


@_POSIX_ONLY
def test_a_commit_landing_meanwhile_stops_it_rather_than_undoing_that_commit(tracked, monkeypatch):
    """The tree comes from HEAD as it was read; a commit on an older tree would undo a newer one."""
    real = child.run_bounded
    landed: list[tuple[str, str, bytes]] = []

    def elsewhere_commits(args, **kwargs):
        if "add" in args and not landed:
            (tracked / "theirs.txt").write_text("theirs\n", encoding="utf-8")
            _git(tracked, "add", "theirs.txt", check=True)
            _git(tracked, "commit", "-q", "-m", "someone else", check=True)
            landed.append(_state(tracked))
        return real(args, **kwargs)

    _ready_to_fail(tracked)
    monkeypatch.setattr(method_link_git.child, "run_bounded", elsewhere_commits)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkHeadMoved"
    assert _git(tracked, "log", "-1", "--format=%s").stdout.strip() == "someone else"
    assert "theirs.txt" in _index(tracked) and LINK in _index(tracked)
    assert _state(tracked) == landed[0], "what the other commit left is not TCC's to change"


@_NOT_ROOT
def test_a_gitignore_that_cannot_take_the_line_leaves_the_link_tracked(tracked):
    """Taken out of the index with nothing ignoring it, the next `git add -A` would put it back."""
    commits = _commits(tracked)
    _stage_work(tracked)
    (tracked / ".gitignore").chmod(0o444)
    before = _state(tracked)
    try:
        outcome = method_link_git.keep_out(tracked)
    finally:
        (tracked / ".gitignore").chmod(0o644)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkNotIgnored"
    _nothing_changed(tracked, commits, before)


# ---- what is at the link's place is not the link --------------------------------------------------


def _tracked_files(repo: Path) -> None:
    copy = repo / LINK
    copy.mkdir(parents=True)
    (copy / "SKILL.md").write_text("an old copy\n", encoding="utf-8")
    (copy / "extra.md").write_text("more\n", encoding="utf-8")
    _git(repo, "add", "-A", check=True)
    _git(repo, "commit", "-q", "-m", "a real copy", check=True)


def test_a_tracked_real_copy_of_the_skill_is_left_tracked_and_said(repo):
    _tracked_files(repo)
    before = _commits(repo)

    outcome = method_link_git.keep_out(repo)

    assert outcome.state == method_link_git.LEFT_ALONE and outcome.key == "methodLinkFilesFound"
    assert _commits(repo) == before
    assert f"{LINK}/SKILL.md" in _index(repo)
    assert (repo / LINK / "SKILL.md").is_file()


def test_a_regular_file_tracked_at_the_link_s_place_is_left_tracked_and_said(repo):
    (repo / LINK).parent.mkdir(parents=True)
    (repo / LINK).write_text("not a link\n", encoding="utf-8")
    _git(repo, "add", "-A", check=True)
    _git(repo, "commit", "-q", "-m", "a plain file", check=True)
    before = _commits(repo)

    outcome = method_link_git.keep_out(repo)

    assert outcome.state == method_link_git.LEFT_ALONE and _commits(repo) == before
    assert LINK in _index(repo)


def test_a_windows_junction_git_read_as_a_folder_comes_out_whole(repo, monkeypatch):
    _tracked_files(repo)
    monkeypatch.setattr(method_link_git, "_is_junction", lambda path: True)

    outcome = method_link_git.keep_out(repo)

    assert outcome.state == method_link_git.COMMITTED
    assert _last_commit_paths(repo) == {f"D\t{LINK}/SKILL.md", f"D\t{LINK}/extra.md", "M\t.gitignore"}
    assert not [path for path in _index(repo) if path.startswith(LINK)]
    assert (repo / LINK / "SKILL.md").is_file(), "the folder behind the junction was touched"


# ---- what the person is told --------------------------------------------------------------------


@pytest.fixture
def words(monkeypatch):
    """The window's table, as `diagnostics_panel` hands it in."""
    monkeypatch.setattr(self_check, "_translate", i18n.t)


@_POSIX_ONLY
def test_the_commit_is_told_with_its_hash_and_that_nothing_was_pushed(tracked, words, app_log_told):
    outcome = method_link_git.keep_out(tracked)

    assert len(app_log_told.warned) == 1
    told = app_log_told.warned[0]
    assert outcome.commit in told and LINK in told and "push" in told.lower()


@_POSIX_ONLY
def test_edits_of_the_gitignore_are_named_in_what_is_told(tracked, words, app_log_told):
    (tracked / ".gitignore").write_text("*.log\nmy-own-line/\n", encoding="utf-8")

    method_link_git.keep_out(tracked)

    assert ".gitignore" in app_log_told.warned[0]
    assert i18n.t("methodLinkCommittedEdits") in app_log_told.warned[0]


@_POSIX_ONLY
def test_a_blocked_link_is_told_once_per_run_and_tried_again(tracked, words, app_log_told):
    _git(tracked, "checkout", "-q", "--detach", check=True)

    first = method_link_git.keep_out(tracked)
    second = method_link_git.keep_out(tracked)

    assert first.key == second.key == "methodLinkDetached"
    assert len(app_log_told.warned) == 1
    assert "detached" in app_log_told.warned[0].lower()


def test_a_found_copy_is_told_once_per_run(repo, words, app_log_told):
    _tracked_files(repo)

    method_link_git.keep_out(repo)
    method_link_git.keep_out(repo)

    assert len(app_log_told.warned) == 1
    assert LINK in app_log_told.warned[0]


def test_no_tracked_link_says_nothing(repo, words, app_log_told):
    method_link_git.keep_out(repo)

    assert app_log_told.warned == []


# ---- a hook, an upstream, a CRLF, a relative link, an inherited GIT_DIR ----------------------------


@_POSIX_ONLY
def test_a_hook_that_widens_the_commit_is_said_with_the_hash_and_the_list(tracked, words, app_log_told):
    """`git add .` under the inherited `GIT_INDEX_FILE`. Not undone: it is the person's hook."""
    (tracked / "unfinished.txt").write_text("not ready\n", encoding="utf-8")
    _hook(tracked, "git add .")

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.COMMITTED
    assert _last_commit_paths(tracked) == {f"D\t{LINK}", "M\t.gitignore", "A\tunfinished.txt"}
    told = app_log_told.warned[0]
    assert outcome.commit in told and "unfinished.txt" in told


@_POSIX_ONLY
def test_a_commit_of_exactly_our_two_paths_names_nothing_extra(tracked, words, app_log_told):
    outcome = method_link_git.keep_out(tracked)

    assert outcome.args["widened"] == ""
    assert i18n.t("methodLinkCommitWidened").split("{")[0].strip() not in app_log_told.warned[0]


@_POSIX_ONLY
def test_nothing_is_pushed(tracked, tmp_path):
    bare = tmp_path / "upstream.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    _git(tracked, "remote", "add", "origin", str(bare), check=True)
    branch = _git(tracked, "symbolic-ref", "--short", "HEAD", check=True).stdout.strip()
    _git(tracked, "push", "-q", "-u", "origin", branch, check=True)
    remote = subprocess.run(["git", "-C", str(bare), "rev-parse", branch], capture_output=True, text=True,
                            check=True).stdout.strip()

    assert method_link_git.keep_out(tracked).state == method_link_git.COMMITTED

    assert subprocess.run(["git", "-C", str(bare), "rev-parse", branch], capture_output=True, text=True,
                          check=True).stdout.strip() == remote


@_POSIX_ONLY
def test_a_crlf_gitignore_keeps_its_line_endings_and_the_block_uses_them(tracked):
    (tracked / ".gitignore").write_bytes(b"*.log\r\nmine/\r\n")

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.COMMITTED
    written = (tracked / ".gitignore").read_bytes()
    assert b"*.log\r\nmine/\r\n" in written and written.count(b"\n") == written.count(b"\r\n")
    assert b"\r\n.claude/skills/autosound-tuning\r\n" in written


def test_teaching_keeps_a_crlf_file_s_endings_outside_any_git(tmp_path):
    (tmp_path / ".gitignore").write_bytes(b"*.log\r\n")

    mcp_key.teach_git_to_ignore(tmp_path)

    written = (tmp_path / ".gitignore").read_bytes()
    assert written.startswith(b"*.log\r\n") and written.count(b"\n") == written.count(b"\r\n")


@_POSIX_ONLY
def test_a_relative_link_is_left_alone(repo):
    """The decision is about the absolute link that breaks a clone; `link_skill_into` promises an
    existing entry is left alone whatever it points at."""
    link = repo / LINK
    link.parent.mkdir(parents=True)
    link.symlink_to("../../my-copy", target_is_directory=True)
    _git(repo, "add", "-A", check=True)
    _git(repo, "commit", "-q", "-m", "a relative link", check=True)
    before = _commits(repo)

    outcome = method_link_git.keep_out(repo)

    assert outcome.state == method_link_git.LEFT_ALONE and outcome.key == ""
    assert _commits(repo) == before and LINK in _index(repo)


@_POSIX_ONLY
def test_an_inherited_git_dir_speaks_for_no_project(tracked, tmp_path, monkeypatch):
    """TCC started from a hook, or an editor's terminal, inherits another repository's git dir."""
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", check=True)
    index_elsewhere = tmp_path / "index-elsewhere"
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(index_elsewhere))
    before = _git(tracked, "--git-dir", str(tracked / ".git"), "--work-tree", str(tracked),
                  "rev-list", "--count", "HEAD").stdout.strip()

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.COMMITTED
    assert _git(tracked, "--git-dir", str(tracked / ".git"), "--work-tree", str(tracked),
                "rev-list", "--count", "HEAD").stdout.strip() == str(int(before) + 1)
    assert not index_elsewhere.exists()


def test_the_key_s_question_is_not_answered_by_an_inherited_git_dir(repo, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", check=True)
    (other / ".mcp.json").write_text("{}", encoding="utf-8")
    _git(other, "add", ".mcp.json", check=True)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))

    mcp_key.teach_git_to_ignore(repo)
    problem = mcp_key._git_would_take_it(repo)

    assert problem == "", "another repository's answer was taken for this project's"


# ---- git's exit codes, read strictly ----------------------------------------------------------------


_SITES = {
    "ls-files": ("ls-files",),
    "where": ("--show-cdup",),
    "check-ignore": ("check-ignore",),
    "head": ("--verify",),
    "ls-tree": ("ls-tree",),
    "symbolic-ref": ("symbolic-ref",),
    "identity": ("var",),
    "show": ("show",),
}


@_POSIX_ONLY
@pytest.mark.parametrize("site", _SITES, ids=list(_SITES))
def test_an_exit_code_that_is_not_the_expected_one_is_git_not_answering(tracked, monkeypatch, site, app_log_heard):
    words = _SITES[site]
    real = child.run_bounded

    def speaks_nonsense(args, **kwargs):
        if all(word in args for word in words):
            return subprocess.CompletedProcess(args, 2, "", "nonsense")
        return real(args, **kwargs)

    commits = _commits(tracked)
    before = _ready_to_fail(tracked)
    monkeypatch.setattr(method_link_git.child, "run_bounded", speaks_nonsense)

    heard = app_log_heard(logging.INFO)
    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.NOTHING and outcome.key == ""
    _nothing_changed(tracked, commits, before)
    assert sum("did not answer" in record.getMessage() for record in heard) == 1, [r.getMessage() for r in heard]


@_POSIX_ONLY
def test_a_commit_s_hash_git_cannot_read_still_reads_committed(tracked, monkeypatch, words, app_log_told):
    real = child.run_bounded

    def no_hash(args, **kwargs):
        if "--short" in args:
            return subprocess.CompletedProcess(args, 128, "", "nonsense")
        return real(args, **kwargs)

    monkeypatch.setattr(method_link_git.child, "run_bounded", no_hash)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.COMMITTED
    assert "HEAD" in app_log_told.warned[0]


# ---- what happens after the commit lands -----------------------------------------------------------


@_POSIX_ONLY
def test_a_foreign_lock_after_the_commit_is_said_and_the_next_start_heals_both_paths(
        tracked, monkeypatch, words, app_log_told):
    """The real index keeps the old `.gitignore`; left alone, the next commit reverts it."""
    real = child.run_bounded

    def locks_after_commit(args, **kwargs):
        out = real(args, **kwargs)
        if "commit" in args and out.returncode == 0:
            (tracked / ".git" / "index.lock").write_text("", encoding="utf-8")
        return out

    monkeypatch.setattr(method_link_git.child, "run_bounded", locks_after_commit)

    outcome = method_link_git.keep_out(tracked)
    monkeypatch.undo()

    assert outcome.state == method_link_git.COMMITTED and outcome.args["behind"]
    told = app_log_told.warned[0]
    assert ".gitignore" in told and "git reset" in told
    assert "never committed" not in told and "as they were" not in told

    (tracked / ".git" / "index.lock").unlink()
    app_log_told.warned.clear()
    again = method_link_git.keep_out(tracked)

    assert again.state == method_link_git.UNSTAGED
    assert _git(tracked, "status", "--porcelain").stdout == "", "the next commit would revert .gitignore"


@_POSIX_ONLY
def test_a_staged_gitignore_edit_after_our_commit_is_kept_by_the_next_start(tracked, tmp_path):
    """Only a real index that TCC's commit left behind is reset, not whatever was staged since."""
    method_link_git.keep_out(tracked)
    (tmp_path / "elsewhere").mkdir()
    link = tracked / LINK
    _git(tracked, "add", "-f", LINK, check=True)
    assert link.is_symlink() and LINK in _index(tracked)
    (tracked / ".gitignore").write_text("*.log\n" + (tracked / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8")
    _git(tracked, "add", ".gitignore", check=True)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.UNSTAGED
    assert _git(tracked, "diff", "--cached", "--name-only").stdout.splitlines() == [".gitignore"]


@_POSIX_ONLY
def test_the_follow_timing_out_after_the_commit_reads_committed(tracked, monkeypatch, words, app_log_told):
    real = child.run_bounded
    landed = []

    def stuck_after(args, **kwargs):
        if landed and ("reset" in args or "rm" in args):
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        out = real(args, **kwargs)
        if "commit" in args and out.returncode == 0:
            landed.append(True)
        return out

    monkeypatch.setattr(method_link_git.child, "run_bounded", stuck_after)
    before = _commits(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.COMMITTED
    assert _commits(tracked) == before + 1
    told = app_log_told.warned[0]
    assert "never committed" not in told and "as they were" not in told


@_POSIX_ONLY
def test_git_has_one_bound_for_the_whole_run(tracked, monkeypatch):
    """The first bound is what the GUI's «Re-link» waits for; no second one may follow it."""
    real = child.run_bounded
    allowed: list[float] = []

    def noting(args, **kwargs):
        allowed.append(kwargs["timeout"])
        return real(args, **kwargs)

    monkeypatch.setattr(method_link_git.child, "run_bounded", noting)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.COMMITTED
    assert allowed == sorted(allowed, reverse=True), "a later command got more time than an earlier one"


# ---- the words -------------------------------------------------------------------------------------


@_POSIX_ONLY
@pytest.mark.parametrize("command", ["read-tree", "rm", "add"])
def test_a_step_before_the_commit_failing_does_not_say_a_commit_was_refused(tracked, monkeypatch, command, words,
                                                                            app_log_told):
    real = child.run_bounded

    def fails(args, **kwargs):
        if command in args and kwargs.get("env", {}).get("GIT_INDEX_FILE"):
            return subprocess.CompletedProcess(args, 128, "", "fatal: nope")
        return real(args, **kwargs)

    monkeypatch.setattr(method_link_git.child, "run_bounded", fails)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.key == "methodLinkNotTried"
    assert "refused the commit" not in app_log_told.warned[0]


@_POSIX_ONLY
def test_unstaging_that_git_refuses_does_not_say_a_commit_was_refused(repo, tmp_path, monkeypatch, words, app_log_told):
    (tmp_path / "elsewhere").mkdir()
    _make_link(repo, tmp_path / "elsewhere")
    _git(repo, "add", "-f", LINK, check=True)
    real = child.run_bounded

    def refuses(args, **kwargs):
        if "rm" in args:
            return subprocess.CompletedProcess(args, 128, "", "fatal: nope")
        return real(args, **kwargs)

    monkeypatch.setattr(method_link_git.child, "run_bounded", refuses)

    outcome = method_link_git.keep_out(repo)

    assert outcome.key == "methodLinkNotTried" and "refused the commit" not in app_log_told.warned[0]


def test_a_head_that_moved_does_not_claim_nothing_changed():
    """`.gitignore` was written by then."""
    assert "changed nothing" not in i18n.t("methodLinkHeadMoved")


def test_an_unstaged_link_does_not_claim_it_was_never_committed():
    """The next start after a failed follow reads this too: TCC's own commit holds its removal."""
    assert "never committed" not in i18n.t("methodLinkUnstaged")


# ---- edits named -------------------------------------------------------------------------------------


@_POSIX_ONLY
def test_lines_the_person_removed_from_gitignore_are_named_too(tracked):
    (tracked / ".gitignore").write_text("", encoding="utf-8")

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.COMMITTED and outcome.args.get("edits") is True


@_POSIX_ONLY
def test_a_gitignore_git_never_held_with_the_person_s_lines_is_named(repo, tmp_path):
    _git(repo, "rm", "-q", "--cached", ".gitignore", check=True)
    _git(repo, "commit", "-q", "-m", "no ignore file", check=True)
    (tmp_path / "elsewhere").mkdir()
    _make_link(repo, tmp_path / "elsewhere")
    _git(repo, "add", "-f", LINK, check=True)
    _git(repo, "commit", "-q", "-m", "with the link", check=True)
    (repo / ".gitignore").write_text("my-rule/\n", encoding="utf-8")

    outcome = method_link_git.keep_out(repo)

    assert outcome.state == method_link_git.COMMITTED and outcome.args.get("edits") is True


# ---- never raises, and the link is made whatever git does ---------------------------------------------


@_POSIX_ONLY
def test_a_temp_folder_git_cannot_have_is_said_and_raises_nothing(tracked, monkeypatch, words, app_log_told):
    def no_room(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(method_link_git.tempfile, "TemporaryDirectory", no_room)
    commits = _commits(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkNotTried"
    assert _commits(tracked) == commits and app_log_told.warned


@_POSIX_ONLY
def test_a_sentence_that_cannot_be_built_raises_nothing(tracked, monkeypatch):
    def broken(_key):
        raise KeyError("no such sentence")

    monkeypatch.setattr(self_check, "translated", broken)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.COMMITTED


def test_git_trouble_never_stops_the_link_being_made(tmp_path, monkeypatch, own_copy_is_the_submodule):
    def trouble(_project):
        raise RuntimeError("git went away")

    monkeypatch.setattr(vendor_loader.method_link_git, "keep_out", trouble)

    assert vendor_loader.link_skill_into(tmp_path) == tmp_path / ".claude" / "skills" / "autosound-tuning"
