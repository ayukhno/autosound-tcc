"""Is there a newer TCC, is there a newer method, and what installs it.

Two questions a tester should never have to ask in a chat. The versions are already on screen
(`core/install_report.py`); this adds the other half — what is on the server — and the one command
that closes the gap.

**The two halves are installed differently, so they update differently.**

*The method* is a shallow git checkout parked on a release tag (`v3.*`). It moves through the
skill's OWN `scripts/upkeep.py` (hub #221, SKL-059; hub #217, SKL-056) — the copy inside the tag
being installed, the way the skill's installers run it: the tag is fetched into the clone (objects
and refs; the working tree is not touched), its signature checked, its `upkeep.py` taken into a
temporary folder and run there. `keep-local` keeps a local change as a patch before anything is
reset, `clone` checks the tag out, `libs` brings numpy, scipy and matplotlib along. TCC checks
nothing out and resets nothing itself; it runs the skill's commands off the GUI thread and shows
what they answer.

*TCC* is a `uv` tool, and updating it means replacing the files of the process doing the asking.
On macOS that quietly works and takes effect at the next start; on Windows it cannot — the running
`.exe` and its loaded DLLs are locked, and `uv` would fail in the middle with a permission error
that reads like a bug. So TCC's update is handed to a terminal the person can watch and told to
run after the app is closed. Which is also the honest shape: it downloads several hundred
megabytes, and that belongs in a window with output, not behind a spinner. `uv` cannot check a
signature, so before the window gets anything TCC checks its own tag the way the method's is
checked (`prepare_tcc_update`, tcc#102): a tag that does not verify gets no script at all.

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
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autosound_tcc.core import child, config, install_report, vendor_loader
from autosound_tcc.core.signed_tags import (SKIP_VERIFY_VAR, TCC_SIGNED_FROM, TCC_SIGNING_KEY,
                                            TCC_SIGNING_PRINCIPAL, allowed_signers_line)

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
    "moved": "The new version changed after it was checked, or the server did not answer — "
             "nothing was installed. Start TCC and press «Update TCC» again.",
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
                       words: Optional[dict] = None, platform: Optional[str] = None,
                       sha: str = "") -> str:
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

    The install is one step between the wait and the result, `tcc_install_command(tag)`. TCC's own
    tag is checked before this script is written at all (`prepare_tcc_update`, tcc#102): a tag
    that does not verify gets no script.

    **`sha` is the commit that check verified, and the script holds uv to it** (review of
    tcc#102). The check runs when the button is pressed; uv resolves the tag NAME only after the
    person has quit TCC, which may be much later. So, right before uv, the script asks the remote
    what the tag's peeled `^{}` line names now, and installs nothing unless it is that commit — a
    tag moved since, a lightweight tag put in its place (no `^{}` line), or no answer all end in
    the `moved` line. uv itself is not pinned to the sha: the tag name is what
    `install_report.requested_revision` reads back — the shown version, the channel, the guide
    link. No `sha` (a release from before signing, the developer's switch): nothing was verified,
    so there is nothing to hold uv to.
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
        # The check before uv: `for /f` reads the first field of git's one line, and an empty
        # answer compares unequal, so it fails closed. `2^>nul` is the redirect escaped into the
        # child command; `^{}` sits inside double quotes, where cmd leaves a caret alone.
        guard = [
            "set GIT_TERMINAL_PROMPT=0",
            'set "tcc_now="',
            f"for /f \"tokens=1\" %%a in ('git ls-remote \"{TCC_REPO}\" "
            f"\"refs/tags/{tag}^{{}}\" 2^>nul') do set \"tcc_now=%%a\"",
            f'if not "%tcc_now%"=="{sha}" goto moved',
        ] if sha else []
        lines = [
            "@echo off",
            "chcp 65001 >nul",
            "cls",
            _cmd_echo(said["wait"]),
            f'powershell -NoProfile -Command "Wait-Process -Id {pid} -ErrorAction SilentlyContinue"',
            *guard,
            _cmd_echo(said["updating"]),
            f"call {command}",
            "if errorlevel 1 goto failed",
            "echo.",
            _cmd_echo(said["done"]),
            "goto :eof",
            *([":moved", "echo.", _cmd_echo(said["moved"]), "goto :eof"] if sha else []),
            ":failed",
            "echo.",
            _cmd_echo(said["failed"]),
        ]
    else:
        say = "printf '%s\\n' {}".format
        guard = [
            f"now=$(GIT_TERMINAL_PROMPT=0 git ls-remote {shlex.quote(TCC_REPO)} "
            f"{shlex.quote(f'refs/tags/{tag}^{{}}')} 2>/dev/null | cut -f1)",
            f'if [ "$now" != {shlex.quote(sha)} ]; then',
            "  " + say(shlex.quote(said["moved"])),
            "  exit 1",
            "fi",
        ] if sha else []
        lines = [
            "#!/bin/sh",
            "# TCC's update, written by TCC for the terminal it opened (core/updates.py).",
            f"printf '{_CLEAR_SCREEN}'",
            say(shlex.quote(said["wait"])),
            f"while kill -0 {pid} 2>/dev/null; do sleep 1; done",
            *guard,
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
                             platform: Optional[str] = None, sha: str = "") -> Path:
    """`tcc_install_script` in a file, for `terminal_launcher.run_script` to run by name.

    A fresh folder of this user's each time (`mkdtemp`, mode 0700): nobody else's file can be
    standing where ours is about to be run. CRLF for the batch file, because cmd reads one by
    line; UTF-8 for both.
    """
    windows = _is_windows(platform)
    folder = Path(folder) if folder else Path(tempfile.mkdtemp(prefix="autosound-tcc-update-"))
    path = folder / ("tcc-update.cmd" if windows else "tcc-update.sh")
    path.write_text(tcc_install_script(pid, tag, words=words, platform=platform, sha=sha),
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


def _git(*args: str, cwd: Optional[Path] = None,
         timeout: float = _ASK_TIMEOUT) -> tuple[bool, str]:
    """Run git, return `(ok, output)`. Never raises — a failed probe is an answer, not a crash."""
    try:
        done = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=timeout,
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


#: The skill's trust anchor, as its own `upkeep.py` and both installers hold it (skill #99, hub
#: #82 HUB-031): a CONSTANT, never a file read from the tag being verified — a tag's own
#: `allowed_signers` would vouch for itself. Tags before `SKILL_SIGNED_FROM` predate signing and
#: pass with a line saying so. `tests/test_updates.py` compares these with the vendored script's.
#: TCC's own anchor and the developer's switch `SKIP_VERIFY_VAR`, one name for both checks, are
#: `core/signed_tags.py`'s (tcc#102), imported above.
SKILL_SIGNING_PRINCIPAL = "ayukhno"
SKILL_SIGNING_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHLm4x1yz9JbFfBlxdQA8vR8yYMupVktswes3CL7QE1y"
SKILL_SIGNED_FROM = "v3.0.64"

#: Where the method lives inside its repository, and what of the NEW tag is taken out to run its
#: updater: `upkeep.py` and the two files it imports — the installers' own list (install.sh
#: `keep_local`, install.ps1 `Save-LocalChanges`, v3.0.64) — plus `requirements.txt`, which `libs`
#: reads beside it. The installers run `libs` from the clone; TCC runs it from here.
_SKILL_IN_REPO = "skills/autosound-tuning"
_UPKEEP_FILES = ("scripts/upkeep.py", "rew_tool/gates/side_effect.py", "rew_tool/console.py",
                 "requirements.txt")

#: A fetch of one release over a network that may be a phone: `upkeep.py`'s own fetch allows 300 s.
_FETCH_TIMEOUT = 300.0


#: What a git that CANNOT check an SSH signature says, as install.sh v3.0.64 `verify_tag` matches
#: it (`*gpg.format*|*"unknown option"*|*"-Y"*`, "this git may be too old"): a git before 2.34 does
#: not know `gpg.format=ssh`, an ssh-keygen without `-Y` answers "unknown option", and git itself
#: names `ssh-keygen -Y` when it is missing. Plus no ssh-keygen at all — "cannot run" on macOS and
#: Linux, "cannot spawn" in Git for Windows. Not a bad signature — a machine that cannot look —
#: and on the VM, with an older git, it read as a forged release.
_CANNOT_CHECK = ("gpg.format", "unknown option", "-Y", "cannot run ssh-keygen",
                 "cannot spawn ssh-keygen")


def _release_key(name: str) -> Optional[tuple[int, ...]]:
    """`v3.0.64` -> (3, 0, 64); None for any other name — the skill's `tag_key`."""
    match = _RELEASE_RE.fullmatch(name)
    return tuple(map(int, match.groups())) if match else None


