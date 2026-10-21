"""`core/codex_session.py` — `CodexSession`: start, turns, the event mapping, interrupt, resume,
close (W-10 task 6, tcc#181).

Against the stand-in from task 1 (`tests/fakes/fake_codex_app_server.py`), spawned as the session's
`binary` through a `codex` wrapper, replaying the recorded scenarios in `tests/fixtures/codex/` or
short ones written here. No real Codex runs and no model turn is paid for. The stand-in asserts its
own half: every request it sends is answered exactly once (exit 3 otherwise) — read here from its
log's verdicts and the session process's exit code.

The session asks first a short probe (`account/read`, `config/read`) and then its own app-server.
The wrapper tells them apart by argv (only the session's own carries `-c`) and replays a probe
scenario to the probe — by default a signed-in Codex with an empty config — and the test's scenario
to the session. The recordings have no `skills/list` answer, so a session over one says the
method's copy is unchecked; `drain` leaves that Notice out unless a test asks for it.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from autosound_tcc.core import codex_session, method_binding
from autosound_tcc.core.agent_events import (Notice, TextDelta, Thinking, ToolCall, ToolEnd,
                                             TurnEnd, Unasked)
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


def probe_rows(config: dict | None = None, account: dict | None = None) -> list[dict]:
    """The probe's exchange: `account/read`, then `config/read`."""
    return [*opening(), out({"id": 2, "method": "account/read"}),
            inn({"id": 2, "result": account or {"account": {"type": "chatgpt"},
                                                "requiresOpenaiAuth": True}}),
            out({"id": 3, "method": "config/read"}),
            inn({"id": 3, "result": config if config is not None else {"config": {}}})]


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
    wrapper.write_text(
        f"#!{sys.executable}\nimport os, sys\nargs = sys.argv[1:]\n"
        "probe = os.environ.get('FAKE_PROBE_SCENARIO')\n"
        "scenario = os.environ['FAKE_CODEX_SCENARIO'] if '-c' in args or not probe else probe\n"
        f"os.execv(sys.executable, [sys.executable, {str(FAKE)!r}, '--scenario', scenario, *args])\n",
        encoding="utf-8")
    wrapper.chmod(0o755)
    log = tmp_path / "fake-log.jsonl"
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("FAKE_CODEX_TIMEOUT", "5")
    monkeypatch.setenv("FAKE_CODEX_WORK", str(tmp_path / "project"))
    signed_in = write(tmp_path, probe_rows(), "probe.jsonl")

    class StandIn:
        binary = str(wrapper)

        @staticmethod
        def use(scenario, probe=None) -> str:
            """`scenario` for the session's app-server, `probe` (default: signed in, an empty
            config) for the probe before it."""
            monkeypatch.setenv("FAKE_CODEX_SCENARIO", str(scenario))
            monkeypatch.setenv("FAKE_PROBE_SCENARIO", str(probe or signed_in))
            return str(wrapper)

        @staticmethod
        def log() -> list[dict]:
            """Whole lines only: a test may read while the stand-in still writes."""
            try:
                text = log.read_text(encoding="utf-8")
            except FileNotFoundError:
                return []
            return [json.loads(line) for line in text.splitlines()[:None if text.endswith("\n")
                                                                  else -1] if line.strip()]

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


#: The one Notice `drain` leaves out — exactly this one: a broader match («unchecked» anywhere)
#: would also swallow any other Notice that happened to use the word (the group review, M9).
UNCHECKED = ("Codex did not list its skills, so which copy of the tuning method it loads is "
             "unchecked: a second copy in Codex's own skills would not be noticed.")


def is_unchecked(event) -> bool:
    return isinstance(event, Notice) and event.text == UNCHECKED


async def drain(gen, on_event=None, *, unchecked: bool = False) -> list:
    """The events, without the «method copy unchecked» Notice every recording earns (above)."""
    events = []
    async for event in gen:
        if not unchecked and is_unchecked(event):
            continue
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
                event = await gen.__anext__()
                if not is_unchecked(event):
                    events.append(event)
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
        finally:
            server = session._server
            await session.close()
        return events, server

    events, server = run(go())
    tool = "mcp__tcc__get_capability_checklist"
    thread = "01a13983-78ef-74e0-92bf-ca42ec7e6753"
    # Each `reasoning` item is a `Thinking` since #223.
    assert events == [Thinking(), Thinking(), ToolCall(tool, {}), ToolEnd(tool),
                      Thinking(), ToolCall(tool, {}), ToolEnd(tool),
                      Thinking(), TextDelta("570"), TurnEnd(thread)]
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
            if is_unchecked(first):
                first = await gen.__anext__()
            # Bound before the first event of the opening turn reached the window.
            bound = registry.load()["phases"]["2"]
            await gen.aclose()
            return first, bound
        finally:
            await session.close()

    first, bound = run(go())
    assert isinstance(first, Thinking)  # the opening `reasoning` item (#223)
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


