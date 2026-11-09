"""The method's link stays out of the project's git (#255; the Arbiter's decision, 2026-11-09).

`.claude/skills/autosound-tuning` is an absolute link to this computer's copy of the method
(`vendor_loader.link_skill_into`). Tracked by git, it reaches a clone on a second Mac as the first
Mac's link. So the link joins TCC's `.gitignore` lines (`mcp_key._IGNORE_LINES`), and one git still
tracks is taken out of the index and committed, by TCC, once.

* **Exactly two paths.** The link's removal and `.gitignore`. The commit is built on a temporary index
  made from HEAD, because `git commit -- <path>` takes a path removed with `git rm --cached` back
  from the disk while the link is still there. What the person staged or left unfinished is not in
  the temporary index, and the real index is touched only after the commit has landed, so there is
  nothing to undo when it does not.
* **`.gitignore` goes in whole.** Uncommitted edits of the person's in it are committed with it, kept
  on disk as they were, and named in what TCC says (`Outcome.args["edits"]`).
* **Hooks run.** Never `--no-verify`: a hook that refuses is the person's rule, and TCC says what to
  do instead.
* **Keyed to the link, not to the `.gitignore` write.** It asks git each time: with no tracked link
  there is nothing to do, so there is no empty commit and no second one.
* **Nothing during a merge, rebase, cherry-pick, revert or bisect**, nothing on a detached HEAD,
  nothing without a git identity, nothing while the index is locked: each is told in words.
* **Not the link, not touched.** Files tracked at the link's place are an old real copy of the method
  and are said, not removed. A Windows junction is the exception: it IS the link, and git reads
  it as a folder of files.
* **Nothing is pushed.**

Runs where the link is made: on a session's worker thread, and on the GUI thread for «Re-link»,
which waits for at most `_GIT_WAIT_S`, once. Told on the strip; what stays unsolved is told once per
run and tried again at the next session start. Qt-free.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from autosound_tcc.core import app_log, child, mcp_key, method_binding

#: The link as git names it: forward slashes on every system.
LINK = ".claude/skills/autosound-tuning"

_IGNORE_FILE = ".gitignore"

#: Goes into the person's own repository.
_MESSAGE = f"TCC: stop tracking the method link {LINK} (it points at one computer's folder)"

#: How long git gets, all its commands together. A hook counts: one slower than this is said.
_GIT_WAIT_S = 10.0

_SYMLINK_MODE = "120000"

#: What git leaves in its folder while it is in the middle of something.
_OPERATIONS = (("MERGE_HEAD", "merge"), ("rebase-merge", "rebase"), ("rebase-apply", "rebase"),
               ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"), ("BISECT_LOG", "bisect"))

NOTHING = "nothing"  # no tracked link, no repository, or git could not say
COMMITTED = "committed"
UNSTAGED = "unstaged"  # staged only and never committed: out of the index, no commit needed
LEFT_ALONE = "left_alone"  # what git tracks at the link's place is not the link
BLOCKED = "blocked"  # a tracked link, and no commit could be made now

_TOLD: set[tuple[str, str, str]] = set()
_TOLD_LOCK = threading.Lock()


@dataclass(frozen=True)
class Outcome:
    state: str = NOTHING
    key: str = ""  # the sentence's key in the window's table; "" says nothing
    args: dict = field(default_factory=dict)
    commit: str = ""


def keep_out(project_dir: Path) -> Outcome:
    """Make sure git does not carry this project's link. Never raises: a session still starts."""
    project = Path(project_dir)
    try:
        outcome = _take_out(project)
    except subprocess.TimeoutExpired:
        outcome = _blocked("methodLinkTimedOut")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        outcome = _blocked("methodLinkCommitFailed", why=mcp_key.in_words(exc))
    _say(project, outcome)
    return outcome


def _blocked(key: str, **args) -> Outcome:
    return Outcome(BLOCKED, key, {"path": LINK, **args})


class _Git:
    """Git in the project, every command inside one bound (`mcp_key`'s way)."""

    def __init__(self, project: Path) -> None:
        self._project = project
        self._give_up = time.monotonic() + _GIT_WAIT_S

    def __call__(self, *command: str, env: dict | None = None) -> subprocess.CompletedProcess:
        extra = {"env": env} if env is not None else {}
        return child.run_bounded(["git", "-C", str(self._project), *command],
                                 timeout=max(0.0, self._give_up - time.monotonic()), text=True,
                                 encoding="utf-8", errors="replace", **extra, **child.quiet())


def _take_out(project: Path) -> Outcome:
    if not os.path.lexists(project / ".git"):
        return Outcome()
    mcp_key.teach_git_to_ignore(project)
    git = _Git(project)
    try:
        listed = git("ls-files", "-s", "-z", "--", LINK)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        app_log.logger().info("git could not say whether it tracks %s in %s: %s", LINK, project,
                              mcp_key.in_words(exc))
        return Outcome()
    entries = [line.split("\t", 1) for line in listed.stdout.split("\0") if "\t" in line]
    if listed.returncode != 0 or not entries:
        return Outcome()
    if not _is_the_link(entries, project):
        app_log.logger().info("git tracks files at %s in %s: not the link, left tracked", LINK, project)
        return Outcome(LEFT_ALONE, "methodLinkFilesFound", {"path": LINK})
    return _untrack(project, git)


def _is_the_link(entries: list[list[str]], project: Path) -> bool:
    """A link git holds as one, or a junction, whose files git holds as a folder's."""
    if all(path == LINK and meta.split(" ")[0] == _SYMLINK_MODE for meta, path in entries):
        return True
    return all(path.startswith(f"{LINK}/") for _, path in entries) and _is_junction(project / LINK)


