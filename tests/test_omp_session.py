"""The omp adapter: frame translation, the Arbiter gate, and the question channel.

Frames here are the ones omp actually emits — captured off `--mode rpc-ui` on the spike stand
before the adapter was written, not invented to match it. The subprocess itself is never started:
what is under test is the translation and the gating, and those are pure given a frame.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from concurrent.futures import Future

import pytest


from autosound_tcc.core.agent_events import Question, TextDelta, ToolCall, TurnEnd
from autosound_tcc.core.mcp_server import ConfirmRequest
from autosound_tcc.core import omp_session as omp_session_module
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


def test_turn_end_does_not_close_the_exchange_on_its_own(tmp_path):
    """A `turn` in omp is one round of the model, so a prompt answered with eight tool calls emits
    nine `turn_end`s. Ending on the first delivered a few process chips and then silence forever —
    measured in use before this was understood."""
    session = _session(tmp_path)

    assert session._handle({"type": "turn_end", "message": {}}) == []


def test_a_round_that_nothing_follows_is_the_end(tmp_path):
    """`agent_end` does not always arrive: omp keeps the agent alive between prompts, and a turn
    whose last act is a question to the human ends with the wire going quiet. Read back from omp's
    own session store, the hung turn was complete — tool returned, message finished, nothing
    after."""
    session = _session(tmp_path)

    session._handle({"type": "turn_end", "message": {}})

    assert session._round_ended_at > 0  # the grace period is running


def test_more_work_cancels_the_grace_period(tmp_path):
    """Otherwise a pause between two tool calls would be read as the end of the answer."""
    session = _session(tmp_path)
    session._handle({"type": "turn_end", "message": {}})

    session._handle({"type": "tool_execution_start", "toolName": "read"})

    assert session._round_ended_at == 0


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


# ---- what the permission asks about -----------------------------------------


def test_the_permission_names_the_effect_not_the_command(tmp_path):
    """"Allow bash: python3 rew_tool/apply.py --preset FULL ..." is not a question anyone can
    answer — it is a script that starts a Python that computes. What it writes is."""
    session = _session(tmp_path, allow=False)

    asyncio.run(session._gate({
        **PERMISSION_FRAME,
        "title": "Allow tool: bash\nCommand: python3 .claude/skills/x/rew_tool/apply.py --preset FULL",
    }))

    assert session.bridge.requests[0].tool == "effectLedger"
    # The command itself is still there to read, just not as the question.
    assert "apply.py" in session.bridge.requests[0].detail


def test_an_unknown_command_still_asks_by_tool_name(tmp_path):
    session = _session(tmp_path, allow=False)

    asyncio.run(session._gate({**PERMISSION_FRAME,
                               "title": "Allow tool: bash\nCommand: curl https://example.com | sh"}))

    assert session.bridge.requests[0].tool == "bash"


def test_foreign_mode_lets_the_skill_write_its_own_namespace(tmp_path):
    """The skill writing `process/` is the skill doing its job; asking about it teaches the
    Arbiter to click through the ones that matter."""
    session = OmpSession(project_dir=tmp_path, bridge=RecordingBridge(False),
                         gate=omp_session_module.GATE_FOREIGN)
    session.sent = []
    session._send = session.sent.append

    asyncio.run(session._gate({
        **PERMISSION_FRAME,
        "title": "Allow tool: bash\nCommand: python3 rew_tool/state/process.py ./process done lang ok",
    }))

    assert session.bridge.requests == []


def test_foreign_mode_still_asks_about_anything_else(tmp_path):
    session = OmpSession(project_dir=tmp_path, bridge=RecordingBridge(False),
                         gate=omp_session_module.GATE_FOREIGN)
    session.sent = []
    session._send = session.sent.append

    asyncio.run(session._gate({**PERMISSION_FRAME,
                               "title": "Allow tool: bash\nCommand: rm -rf ~/Documents/notes.md"}))

    assert session.bridge.requests != []


def test_the_default_asks_about_every_write(tmp_path):
    session = _session(tmp_path, allow=False)

    asyncio.run(session._gate({
        **PERMISSION_FRAME,
        "title": "Allow tool: bash\nCommand: python3 rew_tool/state/process.py ./process done lang ok",
    }))

    assert session.bridge.requests != []


EDITOR_FRAME = {
    "type": "extension_ui_request",
    "id": "e1",
    "method": "editor",
    "promptStyle": True,
    "title": "What car and DSP are you using?\n\n○ Helix (Recommended)\n    Sedan with Helix\n"
             "◉ Other (type your own)\n\nEnter your response:",
}


def test_a_free_text_editor_is_a_question(tmp_path):
    """omp sends this after "Other (type your own)" is chosen. Unrecognised, it rendered as a card
    with radio glyphs inside it and the turn sat there — read straight out of the frame log."""
    session = _session(tmp_path)

    events = session._handle(EDITOR_FRAME)

    assert len(events) == 1
    assert isinstance(events[0], Question)
    assert events[0].id == "e1"
    assert session.sent == []


def test_the_widget_omp_drew_is_not_part_of_the_question(tmp_path):
    """The options were already shown as buttons and the composer already says it is waiting."""
    session = _session(tmp_path)

    question = session._handle(EDITOR_FRAME)[0]

    assert question.question == "What car and DSP are you using?"
    assert "○" not in question.question
    assert "Enter your response" not in question.question


def test_an_editor_is_never_mistaken_for_a_permission(tmp_path):
    """It has no options, and option-less frames used to fall to the gate."""
    session = _session(tmp_path)

    session._handle({**EDITOR_FRAME, "title": "Allow tool: something\n\nEnter your response:"})

    assert session.bridge.requests == []


def test_clearing_a_widget_is_not_reported_as_activity(tmp_path):
    """A `setWidget` with no `widgetLines` is omp's *remove this widget* branch — read out of its
    own bridge, and the shape of all 8 in a real capture. Named on the activity line it announced
    work starting at the exact moment omp said there was none: "⟳ omp:autoresearch…" is where the
    belief that something was off researching came from."""
    session = _session(tmp_path)

    events = session._handle({"type": "extension_ui_request", "id": "w1",
                              "method": "setWidget", "widgetKey": "autoresearch"})

    assert events == []
    assert session.sent[0]["cancelled"] is True


def test_a_widget_that_actually_shows_something_is_named(tmp_path):
    """The other branch: static lines mean omp is displaying a panel of its own, and cancelling
    that silently is how "it went off somewhere" would really look."""
    session = _session(tmp_path)

    events = session._handle({"type": "extension_ui_request", "id": "w2", "method": "setWidget",
                              "widgetKey": "autoresearch", "widgetLines": ["running..."]})

    assert [e.name for e in events] == ["omp:autoresearch"]
    assert session.sent[0]["cancelled"] is True


def test_a_nameless_widget_is_still_just_cancelled(tmp_path):
    session = _session(tmp_path)

    assert session._handle({"type": "extension_ui_request", "id": "w2",
                            "method": "setTitle", "title": "omp"}) == []


def test_the_overlay_turns_off_ompsown_researcher(tmp_path):
    """A tuning session answers questions by measuring, not by reading the web — and the skill
    already has a Critic."""
    session = _session(tmp_path)

    overlay = open(session._argv()[session._argv().index("--config") + 1]).read()

    assert "web_search" in overlay and "enabled: false" in overlay


def test_a_tool_that_returned_stops_the_activity_line(tmp_path):
    """`tool_execution_end` was on the wire and dropped, so the last tool of a turn kept spinning
    for as long as the window was open and a stalled turn looked exactly like a busy one."""
    from autosound_tcc.core.agent_events import ToolEnd

    session = _session(tmp_path)

    events = session._handle({"type": "tool_execution_end", "toolName": "read"})

    assert events == [ToolEnd(name="read")]


# ---- what the model is allowed to see ---------------------------------------


def test_the_model_is_shown_one_skill_not_the_users_library(tmp_path):
    """Measured off omp's own request: 75 skills and 12.5 KB of other people's descriptions in
    every call — including a second `autosound-tuning` from `~/.claude/skills` that TCC does not
    control and that still has the unfixed `file:///skills/...` addressing. This is the omp half
    of the SDK adapter's `setting_sources=["project"]`."""
    session = _session(tmp_path)

    overlay = open(session._argv()[session._argv().index("--config") + 1]).read()

    assert "enableClaudeUser: false" in overlay
    assert "enableClaudeProject: true" in overlay  # the project's own link still counts
    assert 'includeSkills: ["autosound-tuning"]' in overlay


