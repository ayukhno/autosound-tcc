"""TCC as an MCP server — the substrate both AI front-ends stand on.

Inverting the obvious design (TCC drives an agent) turned out to matter for more than taste:

* **Terms.** Anthropic does not allow a third-party product to *offer* claude.ai login or rate
  limits (Agent SDK overview, "Set your API key"). A server the user's own already-authenticated
  CLI connects to sidesteps that entirely — TCC authenticates to nothing and routes nobody's
  traffic. It is the same relationship VS Code or iTerm has with a CLI running inside it.
* **Provider independence.** `claude`, `gemini` and `codex` all speak MCP, so one server serves
  all three — `TCC-TZ.md §4a` option C, arrived at for free.
* **One implementation.** The in-process Agent SDK session (`core.tuning_session`) connects to
  this same server as an ordinary client, so both front-ends share every tool below.

Transport is streamable-HTTP on loopback rather than stdio: TCC is a long-lived GUI process that
is already running when the agent starts, so the agent must dial *in*; a stdio server would have
to be spawned by the client, which would give a second, headless TCC with no window.

**No mock data is exposed.** The measurement panel still renders `ui/tcc/mock_data`, and a tool
serving that to a model would invite EQ proposals computed from fabricated sweeps. Measurements
land here only once the skill emits them for real (SCR-004/SCR-008).

## D-6 audit of this surface (2026-07-31)

The rule: TCC never writes DATA — not state, not project, not profile. A tool either reads, or
carries an INTENT, or is a SIGNAL. Every tool below was checked against "does this write?":

| Tool | Writes | Verdict |
|---|---|---|
| `get_tcc_state`, `get_ledger`, `get_capability_checklist` | — | read |
| `get_pending_signals`, `wait_for_signal` | `.tcc/` bus | TCC's own namespace; the payload is user intent |
| `ack_signals` | `.tcc/` bus log | TCC's own namespace; the record of what the agent did with that intent |
| `propose_change` | — | intent, put on screen for the Arbiter |
| `copy_helix_eq` | clipboard | hand-off to a human, gated |
| `write_rew_filters` | REW's model | an instrument, not project data; gated |
| `call_critic` | `.tcc/` call log | TCC's own namespace |
| `report_phase` | — | **converted** — read-back + refresh signal |
| the four onboarding tools | — | **converted** — intent handed to the skill's writer |

The onboarding tools were the last thing here that authored project data, and only because the
skill had no writer to route an interview through (`dsp_profile.py` could `validate`, `diff` and
`find-bundled`, nothing else). SCR-025 added one; they now pass each confirmed value to it via
`core/profile_writer.py`. The draft, the validation and the refusals all live on the skill's side
— including `finalize` declining an incomplete profile, which this server reports verbatim rather
than deciding for itself.

Nothing on this surface writes project data any more.
"""

from __future__ import annotations

import asyncio
import functools
import json
import secrets
import socket
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

from mcp.server.fastmcp import FastMCP

from autosound_tcc.core import (
    agent_session,
    app_log,
    car_library,
    config,
    critic,
    model_choices,
    process_writer,
    profile_writer,
    project_settings,
    signal_bus,
    vendor_loader,
)
from autosound_tcc.core.session_registry import SessionRegistry
from autosound_tcc.core.signal_bus import SignalBus

SERVER_NAME = "tcc"
DEFAULT_PORT = 8765
_TOKEN_HEADER = "x-tcc-token"
# How long an Arbiter confirmation stays open before the tool call is denied. Long enough that the
# user can walk to the car and back, short enough that a forgotten dialog doesn't pin an MCP call
# open forever.
CONFIRM_TIMEOUT_S = 600.0

# Rides along with every non-empty signal delivery (`get_pending_signals`, `wait_for_signal`).
# In the payload, not only in the tools' docstrings, because a docstring is read once at tool
# discovery and this has to be in front of the model at the moment it holds unhandled signals.
_ACK_REMINDER = (
    "Handle each signal, then close it: ack_signals(ids=[...], outcome=applied|refused|"
    "superseded). `refused` needs a note saying why. Un-acked signals are raised again every "
    "turn."
)


#: How much of a tool's arguments and of its answer goes into the log. Enough to tell one call
#: from the next — which field was saved, whether the writer refused — and not the whole payload:
#: `get_pending_signals` can answer with kilobytes, and a log nobody can page through is the same
#: as no log (report on the run of 2026-09-01: 88 lines, 34 of them Qt warnings, and a completed
#: interview that left no trace at all).
_LOG_VALUE_CHARS = 200


def _brief(value: Any) -> str:
    """One line, bounded, and it says when it cut."""
    text = " ".join(str(value).split())
    return text if len(text) <= _LOG_VALUE_CHARS else text[:_LOG_VALUE_CHARS] + "… (cut)"


