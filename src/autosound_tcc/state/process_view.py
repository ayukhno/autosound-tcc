"""Read the skill's process state (SCR-004) into the shapes the plan panel already renders.

TCC is a schema *consumer*: the skill owns `process/process-state.json` and is the only writer in
v1. This module does the one job on the boundary — turn that file into the `PlanPhase`/`PlanStep`
tuples `ui/tcc/plan_panel.py` was built against, so the renderer needs no changes and the mock and
the real thing stay interchangeable.

The mock's own phase numbering (0..6) was illustrative; the skill's skeleton is **−1..5**
(`references/core/process-phases.md`), so a project with real state shows different phases than
the demo does. That is the mock being wrong, not the reader.

Returns `None` when the project has no process state yet, which is the signal to keep rendering
the mock rather than showing an empty plan that looks like a finished one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from autosound_tcc.core import config, vendor_loader
from autosound_tcc.ui.tcc.mock_data import PlanPhase, PlanStep

# process-state's step status -> the tag chip the panel already styles.
_STATUS_TAGS = {
    "done": ({"en": "ok", "uk": "ок"}, "ok"),
    "in_progress": ({"en": "in progress", "uk": "в роботі"}, "wait"),
    "blocked": ({"en": "blocked", "uk": "заблоковано"}, "wait"),
    "skipped": ("", ""),
    "todo": ("", ""),
}


def process_dir(project_dir: Optional[Path] = None) -> Path:
    """`<project>/process` — the skill's namespace, which TCC reads and never writes."""
    return Path(project_dir or config.project_dir()) / "process"


def has_process_state(project_dir: Optional[Path] = None) -> bool:
    return (process_dir(project_dir) / "process-state.json").is_file()


def state_file(project_dir: Optional[Path] = None) -> Path:
    return process_dir(project_dir) / "process-state.json"


def load_state(project_dir: Optional[Path] = None) -> Optional[dict]:
    """The raw process-state dict, or None if this project has none / the skill isn't vendored."""
    if not has_process_state(project_dir):
        return None
    try:
        process = vendor_loader.load_process()
    except vendor_loader.VendorNotInitializedError:
        return None
    return process.Process(str(process_dir(project_dir))).load()


def load_plan(project_dir: Optional[Path] = None) -> Optional[tuple[PlanPhase, ...]]:
    """The real plan as `PlanPhase` tuples, or None when there is no process state to read."""
    state = load_state(project_dir)
    return to_plan(state) if state else None


def to_plan(state: dict) -> tuple[PlanPhase, ...]:
    """Map one process-state dict onto the panel's dataclasses.

    Phase order comes from the skill's own tuple rather than the JSON object's key order: a phase
    the project has never entered still has to appear, in the right place, as `todo`.
    """
    process = vendor_loader.load_process()
    active = state.get("active_phase")
    phases_meta = state.get("phases", {})
    steps_by_phase: dict[str, list[dict]] = {}
    for step in state.get("plan", []):
        steps_by_phase.setdefault(str(step.get("phase")), []).append(step)

    out: list[PlanPhase] = []
    for key in process.PHASES:
        meta = phases_meta.get(key, {})
        title = meta.get("title") or process.PHASE_TITLES.get(key, key)
        out.append(
            PlanPhase(
                status=meta.get("status", "todo"),
                current=key == active,
                name={"en": f"Phase {key} · {title}", "uk": f"Фаза {key} · {title}"},
                steps=tuple(_to_step(s) for s in steps_by_phase.get(key, [])),
            )
        )
    return tuple(out)


def _to_step(step: dict) -> PlanStep:
    tag, tag_class = _STATUS_TAGS.get(step.get("status", "todo"), ("", ""))
    return PlanStep(
        id=str(step.get("id", "")),
        # Real step names are plain strings from the skill; `i18n.tx` passes those through
        # unchanged, so no per-language wrapper is needed (and inventing one would imply a
        # translation that does not exist).
        name=step.get("name", ""),
        tag=tag,
        tag_class=tag_class,
        source=step.get("source", "skill"),
        skip=bool(step.get("skip")),
        attempt=int(step.get("attempt", 1) or 1),
    )


def done_step_ids(state: dict) -> set[str]:
    """Steps the skill considers done — the panel's checkboxes should reflect these, not guess."""
    return {
        str(s.get("id"))
        for s in state.get("plan", [])
        if s.get("status") == "done"
    }


def reviewer(state: dict) -> Optional[dict]:
    """Last reviewer call recorded by the skill (vendor/model/when), or None."""
    return state.get("reviewer")