def test_the_session_runs_in_the_person_s_own_omp_profile(tmp_path):
    """Whatever works in the person's terminal works in TCC: the logins live in omp's profile, and
    TCC's own profile had none of them."""
    argv = OmpSession(project_dir=tmp_path)._argv()

    # The person's own profile since 2026-09-26 (tcc#56, finding 77): a `tcc` profile kept the
    # logins out — Opus 5 answered in the terminal and was «No API key found» in TCC.
    assert "--profile" not in argv


def test_a_project_with_no_skill_is_called_out_before_the_turn(tmp_path):
    """Without the skill a session does not fail, it improvises — which is worse. Seen whole: the
    model followed a dead `file:///skills/...` reference, hunted the disk with three globs and an
    eight-minute `grep`, then invented an intake of its own."""
    session = _session(tmp_path)

    warning = session.skill_warning()

    assert warning is not None and ".claude/skills/autosound-tuning" in warning


def test_a_project_with_the_skill_linked_says_nothing(tmp_path):
    link = tmp_path / ".claude" / "skills"
    link.mkdir(parents=True)
    (link / "autosound-tuning").mkdir()
    session = _session(tmp_path)

    assert session.skill_warning() is None


def test_a_google_model_with_no_key_is_flagged_before_the_turn(tmp_path, monkeypatch):
    """The failure is silent: without a key omp returns an empty answer and no error. A bundle
    started from the Finder inherits no shell environment, so "works in my terminal" proves
    nothing about the shipped app."""
    for name in omp_session_module._GOOGLE_KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    session = OmpSession(project_dir=tmp_path, model="gemini-3.1-pro-preview")

    warning = session.credential_warning()

    assert warning is not None and "GEMINI_API_KEY" in warning


