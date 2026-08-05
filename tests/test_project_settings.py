"""TCC's own per-project settings file."""

from __future__ import annotations

import json

from autosound_tcc.core import project_settings


def test_a_project_that_was_never_opened_has_no_preference(tmp_path):
    assert project_settings.load(tmp_path) == {}
    assert project_settings.get(tmp_path, "generator") is None


def test_a_hand_broken_file_degrades_to_no_preference_rather_than_crashing(tmp_path):
    (tmp_path / project_settings.FILENAME).write_text("{ truncated", encoding="utf-8")

    assert project_settings.get(tmp_path, "generator", "fallback") == "fallback"


def test_a_setting_survives_and_keeps_its_neighbours(tmp_path):
    project_settings.set_value(tmp_path, "generator", "omp:google/gemini-3.1-pro-preview")
    project_settings.set_value(tmp_path, "critic", "sdk:claude-opus-5")

    assert project_settings.get(tmp_path, "generator") == "omp:google/gemini-3.1-pro-preview"
    assert project_settings.get(tmp_path, "critic") == "sdk:claude-opus-5"
    assert json.loads((tmp_path / project_settings.FILENAME).read_text())["schema_version"] == 1


def test_two_projects_do_not_share_a_choice(tmp_path):
    """The reason this file exists: remembering the model globally means opening a second folder
    silently re-points the first."""
    one, two = tmp_path / "one", tmp_path / "two"
    project_settings.set_value(one, "generator", "sdk:claude-opus-5")
    project_settings.set_value(two, "generator", "omp:google/gemini-3.1-flash-lite")

    assert project_settings.get(one, "generator") == "sdk:claude-opus-5"
    assert project_settings.get(two, "generator") == "omp:google/gemini-3.1-flash-lite"


def test_clearing_a_setting_removes_it(tmp_path):
    project_settings.set_value(tmp_path, "generator", "sdk:claude-opus-5")
    project_settings.set_value(tmp_path, "generator", None)

    assert project_settings.get(tmp_path, "generator") is None


def test_no_temp_file_is_left_behind(tmp_path):
    """Written by rename, because this is touched mid-turn and a half-written file would read as
    "no preference" — silently forgetting what the user chose."""
    project_settings.set_value(tmp_path, "generator", "sdk:claude-opus-5")

    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".tcc-project-")]
    assert leftovers == []
    assert project_settings.path_for(tmp_path).is_file()
