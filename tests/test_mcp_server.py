"""TCC's MCP server: tool surface, the Arbiter gate, and the `.mcp.json` handshake.

Tools are exercised through `FastMCP.call_tool` rather than over HTTP -- same code path the
transport reaches, without a uvicorn process to start and race against in every test.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading
from concurrent.futures import Future
from pathlib import Path

import pytest

from autosound_tcc.core import mcp_server, own_store
from autosound_tcc.core.mcp_server import (
    ConfirmRequest,
    HeadlessBridge,
    TccMcpServer,
    build_server,
    write_mcp_config,
)
from autosound_tcc.core.session_registry import SessionRegistry

from tests import _intake
from autosound_tcc.core.signal_bus import NOT_VISIBLE, PARAM_EDIT_MODE, SignalBus


class RecordingBridge:
    """A stand-in Arbiter whose verdict the test chooses up front."""

    def __init__(self, allow: bool) -> None:
        self.allow = allow
        self.requests: list[ConfirmRequest] = []
        self.clipboard: list[str] = []
        self.proposals: list[dict] = []
        self.events: list[str] = []

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

    def session_closed(self) -> None:
        self.events.append("closed")

    def session_changed(self) -> None:
        self.events.append("changed")

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


def test_every_tool_reaches_the_model_with_its_instructions(tmp_path):
    """A tool with no description is a tool the model has to guess at, and one of ours had none.

    `save_profile_field`'s instructions are computed — the field vocabulary comes off the skill's
    writer — and they were written as an f-string under the `def`. That is not a docstring:
    Python keeps only a plain literal there, so `__doc__` was None and FastMCP registered an empty
    string. Measured on the built server before the fix: every other tool 122–1351 characters,
    that one 0 — including the sentence "one field per call … don't batch everything to the end",
    which is exactly what the interview in SKL-009 did not do.

    Asserted over ALL tools, because the next computed description will be written the same way.
    """
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    tools = asyncio.run(mcp.list_tools())
    silent = [tool.name for tool in tools if not (tool.description or "").strip()]

    assert not silent, "these tools reach the model with no description at all"
    saver = next(tool for tool in tools if tool.name == "save_profile_field")
    assert "don't batch everything to the end" in saver.description, "the instruction is delivered"
    assert "groups" in saver.description and "fields" in saver.description, "and so is the shape"


def test_a_tool_call_and_its_answer_land_in_the_log(tmp_path, caplog):
    """The run that produced SKL-009 left 88 log lines, 34 of them Qt's own, and not one record
    that a half-hour interview had happened. Level and rotation were configured all along
    (`app_log.setup`); what was missing was any call at INFO."""
    import logging

    from autosound_tcc.core import app_log

    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    with caplog.at_level(logging.INFO, logger=app_log.LOGGER_NAME):
        asyncio.run(mcp.call_tool("get_tcc_state", {}))

    lines = [record.getMessage() for record in caplog.records]
    assert any(line.startswith("tool get_tcc_state(") for line in lines), lines
    assert any(line.startswith("tool get_tcc_state -> ") for line in lines), lines


def test_the_log_line_does_not_carry_the_whole_payload(tmp_path):
    """A log nobody can page through is the same as no log."""
    from autosound_tcc.core import app_log

    long_answer = "x" * 5_000

    brief = app_log.brief(long_answer)

    assert len(brief) < 300 and brief.endswith("… (cut)")


def test_tool_surface_is_the_documented_set(tmp_path):
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert names == {
        "get_tcc_state",
        "get_pending_signals",
        "ack_signals",
        "wait_for_signal",
        "get_ledger",
        "get_capability_checklist",
        "check_existing_profile",
        # The cabin twin (SKL-020): has this BODY been described, and have we built
        # on it. The writer beside it exists because the in-app interview has no
        # Bash at all — `tools` is `BUILTIN_TOOLS`, empty — so without a tool a
        # TCC-made project could never record its body.
        "check_existing_car",
        "save_car",
        "save_profile_field",
        "reset_profile_field",
        "finalize_profile",
        "propose_change",
        "show_curves",
        "call_critic",
        # A plain question on the same channel, without the tuning contract (tcc#116).
        "ask_reviewer",
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
        "check_captures",
        "start_capture",
        "record_capture",
        "skip_capture",
        "close_capture",
        # Stopping, and the four writes the method requires that TCC had no tool for: without
        # them the model reached `process.py` through Bash, and `process.py` is not in the
        # read-only allowlist -- so the front-end was DEARER than a bare terminal on exactly the
        # records the method insists on (SKL-026).
        "session_close",
        "set_target",
        "capture_knobs",
        "show_plan",
        "reconcile_plan",
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


def test_the_step_that_supersedes_is_recorded_as_a_link_not_as_a_sentence(tmp_path):
    """SKL-029: the tool used to hand the id over positionally, and the CLI reads bare words after
    the step id as the reason -- so "replaced by b.2" was written as a reason with the text "b.2"
    and the link nowhere. The break this catches is a positional argument in the tool body: with
    one, `superseded_by` lands in `reason` and this assertion fails."""
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    asyncio.run(mcp.call_tool("enter_phase", {"phase": "-1"}))
    asyncio.run(mcp.call_tool("add_step", {"step_id": "b.1", "name": "Baseline"}))
    asyncio.run(mcp.call_tool("add_step", {"step_id": "b.2", "name": "Baseline, again"}))

    said = json.loads(
        _text(asyncio.run(mcp.call_tool("skip_step", {"step_id": "b.1", "superseded_by": "b.2"})))
    )

    assert said["recorded"] is True, said
    events = [
        json.loads(line)
        for line in (tmp_path / "process" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    skipped = [e for e in events if e.get("type") == "step_skipped"]
    assert len(skipped) == 1
    assert skipped[0]["superseded_by"] == "b.2"
    assert not skipped[0].get("reason")


def test_a_skip_with_no_why_is_refused_the_way_a_close_with_no_evidence_is(tmp_path):
    """The model is the one skipping steps here -- there is no button for it -- so the moment the
    tool is called is the only moment the why still exists."""
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    asyncio.run(mcp.call_tool("enter_phase", {"phase": "-1"}))
    asyncio.run(mcp.call_tool("add_step", {"step_id": "b.1", "name": "Baseline"}))

    said = json.loads(_text(asyncio.run(mcp.call_tool("skip_step", {"step_id": "b.1"}))))

    assert said["recorded"] is False
    assert "reason" in said["error"]


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


def test_the_state_says_how_hard_this_session_was_asked_to_think(tmp_path):
    """A record that names the model but not its effort does not say what ran: the same model at
    `high` and at `max` is two different reviewers of its own work. Unlike the model, there is no
    honest "not chosen" here — some level always runs, so an unset project reads as the default."""
    from autosound_tcc.core import config, project_settings

    mcp, _bus, _registry = _server(tmp_path, HeadlessBridge(tmp_path))

    state = json.loads(_text(asyncio.run(mcp.call_tool("get_tcc_state", {}))))
    assert state["effort"] == "xhigh"

    project_settings.set_value(config.tcc_dir(tmp_path), "effort", "max")
    state = json.loads(_text(asyncio.run(mcp.call_tool("get_tcc_state", {}))))
    assert state["effort"] == "max"


def test_get_pending_signals_keeps_a_signal_until_it_is_acked(tmp_path):
    """F-009: this call used to drain, so a signal read by a turn that did nothing with it was
    gone. Now reading is delivery, not handling -- the same open request comes back."""
    mcp, bus, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    bus.push(NOT_VISIBLE, note="band 3 missing")

    first = json.loads(_text(asyncio.run(mcp.call_tool("get_pending_signals", {}))))
    second = json.loads(_text(asyncio.run(mcp.call_tool("get_pending_signals", {}))))

    assert first["count"] == 1
    assert first["signals"][0]["payload"]["note"] == "band 3 missing"
    assert "ack_signals" in first["_ack"]  # the way out rides with the delivery
    assert second["count"] == 1  # un-acked, so still on the books


def test_an_acked_signal_stays_closed(tmp_path):
    mcp, bus, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    signal = bus.push(NOT_VISIBLE, note="band 3 missing")

    result = json.loads(_text(asyncio.run(
        mcp.call_tool("ack_signals", {"ids": [signal.id], "outcome": "applied"})
    )))
    after = json.loads(_text(asyncio.run(mcp.call_tool("get_pending_signals", {}))))

    assert result["acked"] == [signal.id]
    assert after == {"signals": [], "count": 0}  # and no ack reminder on an empty queue


def test_a_refusal_without_a_reason_is_rejected(tmp_path):
    """`refused` is an answer to the Arbiter, and "no" with no why is not one."""
    mcp, bus, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    signal = bus.push(PARAM_EDIT_MODE, on=True)

    result = json.loads(_text(asyncio.run(
        mcp.call_tool("ack_signals", {"ids": [signal.id], "outcome": "refused"})
    )))

    assert "error" in result
    assert bus.pending_count == 1  # nothing was closed


def test_an_invented_outcome_is_rejected(tmp_path):
    mcp, bus, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    signal = bus.push(PARAM_EDIT_MODE, on=True)

    result = json.loads(_text(asyncio.run(
        mcp.call_tool("ack_signals", {"ids": [signal.id], "outcome": "handled"})
    )))

    assert "error" in result
    assert bus.pending_count == 1


def test_an_unknown_id_comes_back_as_a_fact_not_an_error(tmp_path):
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    result = json.loads(_text(asyncio.run(
        mcp.call_tool("ack_signals", {"ids": ["not-an-id"], "outcome": "applied"})
    )))

    assert result["acked"] == []
    assert result["unknown_ids"] == ["not-an-id"]


def test_get_tcc_state_is_loud_about_open_signals(tmp_path):
    """F-009 point 5: `pending_signals: 4` is technically reported and practically invisible.
    Open requests get a sentence -- and only when there are any, because the sentence is spent
    context on every state read otherwise."""
    mcp, bus, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    quiet = json.loads(_text(asyncio.run(mcp.call_tool("get_tcc_state", {}))))
    bus.push(NOT_VISIBLE, note="x")
    loud = json.loads(_text(asyncio.run(mcp.call_tool("get_tcc_state", {}))))

    assert "_signals_waiting" not in quiet
    assert "ack_signals" in loud["_signals_waiting"]
    assert loud["pending_signals"] == 1


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


#: One peaking cut, keyed as REW takes it.
_A_CUT = {"index": 1, "type": "PK", "enabled": True, "frequency": 1000.0, "gaindB": -3.0, "q": 2.0}


def _write_rew_filters(tmp_path) -> dict:
    """`write_rew_filters` of `_A_CUT` to `w-L_10 (sw)`, the Arbiter saying yes: its answer."""
    mcp, _, _ = _server(tmp_path, RecordingBridge(allow=True))
    return json.loads(_text(asyncio.run(mcp.call_tool(
        "write_rew_filters", {"measurement": "w-L_10 (sw)", "filters": [_A_CUT]}))))


def test_rew_down_is_said_and_nothing_is_applied(tmp_path):
    """#176 F4: with REW down, the lookup's own request raised out of `write_rew_filters` and the
    session got a tool error. It answers `applied: false`, with REW's words after `REW: `. REW is
    down here for real: the suite points the method at a port nothing listens on (`_no_live_rew`
    in tests/conftest.py), and the real lookup asks it."""
    with pytest.raises(OSError) as down:  # what the method raises for REW down: a URLError
        mcp_server.vendor_loader.load_rew_api().get_measurements()

    answer = _write_rew_filters(tmp_path)

    assert answer == {"applied": False, "error": f"REW: {down.value}"}


@pytest.mark.parametrize("held, said", [
    ({"1": {"title": "w-R_10 (sw)"}}, "No measurement titled 'w-L_10 (sw)'"),
    ({"1": {"title": "w-L_10 (sw)"}, "2": {"title": "w-L_10 (sw)"}},
     "Ambiguous: 2 measurements titled 'w-L_10 (sw)'"),
], ids=["none", "several"])
def test_a_title_rew_does_not_hold_once_is_said_in_the_methods_words(tmp_path, monkeypatch,
                                                                     held, said):
    """#176 F4: `find_measurement_id` never answers None. It raises a `KeyError` when REW holds no
    measurement by the title and when it holds several, so `if mid is None` was dead and the
    `KeyError` left the tool as an error. The answer has REW down's shape, with the method's own
    words: `exc.args[0]`, since `str()` of a `KeyError` puts them in quotes. Nothing is written.
    The real lookup, over a list REW could answer."""
    rew_api = mcp_server.vendor_loader.load_rew_api()
    monkeypatch.setattr(rew_api, "get_measurements", lambda: held)
    written: list = []
    monkeypatch.setattr(rew_api, "set_filters", lambda mid, filters: written.append(mid))
    with pytest.raises(KeyError) as refused:
        rew_api.find_measurement_id("w-L_10 (sw)", held)

    answer = _write_rew_filters(tmp_path)

    assert answer == {"applied": False, "error": refused.value.args[0]}
    assert answer["error"].startswith(said), answer
    assert written == []


def test_rew_is_asked_and_written_off_the_servers_loop(tmp_path, monkeypatch):
    """#176 F4: the lookup and the write each wait on REW, up to 5 s a request, and both ran on the
    server's loop thread, so every other MCP call waited behind them. They run on a call thread of
    their own (`_in_thread`), as every other tool's blocking work does."""
    rew_api = mcp_server.vendor_loader.load_rew_api()
    ran_on: dict = {}
    written: list = []

    def listed():
        ran_on["lookup"] = threading.current_thread()
        return {"7": {"title": "w-L_10 (sw)"}}

    def write(mid, filters):
        ran_on["write"] = threading.current_thread()
        written.append((mid, filters))
        return {"message": "Filters set"}

    monkeypatch.setattr(rew_api, "get_measurements", listed)
    monkeypatch.setattr(rew_api, "set_filters", write)
    loop_thread = threading.current_thread()  # where `asyncio.run` runs the server's loop

    answer = _write_rew_filters(tmp_path)

    assert answer == {"applied": True, "measurement": "w-L_10 (sw)", "count": 1}
    assert written == [("7", [_A_CUT])]
    assert {step: thread.name for step, thread in ran_on.items()} == {
        "lookup": mcp_server._CALL_THREAD, "write": mcp_server._CALL_THREAD}, ran_on
    assert loop_thread not in ran_on.values()


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


def test_report_phase_on_a_file_that_is_not_a_state_says_it_could_not_be_read(tmp_path):
    """#176: the method reads a cut-off `process-state.json` as the empty process, so the answer
    was «no active_phase -- call enter_phase», sending the agent to record a move it may well have
    recorded. What is true is that the file did not read, and that is the answer."""
    bridge = RecordingBridge(allow=True)
    bridge.refreshes = 0
    mcp, _, registry = _server(tmp_path, bridge)
    (tmp_path / "process").mkdir()
    (tmp_path / "process" / "process-state.json").write_text("{ half", encoding="utf-8")

    result = json.loads(_text(asyncio.run(mcp.call_tool("report_phase", {"phase": "2"}))))

    assert result == {"refreshed": False, "error": "process-state.json could not be read"}
    assert registry.current_phase() is None


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