def test_the_key_omp_actually_reads_counts(tmp_path, monkeypatch):
    """`GEMINI_API_KEY`, checked in omp's binary — not the `GOOGLE_GENERATIVE_AI_API_KEY` the
    OpenCode spike needed, which is a different harness's variable."""
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    session = OmpSession(project_dir=tmp_path, model="gemini-3.1-pro-preview")

    assert session.credential_warning() is None


def test_a_non_google_model_is_not_second_guessed(tmp_path, monkeypatch):
    """omp has its own broker for everything else; TCC does not audit it."""
    for name in omp_session_module._GOOGLE_KEY_VARS:
        monkeypatch.delenv(name, raising=False)

    assert OmpSession(project_dir=tmp_path, model="glm-4.7").credential_warning() is None


def test_chrome_after_the_last_round_does_not_reopen_the_turn(tmp_path):
    """A real turn ended with prose, `turn_end`, and 30 ms later a `setWidget` clearing omp's own
    dashboard. Under "anything that is not turn_end is work" that cancelled the grace period, and
    nothing ever came after it — the exchange stayed open for eight minutes on a finished turn."""
    session = _session(tmp_path)
    session._handle({"type": "turn_end", "message": {}})

    session._handle({"type": "extension_ui_request", "id": "w9", "method": "setWidget",
                     "widgetKey": "autoresearch"})

    assert session._round_ended_at > 0  # still counting down to the end


def test_a_frame_type_nobody_knows_does_not_reopen_the_turn_either(tmp_path):
    """The list is of activity, not of exceptions: an unknown frame that reopens a finished turn
    is a hang, and one that lets it close early costs 2.5s of true silence."""
    session = _session(tmp_path)
    session._handle({"type": "turn_end", "message": {}})

    session._handle({"type": "some_future_frame"})

    assert session._round_ended_at > 0


def test_real_work_still_cancels_the_grace_period(tmp_path):
    session = _session(tmp_path)
    session._handle({"type": "turn_end", "message": {}})

    session._handle({"type": "tool_execution_start", "toolName": "read"})

    assert session._round_ended_at == 0


def test_the_harness_offers_no_plan_of_its_own(tmp_path):
    """`todo` is omp's own checklist, and given a checklist to hold the model reached for it
    instead of the skill's plan — that run wrote **zero** journal events while looking organised
    in the transcript. Same model, same prompt, with `todo` gone: phase entered and eight steps
    added through `mcp__tcc_*`, nine journal events. The plan has one home."""
    argv = OmpSession(project_dir=tmp_path)._argv()

    enabled = argv[argv.index("--tools") + 1].split(",")

    assert "todo" not in enabled
    assert "task" not in enabled and "hub" not in enabled  # no unobserved sub-agents either
    assert {"read", "glob", "grep", "bash", "write", "edit", "ask"} <= set(enabled)


def test_auto_mode_on_omp_still_asks_about_what_cannot_be_undone(tmp_path):
    """`auto` was Allow before any look on omp, so a delete passed silently on a Gemini session
    while the menu's tooltip — and the SDK side — said it would ask (review of #115). The same
    narrow check now runs here; an ordinary command stays silent (the test below)."""
    session = OmpSession(project_dir=tmp_path, bridge=RecordingBridge(False),
                         gate=omp_session_module.GATE_AUTO)
    session.sent = []
    session._send = session.sent.append

    asyncio.run(session._gate({**PERMISSION_FRAME, "id": "f1",
                               "title": "Allow tool: bash\nCommand: rm -rf ~/"}))
    asyncio.run(session._gate({**PERMISSION_FRAME, "id": "f2",
                               "title": "Allow tool: bash\nCommand: ls -la"}))

    assert [(request.reason, request.detail) for request in session.bridge.requests] == [
        ("gateIrreversible", "rm -rf ~/")], "the same reason as the SDK side, then the command"
    assert [frame["value"] for frame in session.sent] == ["Deny", "Approve"]


