"""Throwaway client for `codex app-server` over stdio JSON-RPC (tcc#181 spike).

Stdlib only. Every line both ways goes to a JSONL wire log, which is the evidence.

    python3 client.py probe                     # no model turns: init, account, models, MCP status
    python3 client.py run   <model> <effort>    # turns T1..T4 on one process
    python3 client.py resume <thread_id> <model> <effort>   # new process, thread/resume, T5

Env: TCC_URL, TCC_MCP_TOKEN (from serve_tcc.py) to wire TCC's MCP server.
Safety: cwd = work/scratch, sandbox workspace-write limited to it, network off, approvals
'untrusted' (every non-safe command comes to this client). The client allows only
`echo` / `ls` with no path outside the scratch folder, and declines everything else.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
SCRATCH = WORK / "scratch"
LOGS = WORK / "logs"
CODEX = os.environ.get("CODEX_BIN", "codex")


# --- process-level config: TCC's MCP server in, the user's own extras out --------------------

def codex_args() -> list[str]:
    a = ["app-server"]
    # The user's own MCP servers, plugins, notifier and hooks stay out of the spike session.
    for k in [
        "mcp_servers.home-assistant.enabled=false",
        "mcp_servers.node_repl.enabled=false",
        "notify=[]",
        "features.plugins=false",
        "features.apps=false",
        "features.browser_use=false",
        "features.computer_use=false",
        "features.in_app_browser=false",
        "features.image_generation=false",
        "features.multi_agent=false",
        "features.hooks=false",
        "features.goals=false",
        "features.tool_suggest=false",
        "features.memories=false",
    ]:
        a += ["-c", k]
    url = os.environ.get("TCC_URL")
    if url:
        a += ["-c", f'mcp_servers.tcc.url="{url}"',
              "-c", 'mcp_servers.tcc.env_http_headers={"X-TCC-Token"="TCC_MCP_TOKEN"}']
        mode = os.environ.get("TCC_TOOLS_APPROVAL")  # e.g. "approve"
        if mode:
            a += ["-c", f'mcp_servers.tcc.default_tools_approval_mode="{mode}"']
    return a


# --- the approval gate: where TCC's own setting would plug in --------------------------------

_SAFE_HEAD = {"echo", "ls"}


def _inner_command(cmd: str) -> str:
    """Strip a `/bin/zsh -lc '…'` / `bash -lc "…"` wrapper if present."""
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return cmd
    if len(parts) >= 3 and parts[0].split("/")[-1] in {"bash", "zsh", "sh"} and parts[1] in {"-lc", "-c"}:
        return parts[2]
    return cmd


def gate_command(params: dict) -> tuple[str, str]:
    cmd = params.get("command") or ""
    inner = _inner_command(cmd)
    cwd = str(params.get("cwd") or "")
    reason = ""
    try:
        toks = shlex.split(inner)
    except ValueError:
        toks = []
    ok = bool(toks) and toks[0] in _SAFE_HEAD
    if ok and re.search(r"[;&|`$()]", inner):
        ok, reason = False, "shell metacharacters"
    if ok and ".." in inner:
        ok, reason = False, "parent path"
    if ok and any(t.startswith("/") or t.startswith("~") for t in toks[1:]):
        ok, reason = False, "absolute path"
    if ok and cwd and not cwd.startswith(str(SCRATCH)):
        ok, reason = False, f"cwd outside scratch: {cwd}"
    if not ok and not reason:
        reason = "not echo/ls"
    return ("accept" if ok else "decline"), reason


# --- JSON-RPC over stdio ---------------------------------------------------------------------

class AppServer:
    def __init__(self, tag: str, env_extra: dict[str, str] | None = None) -> None:
        LOGS.mkdir(parents=True, exist_ok=True)
        self.log_path = LOGS / f"{tag}-wire.jsonl"
        self.log = self.log_path.open("a")
        env = dict(os.environ)
        env.update(env_extra or {})
        args = [CODEX, *codex_args()]
        self._w("meta", {"spawn": args, "cwd": str(SCRATCH)})
        self.proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=(LOGS / f"{tag}-stderr.log").open("a"),
            cwd=str(SCRATCH), env=env, text=True, encoding="utf-8", bufsize=1,
        )
        self._next = 1
        self._pending: dict[int, "queue.Queue[dict]"] = {}
        self.events: "queue.Queue[dict]" = queue.Queue()
        self.decisions: list[dict] = []
        self.hold_approvals = False  # T6: leave the approval unanswered and interrupt instead
        self._lock = threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()

    def _w(self, direction: str, obj: dict) -> None:
        self.log.write(json.dumps({"t": round(time.time(), 3), "dir": direction, "msg": obj}) + "\n")
        self.log.flush()

    def _send(self, obj: dict) -> None:
        self._w("->", obj)
        with self._lock:
            assert self.proc.stdin
            self.proc.stdin.write(json.dumps(obj) + "\n")
            self.proc.stdin.flush()

    def _reader(self) -> None:
        assert self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self._w("<-raw", {"line": line[:500]})
                continue
            self._w("<-", msg)
            if "id" in msg and ("result" in msg or "error" in msg) and "method" not in msg:
                q = self._pending.pop(msg["id"], None)
                if q:
                    q.put(msg)
            elif "id" in msg and "method" in msg:
                self._on_server_request(msg)
            elif "method" in msg:
                self.events.put(msg)
        self.events.put({"method": "__eof__"})

    def request(self, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        rid = self._next
        self._next += 1
        q: "queue.Queue[dict]" = queue.Queue()
        self._pending[rid] = q
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        msg = q.get(timeout=timeout)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg["result"]

    def notify(self, method: str, params: dict | None = None) -> None:
        obj = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            obj["params"] = params
        self._send(obj)

    def _reply(self, rid, result: dict) -> None:
        self._send({"jsonrpc": "2.0", "id": rid, "result": result})

    def _on_server_request(self, msg: dict) -> None:
        m, p, rid = msg["method"], msg.get("params") or {}, msg["id"]
        if self.hold_approvals and m == "item/commandExecution/requestApproval":
            self.decisions.append({"kind": "command", "command": p.get("command"), "decision": "held"})
            self.events.put({"method": "__approval_held__", "params": p, "rid": rid})
            return
        if m in ("item/commandExecution/requestApproval", "execCommandApproval"):
            decision, why = gate_command(p)
            self.decisions.append({"kind": "command", "command": p.get("command"), "cwd": p.get("cwd"),
                                   "decision": decision, "why": why})
            self._reply(rid, {"decision": decision})
        elif m in ("item/fileChange/requestApproval", "applyPatchApproval"):
            self.decisions.append({"kind": "fileChange", "decision": "decline"})
            self._reply(rid, {"decision": "decline"})
        elif m == "mcpServer/elicitation/request":
            # TCC's own tools confirm themselves inside TCC's server: accept for `tcc`, decline others.
            action = "accept" if p.get("serverName") == "tcc" else "decline"
            self.decisions.append({"kind": "elicitation", "server": p.get("serverName"), "decision": action})
            self._reply(rid, {"action": action, "content": {} if action == "accept" else None})
        elif m == "item/permissions/requestApproval":
            self.decisions.append({"kind": "permissions", "decision": "decline"})
            self._send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "declined by spike"}})
        else:
            self.decisions.append({"kind": m, "decision": "error"})
            self._send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "not handled"}})

    def initialize(self) -> dict:
        r = self.request("initialize", {"clientInfo": {"name": "tcc-spike", "title": "TCC spike", "version": "0.0.1"},
                                        "capabilities": {"experimentalApi": True}})
        self.notify("initialized")
        return r

    def wait_for(self, pred, timeout: float = 180, on_event=None) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            try:
                ev = self.events.get(timeout=max(0.1, end - time.time()))
            except queue.Empty:
                break
            if on_event:
                on_event(ev)
            if ev.get("method") == "__eof__":
                raise RuntimeError("app-server exited")
            if pred(ev):
                return ev
        raise TimeoutError("event not seen")

    def close(self) -> None:
        try:
            assert self.proc.stdin
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        self._w("meta", {"exit": self.proc.returncode})
        self.log.close()


# --- scenarios -------------------------------------------------------------------------------

THREAD_BASE = {
    "cwd": str(SCRATCH),
    "approvalPolicy": "untrusted",
    "approvalsReviewer": "user",
    "sandbox": "workspace-write",
    "developerInstructions": "You are in a test harness. Keep every answer under 40 words unless asked otherwise.",
}
SANDBOX_POLICY = {"type": "workspaceWrite", "writableRoots": [], "networkAccess": False,
                  "excludeSlashTmp": True, "excludeTmpdirEnvVar": True}


def text(s: str) -> list[dict]:
    return [{"type": "text", "text": s}]


class Turn:
    """Collects one turn's events into a short summary."""

    def __init__(self) -> None:
        self.deltas: list[str] = []
        self.items: list[tuple[str, str, str]] = []
        self.completed: dict | None = None
        self.turn_id: str | None = None

    def on(self, ev: dict) -> None:
        m, p = ev.get("method"), ev.get("params") or {}
        if m == "turn/started":
            self.turn_id = (p.get("turn") or {}).get("id")
        elif m == "item/agentMessage/delta":
            self.deltas.append(p.get("delta", ""))
        elif m in ("item/started", "item/completed"):
            it = p.get("item") or {}
            self.items.append((m.split("/")[1], it.get("type", "?"), json.dumps(it)[:300]))
        elif m == "turn/completed":
            self.completed = p.get("turn")

    def summary(self) -> dict:
        return {"turn_id": self.turn_id, "n_deltas": len(self.deltas), "text": "".join(self.deltas)[:600],
                "items": [(a, b) for a, b, _ in self.items],
                "status": (self.completed or {}).get("status"), "error": (self.completed or {}).get("error")}