def test_the_advertisement_is_withdrawn_when_the_server_goes_down(tmp_path, monkeypatch):
    """`.mcp.json` is an advertisement for a server that is LISTENING. After TCC exits it still
    names a port nothing answers on, so a CLI started in the project folder connects to nothing —
    or, worse, to whatever took that port next. The entry belongs to the running process, so it
    goes down with it (SKL-028)."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"theirs": {"type": "http", "url": "http://x/mcp"}}}),
        encoding="utf-8",
    )
    path = write_mcp_config(tmp_path, 8765, "tok")

    mcp_server.forget_mcp_config(tmp_path)

    servers = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"theirs"}, "ours goes, theirs stays"


@pytest.mark.parametrize("damaged", [
    b"{ not json",
    b"[]",
    b'{"mcpServers": {"theirs": "\xff"}}',
    b'{"mcpServers": ' + b"[" * 100_000 + b"]" * 100_000 + b"}",
], ids=["not-json", "not-an-object", "not-utf8", "nested-too-deep"])
def test_withdrawing_an_advertisement_that_is_not_there_is_not_an_error(
        tmp_path, monkeypatch, damaged, app_log_told, app_log_warnings):
    """It runs on the way out, where an exception has nowhere useful to go and would be raised
    while the window is already closing.

    A damaged file is left where it is, byte for byte, and only logged (the review of Task 19,
    I1). The window unhooks its strip before it stops the server, so a file moved aside at quit
    left the folder with nobody told. It holds no entry the withdrawal could take out, and no write
    follows; the next start's write sets it aside into `.tcc/` and says so on the strip."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    path = tmp_path / ".mcp.json"

    mcp_server.forget_mcp_config(tmp_path)  # no file at all
    path.write_bytes(damaged)
    mcp_server.forget_mcp_config(tmp_path)  # the folder alone: any entry of TCC's
    TccMcpServer(project_dir=tmp_path).stop()  # and a quit's own withdrawal

    assert path.read_bytes() == damaged, "left where it is, byte for byte"
    assert not list(tmp_path.glob(".tcc/*")), "nothing under .tcc/"
    assert app_log_told == [], "nothing said: at quit the strip is unhooked already"
    assert any(str(path) in r.getMessage() for r in app_log_warnings), "logged"


def test_the_advertisement_is_readable_only_by_its_owner(tmp_path, monkeypatch):
    """HUB-026: `.mcp.json` carries `X-TCC-Token` in clear text and was written at whatever the
    umask happened to be — readable by every account on the machine. The token is new on every
    start, so a leak is cheap; the file is not, because the method's README tells the user to back
    this folder up to GitHub."""
    import os
    import stat

    if os.name == "nt":
        import pytest as _pytest

        _pytest.skip("POSIX permissions; Windows keeps its ACLs and says so in the log")
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))

    path = write_mcp_config(tmp_path, 8765, "tok")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_writing_the_advertisement_teaches_the_project_to_ignore_it(tmp_path, monkeypatch):
    """The same folder is what the method's README says to back up to a private GitHub. TCC is
    what puts the token there, so TCC is what says it must not travel."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))

    write_mcp_config(tmp_path, 8765, "tok")

    said = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".mcp.json" in said
    assert ".tcc/" in said


def test_an_existing_gitignore_keeps_every_line_it_had(tmp_path, monkeypatch):
    """The user's file, merged and never clobbered — the same rule `.mcp.json` itself follows."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    (tmp_path / ".gitignore").write_text("*.wav\nmy-notes/\n", encoding="utf-8")

    write_mcp_config(tmp_path, 8765, "tok")

    said = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "*.wav" in said and "my-notes/" in said
    assert ".mcp.json" in said and ".tcc/" in said


def test_the_ignore_lines_are_not_added_twice(tmp_path, monkeypatch):
    """A server restarts many times in a session; a file that grows a line each time is a file
    somebody eventually deletes in annoyance."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))

    write_mcp_config(tmp_path, 8765, "tok")
    write_mcp_config(tmp_path, 8766, "tok2")

    said = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert said.count(".mcp.json") == 1
    assert said.count(".tcc/") == 1


def test_a_gitignore_that_cannot_be_written_is_logged_not_raised(
    tmp_path, monkeypatch, app_log_warnings
):
    """A project whose `.gitignore` cannot be written still deserves a running server. The refusal
    went to `app_log.warn`, which does not exist, so the OSError came out as an AttributeError and
    took `write_mcp_config` down with it."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    (tmp_path / ".gitignore").mkdir()  # a folder by that name: reading and writing both refuse

    path = write_mcp_config(tmp_path, 8765, "tok")

    assert path.exists()
    assert any(".gitignore" in r.getMessage() for r in app_log_warnings)


def test_an_advertisement_that_cannot_be_withdrawn_is_logged_not_raised(
    tmp_path, monkeypatch, app_log_warnings
):
    """Withdrawing runs on the way out, where an exception has nowhere to go."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    write_mcp_config(tmp_path, 8765, "tok")

    def refuse(path, body):
        raise PermissionError(13, "refused", str(path))

    monkeypatch.setattr(mcp_server, "_write_atomically", refuse)

    mcp_server.forget_mcp_config(tmp_path)

    assert any(".mcp.json" in r.getMessage() for r in app_log_warnings)


def test_a_withdrawal_reads_an_mcp_json_saved_with_a_byte_order_mark(tmp_path, monkeypatch):
    """The re-review of Task 19, N3. The withdrawal reads `.mcp.json` on its own now (I1), and
    older Windows Notepad saves UTF-8 with a byte-order mark. Read as plain `utf-8`, such a file
    does not parse: every quit would leave this instance's entry behind, naming a dead port for the
    next CLI, with only the log to say so. Read as `utf-8-sig`, this instance's entry is taken out
    and the rest written back."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    path = tmp_path / ".mcp.json"
    theirs = {"type": "http", "url": "http://x/mcp"}
    ours = {"type": "http", "url": "http://127.0.0.1:8765/mcp", "headers": {"X-TCC-Token": "tok"}}
    body = json.dumps({"mcpServers": {"theirs": theirs, "tcc": ours}}, indent=2)
    path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))

    mcp_server.forget_mcp_config(tmp_path, port=8765, token="tok")

    written = path.read_bytes()
    assert b'"tcc"' not in written, "this instance's entry is taken out"
    assert json.loads(written.decode("utf-8")) == {"mcpServers": {"theirs": theirs}}, (
        "and the rest written back")


def test_an_mcp_json_nested_too_deep_to_write_back_is_left_as_it_was(tmp_path, monkeypatch,
                                                                     app_log_warnings):
    """The review of Task 19, M2. `json.dumps(indent=2)` takes the pure-Python encoder, which runs
    out of stack from about 1 000 levels, on nesting `json.loads` still reads, and the
    withdrawal's `except (OSError, ValueError)` let that `RecursionError` out of a function that
    never raises. Now it is logged and the file left as it was. The write raises it into
    `start()`, which keeps it as the advertisement's error, and writes nothing either.

    The parser's reach is the platform's: Python 3.12 gives it a C recursion budget of 3 000 on
    Windows and 10 000 elsewhere, and 3 000 levels failed the Windows runner — the file was set
    aside as broken before it reached the encoder (N1). So the depth is one both read and the
    encoder cannot write, and both halves of that are checked here, not assumed."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    path = tmp_path / ".mcp.json"
    depth = 1_500
    body = (b'{"mcpServers": {"tcc": {"type": "http", "url": "http://127.0.0.1:8765/mcp"}, '
            b'"deep": ' + b"[" * depth + b"]" * depth + b"}}")
    try:
        data = json.loads(body)
    except RecursionError:
        pytest.skip(f"this Python's JSON parser cannot read {depth} levels, so no file it reads "
                    "is too deep for the encoder alone")
    try:
        json.dumps(data, indent=2)
    except RecursionError:
        pass
    else:
        pytest.fail(f"the indented encoder wrote {depth} levels: this depth no longer reaches M2")
    path.write_bytes(body)

    mcp_server.forget_mcp_config(tmp_path)
    assert path.read_bytes() == body, "the withdrawal leaves it as it was"
    assert any(str(path) in r.getMessage() for r in app_log_warnings), "and logs it"

    with pytest.raises(RecursionError):
        write_mcp_config(tmp_path, 8765, "tok")
    assert path.read_bytes() == body, "the write writes nothing"


def test_an_advertisement_whose_mode_cannot_be_set_is_logged_not_raised(
    tmp_path, monkeypatch, app_log_warnings
):
    """Owner-only is asked for, and a filesystem that refuses the mode still gets the file."""
    import os

    if os.name == "nt":
        pytest.skip("POSIX permissions; Windows keeps its ACLs")
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))

    def refuse(path, mode):
        raise PermissionError(1, "not permitted", str(path))

    monkeypatch.setattr(mcp_server.os, "chmod", refuse)

    path = write_mcp_config(tmp_path, 8765, "tok")

    assert "tcc" in json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    assert any(".mcp.json" in r.getMessage() for r in app_log_warnings)


def test_a_gitignore_that_is_not_utf8_is_left_alone(tmp_path, monkeypatch, app_log_warnings):
    """A UTF-16 `.gitignore` (what `"x" > .gitignore` writes in Windows PowerShell 5.1) raised
    UnicodeDecodeError out of `start()` while uvicorn was already serving (the G1 review)."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    ignore = tmp_path / ".gitignore"
    ignore.write_bytes("node_modules/\n".encode("utf-16"))
    before = ignore.read_bytes()

    path = write_mcp_config(tmp_path, 8765, "tok")

    assert "tcc" in json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    assert ignore.read_bytes() == before, "a file that could not be read is not rewritten"
    assert any(".gitignore" in r.getMessage() for r in app_log_warnings)


