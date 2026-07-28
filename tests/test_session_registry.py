"""SessionRegistry: phase→session mapping that answers SCR-019 (core/session_registry.py)."""

from __future__ import annotations

import json

from autosound_tcc.core.session_registry import SessionRegistry


def test_missing_file_reads_as_an_empty_registry(tmp_path):
    registry = SessionRegistry(tmp_path)

    assert registry.current_phase() is None
    assert registry.resumable_session() is None


def test_record_phase_tracks_step_status_and_evidence(tmp_path):
    registry = SessionRegistry(tmp_path)

    registry.record_phase("2", step="2.3", status="in_progress", evidence=["w-L_10"])
    entry = registry.record_phase("2", status="done", evidence=["m-L_10"])

    assert registry.current_phase() == "2"
    assert entry["step"] == "2.3"  # untouched by the second call
    assert entry["status"] == "done"
    assert entry["evidence"] == ["m-L_10", "w-L_10"]  # accumulated, de-duplicated


def test_entering_a_new_phase_closes_the_previous_one(tmp_path):
    """Phase transition is what ends an AI session -- the agent only reports where it is."""
    registry = SessionRegistry(tmp_path)
    registry.record_phase("1")
    registry.bind_session("1", "sess-phase-1")

    registry.record_phase("2")

    assert registry.resumable_session("1") is None  # closed -> next launch starts fresh
    assert registry.load()["phases"]["1"]["closed"] is True
    assert registry.current_phase() == "2"


def test_open_phase_is_resumable_and_closed_phase_is_not(tmp_path):
    registry = SessionRegistry(tmp_path)
    registry.record_phase("2")
    registry.bind_session("2", "sess-abc")

    assert registry.resumable_session() == "sess-abc"
    assert registry.resumable_session("2") == "sess-abc"

    registry.close_phase("2")

    assert registry.resumable_session("2") is None


def test_writes_are_atomic_and_leave_no_temp_file(tmp_path):
    registry = SessionRegistry(tmp_path)
    registry.record_phase("0")

    assert json.loads(registry.path.read_text(encoding="utf-8"))["current_phase"] == "0"
    assert not (tmp_path / "sessions.json.tmp").exists()


def test_corrupt_file_degrades_to_empty_rather_than_raising(tmp_path):
    registry = SessionRegistry(tmp_path)
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text("{ truncated", encoding="utf-8")

    assert registry.current_phase() is None
    registry.record_phase("3")
    assert registry.current_phase() == "3"
