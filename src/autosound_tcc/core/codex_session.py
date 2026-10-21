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
  tool); command and file-change approvals go through TCC's gate (`shell_gate.judge_action`, the
  table omp shares), then the confirm bar when it asks — `accept` or `decline`, never
  `acceptForSession` (TCC's ticks are the only memory of what was allowed); anything else is a
  JSON-RPC error. A request Codex withdraws (`serverRequest/resolved`) takes the bar down and is
  never answered.

Qt-free; everything runs on the worker's loop (`ui.tcc.agent_worker`).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
from pathlib import Path
from dataclasses import replace
from typing import Any, AsyncIterator, Optional

from autosound_tcc.core import (agents_md, app_log, child, codex_cli, codex_rpc, config, critic,
                                method_binding, model_choices, openers, process_writer,
                                signal_bus, vendor_loader)
from autosound_tcc.core.agent_events import (AgentEvent, Notice, TextDelta, Thinking, ToolCall,
                                             ToolEnd, TurnEnd, Unasked)
from autosound_tcc.core.mcp_server import (CONFIRM_TIMEOUT_S, ConfirmRequest, HeadlessBridge,
                                           UiBridge, await_confirmation)
from autosound_tcc.core.omp_session import FRAME_LOG_MAX_BYTES
from autosound_tcc.core.session_registry import CODEX_ROUTE, SessionRegistry
from autosound_tcc.core.shell_gate import (ALLOW_TITLE, GATE_AUTO, GATE_NEVER, GATE_WRITES,
                                           SHELL_BASH, SHELL_POWERSHELL, Verdict,
                                           allow_title_args, judge_action,
                                           powershell_command_text)
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

#: How long a request swept at the turn's end waits for Codex's own withdrawal before TCC declines it.
SWEEP_DECLINE_S = 1.0

#: The requests Codex sends before it runs something; task 7 answers them from TCC's gate.
COMMAND_APPROVAL = "item/commandExecution/requestApproval"
FILE_APPROVAL = "item/fileChange/requestApproval"
ELICITATION = "mcpServer/elicitation/request"

#: Not a notification Codex sends: the gate's `Unasked`, put on the notifications queue so it reaches
#: the turn's events in order with Codex's own.
_UNASKED = "tcc/unasked"
#: The same for a Notice of the gate's own (a gate that failed, the group review's I1).
_NOTICE = "tcc/notice"
#: The programs whose command line is PowerShell's, by the first word's basename.
_POWERSHELL = frozenset({"powershell", "pwsh"})

#: `/bin/zsh -lc '…'` — how Codex on macOS/Linux wraps every command it runs.
_SHELL_WRAPPER = re.compile(r"^(?:\S*/)?(?:zsh|bash|sh)\s+-l?c\s+(.+)$", re.S)

#: Item types that are tools, and the names the panel (and the gate) know them by.
_COMMAND, _FILE_CHANGE, _MCP_CALL, _AGENT_MESSAGE = (
    "commandExecution", "fileChange", "mcpToolCall", "agentMessage")
#: The model's reasoning. Its text is never shown; that it happened is (#223).
_REASONING = "reasoning"


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


def shown_command(command: str) -> str:
    """What a `powershell -Command …` line runs, for the bar: the `-Command` text as PowerShell gets
    it. Codex on Windows sends its argv joined the POSIX way (`"C:\\…\\powershell.exe" -Command
    '…'"'"'…'`), so shown whole a doubled backslash and a `'"'` stood between the Arbiter and the
    line (W-10). Any other shape — not PowerShell, an option before `-Command` that may take a value,
    `-EncodedCommand`, `-File` — is returned whole: nothing is hidden by the unwrapping. The gate
    takes it apart the same way (`shell_gate.powershell_command_text`)."""
    text = powershell_command_text(command)
    return command if text is None else text


def _names_the_method(name: str) -> bool:
    """Codex's name for the method: bare, or `<plugin>:autosound-tuning` — a real Codex 0.162.1
    namespaces a skill that comes with a `.claude-plugin/`, as the vendored repo does (task 10's
    live run, F1)."""
    return name == SKILL_NAME or name.rsplit(":", 1)[-1] == SKILL_NAME


def shell_of(command: str, *, windows: Optional[bool] = None) -> str:
    """Which shell's reader judges `command` (`judge_action`'s `shell`): PowerShell when its first
    word is `powershell`/`pwsh` (any folder, `.exe` or not, quoted or not); bash when it is Codex's
    `sh`/`bash`/`zsh -lc` wrapper; otherwise the platform's — Codex on Windows runs its commands in
    PowerShell, everywhere else in a POSIX shell."""
    text = (command or "").lstrip()
    if text.startswith('"'):
        first = text[1:].split('"', 1)[0]
    else:
        first = text.split(None, 1)[0] if text else ""
    name = first.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name in _POWERSHELL:
        return SHELL_POWERSHELL
    if _SHELL_WRAPPER.match(text):
        return SHELL_BASH
    windows = os.name == "nt" if windows is None else windows
    return SHELL_POWERSHELL if windows else SHELL_BASH


def _plain(path: str) -> str:
    """`\\\\?\\C:\\x` → `C:\\x`, `\\\\?\\UNC\\host\\share` → `\\\\host\\share`: Windows' long-path
    spelling names the same folder, and a realpath keeps the prefix it was given."""
    if path.startswith(("\\\\?\\UNC\\", "//?/UNC/")):
        return "\\\\" + path[8:]
    if path.startswith(("\\\\?\\", "//?/")):
        return path[4:]
    return path


def where(cwd: Any, project: Any, *, paths=os.path) -> Optional[str]:
    """None when `cwd` is the project itself (or not given); "outside" when it is not in the
    project; else the folder the line runs in, RELATIVE to the project (realpaths) — the gate
    reads operands from the project, and an absolute `cd` would leave `../..` read as text
    (task 7's re-review, N2). Windows' spellings of one folder — any case, `\\\\?\\` — are one
    folder; another drive is outside. `paths`: `ntpath` for the tests' Windows rows."""
    if not cwd:
        return None
    try:
        here = paths.realpath(_plain(str(cwd)))
        home = paths.realpath(_plain(str(project)))
    except (OSError, ValueError):
        return "outside"
    mine, root = paths.normcase(here), paths.normcase(home)
    if mine == root:
        return None
    try:
        inside = paths.commonpath([mine, root]) == root
    except ValueError:  # another drive, or one relative and one absolute
        inside = False
    return paths.relpath(here, home) if inside else "outside"


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
        journal: bool = False,
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
        #: The `codex` to start; None = `codex_cli.settled()` at start. The tests pass the stand-in.
        self.binary = binary
        #: Journal `session-start` once the thread is open: a launch that means to resume learns
        #: only from `thread/resume` whether it did (the window journals every other launch,
        #: `session_routes.record_start`; the group review, M7).
        self.journal = journal
        #: This session wrote its `session-start` (read by the window's stop through
        #: `session_routes.take_open_journal`, which pairs it with one close).
        self.journaled = False
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
        #: A fileChange's `(path, kind)` by itemId — the approval names only the item. Recorded in
        #: the reader (`_on_notification`), so the gate never waits on whoever drains the queue.
        self._changes: dict[str, list[tuple[str, str]]] = {}
        #: Approvals with the gate or on the bar, by request id: cancelled when Codex withdraws one
        #: or the turn ends — the bar comes down and nothing is sent.
        self._gating: dict[Any, asyncio.Task] = {}
        self._timers: dict[Any, asyncio.TimerHandle] = {}
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
        binary = await self._binary()
        env = self._env(binding)
        notices: list[AgentEvent] = []
        # The `AGENTS.md` Codex reads, written by the method into a project made before it seeded
        # one (skill #149); a refusal is said, and the session starts without it.
        if said := await asyncio.to_thread(agents_md.ensure, self.project_dir):
            notices.append(Notice(said))
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
        if self.journal:
            notices += await self._journal_start()
        return notices

    async def _journal_start(self) -> list[AgentEvent]:
        """`session-start codex <model> [resumed]` as it went — `resumed` only when the thread
        was continued. Off the loop: the method's writer is a process. A refusal is said, as the
        window says it on the other routes, and the session goes on."""
        try:
            await asyncio.to_thread(process_writer.record_session, self.project_dir, "codex",
                                    self.model, resumed=self.resumed)
        except process_writer.ProcessWriterError as exc:
            app_log.logger().warning("codex: session-start was not journalled: %s", exc)
            return [Notice(f"journal: {exc}")]
        self.journaled = True
        return []

    def _redact(self, text: str) -> str:
        """`text` without TCC's token: a start's refusal carries Codex's stderr, and a user's own
        `RUST_LOG=trace` prints request headers there (task 6's review, M5)."""
        return text.replace(self.mcp_token, codex_rpc.REDACTED) if self.mcp_token else text

    def _start_failed(self, said: str) -> CodexStartFailed:
        return CodexStartFailed(self._redact(said))

    async def _binary(self) -> str:
        """The Codex to start: `settled()`'s — an old Codex the probe read as too old is passed
        over for the next, as the terminal and the probe pass it (the group review, M4). On a
        thread: it may read a version (`codex --version`), never on the loop."""
        if self.binary:
            return str(self.binary)
        found, read = await asyncio.to_thread(codex_cli.settled)
        if found is None:
            raise CodexNotInstalled(
                "Codex is not installed on this computer (or not where TCC looks for it), so the "
                "session cannot start. Install Codex, then start the session again.")
        if read is not None and read < codex_cli.MIN_VERSION:
            raise CodexStartFailed(
                f"Codex {codex_cli.version_text(read)} at {found.path} is older than "
                f"{codex_cli.version_text(codex_cli.MIN_VERSION)}, the oldest TCC speaks to, so the "
                "session did not start. ☰ → ⚙ Settings → Install Codex puts TCC's own copy beside it.")
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
        except codex_rpc.RpcError as exc:
            # `initialize` refused — the calls after it come back in place (the group review, I2).
            raise self._start_failed(f"Codex refused to start: {exc.message or exc.code}") from exc
        if codex_cli._signed_in_from(account) is False:
            # The pickers and the blocker read the same: the next launch is refused before a spawn.
            codex_cli.mark_signed_out()
            raise CodexSignedOut(
                "Codex is not signed in on this computer, so the session cannot start. "
                "☰ → ⚙ Settings → Sign in to Codex, then start the session again.")
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
            log=self._frame_log(), on_request=self._on_request,
            on_notification=self._on_notification, secret_env=secrets,
            log_cap=FRAME_LOG_MAX_BYTES)
        try:
            await self._server.open()
        except codex_rpc.ConnectionLost as exc:
            raise self._start_failed(f"Codex did not start: {exc}") from exc
        except TimeoutError as exc:
            raise self._start_failed(f"Codex did not answer at start: {exc}") from exc
        except codex_rpc.RpcError as exc:
            raise self._start_failed(f"Codex refused to start: {exc.message or exc.code}") from exc
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
        found = False
        for group in listed.get("data") or []:
            for skill in (group or {}).get("skills") or []:
                if not isinstance(skill, dict):
                    continue
                path = str(skill.get("path") or "")
                if skill.get("enabled") is False:
                    # Off in Codex: not loaded — neither the bound copy nor a second one (M8).
                    continue
                if self._is_bound_copy(path, skill_dir, root):
                    found = True
                    continue
                if not _names_the_method(str(skill.get("name") or "")):
                    continue
                said = (f"Codex also offers a copy of the method at {path}, besides the one this "
                        f"project runs ({skill_dir}), and a session could load either; remove it "
                        f"from Codex's skills, then start the session again.")
                app_log.logger().warning("refused: the Codex session on %s did not start: %s",
                                         self.project_dir, said)
                raise method_binding.MethodRefused(said)
        return [] if found else [self._no_skill_notice()]

    @staticmethod
    def _is_bound_copy(path: str, skill_dir: Path, root: Path) -> bool:
        """Whether a skill Codex lists IS the method this project runs — by its path, never its
        name: the bound copy's `SKILL.md` (Codex lists it resolved), or anything under the
        project's own link in the extra root."""
        if not path:
            return False
        link = root / SKILL_NAME
        spelled = os.path.normcase(os.path.abspath(path))
        if spelled.startswith(os.path.normcase(os.path.abspath(link)) + os.sep):
            return True
        real = os.path.normcase(os.path.realpath(path))
        return real in {os.path.normcase(os.path.realpath(skill_dir / "SKILL.md")),
                        os.path.normcase(os.path.realpath(link / "SKILL.md"))}

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

    def _on_request(self, msg: dict) -> Optional[asyncio.Task]:
        """Every request Codex sends, answered once (the reader calls this): at once, or by the
        approval's gate task."""
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
            # Its own task: the reader goes on reading while the gate looks and the bar waits.
            # Returned, so `AppServer` answers with an error if the gate itself fails.
            task = asyncio.ensure_future(self._gate(rid, method, params))
            self._gating[rid] = task

            def done(finished: asyncio.Task, rid: Any = rid) -> None:
                if self._gating.get(rid) is finished:
                    del self._gating[rid]

            task.add_done_callback(done)
            return task
        app_log.logger().warning("codex: a request TCC does not handle, answered with an error: %s",
                                 method)
        server.respond(rid, error={"code": codex_rpc.METHOD_NOT_FOUND,
                                   "message": f"TCC does not handle {method}"})

    def _on_notification(self, msg: dict) -> None:
        """In the reader, before the notification is queued: what the gate needs at once."""
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "item/started":
            item = params.get("item") or {}
            if item.get("type") == _FILE_CHANGE:
                self._changes[str(item.get("id") or "")] = [
                    (str(change.get("path")), str((change.get("kind") or {}).get("type") or ""))
                    for change in item.get("changes") or []
                    if isinstance(change, dict) and change.get("path")]
        elif method == "serverRequest/resolved":
            rid = params.get("requestId")
            server = self._server
            # Only one still pending: `resolved` also comes for requests already answered.
            if server is not None and server.withdrawn(rid):
                self._drop_gate(rid)
        elif method == "turn/completed":
            # Here, in the reader and in order, not when the turn's reader gets to it: a gate that
            # finished in between would otherwise put its `Unasked` behind `turn/completed`, where
            # it shows as the next turn's first event (re-review M1). Only this thread's turn in
            # flight (N3); before its id is known, the one turn there is.
            turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
            if params.get("threadId") == self.session_id and (
                    not self._turn_id or turn.get("id") == self._turn_id):
                self._sweep_gates()

    def _drop_gate(self, rid: Any, *, decline: bool = False) -> None:
        """Codex withdrew `rid`, or its turn ended: the gate task is cancelled — the bar's future
        with it (`ConfirmBar._on_gave_up`). `decline`: the turn ended, and if Codex has not
        withdrawn `rid` within `SWEEP_DECLINE_S` it is answered `decline` (re-review M2). Not at
        once: Codex withdraws right after `turn/completed`, and an answer racing that withdrawal
        lands on a request it no longer has."""
        task = self._gating.pop(rid, None)
        if task is not None and not task.done():
            task.cancel()
        if decline and task is not None:
            self._timers[rid] = asyncio.get_running_loop().call_later(
                SWEEP_DECLINE_S, self._late_decline, rid)

    def _late_decline(self, rid: Any) -> None:
        self._timers.pop(rid, None)  # fired: no longer one to cancel (N4)
        server = self._server
        # `respond` refuses one Codex withdrew, one already answered, and any once it has ended.
        if server is not None and not server.ended and not server.withdrawn(rid):
            server.respond(rid, {"decision": "decline"})

    def _sweep_gates(self) -> None:
        """The turn is over: what still waits on the gate or the bar goes, declined unless Codex
        withdraws it (M2)."""
        for rid in list(self._gating):
            self._drop_gate(rid, decline=True)

    def _asked(self, method: str, params: dict) -> tuple[str, str, str, str, str]:
        """`(tool, detail, shell, always, shown)` for one approval, as the gate reads it. `always`
        names why it asks whatever the gate says — `irreversible` (a file delete outside the
        project, or a change Codex did not describe), `delete` (one file of the project deleted:
        asks only where the gate asks about writes, `_judge`) or `unknown` (Codex did not say what
        runs, or where TCC cannot judge it) — and is "" otherwise. `shown`
        is `detail` as the bar shows it: a PowerShell line by the text it runs (`shown_command`)."""
        if method == COMMAND_APPROVAL:
            tool, detail, shell, always = self._asked_command(params)
            if shell != SHELL_POWERSHELL:
                return tool, detail, shell, always, detail
            line = self._line(params)
            return tool, detail, shell, always, detail.replace(line, shown_command(line), 1)
        changes = self._changes.get(str(params.get("itemId") or ""))
        reason = str(params.get("reason") or "").strip()
        if changes:
            detail = "\n".join(f"{kind or 'change'}: {path}" for path, kind in changes)
            deletes = [path for path, kind in changes if kind == "delete"]
            always = "" if not deletes else "delete" if all(
                self._one_file_inside(path) for path in deletes) else "irreversible"
        else:
            # Codex named no change TCC saw: what it does is unknown, so it is asked about as a
            # delete would be — under `auto` too.
            detail, always = "a file change Codex did not describe", "irreversible"
        detail += f"\n{reason}" if reason else ""
        return "Edit", detail, SHELL_BASH, always, detail

    @staticmethod
    def _raw(params: dict) -> str:
        raw = params.get("command")
        return shlex.join(map(str, raw)) if isinstance(raw, list) else str(raw or "")

    @classmethod
    def _line(cls, params: dict) -> str:
        """The line `_asked_command` judges, before `_in_folder`: Codex's wrapper off a bash one."""
        raw = cls._raw(params)
        return inner_command(raw) if shell_of(raw) == SHELL_BASH else raw

    def _asked_command(self, params: dict) -> tuple[str, str, str, str]:
        raw = self._raw(params)
        kind = str(params.get("kind") or "command")
        if kind != "command" or not raw.strip():
            # Input to a running terminal (`writeStdin`), or no command at all: nothing the gate
            # can read, so it asks (task 7's review, I2).
            said = raw.strip() or f"{kind}: {json.dumps(params, ensure_ascii=False)[:300]}"
            return "Bash", said, SHELL_BASH, "unknown"
        shell = shell_of(raw)
        line = raw
        if shell == SHELL_BASH:
            line = inner_command(raw)  # Codex's `zsh -lc '…'` wrapper only says how it runs
            if shell_of(line, windows=False) == SHELL_POWERSHELL:
                shell = SHELL_POWERSHELL  # `pwsh -c …` behind the wrapper is PowerShell's line
        # PowerShell lines whole (task 5's reader parses them).
        where = self._where(params.get("cwd"))
        if where is None:
            return "Bash", line, shell, ""
        if where == "outside":
            # The critical case of task 7's review: the gate reads paths from the project, so a
            # line that runs elsewhere — `rm -rf *` in the home — is not one it can judge. The
            # stricter way: it asks (never: through, said), and the bar shows where.
            cwd = str(params.get("cwd"))
            return "Bash", self._in_folder(line, cwd, shell), shell, "unknown"
        return "Bash", self._in_folder(line, where, shell), shell, ""

    def _where(self, cwd: Any) -> Optional[str]:
        return where(cwd, self.project_dir)

    def _one_file_inside(self, path: str) -> bool:
        """A file-change delete's path is one file in the project or the method's copy: not a
        folder, not either root itself, not one a link takes outside them (`where` reads realpaths)."""
        target = Path(_plain(path))
        target = target if target.is_absolute() else self.project_dir / target
        if target.is_dir():
            return False
        return any(where(str(target), root) not in (None, "outside") for root in self._read_roots)

    @staticmethod
    def _in_folder(line: str, cwd: str, shell: str) -> str:
        """The line as it runs in `cwd`, for the gate to judge from there. Codex's PowerShell argv
        by the `-Command` text it runs: behind a `Set-Location` it is a PowerShell line, and the argv
        joined the POSIX way is not one (W-10)."""
        if shell == SHELL_POWERSHELL:
            text = powershell_command_text(line)
            return "Set-Location '" + cwd.replace("'", "''") + "'; " + (line if text is None
                                                                        else text)
        return f"cd {shlex.quote(cwd)} && {line}"

    @staticmethod
    def _always_asks(verdict: Verdict, tool: str, detail: str, why: str, gate: str,
                     ticks: frozenset[str], shell: str = SHELL_BASH) -> Verdict:
        """What asks whatever the gate said: a file delete cannot be undone, so it asks under
        `auto` too (the plan, decided 2026-10-14 after task 5's review, I1); a line the gate cannot
        judge — run outside the project, input to a running terminal, no command — asks under
        every gate. Only `never` lets either through, and says so: a «don't ask again» tick never
        outranks them (the Arbiter, 2026-10-14 — `judge_action` says the same of a dangerous line)."""
        if gate == GATE_NEVER:
            return Verdict(True, unasked=detail)
        reason = "gateIrreversible" if why == "irreversible" else verdict.reason
        if verdict.allowed:
            return Verdict(False, tool=tool, title=ALLOW_TITLE,
                           title_args=allow_title_args(tool, shell), detail=detail, reason=reason)
        return replace(verdict, detail=detail, reason=reason)

    async def _gate(self, rid: Any, method: str, params: dict) -> None:
        """TCC's gate on one approval, answered once: `accept` or `decline`. The gate and the
        ticks are read here, per request, so a gate narrowed mid-session holds from the next. A
        gate that fails declines (task 7's review, I3) — a cancel stays a cancel."""
        try:
            allowed = await self._judge(method, params)
        except Exception as exc:  # noqa: BLE001 — a broken gate is a closed one, said
            app_log.logger().warning("codex: the gate failed on %s %r, declined: %s: %s",
                                     method, rid, type(exc).__name__, exc)
            # In the turn too, not only in tcc.log: a refusal nobody sees reads as Codex
            # stalling (the group review, I1).
            self._say(Notice(f"TCC's check of what Codex asked to run failed "
                             f"({type(exc).__name__}: {exc}), so it was refused. Codex may try "
                             "another way; the details are in tcc.log."))
            allowed = False
        server = self._server
        if server is not None:
            # `respond` refuses an answer to a request Codex withdrew meanwhile.
            server.respond(rid, {"decision": "accept" if allowed else "decline"})

    async def _judge(self, method: str, params: dict) -> bool:
        gate, ticks = self.gate, frozenset(self.always_allowed)
        tool, detail, shell, always, shown = self._asked(method, params)
        if always == "delete":
            # The Arbiter, 2026-10-15: one file of the project deleted is the skill's work —
            # «всі ці питання ніхто не читає а вони тільки дратують». `auto` lets it through (and
            # `never` has nothing to say of it); where every write asks, it asks as before.
            always = "" if gate in (GATE_AUTO, GATE_NEVER) else "irreversible"
        # Off the loop: the gate reads the disk (realpaths, globs, a walk for a recursive delete),
        # and a slow drive must not hold Codex's notifications.
        verdict = await asyncio.to_thread(judge_action, tool, detail, gate=gate,
                                          always_allowed=ticks, read_roots=self._read_roots,
                                          shell=shell)
        if always:
            verdict = self._always_asks(verdict, tool, detail, always, gate, ticks, shell)
        if verdict.allowed:
            if verdict.unasked:
                self._say(Unasked(verdict.unasked))
            return True
        # What the gate read whole is shown as it runs (`shown`): the same text, unwrapped.
        said = verdict.detail or detail
        request = ConfirmRequest(tool=verdict.tool or tool, title=verdict.title or ALLOW_TITLE,
                                 title_args=verdict.title_args or allow_title_args(tool, shell),
                                 detail=shown if said == detail else said, payload=dict(params),
                                 reason=verdict.reason)
        allowed = await await_confirmation(self.bridge, request, CONFIRM_TIMEOUT_S)
        if allowed.failure:  # a `decline` carries no words: the turn says it was not a no (#206)
            self._say(Notice(allowed.refused("")))
        return allowed.allowed

    def _say(self, event: AgentEvent) -> None:
        """An event of the gate's into the turn, in order with Codex's notifications."""
        server = self._server
        if server is not None and isinstance(event, Unasked):
            server.notifications.put_nowait({"method": _UNASKED,
                                             "params": {"command": event.command}})
        elif server is not None and isinstance(event, Notice):
            server.notifications.put_nowait({"method": _NOTICE, "params": {"text": event.text}})

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
            self._changes.clear()
            self._sweep_gates()
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
            # The notification first (re-review M1): a `turn/started` arriving with `turn/start`'s
            # timeout names the turn before the timeout is read as «no turn».
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
            if reply is not None and reply in done:
                answered, reply = reply, None
                events, over = self._on_reply(answered)
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
            return self._no_turn(f"Codex did not start the turn in {int(REQUEST_TIMEOUT_S)} s"), True
        self._turn_id = self._turn_id or ((result.get("turn") or {}).get("id")) or None
        if not self._turn_id:
            # A reply that names no turn, and no `turn/started` before it (re-review M2): nothing
            # will complete what has no id, and Stop could not reach it.
            app_log.logger().warning("codex: turn/start answered without a turn id: %r", result)
            return self._no_turn("Codex answered the message without starting a turn"), True
        self._interrupt_if_wanted()
        return [], False

    def _no_turn(self, said: str) -> list[AgentEvent]:
        return [Notice(f"{said}, so it ended here. Send the message again."),
                TurnEnd(self.session_id)]

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
        if method == _UNASKED:
            return [Unasked(str(params.get("command") or ""))], False
        if method == _NOTICE:
            return [Notice(str(params.get("text") or ""))], False
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
            # A tool Codex never completed — its approval was pending when Stop came — is closed
            # here, or the panel's running row stays open (task 10's live run, F2).
            events: list[AgentEvent] = [ToolEnd(name) for name in self._running.values()]
            self._running.clear()
            self._running_label = ""
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
        if kind == _REASONING:
            # Codex 0.162 reports it once the reasoning is over (started and completed in the same
            # millisecond), so this is late; the panel's own «thinking» line covers the think.
            return [Thinking()]
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
        self._sweep_gates()
        for timer in list(self._timers.values()):
            timer.cancel()
        self._timers.clear()
        for task in list(self._tasks):
            task.cancel()
        server = self._server
        if server is not None:
            await server.close(grace=child.REAP_TIMEOUT_S)
