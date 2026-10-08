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

**The path to the carrier is held here too, since HUB-005 (autosound-hub#12).** Ship asking the
carrier proves nothing if ship cannot find it: an absolute path built from `$HOME` pointed at a
folder that had been renamed, and ship fell before its first check. Everything above stayed green
through it — a seam is only tested from the side that is wired up.

**What none of it proves** is the first real run: GitHub's own reaction to the pushes. That is
somebody else's system and it is not destructive — a rejected push publishes nothing.
"""

from __future__ import annotations

import importlib.util
import inspect
import itertools
import os
import re
import shutil
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
- and something else
"""

UNRELEASED = """# Changelog

## [Unreleased]

- a candidate carries this

## [v0.1.24] — 2026-08-20 · the one before

Paired with method `{sha}`.

- old
- older
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
    return lambda _root, **_asked: (tag, checks(*answers))


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert done.returncode == 0, f"git {' '.join(args)}\n{done.stderr}"
    return done.stdout.strip()


def public_key(path: Path) -> str:
    """`type key` of a `.pub` file — the two words `allowed_signers` and git compare."""
    return " ".join(path.read_text(encoding="utf-8").split()[:2])


@pytest.fixture(scope="session")
def signing_keys(tmp_path_factory):
    """Two throwaway SSH keys, `author` and `stranger`, made here — never the real key, never
    `~/.ssh` (tcc#102). Once per session: every release in this file signs its tag now.

    No `ssh-keygen`, no signed tag: ship cannot release on such a machine, so the release cases
    skip there, loudly, rather than pass on a tag nobody signed."""
    if shutil.which("ssh-keygen") is None:
        pytest.skip("no ssh-keygen on this machine: ship cannot sign a tag here")
    where = tmp_path_factory.mktemp("signing-keys")
    for who in ("author", "stranger"):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", who,
                        "-f", str(where / who)], check=True, capture_output=True)
    return {who: where / f"{who}.pub" for who in ("author", "stranger")}


def no_machine_git(monkeypatch) -> None:
    """Git with nothing of the machine's: global and system config shut out, so the developer's
    own `user.signingkey` cannot reach a fixture, and no ssh-agent to talk to."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)


def sign_with(work: Path, key: Path) -> None:
    """Git in `work` signs tags with `key`, the way `~/.gitconfig` does it on the release machine."""
    git(work, "config", "gpg.format", "ssh")
    git(work, "config", "user.signingkey", str(key))


@pytest.fixture
def repo(tmp_path, monkeypatch, signing_keys):
    """A working tree with a bare repository beside it as `origin`, tagged `v0.1.24`.

    Shaped like TCC's own: a `main` branch, a version in `pyproject.toml`, a changelog whose top
    entry names the NEXT tag, and the method's sha stubbed. It signs like TCC's too (tcc#102):
    `allowed_signers` at the root, and git set to sign with the key in it — a throwaway one.
    """
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    no_machine_git(monkeypatch)
    subprocess.run(["git", "init", "--quiet", "--bare", str(origin)], check=True)
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(work)], check=True)
    git(work, "config", "user.email", "t@t")
    git(work, "config", "user.name", "t")
    git(work, "remote", "add", "origin", str(origin))
    sign_with(work, signing_keys["author"])
    (work / "allowed_signers").write_text(
        f'author namespaces="git" {public_key(signing_keys["author"])}\n', encoding="utf-8")

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


def _run(repo, release=True, test_exit=0, ask=None, say=lambda _m: None, published=None,
         **mode):
    """Ship on the fixture, with the suite stubbed and the channel half stood in for."""
    stub = [sys.executable, "-c", f"import sys; sys.exit({test_exit})"]
    return ship_mod.ship(repo, release=release, test_command=stub,
                         channel=ask or channel(),
                         read_method_sha=lambda _root: METHOD_SHA,
                         # The method's remote is not asked from the fixture either: it has no
                         # submodule, and the suite does not reach the network. The default
                         # stands for the state a release is allowed to happen in — the pin
                         # carries a published tag.
                         read_published_tags=published or (lambda _root, _sha: ["v3.0.58"]),
                         # The fixture has no submodule at all, so the recorded pin is stood in
                         # for as well — agreeing with the checkout, which is the state a release
                         # is allowed to happen in. `test_a_release_refuses_when_the_checkout_is_
                         # not_the_recorded_pin` covers the disagreement directly.
                         read_pinned_sha=lambda _root: METHOD_SHA,
                         relock_with=_relock, say=say, **mode)


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


# ---------------------------------------------------------------- the CHANGELOG, per mode


def test_a_release_refuses_while_unreleased_is_still_there(repo):
    """The skill's rule (tag-check.sh): the notes are renamed to the tag BEFORE it is cut."""
    text = CHANGELOG.format(tag="v0.1.25", sha=METHOD_SHA).replace(
        "# Changelog\n", "# Changelog\n\n## [Unreleased]\n\n- not renamed yet\n")
    (repo / "CHANGELOG.md").write_text(text, encoding="utf-8")

    with pytest.raises(ship_mod.Stop) as stop:
        ship_mod.check_changelog(repo, "v0.1.25")

    assert "rename it to `## [v0.1.25]` first" in str(stop.value)


def test_a_release_entry_shorter_than_three_lines_is_a_forgotten_note(repo):
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [v0.1.25] — 2026-08-27 · short\n\nPaired with method `x`.\n",
        encoding="utf-8")

    with pytest.raises(ship_mod.Stop) as stop:
        ship_mod.check_changelog(repo, "v0.1.25")

    assert "forgotten note" in str(stop.value)


def test_a_candidate_reads_its_notes_from_unreleased(repo):
    (repo / "CHANGELOG.md").write_text(UNRELEASED.format(sha=METHOD_SHA), encoding="utf-8")

    ship_mod.check_candidate_changelog(repo, "v0.2.0")  # no Stop


def test_a_candidate_reads_its_own_section_when_the_version_is_already_named(repo):
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [v0.2.0] — 2026-09-20 · named early\n\n- tried\n", encoding="utf-8")

    ship_mod.check_candidate_changelog(repo, "v0.2.0")  # no Stop


def test_an_empty_unreleased_is_a_forgotten_note_for_a_candidate_too(repo):
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [v0.1.24] — x\n\n- old\n", encoding="utf-8")

    with pytest.raises(ship_mod.Stop) as stop:
        ship_mod.check_candidate_changelog(repo, "v0.2.0")

    assert "forgotten note" in str(stop.value)