def test_a_lone_surrogate_in_the_user_s_config_is_written_escaped(tmp_path, monkeypatch):
    """`"\\ud83d"` -- a string cut mid-emoji -- parsed fine and failed the UTF-8 write."""
    from autosound_tcc.core import config

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    path = config.mcp_config_path(tmp_path)
    path.write_text('{"mcpServers": {"other": {"note": "cut \\ud83d"}}}', encoding="utf-8")

    write_mcp_config(tmp_path, 8765, "tok")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"]["note"] == "cut \ud83d" and "tcc" in data["mcpServers"]

    # And taken back out the same way: the withdrawal raised UnicodeEncodeError out of `stop()`,
    # and every quit skipped the rest of its teardown (the branch review).
    mcp_server.forget_mcp_config(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "tcc" not in data["mcpServers"] and data["mcpServers"]["other"]["note"] == "cut \ud83d"


def test_a_stop_survives_an_advertisement_it_cannot_withdraw(tmp_path, monkeypatch):
    """`stop()` runs on the way out: whatever withdrawing raises is logged there, not let through
    into the window's close."""
    def broken(project_dir, port=None, token=None):
        raise ValueError("not this time")

    monkeypatch.setattr(mcp_server, "forget_mcp_config", broken)
    server = TccMcpServer(project_dir=tmp_path)
    server.stop()  # nothing started: only the withdrawal runs, and it raises


def test_start_keeps_any_failure_of_the_advertisement_as_config_error(tmp_path, monkeypatch):
    """The server is up when `.mcp.json` is written; whatever that write raises is the
    advertisement's failure, not the server's."""
    def broken(project_dir, port, token):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(mcp_server, "write_mcp_config", broken)
    server = TccMcpServer(project_dir=tmp_path, preferred_port=8910)
    try:
        server.start(write_config=True)
        assert server.serving
        assert server.config_error.startswith("UnicodeDecodeError")
    finally:
        server.stop()


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
        assert server.serving and server.stopped_reason is None, "a live server is not dead"
        assert server.config_error == ""
    finally:
        server.stop()

    assert server._thread is None
    assert server.stopped_reason is None, "a stop is not a death"


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


def test_check_existing_profile_reads_the_library_with_the_interviews_own_copy(tmp_path, monkeypatch):
    """#169: `find_bundled` runs a script of the method too, so it runs the copy of the project the
    interview is for — not the current project's, which a server or a terminal started on another
    folder need not share. Here the current project's copy is refused while the interview's is not,
    and the library is read all the same."""
    from autosound_tcc.core import vendor_loader

    bundled = _bundled_dir_with(tmp_path, "Audiotec-Fischer", "Helix DSP Ultra S")
    monkeypatch.setattr(mcp_server.config, "bundled_profiles_dir", lambda: bundled)
    current = tmp_path / "current-car"
    (current / ".claude" / "skills" / vendor_loader.SKILL_NAME).mkdir(parents=True)
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(current))
    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    mcp, _, _ = _server(project_dir, HeadlessBridge(project_dir))

    result = json.loads(_text(asyncio.run(mcp.call_tool(
        "check_existing_profile", {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"},
    ))))

    assert "error" not in result, result
    assert result["bundled_exact_match"]["vendor"] == "Audiotec-Fischer"


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


def test_check_existing_profile_finds_the_musway_of_the_skills_library(tmp_path):
    """#175 D-1 (F8): TCC read its own folder, which held one Helix file, so an interview for the
    method's Musway found no bundled profile. The model is spelled as the library spells it,
    variant and all -- the 512K is another processor (the profile's `_open_questions`), the
    match stays exact (`..._is_strict_no_fuzzy_matching`), and the picker supplies the strings."""
    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    mcp, _, _ = _server(project_dir, HeadlessBridge(project_dir))

    result = json.loads(_text(asyncio.run(mcp.call_tool(
        "check_existing_profile", {"vendor": "Musway", "model": "M6V4 (no 512K)"},
    ))))

    assert "error" not in result, result
    match = result["bundled_exact_match"]
    assert match is not None, "the method's library has this Musway and the tool did not find it"
    assert (match["vendor"], match["name"]) == ("Musway", "M6V4 (no 512K)")
    assert "dsp_profile" not in match


def test_a_skill_older_than_the_library_answers_no_match_and_runs_no_lookup(tmp_path, monkeypatch):
    """`bundled_dir` arrived with the method's library, in v3.0.19, and the loader takes an older
    3.0 skill all the same (the map's note 11). There is no library then, so no match: the draft
    and its questions come back as ever, and no lookup runs against a folder that is not there."""
    import types

    from autosound_tcc.core import profile_writer, vendor_loader

    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    mcp, _, _ = _server(project_dir, HeadlessBridge(project_dir))
    monkeypatch.setattr(vendor_loader, "load_dsp_profile", lambda: types.SimpleNamespace())
    ran = []
    run = profile_writer._run

    def recorded(project, args, *rest, **kwargs):
        ran.append(args[0])
        return run(project, args, *rest, **kwargs)

    monkeypatch.setattr(profile_writer, "_run", recorded)

    result = json.loads(_text(asyncio.run(mcp.call_tool(
        "check_existing_profile", {"vendor": "Musway", "model": "M6V4 (no 512K)"},
    ))))

    assert mcp_server.config.bundled_profiles_dir() is None
    assert "error" not in result, result
    assert result["bundled_exact_match"] is None
    assert "open_questions" in result
    assert ran == ["start"], ran


def test_the_library_is_read_on_the_servers_loop_from_a_module_loaded_when_it_was_built(
        tmp_path, monkeypatch):
    """`check_existing_profile` asks `config.bundled_profiles_dir()`, which loads the method's
    `dsp_profile.py` (#175 D-1). In the app a tool runs on the server's own thread (`tcc-mcp`), and
    a method module's first load there is a worker loading the method (#172). It is not the first:
    `build_server` loads the module on the thread that builds it -- the field vocabulary in
    `save_profile_field`'s description; in the app the GUI thread, `TccMcpServer.start` -- so on the
    loop it comes out of `sys.modules`, under `vendor_loader._LOCK`. Here the tool runs on a thread
    of its own, as in the app, with the import guard watching it."""
    from autosound_tcc.core import vendor_loader

    name = vendor_loader._VENDORED["dsp_profile.py"]
    first_loads = []
    load = vendor_loader._load_file_locked

    def watched(path, module_name):
        if module_name == name and module_name not in sys.modules:
            first_loads.append(threading.get_ident())
        return load(path, module_name)

    monkeypatch.setattr(vendor_loader, "_load_file_locked", watched)
    monkeypatch.delitem(sys.modules, name, raising=False)  # as it was again when the test ends
    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    mcp, _, _ = _server(project_dir, HeadlessBridge(project_dir))
    assert first_loads == [threading.get_ident()], "the build did not load the module"

    answers = []
    loop = threading.Thread(target=lambda: answers.append(_text(asyncio.run(mcp.call_tool(
        "check_existing_profile", {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"},
    )))), name="tcc-mcp", daemon=True)
    loop.start()
    loop.join(60)

    assert not loop.is_alive(), "the tool did not answer"
    assert first_loads == [threading.get_ident()], "the loop's thread loaded the module itself"
    assert json.loads(answers[0])["bundled_exact_match"]["vendor"] == "Audiotec-Fischer"


def test_save_reset_and_finalize_profile_round_trip(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    mcp, _, _ = _server(project_dir, HeadlessBridge(project_dir))

    asyncio.run(mcp.call_tool("check_existing_profile", {"vendor": "Musway", "model": "M6V4"}))
    asyncio.run(mcp.call_tool("save_profile_field", {"path": "dsp_processing_rate_hz", "value": 96000}))
    asyncio.run(mcp.call_tool("save_profile_field", {"path": "groups.0.id", "value": "physical_outputs"}))
    asyncio.run(mcp.call_tool("save_profile_field", {"path": "groups.0.label", "value": "Output channels"}))
    asyncio.run(mcp.call_tool("save_profile_field", {"path": "groups.0.fields", "value": ["hp", "lp"]}))

    reset_result = json.loads(
        _text(asyncio.run(mcp.call_tool("reset_profile_field", {"path": "dsp_processing_rate_hz"})))
    )
    assert reset_result == {"reset": "dsp_processing_rate_hz", "found": True}

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
    assert "dsp_processing_rate_hz" not in saved  # reset before finalize, must not reappear
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
    # The journal opens with a provenance header since method v3.0.37: `written_by` names the
    # checkout that wrote what follows, by sha, and it is written once per run rather than per
    # event. Asserted rather than filtered away — a stamp nobody checks is a stamp that can go
    # missing quietly, and it is the one thing in the file that says two runs are comparable.
    assert events[0]["type"] == "written_by"
    assert [e["type"] for e in events[1:]] == [
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


def test_the_state_carries_the_reviewer_the_arbiter_picked(
    tmp_path, monkeypatch, real_critic_reaches
):
    """Intake opened every session with "how would you like to set up the Reviewer channel?" —
    about a channel already configured in TCC's footer and one `call_critic` away. A GUI that
    knows something and asks anyway is a chat window with more buttons."""
    from autosound_tcc.core import config, project_settings
    from autosound_tcc.core.mcp_server import _reviewer_state

    # The key's own route: an OMP pick reaches nothing until the method calls through omp (tcc#74).
    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "api:gemini-pro-latest")
    monkeypatch.setenv("GEMINI_API_KEY", "key")  # reachability is now about this machine

    state = _reviewer_state(tmp_path)

    assert state["configured"] is True
    assert "gemini" in state["model"]
    assert state["reachable"] is True  # this machine has the vendor's key
    assert "call_critic" in state["how"]


def test_an_unreachable_reviewer_says_so_rather_than_promising(tmp_path, monkeypatch):
    """A reviewer whose vendor has neither a key nor a CLI on this machine is clipboard-only, and
    the model needs to know before it plans a round around an automatic review."""
    from autosound_tcc.core import config, model_choices, project_settings
    from autosound_tcc.core.mcp_server import _reviewer_state

    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "sdk:claude-opus-5")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(model_choices.shutil, "which", lambda _binary: None)

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


def test_a_capture_round_can_be_recorded_through_the_tools(tmp_path, monkeypatch):
    """SCR-034 through the surface the model actually has: without these it would have to shell out
    to `process.py` for the one kind of process write that has no tool."""
    # No REW, whatever this machine runs: closing reads REW since v3.0.62, and a developer's open
    # REW made the journal differ from CI's (the wave's PR, 2026-09-27).
    monkeypatch.setenv("REW_API_URL", "http://127.0.0.1:9")
    _intake.seed(tmp_path)  # phase 0 does not start on a folder intake never touched
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
    # `written_by` first: the provenance header, method v3.0.37. Checked in full in
    # `test_the_process_tools_actually_write_the_journal`; here it is only stepped over.
    assert types[0] == "written_by"
    assert types[1:5] == [
        "phase_entered",
        "capture_task_issued",
        "capture_taken",
        "capture_skipped",
    ]
    # Since method v3.0.62 (skill #77) closing reads the round against REW before it closes; with
    # no REW it says it did not check, and closes on the record alone.
    assert types[-1] == "capture_round_closed"


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
    _intake.seed(tmp_path)
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


# ---- show_curves: a disagreement about a number, without a picture in it ----------------------


class _CurveBridge(HeadlessBridge):
    def __init__(self, project_dir) -> None:
        super().__init__(project_dir)
        self.shown: list[dict] = []

    def show_curves(self, request):
        self.shown.append(request)


def test_show_curves_puts_the_measurement_and_the_models_reading_on_screen(tmp_path):
    bridge = _CurveBridge(tmp_path)
    mcp, _, _ = _server(tmp_path, bridge)

    out = json.loads(_text(asyncio.run(mcp.call_tool("show_curves", {
        "titles": ["w-L_01 (sw)", "w-R_01 (sw)"],
        "markers": [4.52, 4.78],
        "note": "which of these is the arrival?",
    }))))

    assert out["shown"] is True
    assert bridge.shown[-1]["titles"] == ["w-L_01 (sw)", "w-R_01 (sw)"]
    assert bridge.shown[-1]["markers"] == [4.52, 4.78]
    assert bridge.shown[-1]["note"] == "which of these is the arrival?"


def test_show_curves_returns_at_once_and_says_the_answer_comes_as_a_message(tmp_path):
    """It must not be waited on in a loop: the reply is a human dragging a marker, and it arrives
    as an ordinary message so they can see and edit it first."""
    bridge = _CurveBridge(tmp_path)
    mcp, _, _ = _server(tmp_path, bridge)

    out = json.loads(_text(asyncio.run(mcp.call_tool("show_curves", {"titles": ["sub_01 (sw)"]}))))

    assert "message" in out["next"] and "end your turn" in out["next"]


def test_show_curves_refuses_an_empty_request_rather_than_opening_an_empty_window(tmp_path):
    bridge = _CurveBridge(tmp_path)
    mcp, _, _ = _server(tmp_path, bridge)

    out = json.loads(_text(asyncio.run(mcp.call_tool("show_curves", {"titles": ["", "  "]}))))

    assert out["shown"] is False and bridge.shown == []


def test_an_unknown_curve_kind_falls_back_to_the_impulse_rather_than_failing(tmp_path):
    bridge = _CurveBridge(tmp_path)
    mcp, _, _ = _server(tmp_path, bridge)

    asyncio.run(mcp.call_tool("show_curves", {"titles": ["sub_01 (sw)"], "kind": "waterfall"}))

    assert bridge.shown[-1]["kind"] == "impulse"


def test_call_critic_defaults_to_the_model_the_footer_is_set_to(tmp_path, monkeypatch):
    """TCC's picker steered nothing: with no explicit model the call went out with none, the
    reviewer script used its own built-in, and the session's routing test caught the UI showing
    `gemini-3.1-pro-high` while the API was called with `gemini-3.6-flash-high` (2026-08-12). The
    substitution happened BEFORE any fallback — there was nothing to fall back from."""
    from autosound_tcc.core import config, critic, mcp_server, model_choices, project_settings

    monkeypatch.setattr(model_choices, "_CLI_CACHE",
                        {"agy": [model_choices.Choice(harness="agy", model="gemini-3.1-pro-high",
                                                      label="Gemini 3.1 Pro (High)",
                                                      provider="google")]})
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")
    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "agy:gemini-3.1-pro-high")

    assert mcp_server.configured_critic_model(tmp_path) == "gemini-3.1-pro-high"

    seen = {}

    def _fake_run(package, project_dir=None, trace_path=None, model=None, **kw):
        seen["model"] = model
        return critic.CriticResult(critic.MODE_ERROR, "", None, "critic", "stub", 0.0, "now")

    monkeypatch.setattr(critic, "run", _fake_run)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    asyncio.run(mcp.call_tool("call_critic", {"package": "hello"}))

    assert seen["model"] == "gemini-3.1-pro-high", "the Arbiter's pick must reach the call"


def test_a_critique_is_recorded_against_the_step_it_was_called_on(tmp_path, monkeypatch):
    """SKL-026: `record_reviewer` has taken a `step` since it was written, and the tool never
    passed one — so the journal said a review happened and could not say what it was about, and
    the step's own gate could not see it. The break this catches is the missing argument."""
    from autosound_tcc.core import critic, process_writer

    monkeypatch.setattr(
        critic,
        "run",
        lambda package, **kw: critic.CriticResult(
            critic.MODE_API_OR_CLI, "looks fine", "review.md", "critic", "gemini-3.1-pro", 1.0, "now"
        ),
    )
    seen = {}
    monkeypatch.setattr(
        process_writer,
        "record_reviewer",
        lambda project_dir, **kw: seen.update(kw) or "recorded",
    )
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    asyncio.run(mcp.call_tool("call_critic", {"package": "x", "step": "2.1"}))

    assert seen["step"] == "2.1"


def _a_critique(critic):
    """`critic.run` as it answers a review that ran, its text filed where the method files it."""
    return lambda package, **kw: critic.CriticResult(
        critic.MODE_API_OR_CLI, "looks fine", "gemini-3.1-pro-high", "critic", "", 1.0, "now",
        review="process/reviews/20261008-120000-critic.md")


def test_the_critiques_journal_write_runs_off_the_servers_loop(tmp_path, monkeypatch):
    """Fable m2 on G5+G8: `call_critic` wrote the journal on the server's own loop thread, so
    `spawn` waited the full `LOCK_WAIT_S` there for the project's lock — and behind a 120 s
    `check_captures`, every MCP call stalled for up to a minute, then lost the write as busy. It
    goes through `_in_thread`, as every other tool's write does: the loop stays free."""
    from autosound_tcc.core import critic, process_writer

    monkeypatch.setattr(critic, "run", _a_critique(critic))
    ran_on: list = []
    monkeypatch.setattr(process_writer, "record_reviewer",
                        lambda project_dir, **kw: ran_on.append(threading.current_thread()) or "ok")
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    loop_thread = threading.current_thread()  # where `asyncio.run` runs the server's loop

    asyncio.run(mcp.call_tool("call_critic", {"package": "x", "step": "2.1"}))

    assert [thread.name for thread in ran_on] == [mcp_server._CALL_THREAD], \
        f"the journal write ran on {ran_on}, not on a call thread of its own"
    assert ran_on[0] is not loop_thread


@pytest.mark.parametrize("dropped", ["the method's refusal", "too old", "busy", "refused"])
def test_a_critique_the_journal_did_not_take_leaves_one_warning(tmp_path, monkeypatch,
                                                                 app_log_warnings, dropped):
    """Fable m2: a critique that ran must not fail over its own bookkeeping, so a journal write
    that failed was dropped — with no word for a non-zero exit or a copy too old for the command,
    the half `spawn` does not log (it says a busy, refused, cut or unstartable run). One WARNING
    names the critique the journal lost — its file, its model, its step — and why; the critique
    still reaches the session."""
    from autosound_tcc.core import critic, process_writer

    error = {
        "the method's refusal": process_writer.ProcessWriterError("error: no step 2.9 in the plan"),
        "too old": process_writer.TooOld("this project's method is older than `reviewer --review`"),
        "busy": process_writer.Busy("busy: another write to this project is still running"),
        "refused": process_writer.Refused("the project's copy of the method is not one TCC runs"),
    }[dropped]

    def record(project_dir, **kw):
        raise error

    monkeypatch.setattr(critic, "run", _a_critique(critic))
    monkeypatch.setattr(process_writer, "record_reviewer", record)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    app_log_warnings.clear()

    answer = json.loads(_text(asyncio.run(
        mcp.call_tool("call_critic", {"package": "x", "step": "2.9"}))))

    assert answer["critique"] == "looks fine", "the critique still reaches the session"
    said = [record.getMessage() for record in app_log_warnings]
    assert said == ["not recorded: the review process/reviews/20261008-120000-critic.md by "
                    f"gemini-3.1-pro-high for step 2.9 is not in the journal: {error}"], said


def test_the_whole_session_probe_can_be_asked_for(tmp_path, monkeypatch):
    """`capture-check --session` is the only check that reads the whole shoot side by side —
    levels, loudest/quietest, ctl1→ctl3 drift — and it is step 0.6 of the virtual-first path. The
    tool could not ask for it, so in TCC that step did not exist."""
    from autosound_tcc.core import process_writer

    argv = []
    monkeypatch.setattr(
        process_writer, "_run", lambda project_dir, args, **kw: argv.append(args) or "ok"
    )
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    asyncio.run(mcp.call_tool("check_captures", {"titles": ["w-L_1 (sw)"], "session": True}))

    assert argv == [["capture-check", "w-L_1 (sw)", "--session"]]


def test_stopping_is_reachable_without_a_shell(tmp_path, monkeypatch):
    """SKL-025: `session-close` existed nowhere in TCC — not as a tool, not in the UI. The model
    could only reach it through Bash, and `process.py` is not in the read-only allowlist, so
    saying "we stopped" cost an Arbiter permission dialog. It reports and closes nothing itself."""
    from autosound_tcc.core import process_writer

    monkeypatch.setattr(
        process_writer, "close_session", lambda project_dir: (False, "OPEN ROUND r3 at v_004")
    )
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    said = json.loads(_text(asyncio.run(mcp.call_tool("session_close", {}))))

    assert said["recorded"] is False
    assert "OPEN ROUND r3" in said["said"]


def test_the_knobs_of_the_round_are_written_as_the_skill_spells_them(tmp_path, monkeypatch):
    """`capture-knobs NAME=POS` is a fact about the SERIES: without it `verify_prediction
    --project` refuses with exit 4 (RES-007). The break this catches is a dict serialised any
    other way than the skill's own `NAME=POS` words."""
    from autosound_tcc.core import process_writer

    argv = []
    monkeypatch.setattr(
        process_writer, "_run", lambda project_dir, args, **kw: argv.append(args) or "ok"
    )
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    asyncio.run(
        mcp.call_tool("capture_knobs", {"positions": {"SubRC": "4/4", "RealCenter": "ON"}})
    )

    assert argv == [["capture-knobs", "SubRC=4/4", "RealCenter=ON"]]


def test_the_target_curve_is_set_through_a_tool_not_through_bash(tmp_path, monkeypatch):
    """`enter-phase 1` refuses without a recorded target, so this write is not optional — it is a
    gate the method puts in front of the desk."""
    from autosound_tcc.core import process_writer

    argv = []
    monkeypatch.setattr(
        process_writer, "_run", lambda project_dir, args, **kw: argv.append(args) or "ok"
    )
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    asyncio.run(mcp.call_tool("set_target", {"preset": "FULL", "curve": "EPY"}))

    assert argv == [["target", "FULL", "EPY"]]


def test_the_handoff_prompt_names_only_tools_that_exist(tmp_path):
    """The prompt TCC sends at a stop tells the model which tools to call. Rename a tool and the
    prompt goes stale silently — the model then calls something that is not there and the stop
    half-happens. Not a check on the wording: a check that every backticked name in it is on the
    surface. `_HANDOFF_PROMPT` is prose for a model and the rest of it earns no test."""
    from autosound_tcc.ui.tcc.main_window import _HANDOFF_PROMPT

    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    named = set(re.findall(r"`([a-z_]+)`", _HANDOFF_PROMPT))
    assert named, "the prompt names no tool at all — the stop has no order to follow"
    assert named <= names, f"named in the handoff but not on the surface: {sorted(named - names)}"


def test_no_reviewer_picked_says_so_without_calling_it_unreachable(tmp_path):
    """Two different facts wore one shape: with nothing picked the field was simply ABSENT, which
    a model reads as "unreachable" — and then offers to set up a channel the Arbiter may have
    every intention of picking. `configured: false` with `reachable: null` says the honest thing:
    nobody chose yet, so reachability is not a question that has an answer."""
    from autosound_tcc.core import mcp_server

    state = mcp_server._reviewer_state(tmp_path)

    assert state["configured"] is False
    assert "reachable" in state and state["reachable"] is None


def test_the_advice_never_tells_anyone_to_export_the_key(tmp_path, monkeypatch):
    """HUB-025: the key belongs in `~/.config/autosound/critic-env` and NOT in a shell profile —
    the project folder is one `git push` from leaking it, and `.gitignore` stops none of `git add
    -f`, a folder copy, or a backup that is not git. Advice that says "start from a shell that has
    the key" teaches the exact habit the method forbids."""
    from autosound_tcc.core import config, mcp_server, model_choices, project_settings

    monkeypatch.setattr(model_choices, "critic_reaches", lambda choice: False)
    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "agy:gemini-3.1-pro-high")

    how = mcp_server._reviewer_state(tmp_path)["how"]

    assert "export" not in how.lower()
    assert "Reviewer key" in how, "the advice names where the key is entered now (hub #197)"
    assert "never ask for the key in the chat" in how


