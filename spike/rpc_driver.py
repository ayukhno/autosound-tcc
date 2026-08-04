"""Drive omp in `rpc-ui` mode as a non-Node host — i.e. exactly the role TCC
would play — and answer the approval frame deliberately late.

The point is the timeline it prints: if `tool_execution_end` lands only after
the host's `extension_ui_response`, the agent really blocked on us, and omp's
approval gate is a drop-in for `TuningSession._can_use_tool`.

    python spike/rpc_driver.py

Env:
    WARMUP_S      wait before prompting, so MCP discovery finishes (default 12)
    ANSWER_DELAY  how late the host answers the approval (default 6)
    ANSWER        "Approve" or "Deny" (default Approve)
    RUN_S         how long to keep reading frames (default 18)
    PROJECT_DIR   cwd for the agent (default /tmp/fx)
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time

PROJECT = os.environ.get("PROJECT_DIR", "/tmp/fx")
ANSWER_DELAY = float(os.environ.get("ANSWER_DELAY", "6"))
ANSWER = os.environ.get("ANSWER", "Approve")
T0 = time.time()

# Frames omp raises for its own chrome; not part of what we're measuring.
NOISE_METHODS = {"setWidget", "setTitle", "set_editor_text", "notify"}


def log(*parts: object) -> None:
    print(f"[{time.time() - T0:6.2f}s]", *parts, flush=True)


env = dict(os.environ)
env["LM_STUDIO_BASE_URL"] = f"http://127.0.0.1:{os.environ.get('STUB_PORT', '8899')}/v1"
env["OPENAI_API_KEY"] = "stub"

proc = subprocess.Popen(
    ["omp", "--mode", "rpc-ui", "--no-session", "--model", "stub-model",
     "--approval-mode", "always-ask"],
    cwd=PROJECT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    stderr=subprocess.PIPE, text=True, bufsize=1,
)

seen: dict[str, object] = {"approval_frames": 0, "answered_at": None, "tool_end_at": None}


def send(obj: dict) -> None:
    log("HOST ->", json.dumps(obj)[:140])
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def answer_later(frame_id: str, method: str) -> None:
    time.sleep(ANSWER_DELAY)
    seen["answered_at"] = round(time.time() - T0, 2)
    if method == "select":
        send({"type": "extension_ui_response", "id": frame_id, "value": ANSWER})
    elif method == "confirm":
        send({"type": "extension_ui_response", "id": frame_id, "confirmed": ANSWER == "Approve"})
    else:
        send({"type": "extension_ui_response", "id": frame_id, "cancelled": True})


def reader() -> None:
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            frame = json.loads(line)
        except ValueError:
            continue
        kind = frame.get("type")
        if kind == "extension_ui_request":
            method = frame.get("method")
            if method in NOISE_METHODS:
                send({"type": "extension_ui_response", "id": frame.get("id"), "cancelled": True})
                continue
            seen["approval_frames"] = int(seen["approval_frames"]) + 1  # type: ignore[arg-type]
            log("AGENT -> UI REQUEST:", json.dumps(frame)[:300])
            threading.Thread(target=answer_later, daemon=True,
                             args=(frame.get("id"), method)).start()
        elif kind in ("tool_execution_start", "toolcall_start"):
            log("AGENT: tool start", json.dumps(frame)[:160])
        elif kind in ("tool_execution_end", "toolcall_end"):
            seen["tool_end_at"] = round(time.time() - T0, 2)
            log("AGENT: tool end", json.dumps(frame)[:220])
        elif kind in ("agent_end", "error"):
            log("AGENT:", kind, json.dumps(frame)[:200])


threading.Thread(target=reader, daemon=True).start()
time.sleep(float(os.environ.get("WARMUP_S", "12")))
send({"id": "r0", "type": "negotiate_protocol", "protocolVersion": 1})
time.sleep(0.5)
send({"id": "r1", "type": "prompt", "message": "do the thing"})
time.sleep(float(os.environ.get("RUN_S", "18")))
log("SUMMARY", json.dumps(seen))
stderr = proc.stderr.read(1500) if proc.stderr else ""
if stderr.strip():
    log("STDERR:", stderr[:600])
proc.kill()