def test_two_turns_with_approvals_each_answered_once_and_the_brief_rides_each(project, stand_in):
    """file-approval, two turns, the headless bridge (it says no): under `writes` each edit asks
    and is declined, the read-only `ls` passes — each answered once, never `acceptForSession`. The
    bus contract is read here too: the brief rides each turn, each turn gives back what it read."""

    class Bus:
        restored = 0

        def unacked_brief(self):
            return "OPEN SIGNALS: sub too loud"

        def restore_delivered(self):
            Bus.restored += 1

        # The rest of `SignalBus`, which a Codex turn never asks (`test_doubles`): asked, it fails.
        def _unasked(self, *_a, **_k):
            raise AssertionError("a Codex turn asked the bus for more than its brief")

        ack = deliver = is_open = open_ids = pending_count = push = wait = _unasked

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
    assert decisions(stand_in) == ["decline", "decline", "accept", "decline"]
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
    assert [e for e in events if not isinstance(e, Thinking)][0] == ToolCall(
        "mcp__tcc__get_capability_checklist", {})
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
    with status `interrupted`.

    The approval stays pending — the bar up — when the interrupt goes, as it did in the recording.
    Without a bridge the gate declined at once, racing the interrupt: a decline written after the
    stand-in's `resolved` and before TCC read it crossed on the pipe, and the stand-in counted it
    as an answer to a withdrawn request (exit 3, CI 2026-10-14)."""
    thread = PENDING_THREAD
    resumable(project, thread)
    bridge = RecordingBridge(None)
    session = make(project, stand_in.use("interrupt-pending"), bridge=bridge, resume=True)
    order: list[str] = []

    async def on(event):
        order.append(type(event).__name__)
        if isinstance(event, ToolCall) and event.name == "Bash":
            while not bridge.requests:
                await asyncio.sleep(0.01)
            await session.interrupt()
            order.append("interrupt")

    async def go():
        try:
            return await drain(session.start(), on), session._server
        finally:
            await session.close()

    events, server = run(go())
    # The command never completed (its approval was pending): closed before the end (F2).
    assert order[-3:] == ["interrupt", "ToolEnd", "TurnEnd"] and order.count("TurnEnd") == 1
    assert events[-1] == TurnEnd(thread)
    (sent,) = stand_in.sent("turn/interrupt")
    assert sent["params"] == {"threadId": thread, "turnId": "01a13983-1325-7e93-8684-6b21528985c3"}
    assert bridge.futures[0].cancelled() and stand_in.replies() == []
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
    rows = [*frames("resume-ok"), *turn(thread)]
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
    rows = [*frames("resume-error"), *thread_start("fresh-thread"),
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
    session = make(project, stand_in.use("signed-out", probe="signed-out"))

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
    session = make(project, stand_in.use("startup-bad-mcp", probe="startup-bad-mcp"))

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


def test_agents_md_is_asked_of_the_method_before_the_start_and_a_refusal_is_said(
        project, tmp_path, stand_in, monkeypatch):
    """Skill #149 (v3.1.4): the method's `agents-setup` runs before Codex starts, off the loop
    (`agents_md.ensure`); a refusal is a Notice and the session starts all the same."""
    from autosound_tcc.core import agents_md

    ours = str(project / ".claude" / "skills" / "autosound-tuning" / "SKILL.md")
    skills = [{"name": "autosound-tuning", "path": ours, "scope": "user"}]
    rows = [*opening(), out({"id": 2, "method": "skills/extraRoots/set"}),
            inn({"id": 2, "result": {}}), out({"id": 3, "method": "skills/list"}),
            inn({"id": 3, "result": {"data": [{"cwd": str(project), "skills": skills}]}}),
            *thread_start("th"), *turn("th")]
    asked = []
    monkeypatch.setattr(agents_md, "ensure", lambda folder: asked.append(folder)
                        or "AGENTS.md was not written: why")
    session = make(project, stand_in.use(write(tmp_path, rows, "agents.jsonl")))

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    assert run(go()) == [Notice("AGENTS.md was not written: why"), TurnEnd("th")]
    assert asked == [project]


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
    assert "app-server" in main["argv"]

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


# ---- the fix round (task 6's review) ------------------------------------------------------------


def recorded_config() -> dict:
    """config-skills' `config/read` reply: three of the user's MCP servers, all named plainly."""
    return next(f["msg"]["result"] for f in frames("config-skills")
                if f["dir"] == "in" and (f["msg"].get("result") or {}).get("config"))


def test_the_users_mcp_servers_from_config_read_are_switched_off_by_name(project, tmp_path,
                                                                           stand_in):
    config = json.loads(json.dumps(recorded_config()))
    config["config"]["mcp_servers"]["my server"] = {"enabled": True}
    probe = write(tmp_path, probe_rows(config), "probe-config.jsonl")
    session = make(project, stand_in.use("turn-mcp", probe=probe))

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    events = run(go())
    said = events[0]
    assert isinstance(said, Notice) and "my server" in said.text, "a name -c cannot carry"
    main = [row for row in stand_in.log() if "argv" in row][-1]["argv"]
    off = sorted(a for a in main if a.startswith("mcp_servers.") and a.endswith(".enabled=false"))
    assert off == ["mcp_servers.computer-use.enabled=false",
                   "mcp_servers.home-assistant.enabled=false",
                   "mcp_servers.node_repl.enabled=false"]
    assert isinstance(events[-1], TurnEnd)


def test_a_refused_config_read_and_a_refused_skills_list_are_said(project, tmp_path, stand_in):
    probe = write(tmp_path, [*opening(), out({"id": 2, "method": "account/read"}),
                             inn({"id": 2, "result": {"account": {"type": "chatgpt"}}})],
                  "probe-noconfig.jsonl")
    session = make(project, stand_in.use("turn-mcp", probe=probe))

    async def go():
        try:
            return await drain(session.start(), unchecked=True)
        finally:
            await session.close()

    notices = [e.text for e in run(go()) if isinstance(e, Notice)]
    assert any("MCP servers" in text and "stay on" in text for text in notices), notices
    assert UNCHECKED in notices, notices


def test_a_refused_turn_start_ends_the_turn_with_why(project, tmp_path, stand_in):
    rows = [*opening(), *thread_start("th"), out({"id": 90, "method": "turn/start"}),
            inn({"id": 90, "error": {"code": -32600, "message": "thread is busy"}})]
    session = make(project, stand_in.use(write(tmp_path, rows)))

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    assert run(go()) == [Notice("Codex refused the message: thread is busy"), TurnEnd("th")]


def test_a_turn_start_with_no_reply_and_no_turn_ends_instead_of_hanging(
        project, tmp_path, stand_in, monkeypatch):
    """Review I1: no reply to `turn/start` and no `turn/started` — the turn ends, said, so the
    window's `turn_done` comes; it does not wait for a `turn/completed` nothing will send."""
    monkeypatch.setattr(codex_session, "REQUEST_TIMEOUT_S", 1.0)
    monkeypatch.setenv("FAKE_CODEX_TIMEOUT", "15")
    rows = [*opening(), *thread_start("th"), out({"id": 90, "method": "turn/start"}),
            out({"method": "never/sent"})]
    session = make(project, stand_in.use(write(tmp_path, rows)))

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    events = run(go(), 20)
    assert len(events) == 2 and isinstance(events[0], Notice) and "did not start" in events[0].text
    assert events[1] == TurnEnd("th")


def test_a_start_cancelled_during_the_probe_winds_down(project, tmp_path, stand_in):
    """The worker cancels a start on shutdown; mid-probe that must end, not hang the loop."""
    probe = write(tmp_path, [*opening(), out({"id": 2, "method": "account/read"}),
                             out({"method": "never/sent"})], "probe-slow.jsonl")
    session = make(project, stand_in.use("turn-mcp", probe=probe))

    async def go():
        task = asyncio.ensure_future(drain(session.start()))
        await until_sent(stand_in, "account/read")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await session.close()

    run(go(), 15)