def test_a_remembered_tool_outranks_the_auto_guard_on_omp_as_on_the_sdk_side(tmp_path):
    session = OmpSession(project_dir=tmp_path, bridge=RecordingBridge(False),
                         gate=omp_session_module.GATE_AUTO, always_allowed=frozenset({"bash"}))
    session.sent = []
    session._send = session.sent.append

    asyncio.run(session._gate({**PERMISSION_FRAME, "title": "Allow tool: bash\nCommand: rm -rf ~/"}))

    assert session.bridge.requests == []
    assert session.sent[0]["value"] == "Approve"


def test_auto_mode_stops_asking_about_the_harness(tmp_path):
    """The Arbiter's own choice: shell and file traffic runs without a dialog. Narrower than it
    sounds — TCC's tools raise their confirmations inside the tool, so a DSP or REW write still
    stops for a human."""
    session = OmpSession(project_dir=tmp_path, bridge=RecordingBridge(False),
                         gate=omp_session_module.GATE_AUTO)
    session.sent = []
    session._send = session.sent.append

    asyncio.run(session._gate({**PERMISSION_FRAME,
                               "title": "Allow tool: bash\nCommand: rm -rf process"}))

    assert session.bridge.requests == []
    assert session.sent[0]["value"] == "Approve"


def _never_ask_gate(tmp_path, command: str) -> tuple[OmpSession, list]:
    session = OmpSession(project_dir=tmp_path, bridge=RecordingBridge(False),
                         gate=omp_session_module.GATE_NEVER)
    session.sent = []
    session._send = session.sent.append

    async def run():
        await session._gate({**PERMISSION_FRAME, "title": f"Allow tool: bash\nCommand: {command}"})
        events = []
        while not session._events.empty():
            events.append(session._events.get_nowait())
        return events

    return session, asyncio.run(run())


def test_never_ask_approves_an_irreversible_command_and_says_so(tmp_path):
    """The fourth choice (tcc#115) asks about nothing — and what it let through that the narrow
    check would have stopped is a line in the dialog, the same as on the Agent SDK side."""
    from autosound_tcc.core.agent_events import Unasked

    session, events = _never_ask_gate(tmp_path, "rm -rf ~/")

    assert session.bridge.requests == []
    assert session.sent[0]["value"] == "Approve"
    assert events == [Unasked("rm -rf ~/")]


def test_never_ask_says_nothing_about_an_ordinary_command(tmp_path):
    session, events = _never_ask_gate(tmp_path, "ls -la")

    assert session.sent[0]["value"] == "Approve"
    assert events == []


def test_a_remembered_tool_stops_asking_without_turning_the_gate_off(tmp_path):
    session = OmpSession(project_dir=tmp_path, bridge=RecordingBridge(False),
                         always_allowed=frozenset({"write"}))
    session.sent = []
    session._send = session.sent.append

    asyncio.run(session._gate({**PERMISSION_FRAME, "title": "Allow tool: write"}))
    asyncio.run(session._gate({**PERMISSION_FRAME, "title": "Allow tool: edit"}))

    assert [r.tool for r in session.bridge.requests] == ["edit"]  # only the one not remembered


# ---- effort (2026-08-07) ----------------------------------------------------


def test_the_thinking_level_is_stated_on_the_command_line(tmp_path):
    """omp is the metered route — the one the route prefixes exist to make visible — so how hard
    it thinks is how much it costs. Accepting the broker's default would put that number outside
    the Arbiter's view, which is the same failure the prefixes were built for."""
    argv = OmpSession(project_dir=tmp_path, effort="max")._argv()

    assert "--thinking" in argv
    assert argv[argv.index("--thinking") + 1] == "max"


def test_auto_is_not_a_level_tcc_will_pass_to_a_metered_route(tmp_path):
    """omp offers `auto` — "decide for yourself how much to spend". On a metered route with nobody
    watching that is the one setting worth refusing; it falls back to the stated default."""
    argv = OmpSession(project_dir=tmp_path, effort="auto")._argv()

    assert argv[argv.index("--thinking") + 1] == "xhigh"


# ---- per-turn signal delivery (F-009) ---------------------------------------


def _one_turn(session, text):
    """Drive `_prompt` through one whole turn: the queue already holds its end."""

    async def run():
        session._events.put_nowait(TurnEnd())
        return [event async for event in session._prompt(text)]

    return asyncio.run(run())


def test_a_prompt_carries_unacked_signals_into_the_turn(tmp_path):
    """F-009's acceptance on the omp route: a turn in which the model calls no tcc tool at all
    still learns what the Arbiter asked for. Same mechanism as `TuningSession.send` -- the two
    front-ends must not differ on it."""
    from autosound_tcc.core.signal_bus import CHANNEL_TOGGLE, SignalBus

    session = _session(tmp_path)
    session.bus = SignalBus(tmp_path)
    signal = session.bus.push(CHANNEL_TOGGLE, group="rear", channel="r-L", on=False)

    _one_turn(session, "what next?")

    message = session.sent[0]["message"]
    assert message.endswith("what next?")
    assert CHANNEL_TOGGLE in message and signal.id in message


