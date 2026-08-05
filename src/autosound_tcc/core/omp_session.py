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
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from autosound_tcc.core import config, vendor_loader
from autosound_tcc.core.agent_events import (
    AgentEvent,
    Question,
    QuestionOption,
    TextDelta,
    ToolCall,
    TurnEnd,
)
from autosound_tcc.core.mcp_server import ConfirmRequest, HeadlessBridge, UiBridge
from autosound_tcc.core.tuning_session import bash_is_read_only

DEFAULT_MODEL = "gemini-3.1-pro-preview"

# The version omp actually accepts. It advertises `[1, 2]` in its `ready` frame and then rejects 1
# with "Unsupported RPC protocol version" -- checked, not assumed.
RPC_PROTOCOL_VERSION = 2

# Frames omp raises for its own chrome. Answering them `cancelled` is how the host says "I am not
# that kind of UI"; leaving them unanswered stalls the agent.
_CHROME_METHODS = frozenset({"setWidget", "setTitle", "set_editor_text", "notify"})

# Free text. omp sends this after "Other (type your own)" is chosen, and puts the whole rendered
# widget in the title -- the question, a recap of the options as ○/◉ lines, and "Enter your
# response:". Unrecognised, it rendered as a question card with the radio glyphs inside it and the
# turn sat there (frame log, 2026-08-05). The question is the first line; the rest is the widget
# drawing itself, which the panel has already drawn its own way.
_EDITOR_METHOD = "editor"

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