async def until_sent(stand_in, method: str, seconds: float = 10.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while not stand_in.sent(method):
        assert loop.time() < deadline, f"{method} never sent"
        await asyncio.sleep(0.02)


def test_stop_while_turn_start_is_in_flight_interrupts_once_the_turn_is_known(
        project, tmp_path, stand_in, monkeypatch):
    """Review I2: Stop before the turn id is not dropped — `turn/interrupt` goes as soon as the
    reply names the turn, and the turn ends through its own `turn/completed`."""
    monkeypatch.setenv("FAKE_CODEX_PACE", "1")
    rows = [*opening(), *thread_start("th"), out({"id": 90, "method": "turn/start"}),
            {**inn({"id": 90, "result": {"turn": {"id": "t1", "status": "inProgress"}}}), "t": 1.0},
            {**out({"id": 95, "method": "turn/interrupt"}), "t": 1.0},
            {**inn({"id": 95, "result": {}}), "t": 1.0},
            {**inn({"method": "turn/completed", "params": {"threadId": "th", "turn": {
                "id": "t1", "status": "interrupted", "error": None}}}), "t": 1.0}]
    session = make(project, stand_in.use(write(tmp_path, rows)))

    async def go():
        try:
            task = asyncio.ensure_future(drain(session.start()))
            await until_sent(stand_in, "turn/start")
            await session.interrupt()
            return await task
        finally:
            await session.close()

    assert run(go()) == [TurnEnd("th")]
    (sent,) = stand_in.sent("turn/interrupt")
    assert sent["params"] == {"threadId": "th", "turnId": "t1"}
    assert stand_in.breaches() == []


def test_stop_during_the_opening_skips_the_opening_turn(project, tmp_path, stand_in, monkeypatch):
    """Review I2, the choice: Stop while Codex is still starting sends no opening message — the
    opening ends at once, said; nothing ran. The next message goes as usual."""
    monkeypatch.setenv("FAKE_CODEX_PACE", "1")
    rows = [*opening(), out({"id": 80, "method": "thread/start"}),
            {**inn({"id": 80, "result": {"thread": {"id": "th"}}}), "t": 1.0},
            *[{**row, "t": 1.0} for row in turn("th")]]
    session = make(project, stand_in.use(write(tmp_path, rows)))

    async def go():
        try:
            task = asyncio.ensure_future(drain(session.start()))
            await until_sent(stand_in, "thread/start")
            await session.interrupt()
            opening_events = await task
            assert stand_in.sent("turn/start") == [], "no opening message went out"
            return opening_events, await drain(session.send("go on"))
        finally:
            await session.close()

    opening_events, after = run(go())
    assert len(opening_events) == 2 and isinstance(opening_events[0], Notice)
    assert "Stopped" in opening_events[0].text and opening_events[1] == TurnEnd("th")
    assert after == [TurnEnd("th")], "the flag went with the opening"
    assert stand_in.sent("turn/interrupt") == []


def test_a_stop_between_turns_does_not_cancel_the_next_message(project, stand_in):
    session = make(project, stand_in.use("file-approval"))

    async def go():
        try:
            await drain(session.start())
            await session.interrupt()
            return await drain(session.send("Create ws.txt"))
        finally:
            await session.close()

    assert isinstance(run(go())[-1], TurnEnd)
    assert len(stand_in.sent("turn/start")) == 2 and stand_in.sent("turn/interrupt") == []


def test_the_thread_is_bound_again_when_the_phase_moved_during_the_turn(project, stand_in):
    registry = SessionRegistry(project / ".tcc")
    registry.sync_phase("1")
    session = make(project, stand_in.use("turn-mcp"))

    async def on(event):
        if isinstance(event, ToolEnd) and registry.current_phase() == "1":
            registry.sync_phase("2")

    async def go():
        try:
            return await drain(session.start(), on)
        finally:
            await session.close()

    run(go())
    entry = registry.load()["phases"]["2"]
    assert entry["session_id"] == session.session_id and entry["route"] == "codex"


def test_the_sessions_frame_log_rotates_and_keeps_the_end(project, stand_in, monkeypatch):
    monkeypatch.setattr(codex_session, "FRAME_LOG_MAX_BYTES", 3000)
    log = project / ".tcc" / "codex-frames.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("old\n" * 700, encoding="utf-8")
    session = make(project, stand_in.use("turn-mcp"))

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    run(go())
    assert log.with_name(log.name + ".1").exists()
    last = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert last["dir"] == "note" and "ended" in json.dumps(last["msg"])


def test_a_probe_that_times_out_refuses_the_start(project, tmp_path, stand_in, monkeypatch):
    monkeypatch.setattr(codex_session.codex_cli, "PROBE_TIMEOUT_S", 1.0)
    probe = write(tmp_path, [*opening(), out({"id": 2, "method": "account/read"}),
                             out({"method": "never/sent"})], "probe-slow.jsonl")
    session = make(project, stand_in.use("turn-mcp", probe=probe))

    async def go():
        try:
            await drain(session.start())
        finally:
            await session.close()

    with pytest.raises(CodexStartFailed, match="no answer"):
        run(go())
    assert session._server is None


def test_a_lost_connection_at_start_is_said_without_the_token(project, tmp_path, stand_in):
    """Review M5: the stderr tail goes into the start's refusal — never the token in it."""
    dies = [*opening(), {"dir": "eof", "t": 0.0, "exit": 1,
                         "stderr": f"trace: X-TCC-Token: {TOKEN}\nError: lost"}]
    probe = write(tmp_path, dies, "probe-dies.jsonl")

    async def start(s):
        try:
            await drain(s.start())
        finally:
            await s.close()

    with pytest.raises(CodexStartFailed) as probe_failed:
        run(start(make(project, stand_in.use("turn-mcp", probe=probe))))
    assert TOKEN not in str(probe_failed.value) and "lost" in str(probe_failed.value)

    mid_start = write(tmp_path, [*opening(), out({"id": 2, "method": "skills/extraRoots/set"}),
                                 dies[-1]], "main-dies.jsonl")
    with pytest.raises(CodexStartFailed) as main_failed:
        run(start(make(project, stand_in.use(mid_start))))
    assert TOKEN not in str(main_failed.value) and "lost" in str(main_failed.value)


# ---- task 7: approvals through TCC's gate ---------------------------------------------------------

from concurrent.futures import Future  # noqa: E402
import time  # noqa: E402

from autosound_tcc.core import shell_gate  # noqa: E402


class RecordingBridge:
    """A stand-in Arbiter: answers `allow` at once, or (allow=None) never — the bar stays up."""

    def __init__(self, allow=True) -> None:
        self.allow = allow
        self.requests: list = []
        self.futures: list[Future] = []

    def snapshot(self) -> dict:
        return {}

    def request_confirmation(self, request) -> Future:
        self.requests.append(request)
        future: Future = Future()
        if self.allow is not None:
            future.set_result(self.allow)
        self.futures.append(future)
        return future


def decisions(stand_in) -> list:
    return [r.get("result", {}).get("decision") for r in stand_in.replies()]


def approval_turn(thread: str, *, command="", changes=None, after=(), cwd=None,
                  kind: str = "command", item_id: str | None = "i1") -> list[dict]:
    """One turn whose single item asks first: a command, or a file change with `changes`."""
    tid = "turn-1"
    if changes is None:
        body = {"type": "commandExecution", "id": "i1", "command": command}
        ask = {"id": 0, "method": "item/commandExecution/requestApproval", "params": {
            "threadId": thread, "turnId": tid, "itemId": "i1", "command": command, "kind": kind}}
        if cwd is not None:
            ask["params"]["cwd"] = str(cwd)
    else:
        body = {"type": "fileChange", "id": "i1", "changes": changes}
        ask = {"id": 0, "method": "item/fileChange/requestApproval", "params": {
            "threadId": thread, "turnId": tid, "itemId": item_id, "reason": None}}
        if item_id is None:
            del ask["params"]["itemId"]
    return [*opening(), *thread_start(thread), *turn(thread, tid, middle=[
        item("started", thread, tid, body), inn(ask), *after, out({"id": 0, "result": {}}),
        item("completed", thread, tid, body)])]


def run_session(session) -> list:
    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()
    return run(go())


@pytest.mark.parametrize("allow, said", [(True, "accept"), (False, "decline")])
def test_the_arbiters_answer_reaches_codex_once(project, stand_in, allow, said):
    bridge = RecordingBridge(allow)
    session = make(project, stand_in.use("command-approval"), bridge=bridge)
    events = run_session(session)
    assert isinstance(events[-1], TurnEnd)
    assert [r.detail for r in bridge.requests] == ["echo hi > note.txt", "touch denied.txt"]
    assert decisions(stand_in) == [said, said] and stand_in.breaches() == []


def test_a_bar_that_could_not_be_shown_is_declined_and_said(project, stand_in):
    """G1-silent M2 (#206): Codex's `decline` carries no words, so the turn says the confirmation
    could not be shown — not the Arbiter's answer."""
    bridge = RecordingBridge(True)

    def broken(request):
        raise RuntimeError("the bridge is gone")

    bridge.request_confirmation = broken
    session = make(project, stand_in.use("command-approval"), bridge=bridge)
    events = run_session(session)
    said = [e.text for e in events if isinstance(e, Notice)]
    assert decisions(stand_in) == ["decline", "decline"] and stand_in.breaches() == []
    assert said and all("could not be shown" in t and "the bridge is gone" in t for t in said), said


def test_never_lets_a_dangerous_command_through_and_says_so(project, tmp_path, stand_in):
    bridge = RecordingBridge(False)
    rows = approval_turn("th", command="/bin/zsh -lc 'rm -rf ~'")
    session = make(project, stand_in.use(write(tmp_path, rows)), bridge=bridge, gate="never")
    events = run_session(session)
    assert Unasked("rm -rf ~") in events and bridge.requests == []
    assert decisions(stand_in) == ["accept"] and stand_in.breaches() == []


def test_an_always_allowed_tick_passes_without_the_bar(project, stand_in):
    bridge = RecordingBridge(False)
    session = make(project, stand_in.use("command-approval"), bridge=bridge, gate="writes",
                   always_allowed=frozenset({"Bash"}))
    run_session(session)
    assert bridge.requests == [] and decisions(stand_in) == ["accept", "accept"]


def test_a_gate_narrowed_mid_session_holds_from_the_next_request(project, stand_in):
    bridge = RecordingBridge(False)
    session = make(project, stand_in.use("file-approval"), bridge=bridge, gate="auto")

    async def go():
        try:
            await drain(session.start())
            first = list(bridge.requests)
            session.gate = "writes"
            await drain(session.send("Create ws.txt"))
            return first
        finally:
            await session.close()

    first = run(go())
    assert first == [], "under auto two new files and an `ls` pass"
    assert [r.tool for r in bridge.requests] == ["Edit"]
    assert f"{project}/ws.txt" in bridge.requests[0].detail
    assert decisions(stand_in) == ["accept", "accept", "accept", "decline"]
    assert stand_in.breaches() == []


@pytest.mark.parametrize("resolved_first", [False, True])
def test_stop_while_the_bar_waits_takes_the_bar_down_and_sends_nothing(
        project, tmp_path, stand_in, resolved_first):
    """interrupt-pending: the approval waits on the bar; Stop → `turn/interrupt` → Codex withdraws
    the request. The bar's future is cancelled (`ConfirmBar._on_gave_up`), no answer goes out, the
    turn ends — whether `turn/completed` or `serverRequest/resolved` comes first."""
    rows = frames("interrupt-pending")
    if resolved_first:
        resolved = next(r for r in rows if (r.get("msg") or {}).get("method")
                        == "serverRequest/resolved")
        rows.remove(resolved)
        at = next(i for i, r in enumerate(rows) if (r.get("msg") or {}).get("method")
                  == "turn/completed")
        rows.insert(at, resolved)
    resumable(project, PENDING_THREAD)
    bridge = RecordingBridge(None)
    session = make(project, stand_in.use(write(tmp_path, rows)), bridge=bridge, resume=True)

    async def on(event):
        if isinstance(event, ToolCall) and event.name == "Bash":
            while not bridge.requests:
                await asyncio.sleep(0.01)
            await session.interrupt()

    async def go():
        try:
            return await drain(session.start(), on), session._server
        finally:
            await session.close()

    events, server = run(go())
    assert events[-1] == TurnEnd(PENDING_THREAD)
    assert len(bridge.futures) == 1 and bridge.futures[0].cancelled(), "the bar came down"
    assert stand_in.replies() == [] and stand_in.breaches() == []
    assert server.returncode == 0


#: The Arbiter, 2026-10-15: one file of the project deleted does not ask under `auto` — «це ж
#: робота скіла; якщо це за текою чи рекурсивне — тоді може» (until then every delete asked, the
#: call of 2026-10-14 after task 5's review, I1). One outside the project still asks.
@pytest.mark.parametrize("kind, where, asks", [
    ("delete", "outside", True), ("delete", "inside", False), ("delete", "the method", False),
    ("add", "inside", False), ("update", "inside", False)])
def test_under_auto_a_file_delete_outside_asks_and_one_inside_passes(project, tmp_path, stand_in,
                                                                     kind, where, asks):
    bridge = RecordingBridge(False)
    path = {"outside": str(tmp_path / "elsewhere" / "ledger.json"),
            "inside": str(project / "process" / "ledger.json"),
            "the method": str(Path(method_dir(project)) / "SKILL.md")}[where]
    rows = approval_turn("th", changes=[{"path": path, "kind": {"type": kind}, "diff": ""}])
    session = make(project, stand_in.use(write(tmp_path, rows)), bridge=bridge, gate="auto")
    run_session(session)
    if asks:
        (request,) = bridge.requests
        assert request.reason == "gateIrreversible" and path in request.detail
        assert decisions(stand_in) == ["decline"]
    else:
        assert bridge.requests == [] and decisions(stand_in) == ["accept"]
    assert stand_in.breaches() == []


@pytest.mark.parametrize("where, said", [("outside", True), ("inside", False)])
def test_a_file_delete_under_never_passes_and_says_what_auto_would_ask(project, tmp_path, stand_in,
                                                                        where, said):
    path = str(tmp_path / "x.txt" if where == "outside" else project / "x.txt")
    rows = approval_turn("th", changes=[{"path": path, "kind": {"type": "delete"}, "diff": ""}])
    session = make(project, stand_in.use(write(tmp_path, rows)), bridge=RecordingBridge(False),
                   gate="never")
    events = run_session(session)
    assert any(isinstance(e, Unasked) and path in e.command for e in events) is said
    assert decisions(stand_in) == ["accept"]


@pytest.mark.parametrize("gate", ["writes", "foreign"])
def test_where_writes_ask_a_file_delete_inside_asks_as_before(project, tmp_path, stand_in, gate):
    path = str(project / "x.txt")
    rows = approval_turn("th", changes=[{"path": path, "kind": {"type": "delete"}, "diff": ""}])
    bridge, _ = run_gate(project, tmp_path, stand_in, rows, gate=gate)
    (request,) = bridge.requests
    assert request.reason == "gateIrreversible" and decisions(stand_in) == ["decline"]


def test_a_file_change_deleting_a_folder_of_the_project_asks_under_auto(project, tmp_path,
                                                                         stand_in):
    (project / "process").mkdir(exist_ok=True)
    rows = approval_turn("th", changes=[{"path": str(project / "process"),
                                         "kind": {"type": "delete"}, "diff": ""}])
    bridge, _ = run_gate(project, tmp_path, stand_in, rows, gate="auto")
    (request,) = bridge.requests
    assert request.reason == "gateIrreversible"


@pytest.mark.parametrize("command, shell, detail", [
    ('"C:\\WINDOWS\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -Command "Remove-Item x"',
     "powershell", None),
    ("pwsh.exe -NoProfile -Command Get-ChildItem", "powershell", None),
    ("/bin/zsh -lc 'echo hi > note.txt'", "bash", "echo hi > note.txt"),
])
def test_a_powershell_line_is_judged_as_powershell_and_whole(project, tmp_path, stand_in,
                                                               monkeypatch, command, shell, detail):
    seen: list = []
    real = codex_session.judge_action

    def recorder(tool, line, **kw):
        seen.append((tool, line, kw))
        return real(tool, line, **kw)

    monkeypatch.setattr(codex_session, "judge_action", recorder)
    session = make(project, stand_in.use(write(tmp_path, approval_turn("th", command=command))),
                   bridge=RecordingBridge(True))
    run_session(session)
    ((tool, line, kw),) = seen
    assert tool == "Bash" and kw["shell"] == shell and line == (detail or command)
    assert "command" not in kw and kw["gate"] == session.gate
    assert kw["read_roots"] == session._read_roots and kw["read_roots"]


def test_the_gate_runs_off_the_loop(project, tmp_path, stand_in, monkeypatch):
    """`judge_action` touches the disk; a slow one must not hold the notifications."""
    stamps: dict = {}

    def slow(tool, line, **kw):
        stamps["judge_start"] = time.monotonic()
        time.sleep(1.0)
        stamps["judge_end"] = time.monotonic()
        return shell_gate.Verdict(True)

    monkeypatch.setattr(codex_session, "judge_action", slow)
    delta = inn({"method": "item/agentMessage/delta",
                 "params": {"threadId": "th", "turnId": "turn-1", "itemId": "m", "delta": "meanwhile"}})
    rows = approval_turn("th", command="/bin/zsh -lc 'touch a'", after=[delta])
    session = make(project, stand_in.use(write(tmp_path, rows)))

    async def on(event):
        if isinstance(event, TextDelta):
            stamps["delta"] = time.monotonic()

    async def go():
        try:
            return await drain(session.start(), on)
        finally:
            await session.close()

    run(go())
    assert stamps["delta"] < stamps["judge_end"], "the delta arrived while the gate was thinking"
    assert decisions(stand_in) == ["accept"]


# ---- the re-review's Minors ---------------------------------------------------------------------


def test_a_turn_started_arriving_with_the_timeout_is_not_dropped(project):
    """M1: the notifications are read before the reply, so a `turn/started` that arrives together
    with `turn/start`'s timeout names the turn, and the turn goes on to its own completion."""
    session = CodexSession(project_dir=project)
    session.session_id = "th"

    class Server:
        notifications: asyncio.Queue

    async def go():
        server = Server()
        server.notifications = asyncio.Queue()
        server.notifications.put_nowait({"method": "turn/started",
                                         "params": {"threadId": "th", "turn": {"id": "t1"}}})
        server.notifications.put_nowait({"method": "turn/completed", "params": {
            "threadId": "th", "turn": {"id": "t1", "status": "completed"}}})
        reply = asyncio.get_running_loop().create_future()
        reply.set_exception(TimeoutError("turn/start: no answer"))
        return [e async for e in session._read_turn(server, reply)]

    assert run(go()) == [TurnEnd("th")]


def test_a_reply_that_names_no_turn_is_treated_as_no_turn(project, tmp_path, stand_in):
    """M2: a `turn/start` reply without `turn.id`, and no `turn/started` — the turn ends, said."""
    rows = [*opening(), *thread_start("th"), out({"id": 90, "method": "turn/start"}),
            inn({"id": 90, "result": {}}), out({"method": "never/sent"})]
    events = run_session(make(project, stand_in.use(write(tmp_path, rows))))
    assert len(events) == 2 and isinstance(events[0], Notice) and events[1] == TurnEnd("th")


# ---- task 7's fix round (the review: cwd, kind, a failing gate) -----------------------------------


def run_gate(project, tmp_path, stand_in, rows, **kw):
    bridge = RecordingBridge(False)
    session = make(project, stand_in.use(write(tmp_path, rows)), bridge=bridge, **kw)
    events = run_session(session)
    return bridge, events


@pytest.fixture
def places(tmp_path, project):
    """Folders a command can run in: the home, `/`, a sibling project, one inside the project."""
    sibling = tmp_path / "other-project"
    sibling.mkdir()
    (sibling / "keep.txt").write_text("x", encoding="utf-8")
    inside = project / "process"
    inside.mkdir(exist_ok=True)
    return {"home": Path.home(), "root": Path("/"), "sibling": sibling, "inside": inside}


@pytest.mark.parametrize("where", ["home", "root", "sibling"])
@pytest.mark.parametrize("gate, line", [("auto", "rm -rf *"), ("writes", "cat .ssh/id_rsa"),
                                        ("auto", "ls")])
def test_a_command_in_a_folder_outside_the_project_asks(project, tmp_path, stand_in, places,
                                                         where, gate, line):
    """Critical: Codex's `cwd` is the folder the line runs in. Outside the project it always asks
    (the stricter of the two ways) — and the bar shows where."""
    cwd = places[where]
    bridge, _ = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command=f"/bin/zsh -lc '{line}'", cwd=cwd), gate=gate)
    (request,) = bridge.requests
    assert str(cwd) in request.detail and line in request.detail
    assert decisions(stand_in) == ["decline"] and stand_in.breaches() == []


