"""`core/codex_session.py` — `CodexSession`: start, turns, the event mapping, interrupt, resume,
close (W-10 task 6, tcc#181).

Against the stand-in from task 1 (`tests/fakes/fake_codex_app_server.py`), spawned as the session's
`binary` through a `codex` wrapper, replaying the recorded scenarios in `tests/fixtures/codex/` or
short ones written here. No real Codex runs and no model turn is paid for. The stand-in asserts its
own half: every request it sends is answered exactly once (exit 3 otherwise) — read here from its
log's verdicts and the session process's exit code.

The session asks first a short probe (`account/read`, `config/read`) and then its own app-server,
so every scenario is replayed twice: the probe's requests are not in the recordings and the
stand-in answers them with an error, which the session reads as «could not tell».
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from autosound_tcc.core import codex_session, method_binding
from autosound_tcc.core.agent_events import Notice, TextDelta, ToolCall, ToolEnd, TurnEnd
from autosound_tcc.core.codex_session import (CodexSession, CodexSignedOut, CodexStartFailed,
                                              inner_command)
from autosound_tcc.core.session_registry import SessionRegistry
from autosound_tcc.core.tuning_session import system_prompt_append

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures" / "codex"
FAKE = HERE / "fakes" / "fake_codex_app_server.py"
TOKEN = "tok-SECRET-4f1c9"
URL = "http://127.0.0.1:9/mcp"
MODEL = "gpt-5.6-luna"

pytestmark = pytest.mark.skipif(os.name == "nt", reason="a POSIX script stands in for codex")


# ---- scenarios ---------------------------------------------------------------------------------


def frames(name: str) -> list[dict]:
    return [json.loads(line) for line in (FIX / f"{name}.jsonl").read_text(encoding="utf-8")
            .splitlines() if line.strip()]


def out(msg: dict) -> dict:
    return {"dir": "out", "t": 0.0, "msg": msg}


def inn(msg: dict) -> dict:
    return {"dir": "in", "t": 0.0, "msg": msg}


def opening() -> list[dict]:
    return [out({"id": 1, "method": "initialize"}), inn({"id": 1, "result": {}}),
            out({"method": "initialized"})]


def thread_start(thread: str, rid: int = 80) -> list[dict]:
    return [out({"id": rid, "method": "thread/start"}),
            inn({"id": rid, "result": {"thread": {"id": thread}}})]


def turn(thread: str, turn_id: str = "turn-1", *, middle=(), status: str = "completed",
         error: str = "", rid: int = 90) -> list[dict]:
    completed = {"id": turn_id, "status": status, "error": {"message": error} if error else None}
    return [out({"id": rid, "method": "turn/start"}),
            inn({"id": rid, "result": {"turn": {"id": turn_id, "status": "inProgress"}}}),
            *middle,
            inn({"method": "turn/completed", "params": {"threadId": thread, "turn": completed}})]


def item(event: str, thread: str, turn_id: str, body: dict) -> dict:
    return inn({"method": f"item/{event}",
                "params": {"item": body, "threadId": thread, "turnId": turn_id}})


def without_second_initialized(rows: list[dict]) -> list[dict]:
    """resume-ok / resume-error were recorded with `initialized` sent twice; the session sends it
    once, as `codex_rpc` does."""
    kept, seen = [], False
    for row in rows:
        if row["dir"] == "out" and (row.get("msg") or {}).get("method") == "initialized":
            if seen:
                continue
            seen = True
        kept.append(row)
    return kept


def write(tmp_path: Path, rows: list[dict], name: str = "scenario.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


# ---- the stand-in as `codex` ------------------------------------------------------------------


@pytest.fixture
def stand_in(tmp_path, monkeypatch):
    """`use(scenario)` → the `codex` to pass as `binary`; `log()` → the stand-in's own log rows."""
    wrapper = tmp_path / "fake-bin" / "codex"
    wrapper.parent.mkdir()
    wrapper.write_text(f"#!{sys.executable}\nimport os, sys\n"
                       f"os.execv(sys.executable, [sys.executable, {str(FAKE)!r}, *sys.argv[1:]])\n",
                       encoding="utf-8")
    wrapper.chmod(0o755)
    log = tmp_path / "fake-log.jsonl"
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("FAKE_CODEX_TIMEOUT", "5")
    monkeypatch.setenv("FAKE_CODEX_WORK", str(tmp_path / "project"))

    class StandIn:
        binary = str(wrapper)

        @staticmethod
        def use(scenario) -> str:
            monkeypatch.setenv("FAKE_CODEX_SCENARIO", str(scenario))
            return str(wrapper)

        @staticmethod
        def log() -> list[dict]:
            return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
                    if line.strip()]

        @classmethod
        def sent(cls, method: str) -> list[dict]:
            """The client's requests of `method`, as the stand-in received them."""
            return [row["msg"] for row in cls.log() if row.get("dir") == "out"
                    and row["msg"].get("method") == method]

        @classmethod
        def replies(cls) -> list[dict]:
            """The client's answers to the stand-in's own requests."""
            return [row["msg"] for row in cls.log() if row.get("dir") == "out"
                    and "method" not in row["msg"] and "id" in row["msg"]]

        @classmethod
        def breaches(cls) -> list[str]:
            return [b for row in cls.log() if "verdict" in row for b in row["verdict"]["breaches"]]

    return StandIn


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir(exist_ok=True)
    return folder


