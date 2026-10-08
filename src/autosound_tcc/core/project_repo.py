"""The project folder as a git repository — through the method's `project_repo.py` (hub #199).

The method makes a new project a repository when it seeds it, and for one made before that (the
Arbiter's `EPY-Sep2026`) it has one command: `project_repo.py init <project>`. The GitHub backup
it offers and never makes: `status --json` carries the `gh repo create … --private --push` line,
and running it is the Arbiter's yes — a remote is outward-facing.

TCC runs the method's commands and reports what they said. A method older than `project_repo.py`
answers "update the method", not a failure. The copy that runs is the one the project is bound to
(#169), started through `method_cli` as every method script is; the GitHub offer is `gh`'s own
line, and no copy's.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autosound_tcc.core import app_log, child, method_cli, vendor_loader

#: Ten minutes: a first push carries the project's captures, and 120 s was not enough for one
#: (Ruling 48). Still a bound: the push's tree is killed at it (`child.run_bounded`).
_TIMEOUT_S = 600

#: The method's command, relative to its `rew_tool/`.
_SCRIPT = "project_repo.py"


@dataclass(frozen=True)
class RepoResult:
    ok: bool
    said: str
    too_old: bool = False


def script_path() -> Path:
    """TCC's own `project_repo.py`, for a caller with no project (`available`). A command on a
    project runs the copy that project is bound to (`_run`)."""
    return vendor_loader.REW_TOOL_DIR / _SCRIPT


def available() -> bool:
    """Whether TCC's own copy has the command, for a caller with no project. A project is answered
    for by the copy it is bound to, when a command runs on it: `init`'s `too_old`, and for the
    backup's second step `backup_status` — too old there, or refused, with nothing run."""
    return script_path().is_file()


def _run(project: Path, args: list[str]) -> tuple[int, str, str]:
    """`project_repo.py *args` of the copy `project` is bound to, through `method_cli.spawn`:
    bounded, in that copy's environment, and with no lock — the lock's own `process/` has no place
    in a folder being made a repository. Raises `method_cli.ProcessWriterError`: `ScriptMissing`
    for a copy older than the command, `Refused` with the binding's sentence (said in the log by
    `method_cli`), any other for a run that did not come back."""
    try:
        return method_cli.spawn(project, _SCRIPT, args, timeout_s=_TIMEOUT_S, lock=False)
    except method_cli.Refused:
        raise
    except method_cli.ProcessWriterError as exc:
        app_log.logger().info("project repo: %s failed: %s", args[0], exc)
        raise


def init(project: Path) -> RepoResult:
    """`git init`, the `.gitignore`, one first commit — the method's own way."""
    try:
        code, out, err = _run(project, ["init", str(project)])
    except method_cli.ScriptMissing:
        return RepoResult(False, "", too_old=True)
    except method_cli.ProcessWriterError as exc:
        return RepoResult(False, str(exc))
    app_log.logger().info("project repo: init -> exit %s", code)
    return RepoResult(code == 0, out or err)


def backup_status(project: Path) -> dict | RepoResult:
    """What the backup's second step reads: `{repo, remote, gh, init, offer}` as the method reports
    it — or, when there is none, the failed `RepoResult` that says why, for the window to say as it
    says `init`'s. `too_old` for a copy without `project_repo.py`; the binding's sentence for a copy
    TCC will not run (#169); the method's own words for a run that failed or did not answer with a
    status. So «gh is not signed in» follows only from the method saying so: a failure read as an
    empty status said it."""
    try:
        code, out, err = _run(project, ["status", str(project), "--json"])
    except method_cli.ScriptMissing:
        return RepoResult(False, "", too_old=True)
    except method_cli.ProcessWriterError as exc:
        return RepoResult(False, str(exc))
    if code != 0:
        return RepoResult(False, err or out or f"{_SCRIPT} status exited {code}")
    try:
        answer = json.loads(out)
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        return RepoResult(False, f"{_SCRIPT} status did not answer with a status"
                                 + (f": {out[:200]}" if out else ""))
    return answer


def status(project: Path) -> Optional[dict]:
    """`{repo, remote, gh, init, offer}` as the method reports it, or None when it cannot — a
    method older than the command, a copy TCC will not run, a run that did not answer;
    `backup_status` says which."""
    answer = backup_status(project)
    return answer if isinstance(answer, dict) else None


def run_offer(offer: str, project: Path) -> RepoResult:
    """Run the method's `gh repo create …` line — only ever after the Arbiter said yes to it."""
    argv = shlex.split(offer)
    if not argv or argv[0] != "gh":
        return RepoResult(False, f"not a gh command: {offer}")
    try:
        # Bounded with the tree killed: gh pushes through git, and git through its https helper,
        # all on gh's pipes, and this runs on the GUI thread (review of tcc#132).
        proc = child.run_bounded(argv, text=True, encoding="utf-8", errors="replace",
                                 timeout=_TIMEOUT_S, cwd=str(project), **child.quiet())
    except (OSError, subprocess.SubprocessError) as exc:
        return RepoResult(False, f"{type(exc).__name__}: {exc}")
    app_log.logger().info("project repo: gh repo create -> exit %s", proc.returncode)
    return RepoResult(proc.returncode == 0, (proc.stdout.strip() or proc.stderr.strip()))
