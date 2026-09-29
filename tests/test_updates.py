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
    upkeep = _fake_upkeep(monkeypatch, tmp_path, {})

    status = updates.check_skill()

    assert status.updatable is False
    assert (status.reason, status.detail) == ("on_branch", "main"), "a key, not a sentence"
    done = updates.apply_skill()
    assert done.ok is False and done.reason == "on_branch" and done.detail == "main"
    found = updates.local_changes()
    assert found.ok is False and found.reason == "on_branch"
    assert upkeep == [], "upkeep's keep-local resets a clone: a working tree never reaches it"


def test_local_changes_no_longer_grey_the_button(monkeypatch, tmp_path):
    """tcc#91 (SKL-056). A session had patched `rew_tool/contract.py` in the installed clone, and
    the row said «має незакомічені зміни, тому не чіпаю» over a grey button — no next step without
    git by hand. The clone's changes are the skill's `upkeep.py keep-local` business now, so they
    no longer make the clone "not ours", and TCC stopped asking git about them at all."""
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    calls = _git_answers(monkeypatch, {
        "--git-dir": (True, ".git"),
        "--show-superproject-working-tree": (True, ""),
        "symbolic-ref": (False, ""),
        "status": (True, " M skills/autosound-tuning/rew_tool/contract.py"),
        "ls-remote": (True, f"{_THERE}\trefs/tags/v3.0.64"),
    })
    _skill_at(monkeypatch, _HERE, "3.0.61")

    status = updates.check_skill()

    assert status.newer is True and status.updatable is True
    assert not any("status" in call for call in calls), "no porcelain check from TCC any more"


# ---- the skill moved by its own upkeep.py (hub #221 SKL-059, tcc#91) -------------------------

_CLONE_JSON = {"clone": "/c", "from": "v3.0.61", "to": "v3.0.64",
               "signature": "v3.0.64: signature good (ayukhno)"}
_LIBS_JSON = {"python": "/usr/bin/python3", "command": "pip …", "ok": True,
              "before": {"numpy": "2.0.2", "scipy": "1.13.1", "matplotlib": "3.9.4"},
              "after": {"numpy": "2.1.0", "scipy": "1.13.1", "matplotlib": "3.9.4"}, "why": ""}
_KEPT_JSON = {"clone": "/c", "changed": ["skills/autosound-tuning/rew_tool/contract.py"],
              "version": "v3.0.61", "patch": "/h/.claude/skills/autosound-local-changes/x.patch",
              "sent": None, "reset": True}


def _fake_upkeep(monkeypatch, tmp_path, answers: dict):
    """Fake the skill's `upkeep.py` by subcommand -> `(exit code, JSON object or raw stdout)`.

    Returns the list of subcommands it was asked for, each with its own arguments — the ORDER is
    what most of these tests are about. The real script never runs: it would act on a clone."""
    import json

    script = tmp_path / "upkeep.py"
    script.write_text("raise SystemExit('the fake is patched in; this never runs')\n")
    monkeypatch.setattr(updates, "upkeep_script", lambda: script)
    calls = []

    def fake(argv, timeout):
        assert argv[1] == str(script) and argv[2:4] == ["--json", "--clone"], argv
        calls.append(argv[5:])
        code, out = answers.get(argv[5], (0, {}))
        return code, out if isinstance(out, str) else json.dumps(out), ""

    monkeypatch.setattr(updates, "_run_upkeep", fake)
    return calls


def _an_installed_clone(monkeypatch, tmp_path):
    repo = tmp_path / "clone"
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: repo)
    monkeypatch.setattr(updates, "_is_ours", lambda repo: (True, ("", "")))
    return repo