def test_a_reviewer_that_cannot_run_yet_does_not_report_a_green_light(tmp_path, monkeypatch):
    """Found by the Generator itself, on a real Windows session (2026-09-09): `get_tcc_state` said
    `reviewer.reachable: true` and `call_critic` came straight back with
    `mode: not_ready, detail: autosound_context.md not found`. Its own words: "reachable is a
    config-level check — not end-to-end. Don't read that green light as 'the Critic works'."

    It is right, and the fix is not to weaken `reachable` — a transport IS configured — but to
    stop the payload implying more than it knows. `critic.preflight` already lists exactly what is
    missing; the state now carries it, so a model reads "configured, and here is why it cannot run
    yet" instead of a green light it has to discover is hollow."""
    from autosound_tcc.core import config, critic, mcp_server, model_choices, project_settings

    monkeypatch.setattr(model_choices, "critic_reaches", lambda choice: True)
    monkeypatch.setattr(
        critic, "preflight", lambda project_dir=None: ["autosound_context.md not found"]
    )
    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "agy:gemini-3.1-pro-high")

    state = mcp_server._reviewer_state(tmp_path)

    assert state["configured"] is True
    assert state["ready"] is False
    assert any("autosound_context.md" in line for line in state["not_ready_because"])


def test_a_flash_reviewer_pick_is_ready_and_carries_the_warning(tmp_path, monkeypatch):
    """Finding 129 (tcc#118): the Arbiter may pick a Flash reviewer. The state says the method does
    not recommend it, and does not call the pick «not ready» for it."""
    from autosound_tcc.core import config, critic, mcp_server, model_choices, project_settings

    monkeypatch.setattr(model_choices, "critic_reaches", lambda choice: True)
    monkeypatch.setattr(critic, "preflight", lambda project_dir=None: [])
    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "agy:gemini-3.8-flash-low")

    state = mcp_server._reviewer_state(tmp_path)

    assert state["warning"] == mcp_server.FLASH_REVIEWER_WARNING
    assert state["ready"] is True and state["not_ready_because"] == []

    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "agy:gemini-3.1-pro-high")
    assert "warning" not in mcp_server._reviewer_state(tmp_path)


def test_a_reviewer_with_nothing_missing_says_it_is_ready(tmp_path, monkeypatch):
    from autosound_tcc.core import config, critic, mcp_server, model_choices, project_settings

    monkeypatch.setattr(model_choices, "critic_reaches", lambda choice: True)
    monkeypatch.setattr(critic, "preflight", lambda project_dir=None: [])
    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "agy:gemini-3.1-pro-high")

    state = mcp_server._reviewer_state(tmp_path)

    assert state["ready"] is True
    assert state["not_ready_because"] == []


def test_an_explicit_model_still_wins_over_the_footer(tmp_path, monkeypatch):
    from autosound_tcc.core import config, critic, project_settings

    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "agy:gemini-3.1-pro-high")
    seen = {}

    def _fake_run(package, project_dir=None, trace_path=None, model=None, **kw):
        seen["model"] = model
        return critic.CriticResult(critic.MODE_ERROR, "", None, "critic", "stub", 0.0, "now")

    monkeypatch.setattr(critic, "run", _fake_run)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    asyncio.run(mcp.call_tool("call_critic", {"package": "x", "model": "gemini-9-pro-high"}))

    assert seen["model"] == "gemini-9-pro-high"


def test_the_log_says_which_model_a_review_asked_for(tmp_path, monkeypatch):
    """Finding 142 (tcc#140): the log said only who ANSWERED, so a review by the reviewer picked
    before read as a fallback of the one picked now — the «!» said «answered by
    gemini-3.1-pro-preview» beside a pick that had just answered its check. Each line says what
    the call asked for: the footer's pick, or the model the session named."""
    from autosound_tcc.core import config, critic, project_settings

    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "agy:gemini-3.1-pro-high")

    def _fake_run(package, project_dir=None, trace_path=None, model=None, **kw):
        return critic.CriticResult(critic.MODE_API_OR_CLI, "fine", "gemini-3.6-flash-high",
                                   "critic", "", 1.0, "2026-10-02T10:00:00+00:00")

    monkeypatch.setattr(critic, "run", _fake_run)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    asyncio.run(mcp.call_tool("call_critic", {"package": "x"}))
    entry = critic.last_call(tmp_path)
    assert (entry["asked"], entry["model"]) == ("gemini-3.1-pro-high", "gemini-3.6-flash-high")

    asyncio.run(mcp.call_tool("call_critic", {"package": "x", "model": "gemini-9-pro-high"}))
    assert critic.last_call(tmp_path)["asked"] == "gemini-9-pro-high"


def test_no_configured_critic_leaves_the_scripts_own_default_alone(tmp_path, monkeypatch):
    """Empty means "nothing chosen", not "choose for them"."""
    from autosound_tcc.core import critic

    seen = {}

    def _fake_run(package, project_dir=None, trace_path=None, model=None, **kw):
        seen["model"] = model
        return critic.CriticResult(critic.MODE_ERROR, "", None, "critic", "stub", 0.0, "now")

    monkeypatch.setattr(critic, "run", _fake_run)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    asyncio.run(mcp.call_tool("call_critic", {"package": "x"}))

    assert seen["model"] is None


def test_a_server_that_dies_as_it_starts_is_a_failure_of_start(monkeypatch, tmp_path):
    """`_ready` says the THREAD started, and it is set before `serve()` is even called — so a
    server that died on its first line reported success, and the only sign was a chat message
    hours later saying it was not running, with no reason attached (user, Windows 11,
    2026-08-19)."""
    import uvicorn

    class _DeadServer:
        started = False

        def __init__(self, config):
            self.config = config

        async def serve(self, sockets=None):
            raise OSError("port 8765 is not available")

    monkeypatch.setattr(uvicorn, "Server", _DeadServer)
    server = mcp_server.TccMcpServer(project_dir=tmp_path)

    with pytest.raises(RuntimeError) as caught:
        server.start(write_config=False)

    assert "port 8765 is not available" in str(caught.value)
    assert server.serving is False


def test_a_slow_start_is_not_treated_as_a_death(monkeypatch, tmp_path):
    """A timeout is not a failure: a slow machine's server is still a server, and killing a
    working one because it took four seconds would be the worse error."""
    import uvicorn

    class _SlowServer:
        started = False

        def __init__(self, config):
            self.config = config

        async def serve(self, sockets=None):
            await asyncio.sleep(30)

    monkeypatch.setattr(uvicorn, "Server", _SlowServer)
    server = mcp_server.TccMcpServer(project_dir=tmp_path)

    port = server.start(write_config=False)  # must not raise

    assert port and server.failure is None
    server.stop(timeout=0.1)


