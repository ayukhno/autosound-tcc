"""Is there a newer one, and is this installation ours to move.

Every test here fakes the two things that talk to the world — `git` and the installed metadata —
so the suite never asks GitHub anything. What is actually under test is the judgement: which
comparison decides "newer", and what stops the button touching somebody's own checkout.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from autosound_tcc.core import install_report, updates


def _git_answers(monkeypatch, answers: dict):
    """Fake `git` by first argument (`ls-remote`, `symbolic-ref`, …) -> (ok, output)."""
    calls = []

    def fake(*args, cwd=None):
        calls.append(args)
        # Longest key first: "--show-superproject-working-tree" and "--git-dir" are both rev-parse.
        for key in sorted(answers, key=len, reverse=True):
            if key in args:
                return answers[key]
        return True, ""

    monkeypatch.setattr(updates, "_git", fake)
    return calls


_HERE = "a" * 40
_THERE = "b" * 40


def _skill_at(monkeypatch, sha: str, version: str = "3.0.7"):
    """An installed method sitting at `sha`, with `version` in its manifest."""
    monkeypatch.setattr(install_report, "skill_sha", lambda: sha)
    monkeypatch.setattr(install_report, "skill_version", lambda: version)


def test_a_newer_tag_is_an_update_and_the_same_commit_is_not(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "_is_ours", lambda repo: (True, ("", "")))
    _skill_at(monkeypatch, _HERE, "3.0.6")
    _git_answers(monkeypatch, {"ls-remote": (True, f"{_THERE}\trefs/tags/v3.0.7")})

    assert updates.check_skill().newer is True

    _skill_at(monkeypatch, _THERE, "3.0.7")
    status = updates.check_skill()
    assert status.newer is False
    assert status.latest == "3.0.7"
    assert status.installed_sha == _THERE and status.latest_sha == _THERE


def test_the_sha_decides_and_the_version_string_does_not(monkeypatch, tmp_path):
    """HUB-001. `plugin.json`'s version is kept by hand, so two of them being equal says nothing
    about whether this checkout is the one the tag names — in the method's own repository `main`
    carries 3.0.36 while `marketplace.json` still says 2.8.3. A release cut without touching the
    manifest used to read as up to date forever; now the commit answers and the number is only
    shown."""
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "_is_ours", lambda repo: (True, ("", "")))
    _skill_at(monkeypatch, _HERE, "3.0.36")
    _git_answers(monkeypatch, {"ls-remote": (True, f"{_THERE}\trefs/tags/v3.0.36")})

    status = updates.check_skill()

    assert status.newer is True, "same number, different commit — and the commit is the fact"
    assert status.installed == status.latest == "3.0.36", "the number is still shown as it is"


def test_an_annotated_tag_is_compared_by_the_COMMIT_it_points_at(monkeypatch, tmp_path):
    """The trap `--refs` sets, measured in the hub's RELEASE-CHANNEL.md §8.2.

    `ls-remote --refs` drops the peeled `^{}` line, and what is left for an ANNOTATED tag is the
    sha of the tag OBJECT. A checked-out HEAD is a commit, so that comparison never matches and
    every installation reads as out of date while looking like the network working."""
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "_is_ours", lambda repo: (True, ("", "")))
    _skill_at(monkeypatch, _HERE)
    calls = _git_answers(monkeypatch, {"ls-remote": (True,
        f"{_THERE}\trefs/tags/v3.0.7\n{_HERE}\trefs/tags/v3.0.7^{{}}")})

    status = updates.check_skill()

    assert status.latest_sha == _HERE, "the commit, not the tag object"
    assert status.newer is False, "this checkout IS v3.0.7"
    ask = [call for call in calls if "ls-remote" in call][0]
    assert "--refs" not in ask, "--refs would hide the peeled line"
    assert f"{updates.SKILL_TAG_GLOB}^{{}}" in ask, (
        "asked for explicitly, not left to a glob that happens to end in *")


def test_ten_is_newer_than_nine(monkeypatch, tmp_path):
    """The one comparison a string gets wrong: "3.0.10" < "3.0.9" alphabetically. Which tag is
    newest is still decided by its NAME — the shas only say whether we are standing on it."""
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "_is_ours", lambda repo: (True, ("", "")))
    _skill_at(monkeypatch, _HERE, "3.0.9")
    _git_answers(monkeypatch, {
        "ls-remote": (True, f"{_HERE}\trefs/tags/v3.0.9\n{_THERE}\trefs/tags/v3.0.10"),
    })

    status = updates.check_skill()

    assert status.latest == "3.0.10"
    assert status.latest_sha == _THERE
    assert status.newer is True


def test_a_method_git_will_not_answer_for_is_not_up_to_date(monkeypatch, tmp_path):
    """No sha means the question could not be asked, and "could not ask" is not "nothing new"."""
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "_is_ours", lambda repo: (True, ("", "")))
    _skill_at(monkeypatch, "", "3.0.7")
    _git_answers(monkeypatch, {"ls-remote": (True, f"{_THERE}\trefs/tags/v3.0.8")})

    status = updates.check_skill()

    assert status.newer is False
    assert status.installed_sha == "" and status.latest == "3.0.8"


def test_a_developer_s_own_checkout_is_never_touched(monkeypatch, tmp_path):
    """On a branch means somebody works there. The installer's clone is detached at a tag."""
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    _git_answers(monkeypatch, {
        "--git-dir": (True, ".git"),
        "--show-superproject-working-tree": (True, ""),
        "symbolic-ref": (True, "main"),
        "ls-remote": (True, f"{_THERE}\trefs/tags/v9.9.9"),
    })
    _skill_at(monkeypatch, _HERE, "3.0.0")

    status = updates.check_skill()

    assert status.updatable is False
    assert (status.reason, status.detail) == ("on_branch", "main"), "a key, not a sentence"
    ok, why, detail = updates.apply_skill()
    assert ok is False and why == "on_branch" and detail == "main"


