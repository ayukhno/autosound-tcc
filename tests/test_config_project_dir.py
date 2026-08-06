"""Project-folder resolution (core/config.py) — env override, saved choice, recent list."""

from __future__ import annotations

from pathlib import Path

from autosound_tcc.core import config


def test_canonical_env_var_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path / "chosen"))

    assert config.project_dir() == tmp_path / "chosen"


def test_saved_choice_is_used_when_no_env_override(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOSOUND_PROJECT_DIR", raising=False)
    chosen = tmp_path / "saved"
    chosen.mkdir()

    config.set_project_dir(chosen)

    assert config.project_dir() == chosen


def test_recent_list_is_newest_first_and_deduplicated(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOSOUND_PROJECT_DIR", raising=False)
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()

    config.set_project_dir(first)
    config.set_project_dir(second)
    config.set_project_dir(first)  # re-opening moves it back to the front, doesn't duplicate

    assert config.recent_projects() == [first, second]


def test_recent_list_drops_folders_that_no_longer_exist(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOSOUND_PROJECT_DIR", raising=False)
    gone = tmp_path / "gone"
    gone.mkdir()
    config.set_project_dir(gone)
    gone.rmdir()

    assert config.recent_projects() == []


def test_recent_list_is_capped(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOSOUND_PROJECT_DIR", raising=False)
    for i in range(config.MAX_RECENT_PROJECTS + 4):
        folder = tmp_path / f"p{i}"
        folder.mkdir()
        config.set_project_dir(folder)

    assert len(config.recent_projects()) == config.MAX_RECENT_PROJECTS


def test_looks_like_project_accepts_any_of_the_marker_files(tmp_path):
    for marker in ("autosound_context.md", "dsp_profile.json"):
        folder = tmp_path / marker.replace(".", "_")
        folder.mkdir()
        (folder / marker).write_text("x", encoding="utf-8")
        assert config.looks_like_project(folder)

    for marker in (".tcc", "rew_analitic"):
        folder = tmp_path / marker.strip(".")
        folder.mkdir()
        (folder / marker).mkdir()
        assert config.looks_like_project(folder)


def test_looks_like_project_rejects_an_empty_folder(tmp_path):
    """So the caller can warn instead of silently writing `.tcc/` into the wrong directory."""
    empty = tmp_path / "empty"
    empty.mkdir()

    assert not config.looks_like_project(empty)


def test_tcc_dir_does_not_squat_on_the_skills_process_namespace(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))

    assert config.tcc_dir() == tmp_path / ".tcc"
    assert config.tcc_dir().name != "process"  # SCR-004's namespace belongs to the skill
    assert config.mcp_config_path() == tmp_path / ".mcp.json"


def test_paths_follow_an_explicit_project_dir_argument(tmp_path):
    other = tmp_path / "other"

    assert config.tcc_dir(other) == other / ".tcc"
    assert config.mcp_config_path(other) == other / ".mcp.json"
    assert config.dsp_profile_path(other) == other / "dsp_profile.json"
    assert config.project_path(other) == other / "project.json"


def test_state_root_is_scoped_under_the_current_project_by_default(tmp_path, monkeypatch):
    """Regression (2026-07-29): state_root() used to be a project-INDEPENDENT global/env path --
    a brand-new "Create new project" folder showed whichever ledger happened to sit at the old
    default (this dev checkout's own dogfood data, in the real incident)."""
    monkeypatch.delenv("AUTOSOUND_STATE_ROOT", raising=False)
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path / "some_project"))

    assert config.state_root() == tmp_path / "some_project" / "state"


def test_state_root_env_override_still_wins(tmp_path, monkeypatch):
    """The escape hatch for a ledger tree that predates per-project scoping (e.g. this repo's own
    data/private/state/ dogfood ledger) -- must still fully override, not just supply a default."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path / "some_project"))
    override = tmp_path / "legacy_ledger"
    monkeypatch.setenv("AUTOSOUND_STATE_ROOT", str(override))

    assert config.state_root() == override


def test_project_dir_falls_back_to_default_state_root_without_recursing(monkeypatch):
    """project_dir()'s own last-resort fallback must NOT go through state_root() any more --
    state_root() now derives from project_dir(), so that would recurse forever."""
    monkeypatch.delenv("AUTOSOUND_PROJECT_DIR", raising=False)
    monkeypatch.delenv("AUTOSOUND_STATE_ROOT", raising=False)
    monkeypatch.setattr(config, "_settings", lambda: type(
        "S", (), {"value": lambda self, *_a, **_kw: ""}
    )())

    assert config.project_dir() == config.DEFAULT_STATE_ROOT
    assert config.state_root() == config.DEFAULT_STATE_ROOT / "state"


def test_the_launch_flag_becomes_the_remembered_choice(tmp_path, monkeypatch):
    """The flag and the saved choice were two sources of truth that agree until they do not: TCC
    restarts itself on a project switch, the restart carries no flag, and the window comes back on
    the previous folder while the person who typed the flag believes otherwise."""
    import os
    import sys

    from autosound_tcc import app
    from autosound_tcc.core import config

    remembered: list = []
    monkeypatch.setattr(config, "set_project_dir", remembered.append)
    monkeypatch.setattr(app, "config", config)
    monkeypatch.setattr(sys, "argv", ["autosound-tcc", "--project-dir", str(tmp_path)])
    monkeypatch.setattr(app, "ensure_project_chosen", lambda **_: False)  # stop before the window

    app.main()

    assert [str(p) for p in remembered] == [str(tmp_path.resolve())]
    assert os.environ["AUTOSOUND_PROJECT_DIR"] == str(tmp_path.resolve())
