"""Is there a newer TCC, is there a newer method, and what installs it.

Two questions a tester should never have to ask in a chat. The versions are already on screen
(`core/install_report.py`); this adds the other half — what is on the server — and the one command
that closes the gap.

**The two halves are installed differently, so they update differently.**

*The method* is a shallow git checkout parked on a release tag (`v3.*`), which the installer
updates with a fetch and a checkout. TCC can do exactly that itself, in a thread, in under a
second: it is another folder's git repository, and nothing of ours is holding it open.

*TCC* is a `uv` tool, and updating it means replacing the files of the process doing the asking.
On macOS that quietly works and takes effect at the next start; on Windows it cannot — the running
`.exe` and its loaded DLLs are locked, and `uv` would fail in the middle with a permission error
that reads like a bug. So TCC's update is handed to a terminal the person can watch and told to
run after the app is closed. Which is also the honest shape: it downloads several hundred
megabytes, and that belongs in a window with output, not behind a spinner.

Nothing here raises and nothing here writes without being asked: `check_*` only reads and asks the
network, `apply_skill()` is the one function that changes anything, and it refuses on any checkout
that looks like somebody's own working tree.

Qt-free, and every import is at the top — this is called from a worker thread, and an import there
pays PySide6's source-reading import hook (see `core/install_report.py`).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autosound_tcc.core import child, install_report, vendor_loader

#: Where each half comes from. The installer's own constants, kept identical on purpose: an update
#: that pulled from a different place than the install did would be a second source of truth.
TCC_REPO = "https://github.com/ayukhno/autosound-tcc"
SKILL_REPO = "https://github.com/ayukhno/autosound-tuning-skill"

#: The method installs from a release tag, never from `main` — the installer asks for the newest
#: `v3.*` and so do we.
SKILL_TAG_GLOB = "v3.*"

#: And so does TCC now (F-024, 2026-08-22). It used to install from the repository with no ref at
#: all, which means the default branch's HEAD: pressing "update" took whatever had landed on
#: `main` since, finished or not. The panel showed a version and looked like it was following
#: releases, but that number came out of `pyproject.toml` at that commit — it looked like a tag
#: and was not one. `v*` rather than a major-pinned glob because TCC's own line is still `v0.x`
#: and a major bump should not silently stop updates; `_version_key` does the ordering.
TCC_TAG_GLOB = "v*"

#: A network round trip to GitHub, on a machine that may be tethered in a car park.
_ASK_TIMEOUT = 12.0

#: What the installer runs, and therefore what the button offers. `--python 3.12` is not optional:
#: without it `uv` picked the system interpreter and the GUI extras landed where they could not be
#: imported (install.sh carries the same comment).
TCC_INSTALL_COMMAND = (
    f'uv tool install --python 3.12 --upgrade "autosound-tcc[gui,claude] @ git+{TCC_REPO}"'
)


def tcc_install_command(tag: str = "") -> str:
    """The install command, pinned to a release tag when one is known.

    Without a tag it falls back to the ref-less form, which resolves to the default branch. That
    is the OLD behaviour and it stays as the offline path on purpose: a machine that cannot reach
    GitHub to list tags can still be told a command that works. What it must not be is the silent
    default, which is what it was until F-024.
    """
    if not tag:
        return TCC_INSTALL_COMMAND
    return (
        f'uv tool install --python 3.12 --upgrade '
        f'"autosound-tcc[gui,claude] @ git+{TCC_REPO}@{tag}"'
    )


def tcc_install_line(pid: Optional[int] = None, tag: str = "") -> str:
    """The update command, with a wait for THIS process in front of it.

    Telling somebody to close the app first is not enough — it was tried, and the update ran
    anyway while the app was open. `uv` then replaced the package, tried to clear the old
    `Scripts` directory, and could not: the running executable is in it, and Windows will not
    delete a file that is open. It ends in `error: failed to remove directory … Access is denied
    (os error 5)` after appearing to succeed (user, Windows 11, 2026-08-19).

    So the window waits for our own process id to disappear and only then runs `uv`. The person
    closes TCC when they are ready, and the update happens on a machine where nothing holds the
    files. macOS would survive replacing them under a running process, but not always cleanly —
    TCC imports lazily, so a module first needed after the swap would be read from a directory
    that is no longer the one it started with. One behaviour on both platforms is also one thing
    to explain.
    """
    if pid is None:
        pid = os.getpid()
    command = tcc_install_command(tag)
    if sys.platform.startswith("win"):
        # `&` in cmd is "then", regardless of what the previous command returned. Wait-Process
        # returns at once if the id is already gone, which is the case when TCC was closed first.
        return (
            f'echo Close TCC now - this window is waiting for it, then it will update. '
            f'& powershell -NoProfile -Command "Wait-Process -Id {pid} -ErrorAction SilentlyContinue" '
            f'& {command} '
            f'& echo. & echo Done - start TCC again.'
        )
    return (
        f"echo 'Close TCC now — this window is waiting for it, then it will update.'; "
        f"while kill -0 {pid} 2>/dev/null; do sleep 1; done; "
        f"{command}; "
        f"echo; echo 'Done — start TCC again.'"
    )


@dataclass(frozen=True)
class Status:
    """One half of the installation: what is here, what is out there, and what to do about it."""

    name: str
    #: What is installed, as a person reads it — a version, or "" when it cannot be told.
    installed: str
    #: What the server has. "" means the question could not be asked, which is NOT "up to date".
    latest: str
    #: True only when both are known AND they differ in the direction that matters.
    newer: bool
    #: WHY, as a key and never as a sentence: "source_checkout", "no_network", "on_branch"… This
    #: module is Qt-free and language-free, and the panel that shows it is neither — a sentence
    #: composed here came out in English inside a Ukrainian window (user's screenshot, 2026-08-19).
    reason: str = ""
    #: The part of the reason that is data rather than words: a branch name, a git error.
    detail: str = ""
    #: False when this installation is not ours to touch (a checkout, a hand-made symlink).
    updatable: bool = True
    #: The commit that is here, and the commit the newest tag names — "" when either cannot be
    #: read. For the method these are what `newer` is DECIDED by, and since F-036 they are not
    #: printed on the row at all: `installed` and `latest` above are what a person reads and
    #: quotes, and the whole commit is in the installation report (HUB-001, narrowed).
    installed_sha: str = ""
    latest_sha: str = ""


def _git(*args: str, cwd: Optional[Path] = None) -> tuple[bool, str]:
    """Run git, return `(ok, output)`. Never raises — a failed probe is an answer, not a crash."""
    try:
        done = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=_ASK_TIMEOUT,
            check=False, cwd=str(cwd) if cwd else None, **child.quiet())
    except Exception as exc:  # noqa: BLE001 — no git, no network, a hung server
        return False, f"{type(exc).__name__}: {exc}"
    out = (done.stdout or "").strip() or (done.stderr or "").strip()
    return done.returncode == 0, out


def _version_key(text: str) -> tuple:
    """`v3.0.10` -> (3, 0, 10), so 3.0.10 sorts after 3.0.9 — which a string compare gets wrong."""
    return tuple(int(part) for part in re.findall(r"\d+", text)) or (0,)


def _newest_tag_in(repo: str, glob: str) -> tuple[str, str]:
    """The newest tag matching `glob` in `repo`, and the COMMIT it names. `("", "")` if unaskable.

    **No `--refs`, and that is the whole point of this function.** `--refs` drops the peeled `^{}`
    lines, and for an ANNOTATED tag the line that survives carries the sha of the TAG OBJECT, not
    of the commit. A checked-out HEAD is a commit, so a comparison against the unpeeled sha never
    matches: every installation on earth would read as out of date, and it would look like the
    network working. Written down as a trap in the hub's `governance/RELEASE-CHANNEL.md` §8.2, and
    live here — the method's `v3.0.36` is annotated, tag object `56ffb54`, commit `70a4fa7`
    (measured 2026-08-27). A lightweight tag has no `^{}` line and needs the plain one, so both
    are read and the peeled one wins.

    The peel pattern is passed EXPLICITLY as a second one rather than left to `glob`. It works
    either way today, because both globs here end in `*` and so match `…^{}` by accident — and an
    accident is a bad thing to hang this on: narrowing a glob to an exact tag would drop the peel
    again, silently, and bring back the very bug above.
    """
    ok, out = _git("ls-remote", "--tags", repo, glob, f"{glob}^{{}}")
    if not ok or not out:
        return "", ""
    shas: dict[str, str] = {}
    for line in out.splitlines():
        sha, _tab, ref = line.partition("\t")
        if "/" not in ref:
            continue
        name = ref.rsplit("/", 1)[-1]
        peeled = name.endswith("^{}")
        name = name[:-3] if peeled else name
        if peeled or name not in shas:
            shas[name] = sha.strip()
    if not shas:
        return "", ""
    newest = max(shas, key=_version_key)
    return newest, shas[newest]


def newest_tag() -> str:
    """The newest `v3.*` tag in the method's repository, or "" if it cannot be asked."""
    return _newest_tag_in(SKILL_REPO, SKILL_TAG_GLOB)[0]


