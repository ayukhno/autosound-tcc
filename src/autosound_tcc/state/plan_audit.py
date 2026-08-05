"""Does the plan agree with the disk? The "факт" half of ПЛАН — ФАКТ.

The skill's `step_done` requires evidence and gets it: a non-empty list of strings. What it cannot
do is tell a measurement name from a sentence describing one, so a model that narrates its work
closes every step it touches. Watched end to end on 2026-08-05: a free model closed four phases,
reported crossovers, delays, EQ and a listening verdict, and left `dsp_profile.json` alone on
disk — no ledger, no captures, no Critic call. Written up as SCR-035; the skill should refuse
those steps at the source.

Until it does, and after it does as a second pair of eyes, TCC can check from outside, because TCC
can see the disk. This module answers one question per closed step: **does any of its evidence
name something that exists?**

What counts as existing, in the order it is cheap to check:

* a ledger version (`v_007`, `v007`, `vNNN`) with a snapshot under `state/<preset>/`;
* a path that resolves inside the project (`dsp_profile.json`, `autosound_context.md`, a `.mdat`);
* a REW measurement name, checked against titles the caller passes in — REW is not talked to here,
  same rule as `measurement_view`: a view module that blocks on HTTP freezes the GUI.

Deliberately **not** a judgement about whether the tuning was any good, or whether the evidence is
the *right* evidence. It answers "is there anything real behind this tick", which is the question
a green phase over an empty project raises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from autosound_tcc.core import config

# `v_007`, `v007`, `v7` — the ledger's own spelling varies across the skill's prose and files.
_LEDGER = re.compile(r"\bv_?(\d{1,4})\b", re.IGNORECASE)
# Anything that looks like a file the project would hold. Loose on purpose: a false "this exists"
# is only possible when the file really is there, and a false "nothing" is what we are hunting.
_PATHISH = re.compile(r"[\w./\\-]+\.(?:json|md|mdat|txt|csv|yml|yaml)\b")


@dataclass(frozen=True)
class Unbacked:
    """A step the skill considers done whose evidence names nothing that exists."""

    phase: str
    step_id: str
    step_name: str
    evidence: tuple[str, ...]


def _ledger_versions(project_dir: Path) -> set[str]:
    """Every ledger snapshot on disk, as bare numbers ("7" for `v_007.json`)."""
    # `config.state_root()` reads the *current* project and honours `AUTOSOUND_STATE_ROOT`; the
    # per-project fallback keeps this callable for a folder that is not the open one.
    root = config.state_root() if Path(project_dir) == config.project_dir() else Path(project_dir) / "state"
    out: set[str] = set()
    try:
        presets = [p for p in Path(root).iterdir() if p.is_dir()]
    except OSError:
        return out
    for preset in presets:
        for snapshot in preset.glob("v_*.json"):
            match = _LEDGER.search(snapshot.stem)
            if match:
                out.add(str(int(match.group(1))))
    return out


def _is_backed(item: str, project_dir: Path, versions: set[str], titles: set[str]) -> bool:
    text = item.strip()
    if not text:
        return False
    if text in titles:  # an exact REW measurement title
        return True
    for match in _LEDGER.finditer(text):
        if str(int(match.group(1))) in versions:
            return True
    for match in _PATHISH.finditer(text):
        candidate = (project_dir / match.group()).expanduser()
        if candidate.exists():
            return True
    # A measurement name can appear inside a sentence; match on the titles REW reports rather than
    # trying to parse the grammar again here (`measurement_view` owns that).
    return any(title and title in text for title in titles)


def unbacked_steps(
    state: dict,
    project_dir: Optional[Path] = None,
    rew_titles: Iterable[str] = (),
) -> tuple[Unbacked, ...]:
    """Closed steps whose evidence resolves to nothing on disk (or in REW).

    A step with no evidence at all is included too: the skill refuses those, so one that exists is
    either from an older writer or was written around the gate, and either way it is unbacked.
    """
    project = Path(project_dir or config.project_dir())
    versions = _ledger_versions(project)
    titles = {str(title) for title in rew_titles if str(title).strip()}
    out: list[Unbacked] = []
    for step in state.get("plan") or []:
        if not isinstance(step, dict) or step.get("status") != "done" or step.get("skip"):
            continue
        evidence = tuple(str(item) for item in (step.get("evidence") or []))
        if any(_is_backed(item, project, versions, titles) for item in evidence):
            continue
        out.append(
            Unbacked(
                phase=str(step.get("phase", "")),
                step_id=str(step.get("id", "")),
                step_name=str(step.get("name", "")),
                evidence=evidence,
            )
        )
    return tuple(out)