def _logged(fn):
    """A tool that says, at INFO, that it was called and what it answered.

    One wrapper rather than a log line inside each of the twenty-eight tools: a line per tool is
    twenty-eight chances to forget one, and the one that gets forgotten is the one whose absence
    is later reported as "the log shows nothing" (`SKL-009`).

    `functools.wraps` is what keeps this invisible to FastMCP: the schema it builds comes from
    `inspect.signature` and `__doc__`, and both follow `__wrapped__`.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        log = app_log.logger()
        shown = kwargs if kwargs else args
        log.info("mcp %s(%s)", fn.__name__, _brief(shown) if shown else "")
        try:
            result = await fn(*args, **kwargs)
        except Exception:
            # `exception` and re-raise: the model still gets the failure it would have got, and
            # the file now says which tool produced it.
            log.exception("mcp %s raised", fn.__name__)
            raise
        log.info("mcp %s -> %s", fn.__name__, _brief(result))
        return result

    return wrapper


def _vendor_of(model: Optional[str]) -> str:
    """The vendor a model name implies, for the journal's `reviewer` field.

    A guess by design, and a cheap one: the reviewer script reports the model it used and nothing
    about who makes it. Wrong is better than absent here -- the field exists so a reader can see
    that the Critic was a DIFFERENT vendor from the Generator, which is the whole anti-anchoring
    argument, and "?" answers that question for nobody.
    """
    name = (model or "").lower()
    for needle, vendor in (
        ("gemini", "google"), ("gpt", "openai"), ("o1", "openai"), ("claude", "anthropic"),
        ("grok", "xai"), ("llama", "meta"), ("mistral", "mistral"), ("deepseek", "deepseek"),
    ):
        if needle in name:
            return vendor
    return "unknown"


def _reviewer_state(project_dir: Path) -> dict[str, Any]:
    """What TCC already knows about the reviewer channel, so intake stops asking about it.

    The Arbiter picks a Critic in the footer and it is stored per project. The skill, having no
    way to see that, opens every intake with "how would you like to set up the Reviewer
    (Critic-Advisor) channel?" -- about a channel that is configured and one `call_critic` away.
    A GUI that knows something and asks anyway is just a chat window with more buttons.

    `reachable` is the honest half, and since SCR-033 it is a real question rather than a vendor
    check: the reviewer script speaks three transports, so this asks whether THIS machine has the
    chosen vendor's key or CLI. False means clipboard-only — a designed fallback, not a failure.
    """
    key = project_settings.get(config.tcc_dir(project_dir), "critic", "") or ""
    if not key:
        return {
            "configured": False,
            "how": "ask the Arbiter to pick one in TCC's footer",
        }
    known = model_choices.choices([]) + model_choices.critic_choices([])
    harness, _, model = key.partition(":")
    # The catalogue only lists the models the Arbiter marked as theirs, so a perfectly valid
    # choice is often not in it. Judge the key itself rather than reporting "unreachable" for a
    # reviewer that works.
    resolved = model_choices.resolve(known, key)
    choice = resolved.choice or model_choices.Choice(
        harness=harness or "omp", model=model or key, label=key, provider=""
    )
    return {
        "configured": True,
        "model": choice.model,
        # What the Arbiter picked, versus what this machine will actually run. Empty unless the
        # install has an alias — and when it does, the model must not be able to report the
        # project's stored name as if it were the one that answered.
        "substituted": resolved.note,
        "label": choice.label,
        "reachable": model_choices.critic_reaches(choice),
        "how": "call the `call_critic` tool" if model_choices.critic_reaches(choice)
               else "call `call_critic`; it will hand you a clipboard package for this model",
        # Reported once and asked back: the model read this, then put "confirm that this is your
        # independent reviewer?" to the Arbiter. Naming a field `configured` says what the value
        # is; it does not say who decided it. This does.
        "decided_by": "the Arbiter, in TCC's own UI — settled, not a suggestion to confirm",
    }


def configured_critic_model(project_dir: Path) -> str:
    """The reviewer this project's footer is set to, in the CLI's own vocabulary — or "".

    Through `model_choices.resolve`, so a machine-level alias is honoured here exactly as it is in
    the picker; two answers to "which model" is how they came to disagree in the first place.
    """
    key = project_settings.get(config.tcc_dir(project_dir), "critic", "") or ""
    if not key:
        return ""
    resolved = model_choices.resolve(model_choices.critic_choices([]), key)
    if resolved.choice is not None:
        return resolved.choice.model
    return resolved.key.partition(":")[2] or resolved.key


def clipboard_reason(project_dir: Path) -> str:
    """Why a reviewer call would come back as a package rather than as a critique.

    TCC knows this without asking the script, and until now it did not say: the tool answered
    `mode: clipboard` with an empty `detail`, twice in a row, and the model reported it as "the
    critic returned clipboard, no review" with nothing to act on (user, 2026-08-23). A designed
    fallback that cannot explain itself is indistinguishable from a fault.
    """
    key = project_settings.get(config.tcc_dir(project_dir), "critic", "") or ""
    if not key:
        return "no reviewer is configured in TCC's footer, so there is nothing to call"
    harness, _, model = key.partition(":")
    resolved = model_choices.resolve(model_choices.critic_choices([]), key)
    choice = resolved.choice or model_choices.Choice(
        harness=harness or "omp", model=model or key, label=key, provider=""
    )
    if model_choices.critic_reaches(choice):
        return ""  # it can be reached; whatever happened is the script's to explain
    vendor = model_choices.vendor_of(choice)
    if not vendor:
        return (
            f"the reviewer script calls Google, Anthropic or OpenAI models; {choice.model!r} is "
            f"none of those, so no transport here can run it. Pick a reviewer from one of those "
            f"vendors in TCC's footer, or keep this one and review by hand from the package"
        )
    return (
        f"{choice.model!r} is a {vendor} model and this machine has neither that vendor's API key "
        f"nor its CLI, so the package is the only way through"
    )


@dataclass(frozen=True)
class ConfirmRequest:
    """A mutation waiting on the Arbiter's button. This *is* the 🟡→🟢 attest step."""

    tool: str
    title: str
    detail: str
    payload: dict[str, Any] = field(default_factory=dict)


class UiBridge(Protocol):
    """Everything the tools need from the GUI, expressed without importing Qt.

    Keeping this a protocol is what lets the server run headless (CLI spike, pytest) against
    `HeadlessBridge` while the real app supplies a Qt implementation.
    """

    def snapshot(self) -> dict[str, Any]:
        """Current UI-visible state: preset, ledger version, selection, edit mode."""

    def request_confirmation(self, request: ConfirmRequest) -> "Future[bool]":
        """Show the request to the Arbiter; resolve True to allow, False to deny."""

    def copy_to_clipboard(self, text: str) -> None: ...

    def show_proposal(self, proposal: dict[str, Any]) -> None: ...

    def show_critique(self, critique: dict[str, Any]) -> None: ...

    def show_curves(self, request: dict[str, Any]) -> None:
        """Open the curve panel over named REW measurements, with the model's own reading marked.

        The one channel that carries a disagreement about a NUMBER in both directions, without an
        image anywhere in it: the model says where it read the answer, the Arbiter drags a marker
        to where they read it, and what comes back is a value rather than a picture of one.
        """

    def notify_profile_ready(self) -> None:
        """A DSP profile was just written (onboarding via terminal, `finalize_profile` below) --
        the GUI should reload it. Fires only from the terminal path; the in-app onboarding chat
        already restarts into a fresh window off its own `profile_saved` signal."""

    def refresh_from_disk(self) -> None:
        """The skill changed something on disk — re-read the project (D-6's signal direction).

        Not the same as `notify_profile_ready`, which is about one file appearing for the first
        time: this is the ordinary "the tune moved" refresh, and it is a MESSAGE, not data.
        """


class HeadlessBridge:
    """No GUI: every mutation is denied, reads answer from disk.

    Denying rather than allowing is the whole point — a headless run (tests, the CLI spike) has
    nobody to attest a change, and "no Arbiter present" must never mean "no gate".
    """

    def __init__(self, project_dir: Optional[Path] = None) -> None:
        self._project_dir = project_dir or config.project_dir()

    def snapshot(self) -> dict[str, Any]:
        return {"mode": "headless", "project_dir": str(self._project_dir)}

    def request_confirmation(self, request: ConfirmRequest) -> "Future[bool]":
        future: "Future[bool]" = Future()
        future.set_result(False)
        return future

    def copy_to_clipboard(self, text: str) -> None:  # pragma: no cover - nothing to copy into
        pass

    def show_proposal(self, proposal: dict[str, Any]) -> None:
        pass

    def notify_profile_ready(self) -> None:
        pass

    def refresh_from_disk(self) -> None:
        pass

    def show_critique(self, critique: dict[str, Any]) -> None:
        pass

    def show_curves(self, request: dict[str, Any]) -> None:
        pass


