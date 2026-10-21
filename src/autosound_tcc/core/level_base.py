"""The round on the method's level base: what the card and the strip say of it (tcc#220, hub #285).

From v3.2.0 the method's `capture-check` writes `capture.level_base` into `process-state.json`
(the skill's #176/#177; `process-schema.md`): the round's status against the project's level base
(`ok`, `no_base`, `missing`, `mixed`), the base and the previous round, REW's SPL calibration of
each, each title's `to_base_db` — the shift the method SUBTRACTS to bring it to the base — and
`to_previous_db`, and the round's level control with its verdict. For a project bound to such a copy
(`method_features.LEVEL_BASE`) this is the card's level line, in place of W-10's reading of REW's
listing (`level_calibration`, tcc#198), which stays for an older copy.

The method's numbers as it gives them: no record of TCC's own, no REW listing, no arithmetic —
only the method's own line's sign convention, the shift applied being `-to_base_db` (its `LEVEL`
line: «brought to the base … by -16.65 dB»). A round not checked yet has no `level_base`: nothing is
said, and REW's listing is no fallback.

`notes` is what the card says; `news` the part the strip is told, once per (round, what, numbers)
(`level_calibration.tell`): a move against the previous round, a round whose captures disagree, a
capture REW lists no calibration for, a chain change the control names. The base named, the round
being the base, and the control's other verdicts stay on the card.

Qt-free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from autosound_tcc.core import method_features
from autosound_tcc.core.level_calibration import Note, _db

#: The sentences' keys, in the window's language (`ui/tcc/i18n.py`).
IS_BASE = "levelBaseIsBase"
ON_BASE = "levelBaseOn"
MOVED = "levelBaseMoved"
MOVED_BARE = "levelBaseMovedBare"
MIXED = "levelBaseMixed"
MISSING = "levelBaseMissing"
NO_BASE_OFFSET = "levelBaseNoOffset"
CHAIN = "levelBaseChain"
CONTROL_UNSURE = "levelBaseControlUnsure"
CONTROL_SAME = "levelBaseControlSame"
CONTROL_REFERENCE = "levelBaseControlReference"
CONTROL_NOT_TAKEN = "levelBaseControlNotTaken"

#: What the strip is told: news, as the method's `LEVEL` line speaks only on news.
NEWS = frozenset({MOVED, MOVED_BARE, MIXED, MISSING, CHAIN})
#: What the card says calmly, as a fact and not a warning.
QUIET = frozenset({IS_BASE, ON_BASE, NO_BASE_OFFSET, CONTROL_UNSURE, CONTROL_SAME,
                   CONTROL_REFERENCE, CONTROL_NOT_TAKEN})


def applies(project_dir: Optional[Path | str] = None) -> bool:
    """Whether the copy `project_dir` is bound to writes `capture.level_base`."""
    return method_features.has(method_features.LEVEL_BASE, project_dir)


def _number(value: Any) -> Optional[float]:
    return None if isinstance(value, bool) or not isinstance(value, (int, float)) else float(value)


def _note(key: str, round_id: str, **values: str) -> Note:
    return Note(key, tuple(values.items()), round_id)


def _levels(lb: dict, rid: str) -> list[Note]:
    """What the round's status says: the base, a move, mixed, missing — as the method's line."""
    titles = {str(t): r for t, r in (lb.get("titles") or {}).items() if isinstance(r, dict)}
    status, base = lb.get("status"), str(lb.get("base_round") or "")
    base_offset = _number(lb.get("base_offset_db"))
    out: list[Note] = []
    bare = [t for t, r in titles.items() if _number(r.get("offset_db")) is None]
    if status == "missing":
        if bare and base_offset is not None:
            out.append(_note(MISSING, rid, titles=", ".join(bare), base=base))
        elif base_offset is None:
            out.append(_note(NO_BASE_OFFSET, rid, base=base))
    if status == "mixed":
        jumps = ", ".join(f"{t} {_db(shift, sign=True)} dB" for t, r in titles.items()
                          if (shift := _number(r.get("to_base_db"))) is not None)
        out.append(_note(MIXED, rid, jumps=jumps, base=base))
        return out
    moved = [r for r in titles.values() if _number(r.get("to_previous_db")) not in (None, 0.0)]
    if moved:
        jump = moved[0]  # the method's own pick: its line says the first
        delta, to_base = _number(jump.get("to_previous_db")), _number(jump.get("to_base_db"))
        before, after = _number(lb.get("previous_offset_db")), _number(lb.get("offset_db"))
        previous = str(lb.get("previous_round") or "")
        if None in (to_base, before, after):
            out.append(_note(MOVED_BARE, rid, delta=_db(delta, sign=True), previous=previous))
        else:
            out.append(_note(MOVED, rid, delta=_db(delta, sign=True), previous=previous,
                             before=_db(before), after=_db(after), base=base,
                             shift=_db(-to_base, sign=True)))
    elif status == "no_base" and (offset := _number(lb.get("offset_db"))) is not None:
        out.append(_note(IS_BASE, rid, offset=_db(offset)))
    elif status == "ok" and base_offset is not None:
        out.append(_note(ON_BASE, rid, base=base, offset=_db(base_offset)))
    return out


def _control(lb: dict, rid: str) -> list[Note]:
    """What the round's level control says, when the round has one (`title`)."""
    control = lb.get("control") if isinstance(lb.get("control"), dict) else {}
    title = str(control.get("title") or "")
    if not title:
        return []  # `none`: the round has no control, and its why is the record's
    verdict = control.get("verdict")
    if verdict == "chain_change":
        common, align = _number(control.get("common_db")), _number(control.get("align_db"))
        used = [str(b) for b, r in (control.get("bands") or {}).items()
                if isinstance(r, dict) and r.get("used")]
        if common is not None:
            return [_note(CHAIN, rid, title=title, common=_db(common, sign=True),
                          bands=", ".join(used), align=_db(align or 0.0, sign=True))]
    if verdict == "unattributed":
        return [_note(CONTROL_UNSURE, rid, title=title, why=str(control.get("why") or ""))]
    if verdict == "same_chain":
        return [_note(CONTROL_REFERENCE if control.get("reference") else CONTROL_SAME, rid,
                      title=title)]
    if verdict == "not_taken":
        return [_note(CONTROL_NOT_TAKEN, rid, title=title)]
    return []


def notes(round_: Optional[dict]) -> list[Note]:
    """What the card says of `round_`'s `level_base` — the state's round, open or the last — in
    the method's numbers; `[]` for a round not checked yet."""
    lb = (round_ or {}).get("level_base") if isinstance(round_, dict) else None
    if not isinstance(lb, dict):
        return []
    rid = str(round_.get("id") or "")
    return _levels(lb, rid) + _control(lb, rid)


def news(said: list[Note]) -> list[Note]:
    """Those of `said` the strip is told."""
    return [note for note in said if note.key in NEWS]
