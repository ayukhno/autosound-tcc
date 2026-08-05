"""What a tuning conversation emits, said once, so more than one harness can say it.

TCC drives the skill through an agent harness, and which harness is not one decision but two:
Claude runs through the Agent SDK against the user's own CLI, everything else runs through `omp`
(`spike/HANDOFF.md` §5-ter). Both had to arrive somewhere the dialog panel could render, and until
now that somewhere was the SDK's own message objects — `dialog_panel._on_chunk` duck-typed them,
reading `.event` for a stream delta and `.content[].name` for a tool call. That works for exactly
one harness and silently for none of the others.

So the panel is given a vocabulary instead of a vendor. Seven events, chosen because both harnesses
actually produce them and the panel actually renders them:

    TextDelta          prose arriving a piece at a time -> grows the live bubble
    ToolCall           the agent used a tool -> a one-line process chip
    ToolEnd            that tool returned -> the chip stops moving
    Question           a structured question for the Arbiter, and the turn is blocked on it
    QuestionWithdrawn  the harness took a question back -> the card goes
    Notice             the adapter speaking about the harness, not the model speaking
    TurnEnd            the turn finished, carrying the harness's session id for resume

`Question` has no Agent SDK equivalent today; omp raises it (`ask`) and OpenCode raises it
(`question.asked`), and in both the turn **blocks** until the host answers. It is in this vocabulary
rather than bolted onto the omp adapter because a window that does not render it looks like a window
that hung — which is what a live run looked like before the channel was found.

Deliberately absent: token counts, costs, model names, raw provider payloads. Everything the process
needs to survive the session is in `process/journal.jsonl`, written by the skill; a transcript is a
view, not a record (`spike/HANDOFF.md` §2.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class TextDelta:
    """A piece of the assistant's prose. Consecutive deltas belong to one bubble."""

    text: str


@dataclass(frozen=True)
class ToolCall:
    """The agent called a tool. Rendered as a process event, never as a wall of JSON.

    `name` is the harness's name for it and they differ by harness -- `mcp__tcc__get_tcc_state`
    under the SDK, `mcp__tcc_get_tcc_state` under omp. Presentation strips the prefix; nothing
    downstream should match on the whole string.
    """

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolEnd:
    """That tool returned. The activity line stops moving.

    The line's whole claim is "the thing is still working" -- a static line says a tool ran, a
    moving one says it is still running, and that difference is the only reason the line exists.
    Without this event the dots never stopped, so the last tool of a turn appeared to be running
    for as long as the window was open, and a stalled turn looked exactly like a busy one.

    Emitted by the omp adapter (`tool_execution_end`); the SDK adapter has no equivalent yet, so
    the panel treats its absence as "still running", which is what it assumed before.
    """

    name: str = ""


@dataclass(frozen=True)
class QuestionOption:
    label: str
    description: str = ""


@dataclass(frozen=True)
class Question:
    """A structured question for the Arbiter. The turn is parked until `answer` is delivered.

    One question per event even when the harness sends several together: the panel renders them as
    cards and the host answers each, so a batch is a batch of these.
    """

    id: str
    question: str
    options: tuple[QuestionOption, ...] = ()
    header: str = ""
    multi: bool = False


@dataclass(frozen=True)
class Notice:
    """Something the adapter itself has to say, and it is not the model saying it.

    "120s with no output" and "omp refused `negotiate_protocol`" went out as `TextDelta`, so they
    arrived in the transcript under the model's own name and byline -- a sentence about the harness
    attributed to Gemini, in the same bubble style as its analysis. The distinction matters most
    exactly when things are going wrong, which is the only time these are emitted.
    """

    text: str


@dataclass(frozen=True)
class QuestionWithdrawn:
    """A question the harness has taken back, so the card must go.

    omp does this whenever it moves past a frame it raised -- an aborted turn withdraws the
    editor it opened, and the frame log shows it as `method: "cancel"` carrying the id of what it
    is withdrawing. Without this the panel keeps a card whose buttons answer a frame nobody is
    listening to, which is the same confusion as a missing question, only quieter.
    """

    id: str


@dataclass(frozen=True)
class TurnEnd:
    """The turn is over. `session_id` is what a later launch resumes, when the harness has one."""

    session_id: Optional[str] = None


AgentEvent = TextDelta | ToolCall | ToolEnd | Question | QuestionWithdrawn | Notice | TurnEnd


@runtime_checkable
class AgentSession(Protocol):
    """What a tuning-conversation adapter has to provide. Two exist: the Agent SDK one
    (`core.tuning_session`) and, for everything that is not Claude, omp.

    Deliberately not the same as `ui.tcc.agent_worker.AgentSession`, which is looser on purpose:
    the worker also drives the DSP-profile onboarding session, which yields plain strings and has
    no question channel or interrupt. That Protocol says what the *thread* needs; this one says
    what a tuning adapter owes the dialog.
    """

    async def start(self, prompt: Optional[str] = None) -> AsyncIterator[AgentEvent]: ...

    async def send(self, text: str) -> AsyncIterator[AgentEvent]: ...

    async def answer(self, question_id: str, value: str) -> None:
        """Unblock a `Question`. Harnesses without a question channel never raise one."""

    async def interrupt(self) -> None: ...

    async def close(self) -> None: ...
