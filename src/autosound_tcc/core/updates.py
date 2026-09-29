"""Is there a newer TCC, is there a newer method, and what installs it.

Two questions a tester should never have to ask in a chat. The versions are already on screen
(`core/install_report.py`); this adds the other half — what is on the server — and the one command
that closes the gap.

**The two halves are installed differently, so they update differently.**

*The method* is a shallow git checkout parked on a release tag (`v3.*`). Since the skill's
v3.0.64 it moves through the skill's OWN `scripts/upkeep.py` (hub #221, SKL-059; hub #217,
SKL-056): `clone` fetches the tag into `refs/tags` and checks its signature, `libs` brings numpy,
scipy and matplotlib along, and `keep-local` keeps a local change as a patch before anything is
reset. TCC runs no git that changes the clone any more; it runs the skill's command, off the GUI
thread, and shows what it answers. One path with the skill's installers, which call the same
script.

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

import json
import logging
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autosound_tcc.core import child, config, install_report, vendor_loader

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

#: The beta channel's own tags (hub RELEASE-CHANNEL.md §11.1). The first letter keeps them out of
#: `v*`, so a stable installation never sees one; the method's installers carry the same value
#: (`installer-consistency.py --print TCC_BETA_GLOB`).
TCC_BETA_GLOB = "beta-v*"

#: The two channels (§11.2). Anything else a setting could hold reads as stable.
STABLE = "stable"
BETA = "beta"

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


#: What the update window says, for a caller that passes no words of its own. The panel passes the
#: reader's language (`updTerm*` in `ui/tcc/i18n.py`); this module stays language-free, the way its
#: reason KEYS do (see `Status.reason`).
TCC_WINDOW_WORDS = {
    "wait": "Close TCC now — this window is waiting for it, then it will update.",
    "updating": "TCC is closed — updating it now. This can take a few minutes.",
    "done": "Done — start TCC again. This window can be closed.",
    "failed": "The update did not finish — the lines above say why.",
}

#: Cursor home, clear the screen, clear the scrollback. The last one matters: `clear` alone leaves
#: the typed line one scroll away in Terminal.app, and ESC[3J is honoured by Terminal and iTerm.
_CLEAR_SCREEN = r"\033[H\033[2J\033[3J"


def _is_windows(platform: Optional[str]) -> bool:
    return (platform or sys.platform).startswith("win")


def _cmd_echo(text: str) -> str:
    """`echo` of a sentence in a batch file: cmd's operators escaped and `%` doubled, so a
    translation carrying `&` prints it instead of running what follows."""
    for char in "^&|<>":
        text = text.replace(char, "^" + char)
    return "echo " + text.replace("%", "%%")


def tcc_install_script(pid: Optional[int] = None, tag: str = "", *,
                       words: Optional[dict] = None, platform: Optional[str] = None) -> str:
    """The update as the text of a script: the person's lines, the wait, the install, the result.

    **A script run by name, and its first act is to clear the window** (hub #221 ask 3, skill
    #94). The update used to be one shell line TYPED into the terminal, and zsh echoes what is
    typed: `echo 'Close TCC now…'; while kill -0 …; uv tool install … @v0.1.44 …; echo …` filled
    the window, and the one sentence that mattered came last and was lost in it (the Arbiter:
    «можемо заховати зайве?»). Now the terminal types only `sh '<file>'` — or, on Windows, cmd is
    handed the file's name, which it does not echo — and the file clears the screen before it
    says anything. Nothing inside is echoed either: `sh` does not echo a script, and cmd does not
    after `@echo off`. What stays on screen is what to do now, then uv's own answer, then whether
    it worked.

    **It waits for THIS process before it installs.** Telling somebody to close the app first is
    not enough — it was tried, and the update ran anyway while the app was open. `uv` then replaced
    the package, tried to clear the old `Scripts` directory, and could not: the running executable
    is in it, and Windows will not delete a file that is open. It ends in `error: failed to remove
    directory … Access is denied (os error 5)` after appearing to succeed (user, Windows 11,
    2026-08-19). macOS would survive replacing the files under a running process, but not always
    cleanly — TCC imports lazily, so a module first needed after the swap would be read from a
    directory that is no longer the one it started with. One behaviour on both platforms is also
    one thing to explain.

    The install is one step between the wait and the result, `tcc_install_command(tag)`: a check
    of TCC's own tag (tcc#102) goes in front of it with its own line, and nothing else moves.
    """
    if pid is None:
        pid = os.getpid()
    said = {**TCC_WINDOW_WORDS, **(words or {})}
    command = tcc_install_command(tag)
    if _is_windows(platform):
        # UTF-8 with `chcp 65001`, so the Arbiter's language arrives whole (the file is written
        # UTF-8, and cmd decodes each line it reads with the code page current at that moment).
        # `call`, so a `uv.cmd` shim would return here instead of ending the script. `goto`
        # rather than an `if (…) else (…)` block, where a `)` in a translation would close it.
        # Wait-Process returns at once if the id is already gone — TCC closed first.
        lines = [
            "@echo off",
            "chcp 65001 >nul",
            "cls",
            _cmd_echo(said["wait"]),
            f'powershell -NoProfile -Command "Wait-Process -Id {pid} -ErrorAction SilentlyContinue"',
            _cmd_echo(said["updating"]),
            f"call {command}",
            "if errorlevel 1 goto failed",
            "echo.",
            _cmd_echo(said["done"]),
            "goto :eof",
            ":failed",
            "echo.",
            _cmd_echo(said["failed"]),
        ]
    else:
        say = "printf '%s\\n' {}".format
        lines = [
            "#!/bin/sh",
            "# TCC's update, written by TCC for the terminal it opened (core/updates.py).",
            f"printf '{_CLEAR_SCREEN}'",
            say(shlex.quote(said["wait"])),
            f"while kill -0 {pid} 2>/dev/null; do sleep 1; done",
            say(shlex.quote(said["updating"])),
            f"if {command}; then",
            "  echo; " + say(shlex.quote(said["done"])),
            "else",
            "  echo; " + say(shlex.quote(said["failed"])),
            "fi",
        ]
    return "\n".join(lines) + "\n"


def write_tcc_install_script(pid: Optional[int] = None, tag: str = "", *,
                             words: Optional[dict] = None, folder: Optional[Path] = None,
                             platform: Optional[str] = None) -> Path:
    """`tcc_install_script` in a file, for `terminal_launcher.run_script` to run by name.

    A fresh folder of this user's each time (`mkdtemp`, mode 0700): nobody else's file can be
    standing where ours is about to be run. CRLF for the batch file, because cmd reads one by
    line; UTF-8 for both.
    """
    windows = _is_windows(platform)
    folder = Path(folder) if folder else Path(tempfile.mkdtemp(prefix="autosound-tcc-update-"))
    path = folder / ("tcc-update.cmd" if windows else "tcc-update.sh")
    path.write_text(tcc_install_script(pid, tag, words=words, platform=platform),
                    encoding="utf-8", newline="\r\n" if windows else "\n")
    return path


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


#: An environment in which git CANNOT stop to ask. This runs in a daemon thread of a GUI app,
#: polled by a timer, and git's answer to a repository it cannot read is to ask for credentials —
#: on Windows through Git Credential Manager, which is a WINDOW. Nobody is looking at it: the
#: person sees a tall dialog appear over their tune, or a check that never returns (TCC-006, and
#: the user's own "a tall stretched Windows window and then a terminal one", 2026-09-09).
#:
#: All three, because they are three different doors: `GIT_TERMINAL_PROMPT` closes git's own
#: prompt, `GCM_INTERACTIVE` closes the credential manager's dialog, and an empty `GIT_ASKPASS`
#: stops git reaching for a GUI helper. An update check that cannot be answered is silent, which
#: is what it is supposed to be when offline anyway.
_NO_PROMPTING = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GIT_ASKPASS": ""}


_log = logging.getLogger("autosound_tcc")


def _git(*args: str, cwd: Optional[Path] = None) -> tuple[bool, str]:
    """Run git, return `(ok, output)`. Never raises — a failed probe is an answer, not a crash."""
    try:
        done = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=_ASK_TIMEOUT,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, **_NO_PROMPTING},
            # Plain `quiet()`. This used to merge in a console of its own, on the theory that
            # `ls-remote` spawns `git-remote-https` and a grandchild with no console allocates
            # one. Watched on the machine that has the problem (2026-09-11), it does not: across
            # a stepped startup and two window watches, `git ls-remote` produced NO window at all,
            # while `agy` produced one every time. The startup flash was agy, and it is gone
            # because agy is no longer asked at startup (`core/model_choices.refresh_cli_catalogue`).
            # A console handed to git would now be a window we create for nothing.
            check=False, cwd=str(cwd) if cwd else None,
            **child.quiet())
    except Exception as exc:  # noqa: BLE001 — no git, no network, a hung server
        # Logged HERE too, and that is the point: this path returns before the one below, so a
        # missing git and a timed-out probe were the two failures that left no line at all while
        # the window said "could not reach GitHub" (2026-09-20).
        _log.warning("git %s did not run: %s: %s", " ".join(args), type(exc).__name__, exc)
        return False, f"{type(exc).__name__}: {exc}"
    out = (done.stdout or "").strip() or (done.stderr or "").strip()
    if done.returncode != 0:
        # The log used to record that git was SPAWNED and never what it answered, so every failure
        # reached the window as one sentence — "could not reach GitHub" — covering a missing git, a
        # dead network, a refusing server and a bad URL alike. On the Arbiter's machine the log
        # showed `spawn: git ls-remote` and the next line ELEVEN milliseconds later: not a network
        # round trip, an immediate failure, and nothing said which one (2026-09-20).
        _log.warning("git %s exited %s: %s", " ".join(args), done.returncode, out or "(no output)")
    return done.returncode == 0, out


def _version_key(text: str) -> tuple:
    """`v3.0.10` -> (3, 0, 10), so 3.0.10 sorts after 3.0.9 — which a string compare gets wrong."""
    return tuple(int(part) for part in re.findall(r"\d+", text)) or (0,)


_RELEASE_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
_CANDIDATE_RE = re.compile(r"beta-v(\d+)\.(\d+)\.(\d+)-rc(\d+)")


def channel_key(name: str) -> Optional[tuple[int, int, int, int, int]]:
    """The order on the beta channel (hub RELEASE-CHANNEL.md §11.2); None for a name of neither shape.

    A release `vX.Y.Z` is `(X, Y, Z, 1, 0)` and a candidate `beta-vX.Y.Z-rcN` is `(X, Y, Z, 0, N)`:
    a release above its own candidates, candidates of one version by N — `rc10` above `rc2`, which
    a string compare gets wrong — and a candidate for 3.1.0 above 3.0.49. The same key as the
    method's installers (`newest_on_channel`, HUB-060), so the app and `install.sh --channel beta`
    agree on what "newest" is.
    """
    if match := _RELEASE_RE.fullmatch(name):
        return (int(match[1]), int(match[2]), int(match[3]), 1, 0)
    if match := _CANDIDATE_RE.fullmatch(name):
        return (int(match[1]), int(match[2]), int(match[3]), 0, int(match[4]))
    return None


#: What the last `ls-remote` said when it failed, so a caller can put WHY in front of a person
#: instead of "could not reach GitHub". Set by `_newest_tag_in` and read immediately after it, on
#: the same thread — `check_all` asks its two questions in order, never at once.
#:
#: The sentence it replaces cost a session: on the Arbiter's Mac `git` itself could not run (an
#: `xcrun` error about a missing architecture, printed in full two lines lower in the very same
#: dialog), and the update row blamed GitHub — so both of us went and checked the network.
_last_probe_error = ""


def last_probe_error() -> str:
    """Git's own words from the last failed probe, or "" when the last one worked."""
    return _last_probe_error


def _newest_tag_in(repo: str, *globs: str, key=_version_key) -> tuple[str, str]:
    """The newest tag matching any of `globs` in `repo`, and the COMMIT it names. `("", "")` if unaskable.

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

    Several globs are one `ls-remote`, each with its own peel pattern, for the same reason. `key`
    orders the names and drops the ones it answers None for — the beta channel passes
    `channel_key`; stable keeps `_version_key`, which drops nothing.
    """
    global _last_probe_error
    patterns = [pattern for glob in globs for pattern in (glob, f"{glob}^{{}}")]
    ok, out = _git("ls-remote", "--tags", repo, *patterns)
    _last_probe_error = "" if ok and out else (out or "no tag matched")
    if ok and not out:
        # Exit 0 and NOTHING back is a third answer, and it used to read as the same "could not
        # reach GitHub" as a failure — while `_git`'s own log, which only speaks on a non-zero
        # exit, stayed silent. So the row blamed the network for a repository that answered
        # perfectly well and matched no tag (2026-09-20, chasing the Arbiter's update row).
        _log.warning("git ls-remote %s matched nothing for %s — the repo answered, the patterns "
                     "did not", repo, " ".join(patterns))
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
    ranked = {name: sha for name, sha in shas.items() if key(name) is not None}
    if not ranked:
        return "", ""
    newest = max(ranked, key=key)
    return newest, ranked[newest]


def newest_tag() -> str:
    """The newest `v3.*` tag in the method's repository, or "" if it cannot be asked."""
    return _newest_tag_in(SKILL_REPO, SKILL_TAG_GLOB)[0]


def newest_tcc_tag(channel: str = STABLE) -> str:
    """The newest tag of TCC itself on `channel` — a release, or on beta possibly a candidate — or ""."""
    if channel == BETA:
        return _newest_tag_in(TCC_REPO, TCC_TAG_GLOB, TCC_BETA_GLOB, key=channel_key)[0]
    return _newest_tag_in(TCC_REPO, TCC_TAG_GLOB)[0]


def _skill_repo_dir() -> Optional[Path]:
    """The method's git repository root, through the installer's symlink or junction."""
    try:
        return vendor_loader.skill_repo_root()
    except Exception:  # noqa: BLE001
        return None


def _is_ours(repo: Path) -> tuple[bool, tuple[str, str]]:
    """Whether this checkout is the installer's to move, and if not, why not.

    The installer parks its clone on a tag, detached. A developer's clone sits on a branch, or is a
    submodule of somebody's checkout. Moving THAT would throw away somebody's work — the skill's
    `keep-local` resets what it keeps — so the two are told apart before anything runs, the same
    care `install.sh` takes before it touches `~/.claude/skills/autosound-tuning`. Read-only git:
    nothing here changes the clone.

    **Local changes no longer make a clone "not ours"** (tcc#91, SKL-056). They did, through a
    `status --porcelain` here, and a session's patch to `rew_tool/contract.py` on the Windows VM
    left the Arbiter with «має незакомічені зміни, тому не чіпаю» over a grey button and no next
    step without git by hand. The skill's `upkeep.py` names them now (`local_changes()`) and keeps
    them as a patch before it resets anything (`apply_skill(keep_local=True)`).
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
    already turned away everything except the detached clone the installer parked on a tag.
    Whether that clone carries local changes is asked only when the button is pressed
    (`local_changes()`): the skill's `status` takes up to a minute, and every check would pay it.
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



def check_tcc(channel: str = STABLE) -> Status:
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

    On the beta channel the comparison is by commit instead (`_check_tcc_on_beta`).
    """
    version = install_report.app_version()
    _url, commit = install_report.install_source()
    if not commit:
        return Status("tcc", version, "", False, "source_checkout", updatable=False)
    if channel == BETA:
        return _check_tcc_on_beta(version, commit)
    tag = newest_tcc_tag()
    if not tag:
        # WHY, not just "no". `git` unable to run at all is a different problem from a network
        # that is down, and the window had git's own sentence in hand while saying the second.
        return Status("tcc", version, "", False, "probe_failed", last_probe_error())
    latest = tag.lstrip("v")
    if not version:
        # No metadata to compare with: fall back to what is on offer, and let the person decide.
        return Status("tcc", version, latest, True)
    if _version_key(version) >= _version_key(latest):
        return Status("tcc", version, version, False)
    return Status("tcc", version, latest, True)


def _check_tcc_on_beta(version: str, commit: str) -> Status:
    """On beta TCC is compared by COMMIT, the way the method always is.

    A candidate writes nothing — `make ship CANDIDATE=` tags HEAD — so an app built from
    `beta-v0.2.0-rc1` may carry the version of the release before it, and a version compare would
    offer rc1 to an installation that already is rc1, forever. So: the commit of the newest tag on
    the channel is current; a version above that tag's X.Y.Z is a build ahead of the releases,
    current too (the rule `check_tcc` keeps on stable); anything else is newer — rc2 over rc1, and
    the release cut on top of its candidates. Equal X.Y.Z is NOT ahead: under waves the version is
    committed before the tag (hub #148), so rc1 can already say 0.2.0.
    """
    tag, sha = _newest_tag_in(TCC_REPO, TCC_TAG_GLOB, TCC_BETA_GLOB, key=channel_key)
    if not tag:
        return Status("tcc", version, "", False, "no_network")
    installed = install_report.shown_version(version, install_report.requested_revision())
    latest = tag.removeprefix("beta-").removeprefix("v")
    if sha == commit:
        return Status("tcc", installed, latest, False, installed_sha=commit, latest_sha=sha)
    if version and _version_key(version)[:3] > channel_key(tag)[:3]:
        return Status("tcc", installed, version, False, installed_sha=commit, latest_sha=sha)
    return Status("tcc", installed, latest, True, installed_sha=commit, latest_sha=sha)


def check_all(channel: str = STABLE) -> tuple[Status, Status]:
    """Both halves. Two network calls; run it off the GUI thread.

    The channel reaches TCC's half only: the method follows released tags on both channels until
    its beta copy is wired (hub #145 answer, `installation.md` "Two channels on one machine").
    """
    return check_tcc(channel), check_skill()


def channel_for(saved: str, revision: str) -> str:
    """The channel to follow: the saved choice, or — never chosen — what the app was installed from.

    Installed from a `beta-v*` tag and never set → beta: `install.sh --channel beta` put a candidate
    here, and moving its tester to stable at the first update check, without a word, would undo
    that (the Arbiter, 2026-09-14). An unknown saved value reads as stable.
    """
    if saved in (STABLE, BETA):
        return saved
    if not saved and revision.startswith("beta-v"):
        return BETA
    return STABLE


def current_channel() -> str:
    """`channel_for` on this installation. Reads QSettings: call it on the GUI thread, pass the value."""
    return channel_for(config.update_channel(), install_report.requested_revision())


# ---- the skill's own updater (hub #221 SKL-059, hub #217 SKL-056) -------------------------------

#: How long each of `upkeep.py`'s commands may take before TCC stops waiting. Its own inner
#: timeouts, plus room: `status` asks Homebrew and GitHub about the tools too ("up to about a
#: minute", the contract on hub #217); `clone` fetches with 300 s; `libs` lets pip take 900 s over
#: a network that may be a phone in a car park.
_UPKEEP_TIMEOUT = {"status": 150.0, "keep-local": 180.0, "clone": 360.0, "libs": 960.0}


def upkeep_script() -> Optional[Path]:
    """The skill's `scripts/upkeep.py`, from the skill TCC uses, or None when it has none.

    Found the way every other script of the skill is (`contract_check.script_path()`): through
    `vendor_loader.skill_dir()`, which is the vendored submodule in a checkout and the INSTALLED
    skill everywhere else — TCC's wheel carries no copy of the skill on purpose (`vendor_loader`).
    So an installed skill older than v3.0.64, where the script arrived, has none: that is
    `no_upkeep`, said on the row, and never a git fallback — TCC does not move the clone with git
    any more (hub #221).
    """
    try:
        path = vendor_loader.skill_dir() / "scripts" / "upkeep.py"
    except Exception:  # noqa: BLE001 — no skill at all is the same answer
        return None
    return path if path.is_file() else None


def _run_upkeep(argv: list[str], timeout: float) -> tuple[int, str, str]:
    """`(exit code, stdout, stderr)` of one `upkeep.py` run; -1 when it did not run at all.

    `child_env`: UTF-8 on the pipe whatever the Windows code page (the skill's paths and sentences
    arrive whole), and no `__pycache__` written into the clone — `git status` would name those as
    the person's changes. `_NO_PROMPTING`: `clone` fetches, and git must not stop to open a
    credential window over the app (TCC-006).
    """
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False, env=vendor_loader.child_env(**_NO_PROMPTING),
            **child.quiet())
    except Exception as exc:  # noqa: BLE001 — no interpreter, a timeout: an answer, not a crash
        return -1, "", f"{type(exc).__name__}: {exc}"
    return done.returncode, done.stdout or "", done.stderr or ""


