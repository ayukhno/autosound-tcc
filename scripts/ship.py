"""Cut the next patch release: check, bump, test, commit, tag, push.

    make ship              # dry run — reads everything, writes nothing
    make ship REAL=1       # the real thing

**Dry run is the default, and that is not politeness.** The last step publishes a tag, and a
published tag can never be moved or deleted by anyone — including the `release` role
(hub `governance/RELEASE-CHANNEL.md`, and the hook's own `tag_rule`). So every check that can be
made has to be made before it, and the command that does it must be asked for by name.

## Why this file carries the rule instead of trusting the hook

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
`check_rule()` below is the ONLY barrier on it — not a formality, and not a second opinion.

## And why it ALSO asks the hook

`check_rule()` is a second copy of somebody else's rule, and a second copy drifts — that is the
lesson this repository keeps paying for. So `oracle()` feeds the hook the exact command strings
this script would run and prints its verdicts. The rule stays in one place; we compare against it
rather than remember it. When the hook cannot be found, that is REPORTED as unchecked, never
counted as passed.

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
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

#: `vX.Y.Z` and nothing after it. The same shape the hook accepts; anything else is not a patch.
#: Kept identical to `guard-release.VERSION_RE` on purpose — `oracle()` is what proves it still is.
VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

#: TCC's release line. The fourth copy of this glob (`install.sh`, `install.ps1`, `install.cmd`
#: hold the others) and the method's `installer-consistency.py` is what keeps them in step —
#: `tests/test_updates.py::test_our_installer_constants_agree_with_the_installers_own`.
TAG_GLOB = "v*"

#: Where the hub's hook lives, when it is on this machine at all. Ship works without it; it just
#: says so out loud rather than pretending the check passed.
HOOK = Path.home() / "dev" / "autosound-hub" / "hub" / "scripts" / "guard-release.py"

#: The suite, whole. `docs/TESTING.md`: run everything, every time — there is deliberately no
#: fast subset, and a release is the last place to invent one.
TEST_COMMAND = [sys.executable, "-m", "pytest", "tests/", "-q"]


class Stop(Exception):
    """A check said no. Carries the sentence a person reads, not a code."""


@dataclass
class Plan:
    """What ship worked out before it was allowed to touch anything."""

    root: Path
    newest: str = ""
    tag: str = ""
    version: str = ""
    method_sha: str = ""
    commands: list = field(default_factory=list)


def run(argv, cwd: Path, check: bool = True) -> str:
    done = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True)
    if check and done.returncode != 0:
        raise Stop(f"{' '.join(argv)} -> {done.returncode}\n{done.stderr.strip()}")
    return (done.stdout or "").strip()


# ---------------------------------------------------------------- read-only checks


def check_clean_tree(root: Path) -> None:
    dirty = run(["git", "status", "--porcelain"], root)
    if dirty:
        raise Stop("the working tree is not clean — a release must be a tree somebody can "
                   f"check out and get back:\n{dirty}")


def check_branch_synced(root: Path, remote: str = "origin") -> None:
    """On `main`, and level with the remote.

    Fetches first. Tagging a local `main` that is behind publishes a version nobody can reach by
    the branch, and one that is ahead publishes commits the remote has never seen.
    """
    branch = run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], root)
    if branch != "main":
        raise Stop(f"on branch `{branch}`, not `main` — a release is cut from main")
    run(["git", "fetch", "--quiet", remote], root)
    here = run(["git", "rev-parse", "HEAD"], root)
    there = run(["git", "rev-parse", f"{remote}/main"], root)
    if here != there:
        raise Stop(f"`main` and `{remote}/main` differ ({here[:12]} vs {there[:12]}) — "
                   "pull or push before shipping")


def check_follow_tags(root: Path) -> None:
    """`push.followTags=true` sends tags along with a branch push, WITHOUT the tag appearing in
    the command. Ship pushes its tag by name and on purpose; a config that also sends it silently
    would mean a tag can leave before the step meant to publish it — and before the hook can see a
    name. The hub names the same trap in its plan (§9.3); this is the local half.
    """
    done = subprocess.run(["git", "config", "--get", "push.followTags"],
                          cwd=str(root), capture_output=True, text=True)
    if (done.stdout or "").strip().lower() == "true":
        raise Stop("push.followTags is true — tags would ride out with the branch push, "
                   "unnamed and unseen. Turn it off: git config --unset push.followTags")


def newest_tag(root: Path, remote: str = "origin") -> Optional[str]:
    """The newest `vX.Y.Z` on the REMOTE — the same way the hook and the installers ask.

    Network, not `git tag`: a local list can be behind, and then ship would propose a number the
    hook computes differently and refuses. `--refs` is right HERE, where names are wanted — it
    keeps `v0.1.24^{}` out of the list. (The opposite of comparing shas, where dropping the peeled
    line is the bug — see `core/updates.py`.)
    """
    out = run(["git", "ls-remote", "--tags", "--refs", remote, TAG_GLOB], root, check=False)
    names = [line.rsplit("/", 1)[-1] for line in out.splitlines() if "/" in line]
    versions = [n for n in names if VERSION_RE.match(n)]
    if not versions:
        return None
    return max(versions, key=lambda n: tuple(int(g) for g in VERSION_RE.match(n).groups()))


def next_patch(newest: str) -> str:
    major, minor, patch = (int(g) for g in VERSION_RE.match(newest).groups())
    return f"v{major}.{minor}.{patch + 1}"


def check_rule(tag: str, newest: str) -> None:
    """Ship's own copy of the hook's rule — see this module's docstring for why it exists.

    Only the part ship can reach: it cuts patches in TCC's own line, so anything else is not
    ship's to do at all. Minor, major, a jump, a pre-release — all of those go through the
    `release` role, and a `make` target that could do them would hollow that role out.
    """
    if not VERSION_RE.match(tag):
        raise Stop(f"`{tag}` is not vX.Y.Z, so it is not a patch — that goes through `release`")
    nmaj, nmin, npat = (int(g) for g in VERSION_RE.match(newest).groups())
    maj, minor, patch = (int(g) for g in VERSION_RE.match(tag).groups())
    if (maj, minor) != (nmaj, nmin):
        raise Stop(f"`{tag}` changes major/minor against `{newest}` — that is an event, not "
                   "daily work. Through the `release` role.")
    if patch != npat + 1:
        raise Stop(f"expected `{next_patch(newest)}` (one after `{newest}`), got `{tag}` — "
                   "a patch is exactly +1 on the last number")


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


# ---------------------------------------------------------------- the oracle


def oracle(root: Path, commands: list, hook: Path = HOOK) -> list:
    """Ask the hub's hook what it makes of the exact commands ship would run.

    The point is NOT to gate on the answer — `check_rule` already did that. It is to compare our
    copy of the rule against its one owner, cheaply and without touching anything: no network, no
    writes, repeatable. A disagreement here means one of the two moved, and it shows up before a
    release rather than during one.

    Returns `(command, verdict, reason)` per command. A missing hook yields "не перевірено" and
    that is what gets printed — an unavailable check is never a passed one.
    """
    results = []
    for command in commands:
        if not hook.is_file():
            results.append((command, "не перевірено", f"хука нема: {hook}"))
            continue
        payload = json.dumps({"tool_name": "Bash", "cwd": str(root),
                              "tool_input": {"command": command}})
        done = subprocess.run([sys.executable, str(hook)], input=payload,
                              capture_output=True, text=True,
                              env={**os.environ, "HUB_ROLE": "tcc"})
        if done.returncode == 0:
            results.append((command, "ДОЗВОЛЕНО", ""))
        else:
            why = (done.stdout or done.stderr or "").strip().replace("\n", " ")
            results.append((command, "ВІДМОВА", why[:200]))
    return results


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


def ship(root: Path, release: bool, test_command=None, hook: Path = HOOK,
         read_method_sha: Callable[[Path], str] = method_sha,
         relock_with: Callable[[Path], None] = relock,
         say: Callable[[str], None] = print) -> Plan:
    """The whole thing. Reads and decides first; writes only when `release` is true."""
    plan = Plan(root=root)

    check_clean_tree(root)
    check_branch_synced(root)
    check_follow_tags(root)

    newest = newest_tag(root)
    if newest is None:
        raise Stop(f"no `{TAG_GLOB}` tag on the remote to count from — the first release is not "
                   "ship's to invent")
    plan.newest = newest
    plan.tag = next_patch(newest)
    plan.version = plan.tag.lstrip("v")
    check_rule(plan.tag, newest)

    changelog = check_changelog(root, plan.tag)

    plan.method_sha = read_method_sha(root)
    check_paired_method(changelog, plan.method_sha)

    plan.commands = [
        f"git tag {plan.tag}",
        "git push origin main",
        f"git push origin {plan.tag}",
    ]

    say(f"  newest on remote : {newest}")
    say(f"  next patch       : {plan.tag}")
    say(f"  method           : {plan.method_sha[:12] or '(unknown)'}")
    say("  hook says:")
    for command, verdict, why in oracle(root, plan.commands, hook):
        say(f"    {command:<28} {verdict} {why}")

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
        print(f"\n  STOP: {stop}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
