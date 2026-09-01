"""The recorded sessions, replayed through the adapter offline.

`tests/fixtures/omp-frames-real.jsonl` is not written by hand: it is `.tcc/omp-frames.jsonl` out of
a real project after five live runs on 2026-08-05, reduced to the fields the RPC protocol turns on
(`type`, `id`, `method`, `title`, `options`, `widgetKey`, `targetId`, `toolName`) with long values
cut. 681 lines, both directions, one afternoon of the adapter hanging in five different ways.

**What it proves, and why it is worth a file of its own.** Every one of those five hangs was found
after the fact, from a different run, by guessing at what omp had sent — and each guess cost a
session. The frames are the evidence, and the invariant they can settle is a single sentence:
*every `extension_ui_request` gets exactly one `extension_ui_response`.* omp blocks inside the tool
that raised the frame, so a request that goes unanswered is not a lost message, it is the end of
the conversation.

What the recording itself says about the version that produced it, all four countable off the
fixture:

* 23 requests, **4 of them never answered** — two `editor` (omp's free-text prompt, the frame the
  adapter had no branch for) and two `cancel` (omp withdrawing its own editor after the abort).
  Both fell through to "this must be a question", so they waited for an answer nobody could give.
* 4 responses to ids **that appear nowhere as requests**: frames read and answered by the two
  ad-hoc stdout readers in startup, which logged nothing. The blind spot was in the record itself.
* 471 seconds between the last editor frame and the abort that ended the run. That is the whole
  failure, in one number.

The subprocess is never started. The fixture is fed to the adapter's own reader, and a stand-in
Arbiter answers questions the way `DialogPanel` does, because that is the contract the panel keeps.
Point `TCC_OMP_FRAME_LOG` at a full unreduced log to replay that instead.
"""

from __future__ import annotations

import asyncio
import json
import os
from concurrent.futures import Future
from pathlib import Path

import pytest

from autosound_tcc.core import omp_session as omp_session_module
from autosound_tcc.core.agent_events import Notice, Question, QuestionWithdrawn, ToolCall
from autosound_tcc.core.mcp_server import ConfirmRequest
from autosound_tcc.core.omp_session import OmpSession

FIXTURE = Path(__file__).parent / "fixtures" / "omp-frames-real.jsonl"


class AllowingArbiter:
    """Answers every permission yes. What is under test is the wire, not the verdict."""

    def __init__(self) -> None:
        self.requests: list[ConfirmRequest] = []

    def snapshot(self) -> dict:
        return {}

    def request_confirmation(self, request: ConfirmRequest) -> "Future[bool]":
        self.requests.append(request)
        future: "Future[bool]" = Future()
        future.set_result(True)
        return future

    def copy_to_clipboard(self, text: str) -> None: ...

    def show_proposal(self, proposal: dict) -> None: ...

    def show_critique(self, critique: dict) -> None: ...

    def notify_profile_ready(self) -> None: ...

    def refresh_from_disk(self) -> None: ...


def _recorded() -> list[dict]:
    """The log as entries, in order.

    A line the old writer truncated mid-JSON becomes an `_unparseable` placeholder rather than
    disappearing, which is how the fixture keeps them too: the count is a finding, not noise. Set
    `TCC_OMP_FRAME_LOG` to replay a full log from a real project instead of the fixture.
    """
    path = Path(os.environ.get("TCC_OMP_FRAME_LOG") or FIXTURE)
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            entries.append({"dir": "in", "frame": {"type": "_unparseable"}})
    return entries


def _inbound(entries: list[dict]) -> list[dict]:
    return [entry["frame"] for entry in entries if entry.get("dir") == "in"]


