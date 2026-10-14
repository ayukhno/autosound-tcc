"""REW's level calibration across a project's rounds: a change named, never corrected (tcc#198).

Hub #268 (PAS-015), 2026-10-08: between rounds `cap_003` and `cap_004` REW went from 5.40 beta 134
to beta 135 and reset its SPL calibration — every capture's `splOffsetdB` 103.35 → 120.0 — so every
level of the new round read 16.65 dB higher, and the round check said nothing. Read as it stood, that
was «memory 7 is 17 dB louder».

REW's `/measurements` listing carries `splOffsetdB` per capture (the method's `rew_api` names the
listing's fields). TCC reads it where it reads that listing for a round — the measurement panel's
read and Refresh, and after an import — and says, once, when the round's offset differs from the
last round's, or when one round's captures carry more than one. Nothing is shifted: bringing rounds
to one base is the method's math (hub #285, TCC-060), and TCC only names the jump.

The last round's offsets are TCC's own record, kept here per round while REW's listing names its
captures (`FILENAME` in `.tcc/`, never the method's files — D-6), so a round REW no longer holds is
still compared. A capture REW lists without the field (an older REW) is no offset: nothing said.

Qt-free.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from autosound_tcc.core import app_log, config, own_store

#: REW's field, per capture in its `/measurements` listing.
FIELD = "splOffsetdB"

#: TCC's own record of each round's offsets, in `.tcc/`.
FILENAME = "rew-level-calibration.json"
SCHEMA = 1

#: The two sentences' keys, in the window's language (`ui/tcc/i18n.py`).
JUMP = "levelCalJump"
MIXED = "levelCalMixed"

#: The notes already told the strip in this run: `(project, round, key, args)`.
_SAID: set[tuple] = set()
_LOCK = threading.Lock()


@dataclass(frozen=True)
class Note:
    """One thing to say about a round's level calibration: its sentence's `key` and the values it
    is formatted with, as text (`args`, pairs), and the round it is about."""

    key: str
    args: tuple[tuple[str, str], ...]
    round_id: str

    @property
    def values(self) -> dict[str, str]:
        return dict(self.args)


def offset_of(record: Any) -> Optional[float]:
    """The capture's `splOffsetdB`, or None when REW's record carries none — an older REW — or one
    that is no finite number."""
    value = (record or {}).get(FIELD) if isinstance(record, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _listing_index(listing: Optional[dict]) -> tuple[dict[str, float], dict[str, list[float]]]:
    """REW's listing as `uuid -> offset` and `title -> [offset, …]` — a title REW holds more than
    once has more than one, and names none of them."""
    by_uuid: dict[str, float] = {}
    by_title: dict[str, list[float]] = {}
    for record in (listing or {}).values():
        offset = offset_of(record)
        title = str((record or {}).get("title") or "")
        by_title.setdefault(title, []).append(offset)
        uuid = str((record or {}).get("uuid") or "")
        if uuid and offset is not None:
            by_uuid[uuid] = offset
    return by_uuid, by_title


def offsets_of_round(round_: Optional[dict], listing: Optional[dict],
                     not_titles: frozenset = frozenset()) -> dict[str, float]:
    """`{take: offset}` for the standing takes of `round_` that REW's listing names: by the uuid
    the take's verdict pins, else by its title as REW holds it (`as_in_rew`, else the take's own)
    when REW holds exactly one capture under it. `not_titles` are never read by title: a later
    round's takes, whose capture under the same title is not this round's."""
    from autosound_tcc.state import process_view

    by_uuid, by_title = _listing_index(listing)
    out: dict[str, float] = {}
    for title, row in process_view.standing(round_).items():
        uuid = str(((row or {}).get("verified") or {}).get("uuid") or "")
        if uuid in by_uuid:
            out[str(title)] = by_uuid[uuid]
            continue
        typed = str((row or {}).get("as_in_rew") or title)
        if typed in not_titles or str(title) in not_titles:
            continue
        held = by_title.get(typed) or []
        if len(held) == 1 and held[0] is not None:
            out[str(title)] = held[0]
    return out


def store_path(project_dir: Optional[Path] = None) -> Path:
    return config.tcc_dir(project_dir) / FILENAME


def _misshapen(store: dict) -> str:
    rounds = store.get("rounds", {})
    if not isinstance(rounds, dict):
        return '"rounds" is not an object'
    for rid, entry in rounds.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("captures", {}), dict):
            return f'the round "{rid}" is not an object with "captures"'
    return ""


def recorded(project_dir: Optional[Path] = None) -> dict[str, dict[str, float]]:
    """`round -> {take: offset}` as TCC recorded them; `{}` when there is no record, or one that
    cannot be read (`own_store` has said why)."""
    try:
        store = own_store.read_json(store_path(project_dir), misshapen=_misshapen)
    except own_store.StoreUnreadable:
        return {}
    out: dict[str, dict[str, float]] = {}
    for rid, entry in (store.get("rounds") or {}).items():
        captures = {str(t): offset_of({FIELD: v}) for t, v in (entry.get("captures") or {}).items()}
        out[str(rid)] = {t: v for t, v in captures.items() if v is not None}
    return out


def remember(project_dir: Path, round_id: str, offsets: dict[str, float]) -> None:
    """Add `offsets` to the round's record — what REW's listing says now outranks what it said
    before, and a take it no longer lists keeps its last offset. A store that cannot be read is
    not written over, and one that cannot be written is said (`own_store`); either way the note
    is still said from the listing in hand."""
    if not round_id or not offsets:
        return
    path = store_path(project_dir)
    try:
        store = own_store.read_json(path, misshapen=_misshapen)
        rounds = dict(store.get("rounds") or {})
        entry = dict(rounds.get(round_id) or {})
        captures = {**(entry.get("captures") or {}), **offsets}
        if captures == entry.get("captures"):
            return
        rounds[round_id] = {"captures": captures,
                            "at": datetime.now().replace(microsecond=0).isoformat()}
        own_store.write_json(path, {"schema": SCHEMA, "rounds": rounds})
    except own_store.StoreUnreadable:
        return  # said by `own_store`; nothing written over it
    except OSError as exc:
        own_store.say_unwritten(path, exc)


def _db(value: float, sign: bool = False) -> str:
    """`103.35`, `120.0`, `+16.65`: two decimals at most, one at least."""
    text = f"{value:+.2f}" if sign else f"{value:.2f}"
    text = text.rstrip("0")
    return text + "0" if text.endswith(".") else text


def _values(offsets: dict[str, float]) -> list[float]:
    return sorted({round(value, 2) for value in offsets.values()})


def notes(project_dir: Optional[Path], listing: Optional[dict]) -> list[Note]:
    """What to say about the project's round — the open one, else the last — from REW's `listing`
    and TCC's own record: its captures' offsets differ from one another (`MIXED`), or its one offset
    differs from the last round's one (`JUMP`). A first round, equal offsets and captures REW lists
    with no offset say nothing. What the listing names of either round is recorded first."""
    from autosound_tcc.state import process_view

    project = Path(project_dir or config.project_dir())
    current = process_view.capture_round(project)
    rid = str((current or {}).get("id") or "")
    if not rid:
        return []
    own = recorded(project)
    found = offsets_of_round(current, listing)
    remember(project, rid, found)
    now = {**own.get(rid, {}), **found}
    said: list[Note] = []
    values = _values(now)
    if len(values) > 1:
        said.append(Note(MIXED, (("values", ", ".join(_db(v) for v in values)),), rid))
    previous = next((r for r in process_view.capture_rounds(project)
                     if str(r.get("id") or "") not in ("", rid)), None)
    if previous is None or len(values) != 1:
        return said
    pid = str(previous["id"])
    taken_now = frozenset(str(t) for t in process_view.standing(current))
    taken_now |= {str((row or {}).get("as_in_rew") or "")
                  for row in process_view.standing(current).values()} - {""}
    before_found = offsets_of_round(previous, listing, not_titles=taken_now)
    remember(project, pid, before_found)
    before = _values({**before_found, **own.get(pid, {})})
    if len(before) == 1 and before[0] != values[0]:
        said.append(Note(JUMP, (("delta", _db(values[0] - before[0], sign=True)),
                                ("before", _db(before[0])), ("after", _db(values[0]))), rid))
    return said


def first_time(project_dir: Optional[Path], note: Note) -> bool:
    """Whether `note` is said for the first time in this run, for this project — the strip is
    told once; the card keeps the line while it holds."""
    key = (str(Path(project_dir or config.project_dir())), note.round_id, note.key, note.args)
    with _LOCK:
        if key in _SAID:
            return False
        _SAID.add(key)
    return True


def tell(project_dir: Optional[Path], said: list[Note], sentence) -> None:
    """Each of `said` not told yet goes to the strip as a warning, in `sentence(note)`'s words."""
    for note in said:
        if first_time(project_dir, note):
            app_log.warn(sentence(note))
