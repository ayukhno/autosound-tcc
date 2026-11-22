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
  do instead. A hook that widens the commit (`git add .` under the temporary index) is said with the
  hash and the list, and not undone (`Outcome.args["widened"]`).
* **Keyed to the link, not to the `.gitignore` write.** It asks git each time: with no tracked link
  there is nothing to do, so there is no empty commit and no second one.
* **Nothing during a merge, rebase, cherry-pick, revert or bisect**, `.gitignore` included
  (`mcp_key.teach_git_to_ignore`), nothing on a detached HEAD, nothing without a git identity, nothing
  while the index is locked: each is told in words.
* **Git's exit codes are read strictly.** Only the expected code is an answer; anything else is git
  not answering, which does nothing and logs one line.
* **Not the link, not touched.** Files tracked at the link's place are an old real copy of the method
  and are said, not removed. A Windows junction is the exception: it IS the link, and git reads
  it as a folder of files.
* **Nothing is pushed.**

* **A relative link is left alone.** The decision is about the absolute link that breaks a clone;
  `link_skill_into` promises any other entry stays as it is.

Runs where the link is made: on a session's worker thread, and on the GUI thread for «Re-link»,
which waits for at most `_GIT_WAIT_S`, once: one bound for the whole run, the commit's hook and what
follows it included. Told on the strip; what stays unsolved is told once per
run and tried again at the next session start. Qt-free.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
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

NOTHING = "nothing"  # no tracked link, no repository, or git did not answer
COMMITTED = "committed"
UNSTAGED = "unstaged"  # staged only: out of the index, no commit needed
LEFT_ALONE = "left_alone"  # what git tracks at the link's place is not the absolute link
BLOCKED = "blocked"  # a tracked link, and no commit could be made now

#: What git holds at the link's place.
_ABSOLUTE = "absolute"
_RELATIVE = "relative"
_FILES = "files"

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
    except Exception as exc:  # noqa: BLE001 — a session starts whatever git does; no commit was made
        outcome = _blocked("methodLinkNotTried", why=mcp_key.in_words(exc))
    try:
        _say(project, outcome)
    except Exception as exc:  # noqa: BLE001 — a sentence that cannot be built is no reason to stop
        app_log.logger().warning("could not say what became of the method link in %s: %s", project,
                                 mcp_key.in_words(exc))
    return outcome


def _blocked(key: str, **args) -> Outcome:
    return Outcome(BLOCKED, key, {"path": LINK, **args})