def test_a_candidate_with_no_notes_at_all_is_refused(repo):
    # The fixture's CHANGELOG has only `## [v0.1.25]`: neither the version nor Unreleased.
    with pytest.raises(ship_mod.Stop) as stop:
        ship_mod.check_candidate_changelog(repo, "v0.2.0")

    assert "nothing says what the candidate carries" in str(stop.value)


def test_the_paired_line_is_read_from_the_tags_own_section():
    """Not from whatever block happens to be first: an Unreleased section above has no pairing."""
    text = ("# Changelog\n\n## [Unreleased]\n\n- no pairing here\n\n"
            f"## [v0.1.25] — 2026-08-27 · x\n\nPaired with method `{METHOD_SHA}`.\n\n- a\n- b\n")

    ship_mod.check_paired_method(text, METHOD_SHA, "v0.1.25")  # no Stop


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
    that is not there means nothing at all is checking the release.

    The hint in that refusal is checked too (HUB-005): it used to be a hand-typed
    `~/dev/autosound-hub/hub`, and after the rename it sent the reader off to clone the hub into a
    folder where the hub already sat under a different name. A hint that leads somewhere dead
    costs more than no hint, because the reader goes and works.
    """
    missing = tmp_path / "nothing-here" / "hub" / "scripts" / "release-preflight.py"

    with pytest.raises(ship_mod.Stop) as stop:
        ship_mod.load_carrier(missing)

    said = str(stop.value)
    assert "not on this machine" in said
    assert str(missing) in said, "it must name the path it looked at"

    # Picked out on its own. Asking merely whether the folder appears in the sentence proves
    # nothing — it is a PREFIX of the full path named a clause earlier, so the check passes while
    # the hint is still a constant. Caught by mutation: the first version of this assertion was
    # green with `~/dev/autosound/hub` typed back in.
    hint = re.search(r"Clone the hub to (\S+) and run ship again", said)
    assert hint, f"the refusal must keep its `Clone the hub to ...` hint; got: {said}"
    assert hint.group(1) == str(missing.parents[1]), "the hint is computed from the path, not typed"


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
        def preflight(self, root, role, tag=None, want_next=False, candidate=None):
            seen.update(root=root, role=role, tag=tag, want_next=want_next, candidate=candidate)
            return "v0.1.25", []

    monkeypatch.setattr(ship_mod, "load_carrier", lambda *_a, **_k: Recorder())
    monkeypatch.delenv("HUB_ROLE", raising=False)
    ship_mod.channel_checks(tmp_path)

    assert seen["role"] == "tcc"
    assert seen["want_next"] is True and seen["tag"] is None, "ship names no tag; it asks for next"
    assert seen["candidate"] is None


class _Recorder:
    def __init__(self):
        self.seen = {}

    def preflight(self, root, role, tag=None, want_next=False, candidate=None):
        self.seen.update(root=root, role=role, tag=tag, want_next=want_next, candidate=candidate)
        return "v0.2.0", []


@pytest.mark.parametrize("asked, expect", [
    ({"candidate": "v0.2.0"}, {"candidate": "v0.2.0", "tag": None, "want_next": False}),
    ({"version": "v0.2.0"}, {"candidate": None, "tag": "v0.2.0", "want_next": False}),
    ({}, {"candidate": None, "tag": None, "want_next": True}),
])
def test_each_mode_asks_the_carrier_its_own_question(monkeypatch, tmp_path, asked, expect):
    recorder = _Recorder()
    monkeypatch.setattr(ship_mod, "load_carrier", lambda *_a, **_k: recorder)
    monkeypatch.delenv("HUB_ROLE", raising=False)

    ship_mod.channel_checks(tmp_path, **asked)

    assert {key: recorder.seen[key] for key in expect} == expect
    assert recorder.seen["role"] == "tcc"


def test_the_role_comes_from_the_session_so_release_can_cut_a_minor(monkeypatch, tmp_path):
    """ship does not restate who may cut what: it passes the session's role, and the hook decides."""
    recorder = _Recorder()
    monkeypatch.setattr(ship_mod, "load_carrier", lambda *_a, **_k: recorder)
    monkeypatch.setenv("HUB_ROLE", "release")

    ship_mod.channel_checks(tmp_path, version="v0.2.0")

    assert recorder.seen["role"] == "release"


def _write_changelog(repo, text):
    """Commit and publish a CHANGELOG — the state a release is cut from."""
    (repo / "CHANGELOG.md").write_text(text, encoding="utf-8")
    git(repo, "commit", "--quiet", "-am", "changelog")
    git(repo, "push", "--quiet", "origin", "main")


def test_a_candidate_dry_run_names_the_beta_tag_and_writes_nothing(repo):
    _write_changelog(repo, UNRELEASED.format(sha=METHOD_SHA))
    before = git(repo, "rev-parse", "HEAD")

    plan = _run(repo, release=False, ask=channel(tag="beta-v0.2.0-rc1"), candidate="v0.2.0")

    assert (plan.mode, plan.tag) == ("candidate", "beta-v0.2.0-rc1")
    assert plan.commands == ["git tag -s beta-v0.2.0-rc1 -m beta-v0.2.0-rc1",
                             "git push origin main", "git push origin beta-v0.2.0-rc1"]
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "tag", "--list", "beta-v0.2.0-rc1") == ""


def test_a_candidate_tags_head_pushes_the_tag_and_writes_nothing_else(repo):
    _write_changelog(repo, UNRELEASED.format(sha=METHOD_SHA))
    before = git(repo, "rev-parse", "HEAD")
    lock = (repo / "uv.lock").read_text(encoding="utf-8")

    # A red suite stops a release; here it proves that no suite runs for a candidate at all.
    _run(repo, test_exit=1, ask=channel(tag="beta-v0.2.0-rc1"), candidate="v0.2.0")

    assert git(repo, "rev-parse", "HEAD") == before, "no commit"
    assert git(repo, "rev-parse", "beta-v0.2.0-rc1^{commit}") == before, "the tag is on HEAD"
    assert "refs/tags/beta-v0.2.0-rc1" in git(repo, "ls-remote", "--tags", "origin"), "published"
    assert 'version = "0.1.24"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert (repo / "uv.lock").read_text(encoding="utf-8") == lock


def test_a_candidate_without_notes_stops_before_the_tag(repo):
    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo, ask=channel(tag="beta-v0.2.0-rc1"), candidate="v0.2.0")

    assert "nothing says what the candidate carries" in str(stop.value)
    assert git(repo, "tag", "--list", "beta-v0.2.0-rc1") == ""


