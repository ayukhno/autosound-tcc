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
def _no_seal_remembered(monkeypatch, tmp_path):
    """What an earlier test learned about a TCC tag is not this test's answer — in memory or on
    disk."""
    monkeypatch.setattr(updates, "_TCC_SEALS", {})
    monkeypatch.setattr(updates, "_seal_store", lambda: tmp_path / "machine" / "signatures.json")


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
    monkeypatch.setattr(updates, "check_tcc_tag", lambda tag, **kw: asked.append(tag) or (
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
                        lambda tag, **kw: (False, "git version 2.30: no", why, "", None))

    seal = updates.tcc_seal()

    assert (seal.state, seal.reason) == ("unknown", why), seal


def test_a_good_answer_is_remembered_for_the_build_it_was_about(monkeypatch):
    """A fetch per Re-check is the network's price for an answer that cannot change while this
    process runs: the installed commit and the signed tag are both fixed."""
    _tcc_installed(monkeypatch, "v1.1.3", "c" * 40)
    asked = []
    monkeypatch.setattr(updates, "check_tcc_tag", lambda tag, **kw: asked.append(tag) or (
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


# ---- fix round: the cost of the check, the tag's own name, what git could not say -------------

def _answers(asked, sha):
    return lambda tag, **kw: asked.append((tag, kw.get("light"))) or (
        True, f"{tag}: signature good (ayukhno)", "", sha, None)


def test_a_good_answer_for_one_build_is_never_the_answer_for_another(monkeypatch):
    """Same tag, another installed commit: asked again, and not good — the tag names A."""
    asked = []
    monkeypatch.setattr(updates, "check_tcc_tag", _answers(asked, "a" * 40))
    _tcc_installed(monkeypatch, "v1.1.3", "a" * 40)
    assert updates.tcc_seal().state == "good"

    _tcc_installed(monkeypatch, "v1.1.3", "b" * 40)
    other = updates.tcc_seal()
    updates._TCC_SEALS.clear()  # a new process: only the disk remembers
    again = updates.tcc_seal()

    assert (other.state, other.reason) == ("bad", "commit_differs"), other
    assert again == other
    assert len(asked) == 3, "only «good» is kept: a «bad» is asked again"


def test_a_verdict_is_kept_on_disk_so_the_next_start_fetches_nothing(monkeypatch):
    asked = []
    monkeypatch.setattr(updates, "check_tcc_tag", _answers(asked, "a" * 40))
    _tcc_installed(monkeypatch, "v1.1.3", "a" * 40)
    first = updates.tcc_seal()

    updates._TCC_SEALS.clear()  # the next start of TCC
    second = updates.tcc_seal()

    assert first.state == "good" and second == first
    assert asked == [("v1.1.3", True)], "one fetch, a light one"
    assert updates._seal_store().is_file()


def test_a_failed_fetch_is_not_kept_on_disk(monkeypatch):
    asked = []
    monkeypatch.setattr(updates, "check_tcc_tag", lambda tag, **kw: asked.append(tag) or (
        False, "fatal: unable to access", "fetch_failed", "", None))
    _tcc_installed(monkeypatch, "v1.1.3", "a" * 40)
    updates.tcc_seal()
    updates._TCC_SEALS.clear()

    assert updates.tcc_seal().reason == "fetch_failed"
    assert asked == ["v1.1.3", "v1.1.3"]


def test_a_store_that_cannot_be_read_is_only_a_fetch_more(monkeypatch):
    store = updates._seal_store()
    store.parent.mkdir(parents=True)
    store.write_text("{ cut off", encoding="utf-8")
    asked = []
    monkeypatch.setattr(updates, "check_tcc_tag", _answers(asked, "a" * 40))
    _tcc_installed(monkeypatch, "v1.1.3", "a" * 40)

    assert updates.tcc_seal().state == "good" and len(asked) == 1


def test_two_windows_asking_at_once_share_one_check(monkeypatch):
    import threading

    release, asked = threading.Event(), []

    def slow(tag, **kw):
        asked.append(tag)
        release.wait(5)
        return True, f"{tag}: signature good (ayukhno)", "", "a" * 40, None

    monkeypatch.setattr(updates, "check_tcc_tag", slow)
    _tcc_installed(monkeypatch, "v1.1.3", "a" * 40)
    got = []
    threads = [threading.Thread(target=lambda: got.append(updates.tcc_seal())) for _ in range(2)]
    for thread in threads:
        thread.start()
    for _ in range(100):
        if asked:
            break
        threading.Event().wait(0.02)
    release.set()
    for thread in threads:
        thread.join(timeout=5)

    assert asked == ["v1.1.3"] and len(got) == 2 and got[0] == got[1] and got[0].state == "good"


@_NEEDS_KEYGEN
def test_the_seal_fetches_the_tag_without_its_tree(monkeypatch, tmp_path):
    """Verifying needs the tag object and the commit it names, not ~13 MB of files: `tree:0`.
    The origin here allows filters, as GitHub does."""
    _tcc_origin(monkeypatch, tmp_path)
    origin = tmp_path / "tcc-origin"
    _git_in("config", "uploadpack.allowFilter", "true", cwd=origin)
    commit = _git_in("rev-parse", "v0.1.45^{commit}", cwd=origin)
    _tcc_installed(monkeypatch, "v0.1.45", commit)
    kinds = []
    real = updates._verify_tag

    def look(repo, tag, **kw):
        listed = _git_in("cat-file", "--batch-all-objects", "--batch-check", cwd=repo)
        kinds.extend(line.split()[1] for line in listed.splitlines())
        return real(repo, tag, **kw)

    monkeypatch.setattr(updates, "_verify_tag", look)

    seal = updates.tcc_seal()

    assert seal.state == "good", seal
    assert "blob" not in kinds and "tree" not in kinds and "tag" in kinds, kinds


def test_a_git_that_refuses_the_light_fetch_gets_the_whole_tag(monkeypatch, tmp_path):
    fetches = []

    def fake(*args, cwd=None, timeout=None, base_env=None):
        if "fetch" in args:
            fetches.append(args)
            return ("--filter=tree:0" not in args), "error: unknown option `filter=tree:0'"
        if "rev-parse" in args:
            return True, "a" * 40
        if "for-each-ref" in args:
            return True, "v1.1.3"
        return True, 'Good "git" signature for ayukhno with ED25519 key SHA256:x'

    monkeypatch.setattr(updates, "_git", fake)
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)

    ok, _line, _why, sha, pins = updates.check_tcc_tag("v1.1.3", light=True)

    assert ok and sha == "a" * 40 and pins is None
    assert ["--filter=tree:0" in args for args in fetches] == [True, False]


@_NEEDS_KEYGEN
def test_an_old_signed_tag_served_under_a_new_name_is_not_good(monkeypatch, tmp_path):
    """The signature covers the tag object, and the object names its tag: v0.1.45's signed
    object under `refs/tags/v0.1.49` is still v0.1.45 — not a signed v0.1.49."""
    _tcc_origin(monkeypatch, tmp_path)
    origin = tmp_path / "tcc-origin"
    signed = _git_in("rev-parse", "refs/tags/v0.1.45", cwd=origin)
    _git_in("update-ref", "refs/tags/v0.1.49", signed, cwd=origin)

    ok, line, why, sha, _pins = updates.check_tcc_tag("v0.1.49")

    assert (ok, why, sha) == (False, "bad_signature", ""), line
    assert "v0.1.45" in line


@_NEEDS_KEYGEN
def test_a_method_clone_whose_head_moved_off_its_tag_is_not_called_good(monkeypatch, tmp_path):
    """The tag is still in the clone, but HEAD is a commit no signed tag names."""
    clone = _method_clone(monkeypatch, tmp_path, "v3.1.3")
    (clone / "a.txt").write_text("moved on\n")
    _git_in("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "on top", cwd=clone)

    seal = updates.skill_seal()

    assert (seal.state, seal.reason) == ("unknown", "clone_no_tag"), seal


@_NEEDS_KEYGEN
def test_local_changes_that_could_not_be_read_are_unknown_not_none(monkeypatch, tmp_path):
    _method_clone(monkeypatch, tmp_path, "v3.1.3")
    real, asked = updates._git, []

    def status_fails(*args, **kw):
        if "status" in args:
            asked.append(args)
            return False, updates._DidNotRun("TimeoutExpired: git status")
        return real(*args, **kw)

    monkeypatch.setattr(updates, "_git", status_fails)

    seal = updates.skill_seal()

    assert (seal.state, seal.changed) == ("good", None), seal
    assert asked and asked[0][0] == "--no-optional-locks", "the seal never holds index.lock"


# ---- the update window: what uv installed is the commit that was checked ----------------------

def _tool_python(tmp_path, commit: str):
    """A `uv` whose `tool dir` holds an autosound-tcc whose python says it was installed at
    `commit`; every other call records itself and succeeds."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    tools = tmp_path / "tools"
    (tools / "autosound-tcc" / "bin").mkdir(parents=True)
    python = tools / "autosound-tcc" / "bin" / "python"
    python.write_text(f"#!/bin/sh\necho {commit}\n")
    python.chmod(0o755)
    (bindir / "uv").write_text(f'#!/bin/sh\nif [ "$1 $2" = "tool dir" ]; then echo \'{tools}\'; '
                               "exit 0; fi\nexit 0\n")
    (bindir / "uv").chmod(0o755)
    (bindir / "git").write_text(f"#!/bin/sh\nprintf '%s\\trefs/tags/v1.1.4^{{}}\\n' {'c' * 40}\n")
    (bindir / "git").chmod(0o755)
    return bindir


def _gone_pid() -> int:
    import subprocess

    gone = subprocess.Popen(["true"])
    gone.wait()
    return gone.pid


@pytest.mark.skipif(os.name == "nt", reason="runs the macOS script with sh")
@pytest.mark.parametrize("installed", ["c" * 40, "e" * 40])
def test_the_window_says_when_uv_installed_another_commit_than_the_checked_one(tmp_path,
                                                                               installed):
    import subprocess

    bindir = _tool_python(tmp_path, installed)
    folder = tmp_path / "update"
    folder.mkdir()
    path = updates.write_tcc_install_script(pid=_gone_pid(), tag="v1.1.4", folder=folder,
                                            platform="darwin", sha="c" * 40)

    out = subprocess.run(["/bin/sh", str(path)], capture_output=True, text=True,
                         env={**os.environ, "PATH": f"{bindir}:/usr/bin:/bin"}, timeout=30).stdout

    words = updates.TCC_WINDOW_WORDS
    if installed == "c" * 40:
        assert out.rstrip().endswith(words["done"]) and words["differs"] not in out, out
    else:
        assert words["differs"] in out and words["done"] not in out, out
        assert out.rstrip().endswith("e" * 40), out


def test_the_windows_window_reads_what_uv_installed_too():
    script = updates.tcc_install_script(4242, "v1.1.4", platform="win32", sha="c" * 40,
                                        folder=None, check_installed=True)

    assert "uv tool dir" in script and "tcc-installed.py" in script
    assert script.index("if errorlevel 1 goto failed") < script.index("tcc-installed.py")
    assert updates.TCC_WINDOW_WORDS["differs"] in script


# ---- the last round: the shared job always ends, only «good» is kept, a network failure is one -

def test_a_store_that_raises_still_releases_the_shared_check(monkeypatch):
    import threading

    asked = []
    monkeypatch.setattr(updates, "check_tcc_tag", _answers(asked, "a" * 40))
    monkeypatch.setattr(updates, "_seal_store", lambda: (_ for _ in ()).throw(RuntimeError("no home")))
    _tcc_installed(monkeypatch, "v1.1.3", "a" * 40)

    first = updates.tcc_seal()
    got = []
    later = threading.Thread(target=lambda: got.append(updates.tcc_seal()))
    later.start()
    later.join(timeout=5)

    assert first.state == "good" and not later.is_alive() and got, "nobody waits forever"
    assert updates._SEAL_FLIGHTS == {}


def test_a_bad_answer_is_not_kept_across_a_restart(monkeypatch):
    asked = []
    monkeypatch.setattr(updates, "check_tcc_tag", lambda tag, **kw: asked.append(tag) or (
        False, f"{tag}: No principal matched.", "bad_signature", "", None))
    _tcc_installed(monkeypatch, "v1.1.3", "a" * 40)

    assert updates.tcc_seal().state == "bad"
    updates._TCC_SEALS.clear()
    assert updates.tcc_seal().state == "bad"

    assert asked == ["v1.1.3", "v1.1.3"]
    assert not updates._seal_store().exists()


def test_a_store_that_cannot_be_replaced_leaves_no_temporary_file(monkeypatch):
    asked = []
    monkeypatch.setattr(updates, "check_tcc_tag", _answers(asked, "a" * 40))
    monkeypatch.setattr(updates.os, "replace",
                        lambda *a: (_ for _ in ()).throw(PermissionError("held by a reader")))
    _tcc_installed(monkeypatch, "v1.1.3", "a" * 40)

    assert updates.tcc_seal().state == "good"
    folder = updates._seal_store().parent
    assert [path.name for path in folder.iterdir()] == [], "no signatures.json.<pid>.tmp left"


def test_a_light_fetch_the_network_failed_is_said_as_such_and_not_fetched_twice(monkeypatch):
    fetches = []

    def fake(*args, cwd=None, timeout=None, base_env=None):
        if "fetch" in args:
            fetches.append(args)
            return False, "fatal: unable to access 'https://github.com/': Could not resolve host"
        return True, ""

    monkeypatch.setattr(updates, "_git", fake)
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)

    ok, line, why, _sha, _pins = updates.check_tcc_tag("v1.1.3", light=True)

    assert (ok, why) == (False, "fetch_failed") and "Could not resolve host" in line
    assert len(fetches) == 1
