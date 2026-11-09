"""The MCP server's key: one per project, kept across restarts (#247).

A new `X-TCC-Token` on every start left a Claude Code session in the terminal holding the old one:
«Dynamic Client Registration rejected (HTTP 401)» until `/mcp` → reconnect. The key now lives in
`<project>/.tcc/mcp-token` and changes only on an explicit reset.

It is a secret on disk, and that sets the order of everything here:

* **git first.** Before anything is written `.gitignore` is taught TCC's lines and, where there is a
  repository, git is asked whether a `git add -A` (the method's `project_repo.py init`, TCC's Git
  backup) would take the key. Only its definite no refuses the key on disk: a path it does not
  ignore, or one it tracks. A git that cannot answer — any other exit, a timeout, no binary, a broken
  `.git`, dubious ownership — is treated as no git, and the key is kept as for a folder with none.
* **A refusal is only «no key file».** The run gets a key of its own, and `.mcp.json` is written with
  it as ever: a key that dies with the run. Asked once per start and once per reset, in `load` and
  `reset`: the GUI thread pays one bound at most, and `.mcp.json`'s write does not ask again.
* **Whole or not at all, owner only.** `own_store.write_secret`: temp file, fsync, rename, 0600.
* **Every failure still gives a key.** The server never runs without a guard and TCC never fails to
  start over this: a key that cannot be read or kept is replaced by a fresh one for this run, and
  `Key.note` says so for the status strip.

The key itself goes in no log line and no sentence; `problem` holds paths and reasons only.
Qt-free: the MCP server and the CLI use it.
"""

from __future__ import annotations

import errno
import os
import re
import secrets
import stat
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from autosound_tcc.core import app_log, child, config, own_store

#: What `Key.note` says, for whoever tells the person.
KEPT = ""  # the saved key, unchanged: nothing to say
MADE = "made"  # none was saved: a new one, kept from now on
REPLACED = "replaced"  # the saved one was damaged: a new one, kept from now on
RESET = "reset"  # a new one on request, kept from now on
RUN_ONLY = "run_only"  # could not be read or kept: a fresh one for this run alone (`problem`: why)
OLD_ON_DISK = "old_on_disk"  # a reset could neither save the new key nor remove the old one
NO_FOLDER = "no_folder"  # no project was chosen: nowhere that is this project's to keep one

FILE_NAME = "mcp-token"

#: What `secrets.token_urlsafe` makes, and all a header can carry. The lower bound is what a write
#: cut short would fail: the rename makes that impossible for TCC's writes, not for anyone else's.
_SHAPE = re.compile(r"[A-Za-z0-9_-]{32,128}")

#: The most that is ever read from the key's file. Runs on the GUI thread at start: what is there
#: is not this code's to trust, and an enormous file must not fill the memory.
_MOST_READ = 4096

#: What must never travel out of a project folder. `.mcp.json` and `.tcc/mcp-token` carry the
#: session's key; `.tcc/` is also TCC's own per-project state, including the picked models and the
#: packages sent to the reviewer. `.mcp-*.tmp` is `.mcp.json` on its way through a temp file in the
#: project's root: a kill between the write and the rename leaves the key in it. The link to the
#: method is one computer's absolute path (#255), with no trailing slash: a `/` pattern does not
#: match a symlink.
_IGNORE_LINES = (".mcp.json", ".tcc/", ".mcp-*.tmp", ".claude/skills/autosound-tuning")

#: What git leaves in its folder while it is in the middle of something. `sequencer/` is a paused
#: multi-commit cherry-pick or revert, with no `*_HEAD` once a step of it has been committed by hand.
_GIT_OPERATIONS = (("MERGE_HEAD", "merge"), ("rebase-merge", "rebase"), ("rebase-apply", "rebase"),
                   ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"), ("BISECT_LOG", "bisect"),
                   ("sequencer", "cherry-pick or revert"))

#: Point git at a repository other than the one it is asked about. TCC started from a hook or from
#: an editor's terminal inherits them, and they would answer for that repository instead.
_GIT_PLACE_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")


#: How long git gets to answer, all its questions together. `load` and `reset` run on the GUI
#: thread, which waits for them: a hung git costs this much, once, and counts as no git.
_GIT_WAIT_S = 2.0


@dataclass(frozen=True)
class Key:
    token: str = field(repr=False)  # so that a stray `%r` of this cannot put it in a log
    note: str = KEPT
    problem: str = ""