def test_a_patch_with_unreleased_on_top_stops_before_anything_is_written(repo):
    _write_changelog(repo, CHANGELOG.format(tag="v0.1.25", sha=METHOD_SHA).replace(
        "# Changelog\n", "# Changelog\n\n## [Unreleased]\n\n- not renamed yet\n"))

    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo)

    assert "rename it to" in str(stop.value)
    assert 'version = "0.1.24"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert git(repo, "tag", "--list", "v0.1.25") == ""


def test_an_explicit_version_releases_like_a_patch(repo):
    seen = {}

    def ask(_root, **asked):
        seen.update(asked)
        return "v0.1.25", checks(("clean-tree", OK), ("rule", OK))

    plan = _run(repo, ask=ask, version="v0.1.25")

    assert seen == {"candidate": None, "version": "v0.1.25"}
    assert plan.mode == "version"
    assert git(repo, "tag", "--list", "v0.1.25") == "v0.1.25"
    assert 'version = "0.1.25"' in (repo / "pyproject.toml").read_text(encoding="utf-8")


def test_candidate_and_version_exclude_each_other(repo):
    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo, candidate="v0.2.0", version="v0.2.0")

    assert "exclude each other" in str(stop.value)


def test_the_command_line_takes_one_mode(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(ship_mod, "ship", lambda root, **kw: seen.update(kw))

    assert ship_mod.main(["--root", str(tmp_path), "--candidate", "v0.2.0"]) == 0
    assert (seen["candidate"], seen["version"], seen["release"]) == ("v0.2.0", "", False)

    with pytest.raises(SystemExit) as usage:
        ship_mod.main(["--candidate", "v0.2.0", "--tag", "v0.2.0"])
    assert usage.value.code == 2


def _make_n(*args, env=None):
    """`make -n` on this repository, deaf to any make that launched the suite.

    A variable typed after a PARENT make reaches every child make through `MAKEFLAGS`
    (`s -- REAL=1 VERSION=v0.2.0`, GNU Make 3.81) with the origin `command line`, exactly as if it
    had been typed there. `make ship VERSION=vX.Y.Z REAL=1` runs this suite, so without this the
    environment case below would go red inside that release and refuse it. Measured 2026-09-13.
    """
    inherited = {name: value for name, value in (env or os.environ).items()
                 if name not in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL")}
    return subprocess.run(["make", "-n", *args], cwd=str(ROOT), capture_output=True, text=True,
                          env=inherited)


@pytest.mark.skipif(shutil.which("make") is None, reason="no make on this machine")
@pytest.mark.parametrize("assignment, flag", [
    ("CANDIDATE=v0.2.0", "--candidate v0.2.0"),
    ("VERSION=v0.2.0", "--tag v0.2.0"),
])
def test_make_ship_passes_the_mode_to_the_script(assignment, flag):
    for extra in ([], ["REAL=1"]):
        done = _make_n("ship", assignment, *extra)
        assert done.returncode == 0, done.stderr
        assert flag in done.stdout, done.stdout


@pytest.mark.skipif(shutil.which("make") is None, reason="no make on this machine")
def test_a_version_in_the_environment_does_not_change_the_mode(monkeypatch):
    """`VERSION` is a common enough variable name that a shell may carry one; only a word typed
    after `make ship` may turn a patch into a named release.

    Run as it would be inside `make ship VERSION=v0.2.0 REAL=1`, with that make's `MAKEFLAGS` in
    the environment: the release's own suite must not read its mode as this make's."""
    monkeypatch.setenv("MAKEFLAGS", "s -- REAL=1 VERSION=v0.2.0")
    done = _make_n("ship", env={**os.environ, "VERSION": "v9.9.9", "CANDIDATE": "v9.9.9"})
    assert done.returncode == 0, done.stderr
    assert "--tag" not in done.stdout and "--candidate" not in done.stdout, done.stdout


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
    asks = inspect.signature(carrier.preflight).parameters
    assert {"tag", "want_next", "candidate"} <= set(asks), (
        "ship asks the carrier for a patch, a candidate or a named tag; one of those questions is gone")

    real = carrier.Check(name="n", verdict=FAIL, line="l")
    stand_in = checks(("n", FAIL))[0]
    assert {"name", "verdict", "line"} <= set(vars(real))
    assert real.gates is stand_in.gates is True, "a refusal must gate in both"
    assert carrier.Check("n", UNKNOWN, "l").gates is checks(("n", UNKNOWN))[0].gates is False, (
        "`не перевірено` must gate in neither — it is not a refusal")


#: A fresh module name per load: `CARRIER` is computed at import, so a cached module would answer
#: for the tree it was first loaded from and every case after the first would prove nothing.
_LOADS = itertools.count()


def load_ship_from(path: Path):
    """Import a COPY of `ship.py` living somewhere else. Importing it runs nothing."""
    spec = importlib.util.spec_from_file_location(f"ship_under_test_{next(_LOADS)}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # `dataclasses` looks the module up by name to build `Plan`
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


def two_trees(base: Path, parent_name: str) -> tuple[Path, Path]:
    """`<parent_name>/{tcc,hub}` — the two sibling trees, as the machine really carries them.

    The carrier is a stand-in: this is about FINDING it, and `load_carrier` asks only whether the
    path is a file before it reads it.
    """
    tcc = base / parent_name / "tcc"
    (tcc / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "ship.py", tcc / "scripts" / "ship.py")
    carrier = base / parent_name / "hub" / "scripts" / "release-preflight.py"
    carrier.parent.mkdir(parents=True)
    carrier.write_text("# stand-in for the hub's release-preflight.py\n", encoding="utf-8")
    return tcc, carrier


#: Yesterday's name, today's name, and one nobody has used: none of them is written down in ship,
#: and the folder above the trees may be called anything at all.
PARENT_NAMES = ("autosound", "autosound-hub", "some-other-name")

#: Where ship is started from in practice: `make` stands in the root, a person stands in
#: `scripts/`, and `make -C` (or an absolute path) starts it from a folder unrelated to both.
LAUNCH_POINTS = ("root", "scripts", "elsewhere")


@pytest.mark.parametrize("parent_name", PARENT_NAMES)
@pytest.mark.parametrize("launched_from", LAUNCH_POINTS)
def test_the_carrier_is_found_from_the_file_not_from_cwd(tmp_path, monkeypatch, parent_name,
                                                         launched_from):
    """Same answer from every launch point, under any name of the folder above (HUB-005).

    The two forms this replaces both fail here. An absolute `$HOME` path points outside these
    trees entirely. A `cwd`-relative `../hub/...` fails two launch points of three — and passes
    the one from the repository root, which is exactly where a hand check would stand.
    """
    tcc, carrier = two_trees(tmp_path, parent_name)
    here = {"root": tcc, "scripts": tcc / "scripts", "elsewhere": tmp_path}[launched_from]
    monkeypatch.chdir(here)

    ship_elsewhere = load_ship_from(tcc / "scripts" / "ship.py")

    assert ship_elsewhere.CARRIER == carrier.resolve()
    assert ship_elsewhere.CARRIER.is_file()


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

    assert plan.commands == ["git tag -s v0.1.25 -m v0.1.25", "git push origin main",
                             "git push origin v0.1.25"]
    for command in plan.commands:
        assert "--tags" not in command and "--follow-tags" not in command

    source = (ROOT / "scripts" / "ship.py").read_text(encoding="utf-8")
    body = source.split('"""', 2)[2]  # past the module docstring, which quotes them on purpose
    code = [line.split("#", 1)[0] for line in body.splitlines()]
    pushes = [line for line in code if "push" in line and "--tags" in line]
    assert not pushes, f"a push that carries no tag name: {pushes}"
    assert "gh release" not in body, "releases belong to the `release` role, not to a make target"


def test_a_version_committed_on_the_wave_branch_is_tagged_without_a_new_commit(repo):
    """Hub WAVES.md, #148: the version and its CHANGELOG entry are committed on the wave branch, the
    pull request runs the full CI on that commit, and it lands on `main` by `--ff-only`. A release
    commit made by ship on top would be a commit CI never checked — so ship writes nothing and tags
    the commit it finds."""
    (repo / "pyproject.toml").write_text(PYPROJECT.format(version="0.1.25"), encoding="utf-8")
    _relock(repo)
    git(repo, "commit", "--quiet", "-am", "v0.1.25: version and notes, on the wave branch")
    git(repo, "push", "--quiet", "origin", "main")
    head = git(repo, "rev-parse", "HEAD")

    plan = _run(repo)

    assert plan.tag == "v0.1.25"
    assert git(repo, "rev-parse", "HEAD") == head, "no commit on top of what CI checked"
    assert git(repo, "rev-parse", "v0.1.25^{commit}") == head
    assert "refs/tags/v0.1.25" in git(repo, "ls-remote", "--tags", "--refs", "origin")
    assert git(repo, "status", "--porcelain") == ""


def test_a_red_suite_on_a_committed_version_leaves_no_tag(repo):
    """Nothing was written, so nothing is rolled back — but no tag either."""
    (repo / "pyproject.toml").write_text(PYPROJECT.format(version="0.1.25"), encoding="utf-8")
    _relock(repo)
    git(repo, "commit", "--quiet", "-am", "v0.1.25 on the wave branch")
    git(repo, "push", "--quiet", "origin", "main")

    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo, test_exit=1)

    assert "suite failed" in str(stop.value)
    assert git(repo, "tag", "--list", "v0.1.25") == ""


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


# --- fast in development, deterministic at a release (2026-09-09) --------------------------


def test_the_release_runs_the_suite_serially():
    """Everyday runs are parallel — `addopts` in `pyproject.toml` carries `-n auto --dist
    loadfile`, and that is what makes the suite ~65 s instead of ~500 s. A RELEASE is the one
    moment where reproducibility is worth more than eight minutes: one process, one order, the
    same shape the whole history of this suite was measured in.

    The break this catches is somebody speeding the release gate up later. `-n 0` is how xdist is
    switched off from the command line, and it has to be there explicitly, because `addopts`
    applies to every invocation including this one."""
    import scripts.ship as ship

    assert "-n" in ship.TEST_COMMAND
    assert ship.TEST_COMMAND[ship.TEST_COMMAND.index("-n") + 1] == "0"


def test_no_pytest_caller_carries_its_own_distribution_flags():
    """One source for how the suite is distributed, and it is `pyproject.toml`. The Makefile,
    `ship.py` and every CI job invoke pytest, and the moment one of them grows its own `-n`,
    "green locally" and "green in CI" stop meaning the same thing. That already cost two red CI
    runs on a green local suite (user, 2026-09-09), which is why this is a test and not a note.

    A CI shard is not a distribution flag and is deliberately not caught here: it hands pytest a
    LIST OF FILES worked out by `scripts/ci_shard.py`, and every one of them runs serially, in one
    process, exactly as it would locally.

    `ship.py` is the deliberate exception above and is excluded by name."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for relative in ("Makefile", ".github/workflows/ci.yml", ".github/workflows/method-newest.yml"):
        text = (root / relative).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "pytest" not in line or line.lstrip().startswith("#"):
                continue
            assert not re.search(r"(^|\s)-n(\s|=)", line), f"{relative}: {line.strip()}"
            assert "--dist" not in line, f"{relative}: {line.strip()}"


def test_ci_runs_on_every_push_so_the_release_gate_has_a_run_to_read():
    """HUB-057 made green CI on HEAD a condition of every tag, and the commit a release starts from
    is a CHANGELOG commit by construction — a path filter would leave it with no run (hub #136)."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    triggers = text.split("\non:\n", 1)[1].split("\njobs:\n", 1)[0]

    assert "paths-ignore" not in triggers and "paths:" not in triggers
    assert "NOT a release gate" not in text, "the header still says CI holds no tag back"


def test_each_commit_runs_ci_once_main_by_push_a_branch_by_its_pull_request():
    """A push to a PR branch started two identical runs, `push` and `pull_request` — three commits
    ran twice on 2026-09-13, twenty minutes of Windows each. Pushes run for `main` only: the release
    gate reads main's HEAD, so it still always has a run, and a branch is checked through its PR."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    triggers = text.split("\non:\n", 1)[1].split("\njobs:\n", 1)[0]

    push = re.search(r"^  push:\n    branches: \[([^\]]*)\]\n", triggers, re.M)
    assert push, f"push is not limited to named branches:\n{triggers}"
    assert [name.strip() for name in push.group(1).split(",")] == ["main"]
    assert re.search(r"^  pull_request:", triggers, re.M), "a branch would then run no CI at all"


def test_the_pull_request_is_sharded_and_the_push_to_main_runs_the_suite_WHOLE():
    """TCC-020 (hub #181). Which run a person waits for is the whole design: the pull request gets
    four shards per platform, about six minutes instead of twenty-one, and `main` gets the whole
    suite in one process — the shape that can still catch what fewer tests per process hide (the
    Linux abort HUB-049, the `#19` class of native Windows crash). The release gate reads the
    `main` run, and nobody waits for it.

    Asserted on the file rather than trusted to a reading of it, because the failure mode is
    silent both ways round: shards that also ran on `main` would double every wave's CI, and a
    `main` that only ran shards would retire the long-run jobs without anybody deciding to."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    jobs = text.split("\njobs:\n", 1)[1]
    blocks = dict(re.findall(r"^  ([a-z][a-z0-9-]*):\n((?:(?:    .*|\s*)\n)*)", jobs + "\n", re.M))

    shard = blocks.get("shard", "")
    assert "github.event_name == 'pull_request'" in shard, "the shards would run on main too"
    assert "ci_shard.py --splits 4 --group" in shard, "the split is the script's, not the YAML's"
    assert re.search(r"^        group: \[1, 2, 3, 4\]", shard, re.M), \
        "four groups asked for, four groups run — a mismatch silently drops a quarter of the suite"

    for job in ("linux-plan", "windows-plan"):
        assert "github.event_name != 'pull_request'" in blocks.get(job, ""), \
            f"{job} runs on the pull request as well, so the wave pays for the suite twice"

    assert "pr-green" not in blocks and "needs: pr-green" not in text, \
        "the skip-on-main question is gone: main is now the run that must not be skipped"


def test_every_platform_that_runs_the_suite_on_a_pull_request_is_sharded():
    """A platform left out of the matrix is a platform whose feedback is still twenty minutes, and
    the pull request waits for the slowest job it has."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    jobs = text.split("\njobs:\n", 1)[1]
    blocks = dict(re.findall(r"^  ([a-z][a-z0-9-]*):\n((?:(?:    .*|\s*)\n)*)", jobs + "\n", re.M))

    matrix = re.search(r"^        os: \[([^\]]*)\]", blocks.get("shard", ""), re.M)
    assert matrix, "the shard job has no platform matrix"

    assert {name.strip() for name in matrix.group(1).split(",")} == \
        {"ubuntu-latest", "windows-latest", "macos-latest"}
    assert "  macos:" not in text, "macOS runs as shards now; a second whole-suite job would be a copy"


# --- method-newest.yml: the suite against the method tag the app offers (#170, G5 S2) ------
#
# The update press can install a method newer than the pin (`updates.newest_tag()`), so a method
# release that breaks TCC breaks it on a user's machine before any TCC release says so. This
# workflow runs the suite against that tag every night. Read as text, like `ci.yml` above.

METHOD_NEWEST = ROOT / ".github" / "workflows" / "method-newest.yml"


def _workflow_code(text: str) -> list[str]:
    """The lines a runner reads: comments out, so a header explaining a rule cannot trip it."""
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def _workflow_jobs(text: str) -> dict[str, str]:
    """Each job's block by its id, cut the way the `ci.yml` tests above cut theirs."""
    jobs = text.split("\njobs:\n", 1)[1]
    return dict(re.findall(r"^  ([a-z][a-z0-9-]*):\n((?:(?:    .*|\s*)\n)*)", jobs + "\n", re.M))


def test_method_newest_runs_nightly_and_by_hand_and_never_on_a_push():
    """Ruling 2. The hub's release preflight counts every workflow run on `push` for the release
    sha, so a `push` trigger here would make the method's NEWEST tag a condition of TCC's own
    release, and a `pull_request` one would put a method TCC does not pin in front of every wave.

    The `on:` block is read as text: PyYAML would hand its key back as the boolean True."""
    text = METHOD_NEWEST.read_text(encoding="utf-8")
    on = re.search(r"^on:\n((?:(?:[ #].*)?\n)*)", text, re.M)
    assert on, "no block-form `on:` — a one-line trigger list would slip past this read"

    triggers = re.findall(r"^  ([a-z_]+):", on.group(1), re.M)
    assert sorted(triggers) == ["schedule", "workflow_dispatch"], triggers
    assert re.search(r"^    - cron: ", on.group(1), re.M), "a schedule with no cron never runs"


def test_method_newest_tests_the_tag_the_app_offers_and_names_it():
    """The tag is `updates.newest_tag()` — what the update press offers — asked ONCE, by a first
    job, and handed on: a second way of asking would be a second answer. GitHub evaluates
    `run-name` before any job runs, so the suite job's name carries the tag instead, and the run
    summary says it. A red run can be the method's (the suite runs its selftests too), and a red
    that does not say which method it ran is a red nobody can act on."""
    text = METHOD_NEWEST.read_text(encoding="utf-8")
    jobs = _workflow_jobs(text)
    pick, suite = jobs.get("pick", ""), jobs.get("suite", "")

    # Where the value comes from, not just the name: the refusal message quotes the call too.
    assert re.search(r"^ +tag=\$\(uv run ", pick, re.M), "the shell's tag is what Python printed"
    assert re.search(r"^ *tag = updates\.newest_tag\(\)$", pick, re.M), \
        "the tag must be the one the app offers"
    assert '"tag=$tag" >> "$GITHUB_OUTPUT"' in pick, "and that tag is the one handed on"
    assert re.search(r"^    outputs:\n      tag: \$\{\{ steps\.[a-z-]+\.outputs\.tag \}\}$",
                     pick, re.M), "the pick job's tag is a job output"
    assert re.search(r"^    needs: pick$", suite, re.M)
    assert re.search(r"^    name: .*\$\{\{ needs\.pick\.outputs\.tag \}\}", suite, re.M), \
        "the run title cannot carry the tag, so the job name must"
    assert "TAG: ${{ needs.pick.outputs.tag }}" in suite, "the tag reaches the shell through env"
    assert re.search(r'git .*checkout .*"\$TAG"', suite), "the submodule is moved to the tag"
    assert "GITHUB_STEP_SUMMARY" in suite, "the run summary names the tag"
    assert not re.search(r"\bv3\.\d", "\n".join(_workflow_code(text))), \
        "a tag written into the file is a second pin, not the newest"


def test_method_newest_moves_the_submodule_before_the_suite_runs():
    """M80: the checkout of the tag and the suite are two steps of one job, and their order is the
    point. Swapped, the suite runs the PINNED method under the newest tag's name — a green that
    says nothing about the tag. Read as the runner reads the job: comments out, top to bottom."""
    suite = _workflow_code(_workflow_jobs(METHOD_NEWEST.read_text(encoding="utf-8"))["suite"])
    moved = [at for at, line in enumerate(suite) if re.search(r'git .*checkout .*"\$TAG"', line)]
    ran = [at for at, line in enumerate(suite) if "python -m pytest tests/" in line]

    assert moved and ran, f"the move at {moved}, the suite at {ran}"
    assert max(moved) < min(ran), "the suite runs before the submodule is on the tag"


def test_method_newest_goes_red_for_real_on_the_locked_environment():
    """No `continue-on-error`: a nightly that cannot go red is one nobody reads, and the point is
    to see a breaking method release within a day. Every `uv run` is `--locked`: the suite runs
    what `uv.lock` records, not whatever resolves that night. One macOS job, the suite whole: the
    Linux whole-suite run aborts about half the time (HUB-049, `ci.yml`). The skill folder is
    absolute, because conftest moves HOME into `tmp_path`."""
    text = METHOD_NEWEST.read_text(encoding="utf-8")
    code = _workflow_code(text)

    assert not [line for line in code if "continue-on-error" in line]
    runs = [line.strip() for line in code if "uv run" in line]
    assert len(runs) >= 2, "the pick and the suite both run through uv"
    assert all("--locked" in line for line in runs), runs

    suite = _workflow_jobs(text).get("suite", "")
    assert re.search(r"^    runs-on: macos-", suite, re.M)
    assert re.search(r"^        with:\n          submodules: true$", suite, re.M)
    assert ("AUTOSOUND_SKILL_DIR: ${{ github.workspace }}"
            "/vendor/autosound-tuning-skill/skills/autosound-tuning") in suite
    assert re.search(r"uv run --locked --extra dev .*python -m pytest tests/ ", suite)


# --- the pin the repo RECORDS vs the method actually checked out ---------------------------


def test_a_release_refuses_when_the_checkout_is_not_the_recorded_pin():
    """SKL-028. `Paired with method <sha>` is checked against the WORKING checkout of the
    submodule — correctly, since that is what the release was built against. But git records a
    different thing: the gitlink committed in the parent repo. When those two disagree, the
    release pairs itself with a commit that is written down nowhere, and anyone cloning the tag
    gets a different method than the one that was tested.

    Bought this morning: the pin sat at `0cc96f6`, seven commits past `v3.0.46` and on no tag."""
    with pytest.raises(ship_mod.Stop) as stop:
        ship_mod.check_method_pin(pinned="a" * 40, checked_out="b" * 40)

    assert "a" * 12 in str(stop.value) and "b" * 12 in str(stop.value)


def test_a_release_is_fine_when_they_agree():
    ship_mod.check_method_pin(pinned="c" * 40, checked_out="c" * 40)


def test_a_pin_that_cannot_be_read_stops_the_release_rather_than_passing():
    """Silence here would be the worst answer: it reads as "they agree"."""
    for pinned, checked_out in (("", "d" * 40), ("d" * 40, "")):
        with pytest.raises(ship_mod.Stop):
            ship_mod.check_method_pin(pinned=pinned, checked_out=checked_out)


def test_the_recorded_pin_is_read_from_this_repository_for_real():
    """The stub in `_run` is a stand-in, and a stand-in nobody compares is how a green suite
    starts lying — this file says so in its own header. So the real reader runs here, against the
    real repository, where the submodule exists.

    It caught exactly what it was written for: `pinned_method_sha` used an `_SHA` pattern that was
    never defined in this module, so every real release would have died with a NameError while
    every test passed on the stub."""
    root = Path(__file__).resolve().parents[1]
    if not (root / "vendor" / "autosound-tuning-skill").exists():
        pytest.skip("submodule not checked out")

    pinned = ship_mod.pinned_method_sha(root)

    said = subprocess.run(
        ["git", "ls-tree", "HEAD", "vendor/autosound-tuning-skill"],
        cwd=str(root), capture_output=True, text=True,
    ).stdout.split()
    assert pinned == said[2]
    assert len(pinned) == 40


# --- the pin against what the method's remote has PUBLISHED --------------------------------
#
# TCC-021 (hub #182). In a shared wave the order is skill first: the method is fixed and tagged,
# tcc pins that published tag, is tested against it, and only then cuts its own tag (hub
# `governance/WAVES.md` §1 step 4). Two thirds of that were already mechanical — the gitlink must
# be committed (`check_method_pin`), and `check_paired_method` compares the CHANGELOG line with
# the method actually checked out. The third was not: nothing asked whether that commit carries a
# PUBLISHED tag, so a tcc release could ship pinned to an arbitrary commit of the method's `main`
# and the user would be updating to a method that has no version at all.


#: `git ls-remote --tags` as the method's remote really answers it, recorded 2026-09-19 — the
#: `v1.0.0` and `v3.0.58` lines verbatim, plus the two tags that are not versions. Annotated tags
#: come back TWICE: the tag object first, then its `^{}` peel, and only the peel is the commit.
LS_REMOTE_TAGS = (
    "798e176774d7c7641963982599f1e96f430c82ba\trefs/tags/archive/manual-step-by-step-full-history\n"
    "ca089e8de20ae39d542d6814570bb1709594baf2\trefs/tags/manual-v0.1.0\n"
    "d7590fc80bf06842e860d8716b8eb2e1338ffb2c\trefs/tags/manual-v0.1.0^{}\n"
    "4de6933e3eaa8ccc77a9275eca91b130fb00b321\trefs/tags/v1.0.0\n"
    "96883c70e5e84d15ea964bfd78932c82032e6ede\trefs/tags/v1.0.0^{}\n"
    "5e05729643d7f4278e87a934da8811e2c9f5f979\trefs/tags/v3.0.58\n"
    "66f6bdf05d900e6f6058efd8ee8e0040027251a8\trefs/tags/v3.0.58^{}\n"
)
PINNED_V3_0_58 = "66f6bdf05d900e6f6058efd8ee8e0040027251a8"


def test_a_release_refuses_a_method_pin_that_no_published_tag_points_at():
    """A pin on a bare commit of the method's `main` is a release nobody can name."""
    with pytest.raises(ship_mod.Stop) as stop:
        ship_mod.check_published_method("a" * 40, [])

    said = str(stop.value)
    assert "a" * 12 in said, "the refusal names the commit it is about"
    assert "tag the method first" in said, "and the step that is missing"


def test_a_release_is_fine_when_the_pin_carries_a_published_tag():
    """Measured 2026-09-19: the last six tcc tags all pin a tagged method commit — v0.1.41→v3.0.58,
    v0.1.40→v3.0.54, v0.1.39→v3.0.52, v0.1.38 and v0.1.37→v3.0.49, v0.1.36→v3.0.48. This check
    writes down what hands already do rather than changing how releases are cut."""
    ship_mod.check_published_method(PINNED_V3_0_58, ["v3.0.58"])


def test_the_published_tags_are_asked_of_the_REMOTE_and_annotated_tags_are_peeled(monkeypatch):
    """Two things at once, because both are ways this check would quietly pass nothing.

    THE REMOTE, not the local clone: the skill tree beside this one is routinely ahead of what a
    user can install, so `for-each-ref --points-at` would call a tag published that exists on one
    machine. THE PEEL: an annotated tag's first line is the tag object, not the commit, so
    matching the pin against column one without peeling finds nothing for every annotated tag in
    the method's history — which is all of them."""
    seen = {}

    def fake_run(argv, cwd, check=True):
        seen.update(argv=list(argv), cwd=cwd, check=check)
        return LS_REMOTE_TAGS

    monkeypatch.setattr(ship_mod, "run", fake_run)

    names = ship_mod.published_method_tags(ROOT, PINNED_V3_0_58)

    assert names == ["v3.0.58"], "the peel matched, and nothing else did"
    assert "ls-remote" in seen["argv"] and "--tags" in seen["argv"]
    assert Path(seen["argv"][2]).name == "autosound-tuning-skill", \
        "asked inside the submodule, so the URL is the method's own remote"


def test_a_pin_matching_no_line_comes_back_empty_rather_than_guessing(monkeypatch):
    monkeypatch.setattr(ship_mod, "run", lambda *_a, **_k: LS_REMOTE_TAGS)

    assert ship_mod.published_method_tags(ROOT, "b" * 40) == []


def test_a_remote_that_cannot_be_asked_stops_the_release_rather_than_passing(monkeypatch):
    """Unknown is a refusal, never "no objections" (hub `HUB-CONSTRAINTS.md` §1.4). A failed
    `ls-remote` returns the same empty string as a method with no tags at all, so the two must not
    be allowed to read the same: the call checks, and a non-zero exit is a Stop."""
    def fake_run(argv, cwd, check=True):
        assert check, "a failed ls-remote must raise rather than come back as 'no tags'"
        raise ship_mod.Stop("git ls-remote -> 128")

    monkeypatch.setattr(ship_mod, "run", fake_run)

    with pytest.raises(ship_mod.Stop):
        ship_mod.published_method_tags(ROOT, PINNED_V3_0_58)


def test_a_release_stops_before_writing_when_the_pinned_method_is_not_published(repo):
    """The whole point: it aborts with the bump, the commit and the tag all still unwritten."""
    before = git(repo, "rev-parse", "HEAD")

    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo, published=lambda _root, _sha: [])

    assert "tag the method first" in str(stop.value)
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "tag", "--list", "v0.1.25") == ""
    assert 'version = "0.1.24"' in (repo / "pyproject.toml").read_text(encoding="utf-8")


def test_a_release_asks_about_the_RECORDED_pin_and_names_the_tag_it_found(repo):
    """The gitlink is what a clone of the tag gets; the working checkout is only what this machine
    happens to have. They are equal by the time this runs (`check_method_pin`), so the question is
    which one the check is WRITTEN against — and the answer has to be the recorded one."""
    asked = []

    def published(root, sha):
        asked.append(sha)
        return ["v3.0.58"]

    plan = _run(repo, published=published)

    assert asked == [METHOD_SHA], "asked once, about the pin the repository records"
    assert plan.method_tags == ["v3.0.58"], "and the plan says which tag vouched for it"


def test_a_candidate_does_not_ask_the_remote_at_all(repo):
    """The path for a pin deliberately ahead of every tag — a diagnostic build — is the one that
    already exists rather than a new override flag to remember: a candidate skips
    `Paired with method` too, and this check stands beside it. A release is absolute (hub #182)."""
    _write_changelog(repo, UNRELEASED.format(sha=METHOD_SHA))
    asked = []

    _run(repo, ask=channel(tag="beta-v0.2.0-rc1"), candidate="v0.2.0",
         published=lambda _root, sha: asked.append(sha) or [])

    assert asked == [], "a candidate is the diagnostic build, and it answers to nobody's tag"


# --- signed tags (tcc#102, hub #83 HUB-032) ------------------------------------------------
#
# From v0.1.45 TCC's updater installs a release tag only when it verifies against the author's key,
# so an unsigned tag cut here would stop every update. Two halves, and neither is a copy of the
# other: BEFORE the tag the carrier asks whether git would sign with the key in `allowed_signers`
# (`tag-will-be-signed`, hub #84 HUB-033); AFTER it ship verifies the tag it actually made.


def verify_tag(repo: Path, tag: str) -> tuple[int, str]:
    """`git verify-tag` against the tree's own `allowed_signers`, the way a person checks one."""
    done = subprocess.run(
        ["git", "-c", f"gpg.ssh.allowedSignersFile={repo / 'allowed_signers'}", "verify-tag", tag],
        cwd=str(repo), capture_output=True, text=True)
    return done.returncode, done.stderr + done.stdout


def test_the_release_tag_is_signed_and_verifies_against_allowed_signers(repo):
    lines = []
    _run(repo, say=lines.append)

    assert git(repo, "cat-file", "-t", "v0.1.25") == "tag", "a signed tag is an annotated one"
    rc, said = verify_tag(repo, "v0.1.25")
    assert rc == 0 and 'Good "git" signature for author' in said, said
    assert "refs/tags/v0.1.25^{}" in git(repo, "ls-remote", "--tags", "origin"), \
        "the tag object itself was pushed, not a lightweight name"
    assert any('Good "git" signature' in line for line in lines), \
        f"ship's own check of the tag went unsaid: {lines}"


def test_a_tag_that_does_not_verify_is_deleted_and_nothing_is_pushed(repo, signing_keys):
    """Git signed, but with a key `allowed_signers` does not list — the carrier's check before the
    tag would refuse this, so what is under test is the belt after it: ship verifies the tag it
    made, and a tag no updater would install never leaves the machine."""
    sign_with(repo, signing_keys["stranger"])
    main_before = git(repo, "rev-parse", "origin/main")

    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo)

    said = str(stop.value)
    assert "does not verify" in said and "allowed_signers" in said, said
    assert "nothing was pushed" in said, said
    assert git(repo, "tag", "--list", "v0.1.25") == "", "the tag that does not verify is gone"
    assert "v0.1.25" not in git(repo, "ls-remote", "origin")
    assert git(repo, "ls-remote", "origin", "refs/heads/main").split()[0] == main_before


def assert_names_the_local_release_commit(repo: Path, said: str) -> None:
    """A failure past the release commit (the bump path) leaves that commit on local `main`,
    unpushed, and the carrier's `head-published` refuses the next run — so the Stop names the
    commit and both ways on (review of tcc#102, round 1)."""
    head = git(repo, "rev-parse", "HEAD")
    assert head != git(repo, "rev-parse", "origin/main"), "the state the sentence describes"
    assert head[:12] in said and "0.1.25" in said, said
    assert "git push origin main" in said and "git reset --hard origin/main" in said, said


def test_a_tag_git_cannot_sign_names_the_release_commit_left_behind(repo, signing_keys):
    """`git tag -s` itself fails — here no signing key at all, on the release machine a key with
    a passphrase and no agent (git: "unable to sign the tag"). The commit is already made. Then
    the first way on, taken: push it, and ship tags that commit without bumping again."""
    git(repo, "config", "--unset", "user.signingkey")

    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo)

    assert_names_the_local_release_commit(repo, str(stop.value))
    assert git(repo, "tag", "--list", "v0.1.25") == ""
    head = git(repo, "rev-parse", "HEAD")

    sign_with(repo, signing_keys["author"])
    git(repo, "push", "--quiet", "origin", "main")
    _run(repo)

    assert git(repo, "rev-parse", "HEAD") == head, "no second release commit"
    assert git(repo, "rev-parse", "v0.1.25^{commit}") == head


