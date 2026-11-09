"""What the panel says about the project's git and its copy on GitHub (#235). Plain Python, no Qt.

Two sources, and the second replaces the first when it has answered: `GitStatus` (`project_view`,
counts in two children on the GUI thread, 2 s bound) is the panel's first paint; `Read` is the
method's `status --json --fetch`, taken off the GUI thread by `project_github`. A `null` in the
method's answer is a read that failed: it stays None here, and is never counted as zero.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autosound_tcc.state import ledger_line
from autosound_tcc.state.project_view import GitStatus
from autosound_tcc.ui.tcc import i18n


@dataclass(frozen=True)
class Commit:
    hash: str
    time: str
    subject: str = ""


@dataclass(frozen=True)
class Read:
    """The method's answer, `status --json --fetch`. A list that is None could not be read."""

    remote: Optional[str]
    tuning: Optional[tuple[str, ...]]
    housekeeping: Optional[tuple[str, ...]]
    ahead: Optional[tuple[Commit, ...]]
    remote_head: Optional[Commit] = None
    fetched: Optional[str] = None
    fetch_error: Optional[str] = None
    changes_error: Optional[str] = None
    sends: str = "person"
    #: The newest ledger version is later than the last commit the remote holds.
    ledger_newer: bool = False
    #: The run itself failed: the method's or TCC's words, with every list None.
    failed: str = ""

    @property
    def changed(self) -> Optional[int]:
        if self.tuning is None or self.housekeeping is None:
            return None
        return len(self.tuning) + len(self.housekeeping)


def unread(said: str) -> Read:
    """A run that gave no answer: everything unknown, and it says why."""
    return Read(remote=None, tuning=None, housekeeping=None, ahead=None, failed=said or "—")


def from_status(answer: dict, newest_version: Optional[str] = None) -> Optional[Read]:
    """The method's `status --json`, or None for an answer with none of the new keys (a project
    bound to a method older than `save`) or for a folder the method does not call a repository."""
    if not answer.get("repo") or "changes" not in answer:
        return None
    changes = answer.get("changes")
    tuning = None if changes is None else tuple(changes.get("tuning") or ())
    housekeeping = None if changes is None else tuple(changes.get("housekeeping") or ())
    listed = answer.get("ahead")
    ahead = None if listed is None else tuple(
        Commit(c.get("hash", ""), c.get("time", ""), c.get("subject", "")) for c in listed)
    head = answer.get("remote_head")
    remote_head = Commit(head.get("hash", ""), head.get("time", "")) if head else None
    return Read(remote=answer.get("remote"), tuning=tuning, housekeeping=housekeeping, ahead=ahead,
                remote_head=remote_head, fetched=answer.get("fetched"), fetch_error=answer.get("fetch_error"),
                changes_error=answer.get("changes_error"), sends=answer.get("sends") or "person",
                ledger_newer=_ledger_is_newer(newest_version, remote_head))


def _ledger_is_newer(newest: Optional[str], head: Optional[Commit]) -> bool:
    if newest is None:
        return False
    if head is None:  # a ledger, and nothing of it has ever reached the remote
        return True
    a, b = _parsed(newest), _parsed(head.time)
    return a is not None and b is not None and a > b


#: The most names a hover shows of one kind; past it, how many more.
NAMES_IN_TIP = 12


def when(stamp: str) -> str:
    """An ISO time as a person reads it: the hour today, the day and the hour before that."""
    from datetime import datetime

    moment = _parsed(stamp)
    if moment is None:
        return str(stamp)
    local = moment.astimezone()
    return f"{local:%H:%M}" if local.date() == datetime.now().date() else f"{local:%d.%m %H:%M}"


def _short(full: str) -> str:
    return (full or "")[:7]


def _names(heading: str, paths: tuple[str, ...]) -> str:
    shown = "\n".join(f"  {path}" for path in paths[:NAMES_IN_TIP])
    more = len(paths) - NAMES_IN_TIP
    return f"{heading}\n{shown}" + (f"\n{i18n.t('gitTipMore').format(n=more)}" if more > 0 else "")


def changes_tip(read: Read) -> str:
    """What is not committed, tuning files first: the hover of «Unsaved changes»."""
    parts = []
    if read.tuning:
        parts.append(_names(i18n.t("gitTipTuning").format(n=len(read.tuning)), read.tuning))
    if read.housekeeping:
        parts.append(_names(i18n.t("gitTipHousekeeping").format(n=len(read.housekeeping)), read.housekeeping))
    return "\n\n".join(parts)


def on_github(read: Read) -> str:
    """«on GitHub up to <hash> · <time>», or that nothing is."""
    if read.remote_head is None:
        return i18n.t("gitOnGithubNever")
    return i18n.t("gitOnGithubUntil").format(hash=_short(read.remote_head.hash), time=when(read.remote_head.time))


def ahead_tip(read: Read) -> str:
    """The commits the remote does not have, newest first, then what it holds."""
    commits = read.ahead or ()
    lines = [f"{_short(c.hash)} · {when(c.time)} · {c.subject}" for c in commits[:NAMES_IN_TIP]]
    more = len(commits) - NAMES_IN_TIP
    if more > 0:
        lines.append(i18n.t("gitTipMore").format(n=more))
    return "\n".join([*lines, "", on_github(read)]) if lines else on_github(read)