def test_a_quiet_queue_costs_the_prompt_nothing(tmp_path):
    from autosound_tcc.core.signal_bus import SignalBus

    session = _session(tmp_path)
    session.bus = SignalBus(tmp_path)

    _one_turn(session, "what next?")

    assert session.sent[0]["message"] == "what next?"


def test_signals_delivered_but_not_acked_survive_an_omp_turn(tmp_path):
    """The end-of-turn restore on the omp route: read, not acked, so pending again -- the next
    prompt's preamble raises it instead of it dying "delivered"."""
    from autosound_tcc.core.signal_bus import NOT_VISIBLE, SignalBus

    session = _session(tmp_path)
    session.bus = SignalBus(tmp_path)
    signal = session.bus.push(NOT_VISIBLE, note="band 3 missing")
    session.bus.deliver()  # the model read it mid-turn and acked nothing

    _one_turn(session, "ok")

    # `wait` only sees *pending* signals, so returning here proves the restore.
    assert [s.id for s in session.bus.wait(timeout=0.05)] == [signal.id]


def test_the_project_language_reaches_omp_as_an_appended_rule(tmp_path):
    """tcc#56, finding 53: the language went to this constructor as a keyword it did not take, and
    every omp start died on it. Now it is taken, and reaches the model the way the SDK route's
    does — the same rule, appended to omp's system prompt. From a FILE, not the text itself: a long
    argument through a Windows `.cmd` shim is what broke the reviewer CLIs (skill #60)."""
    from pathlib import Path

    argv = OmpSession(project_dir=tmp_path, language="uk")._argv()
    rule = Path(argv[argv.index("--append-system-prompt") + 1]).read_text(encoding="utf-8")
    assert "Ukrainian" in rule and "EVERY word you emit" in rule


def test_a_refused_prompt_ends_the_turn(tmp_path):
    """Finding 77 (tcc#56): «omp refused `prompt`: No API key found for kimi-code …», then «120s with
    no output» and a turn that never ended. A prompt omp refused starts no model call; nothing is
    coming for that turn."""
    session = OmpSession(project_dir=tmp_path)
    events = session._handle({"type": "response", "command": "prompt", "success": False,
                              "error": "No API key found for kimi-code."})
    assert any(isinstance(e, TurnEnd) for e in events)

    other = session._handle({"type": "response", "command": "negotiate_protocol",
                             "success": False, "error": "Unsupported RPC protocol version"})
    assert not any(isinstance(e, TurnEnd) for e in other), "only the prompt's refusal ends a turn"


def test_omp_is_spawned_with_room_for_the_frames_it_announces(tmp_path, monkeypatch):
    """tcc#72, finding 80: every omp turn with a built-in tool hung. asyncio's default line limit is
    64 KiB; omp announces frames up to 1 MiB (`maxFrameBytes`, and 64 MiB reassembled), a `read`'s
    frames passed the limit, `readline` raised, and the reader task died without a word — the
    turn then waited forever behind «120s with no output»."""
    import asyncio as aio

    seen = {}

    async def fake_spawn(*argv, **kwargs):
        seen.update(kwargs)
        raise OSError("not starting omp in a test")

    monkeypatch.setattr(omp_session_module.asyncio, "create_subprocess_exec", fake_spawn)
    session = OmpSession(project_dir=tmp_path)
    try:
        aio.run(session._spawn())
    except OSError:
        pass
    assert seen.get("limit", 0) >= omp_session_module.FRAME_LIMIT_BYTES >= 64 * 1024 * 1024


def test_a_frame_the_reader_cannot_read_ends_the_turn_out_loud(tmp_path):
    """Defence behind the limit: a reader that fails says so and ends the turn, instead of
    leaving it hanging with nothing in the log."""
    import asyncio as aio
    from types import SimpleNamespace

    from autosound_tcc.core.agent_events import Notice

    session = OmpSession(project_dir=tmp_path)

    async def run():
        reader = aio.StreamReader(limit=1024)
        reader.feed_data(b'{"type": "message_update", "pad": "' + b"x" * 5000 + b'"}\n')
        reader.feed_eof()
        session._proc = SimpleNamespace(stdout=reader)
        await session._read_frames()
        events = []
        while not session._events.empty():
            events.append(session._events.get_nowait())
        return events

    events = aio.run(run())
    assert any(isinstance(e, Notice) and "could not read" in e.text for e in events)
    assert events[-1] is None, "the drain is told nothing more is coming"