def newest_tcc_tag() -> str:
    """The newest release tag of TCC itself, or "" if it cannot be asked."""
    return _newest_tag_in(TCC_REPO, TCC_TAG_GLOB)[0]


def _skill_repo_dir() -> Optional[Path]:
    """The method's git repository root, through the installer's symlink or junction."""
    try:
        return vendor_loader.skill_repo_root()
    except Exception:  # noqa: BLE001
        return None


def _is_ours(repo: Path) -> tuple[bool, tuple[str, str]]:
    """Whether this checkout is the installer's to move, and if not, why not.

    The installer parks its clone on a tag, detached, with nothing modified. A developer's clone
    sits on a branch and usually has edits. Moving THAT would throw away somebody's work, so the
    two are told apart before anything is fetched — the same care `install.sh` takes before it
    touches `~/.claude/skills/autosound-tuning`.
    """
    ok, _ = _git("rev-parse", "--git-dir", cwd=repo)
    if not ok:
        return False, ("not_a_checkout", "")
    # A SUBMODULE is detached and clean, which is exactly what an installed release looks like —
    # so every other test here passes it, and pressing the button would have checked a release tag
    # out inside somebody's working repository and left the parent's pin modified. Found by the
    # question "what happens if I press this on the local machine?" (user, 2026-08-19), which is a
    # better test than the three I had written.
    inside, parent = _git("rev-parse", "--show-superproject-working-tree", cwd=repo)
    if inside and parent:
        return False, ("submodule", parent)
    on_branch, branch = _git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=repo)
    if on_branch:
        return False, ("on_branch", branch)
    dirty_ok, dirty = _git("status", "--porcelain", cwd=repo)
    if dirty_ok and dirty:
        return False, ("dirty", "")
    return True, ("", "")
