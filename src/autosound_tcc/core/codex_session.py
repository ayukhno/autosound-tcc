"""The tuning conversation driven by `codex app-server` — Codex as TCC's Generator (W-10, tcc#181).

The third adapter behind `core.agent_events.AgentSession`, in `OmpSession`'s shape: one long-lived
process per session, its stdout read by one reader (`codex_rpc.AppServer`), every turn a generator
that returns only when the turn is over. What it owes the dialog is the same vocabulary the other
two speak (`docs/PLAN-W-10-codex.md`, «The session»):

* **Start** — the binding first (a copy TCC will not run starts nothing); a short probe of the
  user's own Codex (`account/read`: signed out refuses here, with the reason; `config/read`: which
  of the user's extras to switch off); then the session's own app-server with the isolation list
  and TCC's MCP server (`codex_cli.isolation_args`, `codex_cli.tcc_tool_args`), the token only in
  the environment; the method's skill as the one extra skill root, checked; the effort clamped to
  what the model takes; a thread started or resumed (a failed resume says so and starts afresh);
  the thread bound to the phase on the Codex route at once.
* **Turns** — `turn/start`, the open-signals brief in front of the text (F-009, as on the other
  routes), and the notifications mapped to `agent_events` until `turn/completed` or the process
  ending. `TurnEnd` is the last event of a turn and only ever the last.
* **Codex's own requests** — answered exactly once, through `AppServer.respond` (it refuses a
  second answer). TCC's MCP server's elicitation is accepted (its tools gate themselves inside the
  tool); command and file-change approvals are DECLINED in this build — task 7 puts TCC's gate
  (`shell_gate.judge_action`) there; anything else is a JSON-RPC error.

Qt-free; everything runs on the worker's loop (`ui.tcc.agent_worker`).
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from autosound_tcc.core import (app_log, child, codex_cli, codex_rpc, config, critic,
                                method_binding, model_choices, openers, signal_bus,
                                vendor_loader)
from autosound_tcc.core.agent_events import AgentEvent, Notice, TextDelta, ToolCall, ToolEnd, TurnEnd
from autosound_tcc.core.mcp_server import CONFIRM_TIMEOUT_S, HeadlessBridge, UiBridge
from autosound_tcc.core.omp_session import FRAME_LOG_MAX_BYTES
from autosound_tcc.core.session_registry import CODEX_ROUTE, SessionRegistry
from autosound_tcc.core.shell_gate import GATE_WRITES
from autosound_tcc.core.tuning_session import SKILL_NAME, _read_roots_for, system_prompt_append

#: Every frame both ways, next to the project's other TCC state — omp's `omp-frames.jsonl`, for the
#: same reason: the frames are the only place a stuck turn can be read afterwards.
FRAME_LOG = "codex-frames.jsonl"
#: How long a turn may say nothing before the window is told (nothing is cancelled).
SILENCE_WARN_S = 120.0
#: One request to the session's app-server that is not a turn.
REQUEST_TIMEOUT_S = 60.0
#: How long Codex waits for one of TCC's MCP tools: above a confirmation's and a review's limits —
#: Codex's own ~60 s default would cut either (omp's `OMP_TOOL_TIMEOUT_MS`, for the same reason).
TOOL_TIMEOUT_S = int(max(CONFIRM_TIMEOUT_S, critic.DEFAULT_TIMEOUT_S) + 60)

#: The requests Codex sends before it runs something; task 7 answers them from TCC's gate.
COMMAND_APPROVAL = "item/commandExecution/requestApproval"
FILE_APPROVAL = "item/fileChange/requestApproval"
ELICITATION = "mcpServer/elicitation/request"

#: `/bin/zsh -lc '…'` — how Codex on macOS/Linux wraps every command it runs.
_SHELL_WRAPPER = re.compile(r"^(?:\S*/)?(?:zsh|bash|sh)\s+-l?c\s+(.+)$", re.S)

#: Item types that are tools, and the names the panel (and the gate) know them by.
_COMMAND, _FILE_CHANGE, _MCP_CALL, _AGENT_MESSAGE = (
    "commandExecution", "fileChange", "mcpToolCall", "agentMessage")


class CodexNotInstalled(RuntimeError):
    """No Codex on this machine TCC can start."""


class CodexSignedOut(RuntimeError):
    """Codex is installed and has no login: a session would fail at its first turn."""


class CodexStartFailed(RuntimeError):
    """Codex could not be started or did not open a conversation; carries why."""


def inner_command(command: str) -> str:
    """The command inside Codex's shell wrapper — `/bin/zsh -lc 'echo hi'` → `echo hi`. Anything
    that does not parse as exactly one wrapped argument is returned whole (a PowerShell line, a
    command with no wrapper), so nothing is ever hidden by the unwrapping."""
    text = (command or "").strip()
    match = _SHELL_WRAPPER.match(text)
    if not match:
        return command
    try:
        parts = shlex.split(match.group(1))
    except ValueError:
        return command
    return parts[0] if len(parts) == 1 else command


class CodexSession:
    """A tuning conversation bound to one project folder, run by a `codex app-server` process."""

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        bridge: Optional[UiBridge] = None,
        model: str = "",
        resume: bool = False,
        gate: str = GATE_WRITES,
        always_allowed: Optional[frozenset[str]] = None,
        effort: Optional[str] = None,
        language: str = "en",
        mcp_url: Optional[str] = None,
        mcp_token: Optional[str] = None,
        *,
        binary: Optional[str] = None,
    ) -> None:
        self.project_dir = Path(project_dir or config.project_dir())
        self.bridge: UiBridge = bridge or HeadlessBridge(self.project_dir)
        self.model = model or ""
        # TCC's level (high/xhigh/max); the word Codex gets is chosen at start, from what the
        # model's `model/list` entry offers (`model_choices.codex_effort`).
        self.effort = model_choices.resolve_effort(effort)
        self.resume = resume
        # Read at decision time, never copied into a closure: the window narrows them mid-session
        # and the next request must see it (task 7 reads both per request).
        self.gate = gate
        self.always_allowed = always_allowed or frozenset()
        self.language = language
        self.mcp_url = mcp_url
        self.mcp_token = mcp_token
        #: The `codex` to start; None = `codex_cli.find()` at start. The tests pass the stand-in.
        self.binary = binary
        self.registry = SessionRegistry(config.tcc_dir(self.project_dir))
        #: Codex's thread id — what a later launch on the Codex route resumes.
        self.session_id: Optional[str] = None
        #: Whether this session continued a thread (a failed resume starts afresh and says so).
        self.resumed = False
        #: The UI's signal bus (F-009), assigned by `AgentWorker`; None in headless runs.
        self.bus: Optional[signal_bus.SignalBus] = None
        self._read_roots: tuple[Path, ...] = ()
        self._server: Optional[codex_rpc.AppServer] = None
        self._codex_effort = "high"
        self._log_path = config.tcc_dir(self.project_dir) / FRAME_LOG
        self._bound_phase: Optional[str] = None
        # The turn in flight: its id (for `turn/interrupt`), what streamed, what is running.
        self._turn_id: Optional[str] = None
        self._streamed: set[str] = set()
        self._running: dict[str, str] = {}     # itemId -> the ToolCall name it was shown as
        self._running_label = ""               # what the silence notice names
        #: fileChange paths by itemId: the approval request names only the item (task 7).
        self._paths: dict[str, list[str]] = {}
        self._retry_said = False
        self._last_error = ""
        self._getter: Optional[asyncio.Future] = None
        # Stop (task 6's review, I2). `_turn_open`: a turn is wanted — from `start` on, through each
        # `_turn` — so a Stop between turns cancels nothing. `_interrupt_wanted`: a Stop came
        # before the turn had an id; it is carried out the moment the id is known (the reply or
        # `turn/started`), or, before the message went out, by not sending it.
        self._turn_open = False
        self._interrupt_wanted = False
        self._tasks: set[asyncio.Task] = set()

    # ---- start --------------------------------------------------------------------------------

    async def start(self, prompt: Optional[str] = None) -> AsyncIterator[AgentEvent]:
        """Start Codex and run the opening turn. A refusal before the process exists raises
        (`MethodRefused`, `CodexNotInstalled`, `CodexSignedOut`, `CodexStartFailed`) — the worker
        shows a failed start as a failed bubble, as it does for omp.

        A Stop while Codex is still starting skips the opening turn: no message is sent, the
        opening ends at once and says so (`_turn`)."""
        self._turn_open = True
        try:
            notices = await self._open(prompt)
        except BaseException:
            self._turn_open = False
            self._interrupt_wanted = False
            raise
        for notice in notices:
            yield notice
        opening = openers.opening_prompt(resumed=self.resumed, typed=prompt or "")
        async for event in self._turn(opening):
            yield event

    async def _open(self, prompt: Optional[str]) -> list[AgentEvent]:
        """Everything before the opening turn; the Notices it has to say."""
        binding = method_binding.for_project(self.project_dir)
        try:
            skill_dir = binding.require()
        except method_binding.MethodRefused as exc:
            app_log.logger().warning("refused: the Codex session on %s did not start: %s",
                                     self.project_dir, exc)
            raise
        self._read_roots = _read_roots_for(self.project_dir, binding)
        vendor_loader.link_skill_into(self.project_dir)
        binary = self._binary()
        env = self._env(binding)
        notices: list[AgentEvent] = []
        config_read = await self._probe(binary, env)
        if config_read is None:
            config_read = {}
            notices.append(Notice(
                "Codex did not show TCC its config, so the MCP servers in it stay on in this "
                "session — TCC could not name them to switch them off."))
        if unsafe := codex_cli.unsafe_server_names(config_read):
            notices.append(Notice(
                "Codex's own config has MCP servers TCC cannot switch off for this session — "
                f"their names cannot be passed to Codex as a setting: {', '.join(unsafe)}. They "
                "stay on in this session."))
        unknown = codex_cli.unknown_enabled_features(config_read)
        if unknown:
            app_log.logger().warning("codex: features enabled in the user's config that TCC has "
                                     "not classified, left as they are: %s", ", ".join(unknown))
        await self._spawn(binary, env, config_read)
        notices += await self._load_skill(skill_dir)
        await self._clamp_effort()
        notices += await self._open_thread()
        self._bind()
        return notices

    def _redact(self, text: str) -> str:
        """`text` without TCC's token: a start's refusal carries Codex's stderr, and a user's own
        `RUST_LOG=trace` prints request headers there (task 6's review, M5)."""
        return text.replace(self.mcp_token, codex_rpc.REDACTED) if self.mcp_token else text

    def _start_failed(self, said: str) -> CodexStartFailed:
        return CodexStartFailed(self._redact(said))

    def _binary(self) -> str:
        if self.binary:
            return str(self.binary)
        found = codex_cli.find()
        if found is None:
            raise CodexNotInstalled(
                "Codex is not installed on this computer (or not where TCC looks for it), so the "
                "session cannot start. Install Codex, then start the session again.")
        return found.path

    def _env(self, binding: method_binding.Binding) -> dict[str, str]:
        """The session's environment: the reviewer the Arbiter picked and which copy of the method
        runs (merged as on the other routes, the binding last). The token is added at spawn."""
        return vendor_loader.child_env(**{**critic.session_env(self.project_dir),
                                          **binding.session_env()})

    async def _probe(self, binary: str, env: dict[str, str]) -> Optional[dict]:
        """One short app-server before the session's own: the login (signed out refuses the
        start here, before a turn fails on it) and the user's config, which decides the isolation
        list — it has to be known before the session's process is started with it. None when
        Codex would not show its config."""
        try:
            account, config_read = await codex_rpc.ask(
                binary, [("account/read", {}), ("config/read", {"cwd": str(self.project_dir)})],
                timeout=codex_cli.PROBE_TIMEOUT_S, cwd=str(self.project_dir), env=env)
        except TimeoutError:
            raise CodexStartFailed(
                f"Codex gave no answer in {int(codex_cli.PROBE_TIMEOUT_S)} s, so the session "
                "did not start.") from None
        except codex_rpc.ConnectionLost as exc:
            raise self._start_failed(f"Codex did not start: {exc}") from exc
        if codex_cli._signed_in_from(account) is False:
            raise CodexSignedOut(
                "Codex is not signed in on this computer, so the session cannot start. Sign in to "
                "Codex (`codex login` in a terminal), then start the session again.")
        if isinstance(config_read, codex_rpc.RpcError):
            app_log.logger().warning("codex: config/read refused (%s); only TCC's own switches "
                                     "are set, the user's MCP servers stay as configured",
                                     config_read.message)
            return None
        return config_read

    async def _spawn(self, binary: str, env: dict[str, str], config_read: dict) -> None:
        argv = [binary, "app-server", *codex_cli.isolation_args(config_read)]
        secrets: tuple[str, ...] = ()
        env = dict(env)
        if self.mcp_url:
            argv += codex_cli.tcc_tool_args(self.mcp_url, timeout_sec=TOOL_TIMEOUT_S)
        if self.mcp_token:
            # By name in argv (`env_http_headers`), by value only here: no argv, no log line, and
            # no shell Codex starts (`shell_environment_policy.exclude`) ever holds it.
            env[codex_cli.TOKEN_ENV] = self.mcp_token
            secrets = (codex_cli.TOKEN_ENV,)
        self._server = codex_rpc.AppServer(
            argv, cwd=self.project_dir, env=env, spawn_kwargs=self._spawn_kwargs(),
            log=self._frame_log(), on_request=self._on_request, secret_env=secrets,
            log_cap=FRAME_LOG_MAX_BYTES)
        try:
            await self._server.open()
        except codex_rpc.ConnectionLost as exc:
            raise self._start_failed(f"Codex did not start: {exc}") from exc
        except TimeoutError as exc:
            raise self._start_failed(f"Codex did not answer at start: {exc}") from exc
        # Codex starts a shell per command; on Windows they inherit this console, hidden, rather
        # than each opening a window of its own (`child.agent_console`). No-op elsewhere.
        child.hide_agent_console_later(self._server.pid or 0)

    @staticmethod
    def _spawn_kwargs() -> dict:
        """The agent's own console where Windows needs one to hand down (as the SDK route's
        `claude` gets, `child.hide_console_windows`), else no window at all."""
        return child.agent_console() or child.flags()

    def _frame_log(self) -> Path:
        """The frame log's path, its folder made. `AppServer` rotates it to `.1` at the cap
        (omp's cap) and goes on writing, counting from the size it already has."""
        path = self._log_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            app_log.logger().warning("codex: no folder for the frame log %s: %s", path, exc)
        return path

    async def _request(self, method: str, params: dict) -> dict:
        """A start-time request. Codex ending meanwhile is the start failing, said with why."""
        assert self._server is not None
        try:
            return await self._server.request(method, params, timeout=REQUEST_TIMEOUT_S)
        except codex_rpc.ConnectionLost as exc:
            raise self._start_failed(f"Codex stopped while starting ({method}): {exc}") from exc

    async def _load_skill(self, skill_dir: Path) -> list[AgentEvent]:
        """The method as Codex's one extra skill root: the project's own `.claude/skills`, where
        its link to the bound copy is. Checked with `skills/list`: an `autosound-tuning` from
        anywhere else (the user's own Codex skills) would be a second copy the model could load,
        and that refuses the start, as the binding refuses a copy TCC does not run."""
        root = self.project_dir / ".claude" / "skills"
        try:
            await self._request("skills/extraRoots/set", {"extraRoots": [str(root)]})
        except (codex_rpc.RpcError, TimeoutError) as exc:
            app_log.logger().warning("codex: skills/extraRoots/set refused: %s", exc)
            return [self._no_skill_notice()]
        try:
            listed = await self._request("skills/list",
                                         {"cwds": [str(self.project_dir)], "forceReload": True})
        except (codex_rpc.RpcError, TimeoutError) as exc:
            app_log.logger().warning("codex: skills/list refused, the method's skill unchecked: %s",
                                     exc)
            return [Notice(
                "Codex did not list its skills, so which copy of the tuning method it loads is "
                "unchecked: a second copy in Codex's own skills would not be noticed.")]
        ours = {os.path.normcase(os.path.realpath(skill_dir / "SKILL.md")),
                os.path.normcase(os.path.realpath(root / SKILL_NAME / "SKILL.md")),
                os.path.normcase(str(root / SKILL_NAME / "SKILL.md"))}
        found = False
        for group in listed.get("data") or []:
            for skill in (group or {}).get("skills") or []:
                if not isinstance(skill, dict) or skill.get("name") != SKILL_NAME:
                    continue
                path = str(skill.get("path") or "")
                if os.path.normcase(os.path.realpath(path)) in ours \
                        or os.path.normcase(path) in ours:
                    found = True
                    continue
                said = (f"Codex also offers a copy of the method at {path}, besides the one this "
                        f"project runs ({skill_dir}), and a session could load either; remove it "
                        f"from Codex's skills, then start the session again.")
                app_log.logger().warning("refused: the Codex session on %s did not start: %s",
                                         self.project_dir, said)
                raise method_binding.MethodRefused(said)
        return [] if found else [self._no_skill_notice()]

    def _no_skill_notice(self) -> Notice:
        return Notice(
            f"Codex did not load the tuning method from this project's `.claude/skills/"
            f"{SKILL_NAME}`. The session will run without it and improvise one — do not trust "
            "anything it says until the method is loaded.")

    async def _clamp_effort(self) -> None:
        """The effort as this model takes it, from this app-server's `model/list` (the picker's
        last probe when the list cannot be read)."""
        supported: tuple[str, ...] = ()
        cursor = None
        try:
            for _page in range(codex_cli.MAX_PAGES):
                params: dict[str, Any] = {"limit": codex_cli.PAGE_LIMIT}
                if cursor:
                    params["cursor"] = cursor
                page = await self._request("model/list", params)
                supported = codex_cli.efforts_in(page.get("data") or [], self.model)
                cursor = page.get("nextCursor")
                if supported or not cursor:
                    break
        except (codex_rpc.RpcError, TimeoutError) as exc:
            app_log.logger().warning("codex: model/list refused (%s); the effort is clamped from "
                                     "the last probe", exc)
        if not supported:
            supported = codex_cli.supported_efforts(self.model)
        self._codex_effort = model_choices.codex_effort(self.effort, supported)

    def _thread_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "cwd": str(self.project_dir),
            # Codex asks before anything that is not a read, and asks the client (TCC), never a
            # reviewer of its own; the sandbox is off and TCC's gate is the guard — as on the
            # Claude and omp routes (the plan: Seatbelt with no network blocks REW on loopback).
            "approvalPolicy": "untrusted",
            "approvalsReviewer": "user",
            "sandbox": "danger-full-access",
            "developerInstructions": system_prompt_append(self.language),
        }
        if self.model:
            params["model"] = self.model
        return params

    async def _open_thread(self) -> list[AgentEvent]:
        """`thread/resume` of the phase's Codex thread when the launch resumes, else — or when the
        resume fails — `thread/start`."""
        notices: list[AgentEvent] = []
        params = self._thread_params()
        reply: Optional[dict] = None
        previous = self.registry.resumable_session(route=CODEX_ROUTE) if self.resume else None
        try:
            if previous:
                try:
                    reply = await self._request("thread/resume", {
                        **params, "threadId": previous, "excludeTurns": True})
                    self.resumed = True
                except codex_rpc.RpcError as exc:
                    app_log.logger().warning("codex: thread/resume of %s refused: %s",
                                             previous, exc.message)
                    notices.append(Notice(
                        f"Codex could not continue the last conversation ({exc.message}); a new "
                        "one starts. The project's state is on disk, so the session reads it "
                        "again."))
            if reply is None:
                reply = await self._request("thread/start", params)
        except codex_rpc.RpcError as exc:
            raise self._start_failed(f"Codex did not open a conversation: {exc.message}") from exc
        except TimeoutError as exc:
            raise CodexStartFailed(f"Codex did not open a conversation: {exc}") from exc
        thread_id = ((reply or {}).get("thread") or {}).get("id")
        if not thread_id:
            raise CodexStartFailed("Codex opened a conversation without an id, so it could not "
                                   "be resumed later; the session did not start.")
        self.session_id = str(thread_id)
        return notices

    def _bind(self) -> None:
        """The thread to the current phase, on the Codex route — at once, and again when the phase
        moved during a turn (the SDK route binds its id per result the same way)."""
        if not self.session_id:
            return
        try:
            phase = self.registry.current_phase()
            if phase and phase != self._bound_phase:
                self.registry.bind_session(phase, self.session_id, route=CODEX_ROUTE)
                self._bound_phase = phase
        except Exception as exc:  # noqa: BLE001 — bookkeeping must not end a running session
            app_log.logger().warning("codex: the thread %s could not be bound to its phase: %s",
                                     self.session_id, exc)

    # ---- Codex's requests -----------------------------------------------------------------------

    def _on_request(self, msg: dict) -> None:
        """Every request Codex sends, answered once, here (the reader calls this)."""
        server = self._server
        if server is None:
            return
        rid, method = msg.get("id"), str(msg.get("method") or "")
        params = msg.get("params") or {}
        if method == ELICITATION:
            if params.get("serverName") == "tcc":
                # TCC's tools gate themselves inside the tool (`mcp_server._confirm`): asking here
                # too would put two prompts in front of every change.
                server.respond(rid, {"action": "accept", "content": {}})
            else:
                server.respond(rid, {"action": "decline"})
            return
        if method in (COMMAND_APPROVAL, FILE_APPROVAL):
            # TASK 7 puts TCC's gate here (`shell_gate.judge_action`, then `await_confirmation`).
            # Until then nothing Codex asks to run, runs: a decline, never an accept — and never
            # `acceptForSession`, which would make Codex the memory of what was allowed.
            app_log.logger().info("codex: %s %r declined (the gate comes with task 7)", method, rid)
            server.respond(rid, {"decision": "decline"})
            return
        app_log.logger().warning("codex: a request TCC does not handle, answered with an error: %s",
                                 method)
        server.respond(rid, error={"code": codex_rpc.METHOD_NOT_FOUND,
                                   "message": f"TCC does not handle {method}"})

    # ---- turns ----------------------------------------------------------------------------------

    async def send(self, text: str) -> AsyncIterator[AgentEvent]:
        if self._server is None:
            raise RuntimeError("call start() before send()")
        async for event in self._turn(text):
            yield event

    async def _turn(self, text: str) -> AsyncIterator[AgentEvent]:
        """One turn. `turn/start` is not awaited on its own: its reply is read together with the
        notifications (task 6's review, I1 — the reply kept alive while reading), so a reply that
        never comes cannot leave the turn waiting for a `turn/completed` nothing will send — no
        turn id by `REQUEST_TIMEOUT_S` ends the turn, said."""
        server = self._server
        self._retry_said = False
        self._last_error = ""
        self._turn_open = True
        reply: Optional[asyncio.Future] = None
        try:
            if server is None or server.ended:
                yield self._ended_notice()
                return
            if self._interrupt_wanted:
                # Stop came while Codex was still starting: the message is not sent at all.
                yield Notice("Stopped before Codex got the message; nothing was sent.")
                yield TurnEnd(self.session_id)
                return
            params: dict[str, Any] = {
                "threadId": self.session_id,
                # The F-009 injection point: every turn — the opener included — carries the
                # signals the Arbiter raised and the model has not acknowledged.
                "input": [{"type": "text", "text": signal_bus.with_pending_brief(self.bus, text)}],
                "effort": self._codex_effort,
            }
            if self.model:
                params["model"] = self.model
            reply = asyncio.ensure_future(
                server.request("turn/start", params, timeout=REQUEST_TIMEOUT_S))
            async for event in self._read_turn(server, reply):
                yield event
        finally:
            # The turn is over — completed, or Codex died mid-turn, or the worker cancelled it.
            # Signals the turn read but never acknowledged go back to pending, so the next turn's
            # brief raises them again (F-009, as on the other routes).
            self._turn_open = False
            self._interrupt_wanted = False
            if reply is not None:
                if not reply.done():
                    reply.cancel()
                elif not reply.cancelled():
                    reply.exception()  # read, so a refusal handled here is not «never retrieved»
            self._turn_id = None
            self._streamed.clear()
            self._running.clear()
            self._running_label = ""
            self._paths.clear()
            self._drop_getter()
            if self.bus is not None:
                self.bus.restore_delivered()

    async def _read_turn(self, server: codex_rpc.AppServer,
                         reply: Optional[asyncio.Future]) -> AsyncIterator[AgentEvent]:
        """The turn's reply and notifications as `agent_events`, until `turn/completed`, the end
        of the process, a refused `turn/start`, or no turn at all."""
        warned = False
        while True:
            if self._getter is None:
                # One getter outlives a silence, so a notification arriving at that moment is
                # never lost.
                self._getter = asyncio.ensure_future(server.notifications.get())
            getter = self._getter
            waiting = {getter} if reply is None else {getter, reply}
            done, _ = await asyncio.wait(waiting, timeout=SILENCE_WARN_S,
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done:
                if not warned:
                    # Not a timeout — nothing is cancelled — but two silent minutes are a fact the
                    # Arbiter can act on, and which item is running is the useful half of it.
                    warned = True
                    where = (f"Still inside {self._running_label}." if self._running_label
                             else "Codex has said nothing.")
                    yield Notice(f"{int(SILENCE_WARN_S)}s with no output. {where}")
                continue
            if reply is not None and reply in done:
                answered, reply = reply, None
                events, over = self._on_reply(answered)
                for event in events:
                    yield event
                if over:
                    return
            if getter in done:
                self._getter = None
                warned = False
                msg = getter.result()
                if msg is None:
                    yield self._ended_notice()
                    return
                events, over = self._map(msg)
                for event in events:
                    yield event
                if over:
                    return

    def _on_reply(self, reply: asyncio.Future) -> tuple[list[AgentEvent], bool]:
        """`turn/start`'s reply → the turn's id, or why there is no turn."""
        try:
            result = reply.result()
        except codex_rpc.RpcError as exc:
            # No turn started, so none will complete: the turn ends here, said.
            return [Notice(f"Codex refused the message: {exc.message}"),
                    TurnEnd(self.session_id)], True
        except codex_rpc.ConnectionLost:
            return [], False  # the notifications end too, and that end says why
        except TimeoutError:
            if self._turn_id:
                return [], False  # `turn/started` named it; the turn goes on
            app_log.logger().warning("codex: turn/start not confirmed in %g s and no turn/started",
                                     REQUEST_TIMEOUT_S)
            return [Notice(f"Codex did not start the turn in {int(REQUEST_TIMEOUT_S)} s, so it "
                           "ended here. Send the message again."), TurnEnd(self.session_id)], True
        self._turn_id = self._turn_id or ((result.get("turn") or {}).get("id")) or None
        self._interrupt_if_wanted()
        return [], False

    def _interrupt_if_wanted(self) -> None:
        """A Stop that came before the turn had an id, carried out now that it has one."""
        if self._interrupt_wanted and self._turn_id:
            self._interrupt_wanted = False
            task = asyncio.ensure_future(self._send_interrupt())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _drop_getter(self) -> None:
        getter, self._getter = self._getter, None
        if getter is not None and not getter.done():
            getter.cancel()

    def _map(self, msg: dict) -> tuple[list[AgentEvent], bool]:
        """One notification → the events it means, and whether the turn is over."""
        method = msg.get("method")
        params = msg.get("params") or {}
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        of_turn = params.get("turnId") or turn.get("id")
        if method == "turn/started":
            self._turn_id = self._turn_id or of_turn
            self._interrupt_if_wanted()
            return [], False
        if self._turn_id and of_turn and of_turn != self._turn_id:
            return [], False  # another turn's: nothing of this one
        if method == "item/agentMessage/delta":
            delta = params.get("delta")
            if not delta:
                return [], False
            self._streamed.add(str(params.get("itemId") or ""))
            return [TextDelta(str(delta))], False
        if method == "item/started":
            return self._item_started(params.get("item") or {}), False
        if method == "item/completed":
            return self._item_completed(params.get("item") or {}), False
        if method == "turn/completed":
            events: list[AgentEvent] = []
            if turn.get("status") == "failed":
                said = str((turn.get("error") or {}).get("message") or "the turn failed")
                if said != self._last_error:
                    events.append(Notice(f"Codex: {said}"))
            self._bind()
            events.append(TurnEnd(self.session_id))
            return events, True
        if method == "error":
            said = str((params.get("error") or {}).get("message") or "an error")
            if params.get("willRetry"):
                if self._retry_said:
                    return [], False  # one line per storm, not one per attempt
                self._retry_said = True
                return [Notice(f"Codex is retrying: {said}")], False
            self._last_error = said
            return [Notice(f"Codex: {said}")], False
        # Deprecations, config warnings, token usage, rate limits, status: the frame log has them.
        return [], False

    def _item_started(self, item: dict) -> list[AgentEvent]:
        kind, item_id = item.get("type"), str(item.get("id") or "")
        if kind == _MCP_CALL:
            # `mcp__<server>__<tool>`, the SDK's spelling: the gate's `mcp__tcc` prefix holds.
            name = f"mcp__{item.get('server') or '?'}__{item.get('tool') or '?'}"
            arguments = item.get("arguments")
            self._running[item_id] = name
            self._running_label = f"`{name}`"
            return [ToolCall(name, dict(arguments) if isinstance(arguments, dict) else {})]
        if kind == _COMMAND:
            command = inner_command(str(item.get("command") or ""))
            self._running[item_id] = "Bash"
            self._running_label = f"`{command[:120]}`"
            return [ToolCall("Bash", {"command": command})]
        if kind == _FILE_CHANGE:
            paths = [str(change.get("path")) for change in item.get("changes") or []
                     if isinstance(change, dict) and change.get("path")]
            self._paths[item_id] = paths
            self._running[item_id] = "Edit"
            self._running_label = "an edit of " + (", ".join(paths[:3]) or "a file")
            return [ToolCall("Edit", {"paths": paths})]
        return []

    def _item_completed(self, item: dict) -> list[AgentEvent]:
        kind, item_id = item.get("type"), str(item.get("id") or "")
        if kind == _AGENT_MESSAGE:
            streamed = item_id in self._streamed
            self._streamed.discard(item_id)
            text = str(item.get("text") or "")
            # A message Codex did not stream arrives whole, once, here.
            return [TextDelta(text)] if text and not streamed else []
        if item_id in self._running:
            name = self._running.pop(item_id)
            if not self._running:
                self._running_label = ""
            return [ToolEnd(name)]
        return []

    def _ended_notice(self) -> Notice:
        """What a turn says when Codex is gone: its exit code and the last lines it wrote."""
        server = self._server
        code = server.returncode if server is not None else None
        tail = "\n".join((server.stderr_tail if server is not None else "").splitlines()[-5:])
        if self.mcp_token:
            tail = tail.replace(self.mcp_token, codex_rpc.REDACTED)
        said = ("Codex has stopped" + (f" (exit code {code})" if code is not None else "")
                + ", so this session cannot go on. Start a new session.")
        if tail.strip():
            said += "\n" + tail.strip()
        app_log.logger().warning("codex: %s", said.replace("\n", " | "))
        return Notice(said)

    # ---- the rest of the contract ---------------------------------------------------------------

    async def answer(self, question_id: str, value: str) -> None:
        """No question channel on this route (as on the SDK route)."""

    async def cancel_question(self, question_id: str) -> None:
        """No question channel on this route."""

    async def interrupt(self) -> None:
        """Stop: `turn/interrupt` for the turn in flight. The turn still ends through its own
        `turn/completed` (status `interrupted`), so `TurnEnd` stays the turn's last event. Before
        the turn has an id — Codex still starting, or `turn/start` not answered yet — the Stop is
        kept and carried out when the id is known; between turns it does nothing."""
        if not self._turn_open:
            return
        if not (self._server is not None and self.session_id and self._turn_id):
            self._interrupt_wanted = True
            return
        await self._send_interrupt()

    async def _send_interrupt(self) -> None:
        server, thread_id, turn_id = self._server, self.session_id, self._turn_id
        if server is None or server.ended or not (thread_id and turn_id):
            return
        try:
            await server.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id},
                                 timeout=REQUEST_TIMEOUT_S)
        except (codex_rpc.RpcError, codex_rpc.ConnectionLost, TimeoutError) as exc:
            app_log.logger().warning("codex: turn/interrupt of %s failed: %s", turn_id, exc)

    async def close(self) -> None:
        """Stop Codex. Idempotent; safe mid-turn, after a cancel, and with no process.

        A short grace: app-server leaves at its stdin's end, and the worker's shutdown gives the
        whole close 2.5 s before it cancels — past the grace it is terminated, then its tree."""
        self._drop_getter()
        for task in list(self._tasks):
            task.cancel()
        server = self._server
        if server is not None:
            await server.close(grace=child.REAP_TIMEOUT_S)
