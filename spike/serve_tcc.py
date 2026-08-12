"""Run TCC's real MCP server headless, with a bridge that logs every Arbiter
confirmation and holds it open — so we can measure whether a harness actually
blocks waiting for the answer.

Also logs the raw JSON-RPC both ways, which is what proves the handshake.

    python spike/serve_tcc.py [project_dir]

Env:
    HOLD_S      seconds to hold each confirmation before allowing (default 6)
    LIFETIME_S  how long to stay up (default 120)
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import Future
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autosound_tcc.core.mcp_server import ConfirmRequest, TccMcpServer  # noqa: E402
import autosound_tcc.core.mcp_server as M  # noqa: E402

OUT = Path(os.environ.get("SPIKE_OUT", "/tmp/spike"))
OUT.mkdir(parents=True, exist_ok=True)
CONFIRM_LOG = OUT / "confirm.log"
HTTP_LOG = OUT / "http.log"
HOLD_S = float(os.environ.get("HOLD_S", "6"))


def _append(path: Path, obj: dict) -> None:
    with path.open("a") as fh:
        fh.write(json.dumps(obj) + "\n")


class SpyBridge:
    """Stands in for the Qt Arbiter: records the ask, answers late, allows."""

    def __init__(self, project_dir: Path) -> None:
        self._p = project_dir

    def snapshot(self) -> dict:
        return {"mode": "spike", "project_dir": str(self._p)}

    def request_confirmation(self, request: ConfirmRequest) -> "Future[bool]":
        fut: "Future[bool]" = Future()
        _append(CONFIRM_LOG, {"t": time.time(), "event": "asked",
                              "tool": request.tool, "detail": request.detail[:200]})

        def _later() -> None:
            time.sleep(HOLD_S)
            _append(CONFIRM_LOG, {"t": time.time(), "event": "allowed", "tool": request.tool})
            fut.set_result(True)

        threading.Thread(target=_later, daemon=True).start()
        return fut

    def copy_to_clipboard(self, text: str) -> None: ...
    def show_proposal(self, proposal: dict) -> None: ...
    def show_critique(self, critique: dict) -> None: ...
    def notify_profile_ready(self) -> None: ...
    def refresh_from_disk(self) -> None: ...


# Wiretap the ASGI layer so the JSON-RPC conversation is visible. Subclassing
# rather than replacing keeps the real token check in the path.
_Orig = M._TokenGuard


class LoggingGuard(_Orig):  # type: ignore[misc, valid-type]
    async def __call__(self, scope, receive, send):  # noqa: ANN001, ANN204
        if scope.get("type") != "http":
            return await _Orig.__call__(self, scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in (scope.get("headers") or [])}
        _append(HTTP_LOG, {"t": time.time(), "path": scope.get("path"),
                           "method": scope.get("method"),
                           "token_present": "x-tcc-token" in headers,
                           "ua": headers.get("user-agent", "")[:60]})
        body = bytearray()

        async def _recv():
            msg = await receive()
            if msg.get("type") == "http.request":
                body.extend(msg.get("body") or b"")
                if not msg.get("more_body"):
                    _append(HTTP_LOG, {"t": time.time(),
                                       "rpc": bytes(body).decode("utf-8", "replace")[:400]})
            return msg

        async def _send(msg):
            if msg.get("type") == "http.response.body" and msg.get("body"):
                _append(HTTP_LOG, {"t": time.time(),
                                   "resp": msg["body"].decode("utf-8", "replace")[:500]})
            return await send(msg)

        return await _Orig.__call__(self, scope, _recv, _send)


M._TokenGuard = LoggingGuard

project = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fx")
project.mkdir(parents=True, exist_ok=True)
server = TccMcpServer(project_dir=project, bridge=SpyBridge(project))
port = server.start()
print(json.dumps({"port": port, "url": server.url, "token": server.token}), flush=True)
time.sleep(float(os.environ.get("LIFETIME_S", "120")))
