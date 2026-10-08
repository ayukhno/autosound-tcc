"""Is there a newer one, and is this installation ours to move.

Every test here fakes the two things that talk to the world — `git` and the installed metadata —
so the suite never asks GitHub anything. What is actually under test is the judgement: which
comparison decides "newer", and what stops the button touching somebody's own checkout.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from autosound_tcc.core import child, install_report, method_binding, updates
from tests import _hung_child


def _git_answers(monkeypatch, answers: dict):
    """Fake `git` by first argument (`ls-remote`, `symbolic-ref`, …) -> (ok, output)."""
    calls = []

    def fake(*args, cwd=None, timeout=None):
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


def test_a_method_candidate_ahead_of_the_newest_release_is_not_offered_it(monkeypatch, tmp_path):
    """Finding 144 (the Arbiter, Windows VM, 2026-10-03): the method installed at its candidate
    `beta-v3.1.0-rc3`, whose manifest says 3.1.0, read «a newer one is out: 3.0.66» with the button
    live — the commits differ, and that was all `newer` asked. 3.0.66 is OLDER, and pressing would
    have checked it out. Ahead of the newest release is said as such, and offered nothing; by
    number, so 3.0.10 is past 3.0.9 the way `test_ten_is_newer_than_nine` keeps it."""
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "_is_ours", lambda repo: (True, ("", "")))
    _git_answers(monkeypatch, {"ls-remote": (True, f"{_THERE}\trefs/tags/v3.0.66")})
    _skill_at(monkeypatch, _HERE, "3.1.0")

    status = updates.check_skill()

    assert (status.newer, status.reason) == (False, "ahead")
    assert (status.installed, status.latest) == ("3.1.0", "3.0.66"), "both numbers, for the row"

    _git_answers(monkeypatch, {"ls-remote": (True, f"{_THERE}\trefs/tags/v3.0.9")})
    _skill_at(monkeypatch, _HERE, "3.0.10")
    assert (updates.check_skill().newer, updates.check_skill().reason) == (False, "ahead"), (
        "a string compare would call 3.0.10 older than 3.0.9")

    _skill_at(monkeypatch, _HERE, "3.0.9")
    assert updates.check_skill().newer is True, "the same number, another commit: a newer build"
    _skill_at(monkeypatch, _HERE, "3.0.8")
    assert updates.check_skill().newer is True, "older is still offered the newest"


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
    import contextlib
    import json

    script = tmp_path / "upkeep.py"
    script.write_text("raise SystemExit('the fake is patched in; this never runs')\n")

    @contextlib.contextmanager
    def extracted(repo, tag):
        yield updates.Extracted(script, signature=f"{tag}: checked by TCC")

    monkeypatch.setattr(updates, "_upkeep_from_tag", extracted)
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


def test_the_method_is_never_moved_back_to_an_older_release(monkeypatch, tmp_path):
    """Finding 144, the press itself: from the candidate 3.1.0 «Update the method» went to the
    newest release, 3.0.66, and the skill's `clone` checks out whatever tag it is given. The row no
    longer offers it; `apply_skill` refuses it too — the default «newest», and a tag a row offered
    before the clone moved on under it — by the manifest of the clone it would move, before any
    step runs: nothing kept, nothing reset. The same release, or a newer one, still goes."""
    repo = _an_installed_clone(monkeypatch, tmp_path)
    (repo / ".claude-plugin").mkdir(parents=True)
    (repo / ".claude-plugin" / "plugin.json").write_text('{"version": "3.1.0"}', encoding="utf-8")
    _git_answers(monkeypatch, {"ls-remote": (True, f"{_THERE}\trefs/tags/v3.0.66")})
    calls = _fake_upkeep(monkeypatch, tmp_path, {"clone": (0, _CLONE_JSON), "libs": (0, _LIBS_JSON)})

    for done in (updates.apply_skill(), updates.apply_skill("v3.0.66", keep_local=True)):
        assert (done.ok, done.reason, done.detail) == (False, "ahead", "3.1.0 → v3.0.66")
    assert calls == [], "no step ran: nothing kept, nothing reset, nothing checked out"

    assert updates.apply_skill("v3.1.0").ok is True, "its own release goes"
    assert calls == [["clone", "--tag", "v3.1.0"], ["libs"]]


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


# ---- the NEW tag's upkeep.py, as the skill's installers run it (coordinator's ruling on #91) ----
#
# Real git, in throwaway repositories under `tmp_path` (HOME is there too, `conftest.py`): an
# "origin" with release tags, and an installed clone made the installer's way. The `upkeep.py` in
# the tags is a STUB that writes down how it was run and answers the contract's JSON — the real
# one would act on the clone, and what is under test is how TCC finds and runs it.

_STUB_UPKEEP = """\
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
skill = os.path.dirname(here)
beside = [p for p in ("rew_tool/gates/side_effect.py", "rew_tool/console.py", "requirements.txt")
          if os.path.isfile(os.path.join(skill, p))]
with open(os.environ["UPKEEP_STUB_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "file": os.path.abspath(__file__), "beside": beside,
                         "prompt": os.environ.get("GIT_TERMINAL_PROMPT"),
                         "bytecode": os.environ.get("PYTHONDONTWRITEBYTECODE")}) + "\\n")
command = sys.argv[sys.argv.index("--clone") + 2]
print(json.dumps({
    "status": {"clone": {"path": "c", "exists": True, "version": "v3.0.9", "changed": ["a.txt"]},
               "tools": [], "libs": {}},
    "keep-local": {"clone": "c", "changed": ["a.txt"], "version": "v3.0.9", "patch": "/kept/x.patch",
                   "sent": None, "reset": True},
    "clone": {"clone": "c", "from": "v3.0.9", "to": sys.argv[-1],
              "signature": os.environ.get("UPKEEP_STUB_SIGNATURE", "stub: checked")},
    "libs": {"python": "p", "command": "c", "ok": True, "before": {}, "after": {}, "why": ""},
}[command]))
"""


def _git_in(*args, cwd=None):
    import os
    import subprocess as sp

    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    done = sp.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    assert done.returncode == 0, (args, done.stdout, done.stderr)
    return done.stdout.strip()


def _skill_repos(monkeypatch, tmp_path):
    """origin: v3.0.9 (the installed clone's), v3.0.10 (no upkeep.py yet), v3.0.11 (with it).
    The clone: shallow at v3.0.9, a session's edit in it. Returns `(clone, log, temp root)`."""
    import os

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)  # the developer's own git config stays out
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(updates.tempfile, "tempdir", str(temp))
    log = tmp_path / "upkeep-runs.jsonl"
    monkeypatch.setenv("UPKEEP_STUB_LOG", str(log))
    origin = tmp_path / "origin"
    skill = origin / "skills" / "autosound-tuning"
    skill.mkdir(parents=True)
    _git_in("init", "-q", "-b", "main", str(origin))
    (origin / "a.txt").write_text("one\n")
    (skill / "SKILL.md").write_text("the method\n")
    _git_in("add", "-A", cwd=origin)
    _git_in("commit", "-q", "-m", "v3.0.9", cwd=origin)
    _git_in("tag", "-a", "v3.0.9", "-m", "v3.0.9", cwd=origin)
    (skill / "SKILL.md").write_text("the method, later\n")
    _git_in("commit", "-q", "-am", "v3.0.10", cwd=origin)
    _git_in("tag", "-a", "v3.0.10", "-m", "no upkeep.py yet", cwd=origin)
    _add_upkeep(origin)
    _git_in("tag", "-a", "v3.0.11", "-m", "upkeep.py arrives", cwd=origin)
    clone = tmp_path / "home" / ".claude" / "skills" / ".autosound-tuning-src"
    _git_in("-c", "advice.detachedHead=false", "clone", "-q", "--branch", "v3.0.9", "--depth", "1",
            f"file://{origin}", str(clone))
    (clone / "a.txt").write_text("one\na session's patch\n")
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: clone)
    return clone, log, temp


def _add_upkeep(origin):
    skill = origin / "skills" / "autosound-tuning"
    (skill / "scripts").mkdir(exist_ok=True)
    (skill / "rew_tool" / "gates").mkdir(parents=True, exist_ok=True)
    (skill / "scripts" / "upkeep.py").write_text(_STUB_UPKEEP)
    (skill / "rew_tool" / "gates" / "side_effect.py").write_text("# the feedback gate\n")
    (skill / "rew_tool" / "console.py").write_text("def install():\n    return False\n")
    (skill / "requirements.txt").write_text("numpy\nscipy\nmatplotlib\n")
    _git_in("add", "-A", cwd=origin)
    _git_in("commit", "-q", "-m", "upkeep.py", cwd=origin)


def _runs(log):
    import json

    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_an_old_clone_is_moved_by_the_new_tag_s_own_upkeep(monkeypatch, tmp_path):
    """The Arbiter's two machines: the VM's clone is 3.0.61 and the Mac's 3.0.63, and neither has
    `upkeep.py` — it arrived in 3.0.64. So TCC does what the skill's installers do (install.sh
    `keep_local`, install.ps1 `Save-LocalChanges`): fetch the target tag into the clone — objects
    and refs, the working tree untouched — take the NEW tag's `upkeep.py` and the files it imports
    into a temporary folder, and run THAT, with `--clone` naming the installed clone. The script is
    always as new as the skill being installed, and the folder is gone afterwards."""
    clone, log, temp = _skill_repos(monkeypatch, tmp_path)
    head = _git_in("rev-parse", "HEAD", cwd=clone)

    found = updates.local_changes("v3.0.11")
    done = updates.apply_skill("v3.0.11", keep_local=True)

    assert found.ok and found.changed == ("a.txt",), found
    assert done.ok and done.version == "v3.0.11" and done.patch == "/kept/x.patch", done
    runs = _runs(log)
    assert [run["argv"][3:] for run in runs] == [
        ["status"], ["keep-local"], ["clone", "--tag", "v3.0.11"], ["libs"]]
    for run in runs:
        assert run["argv"][:3] == ["--json", "--clone", str(clone)]
        assert run["file"].startswith(str(temp)), "the new tag's copy, not the clone's (it has none)"
        assert run["file"].replace("\\", "/").endswith("skills/autosound-tuning/scripts/upkeep.py")
        assert run["beside"] == ["rew_tool/gates/side_effect.py", "rew_tool/console.py",
                                 "requirements.txt"], "what it imports, and what `libs` reads"
        assert run["prompt"] == "0" and run["bytecode"] == "1"
    assert list(temp.iterdir()) == [], "the temporary copy is removed after each use"
    assert _git_in("rev-parse", "refs/tags/v3.0.11^{commit}", cwd=clone), "the tag was fetched"
    assert _git_in("rev-parse", "HEAD", cwd=clone) == head, "TCC itself moved nothing"
    assert "a session's patch" in (clone / "a.txt").read_text(), "nor reset anything"


