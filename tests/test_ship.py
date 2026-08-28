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

**The channel half is not tested here any more, and that is the point of HUB-003.** Clean tree,
HEAD published, `push.followTags`, the tag free on the remote and the rule itself now belong to
`hub/scripts/release-preflight.py`, which has its own suite — 33 cases,
`python3 hub/scripts/test-release-preflight.py`. What is left to prove HERE is the seam: that ship
asks that carrier, as `tcc`, for the next patch; that a refusal from it stops the release with
nothing written; that every refusal is named in one run rather than one per run; and that a
missing hub is a refusal rather than a shrug.

**The stand-in is held to the real thing.** The fixture cannot call the carrier — its `origin` is
a directory, not `github.com/ayukhno/autosound-tcc`, and the carrier would rightly refuse it. So
the checks it returns are stand-ins, and `test_the_stand_in_has_the_carriers_shape` compares them
against the real module when the hub is on this machine: the same attributes, the same verdict
strings, the same thing gating. A stand-in nobody compares is how a green suite starts lying.

**What none of it proves** is the first real run: GitHub's own reaction to the pushes. That is
somebody else's system and it is not destructive — a rejected push publishes nothing.
"""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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

#: The carrier's verdict words, copied here so the fixture can run without the hub — and pinned to
#: the real ones by `test_the_stand_in_has_the_carriers_shape`.
FAIL, OK, UNKNOWN = "ПРОВАЛ", "ok", "не перевірено"


def checks(*pairs):
    """Stand-ins for the carrier's `Check`, in its shape: `("clean-tree", OK), …`."""
    return [SimpleNamespace(name=name, verdict=verdict, line=f"({verdict})",
                            gates=verdict == FAIL)
            for name, verdict in pairs]


def channel(tag="v0.1.25", answers=(("clean-tree", OK), ("rule", OK))):
    """A stand-in for `ship.channel_checks`: the carrier, without the carrier."""
    return lambda _root: (tag, checks(*answers))


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

    return work


def _relock(root):
    """What `uv lock` does to the one line this project cares about: carry pyproject's version
    into the lock. Stubbed because the fixture is not a real uv project — what is under test is
    that ship CALLS it and commits the result, not uv's own correctness."""
    version = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(), re.M)
    lock = root / "uv.lock"
    lock.write_text(re.sub(r'^version = "[^"]+"', f'version = "{version.group(1)}"',
                           lock.read_text(), flags=re.M), encoding="utf-8")


def _run(repo, release=True, test_exit=0, ask=None, say=lambda _m: None):
    """Ship on the fixture, with the suite stubbed and the channel half stood in for."""
    stub = [sys.executable, "-c", f"import sys; sys.exit({test_exit})"]
    return ship_mod.ship(repo, release=release, test_command=stub,
                         channel=ask or channel(),
                         read_method_sha=lambda _root: METHOD_SHA,
                         relock_with=_relock, say=say)


# ---------------------------------------------------------------- what the fixture proves


def test_a_clean_release_bumps_commits_tags_and_pushes_one_tag_by_name(repo):
    """The happy path, end to end, against a real remote that happens to be a directory."""
    plan = _run(repo)

    assert plan.tag == "v0.1.25", "the tag is the carrier's answer, not ship's arithmetic"
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
])
def test_every_refusal_happens_before_anything_is_written(repo, break_it, expect):
    """Each INVENTORY gate, and the same assertion after each: the tree is untouched.

    A dirty tree used to be the third case here. It is the carrier's now, and the case that
    replaced it is `test_a_channel_refusal_stops_ship_before_anything_is_written` below.
    """
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


# ---------------------------------------------------------------- the seam to the hub


def test_a_channel_refusal_stops_ship_before_anything_is_written(repo):
    """The carrier says no, and ship stops there — the case a dirty tree used to make."""
    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo, ask=channel(answers=(("clean-tree", FAIL), ("rule", OK))))

    assert "clean-tree" in str(stop.value)
    assert 'version = "0.1.24"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert git(repo, "tag", "--list", "v0.1.25") == "", "and no tag"


