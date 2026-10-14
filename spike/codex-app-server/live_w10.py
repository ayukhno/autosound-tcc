"""W-10 Codex task 10, macOS half: TCC's OWN Codex code, live (tcc#181).

The spike (`RESULT.md`) proved six points with throwaway code; this drives the same points through
what the wave built — `CodexSession` made by `session_routes.factory` for a Codex pick, `codex_rpc`,
`codex_cli`, `shell_gate.judge_action`, `codex_terminal` — against the real `codex app-server`, with
TCC's real `TccMcpServer` in this process (headless, a wiretap on its HTTP layer as in
`serve_tcc.py`). No GUI: the gate's confirmation is a stub bridge that answers per scenario
(accept / decline / never answers), as the panel's `await_confirmation` would get it.

    python spike/codex-app-server/live_w10.py config   <project>           # P7 + model/list, no model cost
    python spike/codex-app-server/live_w10.py session  <project> <model>   # P1-P5, P9 (one process)
    python spike/codex-app-server/live_w10.py resume   <project> <model>   # P6, P9 (a new process)
    python spike/codex-app-server/live_w10.py terminal <project> <model>   # P8, P9 (`codex exec`)
    python spike/codex-app-server/live_w10.py tokens   <project>           # the run's token count

`<project>` is a scratch folder OUTSIDE any git repo (Codex reads AGENTS.md up to the git root).
Reports and copies of the logs land in `work/logs/w10live/` (git-ignored). The token never goes into
a report: only whether it was found.

Driver-only deviations, said in RESULT-W10-LIVE.md: the effort word is forced to `low` after
`_clamp_effort` ran (TCC never sends below `high`; the brief caps the run's cost); the phase is seeded
with `SessionRegistry.sync_phase` so the thread binds (TCC's window does this from the method's
process state).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import types
from concurrent.futures import Future
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

from autosound_tcc.core import (codex_cli, codex_rpc, codex_session, codex_terminal,  # noqa: E402
                                session_routes)
import autosound_tcc.core.mcp_server as M  # noqa: E402
from autosound_tcc.core.agent_events import (Notice, TextDelta, ToolCall, ToolEnd,  # noqa: E402
                                             TurnEnd, Unasked)
from autosound_tcc.core.session_registry import SessionRegistry  # noqa: E402
from autosound_tcc.core.shell_gate import GATE_AUTO, GATE_WRITES  # noqa: E402

LOGS = HERE / "work" / "logs" / "w10live"
EFFORT = "low"
TURN_TIMEOUT_S = 300.0
PHASE = "intake"


def _write(name: str, obj) -> Path:
    LOGS.mkdir(parents=True, exist_ok=True)
    path = LOGS / name
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str))
    return path


# ---- TCC's MCP server, headless, with a wiretap -------------------------------------------------

class StubBridge:
    """The panel's side of the gate: `policy(request)` → True (accept) / False (decline) / None
    (never answers: the future is held, and whether it was cancelled is recorded)."""

    def __init__(self, project: Path) -> None:
        self._p = project
        self.policy = lambda request: False
        self.asked: list[dict] = []
        self.on_ask = None

    def snapshot(self) -> dict:
        return {"mode": "live-w10", "project_dir": str(self._p)}

    def request_confirmation(self, request) -> "Future[bool]":
        fut: "Future[bool]" = Future()
        answer = self.policy(request)
        rec = {"t": round(time.time(), 3), "tool": request.tool, "detail": (request.detail or "")[:300],
               "reason": request.reason, "answer": answer}
        self.asked.append(rec)
        if answer is None:
            fut.add_done_callback(lambda f, rec=rec: rec.update(
                cancelled=f.cancelled(), done_at=round(time.time(), 3)))
        else:
            fut.set_result(bool(answer))
        if self.on_ask:
            self.on_ask(rec)
        return fut

    def copy_to_clipboard(self, text: str) -> None: ...
    def show_proposal(self, proposal: dict) -> None: ...
    def show_critique(self, critique: dict) -> None: ...
    def notify_profile_ready(self) -> None: ...
    def refresh_from_disk(self) -> None: ...


def serve(project: Path, bridge: StubBridge, tag: str) -> M.TccMcpServer:
    http_log = LOGS / f"tcc-http-{tag}.jsonl"
    LOGS.mkdir(parents=True, exist_ok=True)

    def append(obj: dict) -> None:
        with http_log.open("a") as fh:
            fh.write(json.dumps(obj) + "\n")

    orig = M._TokenGuard

    class LoggingGuard(orig):  # type: ignore[misc, valid-type]
        async def __call__(self, scope, receive, send):  # noqa: ANN001, ANN204
            if scope.get("type") != "http":
                return await orig.__call__(self, scope, receive, send)
            headers = {k.decode().lower(): v.decode() for k, v in (scope.get("headers") or [])}
            append({"t": time.time(), "method": scope.get("method"), "path": scope.get("path"),
                    "token_present": "x-tcc-token" in headers,
                    "ua": headers.get("user-agent", "")[:60]})
            body = bytearray()

            async def _recv():
                msg = await receive()
                if msg.get("type") == "http.request":
                    body.extend(msg.get("body") or b"")
                    if not msg.get("more_body") and body:
                        append({"t": time.time(), "rpc": bytes(body).decode("utf-8", "replace")[:400]})
                return msg

            return await orig.__call__(self, scope, _recv, send)

    if not getattr(M._TokenGuard, "_w10", False):
        LoggingGuard._w10 = True
        M._TokenGuard = LoggingGuard
    project.mkdir(parents=True, exist_ok=True)
    server = M.TccMcpServer(project_dir=project, bridge=bridge)
    server.start()
    return server


# ---- argv watch: the token in no child's command line -------------------------------------------

class ArgvWatch(threading.Thread):
    """Every 0.3 s: every descendant of this process, its argv checked for the token."""

    def __init__(self, token: str) -> None:
        super().__init__(daemon=True)
        self.token = token
        self.stop = threading.Event()
        self.samples = 0
        self.hits = 0
        self.seen: dict[int, str] = {}

    def run(self) -> None:
        me = os.getpid()
        while not self.stop.is_set():
            out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,args="], capture_output=True,
                                 text=True).stdout
            rows = []
            for line in out.splitlines():
                parts = line.strip().split(None, 2)
                if len(parts) >= 2:
                    rows.append((int(parts[0]), int(parts[1]), parts[2] if len(parts) > 2 else ""))
            kids, frontier = {}, {me}
            while frontier:
                nxt = set()
                for pid, ppid, args in rows:
                    if ppid in frontier and pid not in kids and pid != me:
                        kids[pid] = args
                        nxt.add(pid)
                frontier = nxt
            for pid, args in kids.items():
                if args.startswith("ps "):
                    continue
                self.samples += 1
                if self.token and self.token in args:
                    self.hits += 1
                self.seen.setdefault(pid, args[:160])
            self.stop.wait(0.3)

    def report(self) -> dict:
        codex = {pid: a for pid, a in self.seen.items() if "codex" in a}
        return {"argv_samples": self.samples, "token_in_argv": self.hits,
                "codex_children_seen": len(codex),
                "codex_argv_example": next(iter(codex.values()), "")[:160]}


def codex_children() -> list[str]:
    """`pgrep -P <this pid>` — by PID, not by pattern."""
    out = subprocess.run(["pgrep", "-P", str(os.getpid())], capture_output=True, text=True).stdout
    rows = []
    for pid in out.split():
        args = subprocess.run(["ps", "-o", "args=", "-p", pid], capture_output=True, text=True).stdout
        rows.append(f"{pid} {args.strip()[:80]}")
    return rows


# ---- the session, as the window builds it -------------------------------------------------------

_orig_clamp = codex_session.CodexSession._clamp_effort


async def _clamp_then_low(self) -> None:
    await _orig_clamp(self)
    self.w10_clamped = self._codex_effort
    self._codex_effort = EFFORT


codex_session.CodexSession._clamp_effort = _clamp_then_low


def build(project: Path, model: str, server, bridge, *, resumed: bool, gate: dict):
    choice = types.SimpleNamespace(harness="codex", model=model)
    make = session_routes.factory(
        choice, project_dir=project, bridge=bridge, mcp_url=server.url, mcp_token=server.token,
        gate=lambda: gate["gate"], always_allowed=lambda: frozenset(), resumed=resumed,
        effort=None, language="en")
    session = make()
    session.bus = server.bus  # what `AgentWorker` hands it
    return session


def _short(ev) -> str:
    if isinstance(ev, TextDelta):
        return ev.text[:60]
    if isinstance(ev, ToolCall):
        return f"{ev.name} {json.dumps(getattr(ev, 'args', {}) or {}, ensure_ascii=False)[:120]}"
    if isinstance(ev, ToolEnd):
        return ev.name
    if isinstance(ev, Notice):
        return ev.text[:200]
    if isinstance(ev, Unasked):
        return ev.command[:120]
    if isinstance(ev, TurnEnd):
        return str(ev.session_id)
    return repr(ev)[:120]


async def run_turn(label: str, agen, on_event=None) -> dict:
    events, t0 = [], time.time()

    async def consume():
        async for ev in agen:
            events.append((round(time.time() - t0, 2), type(ev).__name__, ev))
            if on_event:
                await on_event(ev)

    try:
        await asyncio.wait_for(consume(), TURN_TIMEOUT_S)
        timed_out = False
    except asyncio.TimeoutError:
        timed_out = True
    kinds = [k for _, k, _ in events]
    text = "".join(ev.text for _, k, ev in events if k == "TextDelta")
    out = {
        "label": label, "t0": t0, "timed_out": timed_out, "seconds": round(time.time() - t0, 2),
        "counts": {k: kinds.count(k) for k in sorted(set(kinds))},
        "turnend_count": kinds.count("TurnEnd"),
        "last_is_turnend": bool(kinds) and kinds[-1] == "TurnEnd",
        "tools": [(t, k, _short(ev)) for t, k, ev in events if k in ("ToolCall", "ToolEnd", "Unasked")],
        "notices": [_short(ev) for _, k, ev in events if k == "Notice"],
        "text": text[:400],
        "first_delta_at": next((t for t, k, _ in events if k == "TextDelta"), None),
        "turnend_at": next((t for t, k, _ in events if k == "TurnEnd"), None),
    }
    print(json.dumps({k: out[k] for k in ("label", "seconds", "counts", "last_is_turnend", "text")},
                     ensure_ascii=False)[:600], flush=True)
    return out


def frames(project: Path) -> list[dict]:
    path = project / ".tcc" / codex_session.FRAME_LOG
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def answers_per_id(rows: list[dict], since: float = 0.0) -> dict:
    """How many times TCC answered each of Codex's requests (out frames with an id and no method)."""
    n: dict = {}
    for r in rows:
        if r.get("t", 0) < since or r.get("dir") != "out":
            continue
        msg = r.get("msg") or {}
        if isinstance(msg, dict) and "id" in msg and "method" not in msg:
            n[msg["id"]] = n.get(msg["id"], 0) + 1
    return n


