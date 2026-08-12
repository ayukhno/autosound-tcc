"""The car's acoustic flaw map, for the left panel's "Car audio analysis" section (SCR-015).

Phase 0 measures what this cabin and this install do to the sound — room gain, modal peaks, cabin
nulls, SBIR notches, a driver resonance, a de-esser dip that belongs to the tweeter rather than the
car — and the skill now records each finding as data (`project.json` → `acoustics.flaws[]`).

What makes the map worth a panel rather than a paragraph is the second half of every row: not
"there is a dip at 250 Hz" but "and you must not EQ it up". That is the `action` field, and it is
what this module sorts and colours by.

TCC reads. The skill writes, validates, and refuses — `project.py flaw` will not record a dip as
notchable, which is the one rule here with teeth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autosound_tcc.core import config

# How an action reads on screen. The split that matters is not six colours but two answers: this
# one you may correct, that one you must leave alone — everything else is a route to a fix that is
# not EQ. Values are the panel's own traffic-light classes (`theme.py`'s `tl-*`).
_ACTION_TONE = {
    "notch": "done",       # correctable, and the map says so
    "leave": "off",        # a fact of the car; touching it makes things worse
    "no_boost": "bad",     # the mistake this map exists to prevent
    "geometry": "info",
    "delay": "info",
    "crossover": "info",
}


@dataclass(frozen=True)
class Flaw:
    """One measured acoustic feature, and the verdict on what may be done about it."""

    f_hz: float
    level_db: float
    kind: str
    action: str
    channels: tuple[str, ...] = ()
    q: Optional[float] = None
    bw_oct: Optional[float] = None
    why: str = ""
    evidence: tuple[str, ...] = ()
    #: `hypothesis` or `confirmed`. Absent in the file means confirmed: every map written before
    #: the field existed was written as fact, and re-labelling history would be its own lie.
    status: str = "confirmed"

    @property
    def is_hypothesis(self) -> bool:
        return self.status == "hypothesis"

    @property
    def tone(self) -> str:
        # A hypothesis is not a verdict, so it does not get a verdict's colour. Showing "never
        # boost" in red for something nobody has settled is the map claiming more than it knows —
        # which is the failure the status field was added to prevent.
        if self.is_hypothesis:
            return "wait"
        return _ACTION_TONE.get(self.action, "info")

    @property
    def width(self) -> str:
        """Q or octaves, whichever was measured — blank when neither, which is legitimate."""
        if self.q:
            return f"Q{self.q:g}"
        if self.bw_oct:
            return f"{self.bw_oct:g} oct"
        return ""

    @property
    def headline(self) -> str:
        """`188 Hz · Q5 · +5.5 dB` — frequency, width, and the feature's own height or depth."""
        parts = [f"{self.f_hz:g} Hz"]
        if self.width:
            parts.append(self.width)
        parts.append(f"{self.level_db:+g} dB")
        return " · ".join(parts)


def load_flaws(project_dir: Optional[Path] = None) -> tuple[Flaw, ...]:
    """The map, lowest frequency first. Empty when phase 0 has not built it yet.

    Absence is the ordinary state of a project before its baseline, not an error — the section
    says "no data yet" and the intake fills it in.
    """
    project = Path(project_dir or config.project_dir())
    try:
        data = json.loads((project / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    rows = ((data.get("acoustics") or {}).get("flaws") or []) if isinstance(data, dict) else []
    out: list[Flaw] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                Flaw(
                    f_hz=float(row["f_hz"]),
                    level_db=float(row["level_db"]),
                    kind=str(row.get("kind", "")),
                    action=str(row.get("action", "")),
                    status=str(row.get("status") or "confirmed"),
                    channels=tuple(str(c) for c in row.get("channels") or ()),
                    q=float(row["q"]) if row.get("q") else None,
                    bw_oct=float(row["bw_oct"]) if row.get("bw_oct") else None,
                    why=str(row.get("why") or ""),
                    evidence=tuple(str(e) for e in row.get("evidence") or ()),
                )
            )
        except (KeyError, TypeError, ValueError):
            # A row TCC cannot read is the skill's to fix; dropping it beats refusing to draw the
            # rest of a map that is otherwise fine.
            continue
    return tuple(sorted(out, key=lambda flaw: flaw.f_hz))
