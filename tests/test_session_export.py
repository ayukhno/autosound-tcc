"""The last N agent sessions of a project as one readable file (TODO F-054).

Fed hand-built transcripts in Claude Code's own line shape, so what is tested is the reading and the
rendering, not whatever sessions this machine happens to hold.
"""

from __future__ import annotations

import json
import os
import time
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

