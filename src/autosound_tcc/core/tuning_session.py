"""The in-app tuning conversation — front-end A (docs/TCC-TZ.md §4a).

Runs the `autosound-tuning` skill through the Claude Agent SDK inside TCC's own process, so the
dialog panel can render native bubbles instead of a terminal. The skill is Claude-Code-shaped
(SKILL.md + phase references + file state + Bash runs of `rew_tool`), and the Agent SDK is Claude
Code as a library, so it executes the methodology as written rather than a port of it.

This is *one* of two front-ends and deliberately not the foundation: it connects to TCC's own MCP
server (`core.mcp_server`) exactly as an external CLI would, so every tool, signal and gate is
shared with front-end B. Swapping which front-end is in use changes who drives the conversation,
never what the AI can reach.

**Credentials are never handled here.** The SDK resolves them from the environment — an API key,
or whatever the user's own installation is configured with. TCC does not offer, store, or prompt
for a Claude login: a third-party product may not offer claude.ai login or rate limits for its
users (Agent SDK docs, "Set your API key"), and the way to stay clearly outside that is to have
no opinion about auth at all.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
)

from autosound_tcc.core import config
from autosound_tcc.core.mcp_server import ConfirmRequest, HeadlessBridge, UiBridge
from autosound_tcc.core.session_registry import SessionRegistry

DEFAULT_MODEL = "claude-opus-5"
SKILL_NAME = "autosound-tuning"

# Pre-approved, i.e. NOT gated. Keep this list tiny.
#
# Listing a tool here auto-approves it *before* `can_use_tool` is consulted -- the SDK warns about
# this as `CanUseToolShadowedWarning`, and an earlier version of this file listed `Bash` here and
# silently disabled its own allowlist. Only two things belong:
#   * `mcp__tcc` -- TCC's own tools, each of which raises its own confirmation, so gating here too
#     would double-prompt the same action and train the Arbiter to click through both;
#   * `TodoWrite` -- scratch state inside the agent, touches nothing outside the conversation.
# Everything else (Read/Grep/Glob/Bash/...) is deliberately absent so it falls through to
# `can_use_tool`, which is where the real decision is made.
ALLOWED_TOOLS = ["mcp__tcc", "TodoWrite"]

# Hard-blocked: never offered, never promptable. TCC's sanctioned writes all go through its own
# gated MCP tools, where the Arbiter sees exactly what changes; a general-purpose file writer
# would be a second, unaudited path to the same place.
DISALLOWED_TOOLS = ["Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch"]

# Read-only commands the skill runs constantly. Anything outside this set still works -- it just
# has to be confirmed by the Arbiter first, rather than being refused outright.
_SAFE_COMMANDS = frozenset(
    {"ls", "cat", "head", "tail", "wc", "grep", "rg", "find", "file", "stat", "pwd", "echo", "which"}
)
_SAFE_GIT_SUBCOMMANDS = frozenset({"status", "log", "diff", "show", "branch", "remote"})
# `rew_tool` scripts that only read REW and compute. `apply.py` is pointedly not here: it writes
# the ledger, which is a banked decision and belongs in front of a human.
_SAFE_REW_SCRIPTS = frozenset(
    {
        "rew_tool.py",
        "analysis.py",
        "joint_analysis.py",
        "curve_view.py",
        "target_curves.py",
        "target_bands.py",
        "dsp_math.py",
        "eq_gate.py",
        "spot_check.py",
        "verify_measurements.py",
        "level_offsets.py",
        "xover_select.py",
        "equal_loudness.py",
        "nono_curves.py",
        "make_plot.py",
        "atf_eq.py",
    }
)
# Shell syntax that lets one approved-looking command carry another. Presence of any of these
# means the allowlist can no longer reason about what will run, so the Arbiter decides.
_SHELL_CHAINING = re.compile(r"[;&|><`]|\$\(")

SYSTEM_PROMPT_APPEND = """
You are running inside the Tuning Command Center (TCC), the GUI the Arbiter is looking at.

