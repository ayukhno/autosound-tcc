"""The MCP server's key: one per project, kept across restarts (#247).

A new `X-TCC-Token` on every start left a Claude Code session in the terminal holding the old one:
«Dynamic Client Registration rejected (HTTP 401)» until `/mcp` → reconnect. The key now lives in
`<project>/.tcc/mcp-token` and changes only on an explicit reset.

It is a secret on disk, and that sets the order of everything here:

* **git first.** Nothing is written until the project's `.gitignore` names `.tcc/` and, where there
  is a repository, git itself says the key would not be taken — a `git add -A` (the method's
  `project_repo.py init`, TCC's Git backup) must find it already ignored. A `.gitignore` TCC cannot
  read or add to, or a git that answers no, means no file at all.
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
#: project's root: a kill between the write and the rename leaves the key in it.
_IGNORE_LINES = (".mcp.json", ".tcc/", ".mcp-*.tmp")


#: How long git gets to answer, all its questions together. `load` and `reset` run on the GUI
#: thread, which waits for them: a hung git costs this much, once, and counts as a refusal.
_GIT_WAIT_S = 2.0


class NotKeptOutOfGit(OSError):
    """Git could not be told, or says no: the key is not to be written where it would be taken."""


@dataclass(frozen=True)
class Key:
    token: str = field(repr=False)  # so that a stray `%r` of this cannot put it in a log
    note: str = KEPT
    problem: str = ""


def teach_git_to_ignore(project_dir: Path) -> bool:
    """Add our two lines to the project's `.gitignore`, keeping everything already in it; whether
    the file names both of them afterwards.

    The method's README tells the user to back this folder up to a private GitHub, and TCC is what
    puts a token in it — so TCC is what says it must not travel (HUB-026). Measured on the user's
    machine 2026-09-06: of 11 such files, 9 were outside git and 2 ignored, by hand.

    Merged, never clobbered — the same rule `.mcp.json` itself follows: the file is the user's.
    Idempotent, because a server restarts many times in a session and a file that grows a line
    each time is a file somebody eventually deletes in annoyance. Never raises: a project whose
    `.gitignore` cannot be written is a project that still deserves a running server. It does not
    get a key on disk, though: that is what the answer is for.
    """
    path = Path(project_dir) / ".gitignore"
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except (OSError, ValueError) as exc:  # unreadable, or not UTF-8: a file never rewritten blind
        app_log.logger().warning("could not read %s (%s: %s); TCC's lines are not added to it",
                                 path, type(exc).__name__, exc)
        return False
    present = {line.strip() for line in existing.splitlines()}
    missing = [line for line in _IGNORE_LINES if line not in present]
    if not missing:
        return True
    block = "" if not existing or existing.endswith("\n") else "\n"
    block += "\n# TCC: the session's token and TCC's own project state — neither travels.\n"
    block += "".join(f"{line}\n" for line in missing)
    try:
        path.write_text(existing + block, encoding="utf-8")
    except OSError as exc:
        app_log.logger().warning("could not add %s to %s: %s", ", ".join(missing), path, exc)
        return False
    return True


def keep_out_of_git(project_dir: Path) -> str:
    """Teach `.gitignore`, then ask git: "" when a key may be written here, else why it may not."""
    project_dir = Path(project_dir)
    if not teach_git_to_ignore(project_dir):
        return f"{project_dir / '.gitignore'} does not keep .tcc/ out of git"
    return _git_would_take_it(project_dir)


def _git_would_take_it(project_dir: Path) -> str:
    """Whether git, asked, would carry the key: "" when it would not, or when there is no repository
    or no git to ask. The text of `.gitignore` cannot tell: a ` .tcc/` with a leading space or a
    later `!.tcc/` names the line and ignores nothing, and a tracked `.mcp.json` stays tracked
    whatever is ignored. `check-ignore` one path at a time: given several, it says yes for any."""
    if not any(os.path.lexists(there / ".git")
               for there in (project_dir.absolute(), *project_dir.absolute().parents)):
        return ""
    give_up = time.monotonic() + _GIT_WAIT_S
    try:
        if _ask_git(project_dir, give_up, "ls-files", "--error-unmatch", ".mcp.json") == 0:
            return f".mcp.json is tracked by git in {project_dir}"
        for name in (f".tcc/{FILE_NAME}", ".mcp.json"):
            if _ask_git(project_dir, give_up, "check-ignore", "-q", name) != 0:
                return f"git in {project_dir} does not ignore {name}"
    except FileNotFoundError:
        return ""  # no git on this machine, so no `git add -A` either
    except (OSError, subprocess.SubprocessError) as exc:
        return f"git in {project_dir} could not be asked: {_why(exc)}"
    return ""


def _ask_git(project_dir: Path, give_up: float, *question: str) -> int:
    """Git's exit code for `question`. `child.run_bounded`: `subprocess.run` can outwait its own
    timeout on Windows, and this holds the GUI thread."""
    return child.run_bounded(["git", "-C", str(project_dir), *question],
                             timeout=max(0.0, give_up - time.monotonic()),
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
        return _run_only(f"{path}: {_why(exc)}")
    if not token:
        # Not a key at all, so nothing is lost; left as it is, every start would make another.
        return _made(project_dir, REPLACED)
    problem = keep_out_of_git(Path(project_dir))
    if problem:  # the file stays: it may be good again once git is told, and it is the person's
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


def _why(exc: BaseException) -> str:
    """The reason, without an `OSError`'s repeat of the path."""
    return (exc.strerror if isinstance(exc, OSError) else "") or type(exc).__name__


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
        return _run_only(f"{path}: {_why(exc)}")
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
        return f"{_path(project_dir)}: {_why(exc)}"
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
        return f"{path}: {_why(exc)}"
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
        app_log.logger().warning("could not restrict %s: %s", path, _why(exc))