def setup_project(project: Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    reg = SessionRegistry(project / ".tcc")
    if reg.current_phase() != PHASE:
        reg.sync_phase(PHASE)


# ---- P7 + the model list (no model cost) --------------------------------------------------------

def _features_on(cfg: dict) -> list[str]:
    inner = cfg.get("config") if isinstance(cfg.get("config"), dict) else cfg
    feats = inner.get("features") or {}
    return sorted(k for k, v in feats.items()
                  if v is True or (isinstance(v, dict) and v.get("enabled")))


def _servers(cfg: dict) -> dict:
    inner = cfg.get("config") if isinstance(cfg.get("config"), dict) else cfg
    return {name: (body or {}).get("enabled", True) if isinstance(body, dict) else body
            for name, body in (inner.get("mcp_servers") or {}).items()}


async def cmd_config(project: Path) -> None:
    setup_project(project)
    found = codex_cli.find()
    raw, models = await codex_rpc.ask(found.path, [("config/read", {"cwd": str(project)}),
                                                   ("model/list", {})],
                                      timeout=30, cwd=str(project))
    iso_args = codex_cli.isolation_args(raw)
    (iso,) = await codex_rpc.ask(found.path, [("config/read", {"cwd": str(project)})], timeout=30,
                                 cwd=str(project), args=iso_args)

    def inner(c):
        return c.get("config") if isinstance(c.get("config"), dict) else c

    report = {
        "codex": found.path, "version": codex_cli.version_text(codex_cli.version(found)),
        "user_mcp_servers": _servers(raw), "isolated_mcp_servers": _servers(iso),
        "user_features_on": _features_on(raw), "isolated_features_on": _features_on(iso),
        "off_features_still_on": sorted(set(_features_on(iso)) & set(codex_cli.OFF_FEATURES)),
        "unknown_enabled_features_user": codex_cli.unknown_enabled_features(raw),
        "unknown_enabled_features_isolated": codex_cli.unknown_enabled_features(iso),
        "notify": [inner(raw).get("notify"), inner(iso).get("notify")],
        "project_doc_max_bytes": [inner(raw).get("project_doc_max_bytes"),
                                  inner(iso).get("project_doc_max_bytes")],
        "skills": [inner(raw).get("skills"), inner(iso).get("skills")],
        "shell_environment_policy": [inner(raw).get("shell_environment_policy"),
                                     inner(iso).get("shell_environment_policy")],
        "isolation_argc": len(iso_args),
        "models": [(m.get("id"), m.get("displayName"), m.get("hidden"),
                    [e.get("reasoningEffort") for e in m.get("supportedReasoningEfforts") or []],
                    (m.get("description") or "")[:80]) for m in models.get("data") or []],
    }
    _write("config-report.json", report)
    print(json.dumps(report, indent=1, ensure_ascii=False, default=str))


# ---- P1-P5 in one process -----------------------------------------------------------------------

T1 = ("This is a connection test, not a tuning session: call get_tcc_state exactly once, open no "
      "file, load no skill and run no shell command, then reply in one line with the project_dir it "
      "returned.")
T2 = ("Run these two shell commands, each as its own separate command, in this order: "
      "`echo hi > note.txt`, then `touch denied.txt`. Do not retry a refused command and do not try "
      "another way. Then reply in one line: which of note.txt and denied.txt exist now, and the kind "
      "of the TCC signal above.")
T3 = ("Do these three steps in order, one tool call each, and do not retry or work around anything "
      "refused: 1) run the shell command `python3 -c \"import random; print(random.randint(10**8, "
      "10**9))\"`; 2) run the shell command `dd if=/dev/zero of=/dev/null count=0`; 3) delete the "
      "file note.txt with your apply_patch file-editing tool (a `*** Delete File: note.txt` patch), "
      "not with a shell command. Then reply in one line: the number step 1 printed, and which steps "
      "were refused.")
T5 = "Write the numbers from 1 to 400, one per line, and nothing else."
T6 = "Run the shell command `touch held.txt`. Do not retry if it is refused. Reply in one word."


async def cmd_session(project: Path, model: str) -> None:
    setup_project(project)
    for name in ("note.txt", "denied.txt", "held.txt"):
        (project / name).unlink(missing_ok=True)
    bridge = StubBridge(project)
    server = serve(project, bridge, "session")
    gate = {"gate": GATE_WRITES}
    session = build(project, model, server, bridge, resumed=False, gate=gate)
    watch = ArgvWatch(server.token)
    watch.start()
    report: dict = {"model": model, "effort": EFFORT, "project": str(project)}
    t_start = time.time()
    try:
        # T1 — the opener (P1, P2).
        report["T1"] = await run_turn("T1 opener", session.start(T1))
        report["thread_id"] = session.session_id
        report["clamped_effort_before_low"] = getattr(session, "w10_clamped", None)
        report["codex_pid"] = session._server.pid
        status = await session._server.request("mcpServerStatus/list", {}, timeout=30)
        report["mcp_status"] = [(s.get("name"), len(s.get("tools") or {}),
                                 s.get("authStatus")) for s in status.get("data") or []]

        # A window signal between turns (P3) and the gate under `writes` (P4a).
        sig = server.bus.push("button", label="PROBE-SIGNAL")
        report["signal_id"] = sig.id
        session.gate = GATE_WRITES
        bridge.policy = lambda r: "echo hi" in (r.detail or "")
        t2_since = time.time()
        report["T2"] = await run_turn("T2 writes+signal", session.send(T2))
        report["T2"]["files"] = {n: (project / n).exists() for n in ("note.txt", "denied.txt")}
        report["T2"]["asked"] = [a for a in bridge.asked if a["t"] >= t2_since]

        # `auto`: an ordinary line unasked; then the Bash tick and a dangerous line; a file delete.
        session.gate = GATE_AUTO
        session.always_allowed = frozenset()
        bridge.policy = lambda r: False
        rpc = session._server
        orig_on = rpc.on_notification

        def tick_after_python(msg: dict) -> None:
            orig_on(msg)
            item = (msg.get("params") or {}).get("item") or {}
            if msg.get("method") == "item/completed" and item.get("type") == "commandExecution" \
                    and "random" in str(item.get("command")):
                session.always_allowed = frozenset({"Bash"})
                report.setdefault("tick_set_at", time.time())

        rpc.on_notification = tick_after_python
        t3_since = time.time()
        report["T3"] = await run_turn("T3 auto", session.send(T3))
        rpc.on_notification = orig_on
        session.always_allowed = frozenset()
        report["T3"]["asked"] = [a for a in bridge.asked if a["t"] >= t3_since]
        report["T3"]["note_still_there"] = (project / "note.txt").exists()

        # P5a — Stop mid-stream.
        session.gate = GATE_WRITES
        stop = {}

        async def stop_at_first_delta(ev):
            if isinstance(ev, TextDelta) and "sent" not in stop:
                stop["sent"] = time.time()
                await session.interrupt()

        report["T5"] = await run_turn("T5 interrupt mid-stream", session.send(T5), stop_at_first_delta)
        t5 = report["T5"]
        report["T5"]["interrupt_to_turnend_s"] = (
            round(t5["t0"] + t5["turnend_at"] - stop["sent"], 3) if stop and t5["turnend_at"] else None)

        # P5b — Stop while an approval waits on the bar.
        bridge.policy = lambda r: None
        asked = asyncio.Event()
        loop = asyncio.get_running_loop()
        bridge.on_ask = lambda rec: loop.call_soon_threadsafe(asked.set)
        t6_since = time.time()

        async def stop_when_asked():
            await asyncio.wait_for(asked.wait(), 120)
            await asyncio.sleep(1.0)
            report["T6_interrupt_sent"] = time.time()
            await session.interrupt()

        stopper = asyncio.ensure_future(stop_when_asked())
        report["T6"] = await run_turn("T6 interrupt pending", session.send(T6))
        try:
            await asyncio.wait_for(stopper, 5)
        except Exception as exc:  # noqa: BLE001
            report["T6_stopper"] = repr(exc)
        await asyncio.sleep(2.0)  # the sweep's late decline would fire within 1 s
        report["T6"]["asked"] = [a for a in bridge.asked if a["t"] >= t6_since]
        t6 = report["T6"]
        if report.get("T6_interrupt_sent") and t6["turnend_at"] is not None:
            t6["interrupt_to_turnend_s"] = round(t6["t0"] + t6["turnend_at"] - report["T6_interrupt_sent"], 3)
        report["T6"]["held_exists"] = (project / "held.txt").exists()
        bridge.on_ask = None
    finally:
        rpc = session._server
        await session.close()
        report["close"] = {"returncode": rpc.returncode if rpc else None,
                           "codex_children_after_close": codex_children()}
        watch.stop.set()
        watch.join(2)
        report["argv_watch"] = watch.report()
    report.update(evidence(project, server.token, t_start))
    report["T6"]["answers_to_withdrawn"] = report.get("withdrawn_answered")
    _write("session-report.json", report)
    shutil.copyfile(project / ".tcc" / codex_session.FRAME_LOG, LOGS / "codex-frames-session.jsonl")
    print(json.dumps({k: report.get(k) for k in ("thread_id", "close", "argv_watch", "frame_checks")},
                     indent=1, default=str))


def evidence(project: Path, token: str, since: float) -> dict:
    rows = [r for r in frames(project) if r.get("t", 0) >= since]
    ins = [r["msg"] for r in rows if r.get("dir") == "in" and isinstance(r.get("msg"), dict)]
    outs = [r["msg"] for r in rows if r.get("dir") == "out" and isinstance(r.get("msg"), dict)]
    methods_in = [m.get("method") for m in ins if m.get("method")]
    answers = answers_per_id(rows)
    withdrawn = [(m.get("params") or {}).get("requestId") for m in ins
                 if m.get("method") == "serverRequest/resolved"]
    requests_in = {m["id"]: m.get("method") for m in ins if "id" in m and m.get("method")}
    frame_text = (project / ".tcc" / codex_session.FRAME_LOG).read_text(encoding="utf-8")
    http = "".join(p.read_text() for p in LOGS.glob("tcc-http-*.jsonl"))
    http_rows = [json.loads(line) for line in http.splitlines() if line.startswith("{")]
    turn_starts = [m for m in outs if m.get("method") == "turn/start"]
    completed = [((m.get("params") or {}).get("turn") or {}).get("status") for m in ins
                 if m.get("method") == "turn/completed"]
    usage = [((m.get("params") or {}).get("tokenUsage") or {}) for m in ins
             if m.get("method") == "thread/tokenUsage/updated"]
    return {
        "frame_checks": {
            "frames": len(rows),
            "methods_in": {m: methods_in.count(m) for m in sorted(set(methods_in))},
            "elicitations": methods_in.count("mcpServer/elicitation/request"),
            "turn_steer_out": sum(1 for m in outs if m.get("method") == "turn/steer"),
            "turn_start_count": len(turn_starts),
            "turn_start_with_brief": [i for i, m in enumerate(turn_starts)
                                      if "un-acknowledged signal" in json.dumps(m)],
            "turn_completed_statuses": completed,
            "server_requests": requests_in,
            "answers_per_request": answers,
            "answered_twice": [k for k, v in answers.items() if v > 1],
            "withdrawn": withdrawn,
            "second_answer_notes": [r["msg"] for r in rows if r.get("dir") == "note"
                                    and "refused" in str(r.get("msg"))],
            "token_in_frame_log": bool(token) and token in frame_text,
            "token_in_http_log": bool(token) and token in http,
            "argv_logged": next((r["msg"]["argv"][:3] for r in rows if r.get("dir") == "note"
                                 and isinstance(r.get("msg"), dict) and "argv" in r["msg"]), None),
            "usage_last_sum": sum((u.get("last") or {}).get("totalTokens", 0) for u in usage),
            "usage_thread_total_max": max([(u.get("total") or {}).get("totalTokens", 0) for u in usage]
                                          or [0]),
        },
        "tcc_http": {
            "requests": sum(1 for r in http_rows if "method" in r),
            "token_present_all": all(r.get("token_present") for r in http_rows if "method" in r),
            "ua": sorted({r.get("ua") for r in http_rows if "ua" in r}),
            "tools_called": sorted({json.loads(r["rpc"]).get("params", {}).get("name")
                                    for r in http_rows if "rpc" in r and '"tools/call"' in r["rpc"]
                                    and r["rpc"].endswith("}")}),
        },
        "withdrawn_answered": [rid for rid in withdrawn if answers.get(rid)],
    }


# ---- P6 in a new process ------------------------------------------------------------------------

T7 = ("Before you call any tool, answer from our earlier conversation only, in one line: what number "
      "did the python3 random command print, and what project_dir did get_tcc_state return the first "
      "time? Then stop.")


async def cmd_resume(project: Path, model: str) -> None:
    previous = SessionRegistry(project / ".tcc").resumable_session(route="codex")
    bridge = StubBridge(project)
    server = serve(project, bridge, "resume")
    gate = {"gate": GATE_WRITES}
    session = build(project, model, server, bridge, resumed=True, gate=gate)
    watch = ArgvWatch(server.token)
    watch.start()
    report: dict = {"previous_thread": previous}
    t_start = time.time()
    try:
        report["T7"] = await run_turn("T7 resumed", session.start(T7))
        report["resumed"] = session.resumed
        report["thread_id"] = session.session_id
    finally:
        rpc = session._server
        await session.close()
        report["close"] = {"returncode": rpc.returncode if rpc else None,
                           "codex_children_after_close": codex_children()}
        watch.stop.set()
        watch.join(2)
        report["argv_watch"] = watch.report()
    report.update(evidence(project, server.token, t_start))
    rows = [r for r in frames(project) if r.get("t", 0) >= t_start]
    report["thread_resume_out"] = [
        {k: v for k, v in (r["msg"].get("params") or {}).items() if k in ("threadId", "excludeTurns")}
        for r in rows if r.get("dir") == "out" and isinstance(r.get("msg"), dict)
        and r["msg"].get("method") == "thread/resume"]
    _write("resume-report.json", report)
    shutil.copyfile(project / ".tcc" / codex_session.FRAME_LOG, LOGS / "codex-frames-all.jsonl")
    print(json.dumps({k: report.get(k) for k in ("previous_thread", "resumed", "thread_id",
                                                 "thread_resume_out", "close", "argv_watch")},
                     indent=1, default=str))


# ---- P8: the terminal's connection pieces, non-interactively ------------------------------------

T8 = ("Connection test, not a tuning session. 1) Call the tcc MCP tool get_tcc_state once and give "
      "the project_dir it returned. 2) Is an autosound-tuning skill or car-audio tuning method "
      "available to you in this session (in your skills list or your instructions)? If yes, say from "
      "which file path; if no, say no. Do not search the disk. Reply in two short lines.")


async def cmd_terminal(project: Path, model: str) -> None:
    bridge = StubBridge(project)
    server = serve(project, bridge, "terminal-approve" if os.environ.get("W10_TERMINAL_APPROVE") == "1"
                   else "terminal")
    url, token = codex_terminal.connection(project)  # what «Open terminal → Codex» reads
    found = codex_terminal._codex()
    base = codex_terminal.command(found.path, url, model)
    # `approve`: the second run adds the in-app session's one approval key for TCC's server, to
    # tell "the connection fails" from "exec's approval policy `never` refuses the call".
    approve = os.environ.get("W10_TERMINAL_APPROVE") == "1"
    extra = ["-c", 'mcp_servers.tcc.default_tools_approval_mode="approve"'] if approve else []
    tag = "terminal-approve" if approve else "terminal"
    argv = [base[0], "exec", *base[1:], *extra, "-c", f'model_reasoning_effort="{EFFORT}"',
            "--skip-git-repo-check", "--json", T8]
    env = {**os.environ, codex_cli.TOKEN_ENV: token}
    watch = ArgvWatch(token)
    watch.start()
    out_path, err_path = LOGS / f"{tag}-exec.jsonl", LOGS / f"{tag}-exec.stderr"
    t0 = time.time()
    with out_path.open("w") as out, err_path.open("w") as err:
        proc = subprocess.Popen(argv, cwd=str(project), env=env, stdout=out, stderr=err,
                                stdin=subprocess.DEVNULL)
        code = proc.wait(timeout=300)
    watch.stop.set()
    watch.join(2)
    events = [json.loads(line) for line in out_path.read_text().splitlines() if line.startswith("{")]
    items = [e.get("item") or {} for e in events if e.get("type") == "item.completed"]
    report = {
        "argv_shape": [a if not a.startswith("mcp_servers.tcc.url") else "mcp_servers.tcc.url=…"
                       for a in argv[1:-1]],
        "exit": code, "seconds": round(time.time() - t0, 1),
        "token_in_argv_list": token in " ".join(argv),
        "argv_watch": watch.report(),
        "token_in_stdout": token in out_path.read_text(), "token_in_stderr": token in err_path.read_text(),
        "mcp_items": [{k: i.get(k) for k in ("server", "tool", "status", "error")}
                      for i in items if i.get("type") == "mcp_tool_call"],
        "messages": [i.get("text") for i in items if i.get("type") == "agent_message"],
        "item_types": [i.get("type") for i in items],
        "usage": [e.get("usage") for e in events if e.get("type") == "turn.completed"],
        "stderr_tail": err_path.read_text()[-600:].replace(token, "<TOKEN>"),
        "agents_md": (project / "AGENTS.md").exists(),
        "codex_children_after": codex_children(),
    }
    _write(f"{tag}-report.json", report)
    print(json.dumps(report, indent=1, ensure_ascii=False, default=str))


def cmd_tokens(project: Path) -> None:
    rows = frames(project)
    usage = [r["msg"]["params"]["tokenUsage"] for r in rows
             if r.get("dir") == "in" and isinstance(r.get("msg"), dict)
             and r["msg"].get("method") == "thread/tokenUsage/updated"]
    app = sum((u.get("last") or {}).get("totalTokens", 0) for u in usage)
    cached = sum((u.get("last") or {}).get("cachedInputTokens", 0) for u in usage)
    term = [u for name in ("terminal-report.json", "terminal-approve-report.json")
            if (LOGS / name).exists() for u in json.loads((LOGS / name).read_text()).get("usage") or []]
    term_total = sum((u or {}).get("input_tokens", 0) + (u or {}).get("output_tokens", 0) for u in term)
    term_cached = sum((u or {}).get("cached_input_tokens", 0) for u in term)
    print(json.dumps({"app_server_requests": len(usage), "app_server_total": app,
                      "app_server_cached_input": cached, "terminal_total": term_total,
                      "terminal_cached_input": term_cached, "run_total": app + term_total}, indent=1))


if __name__ == "__main__":
    cmd, project, *rest = sys.argv[1:]
    project_path = Path(project).expanduser().resolve()
    if cmd == "tokens":
        cmd_tokens(project_path)
    else:
        asyncio.run({"config": cmd_config, "session": cmd_session, "resume": cmd_resume,
                     "terminal": cmd_terminal}[cmd](project_path, *rest))
