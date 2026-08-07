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


def test_the_session_runs_in_its_own_omp_profile(tmp_path):
    """Its own settings, sessions and caches, so a tuning session is not affected by what the user
    did to their own omp — and free, because the credential path is the environment.

    It does *not* isolate MCP servers: a first measurement said so and was wrong (a cold profile
    has not connected them yet). That is recorded in `_argv` rather than fixed, because omp 17.2.5
    has no switch for the `~/.claude.json` source."""
    argv = OmpSession(project_dir=tmp_path)._argv()

    assert argv[argv.index("--profile") + 1] == omp_session_module.OMP_PROFILE


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