def check_skill() -> Status:
    """The method: the commit installed here against the commit the newest release tag names.

    **Compared by sha, not by the version string**, since HUB-001. `plugin.json`'s version is kept
    by hand and in the method's own repository the two already disagree — `main` carries 3.0.36
    while `marketplace.json` still says 2.8.3 (measured 2026-08-27). Comparing two hand-kept
    strings answers "are these numbers different", when the question is "is this checkout the one
    the tag names": a release cut without touching the manifest would read as up to date forever,
    and a manifest bumped early would offer an installation an update to itself. The version stays
    on the row because it is what a person reads — signature beside identifier, never instead.

    "Ahead of the newest tag" is not a case here the way it is in `check_tcc`: `_is_ours` has
    already turned away everything except the clean detached clone the installer parked on a tag.
    """
    installed = install_report.skill_version()
    sha = install_report.skill_sha()
    repo = _skill_repo_dir()
    latest, latest_sha = _newest_tag_in(SKILL_REPO, SKILL_TAG_GLOB)
    latest_version = latest.lstrip("v")
    if repo is None:
        return Status("skill", installed, latest_version, False, "not_found", updatable=False,
                      installed_sha=sha, latest_sha=latest_sha)
    ours, (why, detail) = _is_ours(repo)
    if not ours:
        return Status("skill", installed, latest_version, False, why, detail, updatable=False,
                      installed_sha=sha, latest_sha=latest_sha)
    if not sha or not latest_sha:
        # Nothing to compare against: no network, or a checkout git would not answer for. NOT
        # "up to date" — `newer` stays False because it is unknown, the rule `check_tcc` keeps.
        return Status("skill", installed, latest_version, False,
                      "" if installed else "no_manifest",
                      installed_sha=sha, latest_sha=latest_sha)
    return Status("skill", installed, latest_version, sha != latest_sha,
                  "" if installed else "no_manifest",
                  installed_sha=sha, latest_sha=latest_sha)