class Replay:
    """One offline run: recorded frames in, responses and events out."""

    def __init__(self, tmp_path: Path, answer_questions: bool = True) -> None:
        self.session = OmpSession(project_dir=tmp_path, bridge=AllowingArbiter())
        self.sent: list[dict] = []
        self.session._send = self.sent.append  # type: ignore[assignment]
        self.events: list = []
        self.answers: list[tuple[str, str]] = []
        self._answer_questions = answer_questions

    async def _run(self, frames: list[dict]) -> None:
        for frame in frames:
            for event in self.session._handle(frame):
                self.events.append(event)
                if isinstance(event, Question) and self._answer_questions:
                    # Exactly what `DialogPanel` does: click the first option, or type when there
                    # is nothing to click. Free text is how omp asks for a car and a processor.
                    value = event.options[0].label if event.options else "Audi A6 / Helix DSP"
                    self.answers.append((event.id, value))
                    await self.session.answer(event.id, value)
            # The gate runs as its own task so the reader keeps draining; give it the loop.
            await asyncio.sleep(0)
        if self.session._pending:
            await asyncio.gather(*list(self.session._pending))

    def run(self, frames: list[dict]) -> "Replay":
        asyncio.run(self._run(frames))
        return self

    @property
    def responses(self) -> list[dict]:
        return [frame for frame in self.sent if frame.get("type") == "extension_ui_response"]


# ---- the invariant ---------------------------------------------------------


def test_every_recorded_request_is_answered_exactly_once(tmp_path):
    """The whole point. One response per request, no seconds, no extras.

    A missing one is a turn that never ends; a duplicate is worse, because it lands on whatever
    omp raised next — that is how a permission came to be answered with a question's text.
    """
    frames = _inbound(_recorded())
    requests = [frame for frame in frames if frame.get("type") == "extension_ui_request"]

    replay = Replay(tmp_path).run(frames)

    answered = [str(response.get("id")) for response in replay.responses]
    assert sorted(answered) == sorted(str(frame.get("id")) for frame in requests)
    assert len(answered) == len(set(answered)), "a request was answered twice"


def test_the_recording_is_the_failure_it_was_captured_for(tmp_path):
    """Guard on the fixture, not on the code: if this stops holding, the file was replaced by one
    that does not contain the bug, and the test above stops proving anything."""
    entries = _recorded()
    requests = {
        str(entry["frame"].get("id")): entry["frame"].get("method")
        for entry in entries
        if entry.get("dir") == "in" and entry["frame"].get("type") == "extension_ui_request"
    }
    answered = {
        str(entry["frame"].get("id"))
        for entry in entries
        if entry.get("dir") == "out" and entry["frame"].get("type") == "extension_ui_response"
    }

    unanswered = {key: method for key, method in requests.items() if key not in answered}

    assert sorted(unanswered.values()) == ["cancel", "cancel", "editor", "editor"]
    # And the other half of the same defect: answers to frames that were never written down,
    # because startup read them off stdout on its own and logged nothing.
    assert len(answered - set(requests)) == 4


def test_nothing_is_left_waiting_when_the_arbiter_never_answers(tmp_path):
    """The Arbiter is allowed to say nothing — they walked away, or the question is unanswerable.

    A request is then in one of exactly three states, and there is no fourth: settled (answered, or
    withdrawn by omp itself), on screen as a question, or in front of the Arbiter as a permission.
    "None of the above" is the hang, and it is what the recording is full of.
    """
    frames = _inbound(_recorded())

    replay = Replay(tmp_path, answer_questions=False).run(frames)

    requests = {str(frame.get("id")) for frame in frames
                if frame.get("type") == "extension_ui_request"}
    session = replay.session
    assert requests - (session._answered | session._parked | session._gating) == set()
    # Withdrawn is settled without a response: omp is not waiting for one, it took the frame back.
    withdrawn = {str(frame.get("targetId")) for frame in frames
                 if frame.get("method") == "cancel"}
    assert withdrawn <= session._answered
    assert withdrawn.isdisjoint({str(response.get("id")) for response in replay.responses})


# ---- the frames that caused it ---------------------------------------------


def test_the_free_text_editor_reaches_the_arbiter_as_a_question(tmp_path):
    """The frame the run died on. omp raises it after "Other (type your own)" is chosen; the
    adapter that shipped that afternoon had no branch for it, so it became a question card with
    omp's radio glyphs drawn inside and then 471 seconds of nothing."""
    frames = _inbound(_recorded())

    replay = Replay(tmp_path).run(frames)

    editors = [frame for frame in frames if frame.get("method") == "editor"]
    assert len(editors) == 2
    answered = {str(response.get("id")) for response in replay.responses}
    for frame in editors:
        assert str(frame.get("id")) in answered
        question = next(e for e in replay.events
                        if isinstance(e, Question) and e.id == str(frame.get("id")))
        assert question.options == ()  # no options: the composer is the answer
        assert "○" not in question.question