def test_a_target_tag_without_upkeep_is_the_installer_s_job(monkeypatch, tmp_path):
    """A release from before `upkeep.py` has nothing TCC could run: one line on the row — update
    once with the skill's installer — and nothing touched. Never the old fetch-and-checkout."""
    clone, log, temp = _skill_repos(monkeypatch, tmp_path)
    head = _git_in("rev-parse", "HEAD", cwd=clone)

    found = updates.local_changes("v3.0.10")
    done = updates.apply_skill("v3.0.10", keep_local=True)

    assert found.reason == "no_upkeep" and done.reason == "no_upkeep" and not done.ok
    assert _runs(log) == []
    assert list(temp.iterdir()) == []
    assert _git_in("rev-parse", "HEAD", cwd=clone) == head
    assert "a session's patch" in (clone / "a.txt").read_text()


# ---- a method on a contract newer than this TCC (#170, G5 S2) ----------------------------------

def _tag_with_contract(origin, tag: str, text) -> None:
    """A release `tag` on top of origin's newest — `upkeep.py` included — whose
    `rew_tool/contract.py` holds `text`, bytes written as they are."""
    path = origin / "skills" / "autosound-tuning" / "rew_tool" / "contract.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    _git_in("add", "-A", cwd=origin)
    _git_in("commit", "-q", "-m", tag, cwd=origin)
    _git_in("tag", "-a", tag, "-m", tag, cwd=origin)


#: Syntax this interpreter does not know: `except` without parentheses is Python 3.14's (PEP 758).
_NEWER_SYNTAX = b"try:\n    pass\nexcept ValueError, TypeError:\n    pass\n"


@pytest.mark.parametrize("text, said", [
    pytest.param(b"CONTRACT_VERSION = 2\n", "CONTRACT_VERSION 2 > {known}", id="contract 2"),
    pytest.param(b"\xef\xbb\xbfCONTRACT_VERSION = 2\n", "CONTRACT_VERSION 2 > {known}",
                 id="contract 2 behind a BOM"),
    pytest.param(_NEWER_SYNTAX, "rew_tool/contract.py: ", id="3.14 syntax",
                 marks=pytest.mark.skipif(sys.version_info >= (3, 14),
                                          reason="3.14 parses its own syntax")),
    pytest.param(b"X = 1\n\x00\n", "rew_tool/contract.py: ", id="a NUL"),
    pytest.param(b"NAME = 'caf\xe9'\n", "rew_tool/contract.py: ",
                 id="a byte that is not UTF-8, in code"),
    pytest.param(b"\x00\xff\xfe not python", "rew_tool/contract.py: ", id="not source"),
    pytest.param(b"CONTRACT_VERSION = int('2')\n", "rew_tool/contract.py: CONTRACT_VERSION",
                 id="a number named, not a plain int (R-aw)"),
])
def test_a_method_this_tcc_cannot_drive_is_refused_before_anything_of_it_runs(monkeypatch, tmp_path,
                                                                              text, said):
    """#170: the skill names its CLI contract (`CONTRACT_VERSION` in `rew_tool/contract.py`), and
    this TCC drives the contracts up to `method_binding.KNOWN_CONTRACT`. A release on a newer one
    is refused at the press, the tag's signature checked first and nothing of it taken out: no
    `status`, no `keep-local`, no `clone`. So is one whose `contract.py` does not parse here — most
    likely a newer method, and read as «no number» it installed (R-ar). The session's patch and the
    clone's release stay as they were, and both steps of the press say the same: the tag, and the
    numbers or Python's words."""
    clone, log, temp = _skill_repos(monkeypatch, tmp_path)
    _tag_with_contract(tmp_path / "origin", "v3.0.12", text)
    head = _git_in("rev-parse", "HEAD", cwd=clone)

    found = updates.local_changes("v3.0.12")
    done = updates.apply_skill("v3.0.12", keep_local=True)

    assert (found.ok, found.reason) == (False, "newer_contract"), found
    assert (done.ok, done.reason) == (False, "newer_contract"), done
    assert found.detail == done.detail
    assert found.detail.startswith(
        "v3.0.12: " + said.format(known=method_binding.KNOWN_CONTRACT)), found.detail
    assert done.patch == "" and done.sent is None, "nothing was kept"
    assert _runs(log) == []
    assert list(temp.iterdir()) == []
    assert _git_in("rev-parse", "HEAD", cwd=clone) == head
    assert "a session's patch" in (clone / "a.txt").read_text()

    root = tmp_path / "taken-out"
    root.mkdir()
    got = updates._extract_upkeep(clone, "v3.0.12", root)
    assert (got.script, got.reason) == (None, "newer_contract")
    assert list(root.iterdir()) == [], "refused before the first file of the tag is copied out"


@pytest.mark.parametrize("text", [
    None,
    "v3.1.1",
    '"""The CLI contract."""\nSCHEMA = 3\n',
    f"CONTRACT_VERSION = {method_binding.KNOWN_CONTRACT}\n",
], ids=["no contract.py", "v3.1.1's contract.py", "no number", "the number this TCC drives"])
def test_a_method_that_names_no_newer_contract_installs_as_today(monkeypatch, tmp_path, text):
    """No number is not a newer one. Every v3 release has a `contract.py`, and up to v3.1.1 it
    names no number — v3.1.1's own is one of the rows here — so those install as they always did.
    So does a release on the contract this TCC drives, and a tag with no `contract.py` at all:
    there is no contract in it to hold to the number."""
    from autosound_tcc.core import vendor_loader

    clone, log, _temp = _skill_repos(monkeypatch, tmp_path)
    tag = "v3.0.11"  # upkeep.py, and no contract.py
    if text == "v3.1.1":
        shipped = vendor_loader._SUBMODULE_DIR / "rew_tool" / "contract.py"
        if not shipped.is_file():
            pytest.skip("the vendored method is not checked out (git submodule update --init)")
        text = shipped.read_bytes()
    if text is not None:
        tag = "v3.0.12"
        _tag_with_contract(tmp_path / "origin", tag, text)

    found = updates.local_changes(tag)
    done = updates.apply_skill(tag, keep_local=True)

    assert found.ok and found.changed == ("a.txt",), found
    assert done.ok and done.version == tag, done
    assert [run["argv"][3:] for run in _runs(log)] == [
        ["status"], ["keep-local"], ["clone", "--tag", tag], ["libs"]]


def _tag_with_contract_entry(origin, tag: str, mode: str, obj: str) -> None:
    """A release `tag` whose `rew_tool/contract.py` is a tree entry of `mode` naming `obj` — a
    symbolic link (120000, `obj` a blob of the link's text) or a gitlink (160000, `obj` a commit) —
    made with git's plumbing, so no link has to be made on the disk."""
    path = "skills/autosound-tuning/rew_tool/contract.py"
    _git_in("update-index", "--add", "--cacheinfo", f"{mode},{obj},{path}", cwd=origin)
    _git_in("commit", "-q", "-m", tag, cwd=origin)
    _git_in("tag", "-a", tag, "-m", tag, cwd=origin)


@pytest.mark.parametrize("entry, named", [("symlink", "a symbolic link"),
                                          ("gitlink", "a gitlink")])
def test_a_contract_that_is_no_file_in_the_tag_refuses_as_one_this_tcc_cannot_read(
        monkeypatch, tmp_path, entry, named):
    """M71, M72 (#170): `ls-tree` listed `rew_tool/contract.py`, and `show` then read whatever the
    entry was. A symbolic link read as its own text — no number — and the release installed, while
    the binding, on disk, would follow the link to the file it names (here on contract 2). A
    gitlink did not show, and refused as `read_failed` — «try again», the button on — every time.
    Only a file (git mode 100644 or 100755) is read now; any other entry refuses as a contract this
    TCC cannot read, before anything of the tag runs."""
    clone, log, temp = _skill_repos(monkeypatch, tmp_path)
    origin = tmp_path / "origin"
    if entry == "symlink":
        real = origin / "skills" / "autosound-tuning" / "rew_tool" / "contract_v2.py"
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text("CONTRACT_VERSION = 2\n", encoding="utf-8")
        _git_in("add", "-A", cwd=origin)
        text = tmp_path / "link-text"
        text.write_text("contract_v2.py", encoding="utf-8")
        _tag_with_contract_entry(origin, "v3.0.12", "120000",
                                 _git_in("hash-object", "-w", str(text), cwd=origin))
    else:
        _tag_with_contract_entry(origin, "v3.0.12", "160000",
                                 _git_in("rev-parse", "HEAD", cwd=origin))
    head = _git_in("rev-parse", "HEAD", cwd=clone)

    found = updates.local_changes("v3.0.12")
    done = updates.apply_skill("v3.0.12", keep_local=True)

    for answer in (found, done):
        assert (answer.ok, answer.reason) == (False, "newer_contract"), answer
        assert answer.detail.startswith("v3.0.12: rew_tool/contract.py: " + named), answer.detail
    assert _runs(log) == [] and list(temp.iterdir()) == []
    assert _git_in("rev-parse", "HEAD", cwd=clone) == head