def _read(session, data: bytes) -> list:
    """What the reader queues for `data` followed by EOF."""
    import asyncio as aio
    from types import SimpleNamespace

    async def run():
        reader = aio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()
        session._proc = SimpleNamespace(stdout=reader)
        await session._read_frames()
        events = []
        while not session._events.empty():
            events.append(session._events.get_nowait())
        return events

    return aio.run(run())


@pytest.mark.parametrize("line", [b"42", b'"a string"', b"null"])
def test_a_frame_that_is_not_an_object_is_skipped_not_fatal(tmp_path, caplog, line):
    """`42` killed the reader with AttributeError, outside its except: nothing was logged and the
    turn waited forever, omp alive (the branch review)."""
    session = OmpSession(project_dir=tmp_path)

    events = _read(session, line + b"\n")

    assert session._ended_by_reader == "", "the reader went on to the end of the stream"
    assert events == [None] and "not an object" in caplog.text


@pytest.mark.parametrize("frame", [
    b'{"type": "tool_execution_start", "toolName": "bash", "args": 5}',
    b'{"type": "message_update", "assistantMessageEvent": "text"}',
])
def test_a_frame_the_handler_cannot_read_ends_the_turn_out_loud(tmp_path, caplog, frame):
    from autosound_tcc.core.agent_events import Notice

    session = OmpSession(project_dir=tmp_path)

    events = _read(session, frame + b"\n")

    assert any(isinstance(e, Notice) and "could not read" in e.text for e in events)
    assert events[-1] is None and session._ended_by_reader
    assert "could not handle" in caplog.text


def test_omp_waits_for_a_tool_as_long_as_a_review_may_take(tmp_path, monkeypatch):
    """Finding 97 (tcc#85): the session's `call_critic` was cut ~30 s in and the session read it
    as «збій транспорту MCP» while the reviewer still worked — omp aborts an MCP request after
    `OMP_MCP_TIMEOUT_MS`, 30 000 ms by default. A review is allowed `critic.DEFAULT_TIMEOUT_S`."""
    import asyncio as aio

    from autosound_tcc.core import critic

    seen = {}

    async def fake_spawn(*argv, **kwargs):
        seen.update(kwargs)
        raise OSError("not starting omp in a test")

    monkeypatch.setattr(omp_session_module.asyncio, "create_subprocess_exec", fake_spawn)
    try:
        aio.run(OmpSession(project_dir=tmp_path)._spawn())
    except OSError:
        pass
    assert int(seen["env"]["OMP_MCP_TIMEOUT_MS"]) > critic.DEFAULT_TIMEOUT_S * 1000


@pytest.mark.skipif(sys.platform.startswith("win"), reason="a POSIX script stands in for omp")
def test_a_newer_omp_that_dropped_a_tool_is_started_again_with_the_tools_it_names(tmp_path,
                                                                                   monkeypatch):
    """Finding 102 (tcc#87): omp 17.4.0 has no `inspect_image`, refused TCC's `--tools` list —
    «Unknown tool in --tools: inspect_image. Valid tools: read, write, …» — and no omp session
    started on that machine. omp names what it takes; TCC starts it again with those."""
    import asyncio as aio
    import textwrap

    bindir = tmp_path / "bin"
    bindir.mkdir()
    omp = bindir / "omp"
    omp.write_text(textwrap.dedent('''\
        #!/usr/bin/env python3
        import sys, time
        tools = sys.argv[sys.argv.index("--tools") + 1].split(",")
        if "inspect_image" in tools:
            sys.stderr.write("CliUsageError: Unknown tool in --tools: inspect_image. Valid tools: "
                             "read, write, edit, glob, grep, bash, ask, ast_edit, goal.\\n")
            sys.exit(1)
        print('{"type": "ready"}', flush=True)
        time.sleep(0.2)
        '''), encoding="utf-8")
    omp.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ.get('PATH', '')}")
    session = OmpSession(project_dir=tmp_path)

    async def start_and_close():
        try:
            await session._start_process()
        finally:
            await session.close()

    aio.run(start_and_close())

    assert session._saw_ready
    assert "inspect_image" not in session._tools
    assert set(session._tools) == {"read", "write", "edit", "glob", "grep", "bash", "ask"}