def test_a_tag_that_does_not_verify_names_the_release_commit_left_behind(repo, signing_keys):
    """The other shape: signed, but by a key `allowed_signers` does not list. Then the second
    way on, taken: reset to what is published, and ship does the bump again."""
    sign_with(repo, signing_keys["stranger"])

    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo)

    assert_names_the_local_release_commit(repo, str(stop.value))

    git(repo, "reset", "--quiet", "--hard", "origin/main")
    sign_with(repo, signing_keys["author"])
    _run(repo)

    assert git(repo, "rev-parse", "v0.1.25^{commit}") == git(repo, "rev-parse", "origin/main")
    assert git(repo, "log", "--format=%s", "-1", "v0.1.25").startswith("v0.1.25: paired")


def test_a_tree_without_allowed_signers_is_named_not_blamed_on_the_signing_key(repo):
    """With no `allowed_signers` git's answer is the same "No principal matched" as a stranger's
    key, and the old hint sent the reader to `user.signingkey`, which was right."""
    git(repo, "rm", "--quiet", "allowed_signers")
    git(repo, "commit", "--quiet", "-m", "no signers")
    git(repo, "push", "--quiet", "origin", "main")

    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo)

    said = str(stop.value)
    assert "no allowed_signers" in said, said
    assert "signingkey" not in said, "the key was never the problem"
    assert git(repo, "tag", "--list", "v0.1.25") == ""