def test_a_clean_clone_is_moved_by_upkeep_clone_then_libs(monkeypatch, tmp_path):
    """Ask 1 and 2 of hub #221: the tag the row offered, through the skill's own `clone` (the tag
    lands in refs/tags — skill #92 — and its signature is checked — skill #99), and then `libs`
    in the same action, so numpy, scipy and matplotlib follow the skill that uses them (skill #98)."""
    _an_installed_clone(monkeypatch, tmp_path)
    git = _git_answers(monkeypatch, {})
    calls = _fake_upkeep(monkeypatch, tmp_path, {"clone": (0, _CLONE_JSON), "libs": (0, _LIBS_JSON)})

    done = updates.apply_skill("v3.0.64")

    assert calls == [["clone", "--tag", "v3.0.64"], ["libs"]]
    assert done.ok is True and done.version == "v3.0.64"
    assert done.signature == "v3.0.64: signature good (ayukhno)", "the skill's line, as it said it"
    assert done.libs_ok is True and done.libs == "numpy 2.0.2 → 2.1.0", "only what moved"
    assert done.patch == "" and done.sent is None, "nothing was kept: nothing was changed here"
    assert git == [], "TCC runs no git against the clone to move it"


def test_upkeep_runs_on_tcc_s_python_with_json_and_the_clone_before_the_command(monkeypatch,
                                                                                 tmp_path):
    """The contract (hub #217, #219): `--json` and `--clone` go BEFORE the subcommand, and the
    interpreter is the one TCC runs on — its console twin on Windows (`child.script_interpreter`)."""
    from autosound_tcc.core import child

    repo = _an_installed_clone(monkeypatch, tmp_path)
    seen = []
    _fake_upkeep(monkeypatch, tmp_path, {"clone": (0, _CLONE_JSON), "libs": (0, _LIBS_JSON)})
    fake = updates._run_upkeep
    monkeypatch.setattr(updates, "_run_upkeep", lambda argv, timeout: seen.append(argv) or fake(
        argv, timeout))

    updates.apply_skill("v3.0.64")

    assert seen[0] == [child.script_interpreter(), str(tmp_path / "upkeep.py"), "--json",
                       "--clone", str(repo), "clone", "--tag", "v3.0.64"]


def test_a_dirty_clone_is_named_then_kept_as_a_patch_before_the_clone_moves(monkeypatch,
                                                                              tmp_path):
    """tcc#91: the changed files named (read from `upkeep.py status`, not from git), then
    `keep-local` — the patch on disk before its own reset — and only then `clone` and `libs`.
    No `--send` without the person's yes, and a declined send still updates."""
    _an_installed_clone(monkeypatch, tmp_path)
    calls = _fake_upkeep(monkeypatch, tmp_path, {
        "status": (0, {"clone": {"path": "/c", "exists": True, "version": "v3.0.61",
                                 "changed": ["skills/autosound-tuning/rew_tool/contract.py"]},
                       "tools": [], "libs": {}}),
        "keep-local": (0, _KEPT_JSON),
        "clone": (0, _CLONE_JSON),
        "libs": (0, _LIBS_JSON),
    })

    found = updates.local_changes()
    done = updates.apply_skill("v3.0.64", keep_local=True, send=False)

    assert found.ok is True
    assert found.changed == ("skills/autosound-tuning/rew_tool/contract.py",)
    assert calls == [["status"], ["keep-local"], ["clone", "--tag", "v3.0.64"], ["libs"]]
    assert done.ok is True and done.patch.endswith("x.patch"), "where the changes went, said"
    assert done.sent is None


def test_a_yes_to_sending_passes_send_and_the_answer_comes_back(monkeypatch, tmp_path):
    _an_installed_clone(monkeypatch, tmp_path)
    url = "https://github.com/ayukhno/autosound-tuning-skill/issues/123"
    calls = _fake_upkeep(monkeypatch, tmp_path, {
        "keep-local": (0, {**_KEPT_JSON, "sent": {"sent": True, "url": url}}),
        "clone": (0, _CLONE_JSON), "libs": (0, _LIBS_JSON)})

    done = updates.apply_skill("v3.0.64", keep_local=True, send=True)

    assert calls[0] == ["keep-local", "--send"]
    assert done.sent == {"sent": True, "url": url}

    why = "no GitHub here (`gh` missing or not signed in); the patch is kept"
    _fake_upkeep(monkeypatch, tmp_path, {
        "keep-local": (0, {**_KEPT_JSON, "sent": {"sent": False, "why": why}}),
        "clone": (0, _CLONE_JSON), "libs": (0, _LIBS_JSON)})
    done = updates.apply_skill("v3.0.64", keep_local=True, send=True)
    assert done.ok is True and done.sent == {"sent": False, "why": why}, "not sent still updates"