def _verdict_by_name(tag: str, signed_from: str, order) -> Optional[tuple[bool, str, str]]:
    """What can be said of `tag` without git, as `_verify_tag` says it — or None when the
    signature itself has to be checked. So a caller that must first FETCH the tag (TCC's own,
    `check_tcc_tag`) fetches nothing for a release that predates signing."""
    if os.environ.get(SKIP_VERIFY_VAR) == "1":
        return True, f"signature NOT checked: {SKIP_VERIFY_VAR}=1 is set (a developer's switch)", ""
    here, first = order(tag), order(signed_from)
    if here is None or first is None:
        return (False, f"{tag!r} is not a release tag (vX.Y.Z), so there is no signature to check",
                "bad_signature")
    # The version triple, not the whole key: on TCC's channel a candidate sorts below its own
    # release, and `beta-v0.1.45-rc1` — signed by the same `make ship` — would read as older than
    # v0.1.45 and pass unchecked (review of tcc#102).
    if here[:3] < first[:3]:
        return True, (f"{tag} predates signed tags (they start at {signed_from}): installed "
                      f"without a signature check"), ""
    return None


def _verify_tag(repo: Path, tag: str, *, signed_from: str = SKILL_SIGNED_FROM,
                principal: str = "", signing_key: str = "",
                order=_release_key) -> tuple[bool, str, str]:
    """`(ok, the line to show, reason key when not ok)` for `tag` in `repo`, by the skill's
    `verify_tag` rules — for the method's tags by default, for TCC's with its own anchor, first
    signed tag and channel order (`check_tcc_tag`).

    Good signature by the constant's key: ok. A release before `signed_from`: ok, and the line
    says it predates signing. The developer's switch skips it, and the line says so. Anything else
    at or after it is refused: `git_too_old` when git could not check at all (`_CANNOT_CHECK`),
    `bad_signature` for an unsigned tag, a stranger's key, a name that is not a release — in git's
    own words either way.

    Only the SSH form of git's answer counts as good (`Good "git" signature …`): the check forces
    `gpg.format=ssh`, and a GPG signature that some key on this machine happens to vouch for
    (`Good signature from …`) is not the author's key.
    """
    principal = principal or SKILL_SIGNING_PRINCIPAL
    signing_key = signing_key or SKILL_SIGNING_KEY
    early = _verdict_by_name(tag, signed_from, order)
    if early is not None:
        return early
    with tempfile.TemporaryDirectory(prefix="autosound_signers_") as tmp:
        signers = Path(tmp) / "allowed_signers"
        signers.write_text(allowed_signers_line(principal, signing_key) + "\n", encoding="utf-8")
        ok, said = _git("-c", "gpg.format=ssh", "-c", f"gpg.ssh.allowedSignersFile={signers}",
                        "verify-tag", tag, cwd=repo)
    if ok and 'Good "git" signature' in said:
        return True, f"{tag}: signature good ({principal})", ""
    last = (said.splitlines() or ["git verify-tag failed"])[-1]
    if any(mark in said for mark in _CANNOT_CHECK):
        _known, version = _git("--version")
        return False, f"{version or 'git'}: {last}", "git_too_old"
    return False, f"{tag}: {last}", "bad_signature"