@pytest.mark.parametrize("breaks", ["ls-tree", "show"])
def test_a_contract_git_could_not_read_refuses_until_it_is_tried_again(monkeypatch, tmp_path,
                                                                       breaks):
    """R-ar: a tag with no `contract.py` installs, so a read that failed must not pass for one.
    Whether git could not list the tag's file (`ls-tree`) or not show its bytes (`show`), the press
    refuses with a reason of its own — try again — in git's words, and nothing of the tag runs:
    here a release this TCC would have installed."""
    clone, log, temp = _skill_repos(monkeypatch, tmp_path)
    _tag_with_contract(tmp_path / "origin", "v3.0.12",
                       f"CONTRACT_VERSION = {method_binding.KNOWN_CONTRACT}\n")
    head = _git_in("rev-parse", "HEAD", cwd=clone)
    said = "fatal: unable to read 0123abcd"
    if breaks == "ls-tree":
        real_git = updates._git
        monkeypatch.setattr(updates, "_git", lambda *args, **kw: (
            (False, said) if "ls-tree" in args else real_git(*args, **kw)))
    else:
        real_show = updates._git_show
        monkeypatch.setattr(updates, "_git_show", lambda repo, spec: (
            (None, said) if spec.endswith("/rew_tool/contract.py") else real_show(repo, spec)))

    found = updates.local_changes("v3.0.12")
    done = updates.apply_skill("v3.0.12", keep_local=True)

    for answer in (found, done):
        assert (answer.ok, answer.reason, answer.detail) == (
            False, "read_failed", f"v3.0.12: {said}"), answer
    assert _runs(log) == [] and list(temp.iterdir()) == []
    assert _git_in("rev-parse", "HEAD", cwd=clone) == head
    assert "a session's patch" in (clone / "a.txt").read_text()


def test_a_release_whose_signature_does_not_check_out_runs_nothing(monkeypatch, tmp_path):
    """The installers verify the fetched tag BEFORE they run anything from it (install.sh:
    `verify_tag` before `keep_local`), and so does TCC: the script about to run comes from that
    tag, and a script that checks its own signature has checked nothing. v3.0.64 onwards are signed
    by the skill's author; an unsigned one is refused with git's own words."""
    clone, log, temp = _skill_repos(monkeypatch, tmp_path)
    origin = tmp_path / "origin"
    _git_in("tag", "-a", "v3.0.64", "-m", "unsigned", cwd=origin)

    done = updates.apply_skill("v3.0.64", keep_local=True)
    found = updates.local_changes("v3.0.64")

    assert done.reason == "bad_signature" and found.reason == "bad_signature", (done, found)
    assert "v3.0.64" in done.detail
    assert _runs(log) == [] and list(temp.iterdir()) == []
    assert "a session's patch" in (clone / "a.txt").read_text()


@pytest.mark.skipif(__import__("shutil").which("ssh-keygen") is None, reason="needs ssh-keygen")
def test_a_release_signed_by_the_author_s_key_runs_and_a_stranger_s_does_not(monkeypatch,
                                                                              tmp_path):
    """The trust anchor is a constant in TCC, the skill's own (`upkeep.py` SIGNING_KEY), never a
    file read from the tag being checked. Throwaway keys here, the constant pointed at one."""
    clone, log, temp = _skill_repos(monkeypatch, tmp_path)
    origin = tmp_path / "origin"
    keys = {}
    for who in ("author", "stranger"):
        path = tmp_path / who
        _git_in_keygen(path, who)
        keys[who] = " ".join((tmp_path / f"{who}.pub").read_text().split()[:2])
    for tag, who in (("v3.0.64", "author"), ("v3.0.65", "stranger")):
        _git_in("-c", "gpg.format=ssh", "-c", f"user.signingkey={tmp_path / who}.pub",
                "tag", "-s", tag, "-m", tag, cwd=origin)
    monkeypatch.setattr(updates, "SKILL_SIGNING_PRINCIPAL", "author")
    monkeypatch.setattr(updates, "SKILL_SIGNING_KEY", keys["author"])

    good = updates.apply_skill("v3.0.64")
    assert good.ok, good
    assert [run["argv"][3:] for run in _runs(log)] == [["clone", "--tag", "v3.0.64"], ["libs"]]

    log.unlink()
    foreign = updates.apply_skill("v3.0.65")
    assert foreign.reason == "bad_signature" and _runs(log) == []
    assert list(temp.iterdir()) == []


# ---- fix round 1: a git too old to check, and TCC's own signature line on the row ------------

@pytest.mark.parametrize("said, why", [
    # git before 2.34: `gpg.format=ssh` is not a value it knows
    ("error: unsupported value for gpg.format: ssh\nfatal: bad config variable 'gpg.format'",
     "git_too_old"),
    # an ssh-keygen without `-Y`
    ("unknown option -- Y\nusage: ssh-keygen [-q] [-b bits] [-C comment] [-f output_keyfile]",
     "openssh_too_old"),
    # git saying so itself
    ("error: ssh-keygen -Y find-principals/verify is needed for ssh signature verification "
     "(available in openssh version 8.2p1+)", "openssh_too_old"),
    # no ssh-keygen at all
    ("error: cannot run ssh-keygen: No such file or directory", "openssh_too_old"),
    # no ssh-keygen at all, in Git for Windows' words
    ("error: cannot spawn ssh-keygen: No such file or directory", "openssh_too_old"),
])
def test_a_git_too_old_to_check_is_not_called_a_bad_signature(monkeypatch, tmp_path, said, why):
    """install.sh v3.0.64 `verify_tag` matches `*gpg.format*|*"unknown option"*|*"-Y"*` and says
    "this git may be too old": a machine that cannot CHECK a signature is not a release whose
    signature is wrong. The VM, where git is older, is exactly where it would read as a forged
    release. Nothing is installed either way.

    And the advice names what is old (tcc#123, W-4 review): git reads `gpg.format`, OpenSSH's
    `ssh-keygen` does the checking. «Update git» to somebody whose ssh-keygen predates `-Y` sends
    them to update the one program that was fine."""
    _an_installed_clone(monkeypatch, tmp_path)
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)
    ran = []
    monkeypatch.setattr(updates, "_run_upkeep", lambda argv, timeout: ran.append(argv))
    monkeypatch.setattr(updates, "_git_blob", lambda repo, spec: pytest.fail("nothing extracted"))

    def fake_git(*args, cwd=None, timeout=None, extra_env=None):
        if "verify-tag" in args:
            return False, said
        if args == ("--version",):
            return True, "git version 2.30.1"
        return True, ""

    monkeypatch.setattr(updates, "_git", fake_git)

    done = updates.apply_skill("v3.0.64", keep_local=True)

    assert done.ok is False and done.reason == why, done
    assert "git version 2.30.1" in done.detail
    assert ran == []


def test_a_signature_that_is_simply_wrong_stays_a_bad_signature(monkeypatch, tmp_path):
    _an_installed_clone(monkeypatch, tmp_path)
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)
    monkeypatch.setattr(updates, "_git", lambda *args, cwd=None, timeout=None, extra_env=None: (
        (False, 'Could not verify signature.\nerror: no principal matched') if "verify-tag" in args
        else (True, "")))

    ok, line, reason = updates._verify_tag(tmp_path, "v3.0.64")

    assert (ok, reason) == (False, "bad_signature") and "no principal matched" in line


@pytest.mark.parametrize("said", [
    # a helper's words that carry the bare `-Y` of git's sentence
    "error: this signing helper does not verify: -Y find-principals",
    # the head of getopt's sentence, from somebody else
    "error: unknown option: -Y find-principals",
    # the config key git names, said by a helper rather than by git
    "hint: this helper signs for git with gpg.format=ssh; it does not verify",
])
def test_a_text_that_merely_carries_a_word_of_git_s_sentences_stays_a_bad_signature(
        monkeypatch, tmp_path, said):
    """T-35 (#174). The classifier matched tokens — a bare `-Y`, `unknown option`, `gpg.format` —
    so words like a signing helper's refusal read as a machine too old to check, and the row sent
    the person to update an OpenSSH or a git that was fine. Only git's own sentences say that."""
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)
    monkeypatch.setattr(updates, "_git", lambda *args, cwd=None, timeout=None, extra_env=None: (
        (False, said) if "verify-tag" in args else (True, "git version 2.51.0")))

    ok, line, reason = updates._verify_tag(tmp_path, "v3.0.64")

    assert (ok, reason) == (False, "bad_signature"), line
    assert line == f"v3.0.64: {said}", "in git's words, naming the tag"


def test_the_signature_is_checked_by_ssh_keygen_whatever_program_git_is_set_to(monkeypatch,
                                                                               tmp_path):
    """T-35 (#174). git checks an SSH signature with `gpg.ssh.program`, and a person who signs
    their own commits through a helper (1Password's) has it set to that helper: through it a good
    release was refused. The check pins git's own default on the command line, before the
    subcommand, where it outranks every config file."""
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)
    asked = []
    monkeypatch.setattr(updates, "_git", lambda *args, cwd=None, timeout=None, extra_env=None: (
        asked.append(args) or (True, 'Good "git" signature for ayukhno with ED25519 key SHA256:x')))

    ok, line, _why = updates._verify_tag(tmp_path, "v3.0.64")

    assert ok, line
    verify = next(args for args in asked if "verify-tag" in args)
    options = verify[:verify.index("verify-tag")]
    assert ("-c", "gpg.ssh.program=ssh-keygen") in zip(options, options[1:]), verify


