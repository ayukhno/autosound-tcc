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
import shutil
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

DEFAULT_MODEL = "gemini-3.1-pro-preview"

# The version omp actually accepts. It advertises `[1, 2]` in its `ready` frame and then rejects 1
# with "Unsupported RPC protocol version" -- checked, not assumed.
RPC_PROTOCOL_VERSION = 2

# Frames omp raises for its own chrome. Answering them `cancelled` is how the host says "I am not
# that kind of UI"; leaving them unanswered stalls the agent.
_CHROME_METHODS = frozenset({"setWidget", "setTitle", "set_editor_text", "notify"})

# omp's own wording on a permission prompt. Matched together with the option shape, and a frame
# that satisfies neither is still treated as a permission -- see `_is_permission`.
_PERMISSION_TITLE_PREFIX = "Allow tool: "
_PERMISSION_OPTIONS = frozenset({"Approve", "Deny"})

# The tool omp uses to ask the human. Its call is rendered as the question itself, so it must not
# also arrive as a process chip.
_ASK_TOOL = "ask"

CONFIRM_TIMEOUT_S = 600.0
READY_TIMEOUT_S = 60.0

# `ready` means the RPC channel is up, NOT that the tool list is built: omp connects its MCP
# servers and loads plugins after it, and announces neither. Prompting on `ready` gets a turn whose
# model never saw TCC's tools -- measured: 17 tools offered instead of 203, none of them `tcc`.
# So after `ready` we wait for the wire to go quiet, which adapts to a cold start instead of
# guessing at it the way the spike's fixed twelve-second sleep did.
SETTLE_QUIET_S = 1.0
SETTLE_CAP_S = 45.0


class OmpNotInstalledError(RuntimeError):
    """`omp` is not on PATH. Fix: `brew install can1357/tap/omp`."""


def is_available() -> bool:
    return shutil.which("omp") is not None


def _overlay_path(project_dir: Path) -> Path:
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
    ) -> None:
        self.project_dir = Path(project_dir or config.project_dir())
        self.bridge: UiBridge = bridge or HeadlessBridge(self.project_dir)
        self.model = model
        self.resume = resume
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._events: asyncio.Queue[Optional[AgentEvent]] = asyncio.Queue()
        self._reader: Optional[asyncio.Task] = None
        self._pending: set[asyncio.Task] = set()
        self._frame_id = 0

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
            str(_overlay_path(self.project_dir)),
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
        proc.stdin.write((json.dumps(frame) + "\n").encode())

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

        Ambiguity resolves to *permission*, and the reason is narrower than "be safe". Neither
        mistake lets a tool through: a permission rendered as a question is simply never answered,
        so the tool stays blocked. What that costs is a turn parked forever on a card nobody can
        act on -- the hang this whole channel exists to prevent -- and a decision that never
        reached the audited `ConfirmRequest` path. Treating the unknown as a permission puts it in
        front of the Arbiter through the gate they already recognise; the cost is a confirmation
        they did not expect, which they can read and refuse.
        """
        if frame.get("method") == "confirm":
            return True
        title = str(frame.get("title") or "")
        options = {str(option) for option in (frame.get("options") or [])}
        if _PERMISSION_OPTIONS & options:
            return True
        # A question is recognised by carrying its own options; anything that offers no choice at
        # all is not a question the Arbiter could answer.
        return title.startswith(_PERMISSION_TITLE_PREFIX) or not options

    @staticmethod
    def _question_from(frame: dict[str, Any]) -> Question:
        options = tuple(
            QuestionOption(label=str(option)) for option in (frame.get("options") or [])
        )
        return Question(
            id=str(frame.get("id") or ""),
            question=str(frame.get("title") or ""),
            options=options,
        )

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
        # TCC's own tools raise their own confirmation inside the tool, so gating here as well
        # would prompt the Arbiter twice for one action and teach them to click through both.
        if tool.startswith("mcp__tcc"):
            self._answer_frame(frame, True)
            return
        request = ConfirmRequest(
            tool=tool,
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
            for event in self._handle(frame):
                await self._events.put(event)
        await self._events.put(None)  # the process ended; unblock whoever is draining

    def _handle(self, frame: dict[str, Any]) -> list[AgentEvent]:
        kind = frame.get("type")

        if kind == "extension_ui_request":
            method = frame.get("method")
            if method in _CHROME_METHODS:
                self._send({"type": "extension_ui_response", "id": frame.get("id"), "cancelled": True})
                return []
            if self._is_permission(frame):
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

        if kind == "turn_end":
            return [TurnEnd()]

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
            stderr=asyncio.subprocess.DEVNULL,
            # omp shells out to the skill, whose scripts are in a git submodule; without this its
            # children drop `__pycache__` into a repo TCC does not own (see vendor_loader).
            env=vendor_loader.child_env(),
        )
        await self._await_ready()
        self._send(
            {"id": self._next_id(), "type": "negotiate_protocol",
             "protocolVersion": RPC_PROTOCOL_VERSION}
        )
        await self._await_settled()
        self._reader = asyncio.create_task(self._read_frames())
        async for event in self._prompt(prompt or self._opening()):
            yield event

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
                raise RuntimeError("omp exited during startup")
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
                raise TimeoutError("omp did not report ready")
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            if not line:
                raise RuntimeError("omp exited before reporting ready")
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
        while True:
            event = await self._events.get()
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
        for task in list(self._pending):
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