#: The thread interrupt-pending was recorded on: the scenario opens with `thread/resume`.
PENDING_THREAD = "01a13981-bb33-7f62-8e83-a45b81f276f1"


def resumable(project: Path, thread: str, phase: str = "3") -> SessionRegistry:
    registry = SessionRegistry(project / ".tcc")
    registry.sync_phase(phase)
    registry.bind_session(phase, thread, route="codex")
    return registry


def make(project: Path, binary: str, **kw) -> CodexSession:
    kw.setdefault("model", MODEL)
    return CodexSession(project_dir=project, mcp_url=URL, mcp_token=TOKEN, binary=binary, **kw)


async def drain(gen, on_event=None) -> list:
    events = []
    async for event in gen:
        events.append(event)
        if on_event is not None:
            await on_event(event)
    return events


def run(coro, seconds: float = 40.0):
    return asyncio.run(asyncio.wait_for(coro, seconds))


# ---- a turn ---------------------------------------------------------------------------------------


def test_a_streamed_turn_with_mcp_calls_maps_to_events_and_turn_end_comes_last(
        project, stand_in):
    """turn-mcp: two `tcc` tool calls, then the answer streamed. `TurnEnd` is the turn's last event
    and the generator returns right after it; the stand-in exits 0."""
    binary = stand_in.use("turn-mcp")
    SessionRegistry(project / ".tcc").sync_phase("1")
    session = make(project, binary)

    async def go():
        gen = session.start()
        events = []
        try:
            while not events or not isinstance(events[-1], TurnEnd):
                events.append(await gen.__anext__())
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
        finally:
            server = session._server
            await session.close()
        return events, server

    events, server = run(go())
    tool = "mcp__tcc__get_capability_checklist"
    thread = "01a13983-78ef-74e0-92bf-ca42ec7e6753"
    assert events == [ToolCall(tool, {}), ToolEnd(tool), ToolCall(tool, {}), ToolEnd(tool),
                      TextDelta("570"), TurnEnd(thread)]
    assert session.session_id == thread
    assert server.returncode == 0 and stand_in.breaches() == []

    started = stand_in.sent("thread/start")[0]["params"]
    assert started["sandbox"] == "danger-full-access"
    assert (started["approvalPolicy"], started["approvalsReviewer"]) == ("untrusted", "user")
    assert started["developerInstructions"] == system_prompt_append("en")
    assert started["cwd"] == str(project) and started["model"] == MODEL
    sent = stand_in.sent("turn/start")[0]["params"]
    assert sent["threadId"] == thread and sent["effort"] == "high" and sent["model"] == MODEL
    assert sent["input"][0]["text"].startswith("Start a tuning session")
    assert stand_in.sent("skills/extraRoots/set")[0]["params"] == {
        "extraRoots": [str(project / ".claude" / "skills")]}


def test_the_registry_binds_the_thread_on_the_codex_route_at_once(project, stand_in):
    binary = stand_in.use("turn-mcp")
    registry = SessionRegistry(project / ".tcc")
    registry.sync_phase("2")
    session = make(project, binary)

    async def go():
        try:
            gen = session.start()
            first = await gen.__anext__()
            # Bound before the first event of the opening turn reached the window.
            bound = registry.load()["phases"]["2"]
            await gen.aclose()
            return first, bound
        finally:
            await session.close()

    first, bound = run(go())
    assert isinstance(first, ToolCall)
    assert bound["session_id"] == session.session_id and bound["route"] == "codex"
    assert registry.resumable_session(route="codex") == session.session_id
    assert registry.resumable_session(route="sdk") is None


