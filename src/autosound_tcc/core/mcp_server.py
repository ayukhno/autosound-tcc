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

from autosound_tcc.core import agent_session, config, critic, vendor_loader
from autosound_tcc.core.session_registry import SessionRegistry
from autosound_tcc.core.signal_bus import SignalBus

SERVER_NAME = "tcc"
DEFAULT_PORT = 8765
_TOKEN_HEADER = "x-tcc-token"
# How long an Arbiter confirmation stays open before the tool call is denied. Long enough that the
# user can walk to the car and back, short enough that a forgotten dialog doesn't pin an MCP call
# open forever.
CONFIRM_TIMEOUT_S = 600.0


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

    def show_critique(self, critique: dict[str, Any]) -> None:
        pass


def _strip_stray_dsp_profile_prefix(path: str) -> str:
    """Defensive: `save_profile_field`/`reset_profile_field`'s `path` is relative to
    `project_profile` (already the unwrapped profile), but an agent that also saw a bundled
    profile's on-disk shape (`{"dsp_profile": {...}}`) can still guess a `dsp_profile.` prefix --
    observed live (2026-07-29 dogfood: "Wrong nesting — path made dsp_profile.dsp_profile").
    Correcting it here is more robust than hoping the tool description alone prevents every case.
    """
    if path.startswith("dsp_profile."):
        return path[len("dsp_profile."):]
    return path


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
        data = registry.load()
        state = {
            "project_dir": str(project_dir),
            "ui": bridge.snapshot(),
            "current_phase": data.get("current_phase"),
            "phases": data.get("phases", {}),
            "pending_signals": bus.pending_count,
        }
        return json.dumps(state, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def get_pending_signals() -> str:
        """Take every user signal raised in the UI since the last call, emptying the queue.

        Signals are things the Arbiter did that you would otherwise not know about: switching on
        param-edit mode, flagging that something you claimed to have changed is not visible, or
        moving attention to another channel. Check this at the start of a turn and before any
        proposal; a `not_visible` signal means re-verify against disk, not restate your claim.
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
        history = vstate.PresetHistory(str(config.state_root()), preset)
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
    # agent_session.SYSTEM_PROMPT if that ever changes. Never touches DSP/REW (just one JSON file),
    # so unlike the writes below, none of this needs the Arbiter gate.
    onboarding_draft: dict[str, Any] = {"vendor": None, "model": None, "data": None}

    @mcp.tool()
    async def get_capability_checklist() -> str:
        """The fixed DSP capability-checklist questions to ask the human about (project-intake.md
        §4). Ask closed questions with concrete options where you can, 2-3 per turn -- never dump
        the whole remaining list into one message, even when several are still open."""
        return json.dumps(agent_session.CAPABILITY_CHECKLIST, ensure_ascii=False)

    @mcp.tool()
    async def check_existing_profile(vendor: str, model: str) -> str:
        """Call this FIRST, before asking the human anything. Checks this project's own
        in-progress draft and the bundled reference library for an EXACT vendor+model match --
        never treat a different model's profile (even a platform sibling's) as fact for this one.
        If it returns a project profile or an exact bundled match, don't re-ask about anything it
        already confirmed -- call get_capability_checklist and ask only about what's still open,
        2-3 questions per turn (see get_capability_checklist's own note).

        `project_profile` and `bundled_exact_match` are both returned UNWRAPPED (no top-level
        `dsp_profile` key) -- `project_profile` IS the object `save_profile_field`'s `path`
        resolves against. A path like `groups.0.fields` reaches `project_profile.groups[0].fields`
        directly; never prefix a path with `dsp_profile.`, that key does not exist at this level.
        """
        try:
            dsp_profile = vendor_loader.load_dsp_profile()
        except vendor_loader.VendorNotInitializedError as exc:
            return json.dumps({"error": str(exc)})
        if onboarding_draft["data"] is None:
            onboarding_draft["vendor"] = vendor
            onboarding_draft["model"] = model
            profile_path = config.dsp_profile_path(project_dir)
            if profile_path.is_file():
                onboarding_draft["data"] = dsp_profile.load_profile(str(profile_path))
            else:
                onboarding_draft["data"] = agent_session.empty_profile_draft(vendor, model)
        bundled = dsp_profile.find_bundled(vendor, model, str(config.bundled_profiles_dir()))
        out = {
            "project_profile": onboarding_draft["data"].get("dsp_profile", onboarding_draft["data"]),
            "open_questions": dsp_profile.open_questions(onboarding_draft["data"]),
            "bundled_exact_match": bundled.get("dsp_profile", bundled) if bundled else None,
        }
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool()
    async def save_profile_field(path: str, value: Any) -> str:
        f"""Save one confirmed field into the in-progress profile draft (call
        check_existing_profile first). One field per call, as soon as it's confirmed -- don't
        batch everything to the end.

        `path` is a dotted path relative to `project_profile` as returned by
        check_existing_profile -- e.g. 'sample_rate_hz' or 'groups.0.fields' reach
        `project_profile.sample_rate_hz` / `project_profile.groups[0].fields` directly. NEVER
        prefix a path with 'dsp_profile.' -- `project_profile` already IS that object, prefixing
        it creates a wrong nested dsp_profile.dsp_profile. `groups` is a flat array, each EXACTLY
        {{"id": "<snake_case_id>", "label": "<Human Label>", "fields": [<tokens>]}} -- `fields`
        must be a flat array of STRING TOKENS drawn ONLY from this vocabulary, nothing else:
        {json.dumps(agent_session.FIELD_VOCABULARY)}
        A capability that doesn't fit this vocabulary belongs in `_open_questions`, not a made-up
        field name.
        """
        if onboarding_draft["data"] is None:
            return json.dumps({"error": "call check_existing_profile first"})
        path = _strip_stray_dsp_profile_prefix(path)
        value = agent_session.maybe_decode_json(value)
        agent_session.set_dotted_field(
            onboarding_draft["data"].setdefault("dsp_profile", {}), path, value
        )
        return json.dumps({"saved": path, "value": value}, ensure_ascii=False)

    @mcp.tool()
    async def reset_profile_field(path: str) -> str:
        """Delete a field from the draft (by dotted path) so it can be re-saved from scratch --
        recovery if a previous save_profile_field produced the wrong shape (e.g. a list written as
        a string), not part of the normal interview flow."""
        if onboarding_draft["data"] is None:
            return json.dumps({"error": "call check_existing_profile first"})
        path = _strip_stray_dsp_profile_prefix(path)
        parts = path.split(".")
        node = onboarding_draft["data"].get("dsp_profile", {})
        for part in parts[:-1]:
            key: Any = int(part) if part.isdigit() else part
            if isinstance(node, (dict, list)) and key in (node if isinstance(node, dict) else range(len(node))):
                node = node[key]
            else:
                return json.dumps({"reset": False, "reason": f"{path} not found"})
        last: Any = int(parts[-1]) if parts[-1].isdigit() else parts[-1]
        if isinstance(node, dict) and last in node:
            del node[last]
        elif isinstance(node, list) and isinstance(last, int) and 0 <= last < len(node):
            node[last] = None
        return json.dumps({"reset": path}, ensure_ascii=False)

    @mcp.tool()
    async def finalize_profile() -> str:
        """Validate and write the profile to disk. Call this when the interview is done or the
        human says they're done -- do not just say so in text, call the tool."""
        if onboarding_draft["data"] is None:
            return json.dumps({"error": "call check_existing_profile first"})
        try:
            dsp_profile = vendor_loader.load_dsp_profile()
        except vendor_loader.VendorNotInitializedError as exc:
            return json.dumps({"error": str(exc)})
        profile_path = config.dsp_profile_path(project_dir)
        dsp_profile.validate_profile(onboarding_draft["data"])
        dsp_profile.save_profile(str(profile_path), onboarding_draft["data"])
        bridge.notify_profile_ready()
        return json.dumps({"saved_to": str(profile_path)}, ensure_ascii=False)

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
    async def report_phase(
        phase: str, step: str = "", status: str = "", evidence: Optional[list[str]] = None
    ) -> str:
        """Tell TCC which phase/step you are on, with evidence links for a finished step.

        TCC uses this to decide whether a later launch resumes your session or starts a fresh one
        (one phase ≈ one session), and to show the Arbiter where the process stands. Report a
        phase change as soon as you make it, not at the end of the turn.
        """
        entry = registry.record_phase(
            phase=phase,
            step=step or None,
            status=status or None,
            evidence=evidence or None,
        )
        return json.dumps({"recorded": True, "phase": phase, "entry": entry}, ensure_ascii=False)

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