@dataclass(frozen=True)
class Upkeep:
    """One `upkeep.py --json` run. `reason` is a key, the way `Status.reason` is."""

    ok: bool
    #: The object it printed — also on a failed step (`libs` exits 3 with its own `why`).
    data: dict
    #: "" · "refused" (`detail` is the skill's sentence) · "no_upkeep" · "upkeep_failed".
    reason: str = ""
    detail: str = ""


def _upkeep(command: str, *args: str, clone: Path) -> Upkeep:
    """Run `upkeep.py --json --clone <clone> <command> [args]` and read its answer.

    `--json` and `--clone` BEFORE the command (the contract on hub #217 and #219), on the
    interpreter TCC runs on — its console twin on Windows, so git under it opens no window
    (`child.script_interpreter`). Exit 3 with `{"ok": false, "refused": …}` is a refusal whose
    sentence goes on screen as the skill wrote it; exit 3 with any other object is a step that
    failed and says why in its own fields.
    """
    script = upkeep_script()
    if script is None:
        return Upkeep(False, {}, "no_upkeep")
    argv = [child.script_interpreter(), str(script), "--json", "--clone", str(clone), command, *args]
    code, out, err = _run_upkeep(argv, _UPKEEP_TIMEOUT.get(command, 300.0))
    try:
        data = json.loads(out) if out.strip() else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        said = (err.strip() or out.strip()).splitlines()
        _log.warning("upkeep %s exited %s with no JSON: %s", command, code,
                     said[-1] if said else "(no output)")
        return Upkeep(False, {}, "upkeep_failed", said[-1] if said else f"exit {code}")
    if data.get("ok") is False and "refused" in data:
        _log.warning("upkeep %s refused: %s", command, data["refused"])
        return Upkeep(False, data, "refused", str(data["refused"]))
    _log.info("upkeep %s: exit %s", command, code)
    return Upkeep(code == 0, data, "" if code == 0 else "upkeep_failed")