def test_a_refused_clone_is_its_own_sentence_and_nothing_else_runs(monkeypatch, tmp_path):
    """Exit 3 and `{"ok": false, "refused": …}` — a bad signature, a dirty clone, no network. The
    sentence is the skill's and goes on screen as it is; `libs` does not run after a clone that
    did not move."""
    _an_installed_clone(monkeypatch, tmp_path)
    said = "v3.0.64: the signature does not check out -- no principal matched; nothing was changed"
    calls = _fake_upkeep(monkeypatch, tmp_path, {
        "clone": (3, {"ok": False, "refused": said}), "libs": (0, _LIBS_JSON)})

    done = updates.apply_skill("v3.0.64")

    assert calls == [["clone", "--tag", "v3.0.64"]]
    assert done.ok is False and (done.reason, done.detail) == ("refused", said)


def test_a_refused_keep_local_stops_before_the_clone(monkeypatch, tmp_path):
    _an_installed_clone(monkeypatch, tmp_path)
    said = "/p.patch does not hold the clone's changes exactly; nothing was reset"
    calls = _fake_upkeep(monkeypatch, tmp_path, {"keep-local": (3, {"ok": False, "refused": said})})

    done = updates.apply_skill("v3.0.64", keep_local=True)

    assert calls == [["keep-local"]]
    assert done.ok is False and done.detail == said


def test_the_patch_is_still_named_when_the_clone_then_refuses(monkeypatch, tmp_path):
    """keep-local has already reset the clone by then: where the changes went must not be lost
    with the refusal."""
    _an_installed_clone(monkeypatch, tmp_path)
    _fake_upkeep(monkeypatch, tmp_path, {
        "keep-local": (0, _KEPT_JSON),
        "clone": (3, {"ok": False, "refused": "could not fetch v3.0.64: timeout; nothing was changed"})})

    done = updates.apply_skill("v3.0.64", keep_local=True)

    assert done.ok is False and done.patch.endswith("x.patch")


def test_libraries_that_did_not_upgrade_do_not_undo_the_update(monkeypatch, tmp_path):
    """`libs` exits 3 with its own object — not a refusal — when pip fails. The clone HAS moved."""
    _an_installed_clone(monkeypatch, tmp_path)
    _fake_upkeep(monkeypatch, tmp_path, {
        "clone": (0, _CLONE_JSON),
        "libs": (3, {**_LIBS_JSON, "ok": False, "why": "ERROR: No matching distribution"})})

    done = updates.apply_skill("v3.0.64")

    assert done.ok is True and done.version == "v3.0.64"
    assert done.libs_ok is False and done.libs == "ERROR: No matching distribution"


def test_an_answer_that_is_not_json_is_said_in_its_own_words(monkeypatch, tmp_path):
    _an_installed_clone(monkeypatch, tmp_path)
    _fake_upkeep(monkeypatch, tmp_path, {"clone": (1, "Traceback …\nOSError: disk full")})

    done = updates.apply_skill("v3.0.64")

    assert done.ok is False and done.reason == "upkeep_failed"
    assert "disk full" in done.detail


def test_a_skill_older_than_its_own_updater_is_told_so(monkeypatch, tmp_path):
    """`upkeep.py` arrived with the skill's v3.0.64. TCC's wheel carries no copy of the skill (it
    finds the installed one — `vendor_loader`), so an installed clone older than that has no
    updater TCC could run, and TCC no longer moves it with git itself (hub #221)."""
    _an_installed_clone(monkeypatch, tmp_path)
    monkeypatch.setattr(updates, "upkeep_script", lambda: None)
    ran = []
    monkeypatch.setattr(updates, "_run_upkeep", lambda argv, timeout: ran.append(argv))

    assert updates.apply_skill("v3.0.64").reason == "no_upkeep"
    assert updates.local_changes().reason == "no_upkeep"
    assert ran == []


