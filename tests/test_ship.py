"""`make ship` — accepted without ever cutting a real release.

Ship's last act publishes a tag, and a published tag can never be moved or deleted by anyone
afterwards. So a live case on a real release is not an option, and this file is what stands in
its place. It is worth being explicit about what each half proves, because the gap between them
is where a green suite would otherwise lie.

**The fixture repo (most of this file).** A real `git init` working tree with a real
`git init --bare` beside it as `origin`, a fake `pyproject.toml` and `CHANGELOG.md`, and the test
command stubbed so it can be made to fail on demand. That is enough to prove the things that
actually go wrong in a release script: the ORDER (bump before tests, tag on the tested tree), the
ROLLBACK (a red suite leaves no bump, no commit, no tag), the ABORTS (a mismatched changelog stops
before anything is written), and that the push sends exactly one tag BY NAME rather than in bulk.

**What the fixture repo cannot prove, and it is not a small thing.** Its `origin` is a directory,
not `github.com/ayukhno/autosound-tcc`, so the hub's `guard-release` hook returns "somebody else's
repository, not our business" and waves everything through. A green fixture run therefore says
NOTHING about whether the real commands would be allowed. That is the same shape as an error
already written down in this project — a refusal produced by fail-closed is not evidence that the
matching rule works.

**So the oracle covers it.** `test_the_hook_agrees_with_our_copy_of_the_rule` feeds the real hook
the exact command strings ship would run, with the real repository as `cwd`, and compares its
verdicts against `check_rule`. No network, no writes, and it fails if either copy of the rule
moves. It skips when the hook is not on this machine — and a skip is reported as a skip, never as
a pass.

**What neither proves** is the first real run: GitHub's own reaction to the pushes. Both are
somebody else's system and neither is destructive — a rejected push publishes nothing.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ship as ship_mod  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

CHANGELOG = """# Changelog

## [{tag}] — 2026-08-27 · a sentence a person wrote

Paired with method `{sha}`.

- something changed
"""

PYPROJECT = '''[project]
name = "fixture"
version = "{version}"
'''

METHOD_SHA = "a" * 40


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert done.returncode == 0, f"git {' '.join(args)}\n{done.stderr}"
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A working tree with a bare repository beside it as `origin`, tagged `v0.1.24`.

    Shaped like TCC's own: a `main` branch, a version in `pyproject.toml`, a changelog whose top
    entry names the NEXT tag, and the method's sha stubbed.
    """
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--quiet", "--bare", str(origin)], check=True)
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(work)], check=True)
    git(work, "config", "user.email", "t@t")
    git(work, "config", "user.name", "t")
    git(work, "remote", "add", "origin", str(origin))

    (work / "pyproject.toml").write_text(PYPROJECT.format(version="0.1.24"), encoding="utf-8")
    (work / "CHANGELOG.md").write_text(
        CHANGELOG.format(tag="v0.1.25", sha=METHOD_SHA), encoding="utf-8")
    (work / "uv.lock").write_text(
        'name = "fixture"\nversion = "0.1.24"\n', encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "--quiet", "-m", "start")
    git(work, "tag", "v0.1.24")
    git(work, "push", "--quiet", "origin", "main")
    git(work, "push", "--quiet", "origin", "v0.1.24")

    monkeypatch.setattr(ship_mod, "HOOK", tmp_path / "no-hook-here.py")
    return work


def _relock(root):
    """What `uv lock` does to the one line this project cares about: carry pyproject's version
    into the lock. Stubbed because the fixture is not a real uv project — what is under test is
    that ship CALLS it and commits the result, not uv's own correctness."""
    version = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(), re.M)
    lock = root / "uv.lock"
    lock.write_text(re.sub(r'^version = "[^"]+"', f'version = "{version.group(1)}"',
                           lock.read_text(), flags=re.M), encoding="utf-8")


def _run(repo, release=True, test_exit=0):
    """Ship on the fixture, with the suite stubbed to whatever outcome the test needs."""
    stub = [sys.executable, "-c", f"import sys; sys.exit({test_exit})"]
    return ship_mod.ship(repo, release=release, test_command=stub,
                         read_method_sha=lambda _root: METHOD_SHA,
                         relock_with=_relock, say=lambda _m: None)


# ---------------------------------------------------------------- what the fixture proves


