"""Drive the skill's process writer (`rew_tool/state/process.py`) — TCC never writes the journal.

Same boundary as `core/profile_writer.py`, for the same reason, and closing the same kind of hole.
`dsp_profile.json` used to be written by TCC because the skill had no writer; `process/journal.jsonl`
has had a writer all along, and the hole was on this side: the MCP surface offered the model
`report_phase`, which *reads* the process and refreshes what the Arbiter sees, and nothing at all
that records a move. So an agent that wanted to record one had to find `state/process.py` on disk
and run it through a shell, which is exactly where the measured runs came apart — one model resolved
the path and the interpreter by itself and recorded eleven events, another used the same tools and
recorded none (`spike/HANDOFF.md` §3).

What crosses this boundary is an INTENT ("the `lang` step is done, here is the evidence"), never a
finished file. The gates stay on the skill's side, where the schema is owned: `done` without
evidence is refused there, and the refusal comes back verbatim through `ProcessWriterError` — the
interviewer needs to hear what the gate said, not a generic failure.

Two things this fixes for free, both measured skill defects (SCR-028, SCR-029): the interpreter is
`sys.executable` — TCC's own venv, never a bare `python` the shell has to guess — and the script is
located through `vendor_loader`, not through an address only one harness understands.

Reads stay where they were: `mcp_server._load_process_state()` imports the skill's module in-process
and calls `Process(...).load()`. Writes go out-of-process for the same reason profile writes do —
one implementation of "record a step" in the world rather than an in-process copy that drifts.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from autosound_tcc.core import vendor_loader

# Local file I/O and a JSON rewrite; anything near this is a hang, not slowness.
DEFAULT_TIMEOUT_S = 20.0


class ProcessWriterError(RuntimeError):
    """The skill's writer refused or could not run. Carries its own message verbatim.

    A refusal is information, not a crash: `done` rejecting a step with no evidence is the план-факт
    gate doing its job (SCR-004), and the caller has to be told exactly that so it can supply the
    evidence rather than retry the same call.
    """


def script_path() -> Path:
    return vendor_loader.REW_TOOL_DIR / "state" / "process.py"


def is_available() -> bool:
    return script_path().is_file()


def _process_dir(project_dir: Path) -> Path:
    """The skill owns the layout; `process.py` creates the directory on first write."""
    return project_dir / "process"


def _run(project_dir: Path, args: list[str], timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    script = script_path()
    if not script.is_file():
        raise ProcessWriterError(
            f"process.py not found at {script}. Run: git submodule update --init --recursive"
        )
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(_process_dir(project_dir)), *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        raise ProcessWriterError(f"process.py timed out after {timeout_s:.0f}s") from None
    except OSError as exc:
        raise ProcessWriterError(str(exc)) from None
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        raise ProcessWriterError(message or f"process.py exited {proc.returncode}")
    return (proc.stdout or "").strip()


def enter_phase(project_dir: Path, phase: str) -> str:
    """Make a phase current. Phases are the skill's fixed skeleton (−1…5), never invented."""
    return _run(project_dir, ["enter-phase", str(phase)])


def add_step(project_dir: Path, step_id: str, name: str, situational: bool = False) -> str:
    """Add a plan step. `situational=True` marks it `source: project` — an insert this car needed,
    as opposed to one instantiated from the phase template."""
    args = ["add-step", step_id, name]
    if situational:
        args.append("--project")
    return _run(project_dir, args)


def start_step(project_dir: Path, step_id: str) -> str:
    """Begin, or re-begin, a step. A re-begin is attempt N+1 — a redo is recorded, never erased."""
    return _run(project_dir, ["start", step_id])


def finish_step(project_dir: Path, step_id: str, evidence: list[str]) -> str:
    """Mark a step done. Evidence is required by the skill and this does not soften that.

    Passing an empty list reaches the same refusal the CLI gives, just without spending a
    subprocess on it.
    """
    if not evidence:
        raise ProcessWriterError(
            f"step {step_id!r} cannot be done without evidence "
            "(measurement names, ledger vNNN, or an audit entry)"
        )
    return _run(project_dir, ["done", step_id, *[str(e) for e in evidence]])


def skip_step(project_dir: Path, step_id: str, superseded_by: str = "") -> str:
    """Supersede a step. It stays visible in the plan — steps are never deleted (SCR-004)."""
    args = ["skip", step_id]
    if superseded_by:
        args.append(superseded_by)
    return _run(project_dir, args)


def block_step(project_dir: Path, step_id: str, reason: str) -> str:
    """Mark a step blocked, with the reason that blocks it."""
    return _run(project_dir, ["block", step_id, reason])


def record_reviewer(project_dir: Path, vendor: str, model: str, step: str = "") -> str:
    """Record a reviewer/critic call against the step it was called on."""
    args = ["reviewer", vendor, model]
    if step:
        args.append(step)
    return _run(project_dir, args)


def set_target(project_dir: Path, preset: str, curve: str) -> str:
    """Point a preset at its active target curve."""
    return _run(project_dir, ["target", preset, curve])


def check(project_dir: Path) -> str:
    """List done steps that carry no evidence — the skill's own план-факт reconciliation."""
    return _run(project_dir, ["check"])


def plan(project_dir: Path, phase: Optional[str] = None) -> str:
    """The plan for a phase (default: the active one), as the skill prints it."""
    args = ["plan"]
    if phase is not None:
        args.append(str(phase))
    return _run(project_dir, args)


def state(project_dir: Path) -> Any:
    """The current state as the CLI reports it.

    Prefer `mcp_server._load_process_state()` in-process for reads; this exists so a caller that
    already has this module does not need a second import path for a one-off.
    """
    import json

    out = _run(project_dir, ["show"])
    try:
        return json.loads(out)
    except ValueError:
        raise ProcessWriterError(f"expected JSON from process.py show, got: {out[:200]}") from None