def test_the_real_subprocess_path_reads_a_stub_upkeep(monkeypatch, tmp_path):
    """One run through `subprocess` with a stub in place of `upkeep.py`: the argv arrives in the
    contract's order, the JSON comes back parsed, and the child cannot stop to ask for a password
    or leave `__pycache__` in the clone (which `git status` would then name as a change)."""
    _an_installed_clone(monkeypatch, tmp_path)
    stub = tmp_path / "upkeep.py"
    stub.write_text(
        "import json, os, sys\n"
        "print(json.dumps({'clone': {'path': '/c', 'exists': True, 'version': 'v3.0.61',\n"
        "  'changed': [' '.join(sys.argv[1:]), os.environ.get('GIT_TERMINAL_PROMPT'),\n"
        "              os.environ.get('PYTHONDONTWRITEBYTECODE')]}}))\n",
        encoding="utf-8")
    monkeypatch.setattr(updates, "upkeep_script", lambda: stub)

    found = updates.local_changes()

    assert found.ok is True, found
    argv, prompt, bytecode = found.changed
    assert argv == f"--json --clone {tmp_path / 'clone'} status"
    assert prompt == "0" and bytecode == "1"


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

    for platform in ("darwin", "win32"):
        assert "@v0.1.11" in updates.tcc_install_script(pid=4242, tag="v0.1.11", platform=platform)


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
    # Not "no network" on the app's word: git says what failed, and the row repeats git (22643c0,
    # finding 40 — the row blamed GitHub while git itself could not run).
    assert status.reason == "probe_failed"
    assert "could not resolve host" in status.detail


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


def test_the_update_waits_for_this_process_before_it_replaces_it():
    """Telling somebody to close the app first was tried and was not enough: `uv` replaced the
    package while TCC was open, then failed clearing the old `Scripts` -- Windows will not delete a
    running executable -- and the install was left half-swapped and would not start (user, Windows
    11, 2026-08-19). The window waits for our pid instead of asking."""
    script = updates.tcc_install_script(pid=4242, platform="win32")
    assert "Wait-Process -Id 4242" in script
    assert script.index("Wait-Process") < script.index("uv tool install"), "wait first, then install"

    script = updates.tcc_install_script(pid=4242, platform="darwin")
    assert "kill -0 4242" in script
    assert script.index("kill -0") < script.index("uv tool install")


def test_the_wait_defaults_to_our_own_process():
    import os

    assert f"kill -0 {os.getpid()} " in updates.tcc_install_script(platform="darwin")


_WORDS = {"wait": "Закрий ТСС — це вікно чекає на нього, тоді оновить.",
          "updating": "ТСС закрито — оновлюю.",
          "done": "Готово — запусти ТСС знову.",
          "failed": "Оновлення не завершилось — чому, сказано вище."}


@pytest.mark.skipif(sys.platform.startswith("win"), reason="runs the macOS script with sh")
def test_the_mac_update_window_shows_only_the_person_s_lines(tmp_path):
    """hub #221 ask 3 (skill #94). zsh echoed the whole typed line — `echo …; while kill -0 …;
    uv tool install … @v0.1.44 …` — and the one sentence the Arbiter needed came last and was lost
    («можемо заховати зайве?»). So the window runs a script file whose first act is to clear the
    screen, the typed `sh '<file>'` included, and what is left is his lines and uv's own answer.

    Run for real here, with a fake `uv` and a process that has already gone."""
    import os
    import subprocess as sp

    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "uv").write_text("#!/bin/sh\necho 'Installed 1 executable: autosound-tcc'\n")
    (bindir / "uv").chmod(0o755)
    gone = sp.Popen(["true"])
    gone.wait()
    path = updates.write_tcc_install_script(pid=gone.pid, tag="v0.1.45", words=_WORDS,
                                            folder=tmp_path, platform="darwin")

    out = sp.run(["/bin/sh", str(path)], capture_output=True, text=True, encoding="utf-8",
                 env={**os.environ, "PATH": f"{bindir}:/usr/bin:/bin"}, timeout=30).stdout

    first, _sep, rest = out.partition(_WORDS["wait"])
    assert first == "\033[H\033[2J\033[3J", "the screen and its scrollback go first"
    assert rest.splitlines() == ["", _WORDS["updating"], "Installed 1 executable: autosound-tcc",
                                 "", _WORDS["done"]]
    for command in ("uv tool install", "kill -0", "echo", "printf"):
        assert command not in out, f"{command!r} reached the window"