def test_outside_the_project_under_never_passes_and_says_where(project, tmp_path, stand_in, places):
    bridge, events = run_gate(project, tmp_path, stand_in,
                              approval_turn("th", command="/bin/zsh -lc 'rm -rf *'",
                                            cwd=places["home"]), gate="never")
    said = [e.command for e in events if isinstance(e, Unasked)]
    assert len(said) == 1 and str(places["home"]) in said[0] and bridge.requests == []
    assert decisions(stand_in) == ["accept"]


@pytest.mark.parametrize("where", ["project", "inside"])
def test_a_command_in_the_project_is_judged_as_before(project, tmp_path, stand_in, places, where):
    cwd = project if where == "project" else places["inside"]
    bridge, _ = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command="/bin/zsh -lc 'ls'", cwd=cwd), gate="auto")
    assert bridge.requests == [] and decisions(stand_in) == ["accept"]


def test_a_request_the_turn_left_behind_unwithdrawn_is_declined(project, tmp_path, stand_in):
    """Re-review M2: the turn ended and Codex never withdrew the request still on the bar — after
    `SWEEP_DECLINE_S` TCC declines it, once (the stand-in waits for that answer)."""
    rows = [r for r in frames("interrupt-pending")
            if (r.get("msg") or {}).get("method") != "serverRequest/resolved"]
    rows.append(out({"id": 0, "result": {}}))
    resumable(project, PENDING_THREAD)
    bridge = RecordingBridge(None)
    session = make(project, stand_in.use(write(tmp_path, rows)), bridge=bridge, resume=True)

    async def on(event):
        if isinstance(event, ToolCall) and event.name == "Bash":
            while not bridge.requests:
                await asyncio.sleep(0.01)
            await session.interrupt()

    async def go():
        try:
            events = await drain(session.start(), on)
            await asyncio.sleep(codex_session.SWEEP_DECLINE_S + 0.5)
            return events
        finally:
            await session.close()

    events = run(go())
    assert events[-1] == TurnEnd(PENDING_THREAD) and bridge.futures[0].cancelled()
    assert decisions(stand_in) == ["decline"] and stand_in.breaches() == []