def _fake_omp(tmp_path, monkeypatch, refusal: str) -> None:
    """A POSIX stand-in for omp on PATH: it refuses `inspect_image` with `refusal` on stderr, and
    with any other list reports `ready` and answers one `prompt` with a line of text."""
    import textwrap

    bindir = tmp_path / "bin"
    bindir.mkdir()
    omp = bindir / "omp"
    omp.write_text(textwrap.dedent(f'''\
        #!/usr/bin/env python3
        import json, sys
        tools = sys.argv[sys.argv.index("--tools") + 1].split(",")
        if "inspect_image" in tools:
            sys.stderr.write({refusal!r})
            sys.exit(1)
        print('{{"type": "ready"}}', flush=True)
        for line in sys.stdin:
            if json.loads(line).get("type") == "prompt":
                print(json.dumps({{"type": "message_update", "assistantMessageEvent":
                                  {{"type": "text_delta", "delta": "hello from omp"}}}}), flush=True)
                print('{{"type": "agent_end"}}', flush=True)
        '''), encoding="utf-8")
    omp.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ.get('PATH', '')}")


_OMP_17_REFUSAL = ("CliUsageError: Unknown tool in --tools: inspect_image. Valid tools: read, write, "
                   "edit, glob, grep, bash, ask, ast_edit, goal.\n")

#: omp 18.3.5's refusal, as it prints it: a source excerpt, the reason, then five stack frames.
_OMP_18_REFUSAL = (
    "14766 |   if (o.length === 0)\n"
    "14767 |   throw new Yp(`Unknown tool${o.length === 1 ? \"\" : \"s\"} in --tools: ...`);\n"
    "                ^\n"
    "CliUsageError: Unknown tool in --tools: inspect_image. Valid tools: read, write, edit, glob, "
    "grep, bash, ask, ast_edit, goal, init_experiment, run_experiment, log_experiment, update_notes.\n"
    "      at dot (/$bunfs/root/omp-darwin-arm64:14767:9)\n"
    "      at U9 (/$bunfs/root/omp-darwin-arm64:640398:12)\n"
    "      at async run (/$bunfs/root/omp-darwin-arm64:640622:14)\n"
    "      at async iJr (/$bunfs/root/omp-darwin-arm64:1849:16)\n"
    "      at async Ipo (/$bunfs/root/omp-darwin-arm64:643770:12)\n"
)


async def _first_turn(session: OmpSession) -> list:
    events = []
    try:
        async for event in session.start():
            events.append(event)
    finally:
        await session.close()
    return events


@pytest.mark.skipif(sys.platform.startswith("win"), reason="a POSIX script stands in for omp")
def test_the_first_turn_after_the_tools_retry_shows_what_omp_says(tmp_path, monkeypatch):
    """Finding 106 (tcc#97): after the retry of tcc#87 the dialog sat on «Запускаю OMP · …» while
    the second omp worked. The refused omp's reader put its end-marker in the event queue, the
    retry kept the queue, and the opening turn read that marker first and ended with nothing."""
    import asyncio as aio

    _fake_omp(tmp_path, monkeypatch, _OMP_17_REFUSAL)
    project = tmp_path / "car"
    project.mkdir()

    events = aio.run(_first_turn(OmpSession(project_dir=project)))

    said = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert "hello from omp" in said
    assert any(isinstance(e, TurnEnd) for e in events)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="a POSIX script stands in for omp")
def test_omp_18s_refusal_behind_a_stack_is_still_read_and_retried(tmp_path, monkeypatch):
    """Finding 109: omp 18 prints a stack after «Unknown tool in --tools: …», and TCC read only the
    last five stderr lines — five frames. The refusal was never seen, no retry, and the Arbiter got
    «omp exited before reporting ready» and the frames."""
    import asyncio as aio

    _fake_omp(tmp_path, monkeypatch, _OMP_18_REFUSAL)
    session = OmpSession(project_dir=tmp_path)

    async def start_and_close():
        try:
            await session._start_process()
        finally:
            await session.close()

    aio.run(start_and_close())

    assert session._saw_ready
    assert "inspect_image" not in session._tools


def test_a_failure_names_omps_reason_not_its_stack_frames(tmp_path):
    """Finding 109: the message was TCC's line plus five `at …` frames; omp's own reason, the one
    line worth reading, was above them."""
    session = OmpSession(project_dir=tmp_path)

    async def feed():
        reader = asyncio.StreamReader()
        reader.feed_data(("SomeError: the reason\n" + "      at frame (x:1:1)\n" * 6).encode())
        reader.feed_eof()
        from types import SimpleNamespace
        session._proc = SimpleNamespace(stderr=reader)
        await session._drain_stderr()

    asyncio.run(feed())

    assert "SomeError: the reason" in session._why("omp exited before reporting ready")


def test_a_failed_confirmation_in_the_omp_session_is_logged_and_denies(tmp_path, caplog):
    """F3e: omp's gate read a failed confirmation as the Arbiter's «no», with nothing logged."""
    import logging

    from autosound_tcc.core import app_log

    session = _session(tmp_path, allow=True)

    def broken(request):
        raise RuntimeError("boom")

    session.bridge.request_confirmation = broken
    with caplog.at_level(logging.WARNING, logger=app_log.LOGGER_NAME):
        asyncio.run(session._gate(PERMISSION_FRAME))

    assert session.sent == [{"type": "extension_ui_response", "id": "f1", "value": "Deny"}]
    assert any("boom" in r.getMessage() for r in caplog.records)


