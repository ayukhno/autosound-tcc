"""Is there a newer one, and is this installation ours to move.

Every test here fakes the two things that talk to the world — `git` and the installed metadata —
so the suite never asks GitHub anything. What is actually under test is the judgement: which
comparison decides "newer", and what stops the button touching somebody's own checkout.
"""

from __future__ import annotations

import subprocess

import pytest

from autosound_tcc.core import install_report, updates


def _git_answers(monkeypatch, answers: dict):
    """Fake `git` by first argument (`ls-remote`, `symbolic-ref`, …) -> (ok, output)."""
    calls = []

    def fake(*args, cwd=None):
        calls.append(args)
        for key, value in answers.items():
            if key in args:
                return value
        return True, ""

    monkeypatch.setattr(updates, "_git", fake)
    return calls


def test_a_newer_tag_is_an_update_and_the_same_tag_is_not(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "_is_ours", lambda repo: (True, ("", "")))
    monkeypatch.setattr(install_report, "skill_version", lambda: "3.0.6")
    _git_answers(monkeypatch, {"ls-remote": (True, "sha\trefs/tags/v3.0.7")})

    assert updates.check_skill().newer is True

    monkeypatch.setattr(install_report, "skill_version", lambda: "3.0.7")
    status = updates.check_skill()
    assert status.newer is False
    assert status.latest == "3.0.7"


def test_ten_is_newer_than_nine(monkeypatch, tmp_path):
    """The one comparison a string gets wrong: "3.0.10" < "3.0.9" alphabetically."""
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "_is_ours", lambda repo: (True, ("", "")))
    monkeypatch.setattr(install_report, "skill_version", lambda: "3.0.9")
    _git_answers(monkeypatch, {
        "ls-remote": (True, "a\trefs/tags/v3.0.9\nb\trefs/tags/v3.0.10"),
    })

    status = updates.check_skill()

    assert status.latest == "3.0.10"
    assert status.newer is True


def test_a_developer_s_own_checkout_is_never_touched(monkeypatch, tmp_path):
    """On a branch means somebody works there. The installer's clone is detached at a tag."""
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    _git_answers(monkeypatch, {
        "rev-parse": (True, ".git"),
        "symbolic-ref": (True, "main"),
        "ls-remote": (True, "sha\trefs/tags/v9.9.9"),
    })
    monkeypatch.setattr(install_report, "skill_version", lambda: "3.0.0")

    status = updates.check_skill()

    assert status.updatable is False
    assert (status.reason, status.detail) == ("on_branch", "main"), "a key, not a sentence"
    ok, why, detail = updates.apply_skill()
    assert ok is False and why == "on_branch" and detail == "main"


def test_uncommitted_changes_also_stop_it(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    _git_answers(monkeypatch, {
        "rev-parse": (True, ".git"),
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


def test_tcc_is_compared_by_commit_not_by_version(monkeypatch):
    """TCC installs from the default branch, so its version number stands still while the build
    moves. The commit is the only thing that differs between a fresh install and a stale one."""
    monkeypatch.setattr(install_report, "app_version", lambda: "0.1.1")
    monkeypatch.setattr(install_report, "install_source",
                        lambda: ("git+https://…", "a" * 40))
    monkeypatch.setattr(updates, "_remote_version", lambda sha: "0.1.1")
    _git_answers(monkeypatch, {"ls-remote": (True, "b" * 40 + "\tHEAD")})

    status = updates.check_tcc()

    assert status.newer is True, "same version, different commit — the commit decides"
    # ...and no hash reaches the row: it is bug-report material, and it is in the block below.
    assert status.installed == "0.1.1"
    assert status.latest == "0.1.1"
    assert "a" * 7 not in status.installed + status.latest

    monkeypatch.setattr(install_report, "install_source", lambda: ("git+…", "b" * 40))
    assert updates.check_tcc().newer is False


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



def test_the_remote_version_is_read_at_the_same_commit(monkeypatch):
    """A version from `main` beside a commit that is not `main`'s head would be a sentence about
    two different builds. The file is read AT the sha."""
    seen = {}

    class _Response:
        def read(self, _n=None):
            return b'[project]\nname = "autosound-tcc"\nversion = "9.9.9"\n'
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(url, timeout=None):
        seen["url"] = url
        return _Response()

    monkeypatch.setattr(updates.urllib.request, "urlopen", fake_urlopen)

    assert updates._remote_version("c" * 40) == "9.9.9"
    assert ("c" * 40) in seen["url"]


def test_an_unreadable_remote_version_falls_back_to_the_installed_number(monkeypatch):
    """Offline mid-check: the row still says there is something newer, without inventing a number."""
    def boom(url, timeout=None):
        raise OSError("no network")

    monkeypatch.setattr(updates.urllib.request, "urlopen", boom)
    monkeypatch.setattr(install_report, "app_version", lambda: "0.1.7")
    monkeypatch.setattr(install_report, "install_source", lambda: ("u", "a" * 40))
    _git_answers(monkeypatch, {"ls-remote": (True, "b" * 40 + "\tHEAD")})

    status = updates.check_tcc()

    assert updates._remote_version("d" * 40) == ""
    assert status.newer is True and status.latest == "0.1.7"