def test_omp_taking_a_question_back_clears_it(tmp_path):
    """`method: "cancel"` with a `targetId`. Unknown, it fell through to "this is a question" and
    put an empty card over the real one; the real one stayed unanswered underneath."""
    frames = _inbound(_recorded())

    replay = Replay(tmp_path, answer_questions=False).run(frames)

    withdrawn = [event for event in replay.events if isinstance(event, QuestionWithdrawn)]
    cancels = [frame for frame in frames if frame.get("method") == "cancel"]
    assert [event.id for event in withdrawn] == [str(frame.get("targetId")) for frame in cancels]
    # And the withdrawal itself is answered, like every other request.
    answered = {str(response.get("id")) for response in replay.responses}
    assert all(str(frame.get("id")) in answered for frame in cancels)


def test_a_method_nobody_has_seen_is_cancelled_and_named(tmp_path):
    """The rule that replaces the list of known frames. The next thing omp adds will reach a
    version of this file that has never heard of it, and the cost of that must be one line in the
    transcript rather than one lost session."""
    replay = Replay(tmp_path)

    events = replay.session._handle(
        {"type": "extension_ui_request", "id": "u1", "method": "quantumPrompt", "title": "?"}
    )

    assert replay.sent == [{"type": "extension_ui_response", "id": "u1", "cancelled": True}]
    assert [event.name for event in events if isinstance(event, ToolCall)] == ["omp:quantumPrompt"]


def test_a_request_with_no_method_at_all_is_still_answered(tmp_path):
    replay = Replay(tmp_path)

    replay.session._handle({"type": "extension_ui_request", "id": "u2"})

    assert replay.sent == [{"type": "extension_ui_response", "id": "u2", "cancelled": True}]


def test_a_branch_that_forgets_to_answer_is_caught(tmp_path):
    """`_ensure_answered` is the net under the classifier, so it is tested as a net: break the
    branch and the frame still gets an answer, plus a name saying which one leaked."""
    replay = Replay(tmp_path)
    replay.session._handle_request = lambda frame: []  # type: ignore[assignment]

    events = replay.session._handle(
        {"type": "extension_ui_request", "id": "u3", "method": "select", "title": "?"}
    )

    assert replay.sent == [{"type": "extension_ui_response", "id": "u3", "cancelled": True}]
    assert [event.name for event in events if isinstance(event, ToolCall)] == [
        "omp:unanswered:select"
    ]


def test_the_same_request_is_never_answered_twice(tmp_path):
    """A stale answer is not harmless: omp has moved on, so it lands on the next frame it raised."""
    replay = Replay(tmp_path)

    asyncio.run(replay.session.answer("q1", "Driver"))
    asyncio.run(replay.session.answer("q1", "Both front"))
    asyncio.run(replay.session.cancel_question("q1"))

    assert replay.sent == [{"type": "extension_ui_response", "id": "q1", "value": "Driver"}]


# ---- the record itself -----------------------------------------------------


def test_the_frame_log_the_old_writer_wrote_is_partly_unreadable(tmp_path):
    """Kept as a fact about the fixture, since it is why `_shrink` exists.

    The first writer capped the serialised *line* at 8000 characters, which cut it mid-string: 64
    of 681 lines will not parse, and they are the big ones — tool catalogues, skill files, the
    frames worth reading. The fixture keeps them as `_unparseable` placeholders so the count is
    still visible here.
    """
    entries = _recorded()

    placeholders = [entry for entry in entries
                    if entry.get("frame", {}).get("type") == "_unparseable"]

    assert len(placeholders) == 64