def build_server(
    project_dir: Path,
    bridge: UiBridge,
    bus: SignalBus,
    registry: SessionRegistry,
) -> FastMCP:
    """One FastMCP instance bound by closure to one project — no path ever comes from the model.

    Same containment rule as `core.agent_session.build_tools`: the tools reach exactly the project
    the caller chose, and a model that asks for another path has no way to express it.
    """
    mcp = FastMCP(
        SERVER_NAME,
        instructions=(
            "Tuning Command Center — the GUI the human tuner (the Arbiter) is looking at. "
            "Read its state instead of asking them to describe it, and check for user signals "
            "before proposing a change. Every mutation here is shown to the Arbiter and takes "
            "effect only if they confirm. Nothing in this server writes to the DSP."
        ),
    )

    def tool(**kwargs):
        """`mcp.tool`, with `_logged` between the function and the registry.

        Every `@mcp.tool()` below is spelled `@tool()` so that adding a tool cannot mean
        forgetting to log it — the only door into the registry runs through here.
        """

        def register(fn):
            return mcp.tool(**kwargs)(_logged(fn))

        return register

    def _load_process_state() -> tuple[Optional[dict[str, Any]], Optional[str]]:
        """The skill's process state, read through the skill's own module (`state/process.py`).

        The one authority on where the tune stands (D-6): TCC reads this, never writes it. Returns
        `(state, None)` or `(None, reason)` — a project with no process yet reads as an empty
        state, which is not an error.
        """
        try:
            process = vendor_loader.load_process()
        except vendor_loader.VendorNotInitializedError as exc:
            return None, str(exc)
        return process.Process(str(project_dir / "process")).load(), None

    async def _confirm(request: ConfirmRequest) -> bool:
        try:
            return await asyncio.wait_for(
                asyncio.wrap_future(bridge.request_confirmation(request)),
                timeout=CONFIRM_TIMEOUT_S,
            )
        except (asyncio.TimeoutError, Exception):
            return False

    # ---- reads -------------------------------------------------------------

    @tool()
    async def get_tcc_state() -> str:
        """What the Arbiter currently has on screen: preset, ledger version, selection, edit mode.

        Call this before proposing anything, so a proposal refers to what they are actually
        looking at rather than to state you inferred earlier in the conversation.
        """
        process_state, error = _load_process_state()
        ui = bridge.snapshot()
        open_signals = bus.pending_count
        state = {
            "project_dir": str(project_dir),
            "ui": ui,
            # Top-level, not left inside `ui`, because it is not a screen detail: it is the answer
            # to the intake's first question. The Arbiter picked it in the app before the session
            # started, and every project file the skill writes follows it.
            "language": ui.get("ui_language"),
            # The phase comes from the skill's own file, not from this server's bookkeeping: two
            # places answering "which phase" is how they drift apart (#10, D-6).
            "current_phase": (process_state or {}).get("active_phase"),
            "process_state_error": error,
            "sessions": registry.load().get("phases", {}),
            "pending_signals": open_signals,
            # How hard this session was asked to think, so a record can say it. A journal entry
            # that names the model but not its effort does not describe what ran -- the same model
            # at `high` and at `max` is two different reviewers of its own work. Fixed for the
            # session: both adapters take it when the session is built, so it cannot have changed
            # since this session started, whatever the picker shows now.
            "effort": model_choices.resolve_effort(
                project_settings.get(config.tcc_dir(project_dir), "effort", "")
            ),
            # The Arbiter already chose a reviewer in the footer, and without this the skill
            # cannot see it: intake asks "how would you like to set up the Reviewer channel?"
            # about a channel that is configured and one tool call away. Anything TCC already
            # knows must not be asked again -- that is the difference between a GUI and a chat.
            "reviewer": _reviewer_state(project_dir),
            # Said in the payload rather than in a system prompt, because it has to reach both
            # front-ends and only one of them has a system prompt TCC controls.
            "_this_is_settled": (
                "Everything above is TCC's own state: what the Arbiter configured in the UI and "
                "what is on their screen right now. Act on it. Do not ask them to confirm a value "
                "they set themselves — ask only about what is missing or contradicts the disk."
            ),
        }
        if open_signals:
            # A bare number is how four `channel_toggle` signals sat unread for seven minutes
            # (F-009): technically reported, practically invisible. Open requests get a sentence.
            state["_signals_waiting"] = (
                f"{open_signals} un-acknowledged user signal(s) are waiting. They are direct "
                "requests from the Arbiter: call get_pending_signals, handle each, and close it "
                "with ack_signals before anything else."
            )
        return json.dumps(state, ensure_ascii=False, indent=2)

    @tool()
    async def get_pending_signals() -> str:
        """Every user signal raised in the UI and not yet acknowledged. Reading is not handling.

        Signals are things the Arbiter did that you would otherwise not know about: switching on
        param-edit mode, flagging that something you claimed to have changed is not visible, or
        moving attention to another channel. Check this at the start of a turn and before any
        proposal; a `not_visible` signal means re-verify against disk, not restate your claim.

        This call used to empty the queue, and a signal read by a turn that did nothing with it
        was gone (F-009). Now a signal stays open until you close it with `ack_signals`, and an
        open signal is raised again at the start of every following turn -- handling it and
        acking it is also how you stop hearing about it.

        A `channel_toggle` signal (`{group, channel, on}`) is the Arbiter asking for a channel to
        be switched on or off in the tree. TCC does not write the ledger, so nothing has changed
        yet: record it the way any other agreed change is recorded (`apply.propose`), and say so.
        Turning one **on** usually means more than a flag -- a physical output needs its virtual
        counterpart and its place in the glossary -- so treat it as a request to make that channel
        real, not as a single field edit.
        """
        signals = [s.as_dict() for s in bus.deliver()]
        payload: dict[str, Any] = {"signals": signals, "count": len(signals)}
        if signals:
            payload["_ack"] = _ACK_REMINDER
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @tool()
    async def ack_signals(ids: list[str], outcome: str, note: str = "") -> str:
        """Close user signals: say what happened to what the Arbiter asked for.

        `outcome` is one of `applied` (carried out -- recorded, proposed, executed), `refused`
        (deliberately not done; `note` must say why, and the refusal belongs in your answer to
        the Arbiter too), or `superseded` (a later signal or event made it moot -- name it in
        `note`). One outcome per call: split a batch that ended differently into several calls.

        This is the other half of the audit log: every raise in `.tcc/signals.jsonl` eventually
        meets its `signal_acked` line, which is what makes "what did the Arbiter ask and what
        came of it" answerable after a restart. Ids you invent or ack twice come back as
        `unknown_ids` rather than as an error -- a second ack arriving late is not worth ending
        a turn over.
        """
        if outcome not in signal_bus.ACK_OUTCOMES:
            return json.dumps(
                {"error": f"outcome must be one of {sorted(signal_bus.ACK_OUTCOMES)}"}
            )
        if outcome == signal_bus.ACK_REFUSED and not note.strip():
            return json.dumps(
                {"error": "a refusal needs a note saying why -- the Arbiter asked for this"}
            )
        acked, unknown = bus.ack(ids, outcome, note=note.strip())
        result: dict[str, Any] = {"acked": acked, "outcome": outcome}
        if unknown:
            result["unknown_ids"] = unknown
        return json.dumps(result, ensure_ascii=False, indent=2)

    async def _heartbeat(progress: float, total: float) -> None:
        """Keep a long park alive. A call that goes silent for the client's idle window is
        aborted rather than awaited, so the progress ping is what makes waiting legal.

        Best-effort by design: there is no request context when the tool is driven directly
        (headless spike, tests), and losing the heartbeat there costs nothing because no idle
        timer is running either."""
        try:
            await mcp.get_context().report_progress(progress=progress, total=total)
        except Exception:
            pass

    @tool()
    async def wait_for_signal(timeout_seconds: float = 900.0) -> str:
        """Park until the Arbiter does something in the UI, then return those signals.

        Use this when you have nothing to do until the human acts — after handing them a
        measurement task or a settings sheet to enter. Returns an empty list if nothing happens
        before the timeout. What comes back is delivered, not handled: close each signal with
        `ack_signals`, exactly as with `get_pending_signals`.
        """
        deadline = min(max(timeout_seconds, 1.0), 3600.0)
        waited = 0.0
        slice_s = 5.0
        while waited < deadline:
            signals = await asyncio.to_thread(bus.wait, min(slice_s, deadline - waited))
            if signals:
                return json.dumps(
                    {
                        "signals": [s.as_dict() for s in signals],
                        "count": len(signals),
                        "_ack": _ACK_REMINDER,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            waited += slice_s
            await _heartbeat(waited, deadline)
        return json.dumps({"signals": [], "count": 0, "timed_out": True})

    @tool()
    async def get_ledger(preset: str, version: str = "") -> str:
        """Read a DSP-state ledger snapshot (`v_NNN.json`) for one preset; blank version = HEAD.

        This is the same versioned snapshot the skill's `apply.propose` writes, read through the
        skill's own `PresetHistory` — not a TCC-side reinterpretation of it.
        """
        try:
            vstate = vendor_loader.load_dsp_state()
        except vendor_loader.VendorNotInitializedError as exc:
            return json.dumps({"error": str(exc)})
        history = vstate.PresetHistory(str(config.state_root()), preset,
                                       project_dir=str(project_dir))
        raw = history.load(version or None)
        return json.dumps(raw, ensure_ascii=False, indent=2)

    # ---- onboarding (DSP-profile capture) -----------------------------------
    #
    # The in-app onboarding chat (ProfileInterviewDialog) drives the SAME interview through the
    # Claude Agent SDK's own in-process tool server (agent_session.build_tools) instead of these --
    # that one is scoped to one vendor/model at construction time, since TCC itself supplies them.
    # These exist so an EXTERNAL CLI (gemini, codex, claude -- "Open Terminal", provider-agnostic
    # by construction, see terminal_launcher.py) can run the identical interview against a brand
    # new project: there's no system_prompt= channel for an arbitrary external agent, so these tool
    # DESCRIPTIONS are the only instructions it gets -- keep them in sync with
    # agent_session's own prompt if that ever changes.
    #
    # Neither path writes the file itself any more (D-6): both hand the confirmed value to the
    # skill's `dsp_profile.py`, which owns the draft, the validation and the schema stamp. No
    # Arbiter gate here -- these touch neither the DSP nor REW, and the gate that matters is the
    # skill's own refusal to finalize an incomplete profile.
    @tool()
    async def get_capability_checklist() -> str:
        """The fixed DSP capability-checklist questions to ask the human about (project-intake.md
        §4). Ask closed questions with concrete options where you can, 2-3 per turn -- never dump
        the whole remaining list into one message, even when several are still open."""
        return json.dumps(profile_writer.capability_checklist(), ensure_ascii=False)

    @tool()
    async def check_existing_profile(vendor: str, model: str) -> str:
        """Call this FIRST, before asking the human anything. Starts (or resumes) this project's
        interview draft and checks the bundled reference library for an EXACT vendor+model match --
        never treat a different model's profile (even a platform sibling's) as fact for this one.
        If it returns a draft with answers or an exact bundled match, don't re-ask about anything
        already confirmed -- call get_capability_checklist and ask only about what's still open,
        2-3 questions per turn (see get_capability_checklist's own note).

        Resuming is real: the draft lives on disk, so an interview interrupted days ago comes back
        with its answers. `project_profile` and `bundled_exact_match` are both UNWRAPPED (no
        top-level `dsp_profile` key) -- `project_profile` IS the object `save_profile_field`'s
        `path` resolves against, so never prefix a path with `dsp_profile.`.
        """
        try:
            current = profile_writer.start(project_dir, vendor, model)
            bundled = profile_writer.find_bundled(
                vendor, model, config.bundled_profiles_dir()
            )
        except profile_writer.ProfileWriterError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({
            "project_profile": current.get("draft", {}),
            "open_questions": current.get("open_questions", []),
            "bundled_exact_match": bundled,
        }, ensure_ascii=False)

    @tool()
    async def check_existing_car(
        make: str, model: str, generation: str = "", body: str = ""
    ) -> str:
        """Call this as soon as you know the car, BEFORE planning an intake from scratch. The
        cabin twin of check_existing_profile: has this body been described before, and have we
        built on it?

        Four parts identify a cabin: `make`, `model` (the nameplate, e.g. "Passat"), `generation`
        (the model run, e.g. "B8") and `body` ("sedan" / "wagon" / "hatchback"). DO NOT ask for
        the year to decide this and never match on it -- the generation IS the span of years whose
        acoustics count as the same, so two builds of one generation and body are one cabin
        whether 2017 or 2018, while the same year in another shell is another cabin. Ask the year
        only as a description of this particular car.

        Three answers come back and they are three, not two:
        * `bundled_exact_match` -- the library's page for EXACTLY this cabin, or null. Null is a
          real answer: nobody has described it, so the intake starts clean. A near miss is never
          reported: a platform sibling is a different car and merely naming one does the damage.
        * `prior_projects` -- builds WE have done on this same body, each with how many flaw-map
          rows it holds and which captures they were read off. Put this in front of the person as
          a question ("there is prior material for this cabin, this much of it -- carry it as
          hypotheses?"), never as a decision you take quietly. Those captures live in THAT
          project, so anything carried travels as a hypothesis, never as fact.
        * `unknown` -- projects that could not say what body they are, because nobody recorded
          one. SHOW THIS SEPARATELY. A project that did not record its body is not a project on
          another body, and reporting it as "none" is how material goes missing in silence.
        """
        return json.dumps(
            car_library.look_up(make, model, generation, body), ensure_ascii=False
        )

    @tool()
    async def save_car(
        make: str, model: str, generation: str = "", body: str = "", year: Any = None
    ) -> str:
        """Record the car in project.json as FOUR parts, as soon as they are confirmed.

        `make`, `model` (nameplate), `generation` (model run), `body` (sedan / wagon / hatchback).
        `year` is optional and describes this one car; it classifies nothing.

        Record the body even when it feels obvious. Without it this project answers "no body
        recorded" forever -- and then check_existing_car cannot tell it from a wagon, so neither
        this build nor any later one can be matched against the cabin library or against the
        earlier builds. That is a silent loss: nothing breaks today, and the material is simply
        not there tomorrow.
        """
        try:
            car = car_library.record(
                config.project_dir(), make, model, generation, body, year
            )
        except Exception as exc:  # noqa: BLE001 — the writer's refusal is an answer
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
        return json.dumps({"recorded": True, "car": car}, ensure_ascii=False)

    # The one tool whose instructions have to be COMPUTED — the field vocabulary comes off the
    # skill's own writer — and, until 2026-09-01, the one tool that reached the model with nothing
    # at all. An f-string under a `def` is not a docstring: Python keeps only a plain literal
    # there, so `save_profile_field.__doc__` was None and FastMCP registered an empty description.
    # Measured on the built server: every other tool 122–1351 characters, this one **0**.
    #
    # What the model therefore never saw, on the interview reported in SKL-009: "one field per
    # call, as soon as it's confirmed — don't batch everything to the end", the exact shape of a
    # `groups` entry, and the vocabulary itself. That run saved four fields in eight seconds at
    # the end of a half-hour interview and finalized a profile full of nulls. The instruction
    # against precisely that was in this file the whole time and never left it.
    #
    # Passed as `description=` rather than written under the `def`, because that is the only way
    # to hand FastMCP a string that had to be built.
    save_field_doc = (
        "Save one confirmed field into the in-progress profile draft (call "
        "check_existing_profile first). One field per call, as soon as it's confirmed -- don't "
        "batch everything to the end. Each call lands on disk, so an interrupted interview keeps "
        "everything answered so far.\n\n"
        "`path` is a dotted path relative to `project_profile` as returned by "
        "check_existing_profile -- e.g. 'dsp_processing_rate_hz' or 'groups.0.fields'. `groups` "
        'is a flat array, each entry EXACTLY {"id": "<snake_case_id>", "label": "<Human Label>", '
        '"fields": [<tokens>]} -- `fields` must be a flat array of STRING TOKENS drawn ONLY from '
        "this vocabulary, nothing else:\n"
        + json.dumps(profile_writer.field_vocabulary())
        + "\nA capability that doesn't fit this vocabulary belongs in `_open_questions`, not a "
        "made-up field name."
    )

    @tool(description=save_field_doc)
    async def save_profile_field(path: str, value: Any) -> str:
        """One confirmed field into the draft. What the MODEL is told is `save_field_doc` above —
        this line is for whoever reads the file."""
        if not profile_writer.has_draft(project_dir):
            return json.dumps({"error": "call check_existing_profile first"})
        try:
            return json.dumps(profile_writer.set_field(project_dir, path, value),
                               ensure_ascii=False)
        except profile_writer.ProfileWriterError as exc:
            return json.dumps({"saved": False, "error": str(exc)})

    @tool()
    async def reset_profile_field(path: str) -> str:
        """Delete a field from the draft (by dotted path) so it can be re-saved from scratch --
        recovery if a previous save_profile_field produced the wrong shape (e.g. a list written as
        a string), not part of the normal interview flow."""
        if not profile_writer.has_draft(project_dir):
            return json.dumps({"error": "call check_existing_profile first"})
        try:
            return json.dumps(profile_writer.reset_field(project_dir, path), ensure_ascii=False)
        except profile_writer.ProfileWriterError as exc:
            return json.dumps({"reset": False, "error": str(exc)})

    @tool()
    async def finalize_profile() -> str:
        """Validate the draft and write `dsp_profile.json`. Call this when the interview is done or
        the human says they're done -- do not just say so in text, call the tool.

        The skill's own writer decides: if it refuses, the reason comes back here and the draft is
        untouched, so fix that one field and call again rather than starting over.
        """
        if not profile_writer.has_draft(project_dir):
            return json.dumps({"error": "call check_existing_profile first"})
        try:
            return json.dumps({"saved_to": str(profile_writer.finalize(project_dir))},
                               ensure_ascii=False)
        except profile_writer.ProfileWriterError as exc:
            return json.dumps({"saved": False, "error": str(exc)})

    # ---- process record (the skill's writer; not gated -- recording is not a change) ----
    #
    # These exist because `report_phase` records nothing and never did: an agent that wanted to
    # write the move had to find `state/process.py` on disk and shell out to it, and whether it
    # managed to was a property of the model, not of the method. The gates stay where the schema
    # is owned -- `finish_step` without evidence is refused by the skill and the refusal is
    # returned verbatim.

    def _record(call, *args, **kwargs) -> str:
        try:
            line = call(project_dir, *args, **kwargs)
        except process_writer.ProcessWriterError as exc:
            return json.dumps({"recorded": False, "error": str(exc)}, ensure_ascii=False)
        bridge.refresh_from_disk()
        state, _ = _load_process_state()
        return json.dumps({"recorded": True, "said": line,
                           "active_phase": (state or {}).get("active_phase")},
                          ensure_ascii=False)

    @tool()
    async def enter_phase(phase: str) -> str:
        """Make a phase current (−1…5) and record it. Phases are the skill's fixed skeleton --
        entering one instantiates its template steps; you do not invent phases."""
        return await asyncio.to_thread(_record, process_writer.enter_phase, phase)

    @tool()
    async def add_step(step_id: str, name: str, situational: bool = False) -> str:
        """Add a plan step. `situational=True` records it as this car's own insert rather than one
        instantiated from the phase template -- the distinction is what makes a plan readable
        later."""
        return await asyncio.to_thread(_record, process_writer.add_step, step_id, name, situational)

    @tool()
    async def start_step(step_id: str) -> str:
        """Begin, or re-begin, a step. Re-beginning is attempt N+1 -- a redo is recorded next to the
        first try, never on top of it."""
        return await asyncio.to_thread(_record, process_writer.start_step, step_id)

    @tool()
    async def finish_step(step_id: str, evidence: list[str]) -> str:
        """Close a step. `evidence` is REQUIRED, and at least one item must RESOLVE rather than
        describe: a REW capture name in the grammar (`tw-L_1 (rta)` -- the method suffix is what
        makes it a capture), a ledger version that exists on disk (`v_003`), or a project file that
        exists (`autosound_context.md`). Prose may ride along with one of those; prose alone is
        refused. The skill checks this, not TCC, and a refusal comes back in the skill's own
        wording -- write the artefact, then close the step against it, rather than retrying the
        same call."""
        return await asyncio.to_thread(_record, process_writer.finish_step, step_id, evidence)

    @tool()
    async def skip_step(step_id: str, superseded_by: str = "") -> str:
        """Supersede a step. It stays visible in the plan -- steps are never deleted, and what
        replaced this one is worth naming."""
        return await asyncio.to_thread(_record, process_writer.skip_step, step_id, superseded_by)

    @tool()
    async def block_step(step_id: str, reason: str) -> str:
        """Mark a step blocked and say what blocks it -- a gate waiting on the human, a measurement
        that cannot be taken yet."""
        return await asyncio.to_thread(_record, process_writer.block_step, step_id, reason)

    @tool()
    async def record_decision(
        question: str, answer: str, step: str = "", invalidates: str = ""
    ) -> str:
        """Record what the Arbiter ruled — the question as put, the answer as given (SCR-030).

        Their half of the conversation is in no machine file otherwise, so a constraint they set is
        invisible to the next session unless somebody re-reads it out of the transcript. Call this
        BEFORE acting on a ruling that constrains a later phase. `invalidates` names what the
        ruling supersedes (channels, captures) when it supersedes anything."""
        return await asyncio.to_thread(
            _record, process_writer.record_decision, question, answer, step, invalidates
        )

    @tool()
    async def check_captures(titles: list[str] = []) -> str:
        """Check the open round's captures against REW and record the verdict (SCR-040).

        Arithmetic, not judgement: does REW hold each measurement, is it in the band asked for, is
        the level a signal rather than silence or a loopback. Do NOT read frequency-response arrays
        to answer this yourself — this computes it, records it against REW's own `uuid`, and the
        step's gate reads what it recorded.

        A step that asked for captures will not close until they pass. `titles` defaults to
        everything the round expects."""
        return await asyncio.to_thread(_record, process_writer.check_captures, titles or None)

    @tool()
    async def start_capture(version: str, expected: list[str], step: str = "") -> str:
        """Open a capture round before measuring: the ledger version being captured at, and the
        titles the phase asks for (SCR-034).

        A round, not a version. The version names the config the measurements were taken under and
        cannot tell two passes at the same config apart -- and the round is what makes a finished
        pass survive REW being closed, since otherwise its status lives only in REW's own list of
        open measurements.

        `step` binds the round to the plan step it satisfies, which is what lets that step's gate
        refuse to close while a capture it asked for is unusable (SCR-040)."""
        return await asyncio.to_thread(
            _record, process_writer.start_capture, version, expected, step
        )

    @tool()
    async def record_capture(title: str) -> str:
        """A measurement came back, by its REW title. One that was not on the round's list is
        recorded as unplanned rather than refused -- the derivation can only say what SHOULD have
        been taken, so "this came back and nobody asked for it" has nowhere else to live."""
        return await asyncio.to_thread(_record, process_writer.record_capture, title)

    @tool()
    async def skip_capture(title: str, reason: str) -> str:
        """A capture deliberately NOT taken, and why. The reason is required: skipped and
        not-yet-taken render identically without it, and the next session proposes it again."""
        return await asyncio.to_thread(_record, process_writer.skip_capture, title, reason)

    @tool()
    async def close_capture(reason: str = "") -> str:
        """Close the open capture round. Whatever is neither taken nor skipped is recorded as
        outstanding rather than quietly dropped."""
        return await asyncio.to_thread(_record, process_writer.close_capture, reason)

    # ---- writes (every one gated on the Arbiter) ---------------------------

    @tool()
    async def propose_change(
        channel: str, param: str, from_value: str, to_value: str, rationale: str
    ) -> str:
        """Put a proposed DSP change on screen as a card for the Arbiter to read.

        Has no effect on anything — TCC never writes to the DSP. The Arbiter enters accepted
        values into their own DSP software; this only makes the proposal legible next to the
        state it refers to.
        """
        proposal = {
            "channel": channel,
            "param": param,
            "from": from_value,
            "to": to_value,
            "rationale": rationale,
        }
        bridge.show_proposal(proposal)
        return json.dumps({"shown": True, "proposal": proposal}, ensure_ascii=False)

    @tool()
    async def write_rew_filters(measurement: str, filters: list[dict]) -> str:
        """Write a filter set into REW's own model for `measurement` (by name). Needs confirmation.

        This touches REW, never the DSP: it is the equivalent of the Arbiter typing the filters
        into REW's EQ window by hand, so they can see the predicted result before deciding.

        Each entry: `index` (1-based slot), `type` (`PK`/`LS`/`HS`/`None`/...), `enabled`, and for
        a peaking filter `frequency`, `q`, and **`gaindB`**. The gain key really is `gaindB` --
        REW accepts an entry using `gain` with a 200 and stores the filter at 0 dB, so a cut
        written that way silently does nothing. Replaces the whole set, so send every slot you
        want kept; clear one with `{"index": N, "type": "None", "enabled": true}`.
        """
        allowed = await _confirm(
            ConfirmRequest(
                tool="write_rew_filters",
                title=f"Записати {len(filters)} фільтр(и) у REW",
                detail=f"Замір: {measurement}",
                payload={"measurement": measurement, "filters": filters},
            )
        )
        if not allowed:
            return json.dumps({"applied": False, "reason": "Arbiter denied or timed out"})
        try:
            rew_api = vendor_loader.load_rew_api()
        except vendor_loader.VendorNotInitializedError as exc:
            return json.dumps({"applied": False, "error": str(exc)})
        mid = rew_api.find_measurement_id(measurement)
        if mid is None:
            return json.dumps({"applied": False, "error": f"no REW measurement named {measurement!r}"})
        rew_api.set_filters(mid, filters)
        return json.dumps({"applied": True, "measurement": measurement, "count": len(filters)})

    @tool()
    async def copy_helix_eq(text: str, note: str = "") -> str:
        """Put a DSP-format EQ block on the Arbiter's clipboard to paste into their DSP software.

        The hand-off point between advice and action: TCC produces the text, a human pastes it.
        Needs confirmation because it overwrites whatever they had on the clipboard.
        """
        allowed = await _confirm(
            ConfirmRequest(
                tool="copy_helix_eq",
                title="Скопіювати EQ у буфер обміну",
                detail=note or f"{len(text.splitlines())} рядк(ів)",
                payload={"preview": text[:400]},
            )
        )
        if not allowed:
            return json.dumps({"copied": False, "reason": "Arbiter denied or timed out"})
        bridge.copy_to_clipboard(text)
        return json.dumps({"copied": True, "chars": len(text)})

    @tool()
    async def show_curves(
        titles: list[str], markers: list[float] | None = None,
        kind: str = "impulse", note: str = "",
    ) -> str:
        """Put a measurement on screen with YOUR reading marked, and ask the Arbiter for theirs.

        Use this the moment a number is in dispute — an IR onset, where a joint sums, which peak is
        the arrival. Do not ask for a screenshot: a picture is an image of an opinion, it cannot be
        computed on, and pushing one back through this transport has ended a session before.

        `titles` are REW measurement names (`w-L_01 (sw)`), one or two — a disagreement is nearly
        always about a pair. `markers` is where YOU read the answer, in the plot's own units
        (milliseconds for `impulse`, Hz for `fr`); the Arbiter's marker starts on yours, so any
        distance between them afterwards is deliberate. `note` says what you are asking them to
        look at.

        Returns as soon as the panel is open. The Arbiter's reading arrives as an ordinary message
        from them — they see it and can edit it first, which is the same rule every other statement
        of theirs follows. Do not wait for it in a loop; finish your turn.
        """
        request = {
            "titles": [str(t) for t in (titles or []) if str(t).strip()],
            "markers": [float(m) for m in (markers or [])],
            "kind": kind if kind in ("impulse", "fr") else "impulse",
            "note": note,
        }
        if not request["titles"]:
            return json.dumps({"shown": False, "reason": "no measurement titles given"})
        bridge.show_curves(request)
        return json.dumps({
            "shown": True,
            "titles": request["titles"],
            "markers": request["markers"],
            "next": "the Arbiter's reading will arrive as a message; end your turn and wait for it",
        })

    @tool()
    async def call_critic(package: str, trace_path: str = "", model: str = "") -> str:
        """Send a proposal package to the Critic (a different vendor's model) and return its reply.

        The reviewer is stateless by design — it re-reads state from disk on every call — which is
        what makes it a drift-watchdog and not a second agent. Cadence is **one call per round**:
        package the whole batch (a crossover strategy, a round's EQ plan, a phase-gate verdict),
        not one call per parameter.

        `package` is the §3 package markdown itself, or a path to an existing package file.

        Three outcomes, and the middle one is not a failure: `answered` carries the critique;
        `clipboard` means no API or CLI was reachable so the package is on the Arbiter's clipboard
        for them to paste into any web chat and bring the reply back by hand; `error` explains why
        nothing ran. Never present `clipboard` as a critique — there isn't one yet.
        """
        # The Arbiter's pick is the default. Without this the call went out with NO model, the
        # reviewer script used its own built-in, and TCC's picker steered nothing at all — the
        # session's own routing test caught it: "Підключення до API (google, gemini-3.6-flash-high)"
        # while the UI showed `gemini-3.1-pro-high` (2026-08-12). The substitution happened BEFORE
        # any fallback; there was nothing to fall back from.
        result = await asyncio.to_thread(
            critic.run,
            package,
            project_dir=project_dir,
            trace_path=trace_path or None,
            model=model or configured_critic_model(project_dir) or None,
        )
        critic.log_call(result, None, project_dir)
        # Into the skill's journal too, with a pointer to the critique's own text (SCR-027). The
        # local log answers the footer's "last called"; the journal is what a resume and any other
        # front-end read, and until now it recorded that a review happened and lost what it argued.
        if result.mode in (critic.MODE_API_OR_CLI, critic.MODE_CLIPBOARD):
            try:
                process_writer.record_reviewer(
                    project_dir,
                    vendor=_vendor_of(result.model),
                    model=result.model or "?",
                    review=result.review or "",
                    mode="clipboard" if result.mode == critic.MODE_CLIPBOARD else "api",
                )
            except process_writer.ProcessWriterError:
                pass  # a critique that ran must not fail over its own bookkeeping
        bridge.show_critique(
            {
                "mode": result.mode,
                "text": result.text,
                "model": result.model,
                "role": result.role,
                "detail": result.detail,
                # The bubble links the text rather than being the only copy of it.
                "review": result.review,
            }
        )
        detail = result.detail
        if result.mode == critic.MODE_CLIPBOARD:
            # The script says WHAT happened; this says why it was always going to.
            why = clipboard_reason(project_dir)
            detail = f"{detail}\n{why}".strip() if detail else why
        return json.dumps(
            {
                "mode": result.mode,
                "critique": result.text,
                "model": result.model,
                "detail": detail,
                "seconds": round(result.duration_s, 1),
            },
            ensure_ascii=False,
        )

    @tool()
    async def report_phase(phase: str = "") -> str:
        """Re-read the process from disk and tell you what it actually says. Not a recorder --
        record with `enter_phase` / `add_step` / `start_step` / `finish_step` on this same surface,
        which drive the skill's own writer.

        This records nothing. It re-reads `process/process-state.json` and refreshes what the
        Arbiter is looking at, then hands you back what that file actually says — so if your call
        and the file disagree, you find out here rather than proposing against a phase that only
        exists in this conversation. `phase` is optional and used only for that comparison.

        Evidence, step status and the plan all belong in that file, written by the skill: there is
        no argument here for them because TCC does not keep a second copy.
        """
        state, error = _load_process_state()
        if error:
            return json.dumps({"refreshed": False, "error": error}, ensure_ascii=False)
        active = (state or {}).get("active_phase")
        bridge.refresh_from_disk()
        if not active:
            return json.dumps(
                {
                    "refreshed": True,
                    "skill_phase": None,
                    "warning": "process-state.json has no active_phase -- "
                               "call enter_phase before reporting one",
                },
                ensure_ascii=False,
            )
        entry = registry.sync_phase(active)
        out = {"refreshed": True, "skill_phase": active, "session": entry}
        if phase and str(phase) != str(active):
            out["mismatch"] = (
                f"you reported phase {phase!r}, but process-state.json says {active!r} -- "
                "the file wins; write the move before reporting it"
            )
        return json.dumps(out, ensure_ascii=False)

    return mcp


class _TokenGuard:
    """Reject any local process that doesn't present the token from `.mcp.json`.

    A loopback port with unauthenticated write tools on it is reachable by everything else running
    as this user. The token doesn't make the surface secret — `.mcp.json` is readable — but it
    does mean a request has to have *found* the config, which stops incidental cross-talk from
    another MCP client on the machine probing ports.
    """

    def __init__(self, app: Any, token: str) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
            if headers.get(_TOKEN_HEADER) != self._token:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": b'{"error":"bad or missing token"}'})
                return
        await self._app(scope, receive, send)


def _free_port(preferred: int = DEFAULT_PORT, tries: int = 20) -> int:
    """First free loopback port at or above `preferred`.

    Scanning upward from a fixed base rather than asking the OS for any free port keeps the URL
    stable across restarts, so a CLI session started earlier usually keeps working after TCC is
    restarted instead of pointing at a dead port.
    """
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"no free port in {preferred}..{preferred + tries}")


def write_mcp_config(project_dir: Path, port: int, token: str) -> Path:
    """Advertise this server in the project's `.mcp.json` so any CLI launched there finds it.

    Merges rather than overwrites: the file is the user's, and clobbering it would silently
    disconnect whatever other MCP servers they had configured for this project.
    """
    path = config.mcp_config_path(project_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    servers = data.setdefault("mcpServers", {})
    servers[SERVER_NAME] = {
        "type": "http",
        "url": f"http://127.0.0.1:{port}/mcp",
        "headers": {"X-TCC-Token": token},
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


class TccMcpServer:
    """Owns the server's lifetime: its own thread, its own asyncio loop, its own uvicorn.

    Qt's event loop is not asyncio-compatible, so the server cannot share the GUI thread. Nothing
    here touches Qt — the tools reach the GUI only through `UiBridge`, whose Qt implementation is
    responsible for marshalling back to the GUI thread.
    """

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        bridge: Optional[UiBridge] = None,
        preferred_port: int = DEFAULT_PORT,
    ) -> None:
        self.project_dir = Path(project_dir or config.project_dir())
        self.tcc_dir = config.tcc_dir(self.project_dir)
        self.bus = SignalBus(self.tcc_dir)
        self.registry = SessionRegistry(self.tcc_dir)
        self.bridge: UiBridge = bridge or HeadlessBridge(self.project_dir)
        self.token = secrets.token_urlsafe(24)
        self.port: Optional[int] = None
        self._preferred_port = preferred_port
        self._thread: Optional[threading.Thread] = None
        self._server: Any = None
        self._ready = threading.Event()
        #: What killed the serving thread, when something did. The thread cannot raise into
        #: `start()` — it is a different stack — so a death there used to be invisible: the caller
        #: held a server object that answered nothing (`start()` sets `_ready` BEFORE serving, so
        #: even the wait succeeded).
        self.failure: Optional[BaseException] = None

    @property
    def url(self) -> Optional[str]:
        return f"http://127.0.0.1:{self.port}/mcp" if self.port else None

    def start(self, write_config: bool = True) -> int:
        """Bind a port, start serving on a background thread, and return the port."""
        import uvicorn

        if self._thread is not None:
            raise RuntimeError("server already started")
        self.tcc_dir.mkdir(parents=True, exist_ok=True)
        self.port = _free_port(self._preferred_port)
        mcp = build_server(self.project_dir, self.bridge, self.bus, self.registry)
        app = _TokenGuard(mcp.streamable_http_app(), self.token)
        uvicorn_config = uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_level="warning", access_log=False,
            # `log_config=None`, and it is not a tidy-up: uvicorn's DEFAULT log config builds a
            # colour formatter whose `__init__` calls `sys.stdout.isatty()`, and a windowed
            # process on Windows has **no stdout at all** — `sys.stdout` is `None`. So merely
            # CONSTRUCTING this Config raised `ValueError: Unable to configure formatter
            # 'default'` from an `AttributeError: 'NoneType' object has no attribute 'isatty'`,
            # and TCC came up with no MCP server and no way for a session to reach it (user, on
            # Windows 11, 2026-08-19; on macOS the .app launcher is a shell script, so stdout is
            # real and this never fired).
            #
            # Passing None tells uvicorn to configure no logging of its own, which is what we want
            # anyway: `core/app_log` already owns this process's logging, and uvicorn's loggers
            # propagate into it. One less thing writing to a stream that may not exist.
            log_config=None,
        )
        self._server = uvicorn.Server(uvicorn_config)

        def _serve() -> None:
            self._ready.set()
            try:
                asyncio.run(self._server.serve())
            except BaseException as exc:  # noqa: BLE001 — the thread's death has to be reportable
                self.failure = exc

        self._thread = threading.Thread(target=_serve, name="tcc-mcp", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        self._wait_until_serving()
        if write_config:
            write_mcp_config(self.project_dir, self.port, self.token)
        return self.port

    def _wait_until_serving(self, timeout: float = 5.0) -> None:
        """Return once uvicorn says it is up — or raise with what stopped it.

        `_ready` only says the THREAD started, and it is set before `serve()` is even called, so
        `start()` used to report success for a server that had already died on its first line: the
        window then held an object that answered nothing, and the only sign was a chat message
        hours later saying the server was not running, with no reason attached (user, on Windows
        11, 2026-08-19). Uvicorn publishes `started`; this waits for it.

        A timeout is NOT a failure: a slow machine's server is still a server, and killing a
        working one because it took four seconds would be the worse error. Only a dead thread or a
        recorded exception raises.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if getattr(self._server, "started", False):
                return
            if self.failure is not None:
                raise RuntimeError(f"the MCP server stopped as it started: {self.failure}")
            if self._thread is not None and not self._thread.is_alive():
                raise RuntimeError(
                    "the MCP server's thread ended before it started serving"
                    + (f": {self.failure}" if self.failure else "")
                )
            time.sleep(0.05)

    @property
    def serving(self) -> bool:
        """Whether uvicorn is actually up — not merely whether a thread was created."""
        return bool(getattr(self._server, "started", False))

    def stop(self, timeout: float = 5.0) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None
        self._server = None
