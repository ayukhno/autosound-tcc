"""Codex in the user's own terminal, with TCC's tools (W-10 Codex task 8, tcc #180).

    python -m autosound_tcc.core.codex_terminal <project> [--model M]

The line «Open terminal → Codex» runs. Claude and omp find TCC through the project's `.mcp.json`
on their own; Codex does not read that file, so this reads it for Codex: TCC's url and token from
TCC's entry, the token handed over in the environment (`codex_cli.TOKEN_ENV`) and Codex started
with TCC's connection pieces only (`codex_cli.tcc_connection_args`). Nothing of the in-app
session's own switches — no approval mode, no isolation: in a terminal the user's own Codex config
rules approvals and extras (the Arbiter, 2026-10-14: «коли в терміналі — налаштування самого
кодекса»).

The token is never in argv, the terminal's line, the screen, a log line or a new file: it goes
from the file TCC already wrote into this process's memory and into Codex's environment.

The method: Codex takes an extra skills root only over app-server (`skills/extraRoots/set`), and
its config has no key for one (0.162.1: `skills` holds `bundled`, `include_instructions`,
`max_context_tokens` and per-skill `config` overrides). A terminal Codex therefore loads the
method through the project's `AGENTS.md`, and its shell runs the bound copy through
`AUTOSOUND_SKILL_ROOT`, which the launcher's line sets (`terminal_launcher.launch`, #169).

Nothing here imports Qt.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from autosound_tcc.core import codex_cli, config

#: TCC's entry in `.mcp.json` and the header its token rides in (`mcp_server.write_mcp_config`).
SERVER_NAME = "tcc"
TOKEN_HEADER = "x-tcc-token"


class Refused(Exception):
    """Codex cannot start with TCC's tools; the text is the one sentence the person reads."""


def connection(project_dir: Path) -> tuple[str, str]:
    """`(url, token)` from TCC's entry in the project's `.mcp.json`, or `Refused`."""
    path = config.mcp_config_path(Path(project_dir))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(f"{path} is not there: open this project in TCC first, then run this "
                      "again.") from None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise Refused(f"{path} could not be read ({type(exc).__name__}): open this project in "
                      "TCC again, then run this again.") from None
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    entry = servers.get(SERVER_NAME) if isinstance(servers, dict) else None
    if not isinstance(entry, dict):
        raise Refused(f"{path} has no entry for TCC: open this project in TCC, then run this "
                      "again.")
    headers = entry.get("headers")
    sent = ({str(k).lower(): v for k, v in headers.items()} if isinstance(headers, dict) else {})
    url, token = entry.get("url"), sent.get(TOKEN_HEADER)
    if not (isinstance(url, str) and url and isinstance(token, str) and token):
        raise Refused(f"TCC's entry in {path} has no address or no key: open this project in "
                      "TCC again, then run this again.")
    return url, token


def _codex() -> codex_cli.Found:
    """The native Codex binary (never a shim), not one known to be too old — or `Refused`."""
    found = codex_cli.find()
    if found is None:
        raise Refused("Codex is not installed on this computer: install it "
                      "(`npm install -g @openai/codex`), then run this again.")
    read = codex_cli.version(found)  # this is a terminal, not the GUI thread: it may run
    if codex_cli.too_old(found):
        raise Refused(f"Codex {codex_cli.version_text(read)} at {found.path} is too old: TCC needs "
                      f"{codex_cli.version_text(codex_cli.MIN_VERSION)} or newer.")
    return found


def command(binary: str, url: str, model: Optional[str]) -> list[str]:
    """Codex's argv: TCC's connection pieces, then the model when one was chosen."""
    from autosound_tcc.core.codex_session import TOOL_TIMEOUT_S  # the session's own bound

    argv = [binary, *codex_cli.tcc_connection_args(url, timeout_sec=TOOL_TIMEOUT_S)]
    if model:
        argv += ["--model", model]
    return argv


def _start(argv: list[str], env: dict, cwd: Path) -> int:
    """Hand the terminal to Codex. POSIX: `execve` — this process becomes Codex. Windows has no
    such replacement (`os.execv` starts a new process and returns), so Codex runs here with this
    console's own stdio — no new window: the terminal already is one — and its code is ours."""
    if not sys.platform.startswith("win"):
        os.chdir(cwd)
        os.execve(argv[0], argv, env)
        return 0  # not reached
    proc = subprocess.Popen(argv, env=env, cwd=str(cwd))
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            continue  # Ctrl+C reached Codex too, in the same console: it decides


def _person_is_there() -> bool:
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except (AttributeError, ValueError):
        return False


def _refuse(sentence: str) -> int:
    """One sentence on stderr and a non-zero exit. The line `exec`ed this process, so a window set
    to close when its shell ends would take the sentence with it: a person at it presses Enter."""
    print(sentence, file=sys.stderr)
    if _person_is_there():
        try:
            input("Press Enter to close. ")
        except (EOFError, KeyboardInterrupt):
            pass
    return 1


def main(args: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m autosound_tcc.core.codex_terminal",
        description="Start Codex in a TCC project with TCC's tools.")
    parser.add_argument("project", help="the project folder TCC has open")
    parser.add_argument("--model", "-m", default=None, help="passed to Codex as --model")
    parsed = parser.parse_args(args)
    project = Path(parsed.project).expanduser().resolve()
    try:
        url, token = connection(project)
        found = _codex()
    except Refused as exc:
        return _refuse(str(exc))
    env = {**os.environ, codex_cli.TOKEN_ENV: token}
    return _start(command(found.path, url, parsed.model), env, project)


if __name__ == "__main__":
    sys.exit(main())