def test_verify_tag_asks_git_for_english_messages_and_nothing_else_of_the_locale(monkeypatch,
                                                                                 tmp_path):
    """R-bd, R-bf (#174). `_CANNOT_CHECK` reads git's sentences, and git ships translations —
    Ukrainian among them, the language this app's people write. The verify-tag child gets
    `LC_MESSAGES=C`, and loses `LC_ALL`, which would override it, and `LANGUAGE`, which gettext
    reads before the locale. The rest of the locale stays the machine's, so a non-ASCII temp path
    is passed as before; `_NO_PROMPTING` is kept."""
    for name, value in (("LC_ALL", "uk_UA.UTF-8"), ("LANGUAGE", "uk"),
                        ("LC_MESSAGES", "uk_UA.UTF-8"), ("LC_CTYPE", "uk_UA.UTF-8")):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)
    seen = []

    def child_spy(argv, **kw):
        seen.append((argv, kw.get("env") or {}))
        return subprocess.CompletedProcess(argv, 0, stderr="", stdout=(
            'Good "git" signature for ayukhno with ED25519 key SHA256:x'))

    monkeypatch.setattr(updates.child, "run_bounded", child_spy)

    ok, line, _why = updates._verify_tag(tmp_path, "v3.0.64")

    assert ok, line
    env = next(env for argv, env in seen if "verify-tag" in argv)
    locale = {name: env[name] for name in ("LC_MESSAGES", "LC_ALL", "LANGUAGE", "LC_CTYPE")
              if name in env}
    assert locale == {"LC_MESSAGES": "C", "LC_CTYPE": "uk_UA.UTF-8"}, locale
    assert {key: env.get(key) for key in updates._NO_PROMPTING} == updates._NO_PROMPTING

    updates._git("--version")
    other = seen[-1][1]
    assert (other.get("LC_ALL"), other.get("LANGUAGE")) == ("uk_UA.UTF-8", "uk"), \
        "that call alone: any other keeps the machine's own"


def test_tcc_s_own_signature_line_reaches_the_row_when_upkeep_gives_none(monkeypatch, tmp_path):
    """HUB-032 asks for a VISIBLE line. The developer's switch and a release from before signing
    were said only in the log; the row showed upkeep's line or nothing."""
    clone, log, temp = _skill_repos(monkeypatch, tmp_path)
    monkeypatch.setenv("UPKEEP_STUB_SIGNATURE", "")

    before = updates.apply_skill("v3.0.11")
    assert before.ok and before.signature.startswith("v3.0.11 predates signed tags"), before

    _git_in("tag", "-a", "v3.0.64", "-m", "unsigned", cwd=tmp_path / "origin")
    monkeypatch.setenv(updates.SKIP_VERIFY_VAR, "1")
    skipped = updates.apply_skill("v3.0.64")
    assert skipped.ok and skipped.signature == (
        f"signature NOT checked: {updates.SKIP_VERIFY_VAR}=1 is set (a developer's switch)")

    monkeypatch.setenv("UPKEEP_STUB_SIGNATURE", "v3.0.64: upkeep's own line")
    assert updates.apply_skill("v3.0.64").signature == "v3.0.64: upkeep's own line", (
        "upkeep's line first when it gives one")


def _git_in_keygen(path, comment):
    import subprocess as sp

    sp.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(path)],
           check=True, capture_output=True)


def test_the_trust_anchor_is_the_skill_s_own():
    """Kept identical on purpose, like the installer constants above: read from the vendored
    `upkeep.py` by `ast`, so nothing of it is imported and no bytecode lands in the submodule."""
    import ast

    from autosound_tcc.core import vendor_loader

    script = vendor_loader.skill_dir() / "scripts" / "upkeep.py"
    if not script.is_file():
        pytest.skip("the method at this pin has no upkeep.py")
    theirs = {node.targets[0].id: node.value.value
              for node in ast.parse(script.read_text(encoding="utf-8")).body
              if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
              and isinstance(node.targets[0], ast.Name)}
    assert theirs["SIGNING_PRINCIPAL"] == updates.SKILL_SIGNING_PRINCIPAL
    assert theirs["SIGNING_KEY"] == updates.SKILL_SIGNING_KEY
    assert theirs["SIGNED_FROM"] == updates.SKILL_SIGNED_FROM
    assert theirs["SKIP_VERIFY_VAR"] == updates.SKIP_VERIFY_VAR


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
    monkeypatch.setattr(install_report, "requested_revision", lambda: "")
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda: "v0.1.11")

    status = updates.check_tcc()

    assert status.newer is False
    # Said as ahead since finding 144, with the release it is ahead of — not as «up to date».
    assert (status.installed, status.latest, status.reason) == ("0.1.12", "0.1.11", "ahead")


def test_a_tcc_candidate_is_its_own_release_and_not_offered_an_older_one(monkeypatch):
    """Finding 144, TCC's row. A candidate writes nothing (hub RELEASE-CHANNEL.md §11.3), so an
    app installed from `beta-v0.2.0-rc1` may still say 0.1.38 — and on stable, by that number,
    v0.1.45 read as newer, and the button would have installed it over the candidate. The tag it
    was installed AT names its release: beta-v0.2.0-rc1 is 0.2.0, ahead of 0.1.45. A candidate of
    the newest release itself is that release, up to date; and the beta box still offers the next
    candidate."""
    _tcc_installed(monkeypatch, "0.1.38", _RC1, "beta-v0.2.0-rc1")
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda channel="stable": "v0.1.45")

    status = updates.check_tcc()

    assert (status.newer, status.reason) == (False, "ahead")
    # Named as the release its tag names, since finding 150 (tcc#146).
    assert (status.installed, status.latest) == ("0.2.0 (beta-v0.2.0-rc1)", "0.1.45")

    _tcc_installed(monkeypatch, "0.1.45", _RC1, "beta-v0.1.45-rc2")
    assert (updates.check_tcc().newer, updates.check_tcc().reason) == (False, ""), (
        "the same release is up to date, not ahead")

    _tcc_installed(monkeypatch, "0.1.38", _RC1, "beta-v0.2.0-rc1")
    _tcc_tags(monkeypatch, f"{_RC1}\trefs/tags/beta-v0.2.0-rc1",
              f"{_RC2}\trefs/tags/beta-v0.2.0-rc2", f"{_HERE}\trefs/tags/v0.1.45")
    beta = updates.check_tcc(updates.BETA)
    assert (beta.newer, beta.latest) == (True, "0.2.0-rc2"), "beta still offers the next candidate"


def test_a_tcc_candidate_s_row_names_the_version_its_tag_names(monkeypatch):
    """Finding 150 (tcc#146): with beta-v1.1.0-rc1 installed, whose metadata still says 0.1.46 (a
    candidate is not bumped), the row read «TCC 0.1.46 (beta-v1.1.0-rc1) — newer than the latest
    release 0.1.46». The row names the release the install tag names — the reading the ahead check
    already makes (`_tcc_release`, finding 144) — on stable and on beta, and in the refusal of a
    stale press; a release, and a build not installed from a candidate, keep their version."""
    _tcc_installed(monkeypatch, "0.1.46", _RC1, "beta-v1.1.0-rc1")
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda channel="stable": "v0.1.46")

    status = updates.check_tcc()

    assert (status.installed, status.latest, status.reason) == (
        "1.1.0 (beta-v1.1.0-rc1)", "0.1.46", "ahead")
    assert updates.prepare_tcc_update(updates.STABLE).detail == "1.1.0 (beta-v1.1.0-rc1) → v0.1.46"

    _tcc_tags(monkeypatch, f"{_HERE}\trefs/tags/v0.1.46", f"{_RC1}\trefs/tags/beta-v1.1.0-rc1")
    assert updates.check_tcc(updates.BETA).installed == "1.1.0 (beta-v1.1.0-rc1)"

    _tcc_installed(monkeypatch, "1.1.1", _RC1, "beta-v1.1.1-rc1")
    assert updates.check_tcc(updates.BETA).installed == "1.1.1 (beta-v1.1.1-rc1)", (
        "a candidate already bumped says the same number")


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

    monkeypatch.setattr(subprocess, "Popen", boom)

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

    monkeypatch.setattr(updates.child, "run_bounded", fake_run)

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


def test_the_newest_tcc_tag_is_ranked_over_release_shaped_names_only(monkeypatch):
    """F10a (#174). `v*` lists every name that starts with a v, and `_version_key` ranked them
    all: `v1.2.0-wip` outranked `v1.1.1`, and the press, which takes a release name only, refused
    it as a bad signature. A name the press refuses is never the newest, on either channel."""
    _git_answers(monkeypatch, {"ls-remote": (True, "\n".join([
        f"{_HERE}\trefs/tags/v1.1.1",
        f"{_THERE}\trefs/tags/v1.2.0-wip",
        f"{'c' * 40}\trefs/tags/v1.1.1.1",
    ]))})

    assert updates.newest_tcc_tag() == "v1.1.1"
    assert updates.newest_tcc_tag(updates.BETA) == "v1.1.1"


