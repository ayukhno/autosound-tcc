"""Cut the git-ignored wire logs into `tests/fixtures/codex/` and the schema into
`tests/fixtures/codex-schema-0.162.1/` (W-10 task 1, tcc#181).

    python3 cut_fixtures.py            # from work/logs (the spike) and work/w10/logs (record_w10.py)

A fixture line is one frame: {"dir": "out"|"in"|"eof", "t": seconds from the first frame, "msg": {...}}.
"out" = the client (TCC) to Codex, "in" = Codex to the client. An "eof" line ends the recording the
way a dying process does: {"dir": "eof", "exit": N, "stderr": "..."}.

Cuts: a scenario is the log's header (initialize … up to the first `turn/start`) plus the turns it is
about. Four edits, all named here: the spike's full-history `thread/resume` keeps `turns: []`;
`config/read` keeps the keys the isolation list reads (no `origins`, `layers`, projects, env values);
`model/list` is dropped (it has its own fixture); `eof-mid-turn` is a real turn cut short.
Then the Arbiter's identity is scrubbed (e-mail, names, host, home paths, installation id, LAN host).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SPIKE_LOGS = HERE / "work" / "logs"
W10_LOGS = HERE / "work" / "w10" / "logs"
OUT = REPO / "tests" / "fixtures" / "codex"
SCHEMA_OUT = REPO / "tests" / "fixtures" / "codex-schema-0.162.1"

HOME = str(Path.home())
SCRUB: list[tuple[str, str]] = [
    (str(HERE / "work" / "w10" / "scratch"), "<WORK>"),
    (str(HERE / "work" / "scratch"), "<WORK>"),
    (str(HERE / "work" / "w10" / "skills"), "<SKILLS>"),
    (str(HERE / "work" / "w10" / "empty-codex-home"), "<CODEX_HOME>"),
    (str(HERE / "work" / "tcc-project"), "<TCC_PROJECT>"),
    (HOME + "/.codex", "<CODEX_HOME>"),
    (HOME, "<HOME>"),
]
SCRUB_RE: list[tuple[str, str]] = [
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "arbiter@example.com"),
    (r"MacBook-Pro-[A-Za-z]+\.local", "arbiter-mac.local"),
    (r"o\.yukhno|ayukhno|Olena|olena", "arbiter"),
    (r'"installationId": "[0-9a-f-]+"', '"installationId": "00000000-0000-4000-8000-000000000001"'),
    (r"192\.168\.\d+\.\d+", "192.0.2.1"),
    (r"(state|code_challenge)=[A-Za-z0-9_\-]+", r"\1=REDACTED"),
]


def scrub(text: str) -> str:
    for a, b in SCRUB:
        text = text.replace(a, b)
    for a, b in SCRUB_RE:
        text = re.sub(a, b, text)
    return text


# --- reading and slicing ---------------------------------------------------------------------

def frames(path: Path) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        e = json.loads(line)
        if e["dir"] == "meta":
            continue
        out.append({"dir": "out" if e["dir"] == "->" else "in", "t": e["t"], "msg": e["msg"]})
    return out


def is_req(f: dict, method: str | None = None) -> bool:
    m = f["msg"]
    return f["dir"] == "out" and "method" in m and "id" in m and (method is None or m["method"] == method)


def header(fs: list[dict]) -> list[dict]:
    for i, f in enumerate(fs):
        if is_req(f, "turn/start"):
            return fs[:i]
    return fs


def turn(fs: list[dict], k: int) -> list[dict]:
    """The k-th turn (0-based): its `turn/start` up to the next client request after `turn/completed`."""
    starts = [i for i, f in enumerate(fs) if is_req(f, "turn/start")]
    i = starts[k]
    done = False
    for j in range(i + 1, len(fs)):
        f = fs[j]
        if f["dir"] == "in" and f["msg"].get("method") == "turn/completed":
            done = True
        elif done and is_req(f):
            return fs[i:j]
    return fs[i:]


def request_pair(fs: list[dict], method: str, nth: int = 0, trailing: bool = True) -> list[dict]:
    """The nth request of `method`, its response, and (if `trailing`) the in-frames up to the next request."""
    idx = [i for i, f in enumerate(fs) if is_req(f, method)][nth]
    rid = fs[idx]["msg"]["id"]
    out = [fs[idx]]
    for f in fs[idx + 1:]:
        if is_req(f):
            break
        if f["dir"] == "in" and f["msg"].get("id") == rid and "method" not in f["msg"]:
            out.append(f)
            if not trailing:
                break
        elif trailing:
            out.append(f)
    return out


def drop_requests(fs: list[dict], method: str) -> list[dict]:
    ids = {f["msg"]["id"] for f in fs if is_req(f, method)}
    return [f for f in fs if not (is_req(f, method) or (f["dir"] == "in" and "method" not in f["msg"]
                                                        and f["msg"].get("id") in ids))]


# --- structural cuts -------------------------------------------------------------------------

def empty_resume_turns(fs: list[dict]) -> list[dict]:
    ids = {f["msg"]["id"] for f in fs if is_req(f, "thread/resume")}
    for f in fs:
        m = f["msg"]
        if f["dir"] == "in" and m.get("id") in ids and "result" in m:
            m["result"]["thread"]["turns"] = []
    return fs


CONFIG_DICTS = ("features", "mcp_servers", "plugins", "skills", "hooks", "apps", "memories", "tools",
                "shell_environment_policy", "notify")
MCP_KEEP = ("enabled", "url", "command", "required")


def cut_config(fs: list[dict]) -> list[dict]:
    ids = {f["msg"]["id"] for f in fs if is_req(f, "config/read")}
    for f in fs:
        m = f["msg"]
        if f["dir"] == "in" and m.get("id") in ids and "result" in m:
            c = m["result"]["config"]
            keep = {k: v for k, v in c.items() if not isinstance(v, (dict, list)) and k not in ("instructions",)}
            for k in CONFIG_DICTS:
                v = c.get(k)
                if k == "mcp_servers" and v:
                    v = {n: {kk: vv for kk, vv in s.items() if kk in MCP_KEEP} for n, s in v.items()}
                elif k == "plugins" and v:
                    v = {n: {"enabled": s.get("enabled")} for n, s in v.items()}
                elif k == "shell_environment_policy" and v:
                    v = {kk: ({n: "REDACTED" for n in vv} if isinstance(vv, dict) else vv) for kk, vv in v.items()}
                keep[k] = v
            m["result"] = {"config": dict(sorted(keep.items()))}
    return fs


def relative(fs: list[dict]) -> list[dict]:
    t0 = fs[0]["t"] if fs else 0
    return [{**f, "t": round(f["t"] - t0, 3)} for f in fs]


def write(name: str, fs: list[dict]) -> None:
    fs = relative(json.loads(json.dumps(fs)))
    text = "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in fs)
    (OUT / f"{name}.jsonl").write_text(scrub(text))
    print(f"{name}: {len(fs)} frames")


# --- the scenarios ---------------------------------------------------------------------------

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tool = frames(SPIKE_LOGS / "tooltest-wire.jsonl")
    run = frames(SPIKE_LOGS / "run-wire.jsonl")
    res = frames(SPIKE_LOGS / "resume-wire.jsonl")
    edits = frames(W10_LOGS / "edits-wire.jsonl")
    res10 = frames(W10_LOGS / "resume-wire.jsonl")
    login = frames(W10_LOGS / "login-wire.jsonl")
    config = frames(W10_LOGS / "config-wire.jsonl")
    skillsoff = frames(W10_LOGS / "skillsoff-wire.jsonl")
    badmcp = frames(W10_LOGS / "badmcp-wire.jsonl")
    # `request_pair(..., trailing=True)` already carries the `initialized` that follows the reply;
    # appending it again recorded it twice in resume-ok / resume-error (task 6's review, Minor 7).
    init10 = request_pair(res10, "initialize")

    write("turn-mcp", header(tool) + turn(tool, 0))
    write("mcp-elicitation", header(run) + turn(run, 0))
    write("command-approval", header(run) + turn(run, 1))
    write("file-approval", header(edits) + turn(edits, 0) + turn(edits, 1))
    write("interrupt-pending", empty_resume_turns(header(res)) + turn(res, 1))

    t = turn(tool, 0)
    cut = next(i for i, f in enumerate(t) if f["msg"].get("method") == "item/started"
               and (f["msg"]["params"]["item"].get("type") == "mcpToolCall"))
    write("eof-mid-turn", header(tool) + t[:cut + 1] + [
        {"dir": "eof", "t": t[cut]["t"] + 0.5, "exit": 1,
         "stderr": "stand-in: the recording is cut here; Codex exited while the MCP tool call ran"}])

    write("resume-ok", init10 + request_pair(res10, "thread/resume", nth=1))
    write("resume-error", init10 + request_pair(res10, "thread/resume", nth=0, trailing=False))
    write("signed-out", request_pair(login, "initialize") + request_pair(login, "account/read"))
    write("login-cancel", [f for f in login])
    write("config-skills", cut_config(drop_requests(config, "model/list")))
    write("skills-bundled-off", skillsoff)
    stderr = (W10_LOGS / "badmcp-stderr.log").read_text().strip()
    write("startup-bad-mcp", badmcp + [{"dir": "eof", "t": badmcp[-1]["t"] + 0.2, "exit": 1, "stderr": stderr}])
    schema()


# --- the schema cut --------------------------------------------------------------------------

PLAN_METHODS = {
    "client": ["initialize", "thread/start", "thread/resume", "thread/read", "turn/start", "turn/interrupt",
               "turn/steer", "model/list", "account/read", "account/login/start", "account/login/cancel",
               "config/read", "skills/list", "skills/extraRoots/set", "mcpServerStatus/list"],
    "server_request": ["item/commandExecution/requestApproval", "item/fileChange/requestApproval",
                       "mcpServer/elicitation/request", "item/permissions/requestApproval",
                       "item/tool/requestUserInput"],
    "notification": ["item/agentMessage/delta", "item/started", "item/completed", "turn/started",
                     "turn/completed", "error", "serverRequest/resolved", "deprecationNotice", "configWarning",
                     "thread/tokenUsage/updated", "account/rateLimits/updated", "account/login/completed",
                     "account/updated", "skills/changed"],
    "client_notification": ["initialized"],
}
BUNDLES = {"client": "ClientRequest.json", "server_request": "ServerRequest.json",
           "notification": "ServerNotification.json", "client_notification": "ClientNotification.json"}


def fixture_methods() -> dict[str, set[str]]:
    """Every method in the fixtures, by kind (a server request has an id and comes in)."""
    kinds: dict[str, set[str]] = {k: set() for k in BUNDLES}
    for p in OUT.glob("*.jsonl"):
        for line in p.read_text().splitlines():
            f = json.loads(line)
            m = f.get("msg") or {}
            if "method" not in m:
                continue
            if f["dir"] == "out":
                kinds["client" if "id" in m else "client_notification"].add(m["method"])
            else:
                kinds["server_request" if "id" in m else "notification"].add(m["method"])
    return kinds


def _refs(node, acc: set[str]) -> None:
    if isinstance(node, dict):
        r = node.get("$ref")
        if isinstance(r, str) and r.startswith("#/definitions/"):
            acc.add(r.rsplit("/", 1)[1])
        for v in node.values():
            _refs(v, acc)
    elif isinstance(node, list):
        for v in node:
            _refs(v, acc)


def _prune(doc: dict, roots) -> dict:
    defs = doc.get("definitions", {})
    seen: set[str] = set()
    todo: set[str] = set()
    _refs(roots, todo)
    while todo:
        n = todo.pop()
        if n in seen or n not in defs:
            continue
        seen.add(n)
        _refs(defs[n], todo)
    return {k: defs[k] for k in sorted(seen)}


def schema() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["codex", "app-server", "generate-json-schema", "--experimental", "--out", tmp],
                       check=True, capture_output=True)
        version = subprocess.run(["codex", "--version"], capture_output=True, text=True).stdout.strip()
        found = fixture_methods()
        if SCHEMA_OUT.exists():
            shutil.rmtree(SCHEMA_OUT)
        SCHEMA_OUT.mkdir(parents=True)
        responses = {}
        for kind, fname in BUNDLES.items():
            doc = json.loads((Path(tmp) / fname).read_text())
            want = set(PLAN_METHODS[kind]) | found[kind]
            keep = [v for v in doc["oneOf"] if v["properties"]["method"]["enum"][0] in want]
            got = {v["properties"]["method"]["enum"][0] for v in keep}
            missing = want - got
            if missing:
                sys.exit(f"not in the {version} schema ({fname}): {sorted(missing)}")
            cut = {k: v for k, v in doc.items() if k not in ("oneOf", "definitions")}
            cut["oneOf"] = keep
            cut["definitions"] = _prune(doc, keep)
            (SCHEMA_OUT / fname).write_text(json.dumps(cut, indent=1, sort_keys=True) + "\n")
            if kind in ("client", "server_request"):
                for v in keep:
                    method = v["properties"]["method"]["enum"][0]
                    pref = v["properties"].get("params", {}).get("$ref", "")
                    name = pref.rsplit("/", 1)[-1]
                    if name.endswith("Params"):
                        responses[method] = name[: -len("Params")] + "Response"
        resp_dir = SCHEMA_OUT / "responses"
        resp_dir.mkdir()
        index = {}
        for method, rname in sorted(responses.items()):
            src = next((p for p in (Path(tmp) / "v2" / f"{rname}.json", Path(tmp) / f"{rname}.json",
                                    Path(tmp) / "v1" / f"{rname}.json") if p.exists()), None)
            if src is None:
                index[method] = None
                continue
            shutil.copyfile(src, resp_dir / src.name)
            index[method] = src.name
        (SCHEMA_OUT / "index.json").write_text(json.dumps(
            {"codex": version, "generated_with": "codex app-server generate-json-schema --experimental",
             "methods": {k: sorted(set(PLAN_METHODS[k]) | found[k]) for k in BUNDLES},
             "responses": index}, indent=1) + "\n")
        print(f"schema: {sum(len(set(PLAN_METHODS[k]) | found[k]) for k in BUNDLES)} methods, "
              f"{len(index)} responses ({version})")


if __name__ == "__main__":
    main()
