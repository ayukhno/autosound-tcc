"""The signature of what is INSTALLED, said beside each version (#195, finding 159).

The Arbiter updated the method and TCC through TCC on Windows and nowhere saw that the tag's
signature was checked. The update checks it (`prepare_tcc_update`, `_extract_upkeep`); this is the
mark for the version that is here now, checked by TCC itself with the same anchors — or why not.
Never «checked» for something that was not: a release before signing, the developer's switch, a
source checkout, a machine that cannot look, each says so.

Throwaway keys and `file://` origins only: nothing here asks GitHub.
"""

from __future__ import annotations

import os
import shutil

import pytest

from autosound_tcc.core import install_report, updates
from tests.test_updates import _git_in, _git_in_keygen, _tcc_origin

_NEEDS_KEYGEN = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="needs ssh-keygen")


@pytest.fixture(autouse=True)
def _no_seal_remembered(monkeypatch):
    """What an earlier test learned about a TCC tag is not this test's answer."""
    monkeypatch.setattr(updates, "_TCC_SEALS", {})


def _tcc_installed(monkeypatch, tag: str, commit: str) -> None:
    monkeypatch.setattr(install_report, "install_source",
                        lambda: ("https://github.com/ayukhno/autosound-tcc", commit))
    monkeypatch.setattr(install_report, "requested_revision", lambda: tag)


# ---- TCC: the tag the running TCC was installed from ------------------------------------------

def test_a_source_checkout_has_no_tag_to_check_and_asks_git_nothing(monkeypatch):
    monkeypatch.setattr(install_report, "install_source", lambda: ("", ""))
    monkeypatch.setattr(updates, "_git", lambda *a, **k: pytest.fail(f"git asked: {a}"))

    seal = updates.tcc_seal()

    assert (seal.state, seal.reason) == ("unknown", "source_checkout")


def test_tcc_installed_from_no_release_tag_is_unknown_not_checked(monkeypatch):
    """uv installed it from a branch (the ref-less command): nothing signed names that build."""
    _tcc_installed(monkeypatch, "", "a" * 40)
    monkeypatch.setattr(updates, "_git", lambda *a, **k: pytest.fail(f"git asked: {a}"))

    seal = updates.tcc_seal()

    assert (seal.state, seal.reason) == ("unknown", "no_tag")


@_NEEDS_KEYGEN
def test_tcc_s_installed_tag_signed_by_the_author_and_naming_this_commit_is_good(monkeypatch,
                                                                                  tmp_path):
    temp = _tcc_origin(monkeypatch, tmp_path)
    commit = _git_in("rev-parse", "v0.1.45^{commit}", cwd=tmp_path / "tcc-origin")
    _tcc_installed(monkeypatch, "v0.1.45", commit)

    seal = updates.tcc_seal()

    assert (seal.state, seal.tag, seal.principal) == ("good", "v0.1.45", "author"), seal
    assert list(temp.iterdir()) == [], "the bare repository and the signers file are gone"


@_NEEDS_KEYGEN
def test_a_signed_tag_that_names_another_commit_than_the_installed_one_is_not_good(monkeypatch,
                                                                                   tmp_path):
    """The signature covers the commit the tag names; a build of another commit is not covered."""
    _tcc_origin(monkeypatch, tmp_path)
    _tcc_installed(monkeypatch, "v0.1.45", "d" * 40)

    seal = updates.tcc_seal()

    assert (seal.state, seal.reason) == ("bad", "commit_differs"), seal
    assert "d" * 12 in seal.detail


@_NEEDS_KEYGEN
@pytest.mark.parametrize("tag", ["v0.1.46", "v0.1.47", "v0.1.48"])
def test_tcc_s_installed_tag_unsigned_or_by_a_stranger_is_bad(monkeypatch, tmp_path, tag):
    _tcc_origin(monkeypatch, tmp_path)
    commit = _git_in("rev-parse", f"{tag}^{{commit}}", cwd=tmp_path / "tcc-origin")
    _tcc_installed(monkeypatch, tag, commit)

    seal = updates.tcc_seal()

    assert (seal.state, seal.reason) == ("bad", "bad_signature"), seal
    assert seal.detail.startswith(f"{tag}: "), "git's own words, naming the tag"