def test_a_message_codex_did_not_stream_arrives_whole_once(project, tmp_path, stand_in):
    thread, tid = "th-1", "turn-1"
    rows = [*opening(), *thread_start(thread), *turn(thread, tid, middle=[
        item("started", thread, tid, {"type": "agentMessage", "id": "m1", "text": ""}),
        item("completed", thread, tid, {"type": "agentMessage", "id": "m1", "text": "Whole."}),
        item("started", thread, tid, {"type": "agentMessage", "id": "m2", "text": ""}),
        inn({"method": "item/agentMessage/delta",
             "params": {"threadId": thread, "turnId": tid, "itemId": "m2", "delta": "Stre"}}),
        inn({"method": "item/agentMessage/delta",
             "params": {"threadId": thread, "turnId": tid, "itemId": "m2", "delta": "amed."}}),
        item("completed", thread, tid, {"type": "agentMessage", "id": "m2", "text": "Streamed."}),
        inn({"method": "thread/tokenUsage/updated", "params": {"threadId": thread, "turnId": tid}}),
        inn({"method": "deprecationNotice", "params": {"summary": "old"}}),
    ])]
    session = make(project, stand_in.use(write(tmp_path, rows)))

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    assert run(go()) == [TextDelta("Whole."), TextDelta("Stre"), TextDelta("amed."), TurnEnd(thread)]


def test_command_and_file_approvals_are_declined_until_the_gate_comes(project, stand_in):
    """Task 6 declines every approval (task 7 puts TCC's gate there): each is answered once, with
    `decline` — never `accept`, never `acceptForSession`. file-approval has two turns, so the bus
    contract is read here too: the brief rides each turn, and each turn gives back what it read."""

    class Bus:
        restored = 0

        def unacked_brief(self):
            return "OPEN SIGNALS: sub too loud"

        def restore_delivered(self):
            Bus.restored += 1

    session = make(project, stand_in.use("file-approval"))
    session.bus = Bus()

    async def go():
        try:
            first = await drain(session.start())
            second = await drain(session.send("Create ws.txt"))
            return first, second, session._server
        finally:
            await session.close()

    first, second, server = run(go())
    assert isinstance(first[-1], TurnEnd) and isinstance(second[-1], TurnEnd)
    assert [e.name for e in first if isinstance(e, ToolCall)] == ["Edit", "Edit", "Bash"]
    calls = [e for e in first if isinstance(e, ToolCall)]
    assert calls[0] == ToolCall("Edit", {"paths": [f"{project}/yes.txt"]}), \
        "the path from the item, kept for the approval that names only the item"
    assert ToolCall("Bash", {"command": "ls -1 yes.txt no.txt 2>&1"}) in first, "unwrapped"
    assert [r["result"] for r in stand_in.replies()] == [{"decision": "decline"}] * 4
    assert server.returncode == 0 and stand_in.breaches() == []
    assert Bus.restored == 2, "restore_delivered once per turn"
    texts = [m["params"]["input"][0]["text"] for m in stand_in.sent("turn/start")]
    assert len(texts) == 2 and all(t.startswith("OPEN SIGNALS: sub too loud\n\n") for t in texts)


def test_the_tcc_elicitation_is_accepted_and_another_servers_declined(project, tmp_path, stand_in):
    rec = frames("mcp-elicitation")
    session = make(project, stand_in.use("mcp-elicitation"))

    async def go(s):
        try:
            return await drain(s.start())
        finally:
            await s.close()

    run(go(session))
    assert stand_in.replies()[-1]["result"] == {"action": "accept", "content": {}}

    other = [json.loads(json.dumps(r)) for r in rec]
    for row in other:
        if (row.get("msg") or {}).get("method") == "mcpServer/elicitation/request":
            row["msg"]["params"]["serverName"] = "someone-else"
    second = make(project, stand_in.use(write(tmp_path, other, "other.jsonl")))
    run(go(second))
    assert stand_in.replies()[-1]["result"] == {"action": "decline"}
    assert stand_in.breaches() == []


