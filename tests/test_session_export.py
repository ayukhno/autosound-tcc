"""The last N agent sessions of a project as one readable file (TODO F-054).

Fed hand-built transcripts in Claude Code's own line shape, so what is tested is the reading and the
rendering, not whatever sessions this machine happens to hold.
"""

from __future__ import annotations

import json
import os
import time
import zipfile
from datetime import datetime
from pathlib import Path

from autosound_tcc.core import session_export


def test_a_project_folder_maps_to_claude_code_s_own_folder_name(tmp_path):
    """Every character but letters, digits and `-` becomes `-` — measured on both machines: the
    Mac's `/Users/o.yukhno/dev/autosound/hub` and the VM's `C:\\Users\\o.yukhno\\_autosound\\testTCC8`."""
    assert session_export.folder_name("/Users/o.yukhno/dev/autosound/hub") == \
        "-Users-o-yukhno-dev-autosound-hub"
    assert session_export.folder_name("C:\\Users\\o.yukhno\\_autosound\\testTCC8") == \
        "C--Users-o-yukhno--autosound-testTCC8"


def _transcript(folder: Path, name: str, lines: list, mtime: float) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_the_newest_sessions_come_first_and_only_as_many_as_asked(tmp_path):
    project = tmp_path / "car"
    folder = tmp_path / "home" / ".claude" / "projects" / session_export.folder_name(str(project))
    now = time.time()
    for age, name in ((300, "old"), (200, "mid"), (100, "new")):
        _transcript(folder, name, [], now - age)

    found = session_export.recent_transcripts(project, 2, home=tmp_path / "home")

    assert [path.stem for path in found] == ["new", "mid"]


def test_a_session_reads_as_who_said_what_with_tools_on_one_line(tmp_path):
    lines = [
        {"type": "mode", "mode": "normal"},
        {"type": "user", "timestamp": "2026-09-14T14:09:00Z",
         "message": {"role": "user", "content": "Start the intake, please"}},
        {"type": "user", "isMeta": True, "timestamp": "2026-09-14T14:09:01Z",
         "message": {"role": "user", "content": "Base directory for this skill: …"}},
        {"type": "assistant", "timestamp": "2026-09-14T14:09:05Z",
         "message": {"role": "assistant", "content": [
             {"type": "thinking", "thinking": "private"},
             {"type": "text", "text": "Reading the project first."},
             {"type": "tool_use", "id": "t1", "name": "Bash",
              "input": {"command": "python3 rew_tool/contract.py check .\nsecond line"}},
         ]}},
        {"type": "user", "timestamp": "2026-09-14T14:09:07Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1",
              "content": "one\ntwo\nthree\nfour\nfive"},
         ]}},
        {"type": "assistant", "isSidechain": True, "timestamp": "2026-09-14T14:09:08Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "subagent talk"}]}},
    ]
    path = _transcript(tmp_path, "abc123", lines, time.time())

    text = session_export.render([path], {"abc123": "-1"})

    assert "## Session abc123 · phase -1" in text
    assert "Arbiter turns: 1 · model words: 4 · tool calls: 1" in text
    assert "Start the intake, please" in text and "Reading the project first." in text
    assert "→ Bash: python3 rew_tool/contract.py check ." in text
    assert "one" in text and "three" in text and "four" not in text and "2 more lines" in text
    for hidden in ("Base directory for this skill", "private", "subagent talk", "second line"):
        assert hidden not in text


def test_the_phase_of_each_session_comes_from_tcc_s_registry(tmp_path):
    tcc = tmp_path / ".tcc"
    tcc.mkdir()
    (tcc / "sessions.json").write_text(json.dumps({
        "schema_version": 1, "current_phase": "0",
        "phases": {"-1": {"session_id": "s1", "closed": True}, "0": {"session_id": "s2"}},
    }), encoding="utf-8")

    assert session_export.phases_by_session(tmp_path) == {"s1": "-1", "s2": "0"}


