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
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from autosound_tcc.core import child as child_process
from autosound_tcc.core import app_log, config, method_cli, vendor_loader

# Generous next to critic.py's model calls: this is local file I/O plus at most one REW probe
# (`rew_api` has its own 5s per-call timeout), so anything approaching this is a hang, not slowness.
DEFAULT_TIMEOUT_S = 30.0

#: The checker, relative to the method's `rew_tool/`.
_SCRIPT = "contract.py"


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
    #: Facts carried in from another project, `{path, value, from, from_exists}` each, and the
    #: source paths that no longer exist (the method's v3.0.53, hub #154 §3). Reported, never
    #: gated: not issues, and not in `ok`.
    inherited: tuple[dict, ...] = ()
    sources_gone: tuple[str, ...] = ()
    #: The phase −1 gate: intake left everything phase 0 needs (`contract.py`'s own `complete`,
    #: what `--gate` exits on). False when the method does not say -- not a green gate.
    complete: bool = False

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

    def continue_head(self) -> Optional[dict]:
        """`{named, heads, stale, warning}` when `tuning-changelog`'s ▶️ CONTINUE block names a
        HEAD the ledger is not at, else None (the method's v3.0.65, S-084, hub #227).

        A warning, never a defect: the checker keeps it out of `ok`, and so `issues()` keeps it
        out of the count. None also for a method that does not say, and for "no opinion" -- no
        changelog, or a block that names no version.
        """
        drift = (self.cross_checks or {}).get("continue_head")
        return drift if isinstance(drift, dict) and drift else None


def script_path() -> Path:
    """TCC's own checker, for a caller with no project (`is_available`). Absent when the submodule
    hasn't been checked out. `run` checks a project with the copy that project is bound to."""
    return vendor_loader.REW_TOOL_DIR / _SCRIPT


def is_available() -> bool:
    return script_path().is_file()


class _Cancellable(subprocess.Popen):
    """A `Popen` that remembers it was killed on purpose.

    Whoever holds the handle (`register`) cancels by calling `kill()`, and the only trace of that
    on POSIX is a negative return code. Windows does not do negative codes at all, so the fact has
    to be kept rather than deduced.
    """

    cancelled = False

    def kill(self) -> None:
        self.cancelled = True
        super().kill()

    def terminate(self) -> None:
        self.cancelled = True
        super().terminate()


def run(
    project_dir: Optional[Path] = None,
    skip_rew: bool = False,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    python_executable: Optional[str] = None,
    register: Optional[Callable[[subprocess.Popen], None]] = None,
) -> ContractReport:
    """Check one project and parse the JSON report. Never raises.

    `skip_rew` maps to the CLI's `--no-rew`, for a purely static audit (the REW leg is best-effort
    on the checker's side already: REW not running is REPORTED, not an error).

    `register` is handed the child process as soon as it exists, so a caller running this on a
    thread can end it early. Without that the only way out is the 30 s timeout, and a window
    closed mid-check would have to be waited on for that long -- or the thread destroyed under
    Qt, which aborts the process.

    The checker is the one of the copy the project is bound to (#169), from `method_cli.resolve` --
    the answer `method_cli.spawn` runs; a child a caller may cancel cannot be its bounded run, so
    the `Popen` stays here. A copy TCC will not run is an error report carrying the binding's
    sentence, with nothing started.
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

    args = ["check", str(project_dir), "--json"]
    if skip_rew:
        args.append("--no-rew")
    try:
        script, env = method_cli.resolve(project_dir, _SCRIPT, args)
    except method_cli.Refused as exc:
        return failed(str(exc))
    if not script.is_file():
        return failed(
            f"contract.py not found at {script}. "
            "Run: git submodule update --init --recursive"
        )

    argv = [
        # The console interpreter rather than TCC's own windowed one — see
        # `child.script_interpreter`: a script started by `pythonw.exe` has no console to hand
        # down, so whatever it runs opens a window of its own.
        python_executable or child_process.script_interpreter(),
        str(script),
        *args,
    ]

    try:
        # `child_process.quiet()`: no stdin to wait on, and no console window flashed on Windows
        # every time the checker runs (see `core/child.py`). Named on import to keep the local
        # variable `child` — the process — as it was.
        proc = _Cancellable(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace",
                            env=env, **child_process.quiet())
    except OSError as exc:
        return failed(str(exc))
    if register is not None:
        register(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return failed(f"contract.py timed out after {timeout_s:.0f}s")
    cancelled = proc.cancelled
    proc = subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
    if cancelled or (proc.returncode is not None and proc.returncode < 0):
        # Killed rather than finished -- a cancel from `register`'s owner. Not an error the user
        # needs told about; the caller that cancelled is on its way out.
        #
        # A negative code is not enough to know that: it is the POSIX way of saying "died by
        # signal", and Windows has no such convention -- `TerminateProcess` sets an ordinary exit
        # code of 1. So a window closing mid-check told the user "contract.py produced no report
        # (exit 1)", which is an error message for something that is not an error (found on the
        # first Windows CI run, 2026-09-07). The intent is recorded where it is known -- in the
        # kill itself -- instead of being inferred afterwards from a number.
        return failed("contract.py was cancelled")

    # Exit code 1 is the checker's "issues found", not a run failure — the report on stdout is the
    # answer either way. Only an unparseable stdout means we genuinely have nothing.
    try:
        report = json.loads(proc.stdout or "")
    except ValueError:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-6:])
        return failed(tail or f"contract.py produced no report (exit {proc.returncode})")

    return report_from_json(report, project_dir, checked_at, time.monotonic() - started)


def report_from_json(report: Any, project_dir, checked_at: str, duration_s: float) -> ContractReport:
    """`contract.py check --json`'s answer as a `ContractReport`. Never raises (F16-5): an answer
    that is not an object is a run that produced no report — `run` promises never to raise, and
    this is the last thing it calls. A field of the wrong shape reads as empty AND is said: the
    report is then an error, not a green verdict over nothing (the G1 review), and `ok` and
    `complete` are true only when they say `true` — `bool("false")` is True."""
    if not isinstance(report, dict):
        return ContractReport(
            ok=False, project_dir=str(project_dir), checked_at=checked_at, duration_s=duration_s,
            error=f"contract.py answered with a JSON {type(report).__name__}, not an object")

    def rows(key: str) -> tuple:
        value = report.get(key)
        return tuple(row for row in value if isinstance(row, dict)) if isinstance(value, list) else ()

    shapes = {"ok": bool, "complete": bool, "files": list, "inherited": list,
              "cross_checks": dict, "sources_gone": list, "project_dir": str}
    wrong = [f"`{key}` as {type(report[key]).__name__}" for key, kind in shapes.items()
             if report.get(key) is not None and not isinstance(report[key], kind)]
    error = ("contract.py's report has " + ", ".join(wrong)) if wrong else ""
    if error:
        app_log.logger().warning("%s; TCC cannot read it as a verdict", error)

    cross, gone = report.get("cross_checks"), report.get("sources_gone")
    return ContractReport(
        ok=report.get("ok") is True and not wrong,
        error=error,
        project_dir=str(report.get("project_dir") or project_dir),
        files=rows("files"),
        cross_checks=cross if isinstance(cross, dict) else {},
        checked_at=checked_at,
        duration_s=duration_s,
        inherited=rows("inherited"),
        sources_gone=tuple(str(path) for path in gone) if isinstance(gone, list) else (),
        complete=report.get("complete") is True and not wrong,
    )