def test_a_delete_in_a_project_subfolder_is_judged_from_there(project, tmp_path, stand_in,
                                                               places, monkeypatch):
    seen: list = []
    real = codex_session.judge_action
    monkeypatch.setattr(codex_session, "judge_action",
                        lambda tool, line, **kw: seen.append(line) or real(tool, line, **kw))
    run_gate(project, tmp_path, stand_in,
             approval_turn("th", command="/bin/zsh -lc 'rm -rf *'", cwd=places["inside"]),
             gate="auto")
    assert seen == ["cd process && rm -rf *"], "relative to the project, as the gate reads paths"


@pytest.mark.parametrize("line", ["rm -rf ../..", "rm -rf ../../.."])
def test_a_climb_out_of_a_project_subfolder_asks(project, tmp_path, stand_in, places, line):
    """N2: from `P/process`, `../..` is the folder above the project."""
    bridge, _ = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command=f"/bin/zsh -lc '{line}'",
                                       cwd=places["inside"]), gate="auto")
    assert len(bridge.requests) == 1 and decisions(stand_in) == ["decline"]


@pytest.mark.parametrize("cwd_of, line", [("home", "rm -rf *"), ("project", "rm -rf ~")])
def test_a_bash_tick_never_outranks_cannot_be_undone_on_codex(project, tmp_path, stand_in,
                                                               places, cwd_of, line):
    """The Arbiter, 2026-10-14: the tick removes the question for an ordinary command only."""
    cwd = places["home"] if cwd_of == "home" else project
    bridge, _ = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command=f"/bin/zsh -lc '{line}'", cwd=cwd),
                         gate="auto", always_allowed=frozenset({"Bash"}))
    assert len(bridge.requests) == 1 and decisions(stand_in) == ["decline"]


def test_a_bash_tick_still_passes_an_ordinary_command_on_codex(project, tmp_path, stand_in):
    bridge, _ = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command="/bin/zsh -lc 'touch a'", cwd=project),
                         gate="writes", always_allowed=frozenset({"Bash"}))
    assert bridge.requests == [] and decisions(stand_in) == ["accept"]


@pytest.mark.parametrize("kind, command", [("writeStdin", "/bin/zsh -lc 'ls'"), ("command", "")])
def test_a_bash_tick_does_not_pass_what_the_gate_cannot_read(project, tmp_path, stand_in,
                                                             kind, command):
    bridge, _ = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command=command, kind=kind),
                         gate="auto", always_allowed=frozenset({"Bash"}))
    assert len(bridge.requests) == 1


@pytest.mark.parametrize("kind, command", [("writeStdin", "/bin/zsh -lc 'ls'"),
                                           ("command", ""), ("command", None)])
def test_input_to_a_running_command_or_no_command_asks(project, tmp_path, stand_in, kind, command):
    bridge, _ = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command=command, kind=kind), gate="auto")
    assert len(bridge.requests) == 1 and decisions(stand_in) == ["decline"]


def test_input_to_a_running_command_under_never_passes_and_says_so(project, tmp_path, stand_in):
    _, events = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command="", kind="writeStdin"), gate="never")
    assert any(isinstance(e, Unasked) for e in events) and decisions(stand_in) == ["accept"]


def test_a_gate_that_fails_declines(project, tmp_path, stand_in, monkeypatch):
    def broken(tool, line, **kw):
        raise OSError("the disk walk failed")

    monkeypatch.setattr(codex_session, "judge_action", broken)
    bridge, events = run_gate(project, tmp_path, stand_in,
                              approval_turn("th", command="/bin/zsh -lc 'touch a'"))
    assert decisions(stand_in) == ["decline"], "a decline, not a JSON-RPC error"
    assert all("error" not in r for r in stand_in.replies()) and isinstance(events[-1], TurnEnd)


