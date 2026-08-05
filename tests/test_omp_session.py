"""The omp adapter: frame translation, the Arbiter gate, and the question channel.

Frames here are the ones omp actually emits — captured off `--mode rpc-ui` on the spike stand
before the adapter was written, not invented to match it. The subprocess itself is never started:
what is under test is the translation and the gating, and those are pure given a frame.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import Future

import pytest

from autosound_tcc.core.agent_events import Question, TextDelta, ToolCall, TurnEnd
from autosound_tcc.core.mcp_server import ConfirmRequest
from autosound_tcc.core.omp_session import OmpSession


class RecordingBridge:
    """A stand-in Arbiter whose verdict the test chooses up front."""

    def __init__(self, allow: bool) -> None:
        self.allow = allow
        self.requests: list[ConfirmRequest] = []

    def snapshot(self) -> dict:
        return {}

    def request_confirmation(self, request: ConfirmRequest) -> "Future[bool]":
        self.requests.append(request)
        future: "Future[bool]" = Future()
        future.set_result(self.allow)
        return future

    def copy_to_clipboard(self, text: str) -> None: ...

    def show_proposal(self, proposal: dict) -> None: ...

    def show_critique(self, critique: dict) -> None: ...

    def notify_profile_ready(self) -> None: ...

    def refresh_from_disk(self) -> None: ...


def _session(tmp_path, allow=True):
    session = OmpSession(project_dir=tmp_path, bridge=RecordingBridge(allow))
    session.sent: list[dict] = []  # type: ignore[attr-defined]
    session._send = session.sent.append  # type: ignore[assignment]
    return session


PERMISSION_FRAME = {
    "type": "extension_ui_request",
    "id": "f1",
    "method": "select",
    "title": "Allow tool: bash",
    "options": ["Approve", "Deny"],
}
QUESTION_FRAME = {
    "type": "extension_ui_request",
    "id": "q1",
    "method": "select",
    "title": "Reference seat for this tune?",
    "options": ["Driver", "Both front", "Other (type your own)"],
}


# ---- translation -----------------------------------------------------------


def test_streamed_text_becomes_a_text_event(tmp_path):
    session = _session(tmp_path)

    events = session._handle(
        {"type": "message_update",
         "assistantMessageEvent": {"type": "text_delta", "delta": "Phase 2, "}}
    )

    assert events == [TextDelta("Phase 2, ")]


def test_non_text_message_updates_are_not_rendered(tmp_path):
    """`text_start` and `text_end` bracket the deltas and carry the same content again."""
    session = _session(tmp_path)

    assert session._handle(
        {"type": "message_update", "assistantMessageEvent": {"type": "text_start"}}
    ) == []


def test_a_tool_execution_becomes_a_tool_call(tmp_path):
    session = _session(tmp_path)

    events = session._handle(
        {"type": "tool_execution_start", "toolName": "mcp__tcc_get_ledger",
         "args": {"preset": "FULL"}}
    )

    assert events == [ToolCall(name="mcp__tcc_get_ledger", arguments={"preset": "FULL"})]


def test_the_ask_tool_is_not_also_a_process_chip(tmp_path):
    """It arrives as the question it raises; a chip beside it would render the same act twice."""
    session = _session(tmp_path)

    assert session._handle({"type": "tool_execution_start", "toolName": "ask"}) == []


def test_agent_end_closes_the_exchange(tmp_path):
    session = _session(tmp_path)

    assert session._handle({"type": "agent_end", "messages": []}) == [TurnEnd()]


def test_turn_end_does_not_close_the_exchange(tmp_path):
    """A `turn` in omp is one round of the model, so a prompt answered with eight tool calls emits
    nine `turn_end`s. Ending on the first delivered a few process chips and then silence forever —
    measured in use before this was understood."""
    session = _session(tmp_path)

    assert session._handle({"type": "turn_end", "message": {}}) == []


def test_chrome_frames_are_answered_and_not_rendered(tmp_path):
    """Unanswered chrome stalls the agent; rendered chrome is noise in the transcript."""
    session = _session(tmp_path)

    events = session._handle(
        {"type": "extension_ui_request", "id": "c1", "method": "setTitle", "title": "omp"}
    )

    assert events == []
    assert session.sent == [{"type": "extension_ui_response", "id": "c1", "cancelled": True}]


# ---- telling a permission from a question ----------------------------------


def test_a_permission_frame_is_recognised(tmp_path):
    assert OmpSession._is_permission(PERMISSION_FRAME) is True


def test_a_question_frame_is_not_a_permission(tmp_path):
    assert OmpSession._is_permission(QUESTION_FRAME) is False


def test_a_free_text_question_is_not_a_permission(tmp_path):
    """omp raises questions with no options at all. Treating those as permissions put the question
    in front of the Arbiter as "Allow <question text>?", sent omp "Approve" as the answer, and
    wedged the turn — seen in a live session, transcript and all."""
    assert OmpSession._is_permission(
        {"type": "extension_ui_request", "id": "x", "method": "select",
         "title": "What is your car make/model?", "options": []}
    ) is False


def test_a_confirm_frame_is_always_a_permission(tmp_path):
    assert OmpSession._is_permission({"method": "confirm", "title": "Proceed?"}) is True


def test_a_question_reaches_the_dialog_with_its_options(tmp_path):
    session = _session(tmp_path)

    events = session._handle(QUESTION_FRAME)

    assert len(events) == 1
    question = events[0]
    assert isinstance(question, Question)
    assert question.id == "q1"
    assert question.question == "Reference seat for this tune?"
    assert [option.label for option in question.options] == [
        "Driver", "Both front", "Other (type your own)"
    ]
    assert session.sent == []  # nothing is answered on the agent's behalf


# ---- the gate --------------------------------------------------------------


def test_a_multiline_title_splits_into_the_tool_and_what_it_wants(tmp_path):
    """omp sends `Allow tool: bash\nCommand: echo spike`. Taking all of it as the tool name puts a
    shell command in the confirmation heading and breaks the `mcp__tcc` check -- seen live."""
    tool, detail = OmpSession._tool_and_detail(
        {"title": "Allow tool: bash\nCommand: echo spike"}
    )

    assert tool == "bash"
    assert detail == "Command: echo spike"


def test_a_tcc_tool_with_arguments_in_the_title_is_still_recognised(tmp_path):
    session = _session(tmp_path, allow=False)

    asyncio.run(session._gate({**PERMISSION_FRAME,
                               "title": "Allow tool: mcp__tcc_copy_helix_eq\nText: PK 1000"}))

    assert session.bridge.requests == []
    assert session.sent == [{"type": "extension_ui_response", "id": "f1", "value": "Approve"}]


def test_a_permission_goes_to_the_arbiter_and_is_answered(tmp_path):
    session = _session(tmp_path, allow=True)

    asyncio.run(session._gate(PERMISSION_FRAME))

    assert session.bridge.requests[0].tool == "bash"
    assert "\n" not in session.bridge.requests[0].tool
    assert session.sent == [{"type": "extension_ui_response", "id": "f1", "value": "Approve"}]


def test_a_refused_permission_denies_the_tool(tmp_path):
    session = _session(tmp_path, allow=False)

    asyncio.run(session._gate(PERMISSION_FRAME))

    assert session.sent == [{"type": "extension_ui_response", "id": "f1", "value": "Deny"}]


def test_tcc_tools_are_not_gated_twice(tmp_path):
    """Each `mcp__tcc` tool raises its own confirmation inside the tool; prompting here as well
    would ask the Arbiter twice for one action and train them to click through both."""
    session = _session(tmp_path, allow=False)

    asyncio.run(session._gate({**PERMISSION_FRAME, "title": "Allow tool: mcp__tcc_copy_helix_eq"}))

    assert session.bridge.requests == []
    assert session.sent == [{"type": "extension_ui_response", "id": "f1", "value": "Approve"}]


def test_a_confirm_permission_answers_in_its_own_vocabulary(tmp_path):
    session = _session(tmp_path, allow=True)

    asyncio.run(session._gate({"type": "extension_ui_request", "id": "f2", "method": "confirm",
                               "title": "Allow tool: bash"}))

    assert session.sent == [{"type": "extension_ui_response", "id": "f2", "confirmed": True}]


# ---- answering -------------------------------------------------------------


def test_answering_a_question_sends_the_chosen_label(tmp_path):
    session = _session(tmp_path)

    asyncio.run(session.answer("q1", "Driver"))

    assert session.sent == [{"type": "extension_ui_response", "id": "q1", "value": "Driver"}]


def test_free_text_answers_pass_through(tmp_path):
    """omp appends "Other (type your own)" to every question and takes the typed value back."""
    session = _session(tmp_path)

    asyncio.run(session.answer("q1", "Helix DSP Ultra S"))

    assert session.sent[0]["value"] == "Helix DSP Ultra S"


def test_interrupt_uses_the_command_omp_actually_has(tmp_path):
    """`interrupt`, `cancel` and `stop` all come back "Unknown command" — asked, not assumed."""
    session = _session(tmp_path)

    asyncio.run(session.interrupt())

    assert session.sent[0]["type"] == "abort"


# ---- process arguments -----------------------------------------------------


def test_xdev_is_turned_off_through_an_overlay_tcc_owns(tmp_path):
    """Without this TCC's MCP tools never enter the model's function list, and the user's own omp
    config is not TCC's to rewrite."""
    session = _session(tmp_path)

    argv = session._argv()
    overlay = argv[argv.index("--config") + 1]

    assert "xdev: false" in open(overlay).read()
    assert str(tmp_path) in overlay