@_NEEDS_KEYGEN
def test_tcc_installed_from_a_tag_before_signing_says_so_and_not_checked(monkeypatch, tmp_path):
    _tcc_origin(monkeypatch, tmp_path)
    _tcc_installed(monkeypatch, "v0.1.44", "a" * 40)
    monkeypatch.setattr(updates, "_git", lambda *a, **k: pytest.fail(f"git asked: {a}"))

    seal = updates.tcc_seal()

    assert (seal.state, seal.tag) == ("predates", "v0.1.44"), seal


@_NEEDS_KEYGEN
def test_the_developer_switch_is_said_as_not_checked(monkeypatch, tmp_path):
    _tcc_origin(monkeypatch, tmp_path)
    _tcc_installed(monkeypatch, "v0.1.45", "a" * 40)
    monkeypatch.setenv(updates.SKIP_VERIFY_VAR, "1")

    seal = updates.tcc_seal()

    assert (seal.state, seal.detail) == ("skipped", updates.SKIP_VERIFY_VAR), seal


def test_a_tag_that_could_not_be_fetched_is_unknown_and_asked_again(monkeypatch):
    """No network is not a verdict on the release, and it is not remembered either."""
    _tcc_installed(monkeypatch, "v1.1.3", "a" * 40)
    asked = []
    monkeypatch.setattr(updates, "check_tcc_tag", lambda tag: asked.append(tag) or (
        False, "fatal: unable to access", "fetch_failed", "", None))

    first, second = updates.tcc_seal(), updates.tcc_seal()

    assert (first.state, first.reason) == ("unknown", "fetch_failed"), first
    assert "unable to access" in first.detail
    assert asked == ["v1.1.3", "v1.1.3"] and second == first


@pytest.mark.parametrize("why", ["git_too_old", "openssh_too_old", "not_checked",
                                 "commit_not_checked"])
def test_a_machine_that_cannot_check_is_unknown_not_bad(monkeypatch, why):
    _tcc_installed(monkeypatch, "v1.1.3", "a" * 40)
    monkeypatch.setattr(updates, "check_tcc_tag",
                        lambda tag: (False, "git version 2.30: no", why, "", None))

    seal = updates.tcc_seal()

    assert (seal.state, seal.reason) == ("unknown", why), seal


def test_a_good_answer_is_remembered_for_the_build_it_was_about(monkeypatch):
    """A fetch per Re-check is the network's price for an answer that cannot change while this
    process runs: the installed commit and the signed tag are both fixed."""
    _tcc_installed(monkeypatch, "v1.1.3", "c" * 40)
    asked = []
    monkeypatch.setattr(updates, "check_tcc_tag", lambda tag: asked.append(tag) or (
        True, "v1.1.3: signature good (ayukhno)", "", "c" * 40, None))

    first, second = updates.tcc_seal(), updates.tcc_seal()

    assert first.state == "good" and second == first
    assert asked == ["v1.1.3"]


# ---- the method: the release tag its clone is at ----------------------------------------------