def test_the_method_s_newest_tag_is_ranked_over_release_shaped_names_only(monkeypatch, tmp_path):
    """F10a's twin on the method's side (R-bc, #174): `v3.*` ranked by `_version_key` put a
    `v3.2.0-wip` above `v3.1.1`, and `_verify_tag`, which takes release names only, would refuse it
    as a bad signature. The press's question (`newest_tag`) and the row's (`check_skill`) both
    answer the release."""
    monkeypatch.setattr(updates, "_skill_repo_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "_is_ours", lambda repo: (True, ("", "")))
    _skill_at(monkeypatch, _HERE, "3.1.0")
    _git_answers(monkeypatch, {"ls-remote": (True, "\n".join([
        f"{_THERE}\trefs/tags/v3.1.1",
        f"{'c' * 40}\trefs/tags/v3.2.0-wip",
        f"{'d' * 40}\trefs/tags/v3.1.1.1",
    ]))})

    assert updates.newest_tag() == "v3.1.1"
    status = updates.check_skill()
    assert (status.latest, status.latest_sha) == ("3.1.1", _THERE)


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
    assert status.installed == "0.2.0 (beta-v0.2.0-rc1)", "the tag's release (finding 150)"
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

    assert status.newer is False
    # Said as ahead since finding 144, with the tag it is ahead of — not as «up to date».
    assert (status.installed, status.latest, status.reason) == ("0.2.1", "0.2.0", "ahead")


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



# ---- TCC's own tag, checked before the terminal gets it (tcc#102, hub #83 HUB-032) ------------
#
# `uv tool install … @<tag>` cannot check a signature, so TCC checks the tag first: the tag object
# fetched into a temporary bare repository, `git verify-tag` against a temporary signers file
# written from the constant (`core/signed_tags.py`), both gone afterwards. The skill's rules and
# the skill's function (`_verify_tag`), with TCC's anchor and TCC's first signed tag, v0.1.45.


def _tcc_origin(monkeypatch, tmp_path):
    """TCC's origin with a tag of every kind around v0.1.45, TCC's constant pointed at a throwaway
    `author` key (never the real one, never `~/.ssh`), and the temporary root watched.

    v0.1.44 lightweight, as every TCC tag before signing; v0.1.45 signed by the author; v0.1.46 by
    a stranger; v0.1.47 annotated, unsigned; v0.1.48 lightweight after signing began."""
    import os

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(updates.tempfile, "tempdir", str(temp))
    keys = {}
    for who in ("author", "stranger"):
        _git_in_keygen(tmp_path / who, who)
        keys[who] = " ".join((tmp_path / f"{who}.pub").read_text().split()[:2])
    origin = tmp_path / "tcc-origin"
    _git_in("init", "-q", "-b", "main", str(origin))
    (origin / "pyproject.toml").write_text('[project]\nname = "autosound-tcc"\n')
    _git_in("add", "-A", cwd=origin)
    _git_in("commit", "-q", "-m", "a release", cwd=origin)
    _git_in("tag", "v0.1.44", cwd=origin)
    for tag, who in (("v0.1.45", "author"), ("v0.1.46", "stranger")):
        _git_in("-c", "gpg.format=ssh", "-c", f"user.signingkey={tmp_path / who}.pub",
                "tag", "-s", tag, "-m", tag, cwd=origin)
    _git_in("tag", "-a", "v0.1.47", "-m", "unsigned", cwd=origin)
    _git_in("tag", "v0.1.48", cwd=origin)
    monkeypatch.setattr(updates, "TCC_REPO", f"file://{origin}")
    monkeypatch.setattr(updates, "TCC_SIGNING_PRINCIPAL", "author")
    monkeypatch.setattr(updates, "TCC_SIGNING_KEY", keys["author"])
    return temp


def _offering(monkeypatch, tag, installed: str = "0.1.40"):
    """`tag` is the newest on the channel, offered to a TCC at `installed` — pinned, because the
    press refuses a tag older than what is installed (review of finding 144, I1), and this tree's
    own version moves with every release."""
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda channel="stable": tag)
    monkeypatch.setattr(install_report, "app_version", lambda: installed)
    monkeypatch.setattr(install_report, "requested_revision", lambda: "")


def _left_in(temp):
    """What the update left in the temporary root: only the terminal's script folder, if any."""
    return sorted(path.name.split("-update-")[0] for path in temp.iterdir())


@pytest.mark.skipif(__import__("shutil").which("ssh-keygen") is None, reason="needs ssh-keygen")
def test_tcc_s_tag_signed_by_the_constant_s_key_passes_and_the_install_is_written(monkeypatch,
                                                                                  tmp_path):
    temp = _tcc_origin(monkeypatch, tmp_path)
    _offering(monkeypatch, "v0.1.45")

    ready = updates.prepare_tcc_update(pid=4242, platform="darwin")

    assert ready.script is not None and ready.reason == "", ready
    assert ready.signature == "v0.1.45: signature good (author)"
    script = ready.script.read_text(encoding="utf-8")
    assert "@v0.1.45" in script, "the tag that was checked"
    verified = _git_in("rev-parse", "v0.1.45^{commit}", cwd=tmp_path / "tcc-origin")
    assert verified in script, "and the commit it named, for the check right before uv"
    assert _left_in(temp) == ["autosound-tcc"], "the bare repository and the signers file are gone"


@pytest.mark.skipif(__import__("shutil").which("ssh-keygen") is None, reason="needs ssh-keygen")
@pytest.mark.parametrize("tag", ["v0.1.46", "v0.1.47", "v0.1.48"])
def test_tcc_s_tag_unsigned_or_by_a_stranger_installs_nothing(monkeypatch, tmp_path, tag):
    """A stranger's key, an annotated tag with no signature, a lightweight one after signing began:
    refused with a reason KEY, and no script is written, so no terminal opens and uv never runs."""
    temp = _tcc_origin(monkeypatch, tmp_path)
    _offering(monkeypatch, tag)

    ready = updates.prepare_tcc_update(pid=4242, platform="darwin")

    assert ready.script is None and ready.reason == "bad_signature", ready
    assert ready.detail.startswith(f"{tag}: "), "git's own words, naming the tag"
    assert list(temp.iterdir()) == [], "nothing written, and the temporaries removed"


@pytest.mark.skipif(__import__("shutil").which("ssh-keygen") is None, reason="needs ssh-keygen")
def test_a_tcc_tag_before_signing_passes_with_a_line_saying_so(monkeypatch, tmp_path):
    """Every TCC tag before v0.1.45 is lightweight and unsigned: it keeps updating, and says so."""
    temp = _tcc_origin(monkeypatch, tmp_path)
    _offering(monkeypatch, "v0.1.44")

    ready = updates.prepare_tcc_update(pid=4242, platform="darwin")

    assert ready.script is not None, ready
    assert ready.signature == ("v0.1.44 predates signed tags (they start at v0.1.45): installed "
                               "without a signature check")
    assert _left_in(temp) == ["autosound-tcc"]


@pytest.mark.skipif(__import__("shutil").which("ssh-keygen") is None, reason="needs ssh-keygen")
def test_a_signing_helper_in_the_person_s_git_config_does_not_refuse_a_good_release(monkeypatch,
                                                                                    tmp_path):
    """T-35 (#174), with real git: the person's own config points `gpg.ssh.program` at a helper
    that cannot check a signature — here one that is not there at all — and the release signed by
    the constant's key still verifies, because the check runs ssh-keygen."""
    temp = _tcc_origin(monkeypatch, tmp_path)
    own = tmp_path / "the-person-s-gitconfig"
    _git_in("config", "--file", str(own), "gpg.ssh.program", str(tmp_path / "signing-helper"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(own))
    _offering(monkeypatch, "v0.1.45")

    ready = updates.prepare_tcc_update(pid=4242, platform="darwin")

    assert ready.script is not None and ready.reason == "", ready
    assert ready.signature == "v0.1.45: signature good (author)"
    assert _left_in(temp) == ["autosound-tcc"]


@pytest.mark.skipif(__import__("shutil").which("ssh-keygen") is None, reason="needs ssh-keygen")
def test_the_developer_switch_skips_tcc_s_check_and_says_so(monkeypatch, tmp_path):
    _tcc_origin(monkeypatch, tmp_path)
    _offering(monkeypatch, "v0.1.46")
    monkeypatch.setenv(updates.SKIP_VERIFY_VAR, "1")

    ready = updates.prepare_tcc_update(pid=4242, platform="darwin")

    assert ready.script is not None, ready
    assert ready.signature == (
        f"signature NOT checked: {updates.SKIP_VERIFY_VAR}=1 is set (a developer's switch)")


def test_the_developer_switch_skips_the_signature_not_the_name_check(monkeypatch, tmp_path):
    """Final W-4 review (tcc#102): the switch returned before the name-shape check, so a remote tag
    of any name reached the install script's text unvalidated. The switch means "skip the
    signature"; a name `channel_key` rejects is still refused, and nothing is fetched or written."""
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(updates.tempfile, "tempdir", str(temp))
    monkeypatch.setenv(updates.SKIP_VERIFY_VAR, "1")
    odd = "v0.1.46-x"
    assert updates.channel_key(odd) is None
    _offering(monkeypatch, odd)
    ran = []
    monkeypatch.setattr(updates, "_git", lambda *args, cwd=None, timeout=None: (
        ran.append(args) or (True, "")))

    ready = updates.prepare_tcc_update(pid=4242, platform="darwin")

    assert ready.script is None and ready.reason == "bad_signature", ready
    assert "is not a release tag" in ready.detail, ready.detail
    assert ran == [], "decided by its name: nothing fetched"
    assert list(temp.iterdir()) == [], "no script written"
    ok, _line, why = updates._verify_tag(tmp_path, "v3.0.64-x")
    assert (ok, why) == (False, "bad_signature"), "the method's tags too"


@pytest.mark.parametrize("said, why", [
    ("error: unsupported value for gpg.format: ssh", "git_too_old"),
    ("error: cannot spawn ssh-keygen: No such file or directory", "openssh_too_old"),
])
def test_a_git_too_old_to_check_tcc_s_tag_installs_nothing(monkeypatch, tmp_path, said, why):
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(updates.tempfile, "tempdir", str(temp))
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)
    _offering(monkeypatch, "v0.1.45")

    def fake_git(*args, cwd=None, timeout=None, extra_env=None):
        if "verify-tag" in args:
            return False, said
        if args == ("--version",):
            return True, "git version 2.30.1.windows.1"
        return True, ""

    monkeypatch.setattr(updates, "_git", fake_git)

    ready = updates.prepare_tcc_update(pid=4242, platform="win32")

    assert ready.script is None and ready.reason == why, ready
    assert "git version 2.30.1" in ready.detail
    assert list(temp.iterdir()) == []


def test_a_tcc_tag_that_cannot_be_fetched_installs_nothing(monkeypatch, tmp_path):
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(updates.tempfile, "tempdir", str(temp))
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)
    _offering(monkeypatch, "v0.1.45")
    monkeypatch.setattr(updates, "_git", lambda *args, cwd=None, timeout=None: (
        (False, "fatal: unable to access 'https://github.com/…': Could not resolve host")
        if "fetch" in args else (True, "")))

    ready = updates.prepare_tcc_update(pid=4242, platform="darwin")

    assert ready.script is None and ready.reason == "fetch_failed", ready
    assert "Could not resolve host" in ready.detail
    assert list(temp.iterdir()) == []


