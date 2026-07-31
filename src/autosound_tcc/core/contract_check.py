"""Run the skill's whole-project contract check (`rew_tool/contract.py`) and parse its report.

`contract.py` is the one command both repos key off (SKILL-SYNC-PLAN.md §2.3): "is this project's
machine data consistent, and at what schema version". It walks every machine file the skill owns
— `project.json`, `dsp_profile.json`, `process/process-state.json` + `journal.jsonl`, each preset's
ledger — plus the cross-file checks no single module can do alone, and prints `--json` for exactly
this consumer.

**Subprocess, not `vendor_loader`** — deliberate, and the reason `contract.py` is the one vendored
module `vendor_loader._VENDORED` does not register. It is shaped as a CLI: it mutates `sys.path`
to reach its own siblings, lazily imports `state/`'s modules under bare names (`state`, `process`)
that would collide with our own `autosound_tcc.state` package, and probes REW over HTTP. Running it
out-of-process keeps all of that on the far side of a pipe — the same pattern TCC already uses for
the Critic scripts (`core/critic.py`).

Read-only in both directions: `contract.py` writes nothing, and neither does this module. A failed
run is reported as `ContractReport.error`, never raised — a diagnostics panel that crashes the
window when the thing it diagnoses is broken would be the wrong instrument.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from autosound_tcc.core import config, vendor_loader

# Generous next to critic.py's model calls: this is local file I/O plus at most one REW probe
# (`rew_api` has its own 5s per-call timeout), so anything approaching this is a hang, not slowness.
DEFAULT_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class ContractReport:
    """One `contract.py check --json` run, or the reason there isn't one.

    `ok` follows the checker's own definition: a file that is MISSING is not a failure (a project
    that hasn't been intake'd yet is normal, not broken) — only a file that exists and fails
    validation, or a cross-file mismatch, flips it. `error` non-empty means the run itself did not
    produce a report, and every other field is empty.
    """

    ok: bool
    project_dir: str
    files: tuple[dict, ...] = ()
    cross_checks: dict = field(default_factory=dict)
    error: str = ""
    checked_at: str = ""
    duration_s: float = 0.0

    @property
    def available(self) -> bool:
        return not self.error

    def issues(self) -> tuple[str, ...]:
        """The complaints that actually make this project inconsistent — what `ok` is False for.

        Deliberately NOT every string in every `issues` list: the checker files "missing -- run
        intake" under the same key, and counting that as a defect would report a brand-new project
        as five problems deep while its own `ok` says fine. Those live in `notes()` instead.
        """
        out: list[str] = []
        for entry in self.files:
            if entry.get("valid") is False:
                out.extend(f"{entry.get('file', '?')}: {issue}" for issue in entry.get("issues") or [])
        cross = self.cross_checks or {}
        out.extend(cross.get("glossary_vs_ledgers") or [])
        out.extend(cross.get("tiers_vs_profile") or [])
        return tuple(out)

    def notes(self) -> tuple[str, ...]:
        """Everything the checker said about files that did NOT fail — "missing", "no glossary
        yet". Facts about how far intake has got, not defects."""
        return tuple(
            f"{entry.get('file', '?')}: {issue}"
            for entry in self.files
            if entry.get("valid") is not False
            for issue in entry.get("issues") or []
        )

    def open_questions(self) -> tuple[str, ...]:
        """Unresolved intake facts the checker surfaced, `<file>: <dotted.path>` per line.

        Not counted as issues — an open question is intake that hasn't happened yet, which is the
        skill's job to finish, not a broken file.
        """
        return tuple(
            f"{entry.get('file', '?')}: {question}"
            for entry in self.files
            for question in (entry.get("open_questions") or [])
        )

    def missing(self) -> tuple[str, ...]:
        return tuple(str(e.get("file", "?")) for e in self.files if not e.get("exists"))

    def rew(self) -> dict:
        return (self.cross_checks or {}).get("rew") or {}


def script_path() -> Path:
    """The vendored checker. Absent when the submodule hasn't been checked out."""
    return vendor_loader.REW_TOOL_DIR / "contract.py"


def is_available() -> bool:
    return script_path().is_file()


def run(
    project_dir: Optional[Path] = None,
    skip_rew: bool = False,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    python_executable: Optional[str] = None,
) -> ContractReport:
    """Check one project and parse the JSON report. Never raises.

    `skip_rew` maps to the CLI's `--no-rew`, for a purely static audit (the REW leg is best-effort
    on the checker's side already: REW not running is REPORTED, not an error).
    """
    project_dir = Path(project_dir or config.project_dir())
    started = time.monotonic()
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def failed(message: str) -> ContractReport:
        return ContractReport(
            ok=False,
            project_dir=str(project_dir),
            error=message,
            checked_at=checked_at,
            duration_s=time.monotonic() - started,
        )

    script = script_path()
    if not script.is_file():
        return failed(
            f"contract.py not found at {script}. "
            "Run: git submodule update --init --recursive"
        )

    argv = [
        python_executable or sys.executable,
        str(script),
        "check",
        str(project_dir),
        "--json",
    ]
    if skip_rew:
        argv.append("--no-rew")

    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return failed(f"contract.py timed out after {timeout_s:.0f}s")
    except OSError as exc:
        return failed(str(exc))

    # Exit code 1 is the checker's "issues found", not a run failure — the report on stdout is the
    # answer either way. Only an unparseable stdout means we genuinely have nothing.
    try:
        report = json.loads(proc.stdout or "")
    except ValueError:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-6:])
        return failed(tail or f"contract.py produced no report (exit {proc.returncode})")

    files = report.get("files") or []
    return ContractReport(
        ok=bool(report.get("ok")),
        project_dir=str(report.get("project_dir") or project_dir),
        files=tuple(f for f in files if isinstance(f, dict)),
        cross_checks=report.get("cross_checks") or {},
        checked_at=checked_at,
        duration_s=time.monotonic() - started,
    )
