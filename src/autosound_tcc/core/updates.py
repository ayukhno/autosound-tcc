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
import urllib.request
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

#: A network round trip to GitHub, on a machine that may be tethered in a car park.
_ASK_TIMEOUT = 12.0

#: What the installer runs, and therefore what the button offers. `--python 3.12` is not optional:
#: without it `uv` picked the system interpreter and the GUI extras landed where they could not be
#: imported (install.sh carries the same comment).
TCC_INSTALL_COMMAND = (
    f'uv tool install --python 3.12 --upgrade "autosound-tcc[gui,claude] @ git+{TCC_REPO}"'
)


def tcc_install_line(pid: Optional[int] = None) -> str:
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
    if sys.platform.startswith("win"):
        # `&` in cmd is "then", regardless of what the previous command returned. Wait-Process
        # returns at once if the id is already gone, which is the case when TCC was closed first.
        return (
            f'echo Close TCC now - this window is waiting for it, then it will update. '
            f'& powershell -NoProfile -Command "Wait-Process -Id {pid} -ErrorAction SilentlyContinue" '
            f'& {TCC_INSTALL_COMMAND} '
            f'& echo. & echo Done - start TCC again.'
        )
    return (
        f"echo 'Close TCC now — this window is waiting for it, then it will update.'; "
        f"while kill -0 {pid} 2>/dev/null; do sleep 1; done; "
        f"{TCC_INSTALL_COMMAND}; "
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


def newest_tag() -> str:
    """The newest `v3.*` tag in the method's repository, or "" if it cannot be asked."""
    ok, out = _git("ls-remote", "--tags", "--refs", SKILL_REPO, SKILL_TAG_GLOB)
    if not ok or not out:
        return ""
    tags = [line.rsplit("/", 1)[-1] for line in out.splitlines() if "/" in line]
    return max(tags, key=_version_key) if tags else ""


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
    on_branch, branch = _git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=repo)
    if on_branch:
        return False, ("on_branch", branch)
    dirty_ok, dirty = _git("status", "--porcelain", cwd=repo)
    if dirty_ok and dirty:
        return False, ("dirty", "")
    return True, ("", "")


def check_skill() -> Status:
    """The method: the version installed here against the newest release tag."""
    installed = install_report.skill_version()
    repo = _skill_repo_dir()
    latest = newest_tag()
    latest_version = latest.lstrip("v")
    if repo is None:
        return Status("skill", installed, latest_version, False, "not_found", updatable=False)
    ours, (why, detail) = _is_ours(repo)
    if not ours:
        return Status("skill", installed, latest_version, False, why, detail, updatable=False)
    if not installed or not latest:
        return Status("skill", installed, latest_version, False,
                      "" if installed else "no_manifest")
    return Status("skill", installed, latest_version,
                  _version_key(latest_version) > _version_key(installed))


def _remote_version(sha: str) -> str:
    """The version in `pyproject.toml` AT that commit, or "" — one anonymous read of a public file.

    Pinned to the sha rather than to the branch so the number and the commit beside it describe
    the same build. Without this the row compared a version against a commit hash — "0.1.4 — a
    newer one is out: 64c72c43eccd" — which is two different kinds of thing in one sentence and
    reads as nonsense (user's screenshot, 2026-08-19).
    """
    url = f"https://raw.githubusercontent.com/ayukhno/autosound-tcc/{sha}/pyproject.toml"
    try:
        with urllib.request.urlopen(url, timeout=_ASK_TIMEOUT) as response:
            text = response.read(20000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 — offline, rate-limited, moved: the sha alone still says it
        return ""
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else ""


def _named(version: str, sha: str) -> str:
    """`0.1.5 · 64c72c4` — what a person compares, and what actually identifies the build."""
    short = sha[:7]
    if version and short:
        return f"{version} · {short}"
    return version or short


def check_tcc() -> Status:
    """TCC: the commit this build came from against the head of the repository it came from.

    Compared by COMMIT, not by version. TCC installs from the default branch, so the version in
    the metadata only moves when a release is cut — a build three days of fixes behind still calls
    itself 0.1.1 (measured, not assumed: an upgrade here went 0.1.5 → 0.1.5 across two commits and
    did carry the new code). The commit is what actually differs, and `direct_url.json` records the
    one this install was built from. Both sides are then SHOWN as version and commit together, so
    the row compares like with like.
    """
    version = install_report.app_version()
    _url, commit = install_report.install_source()
    if not commit:
        return Status("tcc", version, "", False, "source_checkout", updatable=False)
    installed = _named(version, commit)
    ok, out = _git("ls-remote", TCC_REPO, "HEAD")
    head = out.split()[0] if ok and out.split() else ""
    if not head:
        return Status("tcc", installed, "", False, "no_network")
    if head == commit:
        return Status("tcc", installed, installed, False)
    return Status("tcc", installed, _named(_remote_version(head), head), True)


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
