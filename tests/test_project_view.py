"""Reading the skill's `project.json` into the left panel's System/Project-params shapes
(state/project_view.py, SCR-015/016). No vendored submodule needed -- this is plain JSON reading,
except the channel map `load_channels` takes from the method (#126, hub #233), tested both ways.
"""

from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from autosound_tcc.state import project_view


def _write(project_dir, data):
    (project_dir / "project.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def unhurried_git(monkeypatch):
    """The product's bound on each git child, raised for a test that runs real git and is not about
    the bound (the group review, W6): `_GIT_TIMEOUT_S` is 2 s, and on a loaded runner a child cut
    short reads as other facts or another child count -- not a product bug. What holds the bound
    holds it by name (`_bounded`), so it holds either way; the probe's test keeps the 2 s."""
    monkeypatch.setattr(project_view, "_GIT_TIMEOUT_S", 30.0)


def test_no_project_json_reads_as_empty_everywhere(tmp_path):
    assert project_view.has_project(tmp_path) is False
    assert project_view.load_system_params(tmp_path) == ()
    assert project_view.load_channel_summary(tmp_path) == ()
    assert project_view.load_open_questions(tmp_path) == ()


def test_system_params_only_renders_facts_actually_present(tmp_path):
    _write(tmp_path, {
        "dsp": {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"},
        "amps": [{"role": "front", "make": "Helix", "model": "P Six DSP"}, {"role": "sub"}],
        "mic": {"model": "UMIK-1"},
        "source": {},
    })
    rows = project_view.load_system_params(tmp_path)
    assert ("DSP", "Audiotec-Fischer Helix DSP Ultra S") in rows
    assert ("Amp (front)", "Helix P Six DSP") in rows
    assert ("Mic", "UMIK-1") in rows
    # an amp with no make/model, and an empty source block, contribute no row -- not blank ones.
    assert not any(label == "Amp (sub)" for label, _ in rows)
    assert not any(label == "Source" for label, _ in rows)


def test_channel_summary_renders_total_and_off(tmp_path):
    _write(tmp_path, {
        "channel_summary": {
            "virtual_channels": {"total": 8, "off": 1},
            "channels": {"total": 12, "off": 0},
        }
    })
    # Tier ids and counts, not sentences: the words are the panel's to translate (F-006).
    rows = {tier: (total, off) for tier, total, off in
            project_view.load_channel_summary(tmp_path)}
    assert rows["virtual_channels"] == (8, 1)
    assert rows["channels"] == (12, 0)


def test_open_questions_passthrough(tmp_path):
    _write(tmp_path, {"_open_questions": ["mic.calibration_file", "amps.0.gain_db"]})
    assert project_view.load_open_questions(tmp_path) == (
        "mic.calibration_file", "amps.0.gain_db",
    )


def test_has_project_true_once_the_file_exists(tmp_path):
    _write(tmp_path, {})
    assert project_view.has_project(tmp_path) is True


def test_load_channels_keys_by_code_and_skips_entries_without_one(tmp_path):
    """`code` is the join key (SCR-001) — an entry without one cannot be matched to a ledger row,
    and guessing would attach a driver to the wrong channel."""
    _write(tmp_path, {"channels": [
        {"code": "w-L", "driver": {"make": "Audiofrog", "model": "GB25"}},
        {"slot": "D", "descr": "no code here"},
    ]})

    channels = project_view.load_channels(tmp_path)

    assert set(channels) == {"w-L"}
    assert channels["w-L"]["driver"]["model"] == "GB25"


def test_load_channels_reaches_one_channel_by_id_current_name_and_old_name(tmp_path):
    """SCR-039: the ledger's row key is the channel's id, which snapshots keep forever, while
    `code` is what it is called today. Both, plus every retired name, must land on one entry —
    otherwise a rename turns a channel TCC has full identity for into an unknown row."""
    _write(tmp_path, {"channels": [
        {"code": "w-L", "id": "m-L", "previous_names": ["m-L"], "slot": "C", "descr": "Front L"},
        {"code": "tw-L", "slot": "D"},
    ]})

    channels = project_view.load_channels(tmp_path)

    assert channels["m-L"] is channels["w-L"], "id and current name are one channel"
    assert project_view.channel_name(channels["m-L"]) == "w-L", "the label is today's name"
    assert set(channels) == {"m-L", "w-L", "tw-L"}


def test_load_channels_lets_a_live_code_win_over_another_channels_history(tmp_path):
    """A name handed on belongs to whoever holds it now, whatever the row order says. The skill
    refuses to write this shape (`project.py.validate`), so it only arrives hand-edited — and row
    order deciding identity is the kind of bug that shows up as one wrong driver."""
    _write(tmp_path, {"channels": [
        {"code": "w-L", "previous_names": ["m-L"], "descr": "the woofer"},
        {"code": "m-L", "descr": "a genuinely new mid"},
    ]})

    channels = project_view.load_channels(tmp_path)

    assert channels["m-L"]["descr"] == "a genuinely new mid"


def test_load_channels_reaches_a_channel_by_its_name_in_the_one_notation(tmp_path):
    """#126 (#112's review, Minor 4): from the method's v3.0.65 a channel with no ledger row yet
    gets one under the hyphen (`apply._row_key`, S-079), so a channel whose code and id are both
    `w_L` is banked as `w-L` — a name none of its own is, and the rig drew it as a second row with
    no identity. Since v3.0.66 only a driver's side is read that way (hub #232): `sw_f` is banked
    as itself, and no `sw-f` is made up for it. Needs the vendored method; without it the literal
    names stand, as before."""
    _write(tmp_path, {"channels": [
        {"code": "w_L", "slot": "C"},
        {"code": "sw_f", "slot": "A"},
    ]})

    channels = project_view.load_channels(tmp_path)

    assert channels["w-L"] is channels["w_L"]
    assert project_view.channel_name(channels["w-L"]) == "w_L", "the label is the code as written"
    assert set(channels) == {"w_L", "w-L", "sw_f"}


def test_load_channels_with_no_method_keeps_the_literal_names(tmp_path, monkeypatch):
    from autosound_tcc.core import vendor_loader

    def missing():
        raise vendor_loader.VendorNotInitializedError("no skill here")

    # No method at all: neither its channel map (hub #233) nor its notation can be asked.
    monkeypatch.setattr(vendor_loader, "load_dsp_state", missing)
    monkeypatch.setattr(vendor_loader, "load_naming", missing)
    _write(tmp_path, {"channels": [{"code": "w_L", "slot": "C"}]})

    assert set(project_view.load_channels(tmp_path)) == {"w_L"}


def test_load_channels_never_lets_the_one_notation_take_an_exact_name(tmp_path):
    """The one notation fills a gap and nothing more: a name some channel holds as written stays
    that channel's. The method refuses this file (`project.py.validate`: a previous name that reads
    as another channel's live code), so it only arrives hand-edited."""
    _write(tmp_path, {"channels": [
        {"code": "w-L", "descr": "the woofer"},
        {"code": "m-L", "previous_names": ["w_L"], "descr": "the mid"},
    ]})

    channels = project_view.load_channels(tmp_path)

    assert channels["w-L"]["descr"] == "the woofer"
    assert channels["w_L"]["descr"] == "the mid"


def test_load_channels_tolerates_a_missing_or_malformed_key(tmp_path):
    _write(tmp_path, {})
    assert project_view.load_channels(tmp_path) == {}

    _write(tmp_path, {"channels": {"w-L": {}}})  # object where the schema says list
    assert project_view.load_channels(tmp_path) == {}


def test_fact_value_unwraps_wrapped_and_passes_bare_through():
    """`fs_hz` is wrapped, `role` is not; a reader must not have to know which (project-schema.md
    Provenance)."""
    assert project_view.fact_value({"value": 62, "source": "datasheet", "at": "…"}) == 62
    assert project_view.fact_value("woofer") == "woofer"
    assert project_view.fact_value({"value": None, "source": None, "at": None}) is None
    # A plain dict that is NOT a fact wrapper survives intact -- `driver` is one of those.
    assert project_view.fact_value({"make": "Audiofrog"}) == {"make": "Audiofrog"}


def test_driver_label_joins_make_and_model_and_tolerates_older_shapes():
    assert project_view.driver_label({"driver": {"make": "Audiofrog", "model": "GB25"}}) == "Audiofrog GB25"
    assert project_view.driver_label({"driver": {"model": "GB25"}}) == "GB25"
    assert project_view.driver_label({"driver": "Hertz MP70"}) == "Hertz MP70"
    assert project_view.driver_label({}) is None
    assert project_view.driver_label({"driver": {}}) is None


# ---- the DSP is known before `project.json` exists --------------------------


def _profile(project_dir, **fields):
    (project_dir / "dsp_profile.json").write_text(
        json.dumps({"schema_version": 3, "dsp_profile": fields}), encoding="utf-8"
    )


def test_the_dsp_shows_from_the_profile_before_project_json_exists(tmp_path):
    """`project.json` arrives late — the intake asks about the car and the drivers first — while
    `dsp_profile.json` is finalised as soon as the DSP is named. A panel that shows nothing while
    that sits on disk reads as a session that did nothing."""
    _profile(tmp_path, vendor="Audiotec-Fischer", name="Helix DSP Ultra S")

    assert project_view.load_system_params(tmp_path) == (("DSP", "Audiotec-Fischer Helix DSP Ultra S"),)


def test_project_json_wins_over_the_profile(tmp_path):
    """Two sources for one fact: the project's own file is the later, fuller one."""
    _profile(tmp_path, vendor="Audiotec-Fischer", name="Helix DSP Ultra S")
    (tmp_path / "project.json").write_text(
        json.dumps({"dsp": {"vendor": "Musway", "model": "D8V3"}}), encoding="utf-8"
    )

    assert project_view.load_system_params(tmp_path)[0] == ("DSP", "Musway D8V3")


def test_an_unfinished_profile_is_not_a_dsp_name(tmp_path):
    """`check_existing_profile` starts the draft with "unknown" placeholders; showing them as a
    fact would be worse than showing nothing."""
    _profile(tmp_path, vendor="unknown", name="unknown")

    assert project_view.load_system_params(tmp_path) == ()


def test_a_broken_profile_is_not_an_exception(tmp_path):
    (tmp_path / "dsp_profile.json").write_text("{ truncated", encoding="utf-8")

    assert project_view.load_system_params(tmp_path) == ()


def test_git_facts_are_shown_for_a_repo_and_silent_for_anything_else(tmp_path, unhurried_git):
    """The skill makes a project a git repo on purpose — the tune's history is the point. Folders
    that are not repos say nothing: "not a git repo" would be noise on every one of them."""
    import subprocess

    from autosound_tcc.state import project_view

    assert project_view.git_facts(tmp_path) == ()

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "note.md").write_text("hi")

    rows = dict(project_view.git_facts(tmp_path))

    assert "Git" in rows                       # a branch name
    assert rows["Git changes"] == "1"          # the untracked file


def test_git_facts_never_raise_on_a_broken_repo(tmp_path):
    """A missing `git`, a repo mid-rebase, a slow mount — all resolve to "say nothing" rather than
    to a stall or a traceback in a panel."""
    from autosound_tcc.state import project_view

    (tmp_path / ".git").write_text("not a repo, just a file called .git")

    assert project_view.git_facts(tmp_path) == ()


def test_the_car_is_one_line_and_the_generation_is_not_said_twice(tmp_path):
    """Projects written before `save_car` folded the generation into the nameplate
    (`"model": "Passat B8"`), and joining the parts blindly reads `VW Passat B8 B8` (tcc#11)."""
    _write(tmp_path, {"car": {"make": "VW", "model": "Passat B8", "generation": "B8",
                              "body": "sedan", "year": 2019}})

    line, missing = project_view.load_car(tmp_path)

    assert line == "VW Passat B8 sedan · 2019"
    assert missing == ()


def test_a_body_nobody_recorded_comes_back_as_a_gap_not_as_a_blank(tmp_path):
    """`save_car` calls it a silent loss: nothing breaks today, and the material is not there
    tomorrow. The panel can only say so if the loader says which part is missing."""
    _write(tmp_path, {"car": {"make": "VW", "model": "Passat", "generation": "B8"}})

    line, missing = project_view.load_car(tmp_path)

    assert line == "VW Passat B8"
    assert missing == ("body",)


def test_no_car_block_at_all_is_its_own_answer(tmp_path):
    _write(tmp_path, {"dsp": {"vendor": "Musway", "model": "M6V4"}})

    assert project_view.load_car(tmp_path) == ("", project_view.CAR_PARTS)


def test_open_questions_keyed_by_file_match_a_steps_covers(tmp_path, monkeypatch):
    """Method `SKL-047` (hub #189): a step's `covers` entries are `<file>:<dotted.path>`, and the
    intake's open questions are keyed by the same paths — so the two can be compared without
    inventing a normalisation.

    `load_open_questions` above answers for `project.json` alone and drops the file, which is
    right for the onboarding chips it feeds. The plan panel needs BOTH files and the prefix, so it
    can say which of a step's facts are still open.
    """
    import json

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    (tmp_path / "project.json").write_text(json.dumps(
        {"_open_questions": ["sources.sweep_input", "amps.front.gain_db"]}), encoding="utf-8")
    (tmp_path / "dsp_profile.json").write_text(json.dumps(
        {"_open_questions": ["eq.bands_total"]}), encoding="utf-8")

    assert project_view.open_questions_by_file(tmp_path) == frozenset({
        "project.json:sources.sweep_input",
        "project.json:amps.front.gain_db",
        "dsp_profile.json:eq.bands_total",
    })


def test_open_questions_by_file_is_empty_when_there_is_no_project(tmp_path, monkeypatch):
    """A project with neither file answers "nothing open", not an exception: the panel asks this
    on every render, including before intake has written anything."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))

    assert project_view.open_questions_by_file(tmp_path) == frozenset()


def test_git_status_says_whether_history_is_kept_and_backed_up(tmp_path, unhurried_git):
    """The Arbiter's live project had no repository — no history, no backup — and TCC said nothing
    (F-074). He asked to see whether there is a repository and whether there is git at all."""
    import subprocess

    from autosound_tcc.state import project_view

    project = tmp_path / "car"
    project.mkdir()
    assert project_view.git_status(project).level == "bad"
    assert not project_view.git_status(project).repo

    subprocess.run(["git", "init", "-q", str(project)], check=True)
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(project), "config", key, value], check=True)
    (project / "note.md").write_text("hi")
    subprocess.run(["git", "-C", str(project), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "first"], check=True)
    state = project_view.git_status(project)
    assert state.repo and not state.remote and state.level == "wait", "kept, not backed up"

    backup = tmp_path / "backup.git"
    subprocess.run(["git", "init", "-q", "--bare", str(backup)], check=True)
    subprocess.run(["git", "-C", str(project), "remote", "add", "origin", str(backup)], check=True)
    subprocess.run(["git", "-C", str(project), "push", "-q", "-u", "origin", "HEAD"], check=True)
    assert project_view.git_status(project).level == "done"

    (project / "note.md").write_text("more")
    subprocess.run(["git", "-C", str(project), "commit", "-qam", "second"], check=True)
    state = project_view.git_status(project)
    assert state.unpushed == 1 and state.level == "wait", "one commit the backup does not have"


def test_git_that_does_not_run_is_said_so(tmp_path, monkeypatch):
    from autosound_tcc.state import project_view

    monkeypatch.setattr(project_view.shutil, "which", lambda name: None)
    state = project_view.git_status(tmp_path)
    assert not state.works and state.level == "bad"


def test_a_remote_is_named_the_way_a_person_reads_it():
    from autosound_tcc.state import project_view

    assert project_view._remote_label("git@github.com:ayukhno/EPY.git") == "github.com/ayukhno/EPY"
    assert project_view._remote_label("https://github.com/ayukhno/EPY") == "github.com/ayukhno/EPY"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def _repo(project, commit: bool = True):
    """A project folder under git on a branch named `tune`, with one commit unless `commit` is
    False — a project's whole first session."""
    project.mkdir(exist_ok=True)
    _git("init", "-q", str(project))
    _git("-C", str(project), "symbolic-ref", "HEAD", "refs/heads/tune")
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        _git("-C", str(project), "config", key, value)
    if commit:
        (project / "note.md").write_text("hi")
        _git("-C", str(project), "add", "-A")
        _git("-C", str(project), "commit", "-qm", "first")
    return project


def _backup(tmp_path, project, name: str = "origin", upstream: bool = True) -> str:
    """A bare folder next to the project as its remote `name`, pushed to with an upstream unless
    `upstream` is False; what the panel calls it. Nothing leaves the machine."""
    backup = tmp_path / f"{name}.git"
    _git("init", "-q", "--bare", str(backup))
    _git("-C", str(project), "remote", "add", name, str(backup))
    if upstream:
        _git("-C", str(project), "push", "-q", "-u", name, "HEAD")
    return project_view._remote_label(str(backup))


def _bounded(argv, kwargs) -> None:
    """A child `project_view` starts carries its time bound, by the module's name for it: the
    reload's children run on the GUI thread (#172), and one with no bound waits as long as a
    stalled network folder or a cloud placeholder being fetched does (the group review, G4)."""
    assert kwargs.get("timeout") == project_view._GIT_TIMEOUT_S, \
        f"{list(argv)} started without the {project_view._GIT_TIMEOUT_S} s bound: {kwargs}"


def _children(monkeypatch) -> list:
    """The argv of every child started from here on: `project_view` has one door,
    `subprocess.run`, and so has its probe. Each child `project_view` starts is held to its bound
    here (`_bounded`), so every test that counts children holds the bound too, as the osascript
    spy does in `test_terminal_launcher.py`."""
    started, run = [], subprocess.run

    def spy(argv, *args, **kwargs):
        if sys._getframe(1).f_globals.get("__name__") == project_view.__name__:
            _bounded(argv, kwargs)
        started.append(list(argv) if isinstance(argv, (list, tuple)) else [argv])
        return run(argv, *args, **kwargs)

    monkeypatch.setattr(project_view.subprocess, "run", spy)
    return started


def _ahead(tmp_path):
    project = _repo(tmp_path / "car")
    remote = _backup(tmp_path, project)
    (project / "note.md").write_text("more")
    _git("-C", str(project), "commit", "-qam", "second")
    (project / "draft.md").write_text("x")
    return project, dict(branch="tune", changed=1, remote=remote, unpushed=1)


def _detached(tmp_path):
    project = _repo(tmp_path / "car")
    remote = _backup(tmp_path, project)
    (project / "note.md").write_text("more")
    _git("-C", str(project), "commit", "-qam", "second")
    _git("-C", str(project), "checkout", "-q", "--detach", "HEAD~1")
    # The old `rev-parse --short HEAD`: git's own length, seven digits in a repository this small.
    head = _git("-C", str(project), "rev-parse", "HEAD")[:7]
    return project, dict(branch=head, changed=0, remote=remote, unpushed=None)


def _no_upstream(tmp_path):
    project = _repo(tmp_path / "car")
    remote = _backup(tmp_path, project, upstream=False)
    return project, dict(branch="tune", changed=0, remote=remote, unpushed=None)


def _no_remote(tmp_path):
    project = _repo(tmp_path / "car")
    (project / "draft.md").write_text("x")
    return project, dict(branch="tune", changed=1, remote="", unpushed=None)


def _another_name(tmp_path):
    """No `origin`: the first remote by name is the backup, as `git remote`'s first line was."""
    project = _repo(tmp_path / "car")
    remote = _backup(tmp_path, project, name="backup")
    _backup(tmp_path, project, name="mirror", upstream=False)
    (project / "note.md").write_text("more")
    _git("-C", str(project), "commit", "-qam", "second")
    return project, dict(branch="tune", changed=0, remote=remote, unpushed=1)


def _no_commits(tmp_path):
    project = _repo(tmp_path / "car", commit=False)
    (project / "note.md").write_text("hi")
    return project, dict(branch="tune", changed=1, remote="", unpushed=None)


@pytest.mark.parametrize("shape", [_ahead, _detached, _no_upstream, _no_remote, _another_name,
                                   _no_commits],
                         ids=["branch, dirty, ahead, remote", "detached", "no upstream",
                              "no remote", "no origin", "no commits yet"])
def test_a_reload_asks_git_twice_and_hears_the_same_facts(tmp_path, monkeypatch, shape,
                                                           unhurried_git):
    """#172: a reload's `git_status` started seven children on a Mac with `/usr/bin/git` — the
    probe, a `rev-parse` the `.git` check had answered, one call per fact — on the GUI thread; a
    detached head and a remote not named `origin` cost more. Two now: `status --porcelain=v2
    --branch` and `remote -v`. Counted once the probe is remembered (R-q): it runs once per
    process and `git` path, so the call before the count primes it, and only a process's first
    reload pays it. Each shape's facts are what the old calls answered on it (recorded at
    0a7cc94), and they are checked before the count."""
    project, today = shape(tmp_path)
    project_view._git_works()  # primes the probe: once per process and `git` path
    started = _children(monkeypatch)

    state = project_view.git_status(project)

    assert state == project_view.GitStatus(works=True, repo=True, **today)
    assert len(started) <= 2, started


def test_reuse_answers_the_folders_last_read_and_asks_git_nothing(tmp_path, monkeypatch,
                                                                  unhurried_git):
    """The five window actions that are not about git — the reviewer, the Generator, the effort,
    the gate, the language — re-say the panel, and each paid the whole read (#172). `reuse=True`
    answers the folder's last read with no child; a folder not read yet is read."""
    project, _ = _ahead(tmp_path)
    other = _repo(tmp_path / "other")
    read = project_view.git_status(project)
    started = _children(monkeypatch)

    assert project_view.git_status(project, reuse=True) == read
    assert started == [], "the folder was read: nothing to ask"
    assert project_view.git_status(other, reuse=True).branch == "tune"
    assert started, "a folder not read yet is read"


def test_git_is_asked_whether_it_runs_until_it_does(tmp_path, monkeypatch):
    """The probe — `xcode-select -p` and `git --version` on a Mac — ran on every reload (#172). A
    yes is kept for the process and that `git`; a no is asked again, so the Command Line Tools
    installed as the panel's tip says are seen on the next reload, not after a restart."""
    asked = []

    def git(project, *args):
        asked.append(args)
        return None if len(asked) == 1 else "git version 2.50.1"

    monkeypatch.setattr(project_view.shutil, "which", lambda name: str(tmp_path / "bin" / "git"))
    monkeypatch.setattr(project_view, "_git", git)
    monkeypatch.setattr(project_view, "_git_runs", set())

    assert not project_view._git_works()
    assert project_view._git_works(), "installed since the no"
    assert project_view._git_works()
    assert asked == [("--version",), ("--version",)], "a yes is kept: no third question"


def _corrupt_index(project) -> None:
    """`git status` then exits 128 («index file smaller than expected») while `remote -v` and
    `rev-list` still answer: neither needs the index."""
    (project / ".git" / "index").write_bytes(b"not an index")


def test_a_status_git_cannot_give_still_counts_what_the_backup_lacks(tmp_path, monkeypatch,
                                                                     unhurried_git):
    """Review of #172, I-1: the count of commits the backup lacks came from `git status`, so a
    status that failed — a corrupt index, the 2 s bound on a slow folder, a broken submodule, a
    git older than porcelain v2 — left it None, and None read as «backed up» with one commit not
    pushed. A failed status now has it counted the old way, by `rev-list`, which needs no index: a
    third child, on that path only."""
    project, _ = _ahead(tmp_path)
    _corrupt_index(project)
    project_view._git_works()  # primes the probe: once per process and `git` path
    started = _children(monkeypatch)

    state = project_view.git_status(project)

    assert state.changed is None, "the status failed: this is the path under test"
    assert (state.unpushed, state.level) == (1, "wait"), "one commit is not backed up"
    assert [argv[3:] for argv in started][2:] == [["rev-list", "--count", "@{u}..HEAD"]]


@pytest.mark.parametrize("cut, read", [(("status",), (1, "wait", True)),
                                       (("status", "rev-list"), (None, "wait", False))],
                         ids=["status", "status and rev-list"])
def test_a_child_cut_short_by_its_bound_is_never_read_as_backed_up(tmp_path, monkeypatch, cut,
                                                                   read, unhurried_git):
    """G4: I-1 names «the 2 s bound on a slow folder» among the ways the status fails, and only a
    corrupt index stood in for it. Here the bound itself: the children named run past it and are
    cut, as `subprocess.run` cuts one (`TimeoutExpired`). What the backup lacks is then counted by
    `rev-list`; with that cut too it is unknown, and unknown is never «backed up»."""
    project, _ = _ahead(tmp_path)
    project_view._git_works()  # primes the probe: once per process and `git` path
    run = subprocess.run

    def past_the_bound(argv, *args, **kwargs):
        _bounded(argv, kwargs)
        if argv[3] in cut:  # git -C <folder> <verb>
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return run(argv, *args, **kwargs)

    monkeypatch.setattr(project_view.subprocess, "run", past_the_bound)

    state = project_view.git_status(project)

    assert state.changed is None, "the status was cut: this is the path under test"
    assert (state.unpushed, state.level, state.counted) == read


def test_the_probe_s_children_carry_the_bound_too(monkeypatch):
    """G4: on a Mac whose `git` is `/usr/bin/git` -- a shim that opens an installer when the tools
    are missing -- the probe is `xcode-select -p`, then `git --version`, on the GUI thread at a
    process's first reload (#172). Each carries the bound. Played as that Mac on every platform,
    and nothing runs."""
    asked: list = []

    def answered(argv, *args, **kwargs):
        _bounded(argv, kwargs)
        asked.append(argv[0])
        return subprocess.CompletedProcess(argv, 0, stdout="git version 2.50.1\n", stderr="")

    monkeypatch.setattr(project_view, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(project_view, "os", SimpleNamespace(path=SimpleNamespace(
        realpath=lambda path: path)))
    monkeypatch.setattr(project_view, "shutil", SimpleNamespace(which=lambda name: "/usr/bin/git"))
    monkeypatch.setattr(project_view, "_git_runs", set())
    monkeypatch.setattr(project_view.subprocess, "run", answered)

    assert project_view._git_works()
    assert asked == ["xcode-select", "git"]


def test_a_backup_git_cannot_count_is_never_called_backed_up(tmp_path, unhurried_git):
    """...and when `rev-list` cannot count either — here no upstream to count against — the
    count is unknown, and an unknown count is not «backed up»."""
    project = _repo(tmp_path / "car")
    remote = _backup(tmp_path, project, upstream=False)
    _corrupt_index(project)

    state = project_view.git_status(project)

    assert state.remote == remote and state.unpushed is None
    assert state.level == "wait" and not state.counted


def test_the_project_header_shows_a_folder_with_no_history(tmp_path, monkeypatch, unhurried_git):
    """...and a language switch says the folder's last answer again in the new words without asking
    git (#172): it re-said the whole panel, probe and all, on the GUI thread. A reload still
    reads the folder afresh. A backup git could not count is «? not backed up», never «backed
    up» (review of #172, I-1)."""
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc.main_window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    window = MainWindow()
    window._set_project_params(None)
    assert window._project_section.sub_text() == i18n.t("gitSubNoRepo")
    assert window._project_section.dot_status() == "bad"

    _git("init", "-q", str(tmp_path))
    window._set_project_params(None)
    assert window._project_section.sub_text() == i18n.t("gitSubNoRemote"), "a reload reads"
    started = _children(monkeypatch)
    try:
        window._on_language_selected("uk")
        assert window._project_section.sub_text() == i18n.t("gitSubNoRemote")
        assert window._project_section.dot_status() == "wait"
    finally:
        window._on_language_selected("en")
    assert [argv for argv in started if argv[0] in ("git", "xcode-select")] == []

    _git("-C", str(tmp_path), "remote", "add", "origin", str(tmp_path.parent / "backup.git"))
    _corrupt_index(tmp_path)  # and no commit for `rev-list` to count from
    window._set_project_params(None)
    assert window._project_section.sub_text() == i18n.t("gitSubBehind").format(n="?")
    assert window._project_section.dot_status() == "wait"
