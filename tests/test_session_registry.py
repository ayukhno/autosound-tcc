"""SessionRegistry: phase→session mapping that answers SCR-019 (core/session_registry.py)."""

from __future__ import annotations

import json
import os

import pytest

from autosound_tcc.core.own_store import StoreUnreadable
from autosound_tcc.core.session_registry import SessionRegistry


def test_missing_file_reads_as_an_empty_registry(tmp_path):
    registry = SessionRegistry(tmp_path)

    assert registry.current_phase() is None
    assert registry.resumable_session(route="sdk") is None


def test_sync_phase_keeps_session_bookkeeping_and_no_process_data(tmp_path):
    """D-6: the process lives in the skill's `process-state.json`. This registry used to keep its
    own step/status/evidence beside it — two writers of one fact, which is divergence #10."""
    registry = SessionRegistry(tmp_path)

    entry = registry.sync_phase("2")

    assert registry.current_phase() == "2"
    assert entry["closed"] is False
    assert set(entry) == {"session_id", "closed", "updated"}


def test_entering_a_new_phase_closes_the_previous_one(tmp_path):
    """Phase transition is what ends an AI session -- the agent only reports where it is."""
    registry = SessionRegistry(tmp_path)
    registry.sync_phase("1")
    registry.bind_session("1", "sess-phase-1")

    registry.sync_phase("2")

    assert registry.resumable_session("1", route="sdk") is None  # closed -> next launch starts fresh
    assert registry.load()["phases"]["1"]["closed"] is True
    assert registry.current_phase() == "2"


def test_open_phase_is_resumable_and_closed_phase_is_not(tmp_path):
    registry = SessionRegistry(tmp_path)
    registry.sync_phase("2")
    registry.bind_session("2", "sess-abc")

    assert registry.resumable_session(route="sdk") == "sess-abc"
    assert registry.resumable_session("2", route="sdk") == "sess-abc"

    registry.close_phase("2")

    assert registry.resumable_session("2", route="sdk") is None


def test_writes_are_atomic_and_leave_no_temp_file(tmp_path):
    registry = SessionRegistry(tmp_path / ".tcc")
    registry.sync_phase("0")

    assert json.loads(registry.path.read_text(encoding="utf-8"))["current_phase"] == "0"
    assert [p.name for p in registry.path.parent.iterdir()] == ["sessions.json"], (
        "no temp file of any name is left beside it")


def test_two_registries_writing_at_once_each_rename_their_own_file(tmp_path, monkeypatch):
    """The MCP server and the session each hold a registry over the same project
    (`mcp_server.TccMcpServer`, `tuning_session.TuningSession`), and both wrote through one fixed
    `sessions.json.tmp`. A write landing between the other's temp file and its rename took that
    temp file, and the first rename found nothing to rename: a FileNotFoundError out of a phase
    change. Each write has a temp file of its own now (#173)."""
    tcc = tmp_path / ".tcc"
    server_side, session_side = SessionRegistry(tcc), SessionRegistry(tcc)
    real_replace = os.replace
    cut_in = []

    def replace(src, dst, *args, **kwargs):
        if not cut_in:  # the first write, between its temp file and its rename,
            cut_in.append(src)
            session_side.bind_session("2", "sess-b")  # is when the other one writes in full
        real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)

    server_side.sync_phase("2")

    assert cut_in, "the other write did cut in"
    assert server_side.current_phase() == "2", "the last rename's registry, whole"
    assert [p.name for p in tcc.iterdir()] == ["sessions.json"], "and no temp file left behind"