def _method_clone(monkeypatch, tmp_path, tag: str, who: str = "author", *, signed: bool = True):
    """An origin with `tag` (signed by `who`, or annotated unsigned), the installed clone shallow
    at it, the skill's anchor pointed at a throwaway `author` key."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)
    keys = {}
    for name in ("author", "stranger"):
        _git_in_keygen(tmp_path / name, name)
        keys[name] = " ".join((tmp_path / f"{name}.pub").read_text().split()[:2])
    origin = tmp_path / "origin"
    _git_in("init", "-q", "-b", "main", str(origin))
    (origin / "a.txt").write_text("one\n")
    _git_in("add", "-A", cwd=origin)
    _git_in("commit", "-q", "-m", "a release", cwd=origin)
    if signed:
        _git_in("-c", "gpg.format=ssh", "-c", f"user.signingkey={tmp_path / who}.pub",
                "tag", "-s", tag, "-m", tag, cwd=origin)
    else:
        _git_in("tag", "-a", tag, "-m", "unsigned", cwd=origin)
    clone = tmp_path / "clone"
    _git_in("-c", "advice.detachedHead=false", "clone", "-q", "--branch", tag, "--depth", "1",
            f"file://{origin}", str(clone))
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: clone)
    monkeypatch.setattr(install_report, "skill_version", lambda: tag.lstrip("v"))
    monkeypatch.setattr(updates, "SKILL_SIGNING_PRINCIPAL", "author")
    monkeypatch.setattr(updates, "SKILL_SIGNING_KEY", keys["author"])
    return clone


@_NEEDS_KEYGEN
def test_the_method_at_a_tag_signed_by_its_author_is_good(monkeypatch, tmp_path):
    _method_clone(monkeypatch, tmp_path, "v3.1.3")

    seal = updates.skill_seal()

    assert (seal.state, seal.tag, seal.principal, seal.changed) == (
        "good", "v3.1.3", "author", False), seal


@_NEEDS_KEYGEN
def test_local_changes_in_the_method_s_clone_are_said_beside_a_good_signature(monkeypatch,
                                                                             tmp_path):
    """The signature covers the commit; a session's patch in the clone is not part of it."""
    clone = _method_clone(monkeypatch, tmp_path, "v3.1.3")
    (clone / "a.txt").write_text("one\na session's patch\n")

    seal = updates.skill_seal()

    assert (seal.state, seal.changed) == ("good", True), seal


@_NEEDS_KEYGEN
@pytest.mark.parametrize("who, signed", [("stranger", True), ("author", False)])
def test_the_method_at_a_tag_unsigned_or_by_a_stranger_is_bad(monkeypatch, tmp_path, who, signed):
    _method_clone(monkeypatch, tmp_path, "v3.1.3", who, signed=signed)

    seal = updates.skill_seal()

    assert (seal.state, seal.reason) == ("bad", "bad_signature"), seal
    assert seal.detail.startswith("v3.1.3: ")


@_NEEDS_KEYGEN
def test_the_method_at_a_release_before_signing_says_so(monkeypatch, tmp_path):
    _method_clone(monkeypatch, tmp_path, "v3.0.9", signed=False)

    seal = updates.skill_seal()

    assert (seal.state, seal.tag) == ("predates", "v3.0.9"), seal


@_NEEDS_KEYGEN
def test_a_method_clone_that_keeps_no_tag_for_its_commit_is_unknown(monkeypatch, tmp_path):
    """Clones parked before skill #92 kept no `refs/tags`: nothing local names the commit."""
    clone = _method_clone(monkeypatch, tmp_path, "v3.1.3")
    _git_in("tag", "-d", "v3.1.3", cwd=clone)

    seal = updates.skill_seal()

    assert (seal.state, seal.reason) == ("unknown", "clone_no_tag"), seal


def test_no_method_folder_is_unknown(monkeypatch):
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: None)

    seal = updates.skill_seal()

    assert (seal.state, seal.reason) == ("unknown", "not_found")


# ---- the update window: one line about the check, only when it checked ------------------------

@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_the_update_window_says_the_signature_was_checked_before_it_installs(platform):
    script = updates.tcc_install_script(4242, "v1.1.4", platform=platform, sha="c" * 40)

    signed = updates.TCC_WINDOW_WORDS["signed"].replace("{tag}", "v1.1.4").replace(
        "{principal}", updates.TCC_SIGNING_PRINCIPAL)
    assert signed in script, script
    assert script.index(signed) < script.index("uv tool install"), "before it installs"
    assert script.index("c" * 40) < script.index(signed), (
        "after the tag was found still naming the checked commit")


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_an_update_whose_tag_was_not_verified_has_no_such_line(platform):
    """No `sha`: a release before signing, the developer's switch — nothing was checked."""
    script = updates.tcc_install_script(4242, "v0.1.44", platform=platform)

    assert "signature" not in script.lower(), script


def test_the_window_s_line_comes_in_the_words_given(monkeypatch):
    words = {"signed": "Підпис {tag} перевірено: сходиться ({principal})."}

    script = updates.tcc_install_script(4242, "v1.1.4", platform="darwin", sha="c" * 40,
                                        words=words)

    assert f"Підпис v1.1.4 перевірено: сходиться ({updates.TCC_SIGNING_PRINCIPAL})." in script
