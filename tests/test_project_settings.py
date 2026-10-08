"""TCC's own per-project settings file."""

from __future__ import annotations

import json
import os

import pytest

from autosound_tcc.core import own_store, project_settings


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


def test_a_broken_file_is_set_aside_and_said_and_the_write_starts_a_fresh_one(tmp_path,
                                                                              app_log_told):
    """#173, F5. A trailing comma — what a hand edit leaves — read as "no preference", and the
    next `set_value` wrote that back with one field in it: every model choice, tick, delay and
    import answer gone, and nothing said. Now the broken file is set aside with its bytes, the
    window is told, and the write starts a fresh file."""
    path = project_settings.path_for(tmp_path)
    broken = (b'{\n  "generator": "sdk:claude-opus-5",\n'
              b'  "curve_delays": {"w-L_01 (sw)": 0.198},\n}\n')
    path.write_bytes(broken)

    project_settings.set_value(tmp_path, "critic", "sdk:claude-opus-5")

    aside = list(tmp_path.glob(f"{project_settings.FILENAME}.corrupt-*"))
    assert len(aside) == 1, f"exactly one copy set aside: {aside}"
    assert aside[0].read_bytes() == broken, "holding the original bytes"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "critic": "sdk:claude-opus-5", "schema_version": 1}, "the new file holds only the new field"
    assert len(app_log_told) == 1 and str(path) in app_log_told[0], app_log_told


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0,
                    reason="POSIX permissions, and root reads a file whatever its mode")
def test_a_file_that_cannot_be_opened_is_refused_and_left_as_it_was(tmp_path, app_log_told):
    """There and not readable is not "no preference". The old reader answered `{}` for it, and
    the write renamed a fresh file over it — a rename needs the folder, not the file — so the
    settings went the same way. Now the write refuses; a plain read still answers the default,
    because a reader must not take the window down (R-l)."""
    path = project_settings.path_for(tmp_path)
    before = b'{"generator": "sdk:claude-opus-5", "schema_version": 1}'
    path.write_bytes(before)
    path.chmod(0)
    try:
        assert project_settings.get(tmp_path, "generator", "fallback") == "fallback"
        with pytest.raises(OSError) as refused:
            project_settings.set_value(tmp_path, "critic", "sdk:claude-opus-5")
    finally:
        path.chmod(0o600)

    assert path.read_bytes() == before, "never written over"
    assert refused.type is own_store.StoreUnreadable, "the store's own refusal, an OSError"
    assert not list(tmp_path.glob("*.corrupt-*")), "and not set aside: its bytes may be fine"
    assert len(app_log_told) == 1 and str(path) in app_log_told[0], "said once, not per read"


def test_a_settings_file_that_cannot_be_opened_is_refused_on_every_platform(tmp_path,
                                                                            app_log_told):
    """The chmod test above cannot run on Windows (the review of Task 17, Minor 6). A folder where
    the file should be is refused everywhere — `IsADirectoryError` on POSIX, `PermissionError` on
    Windows — so the reader's default and the write's refusal are pinned there too."""
    path = project_settings.path_for(tmp_path)
    path.mkdir()
    (path / "inside").write_text("kept", encoding="utf-8")

    assert project_settings.get(tmp_path, "generator", "fallback") == "fallback"
    assert project_settings.load(tmp_path) == {}
    with pytest.raises(own_store.StoreUnreadable):
        project_settings.set_value(tmp_path, "critic", "sdk:claude-opus-5")

    assert (path / "inside").read_text(encoding="utf-8") == "kept", "never written over"
    assert not list(tmp_path.glob("*.corrupt-*")), "and not set aside: its bytes may be fine"
    assert len(app_log_told) == 1 and str(path) in app_log_told[0], "said once, not per read"


def test_the_window_s_writer_says_a_store_it_cannot_read_once_and_returns(tmp_path, app_log_told):
    """The review of Task 17, Important 2: the window writes from slots and from `closeEvent`, and
    `StoreUnreadable` raised there skipped the rest of the slot — or the whole orderly quit, on
    every quit while the store stayed unreadable. `set_value_or_say` says it (once for this state
    of the file) and returns; `set_value` still raises (R-l). A folder where the file should be
    is refused on every platform, so this runs on Windows too."""
    path = project_settings.path_for(tmp_path)
    path.mkdir()
    (path / "inside").write_text("kept", encoding="utf-8")

    assert project_settings.set_value_or_say(tmp_path, "effort", "high") is False
    assert project_settings.set_value_or_say(tmp_path, "critic", "sdk:claude-opus-5") is False

    assert (path / "inside").read_text(encoding="utf-8") == "kept", "never written over"
    assert len(app_log_told) == 1 and str(path) in app_log_told[0], app_log_told
    with pytest.raises(own_store.StoreUnreadable):
        project_settings.set_value(tmp_path, "effort", "high")
    readable = tmp_path / "readable"
    assert project_settings.set_value_or_say(readable, "effort", "high") is True
    assert project_settings.get(readable, "effort") == "high"