def test_a_clean_release_bumps_commits_tags_and_pushes_one_tag_by_name(repo):
    """The happy path, end to end, against a real remote that happens to be a directory."""
    plan = _run(repo)

    assert plan.newest == "v0.1.24" and plan.tag == "v0.1.25"
    assert 'version = "0.1.25"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert git(repo, "status", "--porcelain") == "", "the release commit took everything with it"

    origin = git(repo, "ls-remote", "--tags", "--refs", "origin")
    assert "refs/tags/v0.1.25" in origin
    assert origin.count("refs/tags/") == 2, "one new tag, not everything local"
    assert git(repo, "rev-parse", "v0.1.25^{commit}") == git(repo, "rev-parse", "origin/main")


def test_the_tag_sits_on_the_tree_that_was_tested(repo):
    """The reason the bump comes before the suite. If it came after, the tested tree and the
    tagged tree would differ by exactly the file that says which release this is."""
    _run(repo)

    tagged = git(repo, "show", "v0.1.25:pyproject.toml")
    assert 'version = "0.1.25"' in tagged, "the tagged tree carries its own version"


def test_a_red_suite_rolls_the_bump_back_and_leaves_nothing(repo):
    """The failure that matters most: a release script that half-ran."""
    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo, test_exit=1)

    assert "rolled back" in str(stop.value)
    assert 'version = "0.1.24"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert git(repo, "status", "--porcelain") == "", "no half-written tree left behind"
    assert git(repo, "tag", "--list", "v0.1.25") == "", "and no tag"
    assert git(repo, "log", "--oneline", "-1") == git(repo, "log", "--oneline", "-1", "origin/main")


@pytest.mark.parametrize("break_it, expect", [
    ("changelog", "top entry"),
    ("paired", "Paired with method"),
    ("dirty", "not clean"),
])
def test_every_refusal_happens_before_anything_is_written(repo, break_it, expect):
    """Each gate, and the same assertion after each: the tree is untouched."""
    if break_it == "changelog":
        (repo / "CHANGELOG.md").write_text(
            CHANGELOG.format(tag="v0.9.9", sha=METHOD_SHA), encoding="utf-8")
        git(repo, "commit", "--quiet", "-am", "wrong entry")
        git(repo, "push", "--quiet", "origin", "main")
    elif break_it == "paired":
        (repo / "CHANGELOG.md").write_text(
            CHANGELOG.format(tag="v0.1.25", sha=METHOD_SHA).replace(
                "Paired with method `" + METHOD_SHA + "`.", "no pairing line here"),
            encoding="utf-8")
        git(repo, "commit", "--quiet", "-am", "no pairing")
        git(repo, "push", "--quiet", "origin", "main")
    elif break_it == "dirty":
        (repo / "stray.txt").write_text("uncommitted", encoding="utf-8")

    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo)

    assert expect in str(stop.value)
    assert 'version = "0.1.24"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert git(repo, "tag", "--list", "v0.1.25") == ""


def test_a_dry_run_writes_nothing_at_all(repo):
    """The default. It must reach the same conclusions and leave the same tree behind."""
    before = git(repo, "rev-parse", "HEAD")

    plan = _run(repo, release=False)

    assert plan.tag == "v0.1.25", "it still worked the number out"
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "tag", "--list", "v0.1.25") == ""
    assert 'version = "0.1.24"' in (repo / "pyproject.toml").read_text(encoding="utf-8")


def test_follow_tags_stops_it(repo):
    """A config, not a command — the one thing that could push the tag before ship means to."""
    git(repo, "config", "push.followTags", "true")

    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo, release=False)

    assert "followTags" in str(stop.value)


def test_a_branch_out_of_step_with_the_remote_stops_it(repo):
    """Tagging a `main` that is ahead publishes a version the remote has never seen."""
    (repo / "extra.txt").write_text("local only", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "local only")

    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo, release=False)

    assert "differ" in str(stop.value)


# ---------------------------------------------------------------- the rule, and its owner


@pytest.mark.parametrize("tag, newest, ok", [
    ("v0.1.25", "v0.1.24", True),
    ("v0.1.26", "v0.1.24", False),   # a jump
    ("v0.2.0", "v0.1.24", False),    # minor
    ("v1.0.0", "v0.1.24", False),    # major
    ("v0.1.25-rc1", "v0.1.24", False),  # pre-release
    ("release-0.1.25", "v0.1.24", False),
])
def test_ships_own_copy_of_the_rule(tag, newest, ok):
    """`check_rule` on its own. Everything but +1 in the last number belongs to `release`."""
    if ok:
        ship_mod.check_rule(tag, newest)
    else:
        with pytest.raises(ship_mod.Stop):
            ship_mod.check_rule(tag, newest)