def test_uncommitted_changes_also_stop_it(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    _git_answers(monkeypatch, {
        "--git-dir": (True, ".git"),
        "--show-superproject-working-tree": (True, ""),
        "symbolic-ref": (False, ""),
        "status": (True, " M skills/autosound-tuning/SKILL.md"),
    })

    ok, why, _detail = updates.apply_skill()

    assert ok is False and why == "dirty"


def test_the_method_is_updated_the_way_the_installer_does_it(monkeypatch, tmp_path):
    """Fetch the tag BY NAME into a --depth 1 clone, then check out FETCH_HEAD."""
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "_is_ours", lambda repo: (True, ("", "")))
    calls = _git_answers(monkeypatch, {"ls-remote": (True, "sha\trefs/tags/v3.0.7")})

    ok, what, _detail = updates.apply_skill()

    assert ok is True and what == "v3.0.7"
    fetch = [c for c in calls if "fetch" in c][0]
    assert "--depth" in fetch and "v3.0.7" in fetch
    assert any("FETCH_HEAD" in c for c in calls)


def test_tcc_is_compared_against_the_newest_release(monkeypatch):
    """Both halves follow tags since F-024, so the row compares versions and means it.

    It used to compare COMMITS, and that was right for what it described: TCC installed from the
    default branch, so the version stood still while the build moved. A release is the unit being
    offered now, so the number on screen is the thing that differs.
    """
    monkeypatch.setattr(install_report, "app_version", lambda: "0.1.10")
    monkeypatch.setattr(install_report, "install_source",
                        lambda: ("git+https://…", "a" * 40))
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda: "v0.1.11")

    status = updates.check_tcc()

    assert status.newer is True
    assert status.installed == "0.1.10" and status.latest == "0.1.11"
    assert "a" * 7 not in status.installed + status.latest, "no hash reaches the row"

    monkeypatch.setattr(updates, "newest_tcc_tag", lambda: "v0.1.10")
    assert updates.check_tcc().newer is False