def check_tcc() -> Status:
    """TCC: the version installed against the newest RELEASE, the way the method half works.

    Compared by version, because since F-024 both halves follow tags. It used to be compared by
    COMMIT, and that was right for what it described: TCC installed from the default branch, so
    the metadata version only moved when a release was cut and a build three days of fixes behind
    still called itself 0.1.1 (measured — an upgrade went 0.1.5 → 0.1.5 across two commits and did
    carry the new code). The commit was the only thing that differed. Now a release IS the unit
    being offered, so the number means what it says.

    The commit is still what a bug report needs, and it is still in the installation block below;
    what this row carries is two version numbers a person can compare.

    A build NEWER than the newest tag is not an update — that is a developer running ahead of the
    releases, and telling them to "update" backwards would be wrong. It reads as up to date.
    """
    version = install_report.app_version()
    _url, commit = install_report.install_source()
    if not commit:
        return Status("tcc", version, "", False, "source_checkout", updatable=False)
    tag = newest_tcc_tag()
    if not tag:
        return Status("tcc", version, "", False, "no_network")
    latest = tag.lstrip("v")
    if not version:
        # No metadata to compare with: fall back to what is on offer, and let the person decide.
        return Status("tcc", version, latest, True)
    if _version_key(version) >= _version_key(latest):
        return Status("tcc", version, version, False)
    return Status("tcc", version, latest, True)


def check_all() -> tuple[Status, Status]:
    """Both halves. Two network calls; run it off the GUI thread."""
    return check_tcc(), check_skill()


def apply_skill(tag: str = "") -> tuple[bool, str, str]:
    """Move the method's checkout onto `tag` (default: the newest release). `(ok, what happened)`.

    Exactly what the installer does, for exactly the same reason it does it that way: the clone is
    `--depth 1`, so the tag being asked for is not in it yet. Fetch it BY NAME and check out
    `FETCH_HEAD`, which works the same whether the ref is a tag, a branch or a sha.
    """
    repo = _skill_repo_dir()
    if repo is None:
        return False, "not_found", ""
    ours, (why, detail) = _is_ours(repo)
    if not ours:
        return False, why, detail
    target = tag or newest_tag()
    if not target:
        return False, "no_network", ""
    ok, out = _git("fetch", "--quiet", "--depth", "1", "origin", target, cwd=repo)
    if not ok:
        return False, "git_failed", out
    ok, out = _git("-c", "advice.detachedHead=false", "checkout", "--quiet", "FETCH_HEAD",
                   cwd=repo)
    if not ok:
        return False, "git_failed", out
    return True, target, ""
