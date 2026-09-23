"""Reading the skill's `project.json` into the left panel's System/Project-params shapes
(state/project_view.py, SCR-015/016). No vendored submodule needed -- this is plain JSON reading.
"""

from __future__ import annotations

import json

from autosound_tcc.state import project_view


def _write(project_dir, data):
    (project_dir / "project.json").write_text(json.dumps(data), encoding="utf-8")


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


def test_git_facts_are_shown_for_a_repo_and_silent_for_anything_else(tmp_path):
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


def test_git_status_says_whether_history_is_kept_and_backed_up(tmp_path):
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


def test_the_project_header_shows_a_folder_with_no_history(tmp_path, monkeypatch):
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