def test_a_failed_install_says_so_instead_of_done(tmp_path):
    for platform in ("darwin", "win32"):
        script = updates.tcc_install_script(pid=1, words=_WORDS, platform=platform)
        assert script.index(_WORDS["failed"]) > script.index("uv tool install")
        assert script.count(_WORDS["done"]) == 1


def test_the_windows_update_window_shows_only_the_person_s_lines(tmp_path):
    """The same on Windows: a `.cmd` file whose first line turns the echo of every line off and
    whose next clears the window, run by name (`terminal_launcher.run_script`). UTF-8 with
    `chcp 65001` so the Arbiter's words arrive whole, CRLF because cmd reads batch files by line,
    and `call` in front of uv so a `.cmd` shim of it would not end this script early."""
    path = updates.write_tcc_install_script(pid=4242, tag="v0.1.45", words=_WORDS,
                                            folder=tmp_path, platform="win32")

    raw = path.read_bytes()
    assert path.suffix == ".cmd"
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), "CRLF throughout"
    lines = raw.decode("utf-8").split("\r\n")
    assert lines[:3] == ["@echo off", "chcp 65001 >nul", "cls"], lines[:3]
    shown = [line[len("echo "):] for line in lines if line.startswith("echo ")]
    assert shown == [_WORDS["wait"], _WORDS["updating"], _WORDS["done"], _WORDS["failed"]]
    install = next(line for line in lines if "uv tool install" in line)
    assert install.startswith("call uv tool install ") and "@v0.1.45" in install


def test_a_sentence_cannot_turn_into_a_command(tmp_path):
    """The words are translations, and `&` or `|` in one would be a second command in cmd; a
    quote would end the string in sh."""
    words = {**_WORDS, "wait": "Close TCC & wait | it's 100% fine <ok>"}
    win = updates.tcc_install_script(pid=1, words=words, platform="win32")
    assert "echo Close TCC ^& wait ^| it's 100%% fine ^<ok^>" in win
    mac = updates.tcc_install_script(pid=1, words=words, platform="darwin")
    assert """printf '%s\\n' 'Close TCC & wait | it'"'"'s 100% fine <ok>'""" in mac


def test_a_repository_that_cannot_be_asked_for_tags_says_so(monkeypatch):
    """Offline mid-check. The row must not invent a number, and must not claim to be current
    either -- "could not ask" is its own answer."""
    monkeypatch.setattr(install_report, "app_version", lambda: "0.1.7")
    monkeypatch.setattr(install_report, "install_source", lambda: ("u", "a" * 40))
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda: "")

    status = updates.check_tcc()

    assert status.newer is False and status.reason == "probe_failed"
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
    done = updates.apply_skill()
    assert done.ok is False and done.reason == "submodule", "and the button cannot do it either"


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
    assert theirs.get("TCC_BETA_GLOB") == updates.TCC_BETA_GLOB
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


def test_the_update_check_can_never_stop_to_ask_for_a_password(monkeypatch):
    """TCC-006. The update check is a GUI app asking GitHub a question in a background thread.
    Git's answer to a repository it cannot read is to ask for credentials — on Windows through
    Git Credential Manager, which is a WINDOW. Nobody is looking at it: the thread is a daemon,
    the caller polls a timer, and the person sees a tall dialog appear over their tune or a
    process that never returns.

    The user's own report (2026-09-09) is "a tall stretched Windows window and then a terminal
    one", and this is the first half of that shape. So the check runs in an environment where
    asking is not possible: it either answers from what it has, or fails and stays silent."""
    from autosound_tcc.core import updates

    seen = {}

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs.get("env") or {}
        import subprocess as sp

        return sp.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(updates.subprocess, "run", fake_run)

    updates._git("ls-remote", "--tags", "https://example.invalid/x.git")

    assert seen["env"].get("GIT_TERMINAL_PROMPT") == "0"
    assert seen["env"].get("GCM_INTERACTIVE") == "never"
    assert seen["env"].get("GIT_ASKPASS") == ""