def test_a_frame_too_big_to_log_is_still_logged_as_json(tmp_path):
    """The replay above reads the log back. A writer that can produce a line nobody can parse is a
    writer that deletes its own evidence, which is what the first one did."""
    session = OmpSession(project_dir=tmp_path, bridge=AllowingArbiter())

    session._log("in", {"type": "response", "id": "big", "text": "x" * 200_000,
                        "tools": [{"name": f"t{n}", "doc": "y" * 5_000} for n in range(300)]})

    lines = session._log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])  # must not raise -- this is the whole assertion
    assert entry["frame"]["type"] == "response"
    assert entry["frame"]["id"] == "big"
    assert len(lines[0]) < 100_000


def test_shrinking_keeps_the_fields_a_frame_is_read_by(tmp_path):
    """Cutting is fine; losing `id` or `method` would make the log unusable for exactly the audit
    it was kept for."""
    frame = {"type": "extension_ui_request", "id": "f1", "method": "select",
             "title": "q" * 5_000, "options": [f"option {n}" for n in range(200)]}

    shrunk = omp_session_module._shrink(frame)

    assert shrunk["id"] == "f1" and shrunk["method"] == "select"
    assert shrunk["title"].endswith("…")
    assert len(shrunk["options"]) == omp_session_module.FRAME_LIST_MAX_ITEMS + 1


# ---- startup, which used to read frames behind the reader's back -----------


class FakeProcess:
    """Just enough of `asyncio.subprocess.Process` to replay a stream into `start()`."""

    def __init__(self, lines: list[str], eof: bool = False) -> None:
        self.stdout = asyncio.StreamReader()
        for line in lines:
            self.stdout.feed_data((line + "\n").encode())
        if eof:
            self.stdout.feed_eof()  # only when the point is a process that died
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.stdin = self
        self.returncode = None
        self.written: list[bytes] = []

    # stdin
    def write(self, data: bytes) -> None:
        self.written.append(data)

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return 0


def test_a_frame_arriving_during_startup_is_answered_and_written_down(tmp_path, monkeypatch):
    """Startup used to hold stdout itself, in two separate loops, and drop everything it was not
    looking for — unanswered and unlogged. omp raises `setWidget` for its own `autoresearch`
    exactly there, and four such answers appear in the recording against requests that were never
    recorded at all: the blind spot was in the evidence, not only in the behaviour."""
    frames = [
        json.dumps({"type": "ready", "protocolVersions": [1, 2]}),
        json.dumps({"type": "extension_ui_request", "id": "s1", "method": "setWidget",
                    "widgetKey": "autoresearch"}),
        json.dumps({"type": "extension_ui_request", "id": "s2", "method": "somethingNew"}),
        json.dumps({"type": "agent_end", "messages": []}),
    ]
    process: list[FakeProcess] = []

    async def fake_exec(*args, **kwargs):
        # Built here rather than in the test body: a StreamReader binds to the running loop.
        process.append(FakeProcess(frames))
        return process[0]

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(omp_session_module, "is_available", lambda: True)
    monkeypatch.setattr(omp_session_module, "SETTLE_QUIET_S", 0.05)
    monkeypatch.setattr(omp_session_module, "TURN_QUIET_S", 0.05)

    async def drive() -> list:
        session = OmpSession(project_dir=tmp_path, bridge=AllowingArbiter())
        events = []
        agen = session.start()
        try:
            async for event in agen:
                events.append(event)
        finally:
            await agen.aclose()
            await session.close()
        return events

    asyncio.run(asyncio.wait_for(drive(), timeout=10))

    sent = [json.loads(chunk.decode()) for chunk in process[0].written]
    answered = {frame.get("id") for frame in sent
                if frame.get("type") == "extension_ui_response"}
    assert {"s1", "s2"} <= answered
    logged = [json.loads(line) for line in
              (tmp_path / ".tcc" / "omp-frames.jsonl").read_text(encoding="utf-8").splitlines()]
    inbound = {entry["frame"].get("id") for entry in logged if entry["dir"] == "in"}
    assert {"s1", "s2"} <= inbound


def test_a_process_that_dies_before_ready_says_so_rather_than_waiting(tmp_path, monkeypatch):
    async def fake_exec(*args, **kwargs):
        return FakeProcess([], eof=True)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(omp_session_module, "is_available", lambda: True)

    async def drive() -> None:
        session = OmpSession(project_dir=tmp_path, bridge=AllowingArbiter())
        agen = session.start()
        async for _ in agen:
            pass

    with pytest.raises(RuntimeError, match="exited before reporting ready"):
        asyncio.run(asyncio.wait_for(drive(), timeout=10))