def _parsed(stamp: str):
    from datetime import datetime

    try:
        value = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.astimezone() if value.tzinfo is None else value


def newest_version_time(root) -> Optional[str]:
    """`created` of the newest ledger version, from the folder (the version looked at, #249, is no
    part of it). None when there is no ledger or none of it says."""
    best, stamp = None, None
    for preset in ledger_line.presets(root):
        versions = ledger_line.versions(root, preset)
        if not versions:
            continue
        try:
            data = json.loads(ledger_line.version_path(root, preset, versions[-1]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        created = data.get("created") if isinstance(data, dict) else None
        when = _parsed(created) if created else None
        if when is not None and (best is None or when > best):
            best, stamp = when, created
    return stamp


def watch_paths(git: Path) -> tuple[set[str], set[str]]:
    """(files, folders) of `.git` that a commit, a checkout or a push changes. Not `.git` itself:
    a fetch writes `FETCH_HEAD` there and the read would feed itself. Nothing for a `.git` that is
    a file (a linked worktree, a submodule): those are read on a ledger write only."""
    if not git.is_dir():
        return set(), set()
    files = {str(p) for p in (git / "HEAD", git / "packed-refs") if p.is_file()}
    refs = git / "refs"
    folders = {str(p) for p in (refs, refs / "heads", refs / "remotes", refs / "remotes" / "origin") if p.is_dir()}
    for base in (refs / "heads", refs / "remotes" / "origin"):
        for where, subs, _names in os.walk(base):
            folders.update(str(Path(where) / sub) for sub in subs)
    return files, folders


def refs_mark(git: Path) -> tuple:
    """What the refs say now: an event on a folder whose refs read the same is nobody's commit.
    A fetch alone rewrites `refs/remotes/origin/HEAD` every time (measured: its lock moves the
    folder's mtime on every fetch, git 2.54), so without this the read fed itself."""
    if not git.is_dir():
        return ()
    found = []
    for path in [git / "HEAD", git / "packed-refs"]:
        found.append((path.name, _text(path)))
    for base in (git / "refs" / "heads", git / "refs" / "remotes" / "origin"):
        for where, _subs, names in os.walk(base):
            for name in sorted(names):
                if not name.endswith(".lock"):
                    full = Path(where) / name
                    found.append((str(full.relative_to(git)), _text(full)))
    return tuple(sorted(found))


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def backup_label(step: int) -> str:
    """«Back up to GitHub (1/2)»: the backup is two presses — the repository, then the private copy
    on GitHub — and the first one looked like all of it (finding 145). The step comes from the
    folder (`panel`), never from a count of presses."""
    return f"{i18n.t('gitBackupBtn')} ({step}/2)"


@dataclass(frozen=True)
class Row:
    key: str
    value: str
    #: The hover: the names behind the number, or "".
    tip: str = ""


@dataclass(frozen=True)
class Panel:
    sub: str
    level: str
    tip: str
    rows: tuple[Row, ...]
    #: Which step of the backup the folder is at: 0 no repository, 1 no remote, None a backup.
    step: Optional[int]


def panel(git: GitStatus, read: Optional[Read], name: str) -> Panel:
    """The panel for `git`, the first paint, and `read`, the method's answer once it has landed."""
    if not git.works:
        return Panel(i18n.t("gitSubBroken"), git.level, i18n.t("gitTipBroken"),
                     (Row(i18n.t("gitRow"), i18n.t("gitSubBroken")),), None)
    if not git.repo:
        sub = i18n.t("gitSubNoRepo")
        tip = i18n.t("gitTipNoRepo").format(button=backup_label(0))
        return Panel(sub, git.level, tip, (Row(i18n.t("gitRow"), sub),), 0)
    changed, unpushed, counted = git.changed, git.unpushed, git.counted
    if read is not None:
        changed, unpushed = read.changed, None if read.ahead is None else len(read.ahead)
        counted = read.ahead is not None
    if not git.remote:
        sub, tip = i18n.t("gitSubNoRemote"), i18n.t("gitTipNoRemote").format(name=name)
    elif unpushed or not counted:  # not counted is «?», never «backed up» (#172)
        n, said = unpushed or "?", i18n.t("gitTipBehind" if counted else "gitTipUncounted")
        sub, tip = i18n.t("gitSubBehind").format(n=n), said.format(n=n, remote=git.remote)
    else:
        sub, tip = i18n.t("gitSubOk"), i18n.t("gitTipOk").format(remote=git.remote)
    rows = [Row(i18n.t("gitRow"), git.branch or "—")]
    if changed is not None:
        rows.append(Row(i18n.t("gitChanges"), str(changed) if changed else i18n.t("gitClean"),
                        changes_tip(read) if read is not None else ""))
    rows.append(Row(i18n.t("gitBackup"), git.remote or i18n.t("gitNone"),
                    on_github(read) if read is not None and git.remote else ""))
    if unpushed or not counted:
        rows.append(Row(i18n.t("gitUnpushed"), str(unpushed or "?"), ahead_tip(read) if read is not None else ""))
    level = git.level if read is None else ("wait" if not git.remote or unpushed or not counted else "done")
    return Panel(sub, level, tip, tuple(rows), None if git.remote else 1)