def test_the_turn_after_omp_died_says_so_instead_of_waiting(tmp_path):
    """F3a: the reader saw EOF, and the next prompt went to the dead process and waited on a queue
    nothing would fill, saying only «no output» every two minutes."""
    from types import SimpleNamespace

    from autosound_tcc.core.agent_events import Notice

    session = _session(tmp_path)

    async def run():
        reader = asyncio.StreamReader()
        reader.feed_eof()  # omp is gone
        session._proc = SimpleNamespace(stdout=reader, stdin=None, returncode=3)
        await session._read_frames()
        while not session._events.empty():  # the turn that was running took its None
            session._events.get_nowait()
        session._stderr_tail = ["FatalError: the reason"]
        turn = session._prompt("next?")
        return await asyncio.wait_for(turn.__anext__(), timeout=2.0)

    first = asyncio.run(run())
    assert isinstance(first, Notice)
    assert "no output" not in first.text, "the silence notice is not the answer"
    assert "omp has stopped" in first.text
    assert "FatalError: the reason" in first.text and "exit code 3" in first.text, \
        "omp's last words and its exit code are the part a bug report needs"
    assert session.sent == [], "nothing is written to a process that is gone"


def _oversized(reader):
    reader.feed_data(b'{"type": "message_update", "pad": "' + b"x" * 5000 + b'"}\n')
    reader.feed_eof()


def test_a_reader_that_stopped_between_turns_is_said_by_the_next_turn(tmp_path, caplog):
    """The reader's own sentence was left in the queue: the next prompt said «omp has stopped»
    about an omp that was alive, blocked on its full pipe (the G1 review)."""
    from types import SimpleNamespace

    from autosound_tcc.core.agent_events import Notice

    session = _session(tmp_path)

    async def turn():
        return [event async for event in session._prompt("next?")]

    async def run():
        reader = asyncio.StreamReader(limit=1024)
        _oversized(reader)
        session._proc = SimpleNamespace(stdout=reader, stdin=None)
        await session._read_frames()  # no turn running
        first = await asyncio.wait_for(turn(), timeout=2.0)
        second = await asyncio.wait_for(turn(), timeout=2.0)
        return first, second

    first, second = asyncio.run(run())
    assert [type(e) for e in first] == [Notice] and "could not read" in first[0].text
    assert len(second) == 1 and "TCC stopped reading omp" in second[0].text
    assert "omp has stopped" not in first[0].text + second[0].text
    assert "TCC stopped reading omp" in caplog.text
    assert session.sent == []


def test_a_reader_that_stopped_mid_turn_says_it_once(tmp_path):
    from types import SimpleNamespace

    from autosound_tcc.core.agent_events import Notice

    session = _session(tmp_path)

    async def collect():
        return [event async for event in session._prompt("go")]

    async def run():
        reader = asyncio.StreamReader(limit=1024)
        session._proc = SimpleNamespace(stdout=reader, stdin=None)
        turn = asyncio.ensure_future(collect())
        await asyncio.sleep(0.05)  # the turn has sent its prompt and waits on the queue
        _oversized(reader)
        await session._read_frames()
        return await asyncio.wait_for(turn, timeout=2.0)

    events = asyncio.run(run())
    notices = [e for e in events if isinstance(e, Notice)]
    assert len(notices) == 1 and "could not read" in notices[0].text, notices


def test_a_close_is_not_a_death(tmp_path):
    """A Stop or a model switch cancels the reader: no «omp has stopped», no end marker (the
    spec's risk: a wrong Notice ends a healthy turn)."""
    from types import SimpleNamespace

    session = _session(tmp_path)

    async def run():
        reader = asyncio.StreamReader()  # omp alive, saying nothing
        session._proc = SimpleNamespace(stdout=reader, stdin=None)
        reading = asyncio.ensure_future(session._read_frames())
        await asyncio.sleep(0)
        reading.cancel()
        try:
            await reading
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    assert not session._ended.is_set() and session._events.empty()


def test_omp_ending_mid_turn_ends_the_turn_out_loud(tmp_path):
    from autosound_tcc.core.agent_events import Notice

    session = _session(tmp_path)

    async def collect(turn):
        return [event async for event in turn]

    async def run():
        turn = session._prompt("go")
        session._events.put_nowait(None)  # the reader's EOF, mid-turn
        return await asyncio.wait_for(collect(turn), timeout=2.0)

    events = asyncio.run(run())
    assert events and isinstance(events[-1], Notice) and "omp has stopped" in events[-1].text