def test_a_build_ahead_of_the_releases_is_not_told_to_update_backwards(monkeypatch):
    """A developer running `main` is ahead of the newest tag on purpose. Offering them an
    "update" to an older release would be telling them to throw work away."""
    monkeypatch.setattr(install_report, "app_version", lambda: "0.1.12")
    monkeypatch.setattr(install_report, "install_source", lambda: ("u", "a" * 40))
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda: "v0.1.11")

    status = updates.check_tcc()

    assert status.newer is False
    assert status.latest == "0.1.12", "and the row shows what is actually here"


def test_the_update_command_pins_the_release_it_is_offering(monkeypatch):
    """Without a ref `uv` installs the default branch — which is what "update" used to mean, and
    is how a machine ended up with whatever had landed on `main` since (F-024). The ref-less form
    survives as the OFFLINE fallback, where no tag can be looked up."""
    pinned = updates.tcc_install_command("v0.1.11")
    assert "@v0.1.11" in pinned and pinned.count("git+") == 1

    assert updates.tcc_install_command("") == updates.TCC_INSTALL_COMMAND
    assert "@v" not in updates.TCC_INSTALL_COMMAND

    assert "@v0.1.11" in updates.tcc_install_line(pid=4242, tag="v0.1.11")


def test_a_source_checkout_is_told_to_use_git(monkeypatch):
    """Running from a clone has no `direct_url.json` and no business calling `uv`."""
    monkeypatch.setattr(install_report, "install_source", lambda: ("", ""))
    monkeypatch.setattr(install_report, "app_version", lambda: "0.1.1")

    status = updates.check_tcc()

    assert status.updatable is False
    assert status.reason == "source_checkout"


def test_an_unreachable_github_is_not_up_to_date(monkeypatch):
    """The difference that matters: "we asked and there is nothing new" vs "we could not ask"."""
    monkeypatch.setattr(install_report, "app_version", lambda: "0.1.1")
    monkeypatch.setattr(install_report, "install_source", lambda: ("u", "a" * 40))
    _git_answers(monkeypatch, {"ls-remote": (False, "could not resolve host")})

    status = updates.check_tcc()

    assert status.newer is False
    assert status.latest == ""
    assert status.reason == "no_network"


def test_the_probe_never_raises_when_git_is_missing(monkeypatch):
    """No git on the machine is a row that says so, not a traceback in a panel."""
    def boom(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)

    ok, out = updates._git("ls-remote", "x")

    assert ok is False and "FileNotFoundError" in out


@pytest.mark.parametrize("text, expected", [
    ("v3.0.7", (3, 0, 7)),
    ("3.0.10", (3, 0, 10)),
    ("nothing", (0,)),
])
def test_version_keys(text, expected):
    assert updates._version_key(text) == expected


def test_the_update_waits_for_this_process_before_it_replaces_it(monkeypatch):
    """Telling somebody to close the app first was tried and was not enough: `uv` replaced the
    package while TCC was open, then failed clearing the old `Scripts` -- Windows will not delete a
    running executable -- and the install was left half-swapped and would not start (user, Windows
    11, 2026-08-19). The window waits for our pid instead of asking."""
    monkeypatch.setattr(updates.sys, "platform", "win32")
    line = updates.tcc_install_line(pid=4242)
    assert "Wait-Process -Id 4242" in line
    assert line.index("Wait-Process") < line.index("uv tool install"), "wait first, then install"

    monkeypatch.setattr(updates.sys, "platform", "darwin")
    line = updates.tcc_install_line(pid=4242)
    assert "kill -0 4242" in line
    assert line.index("kill -0") < line.index("uv tool install")


def test_the_wait_defaults_to_our_own_process():
    import os

    assert str(os.getpid()) in updates.tcc_install_line()

