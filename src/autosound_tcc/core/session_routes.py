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

from autosound_tcc.core import omp_session
from autosound_tcc.core.session_registry import SDK_ROUTE
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


def resume_route(harness: str) -> Optional[str]:
    """The registry route whose id a launch on `harness` resumes (`SessionRegistry.resumable_session`).

    omp → None, any route: it resumes by folder (`--continue`) and asks the registry only whether
    the phase has a live session at all — its rule before routes existed. Everything else is
    carried by the SDK (`factory`), so it reads the SDK's route — a hand-added Codex override
    included, until Codex gets its own session (#181 task 6 turns `CODEX_ROUTE` on here together
    with `factory`'s Codex branch; one without the other told the chat «fresh» over a session
    that resumed — task 2's review, m1).
    """
    if harness == "omp":
        return None
    return SDK_ROUTE


def blocker(choice, server) -> Optional[Refusal]:
    """What refuses to launch `choice` on `server` before anything is built, or None.

    The SDK route takes TCC's url and token directly, so an unwritten `.mcp.json` refuses nothing
    there; omp reaches TCC only through that file, unwritten, it would run without TCC's tools.
    """
    if choice.harness == "omp":
        if not omp_session.is_available():
            return Refusal("ompMissing")
        if getattr(server, "config_error", ""):
            return omp_without_config(server)
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


def terminal_invocation(choice, project_dir: Path) -> tuple[str, str, tuple[str, ...]]:
    """`(cli, model, extra)` for «Open terminal»: the CLI that carries the pick.

    Same choice as the in-app session, same reasoning: the model picker decides the harness, so
    the terminal opens on the CLI that carries it — `claude` for an SDK choice, `omp` for an omp
    one — rather than on whatever happens to be first on PATH. Two front-ends that disagree about
    which model is running would make the picker a lie in one of them.

    Every other harness opens `claude` today, a Codex pick included — the gap task 8 of the Codex
    build closes here, with a `codex` branch (`codex_terminal`).
    """
    if choice.harness == "omp":
        # Without the overlay TCC's own tools stay behind xd:// and never reach the model --
        # the terminal would be quietly weaker than the in-app session for no visible reason.
        return "omp", choice.model, ("--config", str(omp_session.overlay_path(project_dir)))
    return "claude", choice.model, ()
