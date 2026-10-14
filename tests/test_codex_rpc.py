"""`core/codex_rpc.py` — the one JSON-RPC client over stdio for `codex app-server` (W-10 task 3, tcc#181).

Against the stand-in from task 1 (`tests/fakes/fake_codex_app_server.py`, replaying the recorded
scenarios in `tests/fixtures/codex/`) and, where the wire itself is the point, a few-line scripted
server. No real `codex` runs here.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

from autosound_tcc.core import codex_cli, codex_rpc
from autosound_tcc.core import model_choices as mc
from autosound_tcc.core.codex_rpc import AppServer, ConnectionLost, Notify, RpcError

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures" / "codex"
FAKE = HERE / "fakes" / "fake_codex_app_server.py"

# Bound at import, before conftest's guard swaps it for a stub.
_REAL_ASK_CODEX = mc._ask_codex_models

posix_only = pytest.mark.skipif(os.name == "nt", reason="a POSIX script stands in for codex")


def frames(name: str) -> list[dict]:
    return [json.loads(line) for line in (FIX / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def write_scenario(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def fake(scenario, log: Path, *extra: str) -> list[str]:
    return [sys.executable, str(FAKE), "--scenario", str(scenario), "--log", str(log),
            "--timeout", "5", *extra]


def fake_log(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def verdict(log: Path) -> dict:
    return [row for row in fake_log(log) if "verdict" in row][-1]["verdict"]


def script(tmp_path: Path, body: str) -> list[str]:
    path = tmp_path / "server.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(path)]


def opening() -> list[dict]:
    """The recorded `initialize` exchange and `initialized`."""
    rec = frames("config-skills")
    return [rec[0], rec[1], {"dir": "out", "t": 0.6, "msg": {"jsonrpc": "2.0", "method": "initialized"}}]


async def until(server: AppServer, pred, seconds: float = 10.0) -> list[dict]:
    """Notifications read until `pred(msg)`; fails the test on the process ending first."""
    seen: list[dict] = []
    deadline = time.monotonic() + seconds
    while True:
        msg = await asyncio.wait_for(server.notifications.get(), max(0.1, deadline - time.monotonic()))
        assert msg is not None, f"the process ended first; seen {[m['method'] for m in seen]}"
        seen.append(msg)
        if pred(msg):
            return seen


def run(coro):
    return asyncio.run(coro)


# ---- initialize ------------------------------------------------------------------------------

def test_open_initializes_with_the_experimental_api_then_says_initialized(tmp_path):
    log = tmp_path / "fake.jsonl"

    async def go():
        server = AppServer(fake("signed-out", log), cwd=tmp_path)
        result = await server.open()
        await server.close()
        return result

    result = run(go())

    assert result["platformFamily"] == "unix"
    out = [row["msg"] for row in fake_log(log) if row.get("dir") == "out"]
    assert out[0]["method"] == "initialize"
    assert out[0]["params"]["capabilities"] == {"experimentalApi": True}
    assert out[0]["params"]["clientInfo"]["name"] == "autosound-tcc"
    assert out[1] == {"jsonrpc": "2.0", "method": "initialized"}


def test_an_end_before_initialize_answers_is_a_clean_connection_lost_with_stderr(tmp_path):
    """Task 1: a bad `-c mcp_servers.<x>.enabled=false` makes app-server exit 1 at start."""
    log = tmp_path / "fake.jsonl"
    holder = {}

    async def go():
        server = AppServer(fake("startup-bad-mcp", log))
        holder["server"] = server
        with pytest.raises(ConnectionLost) as caught:
            await server.open(timeout=10)
        tail = await asyncio.wait_for(server.notifications.get(), 2)
        return caught.value, tail

    lost, tail = run(go())

    assert "invalid transport" in str(lost) and "invalid transport" in lost.stderr_tail
    assert lost.returncode == 1 and holder["server"].returncode == 1
    assert tail is None, "the queue says the process ended"


def test_a_binary_that_cannot_start_is_connection_lost(tmp_path):
    async def go():
        with pytest.raises(ConnectionLost, match="cannot start"):
            await AppServer([str(tmp_path / "no-such-codex")]).open()

    run(go())


# ---- answers to the server's requests: exactly once --------------------------------------------

def test_each_server_request_is_answered_once_and_a_second_answer_is_refused(tmp_path):
    """command-approval: two approvals, each answered once; the recorded `serverRequest/resolved`
    then arrives for an answered request — not a withdrawal."""
    log = tmp_path / "fake.jsonl"
    seconds: list[bool] = []

    async def go():
        server: AppServer

        def on_request(msg):
            assert server.respond(msg["id"], {"decision": "accept"}) is True
            seconds.append(server.respond(msg["id"], {"decision": "decline"}))

        server = AppServer(fake("command-approval", log), on_request=on_request)
        await server.open()
        await server.request("thread/start", {"cwd": str(tmp_path)})
        await server.request("turn/start", {"threadId": "t", "input": []})
        resolved = [m for m in await until(server, lambda m: m["method"] == "serverRequest/resolved"
                                           and m["params"]["requestId"] == 2)
                    if m["method"] == "serverRequest/resolved"]
        state = (server.withdrawn(1), server.withdrawn(2), server.resolved(1), server.respond(1, {}),
                 server.respond(99, {}))
        await server.close()
        return server, resolved, state

    server, resolved, state = run(go())

    assert seconds == [False, False]
    assert [m["params"]["requestId"] for m in resolved] == [1, 2]
    assert state == (False, False, False, False, False), \
        "resolved for an answered id is no withdrawal; no third answer; no answer to an unknown id"
    assert server.returncode == 0
    v = verdict(log)
    assert v["breaches"] == [] and v["answers"] == {"1": 1, "2": 1}
    replies = [row["msg"] for row in fake_log(log)
               if row.get("dir") == "out" and "method" not in row["msg"] and "id" in row["msg"]]
    assert [r["id"] for r in replies] == [1, 2] and all(r["result"] == {"decision": "accept"}
                                                         for r in replies)


def test_an_answer_after_the_server_withdrew_the_request_is_refused(tmp_path):
    """interrupt-pending: the approval is still open when `turn/interrupt` goes, and
    `serverRequest/resolved` withdraws it; a gate finishing later must not answer."""
    log = tmp_path / "fake.jsonl"
    asked: list[dict] = []

    async def go():
        server = AppServer(fake("interrupt-pending", log), on_request=asked.append)
        await server.open()
        await server.request("thread/resume", {"threadId": "t"})
        await server.request("turn/start", {"threadId": "t", "input": []})
        while not asked:
            await asyncio.sleep(0.02)
        await server.request("turn/interrupt", {"threadId": "t", "turnId": "x"})
        await until(server, lambda m: m["method"] == "serverRequest/resolved")
        state = (server.withdrawn(0), server.respond(0, {"decision": "accept"}), server.resolved(0))
        await server.close()
        return server, state

    server, state = run(go())

    assert asked[0]["id"] == 0 and asked[0]["method"] == "item/commandExecution/requestApproval"
    assert state == (True, False, False)
    assert server.returncode == 0
    v = verdict(log)
    assert v["breaches"] == [] and v["withdrawn"] == [0]


def test_resolved_is_true_only_for_a_request_still_pending(tmp_path):
    async def go():
        server = AppServer(["unused"])
        server._open.update({7: "item/commandExecution/requestApproval", 8: "x"})
        server._proc = None
        return (server.resolved(7), server.resolved(7), server.respond(7, {}),
                server.resolved(42), server.withdrawn(7), server.withdrawn(42))

    assert run(go()) == (True, False, False, False, True, False)


def test_a_server_request_with_no_handler_gets_an_error_not_silence(tmp_path):
    log = tmp_path / "fake.jsonl"

    async def go():
        server = AppServer(fake("command-approval", log))
        await server.open()
        await server.request("thread/start", {})
        await server.request("turn/start", {})
        await until(server, lambda m: m["method"] == "serverRequest/resolved"
                    and m["params"]["requestId"] == 2)
        await server.close()

    run(go())

    v = verdict(log)
    assert v["breaches"] == [] and v["answers"] == {"1": 1, "2": 1}
    errors = [row["msg"]["error"] for row in fake_log(log)
              if row.get("dir") == "out" and "error" in row.get("msg", {})]
    assert len(errors) == 2 and all(e["code"] == codex_rpc.METHOD_NOT_FOUND for e in errors)


# ---- the wire ---------------------------------------------------------------------------------

@posix_only
def test_frames_are_one_line_each_with_no_carriage_return(tmp_path):
    raw_path = tmp_path / "raw.bin"
    argv = script(tmp_path, f'''\
        import json, sys
        raw = open({str(raw_path)!r}, "wb")
        for line in sys.stdin.buffer:
            raw.write(line); raw.flush()
            msg = json.loads(line)
            if "id" in msg and "method" in msg:
                sys.stdout.buffer.write(json.dumps({{"id": msg["id"], "result": {{}}}}).encode() + b"\\n")
                sys.stdout.buffer.flush()
        ''')

    async def go():
        server = AppServer(argv)
        await server.open()
        await server.request("thread/start", {"developerInstructions": "line one\r\nline two\nтри"})
        await server.notify("x/y", {"a": "b\r"})
        await server.close()

    run(go())

    raw = raw_path.read_bytes()
    assert b"\r" not in raw
    lines = raw.split(b"\n")
    assert lines[-1] == b"" and len(lines) == 5  # initialize, initialized, thread/start, x/y
    assert json.loads(lines[2])["params"]["developerInstructions"] == "line one\r\nline two\nтри"


def test_a_line_over_64_kib_is_read_whole(tmp_path):
    big = "x" * (300 * 1024)
    scenario = write_scenario(tmp_path / "long.jsonl", opening() + [
        {"dir": "out", "t": 1, "msg": {"jsonrpc": "2.0", "id": 2, "method": "config/read", "params": {}}},
        {"dir": "in", "t": 1, "msg": {"id": 2, "result": {"config": {"big": big}}}},
    ])

    async def go():
        server = AppServer(fake(scenario, tmp_path / "fake.jsonl"))
        await server.open()
        result = await server.request("config/read", {})
        await server.close()
        return result

    assert run(go())["config"]["big"] == big


@posix_only
def test_a_line_that_is_not_utf8_or_json_is_skipped_not_fatal(tmp_path):
    argv = script(tmp_path, '''\
        import json, sys
        out = sys.stdout.buffer
        for line in sys.stdin.buffer:
            msg = json.loads(line)
            if "id" in msg and "method" in msg:
                out.write(b"\\xff\\xfe not utf-8\\n[1, 2]\\n{not json\\n\\n")
                out.write(json.dumps({"id": msg["id"], "result": {"ok": msg["method"]}}).encode() + b"\\n")
                out.flush()
        ''')

    async def go():
        server = AppServer(argv)
        await server.open()
        result = await server.request("config/read")
        await server.close()
        return result

    assert run(go()) == {"ok": "config/read"}


def test_an_end_in_the_middle_of_a_request_is_connection_lost_with_the_stderr_tail(tmp_path):
    rec = frames("eof-mid-turn")
    upto = next(i for i, f in enumerate(rec) if f["msg"] and f["msg"].get("method") == "thread/start")
    scenario = write_scenario(tmp_path / "eof.jsonl", rec[:upto + 1] + [rec[-1]])

    async def go():
        server = AppServer(fake(scenario, tmp_path / "fake.jsonl"))
        await server.open()
        with pytest.raises(ConnectionLost) as caught:
            await server.request("thread/start", {}, timeout=10)
        with pytest.raises(ConnectionLost):
            await server.request("thread/read", {})
        await server.close()
        return caught.value

    lost = run(go())

    assert lost.returncode == 1
    assert "Codex exited while the MCP tool call ran" in lost.stderr_tail
    assert "Codex exited" in str(lost) and "exit 1" in str(lost)


@posix_only
def test_a_silent_server_times_out_and_close_leaves_no_process(tmp_path):
    """It answers `initialize`, then nothing — and it ignores stdin's end and SIGTERM, so only the
    kill gets rid of it."""
    argv = script(tmp_path, '''\
        import json, signal, sys, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for line in sys.stdin.buffer:
            msg = json.loads(line)
            if msg.get("method") == "initialize":
                sys.stdout.buffer.write(json.dumps({"id": msg["id"], "result": {}}).encode() + b"\\n")
                sys.stdout.buffer.flush()
        time.sleep(600)
        ''')

    async def go():
        server = AppServer(argv)
        await server.open()
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await server.request("model/list", {}, timeout=0.3)
        waited = time.monotonic() - started
        await server.close(grace=0.3)
        await server.close(grace=0.3)  # idempotent
        return server, waited

    server, waited = run(go())

    assert waited < 3
    assert server.returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(server.pid, 0)


def test_notifications_arrive_in_the_recorded_order_and_none_ends_them(tmp_path):
    rec = frames("turn-mcp")
    expected = [f["msg"] for f in rec if f["dir"] == "in" and "method" in f["msg"] and "id" not in f["msg"]]

    async def go():
        server = AppServer(fake("turn-mcp", tmp_path / "fake.jsonl"))
        await server.open()
        await server.request("thread/start", {})
        await server.request("turn/start", {})
        got = []
        while (msg := await asyncio.wait_for(server.notifications.get(), 10)) is not None:
            got.append(msg)
        await server.close()
        return got

    assert run(go()) == expected


# ---- one-shot asks ---------------------------------------------------------------------------

def _codex_wrapper(tmp_path: Path, scenarios: list[Path], log: Path) -> Path:
    """A `codex` that replays `scenarios[n]` on its n-th start."""
    path = tmp_path / "codex"
    count = tmp_path / "starts"
    path.write_text(textwrap.dedent(f'''\
        #!{sys.executable}
        import os, sys
        from pathlib import Path
        count = Path({str(count)!r})
        n = int(count.read_text()) if count.exists() else 0
        count.write_text(str(n + 1))
        scenarios = {[str(s) for s in scenarios]!r}
        os.execv(sys.executable, [sys.executable, {str(FAKE)!r}, "--scenario", scenarios[min(n, len(scenarios) - 1)],
                                  "--log", {str(log)!r}, "--timeout", "5", *sys.argv[1:]])
        '''), encoding="utf-8")
    path.chmod(0o755)
    return path


def _model_page(tmp_path: Path, name: str, data: list, cursor=None) -> Path:
    result = {"data": data, **({"nextCursor": cursor} if cursor else {})}
    return write_scenario(tmp_path / f"{name}.jsonl", opening() + [
        {"dir": "out", "t": 1, "msg": {"jsonrpc": "2.0", "id": 2, "method": "model/list", "params": {}}},
        {"dir": "in", "t": 1, "msg": {"id": 2, "result": result}},
    ])


def _codex_is(monkeypatch, codex: Path) -> None:
    """The model list asks the Codex `codex_cli.find()` found (W-10 task 4)."""
    monkeypatch.setattr(mc, "cli_available", lambda harness: harness == "codex")
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: codex_cli.Found(str(codex), "path"))


@posix_only
def test_the_model_list_follows_next_cursor_in_one_app_server(tmp_path, monkeypatch):
    """Since task 4 the list is part of `codex_cli.probe`: `account/read`, then every page of
    `model/list` from the same app-server (one start, not one per page)."""
    log = tmp_path / "fake.jsonl"
    page = {"dir": "out", "t": 1, "msg": {"jsonrpc": "2.0", "id": 3, "method": "model/list"}}
    scenario = write_scenario(tmp_path / "paged.jsonl", opening() + [
        page, {"dir": "in", "t": 1, "msg": {"id": 3, "result": {"data": [
            {"id": "gpt-a", "model": "gpt-a", "displayName": "GPT-A"},
            {"id": "old", "model": "old", "hidden": True}], "nextCursor": "p2"}}},
        {**page, "msg": {**page["msg"], "id": 4}},
        {"dir": "in", "t": 1, "msg": {"id": 4, "result": {"data": [{"id": "gpt-b", "model": "gpt-b"}]}}},
    ])
    _codex_is(monkeypatch, _codex_wrapper(tmp_path, [scenario], log))

    rows = _REAL_ASK_CODEX()

    assert [(c.model, c.label) for c in rows] == [("gpt-a", "GPT-A"), ("gpt-b", "gpt-b")]
    asked = [row["msg"]["params"] for row in fake_log(log)
             if row.get("dir") == "out" and row["msg"].get("method") == "model/list"]
    assert asked == [{"limit": codex_cli.PAGE_LIMIT}, {"limit": codex_cli.PAGE_LIMIT, "cursor": "p2"}]
    argvs = [row["argv"] for row in fake_log(log) if "argv" in row]
    assert len(argvs) == 1 and argvs[0][-1] == "app-server"
    assert mc._LIST_WHY["codex"] == ""


@posix_only
def test_a_model_list_from_a_codex_that_dies_at_start_keeps_the_reason(tmp_path, monkeypatch):
    _codex_is(monkeypatch, _codex_wrapper(tmp_path, [FIX / "startup-bad-mcp.jsonl"],
                                          tmp_path / "fake.jsonl"))

    assert _REAL_ASK_CODEX() == []
    assert "invalid transport" in mc._LIST_WHY["codex"]


@posix_only
def test_ask_runs_requests_and_notifications_in_order_and_returns_errors_in_place(tmp_path):
    log = tmp_path / "fake.jsonl"
    codex = _codex_wrapper(tmp_path, [_model_page(tmp_path, "p", [{"id": "m"}])], log)

    replies = codex_rpc.ask_blocking(str(codex), [
        ("model/list", {}), Notify("x/note", {"a": 1}), ("no/such", {"b": 2})], timeout=10,
        args=("-c", "k=v"))

    assert replies[0] == {"data": [{"id": "m"}]} and replies[1] == {}
    assert isinstance(replies[2], RpcError) and replies[2].code == -32601
    out = [row["msg"] for row in fake_log(log) if row.get("dir") == "out"]
    assert [m.get("method") for m in out] == ["initialize", "initialized", "model/list", "x/note", "no/such"]
    assert [row["argv"][-3:] for row in fake_log(log) if "argv" in row] == [["app-server", "-c", "k=v"]]


@posix_only
def test_ask_on_a_server_that_never_answers_times_out(tmp_path):
    codex = tmp_path / "codex"
    codex.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(600)\n", encoding="utf-8")
    codex.chmod(0o755)

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        codex_rpc.ask_blocking(str(codex), [("model/list", {})], timeout=0.5)
    assert time.monotonic() - started < 5


# ---- the frame log ---------------------------------------------------------------------------

def test_the_frame_log_never_holds_the_mcp_token(tmp_path):
    token = "tcc-secret-\"token\"-0123456789"
    scenario = write_scenario(tmp_path / "s.jsonl", opening() + [
        {"dir": "out", "t": 1, "msg": {"jsonrpc": "2.0", "id": 2, "method": "config/read", "params": {}}},
        {"dir": "in", "t": 1, "msg": {"id": 2, "result": {"echo": "<TOKEN>"}}},
    ])
    ours = tmp_path / "frames.jsonl"

    async def go():
        server = AppServer(fake(scenario, tmp_path / "fake.jsonl", "--sub", f"<TOKEN>={token}"),
                           env={**os.environ, "TCC_MCP_TOKEN": token}, log=ours,
                           secret_env=("TCC_MCP_TOKEN",))
        await server.open()
        result = await server.request("config/read", {"headers": {"Authorization": f"Bearer {token}"}})
        await server.close()
        return result

    assert run(go()) == {"echo": token}
    text = ours.read_text(encoding="utf-8")
    assert token not in text and json.dumps(token)[1:-1] not in text
    assert text.count(codex_rpc.REDACTED) >= 2
    dirs = [json.loads(line)["dir"] for line in text.splitlines()]
    assert "in" in dirs and "out" in dirs


def test_the_frame_log_rotates_at_its_cap_and_keeps_the_late_frames(tmp_path):
    """At the cap the log moves to `.1` and writing goes on (omp's rule): the late frames are the
    ones a stuck turn needs (task 6's review, I3). A log already there counts toward the cap."""
    ours = tmp_path / "frames.jsonl"
    ours.write_text("x" * 350 + "\n", encoding="utf-8")

    async def go():
        server = AppServer(fake("signed-out", tmp_path / "fake.jsonl"), log=ours, log_cap=400)
        await server.open()
        await server.close()

    run(go())

    rotated = ours.with_name(ours.name + ".1")
    assert rotated.exists(), "the file there already plus this session's frames passed the cap"
    assert ours.stat().st_size <= 400 and rotated.stat().st_size <= 400 + 400
    last = json.loads(ours.read_text(encoding="utf-8").splitlines()[-1])
    assert last["dir"] == "note" and "ended" in json.dumps(last["msg"]), \
        "the very last frame (the end) is still written"


def test_a_rotation_that_cannot_move_the_log_empties_it_and_writing_goes_on(tmp_path):
    """M3: `.1` cannot be replaced (here a folder; on Windows a viewer holding it) — the log is
    emptied instead and the late frames are still written."""
    ours = tmp_path / "frames.jsonl"
    ours.write_text("x" * 350 + "\n", encoding="utf-8")
    (tmp_path / "frames.jsonl.1").mkdir()

    async def go():
        server = AppServer(fake("signed-out", tmp_path / "fake.jsonl"), log=ours, log_cap=400)
        await server.open()
        await server.close()

    run(go())

    text = ours.read_text(encoding="utf-8")
    assert "x" * 350 not in text and ours.stat().st_size <= 400
    last = json.loads(text.splitlines()[-1])
    assert last["dir"] == "note" and "ended" in json.dumps(last["msg"])


def test_open_cancelled_at_the_spawn_ends(tmp_path):
    """M4: a cancel through the awaiting task at the moment of the spawn ends promptly and leaves
    no process (a spawn left pending to `asyncio.run`'s cleanup is CPython's hang — see `open`)."""
    log = tmp_path / "fake.jsonl"

    async def go():
        server = AppServer(fake(write_scenario(tmp_path / "s.jsonl", [
            *opening(), {"dir": "out", "t": 0.0, "msg": {"method": "never/sent"}}]), log))
        task = asyncio.ensure_future(server.open())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(task), 10)
        await server.close()
        return server

    server = run(go())
    if server.pid is not None:
        assert server.returncode is not None


def test_the_notification_hook_sees_each_notification_before_it_is_queued(tmp_path):
    seen: list[str] = []

    async def go():
        server = AppServer(fake("mcp-elicitation", tmp_path / "fake.jsonl"),
                           on_request=lambda msg: None,
                           on_notification=lambda msg: seen.append(
                               (msg["method"], server.notifications.qsize())))
        await server.open()
        await server.close()

    run(go())
    assert seen and seen[0][0] == "remoteControl/status/changed"
    assert seen[0][1] == 0, "called before the notification is queued"


def test_a_frame_log_that_cannot_be_written_does_not_stop_anything(tmp_path):
    async def go():
        server = AppServer(fake("signed-out", tmp_path / "fake.jsonl"),
                           log=tmp_path / "no" / "such" / "dir" / "f.jsonl")
        result = await server.open()
        await server.close()
        return result

    assert run(go())["platformOs"] == "macos"