def test_a_request_tcc_does_not_handle_is_answered_with_an_error_once(project, tmp_path, stand_in):
    thread, tid = "th-1", "turn-1"
    rows = [*opening(), *thread_start(thread), *turn(thread, tid, middle=[
        inn({"id": 7, "method": "item/tool/requestUserInput",
             "params": {"threadId": thread, "turnId": tid, "questions": []}}),
        out({"id": 7, "result": {}}),
    ])]
    session = make(project, stand_in.use(write(tmp_path, rows)))

    async def go():
        try:
            return await drain(session.start()), session._server
        finally:
            await session.close()

    events, server = run(go())
    assert events == [TurnEnd(thread)]
    (reply,) = stand_in.replies()
    assert reply["error"]["code"] == -32601 and "requestUserInput" in reply["error"]["message"]
    assert server.returncode == 0 and stand_in.breaches() == []


# ---- ends -----------------------------------------------------------------------------------------


def test_codex_dying_mid_turn_ends_the_turn_with_why_and_the_next_turn_says_so(project, stand_in):
    session = make(project, stand_in.use("eof-mid-turn"))

    async def go():
        try:
            events = await drain(session.start())
            after = await drain(session.send("still there?"))
            return events, after
        finally:
            await session.close()

    events, after = run(go())
    assert events[0] == ToolCall("mcp__tcc__get_capability_checklist", {})
    assert not any(isinstance(e, TurnEnd) for e in events)
    said = events[-1]
    assert isinstance(said, Notice) and "exit code 1" in said.text
    assert "Codex exited while the MCP tool call ran" in said.text, "the stderr tail"
    assert len(after) == 1 and isinstance(after[0], Notice) and "stopped" in after[0].text


def test_a_failed_turn_says_why_once_and_a_retry_storm_once(project, tmp_path, stand_in):
    thread, tid = "th-1", "turn-1"

    def error(message, retry):
        return inn({"method": "error", "params": {"threadId": thread, "turnId": tid,
                                                  "willRetry": retry, "error": {"message": message}}})

    rows = [*opening(), *thread_start(thread), *turn(thread, tid, status="failed", error="boom",
                                                     middle=[error("busy", True), error("busy", True),
                                                             error("boom", False)])]
    session = make(project, stand_in.use(write(tmp_path, rows)))

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    assert run(go()) == [Notice("Codex is retrying: busy"), Notice("Codex: boom"), TurnEnd(thread)]


def test_a_silent_turn_names_the_running_item(project, tmp_path, stand_in, monkeypatch):
    monkeypatch.setattr(codex_session, "SILENCE_WARN_S", 0.3)
    thread, tid = "th-1", "turn-1"
    call = {"type": "mcpToolCall", "id": "c1", "server": "tcc", "tool": "slow", "arguments": {}}
    rows = [*opening(), *thread_start(thread), *turn(thread, tid, status="interrupted", middle=[
        item("started", thread, tid, call),
        out({"id": 95, "method": "turn/interrupt"}), inn({"id": 95, "result": {}}),
    ])]
    session = make(project, stand_in.use(write(tmp_path, rows)))

    async def on(event):
        if isinstance(event, Notice):
            await session.interrupt()

    async def go():
        try:
            return await drain(session.start(), on)
        finally:
            await session.close()

    events = run(go())
    assert events[0] == ToolCall("mcp__tcc__slow", {})
    assert isinstance(events[1], Notice) and "Still inside `mcp__tcc__slow`" in events[1].text
    assert events[-1] == TurnEnd(thread)


# ---- interrupt ------------------------------------------------------------------------------------


def test_interrupt_sends_turn_interrupt_and_the_turn_ends_on_its_own_completion(project, stand_in):
    """interrupt-pending (recorded on a resumed thread): the turn waits — the stand-in waits for
    `turn/interrupt` — until interrupt() sends it; `TurnEnd` comes only after `turn/completed`
    with status `interrupted`."""
    thread = PENDING_THREAD
    resumable(project, thread)
    session = make(project, stand_in.use("interrupt-pending"), resume=True)
    order: list[str] = []

    async def on(event):
        order.append(type(event).__name__)
        if isinstance(event, ToolCall) and event.name == "Bash":
            await session.interrupt()
            order.append("interrupt")

    async def go():
        try:
            return await drain(session.start(), on), session._server
        finally:
            await session.close()

    events, server = run(go())
    assert order[-2:] == ["interrupt", "TurnEnd"] and order.count("TurnEnd") == 1
    assert events[-1] == TurnEnd(thread)
    (sent,) = stand_in.sent("turn/interrupt")
    assert sent["params"] == {"threadId": thread, "turnId": "01a13983-1325-7e93-8684-6b21528985c3"}
    assert server.returncode == 0 and stand_in.breaches() == []