def _ours_to_run(repo: Optional[Path]) -> tuple[str, str]:
    """`("", "")` when the skill's updater may act on `repo`, else the reason key and its detail."""
    if repo is None:
        return "not_found", ""
    ours, (why, detail) = _is_ours(repo)
    if not ours:
        return why, detail
    if upkeep_script() is None:
        return "no_upkeep", ""
    return "", ""


@dataclass(frozen=True)
class LocalChanges:
    """What the installed clone carries that its release does not, as `upkeep.py status` names it."""

    ok: bool
    changed: tuple[str, ...] = ()
    reason: str = ""
    detail: str = ""


def local_changes() -> LocalChanges:
    """The clone's changed files, asked of the skill (`upkeep.py status`) — slow, run it off the
    GUI thread. It replaces the `status --porcelain` TCC used to run itself (tcc#91)."""
    repo = _skill_repo_dir()
    why, detail = _ours_to_run(repo)
    if why:
        return LocalChanges(False, reason=why, detail=detail)
    answer = _upkeep("status", clone=repo)
    if not answer.ok:
        return LocalChanges(False, reason=answer.reason, detail=answer.detail)
    clone = answer.data.get("clone") or {}
    if clone.get("error"):
        return LocalChanges(False, reason="upkeep_failed", detail=str(clone["error"]))
    if clone.get("exists") is False:
        return LocalChanges(False, reason="not_found", detail=str(clone.get("path") or ""))
    return LocalChanges(True, tuple(str(name) for name in clone.get("changed") or ()))