def teach_git_to_ignore(project_dir: Path, *, give_up: Optional[float] = None) -> None:
    """Add our lines to the project's `.gitignore`, keeping everything already in it.

    The method's README tells the user to back this folder up to a private GitHub, and TCC is what
    puts a token in it — so TCC is what says it must not travel (HUB-026). Measured on the user's
    machine 2026-09-06: of 11 such files, 9 were outside git and 2 ignored, by hand.

    Merged, never clobbered — the same rule `.mcp.json` itself follows: the file is the user's.
    Idempotent, because a server restarts many times in a session and a file that grows a line
    each time is a file somebody eventually deletes in annoyance. Never raises: a project whose
    `.gitignore` cannot be read or written still deserves a running server, and whether the key
    would travel is git's to say (`keep_out_of_git`), not this file's.

    Not during a merge, rebase, cherry-pick, revert or bisect, for any caller: a `.gitignore` changed
    then stops `rebase --continue`, and lands inside a conflict on the file. Git is asked only when
    a line is missing, within `give_up` when a caller already holds a bound. Line endings stay the
    file's: `newline=""`, or a CRLF file comes back LF and its whole diff goes into a commit.
    """
    path = Path(project_dir) / ".gitignore"
    try:
        with open(path, encoding="utf-8", newline="") as file:
            existing = file.read()
    except FileNotFoundError:
        existing = ""
    except (OSError, ValueError) as exc:  # unreadable, or not UTF-8: a file never rewritten blind
        app_log.logger().warning("could not read %s (%s: %s); TCC's lines are not added to it",
                                 path, type(exc).__name__, exc)
        return
    present = {line.strip() for line in existing.splitlines()}
    missing = [line for line in _IGNORE_LINES if line not in present]
    if not missing:
        return
    operation = _operation_under_way(Path(project_dir), give_up)
    if operation:
        app_log.logger().info("git is in the middle of a %s in %s: .gitignore is left as it is",
                              operation, project_dir)
        return
    eol = "\r\n" if "\r\n" in existing else "\n"
    block = "" if not existing or existing.endswith("\n") else eol
    block += f"{eol}# TCC: the session's token and TCC's own project state — neither travels.{eol}"
    block += "".join(f"{line}{eol}" for line in missing)
    try:
        path.write_text(existing + block, encoding="utf-8", newline="")
    except OSError as exc:
        app_log.logger().warning("could not add %s to %s: %s", ", ".join(missing), path, exc)


def git_env() -> dict[str, str]:
    """The environment for git asked about a project, without what would point it elsewhere."""
    return {name: value for name, value in os.environ.items() if name not in _GIT_PLACE_VARS}


def git_operation_in(git_dir: Path) -> str:
    """What git is in the middle of in `git_dir` (`rev-parse --absolute-git-dir`, for a linked
    worktree's folder as well), or "" when nothing."""
    for marker, operation in _GIT_OPERATIONS:
        if (git_dir / marker).exists():
            return operation
    return ""


def _has_git(project_dir: Path) -> bool:
    return any(os.path.lexists(there / ".git")
               for there in (project_dir.absolute(), *project_dir.absolute().parents))


def _operation_under_way(project_dir: Path, give_up: Optional[float]) -> str:
    """What git is in the middle of here, "" when nothing or when git did not answer: only a
    definite answer stops the write. A git that cannot say (a broken `.git`, dubious ownership)
    still needs these lines there, since the key is kept in that case (`_git_would_take_it`)."""
    if not _has_git(project_dir):
        return ""
    limit = give_up if give_up is not None else time.monotonic() + _GIT_WAIT_S
    try:
        done = child.run_bounded(["git", "-C", str(project_dir), "rev-parse", "--absolute-git-dir"],
                                 timeout=max(0.0, limit - time.monotonic()), text=True, encoding="utf-8",
                                 errors="replace", env=git_env(), **child.quiet())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        app_log.logger().info("git did not answer where its folder is in %s: %s", project_dir, in_words(exc))
        return ""
    if done.returncode != 0 or not (done.stdout or "").strip():
        app_log.logger().info("git did not answer where its folder is in %s (exit %s)", project_dir,
                              done.returncode)
        return ""
    return git_operation_in(Path(done.stdout.strip()))


def keep_out_of_git(project_dir: Path) -> str:
    """Teach `.gitignore`, then ask git: "" when a key may be written here, else why it may not."""
    project_dir = Path(project_dir)
    teach_git_to_ignore(project_dir)
    return _git_would_take_it(project_dir)