def test_a_tag_that_could_not_be_deleted_says_so_and_names_the_command(repo, signing_keys,
                                                                       monkeypatch):
    """The Stop used to say "the tag was deleted again" whatever `git tag -d` answered."""
    sign_with(repo, signing_keys["stranger"])
    real_run = ship_mod.run

    def run(argv, cwd, check=True):
        if argv[:3] == ["git", "tag", "-d"]:
            if check:
                raise ship_mod.Stop("git tag -d v0.1.25 -> 1\nerror: could not lock the ref")
            return ""
        return real_run(argv, cwd, check)

    monkeypatch.setattr(ship_mod, "run", run)

    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo)

    said = str(stop.value)
    assert "was deleted again" not in said, said
    assert "could NOT be deleted" in said and "`git tag -d v0.1.25`" in said, said
    assert "could not lock the ref" in said, "git's own reason"
    assert "v0.1.25" not in git(repo, "ls-remote", "origin"), "and still nothing was pushed"


def test_the_carriers_signing_refusal_stops_ship_before_anything_is_written(repo):
    """`tag-will-be-signed` (hub #84 HUB-033) is the refusal before the tag; ship prints it by
    that name and stops on it like any other channel check."""
    lines = []
    with pytest.raises(ship_mod.Stop) as stop:
        _run(repo, say=lines.append,
             ask=channel(answers=(("clean-tree", OK), ("tag-will-be-signed", FAIL))))

    assert "tag-will-be-signed" in str(stop.value)
    assert any("tag-will-be-signed" in line and FAIL in line for line in lines), lines
    assert 'version = "0.1.24"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert git(repo, "tag", "--list", "v0.1.25") == ""