@pytest.mark.parametrize("name, expected", [
    ("v3.1.0", (3, 1, 0, 1, 0)),
    ("beta-v3.1.0-rc2", (3, 1, 0, 0, 2)),
    ("v3.1.1-foo", None),
    ("beta-v3.1.0", None),
    ("3.1.0", None),
])
def test_channel_keys(name, expected):
    assert updates.channel_key(name) == expected


def test_the_beta_order_is_the_installers_own():
    """Hub RELEASE-CHANNEL.md §11.2 — the cases the method's `newest_on_channel` is held to."""
    key = updates.channel_key
    assert key("v3.1.0") > key("beta-v3.1.0-rc2"), "a release above its own candidates"
    assert key("beta-v3.1.0-rc10") > key("beta-v3.1.0-rc2"), "rc10 above rc2"
    assert key("beta-v3.1.0-rc1") > key("v3.0.49"), "a candidate for 3.1.0 above 3.0.49"


def test_beta_lists_releases_and_candidates_each_with_its_own_peel(monkeypatch):
    calls = _git_answers(monkeypatch, {"ls-remote": (True, "\n".join([
        f"{_HERE}\trefs/tags/v0.1.39",
        f"{_THERE}\trefs/tags/beta-v0.1.40-rc2",
        f"{'c' * 40}\trefs/tags/beta-v0.1.40-rc10",
        f"{'d' * 40}\trefs/tags/beta-v0.1.40-rc10^{{}}",
    ]))})

    assert updates._newest_tag_in(
        updates.TCC_REPO, updates.TCC_TAG_GLOB, updates.TCC_BETA_GLOB, key=updates.channel_key,
    ) == ("beta-v0.1.40-rc10", "d" * 40), "the newest by the key, and the peeled commit wins"
    assert calls[-1][-4:] == ("v*", "v*^{}", "beta-v*", "beta-v*^{}")
    assert updates.newest_tcc_tag(updates.BETA) == "beta-v0.1.40-rc10"


def test_stable_still_asks_for_releases_only(monkeypatch):
    calls = _git_answers(monkeypatch, {"ls-remote": (True, f"{_HERE}\trefs/tags/v0.1.39")})

    assert updates.newest_tcc_tag() == "v0.1.39"
    assert calls[-1] == ("ls-remote", "--tags", updates.TCC_REPO, "v*", "v*^{}")


_RC1, _RC2, _REL = "1" * 40, "2" * 40, "3" * 40


def _tcc_installed(monkeypatch, version: str, commit: str, revision: str = ""):
    monkeypatch.setattr(install_report, "app_version", lambda: version)
    monkeypatch.setattr(install_report, "install_source", lambda: ("u", commit))
    monkeypatch.setattr(install_report, "requested_revision", lambda: revision)


def _tcc_tags(monkeypatch, *lines: str):
    _git_answers(monkeypatch, {"ls-remote": (True, "\n".join(lines))})


def test_on_beta_the_installed_candidate_is_current(monkeypatch):
    """A candidate writes nothing, so rc1 can say 0.1.38. By version it would be offered to itself
    forever; by commit it is what it is."""
    _tcc_installed(monkeypatch, "0.1.38", _RC1, "beta-v0.2.0-rc1")
    _tcc_tags(monkeypatch, f"{_HERE}\trefs/tags/v0.1.38", f"{_RC1}\trefs/tags/beta-v0.2.0-rc1")

    status = updates.check_tcc(updates.BETA)

    assert status.newer is False
    assert status.installed == "0.1.38 (beta-v0.2.0-rc1)"
    assert status.latest == "0.2.0-rc1"