def test_a_session_that_runs_past_midnight_names_both_days(tmp_path):
    lines = [
        {"type": "user", "timestamp": "2026-09-16T23:50:00Z",
         "message": {"role": "user", "content": "late"}},
        {"type": "user", "timestamp": "2026-09-17T00:10:00Z",
         "message": {"role": "user", "content": "later"}},
    ]
    path = _transcript(tmp_path, "night", lines, time.time())

    assert "2026-09-16 23:50 → 2026-09-17 00:10" in session_export.render([path])



def _one_line(when: str = "2026-09-19T12:01:00Z") -> list:
    return [{"type": "user", "timestamp": when, "message": {"role": "user", "content": "привіт"}}]


def test_the_chooser_gets_when_how_big_and_which_phase(tmp_path):
    """The tab lists sessions to tick, so the list has to say which is which without opening one
    (the user, 2026-09-19). Newest first, as everywhere else."""
    project = tmp_path / "EPY-Sep2026"
    project.mkdir()
    folder = tmp_path / "home" / ".claude" / "projects" / session_export.folder_name(str(project))
    day = datetime(2026, 9, 18, 20, 17).timestamp()
    _transcript(folder, "older", _one_line(), day)
    _transcript(folder, "newer", _one_line(), day + 3600)
    (project / ".tcc").mkdir()
    (project / ".tcc" / "sessions.json").write_text(
        json.dumps({"phases": {"-1": {"session_id": "newer"}}}), encoding="utf-8")

    rows = session_export.sessions(project, home=tmp_path / "home")

    assert [row.session_id for row in rows] == ["newer", "older"]
    assert rows[0].phase == "-1" and rows[1].phase is None
    assert rows[0].size > 0
    assert rows[0].when.hour == 21 and rows[1].when.hour == 20


def test_the_default_name_carries_the_project_and_the_days_being_saved(tmp_path):
    """Named for WHAT is saved, not for when the saving happened (the user, 2026-09-19)."""
    project = tmp_path / "EPY-Sep2026"
    one = session_export.SessionRow(path=Path("a.jsonl"), when=datetime(2026, 9, 19, 12, 1), size=1)
    two = session_export.SessionRow(path=Path("b.jsonl"), when=datetime(2026, 9, 18, 20, 17), size=1)

    assert session_export.default_stem(project, [one]) == "EPY-Sep2026-sessions-2026-09-19"
    assert session_export.default_stem(project, [one, two]) == \
        "EPY-Sep2026-sessions-2026-09-18_2026-09-19"
    assert session_export.default_stem(project, []) == "EPY-Sep2026-sessions"


def test_each_session_can_be_its_own_file_inside_one_archive(tmp_path):
    """The user, 2026-09-19: «може кожну окремим файлом і архів»."""
    project = tmp_path / "car"
    project.mkdir()
    folder = tmp_path / "home" / ".claude" / "projects" / session_export.folder_name(str(project))
    day = datetime(2026, 9, 18, 20, 17).timestamp()
    _transcript(folder, "aaaaaaaa-1111", _one_line(), day)
    _transcript(folder, "bbbbbbbb-2222", _one_line(), day + 3600)
    rows = session_export.sessions(project, home=tmp_path / "home")

    target = session_export.save_each_file(rows, tmp_path / "out.zip", title="car")

    with zipfile.ZipFile(target) as archive:
        names = sorted(archive.namelist())
        assert names == ["2026-09-18-2017-aaaaaaaa.md", "2026-09-18-2117-bbbbbbbb.md"]
        assert "привіт" in archive.read(names[0]).decode("utf-8")


def test_one_chosen_session_is_a_file_and_not_an_archive_of_one(tmp_path):
    """An archive holding one thing is a step between the person and what they asked for."""
    project = tmp_path / "car"
    project.mkdir()
    folder = tmp_path / "home" / ".claude" / "projects" / session_export.folder_name(str(project))
    _transcript(folder, "only", _one_line(), datetime(2026, 9, 19, 12, 1).timestamp())
    rows = session_export.sessions(project, home=tmp_path / "home")

    target = session_export.save_each_file(rows, tmp_path / "one.md", title="car")

    assert target.read_text(encoding="utf-8").startswith("# Sessions — car")
    assert not zipfile.is_zipfile(target)