def test_ship_shows_the_tag_line_it_runs():
    """The line in the plan is built from the same argv `publish` runs, so the two cannot drift."""
    assert " ".join(ship_mod.tag_command("v0.1.25")) == "git tag -s v0.1.25 -m v0.1.25"


def test_the_carrier_refuses_a_tag_git_would_not_sign_and_names_the_fix(tmp_path, monkeypatch,
                                                                        signing_keys):
    """The refusal BEFORE the tag is the carrier's `tag-will-be-signed` (hub #84 HUB-033), which
    ship prints and stops on like every other channel check — not a second copy of it here, the
    rule this file's header keeps since HUB-003. So it is asked of the real carrier, on a
    throwaway tree carrying an `allowed_signers` like this repository's.

    Skipped, loudly, when the hub is not here — and then ship refuses anyway: no carrier, no
    release."""
    if not ship_mod.CARRIER.is_file():
        pytest.skip(f"the hub's carrier is not on this machine ({ship_mod.CARRIER})")
    carrier = ship_mod.load_carrier()
    assert "check_signing(" in inspect.getsource(carrier.preflight), \
        "the preflight no longer asks whether the tag will be signed"

    no_machine_git(monkeypatch)
    tree = tmp_path / "tree"
    subprocess.run(["git", "init", "--quiet", str(tree)], check=True)
    (tree / "allowed_signers").write_text(
        f'author namespaces="git" {public_key(signing_keys["author"])}\n', encoding="utf-8")
    tcc = carrier.ROLE_REPO["tcc"]

    unset = carrier.check_signing(tree, tcc)
    assert unset.gates, unset
    assert "git config --global gpg.format ssh" in unset.line, unset.line
    assert "git config --global user.signingkey ~/.ssh/id_ed25519.pub" in unset.line, unset.line

    sign_with(tree, signing_keys["stranger"])
    assert carrier.check_signing(tree, tcc).gates, "another key is refused too"

    sign_with(tree, signing_keys["author"])
    assert not carrier.check_signing(tree, tcc).gates, "the key in allowed_signers passes"
