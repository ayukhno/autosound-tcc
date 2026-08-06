"""TCC's MCP server: tool surface, the Arbiter gate, and the `.mcp.json` handshake.

Tools are exercised through `FastMCP.call_tool` rather than over HTTP -- same code path the
transport reaches, without a uvicorn process to start and race against in every test.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import Future

import pytest

from autosound_tcc.core import mcp_server
from autosound_tcc.core.mcp_server import (
    ConfirmRequest,
    HeadlessBridge,
    TccMcpServer,
    build_server,
    write_mcp_config,
)
from autosound_tcc.core.session_registry import SessionRegistry
from autosound_tcc.core.signal_bus import NOT_VISIBLE, PARAM_EDIT_MODE, SignalBus


class RecordingBridge:
    """A stand-in Arbiter whose verdict the test chooses up front."""

    def __init__(self, allow: bool) -> None:
        self.allow = allow
        self.requests: list[ConfirmRequest] = []
        self.clipboard: list[str] = []
        self.proposals: list[dict] = []

    def snapshot(self) -> dict:
        return {"preset": "FULL", "selected": "m_L"}

    def request_confirmation(self, request: ConfirmRequest) -> "Future[bool]":
        self.requests.append(request)
        future: "Future[bool]" = Future()
        future.set_result(self.allow)
        return future

    def copy_to_clipboard(self, text: str) -> None:
        self.clipboard.append(text)

    def show_proposal(self, proposal: dict) -> None:
        self.proposals.append(proposal)

    def notify_profile_ready(self) -> None:
        pass

    def refresh_from_disk(self) -> None:
        self.refreshes += 1

    refreshes = 0


def _server(tmp_path, bridge):
    bus = SignalBus(tmp_path)
    registry = SessionRegistry(tmp_path)
    return build_server(tmp_path, bridge, bus, registry), bus, registry


def _write_process_state(project_dir, active_phase: str) -> None:
    """Seed the skill-owned process state — the only place a phase legitimately comes from."""
    process_dir = project_dir / "process"
    process_dir.mkdir(parents=True, exist_ok=True)
    (process_dir / "process-state.json").write_text(
        json.dumps({"schema_version": 1, "active_phase": active_phase}), encoding="utf-8"
    )


def _text(result) -> str:
    blocks = result[0] if isinstance(result, tuple) else result
    return blocks[0].text


def test_tool_surface_is_the_documented_set(tmp_path):
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert names == {
        "get_tcc_state",
        "get_pending_signals",
        "wait_for_signal",
        "get_ledger",
        "get_capability_checklist",
        "check_existing_profile",
        "save_profile_field",
        "reset_profile_field",
        "finalize_profile",
        "propose_change",
        "call_critic",
        "write_rew_filters",
        "copy_helix_eq",
        "report_phase",
        "enter_phase",
        "add_step",
        "start_step",
        "finish_step",
        "skip_step",
        "block_step",
        # The capture round (SCR-034) -- recording one is a tool, like every other process write,
        # rather than a shell-out the model has to remember the path for.
        "record_decision",
        "start_capture",
        "record_capture",
        "skip_capture",
        "close_capture",
    }
    # No measurement tool: the panel is still mock data, and serving fabricated sweeps to a model
    # invites EQ computed from numbers that were never measured.
    assert not any("measurement" in name for name in names)


def test_get_tcc_state_reports_the_skills_phase_not_its_own(tmp_path):
    """D-6: the phase is read out of `process-state.json`. TCC answering from its own bookkeeping
    is what let the two drift (#10)."""
    bridge = RecordingBridge(allow=True)
    mcp, bus, registry = _server(tmp_path, bridge)
    _write_process_state(tmp_path, "2")
    registry.sync_phase("4")  # stale mirror -- must NOT be what the agent is told
    bus.push(PARAM_EDIT_MODE, on=True)

    state = json.loads(_text(asyncio.run(mcp.call_tool("get_tcc_state", {}))))

    assert state["ui"] == {"preset": "FULL", "selected": "m_L"}
    assert state["current_phase"] == "2"
    assert state["pending_signals"] == 1


def test_a_step_cannot_be_closed_against_a_sentence(tmp_path):
    """The gate is the skill's (SCR-035), and this pins that it reaches the model through TCC's
    surface too -- a tool that swallowed the refusal would put the hole straight back."""
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    asyncio.run(mcp.call_tool("enter_phase", {"phase": "-1"}))
    asyncio.run(mcp.call_tool("add_step", {"step_id": "b.1", "name": "Baseline"}))

    said = json.loads(
        _text(
            asyncio.run(
                mcp.call_tool(
                    "finish_step",
                    {"step_id": "b.1", "evidence": ["baseline measurements analysed"]},
                )
            )
        )
    )

    assert said["recorded"] is False
    assert "resolves" in said["error"]  # and the reason is the skill's own wording


def test_the_state_says_which_language_the_arbiter_is_working_in(tmp_path):
    """Intake's first question is "which language?" -- and the app has been speaking the answer
    since before the session started. Top-level, not buried in `ui`: it decides what language every
    project file the skill writes is in, which is not a screen detail."""

    class _Bridge(RecordingBridge):
        def snapshot(self) -> dict:
            return {"preset": "FULL", "ui_language": "uk"}

    mcp, _bus, _registry = _server(tmp_path, _Bridge(allow=True))

    state = json.loads(_text(asyncio.run(mcp.call_tool("get_tcc_state", {}))))

    assert state["language"] == "uk"


def test_a_front_end_that_reports_no_language_says_so_rather_than_guessing(tmp_path):
    mcp, _bus, _registry = _server(tmp_path, HeadlessBridge(tmp_path))

    state = json.loads(_text(asyncio.run(mcp.call_tool("get_tcc_state", {}))))

    assert state["language"] is None  # ask, then -- exactly as with no front-end at all


def test_get_pending_signals_drains_once(tmp_path):
    mcp, bus, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    bus.push(NOT_VISIBLE, note="band 3 missing")

    first = json.loads(_text(asyncio.run(mcp.call_tool("get_pending_signals", {}))))
    second = json.loads(_text(asyncio.run(mcp.call_tool("get_pending_signals", {}))))

    assert first["count"] == 1
    assert first["signals"][0]["payload"]["note"] == "band 3 missing"
    assert second["count"] == 0


def test_wait_for_signal_times_out_without_blocking_forever(tmp_path):
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    result = json.loads(
        _text(asyncio.run(mcp.call_tool("wait_for_signal", {"timeout_seconds": 1.0})))
    )

    assert result == {"signals": [], "count": 0, "timed_out": True}


def test_propose_change_reaches_the_ui_without_touching_anything(tmp_path):
    bridge = RecordingBridge(allow=False)
    mcp, _, _ = _server(tmp_path, bridge)

    result = json.loads(
        _text(
            asyncio.run(
                mcp.call_tool(
                    "propose_change",
                    {
                        "channel": "m_L",
                        "param": "eq",
                        "from_value": "none",
                        "to_value": "PK 1120 -2.5 Q2.2",
                        "rationale": "hot left lobe",
                    },
                )
            )
        )
    )

    assert result["shown"] is True
    assert bridge.proposals[0]["channel"] == "m_L"
    # A proposal is not a mutation, so it must not have asked the Arbiter to confirm anything.
    assert bridge.requests == []


def test_clipboard_write_needs_the_arbiter(tmp_path):
    denied = RecordingBridge(allow=False)
    mcp, _, _ = _server(tmp_path, denied)

    result = json.loads(_text(asyncio.run(mcp.call_tool("copy_helix_eq", {"text": "PK 1000 -3 Q2"}))))

    assert result["copied"] is False
    assert denied.clipboard == []
    assert denied.requests[0].tool == "copy_helix_eq"


def test_clipboard_write_proceeds_once_confirmed(tmp_path):
    allowed = RecordingBridge(allow=True)
    mcp, _, _ = _server(tmp_path, allowed)

    result = json.loads(_text(asyncio.run(mcp.call_tool("copy_helix_eq", {"text": "PK 1000 -3 Q2"}))))

    assert result["copied"] is True
    assert allowed.clipboard == ["PK 1000 -3 Q2"]


def test_headless_bridge_denies_every_mutation(tmp_path):
    """No Arbiter present must mean no gate passed -- never 'no gate'."""
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    result = json.loads(_text(asyncio.run(mcp.call_tool("copy_helix_eq", {"text": "x"}))))

    assert result["copied"] is False


def test_rew_write_is_denied_before_any_rew_call(tmp_path, monkeypatch):
    """The gate runs first: a denied call must not reach REW even to look up the measurement."""
    called = []
    monkeypatch.setattr(
        mcp_server.vendor_loader,
        "load_rew_api",
        lambda: called.append("loaded"),
    )
    mcp, _, _ = _server(tmp_path, RecordingBridge(allow=False))

    result = json.loads(
        _text(
            asyncio.run(
                mcp.call_tool("write_rew_filters", {"measurement": "w-L_10", "filters": [{}]})
            )
        )
    )

    assert result["applied"] is False
    assert called == []


def test_report_phase_reads_the_phase_back_and_refreshes(tmp_path):
    """It is a signal, not a writer (D-6): the answer comes from the skill's file, and the GUI is
    told to re-read disk."""
    bridge = RecordingBridge(allow=True)
    bridge.refreshes = 0
    mcp, _, registry = _server(tmp_path, bridge)
    _write_process_state(tmp_path, "2")

    result = json.loads(_text(asyncio.run(mcp.call_tool("report_phase", {"phase": "2"}))))

    assert result["refreshed"] is True
    assert result["skill_phase"] == "2"
    assert "mismatch" not in result
    assert bridge.refreshes == 1
    assert registry.current_phase() == "2"  # mirrored for session resume, from the file's value


def test_report_phase_tells_the_agent_when_it_disagrees_with_disk(tmp_path):
    """The whole point of the read-back: a phase that exists only in the conversation gets caught
    here instead of becoming the basis of a proposal."""
    bridge = RecordingBridge(allow=True)
    bridge.refreshes = 0
    mcp, _, registry = _server(tmp_path, bridge)
    _write_process_state(tmp_path, "2")

    result = json.loads(_text(asyncio.run(mcp.call_tool("report_phase", {"phase": "4"}))))

    assert result["skill_phase"] == "2"
    assert "mismatch" in result
    assert registry.current_phase() == "2"  # the file wins, not the claim


def test_report_phase_writes_nothing_when_the_skill_has_no_phase(tmp_path):
    """No `active_phase` on disk means the move was never written — inventing one here would put
    TCC back in the business of authoring the process."""
    bridge = RecordingBridge(allow=True)
    bridge.refreshes = 0
    mcp, _, registry = _server(tmp_path, bridge)

    result = json.loads(_text(asyncio.run(mcp.call_tool("report_phase", {"phase": "2"}))))

    assert result["refreshed"] is True
    assert result["skill_phase"] is None
    assert "warning" in result
    assert registry.current_phase() is None
    assert not (tmp_path / "process").exists()


def test_write_mcp_config_merges_instead_of_clobbering(tmp_path, monkeypatch):
    """`.mcp.json` is the user's file -- other servers they configured must survive."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"theirs": {"type": "http", "url": "http://x/mcp"}}}),
        encoding="utf-8",
    )

    path = write_mcp_config(tmp_path, 8765, "tok")

    servers = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"theirs", "tcc"}
    assert servers["tcc"]["url"] == "http://127.0.0.1:8765/mcp"
    assert servers["tcc"]["headers"]["X-TCC-Token"] == "tok"


def test_free_port_skips_a_port_already_in_use(tmp_path):
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        busy = taken.getsockname()[1]
        taken.listen(1)

        assert mcp_server._free_port(preferred=busy, tries=5) != busy


@pytest.mark.parametrize("write_config", [True, False])
def test_server_starts_stops_and_advertises_itself(tmp_path, monkeypatch, write_config):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    server = TccMcpServer(project_dir=tmp_path, preferred_port=8900)

    port = server.start(write_config=write_config)
    try:
        assert server.url == f"http://127.0.0.1:{port}/mcp"
        assert (tmp_path / ".mcp.json").exists() is write_config
    finally:
        server.stop()

    assert server._thread is None


# ---- onboarding tools (2026-07-29) -- an external CLI's path to driving onboarding,
# see core/agent_session.py's in-process equivalent for the Claude-SDK path ------------------


def test_capability_checklist_comes_from_the_skill(tmp_path):
    """The interview is the skill's. TCC used to keep its own copy of the questions beside the
    schema they fill in -- two lists, one of which would eventually be the stale one."""
    from autosound_tcc.core import profile_writer

    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    result = json.loads(_text(asyncio.run(mcp.call_tool("get_capability_checklist", {}))))

    assert result == profile_writer.capability_checklist()
    assert result, "the skill must actually supply questions"


def _bundled_dir_with(tmp_path, vendor: str, name: str):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "one.json").write_text(json.dumps(
        {"dsp_profile": {"name": name, "vendor": vendor, "groups": []}}
    ))
    return bundled


def test_check_existing_profile_finds_an_exact_bundled_match(tmp_path, monkeypatch):
    bundled = _bundled_dir_with(tmp_path, "Audiotec-Fischer", "Helix DSP Ultra S")
    monkeypatch.setattr(mcp_server.config, "bundled_profiles_dir", lambda: bundled)
    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    mcp, _, _ = _server(project_dir, HeadlessBridge(project_dir))

    result = json.loads(_text(asyncio.run(mcp.call_tool(
        "check_existing_profile", {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"},
    ))))

    # Unwrapped -- no top-level "dsp_profile" key -- so it's directly what save_profile_field's
    # `path` resolves against, same shape as project_profile (regression: a wrapped response here
    # is exactly what led an agent to double-nest dsp_profile.dsp_profile, 2026-07-29 dogfood).
    assert result["bundled_exact_match"]["vendor"] == "Audiotec-Fischer"
    assert "dsp_profile" not in result["bundled_exact_match"]
    assert "dsp_profile" not in result["project_profile"]


def test_check_existing_profile_is_strict_no_fuzzy_matching(tmp_path, monkeypatch):
    """Regression context: free-typing "Helix"/"Ultra S" against a profile actually keyed
    `Audiotec-Fischer`/`Helix DSP Ultra S` must NOT match -- that strictness is deliberate
    (project-intake.md §4), the fix for the user's report was the picker (new_project_dialog.py),
    not loosening this check."""
    bundled = _bundled_dir_with(tmp_path, "Audiotec-Fischer", "Helix DSP Ultra S")
    monkeypatch.setattr(mcp_server.config, "bundled_profiles_dir", lambda: bundled)
    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    mcp, _, _ = _server(project_dir, HeadlessBridge(project_dir))

    result = json.loads(_text(asyncio.run(mcp.call_tool(
        "check_existing_profile", {"vendor": "Helix", "model": "Ultra S"},
    ))))

    assert result["bundled_exact_match"] is None


def test_save_reset_and_finalize_profile_round_trip(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    mcp, _, _ = _server(project_dir, HeadlessBridge(project_dir))

    asyncio.run(mcp.call_tool("check_existing_profile", {"vendor": "Musway", "model": "M6V4"}))
    asyncio.run(mcp.call_tool("save_profile_field", {"path": "sample_rate_hz", "value": 96000}))
    asyncio.run(mcp.call_tool("save_profile_field", {"path": "groups.0.id", "value": "physical_outputs"}))
    asyncio.run(mcp.call_tool("save_profile_field", {"path": "groups.0.label", "value": "Output channels"}))
    asyncio.run(mcp.call_tool("save_profile_field", {"path": "groups.0.fields", "value": ["hp", "lp"]}))

    reset_result = json.loads(
        _text(asyncio.run(mcp.call_tool("reset_profile_field", {"path": "sample_rate_hz"})))
    )
    assert reset_result == {"reset": "sample_rate_hz", "found": True}

    # Every answer so far is already on disk, in the skill's draft -- a session that died here
    # would resume with all of it (SCR-025).
    draft = json.loads((project_dir / "dsp_profile.draft.json").read_text())["dsp_profile"]
    assert draft["groups"][0]["fields"] == ["hp", "lp"], draft

    finalize_result = json.loads(_text(asyncio.run(mcp.call_tool("finalize_profile", {}))))

    saved_path = project_dir / "dsp_profile.json"
    assert finalize_result == {"saved_to": str(saved_path)}
    saved = json.loads(saved_path.read_text())["dsp_profile"]
    assert saved["groups"][0] == {
        "id": "physical_outputs", "label": "Output channels", "fields": ["hp", "lp"],
    }
    assert "sample_rate_hz" not in saved  # reset before finalize, must not reappear
    # finalize promotes the draft and clears it -- the skill's writer did the writing, not TCC.
    assert not (project_dir / "dsp_profile.draft.json").exists()


def test_onboarding_tools_before_check_existing_profile_are_a_clean_error(tmp_path):
    """save/reset/finalize all need the draft check_existing_profile starts -- an agent that skips
    it gets a message it can act on, not a half-filled draft whose missing vendor/name only
    surfaces much later, at finalize."""
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    for tool, args in (
        ("save_profile_field", {"path": "x", "value": 1}),
        ("reset_profile_field", {"path": "x"}),
        ("finalize_profile", {}),
    ):
        result = json.loads(_text(asyncio.run(mcp.call_tool(tool, args))))
        assert "error" in result


def test_the_process_tools_actually_write_the_journal(tmp_path):
    """The hole the harness spike found: the surface offered `report_phase`, which records nothing,
    so whether the process got recorded depended on the model shelling out to `process.py` by
    itself. These tools drive the skill's own writer, so the journal grows without that luck."""
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    # The step is closed against the file the answer was written into, not against a sentence
    # saying it was: the skill refuses evidence that resolves to nothing (SCR-035).
    (tmp_path / "autosound_context.md").write_text("Language: uk\n", encoding="utf-8")

    for tool, args in (
        ("enter_phase", {"phase": "-1"}),
        ("add_step", {"step_id": "lang", "name": "Set session language"}),
        ("start_step", {"step_id": "lang"}),
        (
            "finish_step",
            {"step_id": "lang", "evidence": ["autosound_context.md: language uk"]},
        ),
    ):
        result = json.loads(_text(asyncio.run(mcp.call_tool(tool, args))))
        assert result["recorded"] is True, (tool, result)

    events = [
        json.loads(line)
        for line in (tmp_path / "process" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [e["type"] for e in events] == [
        "phase_entered", "step_added", "attempt_started", "step_done"
    ]
    assert json.loads(
        _text(asyncio.run(mcp.call_tool("report_phase", {})))
    )["skill_phase"] == "-1"


def test_finish_step_without_evidence_is_refused_by_the_skill(tmp_path):
    """No evidence, no done (SCR-004). The gate lives in the skill and its wording comes back
    verbatim, because the caller has to know what to supply rather than that something failed."""
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    asyncio.run(mcp.call_tool("enter_phase", {"phase": "-1"}))
    asyncio.run(mcp.call_tool("add_step", {"step_id": "lang", "name": "Set session language"}))

    result = json.loads(
        _text(asyncio.run(mcp.call_tool("finish_step", {"step_id": "lang", "evidence": []})))
    )

    assert result["recorded"] is False
    assert "evidence" in result["error"]
    assert "step_done" not in (tmp_path / "process" / "journal.jsonl").read_text(encoding="utf-8")


# ---- what TCC already knows and must not ask twice --------------------------


def test_the_state_carries_the_reviewer_the_arbiter_picked(tmp_path):
    """Intake opened every session with "how would you like to set up the Reviewer channel?" —
    about a channel already configured in TCC's footer and one `call_critic` away. A GUI that
    knows something and asks anyway is a chat window with more buttons."""
    from autosound_tcc.core import config, project_settings
    from autosound_tcc.core.mcp_server import _reviewer_state

    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "omp:google/gemini-3.1-pro")

    state = _reviewer_state(tmp_path)

    assert state["configured"] is True
    assert "gemini" in state["model"]
    assert state["reachable"] is True  # the reviewer script is Gemini-shaped
    assert "call_critic" in state["how"]


def test_an_unreachable_reviewer_says_so_rather_than_promising(tmp_path):
    """Non-Gemini choices are clipboard-only until SCR-033; the model needs to know that before
    it plans a round around an automatic review."""
    from autosound_tcc.core import config, project_settings
    from autosound_tcc.core.mcp_server import _reviewer_state

    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "sdk:claude-opus-5")

    state = _reviewer_state(tmp_path)

    assert state["configured"] is True and state["reachable"] is False
    assert "clipboard" in state["how"]


def test_no_reviewer_chosen_points_at_the_footer(tmp_path):
    from autosound_tcc.core.mcp_server import _reviewer_state

    assert _reviewer_state(tmp_path)["configured"] is False


def test_the_reviewer_says_who_decided_it(tmp_path):
    """Reported once and asked back: the model read the reviewer out of TCC's state and then put
    "confirm that this is your independent reviewer?" to the Arbiter. `configured` says what the
    value is; it does not say who decided it, and a value the Arbiter set in the UI is settled."""
    from autosound_tcc.core import config, project_settings
    from autosound_tcc.core.mcp_server import _reviewer_state

    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "omp:google/gemini-3.1-pro")

    assert "Arbiter" in _reviewer_state(tmp_path)["decided_by"]