def test_the_server_starts_in_a_process_with_no_stdout(monkeypatch, tmp_path):
    """A windowed process on Windows has no stdout — `sys.stdout` is None — and uvicorn's default
    log config builds a colour formatter that calls `sys.stdout.isatty()`. Constructing the Config
    raised, so TCC came up with no MCP server at all (user, Windows 11, 2026-08-19)."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    server = mcp_server.TccMcpServer(project_dir=tmp_path)
    try:
        port = server.start(write_config=False)
        assert port
    finally:
        server.stop(timeout=2.0)


def test_a_clipboard_fallback_says_why_it_was_always_going_to_be_one(
    tmp_path, monkeypatch, real_critic_reaches
):
    """The tool answered `mode: clipboard` with an empty `detail`, twice in a row, and the model
    reported "the critic returned clipboard, no review" with nothing to act on (user,
    2026-08-23). A designed fallback that cannot explain itself is indistinguishable from a
    fault — and TCC knows the reason without asking the script."""
    from autosound_tcc.core import config, mcp_server, project_settings

    project = tmp_path / "proj"
    (project / ".tcc").mkdir(parents=True)

    # Nothing chosen at all.
    assert "no reviewer is configured" in mcp_server.clipboard_reason(project)

    # An OMP pick goes through omp (tcc#74): whoever is behind the selector, without omp here
    # there is nothing to call it with — and that is what is said, not a vendor question.
    from autosound_tcc.core import critic

    monkeypatch.setattr(critic, "omp_route_available", lambda: True)
    monkeypatch.setattr(mcp_server.model_choices.shutil, "which", lambda name: None)
    project_settings.set_value(config.tcc_dir(project), "critic", "omp:kimi-code/kimi-k2.5")
    said = mcp_server.clipboard_reason(project)
    assert "kimi-code/kimi-k2.5" in said and "omp is not installed" in said, said

    # A model from a vendor no transport here knows.
    project_settings.set_value(config.tcc_dir(project), "critic", "codex:kimi-k2.5")
    said = mcp_server.clipboard_reason(project)
    assert "kimi-k2.5" in said
    assert "Google, Anthropic or OpenAI" in said, said

    # A vendor with a transport, once that transport is actually present, has nothing to explain.
    monkeypatch.setattr(mcp_server.model_choices.shutil, "which",
                        lambda name: "/usr/bin/agy" if name == "agy" else None)
    project_settings.set_value(config.tcc_dir(project), "critic", "agy:gemini-3.1-pro-high")
    assert mcp_server.clipboard_reason(project) == ""



def test_the_cabin_question_reaches_the_model_with_all_three_answers(tmp_path, monkeypatch):
    """`check_existing_profile` gives the processor answer on its own; the cabin one used to
    depend on a session remembering to look, and on the live intake it looked, decided silently,
    and the material sat unused for two days (public `skill#19`).

    The third answer is the one that has to survive the trip: `unknown` is projects that never
    recorded a body, and reporting them as "none" is that same failure a floor down.
    """
    from autosound_tcc.core import car_library

    if not car_library.available():
        pytest.skip("the car library arrived with method v3.0.40")

    other = tmp_path / "silent"
    other.mkdir()
    (other / "project.json").write_text(
        json.dumps({"schema_version": 3, "car": {"make": "VW", "model": "Passat B8"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_server.config, "recent_projects", lambda: [other])
    monkeypatch.setattr(mcp_server.config, "chosen_project_dir", lambda: None)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    got = json.loads(_text(asyncio.run(mcp.call_tool(
        "check_existing_car",
        {"make": "VW", "model": "Passat", "generation": "B8", "body": "sedan"},
    ))))

    assert got["bundled_exact_match"]["slug"] == "vw-passat-b8-sedan"
    assert got["prior_projects"] == []
    assert [u["path"] for u in got["unknown"]] == [str(other)]

    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    said = tools["check_existing_car"].description
    assert "SHOW THIS SEPARATELY" in said, "the model is told not to fold `unknown` into `none`"
    assert "never match on it" in said, "and that the year classifies nothing"
    # And what the answer is bounded BY. "builds WE have done" promised the whole shop; what it
    # can deliver is the folders TCC has been opened on, and nothing said so (tcc#10).
    assert "AMONG THE PROJECTS TCC HAS OPENED" in said
    assert got["searched"] == [str(other)], "the scope travels with the answer"


def test_the_interview_can_record_a_body_because_it_has_no_other_way_to(tmp_path, monkeypatch):
    """`agent_session.BUILTIN_TOOLS` is empty — the in-app interview has no Bash at all — so
    without this tool a TCC-made project could never record its body, and would answer "no body
    recorded" for the rest of its life. Nothing breaks the day it happens; the material is simply
    not there the day somebody looks."""
    from autosound_tcc.core import car_library

    if not car_library.available():
        pytest.skip("the car library arrived with method v3.0.40")

    monkeypatch.setattr(mcp_server.config, "project_dir", lambda: tmp_path)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    said = json.loads(_text(asyncio.run(mcp.call_tool(
        "save_car",
        {"make": "VW", "model": "Passat", "generation": "B8", "body": "sedan", "year": 2018},
    ))))

    assert said["recorded"] is True
    assert said["car"]["body"] == "sedan" and said["car"]["generation"] == "B8"
    saved = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert saved["car"]["make"] == "VW", "written through the method's own writer"


def test_a_car_the_method_refuses_comes_back_as_its_own_sentence(tmp_path, monkeypatch):
    """The tool defaults `generation` and `body` to "", and the method's `set-car` refuses a blank
    part (#169, N9). The answer is that sentence itself — no class name in front of it — so the
    session reads which part to ask the person for; nothing is recorded, nothing is written."""
    from autosound_tcc.core import car_library

    if not car_library.available():
        pytest.skip("the car library arrived with method v3.0.40")

    monkeypatch.setattr(mcp_server.config, "project_dir", lambda: tmp_path)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    said = json.loads(_text(asyncio.run(mcp.call_tool(
        "save_car", {"make": "VW", "model": "Passat", "generation": "B8"},
    ))))

    assert "recorded" not in said, said
    assert said["error"].startswith("the car is four parts and body is blank"), said
    assert not (tmp_path / "project.json").exists(), "nothing was written"


def test_an_unwritable_advertisement_does_not_take_the_server_down(tmp_path, monkeypatch, caplog):
    """From the user's own log (2026-09-06): `PermissionError` on `.mcp.json` escaped `start()`,
    the window said "the MCP server did not start" — about a server that was SERVING — and the
    session then ran with no tools at all. The file is an advertisement for a CLI started in the
    project folder; the in-app session connects by port and token and never reads it."""
    import logging

    from autosound_tcc.core import app_log, mcp_server as mod

    def _refuse(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    # The write goes through a temp file and a rename now (a hidden file cannot be truncated in
    # place on Windows), so this is where a refusal has to be planted.
    monkeypatch.setattr(mod.os, "replace", _refuse)
    server = mod.TccMcpServer(bridge=HeadlessBridge(tmp_path), project_dir=tmp_path)
    try:
        with caplog.at_level(logging.WARNING, logger=app_log.LOGGER_NAME):
            port = server.start()

        assert port, "the server is up"
        assert "PermissionError" in server.config_error
        assert server.config_unreadable is None, "a write that failed is not a read refused"
        assert server.config_unmoved is None, "nor a damaged file whose move was refused"
        assert any("mcp config not written" in r.getMessage() for r in caplog.records)
    finally:
        server.stop()


def test_a_start_that_could_not_read_the_advertisement_keeps_which_file(tmp_path, monkeypatch,
                                                                        app_log_told):
    """The review of Task 19, M4: a read refusal reached the window's advice for a write that
    failed, «Make the project folder writable». `start()` keeps the file it could not read, so the
    window can name it and say to check it instead. A folder in its place is refused everywhere."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    path = tmp_path / ".mcp.json"
    path.mkdir()
    server = TccMcpServer(project_dir=tmp_path, preferred_port=8970)
    try:
        server.start()
        assert server.serving and server.config_error.startswith("StoreUnreadable"), (
            server.config_error)
        assert server.config_unreadable == path and server.config_unmoved is None
    finally:
        server.stop()


def test_a_start_that_could_not_move_a_damaged_advertisement_aside_keeps_it_apart(
        tmp_path, monkeypatch, app_log_told):
    """The re-review of Task 19, N2. A damaged `.mcp.json` whose move into `.tcc/` is refused — a
    read-only project folder, a lock on the rename — is refused as unreadable too, and it got the
    advice for a file that could not be opened: «check that it can be opened», pointing away from
    the cause. It was read. `start()` keeps it apart, so the window can say what fits."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    path = tmp_path / ".mcp.json"
    path.write_bytes(b'{"mcpServers": {"theirs": {}},}')  # a hand edit's trailing comma
    real_replace = os.replace

    def refuse_the_move_aside(src, dst, *args, **kwargs):
        if Path(src) == path:
            raise PermissionError(13, "Permission denied", str(src))
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(own_store.os, "replace", refuse_the_move_aside)
    server = TccMcpServer(project_dir=tmp_path, preferred_port=8990)
    try:
        server.start()
        assert server.serving and server.config_error.startswith("StoreNotSetAside"), (
            server.config_error)
        assert server.config_unmoved == path and server.config_unreadable is None
    finally:
        server.stop()

    assert path.read_bytes() == b'{"mcpServers": {"theirs": {}},}', "never written over"


def test_the_advertisement_is_renamed_over_never_truncated_in_place(tmp_path):
    """`attrib` on the user's machine answered `A   H` — the file was HIDDEN, not read-only, and
    Windows refuses `CREATE_ALWAYS` (which is what `open(..., "w")` does) on a hidden file unless
    the caller repeats the attribute. The refusal arrives as `PermissionError` saying nothing about
    hiding. A rename over the target has no such rule — and is atomic, which a config a CLI parses
    wanted anyway."""
    from autosound_tcc.core import mcp_server as mod

    path = tmp_path / ".mcp.json"
    path.write_text('{"mcpServers": {"other": {"type": "http"}}}', encoding="utf-8")
    inode_before = path.stat().st_ino

    mod.write_mcp_config(tmp_path, 8765, "token")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["tcc"]["url"].endswith(":8765/mcp")
    assert data["mcpServers"]["other"], "somebody else's server is still theirs"
    assert path.stat().st_ino != inode_before, "a new file was renamed over the old one"
    assert not list(tmp_path.glob(".mcp-*.tmp")), "and nothing was left behind"


def test_a_read_only_advertisement_is_written_anyway(tmp_path, monkeypatch):
    """The file is TCC's own advertisement — a read-only flag on it is not a decision anybody made
    about their configuration. Cleared on the last attempt, and said in the log."""
    from autosound_tcc.core import mcp_server as mod

    path = tmp_path / ".mcp.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o444)

    written = mod.write_mcp_config(tmp_path, 8765, "token")

    assert json.loads(written.read_text(encoding="utf-8"))["mcpServers"]["tcc"]["type"] == "http"


def test_an_unreadable_file_is_not_reported_as_hidden(monkeypatch):
    """`GetFileAttributesW` returns a DWORD, and undeclared ctypes makes its error value unreachable.

    All-ones — `INVALID_FILE_ATTRIBUTES`, what the API returns when it cannot read the file at all
    — arrives as a signed `-1` and never equals the `0xFFFFFFFF` it is compared against. The error
    branch is dead, and `-1 & FILE_ATTRIBUTE_HIDDEN` is truthy, so a file that could not be read
    reports back as hidden — and `_rehide` then ORs a bit into a number that is not an attribute
    set. Same class as the truncated handle in `core/child.py`, found by sweeping for it.
    """
    import ctypes

    from autosound_tcc.core import mcp_server

    class _Call:
        def __init__(self, result):
            self.result = result
            self.restype = None
            self.argtypes = None

        def __call__(self, *_args):
            return self.result

    class _FakeKernel32:
        def __init__(self):
            self.GetFileAttributesW = _Call(0xFFFFFFFF)  # "I could not read this"

    fake = _FakeKernel32()

    assert mcp_server._hidden(Path("nowhere.json"), kernel32=fake) is False
    assert fake.GetFileAttributesW.restype is ctypes.c_uint32, "a DWORD is not a signed int"


def test_a_refused_reviewer_is_not_ready_and_says_why_in_one_phrase(tmp_path, monkeypatch):
    """Windows, 2026-09-13: the payload said `ready: true` and the call failed in two seconds —
    "Selected model is not supported in the selected location"."""
    from autosound_tcc.core import availability, config, project_settings
    from autosound_tcc.core.mcp_server import _reviewer_state

    availability.reset()
    key = "agy:gemini-3.1-pro-high"
    project_settings.set_value(config.tcc_dir(tmp_path), "critic", key)
    monkeypatch.setattr("autosound_tcc.core.critic.preflight", lambda _p: [])
    availability.refused(key, availability.LOCATION, "not supported in the selected location")
    try:
        state = _reviewer_state(tmp_path)
    finally:
        availability.reset()

    assert state["ready"] is False
    assert availability.PHRASES[availability.LOCATION] in state["not_ready_because"]


@pytest.mark.parametrize("listed", [True, False], ids=["target-in-catalogue", "target-not-listed"])
def test_a_refusal_under_an_aliased_reviewer_is_where_the_reviewer_is_reported(
        tmp_path, monkeypatch, listed):
    """The call goes to the alias target, and its refusal was filed under the STORED key while
    `get_tcc_state` looks it up under the resolved one — so a refused reviewer read as ready (final
    review, Important 2). `_offer_replacement` writes such an alias whenever a model retires."""
    from autosound_tcc.core import (
        availability, config, critic, mcp_server, model_choices, model_overrides, process_writer,
        project_settings,
    )

    old, new = "agy:gemini-3.0-pro", "agy:gemini-3.1-pro-high"
    if listed:
        monkeypatch.setattr(model_choices, "_CLI_CACHE",
                            {"agy": [model_choices.Choice(harness="agy", model="gemini-3.1-pro-high",
                                                          label="Gemini 3.1 Pro (High)",
                                                          provider="google")]})
        monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")
    project_settings.set_value(config.tcc_dir(tmp_path), "critic", old)
    model_overrides.set_alias(old, new)
    sent = {}

    def _fake_run(package, **kw):
        sent.update(kw)
        return critic.CriticResult(
            critic.MODE_CLIPBOARD, "", None, "critic",
            "error: Selected model is not supported in the selected location.", 1.0, "now")

    monkeypatch.setattr(critic, "run", _fake_run)
    monkeypatch.setattr(critic, "preflight", lambda _p=None: [])
    monkeypatch.setattr(model_choices, "critic_reaches", lambda _c: True)
    monkeypatch.setattr(process_writer, "record_reviewer", lambda project_dir, **kw: "recorded")
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    availability.reset()
    try:
        asyncio.run(mcp.call_tool("call_critic", {"package": "x"}))
        state = mcp_server._reviewer_state(tmp_path)
    finally:
        availability.reset()

    assert (sent["model"], sent["harness"]) == ("gemini-3.1-pro-high", "agy")
    assert state["ready"] is False
    assert availability.PHRASES[availability.LOCATION] in state["not_ready_because"]


def test_a_bookkeeping_failure_does_not_lose_the_critique(tmp_path, monkeypatch):
    """The line right after this one, `process_writer.record_reviewer`, is guarded with exactly
    this reasoning: "a critique that ran must not fail over its own bookkeeping." A raise out of
    `availability.record_reviewer_outcome` must not propagate past a critique already obtained
    and logged via `critic.log_call` -- or `bridge.show_critique` and the returned JSON never see
    it (review finding, fix round 1)."""
    from autosound_tcc.core import availability, critic, process_writer

    monkeypatch.setattr(
        critic,
        "run",
        lambda *a, **k: critic.CriticResult(
            critic.MODE_API_OR_CLI, "the sub is 3 dB hot", "gemini-3.1-pro", "critic", "",
            1.0, "now",
        ),
    )
    monkeypatch.setattr(process_writer, "record_reviewer", lambda project_dir, **kw: "recorded")

    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(availability, "record_reviewer_outcome", _boom)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    result = json.loads(_text(asyncio.run(mcp.call_tool("call_critic", {"package": "x"}))))

    assert result["critique"] == "the sub is 3 dB hot"


def test_a_recorded_session_close_tells_the_window_and_a_later_write_takes_it_back(
        tmp_path, monkeypatch):
    """TEST-FINDINGS 26: after a correct close, quitting still asked "Save before closing?". The
    Arbiter's proposal: the close TCC already hears marks the session saved, and anything the
    session writes after it clears the mark."""
    from autosound_tcc.core import process_writer

    monkeypatch.setattr(process_writer, "close_session",
                        lambda project_dir: (True, "session closed"))
    monkeypatch.setattr(process_writer, "_run", lambda project_dir, args, **kw: "ok")
    bridge = RecordingBridge(allow=True)
    mcp, _, _ = _server(tmp_path, bridge)

    asyncio.run(mcp.call_tool("session_close", {}))
    assert bridge.events == ["closed"]

    asyncio.run(mcp.call_tool("check_captures", {"titles": ["w-L_1 (sw)"]}))
    assert bridge.events == ["closed", "changed"]


def test_a_close_that_names_open_work_marks_nothing(tmp_path, monkeypatch):
    from autosound_tcc.core import process_writer

    monkeypatch.setattr(process_writer, "close_session",
                        lambda project_dir: (False, "OPEN ROUND r3 at v_004"))
    bridge = RecordingBridge(allow=True)
    mcp, _, _ = _server(tmp_path, bridge)

    asyncio.run(mcp.call_tool("session_close", {}))

    assert bridge.events == []



def test_call_critic_takes_the_route_for_one_run_and_a_refusal_names_it(tmp_path, monkeypatch):
    """tcc#59, finding 63: the Generator ran the reviewer script directly for `--via api`, which
    `call_critic` could not ask for, and the reply went to the journal past the window — no Critic
    bubble. Now the tool takes it, and a refusal says to retry through it rather than the script."""
    from autosound_tcc.core import critic

    seen = {}

    def _fake_run(package, project_dir=None, trace_path=None, model=None, via="", **kw):
        seen["via"] = via
        return critic.CriticResult(critic.MODE_REFUSED, "", None, "critic",
                                   "CLI 'agy': The stream was interrupted.", 0.0, "now")

    monkeypatch.setattr(critic, "run", _fake_run)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    out = asyncio.run(mcp.call_tool("call_critic", {"package": "hello", "via": "api"}))
    assert seen["via"] == "api"

    out = asyncio.run(mcp.call_tool("call_critic", {"package": "hello"}))
    text = json.dumps(out, ensure_ascii=False, default=str)
    assert "via" in text and "call_critic" in text


def test_an_omp_reviewer_pick_is_refused_before_anything_runs(tmp_path, monkeypatch):
    """The Arbiter, 2026-09-27: an OMP pick goes through omp or not at all. The reviewer script has
    no omp route yet (hub #216 TCC-034), so `call_critic` says so and calls nothing — it went to
    Google's API as `gemini-3.1-pro` and came back 404 (finding 85). `get_tcc_state` says the same."""
    from autosound_tcc.core import config, critic, project_settings

    monkeypatch.setattr(critic, "omp_route_available", lambda: False)  # a method before v3.0.63
    project_settings.set_value(config.tcc_dir(tmp_path), "critic",
                               "omp:google-antigravity/gemini-3.1-pro-high")
    ran = []
    monkeypatch.setattr(critic, "run", lambda *a, **kw: ran.append(True))
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    out = asyncio.run(mcp.call_tool("call_critic", {"package": "hello"}))
    text = json.dumps(out, ensure_ascii=False, default=str)
    assert ran == []
    assert "omp" in text and "TCC-034" in text

    state = json.dumps(asyncio.run(mcp.call_tool("get_tcc_state", {})), ensure_ascii=False,
                       default=str)
    assert "TCC-034" in state


def test_start_capture_takes_the_methods_plan_when_no_list_is_given(tmp_path, monkeypatch):
    """SKL-054 (hub #214, tcc#77): a request to measure is a round whose list the METHOD gives
    (`--plan`), and the session is handed the list the method printed rather than composing one."""
    from autosound_tcc.core import process_writer

    seen = {}

    def _start(project_dir, version, expected, step="", origin="", plan=False, optional=(),
               start_method=""):
        seen.update(version=version, expected=list(expected), plan=plan,
                    optional=list(optional), start=start_method)
        return "cap_001 — the method's list"

    monkeypatch.setattr(process_writer, "start_capture", _start)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    out = asyncio.run(mcp.call_tool("start_capture", {"version": "61", "optional": ["Ws_61 (sw)"],
                                                      "start": "rta"}))
    assert seen == {"version": "61", "expected": [], "plan": True, "optional": ["Ws_61 (sw)"],
                    "start": "rta"}
    assert "the method's list" in json.dumps(out, ensure_ascii=False, default=str)

    asyncio.run(mcp.call_tool("start_capture", {"version": "61", "expected": ["sw_61 (sw)"]}))
    assert seen["plan"] is False and seen["expected"] == ["sw_61 (sw)"]


def test_with_the_omp_route_an_omp_reviewer_pick_is_called(tmp_path, monkeypatch):
    from autosound_tcc.core import config, critic, project_settings

    monkeypatch.setattr(critic, "omp_route_available", lambda: True)
    project_settings.set_value(config.tcc_dir(tmp_path), "critic",
                               "omp:google-antigravity/gemini-3.1-pro-high")
    seen = {}

    def _fake_run(package, project_dir=None, trace_path=None, model=None, harness="", **kw):
        seen.update(model=model, harness=harness)
        return critic.CriticResult(critic.MODE_ERROR, "", None, "critic", "stub", 0.0, "now")

    monkeypatch.setattr(critic, "run", _fake_run)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    asyncio.run(mcp.call_tool("call_critic", {"package": "hello"}))

    assert seen == {"model": "google-antigravity/gemini-3.1-pro-high", "harness": "omp"}


def test_an_omp_reviewer_pick_is_never_sent_down_another_route(tmp_path, monkeypatch):
    """Finding 98 (tcc#85): after an OMP reviewer refused, TCC's own hint told the session to retry
    `via="api"`, and it did. For an OMP pick that is the Arbiter's rule broken by TCC: the hint is
    not given, and a `via` other than omp is refused before anything runs."""
    from autosound_tcc.core import config, critic, project_settings

    monkeypatch.setattr(critic, "omp_route_available", lambda: True)
    project_settings.set_value(config.tcc_dir(tmp_path), "critic",
                               "omp:openai-codex/gpt-5.6-terra")
    ran = []

    def _fake_run(package, **kw):
        ran.append(kw.get("via"))
        return critic.CriticResult(critic.MODE_REFUSED, "", None, "critic",
                                   "· omp: Codex error event: usage_limit_reached", 0.0, "now")

    monkeypatch.setattr(critic, "run", _fake_run)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    out = json.dumps(asyncio.run(mcp.call_tool("call_critic", {"package": "hello"})),
                     ensure_ascii=False, default=str)
    assert 'via="api"' not in out and "via=\\\\\"api\\\\\"" not in out
    assert "omp" in out

    out = json.dumps(asyncio.run(mcp.call_tool("call_critic", {"package": "hello", "via": "api"})),
                     ensure_ascii=False, default=str)
    assert ran == [""], "the api retry never ran"
    assert "omp only" in out


def test_the_generators_own_model_is_no_reviewer(tmp_path, monkeypatch):
    """Finding 99 (tcc#85): «OMP · Claude Opus 5» as the reviewer of a Claude Opus 5 session hung
    twice with no output — the method's warned deadlock; Sonnet answered the same package."""
    from autosound_tcc.core import config, critic, model_choices, project_settings

    monkeypatch.setattr(critic, "omp_route_available", lambda: True)
    generator = model_choices.Choice(harness="omp", model="anthropic/claude-opus-5",
                                     label="Claude Opus 5")
    same = model_choices.Choice(harness="omp", model="anthropic/claude-opus-5", label="Claude Opus 5")
    sdk_same = model_choices.Choice(harness="sdk", model="claude-opus-5", label="Claude Opus 5")
    other = model_choices.Choice(harness="omp", model="anthropic/claude-sonnet-5",
                                 label="Claude Sonnet 5")
    assert model_choices.not_a_reviewer(same, generator=generator) == "self"
    assert model_choices.not_a_reviewer(sdk_same, generator=generator) == "self"
    assert model_choices.not_a_reviewer(other, generator=generator) == ""

    project_settings.set_value(config.tcc_dir(tmp_path), "generator", "omp:anthropic/claude-opus-5")
    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "omp:anthropic/claude-opus-5")
    ran = []
    monkeypatch.setattr(critic, "run", lambda *a, **kw: ran.append(True))
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    out = json.dumps(asyncio.run(mcp.call_tool("call_critic", {"package": "hello"})),
                     ensure_ascii=False, default=str)
    assert ran == [] and "generator" in out


# ---- ask_reviewer: a plain question to the reviewer, through TCC (tcc#116) --------------------


def _stub_reviewer(tmp_path, monkeypatch, body):
    """The method's reviewer script, stood in for by `body` (Python, argv = [task, package]). The
    only fake in these tests: TCC's pick, its refusals, the record and the bubble are the real
    ones."""
    from autosound_tcc.core import critic

    script = tmp_path / "stub_reviewer.py"
    script.write_text("import os, sys\n" + body, encoding="utf-8")
    monkeypatch.setattr(critic, "script_path", lambda: script)
    return script


class _CritiqueBridge(RecordingBridge):
    def __init__(self) -> None:
        super().__init__(allow=True)
        self.critiques: list[dict] = []

    def show_critique(self, critique: dict) -> None:
        self.critiques.append(critique)


def _pick_agy_reviewer(project, monkeypatch):
    from autosound_tcc.core import config, model_choices, project_settings

    monkeypatch.setattr(model_choices, "_CLI_CACHE",
                        {"agy": [model_choices.Choice(harness="agy", model="gemini-3.1-pro-high",
                                                      label="Gemini 3.1 Pro (High)",
                                                      provider="google")]})
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")
    project_settings.set_value(config.tcc_dir(project), "critic", "agy:gemini-3.1-pro-high")


def test_ask_reviewer_runs_the_methods_ask_task_with_tccs_pick_and_records_the_reply(
        tmp_path, monkeypatch):
    """Finding 124: asked to check the Critic «через режим ASK», the session searched TCC's source
    for an ASK mode and sent its question as a Critic review — `call_critic` always runs the
    tuning task, and the session may not run the method's `ask` itself. The door: the method's
    `ask`, TCC's model, the reply filed as `process/reviews/<ts>-ask.md`, an «ASK» bubble, and
    no tuning contract asked for — this project has none."""
    from autosound_tcc.core import critic

    _pick_agy_reviewer(tmp_path, monkeypatch)
    _stub_reviewer(tmp_path, monkeypatch, (
        "question = open(sys.argv[2], encoding='utf-8').read()\n"
        "rel = os.path.join('process', 'reviews', '2026-10-01T10-00-00-' + sys.argv[1] + '.md')\n"
        "os.makedirs(os.path.dirname(rel), exist_ok=True)\n"
        "open(rel, 'w', encoding='utf-8').write('pong')\n"
        "print('>> REVIEW_FILE: ' + rel, file=sys.stderr)\n"
        "print('task=' + sys.argv[1] + ' model=' + os.environ.get('GEMINI_CRITIC_MODEL', 'none'))\n"
        "print(question)\n"
        "print('— [' + sys.argv[1] + ': gemini-3.1-pro-high]')\n"
    ))
    bridge = _CritiqueBridge()
    mcp, _, _ = _server(tmp_path, bridge)

    out = json.loads(_text(asyncio.run(mcp.call_tool(
        "ask_reviewer", {"question": "Are you there?", "context": "Start of the session."}))))

    assert out["mode"] == critic.MODE_API_OR_CLI, out
    assert "task=ask model=gemini-3.1-pro-high" in out["critique"]
    assert "Are you there?" in out["critique"] and "Start of the session." in out["critique"]
    assert out["model"] == "gemini-3.1-pro-high"
    review = "process/reviews/2026-10-01T10-00-00-ask.md"
    assert (tmp_path / review).read_text(encoding="utf-8") == "pong"
    assert bridge.critiques[-1]["role"] == "ask"
    assert bridge.critiques[-1]["review"] == review
    assert json.loads(critic.log_path(tmp_path).read_text(encoding="utf-8")
                      .splitlines()[-1])["role"] == "ask"
    # A question is not a review: the journal's reviewer record is the process's last critique,
    # and a plain question filed there would read as one. A review on the same channel — given the
    # two files a review needs — is filed.
    journal = tmp_path / "process" / "journal.jsonl"
    assert not journal.exists() or '"critic_called"' not in journal.read_text(encoding="utf-8")
    (tmp_path / "rew_analitic").mkdir()
    for name in ("data-contract-template.md", "autosound_context.md"):
        (tmp_path / "rew_analitic" / name).write_text("x", encoding="utf-8")
    asyncio.run(mcp.call_tool("call_critic", {"package": "## proposal"}))
    assert '"critic_called"' in journal.read_text(encoding="utf-8")


@pytest.mark.parametrize("settings, omp_route, reason", [
    pytest.param({"critic": "omp:google-antigravity/gemini-3.1-pro-high"}, False,
                 mcp_server.OMP_REVIEWER_REFUSAL, id="omp-without-its-route"),
    pytest.param({"generator": "omp:anthropic/claude-opus-5",
                  "critic": "omp:anthropic/claude-opus-5"}, True,
                 mcp_server.SELF_REVIEWER_REFUSAL, id="the-generators-own-model"),
])
def test_ask_reviewer_is_refused_for_the_reasons_call_critic_is(
        tmp_path, monkeypatch, settings, omp_route, reason):
    """No route, no call — for a question exactly as for a review (tcc#74, tcc#85)."""
    from autosound_tcc.core import config, critic, project_settings

    monkeypatch.setattr(critic, "omp_route_available", lambda: omp_route)
    for key, value in settings.items():
        project_settings.set_value(config.tcc_dir(tmp_path), key, value)
    ran = tmp_path / "the-script-ran"
    _stub_reviewer(tmp_path, monkeypatch, f"open({str(ran)!r}, 'w').write('yes')\n")
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    asked = json.loads(_text(asyncio.run(mcp.call_tool("ask_reviewer", {"question": "ping?"}))))
    reviewed = json.loads(_text(asyncio.run(mcp.call_tool("call_critic", {"package": "ping?"}))))

    assert not ran.exists(), "nothing was called"
    assert asked["mode"] == critic.MODE_ERROR and asked["detail"] == reason
    assert asked == reviewed


def test_ask_reviewer_with_no_reviewer_picked_says_why_as_call_critic_does(tmp_path, monkeypatch):
    """The script falls to the clipboard with nothing picked; TCC says why, for a question as for
    a review."""
    _stub_reviewer(tmp_path, monkeypatch, (
        "print('▶ РУЧНИЙ РЕЖИМ: БУФЕР ОБМІНУ (CLIPBOARD MODE)', file=sys.stderr)\n"
    ))
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    asked = json.loads(_text(asyncio.run(mcp.call_tool("ask_reviewer", {"question": "ping?"}))))

    assert asked["mode"] == "clipboard"
    assert "no reviewer is configured" in asked["detail"]


def test_an_empty_question_calls_nothing(tmp_path, monkeypatch):
    ran = tmp_path / "the-script-ran"
    _stub_reviewer(tmp_path, monkeypatch, f"open({str(ran)!r}, 'w').write('yes')\n")
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    out = json.loads(_text(asyncio.run(mcp.call_tool("ask_reviewer", {"question": "  "}))))

    assert out["mode"] == "error" and not ran.exists()


def test_the_ask_door_says_it_is_a_question_and_sends_a_review_to_call_critic(tmp_path):
    """The description is all the session reads to choose between the two doors."""
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    said = tools["ask_reviewer"].description

    assert "call_critic" in said and "not a review" in said
    assert set(tools["ask_reviewer"].inputSchema["properties"]) == {"question", "context"}


def test_a_refused_question_is_not_sent_back_through_the_review_door(tmp_path, monkeypatch):
    """A refused review is told to retry `call_critic` with `via="api"` (tcc#59). A refused question
    must not be: `ask_reviewer` takes no `via`, and the hint would send the question back as a
    review — finding 124 the other way round (tcc#116)."""
    _stub_reviewer(tmp_path, monkeypatch, (
        "print('⛔ РЕЦЕНЗІЇ НЕ ОТРИМАНО — нічого не збережено як рецензію:', file=sys.stderr)\n"
        "print(\"   · CLI 'agy': quota exhausted\", file=sys.stderr)\n"
        "print('=' * 50, file=sys.stderr)\n"
        "sys.exit(4)\n"
    ))
    (tmp_path / "rew_analitic").mkdir()
    for name in ("data-contract-template.md", "autosound_context.md"):
        (tmp_path / "rew_analitic" / name).write_text("x", encoding="utf-8")
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    asked = json.loads(_text(asyncio.run(mcp.call_tool("ask_reviewer", {"question": "ping?"}))))
    reviewed = json.loads(_text(asyncio.run(mcp.call_tool("call_critic", {"package": "ping?"}))))

    assert asked["mode"] == reviewed["mode"] == "refused"
    assert "quota exhausted" in asked["detail"]
    assert "call_critic again" not in asked["detail"]
    assert "call_critic again" in reviewed["detail"], "a review still gets its retry"


def test_the_state_says_a_question_needs_no_intake_where_a_review_is_not_ready(
        tmp_path, monkeypatch):
    """Finding 124's folder: «check the Critic at the start» is asked before intake, where the
    state's `ready` is a review's and says no for the two missing files. The session read that no
    and had no other door; the state now names the one that needs neither file (tcc#116)."""
    from autosound_tcc.core import config, critic, model_choices, project_settings

    monkeypatch.setattr(model_choices, "critic_reaches", lambda choice: True)
    project_settings.set_value(config.tcc_dir(tmp_path), "critic", "agy:gemini-3.1-pro-high")

    state = mcp_server._reviewer_state(tmp_path)

    assert state["ready"] is False
    assert any("autosound_context.md" in line for line in state["not_ready_because"])
    assert state["ask"]["ready"] is True and state["ask"]["not_ready_because"] == []
    assert "ask_reviewer" in state["ask"]["how"] and "no intake" in state["ask"]["how"]

    # What holds back the channel holds back a question too.
    monkeypatch.setattr(critic, "omp_route_available", lambda: False)
    project_settings.set_value(config.tcc_dir(tmp_path), "critic",
                               "omp:google-antigravity/gemini-3.1-pro-high")
    state = mcp_server._reviewer_state(tmp_path)
    assert state["ask"]["ready"] is False
    assert mcp_server.OMP_REVIEWER_REFUSAL in state["ask"]["not_ready_because"]


def test_a_pin_the_run_set_aside_is_named_in_the_reviewer_state_for_every_task(
        tmp_path, monkeypatch):
    """Finding 130 (tcc#113): a model pinned in a critic-env outranked the footer's pick. TCC now
    names its pick by the method's `--model` — for a question as for a review, one path (tcc#116)
    — and the state names a pin the run set aside, as the method reported it; a run that sets
    none aside clears it."""
    from autosound_tcc.core import availability

    _pick_agy_reviewer(tmp_path, monkeypatch)
    env_file = tmp_path / ".critic-env"
    _stub_reviewer(tmp_path, monkeypatch, (
        "if len(sys.argv) < 2:\n"
        "    print('Використання: ... [--model <id>] [--provider google|anthropic|openai]')\n"
        "    sys.exit(1)\n"
        "args = sys.argv[1:]\n"
        "pick = args[args.index('--model') + 1]\n"
        "path = os.path.join(os.getcwd(), '.critic-env')\n"
        "pinned = open(path, encoding='utf-8').read().strip() if os.path.isfile(path) else ''\n"
        "provider = args[args.index('--provider') + 1] if '--provider' in args else '-'\n"
        "if pinned:\n"
        "    print(f'>> --model {pick} --provider {provider}: '\n"
        "          f'рецензент цього запуску — {pick} (провайдер google); не діють для нього: '\n"
        "          f'{pinned} ({path}, рядок 1). Для інших запусків закріплене лишається типовим',\n"
        "          file=sys.stderr)\n"
        "print('provider=' + provider)\n"
        "print('— [' + args[0] + ': ' + pick + ']')\n"
    ))
    (tmp_path / "rew_analitic").mkdir()
    for name in ("data-contract-template.md", "autosound_context.md"):
        (tmp_path / "rew_analitic" / name).write_text("x", encoding="utf-8")
    bridge = _CritiqueBridge()
    mcp, _, _ = _server(tmp_path, bridge)
    pin = {"variable": "AUTOSOUND_CRITIC_MODEL", "value": "gpt-5.6-terra", "file": str(env_file),
           "line": 1}
    availability.reset()
    try:
        for tool, args in (("ask_reviewer", {"question": "Are you there?"}),
                           ("call_critic", {"package": "## proposal"})):
            env_file.write_text("AUTOSOUND_CRITIC_MODEL=gpt-5.6-terra\n", encoding="utf-8")
            out = json.loads(_text(asyncio.run(mcp.call_tool(tool, args))))
            assert out["model"] == "gemini-3.1-pro-high", (tool, out)
            assert "provider=google" in out["critique"], "the pick's vendor goes with it"
            assert bridge.critiques[-1]["by_model_flag"] is True
            state = mcp_server._reviewer_state(tmp_path)
            assert state["pins_set_aside"]["pins"] == [pin], (tool, state)
            assert "critic-env" in state["pins_set_aside"]["means"]

            env_file.write_text("", encoding="utf-8")
            asyncio.run(mcp.call_tool(tool, args))
            assert "pins_set_aside" not in mcp_server._reviewer_state(tmp_path), tool
    finally:
        availability.reset()


def test_pins_a_session_named_model_set_aside_are_filed_under_that_model(tmp_path, monkeypatch):
    """tcc#113 review, Minor 3: a session may name its own `model` to `call_critic`. The method names
    the pins against THAT model, and filed under the footer's pick they made the state say the
    pick's run set aside a pin — even one equal to the pick. They go under the model the run named,
    and the pick's own record is left as it was."""
    from autosound_tcc.core import availability, model_choices

    _pick_agy_reviewer(tmp_path, monkeypatch)
    monkeypatch.setattr(model_choices, "critic_reaches", lambda choice: True)
    env_file = tmp_path / ".critic-env"
    env_file.write_text("AUTOSOUND_CRITIC_MODEL=gemini-3.1-pro-high\n", encoding="utf-8")
    _stub_reviewer(tmp_path, monkeypatch, (
        "if len(sys.argv) < 2:\n"
        "    print('Використання: ... [--model <id>] [--provider google|anthropic|openai]')\n"
        "    sys.exit(1)\n"
        "args = sys.argv[1:]\n"
        "pick = args[args.index('--model') + 1]\n"
        "path = os.path.join(os.getcwd(), '.critic-env')\n"
        "print(f'>> --model {pick}: рецензент цього запуску — {pick} (провайдер google); '\n"
        "      f'не діють для нього: AUTOSOUND_CRITIC_MODEL=gemini-3.1-pro-high ({path}, рядок 1). '\n"
        "      'Для інших запусків закріплене лишається типовим', file=sys.stderr)\n"
        "print('answer')\n"
        "print('— [' + args[0] + ': ' + pick + ']')\n"
    ))
    (tmp_path / "rew_analitic").mkdir()
    for name in ("data-contract-template.md", "autosound_context.md"):
        (tmp_path / "rew_analitic" / name).write_text("x", encoding="utf-8")
    mcp, _, _ = _server(tmp_path, _CritiqueBridge())
    earlier = [{"variable": "GEMINI_CRITIC_MODEL", "value": "x", "file": None, "line": None}]
    availability.reset()
    try:
        availability.set_aside("agy:gemini-3.1-pro-high", earlier)
        out = json.loads(_text(asyncio.run(mcp.call_tool(
            "call_critic", {"package": "## proposal", "model": "gemini-2.5-pro"}))))
        assert out["model"] == "gemini-2.5-pro", out
        assert availability.pins_set_aside("agy:gemini-2.5-pro") == [
            {"variable": "AUTOSOUND_CRITIC_MODEL", "value": "gemini-3.1-pro-high",
             "file": str(env_file), "line": 1}]
        assert availability.pins_set_aside("agy:gemini-3.1-pro-high") == earlier
        assert mcp_server._reviewer_state(tmp_path)["pins_set_aside"]["pins"] == earlier
    finally:
        availability.reset()


# ── VM-4 (tcc#113): no refusal hint on a run that answered ───────────────────────────────────────

#: A method that takes `--model` and, before it calls anybody, names the critic-env pin the run set
#: aside (`lost_pins`, hub #226) — the line the VM printed on 2026-10-01.
_SETS_A_PIN_ASIDE = (
    "if len(sys.argv) < 2:\n"
    "    print('Використання: ... [--model <id>] [--provider google|anthropic|openai]')\n"
    "    sys.exit(1)\n"
    "args = sys.argv[1:]\n"
    "pick = args[args.index('--model') + 1]\n"
    "print(f'>> --model {pick} --provider google: рецензент цього запуску — {pick} '\n"
    "      '(провайдер google); не діють для нього: AUTOSOUND_CRITIC_MODEL=gpt-5.6-terra '\n"
    "      '(C:/Users/Tuner/AppData/Roaming/autosound/critic-env, рядок 1). '\n"
    "      'Для інших запусків закріплене лишається типовим', file=sys.stderr)\n"
)


def _reviewer_tools(tmp_path, monkeypatch, body, *, via=""):
    """`ask_reviewer` and `call_critic` over a stub method, each called once: {tool: its answer}.
    With `via`, only `call_critic` — the door that takes it."""
    _pick_agy_reviewer(tmp_path, monkeypatch)
    _stub_reviewer(tmp_path, monkeypatch, _SETS_A_PIN_ASIDE + body)
    (tmp_path / "rew_analitic").mkdir(exist_ok=True)
    for name in ("data-contract-template.md", "autosound_context.md"):
        (tmp_path / "rew_analitic" / name).write_text("x", encoding="utf-8")
    mcp, _, _ = _server(tmp_path, _CritiqueBridge())
    calls = ((("call_critic", {"package": "## proposal", "via": via}),) if via else
             (("ask_reviewer", {"question": "Are you there?"}),
              ("call_critic", {"package": "## proposal"})))
    return {tool: json.loads(_text(asyncio.run(mcp.call_tool(tool, args)))) for tool, args in calls}


def test_a_run_that_answered_carries_no_refusal_hint(tmp_path, monkeypatch):
    """VM-4: `ask_reviewer` answered over the API (gemini, 10.5 s) with a critic-env pin set
    aside, and TCC's result still told the session «the reviewer CLI refused the model it was
    given» — the bare word «model» matched the pins line. An answer is the proof the route works:
    no hint rides on it, through either door."""
    from autosound_tcc.core import availability, critic

    availability.reset()
    try:
        answers = _reviewer_tools(tmp_path, monkeypatch, (
            "print('pong')\n"
            "print('— [' + args[0] + ': ' + pick + ']')\n"))
    finally:
        availability.reset()
    for tool, out in answers.items():
        assert out["mode"] == critic.MODE_API_OR_CLI, (tool, out)
        assert "refused the model" not in out["detail"], (tool, out["detail"])
        assert "What to do" not in out["detail"], (tool, out["detail"])


def test_a_real_model_refusal_still_says_what_to_do(tmp_path, monkeypatch):
    """The CLI's own refusal of the model keeps its hint, the pins line beside it or not."""
    from autosound_tcc.core import availability, critic

    refusal = ('>> ⛔ agy повернув помилку: error: invalid model selection (--model '
               '"gemini-3.5-flash-medium" --effort ""): model gemini-3.5-flash-medium is not '
               'recognized as a known model or custom model in settings')
    availability.reset()
    try:
        answers = _reviewer_tools(tmp_path, monkeypatch, (
            f"print({refusal!r}, file=sys.stderr)\n"
            "print('▶ РУЧНИЙ РЕЖИМ: БУФЕР ОБМІНУ (CLIPBOARD MODE)', file=sys.stderr)\n"))
    finally:
        availability.reset()
    for tool, out in answers.items():
        assert out["mode"] == critic.MODE_CLIPBOARD, (tool, out)
        assert "What to do: the reviewer CLI refused the model" in out["detail"], (tool, out)


#: The method's step down from a failed API call to a CLI, with Gemini's words for a key it does
#: not take — then a CLI answers.
_KEY_REJECTED = (">> Помилка виклику API (Помилка запиту до Gemini API: HTTP Error 400: Bad Request "
                 "— API key not valid. Please pass a valid API key.). Спроба локального CLI...")
_ANSWERS = "print('pong')\nprint('— [' + args[0] + ': ' + pick + ']')\n"


def test_an_answer_after_a_rejected_key_still_says_the_key_costs_time(tmp_path, monkeypatch):
    """VM-4 review, Important 2: the API rejected the key, a CLI answered after it. «Every call
    spends that time first» is true of that run, and its result is the only place a session can
    learn it — through either door, with the pins line beside it and no refusal hint."""
    from autosound_tcc.core import availability, critic

    availability.reset()
    try:
        answers = _reviewer_tools(tmp_path, monkeypatch,
                                  f"print({_KEY_REJECTED!r}, file=sys.stderr)\n" + _ANSWERS)
    finally:
        availability.reset()
    for tool, out in answers.items():
        assert out["mode"] == critic.MODE_API_OR_CLI, (tool, out)
        assert "What to do: `GEMINI_API_KEY` is set and the API rejected it" in out["detail"], (
            tool, out["detail"])
        assert "refused the model" not in out["detail"], (tool, out["detail"])


def test_an_answered_api_run_that_names_its_key_gets_no_key_note(tmp_path, monkeypatch):
    """`--via api` names the key it took (`>> --via api: ключ GEMINI_API_KEY із середовища …`),
    and «api_key» in it read as «the API rejected it» — on a run the API answered."""
    from autosound_tcc.core import availability, critic

    named = (">> --via api: ключ GEMINI_API_KEY із середовища; "
             "/Users/x/.config/autosound/critic-env (рядок 2) гасить його для інших запусків")
    availability.reset()
    try:
        answers = _reviewer_tools(tmp_path, monkeypatch, (
            f"print({named!r}, file=sys.stderr)\n"
            "print('>> REVIEW_ROUTE: api', file=sys.stderr)\n" + _ANSWERS), via="api")
    finally:
        availability.reset()
    out = answers["call_critic"]
    assert out["mode"] == critic.MODE_API_OR_CLI, out
    assert "What to do" not in out["detail"] and "rejected" not in out["detail"], out["detail"]


# ── tcc#129: Anthropic's and OpenAI's rejected key, as urllib's bare «HTTP Error 401» ─────────────

#: The method's stderr for an Anthropic call whose key the API did not take and whose CLI then
#: answered, line for line as it prints it: the call, the step down with urllib's own words (no
#: key named), the CLI, the route, and `_persist_review`'s three lines. The critic keeps the last
#: six, so the line naming the vendor is cut — as on the machine (review of #129, Minor 1).
_ANTHROPIC_401 = (
    "rel = os.path.join('process', 'reviews', '2026-10-02T10-00-00-' + args[0] + '.md')\n"
    "os.makedirs(os.path.dirname(rel), exist_ok=True)\n"
    "open(rel, 'w', encoding='utf-8').write('pong')\n"
    "for line in ('>> Підключення до API (anthropic, ' + pick + '), чекаю до 300 с...',\n"
    "             '>> Помилка виклику API (HTTP Error 401: Unauthorized). Спроба локального CLI...',\n"
    "             \">> Виклик локального CLI 'claude' (anthropic), чекаю до 600 с...\",\n"
    "             '>> REVIEW_ROUTE: cli',\n"
    "             '>> Текст рецензії збережено: ' + rel,\n"
    "             '>> REVIEW_FILE: ' + rel,\n"
    "             '>> Запиши посилання: process.py <project>/process reviewer <vendor> ' + pick\n"
    "             + ' --review ' + rel):\n"
    "    print(line, file=sys.stderr)\n"
)


def test_an_answer_after_a_bare_401_says_the_key_costs_time(tmp_path, monkeypatch):
    """No key word matched «HTTP Error 401: Unauthorized», so an Anthropic or OpenAI key the API
    rejected never got the note, though every call spends that attempt first. With the method's
    real tail the line naming the vendor is gone; the variable is named all the same."""
    from autosound_tcc.core import availability, critic

    availability.reset()
    try:
        answers = _reviewer_tools(tmp_path, monkeypatch, _ANTHROPIC_401 + _ANSWERS)
    finally:
        availability.reset()
    for tool, out in answers.items():
        assert out["mode"] == critic.MODE_API_OR_CLI, (tool, out)
        assert "Підключення до API" not in out["detail"], "the tail is the method's real one"
        assert "What to do: `ANTHROPIC_API_KEY` is set and the API rejected it" in out["detail"], (
            tool, out["detail"])


def test_a_refusal_after_a_bare_401_says_the_key(tmp_path, monkeypatch):
    """A run that did not answer: the method's refusal block names the API rung's words on its own
    line, and the key note comes from there."""
    from autosound_tcc.core import availability, critic

    refused = (
        "print('⛔ РЕЦЕНЗІЇ НЕ ОТРИМАНО — нічого не збережено як рецензію:', file=sys.stderr)\n"
        "print('   · API openai: HTTP Error 401: Unauthorized', file=sys.stderr)\n"
        "print(\"   · CLI 'codex': not signed in\", file=sys.stderr)\n"
        "print('=' * 50, file=sys.stderr)\n"
        "sys.exit(4)\n")
    availability.reset()
    try:
        answers = _reviewer_tools(tmp_path, monkeypatch, refused)
    finally:
        availability.reset()
    for tool, out in answers.items():
        assert out["mode"] == critic.MODE_REFUSED, (tool, out)
        assert "What to do: `OPENAI_API_KEY` is set and the API rejected it" in out["detail"], (
            tool, out["detail"])



def _waited_for_at_exit(thread) -> bool:
    """Whether interpreter exit joins `thread`: a non-daemon thread, or a worker of a
    `concurrent.futures` pool, which `concurrent.futures.thread._python_exit` joins whatever its
    daemon flag -- a pool made on a daemon thread has daemon workers, and they are joined all the
    same (the reviewer measured it: 6.2 s of exit for a 6-s call)."""
    from concurrent.futures import thread as pool_threads

    return not thread.daemon or thread in pool_threads._threads_queues


def test_a_reviewer_call_still_out_does_not_hold_the_exit(tmp_path, monkeypatch):
    """Review of #132, I2 (Ruling 45): `asyncio.to_thread` runs on the loop's default pool, and
    Python joins a pool's workers at exit. A Critic review still out when the window closed --
    `critic.run`, up to 600 s -- kept TCC running with no window, and the TCC update waited on its
    pid. The server's blocking calls run on daemon threads of their own: nothing is left for exit
    to wait on, and the call still comes back with its answer."""
    import threading

    from autosound_tcc.core import critic

    reached, release = threading.Event(), threading.Event()
    ran_on: list = []

    def _slow_review(*_a, **_k):
        ran_on.append(threading.current_thread())
        reached.set()
        release.wait(30)
        return critic.CriticResult(critic.MODE_API_OR_CLI, "the sub is 3 dB hot", "gemini",
                                   "critic", "", 1.0, "2026-10-02T12:00:00+00:00")

    monkeypatch.setattr(critic, "run", _slow_review)
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))
    before = {t for t in threading.enumerate() if _waited_for_at_exit(t)}
    answer: list = []
    caller = threading.Thread(
        target=lambda: answer.append(asyncio.run(mcp.call_tool("call_critic", {"package": "x"}))),
        name="test-mcp-loop", daemon=True)
    caller.start()
    try:
        assert reached.wait(10), "the reviewer was not reached"
        held = {t for t in threading.enumerate() if _waited_for_at_exit(t)} - before
        assert not _waited_for_at_exit(ran_on[0]) and not held, (
            f"exit would wait for {sorted(t.name for t in held | set(ran_on))}")
    finally:
        release.set()
        caller.join(10)
    assert answer and "the sub is 3 dB hot" in _text(answer[0])


