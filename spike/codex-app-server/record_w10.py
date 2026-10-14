"""W-10 task 1 recording: what the spike left out (tcc#181).

Reuses `client.AppServer`. Every process gets its own wire log in `work/w10/logs/`; the cut into
`tests/fixtures/codex/` is `cut_fixtures.py`.

    python3 record_w10.py config      # P1a no model: config/read, skills/list ± extraRoots, model/list
    python3 record_w10.py skillsoff [key]  # P1b no model: skills/list with a user-skills key off
    python3 record_w10.py edits <model> <effort>     # P1c: 2 tiny turns, fileChange accept + decline
    python3 record_w10.py resume <thread_id> <model>  # P2 no model: resume error + excludeTurns
    python3 record_w10.py login       # P3 no model, an EMPTY CODEX_HOME: account/read, login start+cancel

Safety: cwd = work/w10/scratch; thread sandbox read-only (so every edit asks), one turn with
workspace-write limited to the scratch folder; network off; the client accepts the first file change
(the prompt names a file in the scratch folder, checked after the run), declines every other one and
every command.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import client as C

HERE = Path(__file__).resolve().parent
W10 = HERE / "work" / "w10"
C.SCRATCH = W10 / "scratch"
C.LOGS = W10 / "logs"
SKILL_ROOT = W10 / "skills"  # a copy of the method's SKILL.md only — the extra root
VENDORED = HERE.parents[1] / "vendor" / "autosound-tuning-skill" / "skills" / "autosound-tuning" / "SKILL.md"


def _prep() -> None:
    C.SCRATCH.mkdir(parents=True, exist_ok=True)
    (SKILL_ROOT / "autosound-tuning").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(VENDORED, SKILL_ROOT / "autosound-tuning" / "SKILL.md")


class Recorder(C.AppServer):
    """Accepts the first file change inside the scratch folder, declines the rest and every command."""

    def __init__(self, tag: str, env_extra: dict[str, str] | None = None, extra_args: list[str] | None = None):
        self._extra_args = extra_args or []
        orig = C.codex_args
        C.codex_args = lambda: [*orig(), *self._extra_args]
        try:
            super().__init__(tag, env_extra)
        finally:
            C.codex_args = orig
        self.accepted_edits = 0

    def _on_server_request(self, msg: dict) -> None:
        m, rid = msg["method"], msg["id"]
        if m == "item/fileChange/requestApproval":
            ok = self.accepted_edits == 0
            self.accepted_edits += ok
            decision = "accept" if ok else "decline"
            self.decisions.append({"kind": "fileChange", "decision": decision})
            self._reply(rid, {"decision": decision})
        elif m == "item/commandExecution/requestApproval":
            self.decisions.append({"kind": "command", "command": (msg.get("params") or {}).get("command"),
                                   "decision": "decline"})
            self._reply(rid, {"decision": "decline"})
        else:
            super()._on_server_request(msg)


THREAD = {
    "cwd": str(C.SCRATCH),
    "approvalPolicy": "untrusted",
    "approvalsReviewer": "user",
    "sandbox": "read-only",
    "developerInstructions": "You are in a test harness. Keep every answer under 20 words.",
}
WS_POLICY = {"type": "workspaceWrite", "writableRoots": [], "networkAccess": False,
             "excludeSlashTmp": True, "excludeTmpdirEnvVar": True}


def _safe(req, *a, **kw):
    try:
        return req(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def cmd_config() -> None:
    _prep()
    s = Recorder("config")
    s.initialize()
    out = {"config": s.request("config/read", {"cwd": str(C.SCRATCH)})}
    out["skills_before"] = s.request("skills/list", {"cwds": [str(C.SCRATCH)]})
    out["extra"] = s.request("skills/extraRoots/set", {"extraRoots": [str(SKILL_ROOT)]})
    out["skills_after"] = s.request("skills/list", {"cwds": [str(C.SCRATCH)], "forceReload": True})
    out["models"] = [(m["id"], [e["reasoningEffort"] for e in m["supportedReasoningEfforts"]])
                     for m in s.request("model/list", {})["data"]]
    s.close()
    print(json.dumps({k: (v if k != "config" else list(v)) for k, v in out.items()}, indent=1)[:5000])


def cmd_skillsoff(key: str = "skills.bundled.enabled=false") -> None:
    """`features.skip_host_skill_discovery=true` left the bundled skills in; `skills.bundled.enabled=false` is the try."""
    _prep()
    s = Recorder("skillsoff", extra_args=["-c", key])
    s.initialize()
    s.request("skills/extraRoots/set", {"extraRoots": [str(SKILL_ROOT)]})
    r = s.request("skills/list", {"cwds": [str(C.SCRATCH)], "forceReload": True})
    s.close()
    print(json.dumps(r, indent=1)[:3000])


def cmd_edits(model: str, effort: str) -> None:
    _prep()
    s = Recorder("edits")
    s.initialize()
    tid = s.request("thread/start", {**THREAD, "model": model})["thread"]["id"]
    report: dict = {"thread_id": tid}
    t1 = _turn(s, tid, model, effort, None,
               "Using your file-editing tool (apply_patch, not a shell command), create yes.txt "
               "containing `yes`; then, as a separate edit, create no.txt containing `no`. "
               "Do not retry a refused edit. Then say which files exist.")
    report["F1"] = {**t1.summary(), "decisions": list(s.decisions),
                    "yes": (C.SCRATCH / "yes.txt").exists(), "no": (C.SCRATCH / "no.txt").exists()}
    s.decisions.clear()
    t2 = _turn(s, tid, model, effort, WS_POLICY,
               "Using apply_patch, create ws.txt containing `ws`. Do not retry if refused. One word reply.")
    report["F2_workspace_write"] = {**t2.summary(), "decisions": list(s.decisions),
                                    "ws": (C.SCRATCH / "ws.txt").exists()}
    s.close()
    (C.LOGS / "edits-report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


def _turn(s, tid, model, effort, policy, prompt):
    t = C.Turn()
    params = {"threadId": tid, "input": C.text(prompt), "model": model, "effort": effort}
    if policy:
        params["sandboxPolicy"] = policy
    s.request("turn/start", params)
    s.wait_for(lambda ev: ev.get("method") == "turn/completed", timeout=240, on_event=t.on)
    return t


def cmd_resume(tid: str, model: str) -> None:
    _prep()
    s = Recorder("resume")
    s.initialize()
    bogus = "00000000-0000-7000-8000-000000000000"
    out = {"bogus": _safe(s.request, "thread/resume", {**THREAD, "threadId": bogus, "excludeTurns": True,
                                                       "model": model})}
    r = s.request("thread/resume", {**THREAD, "threadId": tid, "excludeTurns": True, "model": model})
    out["ok"] = {"id": r["thread"]["id"], "turns": len(r["thread"].get("turns") or []), "keys": list(r)}
    time.sleep(2)  # let trailing notifications land in the log
    s.close()
    print(json.dumps(out, indent=1))


def cmd_login() -> None:
    _prep()
    home = W10 / "empty-codex-home"
    home.mkdir(parents=True, exist_ok=True)
    # The spike's off-switches name the Arbiter's MCP servers; in an empty CODEX_HOME they do not exist
    # and `-c mcp_servers.<absent>.enabled=false` kills the app-server at start ("invalid transport").
    orig = C.codex_args
    C.codex_args = lambda: ["app-server"]
    try:
        s = Recorder("login", env_extra={"CODEX_HOME": str(home)})
    finally:
        C.codex_args = orig
    s.initialize()
    out = {"account": s.request("account/read", {})}
    start = s.request("account/login/start", {"type": "chatgpt"})
    out["start_keys"] = list(start)
    out["cancel"] = _safe(s.request, "account/login/cancel", {"loginId": start.get("loginId")})
    try:
        out["completed"] = s.wait_for(lambda ev: ev.get("method") == "account/login/completed", timeout=5)
    except TimeoutError:
        out["completed"] = None
    out["second_cancel"] = _safe(s.request, "account/login/cancel", {"loginId": start.get("loginId")})
    s.close()
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:]
    {"config": cmd_config, "skillsoff": cmd_skillsoff, "edits": cmd_edits, "resume": cmd_resume,
     "login": cmd_login}[cmd](*rest)
