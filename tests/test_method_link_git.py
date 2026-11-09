"""The method's link stays out of the project's git (#255).

`.claude/skills/autosound-tuning` is an absolute link to one machine's folder. Once git carried it, a
clone on a second Mac opened with the first Mac's method. The Arbiter's decision (2026-11-09): TCC
ignores the link, takes a tracked one out of the index once, and commits exactly that itself.

Every test runs a real git in `tmp_path` and reads what landed in the index and in `git log`. A POSIX
symlink stands for the link; a Windows junction, which git reads as a folder, is patched in.
"""

from __future__ import annotations

import importlib
import os
import subprocess
from pathlib import Path

import pytest

from autosound_tcc.core import child, mcp_key, method_binding, method_link_git, self_check, vendor_loader
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
    assert vendor_loader.link_skill_into(tracked) == tracked / LINK

    assert LINK not in _index(tracked)


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

    method_binding.relink(method_binding.for_project(tracked))

    assert LINK not in _index(tracked)
    assert (tracked / LINK).is_symlink()


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
    before = _commits(repo)

    outcome = method_link_git.keep_out(repo)

    assert outcome.state == method_link_git.UNSTAGED
    assert _commits(repo) == before and LINK not in _index(repo)


@_POSIX_ONLY
def test_a_link_staged_before_the_first_commit_makes_no_first_commit(tmp_path, isolated_git):
    project = tmp_path / "car"
    project.mkdir()
    _git(project, "init", "-q", check=True)
    (tmp_path / "elsewhere").mkdir()
    _make_link(project, tmp_path / "elsewhere")
    _git(project, "add", "-f", LINK, check=True)

    outcome = method_link_git.keep_out(project)

    assert outcome.state == method_link_git.UNSTAGED
    assert LINK not in _index(project)
    assert _git(project, "rev-parse", "-q", "--verify", "HEAD").returncode != 0


# ---- when a commit must not be made, or cannot be ------------------------------------------------


@_POSIX_ONLY
@pytest.mark.parametrize("marker, operation", [
    ("MERGE_HEAD", "merge"), ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"),
    ("BISECT_LOG", "bisect"), ("rebase-merge", "rebase"), ("rebase-apply", "rebase"),
])
def test_nothing_happens_while_git_is_in_the_middle_of_something(tracked, marker, operation):
    before = _commits(tracked)
    (tracked / ".git" / marker).write_text("", encoding="utf-8")

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkMidOperation"
    assert outcome.args["operation"] == operation
    _untouched(tracked, before)


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
    before = _commits(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.key == "methodLinkMidOperation" and outcome.args["operation"] == "merge"
    _untouched(tracked, before)
    assert (tracked / ".git" / "MERGE_HEAD").exists()


@_POSIX_ONLY
def test_a_detached_head_is_left_alone_and_said(tracked):
    _git(tracked, "checkout", "-q", "--detach", check=True)
    before = _commits(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkDetached"
    _untouched(tracked, before)


@_POSIX_ONLY
def test_no_git_identity_is_left_alone_and_said(tracked):
    _git(tracked, "config", "--unset", "user.name", check=True)
    _git(tracked, "config", "--unset", "user.email", check=True)
    _git(tracked, "config", "user.useConfigOnly", "true", check=True)
    before = _commits(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkNoIdentity"
    _untouched(tracked, before)


@_POSIX_ONLY
def test_a_locked_index_is_left_alone_and_said(tracked):
    (tracked / ".git" / "index.lock").write_text("", encoding="utf-8")
    before = _commits(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkLocked"
    _untouched(tracked, before)


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
    before = _commits(tracked)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkTimedOut"
    _untouched(tracked, before)


@_POSIX_ONLY
def test_a_commit_landing_meanwhile_stops_it_rather_than_undoing_that_commit(tracked, monkeypatch):
    """The tree comes from HEAD as it was read; a commit on an older tree would undo a newer one."""
    real = child.run_bounded
    done = []

    def elsewhere_commits(args, **kwargs):
        if "add" in args and not done:
            done.append(True)
            (tracked / "theirs.txt").write_text("theirs\n", encoding="utf-8")
            _git(tracked, "add", "theirs.txt", check=True)
            _git(tracked, "commit", "-q", "-m", "someone else", check=True)
        return real(args, **kwargs)

    monkeypatch.setattr(method_link_git.child, "run_bounded", elsewhere_commits)

    outcome = method_link_git.keep_out(tracked)

    assert outcome.state == method_link_git.BLOCKED
    assert _git(tracked, "log", "-1", "--format=%s").stdout.strip() == "someone else"
    assert "theirs.txt" in _index(tracked) and LINK in _index(tracked)


@_NOT_ROOT
def test_a_gitignore_that_cannot_take_the_line_leaves_the_link_tracked(tracked):
    """Taken out of the index with nothing ignoring it, the next `git add -A` would put it back."""
    (tracked / ".gitignore").chmod(0o444)
    before = _commits(tracked)
    try:
        outcome = method_link_git.keep_out(tracked)
    finally:
        (tracked / ".gitignore").chmod(0o644)

    assert outcome.state == method_link_git.BLOCKED and outcome.key == "methodLinkNotIgnored"
    _untouched(tracked, before)


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