def _git_blob(repo: Path, spec: str) -> Optional[bytes]:
    """`git show <tag>:<path>` as BYTES, or None when the tag has no such file.

    Bytes, not text: a file is copied out of the tag as it is, the way install.ps1 takes a zip
    rather than let PowerShell decode it through the console's code page."""
    try:
        done = subprocess.run(["git", "-C", str(repo), "show", spec], capture_output=True,
                              timeout=_ASK_TIMEOUT, check=False,
                              env={**os.environ, **_NO_PROMPTING}, **child.quiet())
    except Exception:  # noqa: BLE001 — no git: the same as no file
        return None
    return done.stdout if done.returncode == 0 else None


@dataclass(frozen=True)
class Extracted:
    """The new tag's `upkeep.py`, taken out to run — or why there is none to run."""

    script: Optional[Path]
    #: A key when `script` is None, as `Status.reason`; `detail` is git's words or the line.
    reason: str = ""
    detail: str = ""
    #: TCC's own line about the tag's signature — shown on the row when `upkeep.py clone` gives
    #: none, so the developer's switch and a release from before signing are never silent (HUB-032).
    signature: str = ""


def _extract_upkeep(repo: Path, tag: str, root: Path) -> Extracted:
    """Fetch `tag` into the clone, check it, take its `upkeep.py` out into `root`.

    Exactly the installers' order (install.sh
    `checkout_method` → `verify_tag` → `keep_local`): what was fetched is checked BEFORE anything of
    it runs — the script about to run comes from this tag, and a script that checks its own
    signature has checked nothing. `upkeep.py clone` checks it again; that one is the skill's.

    The fetch writes objects and `refs/tags/<tag>` into the clone and nothing else: the working
    tree, the index and HEAD are as they were, local changes included (skill #92's refspec, so
    `describe` can name the tag later).
    """
    ok, said = _git("fetch", "--quiet", "--depth", "1", "origin",
                    f"+refs/tags/{tag}:refs/tags/{tag}", cwd=repo, timeout=_FETCH_TIMEOUT)
    if not ok:
        return Extracted(None, "fetch_failed", said)
    signed, line, why = _verify_tag(repo, tag)
    _log.info("skill tag %s: %s", tag, line)
    if not signed:
        return Extracted(None, why, line)
    for name in _UPKEEP_FILES:
        blob = _git_blob(repo, f"refs/tags/{tag}:{_SKILL_IN_REPO}/{name}")
        if blob is None:
            continue  # the installers' `|| true`: only upkeep.py itself is required
        target = root / _SKILL_IN_REPO / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    script = root / _SKILL_IN_REPO / "scripts" / "upkeep.py"
    if not script.is_file():
        # A release from before the script (v3.0.64): nothing to run, and no git fallback — the
        # skill's installer is the one way across, once.
        return Extracted(None, "no_upkeep", signature=line)
    return Extracted(script, signature=line)