def test_no_tag_to_check_installs_nothing_rather_than_the_default_branch(monkeypatch, tmp_path):
    """Without a tag the old command installs `main` as it stands — which no signature covers."""
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(updates.tempfile, "tempdir", str(temp))
    _offering(monkeypatch, "")
    monkeypatch.setattr(updates, "last_probe_error", lambda: "Could not resolve host")

    ready = updates.prepare_tcc_update(pid=4242, platform="darwin")

    assert ready.script is None and ready.reason == "probe_failed"
    assert ready.detail == "Could not resolve host"
    assert list(temp.iterdir()) == []


def test_the_update_log_gets_the_check_s_result(monkeypatch, tmp_path):
    """HUB-032's closing evidence: a line of the update log with the result of the check."""
    monkeypatch.setattr(updates.tempfile, "tempdir", str(tmp_path))
    _offering(monkeypatch, "v0.1.44")
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)
    said = []

    class Log:
        def info(self, text, *args):
            said.append(text % args)

        warning = info

    monkeypatch.setattr(updates, "_log", Log())

    updates.prepare_tcc_update(pid=4242, platform="darwin")

    assert said == ["tcc tag v0.1.44: v0.1.44 predates signed tags (they start at v0.1.45): "
                    "installed without a signature check"]


def test_a_stale_update_tcc_press_does_not_install_an_older_release(monkeypatch, tmp_path):
    """Review of finding 144, I1: the press resolves the newest tag again when it runs, so a row
    gone stale — a second project window after the beta box was unticked in another, a candidate
    installed from a terminal while TCC ran — kept «Update TCC» live, and the press wrote the
    install of an OLDER release over the candidate. Refused as `ahead`, the row's own rule, before
    anything is fetched or written."""
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(updates.tempfile, "tempdir", str(temp))
    _tcc_installed(monkeypatch, "0.1.38", _RC1, "beta-v0.2.0-rc1")
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda channel="stable": "v0.1.45")
    ran = []
    monkeypatch.setattr(updates, "_git", lambda *args, cwd=None, timeout=None: (
        ran.append(args) or (True, "")))

    ready = updates.prepare_tcc_update(updates.STABLE, pid=4242, platform="darwin")

    assert (ready.script, ready.reason, ready.tag) == (None, "ahead", "v0.1.45"), ready
    assert ready.detail == "0.2.0 (beta-v0.2.0-rc1) → v0.1.45"
    assert ran == [], "nothing fetched"
    assert list(temp.iterdir()) == [], "no script written"


def test_a_beta_candidate_of_tcc_is_ordered_on_its_channel_not_refused_as_no_release(monkeypatch):
    """`make ship CANDIDATE=` signs its tag too (one `publish`), so a candidate after v0.1.45 is
    checked like a release — not refused for not being named vX.Y.Z."""
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)
    fetched = []
    monkeypatch.setattr(updates, "_git", lambda *args, cwd=None, timeout=None, extra_env=None: (
        fetched.append(args) or ((True, "c" * 40) if "rev-parse" in args else
                                 (True, 'Good "git" signature for ayukhno with ED25519 key SHA256:x'))))

    ok, line, why, sha = updates.check_tcc_tag("beta-v0.2.0-rc1")

    assert (ok, why, sha) == (True, "", "c" * 40), line
    assert any("fetch" in args for args in fetched), "checked, not passed by its name"


def test_tcc_s_anchor_is_the_one_in_signed_tags():
    """One definition each: the skip switch too, which task 9 had defined here as well."""
    from autosound_tcc.core import signed_tags

    assert updates.TCC_SIGNING_KEY == signed_tags.TCC_SIGNING_KEY
    assert updates.TCC_SIGNED_FROM == signed_tags.TCC_SIGNED_FROM == "v0.1.45"
    assert updates.SKIP_VERIFY_VAR is signed_tags.SKIP_VERIFY_VAR


# ---- fix round 1: the tag checked again right before uv; a candidate of v0.1.45 is checked -----
#
# `check_tcc_tag` verifies the tag object when the button is pressed, and `uv` resolves the NAME
# only after the person has quit TCC — an unbounded wait. So the script asks, right before uv,
# whether the tag still names the commit that was verified, and installs nothing if it does not
# (review of tcc#102). Pinning uv to the sha instead was ruled out: the tag name is what
# `requested_revision` reads back (the shown version, the channel, the guide link).

_VERIFIED = "c" * 40
_MOVED_WORDS = {**_WORDS, "moved": "Тег змінився після перевірки — нічого не встановлено. "
                                   "Натисни «Оновити» ще раз."}


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_the_script_checks_the_tag_still_names_the_verified_commit_before_uv(platform):
    script = updates.tcc_install_script(pid=1, tag="v0.1.46", words=_MOVED_WORDS,
                                        platform=platform, sha=_VERIFIED)

    guard = script.index("ls-remote")
    assert _VERIFIED in script and "refs/tags/v0.1.46^{}" in script
    assert script.index(_WORDS["wait"]) < guard < script.index(_WORDS["updating"]), \
        "after TCC has closed, before the line that says it is updating"
    assert guard < script.index("uv tool install")
    assert _MOVED_WORDS["moved"] in script, "the person's line, in the person's language"
    unchecked = updates.tcc_install_script(pid=1, tag="v0.1.44", words=_MOVED_WORDS,
                                           platform=platform)
    assert "ls-remote" not in unchecked, "nothing was verified, so there is nothing to hold it to"


def _moving_remote(tmp_path):
    """A bare "remote" with `v0.1.46` annotated on one commit; returns `(remote, work, commit)`."""
    work, remote = tmp_path / "work", tmp_path / "remote.git"
    _git_in("init", "-q", "-b", "main", str(work))
    (work / "a.txt").write_text("one\n")
    _git_in("add", "-A", cwd=work)
    _git_in("commit", "-q", "-m", "checked", cwd=work)
    _git_in("tag", "-a", "v0.1.46", "-m", "checked", cwd=work)
    _git_in("init", "-q", "--bare", str(remote))
    _git_in("push", "-q", str(remote), "main", "v0.1.46", cwd=work)
    return remote, work, _git_in("rev-parse", "v0.1.46^{commit}", cwd=work)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="runs the macOS script with sh")
@pytest.mark.parametrize("moved", [False, True], ids=["unmoved", "moved"])
def test_a_tag_moved_after_the_check_is_not_installed(monkeypatch, tmp_path, moved):
    """Run for real with `/bin/sh`: a fake `uv` that leaves a mark, a process already gone, and a
    remote whose tag is force-moved AFTER the script was written from the verified commit."""
    import os
    import shutil
    import subprocess as sp

    remote, work, verified = _moving_remote(tmp_path)
    monkeypatch.setattr(updates, "TCC_REPO", f"file://{remote}")
    mark = tmp_path / "uv-ran"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "uv").write_text(f"#!/bin/sh\necho ran > '{mark}'\n"
                               "echo 'Installed 1 executable: autosound-tcc'\n")
    (bindir / "uv").chmod(0o755)
    gone = sp.Popen(["true"])
    gone.wait()
    folder = tmp_path / "script"
    folder.mkdir()
    path = updates.write_tcc_install_script(pid=gone.pid, tag="v0.1.46", words=_MOVED_WORDS,
                                            folder=folder, platform="darwin", sha=verified)
    if moved:
        (work / "a.txt").write_text("two\n")
        _git_in("commit", "-q", "-am", "not what was checked", cwd=work)
        _git_in("tag", "-f", "-a", "v0.1.46", "-m", "moved", cwd=work)
        _git_in("push", "-q", "--force", str(remote), "refs/tags/v0.1.46", cwd=work)

    git_dir = os.path.dirname(shutil.which("git"))
    out = sp.run(["/bin/sh", str(path)], capture_output=True, text=True, encoding="utf-8",
                 env={**os.environ, "PATH": f"{bindir}:{git_dir}:/usr/bin:/bin"},
                 timeout=30).stdout

    if moved:
        assert not mark.exists(), "uv never ran"
        assert _MOVED_WORDS["moved"] in out and _WORDS["updating"] not in out, out
    else:
        assert mark.exists(), "the tag the check verified is installed"
        assert out.rstrip().endswith(_WORDS["done"]), out
    for command in ("ls-remote", "git ", "printf", verified):
        assert command not in out, f"{command!r} reached the window"


# ---- tcc#123: the guard cannot wait for a password or a silent server; the folder goes after ------


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_the_guard_closes_every_door_git_could_stop_at(platform):
    """W-4 review of tcc#102: the guard set `GIT_TERMINAL_PROMPT` alone. Git Credential Manager's
    window is a door of its own (`GCM_INTERACTIVE`), and a server that stops answering holds the
    window on «waiting for TCC» with nothing on screen. The doors are the update check's own
    (`_NO_PROMPTING`); the wait is bounded on each system by what it can rely on."""
    script = updates.tcc_install_script(pid=1, tag="v0.1.46", words=_MOVED_WORDS,
                                        platform=platform, sha=_VERIFIED)
    guard = script[script.index(_WORDS["wait"]):script.index(_WORDS["updating"])]

    if platform == "darwin":
        assert "GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never GIT_ASKPASS='' git ls-remote" in guard
        assert f"-lt {updates._GUARD_TIMEOUT_S} ]" in guard, "a deadline, not a hope"
        assert "timeout " not in guard, "macOS has no `timeout` to rely on"
        kills = [line.strip() for line in guard.splitlines() if 'kill "$ask"' in line]
        assert kills == [f'if [ "$waited" -ge {updates._GUARD_TIMEOUT_S} ]; then '
                         f'kill "$ask" 2>/dev/null; fi'], "a git that answered is not killed"
    else:
        for line in ("set GIT_TERMINAL_PROMPT=0", "set GCM_INTERACTIVE=never",
                     'set "GIT_ASKPASS="', "set GIT_HTTP_LOW_SPEED_LIMIT=1000",
                     f"set GIT_HTTP_LOW_SPEED_TIME={updates._GUARD_TIMEOUT_S}"):
            assert line in guard.splitlines(), line
        assert guard.index("GCM_INTERACTIVE") < guard.index("ls-remote")