def _git_would_take_it(project_dir: Path) -> str:
    """Why git would carry the key, or "" when it would not or cannot say. The text of `.gitignore`
    cannot tell: a ` .tcc/` with a leading space or a later `!.tcc/` names the line and ignores
    nothing, and a tracked `.mcp.json` stays tracked whatever is ignored. `check-ignore` one path at
    a time: given several, it says yes for any.

    Only exit 1 is a no, from `check-ignore` as from a `ls-files` that found the path tracked (exit
    0): every other way this ends is git not answering. A broken repository is no reason to take
    away the terminal routes, and its `.git` carries nothing out of here either."""
    if not _has_git(project_dir):
        return ""
    give_up = time.monotonic() + _GIT_WAIT_S
    try:
        tracked = _ask_git(project_dir, give_up, "ls-files", "--error-unmatch", ".mcp.json")
        if tracked == 0:
            return f"git tracks .mcp.json in {project_dir}"
        if tracked != 1:
            return ""
        for name in (f".tcc/{FILE_NAME}", ".mcp.json"):
            ignored = _ask_git(project_dir, give_up, "check-ignore", "-q", name)
            if ignored == 1:
                return f"git in {project_dir} does not ignore {name}"
            if ignored != 0:
                return ""
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        app_log.logger().info("git could not be asked about the MCP key in %s: %s", project_dir,
                              in_words(exc))
    return ""


def _ask_git(project_dir: Path, give_up: float, *question: str) -> int:
    """Git's exit code for `question`. `child.run_bounded`: `subprocess.run` can outwait its own
    timeout on Windows, and this holds the GUI thread."""
    return child.run_bounded(["git", "-C", str(project_dir), *question],
                             timeout=max(0.0, give_up - time.monotonic()), env=git_env(),
                             **child.quiet()).returncode


def load(project_dir: Optional[Path]) -> Key:
    """This project's key: the saved one, or a new one and what became of it. Never raises.

    `project_dir` None is a window nobody chose a folder for: `config.project_dir()` then answers a
    fallback that is no project's, so a key is made and nothing is written there."""
    if project_dir is None:
        return Key(_fresh(), NO_FOLDER)
    path = _path(project_dir)
    try:
        token = _read_saved(path)
    except FileNotFoundError:
        return _made_first(Path(project_dir))
    except (OSError, ValueError) as exc:
        # There and refused: the bytes may be perfectly good, so nothing is written over them
        # (`own_store`'s rule). A reset is the person asking, and it may.
        return _run_only(f"{path}: {in_words(exc)}")
    if not token:
        # Not a key at all, so nothing is lost; left as it is, every start would make another.
        return _made(project_dir, REPLACED)
    problem = keep_out_of_git(Path(project_dir))
    if problem:  # git would carry the file, and nothing uses it now: it goes, so `add -A` cannot
        if not _operation_under_way(Path(project_dir), None):  # …unless a bisect or a rebase only
            try:  # stands on an older `.gitignore` for now: the key is good again after it
                path.unlink()
            except OSError as exc:
                app_log.logger().warning("could not remove the MCP key %s: %s", path, in_words(exc))
        return _run_only(problem)
    return Key(token)


def reset(project_dir: Optional[Path]) -> Key:
    """A new key on request, saved over the old one. Never raises.

    A person resets because a key leaked. If the new one cannot be saved, the old one must not be
    what the next start reads back, so its file goes; `OLD_ON_DISK` when that is refused too."""
    if project_dir is None:
        return Key(_fresh(), NO_FOLDER)
    key = _made(project_dir, RESET)
    if key.note != RUN_ONLY:
        return key
    refused = _discard(_path(project_dir))
    if not refused:
        return key
    app_log.logger().warning("the revoked MCP key is still on disk: %s", refused)
    return Key(key.token, OLD_ON_DISK, f"{key.problem}; {refused}")


def _path(project_dir: Path) -> Path:
    return config.tcc_dir(Path(project_dir)) / FILE_NAME


def _fresh() -> str:
    return secrets.token_urlsafe(24)


def in_words(exc: BaseException) -> str:
    """The reason as the strip can say it: an `OSError`'s without its repeat of the path, never the
    name of a class."""
    return (exc.strerror if isinstance(exc, OSError) else "") or str(exc) or "no reason given"