def test_a_repository_that_cannot_be_asked_for_tags_says_so(monkeypatch):
    """Offline mid-check. The row must not invent a number, and must not claim to be current
    either -- "could not ask" is its own answer."""
    monkeypatch.setattr(install_report, "app_version", lambda: "0.1.7")
    monkeypatch.setattr(install_report, "install_source", lambda: ("u", "a" * 40))
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda: "")

    status = updates.check_tcc()

    assert status.newer is False and status.reason == "no_network"
    assert status.latest == ""
def test_a_submodule_is_not_an_installed_release(monkeypatch, tmp_path):
    """The case the other guards let through: a submodule is detached and clean, exactly like a
    release checkout. Updating it would check a tag out inside somebody's working repository and
    leave the parent's pin modified."""
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    _skill_at(monkeypatch, _HERE, "3.0.7")
    _git_answers(monkeypatch, {
        "--git-dir": (True, ".git"),
        "--show-superproject-working-tree": (True, "/Users/somebody/dev/autosound-tcc"),
        "ls-remote": (True, f"{_THERE}\trefs/tags/v3.0.8"),
    })

    status = updates.check_skill()

    assert status.updatable is False
    assert status.reason == "submodule"
    assert status.detail.endswith("autosound-tcc")
    ok, why, _detail = updates.apply_skill()
    assert ok is False and why == "submodule", "and the button cannot do it either"


def test_our_installer_constants_agree_with_the_installers_own(monkeypatch):
    """F-030. Four values here are "the installer's own constants, kept identical on purpose" —
    and until the method grew a way to print them, identical meant somebody typed them twice.
    The method's tag glob is written FOUR times: `install.sh`, `install.ps1`, `install.cmd`, and
    this module. Its own checker keeps its three in step; ours was the copy nobody checked.

    Read from the checker's OUTPUT, not from its source. A grep over their script would pass on
    a comment and break silently on a refactor of theirs; `--print` is an interface they now
    maintain, and an unknown name exits 2 with the available ones listed, so a typo here fails
    loudly instead of comparing against an empty string. That last property is asserted too,
    because it is the whole reason reading their output is safe.

    The repository URLs are compared with a trailing `.git` taken off both sides, deliberately.
    They are the same remote either way — `git ls-remote` accepts both — and the method spells
    the skill's with the suffix and TCC's without. Asserting the characters would be asserting
    somebody's punctuation and would fail on a difference nothing can act on; asserting the
    remote is what the constant is FOR.
    """
    import subprocess as sp

    from autosound_tcc.core import vendor_loader

    if not vendor_loader.is_available():
        pytest.skip("rew_tool submodule not initialized")
    script = vendor_loader.skill_dir().parent.parent / "scripts" / "installer-consistency.py"
    if not script.is_file():
        pytest.skip(f"the method at this pin has no {script.name}")

    done = sp.run([sys.executable, str(script), "--print"],
                  capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    theirs = dict(
        line.split("=", 1) for line in done.stdout.splitlines() if "=" in line
    )

    assert theirs.get("SKILL_TAG_GLOB") == updates.SKILL_TAG_GLOB
    assert theirs.get("TCC_TAG_GLOB") == updates.TCC_TAG_GLOB
    assert _same_remote(theirs.get("SKILL_REPO", ""), updates.SKILL_REPO)
    assert _same_remote(theirs.get("TCC_REPO", ""), updates.TCC_REPO)

    # And the guard that makes the four assertions above trustworthy: asking for a name that does
    # not exist is an error with the real names in it, never an empty string.
    missed = sp.run([sys.executable, str(script), "--print", "NO_SUCH_NAME"],
                    capture_output=True, text=True, timeout=60, check=False)
    assert missed.returncode != 0
    assert "SKILL_TAG_GLOB" in (missed.stdout + missed.stderr)


def _same_remote(a: str, b: str) -> bool:
    return a.rstrip("/").removesuffix(".git") == b.rstrip("/").removesuffix(".git")