def test_a_file_change_naming_no_item_asks_as_a_delete(project, tmp_path, stand_in):
    rows = approval_turn("th", changes=[{"path": str(project / "a"), "kind": {"type": "add"}}],
                         item_id=None)
    bridge, _ = run_gate(project, tmp_path, stand_in, rows, gate="auto")
    (request,) = bridge.requests
    assert request.reason == "gateIrreversible" and decisions(stand_in) == ["decline"]


def test_unasked_comes_strictly_before_turn_end(project, tmp_path, stand_in):
    _, events = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command="/bin/zsh -lc 'rm -rf ~'"), gate="never")
    kinds = [type(e).__name__ for e in events]
    assert kinds.count("Unasked") == 1 and kinds.index("Unasked") < kinds.index("TurnEnd")
    assert kinds[-1] == "TurnEnd"


@pytest.mark.parametrize("command, windows, shell", [
    ("cmd /c del x", False, "bash"),
    ("cmd /c del x", True, "powershell"),  # not bash; PowerShell's reader is never read-only
    ('"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -Command Remove-Item x', False, "powershell"),
    ("env FOO=1 bash -c 'rm x'", False, "bash"),
    ("env FOO=1 bash -c 'rm x'", True, "powershell"),
    ("/bin/zsh -lc 'pwsh -c Remove-Item x'", False, "bash"),
])
def test_shell_of_corner_cases(command, windows, shell):
    assert codex_session.shell_of(command, windows=windows) == shell


def test_powershell_behind_codexs_wrapper_is_judged_as_powershell(project, tmp_path, stand_in,
                                                                   monkeypatch):
    seen: list = []
    real = codex_session.judge_action
    monkeypatch.setattr(codex_session, "judge_action",
                        lambda tool, line, **kw: seen.append((line, kw["shell"]))
                        or real(tool, line, **kw))
    run_gate(project, tmp_path, stand_in,
             approval_turn("th", command="/bin/zsh -lc 'pwsh -c Remove-Item x'"))
    assert seen == [("pwsh -c Remove-Item x", "powershell")]


#: What a Windows Codex 0.162.1 sent for a delete (the Arbiter's VM, W-10): its argv joined the
#: POSIX way — a double-quoted stretch doubles a backslash, an apostrophe closes and reopens.
WINDOWS_DELETE = (
    '"C:\\\\WINDOWS\\\\System32\\\\WindowsPowerShell\\\\v1.0\\\\powershell.exe" -Command '
    "'$resolvedTarget = (Resolve-Path -LiteralPath '\"'test-tcc.txt').Path; if (\""
    "'$resolvedTarget -ne '\"'C:\\\\Users\\\\o.yukhno\\\\dev\\\\testAgy-auto\\\\test-tcc.txt') "
    "{ throw \\\"Unexpected target: \"'$resolvedTarget\" }; "
    "Remove-Item -LiteralPath $resolvedTarget -Force'")
#: …and the line PowerShell runs: what the bar shows.
WINDOWS_DELETE_RUNS = (
    "$resolvedTarget = (Resolve-Path -LiteralPath 'test-tcc.txt').Path; if ($resolvedTarget -ne "
    "'C:\\Users\\o.yukhno\\dev\\testAgy-auto\\test-tcc.txt') { throw \"Unexpected target: "
    "$resolvedTarget\" }; Remove-Item -LiteralPath $resolvedTarget -Force")


@pytest.mark.parametrize("command, shown", [
    (WINDOWS_DELETE, WINDOWS_DELETE_RUNS),
    ('pwsh.exe -NoProfile -Command "Remove-Item x"', "Remove-Item x"),
    ("powershell -c Remove-Item x", "Remove-Item x"),
    # Not one `-Command` text TCC can take apart: shown whole, nothing hidden.
    ("powershell -ExecutionPolicy Bypass -Command Remove-Item x",
     "powershell -ExecutionPolicy Bypass -Command Remove-Item x"),
    ("powershell -EncodedCommand AAAA", "powershell -EncodedCommand AAAA"),
    ("Remove-Item x", "Remove-Item x"),
])
def test_powershell_text_is_the_line_powershell_runs(command, shown):
    assert codex_session.shown_command(command) == shown


def test_a_windows_delete_shows_the_line_as_it_runs_and_names_powershell(project, tmp_path,
                                                                         stand_in, monkeypatch):
    """The Arbiter's VM, W-10: the bar showed Codex's quoting — `\\\\` and `'"'` — and said «Bash»
    for a PowerShell line. The gate reads the whole line Codex sent; what is shown is unwrapped.
    Under `writes` it asks; under `auto` it no longer does (one file of the project, the target
    assigned from a literal on the line — the Arbiter, 2026-10-15)."""
    seen: list = []
    real = codex_session.judge_action
    monkeypatch.setattr(codex_session, "judge_action",
                        lambda tool, line, **kw: seen.append(line) or real(tool, line, **kw))
    bridge, _ = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command=WINDOWS_DELETE), gate="writes")
    (request,) = bridge.requests
    assert seen == [WINDOWS_DELETE]
    assert request.detail == WINDOWS_DELETE_RUNS
    assert "\\\\" not in request.detail and "'\"'" not in request.detail
    assert (request.title, request.title_args) == (shell_gate.ALLOW_TITLE, {"tool": "PowerShell"})
    assert request.tool == "Bash"  # what a «don't ask again» tick remembers stays the tool


def test_a_windows_delete_run_in_a_subfolder_shows_the_folder_and_the_line(project, tmp_path,
                                                                           stand_in):
    (project / "process").mkdir(exist_ok=True)
    bridge, _ = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command=WINDOWS_DELETE, cwd=project / "process"),
                         gate="writes")
    (request,) = bridge.requests
    assert request.detail == "Set-Location 'process'; " + WINDOWS_DELETE_RUNS


@pytest.mark.parametrize("cwd", [None, "process"])
def test_the_arbiters_windows_delete_passes_auto(project, tmp_path, stand_in, cwd):
    """The Arbiter's VM, W-10 round 3: Codex's own shape for a delete of one file — the target
    resolved from a literal on the line and checked — asked as «cannot be undone» under `auto`."""
    (project / "process").mkdir(exist_ok=True)
    bridge, _ = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command=WINDOWS_DELETE,
                                       cwd=None if cwd is None else project / cwd), gate="auto")
    assert bridge.requests == [] and decisions(stand_in) == ["accept"]


# ---- task 10's live run: F1 (Codex namespaces the method), F2 (a tool left open at Stop) ---------


def method_dir(project) -> str:
    return os.path.realpath(method_binding.for_project(project).require())


def namespaced_rows(path: str = "<METHOD>/SKILL.md", name: str = "autosound-tuning:autosound-tuning"):
    rows = json.loads(json.dumps(frames("skills-namespaced")))
    skill = rows[-1]["msg"]["result"]["data"][0]["skills"][0]
    skill["path"], skill["name"] = path, name
    return [*rows, *thread_start("th"), *turn("th")]


def test_a_real_codexs_namespaced_method_is_ours(project, tmp_path, stand_in, monkeypatch):
    """F1: a real Codex 0.162.1 lists the linked method as `autosound-tuning:autosound-tuning`
    (the vendored repo carries `.claude-plugin/`), at the bound copy's real path — no Notice."""
    monkeypatch.setenv("FAKE_CODEX_SUB", f"<METHOD>={method_dir(project)}")
    session = make(project, stand_in.use(write(tmp_path, namespaced_rows())))

    async def go():
        try:
            return await drain(session.start(), unchecked=True)
        finally:
            await session.close()

    assert run(go()) == [TurnEnd("th")]


@pytest.mark.parametrize("name", ["autosound-tuning", "autosound-tuning:autosound-tuning",
                                  "someone:autosound-tuning"])