# Paths the skill legitimately owns inside a project.
_SKILL_OWNED = ("process/", "state/", "dsp_profile.json", "dsp_profile.draft.json",
                "project.json", "autosound_context.md", "tuning-changelog", "audit-trail.md")


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
        "# Written by TCC. Without this, TCC's MCP tools are mounted under xd:// device URLs\n"
        "# and never enter the model's function list -- measured, see spike/HANDOFF.md 5-bis.\n"
        "tools:\n  xdev: false\n",
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
    ) -> None:
        self.project_dir = Path(project_dir or config.project_dir())
        self.bridge: UiBridge = bridge or HeadlessBridge(self.project_dir)
        self.model = model
        self.resume = resume
        self.gate = gate
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

    # ---- wire --------------------------------------------------------------

    def _argv(self) -> list[str]:
        argv = [
            "omp",
            "--mode",
            "rpc-ui",
            "--model",
            self.model,
            "--approval-mode",
            "always-ask",
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
                fh.write(json.dumps({"t": time.time(), "dir": direction, "frame": frame},
                                     ensure_ascii=False)[:8000] + "\n")
        except OSError:
            pass

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
        if frame.get("method") == "confirm":
            self._send({"type": "extension_ui_response", "id": frame.get("id"), "confirmed": allowed})
        else:
            self._send(
                {"type": "extension_ui_response", "id": frame.get("id"),
                 "value": "Approve" if allowed else "Deny"}
            )

    # ---- reading ------------------------------------------------------------

    async def _read_frames(self) -> None:
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
        await self._events.put(None)  # the process ended; unblock whoever is draining

    def _handle(self, frame: dict[str, Any]) -> list[AgentEvent]:
        kind = frame.get("type")
        # Any frame that is not the end of a round means the exchange is still moving, so the
        # grace period restarts. Set here rather than at the bottom: most branches return early.
        if kind != _ROUND_END:
            self._round_ended_at = 0.0

        if kind == "extension_ui_request":
            method = frame.get("method")
            if method in _CHROME_METHODS:
                self._send({"type": "extension_ui_response", "id": frame.get("id"), "cancelled": True})
                return []
            if method != _EDITOR_METHOD and self._is_permission(frame):
                task = asyncio.create_task(self._gate(frame))
                self._pending.add(task)
                task.add_done_callback(self._pending.discard)
                return []
            return [self._question_from(frame)]

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
            return [ToolCall(name=name, arguments=dict(frame.get("args") or {}))]

        if kind == _EXCHANGE_END:
            return [TurnEnd()]

        if kind == _ROUND_END:
            self._round_ended_at = time.time()
            return []

        return []

    # ---- lifecycle ----------------------------------------------------------

    async def start(self, prompt: Optional[str] = None) -> AsyncIterator[AgentEvent]:
        if not is_available():
            raise OmpNotInstalledError("omp is not on PATH — install it: brew install can1357/tap/omp")
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv(),
            cwd=str(self.project_dir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # omp shells out to the skill, whose scripts are in a git submodule; without this its
            # children drop `__pycache__` into a repo TCC does not own (see vendor_loader).
            env=vendor_loader.child_env(),
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self._await_ready()
        self._send(
            {"id": self._next_id(), "type": "negotiate_protocol",
             "protocolVersion": RPC_PROTOCOL_VERSION}
        )
        await self._await_settled()
        self._reader = asyncio.create_task(self._read_frames())
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
        Chrome frames are answered while waiting, because an unanswered one stalls the agent.

        Capped, so a harness that chatters forever costs a slow first turn rather than a hang.
        """
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        deadline = asyncio.get_running_loop().time() + SETTLE_CAP_S
        while asyncio.get_running_loop().time() < deadline:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=SETTLE_QUIET_S)
            except asyncio.TimeoutError:
                return  # quiet for a full window: startup is done
            if not line:
                raise RuntimeError(self._why("omp exited during startup"))
            try:
                frame = json.loads(line.decode(errors="replace").strip())
            except ValueError:
                continue
            if frame.get("type") == "extension_ui_request" and frame.get("method") in _CHROME_METHODS:
                self._send({"type": "extension_ui_response", "id": frame.get("id"), "cancelled": True})

    async def _await_ready(self) -> None:
        """Wait for omp's `ready` frame rather than sleeping at it.

        `ready` means the RPC channel is negotiable. It does **not** mean the tool list is built --
        that is what `_await_settled` is for.
        """
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        deadline = asyncio.get_running_loop().time() + READY_TIMEOUT_S
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(self._why("omp did not report ready"))
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            if not line:
                raise RuntimeError(self._why("omp exited before reporting ready"))
            try:
                frame = json.loads(line.decode(errors="replace").strip())
            except ValueError:
                continue
            if frame.get("type") == "ready":
                return

    def _opening(self) -> str:
        return (
            "Resume this tuning project. Read state from disk first, call get_tcc_state and "
            "get_pending_signals, then tell me where we are and what the next step is."
            if self.resume
            else "Start a tuning session for this project. Read state from disk, call "
            "get_tcc_state, then tell me where we are and what the next step is."
        )

    async def _prompt(self, text: str) -> AsyncIterator[AgentEvent]:
        self._send({"id": self._next_id(), "type": "prompt", "message": text})
        self._last_frame_at = time.time()
        warned = False
        while True:
            quiet = TURN_QUIET_S if self._round_ended_at else SILENCE_WARN_S
            try:
                event = await asyncio.wait_for(self._events.get(), timeout=quiet)
            except asyncio.TimeoutError:
                if self._round_ended_at:
                    # A round ended and nothing followed: the model has finished talking, whether
                    # or not omp bothers to say `agent_end`.
                    self._round_ended_at = 0.0
                    yield TurnEnd()
                    return
                # Not a cancellation: the turn may still be thinking. But "silent for two minutes"
                # is a fact the Arbiter can act on, and an animated line saying "working" is not.
                if not warned:
                    warned = True
                    yield TextDelta(
                        f"\n\n[{int(SILENCE_WARN_S)}s with no output. "
                        f"{self._why('omp has said nothing.')}]\n\n"
                    )
                continue
            warned = False
            if event is None:  # process ended mid-turn
                return
            yield event
            if isinstance(event, TurnEnd):
                return

    async def send(self, text: str) -> AsyncIterator[AgentEvent]:
        if self._proc is None:
            raise RuntimeError("call start() before send()")
        async for event in self._prompt(text):
            yield event

    async def answer(self, question_id: str, value: str) -> None:
        """Deliver the Arbiter's answer to a parked question. Free text is passed through as-is —
        omp adds an "Other (type your own)" option to every question and accepts the typed value."""
        self._send({"type": "extension_ui_response", "id": question_id, "value": value})

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