def test_a_corrupt_file_is_set_aside_and_said_and_the_next_phase_starts_a_fresh_one(
        tmp_path, app_log_told):
    """#173. A truncated file read as an empty registry, and the next phase was written over it:
    which session belonged to which phase gone, and nothing said. A read still answers an empty
    registry rather than raise; the broken file is kept beside the fresh one, bytes and all."""
    registry = SessionRegistry(tmp_path)
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text("{ truncated", encoding="utf-8")

    assert registry.current_phase() is None
    registry.sync_phase("3")
    assert registry.current_phase() == "3"

    aside = list(tmp_path.glob("sessions.json.corrupt-*"))
    assert len(aside) == 1, f"exactly one copy set aside: {aside}"
    assert aside[0].read_bytes() == b"{ truncated", "holding the original bytes"
    assert len(app_log_told) == 1 and str(registry.path) in app_log_told[0], app_log_told


def test_a_registry_that_is_not_an_object_is_set_aside_not_an_attribute_error(tmp_path,
                                                                               app_log_told):
    """`[]` is valid JSON, and `load` called `setdefault` on it: an AttributeError out of every
    read and every write — the window's session probe among them (#173)."""
    registry = SessionRegistry(tmp_path)
    registry.path.write_text("[]", encoding="utf-8")

    assert registry.resumable_session(route="sdk") is None
    registry.sync_phase("1")

    assert registry.current_phase() == "1"
    aside = list(tmp_path.glob("sessions.json.corrupt-*"))
    assert len(aside) == 1 and aside[0].read_bytes() == b"[]", aside
    assert len(app_log_told) == 1 and str(registry.path) in app_log_told[0], app_log_told


@pytest.mark.parametrize("misshapen", [
    b'{"current_phase": "2", "phases": []}',
    b'{"current_phase": "2", "phases": {"2": "sess-abc"}}',
    b'{"current_phase": ["2"], "phases": {}}',
], ids=["phases-not-an-object", "an-entry-not-an-object", "current-phase-not-a-string"])
def test_a_registry_shaped_wrong_inside_is_set_aside_not_an_error(tmp_path, app_log_told,
                                                                  misshapen):
    """The `[]` class one level down (#173, the review of Task 18, Minor 1). Missing keys were
    filled in and nothing that was there was looked at: `phases` holding a list, or a phase entry
    holding a string, raised AttributeError out of `resumable_session` — which
    `TuningSession.__init__` calls unguarded, so every session start failed naming no file — and
    a `current_phase` holding a list raised TypeError out of the next phase change. Set aside
    with its bytes and said once, and the next phase starts a fresh registry."""
    registry = SessionRegistry(tmp_path)
    registry.path.write_bytes(misshapen)

    assert registry.resumable_session(route="sdk") is None
    registry.sync_phase("3")

    assert registry.current_phase() == "3"
    aside = list(tmp_path.glob("sessions.json.corrupt-*"))
    assert len(aside) == 1 and aside[0].read_bytes() == misshapen, aside
    assert len(app_log_told) == 1 and str(registry.path) in app_log_told[0], app_log_told


#: Each of the registry's writes, for the refusal tests below.
_EACH_WRITE = pytest.mark.parametrize("write", [
    lambda registry: registry.sync_phase("3"),
    lambda registry: registry.bind_session("2", "sess-new"),
    lambda registry: registry.close_phase("2"),
], ids=["sync_phase", "bind_session", "close_phase"])


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0,
                    reason="POSIX permissions, and root reads a file whatever its mode")
@_EACH_WRITE
def test_a_registry_that_cannot_be_opened_reads_as_empty_and_is_never_written_over(
        tmp_path, app_log_told, write):
    """There and not readable is not "no sessions" (#173, R-l). The old reader answered an empty
    registry, and the next write renamed a fresh one over it — the live session's id gone. Now a
    write refuses; a read still answers empty, because the window builds a session only to read
    this, unguarded."""
    registry = SessionRegistry(tmp_path)
    registry.sync_phase("2")
    registry.bind_session("2", "sess-live")
    before = registry.path.read_bytes()
    registry.path.chmod(0)
    try:
        assert registry.resumable_session(route="sdk") is None
        with pytest.raises(OSError) as refused:
            write(registry)
    finally:
        registry.path.chmod(0o600)

    assert registry.path.read_bytes() == before, "never written over"
    assert refused.type is StoreUnreadable, "refused as the store's own failure, an OSError"
    assert not list(tmp_path.glob("*.corrupt-*")), "and not set aside: its bytes may be fine"
    assert len(app_log_told) == 1 and str(registry.path) in app_log_told[0], "said once"


