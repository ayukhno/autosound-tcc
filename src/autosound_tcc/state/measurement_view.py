"""Derive the capture task from the glossary + REW, instead of hard-coding a series (SCR-008).

SCR-004 is explicit that the measurement task is **not hand-written** — it is a function of
(phase × glossary × ledger version). This is that function on TCC's side: it asks the skill's
`naming` module what a phase expects, asks REW what it actually holds, and folds the two into the
`MeasSession` shape the panel already renders.

Why this had to wait for SCR-008: the mock series hard-coded `c_*` and `r-L/r-R_*`. The car it was
modelled on has the centre disconnected and no rear speakers at all, so a third of that checklist
was tasks nobody could carry out. A checklist with impossible rows in it stops being read.

Returns `None` when the project has no glossary — the signal to keep the mock rather than render
an empty task that looks like a completed one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from autosound_tcc.core import config, vendor_loader
from autosound_tcc.state import process_view
from autosound_tcc.ui.tcc.mock_data import MeasGroup, MeasItem, MeasSession

STATUS_DONE = "done"
STATUS_WAIT = "wait"
# The panel's own legend already calls this one "taken, unusable" -- exactly what a capture becomes
# when the hardware under it changed (SCR-014).
STATUS_STALE = "bad"
# Decided against, with a reason, and recorded as such by the skill (SCR-034). Distinct from
# waiting: before the round was recorded these were the same colour, so a capture the tuner had
# ruled out came back on the checklist every session.
STATUS_SKIPPED = "skip"


def glossary_path(project_dir: Optional[Path] = None) -> Path:
    return Path(project_dir or config.project_dir()) / "glossary.json"


def has_glossary(project_dir: Optional[Path] = None) -> bool:
    """A standalone `glossary.json`, or one embedded in `project.json` (SCR-011)."""
    project = Path(project_dir or config.project_dir())
    if (project / "glossary.json").is_file():
        return True
    try:
        import json

        return bool(json.loads((project / "project.json").read_text(encoding="utf-8")).get("glossary"))
    except (OSError, ValueError):
        return False


def build_session(
    phase: str,
    version,
    titles: list[str],
    project_dir: Optional[Path] = None,
) -> Optional[MeasSession]:
    """One capture task: what `phase` expects at `version`, checked against `titles` from REW.

    `titles` is passed in rather than fetched here so the caller controls when REW is talked to —
    the panel already owns a worker for that, and a view module that blocks on HTTP is a view
    module that freezes the GUI.
    """
    project = Path(project_dir or config.project_dir())
    if not has_glossary(project):
        return None
    try:
        naming = vendor_loader.load_naming()
    except vendor_loader.VendorNotInitializedError:
        return None

    glossary = naming.Glossary.for_project(str(project))
    groups_spec = naming.expected_groups(phase, glossary, version)
    if not groups_spec:
        # A phase that captures nothing (phase 1 analyses `_1`) is a real answer, and an empty
        # task is the honest way to show it.
        return MeasSession(
            id=f"v{version}",
            version={"en": f"Phase {phase} · no capture", "uk": f"Фаза {phase} · без замірів"},
            groups=(),
        )

    # Keyed by parsed identity, not by raw title, so `c_01 (rta)` counts as `c_1 (rta)` -- REW
    # titles are hand-typed and zero-padding is common.
    parsed = {}
    for title in titles:
        entry = naming.parse_name(title, glossary)
        if entry:
            parsed[naming.name_key(entry)] = entry

    # SCR-014: a capture whose channel was invalidated by a `config_change` is not "done" -- the
    # graph exists and is unusable, which is a different thing from missing, and the panel has a
    # colour for exactly that. Flagging it here rather than in the panel keeps the panel a renderer.
    stale = process_view.stale_channels(project)

    # The round the skill recorded, if there is one (SCR-034). REW's open-measurement list is what
    # this panel used to be built on entirely, which meant closing REW turned a finished round back
    # into an empty checklist. What was recorded is a fact; what REW happens to have open is a
    # snapshot of another application's session.
    round_ = process_view.capture_round(project) or {}
    recorded_taken = {str(t) for t in (round_.get("taken") or {})}
    recorded_skipped = {str(t) for t in (round_.get("skipped") or {})}
    # What the arithmetic said about each curve (SCR-040). A verdict outranks "a title exists":
    # a sweep that never finished and a muted channel both leave a title behind, and every later
    # phase used to compute on them.
    verdicts = {
        str(title): (entry or {}).get("verified") or {}
        for title, entry in (round_.get("taken") or {}).items()
    }

    def status_for(name: str) -> str:
        entry = naming.parse_name(name, glossary)
        if name in recorded_skipped:
            return STATUS_SKIPPED  # a decision, and it outranks both REW and the derivation
        verdict = verdicts.get(name)
        if verdict and not verdict.get("ok"):
            # The panel's own legend already calls this "taken, unusable" -- which is exactly what
            # a capture that came back and failed the check is.
            return STATUS_STALE
        if naming.name_key(entry) not in parsed and name not in recorded_taken:
            return STATUS_WAIT
        # Both names a renamed channel answers to (SCR-039): a `config_change` names whichever the
        # session was using, and the capture's title carries whichever it was typed under. Either
        # side alone would leave a real invalidation looking like a clean capture.
        codes = {(entry or {}).get("code"), (entry or {}).get("code_current")} - {None}
        return STATUS_STALE if codes & set(stale) else STATUS_DONE

    def issues_for(name: str) -> Optional[str]:
        """Why a capture is unusable, in the checker's own words — the panel shows it on hover."""
        issues = (verdicts.get(name) or {}).get("issues") or []
        return "; ".join(str(i) for i in issues) or None

    groups = []
    for spec in groups_spec:
        items = tuple(
            MeasItem(name=name, status=status_for(name), extra=issues_for(name))
            for name in spec["names"]
        )
        groups.append(MeasGroup(type=spec["label"], items=items))

    extras = _extras(naming, glossary, parsed, groups_spec, version)
    if extras:
        # Ours, at this version, but not on the checklist -- an experiment tag, a channel the
        # phase doesn't ask for. Shown, flagged blue, never silently dropped.
        groups.append(MeasGroup(type="additional", items=extras))

    # The round's own id when there is one: the ledger version names the config the measurements
    # were taken under and cannot tell two passes at the same config apart, which is exactly what
    # "this session's task" means (SCR-034).
    round_id = str(round_.get("id") or "") if not round_.get("closed") else ""
    return MeasSession(
        id=round_id or f"v{version}",
        version={
            "en": f"Capture series v{version} · phase {phase}"
            + (f" · {round_id}" if round_id else ""),
            "uk": f"Серія v{version} · фаза {phase}" + (f" · {round_id}" if round_id else ""),
        },
        groups=tuple(groups),
    )


