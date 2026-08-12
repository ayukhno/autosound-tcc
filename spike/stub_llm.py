"""A fake OpenAI-compatible model, so the spike costs nothing and never varies.

It does two jobs:
  * records the exact tool catalogue the harness advertises (this is how we see
    whether TCC's MCP tools reached the model at all);
  * answers with one tool call, preferring a TCC tool and falling back to the
    harness's own `bash` — which is enough to trigger the approval gate.

Point a harness at it as if it were LM Studio:
    LM_STUDIO_BASE_URL=http://127.0.0.1:8899/v1  OPENAI_API_KEY=stub
"""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

OUT = Path(os.environ.get("SPIKE_OUT", "/tmp/spike"))
OUT.mkdir(parents=True, exist_ok=True)
LOG = OUT / "llm.log"
CATALOGUE = OUT / "catalogue.json"
PORT = int(os.environ.get("STUB_PORT", "8899"))

# First match wins. `bash` last: it always exists, so the approval gate fires
# even when the MCP tools never made it into the catalogue.
PREFERRED = (os.environ.get("PREFER") or "").split(",") if os.environ.get("PREFER") else [
    "copy_helix_eq", "write_rew_filters", "get_tcc_state", "bash"]
ARGS = {
    "copy_helix_eq": {"text": "SPIKE EQ", "note": "spike"},
    "write_rew_filters": {"measurement": "m1", "filters": []},
    "get_tcc_state": {},
    "bash": {"command": "echo spike", "i": "spike probe"},
    # The harness's own user-question channel — the thing that decides whether a
    # structured question reaches the host, or the window just looks hung.
    "ask": {"i": "spike question", "questions": [{
        "id": "seat", "question": "Reference seat for this tune?",
        "options": [{"label": "Driver", "description": "one point, sharpest image"},
                    {"label": "Both front", "description": "wider zone, softer image"}]}]},
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: ANN002 - silence stock logging
        pass

    def _send(self, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if "/models" in self.path:
            return self._send(json.dumps({"object": "list", "data": [
                {"id": "stub-model", "object": "model", "owned_by": "spike"}]}).encode())
        self._send(b'{"ok":true}')

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(length) or b"{}")
        tools = req.get("tools") or []
        names = [t.get("function", {}).get("name", "") for t in tools]
        if tools and not CATALOGUE.exists():
            CATALOGUE.write_text(json.dumps(tools, indent=2))
        answered = sum(1 for m in req.get("messages", []) if m.get("role") == "tool")
        with LOG.open("a") as fh:
            fh.write(json.dumps({"t": time.time(), "stream": bool(req.get("stream")),
                                 "names": names, "tool_results": answered}) + "\n")

        target = next((n for p in PREFERRED for n in names if p in n), None)
        if target and answered == 0:
            key = next(p for p in PREFERRED if p in target)
            delta = {"role": "assistant", "content": None, "tool_calls": [
                {"index": 0, "id": "call_1", "type": "function",
                 "function": {"name": target, "arguments": json.dumps(ARGS[key])}}]}
            finish = "tool_calls"
        else:
            delta = {"role": "assistant",
                     "content": f"SPIKE DONE. tools={len(names)} tool_results={answered}"}
            finish = "stop"

        usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        if req.get("stream"):
            chunks = [
                {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage},
            ]
            body = "".join(
                "data: " + json.dumps({"id": "c1", "object": "chat.completion.chunk",
                                       "created": int(time.time()), "model": "stub-model", **c}) + "\n\n"
                for c in chunks
            ) + "data: [DONE]\n\n"
            return self._send(body.encode(), "text/event-stream")

        self._send(json.dumps({"id": "c1", "object": "chat.completion",
                               "created": int(time.time()), "model": "stub-model",
                               "choices": [{"index": 0, "message": delta,
                                            "finish_reason": finish}],
                               "usage": usage}).encode())


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