def test_interrupt_with_no_turn_open_sends_nothing(project, stand_in):
    session = make(project, stand_in.use("turn-mcp"))

    async def go():
        try:
            await drain(session.start())
            await session.interrupt()
        finally:
            await session.close()

    run(go())
    assert stand_in.sent("turn/interrupt") == []


# ---- resume -------------------------------------------------------------------------------------


def test_a_resume_continues_the_phases_codex_thread_without_its_turns(project, tmp_path, stand_in):
    thread = "01a139c1-783b-75c0-afc6-38328bee7086"
    resumable(project, thread)
    rows = [*without_second_initialized(frames("resume-ok")), *turn(thread)]
    session = make(project, stand_in.use(write(tmp_path, rows)), resume=True)

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    events = run(go())
    assert events == [TurnEnd(thread)] and session.resumed
    (resumed,) = stand_in.sent("thread/resume")
    assert resumed["params"]["threadId"] == thread and resumed["params"]["excludeTurns"] is True
    assert resumed["params"]["sandbox"] == "danger-full-access"
    assert stand_in.sent("thread/start") == []
    text = stand_in.sent("turn/start")[0]["params"]["input"][0]["text"]
    assert text.startswith("Resume this tuning project"), "the resumed opener"


def test_a_resume_that_fails_says_so_and_starts_a_fresh_thread(project, tmp_path, stand_in):
    registry = resumable(project, "00000000-0000-7000-8000-000000000000")
    rows = [*without_second_initialized(frames("resume-error")), *thread_start("fresh-thread"),
            *turn("fresh-thread")]
    session = make(project, stand_in.use(write(tmp_path, rows)), resume=True)

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    events = run(go())
    assert isinstance(events[0], Notice) and "no rollout found" in events[0].text
    assert events[1:] == [TurnEnd("fresh-thread")] and not session.resumed
    assert registry.resumable_session(route="codex") == "fresh-thread"
    text = stand_in.sent("turn/start")[0]["params"]["input"][0]["text"]
    assert text.startswith("Start a tuning session"), "a fresh thread gets the fresh opener"


# ---- refusals at start --------------------------------------------------------------------------


def test_a_signed_out_codex_refuses_the_start_before_the_session_process(project, stand_in):
    session = make(project, stand_in.use("signed-out"))

    async def go():
        try:
            await drain(session.start())
        finally:
            await session.close()

    with pytest.raises(CodexSignedOut, match="not signed in"):
        run(go())
    assert session._server is None
    assert len([row for row in stand_in.log() if "argv" in row]) == 1, "the probe only"


def test_a_codex_that_dies_at_start_says_why(project, stand_in):
    session = make(project, stand_in.use("startup-bad-mcp"))

    async def go():
        try:
            await drain(session.start())
        finally:
            await session.close()

    with pytest.raises(CodexStartFailed, match="invalid transport"):
        run(go())


def test_a_second_copy_of_the_method_in_codex_refuses_the_start(project, tmp_path, stand_in):
    elsewhere = "/Users/someone/.codex/skills/autosound-tuning/SKILL.md"
    rows = [*opening(), out({"id": 2, "method": "skills/extraRoots/set"}), inn({"id": 2, "result": {}}),
            out({"id": 3, "method": "skills/list"}),
            inn({"id": 3, "result": {"data": [{"cwd": str(project), "skills": [
                {"name": "autosound-tuning", "path": elsewhere, "scope": "user"}]}]}})]
    session = make(project, stand_in.use(write(tmp_path, rows)))

    async def go():
        try:
            await drain(session.start())
        finally:
            await session.close()

    with pytest.raises(method_binding.MethodRefused, match=elsewhere):
        run(go())