def test_a_call_left_running_by_a_test_is_drained_before_the_next(tmp_path):
    """tcc#141: since the MCP calls run on daemon threads (tcc#132), `asyncio.run` no longer joins
    a call at a test's end, so a call one test left running could touch process-wide state in the
    next. The suite drains them after every test (`tests/conftest.py`); this is what it calls."""
    import threading
    import time

    from autosound_tcc.core import mcp_server

    done = threading.Event()
    mcp_server._CALLS.submit(lambda: (time.sleep(0.3), done.set()))

    left = mcp_server.drain_calls(timeout=2.0)

    assert left == 0 and done.is_set()


def test_draining_gives_up_at_its_limit_and_says_how_many_are_left():
    import threading

    from autosound_tcc.core import mcp_server

    release = threading.Event()
    mcp_server._CALLS.submit(release.wait)
    try:
        assert mcp_server.drain_calls(timeout=0.1) == 1
    finally:
        release.set()
        assert mcp_server.drain_calls(timeout=2.0) == 0


def test_a_call_an_earlier_test_left_stuck_costs_a_later_drain_nothing():
    """Night review of tcc#141, M11: the drain joined every live call, so one that never ends -- a
    confirm waiting out its 600 s -- added the whole 2 s to every later test in the worker, and
    named nobody. A test waits for the calls it started, and only those."""
    import threading
    import time

    from autosound_tcc.core import mcp_server

    release = threading.Event()
    mcp_server._CALLS.submit(release.wait)  # an earlier test's, never ending
    try:
        before = mcp_server.calls_out()
        started = time.monotonic()

        left = mcp_server.drain_calls(timeout=2.0, ignore=before)

        assert left == 0 and time.monotonic() - started < 0.5
    finally:
        release.set()
        assert mcp_server.drain_calls(timeout=2.0) == 0


