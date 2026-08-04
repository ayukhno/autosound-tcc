"""Same two questions as `rpc_driver.py`, asked of OpenCode instead of omp.

OpenCode has no stdio host protocol — it exposes an HTTP server (`opencode serve`) with an
OpenAPI spec, so the host role is played over REST + an SSE event stream:

    GET  /event                        server-sent events, including `permission.asked`
    POST /permission/{requestID}/reply the host's answer
    POST /session, /session/{id}/message

Answers late on purpose, so the gap between the ask and the tool result shows whether the
agent actually blocked on us.

    python spike/oc_driver.py            (expects serve_tcc.py + stub_llm.py already running)

Env: OC_PORT, ANSWER_DELAY, ANSWER (allow|reject|always), RUN_S, PROJECT_DIR
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

BASE = f"http://127.0.0.1:{os.environ.get('OC_PORT', '4096')}"
ANSWER_DELAY = float(os.environ.get("ANSWER_DELAY", "6"))
ANSWER = os.environ.get("ANSWER", "always")
T0 = time.time()
seen: dict[str, object] = {"permission_asks": 0, "answered_at": None, "tool_end_at": None,
                           "tools_offered": None}


def log(*parts: object) -> None:
    print(f"[{time.time() - T0:6.2f}s]", *parts, flush=True)


def call(method: str, path: str, body: dict | None = None, timeout: float = 20.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, "_body": exc.read().decode()[:400]}
    except Exception as exc:  # noqa: BLE001 - a dead server is a result, not a crash
        return {"_error": str(exc)}


def reply_later(request_id: str) -> None:
    time.sleep(ANSWER_DELAY)
    seen["answered_at"] = round(time.time() - T0, 2)
    out = call("POST", f"/permission/{request_id}/reply", {"reply": ANSWER})
    log("HOST -> permission reply", ANSWER, "->", json.dumps(out)[:120])


def events() -> None:
    req = urllib.request.Request(BASE + "/event")
    try:
        with urllib.request.urlopen(req, timeout=120) as stream:
            for raw in stream:
                line = raw.decode(errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except ValueError:
                    continue
                kind = ev.get("type", "")
                props = ev.get("properties", {})
                if kind == "permission.asked" or kind.startswith("permission."):
                    if kind == "permission.asked":
                        seen["permission_asks"] = int(seen["permission_asks"]) + 1  # type: ignore[arg-type]
                        rid = props.get("requestID") or props.get("id") or ""
                        log("AGENT -> PERMISSION ASKED:", json.dumps(props)[:260])
                        threading.Thread(target=reply_later, args=(rid,), daemon=True).start()
                    else:
                        log("AGENT:", kind, json.dumps(props)[:160])
                elif kind in ("message.part.updated", "message.updated"):
                    part = props.get("part", {})
                    if part.get("type") == "tool":
                        state = (part.get("state") or {}).get("status")
                        if state in ("running", "completed", "error"):
                            if state != "running":
                                seen["tool_end_at"] = round(time.time() - T0, 2)
                            log(f"AGENT: tool {part.get('tool')} -> {state}")
                elif kind == "session.error":
                    log("AGENT: session.error", json.dumps(props)[:300])
    except Exception as exc:  # noqa: BLE001
        log("event stream ended:", exc)


threading.Thread(target=events, daemon=True).start()
time.sleep(1.0)

log("MCP status:", json.dumps(call("GET", "/mcp"))[:400])

session = call("POST", "/session", {})
sid = session.get("id") or session.get("info", {}).get("id")
log("session:", sid, json.dumps(session)[:160])

if sid:
    log("HOST -> prompt")
    threading.Thread(target=lambda: log("prompt returned:", json.dumps(call(
        "POST", f"/session/{sid}/message",
        {"model": {"providerID": "stub", "modelID": "stub-model"},
         "parts": [{"type": "text", "text": "do the thing"}]}, timeout=90))[:300]),
        daemon=True).start()

time.sleep(float(os.environ.get("RUN_S", "22")))
log("SUMMARY", json.dumps(seen))
