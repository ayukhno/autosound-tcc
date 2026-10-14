"""The Codex fixtures and the app-server stand-in (W-10 task 1, tcc#181).

`tests/fixtures/codex/*.jsonl` are real `codex app-server` wire logs (codex-cli 0.162.1, 2026-10-14),
cut by `spike/codex-app-server/cut_fixtures.py` and scrubbed of the Arbiter's identity. The stand-in
`tests/fakes/fake_codex_app_server.py` replays one of them over stdio; here a tiny scripted client
plays the recorded client side against it — no TCC session yet. Also: the fixtures parse and keep the
protocol's own invariant, every method the fixtures and the plan use is in the schema cut (the churn
guard: re-record on a new Codex, re-cut, and a vanished method fails here), and nothing identifies
the Arbiter.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures" / "codex"
SCHEMA = HERE / "fixtures" / "codex-schema-0.162.1"
FAKE = HERE / "fakes" / "fake_codex_app_server.py"

# What `docs/PLAN-W-10-codex.md` names in «The session» and its two tables.
PLAN_METHODS = {
    "ClientRequest.json": ["initialize", "thread/start", "thread/resume", "turn/start", "turn/interrupt",
                           "model/list", "account/read", "account/login/start", "account/login/cancel",
                           "config/read", "skills/list", "skills/extraRoots/set"],
    "ClientNotification.json": ["initialized"],
    "ServerRequest.json": ["item/commandExecution/requestApproval", "item/fileChange/requestApproval",
                           "mcpServer/elicitation/request", "item/permissions/requestApproval",
                           "item/tool/requestUserInput"],
    "ServerNotification.json": ["item/agentMessage/delta", "item/started", "item/completed", "turn/completed",
                                "error", "serverRequest/resolved", "deprecationNotice", "configWarning",
                                "thread/tokenUsage/updated", "account/rateLimits/updated",
                                "account/login/completed"],
}
REPLAYED = ["turn-mcp", "mcp-elicitation", "command-approval", "file-approval", "interrupt-pending",
            "resume-ok", "resume-error", "signed-out", "login-cancel", "config-skills", "skills-bundled-off"]
DYING = {"eof-mid-turn": "Codex exited while the MCP tool call ran", "startup-bad-mcp": "invalid transport"}
ID_SHIFT = 1000  # the client's ids differ from the recording's: the stand-in must answer under the live ones


def frames(name: str) -> list[dict]:
    return [json.loads(line) for line in (FIX / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()]


def is_request(m: dict) -> bool:
    return "method" in m and "id" in m


def is_response(m: dict) -> bool:
    return "method" not in m and "id" in m


# --- a scripted client ------------------------------------------------------------------------

class Client:
    """Plays a recording's "out" frames against the stand-in, in the recorded interleaving.

    `reply(msg)` may change the client's answer to a server request: return a list of messages to
    send instead (empty = do not answer), or None to stop the script and close stdin.
    """

    def __init__(self, name: str, tmp: Path, *, reply=None, before_close=None, timeout: float = 5,
                 extra: list[str] | None = None):
        self.name = name
        self.log = tmp / "fake.jsonl"
        self.work = tmp / "work dir ü"
        self.proc = subprocess.Popen(
            [sys.executable, str(FAKE), "app-server", "-c", "features.plugins=false", "--scenario", name,
             "--work", str(self.work), "--log", str(self.log), "--timeout", str(timeout), *(extra or [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.reply = reply
        self.before_close = before_close
        self.got: list[dict] = []
        self.eof = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for raw in self.proc.stdout:
            self.got.append(json.loads(raw))
        self.eof.set()

    def _wait_count(self, n: int, timeout: float = 10) -> None:
        end = time.time() + timeout
        while len(self.got) < n and not self.eof.is_set() and time.time() < end:
            time.sleep(0.005)

    def _send(self, msg: dict) -> None:
        self.proc.stdin.write(json.dumps(msg).encode() + b"\n")
        self.proc.stdin.flush()

    def play(self) -> tuple[int, str]:
        recorded = frames(self.name)
        seen_in = 0
        try:
            for f in recorded:
                if f["dir"] == "in":
                    seen_in += 1
                    continue
                if f["dir"] == "eof":
                    break
                self._wait_count(seen_in)
                m = dict(f["msg"])
                if is_request(m):
                    m["id"] = m["id"] + ID_SHIFT
                    self._send(m)
                elif is_response(m) and self.reply is not None:
                    out = self.reply(m)
                    if out is None:
                        break
                    for x in out:
                        self._send(x)
                else:
                    self._send(m)
            else:
                self._wait_count(seen_in)
                if self.before_close:
                    self.before_close(self)
        except BrokenPipeError:
            pass
        try:
            self.proc.stdin.close()
        except BrokenPipeError:
            pass
        code = self.proc.wait(timeout=20)
        self.eof.wait(5)
        return code, self.proc.stderr.read().decode()


# --- the stand-in replays every scenario -----------------------------------------------------

@pytest.mark.parametrize("name", REPLAYED)
def test_stand_in_replays_the_scenario(name: str, tmp_path: Path) -> None:
    client = Client(name, tmp_path)
    code, err = client.play()
    assert code == 0, err
    assert "ASSERT" not in err and "TIMEOUT" not in err, err

    recorded_in = [f["msg"] for f in frames(name) if f["dir"] == "in"]
    assert len(client.got) == len(recorded_in)
    asked = {f["msg"]["id"] for f in frames(name) if f["dir"] == "out" and is_request(f["msg"])}
    for got, rec in zip(client.got, recorded_in):
        if is_response(rec):
            assert got["id"] == rec["id"] + ID_SHIFT and rec["id"] in asked
        else:
            assert got.get("method") == rec["method"]
    text = json.dumps(client.got, ensure_ascii=False)
    assert "<WORK>" not in text
    if "<WORK>" in json.dumps(recorded_in, ensure_ascii=False):
        assert str(client.work) in text

    verdict = json.loads(client.log.read_text(encoding="utf-8").splitlines()[-1])["verdict"]
    assert verdict["breaches"] == []


def test_the_log_carries_argv_and_whether_the_token_is_in_the_env(tmp_path: Path) -> None:
    client = Client("signed-out", tmp_path)
    assert client.play()[0] == 0
    first = json.loads(client.log.read_text(encoding="utf-8").splitlines()[0])
    assert first["argv"][:3] == ["app-server", "-c", "features.plugins=false"]
    assert first["env"] == {"TCC_MCP_TOKEN": False}


@pytest.mark.parametrize("name", sorted(DYING))
def test_a_dying_codex_closes_stdout_and_exits_with_the_recorded_code(name: str, tmp_path: Path) -> None:
    client = Client(name, tmp_path)
    code, err = client.play()
    assert client.eof.is_set()
    assert code == 1
    assert DYING[name] in err


def test_the_approval_scenarios_carry_what_they_are_named_for() -> None:
    def server_requests(name):
        return [f["msg"]["method"] for f in frames(name) if f["dir"] == "in" and is_request(f["msg"])]

    def replies(name):
        return [f["msg"]["result"].get("decision") for f in frames(name)
                if f["dir"] == "out" and is_response(f["msg"])]

    assert server_requests("command-approval") == ["item/commandExecution/requestApproval"] * 2
    assert replies("command-approval") == ["accept", "decline"]
    assert server_requests("file-approval")[:2] == ["item/fileChange/requestApproval"] * 2
    assert replies("file-approval")[:2] == ["accept", "decline"]
    assert server_requests("mcp-elicitation") == ["mcpServer/elicitation/request"]
    assert "mcpToolCall" in json.dumps(frames("turn-mcp"))

    pending = frames("interrupt-pending")
    held = [f["msg"]["id"] for f in pending if f["dir"] == "in" and is_request(f["msg"])]
    resolved = [f["msg"]["params"]["requestId"] for f in pending
                if f["msg"].get("method") == "serverRequest/resolved"]
    assert held == resolved and not [f for f in pending if f["dir"] == "out" and is_response(f["msg"])]
    status = [f["msg"]["params"]["turn"]["status"] for f in pending if f["msg"].get("method") == "turn/completed"]
    assert status == ["interrupted"]


# --- the stand-in's check bites ----------------------------------------------------------------

def test_an_unanswered_server_request_fails_the_run(tmp_path: Path) -> None:
    client = Client("command-approval", tmp_path, reply=lambda m: None)
    code, err = client.play()
    assert code == 3
    assert "ASSERT server request id=1 (item/commandExecution/requestApproval) was never answered" in err


def test_a_second_answer_fails_the_run(tmp_path: Path) -> None:
    client = Client("command-approval", tmp_path, reply=lambda m: [m, m])
    code, err = client.play()
    assert code == 3
    assert "answered more than once" in err


def test_an_answer_to_a_withdrawn_request_fails_the_run(tmp_path: Path) -> None:
    late = {"id": 0, "result": {"decision": "accept"}}  # the approval Codex withdrew on interrupt
    code, err = Client("interrupt-pending", tmp_path, before_close=lambda c: c._send(late)).play()
    assert code == 3
    assert "answered after serverRequest/resolved withdrew it" in err


def test_an_answer_to_an_id_never_sent_fails_the_run(tmp_path: Path) -> None:
    client = Client("command-approval", tmp_path, reply=lambda m: [m, {"id": 77, "result": {"decision": "accept"}}])
    code, err = client.play()
    assert code == 3
    assert "id=77, which this server never sent" in err


def test_a_silent_client_times_out_with_a_named_step() -> None:
    proc = subprocess.Popen([sys.executable, str(FAKE), "--scenario", "signed-out", "--timeout", "0.3"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    code = proc.wait(timeout=10)  # stdin stays open and silent
    err = proc.stderr.read().decode()
    proc.stdin.close()
    assert code == 4
    assert "TIMEOUT 0.3s waiting for the client: initialize (frame 1)" in err


def test_an_unrecorded_request_gets_an_error_and_a_default_gets_its_answer(tmp_path: Path) -> None:
    proc = subprocess.Popen([sys.executable, str(FAKE), "--scenario", "resume-error"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    msgs = [{"id": 1, "method": "skills/extraRoots/set", "params": {"extraRoots": []}},
            {"id": 2, "method": "thread/fork", "params": {}}]
    out, err = proc.communicate(b"".join(json.dumps(m).encode() + b"\n" for m in msgs), timeout=10)
    got = [json.loads(line) for line in out.splitlines()]
    assert {"id": 1, "result": {}} in got
    assert any(g.get("id") == 2 and "no recorded answer for thread/fork" in g["error"]["message"] for g in got)
    assert proc.returncode == 0, err


def test_version_and_usage() -> None:
    out = subprocess.run([sys.executable, str(FAKE), "--version"], capture_output=True, text=True)
    assert out.stdout.strip() == "codex-cli 0.162.1"
    env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_CODEX_")}
    out = subprocess.run([sys.executable, str(FAKE), "app-server"], capture_output=True, text=True, env=env)
    assert out.returncode == 2 and "no scenario" in out.stderr


def test_the_stand_in_is_an_executable_stdlib_script() -> None:
    text = FAKE.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env python3\n")
    assert os.access(FAKE, os.X_OK)
    imports = set(re.findall(r"^(?:from|import) ([a-z_]+)", text, re.M))
    assert imports <= {"__future__", "json", "os", "queue", "sys", "threading", "time", "pathlib"}


# --- the fixtures themselves -------------------------------------------------------------------

ALL = sorted(p.stem for p in FIX.glob("*.jsonl"))


@pytest.mark.parametrize("name", ALL)
def test_a_fixture_parses_and_keeps_the_protocol_invariant(name: str) -> None:
    fs = frames(name)
    assert fs and all(f["dir"] in ("in", "out", "eof") for f in fs)
    assert all(isinstance(f["t"], (int, float)) for f in fs)
    assert [f for f in fs if f["dir"] == "eof"] in ([], [fs[-1]])
    asked = {f["msg"]["id"] for f in fs if f["dir"] == "out" and is_request(f["msg"])}
    answered = [f["msg"]["id"] for f in fs if f["dir"] == "in" and is_response(f["msg"])]
    assert set(answered) <= asked and len(answered) == len(set(answered))
    # Codex's side of the same rule: each server request answered once or withdrawn, never both.
    sent = [f["msg"]["id"] for f in fs if f["dir"] == "in" and is_request(f["msg"])]
    replies = [f["msg"]["id"] for f in fs if f["dir"] == "out" and is_response(f["msg"])]
    assert len(replies) == len(set(replies)) and set(replies) <= set(sent)
    if name != "interrupt-pending":
        assert set(replies) == set(sent)


def test_the_wheel_layout_names_one_binary_per_platform() -> None:
    w = json.loads((FIX / "wheel-0.162.1.json").read_text())
    assert set(w["wheels"]) == {"macos-arm64", "macos-x86_64", "windows-amd64", "windows-arm64"}
    for plat, row in w["wheels"].items():
        members = {m["path"]: m for m in row["members"]}
        assert members[row["binary"]]["mode"] == "0o100755", plat
        assert row["binary"].endswith(".exe") == plat.startswith("windows")
        assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"])


# --- the churn guard -----------------------------------------------------------------------------

def _schema_methods(bundle: str) -> set[str]:
    doc = json.loads((SCHEMA / bundle).read_text())
    return {v["properties"]["method"]["enum"][0] for v in doc["oneOf"]}


def _fixture_methods() -> dict[str, set[str]]:
    kinds = {b: set() for b in PLAN_METHODS}
    for name in ALL:
        for f in frames(name):
            m = f.get("msg") or {}
            if "method" not in m:
                continue
            if f["dir"] == "out":
                kinds["ClientRequest.json" if "id" in m else "ClientNotification.json"].add(m["method"])
            else:
                kinds["ServerRequest.json" if "id" in m else "ServerNotification.json"].add(m["method"])
    return kinds


@pytest.mark.parametrize("bundle", sorted(PLAN_METHODS))
def test_every_method_in_the_fixtures_and_the_plan_is_in_the_schema_cut(bundle: str) -> None:
    have = _schema_methods(bundle)
    want = set(PLAN_METHODS[bundle]) | _fixture_methods()[bundle]
    assert want - have == set(), f"not in {bundle} of codex-schema-0.162.1"


def test_every_client_request_has_its_response_schema() -> None:
    index = json.loads((SCHEMA / "index.json").read_text())
    assert index["codex"] == "codex-cli 0.162.1"
    for method in PLAN_METHODS["ClientRequest.json"] + PLAN_METHODS["ServerRequest.json"]:
        name = index["responses"].get(method)
        assert name and (SCHEMA / "responses" / name).exists(), method


# --- nothing that identifies the Arbiter ----------------------------------------------------------

def test_no_fixture_carries_the_arbiters_identity() -> None:
    home = str(Path.home())
    user = Path.home().name
    email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    paths = [*FIX.iterdir(), *SCHEMA.rglob("*.json")]
    for p in paths:
        text = p.read_text(encoding="utf-8")
        assert home not in text, p.name
        assert not re.search(r"(/Users/|/home/|[A-Z]:\\\\Users\\\\)(?!arbiter)[A-Za-z]", text), p.name
        if user not in ("arbiter", "runner", "root"):
            assert user not in text, p.name
        for found in email.findall(text):
            assert found.endswith("@example.com"), (p.name, found)
        assert not re.search(r"192\.168\.\d|10\.\d+\.\d+\.\d+:\d", text), p.name