def test_a_capture_round_can_be_recorded_through_the_tools(tmp_path):
    """SCR-034 through the surface the model actually has: without these it would have to shell out
    to `process.py` for the one kind of process write that has no tool."""
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    asyncio.run(mcp.call_tool("enter_phase", {"phase": "0"}))

    for tool, args in (
        ("start_capture", {"version": "3", "expected": ["sw_1 (sw)", "sw_1 (rta)"]}),
        ("record_capture", {"title": "sw_1 (sw)"}),
        ("skip_capture", {"title": "sw_1 (rta)", "reason": "sub is disconnected"}),
        ("close_capture", {"reason": "round done"}),
    ):
        result = json.loads(_text(asyncio.run(mcp.call_tool(tool, args))))
        assert result["recorded"] is True, (tool, result)

    types = [
        json.loads(line)["type"]
        for line in (tmp_path / "process" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert types == [
        "phase_entered",
        "capture_task_issued",
        "capture_taken",
        "capture_skipped",
        "capture_round_closed",
    ]


def test_skipping_a_capture_without_a_reason_is_refused(tmp_path):
    """A skip with no reason is a gap wearing a decision's clothes: the next session proposes it
    again, which is the thing SCR-034 exists to stop."""
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    asyncio.run(mcp.call_tool("enter_phase", {"phase": "0"}))
    asyncio.run(mcp.call_tool("start_capture", {"version": "3", "expected": ["sw_1 (sw)"]}))

    said = json.loads(
        _text(asyncio.run(mcp.call_tool("skip_capture", {"title": "sw_1 (sw)", "reason": " "})))
    )

    assert said["recorded"] is False
    assert "reason" in said["error"]


def test_an_arbiters_ruling_is_recorded_as_the_answer_not_as_prose(tmp_path):
    """Their half of the conversation was in no machine file: the only trace of an answer was a
    hand-typed evidence string, so a constraint they set was invisible to the next session."""
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    asyncio.run(mcp.call_tool("enter_phase", {"phase": "0"}))

    said = json.loads(
        _text(
            asyncio.run(
                mcp.call_tool(
                    "record_decision",
                    {
                        "question": "Sample rate for the baseline?",
                        "answer": "96 kHz, not 48",
                        "invalidates": "sw_1 (sw)",
                    },
                )
            )
        )
    )
    assert said["recorded"] is True

    events = [
        json.loads(line)
        for line in (tmp_path / "process" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    decision = next(e for e in events if e["type"] == "user_decision")
    assert decision["answer"] == "96 kHz, not 48"
    assert decision["phase"] == "0"  # asked under the phase it constrains
    assert decision["invalidates"] == "sw_1 (sw)"  # same shape as config_change.impact


def test_a_critique_reaches_the_journal_with_a_pointer_to_its_text(tmp_path, monkeypatch):
    """`critic_called` recorded that a review happened and lost what it argued (SCR-027). The local
    log answers the footer; the journal is what a resume and any other front-end read."""
    from autosound_tcc.core import critic

    class _Bridge(RecordingBridge):
        critiques: list = []

        def show_critique(self, critique: dict) -> None:
            self.critiques.append(critique)

    bridge = _Bridge(allow=True)
    mcp, _, _ = _server(tmp_path, bridge)
    asyncio.run(mcp.call_tool("enter_phase", {"phase": "2"}))
    monkeypatch.setattr(
        critic,
        "run",
        lambda *a, **k: critic.CriticResult(
            critic.MODE_API_OR_CLI, "the sub is 3 dB hot", "gemini-2.5-pro", "critic", "",
            1.0, "2026-08-06T21:00:00+00:00", "process/reviews/2026-08-06T21-critic.md",
        ),
    )

    asyncio.run(mcp.call_tool("call_critic", {"package": "## proposal"}))

    events = [
        json.loads(line)
        for line in (tmp_path / "process" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # The bubble links the file rather than being the only copy of it.
    assert bridge.critiques[-1]["review"] == "process/reviews/2026-08-06T21-critic.md"
    called = next(e for e in events if e["type"] == "critic_called")
    assert called["review"] == "process/reviews/2026-08-06T21-critic.md"
    assert called["vendor"] == "google"  # inferred from the model, so "a different vendor" is legible
    assert called["mode"] == "api"