def test_the_hook_agrees_with_our_copy_of_the_rule():
    """THE test the fixture repo cannot be: the real hook, on the real repository.

    `check_rule` is a second copy of a rule the hub owns, and a second copy drifts. So the same
    names go to both, and the verdicts must match. Nothing is written and nothing is fetched from
    a remote we do not already talk to; the hook is asked, not the network.

    Skipped, loudly, when the hub is not on this machine — an unavailable check is not a passed
    one, which is the whole reason `oracle()` reports "не перевірено" rather than staying quiet.
    """
    if not ship_mod.HOOK.is_file():
        pytest.skip(f"the hub's hook is not on this machine ({ship_mod.HOOK})")

    newest = ship_mod.newest_tag(ROOT)
    if newest is None:
        pytest.skip("could not read the remote's tags")
    good = ship_mod.next_patch(newest)
    major, minor, patch = (int(g) for g in ship_mod.VERSION_RE.match(newest).groups())
    jump = f"v{major}.{minor}.{patch + 2}"

    verdicts = dict((command, verdict) for command, verdict, _why in ship_mod.oracle(
        ROOT, [f"git tag {good}", f"git push origin {good}", "git push origin main",
               f"git tag {jump}", "git push --tags origin"]))

    assert verdicts[f"git tag {good}"] == "ДОЗВОЛЕНО", (
        f"ship would cut {good} and the hook refuses it — one of the two rules moved")
    assert verdicts[f"git push origin {good}"] == "ДОЗВОЛЕНО"
    assert verdicts["git push origin main"] == "ДОЗВОЛЕНО"
    assert verdicts[f"git tag {jump}"] == "ВІДМОВА", "a jump must be refused by both"
    assert verdicts["git push --tags origin"] == "ВІДМОВА", "bulk pushes have no target"

    # And our own copy says the same about the same two names.
    ship_mod.check_rule(good, newest)
    with pytest.raises(ship_mod.Stop):
        ship_mod.check_rule(jump, newest)


def test_ship_never_pushes_in_BULK_and_never_releases(repo):
    """The two forms that would hollow out the `release` role, asserted twice over.

    On the commands ship actually builds — the closed set it can run — and on its source, because
    a future edit could add a push this fixture never exercises. The source check looks for a
    `push` and a `--tags` on the SAME line: `newest_tag` legitimately reads `ls-remote --tags`,
    and a blanket ban on the string would fail on the one place it is correct. (Written the crude
    way first; the suite said so.)
    """
    plan = _run(repo, release=False)

    assert plan.commands == ["git tag v0.1.25", "git push origin main",
                             "git push origin v0.1.25"]
    for command in plan.commands:
        assert "--tags" not in command and "--follow-tags" not in command

    source = (ROOT / "scripts" / "ship.py").read_text(encoding="utf-8")
    body = source.split('"""', 2)[2]  # past the module docstring, which quotes them on purpose
    code = [line.split("#", 1)[0] for line in body.splitlines()]
    pushes = [line for line in code if "push" in line and "--tags" in line]
    assert not pushes, f"a push that carries no tag name: {pushes}"
    assert "gh release" not in body, "releases belong to the `release` role, not to a make target"


def test_the_lock_file_moves_with_the_version_and_lands_in_the_release_commit(repo):
    """Found by ship's own clean-tree gate, the first time it ran after a release.

    `uv.lock` records the project's OWN version. Ship bumped `pyproject.toml` and not the lock, so
    `v0.1.25` was tagged on a tree whose lock still said `0.1.24` — and the next `uv run` rewrote
    it, leaving a dirty tree that refused the following release. One fact in two files, which is
    the shape this project keeps paying for.
    """
    _run(repo)

    assert 'version = "0.1.25"' in (repo / "uv.lock").read_text(encoding="utf-8")
    assert git(repo, "status", "--porcelain") == "", "nothing left over for the next run to trip on"
    changed = git(repo, "show", "--name-only", "--format=", "v0.1.25").split()
    assert "uv.lock" in changed, f"the lock did not travel with the release commit: {changed}"


def test_a_red_suite_puts_the_lock_back_too(repo):
    """The rollback has to undo both halves, or a failed release leaves the lock ahead of the
    version it locks."""
    with pytest.raises(ship_mod.Stop):
        _run(repo, test_exit=1)

    assert 'version = "0.1.24"' in (repo / "uv.lock").read_text(encoding="utf-8")
    assert git(repo, "status", "--porcelain") == ""
