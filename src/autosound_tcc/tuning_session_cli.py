"""Headless CLI for the tuning conversation — the same `core.tuning_session.TuningSession` the
dialog panel drives, without Qt.

This is the acceptance harness for front-end A (docs/TCC-TZ.md §4a): it proves the skill loads
from the project's own worktree branch, that resume picks the right session back up, and that the
permission gate refuses what it should — all before any of it is wired to a widget.

It starts TCC's MCP server too, so the agent sees the same `tcc` tools it will see in the app.
There is no GUI here, so `HeadlessBridge` answers every confirmation with "deny": a headless run
has no Arbiter, and no Arbiter must never quietly mean no gate. Expect the agent to be refused if
it tries to write; that refusal is the test passing.

Usage:
    AUTOSOUND_PROJECT_DIR=~/projects/--MyCar_Jul26 tuning-session
    tuning-session --project-dir /path/to/project --prompt "what's the current phase?"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from autosound_tcc.core import config
from autosound_tcc.core.agent_events import AgentEvent, Question, TextDelta, ToolCall, TurnEnd
from autosound_tcc.core.mcp_server import TccMcpServer
from autosound_tcc.core.tuning_session import TuningSession


def _render(event: AgentEvent) -> None:
    """Print an event the way the dialog panel shows it: prose, and tool calls as events."""
    if isinstance(event, TextDelta):
        print(event.text, end="", flush=True)
    elif isinstance(event, ToolCall):
        print(f"\n  · {event.name}", flush=True)
    elif isinstance(event, Question):
        options = " / ".join(o.label for o in event.options)
        print(f"\n  ? {event.question}{f' [{options}]' if options else ''}", flush=True)
    elif isinstance(event, TurnEnd):
        print("\n[turn done]\n", flush=True)


async def _run(project_dir: Path, prompt: str | None, once: bool) -> None:
    server = TccMcpServer(project_dir=project_dir)
    port = server.start()
    print(f"--- TCC MCP server on {server.url} ---")
    print(f"--- project: {project_dir} ---")

    session = TuningSession(
        project_dir=project_dir,
        mcp_url=server.url,
        mcp_token=server.token,
        bridge=server.bridge,
    )
    if session.resumed_from:
        print(f"--- resuming session {session.resumed_from} (phase {session.registry.current_phase()}) ---")
    else:
        print("--- new session ---")
    print("(empty line or Ctrl-D to end)\n")

    try:
        async for message in session.start(prompt):
            _render(message)
        while not once:
            try:
                user_text = await asyncio.get_running_loop().run_in_executor(None, lambda: input("> "))
            except EOFError:
                break
            if not user_text.strip():
                break
            async for message in session.send(user_text):
                _render(message)
    finally:
        await session.close()
        server.stop()

    if session.session_id:
        print(f"Session id: {session.session_id} (bound to phase {session.registry.current_phase()})")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Tuning project folder (default: AUTOSOUND_PROJECT_DIR or the saved choice)",
    )
    parser.add_argument("--prompt", default=None, help="Opening prompt instead of the default resume prompt")
    parser.add_argument("--once", action="store_true", help="Run one turn and exit (for smoke tests)")
    args = parser.parse_args(argv)

    project_dir = args.project_dir or config.project_dir()
    if not config.looks_like_project(project_dir):
        print(
            f"warning: {project_dir} doesn't look like a tuning project "
            "(no autosound_context.md / rew_analitic / dsp_profile.json)",
            file=sys.stderr,
        )
    asyncio.run(_run(Path(project_dir), args.prompt, args.once))
    return 0


if __name__ == "__main__":
    sys.exit(main())