def test_the_projects_own_skill_listed_is_quiet_and_none_listed_is_said(project, tmp_path, stand_in):
    def rows(skills):
        return [*opening(), out({"id": 2, "method": "skills/extraRoots/set"}),
                inn({"id": 2, "result": {}}), out({"id": 3, "method": "skills/list"}),
                inn({"id": 3, "result": {"data": [{"cwd": str(project), "skills": skills}]}}),
                *thread_start("th"), *turn("th")]

    ours = str(project / ".claude" / "skills" / "autosound-tuning" / "SKILL.md")

    async def go(s):
        try:
            return await drain(s.start())
        finally:
            await s.close()

    listed = make(project, stand_in.use(write(tmp_path, rows([
        {"name": "autosound-tuning", "path": ours, "scope": "user"}]), "ours.jsonl")))
    assert run(go(listed)) == [TurnEnd("th")]
    missing = make(project, stand_in.use(write(tmp_path, rows([]), "none.jsonl")))
    events = run(go(missing))
    assert isinstance(events[0], Notice) and "did not load the tuning method" in events[0].text


# ---- the token and the process --------------------------------------------------------------------


def test_the_token_is_in_the_environment_never_in_argv_or_the_frame_log(project, stand_in):
    session = make(project, stand_in.use("turn-mcp"))

    async def go():
        try:
            return await drain(session.start(f"and say {TOKEN}"))
        finally:
            await session.close()

    run(go())
    spawned = [row for row in stand_in.log() if "argv" in row]
    assert len(spawned) == 2, "the probe, then the session"
    probe, main = spawned
    assert all(TOKEN not in " ".join(row["argv"]) for row in spawned)
    assert main["env"]["TCC_MCP_TOKEN"] is True and probe["env"]["TCC_MCP_TOKEN"] is False
    assert f'mcp_servers.tcc.url="{URL}"' in main["argv"]
    assert 'mcp_servers.tcc.env_http_headers={"X-TCC-Token"="TCC_MCP_TOKEN"}' in main["argv"]
    assert "features.plugins=false" in main["argv"] and "project_doc_max_bytes=0" in main["argv"]
    assert main["argv"][0] == "app-server"

    frame_log = (project / ".tcc" / "codex-frames.jsonl").read_text(encoding="utf-8")
    assert TOKEN not in frame_log
    assert "and say <redacted>" in frame_log, "the turn's text went out, the token replaced"


def test_close_mid_turn_leaves_no_process_and_is_idempotent(project, stand_in):
    resumable(project, PENDING_THREAD)
    session = make(project, stand_in.use("interrupt-pending"), resume=True)

    async def go():
        gen = session.start()
        async for event in gen:
            if isinstance(event, ToolCall) and event.name == "Bash":
                break
        server = session._server
        await session.close()
        await gen.aclose()
        await session.close()
        return server

    server = run(go())
    assert server.returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(server.pid, 0)


def test_close_after_a_cancelled_turn_and_with_no_process(project, stand_in):
    run(CodexSession(project_dir=project, binary="/nonexistent/codex").close())
    resumable(project, PENDING_THREAD)
    session = make(project, stand_in.use("interrupt-pending"), resume=True)

    async def go():
        seen = asyncio.Event()

        async def consume():
            async for event in session.start():
                if isinstance(event, ToolCall):
                    seen.set()

        task = asyncio.ensure_future(consume())
        await asyncio.wait_for(seen.wait(), 20)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        server = session._server
        await session.close()
        return server

    server = run(go())
    assert server.returncode is not None


# ---- effort and the wrapper -----------------------------------------------------------------------


def test_the_effort_is_clamped_to_what_the_model_takes(project, tmp_path, stand_in):
    rows = [*opening(), out({"id": 4, "method": "model/list"}),
            inn({"id": 4, "result": {"data": [{"model": MODEL, "supportedReasoningEfforts": [
                {"reasoningEffort": "high"}, {"reasoningEffort": "xhigh"}]}], "nextCursor": None}}),
            *thread_start("th"), *turn("th")]
    session = make(project, stand_in.use(write(tmp_path, rows)), effort="max")

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    run(go())
    assert stand_in.sent("turn/start")[0]["params"]["effort"] == "xhigh"


@pytest.mark.parametrize("command, inner", [
    ("/bin/zsh -lc 'echo hi > note.txt'", "echo hi > note.txt"),
    ("bash -c 'ls -1'", "ls -1"),
    ("Remove-Item -Recurse x", "Remove-Item -Recurse x"),
    ("/bin/zsh -lc 'a' 'b'", "/bin/zsh -lc 'a' 'b'"),
    ("/bin/zsh -lc 'unclosed", "/bin/zsh -lc 'unclosed"),
])
def test_inner_command_unwraps_only_one_wrapped_argument(command, inner):
    assert inner_command(command) == inner