def _extras(naming, glossary, parsed: dict, groups_spec: list, version) -> tuple[MeasItem, ...]:
    wanted = {
        naming.name_key(naming.parse_name(name, glossary))
        for spec in groups_spec
        for name in spec["names"]
    }
    try:
        version_n = int(version)
    except (TypeError, ValueError):
        version_n = version
    out = []
    for key, entry in sorted(parsed.items(), key=lambda kv: kv[1]["title"]):
        if key in wanted or (entry["version_n"] or entry["version"]) != version_n:
            continue
        out.append(
            MeasItem(
                name=entry["title"],
                status=STATUS_DONE,
                extra=entry["modifier"],
                additional=True,
            )
        )
    return tuple(out)


def off_convention(titles: list[str], project_dir: Optional[Path] = None) -> list[str]:
    """Titles REW holds that aren't in the naming grammar at all.

    Worth surfacing separately from "not captured yet": no analysis will ever find these by name,
    so they are invisible to every later step rather than merely missing.
    """
    project = Path(project_dir or config.project_dir())
    if not has_glossary(project):
        return []
    try:
        naming = vendor_loader.load_naming()
    except vendor_loader.VendorNotInitializedError:
        return []
    glossary = naming.Glossary.for_project(str(project))
    return [t for t in titles if naming.parse_name(t, glossary) is None]