def test_a_second_copy_in_either_spelling_refuses_the_start(project, tmp_path, stand_in,
                                                             monkeypatch, name):
    """F1: «ours» is decided by the path, not the name: the method from anywhere else refuses,
    bare or namespaced."""
    elsewhere = "/opt/other/autosound-tuning/SKILL.md"
    monkeypatch.setenv("FAKE_CODEX_SUB", f"<METHOD>={method_dir(project)}")
    rows = json.loads(json.dumps(frames("skills-namespaced")))
    rows[-1]["msg"]["result"]["data"][0]["skills"].append(
        {"name": name, "path": elsewhere, "scope": "user", "enabled": True})
    session = make(project, stand_in.use(write(tmp_path, [*rows, *thread_start("th"),
                                                          *turn("th")])))

    async def go():
        try:
            await drain(session.start())
        finally:
            await session.close()

    with pytest.raises(method_binding.MethodRefused, match=elsewhere):
        run(go())


def test_the_method_under_the_extra_root_is_ours_by_its_path(project, tmp_path, stand_in):
    """A copy listed at the project's own link (not resolved) is the bound one, whatever its name."""
    path = str(project / ".claude" / "skills" / "autosound-tuning" / "SKILL.md")
    session = make(project, stand_in.use(write(tmp_path, namespaced_rows(path=path))))

    async def go():
        try:
            return await drain(session.start(), unchecked=True)
        finally:
            await session.close()

    assert run(go()) == [TurnEnd("th")]


def test_a_tool_left_open_at_stop_is_closed_before_turn_end(project, stand_in):
    """F2: the approval was pending when Stop came, so Codex sends no `item/completed` for the
    command: `turn/completed` closes it, and the panel's running row stops."""
    resumable(project, PENDING_THREAD)
    bridge = RecordingBridge(None)
    session = make(project, stand_in.use("interrupt-pending"), bridge=bridge, resume=True)

    async def on(event):
        if isinstance(event, ToolCall) and event.name == "Bash":
            while not bridge.requests:
                await asyncio.sleep(0.01)
            await session.interrupt()

    async def go():
        try:
            return await drain(session.start(), on)
        finally:
            await session.close()

    events = run(go())
    tools = [e for e in events if isinstance(e, (ToolCall, ToolEnd))]
    assert tools == [ToolCall("Bash", {"command": "touch held.txt"}), ToolEnd("Bash")]
    assert events[-1] == TurnEnd(PENDING_THREAD) and isinstance(events[-2], ToolEnd)


# ---- the group fix round ------------------------------------------------------------------------


def test_a_gate_that_fails_says_so_in_the_turn(project, tmp_path, stand_in, monkeypatch):
    """I1: the decline came with a WARNING in tcc.log only; the turn now says TCC's check failed
    and the command was refused — before `TurnEnd`."""
    def broken(tool, line, **kw):
        raise OSError("the disk walk failed")

    monkeypatch.setattr(codex_session, "judge_action", broken)
    _, events = run_gate(project, tmp_path, stand_in,
                         approval_turn("th", command="/bin/zsh -lc 'touch a'"))

    said = [e.text for e in events if isinstance(e, Notice)]
    assert len(said) == 1 and "TCC's check" in said[0] and "refused" in said[0]
    assert "the disk walk failed" in said[0]
    kinds = [type(e).__name__ for e in events]
    assert kinds.index("Notice") < kinds.index("TurnEnd")
    assert decisions(stand_in) == ["decline"]


def _refused_initialize(tmp_path, name):
    return write(tmp_path, [out({"id": 1, "method": "initialize"}),
                            inn({"id": 1, "error": {"code": -32600,
                                                    "message": "this client is too old"}})], name)


@pytest.mark.parametrize("where", ["probe", "session"])
def test_an_initialize_codex_refuses_is_a_start_that_failed_with_its_words(
        project, tmp_path, stand_in, where):
    """I2: an `RpcError` on `initialize` reached the window raw («RpcError: …»); it is
    `CodexStartFailed` now, the server's own sentence kept — on the probe and on the session's own
    app-server alike."""
    refused = _refused_initialize(tmp_path, "refused.jsonl")
    binary = (stand_in.use("turn-mcp", probe=refused) if where == "probe"
              else stand_in.use(refused))
    session = make(project, binary)

    async def go():
        try:
            await drain(session.start())
        finally:
            await session.close()

    with pytest.raises(CodexStartFailed, match="this client is too old"):
        run(go())


def test_a_signed_out_start_names_the_menu_line_and_tells_the_pickers(project, stand_in,
                                                                      monkeypatch):
    """M5: «`codex login` in a terminal» was the only advice; the blocker's menu line is the one
    TCC offers. And the cached login now reads signed out, so the next launch is refused by the
    blocker before anything spawns."""
    from autosound_tcc.core import codex_cli
    monkeypatch.setattr(codex_cli, "_PROBE", codex_cli.Probe(signed_in=True, asked=True))
    session = make(project, stand_in.use("signed-out", probe="signed-out"))

    async def go():
        try:
            await drain(session.start())
        finally:
            await session.close()

    with pytest.raises(CodexSignedOut) as caught:
        run(go())
    assert "☰ → ⚙ Settings → Sign in to Codex" in str(caught.value)
    assert "codex login" not in str(caught.value)
    assert codex_cli.signed_in() is False
    assert codex_cli.last_probe().asked, "the rest of the probe kept"


@pytest.mark.parametrize("read, refused", [((0, 162, 1), False), ((0, 100, 0), True)])
def test_the_binary_is_the_settled_codex_never_one_known_too_old(project, monkeypatch, read,
                                                                 refused):
    """M4: `find()` could hand the session an old Codex the probe had already read as too old.
    The session takes `settled()`'s answer (on a thread: it may read a version), and one still too
    old refuses the start, said."""
    from autosound_tcc.core import codex_cli
    found = codex_cli.Found("/opt/codex", codex_cli.SOURCE_PATH)
    calls: list = []
    monkeypatch.setattr(codex_cli, "settled", lambda: calls.append(1) or (found, read))
    monkeypatch.setattr(codex_cli, "find", lambda **_k: pytest.fail("find() alone: unsettled"))
    session = CodexSession(project_dir=project)

    if refused:
        with pytest.raises(CodexStartFailed, match="0.100.0"):
            run(session._binary())
    else:
        assert run(session._binary()) == "/opt/codex"
    assert calls == [1]


def test_no_codex_at_all_is_not_installed(project, monkeypatch):
    from autosound_tcc.core import codex_cli
    monkeypatch.setattr(codex_cli, "settled", lambda: (None, None))
    with pytest.raises(codex_session.CodexNotInstalled):
        run(CodexSession(project_dir=project)._binary())


@pytest.mark.parametrize("ok", [True, False])
def test_the_journal_says_whether_the_resume_held(project, tmp_path, stand_in, monkeypatch, ok):
    """M7: the window journalled `resumed` before the session knew; a refused `thread/resume`
    starts afresh. A launch that means to resume lets the session journal it once it knows."""
    recorded: list = []
    monkeypatch.setattr(codex_session.process_writer, "record_session",
                        lambda project_dir, harness, model, resumed=False:
                        recorded.append((harness, model, resumed)))
    if ok:
        thread = "01a139c1-783b-75c0-afc6-38328bee7086"
        resumable(project, thread)
        rows = [*frames("resume-ok"), *turn(thread)]
    else:
        resumable(project, "00000000-0000-7000-8000-000000000000")
        rows = [*frames("resume-error"), *thread_start("fresh-thread"), *turn("fresh-thread")]
    session = make(project, stand_in.use(write(tmp_path, rows)), resume=True, journal=True)

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    run(go())
    assert recorded == [("codex", MODEL, ok)]


def test_a_session_not_asked_to_journal_writes_nothing(project, tmp_path, stand_in, monkeypatch):
    monkeypatch.setattr(codex_session.process_writer, "record_session",
                        lambda *a, **k: pytest.fail("the window journals this launch"))
    session = make(project, stand_in.use("turn-mcp"))

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    run(go())