def _fake_bin(tmp_path, git: str):
    """A `bin` with a `uv` that leaves a mark and the `git` given; returns `(bindir, mark)`."""
    mark = tmp_path / "uv-ran"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "uv").write_text(f"#!/bin/sh\necho ran > '{mark}'\n"
                               "echo 'Installed 1 executable: autosound-tcc'\n")
    (bindir / "git").write_text("#!/bin/sh\n" + git)
    for tool in ("uv", "git"):
        (bindir / tool).chmod(0o755)
    return bindir, mark


def _gone_pid() -> int:
    gone = subprocess.Popen(["true"])
    gone.wait()
    return gone.pid


@pytest.mark.skipif(sys.platform.startswith("win"), reason="runs the macOS script with sh")
@pytest.mark.parametrize("shape", ["given folder", "its own folder"])
def test_a_server_that_never_answers_ends_in_the_moved_line_not_a_wait(monkeypatch, tmp_path,
                                                                      shape):
    """Run for real with `/bin/sh` and a `git` that never answers: the script stops asking at its
    deadline and says the server did not answer, and uv never runs. The `git` it ran had every
    prompting door closed. In the shape TCC writes it too -- its own folder, its EXIT trap -- and
    that folder is gone after (review of tcc#123)."""
    import os
    import time

    seen = tmp_path / "git-env"
    bindir, mark = _fake_bin(tmp_path, f"echo \"$GIT_TERMINAL_PROMPT $GCM_INTERACTIVE "
                                       f"[${{GIT_ASKPASS-unset}}]\" > '{seen}'\nexec sleep 600\n")
    monkeypatch.setattr(updates, "_GUARD_TIMEOUT_S", 2)
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(updates.tempfile, "tempdir", str(temp))
    folder = tmp_path / "script"
    folder.mkdir()
    path = updates.write_tcc_install_script(pid=_gone_pid(), tag="v0.1.46", words=_MOVED_WORDS,
                                            folder=folder if shape == "given folder" else None,
                                            platform="darwin", sha=_VERIFIED)

    started = time.monotonic()
    out = subprocess.run(["/bin/sh", str(path)], capture_output=True, text=True,
                         encoding="utf-8", env={**os.environ, "PATH": f"{bindir}:/usr/bin:/bin"},
                         timeout=30).stdout

    assert time.monotonic() - started < 15, "the deadline held"
    assert _MOVED_WORDS["moved"] in out and _WORDS["updating"] not in out, out
    assert not mark.exists(), "uv never ran"
    assert seen.read_text().split() == ["0", "never", "[]"]
    assert list(temp.iterdir()) == [], "its own folder went with it"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="runs the macOS script with sh")
@pytest.mark.parametrize("answer", ["", "d" * 40], ids=["installed", "moved"])
def test_the_update_s_own_folder_is_gone_when_its_script_ends(monkeypatch, tmp_path, answer):
    """W-4 review of tcc#102: every press left an `autosound-tcc-update-*` folder in the temp
    directory, for good -- the script is run after TCC has quit, so nobody was left to remove
    it. The script removes its own folder as it ends, however it ends. Run for real with `/bin/sh`."""
    import os

    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(updates.tempfile, "tempdir", str(temp))
    bindir, mark = _fake_bin(tmp_path, f"printf '%s\\trefs/tags/v0.1.46^{{}}\\n' "
                                       f"'{answer or _VERIFIED}'\n")
    path = updates.write_tcc_install_script(pid=_gone_pid(), tag="v0.1.46", words=_MOVED_WORDS,
                                            platform="darwin", sha=_VERIFIED)
    assert path.parent.parent == temp

    out = subprocess.run(["/bin/sh", str(path)], capture_output=True, text=True,
                         encoding="utf-8", env={**os.environ, "PATH": f"{bindir}:/usr/bin:/bin"},
                         timeout=30).stdout

    assert mark.exists() is (not answer), out
    assert list(temp.iterdir()) == [], "the folder and everything in it went with the script"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="runs the macOS script with sh")
@pytest.mark.parametrize("shell", ["/bin/sh", "/bin/dash"])
def test_a_window_closed_while_it_waits_still_takes_the_folder(monkeypatch, tmp_path, shell):
    """Closing the window sends the script SIGHUP. bash runs an EXIT trap on it, dash does not
    (review of tcc#123): HUP, INT and TERM end the script, and the end takes the folder."""
    import os
    import shutil
    import signal

    if not shutil.which(shell):
        pytest.skip(f"no {shell} here")
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(updates.tempfile, "tempdir", str(temp))
    tcc = subprocess.Popen(["sleep", "60"])  # TCC, still open: the script waits for it
    try:
        path = updates.write_tcc_install_script(pid=tcc.pid, tag="v0.1.46", words=_MOVED_WORDS,
                                                platform="darwin", sha=_VERIFIED)
        script = subprocess.Popen([shell, str(path)], stdout=subprocess.PIPE, text=True,
                                  encoding="utf-8", env={**os.environ, "PATH": "/usr/bin:/bin"})
        for line in script.stdout:  # its traps are set by the time it says this
            if _WORDS["wait"] in line:
                break
        script.send_signal(signal.SIGHUP)
        script.wait(timeout=10)
        script.stdout.close()
    finally:
        tcc.kill()
        tcc.wait()

    assert list(temp.iterdir()) == [], "the folder went with the window"


@pytest.mark.parametrize("platform", ["darwin", "win32"])
@pytest.mark.parametrize("folder", ["", "autosound-tcc-update-x", "/tmp/somebody-else-s"],
                         ids=["empty", "relative", "not-ours"])
def test_a_folder_that_is_not_the_update_s_own_is_never_removed(platform, folder):
    """The script removes `folder` as it ends; on Windows after `cd /d "%TEMP%"`, so an empty one
    -- `Path("")`, which reads `.` -- would have emptied the temp directory (review of tcc#123).
    Only an absolute path whose name is the one `write_tcc_install_script` gives is taken."""
    from pathlib import Path

    with pytest.raises(ValueError, match="not the update's own folder"):
        updates.tcc_install_script(pid=1, tag="v0.1.46", platform=platform, sha=_VERIFIED,
                                   folder=Path(folder))
    ours = Path("/tmp/autosound-tcc-update-x1y2").resolve()
    assert str(ours) in updates.tcc_install_script(pid=1, tag="v0.1.46", platform=platform,
                                                   sha=_VERIFIED, folder=ours)


def test_the_windows_update_removes_its_folder_after_its_last_line(monkeypatch, tmp_path):
    """The same on Windows, where cmd reads a batch file line by line while it runs it: deleting
    it from inside stops the script with «The batch file cannot be found». So every exit goes
    to one last line, and that line leaves the batch first (`(goto)`), moves the window out of
    the folder it was started in, and removes the folder. A folder the caller gave is the
    caller's, and stays."""
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(updates.tempfile, "tempdir", str(temp))
    path = updates.write_tcc_install_script(pid=4242, tag="v0.1.46", words=_MOVED_WORDS,
                                            platform="win32", sha=_VERIFIED)
    lines = path.read_bytes().decode("utf-8").split("\r\n")

    assert lines[-1] == "", "the file ends with its line break"
    assert lines[-3:-1] == [":end", f'(goto) 2>nul & cd /d "%TEMP%" & rmdir /s /q "{path.parent}"']
    assert "goto :eof" not in lines, "no exit around the last line"
    assert [line for line in lines if line.startswith("goto ")] == ["goto end", "goto end"]

    given = tmp_path / "given"
    given.mkdir()
    kept = updates.write_tcc_install_script(pid=4242, tag="v0.1.46", words=_MOVED_WORDS,
                                            folder=given, platform="win32", sha=_VERIFIED)
    assert "rmdir" not in kept.read_text(encoding="utf-8")


def test_a_candidate_of_the_first_signed_version_is_checked_one_before_it_predates(monkeypatch):
    """Candidates sort below their release on the channel, so `beta-v0.1.45-rc1` read as older
    than v0.1.45 and passed unverified — while `make ship CANDIDATE=` signs it. The version
    triple decides "predates", not the channel order."""
    monkeypatch.delenv(updates.SKIP_VERIFY_VAR, raising=False)

    assert updates._verdict_by_name("beta-v0.1.45-rc1", "v0.1.45", updates.channel_key) is None
    ok, line, why = updates._verdict_by_name("beta-v0.1.44-rc1", "v0.1.45", updates.channel_key)
    assert ok and why == "" and "predates signed tags" in line
    assert updates._verdict_by_name("v0.1.45", "v0.1.45", updates.channel_key) is None


# ---- omp, agy, gh and Claude Code: the skill's `upkeep.py status` / `tools` (tcc#98, hub #219) --
#
# The vendored skill's `upkeep.py` is a stub file here and its run is faked (`_run_upkeep`): the
# real `tools` would update this machine's own omp, gh and Claude Code.

#: `conftest.py` stands in for both in every test — the status asks Homebrew and GitHub, and an
#: update must never reach the developer's own tools; these are the real ones, captured at import.
_REAL_TOOLS_STATUS = updates.tools_status
_REAL_UPDATE_TOOLS = updates.update_tools

#: `status` as hub #219's contract comment prints it.
_TOOLS_STATUS_JSON = {
    "clone": {"path": "/h/.claude/skills/.autosound-tuning-src", "exists": True,
              "version": "v3.0.63", "changed": ["skills/autosound-tuning/rew_tool/contract.py"]},
    "tools": [{"name": "omp", "path": "/opt/homebrew/bin/omp", "how": "brew", "package": "omp",
               "installed": "17.2.9", "available": "18.4.3", "updatable": True}],
    "libs": {"python": "/usr/bin/python3",
             "installed": {"numpy": "2.0.2", "scipy": "1.13.1", "matplotlib": "3.9.4"}},
}


