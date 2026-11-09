"""The MCP server's key: one per project, kept across restarts (#247).

A new `X-TCC-Token` on every start left a Claude Code session in the terminal holding the old one:
«Dynamic Client Registration rejected (HTTP 401)» until `/mcp` → reconnect. The key now lives in
`<project>/.tcc/mcp-token` and changes only on an explicit reset.

It is a secret on disk, and that sets the order of everything here:

* **git first.** Nothing is written until the project's `.gitignore` names `.tcc/` — a `git add -A`
  (the method's `project_repo.py init`, TCC's Git backup) must find it already ignored. A `.gitignore`
  TCC cannot read or add to means no file at all.
* **Whole or not at all, owner only.** `own_store.write_secret`: temp file, fsync, rename, 0600.
* **Every failure still gives a key.** The server never runs without a guard and TCC never fails to
  start over this: a key that cannot be read or kept is replaced by a fresh one for this run, and
  `Key.note` says so for the status strip.

The key itself goes in no log line and no sentence; `problem` holds paths and reasons only.
Qt-free: the MCP server and the CLI use it.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from autosound_tcc.core import app_log, config, own_store

#: What `Key.note` says, for whoever tells the person.
KEPT = ""  # the saved key, unchanged: nothing to say
MADE = "made"  # none was saved: a new one, kept from now on
REPLACED = "replaced"  # the saved one was damaged: a new one, kept from now on
RESET = "reset"  # a new one on request, kept from now on
RUN_ONLY = "run_only"  # could not be read or kept: a fresh one for this run alone (`problem`: why)
NO_FOLDER = "no_folder"  # no project was chosen: nowhere that is this project's to keep one

FILE_NAME = "mcp-token"

#: What `secrets.token_urlsafe` makes, and all a header can carry. The lower bound is what a write
#: cut short would fail: the rename makes that impossible for TCC's writes, not for anyone else's.
_SHAPE = re.compile(r"[A-Za-z0-9_-]{32,128}")

#: What must never travel out of a project folder. `.mcp.json` and `.tcc/mcp-token` carry the
#: session's key; `.tcc/` is also TCC's own per-project state, including the picked models and the
#: packages sent to the reviewer. `.mcp-*.tmp` is `.mcp.json` on its way through a temp file in the
#: project's root: a kill between the write and the rename leaves the key in it.
_IGNORE_LINES = (".mcp.json", ".tcc/", ".mcp-*.tmp")


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


def load(project_dir: Optional[Path]) -> Key:
    """This project's key: the saved one, or a new one and what became of it. Never raises.

    `project_dir` None is a window nobody chose a folder for: `config.project_dir()` then answers a
    fallback that is no project's, so a key is made and nothing is written there."""
    if project_dir is None:
        return Key(_fresh(), NO_FOLDER)
    path = _path(project_dir)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return _made(project_dir, MADE)
    except (OSError, ValueError) as exc:
        # There and refused: the bytes may be perfectly good, so nothing is written over them
        # (`own_store`'s rule). A reset is the person asking, and it may.
        return _run_only(f"{path}: {_why(exc)}")
    try:
        token = raw.decode("ascii").strip()
    except ValueError:
        token = ""
    if not _SHAPE.fullmatch(token):
        # Not a key at all, so nothing is lost; left as it is, every start would make another.
        return _made(project_dir, REPLACED)
    _close(path)
    return Key(token)


def reset(project_dir: Optional[Path]) -> Key:
    """A new key on request, saved over the old one. Never raises."""
    if project_dir is None:
        return Key(_fresh(), NO_FOLDER)
    return _made(project_dir, RESET)


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


def _keep(project_dir: Path, token: str) -> str:
    """Save `token`, git told first: "" when it landed, else why it did not."""
    try:
        project_dir.mkdir(parents=True, exist_ok=True)  # a project not made yet has no `.gitignore`
        if not teach_git_to_ignore(project_dir):
            return f"{project_dir / '.gitignore'} does not keep .tcc/ out of git"
        own_store.write_secret(_path(project_dir), token + "\n")
    except (OSError, ValueError) as exc:
        return f"{_path(project_dir)}: {_why(exc)}"
    return ""


def _close(path: Path) -> None:
    """A key others can read — restored from a backup, set by hand — goes back to the owner's
    alone. Only a file already known to hold a key: nothing is changed about any other. Windows
    keeps its own ACLs, inherited from the project folder, as for `.mcp.json`."""
    if os.name == "nt":
        return
    try:
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            os.chmod(path, 0o600)
    except OSError as exc:
        app_log.logger().warning("could not restrict %s: %s", path, _why(exc))
