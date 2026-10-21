"""Cut the next patch release: check, bump, test, commit, tag, push.

    make ship              # dry run — reads everything, writes nothing
    make ship REAL=1       # the real thing
    make ship VERSION=vY AT=<commit>   # TCC's OWN pre-tag checks at a commit, not the hub's
                                       # preflight: dry, no suite, writes nothing; exit 0 = ready,
                                       # 1 = not, with the reason

**Dry run is the default, and that is not politeness.** The last step publishes a tag, and a
published tag can never be moved or deleted by anyone — including the `release` role
(hub `governance/RELEASE-CHANNEL.md`, and the hook's own `tag_rule`). So every check that can be
made has to be made before it, and the command that does it must be asked for by name.

## Why this file needs a barrier at all

The hub's `guard-release.py` refuses a bad tag or a bulk push, and it would look like a safety net
under this script. It is not one. The hook parses the COMMAND LINE, and `make ship` contains no
git verb at all, so it exits before it reaches any rule. Measured 2026-08-27:

    make ship                      -> exit 0   (the hook saw nothing)
    bash -c 'git push --tags ...'  -> exit 0   (an interpreter, not a command it can read)
    git push --tags origin         -> exit 2   (refused)

Raised with the hub as TCC-001 (autosound-hub#8) and **settled there**: it is recorded as a
boundary rather than a defect, `governance/RELEASE-CHANNEL.md` §8.10, which splits the ways round
the hook into two classes. WRAPPERS — the verb is in the line, just not at the front
(`timeout git push`, `env git push`, `eval "git push"`) — were closed the same day and are held by
a probe of theirs. OPAQUE launches — `make`, `./script.sh`, `python3 -c`, an interpreter — have no
verb in the line, and the hub's own finding is that they are not catchable: the only event that
sees a child process arrives AFTER it ran, and even then only when the target does not silence its
output.

So the hub does not pretend to cover this path, and `make ship` is squarely in the second class.
Between `make ship` and a published tag there is nothing but what this file does first.

## The barrier is the hub's, called rather than copied (HUB-003, autosound-hub#10)

It used to be `check_rule()` here — a second copy of the hook's rule, with `oracle()` beside it to
catch the copy drifting from its owner. Caught is not the same as prevented, and this repository
has paid for "one fact in two places" often enough to stop shipping the shape.

Both are gone. The channel half of the preflight — clean tree, HEAD published, `push.followTags`,
the tag free on the remote, the rule itself, and the hook's verdict on the exact command lines
that will run — is `hub/scripts/release-preflight.py`, shared with `skill`. It does not restate
the rule either: it imports `guard-release.tag_rule()` and calls it. One copy, for both repos.

**No hub on this machine, no release.** The old hook check was allowed to say "not checked" and
carry on, because it was a comparison and not a gate. This IS the gate, on a path the hook cannot
see, so "not checked" here would mean nothing is checking the release at all — and unknown is a
refusal, never "no objections" (hub `HUB-CONSTRAINTS.md` §1.4).

That is about the carrier being ABSENT, which is a different thing from a single check inside it
coming back `не перевірено` — the hook missing while the hub is here, most often. Those are
printed and do not stop the release, and the decision is the carrier's own (`Check.gates`), not
one this file takes a second view on. Holding a second view is how the copy came back.

## What stayed: the inventory, and everything that writes

The CHANGELOG entry and its `Paired with method` line, the bump, `uv.lock`, the suite, the commit,
the tag and the two pushes. None of them has a second copy anywhere, so there is nothing to bring
together: the boundary is ownership, not tidiness (hub `RELEASE-CHANNEL.md` §9).

The two halves also REPORT differently, and that is deliberate. The carrier runs every channel
check and names all of them at once, so one run tells a person everything that is not ready
(§9.5). The inventory half below stops at the first, because those checks are sequential by data —
there is no `Paired with method` line to check until there is an entry to read it from.

## The order, and the one thing it is built around

The bump happens BEFORE the tests, so the tree that gets tested is character for character the
tree that gets tagged — version included. A red suite rolls the bump back and leaves nothing.

"The version" is two files, not one: `pyproject.toml` and `uv.lock`, which records the project's
own version as well. Missing the second is how v0.1.25 came to be tagged on a tree whose lock said
0.1.24 — found by this script's own clean-tree gate on the next run, which is the good way to find
it and still one file too many to keep a single fact in. And a third since tcc#174: the tag
README's install line names, which the suite holds to the version, so `bump` moves it too.

Everything up to and including the local tag is reversible. The single irreversible act is the
last line of the script, on its own, by name.

## CI's green run on the commit is the release's test run (tcc#201, hub #277, #246)

Hub `RELEASE-CHANNEL.md` §9.9.1, the user's word 2026-10-14: the PR's green `pull_request` run on
the very commit being tagged is the release's test run, and ship does not run the suite again.
v1.1.3 ran it three times on one commit — the PR, `main`'s push, and here, 15 min serially with the
VM paused. So where the tag goes on a commit CI saw (the version committed on the wave branch), the
carrier's `ci-green` for that commit decides: `ok` — no local run; anything that did not refuse and
is not `ok` (the check missing, or `не перевірено`) — CI could not be read, and the whole suite runs
here as the fallback. One line says which. Unknown is never green, and a refusal stays a refusal:
whether CI that could not be read refuses is the carrier's call (`Check.gates`), not one ship
overrides. Today it refuses (`ci-green` and `windows-ran` both), so **the local fallback cannot run
until the hub reports unreadable CI as `не перевірено`** — and whether a release may go out anyway
with CI unread is the user's decision, not ship's. A bump makes a new commit CI never saw, so the
suite runs there as before.

`VERSION=vY AT=<commit>` runs **TCC's own** pre-tag checks against that commit, read from it
(`git show`, `git ls-tree`): the CHANGELOG entry, the version, the recorded pin against `Paired with
method`, and that pin's published tag. Not the hub's preflight: the release train runs that itself,
with the tags it promises (`promised`), and asked here without them `minor-pair` would refuse every
paired release, whose pin carries only the skill's candidate tag until the train cuts it (review of
tcc#201). The ref is resolved to one full sha once, and every read is of that commit. No suite, and
nothing written — it reads git objects and asks the method's remote for its tags (`ls-remote`).

## A candidate may carry its release — the release train (tcc#226, hub #246 asks 1–2)

The train tags each product's newest candidate's commit, the skill's first (hub RELEASE-CHANNEL.md
§11.6), so TCC's last candidate already carries the release. A candidate whose `pyproject.toml`
already says its version is such a candidate, and `CANDIDATE=` holds it to the release's own checks
on HEAD — the ones `VERSION=… AT=` will make on that same commit: `## [vY]` on top with no
`## [Unreleased]`, a note that says something, and `Paired with method` naming the pin's sha. Its
pin is the skill's candidate, so the published-tag check changes: the line names the skill's
coming tag `vX` beside the sha, and the pin must carry `vX` or a published `beta-vX-rcN` — a typo in
the line, or a pin on another version's candidate, is refused. A candidate whose version is not
moved yet is an ordinary one, checked as before, and the plan says it does not carry the release.

## The tag is signed, and checked before it leaves (tcc#102, hub #83 HUB-032)

From `v0.1.45` TCC's updater installs a release tag only when it verifies against the author's key,
so a tag cut unsigned would stop every update. Two halves, and neither is a copy of the other.
BEFORE the tag, whether git will sign with the key in `allowed_signers` is the carrier's question
(`tag-will-be-signed`, hub #84 HUB-033 — put there so this repository asks it without a second
copy); its refusal names the `git config` lines that fix it, and ship prints it like any other.
AFTER the tag, ship verifies the tag it actually made against that file, before either push: a tag
that does not verify is deleted again and nothing leaves the machine.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

#: The hub's carrier of the channel preflight. Ship does NOT work without it — see the module
#: docstring. The version pattern and the release glob went with it: they were copies of the
#: hook's, and the carrier reads the hook's own (`guard-release.VERSION_RE`, `RELEASE_GLOB`).
#:
#: Anchored to THIS FILE, not to `$HOME` and not to `cwd`: the hub is the tree beside ours, so the
#: only thing between them is the folder above, and a path written from here survives that folder
#: being renamed. It did not survive it as an absolute path — `autosound-hub` → `autosound` on
#: 2026-08-29 pointed ship at nothing and it fell before the first check (HUB-005,
#: autosound-hub#12). `cwd` is no better an anchor: ship runs from the repo root under `make`, from
#: `scripts/` by hand, and from anywhere at all under `make -C`.
CARRIER = Path(__file__).resolve().parents[2] / "hub" / "scripts" / "release-preflight.py"

#: The suite, whole. `docs/TESTING.md`: run everything, every time — there is deliberately no
#: fast subset, and a release is the last place to invent one.
#:
#: `-n 0` is belt and braces: the default is serial anyway (`pyproject.toml` carries no
#: `addopts`), but a release must not become parallel because somebody exported PYTEST_ADDOPTS in
#: the shell it was cut from. Parallel runs killed a Qt worker in 2 of 15 full runs on this
#: machine and did not reproduce on demand (tcc#22) — a release is the last place to accept that.
TEST_COMMAND = [sys.executable, "-m", "pytest", "tests/", "-q", "-n", "0"]

#: The carrier's check that judges CI on the commit, and its word for a pass. Copies, so ship can
#: read a verdict without holding the module — pinned to the real ones by
#: `test_the_stand_in_has_the_carriers_shape`. Only this word skips the suite: unknown is not green.
CI_GREEN = "ci-green"
CARRIER_OK = "ok"


#: A full git object name. `ls-tree` prints a mode, a type, the sha and the path, and only the
#: third field is ours — a pattern rather than "take field 3" so a surprise in that output is a
#: refusal instead of a nonsense sha travelling into a release.
_SHA = re.compile(r"^[0-9a-f]{40}$")


class Stop(Exception):
    """A check said no. Carries the sentence a person reads, not a code."""


@dataclass
class Plan:
    """What ship worked out before it was allowed to touch anything."""

    root: Path
    mode: str = "patch"
    tag: str = ""
    version: str = ""
    method_sha: str = ""
    method_tags: list = field(default_factory=list)
    commands: list = field(default_factory=list)


def run(argv, cwd: Path, check: bool = True) -> str:
    # `encoding` spelled out, because `text=True` alone decodes with the machine's locale code
    # page — cp1251/cp866 on the Windows box this project is released from. Every subprocess call
    # in `src/` was hardened for that after a Cyrillic answer came back as mojibake
    # (`core/process_writer.py` carries the story); this helper, which runs every `git` and `gh`
    # command in the release, was missed. A Cyrillic commit subject is enough to trip it.
    done = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if check and done.returncode != 0:
        raise Stop(f"{' '.join(argv)} -> {done.returncode}\n{done.stderr.strip()}")
    return (done.stdout or "").strip()


# ---------------------------------------------------------------- the channel half, borrowed


def load_carrier(path: Path = CARRIER):
    """The hub's `release-preflight.py`, loaded by path — its name has a hyphen and will not import.

    A hub that is not here is a STOP, and the sentence names the path it looked at. "The hub is
    missing" and "nothing is checking this release" are the same statement on this path: the hook
    never sees a git command run from inside a make recipe.
    """
    if not path.is_file():
        raise Stop(
            f"the hub's channel preflight is not on this machine ({path}), and it is the only "
            "thing between `make ship` and a published tag — the hook cannot see git run from "
            f"inside a make recipe. Clone the hub to {path.parents[1]} and run ship again.")
    spec = importlib.util.spec_from_file_location("release_preflight", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — a hub that is here but will not load is still no gate
        raise Stop(f"{path} is on this machine but did not load: {exc!r}. It reads the hook beside "
                   "it (guard-release.py) at import time; half a hub is not a barrier.") from exc
    return module


def channel_checks(root: Path, path: Path = CARRIER, *, candidate: str | None = None,
                   version: str | None = None):
    """Every channel precondition, asked of the carrier. Returns `(tag, checks)`, writes nothing.

    One question per mode: the next patch, the next candidate for `candidate`, or the named
    `version`. The carrier names the tag in the first two and judges it in all three — including
    whether `candidate` or `version` looks like a version at all; ship keeps no copy of that pattern.

    The role is the session's (`HUB_ROLE`), and `tcc` when there is none. It decides which
    repository and line the carrier reports on and which tags the hook lets this session cut: a
    minor is the `release` role's. ship does not restate that rule; it passes the role on.
    """
    role = os.environ.get("HUB_ROLE") or "tcc"
    carrier = load_carrier(path)
    if candidate:
        return carrier.preflight(root, role=role, candidate=candidate)
    if version:
        return carrier.preflight(root, role=role, tag=version)
    return carrier.preflight(root, role=role, want_next=True)


# ---------------------------------------------------------------- the inventory, ours alone


#: `## [Unreleased]`, in any case — where a line's notes sit between tags (hub RELEASE-CHANNEL.md
#: §11.5), renamed to the tag in the commit a release is cut from.
_UNRELEASED = re.compile(r"^## \[unreleased\]", re.I | re.M)

#: A release note shorter than this is a forgotten note. The skill's `tag-check.sh` holds the same
#: floor; one rule, two doors, and they should not drift apart.
RELEASE_NOTE_MIN_LINES = 3

#: The fewest characters of a sha the `Paired with method` line may name the method by: git's
#: own short sha. One character used to pair with any sha that held it (F13, #174).
PAIRED_SHA_MIN = 7


def section(text: str, heading: str) -> str | None:
    """The body under `## [heading]`, up to the next `## `; None when there is no such heading."""
    found = re.search(rf"^## \[{re.escape(heading)}\][^\n]*\n(.*?)(?=^## |\Z)", text,
                      re.M | re.S | re.I)
    return found.group(1) if found else None


def _filled(body: str) -> int:
    return sum(1 for line in body.splitlines() if line.strip())


def read_at(root: Path, at: str, name: str) -> str | None:
    """`name` as commit `at` carries it; None only when git says that commit has no such path.

    Asked in two steps so «absent» is git's own answer rather than a reading of its error text:
    `ls-tree` lists nothing for a path the commit lacks. Any other failure — a commit that is not
    here, a git that will not run — is a Stop with git's words, never a quiet «no file».
    """
    if not run(["git", "ls-tree", at, "--", name], root):
        return None
    return run(["git", "show", f"{at}:{name}"], root)


#: The locked set every release carries from v1.1.4 (tcc#194): README's install line names it at the
#: tag, and TCC's updater holds uv to it — a release without it would send both to nothing.
CONSTRAINTS = "constraints.txt"


def check_constraints(root: Path, at: str) -> None:
    """The commit being released carries `CONSTRAINTS`, read from that commit, not the tree."""
    if read_at(root, at, CONSTRAINTS) is None:
        raise Stop(f"no {CONSTRAINTS} in {at[:12]} — README's install line and TCC's updater read "
                   f"it from the release tag (tcc#194); `make constraints` and commit it first")


def _read_changelog(root: Path, at: str = "") -> str:
    if at:
        text = read_at(root, at, "CHANGELOG.md")
        if text is None:
            raise Stop(f"no CHANGELOG.md in {at[:12]}")
        return text
    path = root / "CHANGELOG.md"
    if not path.is_file():
        raise Stop("no CHANGELOG.md")
    return path.read_text(encoding="utf-8")


def check_changelog(root: Path, tag: str, at: str = "") -> str:
    """The top entry must already be this release's.

    A gate, not a convenience. The heading is a sentence about what changed — content, and ship
    does not write content. Requiring it here also means the release notes exist BEFORE the tag
    rather than being written afterwards against a published number.

    So `## [Unreleased]` must be gone by then: the notes gathered under it are renamed to this
    heading, by hand, in the commit the release is cut from — the skill's model (hub
    RELEASE-CHANNEL.md §11.3, `tag-check.sh`). With `at`, the file as that commit carries it.
    """
    text = _read_changelog(root, at)
    if _UNRELEASED.search(text):
        raise Stop(f"CHANGELOG.md still has a `## [Unreleased]` heading — rename it to `## [{tag}]` "
                   "first; the heading is yours to word, not ship's")
    found = re.search(r"^## \[(v\d+\.\d+\.\d+)\]", text, re.M)
    if not found:
        raise Stop("CHANGELOG.md has no `## [vX.Y.Z]` heading to read")
    if found.group(1) != tag:
        raise Stop(f"CHANGELOG.md's top entry is `{found.group(1)}`, and ship is cutting `{tag}` "
                   f"— write the entry first; its heading is yours to word, not ship's")
    lines = _filled(section(text, tag) or "")
    if lines < RELEASE_NOTE_MIN_LINES:
        raise Stop(f"the `## [{tag}]` entry has {lines} non-empty line(s) — an empty note is a "
                   "forgotten note")
    return text


def check_candidate_changelog(root: Path, version: str) -> None:
    """What a candidate carries: `## [vX.Y.Z]` if the version is already named, else `## [Unreleased]`.

    A candidate writes nothing, so its notes may still sit under `## [Unreleased]`: the release
    commit renames them (hub RELEASE-CHANNEL.md §11.3, the skill's `tag-check.sh --candidate`). They
    must say something all the same — an empty note is a forgotten note for a candidate too.
    A candidate that carries its release is read by `check_changelog` instead (tcc#226).
    """
    text = _read_changelog(root)
    for heading in (version, "Unreleased"):
        body = section(text, heading)
        if body is None:
            continue
        if not _filled(body):
            raise Stop(f"`## [{heading}]` has no entry — an empty note is a forgotten note")
        return
    raise Stop(f"CHANGELOG.md has neither `## [{version}]` nor `## [Unreleased]` — nothing says "
               "what the candidate carries")


def check_paired_method(changelog: str, method_sha: str, tag: str) -> None:
    """The "Paired with method" line against the method actually checked out.

    This line is written by hand, and hands are exactly where it drifts from reality without a
    sound. The sha is the identifier (HUB-001); the version string beside it is a signature, so
    the version alone cannot carry this check.
    """
    body = section(changelog, tag) or ""
    found = re.search(r"[Pp]aired with method[^\n]*?`([^`]+)`", body)
    if not found:
        raise Stop(f"the `## [{tag}]` entry has no `Paired with method` line — a release that "
                   "does not say which method it was built against cannot be reproduced")
    said = found.group(1).strip().lstrip("v")
    if not method_sha:
        raise Stop("the method's sha could not be read, so the CHANGELOG's pairing cannot be "
                   "checked — see core/install_report.skill_sha")
    if not method_sha.startswith(said):
        # A tag name is allowed there too, and is what the file uses today; only a SHA can be
        # checked automatically, so a tag is reported rather than silently accepted. From its
        # start only: `said in method_sha` paired any piece of the sha (F13, #174).
        raise Stop(f"CHANGELOG says the method is `{said}`, the checkout is at "
                   f"`{method_sha[:12]}` — if `{said}` is a tag, put the sha beside it so this "
                   "can be checked rather than believed")
    if len(said) < PAIRED_SHA_MIN:
        raise Stop(f"CHANGELOG says the method is `{said}` — the start of the checkout's "
                   f"`{method_sha[:12]}`, but too short to name one commit; write at least "
                   f"{PAIRED_SHA_MIN} characters of the sha")


def paired_method_version(changelog: str, tag: str) -> str:
    """The method's version the `Paired with method` line of `## [tag]` names beside its sha —
    `` **`v3.2.0`** `` — or "" when that paragraph names none."""
    body = section(changelog, tag) or ""
    found = re.search(r"[Pp]aired with method[^\n]*?`[^`]+`(.*?)(?:\n[ \t]*\n|\Z)", body, re.S)
    named = re.search(r"`(v\d+\.\d+\.\d+)`", found.group(1)) if found else None
    return named.group(1) if named else ""


def check_coming_method(changelog: str, tag: str, pinned: str, tags: list) -> str:
    """A candidate that carries its release: the pin carries the method version its line names —
    released as `vX`, or the skill's candidate `beta-vX-rcN` (tcc#226, hub #246 ask 2).

    The train tags the skill's newest candidate's commit `vX` first, then TCC's on its own, so the
    line names a tag that does not exist yet while the candidate is tried. What can be checked
    instead is that the pin is a published candidate OF THAT version: a typo in the line, or a pin
    on another version's candidate or on no tag at all, is refused. Which of X's candidates (the
    newest) and the minor pairing are the hub's, at the train (`minor-pair` with `promised`).
    The `beta-` prefix is the hub's candidate name (RELEASE-CHANNEL.md §11.1).
    """
    named = paired_method_version(changelog, tag)
    if not named:
        raise Stop(f"the `## [{tag}]` entry's `Paired with method` line names no method tag beside "
                   "the sha — a candidate that carries its release names the skill's coming tag, "
                   "`vX.Y.Z`, so it can be held to the pin")
    if named in tags or any(re.fullmatch(rf"beta-{re.escape(named)}-rc\d+", t) for t in tags):
        return named
    raise Stop(f"the `## [{tag}]` entry pairs with method `{named}`, and the pin `{pinned[:12]}` "
               f"carries {', '.join(tags) or 'no published tag'} — neither `{named}` nor a "
               f"published `beta-{named}-rcN`. A typo in the line, or the pin is not the skill's "
               f"candidate of {named}: pin its last candidate, the commit the train tags {named}")


# ---------------------------------------------------------------- the writing half


def current_version(root: Path, at: str = "") -> str:
    """`pyproject.toml`'s version as it stands — or as commit `at` carries it — or "" when there
    is no version line."""
    text = (read_at(root, at, "pyproject.toml") if at
            else (root / "pyproject.toml").read_text(encoding="utf-8")) or ""
    found = re.search(r'^version = "([^"]+)"', text, re.M)
    return found.group(1) if found else ""


def check_version_at(root: Path, at: str, version: str) -> None:
    """A commit tagged where it stands is not bumped: it must already say the version."""
    said = current_version(root, at)
    if said != version:
        raise Stop(f"pyproject.toml in {at[:12]} says {said or 'no version'}, and the tag is "
                   f"v{version} — a commit tagged where it stands carries its version already")


#: The tag README's install line names (tcc#174): `…/autosound-tcc@v1.1.2'`. That line is what a
#: person who installs by hand pastes, so it names the release it installs, and
#: `tests/test_readme.py` holds it to pyproject's version.
README_TAG = re.compile(r"(git\+https://github\.com/ayukhno/autosound-tcc@v)([^'\"\s]+)")

#: Every tag on that line, the install's and the one its `--constraints` URL names
#: (`…/autosound-tcc/v1.1.2/constraints.txt`, tcc#194): the bump moves them together, or the
#: install would be held to another release's versions.
README_LINE_TAG = re.compile(r"(ayukhno/autosound-tcc[@/]v)([^'\"\s/]+)")


def bump(root: Path, version: str) -> str:
    """`pyproject.toml`'s version and the tag README's install line names, and the old version so
    a failed suite can put both back.

    README moves with the version because the suite checks the two agree: a bump that left it
    behind failed its own suite and rolled every release outside the wave path back (tcc#174). A
    tree with no README has nothing to move. One that has a README but not exactly one tagged
    install line is a refusal, said before anything is written. Every tag on that line moves —
    the `--constraints` URL's with the package's (tcc#194) — and no tag on any other line.
    """
    path = root / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    found = re.search(r'^version = "([^"]+)"', text, re.M)
    if not found:
        raise Stop("pyproject.toml has no `version = \"...\"` line")
    readme = root / "README.md"
    words = readme.read_text(encoding="utf-8") if readme.is_file() else None
    if words is not None:
        named = len(README_TAG.findall(words))
        if named != 1:
            raise Stop(f"README.md should carry one install line naming a tag "
                       f"(`…/autosound-tcc@vX.Y.Z`) for the bump to move, and carries {named}")
        lines = words.splitlines(keepends=True)
        at = next(at for at, line in enumerate(lines) if README_TAG.search(line))
        lines[at] = README_LINE_TAG.sub(lambda tag: tag.group(1) + version, lines[at])
        words = "".join(lines)
    was = found.group(1)
    path.write_text(text[:found.start(1)] + version + text[found.end(1):], encoding="utf-8")
    if words is not None:
        readme.write_text(words, encoding="utf-8")
    return was


def tracked(root: Path, name: str) -> bool:
    return bool(run(["git", "ls-files", "--error-unmatch", name], root, check=False))


def relock(root: Path) -> None:
    """Put the new version into `uv.lock` too, through uv rather than by hand.

    `uv.lock` records the project's OWN version, so a bump leaves it stale — and this was found
    the way such things are: the first `uv run` after v0.1.25 rewrote the lock, the tree went
    dirty, and ship's own clean-tree gate refused the next release. Worse than the nuisance is
    what it means for the tag already cut: `v0.1.25` names a tree whose lock says `0.1.24`, which
    is precisely the kind of "two places, one fact" this project keeps paying for.

    Through `uv lock`, not a regex: the lock is uv's file and its shape is uv's business. If uv is
    not here, that is a STOP rather than a shrug — a release that silently leaves the lock behind
    is the bug this function exists to close.
    """
    if not tracked(root, "uv.lock"):
        return
    done = subprocess.run(["uv", "lock", "--quiet"], cwd=str(root),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise Stop("uv.lock is tracked and `uv lock` failed, so the lock would keep the old "
                   f"version while the tag says otherwise:\n{done.stderr.strip()}")


#: The method's tree inside this repository. One name rather than a literal in every place that
#: has to say it: the gitlink reader, the remote reader and the refusal are all about this path.
METHOD_TREE = "vendor/autosound-tuning-skill"


def pinned_method_sha(root: Path, at: str = "HEAD") -> str:
    """The method commit this repository RECORDS — the gitlink, not the working checkout — in
    HEAD, or in commit `at`.

    `git ls-tree` rather than anything inside the submodule: what a person gets when they clone
    the tag is whatever the parent commit points at, and that is this.
    """
    line = run(["git", "ls-tree", at, METHOD_TREE], root, check=False)
    parts = line.split()
    return parts[2] if len(parts) > 2 and _SHA.match(parts[2]) else ""


def check_method_pin(pinned: str, checked_out: str) -> None:
    """The recorded pin against the checkout the suite actually ran on.

    `check_paired_method` compares the CHANGELOG with the working checkout, which is right — that
    is what was tested. Nothing compared it with the gitlink, and those two drift: a submodule
    left on a detached commit tests one method while the repository records another, so the tag
    pairs itself with a commit written down nowhere and a fresh clone gets something else.

    Bought 2026-09-09: the pin sat at `0cc96f6`, seven commits past `v3.0.46` and on no tag at
    all, while everything was tested against that checkout.
    """
    if not pinned or not checked_out:
        raise Stop(
            "the method's pin could not be read on both sides "
            f"(recorded: {pinned[:12] or '?'}, checked out: {checked_out[:12] or '?'}) — "
            "a release cannot say which method it was built against"
        )
    if pinned != checked_out:
        raise Stop(
            f"the repository records method `{pinned[:12]}` but the checkout is at "
            f"`{checked_out[:12]}` — commit the submodule move, or check the recorded one out, "
            "so the tag pairs with a commit that exists in this history"
        )


def method_url_at(root: Path, at: str) -> str:
    """The method's remote as commit `at` records it in `.gitmodules` — not the working checkout's.

    A clone without `--recurse-submodules` leaves the method's folder empty, and `git -C` there
    runs in TCC's own repository: `ls-remote origin` then answers with TCC's tags (review of
    tcc#201). The commit's own record names the method wherever the checkout stands.
    """
    blob = f"{at}:.gitmodules"
    paths = run(["git", "config", "--blob", blob, "--get-regexp", r"^submodule\..*\.path$"],
                root, check=False)
    name = next((key[len("submodule."):-len(".path")] for key, _, value in
                 (line.partition(" ") for line in paths.splitlines()) if value == METHOD_TREE),
                "")
    url = run(["git", "config", "--blob", blob, "--get", f"submodule.{name}.url"], root,
              check=False) if name else ""
    if not url or url.startswith((".", "-")):  # «-»: an option to ls-remote, as git refuses it
        raise Stop(f"the method's URL could not be read from .gitmodules in {at[:12]} "
                   f"(submodule `{METHOD_TREE}`: {url or 'no url'}) — without it nothing can say "
                   "whether the pin carries a published tag")
    return url


def published_method_tags(root: Path, sha: str, remote: str = "") -> list[str]:
    """Tag names the method's REMOTE has pointing at `sha` — published, not merely local.

    `ls-remote` rather than `for-each-ref --points-at`: the skill tree beside this one is
    routinely ahead of what a person can actually install, so a tag that exists on this machine
    only is not an answer to "does this pin have a version".

    Annotated tags come back twice — the tag object, then its `^{}` peel — and only the peel
    carries the commit. A gitlink always points at a commit, so the peel is the line that can
    match; matching column one without peeling would find nothing for every annotated tag.

    Not `check=False`: a remote that cannot be asked returns the same empty output as a method
    with no tags at all, and those two must not read the same (hub `HUB-CONSTRAINTS.md` §1.4 —
    unknown is a refusal, never "no objections").

    `remote`: the method's URL, asked from `root` — a check at a commit reads it from that
    commit's `.gitmodules` (`method_url_at`); without it, the checkout's own `origin`.
    """
    argv = (["git", "ls-remote", "--tags", "--", remote] if remote
            else ["git", "-C", str(root / METHOD_TREE), "ls-remote", "--tags", "origin"])
    out = run(argv, root)
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == sha and parts[1].startswith("refs/tags/"):
            names.add(parts[1][len("refs/tags/"):].removesuffix("^{}"))
    return sorted(names)


def check_published_method(pinned: str, tags: list) -> None:
    """The recorded pin against what the method has PUBLISHED.

    `check_method_pin` proves the gitlink and the checkout agree, and `check_paired_method` proves
    the CHANGELOG names that same commit. All three could agree on a commit of the method's `main`
    that was never released — and then this repository ships a tag whose method has no version at
    all, so the user updates to something nobody can name or go back to.

    In a shared wave the order is skill first: the method is fixed and tagged, tcc pins that
    published tag and is tested against it, and only then cuts its own tag (hub
    `governance/WAVES.md` §1 step 4). This is the third of that order made mechanical; the other
    two already are.

    It is ABSOLUTE for a release, with no override to remember, because the case an override
    would serve already has a path: a candidate (`make ship CANDIDATE=…`) skips
    `Paired with method` too, and skips this — unless it carries its release, and then
    `check_coming_method` asks for the skill's candidate of the version its line names. Measured before it was written, 2026-09-19: the
    last six tcc tags all pin a tagged method commit, so nothing about how releases are cut
    changes — this only writes down what hands already do.
    """
    if tags:
        return
    raise Stop(
        f"the method pinned here, `{pinned[:12]}`, carries no published tag on its remote — "
        "tag the method first, then move the pin and test against it (hub governance/WAVES.md "
        "§1 step 4: in a shared wave the order is skill first). A build against a method with no "
        "version is a candidate rather than a release: `make ship CANDIDATE=vX.Y.Z` does not ask "
        "this."
    )


def method_sha(root: Path) -> str:
    """The commit of the method this build is against, through its one reader (HUB-001).

    A function rather than an inline import so that it is a SEAM: a test can hand `ship()` a
    different one instead of reaching into `sys.modules`, which does not work anyway once
    `autosound_tcc.core` is imported — `from ... import install_report` takes the package's
    attribute, not the entry in `sys.modules`. Learned by writing the test that did that.
    """
    sys.path.insert(0, str(root / "src"))
    from autosound_tcc.core import install_report
    return install_report.skill_sha()


#: Who signs this repository's tags, for people and for `git verify-tag` (tcc#102). The updater
#: does not read it — it carries the key as a constant, `core/signed_tags.py`.
SIGNERS = "allowed_signers"


def tag_command(tag: str, at: str = "") -> list[str]:
    """The one tag line, signed, in the skill's form (`tag-check.sh`: `git tag -s X -m X`). The plan
    shows it and `publish` runs it, from here both, so the line shown is the line run. `at` names
    the commit when it is not HEAD — shown only: a check at a commit runs nothing."""
    return ["git", "tag", "-s", tag, "-m", tag, *([at] if at else [])]


def drop_tag(root: Path, tag: str) -> str:
    """Delete the local `tag` that must not leave this machine; the sentence that says what
    happened — including when git would not delete it, and then the command to do it by hand."""
    try:
        run(["git", "tag", "-d", tag], root)
    except Stop as failed:
        why = str(failed).strip().splitlines()[-1]
        return (f"The tag could NOT be deleted ({why}) — delete it by hand before anything else, "
                f"`git tag -d {tag}`; nothing was pushed")
    return "The tag was deleted again and nothing was pushed"


def verify_signed_tag(root: Path, tag: str) -> str:
    """The tag just made, verified against `allowed_signers`: git's own `Good` line, or a Stop.

    The SSH form of that line (`Good "git" signature for …`) and nothing looser: a tag signed with
    GPG by a machine left on `gpg.format=openpgp` says `Good signature from …`, and the updater
    would refuse it all the same. A tag that does not verify is deleted before the Stop — it must
    not leave this machine, and a run after the fix needs the name free.

    A tree with no `allowed_signers` is its own sentence: git answers it with the same
    "No principal matched" as a stranger's key, and the key hint would send the reader to a
    `user.signingkey` that was right all along (review of tcc#102).
    """
    signers = Path(root).resolve() / SIGNERS
    if not signers.is_file():
        raise Stop(f"{tag} was signed, but there is no {SIGNERS} in this tree to verify it "
                   f"against. {drop_tag(root, tag)}: TCC's updater refuses a release tag that "
                   f"does not verify (tcc#102). Put {SIGNERS} back at the repository root")
    # The updater's own recipe, one copy (`core/signed_tags`, #174), imported the way
    # `method_sha` imports its reader: `gpg.ssh.program` pinned, so a signing helper in this
    # machine's git config is not what verifies, and git's messages in English with the charset
    # kept, so the reason quoted below is git's English sentence.
    sys.path.insert(0, str(Path(root) / "src"))
    from autosound_tcc.core import signed_tags
    done = subprocess.run(["git", "-c", f"gpg.ssh.allowedSignersFile={signers}",
                           *signed_tags.VERIFY_PROGRAM, "verify-tag", tag],
                          cwd=str(root), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=signed_tags.verify_env(os.environ))
    said = [line.strip() for line in f"{done.stderr}\n{done.stdout}".splitlines() if line.strip()]
    good = next((line for line in said if line.startswith('Good "git" signature')), "")
    if done.returncode == 0 and good:
        return good
    reason = said[-1].rstrip(".") if said else f"git verify-tag exit {done.returncode}"
    raise Stop(f"{tag} was signed, but it does not verify against {SIGNERS} — {reason}. "
               f"{drop_tag(root, tag)}: TCC's updater refuses a release tag that does not verify "
               f"(tcc#102). `git config user.signingkey` must name the key in {SIGNERS}")


def left_behind(root: Path, version: str) -> str:
    """What a failure after the release commit leaves, and the two ways on; "" when HEAD is
    already published — a failure past `git push origin main` leaves nothing of that kind.

    Bought in review (tcc#102): `git tag -s` failing (a key with a passphrase and no agent) or a
    tag that does not verify left the bumped commit on local `main`, unpushed, and the Stop said
    only why the tag failed — while the next run is refused by the carrier's `head-published`.
    """
    head = run(["git", "rev-parse", "HEAD"], root, check=False)
    published = run(["git", "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main"], root,
                    check=False)
    if not head or head == published:
        return ""
    return (f"The release commit {head[:12]} (version {version}) stays on local main, not pushed, "
            "and the next `make ship REAL=1` is refused (`head-published`) until one of two: "
            "`git push origin main` — ship then tags that commit and writes nothing — or "
            "`git reset --hard origin/main` — ship then does the bump again.")


def publish(root: Path, tag: str, say: Callable[[str], None]) -> None:
    """Tag HEAD, signed, check the signature, and publish that one tag by name — the last act of
    every mode."""
    run(tag_command(tag), root)
    good = verify_signed_tag(root, tag)
    say(f"  tagged {tag}, {good} (still local — `git tag -d {tag}` undoes it)")
    run(["git", "push", "origin", "main"], root)
    # The one irreversible line in this file. By NAME, never `--tags`: a bulk push has no target
    # in the command, and a published tag cannot be moved or removed by anybody afterwards.
    run(["git", "push", "origin", tag], root)
    say(f"  pushed {tag}")


def check_at(root: Path, plan: Plan, sha: str, say: Callable[[str], None],
             read_pinned_sha: Callable[..., str],
             read_published_tags: Callable[..., list],
             read_method_url: Callable[[Path, str], str]) -> Plan:
    """TCC's own pre-tag checks against commit `sha` (full, resolved once) — read-only, no suite.

    Everything is read from the commit, not the working tree: the CHANGELOG entry, the version
    (a commit tagged where it stands is not bumped), and the pin the `Paired with method` line is
    held to — CI tested the recorded pin, and no local checkout is in question because nothing
    runs here. The channel half — CI on the commit, the tag's rule, the pairing with the skill's
    promised tag — is the hub's preflight, which the release train runs itself.
    """
    plan.version = plan.tag.lstrip("v")
    changelog = check_changelog(root, plan.tag, at=sha)
    check_version_at(root, sha, plan.version)
    check_constraints(root, sha)
    plan.method_sha = read_pinned_sha(root, sha)
    if not plan.method_sha:
        raise Stop(f"the method's pin in {sha[:12]} could not be read — a release cannot say "
                   "which method it was built against")
    check_paired_method(changelog, plan.method_sha, plan.tag)
    plan.method_tags = list(read_published_tags(root, plan.method_sha,
                                                remote=read_method_url(root, sha)))
    check_published_method(plan.method_sha, plan.method_tags)
    plan.commands = [" ".join(tag_command(plan.tag, sha)), "git push origin main",
                     f"git push origin {plan.tag}"]
    say(f"  version          : {plan.tag} at {sha[:12]}")
    say(f"  method           : {plan.method_sha[:12]}  published as "
        f"{', '.join(plan.method_tags)}")
    say(f"\n  READY — {plan.tag} at {sha[:12]}: TCC's own checks pass (the hub's preflight is the "
        "train's). Dry: nothing was written, and no suite ran here.")
    return plan


def ship(root: Path, release: bool, test_command=None,
         channel: Callable[..., tuple] = channel_checks,
         read_method_sha: Callable[[Path], str] = method_sha,
         read_pinned_sha: Callable[[Path], str] = pinned_method_sha,
         read_published_tags: Callable[..., list] = published_method_tags,
         read_method_url: Callable[[Path, str], str] = method_url_at,
         relock_with: Callable[[Path], None] = relock,
         say: Callable[[str], None] = print,
         candidate: str = "", version: str = "", at: str = "") -> Plan:
    """The whole thing. Reads and decides first; writes only when `release` is true.

    Three modes, the skill's model (hub RELEASE-CHANNEL.md §11): the next patch; a candidate for
    `candidate`, which writes nothing and tags HEAD `beta-vX.Y.Z-rcN` — held to the release's own
    checks when its pyproject already says that version (it carries the release, tcc#226); a
    named `version`, released the way a patch is. With `at`, the named `version` is only checked against that commit by TCC's
    own checks — not the hub's preflight, which is the train's: dry, no suite, nothing written
    (tcc#201, hub #246).
    """
    if candidate and version:
        raise Stop("CANDIDATE and VERSION exclude each other — one run cuts one tag")
    if at and (candidate or not version):
        raise Stop("AT checks a named release at a commit — give it VERSION=vX.Y.Z, without "
                   "CANDIDATE")
    if at and release:
        raise Stop("AT is a dry check and never cuts anything — drop REAL=1; the release itself "
                   "goes through `make ship VERSION=… REAL=1` on that commit, or the release train")
    plan = Plan(root=root, mode="candidate" if candidate else "version" if version else "patch")
    if at:
        # Once, to a full sha: a moving ref (`origin/main`) must not name one commit to one read
        # and another to the next.
        sha = run(["git", "rev-parse", "--verify", "--quiet", f"{at}^{{commit}}"], root,
                  check=False)
        if not sha:
            raise Stop(f"`{at}` does not resolve to a commit in {root}")
        plan.tag = version
        return check_at(root, plan, sha, say, read_pinned_sha, read_published_tags,
                        read_method_url)

    tag, checks = channel(root, candidate=candidate or None, version=version or None)
    say("  channel preflight — hub/scripts/release-preflight.py:")
    for check in checks:
        # The carrier's own verdicts and sentences, not a translation of them: rewording somebody
        # else's refusal is how the wording drifts from what they actually said.
        say(f"    {check.verdict:<12} {check.name:<34} {check.line}")
    refused = [check for check in checks if check.gates]
    if refused:
        raise Stop(f"the channel preflight refuses this release — {len(refused)} of "
                   f"{len(checks)}:\n"
                   + "\n".join(f"    {check.name}: {check.line}" for check in refused))
    if not tag:
        # Belt: the carrier returns no tag only alongside a refusal, and ship invents no number.
        raise Stop("the channel preflight worked out no tag and refused nothing — ask it "
                   "directly before shipping")
    plan.tag = tag
    ci = next((check for check in checks if check.name == CI_GREEN), None)
    ci_green = ci is not None and ci.verdict == CARRIER_OK

    # Every tagging path tags HEAD's tree, or HEAD's plus the bump, which leaves the file alone —
    # so HEAD is the release commit's answer, asked before anything is written.
    check_constraints(root, run(["git", "rev-parse", "HEAD"], root))
    # A candidate whose pyproject already says its version carries the release (tcc#226): the train
    # tags this very commit, so it is held to the release's own checks here, not on release day.
    carries = plan.mode == "candidate" and current_version(root) == candidate.lstrip("v")
    if plan.mode == "candidate" and not carries:
        check_candidate_changelog(root, candidate)
    else:
        plan.version = (candidate or tag).lstrip("v")
        changelog = check_changelog(root, candidate or plan.tag)

    plan.method_sha = read_method_sha(root)
    pinned = read_pinned_sha(root)
    check_method_pin(pinned, plan.method_sha)
    if plan.mode != "candidate":
        check_paired_method(changelog, plan.method_sha, plan.tag)
        plan.method_tags = list(read_published_tags(root, pinned))
        check_published_method(pinned, plan.method_tags)
    elif carries:
        check_paired_method(changelog, plan.method_sha, candidate)
        plan.method_tags = list(read_published_tags(root, pinned))
        coming = check_coming_method(changelog, candidate, pinned, plan.method_tags)

    # The three lines that will actually run. The carrier builds the SAME three to put in front
    # of the hook, from its own literal — so an edit here that is not made there would leave the
    # oracle vouching for lines nobody runs. Pinned on this side by
    # `test_ship_never_pushes_in_BULK_and_never_releases`; the other side is the hub's. The tag
    # line is signed since tcc#102; the carrier's literal still reads `git tag <tag>`, and the
    # hook judges both the same (`-s` and `-m` are among its `TAG_WRITE` flags; asked 2026-09-29).
    plan.commands = [
        " ".join(tag_command(plan.tag)),
        "git push origin main",
        f"git push origin {plan.tag}",
    ]

    say(f"  {plan.mode:<17}: {plan.tag}")
    published = f"  published as {', '.join(plan.method_tags)}" if plan.method_tags else ""
    say(f"  method           : {plan.method_sha[:12] or '(unknown)'}{published}")
    if carries:
        say(f"  carries          : the release {candidate}, paired with method {coming} — the "
            "train tags this commit")
    elif plan.mode == "candidate":
        say(f"  carries          : this candidate does not carry the release — pyproject.toml "
            f"says {current_version(root) or 'no version'}, not {candidate.lstrip('v')}; fine for "
            "a patch's candidate, the release train refuses it")

    if not release:
        again = {"candidate": f" CANDIDATE={candidate}",
                 "version": f" VERSION={version}"}.get(plan.mode, "")
        say(f"\n  DRY RUN — nothing was written. Real run: make ship{again} REAL=1")
        return plan

    if plan.mode == "candidate":
        # Nothing to bump and nothing new to test: the tree being tagged is HEAD, and the carrier
        # has already refused a HEAD that is unpublished or whose CI is not green.
        publish(root, plan.tag, say)
        return plan

    if current_version(root) == plan.version:
        # A wave (hub WAVES.md, #148): the version and its CHANGELOG entry were committed on the wave
        # branch, the pull request ran the full CI on that commit, and `--ff-only` landed it here. A
        # release commit on top would be one CI never checked — so nothing is written, and the tag
        # goes on the commit that was checked.
        say(f"\n  version {plan.version} is already committed — tagging this commit, writing nothing")
        if ci_green:
            # Hub RELEASE-CHANNEL.md §9.9.1: that run IS the release's test run (tcc#201).
            say(f"  {CI_GREEN} is ok on this commit — CI's run is the release's test run; "
                "the suite is not run again here")
        else:
            why = (f"{CI_GREEN} is missing from the hub's answer" if ci is None else
                   f"{CI_GREEN} came back «{ci.verdict}» — CI could not be read for this commit")
            say(f"  {why}: running the whole suite locally instead, the fallback "
                "(hub RELEASE-CHANNEL.md §9.9.1)…")
            done = subprocess.run(test_command or TEST_COMMAND, cwd=str(root))
            if done.returncode != 0:
                raise Stop(f"the suite failed ({done.returncode}) — nothing was written and "
                           "nothing was tagged")
        publish(root, plan.tag, say)
        return plan

    was = bump(root, plan.version)
    relock_with(root)
    say(f"\n  version {was} -> {plan.version}")
    say("  the release commit is new — CI has not run on it, so the whole suite runs "
        "locally…")
    done = subprocess.run(test_command or TEST_COMMAND, cwd=str(root))
    if done.returncode != 0:
        bump(root, was)
        relock_with(root)
        raise Stop(f"the suite failed ({done.returncode}) — the version bump was rolled back "
                   "and nothing was committed")

    files = ["pyproject.toml", "CHANGELOG.md"]
    for name in ("uv.lock", "README.md"):
        if tracked(root, name):
            files.append(name)
    run(["git", "add", *files], root)
    run(["git", "commit", "-m", f"{plan.tag}: paired with method {plan.method_sha[:12]}"], root)
    say(f"  committed {plan.tag}")
    try:
        publish(root, plan.tag, say)
    except Stop as stop:
        # Past the release commit now, so whatever stopped the tag also left that commit behind.
        state = left_behind(root, plan.version)
        raise Stop(f"{stop}\n  {state}" if state else str(stop)) from stop
    return plan


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Cut a release: the next patch, a beta candidate, or a named version.")
    parser.add_argument("--release", action="store_true",
                        help="actually write, commit, tag and push (default: dry run)")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--candidate", metavar="vX.Y.Z", default="",
                      help="the next beta candidate for this version (beta-vX.Y.Z-rcN, named by "
                           "the hub); writes nothing but the tag")
    mode.add_argument("--tag", metavar="vX.Y.Z", default="",
                      help="release this version instead of the next patch; the hub decides "
                           "whether this role may")
    parser.add_argument("--at", metavar="COMMIT", default="",
                        help="with --tag: TCC's own pre-tag checks of that release at this commit, "
                             "not the hub's preflight — dry, no suite; exit 0 = ready (the release "
                             "train's `check`, hub #246)")
    args = parser.parse_args(argv)

    root = Path(args.root)
    print(f"ship {'REAL' if args.release else '(dry run)'} — {root}"
          + (f" — at {args.at}" if args.at else ""))
    try:
        ship(root, release=args.release, candidate=args.candidate, version=args.tag, at=args.at)
    except Stop as stop:
        # Flushed first, or the refusal overtakes the lines it refers to: `say` goes to stdout,
        # which is block-buffered the moment this is piped anywhere, and stderr is not. Seen on
        # the first live run of this file (the carrier's own `main` carries the same line).
        sys.stdout.flush()
        print(f"\n  STOP: {stop}", file=sys.stderr)
        said = [line.strip() for line in str(stop).splitlines() if line.strip()]
        if len(said) > 1:
            # The release train records a check's LAST line as its reason (hub release-train.py),
            # so a refusal that runs to several lines ends with all of it on one.
            print(f"  STOP: {' | '.join(said)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
