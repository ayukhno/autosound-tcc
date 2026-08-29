"""Cut the next patch release: check, bump, test, commit, tag, push.

    make ship              # dry run — reads everything, writes nothing
    make ship REAL=1       # the real thing

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
it and still one file too many to keep a single fact in.

Everything up to and including the local tag is reversible. The single irreversible act is the
last line of the script, on its own, by name.
"""
from __future__ import annotations

import argparse
import importlib.util
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
TEST_COMMAND = [sys.executable, "-m", "pytest", "tests/", "-q"]


class Stop(Exception):
    """A check said no. Carries the sentence a person reads, not a code."""


@dataclass
class Plan:
    """What ship worked out before it was allowed to touch anything."""

    root: Path
    tag: str = ""
    version: str = ""
    method_sha: str = ""
    commands: list = field(default_factory=list)


def run(argv, cwd: Path, check: bool = True) -> str:
    done = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True)
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


def channel_checks(root: Path, path: Path = CARRIER):
    """Every channel precondition, asked of the carrier. Returns `(tag, checks)`, writes nothing.

    The role is named HERE and nowhere else: it decides which repository and which release line
    the carrier reports on, and the hook it consults reads the repository from `cwd`. Ship cuts
    patches in TCC's line and nothing else, so the one right answer is a constant, not a flag.
    """
    return load_carrier(path).preflight(root, role="tcc", want_next=True)


# ---------------------------------------------------------------- the inventory, ours alone


def check_changelog(root: Path, tag: str) -> str:
    """The top entry must already be this release's.

    A gate, not a convenience. The heading is a sentence about what changed — content, and ship
    does not write content. Requiring it here also means the release notes exist BEFORE the tag
    rather than being written afterwards against a published number.
    """
    path = root / "CHANGELOG.md"
    if not path.is_file():
        raise Stop("no CHANGELOG.md")
    text = path.read_text(encoding="utf-8")
    found = re.search(r"^## \[(v\d+\.\d+\.\d+)\]", text, re.M)
    if not found:
        raise Stop("CHANGELOG.md has no `## [vX.Y.Z]` heading to read")
    if found.group(1) != tag:
        raise Stop(f"CHANGELOG.md's top entry is `{found.group(1)}`, and ship is cutting `{tag}` "
                   f"— write the entry first; its heading is yours to word, not ship's")
    return text


def check_paired_method(changelog: str, method_sha: str) -> None:
    """The "Paired with method" line against the method actually checked out.

    This line is written by hand, and hands are exactly where it drifts from reality without a
    sound. The sha is the identifier (HUB-001); the version string beside it is a signature, so
    the version alone cannot carry this check.
    """
    entry = changelog.split("## [", 2)
    body = entry[1] if len(entry) > 1 else changelog
    found = re.search(r"[Pp]aired with method[^\n]*?`([^`]+)`", body)
    if not found:
        raise Stop("the top CHANGELOG entry has no `Paired with method` line — a release that "
                   "does not say which method it was built against cannot be reproduced")
    said = found.group(1).strip().lstrip("v")
    if not method_sha:
        raise Stop("the method's sha could not be read, so the CHANGELOG's pairing cannot be "
                   "checked — see core/install_report.skill_sha")
    if not (method_sha.startswith(said) or said in method_sha):
        # A tag name is allowed there too, and is what the file uses today; only a SHA can be
        # checked automatically, so a tag is reported rather than silently accepted.
        raise Stop(f"CHANGELOG says the method is `{said}`, the checkout is at "
                   f"`{method_sha[:12]}` — if `{said}` is a tag, put the sha beside it so this "
                   "can be checked rather than believed")


# ---------------------------------------------------------------- the writing half


def bump(root: Path, version: str) -> str:
    """`pyproject.toml`'s version, and the old value so a failed suite can put it back."""
    path = root / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    found = re.search(r'^version = "([^"]+)"', text, re.M)
    if not found:
        raise Stop("pyproject.toml has no `version = \"...\"` line")
    was = found.group(1)
    path.write_text(text[:found.start(1)] + version + text[found.end(1):], encoding="utf-8")
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
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise Stop("uv.lock is tracked and `uv lock` failed, so the lock would keep the old "
                   f"version while the tag says otherwise:\n{done.stderr.strip()}")


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


def ship(root: Path, release: bool, test_command=None,
         channel: Callable[[Path], tuple] = channel_checks,
         read_method_sha: Callable[[Path], str] = method_sha,
         relock_with: Callable[[Path], None] = relock,
         say: Callable[[str], None] = print) -> Plan:
    """The whole thing. Reads and decides first; writes only when `release` is true."""
    plan = Plan(root=root)

    tag, checks = channel(root)
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
    plan.version = tag.lstrip("v")

    changelog = check_changelog(root, plan.tag)

    plan.method_sha = read_method_sha(root)
    check_paired_method(changelog, plan.method_sha)

    # The three lines that will actually run. The carrier builds the SAME three to put in front
    # of the hook, from its own literal — so an edit here that is not made there would leave the
    # oracle vouching for lines nobody runs. Pinned on this side by
    # `test_ship_never_pushes_in_BULK_and_never_releases`; the other side is the hub's.
    plan.commands = [
        f"git tag {plan.tag}",
        "git push origin main",
        f"git push origin {plan.tag}",
    ]

    say(f"  next patch       : {plan.tag}")
    say(f"  method           : {plan.method_sha[:12] or '(unknown)'}")

    if not release:
        say("\n  DRY RUN — nothing was written. Real run: make ship REAL=1")
        return plan

    was = bump(root, plan.version)
    relock_with(root)
    say(f"\n  version {was} -> {plan.version}")
    say("  running the suite…")
    done = subprocess.run(test_command or TEST_COMMAND, cwd=str(root))
    if done.returncode != 0:
        bump(root, was)
        relock_with(root)
        raise Stop(f"the suite failed ({done.returncode}) — the version bump was rolled back "
                   "and nothing was committed")

    files = ["pyproject.toml", "CHANGELOG.md"]
    if tracked(root, "uv.lock"):
        files.append("uv.lock")
    run(["git", "add", *files], root)
    run(["git", "commit", "-m", f"{plan.tag}: paired with method {plan.method_sha[:12]}"], root)
    run(["git", "tag", plan.tag], root)
    say(f"  committed and tagged {plan.tag} (still local — `git tag -d {plan.tag}` undoes it)")

    run(["git", "push", "origin", "main"], root)
    # The one irreversible line in this file. By NAME, never `--tags`: a bulk push has no target
    # in the command, and a published tag cannot be moved or removed by anybody afterwards.
    run(["git", "push", "origin", plan.tag], root)
    say(f"  pushed {plan.tag}")
    return plan


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Cut the next patch release.")
    parser.add_argument("--release", action="store_true",
                        help="actually write, commit, tag and push (default: dry run)")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)

    root = Path(args.root)
    print(f"ship {'REAL' if args.release else '(dry run)'} — {root}")
    try:
        ship(root, release=args.release)
    except Stop as stop:
        # Flushed first, or the refusal overtakes the lines it refers to: `say` goes to stdout,
        # which is block-buffered the moment this is piped anywhere, and stderr is not. Seen on
        # the first live run of this file (the carrier's own `main` carries the same line).
        sys.stdout.flush()
        print(f"\n  STOP: {stop}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