def test_a_call_still_out_is_named_by_the_tool_it_runs():
    """Said once, at its source: which call it is, not only how many (M11)."""
    import asyncio
    import threading

    from autosound_tcc.core import mcp_server

    release = threading.Event()

    def confirm_on_the_arbiter():
        release.wait(10)

    caller = threading.Thread(
        target=lambda: asyncio.run(mcp_server._in_thread(confirm_on_the_arbiter)), daemon=True)
    before = mcp_server.calls_out()
    caller.start()
    try:
        for _ in range(100):
            out = mcp_server.calls_out() - before
            if out:
                break
            threading.Event().wait(0.02)
        assert [mcp_server.call_name(t) for t in out] == [
            "test_a_call_still_out_is_named_by_the_tool_it_runs.<locals>.confirm_on_the_arbiter"]
    finally:
        release.set()
        caller.join(10)
        assert mcp_server.drain_calls(timeout=2.0) == 0


def test_a_server_that_dies_after_a_good_start_reads_dead_and_is_logged(
        monkeypatch, tmp_path, app_log_warnings):
    """The healthy side and the death, through the real serving thread (the G1 review): a gate
    that refused every live server passed every test before; and the death went to no log."""
    import threading

    import uvicorn

    release = threading.Event()

    class _ServerThatDiesLater:
        started = False

        def __init__(self, config):
            self.config, self.should_exit = config, False

        async def serve(self, sockets=None):
            import asyncio

            self.started = True
            while not release.is_set():
                await asyncio.sleep(0.01)
            raise OSError("the socket went away")

    monkeypatch.setattr(uvicorn, "Server", _ServerThatDiesLater)
    server = mcp_server.TccMcpServer(project_dir=tmp_path)
    server.start(write_config=False)
    try:
        assert server.serving and server.stopped_reason is None
        release.set()
        server._thread.join(5)
        assert not server.serving
        assert server.stopped_reason == "OSError: the socket went away"
        assert any("stopped serving" in r.getMessage() for r in app_log_warnings)
    finally:
        server.stop()


