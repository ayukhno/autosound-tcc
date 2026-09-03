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

#: What the OWNER's panel shows: the part of the map that is still true after the tune.
#: Geometry and install, a fact of the car nobody will correct, and physics that must never be
#: boosted because it is interference rather than a shortage of level.
#:
#: The rest -- `notch`, `crossover`, `delay` -- is the tuning PLAN: the cuts the tuner will make
#: and the crossings they will choose, none of which will exist as a defect once the work is done.
#: On the Passat's live map that was 8 rows of 18, sitting at the same weight as two that ask the
#: owner for money (a tweeter pod, a rebuild of the rear doors) -- and the section sits in the row
#: that says what the project IS, next to "project parameters" and "system parameters" (owner's
#: decision 2026-09-02, SKL-015).
#:
#: An ALLOW-list, not a deny-list, and that direction is the decision: a kind the method adds
#: later is working data until somebody says otherwise, so it stays out of the owner's page by
#: default rather than appearing there unreviewed.
_OWNER_ACTIONS = frozenset({"geometry", "leave", "no_boost"})


#: The kinds that are a property of TIME rather than of frequency (skill v3.0.17,
#: `project.py TIME_DOMAIN_KINDS`): they carry `t_ms` instead of `level_db`, and `f_hz` is optional
#: because a lag can be broadband. Our own copy of the tuple, deliberately paired with a shape test
#: below rather than trusted alone -- a row that carries `t_ms` and no `level_db` is treated as
#: time-domain even when its kind is one the method added after this line was written. A map class
#: silently dropped is exactly the failure this file's `except` clause makes invisible.
_TIME_DOMAIN_KINDS = ("energy_lag", "ringing", "decay_asymmetry")


@dataclass(frozen=True)
class Flaw:
    """One measured acoustic feature, and the verdict on what may be done about it."""

    kind: str
    action: str
    #: A frequency feature has `f_hz` and `level_db`; a time-domain one has `t_ms` and may have
    #: neither. Optional here rather than required, since v3.0.17.
    f_hz: Optional[float] = None
    level_db: Optional[float] = None
    t_ms: Optional[float] = None
    channels: tuple[str, ...] = ()
    q: Optional[float] = None
    bw_oct: Optional[float] = None
    why: str = ""
    evidence: tuple[str, ...] = ()
    #: `hypothesis` or `confirmed`. Absent in the file means confirmed: every map written before
    #: the field existed was written as fact, and re-labelling history would be its own lie.
    status: str = "confirmed"
    #: One short sentence in the owner's language -- what a person HEARS, not what the method
    #: measured. Written by the skill (SKL-016); empty until it is, and the row then reads as it
    #: always did. `why` cannot serve: it carries the audit trail as well as the explanation, and
    #: on the live map its longest was 763 characters with `MMM`, `§26` and `ILL-POSED` in it.
    plain: str = ""

    @property
    def is_hypothesis(self) -> bool:
        return self.status == "hypothesis"

    @property
    def is_owner_fact(self) -> bool:
        """Does this row survive the tune -- i.e. does the owner's panel show it?

        The line runs along `action` alone; no new field was needed, which is why this landed
        without waiting for the method (SKL-015, owner 2026-09-02).
        """
        return self.action in _OWNER_ACTIONS

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
    def is_time_domain(self) -> bool:
        """By SHAPE first, kind second: a row carrying a time and no level is a time-domain row
        whatever it calls itself, which keeps a kind added later from vanishing off the panel."""
        return self.t_ms is not None or self.kind in _TIME_DOMAIN_KINDS

    @property
    def headline(self) -> str:
        """`188 Hz · Q5 · +5.5 dB` for a frequency feature.

        A time-domain row has no dB and may have no frequency at all — a broadband energy lag is
        the whole point of the class — so it reads `energy lag · +3.2 ms`, with the band in front
        when the method did confine it to one.
        """
        parts = []
        if self.is_time_domain:
            parts.append(self.kind.replace("_", " ") or "timing")
        if self.f_hz is not None:
            parts.append(f"{self.f_hz:g} Hz")
        if self.width:
            parts.append(self.width)
        if self.level_db is not None:
            parts.append(f"{self.level_db:+g} dB")
        if self.t_ms is not None:
            parts.append(f"{self.t_ms:+g} ms")
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
            kind = str(row.get("kind", ""))
            timed = row.get("t_ms") is not None or kind in _TIME_DOMAIN_KINDS
            out.append(
                Flaw(
                    # A frequency row still has to bring both numbers; a time-domain one has to
                    # bring `t_ms` and nothing else is required of it.
                    f_hz=float(row["f_hz"]) if not timed else _optional_float(row.get("f_hz")),
                    level_db=(
                        _optional_float(row.get("level_db")) if timed
                        else float(row["level_db"])
                    ),
                    t_ms=float(row["t_ms"]) if timed else None,
                    kind=kind,
                    action=str(row.get("action", "")),
                    status=str(row.get("status") or "confirmed"),
                    channels=tuple(str(c) for c in row.get("channels") or ()),
                    q=float(row["q"]) if row.get("q") else None,
                    bw_oct=float(row["bw_oct"]) if row.get("bw_oct") else None,
                    why=str(row.get("why") or ""),
                    plain=str(row.get("plain") or ""),
                    evidence=tuple(str(e) for e in row.get("evidence") or ()),
                )
            )
        except (KeyError, TypeError, ValueError):
            # A row TCC cannot read is the skill's to fix; dropping it beats refusing to draw the
            # rest of a map that is otherwise fine.
            continue
    # Frequency first, lowest to highest, as before. The rows with no frequency at all cannot
    # join that order, so they follow it, in time order among themselves.
    return tuple(
        sorted(out, key=lambda flaw: (flaw.f_hz is None, flaw.f_hz or 0.0, flaw.t_ms or 0.0))
    )


def split_for_owner(flaws) -> tuple[tuple[Flaw, ...], int]:
    """`(what the panel shows, how many it withheld)`.

    Two returns rather than one filtered list, because the count is shown: eight rows quietly
    gone from a map somebody read yesterday looks like lost data, and a panel that says what it
    is not showing costs one muted line to say so.

    `load_flaws` deliberately keeps returning everything -- the map on disk is the map, and the
    audience is the panel's business, not the reader's.
    """
    shown = tuple(flaw for flaw in flaws if flaw.is_owner_fact)
    return shown, len(tuple(flaws)) - len(shown)


def _optional_float(value) -> Optional[float]:
    return None if value is None else float(value)