@_EACH_WRITE
def test_a_registry_that_cannot_be_opened_is_refused_on_every_platform(tmp_path, app_log_told,
                                                                       write):
    """The chmod test above cannot run on Windows (the review of Task 18, Minor 3). A folder where
    the file should be is refused everywhere — `IsADirectoryError` on POSIX, `PermissionError` on
    Windows — so the reads' empty registry and the writes' refusal are pinned there too. The old
    write failed here as well, but on its rename, having said nothing and leaving its
    `sessions.json.tmp` behind: the type is what tells the store's refusal from that."""
    tcc = tmp_path / ".tcc"
    registry = SessionRegistry(tcc)
    registry.path.mkdir(parents=True)
    (registry.path / "inside").write_text("kept", encoding="utf-8")

    assert registry.resumable_session(route="sdk") is None
    with pytest.raises(OSError) as refused:
        write(registry)

    assert refused.type is StoreUnreadable, "refused as the store's own failure, an OSError"
    assert (registry.path / "inside").read_text(encoding="utf-8") == "kept", "never written over"
    assert [p.name for p in tcc.iterdir()] == ["sessions.json"], (
        "not set aside, and no temp file left beside it")
    assert len(app_log_told) == 1 and str(registry.path) in app_log_told[0], "said once"


# ---- routes (tcc #181): an id is resumed only by the harness that made it --------------------


def test_bind_session_writes_its_route(tmp_path):
    registry = SessionRegistry(tmp_path)
    registry.sync_phase("2")

    registry.bind_session("2", "sess-claude")
    assert registry.load()["phases"]["2"]["route"] == "sdk", "the SDK's, unless said otherwise"
    registry.bind_session("2", "thread-codex", route="codex")
    assert registry.load()["phases"]["2"]["route"] == "codex"
    assert registry.load()["schema_version"] == 1, "additive: the schema stays 1"


def test_a_claude_id_is_never_handed_to_codex_and_the_reverse(tmp_path):
    registry = SessionRegistry(tmp_path)
    registry.sync_phase("2")

    registry.bind_session("2", "sess-claude", route="sdk")
    assert registry.resumable_session(route="codex") is None
    assert registry.resumable_session(route="sdk") == "sess-claude"

    registry.bind_session("2", "thread-codex", route="codex")
    assert registry.resumable_session(route="sdk") is None
    assert registry.resumable_session(route="codex") == "thread-codex"


def test_an_entry_from_before_routes_reads_as_the_sdks(tmp_path):
    """Every id written before the field existed was the SDK's: it still resumes there, and only
    there."""
    registry = SessionRegistry(tmp_path)
    registry.path.write_text(json.dumps({
        "schema_version": 1, "current_phase": "3",
        "phases": {"3": {"session_id": "sess-old", "closed": False}},
    }), encoding="utf-8")

    assert registry.resumable_session(route="sdk") == "sess-old"
    assert registry.resumable_session(route="codex") is None


def test_no_route_asked_means_any_route_and_a_closed_phase_still_gives_none(tmp_path):
    """omp's rule: it resumes by folder and asks only whether the phase has a live session."""
    registry = SessionRegistry(tmp_path)
    registry.sync_phase("2")
    registry.bind_session("2", "thread-codex", route="codex")

    assert registry.resumable_session(route=None) == "thread-codex"
    registry.close_phase("2")
    assert registry.resumable_session(route=None) is None


def test_the_route_cannot_be_left_out():
    """Required, so no new caller gets another harness's id by forgetting to name its own."""
    with pytest.raises(TypeError):
        SessionRegistry.resumable_session(SessionRegistry(os.devnull))  # type: ignore[call-arg]
