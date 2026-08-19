"""Drive the skill's DSP-profile writer (`rew_tool/dsp_profile.py`) — TCC never writes the file.

D-6, one-way writes: the skill writes data, TCC reads it. `dsp_profile.json` was the last thing
TCC still authored itself, and for a plain reason — until SCR-025 the skill had no writer to route
an interview through, so the host app assembled the file. It has one now, and this module is how
the two front-ends reach it: the in-app onboarding chat (`core/agent_session.py`) and any external
CLI connected over MCP (`core/mcp_server.py`).

What crosses this boundary is an INTENT ("the user confirmed `sample_rate_hz` is 96000"), never a
finished file. Validation, the `dsp_profile.draft.json` that survives a lost session, the JSON-
decoding defences and the schema-version stamp all live on the skill's side, where the schema is
owned — TCC gets whatever the writer decided, including its refusals.

Subprocess, same reasoning as `core/contract_check.py`: `dsp_profile.py` is shaped as a CLI, and
running it out-of-process means there is exactly one implementation of "write a profile field" in
the world rather than an in-process copy that drifts.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from autosound_tcc.core import child
from autosound_tcc.core import vendor_loader

# Local file I/O and a JSON dump; anything near this is a hang, not slowness.
DEFAULT_TIMEOUT_S = 20.0


class ProfileWriterError(RuntimeError):
    """The skill's writer refused or could not run. Carries its own message verbatim.

    A refusal is information, not a crash: `finalize` rejecting a half-answered draft is the gate
    doing its job, and the interviewer needs to hear exactly what it said.
    """


def script_path() -> Path:
    return vendor_loader.REW_TOOL_DIR / "dsp_profile.py"


def is_available() -> bool:
    return script_path().is_file()


def _run(args: list[str], timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    script = script_path()
    if not script.is_file():
        raise ProfileWriterError(
            f"dsp_profile.py not found at {script}. Run: git submodule update --init --recursive"
        )
    try:
        proc = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=vendor_loader.child_env(), **child.quiet())
    except subprocess.TimeoutExpired:
        raise ProfileWriterError(f"dsp_profile.py timed out after {timeout_s:.0f}s") from None
    except OSError as exc:
        raise ProfileWriterError(str(exc)) from None
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        raise ProfileWriterError(message or f"dsp_profile.py exited {proc.returncode}")
    return proc.stdout


def _run_json(args: list[str]) -> Any:
    out = _run(args)
    try:
        return json.loads(out)
    except ValueError:
        raise ProfileWriterError(f"expected JSON from dsp_profile.py {args[0]}, got: {out[:200]}")


def start(project_dir: Path, vendor: str, model: str) -> dict:
    """Begin or resume the interview. Returns `{"draft": ..., "open_questions": [...]}`."""
    return _run_json(["start", str(project_dir), vendor, model])


def draft(project_dir: Path) -> dict:
    """The in-progress draft plus what is still unanswered, straight off disk."""
    return _run_json(["draft", str(project_dir)])


def set_field(project_dir: Path, path: str, value: Any) -> dict:
    """Record one confirmed field. `value` is serialised to JSON unless it is already a string —
    the writer decodes a JSON-looking string back into the real structure, which is what makes a
    list survive the round trip."""
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return _run_json(["set-field", str(project_dir), path, raw])


def reset_field(project_dir: Path, path: str) -> dict:
    return _run_json(["reset-field", str(project_dir), path])


def finalize(project_dir: Path) -> Path:
    """Promote the draft to `dsp_profile.json`. Raises `ProfileWriterError` with the writer's own
    reason when the draft is not a valid profile yet — the draft survives, so the interview can
    fix and retry."""
    out = _run(["finalize", str(project_dir)]).strip()
    return Path(out.split(" ", 1)[1]) if out.startswith("wrote ") else Path(out)


def find_bundled(vendor: str, model: str, bundled_dir: Path) -> Optional[dict]:
    """Exact vendor+model match in the reference library, or None. A read, but routed here so the
    onboarding path has one door to the skill's profile module.

    Returned UNWRAPPED (no top-level `dsp_profile` key), matching the draft's shape. An agent that
    sees the two answers in different shapes starts guessing prefixes — that is exactly how a
    `dsp_profile.dsp_profile` double-nesting reached disk in the 2026-07-29 dogfood run.
    """
    out = _run(["find-bundled", vendor, model, str(bundled_dir)]).strip()
    if not out or out == "no exact match":
        return None
    try:
        found = json.loads(out)
    except ValueError:
        return None
    return found.get("dsp_profile", found) if isinstance(found, dict) else None


def has_draft(project_dir: Path) -> bool:
    """Whether an interview has been started for this project (a draft, or an existing profile to
    correct). The onboarding tools check this so calling them out of order is a message an agent
    can act on rather than a half-filled draft that only fails much later, at finalize."""
    project_dir = Path(project_dir)
    return (project_dir / "dsp_profile.draft.json").is_file() or (
        project_dir / "dsp_profile.json"
    ).is_file()


def field_vocabulary() -> dict:
    """The only field tokens a group's `fields` may contain — read from the skill, never copied.

    In-process (`vendor_loader`) rather than by subprocess: this is a constant being READ, and the
    subprocess rule exists for writes. A copy maintained here is exactly how a consumer's renderer
    and the schema it renders drift apart.
    """
    return dict(vendor_loader.load_dsp_profile().FIELD_VOCABULARY)


def capability_checklist() -> list[str]:
    """The fixed interview questions, from the skill for the same reason as the vocabulary."""
    return list(vendor_loader.load_dsp_profile().CAPABILITY_CHECKLIST)