def test_on_beta_the_next_candidate_and_then_the_release_are_newer(monkeypatch):
    _tcc_installed(monkeypatch, "0.1.38", _RC1, "beta-v0.2.0-rc1")
    _tcc_tags(monkeypatch, f"{_RC1}\trefs/tags/beta-v0.2.0-rc1",
              f"{_RC2}\trefs/tags/beta-v0.2.0-rc2")
    status = updates.check_tcc(updates.BETA)
    assert status.newer is True and status.latest == "0.2.0-rc2"

    _tcc_tags(monkeypatch, f"{_RC2}\trefs/tags/beta-v0.2.0-rc2", f"{_REL}\trefs/tags/v0.2.0")
    status = updates.check_tcc(updates.BETA)
    assert status.newer is True and status.latest == "0.2.0", "the release is cut on its candidates"


def test_on_beta_the_release_once_installed_is_current(monkeypatch):
    _tcc_installed(monkeypatch, "0.2.0", _REL, "v0.2.0")
    _tcc_tags(monkeypatch, f"{_RC2}\trefs/tags/beta-v0.2.0-rc2", f"{_REL}\trefs/tags/v0.2.0")

    status = updates.check_tcc(updates.BETA)

    assert status.newer is False
    assert status.installed == "0.2.0", "a release shows its version alone"


def test_on_beta_a_build_ahead_of_the_newest_tag_is_not_sent_back(monkeypatch):
    _tcc_installed(monkeypatch, "0.2.1", "e" * 40)
    _tcc_tags(monkeypatch, f"{_REL}\trefs/tags/v0.2.0")

    status = updates.check_tcc(updates.BETA)

    assert status.newer is False and status.latest == "0.2.1"


def test_on_beta_a_candidate_already_carrying_its_version_is_offered_the_next(monkeypatch):
    """Waves commit the version before the tag (hub #148), so rc1 can already say 0.2.0 — equal to
    the newest tag's X.Y.Z is not ahead of it."""
    _tcc_installed(monkeypatch, "0.2.0", _RC1, "beta-v0.2.0-rc1")
    _tcc_tags(monkeypatch, f"{_RC1}\trefs/tags/beta-v0.2.0-rc1",
              f"{_RC2}\trefs/tags/beta-v0.2.0-rc2")

    assert updates.check_tcc(updates.BETA).newer is True


def test_on_beta_an_unreachable_github_is_not_up_to_date(monkeypatch):
    _tcc_installed(monkeypatch, "0.1.38", _RC1)
    _git_answers(monkeypatch, {"ls-remote": (False, "fatal: unable to access")})

    status = updates.check_tcc(updates.BETA)

    assert (status.newer, status.latest, status.reason) == (False, "", "no_network")


#: `conftest.py` stands in for `check_all` in every test, to keep the suite off the network; this
#: is the real one, captured at import, before any fixture runs.
_REAL_CHECK_ALL = updates.check_all


def test_check_all_hands_the_channel_to_tcc_and_not_to_the_method(monkeypatch):
    seen = []
    monkeypatch.setattr(updates, "check_tcc", lambda channel="stable": seen.append(channel) or "t")
    monkeypatch.setattr(updates, "check_skill", lambda: "s")

    assert _REAL_CHECK_ALL(updates.BETA) == ("t", "s")
    assert seen == ["beta"]


@pytest.mark.parametrize("saved, revision, expected", [
    ("", "", "stable"),
    ("", "v0.1.39", "stable"),
    ("", "beta-v0.2.0-rc1", "beta"),
    ("stable", "beta-v0.2.0-rc1", "stable"),
    ("beta", "", "beta"),
    ("nightly", "beta-v0.2.0-rc1", "stable"),
])
def test_the_channel_is_the_choice_else_what_the_app_was_installed_from(saved, revision, expected):
    assert updates.channel_for(saved, revision) == expected


def test_the_channel_setting_round_trips(monkeypatch):
    from autosound_tcc.core import config

    monkeypatch.setattr(install_report, "requested_revision", lambda: "")
    assert config.update_channel() == ""
    assert updates.current_channel() == "stable"

    config.set_update_channel("beta")

    assert config.update_channel() == "beta"
    assert updates.current_channel() == "beta"

