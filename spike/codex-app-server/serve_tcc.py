"""TCC's real MCP server, headless, for the Codex app-server spike (#181).

Same idea as `spike/serve_tcc.py` (the omp spike): the real `TccMcpServer`, the real
`X-TCC-Token` guard, and a wiretap on the HTTP layer so the MCP JSON-RPC is visible.
The stand-in bridge DENIES every confirmation: the spike only reads.

    .venv/bin/python spike/codex-app-server/serve_tcc.py <project_dir> <out_dir>

Prints one JSON line {port, url, token} and stays up for LIFETIME_S (default 1800).
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import Future
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from autosound_tcc.core.mcp_server import ConfirmRequest, TccMcpServer  # noqa: E402
import autosound_tcc.core.mcp_server as M  # noqa: E402

project = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
HTTP_LOG = OUT / "tcc-http.jsonl"


def _append(obj: dict) -> None:
    with HTTP_LOG.open("a") as fh:
        fh.write(json.dumps(obj) + "\n")


class DenyBridge:
    def __init__(self, project_dir: Path) -> None:
        self._p = project_dir

    def snapshot(self) -> dict:
        return {"mode": "spike", "project_dir": str(self._p)}

    def request_confirmation(self, request: ConfirmRequest) -> "Future[bool]":
        _append({"t": time.time(), "confirm_asked": request.tool, "answer": "deny"})
        fut: "Future[bool]" = Future()
        fut.set_result(False)
        return fut

    def copy_to_clipboard(self, text: str) -> None: ...
    def show_proposal(self, proposal: dict) -> None: ...
    def show_critique(self, critique: dict) -> None: ...
    def notify_profile_ready(self) -> None: ...
    def refresh_from_disk(self) -> None: ...


_Orig = M._TokenGuard


class LoggingGuard(_Orig):  # type: ignore[misc, valid-type]
    async def __call__(self, scope, receive, send):  # noqa: ANN001, ANN204
        if scope.get("type") != "http":
            return await _Orig.__call__(self, scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in (scope.get("headers") or [])}
        _append({"t": time.time(), "method": scope.get("method"), "path": scope.get("path"),
                 "token_present": "x-tcc-token" in headers,
                 "ua": headers.get("user-agent", "")[:60]})
        body = bytearray()

        async def _recv():
            msg = await receive()
            if msg.get("type") == "http.request":
                body.extend(msg.get("body") or b"")
                if not msg.get("more_body") and body:
                    _append({"t": time.time(), "rpc": bytes(body).decode("utf-8", "replace")[:600]})
            return msg

        async def _send(msg):
            if msg.get("type") == "http.response.start":
                _append({"t": time.time(), "status": msg.get("status")})
            if msg.get("type") == "http.response.body" and msg.get("body"):
                _append({"t": time.time(), "resp": msg["body"].decode("utf-8", "replace")[:600]})
            return await send(msg)

        return await _Orig.__call__(self, scope, _recv, _send)


M._TokenGuard = LoggingGuard

project.mkdir(parents=True, exist_ok=True)
server = TccMcpServer(project_dir=project, bridge=DenyBridge(project))
port = server.start()
print(json.dumps({"port": port, "url": server.url, "token": server.token}), flush=True)
time.sleep(float(os.environ.get("LIFETIME_S", "1800")))