def test_omp_refusing_a_command_is_said_out_loud(tmp_path):
    """`response` is omp answering something TCC sent, and `success: false` is the only place it
    says no. A rejected `negotiate_protocol` leaves a session that is up, connected and silent
    forever — the same shape as every other hang, arriving on the one frame nobody was reading."""
    replay = Replay(tmp_path)

    events = replay.session._handle(
        {"type": "response", "id": "tcc1", "command": "negotiate_protocol",
         "success": False, "error": "Unsupported RPC protocol version"}
    )

    assert len(events) == 1
    # A Notice, not a TextDelta: under the model's byline it read as the model saying it.
    assert isinstance(events[0], Notice)
    assert "Unsupported RPC protocol version" in events[0].text
    assert "negotiate_protocol" in events[0].text


def test_a_command_omp_accepted_is_not_narrated(tmp_path):
    """Every prompt gets one of these. Rendering them would put "response: prompt ok" above every
    answer in the transcript."""
    replay = Replay(tmp_path)

    assert replay.session._handle(
        {"type": "response", "id": "tcc2", "command": "prompt", "success": True}
    ) == []


# ---- what omp does about a model that answers badly -------------------------


def test_a_retry_storm_is_explained_once(tmp_path):
    """Seven attempts over 106 seconds, all of them invisible: the wire carried nothing but empty
    messages while omp fought `MALFORMED_FUNCTION_CALL` out of a small model, and the window had
    nothing to show. One line naming the cause turns that silence into something the Arbiter can
    read; one line per attempt would be seven bubbles saying the same thing."""
    replay = Replay(tmp_path)

    first = replay.session._handle(
        {"type": "auto_retry_start", "attempt": 1, "maxAttempts": 10,
         "errorMessage": "Generation failed with finish reason: MALFORMED_FUNCTION_CALL"}
    )
    rest = [replay.session._handle({"type": "auto_retry_start", "attempt": n, "maxAttempts": 10,
                                    "errorMessage": "same"}) for n in range(2, 8)]

    assert len(first) == 1 and isinstance(first[0], Notice)
    assert "MALFORMED_FUNCTION_CALL" in first[0].text
    assert "10" in first[0].text  # the budget, so the silence has a known end
    assert rest == [[]] * 6


def test_the_retry_line_does_not_diagnose_on_omps_behalf(tmp_path):
    """It opened with "the model's answer came back broken", which is true of a malformed call and
    a lie about the error that actually turned up: a 429 saying the account's prepaid credits were
    gone. Ten retries of that are hopeless, and blaming the model sends the Arbiter to fix the
    wrong thing."""
    replay = Replay(tmp_path)

    events = replay.session._handle(
        {"type": "auto_retry_start", "attempt": 1, "maxAttempts": 10,
         "errorMessage": "Google API error (429): Your prepayment credits are depleted."}
    )

    assert "prepayment credits are depleted" in events[0].text
    assert "broken" not in events[0].text


def test_giving_up_says_what_it_gave_up_on(tmp_path):
    """The line people screenshot. By then the first Notice has scrolled, and "gave up" alone says
    nothing about what to do next."""
    replay = Replay(tmp_path)
    replay.session._handle({"type": "auto_retry_start", "attempt": 1, "maxAttempts": 10,
                            "errorMessage": "Google API error (429): credits depleted."})

    events = replay.session._handle({"type": "auto_retry_end", "success": False, "attempt": 10})

    assert "credits depleted" in events[0].text
    assert "produced nothing" in events[0].text


def test_a_recovered_retry_says_so(tmp_path):
    replay = Replay(tmp_path)
    replay.session._handle({"type": "auto_retry_start", "attempt": 1, "maxAttempts": 10})

    events = replay.session._handle({"type": "auto_retry_end", "success": True, "attempt": 7})

    assert isinstance(events[0], Notice)
    assert "attempt 7" in events[0].text