def test_a_fresh_session_does_not_continue_a_previous_one(tmp_path):
    assert "--continue" not in OmpSession(project_dir=tmp_path)._argv()


def test_resuming_continues_the_projects_own_session(tmp_path):
    argv = OmpSession(project_dir=tmp_path, resume=True)._argv()

    assert "--continue" in argv
    assert str(tmp_path) in argv[argv.index("--session-dir") + 1]


def test_a_free_text_question_reaches_the_dialog(tmp_path):
    """No options means the composer is the answer, which it already knows how to be."""
    session = _session(tmp_path)

    events = session._handle(
        {"type": "extension_ui_request", "id": "q9", "method": "select",
         "title": "What is your car make/model?", "options": []}
    )

    assert len(events) == 1
    assert isinstance(events[0], Question)
    assert events[0].options == ()
    assert session.sent == []  # nothing answered on the agent's behalf


# ---- what goes through without asking --------------------------------------


def test_reading_does_not_need_permission(tmp_path):
    """`always-ask` otherwise puts a dialog in front of every file the skill opens — and the skill
    is built on opening files, so the Arbiter learns to click through, which is worse."""
    session = _session(tmp_path, allow=False)

    for tool in ("read", "glob", "grep"):
        asyncio.run(session._gate({**PERMISSION_FRAME, "title": f"Allow tool: {tool}"}))

    assert session.bridge.requests == []
    assert all(sent["value"] == "Approve" for sent in session.sent)


