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


def _server(tmp_path, bridge):
    bus = SignalBus(tmp_path)
    registry = SessionRegistry(tmp_path)
    return build_server(tmp_path, bridge, bus, registry), bus, registry


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
    }
    # No measurement tool: the panel is still mock data, and serving fabricated sweeps to a model
    # invites EQ computed from numbers that were never measured.
    assert not any("measurement" in name for name in names)


def test_get_tcc_state_reports_ui_phase_and_queue_depth(tmp_path):
    bridge = RecordingBridge(allow=True)
    mcp, bus, registry = _server(tmp_path, bridge)
    registry.record_phase("2", step="2.3")
    bus.push(PARAM_EDIT_MODE, on=True)

    state = json.loads(_text(asyncio.run(mcp.call_tool("get_tcc_state", {}))))

    assert state["ui"] == {"preset": "FULL", "selected": "m_L"}
    assert state["current_phase"] == "2"
    assert state["pending_signals"] == 1


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


def test_report_phase_records_into_the_registry(tmp_path):
    mcp, _, registry = _server(tmp_path, HeadlessBridge(tmp_path))

    asyncio.run(
        mcp.call_tool("report_phase", {"phase": "2", "step": "2.3", "status": "in_progress"})
    )

    assert registry.current_phase() == "2"
    assert registry.load()["phases"]["2"]["step"] == "2.3"


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


def test_capability_checklist_matches_agent_sessions_fixed_list(tmp_path):
    from autosound_tcc.core import agent_session

    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    result = json.loads(_text(asyncio.run(mcp.call_tool("get_capability_checklist", {}))))

    assert result == agent_session.CAPABILITY_CHECKLIST


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
    assert reset_result == {"reset": "sample_rate_hz"}

    finalize_result = json.loads(_text(asyncio.run(mcp.call_tool("finalize_profile", {}))))

    saved_path = project_dir / "dsp_profile.json"
    assert finalize_result == {"saved_to": str(saved_path)}
    saved = json.loads(saved_path.read_text())["dsp_profile"]
    assert saved["groups"][0] == {
        "id": "physical_outputs", "label": "Output channels", "fields": ["hp", "lp"],
    }
    assert "sample_rate_hz" not in saved  # reset before finalize, must not reappear


def test_onboarding_tools_before_check_existing_profile_are_a_clean_error(tmp_path):
    """save/reset/finalize all need the draft check_existing_profile initializes -- an agent that
    skips it (or calls tools out of the documented order) gets a message it can act on, not a
    KeyError/AttributeError traceback."""
    mcp, _, _ = _server(tmp_path, HeadlessBridge(tmp_path))

    for tool, args in (
        ("save_profile_field", {"path": "x", "value": 1}),
        ("reset_profile_field", {"path": "x"}),
        ("finalize_profile", {}),
    ):
        result = json.loads(_text(asyncio.run(mcp.call_tool(tool, args))))
        assert "error" in result