def test_a_server_that_stops_on_its_own_says_so(monkeypatch, tmp_path, app_log_warnings):
    """A serve() that returns without `stop()` asking is a server gone with no exception."""
    import uvicorn

    class _ServerThatEnds:
        started = False

        def __init__(self, config):
            self.config, self.should_exit = config, False

        async def serve(self, sockets=None):
            self.started = True

    monkeypatch.setattr(uvicorn, "Server", _ServerThatEnds)
    server = mcp_server.TccMcpServer(project_dir=tmp_path)
    server.start(write_config=False)
    server._thread.join(5)
    assert any("on its own" in r.getMessage() for r in app_log_warnings)
    app_log_warnings.clear()
    server.stop()
    assert not any("on its own" in r.getMessage() for r in app_log_warnings), "a stop is asked for"


def test_a_server_whose_thread_died_is_not_serving_and_says_why(tmp_path):
    """F3c: uvicorn's `started` is set once and never cleared, so `serving` read True for a server
    whose thread had died."""
    import threading
    from types import SimpleNamespace

    from autosound_tcc.core.mcp_server import TccMcpServer

    server = TccMcpServer(project_dir=tmp_path)
    assert server.stopped_reason is None and not server.serving, "never started: nothing to say"

    server._server = SimpleNamespace(started=True)  # uvicorn got up once
    server._thread = threading.Thread(target=lambda: None)
    server._thread.start()
    server._thread.join()
    assert not server.serving
    assert server.stopped_reason == "the MCP server's thread ended"

    server.failure = OSError("p")
    assert server.stopped_reason == "OSError: p"


class _BrokenBar:
    """A confirmation bar that fails instead of answering."""

    def request_confirmation(self, request):
        raise RuntimeError("boom")


class _SilentBar:
    """A confirmation bar nobody answers."""

    def request_confirmation(self, request):
        from concurrent.futures import Future
        return Future()


def test_a_failed_confirmation_is_logged_and_denied(caplog):
    """F3e: the failure read as the Arbiter's «no», with nothing in the log."""
    import asyncio
    import logging

    from autosound_tcc.core import app_log
    from autosound_tcc.core.mcp_server import ConfirmRequest, await_confirmation

    request = ConfirmRequest(tool="bash", title="Allow bash?", detail="rm x")
    with caplog.at_level(logging.WARNING, logger=app_log.LOGGER_NAME):
        allowed = asyncio.run(await_confirmation(_BrokenBar(), request, timeout_s=1.0))

    assert allowed is False
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "boom" in said and "bash" in said and "rm x" in said, "which command, too"


def test_an_unanswered_confirmation_is_a_denial_with_a_trace_not_a_warning(caplog):
    """Nobody answering is not a failure -- but it left nothing in tcc.log at all, and the bar
    stayed up (the G1 review): one INFO line now says what was denied and after how long."""
    import asyncio
    import logging

    from autosound_tcc.core import app_log
    from autosound_tcc.core.mcp_server import ConfirmRequest, await_confirmation

    request = ConfirmRequest(tool="bash", title="Allow bash?", detail="rm x")
    with caplog.at_level(logging.INFO, logger=app_log.LOGGER_NAME):
        allowed = asyncio.run(await_confirmation(_SilentBar(), request, timeout_s=0.05))

    assert allowed is False
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("bash" in r.getMessage() and "no answer" in r.getMessage() for r in caplog.records)


class _TimingOutBar:
    """A bar whose own call fails with TimeoutError -- a broken bridge, not a silent Arbiter."""

    def __init__(self, on_the_future=False):
        self.on_the_future = on_the_future

    def request_confirmation(self, request):
        from concurrent.futures import Future

        if not self.on_the_future:
            raise TimeoutError("the bridge timed out")
        future = Future()
        future.set_exception(TimeoutError("the bar timed out"))
        return future


@pytest.mark.parametrize("on_the_future", [False, True])
def test_a_bridge_s_own_timeout_is_a_failure_not_silence(caplog, on_the_future):
    """Since 3.11 every TimeoutError is asyncio's: the bridge's own was read as «nobody answered»."""
    import asyncio
    import logging

    from autosound_tcc.core import app_log
    from autosound_tcc.core.mcp_server import ConfirmRequest, await_confirmation

    request = ConfirmRequest(tool="bash", title="Allow bash?", detail="rm x")
    with caplog.at_level(logging.WARNING, logger=app_log.LOGGER_NAME):
        allowed = asyncio.run(await_confirmation(_TimingOutBar(on_the_future), request, 5.0))

    assert allowed is False
    assert any("timed out" in r.getMessage() and r.levelno == logging.WARNING
               for r in caplog.records)


def test_a_cancelled_confirmation_is_a_cancel_not_a_denial(caplog):
    """omp's close() cancels a pending gate: that is not a confirmation that failed."""
    import asyncio
    import logging

    from autosound_tcc.core import app_log
    from autosound_tcc.core.mcp_server import ConfirmRequest, await_confirmation

    request = ConfirmRequest(tool="bash", title="Allow bash?", detail="rm x")

    async def run():
        task = asyncio.ensure_future(await_confirmation(_SilentBar(), request, timeout_s=10))
        await asyncio.sleep(0)
        task.cancel()
        await task

    with caplog.at_level(logging.WARNING, logger=app_log.LOGGER_NAME):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run())
    assert not caplog.records


def test_a_tool_s_confirmation_that_fails_is_logged_and_writes_nothing(tmp_path, caplog):
    """The two tools that change the tune ask through `_confirm`; reverting it to the silent
    swallow passed every test before (the G1 review)."""
    import logging

    from autosound_tcc.core import app_log

    bridge = RecordingBridge(allow=True)
    bridge.request_confirmation = _BrokenBar().request_confirmation
    mcp, _, _ = _server(tmp_path, bridge)
    with caplog.at_level(logging.WARNING, logger=app_log.LOGGER_NAME):
        result = json.loads(_text(asyncio.run(
            mcp.call_tool("copy_helix_eq", {"text": "PK 1000 -3 Q2"}))))

    assert result["copied"] is False and bridge.clipboard == []
    assert any("copy_helix_eq" in r.getMessage() and "boom" in r.getMessage()
               for r in caplog.records)


@pytest.mark.parametrize("text", ["[]", "null", "3", '{"mcpServers": [], "other": 1}'])
def test_an_mcp_json_of_the_wrong_shape_neither_raises_nor_stops_the_server(
        tmp_path, text, app_log_told):
    """F16-5: `forget_mcp_config` never raises; `write_mcp_config` raising anything but OSError
    escaped `start()` and took the server down with it.

    And none of them is replaced (#173, the review of Task 19, M3). An `"mcpServers"` that is
    there, not null and not an object was replaced by the write — whatever it held gone from the
    user's file, with no copy and nothing on the strip. Like a file that is not an object, it is
    now the write's to set aside into `.tcc/`, with its bytes, and to say. The withdrawal before it
    leaves the file as it is and says nothing (I1)."""
    from autosound_tcc.core import config

    path = config.mcp_config_path(tmp_path)
    path.write_text(text, encoding="utf-8")

    mcp_server.forget_mcp_config(tmp_path)
    assert path.read_text(encoding="utf-8") == text and app_log_told == [], (
        "the withdrawal leaves it as it is, and says nothing")
    write_mcp_config(tmp_path, 8765, "tok")

    kept = list((tmp_path / ".tcc").glob(".mcp.json.corrupt-*"))
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == text, kept
    assert len(app_log_told) == 1, app_log_told
    assert str(path) in app_log_told[0] and str(kept[0]) in app_log_told[0], app_log_told
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"mcpServers"} and set(data["mcpServers"]) == {"tcc"}, data
    assert data["mcpServers"]["tcc"]["url"] == "http://127.0.0.1:8765/mcp"


def test_an_mcp_servers_of_null_is_taken_for_absent(tmp_path, monkeypatch, app_log_told):
    """Null holds nothing to lose, so it is not a wrong shape: the write puts TCC's entry in its
    place, keeps the user's other keys, and sets nothing aside."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    path = tmp_path / ".mcp.json"
    path.write_text('{"mcpServers": null, "other": 1}', encoding="utf-8")

    write_mcp_config(tmp_path, 8765, "tok")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["other"] == 1 and set(data["mcpServers"]) == {"tcc"}
    assert not list(tmp_path.rglob("*.corrupt-*")) and app_log_told == []


# ---- F16-6 (#173): `.mcp.json` read the store's way, and withdrawn by its own instance only ----


def test_one_instance_s_stop_leaves_another_instance_s_advertisement(tmp_path, monkeypatch):
    """Two TCCs on one project folder share the one `"tcc"` key. B's start wrote over A's entry,
    and A's quit then took B's out: a CLI started in the folder afterwards found no server while B
    was still serving one. A's stop takes out only the entry that names its own port and token."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    path = tmp_path / ".mcp.json"
    a = TccMcpServer(project_dir=tmp_path, preferred_port=8930)
    b = TccMcpServer(project_dir=tmp_path, preferred_port=8950)
    try:
        a.start()
        b.start()
        assert a.port != b.port and a.config_error == b.config_error == ""

        a.stop()

        entry = json.loads(path.read_text(encoding="utf-8"))["mcpServers"].get("tcc")
        assert entry is not None, "A's quit took B's advertisement with it"
        assert entry["url"] == b.url and entry["headers"]["X-TCC-Token"] == b.token
    finally:
        a.stop()
        b.stop()

    assert "tcc" not in json.loads(path.read_text(encoding="utf-8"))["mcpServers"], (
        "and B's own stop takes it")


@pytest.mark.parametrize("port, token", [(8766, "tok"), (8765, "not-tok")],
                         ids=["another-port", "another-token"])
def test_a_withdrawal_takes_only_the_entry_that_names_its_port_and_token(tmp_path, monkeypatch,
                                                                         port, token):
    """Both halves are compared, the token too: a server that stops gives its port back before it
    withdraws its entry, and the next TCC can take that port and write its own entry in between."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    path = write_mcp_config(tmp_path, 8765, "tok")

    mcp_server.forget_mcp_config(tmp_path, port=port, token=token)
    assert "tcc" in json.loads(path.read_text(encoding="utf-8"))["mcpServers"], (
        "another instance's entry stays")

    mcp_server.forget_mcp_config(tmp_path, port=8765, token="tok")
    assert "tcc" not in json.loads(path.read_text(encoding="utf-8"))["mcpServers"]


def test_a_damaged_mcp_json_is_kept_under_tcc_with_the_user_s_servers_and_said(
        tmp_path, monkeypatch, app_log_told):
    """A `.mcp.json` that did not parse was read as empty and replaced with TCC's entry alone: the
    user's other servers gone, and nothing said. Now it goes the store's way — set aside with its
    bytes and said — into `.tcc/`, not beside it (ruling 9): the copy carries the old
    `X-TCC-Token`, git ignores `.tcc/` whole, and it ignores `.mcp.json` only by that exact name."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    path = tmp_path / ".mcp.json"
    damaged = (b'{"mcpServers": {\n'
               b'  "theirs": {"type": "http", "url": "http://x/mcp"},\n'
               b'  "tcc": {"type": "http", "headers": {"X-TCC-Token": "old"}},\n'
               b'}}\n')  # the trailing comma of a hand edit
    path.write_bytes(damaged)

    write_mcp_config(tmp_path, 8765, "tok")

    kept = list((tmp_path / ".tcc").glob(".mcp.json.corrupt-*"))
    assert len(kept) == 1, kept
    assert kept[0].read_bytes() == damaged, "the original bytes, the user's servers among them"
    assert not list(tmp_path.glob(".mcp.json.corrupt-*")), "nothing beside it, where git takes it"
    assert len(app_log_told) == 1, app_log_told
    assert str(path) in app_log_told[0] and str(kept[0]) in app_log_told[0], app_log_told
    servers = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"tcc"} and servers["tcc"]["headers"]["X-TCC-Token"] == "tok"


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0,
                    reason="POSIX permissions, and root reads a file whatever its mode")
def test_an_mcp_json_that_cannot_be_read_is_not_written_over(tmp_path, monkeypatch,
                                                             app_log_told):
    """There and not readable is not empty (W-8's review, F-098). The old read answered `{}` for
    any OSError, and the write renamed a file holding TCC's entry alone over the user's — every
    other server they had configured for the project gone. Now the write refuses, as the store's
    own failure: `start()` keeps it as the advertisement's error, and the server stays up. The
    withdrawal leaves it alone too, and says nothing more."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps({"mcpServers": {"theirs": {"type": "http", "url": "http://x/mcp"}}}),
                    encoding="utf-8")
    before = path.read_bytes()
    path.chmod(0)
    try:
        with pytest.raises(OSError) as refused:
            write_mcp_config(tmp_path, 8765, "tok")
        mcp_server.forget_mcp_config(tmp_path, port=8765, token="tok")
    finally:
        path.chmod(0o600)

    assert path.read_bytes() == before, "never written over"
    assert refused.type is own_store.StoreUnreadable, "refused as the store's own failure"
    assert not list(tmp_path.glob(".mcp*.tmp")) and not list(tmp_path.rglob("*.corrupt-*")), (
        "not set aside, and no temp file left: its bytes may be fine")
    assert len(app_log_told) == 1 and str(path) in app_log_told[0], "said once, not per read"


def test_an_mcp_json_that_cannot_be_opened_is_refused_on_every_platform(tmp_path, monkeypatch,
                                                                        app_log_told):
    """The chmod test above cannot run on Windows. A folder where the file should be is refused
    everywhere — `IsADirectoryError` on POSIX, `PermissionError` on Windows. The old write failed
    here as well, but on its rename and having said nothing: the type tells the two apart."""
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    path = tmp_path / ".mcp.json"
    path.mkdir()
    (path / "inside").write_text("kept", encoding="utf-8")

    with pytest.raises(OSError) as refused:
        write_mcp_config(tmp_path, 8765, "tok")
    assert refused.type is own_store.StoreUnreadable, "refused as the store's own failure"
    mcp_server.forget_mcp_config(tmp_path, port=8765, token="tok")

    assert (path / "inside").read_text(encoding="utf-8") == "kept", "never written over"
    assert not list(tmp_path.glob(".mcp*.tmp")) and not list(tmp_path.rglob("*.corrupt-*")), (
        "not set aside, and no temp file left beside it")
    assert len(app_log_told) == 1 and str(path) in app_log_told[0], "said once, not per read"
