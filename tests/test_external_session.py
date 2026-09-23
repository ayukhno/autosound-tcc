"""Finding 41: a session started in a terminal is named in TCC's footer, model and all."""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402
from mcp.types import Implementation  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import config  # noqa: E402
from autosound_tcc.core.mcp_server import HeadlessBridge, build_server  # noqa: E402
from autosound_tcc.core.session_registry import SessionRegistry  # noqa: E402
from autosound_tcc.core.signal_bus import SignalBus  # noqa: E402
from autosound_tcc.ui.tcc import i18n  # noqa: E402


class _Bridge(HeadlessBridge):
    def __init__(self, project_dir):
        super().__init__(project_dir)
        self.sessions: list[dict] = []

    def external_session(self, info: dict) -> None:
        self.sessions.append(info)


def test_the_client_and_the_model_it_names_reach_the_window(tmp_path):
    bridge = _Bridge(tmp_path)
    mcp = build_server(tmp_path, bridge, SignalBus(tmp_path), SessionRegistry(tmp_path))

    async def run():
        async with create_connected_server_and_client_session(
                mcp._mcp_server, client_info=Implementation(name="antigravity-cli", version="1.2")
        ) as client:
            await client.call_tool("get_tcc_state", {"model": "gemini-3.1-pro-high"})
            await client.call_tool("get_tcc_state", {})

    asyncio.run(run())
    assert bridge.sessions[0] == {"client": "antigravity-cli", "version": "1.2",
                                  "model": "gemini-3.1-pro-high"}
    assert bridge.sessions[-1]["model"] == "gemini-3.1-pro-high", \
        "a later call that does not repeat the model does not erase it"


def test_the_footer_names_the_terminal_session(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc.main_window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    window = MainWindow()
    assert window._ext_session_lbl.isHidden()
    window._on_external_session({"client": "antigravity-cli", "version": "1.2",
                                 "model": "gemini-3.1-pro-high"})
    assert not window._ext_session_lbl.isHidden()
    shown = i18n.t("extTerminal").format(who="agy", model="gemini-3.1-pro-high")
    assert window._ext_session_lbl.text() == shown or window._ext_session_lbl.toolTip() == shown \
        or shown in str(getattr(window._ext_session_lbl, "_full", "")), \
        "agy, not the handshake's own name, and the model as the session named it"


def test_the_in_app_session_is_not_mistaken_for_a_terminal_one(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc.main_window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    window = MainWindow()
    window._agent_worker = object()
    try:
        window._on_external_session({"client": "claude-code", "version": "2", "model": "x"})
        assert window._ext_session_lbl.isHidden()
    finally:
        window._agent_worker = None
