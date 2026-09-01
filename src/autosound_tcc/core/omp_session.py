"""The tuning conversation driven by `omp`, for every model that is not Claude.

Second of the two adapters behind `core.agent_events.AgentSession`. The split is by provider, not
by preference (`spike/HANDOFF.md` §5-ter): Claude runs through the Agent SDK against the user's own
CLI, because that is the path whose licensing is settled; everything else — Gemini, local models,
whatever subscriptions the user has already put in omp's own credential broker — runs through here.

**Credentials are never handled here either.** omp resolves them from its broker and the
environment. TCC does not configure omp's Anthropic OAuth, does not offer it, and does not steer
toward it: a fallback path does not make shipping the primary one safe.

What this owes the rest of TCC, all four measured on the spike stand before a line of it was
written (`spike/rpc_driver.py`, and the frame capture behind the constants below):

* **Streamed prose and tool calls** as `agent_events`, so the dialog panel cannot tell which
  harness produced the turn.
* **The Arbiter gate.** omp asks its host for permission on its own built-in tools and blocks
  until the answer comes back — proven at 6s of deliberate delay. TCC's own MCP tools gate
  themselves inside the tool (`mcp_server._confirm`), so they are approved here rather than
  double-prompted, exactly as the SDK adapter does.
* **The question channel.** omp's `ask` reaches the host as a select frame and parks the turn.
  Rendering it is not optional: an unanswered question is indistinguishable from a hung window.
* **`tools.xdev=false`**, without which TCC's MCP tools never enter the model's function list at
  all — they sit behind `xd://` device URLs and the skill's "call `get_tcc_state`" means nothing.

Known and deliberate: omp's permission frame and its question frame are *the same frame* —
`method: "select"`, no discriminator — so they are told apart by shape, conservatively. See
`_is_permission`.

**The one invariant this file exists to keep: every `extension_ui_request` is answered exactly
once.** omp blocks inside the tool that raised the frame, so an unanswered one is not a dropped
message — it is the turn stopping forever, and it looks identical to a crash, a slow model and a
hung window. Five separate "hangs" in one day were the same defect wearing different frames
(`turn_end`, `setWidget`, `editor`, `cancel`, and a disabled composer), each found only after the
fact. So the adapter no longer works from a list of frames it recognises: `_read_frames` checks,
for every request, that it was answered, parked as a question, or handed to the gate, and anything
left over is cancelled and **named on the activity line**. An unknown frame costs one cancelled
widget and one visible word; it can no longer cost a session.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from autosound_tcc.core import child, config, model_choices, signal_bus, vendor_loader
from autosound_tcc.core.agent_events import (
    AgentEvent,
    Notice,
    Question,
    QuestionOption,
    QuestionWithdrawn,
    TextDelta,
    ToolCall,
    ToolEnd,
    TurnEnd,
)
from autosound_tcc.core.mcp_server import ConfirmRequest, HeadlessBridge, UiBridge
from autosound_tcc.core.tuning_session import SKILL_NAME, bash_is_read_only

DEFAULT_MODEL = "gemini-3.1-pro-preview"

# The omp profile TCC runs sessions in. Named rather than default so a tuning session cannot pick
# up the user's own MCP servers -- see `_argv`.
OMP_PROFILE = "tcc"

# What omp reads for a Google model, checked in its binary rather than assumed: `GEMINI_API_KEY`
# and `GOOGLE_API_KEY`, *not* the `GOOGLE_GENERATIVE_AI_API_KEY` that OpenCode wanted. Worth
# checking before the turn because the failure is silent -- no key means an empty answer and no
# error -- and because a double-clicked app bundle inherits almost no environment at all.
_GOOGLE_KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

# omp's built-in tools a tuning session may use. An allowlist because of what the *rest* of them
# do to the method, and `todo` is the case that proves it: given a checklist to hold, the model
# reached for omp's own todo list instead of the skill's plan, and a plan that lives in the
# harness is invisible to the panel, to `process-state.json` and to the Arbiter -- the run that
# did this wrote **zero** journal events while looking, in the transcript, like it was organised.
# The skill's plan has exactly one home (`mcp__tcc_add_step` / `process.py`), so nothing else may
# offer one. `task`/`hub` spawn sub-agents that would run the method unobserved, `eval`/`debug`/
# `lsp`/`ast_edit` are code-editing tools with no meaning here, and `web_search` is the researcher
# the overlay already turns off.
#
# Not filtered by this: `mcp__*` tools, which omp rejects as names here -- TCC's own surface is
# scoped by the profile instead.
_ENABLED_TOOLS = (
    "read", "write", "edit", "glob", "grep", "bash", "ask", "inspect_image",
)

# The version omp actually accepts. It advertises `[1, 2]` in its `ready` frame and then rejects 1
# with "Unsupported RPC protocol version" -- checked, not assumed.
RPC_PROTOCOL_VERSION = 2

# Frames omp raises for its own chrome. Answering them `cancelled` is how the host says "I am not
# that kind of UI"; leaving them unanswered stalls the agent.
_CHROME_METHODS = frozenset({"setWidget", "setTitle", "set_editor_text", "notify"})

# omp taking back a frame it raised earlier; `targetId` says which. Seen in the frame log after an
# abort: the editor omp had opened was withdrawn, and the card for it was still on screen with
# buttons that answered nothing. Unhandled it was worse than useless -- an unknown method fell
# through to "this is a question", so an empty card replaced the real one and was never answered.
_CANCEL_METHOD = "cancel"


# Free text. omp sends this after "Other (type your own)" is chosen, and puts the whole rendered
# widget in the title -- the question, a recap of the options as ○/◉ lines, and "Enter your
# response:". Unrecognised, it rendered as a question card with the radio glyphs inside it and the
# turn sat there (frame log, 2026-08-05). The question is the first line; the rest is the widget
# drawing itself, which the panel has already drawn its own way.
_EDITOR_METHOD = "editor"

# Frames that carry something to put in front of the Arbiter. Everything outside these, the chrome
# above and `cancel` is unknown -- and unknown is cancelled and named, never left to sit.
_SELECT_METHOD = "select"
_CONFIRM_METHOD = "confirm"
_QUESTION_METHODS = frozenset({_SELECT_METHOD, _EDITOR_METHOD, _CONFIRM_METHOD})

# omp's own wording on a permission prompt. Matched together with the option shape, and a frame
# that satisfies neither is still treated as a permission -- see `_is_permission`.
_PERMISSION_TITLE_PREFIX = "Allow tool: "
_PERMISSION_OPTIONS = frozenset({"Approve", "Deny"})

# The tool omp uses to ask the human. Its call is rendered as the question itself, so it must not
# also arrive as a process chip.
_ASK_TOOL = "ask"

# What ends an exchange. `agent_end` says so outright -- but it does not always arrive: omp keeps
# the agent alive between prompts in `rpc-ui`, and a turn whose last act is a question to the human
# can end with the wire simply going quiet. Read from omp's own session store afterwards, the
# hung turn was complete: the tool returned, the model finished its message, nothing followed.
#
# `turn_end` alone is not the end either -- a turn is one round of the model, so a prompt answered
# with eight tool calls emits nine of them, and ending on the first delivers three process chips
# and then silence (measured: turn_start 9, turn_end 9, agent_start 1, agent_end 1).
#
# So: `agent_end` ends it, and so does a `turn_end` that nothing follows. The grace period is what
# separates "the model is about to call another tool" from "the model has finished talking".
_EXCHANGE_END = "agent_end"
_ROUND_END = "turn_end"
TURN_QUIET_S = 2.5

# omp retrying the model on its own. Invisible until now, and it is minutes: seven attempts over
# 106 seconds on `MALFORMED_FUNCTION_CALL` from a small model, with nothing on the wire but empty
# messages. A window that shows none of that is a window that looks broken while omp is coping.
_RETRY_START = "auto_retry_start"
_RETRY_END = "auto_retry_end"


# What counts as the exchange still moving, and therefore cancels the grace period above. Named
# rather than inferred from "not `turn_end`": omp's chrome arrives *after* the last round -- a
# `setWidget` clearing its own dashboard 30 ms behind the final `turn_end` -- and treating that as
# work reopened a turn that was finished, with nothing else ever coming. Measured that way.
_ACTIVITY_TYPES = frozenset({
    "message_start", "message_update", "message_end",
    "tool_execution_start", "tool_execution_update", "tool_execution_end",
    "turn_start", "agent_start", _RETRY_START, _RETRY_END,
})

# Tools that only look. Auto-approved because `--approval-mode always-ask` otherwise puts a
# dialog in front of every file the skill opens -- and the skill is built on opening files, so the
# Arbiter learns to click through, which is worse than not asking.
_READ_ONLY_TOOLS = frozenset({"read", "glob", "grep", "ls", "list", "todo", "hub"})

# Never auto-approved, whatever else is true: these can overwrite a measurement, a ledger or the
# project's own files, which is the evidence everything else is built on.
_ALWAYS_GATED_TOOLS = frozenset({"write", "edit", "ast_edit", "eval", "browser", "task"})

CONFIRM_TIMEOUT_S = 600.0
READY_TIMEOUT_S = 60.0

# `ready` means the RPC channel is up, NOT that the tool list is built: omp connects its MCP
# servers and loads plugins after it, and announces neither. Prompting on `ready` gets a turn whose
# model never saw TCC's tools -- measured: 17 tools offered instead of 203, none of them `tcc`.
# So after `ready` we wait for the wire to go quiet, which adapts to a cold start instead of
# guessing at it the way the spike's fixed twelve-second sleep did.
SETTLE_QUIET_S = 1.0
SETTLE_CAP_S = 45.0

# Every frame, both directions, next to the project's other TCC state. Three hangs were diagnosed
# by guessing at what omp had sent, and each guess cost a session: `turn_end` mistaken for the end
# of an exchange, a transcript wiped mid-turn, a free-text question answered as a permission. The
# frames are the only place those are visible, and they are cheap to keep.
FRAME_LOG = "omp-frames.jsonl"
FRAME_LOG_MAX_BYTES = 4_000_000
# Big frames are shrunk field by field rather than by cutting the line, so every line parses --
# see `_shrink`.
FRAME_VALUE_MAX_CHARS = 600
FRAME_LIST_MAX_ITEMS = 24

# How long a turn may produce nothing before the window says so. Not a timeout -- nothing is
# cancelled -- but "it has been silent for two minutes" is a fact the Arbiter can act on, and
# staring at an animated line is not.
SILENCE_WARN_S = 120.0

# What the skill's own writers do, so a permission can ask about the effect instead of the command
# line. "Allow bash: python3 rew_tool/apply.py --preset FULL ..." is not a question anyone can
# answer -- it is a script that starts a Python that computes -- while "write a ledger snapshot"
# is. Only the writers are listed: readers never reach the gate.
_EFFECTS: tuple[tuple[str, str], ...] = (
    ("state/process.py", "effectProcess"),
    ("dsp_profile.py", "effectProfile"),
    ("apply.py", "effectLedger"),
    ("project.py", "effectProject"),
    ("contract.py", "effectContract"),
)

# Which writes still ask. `writes` gates everything that is not read-only; `foreign` also lets the
# skill write its own files (`process/`, `state/`, and the project files it owns) and asks only
# about what reaches outside them. The choice belongs to the project (SCR-004's "the skill owns
# its namespace" read as a permission rule).
GATE_WRITES = "writes"
GATE_FOREIGN = "foreign"
# Nothing from the harness asks. Chosen by the Arbiter, and narrower than it sounds: TCC's own
# tools raise their confirmations *inside* the tool, so a DSP or REW write still stops for a
# human. What this turns off is the shell-and-file traffic, which is where the noise was -- and a
# gate that fires on `ls` is a gate that gets clicked through, which protects nothing.
GATE_AUTO = "auto"

# What a project starts on. `auto`, not `writes` (user, 2026-08-21): the reason the strictest
# setting was the default -- "start with every write and narrow it if it gets in the way" -- is an
# argument for a gate that TEACHES, and what it taught was clicking through. TCC's own tools still
# confirm inside themselves, so what this default hands over is the shell-and-file traffic and
# nothing that reaches the DSP.
GATE_DEFAULT = GATE_AUTO

# Paths the skill legitimately owns inside a project.
_SKILL_OWNED = ("process/", "state/", "dsp_profile.json", "dsp_profile.draft.json",
                "project.json", "autosound_context.md", "tuning-changelog", "audit-trail.md")


def _shrink(value: Any, limit: int = FRAME_VALUE_MAX_CHARS, depth: int = 0) -> Any:
    """A frame small enough to log, still valid JSON.

    The first version of the log capped the *serialised line* instead, which cut it mid-string and
    left 64 of 681 lines unparseable -- and they were the interesting ones, since only the big
    frames reached the cap. A record that cannot be read back is not a record, and this file's own
    replay test reads it back. So long strings are cut and long lists are cut, and the envelope
    always closes.
    """
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if depth >= 6:
        return "…"
    if isinstance(value, list):
        head = [_shrink(item, limit, depth + 1) for item in value[:FRAME_LIST_MAX_ITEMS]]
        return head + ["…"] if len(value) > FRAME_LIST_MAX_ITEMS else head
    if isinstance(value, dict):
        return {key: _shrink(item, limit, depth + 1) for key, item in value.items()}
    return value


class OmpNotInstalledError(RuntimeError):
    """`omp` is not on PATH. Fix: `brew install can1357/tap/omp`."""


def is_available() -> bool:
    return shutil.which("omp") is not None


def overlay_path(project_dir: Path) -> Path:
    """Config overlay TCC owns, written next to the project's own TCC state.

    A file rather than a flag because `tools.xdev` has no command-line form, and TCC's own file
    rather than the user's `~/.omp` because turning their global tool exposure inside out to run
    one tuning session would be a rude thing for an app to do.
    """
    path = config.tcc_dir(project_dir) / "omp-overlay.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Written by TCC.\n"
        "#\n"
        "# xdev: without this, TCC's MCP tools are mounted under xd:// device URLs and never enter\n"
        "# the model's function list -- measured, see spike/HANDOFF.md 5-bis.\n"
        "#\n"
        "# web_search: a tuning session answers questions by measuring, not by reading the web.\n"
        "# The skill has its own knowledge files and its own Critic, so a second, unasked-for\n"
        "# researcher would spend exactly the tokens this harness was chosen to save.\n"
        "#\n"
        "# NOT the explanation for the quiet turns, though an earlier reading of this file said so:\n"
        "# every `setWidget autoresearch` in a real capture carries no `widgetLines`, which in\n"
        "# omp's own bridge is the *clear the widget* branch. It was announcing the absence of a\n"
        "# researcher, not the presence of one. Kept because the setting is right on its merits.\n"
        "tools:\n  xdev: false\n"
        "web_search:\n  enabled: false\n"
        "#\n"
        "# skills: the model is shown one skill, not the user's library. Measured against omp's\n"
        "# own request: 75 skills and 12.5 KB of other people's descriptions in every call, and\n"
        "# among them a second `autosound-tuning` from ~/.claude/skills that TCC does not control.\n"
        "# This is the omp half of what the SDK adapter gets from `setting_sources=[\"project\"]`.\n"
        "skills:\n"
        "  enableClaudeUser: false\n"
        "  enableCodexUser: false\n"
        "  enablePiUser: false\n"
        "  enableAgentsUser: false\n"
        "  enableClaudeProject: true\n"
        f"  includeSkills: [\"{SKILL_NAME}\"]\n",
        encoding="utf-8",
    )
    return path


class OmpSession:
    """A tuning conversation bound to one project folder, run by an `omp` subprocess."""

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        bridge: Optional[UiBridge] = None,
        model: str = DEFAULT_MODEL,
        resume: bool = False,
        gate: str = GATE_WRITES,
        always_allowed: Optional[frozenset[str]] = None,
        effort: Optional[str] = None,
    ) -> None:
        self.project_dir = Path(project_dir or config.project_dir())
        self.bridge: UiBridge = bridge or HeadlessBridge(self.project_dir)
        self.model = model
        # See `_argv`: on a metered route the thinking level is a price, so it is chosen rather
        # than inherited. Same three words as the SDK route (`model_choices.EFFORT_LEVELS`).
        self.effort = model_choices.resolve_effort(effort)
        self.resume = resume
        self.gate = gate
        # Tools the Arbiter ticked "don't ask again" on, per project.
        self.always_allowed = always_allowed or frozenset()
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._events: asyncio.Queue[Optional[AgentEvent]] = asyncio.Queue()
        self._reader: Optional[asyncio.Task] = None
        self._pending: set[asyncio.Task] = set()
        self._frame_id = 0
        # Kept, not discarded: a subprocess that fails to start is the one thing the user cannot
        # diagnose from the transcript, and "nothing happened" was exactly how it presented.
        self._stderr_tail: list[str] = []
        self._stderr_task: Optional[asyncio.Task] = None
        self._log_path = config.tcc_dir(self.project_dir) / FRAME_LOG
        self._last_frame_at = 0.0
        # When the last round ended, or 0 if a round is in flight -- see `_ROUND_END`.
        self._round_ended_at = 0.0
        # The three states a request can be in, and there is no fourth. `_answered` is done,
        # `_parked` is with the Arbiter as a question, `_gating` is with the Arbiter as a
        # permission. A request in none of them after `_handle` is a frame this adapter did not
        # understand, and `_read_frames` will not let it stay that way.
        self._answered: set[str] = set()
        self._parked: set[str] = set()
        self._gating: set[str] = set()
        # The tool omp is inside right now, "" when it is between tools. A turn that goes quiet is
        # a different fact depending on this: a model thinking, or a `grep` that has been running
        # for eight minutes (measured, on a pattern with no path).
        self._running_tool = ""
        self._retrying = False
        self._retry_reason = ""
        self._ready = asyncio.Event()
        self._saw_ready = False
        self._ended = asyncio.Event()
        # The UI's signal bus, for delivering un-acknowledged signals inside the turn itself.
        # Same contract as `TuningSession.bus` (F-009): assigned by `AgentWorker` once it builds
        # the session, None in headless runs -- delivery must not depend on which front-end runs.
        self.bus: Optional[signal_bus.SignalBus] = None

    # ---- wire --------------------------------------------------------------

    def _argv(self) -> list[str]:
        argv = [
            "omp",
            "--mode",
            "rpc-ui",
            "--model",
            self.model,
            # Stated, not inherited. This is the METERED route -- the one the route prefixes exist
            # to make visible -- so how hard it thinks is how much it costs, and accepting the
            # broker's default would put that number outside the Arbiter's view. omp also offers
            # `auto`, which TCC does not: "let it decide how much to spend" is the one setting a
            # metered route should never hold while nobody is watching.
            "--thinking",
            self.effort,
            "--approval-mode",
            "always-ask",
            # Its own settings, sessions and caches, so a tuning session is not affected by what
            # the user did to their own omp. Cheap: the credential broker is per profile, but the
            # working path is the environment (`GEMINI_API_KEY`), which every profile shares.
            #
            # **It does NOT isolate MCP servers, despite a first measurement that said it did.**
            # That reading was a cold cache: a fresh profile has not connected the servers omp
            # imports from `~/.claude.json` yet, so an early request sees a short catalogue. Once
            # warm they are all back -- 166 foreign tools on this machine, 156 of them Home
            # Assistant, ~600 KB of schemas in every call. omp 17.2.5 has no switch for that
            # source: `mcp.enableProjectConfig` governs the project file only, the per-source
            # toggles exist for skills and not for MCP, and `disabledExtensions` was tried and has
            # no effect. What is left is the user's own `~/.claude.json` -- servers declared at the
            # top level load in every directory, the same ones scoped to a project do not.
            "--profile",
            OMP_PROFILE,
            "--tools",
            ",".join(_ENABLED_TOOLS),
            "--config",
            str(overlay_path(self.project_dir)),
            # Sessions live with the project, so resuming is "continue this project's last one"
            # and no session id has to be carried across processes.
            "--session-dir",
            str(config.tcc_dir(self.project_dir) / "omp-sessions"),
        ]
        if self.resume:
            argv.append("--continue")
        return argv

    def _send(self, frame: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            return
        self._log("out", frame)
        proc.stdin.write((json.dumps(frame) + "\n").encode())

    def _log(self, direction: str, frame: dict[str, Any]) -> None:
        """Append one frame. Never raises: a diagnostic that can break the session is worse than
        no diagnostic."""
        try:
            path = self._log_path
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > FRAME_LOG_MAX_BYTES:
                path.unlink()
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": time.time(), "dir": direction,
                                     "frame": _shrink(frame)}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ---- responses ----------------------------------------------------------

    def _respond(self, frame_id: Any, payload: dict[str, Any]) -> None:
        """The only way a response leaves this adapter, so "exactly once" is a property of the
        code and not of everyone remembering.

        A second answer to the same id is dropped rather than sent: omp has moved on, and the
        stale one lands on whatever it raised next. That is how a permission got answered with a
        question's text.
        """
        key = str(frame_id or "")
        if key and key in self._answered:
            return
        if key:
            self._answered.add(key)
            self._parked.discard(key)
            self._gating.discard(key)
        self._send({"type": "extension_ui_response", "id": frame_id, **payload})

    def _next_id(self) -> str:
        self._frame_id += 1
        return f"tcc{self._frame_id}"

    # ---- frame classification ----------------------------------------------

    @staticmethod
    def _is_permission(frame: dict[str, Any]) -> bool:
        """Whether a select frame is omp asking permission, rather than the agent asking the human.

        They arrive as the same frame type with no field to tell them apart, so this reads their
        shape: omp's own prompt is titled "Allow tool: <name>" and offers Approve/Deny, while a
        question carries the model's wording and its own options.

        Recognised **positively**, and only positively. An earlier version treated an
        option-less select as a permission on the theory that ambiguity should resolve toward the
        gate. Observed failing: omp raises free-text questions with no options, so the model asked
        "what is your car make/model?", TCC showed "Allow ...?" with the question as the tool name,
        the Arbiter allowed it, and omp received "Approve" as the answer to a question. The
        transcript recorded `Arbiter allowed What is your car make/model...` and the turn wedged.

        A permission from omp always says so -- Approve/Deny among its options, or the title omp
        writes for its own prompt. Anything else is the agent talking to the human, and a question
        with no options is answered by typing, which the composer already does.
        """
        title = str(frame.get("title") or "")
        options = {str(option) for option in (frame.get("options") or [])}
        if _PERMISSION_OPTIONS & options:
            return True
        if title.startswith(_PERMISSION_TITLE_PREFIX):
            return True
        # `confirm` is a yes/no frame, which is the shape of a permission and not of a question.
        return frame.get("method") == "confirm"

    @staticmethod
    def _question_from(frame: dict[str, Any]) -> Question:
        options = tuple(
            QuestionOption(label=str(option)) for option in (frame.get("options") or [])
        )
        return Question(
            id=str(frame.get("id") or ""),
            question=OmpSession._question_text(frame),
            options=options,
        )

    @staticmethod
    def _question_text(frame: dict[str, Any]) -> str:
        """The question, without the widget omp drew around it.

        An `editor` title carries the option recap and "Enter your response:" as text. Those are
        omp painting a terminal UI; the panel has already shown the options as buttons and the
        composer already says it is waiting for an answer.
        """
        title = str(frame.get("title") or "")
        if frame.get("method") != _EDITOR_METHOD:
            return title
        head = title.split("\n\n", 1)[0].strip()
        return head or title.strip()

    @staticmethod
    def _tool_and_detail(frame: dict[str, Any]) -> tuple[str, str]:
        """Split omp's permission title into the tool and what it wants to do.

        The title is not one line: a bash permission arrives as
        `Allow tool: bash\\nCommand: echo spike`. Taking the whole thing as the tool name puts a
        shell command in the confirmation's heading and makes the `mcp__tcc` check depend on the
        arguments -- observed on the first live run of this adapter, before it was split here.
        """
        title = str(frame.get("title") or "")
        if title.startswith(_PERMISSION_TITLE_PREFIX):
            title = title[len(_PERMISSION_TITLE_PREFIX):]
        head, _, rest = title.partition("\n")
        args = frame.get("args")
        detail = rest.strip() or (json.dumps(args, ensure_ascii=False) if args else "")
        return head.strip(), detail[:400]

    # ---- the Arbiter gate ---------------------------------------------------

    async def _gate(self, frame: dict[str, Any]) -> None:
        """Put omp's permission request in front of the Arbiter and answer when they decide.

        Runs as its own task: the reader must keep draining frames while this is parked, or the
        agent's own progress frames queue up behind the question we are asking about them.
        """
        tool, detail = self._tool_and_detail(frame)
        if self._auto_allowed(tool, detail):
            self._answer_frame(frame, True)
            return
        command = detail.split("Command:", 1)[-1].strip() if "Command:" in detail else detail
        effect = self.effect_of(command)
        request = ConfirmRequest(
            # The question is what it will change, not what it will run: a command line three
            # nested calls deep is not something anyone can read and judge, so they approve it
            # unread -- which is worse protection than no gate at all.
            tool=effect or tool,
            title=f"Дозволити {tool}?",
            detail=detail,
            payload=dict(frame),
        )
        try:
            allowed = await asyncio.wait_for(
                asyncio.wrap_future(self.bridge.request_confirmation(request)),
                timeout=CONFIRM_TIMEOUT_S,
            )
        except Exception:
            allowed = False
        self._answer_frame(frame, allowed)

    def _auto_allowed(self, tool: str, detail: str) -> bool:
        """Whether this can go through without asking.

        Three things pass, and the reasoning for each is different. TCC's own tools raise their
        own confirmation *inside* the tool, so asking here too prompts twice for one action and
        teaches the Arbiter to click through both. Tools that only look cannot damage the evidence
        the tune is built on. And a bash command already judged read-only by the SDK adapter's
        allowlist -- one definition, shared -- is the same command whichever harness runs it.

        Everything else asks, and a short list can never be talked into passing: anything that
        writes or evaluates goes in front of the Arbiter even if it looks harmless, because what
        it can overwrite is a measurement or a ledger.
        """
        if self.gate == GATE_AUTO:
            return True
        if tool in self.always_allowed:
            return True
        if tool in _ALWAYS_GATED_TOOLS:
            return False
        if tool.startswith("mcp__tcc"):
            return True
        if tool in _READ_ONLY_TOOLS:
            return True
        if tool == "bash":
            command = detail.split("Command:", 1)[-1].strip() if "Command:" in detail else detail
            if bash_is_read_only(command):
                return True
            # `foreign`: the skill writing its own namespace is the skill doing its job, and asking
            # about it teaches the Arbiter to click through the ones that matter.
            return self.gate == GATE_FOREIGN and self._touches_only_skill_files(command)
        return False

    @staticmethod
    def _touches_only_skill_files(command: str) -> bool:
        paths = re.findall(r"[\w./\-]+\.(?:json|md|jsonl|txt)\b|\b(?:process|state)/[\w./\-]*", command)
        if not paths:
            return False
        return all(any(owned in path for owned in _SKILL_OWNED) for path in paths)

    @staticmethod
    def effect_of(command: str) -> Optional[str]:
        """An i18n key naming what a prescribed command writes, or None if TCC does not know it."""
        for needle, key in _EFFECTS:
            if needle in command:
                return key
        return None

    def _answer_frame(self, frame: dict[str, Any], allowed: bool) -> None:
        if frame.get("method") == _CONFIRM_METHOD:
            self._respond(frame.get("id"), {"confirmed": allowed})
        else:
            self._respond(frame.get("id"), {"value": "Approve" if allowed else "Deny"})

    # ---- reading ------------------------------------------------------------

    async def _read_frames(self) -> None:
        """Own stdout, from the first byte to EOF.

        Everything that reads frames reads them here. Startup used to have two readers of its own
        -- one waiting for `ready`, one waiting for the wire to go quiet -- and both dropped every
        frame they were not looking for, unanswered and unlogged. That is a hang that leaves no
        trace at all: the frame is not in the log, because the log is written here.
        """
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except ValueError:
                continue
            self._last_frame_at = time.time()
            self._log("in", frame)
            for event in self._handle(frame):
                await self._events.put(event)
        self._ended.set()
        self._ready.set()  # nothing more is coming; unblock a startup still waiting for it
        await self._events.put(None)  # the process ended; unblock whoever is draining

    def _handle(self, frame: dict[str, Any]) -> list[AgentEvent]:
        kind = frame.get("type")
        # Only work restarts the grace period, and "work" is a list rather than "anything that is
        # not `turn_end`". omp sends chrome after the last round -- a real turn ended with prose,
        # `turn_end`, and then a `setWidget` clearing its own dashboard 30 ms later, which under
        # the old rule cancelled the grace and left the exchange open forever. The window sat
        # there for eight minutes on a turn that was complete.
        if kind in _ACTIVITY_TYPES:
            self._round_ended_at = 0.0

        if kind == "ready":
            self._saw_ready = True
            self._ready.set()
            return []

        if kind == "extension_ui_request":
            events = self._handle_request(frame)
            return events + self._ensure_answered(frame)

        if kind == "message_update":
            event = frame.get("assistantMessageEvent") or {}
            if event.get("type") == "text_delta" and event.get("delta"):
                return [TextDelta(str(event["delta"]))]
            return []

        if kind == "tool_execution_start":
            name = str(frame.get("toolName") or "")
            if not name or name == _ASK_TOOL:
                # `ask` is rendered as the question it raises, not as a process chip as well.
                return []
            # Kept so a silent turn can say what it is silent *inside* -- see `_prompt`.
            self._running_tool = name
            return [ToolCall(name=name, arguments=dict(frame.get("args") or {}))]

        if kind == "tool_execution_end":
            # What stops the activity line moving. Without it the last tool of a turn appeared to
            # be running forever, which is how a stalled turn came to look like a busy one.
            self._running_tool = ""
            return [ToolEnd(name=str(frame.get("toolName") or ""))]

        if kind == _RETRY_START:
            # omp fighting the model, which it does silently: seven attempts over 106 seconds,
            # nothing on the wire but empty messages, and a window with nothing to show. The cause
            # is in the frame -- `MALFORMED_FUNCTION_CALL` from a small model -- and it is the
            # difference between "this is broken" and "this is being retried".
            attempt = frame.get("attempt")
            self._retrying = True
            self._retry_reason = str(frame.get("errorMessage") or "").strip()
            if attempt != 1:
                return []  # one line per storm, not one per attempt
            budget = frame.get("maxAttempts")
            # omp's own words, not an interpretation of them. An earlier version opened with "the
            # model's answer came back broken", which is true of `MALFORMED_FUNCTION_CALL` and a
            # lie about the error that actually turned up in use -- a 429 saying the account's
            # prepaid credits were gone. Retrying that ten times is hopeless, and telling the
            # Arbiter their model is broken sends them to fix the wrong thing.
            return [Notice(
                f"omp is retrying the model (up to {budget}): {self._retry_reason}"
                if self._retry_reason else f"omp is retrying the model (up to {budget})."
            )]

        if kind == _RETRY_END:
            if not self._retrying:
                return []
            self._retrying = False
            attempt = frame.get("attempt")
            if frame.get("success"):
                return [Notice(f"omp got an answer on attempt {attempt}.")]
            # The line people screenshot, so it carries the reason again: by now the first Notice
            # has scrolled, and "gave up" on its own says nothing about what to do next.
            gave_up = f"omp gave up after {attempt} attempts — this turn produced nothing."
            # ...and a turn that produced nothing is OVER. It was not, and that is CAR-004: the
            # credits ran out mid-turn, omp retried its ten times, said so, and then said nothing
            # ever again. No `turn_end` frame follows a give-up, so the window sat on "thinking"
            # with a queued message promised "the moment this turn ends" — a promise that had
            # nothing left to come true. The Arbiter got out with `Send now`, which is a button
            # for a state the app should not have been in.
            #
            # Marked as a finished ROUND rather than yielding `TurnEnd` here, deliberately. If omp
            # does carry on after giving up on one model call, the next frame is activity and
            # clears this again (`_ACTIVITY_TYPES`, above) — so nothing is cut off underneath a
            # session that recovered. If nothing follows, `_prompt` closes the turn after its
            # ordinary 2.5 s grace instead of waiting out `SILENCE_WARN_S` and then forever.
            self._round_ended_at = time.time()
            return [Notice(f"{gave_up} {self._retry_reason}".strip())]

        if kind == _EXCHANGE_END:
            return [TurnEnd()]

        if kind == _ROUND_END:
            self._round_ended_at = time.time()
            return []

        if kind == "response" and frame.get("success") is False:
            # omp's answer to something TCC sent, and the only place it says no. A rejected
            # `negotiate_protocol` is exactly this shape ("Unsupported RPC protocol version") and
            # leaves a session that is up, connected and permanently silent -- so it gets said out
            # loud rather than dropped for being an outbound frame's business.
            reason = frame.get("error") or frame.get("message") or ""
            return [Notice(f"omp refused `{frame.get('command')}`: {reason}")]

        return []

    def _handle_request(self, frame: dict[str, Any]) -> list[AgentEvent]:
        """One request in; the response goes out here or the frame is parked, never neither.

        The methods are handled by name and the last branch is the point of the whole thing: a
        method this adapter has never seen is cancelled and said out loud. Five hangs in a day
        came from the opposite default -- the frame we did not recognise fell through to "this
        must be a question", so it waited for an answer nobody could give, and the only evidence
        was a window doing nothing.
        """
        method = str(frame.get("method") or "")

        if method in _CHROME_METHODS:
            self._respond(frame.get("id"), {"cancelled": True})
            return self._widget_events(frame)

        if method == _CANCEL_METHOD:
            # omp taking its own frame back. The card for it is still on screen with buttons that
            # answer nothing, so say so; the withdrawal itself is answered like any other request.
            target = str(frame.get("targetId") or "")
            self._respond(frame.get("id"), {"cancelled": True})
            if target and target in self._parked:
                self._parked.discard(target)
                self._answered.add(target)
                return [QuestionWithdrawn(id=target)]
            return []

        if method in _QUESTION_METHODS:
            if method != _EDITOR_METHOD and self._is_permission(frame):
                self._gating.add(str(frame.get("id") or ""))
                task = asyncio.create_task(self._gate(frame))
                self._pending.add(task)
                task.add_done_callback(self._pending.discard)
                return []
            question = self._question_from(frame)
            self._parked.add(question.id)
            return [question]

        self._respond(frame.get("id"), {"cancelled": True})
        return [ToolCall(name=f"omp:{method or 'unknown'}")]

    @staticmethod
    def _widget_events(frame: dict[str, Any]) -> list[AgentEvent]:
        """A `setWidget` is only worth a line when it *shows* something.

        Read out of omp's own binary rather than guessed at, because the guess was wrong and cost
        a commit. Its rpc-ui bridge sends the frame only when the widget is being cleared or set to
        static lines:

            setWidget(key, lines, opts) {
              if (lines === undefined || Array.isArray(lines)) { output({ method: "setWidget", ...

        A live widget is registered with a *render function*, which is neither -- so no frame goes
        out at all. Every `setWidget` in a real capture (8 of 8) arrives with no `widgetLines`,
        which is the `undefined` branch: **"remove the autoresearch widget"**. The activity line
        was showing that as `⟳ omp:autoresearch...`, i.e. announcing work as starting at the exact
        moment omp said there was none -- and the frame is fire-and-forget on omp's side, never
        entered in its pending map, so it is not even something to answer.
        """
        lines = frame.get("widgetLines")
        key = str(frame.get("widgetKey") or "")
        if not key or not isinstance(lines, list) or not lines:
            return []
        return [ToolCall(name=f"omp:{key}")]

    def _ensure_answered(self, frame: dict[str, Any]) -> list[AgentEvent]:
        """The net under `_handle_request`: nothing leaves this method still waiting.

        It should never fire -- every branch above answers or parks. It exists because the failure
        it catches costs a whole session and presents as "TCC hung", and because the next frame omp
        adds will reach a version of this file that has not heard of it.
        """
        key = str(frame.get("id") or "")
        if not key or key in self._answered or key in self._parked or key in self._gating:
            return []
        self._respond(frame.get("id"), {"cancelled": True})
        return [ToolCall(name=f"omp:unanswered:{frame.get('method') or '?'}")]

    # ---- lifecycle ----------------------------------------------------------

    async def start(self, prompt: Optional[str] = None) -> AsyncIterator[AgentEvent]:
        if not is_available():
            raise OmpNotInstalledError("omp is not on PATH — install it: brew install can1357/tap/omp")
        # Before the process starts: omp scans for skills at startup, so a link created later in
        # the turn would not be seen until the next session.
        vendor_loader.link_skill_into(self.project_dir)
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv(),
            cwd=str(self.project_dir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # omp shells out to the skill, whose scripts are in a git submodule; without this its
            # children drop `__pycache__` into a repo TCC does not own (see vendor_loader).
            env=vendor_loader.child_env(),
            # Its stdin is the pipe we drive it through, so `quiet()` would be wrong here; this is
            # the other half — no console window on Windows (see core/child.py).
            **child.flags(),
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        # Started before anything is awaited, so no frame is read anywhere else: whatever arrives
        # during startup is classified, answered and logged like every other frame.
        self._reader = asyncio.create_task(self._read_frames())
        await self._await_ready()
        self._send(
            {"id": self._next_id(), "type": "negotiate_protocol",
             "protocolVersion": RPC_PROTOCOL_VERSION}
        )
        await self._await_settled()
        for warning in (self.skill_warning(), self.credential_warning()):
            # After the link attempt in `start`, so a skill warning here means it actually failed.
            if warning:
                yield Notice(warning)
        async for event in self._prompt(prompt or self._opening()):
            yield event

    async def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        async for raw in proc.stderr:
            line = raw.decode(errors="replace").rstrip()
            if line:
                self._stderr_tail = (self._stderr_tail + [line])[-20:]

    def _why(self, fallback: str) -> str:
        """`fallback`, with whatever omp said on stderr — the part worth reading."""
        tail = "\n".join(self._stderr_tail[-5:]).strip()
        return f"{fallback}\n{tail}" if tail else fallback

    async def _await_settled(self) -> None:
        """Wait until omp stops emitting startup frames, i.e. until its tools exist.

        There is no "tools are loaded" frame to wait for -- `ready` fires first and MCP connection
        happens quietly afterwards -- so this reads the only signal there is: the wire going quiet.
        The reader keeps answering whatever arrives meanwhile; this only watches the clock.

        Capped, so a harness that chatters forever costs a slow first turn rather than a hang.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SETTLE_CAP_S
        while loop.time() < deadline:
            if self._ended.is_set():
                raise RuntimeError(self._why("omp exited during startup"))
            quiet_for = time.time() - self._last_frame_at
            if quiet_for >= SETTLE_QUIET_S:
                return
            await asyncio.sleep(min(SETTLE_QUIET_S - quiet_for, 0.2))

    async def _await_ready(self) -> None:
        """Wait for omp's `ready` frame rather than sleeping at it.

        `ready` means the RPC channel is negotiable. It does **not** mean the tool list is built --
        that is what `_await_settled` is for. The frame itself is seen by the reader, which is the
        only thing holding stdout.
        """
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=READY_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise TimeoutError(self._why("omp did not report ready")) from None
        if not self._saw_ready:
            raise RuntimeError(self._why("omp exited before reporting ready"))

    def _opening(self) -> str:
        return (
            "Resume this tuning project. Read state from disk first, call get_tcc_state and "
            "get_pending_signals, then tell me where we are and what the next step is."
            if self.resume
            else "Start a tuning session for this project. Read state from disk, call "
            "get_tcc_state, then tell me where we are and what the next step is."
        )

    def credential_warning(self) -> Optional[str]:
        """Whether the model this session runs has anything to authenticate with.

        Only the Google family is checked, because it is the one TCC defaults to and the one whose
        failure is silent: without a key the turn comes back empty and nothing says why. A bundle
        started from the Finder has no shell environment, so "it works in my terminal" is not
        evidence that it works when double-clicked.
        """
        if "gemini" not in self.model.lower() and "google" not in self.model.lower():
            return None
        if any(os.environ.get(name) for name in _GOOGLE_KEY_VARS):
            return None
        return (
            f"No {' or '.join(_GOOGLE_KEY_VARS)} in this process's environment. omp will have "
            f"nothing to authenticate `{self.model}` with, and that failure is silent — the turn "
            "comes back empty. Start TCC from a shell that has the key, or run "
            f"`omp --profile {OMP_PROFILE} auth login`."
        )

    def skill_warning(self) -> Optional[str]:
        """Whether this project has a skill at all, said before the turn rather than after it.

        Called after `vendor_loader.link_skill_into`, so it fires only when TCC could not install
        the skill itself — no submodule, or a filesystem that refuses symlinks.

        A session with no `.claude/skills/autosound-tuning` does not fail -- it improvises, and
        that is far worse than failing. Seen whole in a real run: the model read `skill://` from
        whatever was in `~/.claude/skills`, followed a `file:///skills/...` reference that resolves
        nowhere (SCR-029), then hunted the disk with three globs and a `grep` that ran for eight
        minutes, and finally invented an intake of its own. Every number it wrote was made up.
        """
        link = self.project_dir / ".claude" / "skills" / SKILL_NAME
        try:
            if link.exists():
                return None
        except OSError:
            pass
        return (
            f"This project has no `.claude/skills/{SKILL_NAME}`. The session will run without the "
            "tuning method and improvise one — link the skill into the project before trusting "
            "anything it says."
        )

    async def _prompt(self, text: str) -> AsyncIterator[AgentEvent]:
        self._round_ended_at = 0.0  # a round that ended before this prompt did not end this one
        self._retrying = False  # a storm belongs to the turn it happened in
        self._retry_reason = ""
        # The F-009 injection point: every turn -- the opener included -- passes through here, so
        # un-acknowledged signals reach the model even in a turn where it calls no tcc tool at
        # all. Same mechanism as `TuningSession.send`; the two front-ends must not differ on it.
        self._send({"id": self._next_id(), "type": "prompt",
                    "message": signal_bus.with_pending_brief(self.bus, text)})
        self._last_frame_at = time.time()
        warned = False
        try:
            while True:
                quiet = TURN_QUIET_S if self._round_ended_at else SILENCE_WARN_S
                try:
                    event = await asyncio.wait_for(self._events.get(), timeout=quiet)
                except asyncio.TimeoutError:
                    if self._parked:
                        # Silence with a question on screen is not silence: omp is blocked inside
                        # `ask`, waiting for the Arbiter, and the panel is already saying so.
                        # Ending the turn here would drop the answer on the floor, and warning
                        # about it would blame the harness for waiting on us.
                        continue
                    if self._round_ended_at:
                        # A round ended and nothing followed: the model has finished talking,
                        # whether or not omp bothers to say `agent_end`.
                        self._round_ended_at = 0.0
                        yield TurnEnd()
                        return
                    # Not a cancellation: the turn may still be thinking. But "silent for two
                    # minutes" is a fact the Arbiter can act on, and an animated line saying
                    # "working" is not.
                    if not warned:
                        warned = True
                        # Naming the tool is the whole value: "omp has said nothing" and "still
                        # inside grep" call for different things from the Arbiter, and the second
                        # one was true for 510 seconds while the first was all the window said.
                        where = (f"Still inside `{self._running_tool}`."
                                 if self._running_tool else "omp has said nothing.")
                        yield Notice(f"{int(SILENCE_WARN_S)}s with no output. {self._why(where)}")
                    continue
                warned = False
                if event is None:  # process ended mid-turn
                    return
                yield event
                if isinstance(event, TurnEnd):
                    return
        finally:
            # The turn is over -- normally, or because omp died mid-turn, which is why this is a
            # finally. Signals the turn read but never acked go back to pending here, so the next
            # turn's preamble raises them again instead of them dying "delivered".
            if self.bus is not None:
                self.bus.restore_delivered()

    async def send(self, text: str) -> AsyncIterator[AgentEvent]:
        if self._proc is None:
            raise RuntimeError("call start() before send()")
        async for event in self._prompt(text):
            yield event

    async def answer(self, question_id: str, value: str) -> None:
        """Deliver the Arbiter's answer to a parked question. Free text is passed through as-is —
        omp adds an "Other (type your own)" option to every question and accepts the typed value."""
        self._respond(question_id, {"value": value})

    async def cancel_question(self, question_id: str) -> None:
        """Withdraw a question. omp is blocked inside `ask`; `abort` does not reach it."""
        self._respond(question_id, {"cancelled": True})

    async def interrupt(self) -> None:
        """`abort` is the command omp actually has; `interrupt`, `cancel` and `stop` are not
        commands it knows -- established by asking it."""
        self._send({"id": self._next_id(), "type": "abort"})

    async def close(self) -> None:
        for task in list(self._pending) + ([self._stderr_task] if self._stderr_task else []):
            task.cancel()
        if self._reader is not None:
            self._reader.cancel()
        proc = self._proc
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                proc.kill()
        self._proc = None