- TCC exposes itself over MCP as the `tcc` server. Prefer `get_tcc_state` over asking the Arbiter
  to describe what is on their screen.
- Call `get_pending_signals` at the start of a turn and before any proposal. A `not_visible`
  signal means something you believe you changed did not reach the UI: re-check against disk
  instead of restating the claim.
- Report phase and step through `report_phase` as soon as they change. TCC uses that to decide
  whether a later launch resumes this session or starts a new one.
- You cannot write to the DSP from here, by design. Propose values; the Arbiter enters them.
"""


def _is_within(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def _read_roots_for(project_dir: Path) -> tuple[Path, ...]:
    """Directories the agent may read from without asking: the project, and the skill itself.

    The skill has to be in here. `.claude/skills/autosound-tuning` is a symlink out to the skill
    worktree, so it resolves *outside* the project — and the method is built on loading the active
    phase's reference file on demand (`SKILL.md`, "Phase Sliding Window"). Gating those reads
    turns every phase transition into a permission click for content TCC itself installed.

    Both roots are resolved through symlinks, so this grants the skill's real location rather than
    the link, and a path that merely *looks* like it is under the project doesn't slip through.
    """
    roots = [project_dir]
    skill_link = project_dir / ".claude" / "skills" / SKILL_NAME
    try:
        if skill_link.exists():
            roots.append(skill_link.resolve())
    except OSError:
        pass
    return tuple(roots)


def bash_is_read_only(command: str) -> bool:
    """Whether `command` is one of the read-only invocations the skill makes all day.

    Conservative by construction: unparseable or chained commands are not read-only, so the
    answer degrades to "ask the Arbiter" rather than to "allow".
    """
    if _SHELL_CHAINING.search(command):
        return False
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    head, *rest = parts
    name = Path(head).name
    if name in _SAFE_COMMANDS:
        return True
    if name == "git":
        return bool(rest) and rest[0] in _SAFE_GIT_SUBCOMMANDS
    if name.startswith("python"):
        script = next((arg for arg in rest if arg.endswith(".py")), None)
        return script is not None and Path(script).name in _SAFE_REW_SCRIPTS
    return False


class TuningSession:
    """A resumable tuning conversation bound to one project folder."""

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        mcp_url: Optional[str] = None,
        mcp_token: Optional[str] = None,
        bridge: Optional[UiBridge] = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.project_dir = Path(project_dir or config.project_dir())
        self.registry = SessionRegistry(config.tcc_dir(self.project_dir))
        self.bridge: UiBridge = bridge or HeadlessBridge(self.project_dir)
        self.model = model
        self.session_id: Optional[str] = None
        self._read_roots = _read_roots_for(self.project_dir)
        self.resumed_from: Optional[str] = self.registry.resumable_session()
        self._phase_at_start = self.registry.current_phase()
        self._mcp_servers: dict[str, Any] = {}
        if mcp_url:
            self._mcp_servers["tcc"] = {
                "type": "http",
                "url": mcp_url,
                "headers": {"X-TCC-Token": mcp_token or ""},
            }
        self._client: Optional[ClaudeSDKClient] = None
        self._started = False

    # ---- permission gate ---------------------------------------------------

    async def _can_use_tool(self, tool_name: str, tool_input: dict, context: Any):
        """Deny by default; allow the reads the skill needs; send everything else to the Arbiter.

        TCC's own `mcp__tcc__*` tools are allowed through here because each one gates itself --
        `write_rew_filters` and `copy_helix_eq` raise their own confirmation, and double-prompting
        the same action trains the Arbiter to click through both.
        """
        if tool_name.startswith("mcp__tcc"):
            return PermissionResultAllow()

        if tool_name in ("Read", "Grep", "Glob"):
            target = tool_input.get("file_path") or tool_input.get("path") or ""
            if not target or any(_is_within(Path(target), root) for root in self._read_roots):
                return PermissionResultAllow()
            return await self._ask(
                tool_name,
                f"Читання поза папкою проєкту: {target}",
                tool_input,
                deny_reason=f"{target} is outside the project folder",
            )

        if tool_name == "Bash":
            command = tool_input.get("command", "")
            if bash_is_read_only(command):
                return PermissionResultAllow()
            return await self._ask(tool_name, command, tool_input, deny_reason="command not on the read-only allowlist")

        return await self._ask(tool_name, str(tool_input)[:400], tool_input, deny_reason=f"{tool_name} is not pre-approved")

    async def _ask(self, tool: str, detail: str, payload: dict, deny_reason: str):
        import asyncio

        request = ConfirmRequest(tool=tool, title=f"Дозволити {tool}?", detail=detail, payload=payload)
        try:
            allowed = await asyncio.wait_for(
                asyncio.wrap_future(self.bridge.request_confirmation(request)), timeout=600.0
            )
        except Exception:
            allowed = False
        if allowed:
            return PermissionResultAllow()
        return PermissionResultDeny(message=f"Arbiter did not approve: {deny_reason}")

    # ---- lifecycle ---------------------------------------------------------

    def _options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            cwd=str(self.project_dir),
            model=self.model,
            system_prompt={"type": "preset", "preset": "claude_code", "append": SYSTEM_PROMPT_APPEND},
            # Project scope only: the skill must come from this project's own
            # `.claude/skills/autosound-tuning` symlink (the TCC worktree branch), not from
            # whatever the developer happens to have installed globally.
            setting_sources=["project"],
            skills=[SKILL_NAME],
            allowed_tools=ALLOWED_TOOLS,
            disallowed_tools=DISALLOWED_TOOLS,
            mcp_servers=self._mcp_servers,
            can_use_tool=self._can_use_tool,
            include_partial_messages=True,
            resume=self.resumed_from,
        )

    async def start(self, prompt: Optional[str] = None) -> AsyncIterator[Any]:
        """Open (or resume) the session and yield raw SDK messages for the caller to render."""
        self._client = ClaudeSDKClient(options=self._options())
        await self._client.connect()
        self._started = True
        opener = prompt or (
            "Resume this tuning project. Read state from disk first, call get_tcc_state and "
            "get_pending_signals, then tell me where we are and what the next step is."
            if self.resumed_from
            else "Start a tuning session for this project. Read state from disk, call "
            "get_tcc_state, then tell me where we are and what the next step is."
        )
        await self._client.query(opener)
        async for message in self._drain():
            yield message

    async def send(self, text: str) -> AsyncIterator[Any]:
        if not self._started or self._client is None:
            raise RuntimeError("call start() before send()")
        await self._client.query(text)
        async for message in self._drain():
            yield message

    async def interrupt(self) -> None:
        if self._client is not None:
            await self._client.interrupt()

    async def _drain(self) -> AsyncIterator[Any]:
        assert self._client is not None
        async for message in self._client.receive_response():
            if isinstance(message, ResultMessage):
                self._remember_session(message)
                yield message
                return
            yield message

    def _remember_session(self, result: ResultMessage) -> None:
        """Bind the SDK's session id to the current phase so a later launch can resume it."""
        if not result.session_id:
            return
        self.session_id = result.session_id
        phase = self.registry.current_phase() or self._phase_at_start
        if phase:
            self.registry.bind_session(phase, result.session_id)

    async def close(self) -> None:
        if self._started and self._client is not None:
            await self._client.disconnect()
        self._started = False

    @staticmethod
    def text_of(message: Any) -> str:
        """Concatenated text of an AssistantMessage, for callers that only want the prose."""
        if not isinstance(message, AssistantMessage):
            return ""
        return "".join(getattr(block, "text", "") for block in message.content)