def test_a_read_only_command_does_not_need_permission(tmp_path):
    """One definition of read-only, shared with the SDK adapter: the same command is the same
    command whichever harness runs it."""
    session = _session(tmp_path, allow=False)

    asyncio.run(session._gate({**PERMISSION_FRAME,
                               "title": "Allow tool: bash\nCommand: ls -la process"}))

    assert session.bridge.requests == []
    assert session.sent[0]["value"] == "Approve"


def test_a_command_that_writes_still_asks(tmp_path):
    session = _session(tmp_path, allow=False)

    asyncio.run(session._gate({**PERMISSION_FRAME,
                               "title": "Allow tool: bash\nCommand: rm -rf process"}))

    assert session.bridge.requests[0].tool == "bash"
    assert session.sent[0]["value"] == "Deny"


def test_a_chained_command_asks_even_when_both_halves_look_safe(tmp_path):
    """A chain means the allowlist can no longer reason about what will run."""
    session = _session(tmp_path, allow=False)

    asyncio.run(session._gate({**PERMISSION_FRAME,
                               "title": "Allow tool: bash\nCommand: ls; rm -rf process"}))

    assert session.bridge.requests != []


def test_writing_and_evaluating_always_ask(tmp_path):
    """These can overwrite a measurement or a ledger — the evidence everything else rests on."""
    session = _session(tmp_path, allow=False)

    for tool in ("write", "edit", "eval"):
        asyncio.run(session._gate({**PERMISSION_FRAME, "title": f"Allow tool: {tool}"}))

    assert [r.tool for r in session.bridge.requests] == ["write", "edit", "eval"]


def test_every_frame_is_written_down(tmp_path):
    """Three hangs were diagnosed by guessing at what omp had sent, and each guess cost a session.
    The frames are the only place those are visible."""
    session = OmpSession(project_dir=tmp_path, bridge=RecordingBridge(True))

    session._log("in", {"type": "agent_end"})
    session._log("out", {"type": "prompt", "message": "hi"})

    lines = [json.loads(line) for line in session._log_path.read_text().splitlines()]
    assert [entry["dir"] for entry in lines] == ["in", "out"]
    assert lines[0]["frame"]["type"] == "agent_end"


def test_logging_never_breaks_the_session(tmp_path, monkeypatch):
    """A diagnostic that can take the session down is worse than no diagnostic."""
    session = OmpSession(project_dir=tmp_path, bridge=RecordingBridge(True))
    monkeypatch.setattr(
        type(session._log_path), "open", lambda *a, **kw: (_ for _ in ()).throw(OSError("full"))
    )

    session._log("in", {"type": "agent_end"})  # must not raise
