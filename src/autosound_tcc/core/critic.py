"""The Critic channel — a wrapper around the skill's own reviewer scripts, not a new integration.

The tuning method is a three-role loop (SKILL.md §Three Roles): the Generator proposes, the
Critic challenges, the Arbiter decides. The Critic is deliberately **stateless** — a one-shot call
that re-reads state from disk — which is what makes it a drift-watchdog rather than a second
agent, and what makes it cheap to run as a subprocess.

The skill already ships a working reviewer channel, so TCC calls it instead of building one:
`scripts/autosound_ai.py <role> <package.md> [trace.csv]`. That script is stdlib-only and
cross-platform (its bash sibling `gemini_critic.sh` is macOS/Linux), and it already knows how to
reach a local CLI (`agy`/`gemini`), a cloud API, or fall back to the clipboard.

**The contract that matters, and the trap in it:** the critique is written to *stdout* and ends
with a `— [critic: <model>]` marker; progress goes to *stderr*. When neither an API nor a CLI is
reachable the script does not fail — it compiles the package, copies it to the clipboard, and
returns **exit code 0 with empty stdout**. So a caller that trusts the return code reports success
and shows an empty critique. Clipboard mode is a legitimate outcome (it is the zero-cost path:
paste into any free web chat and bring the answer back), but it has to be reported as *manual*,
never as an answer.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from autosound_tcc.core import config, vendor_loader

DEFAULT_TIMEOUT_S = 600.0
# The script prints this as its last stdout line on a real answer: `— [critic: Gemini 3.1 Pro]`.
_MODEL_MARKER = re.compile(r"^—\s*\[(?P<role>\w+):\s*(?P<model>.+?)\]\s*$", re.MULTILINE)
_CLIPBOARD_MARKER = "CLIPBOARD MODE"
# The script writes the critique to `process/reviews/<ts>-<role>.md` and says so on stderr in two
# forms; this is the machine-readable one, so nothing here parses a translated sentence (SCR-027).
_REVIEW_MARKER = re.compile(r"^>>\s*REVIEW_FILE:\s*(?P<path>.+?)\s*$", re.MULTILINE)

MODE_API_OR_CLI = "answered"
MODE_CLIPBOARD = "clipboard"
MODE_ERROR = "error"
#: The reviewer was not called because the PROJECT is not ready — no contract, no context, which
#: is the ordinary state of a folder that has not been through intake yet. Distinct from
#: `MODE_ERROR` because it is not a fault and reporting it as one sends somebody debugging a
#: working channel: on a fresh project the first thing anyone tries is "check the reviewer", and
#: what came back was two missing filenames in English under a Ukrainian UI (user, 2026-08-13).
MODE_NOT_READY = "not_ready"


@dataclass(frozen=True)
class CriticResult:
    """What came back from one reviewer call."""

    mode: str  # answered | clipboard | error | not_ready
    text: str  # the critique itself, marker line stripped; "" unless mode == answered
    model: Optional[str]  # as reported by the script, e.g. "Gemini 3.1 Pro (High)"
    role: str
    detail: str  # stderr tail — why it fell back, or what failed
    duration_s: float
    called_at: str
    # Project-relative path to the critique's own text (SCR-027). The reasoning used to live only
    # in the chat stream, so a session rendered from disk knew a review happened and not what it
    # argued. `None` when the script could not write it.
    review: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.mode == MODE_API_OR_CLI


def script_path() -> Path:
    """`autosound_ai.py` inside the vendored skill."""
    return vendor_loader.REW_TOOL_DIR.parent / "scripts" / "autosound_ai.py"


def is_available() -> bool:
    return script_path().is_file()


def _project_mirror(project_dir: Path) -> Path:
    """Where the script looks for the data contract and project context."""
    return project_dir / "rew_analitic"


def preflight(project_dir: Optional[Path] = None) -> list[str]:
    """Reasons the Critic cannot run yet, as user-facing lines. Empty list = ready.

    Checked here rather than left to the script because the script exits with a bare message on a
    missing file, and "nothing happened" is the worst thing a button can do.
    """
    project_dir = Path(project_dir or config.project_dir())
    problems: list[str] = []
    if not is_available():
        problems.append(f"reviewer script not found at {script_path()}")
    mirror = _project_mirror(project_dir)
    for name in ("data-contract-template.md", "autosound_context.md"):
        if not (mirror / name).is_file():
            problems.append(f"{name} missing from {mirror}")
    return problems


def package_dir(project_dir: Optional[Path] = None) -> Path:
    """Where TCC drops packages it composed itself.

    Under `.tcc/` rather than `rew_analitic/`: packages the skill's Generator writes belong to the
    project record and are named by the skill, and mixing TCC-generated ones into the same folder
    would blur which of the two authored a given review.
    """
    return config.tcc_dir(project_dir) / "packages"


def write_package(markdown: str, project_dir: Optional[Path] = None) -> Path:
    """Persist a package so the reviewer call has a file to read, and so the call is auditable."""
    folder = package_dir(project_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"pkg_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def run(
    package: str,
    project_dir: Optional[Path] = None,
    trace_path: Optional[str] = None,
    role: str = "critic",
    model: Optional[str] = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    python_executable: Optional[str] = None,
) -> CriticResult:
    """Call the reviewer once. `package` is either markdown or a path to an existing package file.

    `model` overrides the script's own default through the env var it already reads
    (`GEMINI_CRITIC_MODEL` / `GEMINI_ADVISOR_MODEL`), so the footer's model picker steers the
    subprocess without this module knowing anything about model names.
    """
    python_executable = python_executable or sys.executable
    project_dir = Path(project_dir or config.project_dir())
    started = time.monotonic()
    called_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    problems = preflight(project_dir)
    if problems:
        # A missing SCRIPT is a broken install; missing project files are a project that has not
        # started yet. Same list, two different things to say about it.
        mode = MODE_ERROR if not is_available() else MODE_NOT_READY
        return CriticResult(mode, "", None, role, "; ".join(problems), 0.0, called_at)

    candidate = Path(package)
    package_path = candidate if candidate.suffix == ".md" and candidate.is_file() else write_package(
        package, project_dir
    )

    argv = [python_executable, str(script_path()), role, str(package_path)]
    if trace_path:
        argv.append(str(trace_path))

    env_overrides = {"PROJECT_MIRROR": str(_project_mirror(project_dir))}
    if model:
        env_overrides["GEMINI_CRITIC_MODEL" if role == "critic" else "GEMINI_ADVISOR_MODEL"] = model

    env = vendor_loader.child_env(**env_overrides)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(project_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return CriticResult(
            MODE_ERROR, "", None, role, f"reviewer timed out after {timeout_s:.0f}s",
            time.monotonic() - started, called_at,
        )
    except OSError as exc:
        return CriticResult(
            MODE_ERROR, "", None, role, str(exc), time.monotonic() - started, called_at
        )

    duration = time.monotonic() - started
    stdout, stderr = proc.stdout or "", proc.stderr or ""
    tail = "\n".join(line for line in stderr.strip().splitlines()[-6:])

    # Deliberately not `proc.returncode == 0`: clipboard mode returns 0 with nothing on stdout.
    match = _MODEL_MARKER.search(stdout)
    review_match = _REVIEW_MARKER.search(stderr)
    review = review_match.group("path") if review_match else None
    if stdout.strip():
        text = _MODEL_MARKER.sub("", stdout).strip()
        return CriticResult(
            MODE_API_OR_CLI, text, match.group("model") if match else None, role, tail,
            duration, called_at, review,
        )
    if _CLIPBOARD_MARKER in stderr:
        # The clipboard path writes the compiled PACKAGE to the same place, so a review the Arbiter
        # works by hand is on the record rather than looking like no review at all.
        return CriticResult(MODE_CLIPBOARD, "", None, role, tail, duration, called_at, review)
    return CriticResult(MODE_ERROR, "", None, role, tail or "reviewer produced no output",
                        duration, called_at)


def log_path(project_dir: Optional[Path] = None) -> Path:
    return config.tcc_dir(project_dir) / "critic-log.jsonl"


def log_call(result: CriticResult, package_path: Optional[Path], project_dir: Optional[Path] = None) -> None:
    """Append one reviewer call to an append-only log.

    "Which AI reviewed this, on which model, when" is part of the process record the concept calls
    for (TCC-Concept §4: the advisor panel shows vendor/model and when it was last called). It
    lives here until SCR-004's `process-state.json` exists to hold it properly.
    """
    import json

    path = log_path(project_dir)
    entry = {
        "at": result.called_at,
        "role": result.role,
        "mode": result.mode,
        "model": result.model,
        "duration_s": round(result.duration_s, 1),
        "package": str(package_path) if package_path else None,
        "review": result.review,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # the log is a convenience; losing it must not fail the call that succeeded


def last_call(project_dir: Optional[Path] = None) -> Optional[dict]:
    """The most recent reviewer call, for the footer's advisor status. None if never called."""
    import json

    path = log_path(project_dir)
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def doctor(project_dir: Optional[Path] = None, python_executable: Optional[str] = None) -> str:
    """The script's own environment check, for a settings/status screen."""
    if not is_available():
        return f"reviewer script not found at {script_path()}"
    python_executable = python_executable or sys.executable
    project_dir = Path(project_dir or config.project_dir())
    try:
        proc = subprocess.run(
            [python_executable, str(script_path()), "doctor"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=60,
            env=vendor_loader.child_env(),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"doctor failed: {exc}"
    return (proc.stdout or proc.stderr).strip()