@contextmanager
def _upkeep_from_tag(repo: Path, tag: str):
    """Yields the `Extracted` `upkeep.py` of `tag`; the copy is removed after.

    The NEW tag's script, not the clone's own: the clones on the Arbiter's machines (3.0.61 on the
    VM, 3.0.63 on the Mac) predate the script altogether, and install.sh says the same of itself —
    "the clone's own version may predate the script". So the script is always as new as the skill
    being installed. TCC's wheel carries no copy of the skill (`vendor_loader`), so there is no
    third place it could come from.
    """
    root = Path(tempfile.mkdtemp(prefix="autosound-upkeep-"))
    try:
        yield _extract_upkeep(repo, tag, root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


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


def _upkeep(command: str, *args: str, clone: Path, script: Path) -> Upkeep:
    """Run `upkeep.py --json --clone <clone> <command> [args]` and read its answer.

    `--json` and `--clone` BEFORE the command (the contract on hub #217 and #219), on the
    interpreter TCC runs on — its console twin on Windows, so git under it opens no window
    (`child.script_interpreter`). Exit 3 with `{"ok": false, "refused": …}` is a refusal whose
    sentence goes on screen as the skill wrote it; exit 3 with any other object is a step that
    failed and says why in its own fields.
    """
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
    return "", ""


@dataclass(frozen=True)
class LocalChanges:
    """What the installed clone carries that its release does not, as `upkeep.py status` names it."""

    ok: bool
    changed: tuple[str, ...] = ()
    reason: str = ""
    detail: str = ""


def _target(tag: str) -> tuple[str, str]:
    """`(tag, "")`, or `("", git's words)` when no tag was given and the newest cannot be asked."""
    if tag:
        return tag, ""
    newest = newest_tag()
    return newest, "" if newest else (last_probe_error() or "no tag matched")


def local_changes(tag: str = "") -> LocalChanges:
    """The clone's changed files, as the `upkeep.py` of `tag` (default: the newest release) names
    them — `status`. Slow (a fetch, and `status` asks about the tools too): off the GUI thread. It
    replaces the `status --porcelain` TCC used to run itself (tcc#91)."""
    repo = _skill_repo_dir()
    why, detail = _ours_to_run(repo)
    if why:
        return LocalChanges(False, reason=why, detail=detail)
    target, said = _target(tag)
    if not target:
        return LocalChanges(False, reason="probe_failed", detail=said)
    with _upkeep_from_tag(repo, target) as got:
        if got.script is None:
            return LocalChanges(False, reason=got.reason, detail=got.detail)
        answer = _upkeep("status", clone=repo, script=got.script)
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
    """Move the method's clone onto `tag` (default: the newest release) with the `upkeep.py` of
    that tag (`_upkeep_from_tag`): `keep-local` first when asked, then `clone`, then `libs`, all
    with the one copy, removed afterwards (hub #221, tcc#91).

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
    target, said = _target(tag)
    if not target:
        return SkillUpdate(False, "probe_failed", said)
    with _upkeep_from_tag(repo, target) as got:
        if got.script is None:
            return SkillUpdate(False, got.reason, got.detail)
        return _apply_with(got, repo, target, keep_local=keep_local, send=send)


def _apply_with(got: Extracted, repo: Path, target: str, *, keep_local: bool,
                send: bool) -> SkillUpdate:
    """`apply_skill`'s steps, with the new tag's `upkeep.py` already in hand."""
    script = got.script
    patch, sent = "", None
    if keep_local:
        kept = _upkeep("keep-local", *(["--send"] if send else []), clone=repo, script=script)
        if not kept.ok:
            return SkillUpdate(False, kept.reason, kept.detail)
        patch, sent = str(kept.data.get("patch") or ""), kept.data.get("sent")
        # The receipt, where it survives the dialog being closed mid-update.
        _log.info("skill: local changes kept in %s; sent: %s", patch or "(none)", sent)
    moved = _upkeep("clone", "--tag", target, clone=repo, script=script)
    if not moved.ok:
        return SkillUpdate(False, moved.reason, moved.detail, patch=patch, sent=sent)
    _log.info("skill: %s -> %s (%s)", moved.data.get("from"), moved.data.get("to"),
              moved.data.get("signature") or got.signature)
    libs = _upkeep("libs", clone=repo, script=script)
    libs_ok = libs.ok and bool(libs.data.get("ok", True))
    return SkillUpdate(
        True,
        version=str(moved.data.get("to") or target),
        signature=str(moved.data.get("signature") or got.signature),
        patch=patch, sent=sent,
        libs_ok=libs_ok,
        libs=_libs_moved(libs.data) if libs_ok
        else str(libs.data.get("why") or libs.detail or libs.reason),
    )


# ---- TCC's own tag, checked before the terminal gets it (tcc#102, hub #83 HUB-032) -------------


def check_tcc_tag(tag: str) -> tuple[bool, str, str, str]:
    """`_verify_tag`'s answer for one of TCC's own tags — `(ok, the line to show, reason key,
    the commit the verified tag names)`, that commit "" when nothing was verified.

    `uv tool install … @<tag>` checks no signature, so the tag object is fetched first into a
    temporary BARE repository — TCC has no clone of itself to fetch into — and verified there
    against a temporary signers file written from the constant (`core/signed_tags.py`), never
    from a file in the tag. Both are removed on every path, a failed fetch included.

    TCC's first signed tag is `TCC_SIGNED_FROM`, and tags are ordered the way TCC's channel orders
    them (`channel_key`): a beta candidate is signed by the same `make ship` and checked like a
    release. A name the check can decide on alone — the developer's switch, a release from before
    signing — is decided without fetching anything.

    The commit comes back so the install script can hold uv to it (`tcc_install_script`): uv
    resolves the tag's NAME only after the person quits TCC. A verified tag whose commit git then
    cannot name is refused — fail closed, never "verified, but unpinned".
    """
    early = _verdict_by_name(tag, TCC_SIGNED_FROM, channel_key)
    if early is not None:
        return (*early, "")
    with tempfile.TemporaryDirectory(prefix="autosound-tcc-tag-", ignore_cleanup_errors=True) as tmp:
        repo = Path(tmp)
        ok, said = _git("init", "--quiet", "--bare", str(repo))
        if ok:
            ok, said = _git("fetch", "--quiet", "--no-tags", "--depth", "1", TCC_REPO,
                            f"+refs/tags/{tag}:refs/tags/{tag}", cwd=repo, timeout=_FETCH_TIMEOUT)
        if not ok:
            return False, said, "fetch_failed", ""
        ok, line, why = _verify_tag(repo, tag, signed_from=TCC_SIGNED_FROM,
                                    principal=TCC_SIGNING_PRINCIPAL, signing_key=TCC_SIGNING_KEY,
                                    order=channel_key)
        if not ok:
            return False, line, why, ""
        named, sha = _git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}", cwd=repo)
    if not named or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", sha):
        return False, f"{tag}: git names no commit for the verified tag ({sha})", "bad_signature", ""
    return True, line, "", sha


@dataclass(frozen=True)
class TccUpdate:
    """TCC's update made ready for the terminal — or why it was not. `Extracted`'s shape: the thing
    to run, or a reason key and git's words; and the signature line either way it passed."""

    script: Optional[Path]
    reason: str = ""
    detail: str = ""
    #: TCC's line about the tag's signature: good, predates signing, or NOT checked under the
    #: developer's switch — shown on the row, never only in the log (HUB-032).
    signature: str = ""
    tag: str = ""


def prepare_tcc_update(channel: str = STABLE, *, pid: Optional[int] = None,
                       words: Optional[dict] = None,
                       platform: Optional[str] = None) -> TccUpdate:
    """The newest tag on `channel`, checked (`check_tcc_tag`), and only then its install script
    (`write_tcc_install_script`). A fetch and a check: off the GUI thread.

    A tag that does not verify gets NO script, so no terminal opens and `uv` never runs: nothing
    is installed, and the reason is the row's to say. No tag at all is refused too — the ref-less
    command would install `main` as it stands, which no signature covers.
    """
    tag = newest_tcc_tag(channel)
    if not tag:
        return TccUpdate(None, "probe_failed", last_probe_error() or "no tag matched")
    ok, line, why, sha = check_tcc_tag(tag)
    # The update log's line with the check's result — the evidence HUB-032 closes on.
    (_log.info if ok else _log.warning)("tcc tag %s: %s", tag, line)
    if not ok:
        return TccUpdate(None, why, line, tag=tag)
    script = write_tcc_install_script(pid, tag, words=words, platform=platform, sha=sha)
    return TccUpdate(script, signature=line, tag=tag)