def _skills_rows(project, skills):
    return [*opening(), out({"id": 2, "method": "skills/extraRoots/set"}),
            inn({"id": 2, "result": {}}), out({"id": 3, "method": "skills/list"}),
            inn({"id": 3, "result": {"data": [{"cwd": str(project), "skills": skills}]}}),
            *thread_start("th"), *turn("th")]


def test_a_disabled_bound_copy_is_not_loaded(project, tmp_path, stand_in):
    """M8: the bound copy listed but disabled is not one Codex loads — said, as none listed is."""
    ours = str(project / ".claude" / "skills" / "autosound-tuning" / "SKILL.md")
    session = make(project, stand_in.use(write(tmp_path, _skills_rows(project, [
        {"name": "autosound-tuning", "path": ours, "scope": "repo", "enabled": False}]))))

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    events = run(go())
    assert isinstance(events[0], Notice) and "did not load the tuning method" in events[0].text


def test_a_disabled_stray_copy_does_not_refuse_the_start(project, tmp_path, stand_in):
    """M8: a second copy the user switched off cannot be loaded, so it is not a second method."""
    ours = str(project / ".claude" / "skills" / "autosound-tuning" / "SKILL.md")
    session = make(project, stand_in.use(write(tmp_path, _skills_rows(project, [
        {"name": "autosound-tuning", "path": ours, "scope": "repo", "enabled": True},
        {"name": "autosound-tuning", "path": "/opt/other/autosound-tuning/SKILL.md",
         "scope": "user", "enabled": False}]))))

    async def go():
        try:
            return await drain(session.start())
        finally:
            await session.close()

    assert run(go()) == [TurnEnd("th")]


@pytest.mark.parametrize("gate, where", [("writes", "inside"), ("foreign", "inside"),
                                         ("auto", "outside")])
def test_an_edit_tick_never_lets_a_file_delete_through(project, tmp_path, stand_in, gate, where):
    """I4: a «don't ask again» tick on `Edit` removes the question for an ordinary edit, never for
    a delete — the gate's tick is read first and the delete's «cannot be undone» after it, so the
    order in `_judge` cannot be swapped without this failing. (Under `auto` one file of the project
    passes without a tick — the Arbiter, 2026-10-15 — so the row there is one outside it.)"""
    path = project / "a.txt" if where == "inside" else tmp_path / "a.txt"
    rows = approval_turn("th", changes=[{"path": str(path), "kind": {"type": "delete"}}])
    bridge, _ = run_gate(project, tmp_path, stand_in, rows, gate=gate,
                         always_allowed=frozenset({"Edit"}))

    (request,) = bridge.requests
    assert request.reason == "gateIrreversible" and decisions(stand_in) == ["decline"]


def test_an_edit_tick_lets_an_ordinary_edit_through(project, tmp_path, stand_in):
    rows = approval_turn("th", changes=[{"path": str(project / "a.txt"),
                                         "kind": {"type": "update"}}])
    bridge, _ = run_gate(project, tmp_path, stand_in, rows, gate="writes",
                         always_allowed=frozenset({"Edit"}))

    assert bridge.requests == [] and decisions(stand_in) == ["accept"]


# ---- Windows inputs, as pure functions (group fix I5) -------------------------------------------

WIN_PROJECT = r"C:\Users\Me\Documents\car"


@pytest.mark.parametrize("cwd, said", [
    (WIN_PROJECT, None),
    (r"c:\users\me\documents\CAR", None),                      # another case, the same folder
    (r"\\?\C:\Users\Me\Documents\car", None),                  # the long-path spelling
    (WIN_PROJECT + r"\process", "process"),
    (r"C:\USERS\ME\DOCUMENTS\CAR\Process\Sub", r"Process\Sub"),
    (r"\\?\C:\Users\Me\Documents\car\state", "state"),
    (r"C:\Users\Me", "outside"),
    (r"C:\Users\Me\Documents\car-other", "outside"),           # a sibling sharing the prefix
    (r"D:\Users\Me\Documents\car", "outside"),                 # another drive
    (r"\\?\D:\x", "outside"),
])
def test_where_reads_a_windows_cwd(cwd, said):
    """Codex on Windows names its `cwd` as Windows does: any case, the `\\\\?\\` prefix. The same
    folder in another spelling is the project, not «outside» (which asks about everything)."""
    import ntpath
    assert codex_session.where(cwd, WIN_PROJECT, paths=ntpath) == said


@pytest.mark.parametrize("cwd", ["process", r"C:\Users\O'Brien\car's folder"])
def test_in_folder_for_powershell_quotes_the_folder_as_powershell_does(cwd):
    line = CodexSession._in_folder("Remove-Item -Recurse -Force ..", cwd, "powershell")

    assert line == "Set-Location '" + cwd.replace("'", "''") + "'; Remove-Item -Recurse -Force .."


def test_a_powershell_line_run_in_a_subfolder_is_judged_from_there(tmp_path):
    """The gate reads the PowerShell line `_in_folder` builds: `..` from `process` is the project
    itself — a recursive delete of it asks; a delete of a file there does not under `auto`."""
    from autosound_tcc.core.shell_gate import GATE_AUTO, SHELL_POWERSHELL, judge_action
    from autosound_tcc.core.tuning_session import _read_roots_for
    (tmp_path / "process").mkdir()
    roots = _read_roots_for(tmp_path)

    wide = CodexSession._in_folder("Remove-Item -Recurse -Force ..\\..", "process", "powershell")
    narrow = CodexSession._in_folder("Remove-Item x.tmp", "process", "powershell")

    assert not judge_action("Bash", wide, gate=GATE_AUTO, read_roots=roots,
                            shell=SHELL_POWERSHELL).allowed
    assert judge_action("Bash", narrow, gate=GATE_AUTO, read_roots=roots,
                        shell=SHELL_POWERSHELL).allowed


def test_the_session_says_it_journalled_only_when_it_did(project, tmp_path, stand_in, monkeypatch):
    """The re-review's I (B): the window closes a Codex resume's journal line only when the
    session says it wrote the start; a refused `session-start` is a Notice and no claim."""
    from autosound_tcc.core import process_writer

    def refused(*a, **k):
        raise process_writer.ProcessWriterError("holds no project.json")

    thread = "01a139c1-783b-75c0-afc6-38328bee7086"
    resumable(project, thread)
    rows = [*frames("resume-ok"), *turn(thread)]
    results = {}
    for name, record in (("ok", lambda *a, **k: "ok"), ("refused", refused)):
        monkeypatch.setattr(codex_session.process_writer, "record_session", record)
        session = make(project, stand_in.use(write(tmp_path, rows, f"{name}.jsonl")), resume=True,
                       journal=True)

        async def go(s=session):
            try:
                return await drain(s.start())
            finally:
                await s.close()

        events = run(go())
        results[name] = (session.journaled, events)
    assert results["ok"][0] is True
    journaled, events = results["refused"]
    assert journaled is False
    assert any(isinstance(e, Notice) and "holds no project.json" in e.text for e in events)


def test_a_start_that_fails_before_the_journal_claims_nothing(project, stand_in):
    """(A): signed out — the session never reached its journal line."""
    session = make(project, stand_in.use("signed-out", probe="signed-out"), resume=True,
                   journal=True)

    async def go():
        try:
            await drain(session.start())
        finally:
            await session.close()

    with pytest.raises(CodexSignedOut):
        run(go())
    assert session.journaled is False


def test_a_reasoning_item_says_the_model_is_thinking(tmp_path):
    """#223: Codex's `reasoning` item was dropped, so the panel never heard of a think. Its text
    stays out — the panel says «thinking», never what was thought."""
    session = CodexSession(project_dir=tmp_path)
    item = {"type": "reasoning", "id": "rs_1", "summary": ["secret plan"], "content": []}

    assert session._map({"method": "item/started", "params": {"item": item}}) == ([Thinking()], False)
    assert session._map({"method": "item/completed", "params": {"item": item}}) == ([], False)
