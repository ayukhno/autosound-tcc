"""Which harness carries a pick, as functions — routing out of the window (tcc #181).

Four questions the window used to answer inline, one branch per harness each: which session a
pick gets (`factory`), which registry id a launch may resume (`resume_route`), what refuses a
launch before anything is built (`blocker`), and which CLI «Open terminal» starts
(`terminal_invocation`). A new route is added here, beside the others, and the window does not
change. Qt-free: the window translates a refusal (`Refusal` carries an i18n key, the
`model_picks` precedent), and the functions are tested without one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, NamedTuple, Optional

from autosound_tcc.core import (child, codex_cli, codex_session, omp_session, process_writer,
                                terminal_launcher)
from autosound_tcc.core.session_registry import CODEX_ROUTE, SDK_ROUTE
from autosound_tcc.core.tuning_session import TuningSession


class Refusal(NamedTuple):
    """Why a launch cannot start: an i18n key and what it is formatted with."""

    key: str
    args: dict[str, Any] = {}


def factory(choice, *, project_dir: Path, bridge, mcp_url: Optional[str],
            mcp_token: Optional[str], gate: Callable[[], str],
            always_allowed: Callable[[], frozenset[str]], resumed: bool,
            effort: Optional[str], language: str) -> Callable[[], Any]:
    """How the session for `choice` is built — called on the worker's thread, once.

    `gate` and `always_allowed` are asked when the session is BUILT, not when the factory is made:
    the window makes the factory, then asks the machine's gate question
    (`_ensure_machine_gate_answered`), and the answer given there is the one the session runs.

    Both routes get the project's language, the same one the interview has always been given.
    It went into `get_tcc_state` and nowhere else, so the model could only learn it by asking —
    and the first turn answers before it has. Put into the omp factory alone (wave 2.1), it
    was a keyword omp did not take, and the SDK route it was meant for never got it (tcc#56).
    """
    if choice.harness == "omp":
        # omp reads the project's own `.mcp.json`, which the MCP server wrote on start, so it
        # needs no url/token of its own.
        return lambda: omp_session.OmpSession(
            project_dir=project_dir,
            bridge=bridge,
            model=choice.model,
            resume=resumed,
            gate=gate(),
            always_allowed=always_allowed(),
            effort=effort,
            language=language,
        )
    if choice.harness == "codex":
        # Codex reaches TCC's tools by url, its token in the environment only
        # (`codex_session.CodexSession._spawn`) — never through `.mcp.json`.
        return lambda: codex_session.CodexSession(
            project_dir=project_dir,
            bridge=bridge,
            model=choice.model,
            resume=resumed,
            gate=gate(),
            always_allowed=always_allowed(),
            effort=effort,
            language=language,
            mcp_url=mcp_url,
            mcp_token=mcp_token,
            journal=resumed,  # `record_start` left this launch's journal line to the session
        )
    return lambda: TuningSession(
        project_dir=project_dir,
        mcp_url=mcp_url,
        mcp_token=mcp_token,
        bridge=bridge,
        model=choice.model,
        gate=gate(),
        always_allowed=always_allowed(),
        effort=effort,
        language=language,
    )


def record_start(project_dir: Path, choice, resumed: bool) -> None:
    """The journal's `session-start` for a launch, before its first token — unless the session
    says it itself. A Codex launch that means to resume learns only from `thread/resume` whether
    it did (a refused one starts afresh), so `CodexSession` journals that one once it knows
    (`factory` passes `journal=resumed`; the group review, M7). Raises `ProcessWriterError`."""
    if choice.harness == "codex" and resumed:
        return
    process_writer.record_session(project_dir, choice.harness, choice.model, resumed=resumed)


def resume_route(harness: str) -> Optional[str]:
    """The registry route whose id a launch on `harness` resumes (`SessionRegistry.resumable_session`).

    omp → None, any route: it resumes by folder (`--continue`) and asks the registry only whether
    the phase has a live session at all — its rule before routes existed. Codex → its own route:
    a thread id is resumed only by `CodexSession`, which `factory` builds for the same pick (#181
    task 6 — turned on together; one without the other told the chat «fresh» over a session that
    resumed, task 2's review, m1). Everything else is carried by the SDK and reads the SDK's route.
    """
    if harness == "omp":
        return None
    if harness == "codex":
        return CODEX_ROUTE
    return SDK_ROUTE


def blocker(choice, server) -> Optional[Refusal]:
    """What refuses to launch `choice` on `server` before anything is built, or None.

    The SDK route takes TCC's url and token directly, so an unwritten `.mcp.json` refuses nothing
    there; omp reaches TCC only through that file, unwritten, it would run without TCC's tools.
    Codex takes the url and token directly too; its own blockers (task 9) each name the menu line
    that fixes it, as omp's do: not found and too old → «Install Codex», signed out → «Sign in to
    Codex». All three are read without running anything — `too_old` is known only once a worker
    ran `version()` (the probe does), and an unread version or login is not a block.
    """
    if choice.harness == "omp":
        if not omp_session.is_available():
            return Refusal("ompMissing")
        if getattr(server, "config_error", ""):
            return omp_without_config(server)
    if choice.harness == "codex":
        return codex_blocker()
    return None


def codex_blocker() -> Optional[Refusal]:
    """Codex's own refusals, stat calls and cached readings only (the GUI thread asks)."""
    found = codex_cli.find()
    if found is None:
        return Refusal("codexMissing")
    if codex_cli.too_old(found):
        return Refusal("codexTooOld", {
            "version": codex_cli.version_text(codex_cli.known_version(found)),
            "min": codex_cli.version_text(codex_cli.MIN_VERSION)})
    if codex_cli.signed_in() is False:
        return Refusal("codexSignedOut")
    return None


def omp_without_config(server) -> Refusal:
    """Why an omp session cannot start: omp reaches TCC only through `.mcp.json`, and TCC's entry
    is not in it. A file TCC could not read is named, and the advice is to check it; the folder's
    write permission would not open it (#173, the review of Task 19, M4). A damaged file TCC read
    but could not move aside is named too, and the advice is to fix or remove it, or to make the
    folder writable (N2). A write that failed keeps the folder's advice."""
    unmoved = getattr(server, "config_unmoved", None)
    if unmoved:
        return Refusal("mcpConfigUnmovedOmp", {"path": unmoved, "error": server.config_error})
    unreadable = getattr(server, "config_unreadable", None)
    if unreadable:
        return Refusal("mcpConfigUnreadOmp", {"path": unreadable, "error": server.config_error})
    return Refusal("mcpNoConfigOmp", {"error": server.config_error})


#: «Open terminal in this project…»'s lines, in order (tcc #180): a plain shell, then the clients.
TERMINAL_CLIENTS: tuple[str, ...] = (terminal_launcher.TERMINAL,
                                     *(exe for exe, _label in terminal_launcher.MENU_CLIENTS))

#: The client that carries each harness; any other harness is carried by the SDK, i.e. `claude`.
_CLIENT_OF_HARNESS = {"omp": "omp", "codex": "codex"}

#: The module the Codex line runs (`codex_terminal`): it hands Codex TCC's url and token.
CODEX_TERMINAL = "autosound_tcc.core.codex_terminal"


def client_of(choice) -> str:
    """The terminal client that carries `choice`'s harness."""
    return _CLIENT_OF_HARNESS.get(choice.harness, "claude")


def client_invocation(client: str, choice, project_dir: Path
                      ) -> tuple[str, Optional[str], tuple[str, ...]]:
    """`(cli, model, extra)` that opens `client` — the one named, never another (tcc #180).

    The pick's model rides only to the client that carries the pick (an SDK pick → Claude, omp →
    OMP, Codex → Codex); any other client keeps its own model, and so does every client when no
    model is chosen (`choice` None). omp gets its overlay always: without
    it TCC's tools stay behind xd:// and never reach the model. Codex runs through
    `codex_terminal`, which hands it TCC's url and token — the token never in the line; a Codex
    that is gone is `TerminalLaunchError`, said like any client the launcher cannot find.
    """
    model = choice.model if choice is not None and client_of(choice) == client else None
    if client == "omp":
        return "omp", model, ("--config", str(omp_session.overlay_path(project_dir)))
    if client == "codex":
        if not terminal_launcher.client_available("codex"):
            raise terminal_launcher.TerminalLaunchError(
                "Codex is not installed on this computer, so no terminal was opened for it")
        # The console interpreter: under the GUI `sys.executable` is `pythonw.exe` on Windows, and
        # a line run with it has no console for `codex_terminal`'s refusals or for Codex.
        return child.script_interpreter(), model, ("-m", CODEX_TERMINAL, str(project_dir))
    return client, model, ()


def terminal_invocation(choice, project_dir: Path) -> tuple[str, Optional[str], tuple[str, ...]]:
    """`(cli, model, extra)` for «Open terminal» with no client named: the CLI that carries the
    pick (`client_of`) — the handoff's «start in a terminal» path.

    Same choice as the in-app session, same reasoning: the model picker decides the harness, so
    the terminal opens on the CLI that carries it — `claude` for an SDK choice, `omp` for an omp
    one, Codex for a Codex one (W-10 Codex task 8 closed «a Codex pick opens Claude») — rather
    than on whatever happens to be first on PATH. Two front-ends that disagree about which model
    is running would make the picker a lie in one of them.
    """
    return client_invocation(client_of(choice), choice, project_dir)
