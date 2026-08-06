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
from dataclasses import replace
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
# A done step whose evidence names a channel a `config_change` invalidated (SCR-014). It overrides
# the "ok" chip rather than sitting beside it: the step is not done any more in the only sense that
# matters -- what it produced can no longer be trusted.
_STALE_TAG = ({"en": "recheck", "uk": "перезняти"}, "wait")

# The skill's fixed phase skeleton, in the languages TCC speaks. Translated HERE rather than
# written translated into `process-state.json`: the phases are the method's, identical in every
# project, and a title translated at write time freezes the file into whatever language the intake
# happened to run in -- after which switching the app to EN leaves half the panel in UK. Keyed by
# the skill's own English title, so a phase whose title has been changed on purpose (or a skeleton
# this version has not seen) is left exactly as the file has it.
_PHASE_TITLES_UK = {
    "Project intake & checklist": "Прийом проєкту та чеклист",
    "Baseline & target selection": "Базовий замір і вибір цілі",
    "Crossovers, levels & delays": "Кросовери, рівні та затримки",
    "EQ & acoustic alignment": "EQ та акустичне узгодження",
    "Technical verdict & lock": "Технічний вердикт і фіксація",
    "Targeted listening → feedback → close": "Цільове прослуховування → фідбек → закриття",
    "Variations (cyclical)": "Варіації (циклічно)",
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


def capture_round(project_dir: Optional[Path] = None) -> Optional[dict]:
    """The capture round the skill has open, or None (SCR-034).

    Only the OPEN one is in `process-state.json`; every round that ever happened is in the journal,
    the same split the active phase uses. A closed round is returned as it stands — the panel still
    wants to show what the last pass produced, it just must not treat it as the live task.
    """
    state = load_state(project_dir)
    round_ = (state or {}).get("capture")
    return round_ if isinstance(round_, dict) else None


def load_plan(project_dir: Optional[Path] = None) -> Optional[tuple[PlanPhase, ...]]:
    """The real plan as `PlanPhase` tuples, or None when there is no process state to read."""
    state = load_state(project_dir)
    return to_plan(state) if state else None


def to_plan(state: dict, stale: Optional[dict] = None) -> tuple[PlanPhase, ...]:
    """Map one process-state dict onto the panel's dataclasses.

    Phase order comes from the skill's own tuple rather than the JSON object's key order: a phase
    the project has never entered still has to appear, in the right place, as `todo`.

    `stale` is `stale_channels()`'s result: a done step whose evidence names one of those channels
    is re-chipped "recheck", because what it produced no longer describes the car.
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
                name={
                    "en": f"Phase {key} · {title}",
                    "uk": f"Фаза {key} · {_PHASE_TITLES_UK.get(title, title)}",
                },
                steps=tuple(_to_step(s, stale or {}) for s in steps_by_phase.get(key, [])),
            )
        )
    return tuple(out)


def _to_step(step: dict, stale: Optional[dict] = None) -> PlanStep:
    tag, tag_class = _STATUS_TAGS.get(step.get("status", "todo"), ("", ""))
    evidence = " ".join(str(item) for item in step.get("evidence") or [])
    if evidence and any(code in evidence for code in (stale or {})):
        tag, tag_class = _STALE_TAG
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


# ---- what a config change invalidated (SCR-014) -----------------------------


def config_changes(project_dir: Optional[Path] = None) -> tuple[dict, ...]:
    """Every `config_change` event in the journal, oldest first, with its `impact` parsed.

    The parse comes from the skill (`project.Project.parse_impact`), not from a regex here: the
    field is written by the skill and a second reading of it in a consumer is how two readings
    drift apart.
    """
    process = _process_module()
    if process is None:
        return ()
    proc = process.Process(str(process_dir(project_dir)))
    if not (process_dir(project_dir) / "journal.jsonl").is_file():
        return ()
    parse = _impact_parser()
    out = []
    for event in proc.events(kinds=[process.EV_CONFIG_CHANGE]):
        event = dict(event)
        event["impact_parsed"] = parse(event.get("impact")) if parse else {
            "kind": "other", "codes": (), "raw": event.get("impact") or ""
        }
        out.append(event)
    return tuple(out)


def stale_channels(project_dir: Optional[Path] = None) -> dict[str, dict]:
    """`{channel_code: the change that invalidated it}` — what needs re-measuring, and why.

    SCR-014's whole point: a driver swap or a re-gain must flag *exactly* the affected captures,
    never silently. The rule is derived from the journal alone, so it needs no capture timestamps
    from REW (which does not reliably give them):

        a `config_change` invalidates its channels until a LATER `step_done` whose evidence names
        that channel.

    "Later" is journal ORDER, not the `at` stamps: the journal is append-only, so a later line is
    later by construction, while `at` is second-resolution — a change and the capture that answers
    it land in the same second often enough that comparing stamps drops a real clear (caught by the
    test, not in the field). One ordered pass, therefore, rather than two lists compared by time.

    The result reads as "the skill has not recorded a capture for this channel since the change" —
    the honest claim, and the one a tuner can act on. `full_rebaseline` invalidates every channel
    the glossary knows; an impact the parser cannot act on (`voicing`, free text) flags nothing,
    since guessing which channels a sentence meant is how a checklist starts lying.
    """
    process = _process_module()
    if process is None or not (process_dir(project_dir) / "journal.jsonl").is_file():
        return {}
    proc = process.Process(str(process_dir(project_dir)))
    parse = _impact_parser()

    stale: dict[str, dict] = {}
    for event in proc.events():  # oldest first
        kind = event.get("type")
        if kind == process.EV_CONFIG_CHANGE:
            parsed = parse(event.get("impact")) if parse else {"kind": "other", "codes": ()}
            codes = parsed.get("codes") or ()
            if parsed.get("kind") == "full_rebaseline":
                codes = _known_channel_codes(project_dir)
            for code in codes:
                stale[code] = {**event, "impact_parsed": parsed}
        elif kind == process.EV_STEP_DONE:
            # Evidence is free-form pointers (REW names, `v_003`, an audit entry), so a substring
            # match on the code is what actually works against what the skill writes.
            evidence = " ".join(str(item) for item in event.get("evidence") or [])
            for code in [c for c in stale if c in evidence]:
                del stale[code]
    return stale


def _known_channel_codes(project_dir: Optional[Path] = None) -> tuple[str, ...]:
    """Active channel codes from the glossary — what "everything" means for `full_rebaseline`."""
    try:
        naming = vendor_loader.load_naming()
    except vendor_loader.VendorNotInitializedError:
        return ()
    glossary = naming.Glossary.for_project(str(Path(project_dir or config.project_dir())))
    return tuple(glossary.channel_codes(active_only=True))


def _process_module():
    try:
        return vendor_loader.load_process()
    except vendor_loader.VendorNotInitializedError:
        return None


def _impact_parser():
    """`project.Project.parse_impact`, or None when the submodule isn't checked out."""
    try:
        return vendor_loader.load_project().Project.parse_impact
    except (vendor_loader.VendorNotInitializedError, AttributeError):
        return None


_UNBACKED_TAG = ({"en": "unproven", "uk": "без доказу"}, "bad")


def mark_unbacked(
    phases: tuple[PlanPhase, ...], step_ids: set[str]
) -> tuple[PlanPhase, ...]:
    """Re-tag closed steps whose evidence resolves to nothing on disk (`state.plan_audit`).

    A chip rather than an un-tick: the skill did close the step, and pretending otherwise would
    put TCC's opinion into a file it does not own. What the panel shows is the disagreement --
    which is what a panel called ПЛАН — ФАКТ is for.
    """
    if not step_ids:
        return phases
    out = []
    for phase in phases:
        steps = tuple(
            replace(step, tag=_UNBACKED_TAG[0], tag_class=_UNBACKED_TAG[1])
            if step.id in step_ids else step
            for step in phase.steps
        )
        out.append(replace(phase, steps=steps))
    return tuple(out)