def test_the_window_s_writer_says_a_write_that_fails_once_and_returns(tmp_path, monkeypatch,
                                                                     app_log_told):
    """R-bl: a read-only `.tcc/` or a full disk fails the write itself, and on the close path that
    broke the quit the same way an unreadable store did. Said once for this state of the file —
    though every call reads the store fine before it writes — and the writer returns; `set_value`
    still raises."""
    path = project_settings.path_for(tmp_path)
    path.write_text('{"generator": "sdk:claude-opus-5"}', encoding="utf-8")

    def full(_target, _data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(own_store, "write_json", full)

    assert project_settings.set_value_or_say(tmp_path, "effort", "high") is False
    assert project_settings.set_value_or_say(tmp_path, "critic", "sdk:claude-opus-5") is False

    assert len(app_log_told) == 1, app_log_told
    assert str(path) in app_log_told[0] and "No space left on device" in app_log_told[0]
    with pytest.raises(OSError) as refused:
        project_settings.set_value(tmp_path, "effort", "high")
    assert refused.type is OSError, "the write's own failure, as it was"


def test_a_write_that_fails_again_after_one_landed_is_said_again(tmp_path, monkeypatch,
                                                                 app_log_told):
    """The re-review of Task 17, N2: what was said about a failed write was never forgotten. A
    write failing while the store is absent, one landing, the store deleted while TCC ran, and the
    same failure again: the same state as the first time, so it went unsaid."""
    path = project_settings.path_for(tmp_path)
    real_write, full = own_store.write_json, []

    def write(target, data):
        if full:
            raise OSError(28, "No space left on device")
        real_write(target, data)

    monkeypatch.setattr(own_store, "write_json", write)

    full.append(True)
    assert project_settings.set_value_or_say(tmp_path, "effort", "high") is False
    full.clear()
    assert project_settings.set_value_or_say(tmp_path, "effort", "high") is True
    path.unlink()
    full.append(True)
    assert project_settings.set_value_or_say(tmp_path, "effort", "high") is False

    assert len(app_log_told) == 2, app_log_told


def test_what_kept_a_save_off_the_disk_is_named_after_it_was_said_once(tmp_path, app_log_told):
    """The re-review of Task 17, round 2: a Save is the person asking, and its answer names what
    is wrong even after the failure was said once and the memo keeps every later read quiet.
    Once the store is fine again, there is nothing wrong to name but its path."""
    path = project_settings.path_for(tmp_path)
    path.mkdir()
    for _ in range(2):
        assert project_settings.set_value_or_say(tmp_path, "effort", "high") is False

    assert len(app_log_told) == 1
    assert project_settings.why_not_saved(tmp_path) == app_log_told[0]
    path.rmdir()
    assert project_settings.set_value_or_say(tmp_path, "effort", "high") is True
    assert project_settings.why_not_saved(tmp_path) == str(path)


def test_a_pick_that_did_not_land_is_in_force_for_the_run(tmp_path, app_log_told):
    """#173, I2: the window reads the gate and the effort back from the store — the gate at every
    permission, the effort at every session start — so a pick whose write did not land had no
    effect at all, and after the store's one report, nothing said so. Held for the run, it is what
    `get` answers, strict or not; said once per value; let go of when a write of it lands."""
    path = project_settings.path_for(tmp_path)
    path.mkdir()

    first = project_settings.pick(tmp_path, "gate", "writes")
    assert first == (False, True), "not saved, and the window has it to say"
    assert project_settings.get(tmp_path, "gate") == "writes"
    assert project_settings.get(tmp_path, "gate", strict=True) == "writes", "known: no refusal"
    assert project_settings.pick(tmp_path, "gate", "writes") == (False, False), "said once"
    assert project_settings.pick(tmp_path, "gate", "auto") == (False, True), "a new pick is news"
    assert project_settings.pick(tmp_path, "effort", "low") == (False, True)
    assert project_settings.get(tmp_path, "effort") == "low"
    assert len(app_log_told) == 1, "the store itself is said once, as before"

    path.rmdir()
    project_settings.set_value(tmp_path, "effort", "high")
    assert project_settings.get(tmp_path, "effort") == "high", "a write that landed lets go"
    assert project_settings.pick(tmp_path, "gate", "foreign") == (True, False)
    assert project_settings.get(tmp_path, "gate", strict=True) == "foreign"


def test_a_tick_that_did_not_land_is_not_held(tmp_path, app_log_told):
    """`always_allowed` is no pick held for the run: a tool whose tick did not land asks again,
    the safe way to be wrong (the review of Task 17, N1)."""
    project_settings.path_for(tmp_path).mkdir()

    assert project_settings.pick(tmp_path, "always_allowed", "Bash") == (False, False)
    assert project_settings.get(tmp_path, "always_allowed") is None


def test_a_strict_read_tells_a_store_that_cannot_be_read_from_one_that_is_not_there(
        tmp_path, app_log_told):
    """I2 (c): for the gate, «unreadable» is not «no preference» (R-bt). A plain read still answers
    the default (R-l); a strict one raises the store's refusal. Absent, and broken — set aside,
    so absent now — are «no preference» either way."""
    assert project_settings.get(tmp_path, "gate", "", strict=True) == ""
    path = project_settings.path_for(tmp_path)
    path.write_text('{"gate": "writes",}', encoding="utf-8")
    assert project_settings.get(tmp_path, "gate", "", strict=True) == ""
    assert not path.exists() and len(app_log_told) == 1, "set aside, and said"
    path.mkdir()

    assert project_settings.get(tmp_path, "gate", "") == ""
    with pytest.raises(own_store.StoreUnreadable):
        project_settings.get(tmp_path, "gate", "", strict=True)