def test_a_retry_that_ran_out_says_that_instead(tmp_path):
    replay = Replay(tmp_path)
    replay.session._handle({"type": "auto_retry_start", "attempt": 1, "maxAttempts": 10})

    events = replay.session._handle({"type": "auto_retry_end", "success": False, "attempt": 10})

    assert "gave up" in events[0].text


def test_a_turn_that_produced_nothing_is_a_turn_that_ended(tmp_path):
    """CAR-004, from a Windows run on 2026-09-01. The credits ran out mid-turn; omp retried its
    ten times, said "produced nothing" — and then said nothing ever again. There is no `turn_end`
    frame after a give-up, so the window kept saying "thinking" and a queued message kept promising
    to go "the moment this turn ends", which nothing was ever going to make true. The Arbiter got
    out by pressing `Send now`.

    A finished ROUND rather than a `TurnEnd` outright: `_prompt` closes the turn 2.5 s later if
    nothing follows, and the next test says what happens when something does."""
    replay = Replay(tmp_path)
    replay.session._handle({"type": "auto_retry_start", "attempt": 1, "maxAttempts": 10,
                            "errorMessage": "Google API error (429): credits depleted."})

    replay.session._handle({"type": "auto_retry_end", "success": False, "attempt": 10})

    assert replay.session._round_ended_at, "the turn is closing, not hanging"


def test_a_session_that_carries_on_after_giving_up_is_not_cut_off(tmp_path):
    """The other half of the same rule. omp giving up on one model call is not proof that the turn
    is finished — if the next frame is work, the turn goes on."""
    replay = Replay(tmp_path)
    replay.session._handle({"type": "auto_retry_start", "attempt": 1, "maxAttempts": 10})
    replay.session._handle({"type": "auto_retry_end", "success": False, "attempt": 10})

    replay.session._handle({"type": "message_start"})

    assert not replay.session._round_ended_at, "activity reopens it"


def test_a_recovered_storm_leaves_the_turn_running(tmp_path):
    """A storm that ENDED WELL is not an ending at all: the answer omp finally got is the turn."""
    replay = Replay(tmp_path)
    replay.session._handle({"type": "auto_retry_start", "attempt": 1, "maxAttempts": 10})

    replay.session._handle({"type": "auto_retry_end", "success": True, "attempt": 7})

    assert not replay.session._round_ended_at


def test_a_retry_end_without_a_storm_is_not_narrated(tmp_path):
    replay = Replay(tmp_path)

    assert replay.session._handle({"type": "auto_retry_end", "success": True, "attempt": 1}) == []


def test_the_silence_warning_names_the_tool_it_is_stuck_in(tmp_path, monkeypatch):
    """"omp has said nothing" and "still inside grep" ask different things of the Arbiter. The
    second was true for 510 seconds -- a `grep` for `groups` with no path, started and never
    returned -- while the first was all the window said."""
    monkeypatch.setattr(omp_session_module, "SILENCE_WARN_S", 0.05)
    session = OmpSession(project_dir=tmp_path, bridge=AllowingArbiter())
    sent: list[dict] = []
    session._send = sent.append  # type: ignore[assignment]
    session._handle({"type": "tool_execution_start", "toolName": "grep", "args": {}})

    async def first_event():
        async for event in session._prompt("hi"):
            return event

    event = asyncio.run(asyncio.wait_for(first_event(), timeout=5))

    assert isinstance(event, Notice)
    assert "grep" in event.text


def test_a_tool_that_returned_is_no_longer_what_we_are_stuck_in(tmp_path, monkeypatch):
    monkeypatch.setattr(omp_session_module, "SILENCE_WARN_S", 0.05)
    session = OmpSession(project_dir=tmp_path, bridge=AllowingArbiter())
    session._send = lambda frame: None  # type: ignore[assignment]
    session._handle({"type": "tool_execution_start", "toolName": "grep", "args": {}})
    session._handle({"type": "tool_execution_end", "toolName": "grep"})

    async def first_event():
        async for event in session._prompt("hi"):
            return event

    event = asyncio.run(asyncio.wait_for(first_event(), timeout=5))

    assert "grep" not in event.text
