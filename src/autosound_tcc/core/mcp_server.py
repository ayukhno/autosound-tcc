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
import json
import secrets
import socket
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

from mcp.server.fastmcp import FastMCP

from autosound_tcc.core import (
    agent_session,
    config,
    critic,
    model_choices,
    process_writer,
    profile_writer,
    project_settings,
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


def _reviewer_state(project_dir: Path) -> dict[str, Any]:
    """What TCC already knows about the reviewer channel, so intake stops asking about it.

    The Arbiter picks a Critic in the footer and it is stored per project. The skill, having no
    way to see that, opens every intake with "how would you like to set up the Reviewer
    (Critic-Advisor) channel?" -- about a channel that is configured and one `call_critic` away.
    A GUI that knows something and asks anyway is just a chat window with more buttons.

    `reachable` is the honest half: the reviewer script is Gemini-shaped, so a non-Gemini choice
    is clipboard-only until SCR-033 lands (`model_choices.critic_reaches`).
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
    choice = model_choices.find(known, key) or model_choices.Choice(
        harness=harness or "omp", model=model or key, label=key, provider=""
    )
    return {
        "configured": True,
        "model": choice.model,
        "label": choice.label,
        "reachable": model_choices.critic_reaches(choice),
        "how": "call the `call_critic` tool" if model_choices.critic_reaches(choice)
               else "call `call_critic`; it will hand you a clipboard package for this model",
        # Reported once and asked back: the model read this, then put "confirm that this is your
        # independent reviewer?" to the Arbiter. Naming a field `configured` says what the value
        # is; it does not say who decided it. This does.
        "decided_by": "the Arbiter, in TCC's own UI — settled, not a suggestion to confirm",
    }


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

    @mcp.tool()
    async def get_tcc_state() -> str:
        """What the Arbiter currently has on screen: preset, ledger version, selection, edit mode.

        Call this before proposing anything, so a proposal refers to what they are actually
        looking at rather than to state you inferred earlier in the conversation.
        """
        process_state, error = _load_process_state()
        ui = bridge.snapshot()
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
            "pending_signals": bus.pending_count,
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
        return json.dumps(state, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def get_pending_signals() -> str:
        """Take every user signal raised in the UI since the last call, emptying the queue.

        Signals are things the Arbiter did that you would otherwise not know about: switching on
        param-edit mode, flagging that something you claimed to have changed is not visible, or
        moving attention to another channel. Check this at the start of a turn and before any
        proposal; a `not_visible` signal means re-verify against disk, not restate your claim.

        A `channel_toggle` signal (`{group, channel, on}`) is the Arbiter asking for a channel to
        be switched on or off in the tree. TCC does not write the ledger, so nothing has changed
        yet: record it the way any other agreed change is recorded (`apply.propose`), and say so.
        Turning one **on** usually means more than a flag -- a physical output needs its virtual
        counterpart and its place in the glossary -- so treat it as a request to make that channel
        real, not as a single field edit.
        """
        signals = [s.as_dict() for s in bus.drain()]
        return json.dumps({"signals": signals, "count": len(signals)}, ensure_ascii=False, indent=2)

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

    @mcp.tool()
    async def wait_for_signal(timeout_seconds: float = 900.0) -> str:
        """Park until the Arbiter does something in the UI, then return those signals.

        Use this when you have nothing to do until the human acts — after handing them a
        measurement task or a settings sheet to enter. Returns an empty list if nothing happens
        before the timeout.
        """
        deadline = min(max(timeout_seconds, 1.0), 3600.0)
        waited = 0.0
        slice_s = 5.0
        while waited < deadline:
            signals = await asyncio.to_thread(bus.wait, min(slice_s, deadline - waited))
            if signals:
                return json.dumps(
                    {"signals": [s.as_dict() for s in signals], "count": len(signals)},
                    ensure_ascii=False,
                    indent=2,
                )
            waited += slice_s
            await _heartbeat(waited, deadline)
        return json.dumps({"signals": [], "count": 0, "timed_out": True})

    @mcp.tool()
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
    @mcp.tool()
    async def get_capability_checklist() -> str:
        """The fixed DSP capability-checklist questions to ask the human about (project-intake.md
        §4). Ask closed questions with concrete options where you can, 2-3 per turn -- never dump
        the whole remaining list into one message, even when several are still open."""
        return json.dumps(profile_writer.capability_checklist(), ensure_ascii=False)

    @mcp.tool()
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

    @mcp.tool()
    async def save_profile_field(path: str, value: Any) -> str:
        f"""Save one confirmed field into the in-progress profile draft (call
        check_existing_profile first). One field per call, as soon as it's confirmed -- don't
        batch everything to the end. Each call lands on disk, so an interrupted interview keeps
        everything answered so far.

        `path` is a dotted path relative to `project_profile` as returned by
        check_existing_profile -- e.g. 'sample_rate_hz' or 'groups.0.fields'. `groups` is a flat
        array, each entry EXACTLY {{"id": "<snake_case_id>", "label": "<Human Label>",
        "fields": [<tokens>]}} -- `fields` must be a flat array of STRING TOKENS drawn ONLY from
        this vocabulary, nothing else:
        {json.dumps(profile_writer.field_vocabulary())}
        A capability that doesn't fit this vocabulary belongs in `_open_questions`, not a made-up
        field name.
        """
        if not profile_writer.has_draft(project_dir):
            return json.dumps({"error": "call check_existing_profile first"})
        try:
            return json.dumps(profile_writer.set_field(project_dir, path, value),
                               ensure_ascii=False)
        except profile_writer.ProfileWriterError as exc:
            return json.dumps({"saved": False, "error": str(exc)})

    @mcp.tool()
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

    @mcp.tool()
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

    @mcp.tool()
    async def enter_phase(phase: str) -> str:
        """Make a phase current (−1…5) and record it. Phases are the skill's fixed skeleton --
        entering one instantiates its template steps; you do not invent phases."""
        return await asyncio.to_thread(_record, process_writer.enter_phase, phase)

    @mcp.tool()
    async def add_step(step_id: str, name: str, situational: bool = False) -> str:
        """Add a plan step. `situational=True` records it as this car's own insert rather than one
        instantiated from the phase template -- the distinction is what makes a plan readable
        later."""
        return await asyncio.to_thread(_record, process_writer.add_step, step_id, name, situational)

    @mcp.tool()
    async def start_step(step_id: str) -> str:
        """Begin, or re-begin, a step. Re-beginning is attempt N+1 -- a redo is recorded next to the
        first try, never on top of it."""
        return await asyncio.to_thread(_record, process_writer.start_step, step_id)

    @mcp.tool()
    async def finish_step(step_id: str, evidence: list[str]) -> str:
        """Close a step. `evidence` is REQUIRED, and at least one item must RESOLVE rather than
        describe: a REW capture name in the grammar (`tw-L_1 (rta)` -- the method suffix is what
        makes it a capture), a ledger version that exists on disk (`v_003`), or a project file that
        exists (`autosound_context.md`). Prose may ride along with one of those; prose alone is
        refused. The skill checks this, not TCC, and a refusal comes back in the skill's own
        wording -- write the artefact, then close the step against it, rather than retrying the
        same call."""
        return await asyncio.to_thread(_record, process_writer.finish_step, step_id, evidence)

    @mcp.tool()
    async def skip_step(step_id: str, superseded_by: str = "") -> str:
        """Supersede a step. It stays visible in the plan -- steps are never deleted, and what
        replaced this one is worth naming."""
        return await asyncio.to_thread(_record, process_writer.skip_step, step_id, superseded_by)

    @mcp.tool()
    async def block_step(step_id: str, reason: str) -> str:
        """Mark a step blocked and say what blocks it -- a gate waiting on the human, a measurement
        that cannot be taken yet."""
        return await asyncio.to_thread(_record, process_writer.block_step, step_id, reason)

    # ---- writes (every one gated on the Arbiter) ---------------------------

    @mcp.tool()
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

    @mcp.tool()
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

    @mcp.tool()
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

    @mcp.tool()
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
        result = await asyncio.to_thread(
            critic.run,
            package,
            project_dir=project_dir,
            trace_path=trace_path or None,
            model=model or None,
        )
        critic.log_call(result, None, project_dir)
        bridge.show_critique(
            {
                "mode": result.mode,
                "text": result.text,
                "model": result.model,
                "role": result.role,
                "detail": result.detail,
            }
        )
        return json.dumps(
            {
                "mode": result.mode,
                "critique": result.text,
                "model": result.model,
                "detail": result.detail,
                "seconds": round(result.duration_s, 1),
            },
            ensure_ascii=False,
        )

    @mcp.tool()
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
            app, host="127.0.0.1", port=self.port, log_level="warning", access_log=False
        )
        self._server = uvicorn.Server(uvicorn_config)

        def _serve() -> None:
            self._ready.set()
            asyncio.run(self._server.serve())

        self._thread = threading.Thread(target=_serve, name="tcc-mcp", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        if write_config:
            write_mcp_config(self.project_dir, self.port, self.token)
        return self.port

    def stop(self, timeout: float = 5.0) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None
        self._server = None