def run_turn(s: AppServer, thread_id: str, prompt: str, model: str, effort: str,
             during=None, timeout: float = 240) -> Turn:
    t = Turn()
    s.request("turn/start", {"threadId": thread_id, "input": text(prompt), "model": model, "effort": effort,
                             "sandboxPolicy": SANDBOX_POLICY})

    def on(ev):
        t.on(ev)
        if during:
            during(s, t, ev)

    s.wait_for(lambda ev: ev.get("method") == "turn/completed", timeout=timeout, on_event=on)
    return t


def cmd_probe() -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    s = AppServer("probe", {"TCC_MCP_TOKEN": os.environ.get("TCC_MCP_TOKEN", "")})
    out = {"initialize": s.initialize()}
    out["account"] = s.request("account/read", {})
    out["models"] = s.request("model/list", {})
    try:
        out["mcp"] = s.request("mcpServerStatus/list", {}, timeout=60)
    except Exception as e:  # noqa: BLE001
        out["mcp"] = str(e)
    s.close()
    print(json.dumps(out, indent=1)[:6000])


def cmd_run(model: str, effort: str) -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    s = AppServer("run", {"TCC_MCP_TOKEN": os.environ.get("TCC_MCP_TOKEN", "")})
    s.initialize()
    th = s.request("thread/start", {**THREAD_BASE, "model": model})
    tid = th["thread"]["id"]
    report: dict = {"thread_id": tid, "model": model, "effort": effort}

    # T1 — streaming + a real TCC tool read
    t1 = run_turn(s, tid, "Call the MCP tool get_tcc_state on the `tcc` server once, then reply with only "
                          "the value of its project_dir field.", model, effort)
    report["T1_stream_and_tcc_read"] = t1.summary()

    # T2 — approvals: one allowed (echo into scratch), one declined (touch)
    t2 = run_turn(s, tid, "Run exactly these two shell commands, one at a time, in the current folder, and "
                          "do not retry or work around a refusal: first `echo hi > note.txt`, then "
                          "`touch denied.txt`. Then say which ran.", model, effort)
    report["T2_approvals"] = {**t2.summary(), "decisions": list(s.decisions),
                              "note_exists": (SCRATCH / "note.txt").exists(),
                              "denied_exists": (SCRATCH / "denied.txt").exists()}

    # T3 — a window signal: turn/steer into the running turn after its first delta
    steered: dict = {}

    def steer(s_, t_, ev):
        if not steered and ev.get("method") == "item/agentMessage/delta" and t_.turn_id:
            steered["at_delta"] = len(t_.deltas)
            try:
                steered["resp"] = s_.request("turn/steer", {
                    "threadId": tid, "expectedTurnId": t_.turn_id,
                    "input": text("[TCC window signal] The user pressed STOP-LIST. Abandon the list and "
                                  "answer only: SIGNAL RECEIVED.")})
            except Exception as e:  # noqa: BLE001
                steered["error"] = str(e)

    t3 = run_turn(s, tid, "List the numbers from 1 to 120 in words, one per line.", model, effort, during=steer)
    report["T3_steer"] = {**t3.summary(), "steer": steered}

    # T4 — interrupt after the first delta
    intr: dict = {}

    def interrupt(s_, t_, ev):
        if not intr and ev.get("method") == "item/agentMessage/delta" and t_.turn_id:
            intr["at_delta"] = len(t_.deltas)
            intr["t0"] = time.time()
            try:
                intr["resp"] = s_.request("turn/interrupt", {"threadId": tid, "turnId": t_.turn_id})
            except Exception as e:  # noqa: BLE001
                intr["error"] = str(e)
        if ev.get("method") == "turn/completed" and "t0" in intr:
            intr["stop_s"] = round(time.time() - intr["t0"], 2)

    t4 = run_turn(s, tid, "Write the numbers from 1 to 200 in words, one per line.", model, effort, during=interrupt)
    report["T4_interrupt"] = {**t4.summary(), "interrupt": intr}

    # is the process still healthy after the interrupt?
    report["after_interrupt_thread_read"] = bool(s.request("thread/read", {"threadId": tid, "includeTurns": False}))
    s.close()
    (LOGS / "run-report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


def cmd_resume(tid: str, model: str, effort: str) -> None:
    s = AppServer("resume", {"TCC_MCP_TOKEN": os.environ.get("TCC_MCP_TOKEN", "")})
    s.initialize()
    r = s.request("thread/resume", {**THREAD_BASE, "threadId": tid, "model": model})
    turns = (r.get("thread") or {}).get("turns") or []
    report: dict = {"thread_id": r["thread"]["id"], "n_turns_restored": len(turns),
                    "turn_statuses": [t.get("status") for t in turns]}
    t5 = run_turn(s, tid, "Without calling any tool: what project_dir value did get_tcc_state return earlier "
                          "in this conversation, and what did the window signal ask you to answer? One line.",
                  model, effort)
    report["T5_after_resume"] = t5.summary()

    # T6 — interrupt while an approval is pending (the confirm bar is up and the user stops)
    s.hold_approvals = True
    held: dict = {}

    def stop_at_approval(s_, t_, ev):
        if ev.get("method") == "__approval_held__" and not held:
            held["command"] = ev["params"].get("command")
            held["t0"] = time.time()
            held["resp"] = s_.request("turn/interrupt", {"threadId": tid, "turnId": t_.turn_id})
        if ev.get("method") == "serverRequest/resolved":
            held["resolved_event"] = ev.get("params")
        if ev.get("method") == "turn/completed" and "t0" in held:
            held["stop_s"] = round(time.time() - held["t0"], 2)

    t6 = run_turn(s, tid, "Run the shell command `touch held.txt` in the current folder.", model, effort,
                  during=stop_at_approval)
    report["T6_interrupt_at_pending_approval"] = {**t6.summary(), "held": held,
                                                  "held_exists": (SCRATCH / "held.txt").exists()}
    s.close()
    (LOGS / "resume-report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


def cmd_tooltest(model: str, effort: str) -> None:
    """One turn, TCC_TOOLS_APPROVAL=approve: does Codex still ask before a `tcc` tool?"""
    s = AppServer("tooltest", {"TCC_MCP_TOKEN": os.environ.get("TCC_MCP_TOKEN", "")})
    s.initialize()
    th = s.request("thread/start", {**THREAD_BASE, "model": model, "ephemeral": True})
    tid = th["thread"]["id"]
    t = run_turn(s, tid, "Call the MCP tool get_capability_checklist on the `tcc` server once, then reply "
                         "with only the number of characters in its result, roughly.", model, effort)
    report = {"thread_id": tid, "tools_approval": os.environ.get("TCC_TOOLS_APPROVAL"),
              **t.summary(), "decisions": list(s.decisions)}
    s.close()
    (LOGS / "tooltest-report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "probe":
        cmd_probe()
    elif cmd == "run":
        cmd_run(sys.argv[2], sys.argv[3])
    elif cmd == "tooltest":
        cmd_tooltest(sys.argv[2], sys.argv[3])
    elif cmd == "resume":
        cmd_resume(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        raise SystemExit(__doc__)