def _run_only(problem: str) -> Key:
    app_log.logger().warning("the MCP key lasts this run only: %s", problem)
    return Key(_fresh(), RUN_ONLY, problem)


def _made(project_dir: Path, note: str) -> Key:
    """A new key under `note`, when it could be kept; else one for this run."""
    token = _fresh()
    problem = _keep(Path(project_dir), token)
    if problem:
        return _run_only(problem)
    return Key(token, note)


def _made_first(project_dir: Path) -> Key:
    """This project's first key. Two TCCs starting on one folder both find no file and both get
    here; the rename let the last one win, and left the other serving a key the file did not hold.
    So the first to land is the project's key, and the other takes that one."""
    token = _fresh()
    try:
        problem = _keep(project_dir, token, first=True)
    except FileExistsError:
        return _theirs(project_dir)
    if problem:
        return _run_only(problem)
    return Key(token, MADE)


def _theirs(project_dir: Path) -> Key:
    """The key another TCC has just landed. Told as made: to this TCC's sessions it is new too.
    Empty only for the moment a folder with no hard links is mid-write: this run then uses its own."""
    path = _path(project_dir)
    try:
        token = _read_saved(path)
    except (OSError, ValueError) as exc:
        return _run_only(f"{path}: {in_words(exc)}")
    if not token:
        return _run_only(f"{path}: another TCC was still writing it")
    return Key(token, MADE)


def _keep(project_dir: Path, token: str, first: bool = False) -> str:
    """Save `token`, git told first: "" when it landed, else why it did not. With `first`, only if
    no key is there: `FileExistsError` when one is (`_made_first`)."""
    try:
        project_dir.mkdir(parents=True, exist_ok=True)  # a project not made yet has no `.gitignore`
        problem = keep_out_of_git(project_dir)
        if problem:
            return problem
        own_store.write_secret(_path(project_dir), token + "\n", only_if_absent=first)
    except (OSError, ValueError) as exc:
        if first and isinstance(exc, FileExistsError):
            raise
        return f"{_path(project_dir)}: {in_words(exc)}"
    return ""


def _discard(path: Path) -> str:
    """Take the key's file away: "" when no key is left there, else why it is. A link goes, and
    nothing behind it; a folder or a device holds no key this file ever read."""
    try:
        if path.parent.is_symlink():
            return ""  # nothing of TCC's was ever kept through a link
        if not stat.S_ISREG(os.lstat(path).st_mode) and not path.is_symlink():
            return ""
        os.unlink(path)
    except (FileNotFoundError, NotADirectoryError):
        return ""
    except OSError as exc:
        return f"{path}: {in_words(exc)}"
    return ""


def _read_saved(path: Path) -> str:
    """The key saved at `path`, or "" when what is there is not one. Raises what the read raised.

    Only TCC's own plain file, in TCC's own folder: a `.tcc` or a key file that is a link would
    have the key read from, and closed in, somewhere else. Not opened blind either: a FIFO would
    wait for a writer that never comes, on the GUI thread, so it is opened not to wait and looked
    at through the open file. No more than `_MOST_READ` is taken in.

    Windows has neither `O_NOFOLLOW` nor FIFOs: there the link is looked at before the open."""
    if path.parent.is_symlink() or (not hasattr(os, "O_NOFOLLOW") and path.is_symlink()):
        raise OSError(errno.ELOOP, "a link where TCC's own file or folder should be")
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
             | getattr(os, "O_BINARY", 0))
    handle = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(handle).st_mode):
            raise OSError(errno.EINVAL, "not a plain file")
        token = _as_token(os.read(handle, _MOST_READ))
        if token:
            _close(handle, path)
        return token
    finally:
        os.close(handle)


def _as_token(raw: bytes) -> str:
    """The key in `raw`, or "" when that is not one."""
    try:
        token = raw.decode("ascii").strip()
    except ValueError:
        return ""
    return token if _SHAPE.fullmatch(token) else ""


def _close(handle: int, path: Path) -> None:
    """A key others can read — restored from a backup, set by hand — goes back to the owner's
    alone: through the open file, which follows no link. Only a file already known to hold a key:
    nothing is changed about any other. Windows keeps its own ACLs, inherited from the project
    folder, as for `.mcp.json`."""
    if os.name == "nt":
        return
    try:
        if stat.S_IMODE(os.fstat(handle).st_mode) & 0o077:
            os.fchmod(handle, 0o600)
    except OSError as exc:
        app_log.logger().warning("could not restrict %s: %s", path, in_words(exc))