def _is_junction(path: Path) -> bool:
    """`os.path.isjunction` is from Python 3.12; `is_symlink` says False for a junction."""
    if not sys.platform.startswith("win") or path.is_symlink():
        return False
    return method_binding._is_link(path, os.path.realpath(path), os.path.realpath(path.parent))


def _untrack(project: Path, git: _Git) -> Outcome:
    top = git("rev-parse", "--show-cdup", "--absolute-git-dir")
    lines = top.stdout.splitlines()
    if top.returncode != 0 or len(lines) != 2 or lines[0]:
        return Outcome()  # a broken `.git`: git answered for some repository above this folder
    git_dir = Path(lines[1])
    for marker, operation in _OPERATIONS:
        if (git_dir / marker).exists():
            return _blocked("methodLinkMidOperation", operation=operation)
    lock = git_dir / "index.lock"
    if lock.exists():
        return _blocked("methodLinkLocked", lock=str(lock))
    if git("check-ignore", "-q", "--no-index", "--", LINK).returncode != 0:
        return _blocked("methodLinkNotIgnored")  # out of the index, `add -A` would put it back
    head = _head(git)
    if not head or not git("ls-tree", "--name-only", "-z", head, "--", LINK).stdout:
        return _unstage(git)
    if git("symbolic-ref", "-q", "HEAD").returncode != 0:
        return _blocked("methodLinkDetached")
    if any(git("var", who).returncode != 0 for who in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT")):
        return _blocked("methodLinkNoIdentity")
    edits = _person_edited(git, project)
    refused = _commit(git, head)
    if refused is not None:
        return refused
    return Outcome(COMMITTED, "methodLinkCommitted",
                   {"path": LINK, "edits": edits, "commit": (short := _follow_in_index(project))},
                   commit=short)


def _head(git: _Git) -> str:
    found = git("rev-parse", "-q", "--verify", "HEAD")
    return found.stdout.strip() if found.returncode == 0 else ""


def _forget_link() -> tuple[str, ...]:
    return ("rm", "-r", "--cached", "-f", "-q", "--", LINK)


def _unstage(git: _Git) -> Outcome:
    """Staged and never committed (or no first commit yet): history holds no link to remove."""
    done = git(*_forget_link())
    if done.returncode != 0:
        return _blocked("methodLinkCommitFailed", why=_said(done))
    return Outcome(UNSTAGED, "methodLinkUnstaged", {"path": LINK})


def _commit(git: _Git, head: str) -> Outcome | None:
    """The commit, on an index of its own: None when it landed, else what stopped it. The real index
    is not touched here, so every way out leaves it as the person had it."""
    with tempfile.TemporaryDirectory(prefix="tcc-index-", ignore_cleanup_errors=True) as temp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(temp) / "index")}
        for step in (("read-tree", head), _forget_link(), ("add", "-f", "--", _IGNORE_FILE)):
            done = git(*step, env=env)
            if done.returncode != 0:
                return _blocked("methodLinkCommitFailed", why=_said(done))
        if _head(git) != head:  # a commit on the tree read before it would undo that commit
            return _blocked("methodLinkHeadMoved")
        made = git("commit", "-q", "-m", _MESSAGE, env=env)
        if made.returncode != 0:
            return _blocked("methodLinkCommitFailed", why=_said(made))
    return None


def _follow_in_index(project: Path) -> str:
    """The commit has landed: the real index catches up, and the new commit's short hash. A bound of
    its own, so that a commit which used up the first cannot read as one that did not land. A
    failure here heals itself: the next start finds the link staged only, and unstages it."""
    git = _Git(project)
    try:
        for step in (_forget_link(), ("add", "-f", "--", _IGNORE_FILE)):
            done = git(*step)
            if done.returncode != 0:
                app_log.logger().warning("the real index did not follow TCC's commit in %s: %s",
                                         project, _said(done))
        return git("rev-parse", "--short", "HEAD").stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        app_log.logger().warning("the real index did not follow TCC's commit in %s: %s", project,
                                 mcp_key.in_words(exc))
        return ""


def _person_edited(git: _Git, project: Path) -> bool:
    """Whether `.gitignore` differs from HEAD by more than TCC's own lines."""
    shown = git("show", f"HEAD:{_IGNORE_FILE}")
    committed = set(shown.stdout.splitlines()) if shown.returncode == 0 else set()
    try:
        disk = set((project / _IGNORE_FILE).read_text(encoding="utf-8").splitlines())
    except (OSError, ValueError):
        return False
    ours = {*mcp_key._IGNORE_LINES, ""}
    return any(line.strip() not in ours and not line.startswith("# TCC:") for line in committed ^ disk)


def _said(done: subprocess.CompletedProcess) -> str:
    """What git said, in one line and no longer than a sentence can carry."""
    return " ".join(((done.stderr or "") + " " + (done.stdout or "")).split())[-300:] or "no reason given"


def _say(project: Path, outcome: Outcome) -> None:
    """On the strip, once per run for what stays the same: a commit is its own news (its hash)."""
    if not outcome.key:
        return
    mark = (str(project), outcome.key, outcome.commit)
    with _TOLD_LOCK:
        if mark in _TOLD:
            return
        _TOLD.add(mark)
    from autosound_tcc.core import self_check  # its translator is the window's (`use_translator`)

    text = self_check.translated(outcome.key).format(**outcome.args)
    if outcome.args.get("edits"):
        text += " " + self_check.translated("methodLinkCommittedEdits")
    app_log.warn(text)