def _vendored_upkeep(monkeypatch, tmp_path, answer, code=0):
    """The skill TCC runs on, with an `upkeep.py` in it whose run is faked. Returns the script and
    the `(argv, timeout)` of every run."""
    import json

    from autosound_tcc.core import vendor_loader

    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    script = skill / "scripts" / "upkeep.py"
    script.write_text("raise SystemExit('the fake is patched in; this never runs')\n")
    monkeypatch.setattr(vendor_loader, "skill_dir", lambda: skill)
    seen = []

    def fake(argv, timeout):
        seen.append((argv, timeout))
        return code, answer if isinstance(answer, str) else json.dumps(answer), ""

    monkeypatch.setattr(updates, "_run_upkeep", fake)
    return script, seen


def test_the_tools_status_of_hub_219_is_read_into_one_row_per_tool(monkeypatch, tmp_path):
    """The contract's own example: omp from Homebrew, 17.2.9 here and 18.4.3 out. Run from the
    skill TCC runs on, on TCC's interpreter, `--json` before the command and no `--clone` — the
    clone half of the answer is the method row's business."""
    from autosound_tcc.core import child

    script, seen = _vendored_upkeep(monkeypatch, tmp_path, _TOOLS_STATUS_JSON)

    found = _REAL_TOOLS_STATUS()

    assert found.ok is True
    assert found.tools == (updates.Tool("omp", "17.2.9", "18.4.3", True),)
    assert found.tools[0].newer and found.tools[0].offered
    argv, timeout = seen[0]
    assert argv == [child.script_interpreter(), str(script), "--json", "status"]
    assert timeout >= 60, "up to about a minute, by the contract"


def test_an_empty_available_reads_unknown_never_up_to_date(monkeypatch, tmp_path):
    """`available: ""` is a source that cannot say without installing (agy, a native Claude Code):
    unknown, so the button is offered. Equal versions are current; `other` is left alone."""
    rows = [
        {"name": "claude", "how": "npm", "installed": "2.1.286", "available": "2.1.286",
         "updatable": True},
        {"name": "agy", "how": "self", "installed": "1.2.14", "available": "", "updatable": True},
        {"name": "gh", "how": "other", "installed": "2.92.0", "available": "", "updatable": False},
    ]
    _vendored_upkeep(monkeypatch, tmp_path, {**_TOOLS_STATUS_JSON, "tools": rows})

    claude, agy, gh = _REAL_TOOLS_STATUS().tools

    assert agy.available == "" and not agy.newer and agy.offered, "unknown is not up to date"
    assert not claude.newer and not claude.offered, "the same version: nothing to offer"
    assert not gh.offered, "installed some other way: not TCC's to update"


def test_only_what_is_present_gets_a_row(monkeypatch, tmp_path):
    _vendored_upkeep(monkeypatch, tmp_path, {**_TOOLS_STATUS_JSON, "tools": []})

    found = _REAL_TOOLS_STATUS()

    assert found.ok is True and found.tools == ()


def test_a_status_that_does_not_answer_says_why_in_its_own_words(monkeypatch, tmp_path):
    _vendored_upkeep(monkeypatch, tmp_path, "Traceback …\nOSError: disk full", code=1)

    found = _REAL_TOOLS_STATUS()

    assert found.ok is False and found.reason == "upkeep_failed"
    assert "disk full" in found.detail


def test_a_method_older_than_its_updater_says_so_and_runs_nothing(monkeypatch, tmp_path):
    """`upkeep.py` arrived in v3.0.64; a clone from before it has nothing to ask."""
    from autosound_tcc.core import vendor_loader

    monkeypatch.setattr(vendor_loader, "skill_dir", lambda: tmp_path / "old-skill")
    monkeypatch.setattr(updates, "_run_upkeep",
                        lambda argv, timeout: pytest.fail("there is no script to run"))

    assert _REAL_TOOLS_STATUS().reason == "no_upkeep_here"
    assert _REAL_UPDATE_TOOLS(["omp"]).reason == "no_upkeep_here"


def test_updating_runs_tools_with_only_the_names_pressed(monkeypatch, tmp_path):
    from autosound_tcc.core import child

    answer = [{"name": "omp", "how": "brew", "old": "17.2.9", "new": "18.4.3", "ok": True,
               "command": "/opt/homebrew/bin/brew upgrade omp"}]
    script, seen = _vendored_upkeep(monkeypatch, tmp_path, answer)

    done = _REAL_UPDATE_TOOLS(["omp"])

    argv, _timeout = seen[0]
    assert argv == [child.script_interpreter(), str(script), "--json", "tools", "--only", "omp"]
    assert done.reason == ""
    assert done.rows == (updates.ToolUpdate("omp", True, "17.2.9", "18.4.3"),)


def test_a_tool_that_did_not_update_says_why_and_the_others_still_come_back(monkeypatch,
                                                                            tmp_path):
    """Exit 3 when any row is not `ok` — and the list is still printed: one failed update leaves
    that tool as it was, says why, and hides nothing of the rest."""
    answer = [
        {"name": "omp", "how": "brew", "old": "17.2.9", "new": "17.2.9", "ok": False,
         "why": "Error: omp: Permission denied @ rb_sysopen", "command": "brew upgrade omp"},
        {"name": "gh", "how": "release", "old": "2.92.0", "new": "2.101.0", "ok": True},
    ]
    _script, seen = _vendored_upkeep(monkeypatch, tmp_path, answer, code=3)

    done = _REAL_UPDATE_TOOLS(["omp", "gh"])

    assert seen[0][0][-4:] == ["--only", "omp", "--only", "gh"]
    omp, gh = done.rows
    assert omp == updates.ToolUpdate("omp", False, "17.2.9", "17.2.9",
                                     "Error: omp: Permission denied @ rb_sysopen")
    assert gh.ok and gh.new == "2.101.0"


def test_no_names_updates_nothing(monkeypatch, tmp_path):
    """`tools` with no `--only` updates EVERY tool present — so an empty list never reaches it."""
    _script, seen = _vendored_upkeep(monkeypatch, tmp_path, [])

    done = _REAL_UPDATE_TOOLS([])

    assert seen == [] and done.rows == ()


def test_an_update_that_does_not_answer_says_why(monkeypatch, tmp_path):
    _vendored_upkeep(monkeypatch, tmp_path, "", code=-1)
    monkeypatch.setattr(updates, "_run_upkeep",
                        lambda argv, timeout: (-1, "", "TimeoutExpired: no answer in 960 s"))

    done = _REAL_UPDATE_TOOLS(["omp"])

    assert done.rows == () and done.reason == "upkeep_failed"
    assert "TimeoutExpired" in done.detail


def test_a_name_the_skill_does_not_know_is_its_usage_error_in_its_own_words(monkeypatch,
                                                                            tmp_path):
    """argparse refuses an `--only` outside `TOOLS`: exit 2, usage on stderr, no JSON at all."""
    said = ("upkeep.py tools: error: argument --only: invalid choice: 'uv' "
            "(choose from 'claude', 'omp', 'agy', 'gh')")
    _vendored_upkeep(monkeypatch, tmp_path, [])
    monkeypatch.setattr(updates, "_run_upkeep",
                        lambda argv, timeout: (2, "", f"usage: upkeep.py tools [-h]\n{said}\n"))

    done = _REAL_UPDATE_TOOLS(["uv"])

    assert done == updates.ToolsUpdate((), "upkeep_failed", said)


# ---- a git that never answers (review of #132, I3) -----------------------------------------------
#
# git runs https as a child of its own, `git-remote-https`, and the helper inherits git's stderr:
# TCC's pipe. At the timeout `subprocess.run` killed git alone and then, on Windows, waited with no
# bound for the helper to let go -- on a stalled link, curl's own minutes.


def test_a_git_that_never_answers_is_killed_with_its_https_helper(monkeypatch, tmp_path):
    spawns = _hung_child.install(monkeypatch)

    ok, said = updates._git("ls-remote", "--tags", "https://example.invalid/x.git")
    blob = updates._git_blob(tmp_path, "v0.1.46:upkeep.py")

    assert not ok and said.startswith("TimeoutExpired") and blob is None
    assert [git.args[:2] for git in spawns.hung] == [["git", "ls-remote"], ["git", "-C"]]
    for git in spawns.hung:
        assert git.killed and git.timeouts == [updates._ASK_TIMEOUT, child.REAP_TIMEOUT_S]
    assert [kill[-1] for kill in spawns.taskkills] == [str(git.pid) for git in spawns.hung]


def test_the_tcc_rows_check_ends_when_git_never_answers(monkeypatch):
    """«Оновити TCC» runs this on a thread and the row polls it with no cap on its tries
    (`diagnostics_panel._poll_tcc_job`): the row said «checking the tag…», its button grey, for as
    long as git hung. Bounded, the step ends, and the row has git's reason to say."""
    spawns = _hung_child.install(monkeypatch)

    ready = updates.prepare_tcc_update(updates.STABLE)

    assert ready.script is None and ready.reason == "probe_failed"
    assert "TimeoutExpired" in ready.detail
    assert spawns.hung and all(git.killed for git in spawns.hung)


def test_an_upkeep_run_that_never_answers_is_bounded_on_windows(monkeypatch):
    """F16-1: `_run_upkeep` was one of three children left on `subprocess.run` (tcc#132)."""
    spawns = _hung_child.install(monkeypatch)

    code, out, err = updates._run_upkeep(["python", "upkeep.py", "--json", "libs"], timeout=1)

    assert code == -1 and out == "" and err.startswith("TimeoutExpired")
    assert spawns.hung and all(child.killed for child in spawns.hung)