def test_one_run_names_every_refusal_not_just_the_first(repo):
    """The carrier's own form (`RELEASE-CHANNEL.md` §9.5), and the reason it returns a LIST.

    Ship used to stop at the first check that said no, so four problems took four runs to find.
    Passing the list on unchanged is the whole benefit; folding it back to the first would undo it
    silently, because the run still ends in a refusal either way.
    """
    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo, ask=channel(answers=(("clean-tree", FAIL), ("rule", OK),
                                        ("follow-tags", FAIL), ("tag-free", FAIL))))

    said = str(stop.value)
    for name in ("clean-tree", "follow-tags", "tag-free"):
        assert name in said, f"{name} was refused and the run did not say so: {said}"
    assert "3 of 4" in said


def test_unchecked_is_printed_and_does_not_stop_the_release(repo):
    """`не перевірено` is the carrier's word for a check it could not make — the hook missing,
    most often. It is not a refusal, and it is not a pass either: it gets said."""
    lines = []
    _run(repo, ask=channel(answers=(("clean-tree", OK), ("oracle: git tag v0.1.25", UNKNOWN))),
         say=lines.append)

    assert git(repo, "tag", "--list", "v0.1.25") == "v0.1.25", "an unchecked line is not a refusal"
    assert any(UNKNOWN in line for line in lines), f"it went unsaid: {lines}"


def test_a_missing_hub_is_a_refusal_not_a_shrug(tmp_path):
    """The decision HUB-003 left to this role. The hook is invisible to `make ship`, so a carrier
    that is not there means nothing at all is checking the release."""
    with pytest.raises(ship_mod.Stop) as stop:
        ship_mod.load_carrier(tmp_path / "not-here.py")

    assert "not on this machine" in str(stop.value)
    assert str(tmp_path / "not-here.py") in str(stop.value), "it must name the path it looked at"


def test_ship_defaults_to_the_real_carrier():
    """The stand-in exists for the fixture. If it ever became the DEFAULT, every test here would
    still be green and no release would be checked by anything."""
    default = inspect.signature(ship_mod.ship).parameters["channel"].default
    assert default is ship_mod.channel_checks
    assert inspect.signature(ship_mod.channel_checks).parameters["path"].default \
        == ship_mod.CARRIER


def test_ship_asks_the_carrier_as_tcc_and_for_the_next_patch(monkeypatch, tmp_path):
    """The role is what decides which repository and which line the carrier reports on — and the
    hook it consults reads the repository from `cwd`. Asked as anything else, the answer would be
    about somebody else's releases."""
    seen = {}

    class Recorder:
        def preflight(self, root, role, tag=None, want_next=False):
            seen.update(root=root, role=role, tag=tag, want_next=want_next)
            return "v0.1.25", []

    monkeypatch.setattr(ship_mod, "load_carrier", lambda *_a, **_k: Recorder())
    ship_mod.channel_checks(tmp_path)

    assert seen["role"] == "tcc"
    assert seen["want_next"] is True and seen["tag"] is None, "ship names no tag; it asks for next"


def test_the_stand_in_has_the_carriers_shape():
    """THE test the fixture cannot be: the real carrier, on this machine.

    No network and no writes — the module is loaded and its shape is read. It does not RUN the
    preflight on purpose: that fetches, and it would go red on a dirty working tree, which is the
    normal state of this repository while somebody is working in it.

    Skipped, loudly, when the hub is not here. A skip is a skip, never a pass.
    """
    if not ship_mod.CARRIER.is_file():
        pytest.skip(f"the hub's carrier is not on this machine ({ship_mod.CARRIER})")

    carrier = ship_mod.load_carrier()

    assert (carrier.FAIL, carrier.OK, carrier.UNKNOWN) == (FAIL, OK, UNKNOWN), (
        "the verdict words this file stands in for have moved")
    parameters = inspect.signature(carrier.preflight).parameters
    assert {"root", "role", "tag", "want_next"} <= set(parameters), (
        f"ship calls preflight by these names: {list(parameters)}")

    real = carrier.Check(name="n", verdict=FAIL, line="l")
    stand_in = checks(("n", FAIL))[0]
    assert {"name", "verdict", "line"} <= set(vars(real))
    assert real.gates is stand_in.gates is True, "a refusal must gate in both"
    assert carrier.Check("n", UNKNOWN, "l").gates is checks(("n", UNKNOWN))[0].gates is False, (
        "`не перевірено` must gate in neither — it is not a refusal")


# ---------------------------------------------------------------- what ship still owns


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