@dataclass(frozen=True)
class SkillUpdate:
    """What «Update the method» did: where the clone landed, and what happened on the way."""

    ok: bool
    #: A key when not ok, as `Status.reason`; `detail` is the skill's own sentence or data.
    reason: str = ""
    detail: str = ""
    #: The tag the clone is at now, as `git describe` names it ("v3.0.64").
    version: str = ""
    #: The skill's line about the tag's signature (skill #99), shown as it wrote it.
    signature: str = ""
    #: Where `keep-local` put the local changes; "" when there were none to keep.
    patch: str = ""
    #: `keep-local`'s answer about the send: None (not asked), `{"sent": True, "url"}`, or
    #: `{"sent": False, "why"}`.
    sent: Optional[dict] = None
    #: `libs`: None when it did not run, else whether it worked; `libs` is what moved ("numpy
    #: 2.0.2 → 2.1.0", "" when nothing did) or, when it failed, why.
    libs_ok: Optional[bool] = None
    libs: str = ""


def _libs_moved(data: dict) -> str:
    before, after = data.get("before") or {}, data.get("after") or {}
    return ", ".join(f"{name} {before.get(name) or '—'} → {version}"
                     for name, version in after.items() if version and version != before.get(name))


def apply_skill(tag: str = "", *, keep_local: bool = False, send: bool = False) -> SkillUpdate:
    """Move the method's clone onto `tag` (default: the newest release) with the skill's own
    `upkeep.py`: `keep-local` first when asked, then `clone`, then `libs` (hub #221, tcc#91).

    `clone` fetches the tag into `refs/tags`, so `git describe` names it afterwards (skill #92 —
    the bare-name fetch this function used to run moved HEAD and stored no tag), and checks its
    signature against the skill author's key (skill #99). `libs` follows in the same press, so
    numpy, scipy and matplotlib move with the skill that uses them (skill #98).

    `keep_local` runs `keep-local` BEFORE the clone moves: the patch is on disk, and checked to
    hold exactly the changes, before the skill's own reset — TCC resets nothing itself. `send` is
    the person's yes to sending that patch to the skill as an issue; only then does `--send` go,
    because it leaves the machine. A refusal at any step stops the steps after it, and whatever
    was already done (the kept patch) is still in the answer.
    """
    repo = _skill_repo_dir()
    why, detail = _ours_to_run(repo)
    if why:
        return SkillUpdate(False, why, detail)
    patch, sent = "", None
    if keep_local:
        kept = _upkeep("keep-local", *(["--send"] if send else []), clone=repo)
        if not kept.ok:
            return SkillUpdate(False, kept.reason, kept.detail)
        patch, sent = str(kept.data.get("patch") or ""), kept.data.get("sent")
    target = tag or newest_tag()
    # No tag known (offline) is left to the skill, which asks for the newest itself and refuses
    # in its own sentence when it cannot.
    moved = _upkeep("clone", *(["--tag", target] if target else []), clone=repo)
    if not moved.ok:
        return SkillUpdate(False, moved.reason, moved.detail, patch=patch, sent=sent)
    libs = _upkeep("libs", clone=repo)
    libs_ok = libs.ok and bool(libs.data.get("ok", True))
    return SkillUpdate(
        True,
        version=str(moved.data.get("to") or target),
        signature=str(moved.data.get("signature") or ""),
        patch=patch, sent=sent,
        libs_ok=libs_ok,
        libs=_libs_moved(libs.data) if libs_ok
        else str(libs.data.get("why") or libs.detail or libs.reason),
    )