class _Git:
    """Git in the project, every command inside one bound (`mcp_key`'s way)."""

    def __init__(self, project: Path) -> None:
        self.project = project
        self.give_up = time.monotonic() + _GIT_WAIT_S

    def __call__(self, *command: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return child.run_bounded(["git", "-C", str(self.project), *command],
                                 timeout=max(0.0, self.give_up - time.monotonic()), text=True,
                                 encoding="utf-8", errors="replace",
                                 env=mcp_key.git_env() if env is None else env, **child.quiet())


def _no_answer(git: _Git, question: str, done: subprocess.CompletedProcess | None = None,
               why: str = "") -> Outcome:
    """Git did not answer `question`: nothing is done, and it is logged once."""
    said = why or (f"exit {done.returncode}: {_said(done)}" if done is not None else "no reason given")
    app_log.logger().info("git did not answer %s in %s: %s", question, git.project, said)
    return Outcome()


def _take_out(project: Path) -> Outcome:
    if not os.path.lexists(project / ".git"):
        return Outcome()
    git = _Git(project)
    mcp_key.teach_git_to_ignore(project, give_up=git.give_up)
    try:
        listed = git("ls-files", "-s", "-z", "--", LINK)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return _no_answer(git, "whether it tracks the link", why=mcp_key.in_words(exc))
    if listed.returncode != 0:
        return _no_answer(git, "whether it tracks the link", listed)
    entries = [line.split("\t", 1) for line in listed.stdout.split("\0") if "\t" in line]
    if not entries:
        return Outcome()
    what = _what_is_tracked(entries, git)
    if what is None:
        return Outcome()
    if what == _FILES:
        app_log.logger().info("git tracks files at %s in %s: not the link, left tracked", LINK, project)
        return Outcome(LEFT_ALONE, "methodLinkFilesFound", {"path": LINK})
    if what == _RELATIVE:
        app_log.logger().info("the method link tracked at %s in %s is not absolute: left tracked", LINK, project)
        return Outcome(LEFT_ALONE)
    return _untrack(project, git)


def _what_is_tracked(entries: list[list[str]], git: _Git) -> str | None:
    """A link git holds as one, read for where it points; a junction, whose files git holds as a
    folder's; or files. None: git did not answer."""
    if all(path == LINK and meta.split(" ")[0] == _SYMLINK_MODE for meta, path in entries):
        blob = entries[0][0].split(" ")[1]
        target = git("cat-file", "-p", blob)
        if target.returncode != 0:
            _no_answer(git, "where the link points", target)
            return None
        text = target.stdout.rstrip("\n")
        return _ABSOLUTE if posixpath.isabs(text) or ntpath.isabs(text) else _RELATIVE
    if all(path.startswith(f"{LINK}/") for _, path in entries) and _is_junction(git.project / LINK):
        return _ABSOLUTE
    return _FILES


def _is_junction(path: Path) -> bool:
    """`os.path.isjunction` is from Python 3.12; `is_symlink` says False for a junction."""
    if not sys.platform.startswith("win") or path.is_symlink():
        return False
    return method_binding._is_link(path, os.path.realpath(path), os.path.realpath(path.parent))


def _untrack(project: Path, git: _Git) -> Outcome:
    top = git("rev-parse", "--show-cdup", "--absolute-git-dir")
    lines = (top.stdout or "").splitlines() if top.returncode == 0 else []
    if len(lines) != 2 or lines[0]:  # a broken `.git`: git answered for some repository above this folder
        return _no_answer(git, "where its repository is", top)
    git_dir = Path(lines[1])
    operation = mcp_key.git_operation_in(git_dir)
    if operation:
        return _blocked("methodLinkMidOperation", operation=operation)
    lock = git_dir / "index.lock"
    if lock.exists():
        return _blocked("methodLinkLocked", lock=str(lock))
    ignored = git("check-ignore", "-q", "--no-index", "--", LINK)
    if ignored.returncode == 1:
        return _blocked("methodLinkNotIgnored")  # out of the index, `add -A` would put it back
    if ignored.returncode != 0:
        return _no_answer(git, "whether it ignores the link", ignored)
    head = _head(git)
    if head is None:
        return _no_answer(git, "what HEAD is")
    if not head:
        return _unstage(git)
    held = git("ls-tree", "--name-only", "-z", head, "--", LINK)
    if held.returncode != 0:
        return _no_answer(git, "whether HEAD holds the link", held)
    if not held.stdout:
        return _unstage(git)
    branch = git("symbolic-ref", "-q", "HEAD")
    if branch.returncode == 1:
        return _blocked("methodLinkDetached")
    if branch.returncode != 0:
        return _no_answer(git, "which branch is out", branch)
    for who in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        ident = git("var", who)
        if ident.returncode == 128:  # git's own exit for «please tell me who you are»
            return _blocked("methodLinkNoIdentity")
        if ident.returncode != 0:
            return _no_answer(git, "who commits", ident)
    edits = _person_edited(git, project, head)
    if edits is None:
        return Outcome()
    stopped = _commit(git, head)
    if stopped is not None:
        return stopped
    return _landed(git, edits)


def _head(git: _Git) -> str | None:
    """HEAD's commit, "" for none yet, None when git did not answer."""
    found = git("rev-parse", "-q", "--verify", "HEAD")
    if found.returncode == 0:
        return found.stdout.strip()
    if found.returncode == 1:
        return ""
    return None


def _forget_link() -> tuple[str, ...]:
    return ("rm", "-r", "--cached", "-f", "-q", "--", LINK)


#: The real index made to match HEAD for both paths, in one step: on a commit of TCC's, the link's
#: removal and `.gitignore` land together or not at all.
_FOLLOW = ("reset", "-q", "--", LINK, _IGNORE_FILE)


def _unstage(git: _Git) -> Outcome:
    """Staged only, or no first commit yet: HEAD holds no link to remove. Also what a start finds
    after a follow that failed (`_landed`), and then `.gitignore` is behind HEAD too."""
    done = git(*(_FOLLOW if _index_behind_our_commit(git) else _forget_link()))
    if done.returncode != 0:
        return _blocked("methodLinkNotTried", why=_said(done))
    return Outcome(UNSTAGED, "methodLinkUnstaged", {"path": LINK})


def _index_behind_our_commit(git: _Git) -> bool:
    """HEAD is TCC's own commit, and the real index still has `.gitignore` as it was before it. No
    other staged edit counts: one of the person's is theirs and goes unreset."""
    subject = git("log", "-1", "--format=%s", "HEAD")
    if subject.returncode != 0 or subject.stdout.strip() != _MESSAGE:
        return False
    return _blob(git, f":{_IGNORE_FILE}") == _blob(git, f"HEAD~1:{_IGNORE_FILE}")


def _blob(git: _Git, name: str) -> str:
    """The object `name` is, or "" when there is none."""
    found = git("rev-parse", "-q", "--verify", name)
    return found.stdout.strip() if found.returncode == 0 else ""


def _commit(git: _Git, head: str) -> Outcome | None:
    """The commit, on an index of its own: None when it landed, else what stopped it. The real index
    is not touched here, so every way out leaves it as the person had it."""
    with tempfile.TemporaryDirectory(prefix="tcc-index-", ignore_cleanup_errors=True) as temp:
        env = {**mcp_key.git_env(), "GIT_INDEX_FILE": str(Path(temp) / "index")}
        for step in (("read-tree", head), _forget_link(), ("add", "-f", "--", _IGNORE_FILE)):
            done = git(*step, env=env)
            if done.returncode != 0:
                return _blocked("methodLinkNotTried", why=_said(done))
        now = _head(git)
        if now is None:
            return _no_answer(git, "whether HEAD moved")
        if now != head:  # a commit on the tree read before it would undo that commit
            return _blocked("methodLinkHeadMoved")
        made = git("commit", "-q", "-m", _MESSAGE, env=env)
        if made.returncode != 0:
            return _blocked("methodLinkCommitFailed", why=_said(made))
    return None


def _landed(git: _Git, edits: bool) -> Outcome:
    """The commit is in: what follows it never reads as one that did not land. Everything here is
    within the same bound, so a slow hook leaves less of it, and whatever it costs is said."""
    short = _short_head(git)
    behind = _follow_in_index(git)
    return Outcome(COMMITTED, "methodLinkCommitted",
                   {"path": LINK, "edits": edits, "commit": short or "HEAD",
                    "widened": _widened_by_hook(git), "behind": behind},
                   commit=short)


def _short_head(git: _Git) -> str:
    try:
        shown = git("rev-parse", "--short", "HEAD")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        app_log.logger().info("git did not answer with TCC's commit in %s: %s", git.project,
                              mcp_key.in_words(exc))
        return ""
    if shown.returncode != 0:
        app_log.logger().info("git did not answer with TCC's commit in %s: exit %s", git.project,
                              shown.returncode)
        return ""
    return shown.stdout.strip()


def _follow_in_index(git: _Git) -> str:
    """The real index catches up with the commit: "" when it did, else why it did not. A next start
    heals the rest (`_unstage`); until then git shows both paths behind, so it is said."""
    try:
        done = git(*_FOLLOW)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        why = mcp_key.in_words(exc)
    else:
        if done.returncode == 0:
            return ""
        why = _said(done)
    app_log.logger().warning("the real index did not follow TCC's commit in %s: %s", git.project, why)
    return why


def _widened_by_hook(git: _Git) -> str:
    """What the commit holds beyond `.gitignore` and the link, as a list to say: a hook of the
    person's put it there, under the index TCC built. Said, not undone."""
    try:
        shown = git("diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "HEAD")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        app_log.logger().info("git did not answer what TCC's commit holds in %s: %s", git.project,
                              mcp_key.in_words(exc))
        return ""
    if shown.returncode != 0:
        app_log.logger().info("git did not answer what TCC's commit holds in %s: exit %s", git.project,
                              shown.returncode)
        return ""
    held = [path for path in shown.stdout.split("\0") if path]
    return ", ".join(path for path in held if path != _IGNORE_FILE and path != LINK and not path.startswith(f"{LINK}/"))


def _person_edited(git: _Git, project: Path, head: str) -> bool | None:
    """Whether `.gitignore` differs from HEAD by more than TCC's own lines. None: git did not answer."""
    held = git("ls-tree", "--name-only", "-z", head, "--", _IGNORE_FILE)
    if held.returncode != 0:
        _no_answer(git, "whether HEAD holds .gitignore", held)
        return None
    committed: set[str] = set()
    if held.stdout:
        shown = git("show", f"HEAD:{_IGNORE_FILE}")
        if shown.returncode != 0:
            _no_answer(git, "what HEAD's .gitignore says", shown)
            return None
        committed = set(shown.stdout.splitlines())
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
    for said, key in (("edits", "methodLinkCommittedEdits"), ("widened", "methodLinkCommitWidened"),
                      ("behind", "methodLinkCommittedIndexBehind")):
        if outcome.args.get(said):
            text += " " + self_check.translated(key).format(**outcome.args)
    app_log.warn(text)
