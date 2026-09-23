"""The project folder as a git repository — through the method's `project_repo.py` (hub #199).

The method makes a new project a repository when it seeds it, and for one made before that (the
Arbiter's `EPY-Sep2026`) it has one command: `project_repo.py init <project>`. The GitHub backup
it offers and never makes: `status --json` carries the `gh repo create … --private --push` line,
and running it is the Arbiter's yes — a remote is outward-facing.

TCC runs the method's commands and reports what they said. A vendored method older than
`project_repo.py` answers "update the method", not a failure.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autosound_tcc.core import app_log, child, vendor_loader

_TIMEOUT_S = 120


@dataclass(frozen=True)
class RepoResult:
    ok: bool
    said: str
    too_old: bool = False


def script_path() -> Path:
    return vendor_loader.REW_TOOL_DIR / "project_repo.py"


def available() -> bool:
    return script_path().is_file()


def _run(argv: list[str]) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=_TIMEOUT_S,
                              env=vendor_loader.child_env(), **child.quiet())
    except (OSError, subprocess.SubprocessError) as exc:
        app_log.logger().info("project repo: %s failed: %s", argv[2:4], type(exc).__name__)
        return None


def init(project: Path) -> RepoResult:
    """`git init`, the `.gitignore`, one first commit — the method's own way."""
    if not available():
        return RepoResult(False, "", too_old=True)
    proc = _run([child.script_interpreter(), str(script_path()), "init", str(project)])
    if proc is None:
        return RepoResult(False, "")
    said = (proc.stdout.strip() or proc.stderr.strip())
    app_log.logger().info("project repo: init -> exit %s", proc.returncode)
    return RepoResult(proc.returncode == 0, said)


def status(project: Path) -> Optional[dict]:
    """`{repo, remote, gh, init, offer}` as the method reports it, or None when it cannot."""
    if not available():
        return None
    proc = _run([child.script_interpreter(), str(script_path()), "status", str(project), "--json"])
    if proc is None or proc.returncode != 0:
        return None
    try:
        answer = json.loads(proc.stdout)
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None


def run_offer(offer: str, project: Path) -> RepoResult:
    """Run the method's `gh repo create …` line — only ever after the Arbiter said yes to it."""
    argv = shlex.split(offer)
    if not argv or argv[0] != "gh":
        return RepoResult(False, f"not a gh command: {offer}")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=_TIMEOUT_S, cwd=str(project),
                              **child.quiet())
    except (OSError, subprocess.SubprocessError) as exc:
        return RepoResult(False, f"{type(exc).__name__}: {exc}")
    app_log.logger().info("project repo: gh repo create -> exit %s", proc.returncode)
    return RepoResult(proc.returncode == 0, (proc.stdout.strip() or proc.stderr.strip()))
