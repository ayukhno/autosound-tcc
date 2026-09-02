"""What the import dialog decides, decided here — no Qt, so all of it is testable without a window.

The dialog above this module is a table and four controls. Everything that can be got WRONG lives
here: which measurement is which, what order they were captured in, which ones this project has
already taken, and how much of the list to show at once.

## Why identity is the uuid and nothing else

Measured on the user's live REW on 2026-09-02, four times over one 102-measurement file
(`docs/CAPTURE-IMPORT-PLAN.md` carries the numbers):

* REW's **ordinal is the index of a VIEW.** `sw_01 (sw)` came back as number 1 with a "sweeps only"
  filter on and number 18 with no filter — one measurement, one uuid, two positions. The position
  also moves when the list is sorted, and when the tuner drags a row by hand.
* The **UI filter reaches the API.** `GET /measurements` served 17, then 85, then 102 from the same
  file as the filter changed. It answers with what REW is SHOWING, not with what REW holds — and a
  filtered view is renumbered `1..N` with no gaps, so nothing in the answer reveals what is hidden.
* The **list order is not capture order.** Rows captured at 13:25 were served after rows captured at
  20:11.

So: identity is `uuid`, order is `date`, and the ordinal is resolved fresh at the moment it is used
and never stored. That is the same rule the method states for its own tools (`rew-api-quirks.md`),
arrived at here from the other end.

## Why `date` is parsed defensively

It is a display string, not a timestamp: `2026-Jun-22 12:10:35`, the month as a word, formatted by
REW's (Java) locale. `strptime("%b")` would read that on an English machine and fail on the user's
Ukrainian one — so the month table below is explicit and locale-independent, and a string that does
not parse is not an error: the order falls back to REW's own, the caller is told
(`ordered_by_date()`), and the raw string goes to the log so the first machine that produces a new
format tells us what it is instead of just degrading.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from autosound_tcc.core import app_log, config

#: The store's own schema, in its own file. Not `tcc-project.json`: that one is settings a person
#: chose, this is a log of what happened, and a reader of either should not have to skip the other.
FILENAME = "imported-measurements.json"
SCHEMA = 1

#: How many rows the dialog opens on when the round is waiting for fewer than this — a window of
#: three is a window that hides the measurement taken just before the three.
MIN_WINDOW = 10
#: What one press of "+10" adds. The user's own number, and it is a PORTION rather than a new
#: filter: the point is to look a little further back, not to change what the list means.
PAGE = 10

#: English month abbreviations, by hand rather than through `%b`, which is locale-dependent in
#: `strptime` and would therefore read REW's answer correctly on the machine this was written on
#: and silently fail on the machine it runs on.
_MONTHS = {name: number for number, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

_REW_DATE = re.compile(r"^\s*(\d{4})-([A-Za-z]{3,})-(\d{1,2})[ T](\d{1,2}):(\d{2}):(\d{2})")

#: Raw date strings this process has already failed on, so a file full of one unknown format
#: produces one log line rather than a hundred.
_unparsed_seen: set[str] = set()


@dataclass(frozen=True)
class Candidate:
    """One REW measurement, as the import dialog sees it.

    `ordinal` is here to be USED IMMEDIATELY (it is what a rename call takes) and never to be
    stored — see the module docstring for what it is worth.
    """

    ordinal: str
    title: str
    uuid: str
    date: str
    when: Optional[datetime]
    imported: bool

    @property
    def identified(self) -> bool:
        """Whether this measurement can be recorded at all.

        A REW old enough to answer without a `uuid` is not a broken REW, but nothing this module
        promises holds for it: it cannot be recognised again after a rename. Such a row is listed
        and can be renamed; it is not written into the store, because a store keyed by an empty
        string would hide every unidentified measurement after the first.
        """
        return bool(self.uuid)


# ---- the store ---------------------------------------------------------------------------


def store_path(project_dir: Optional[Path] = None) -> Path:
    return config.tcc_dir(project_dir) / FILENAME


def load_imported(project_dir: Optional[Path] = None) -> dict[str, dict]:
    """`uuid -> {title, round, when, date}`, or `{}`.

    A missing file is the normal state of a project nobody has imported into yet, and a corrupt one
    degrades to "nothing imported" rather than taking the dialog down: the worst that follows is a
    list showing rows the tuner has seen before, which they can read.
    """
    try:
        raw = json.loads(store_path(project_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = raw.get("measurements") if isinstance(raw, dict) else None
    return {str(k): v for k, v in entries.items() if isinstance(v, dict)} if isinstance(entries, dict) else {}


def imported_titles(project_dir: Optional[Path] = None) -> list[str]:
    """Every title this project has imported, for the checklist.

    The reason this exists: "captured" used to mean "REW is showing a title like that RIGHT NOW", so
    the checklist emptied itself when REW was closed — or filtered. What the project imported is a
    fact about the project, and it is the half that should survive the tool being shut.
    """
    titles = [str(entry.get("title") or "") for entry in load_imported(project_dir).values()]
    return sorted({title for title in titles if title.strip()})


def record_imported(rows: Iterable["Candidate"], round_id: str = "",
                    project_dir: Optional[Path] = None, titles: Optional[dict] = None) -> int:
    """Write these measurements down as imported. Returns how many entries were added or updated.

    `titles` overrides the title per uuid — that is how step 2's rename records what the
    measurement is called AFTER the rename rather than before, without this module knowing anything
    about renaming.

    Atomic, like every other writer in `.tcc/`: this runs at the end of a capture round, and a
    half-written store would read as "nothing was imported" and put the whole round back on the
    checklist.
    """
    directory = config.tcc_dir(project_dir)
    data = {"schema": SCHEMA, "measurements": dict(load_imported(project_dir))}
    stamp = datetime.now().replace(microsecond=0).isoformat()
    written = 0
    for row in rows:
        if not row.identified:
            continue
        title = str((titles or {}).get(row.uuid) or row.title)
        data["measurements"][row.uuid] = {
            "title": title, "round": str(round_id or ""), "when": stamp, "date": row.date,
        }
        written += 1
    if not written:
        return 0
    directory.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(directory), prefix=".imported-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, store_path(project_dir))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return written


# ---- reading REW's answer ----------------------------------------------------------------


def parse_date(raw: Any) -> Optional[datetime]:
    """REW's display date as a `datetime`, or None — see the module docstring for why not `%b`."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)  # a REW that ever starts answering properly
    except ValueError:
        pass
    match = _REW_DATE.match(text)
    month = _MONTHS.get(match.group(2)[:3].lower()) if match else None
    if match and month:
        try:
            return datetime(int(match.group(1)), month, int(match.group(3)),
                            int(match.group(4)), int(match.group(5)), int(match.group(6)))
        except ValueError:
            pass
    if text not in _unparsed_seen:
        _unparsed_seen.add(text)
        app_log.logger().info("rew date not understood, keeping REW's own order: %r", text)
    return None


def candidates(measurements: dict, project_dir: Optional[Path] = None,
               imported: Optional[dict] = None) -> list[Candidate]:
    """REW's answer as rows, oldest first.

    Sorted by capture time when every row carries a readable one, and left in REW's own order when
    they do not — never half and half. A list sorted by whatever parsed, with the rest swept to one
    end, is the shape that looks ordered and is not.
    """
    seen = load_imported(project_dir) if imported is None else imported
    rows: list[tuple[int, Candidate]] = []
    for ordinal, raw in (measurements or {}).items():
        raw = raw or {}
        uuid = str(raw.get("uuid") or "")
        position = int(ordinal) if str(ordinal).isdigit() else 0
        rows.append((position, Candidate(
            ordinal=str(ordinal),
            title=str(raw.get("title") or ""),
            uuid=uuid,
            date=str(raw.get("date") or ""),
            when=parse_date(raw.get("date")),
            imported=bool(uuid) and uuid in seen,
        )))
    rows.sort(key=lambda pair: pair[0])
    ordered = [row for _position, row in rows]
    if ordered and all(row.when is not None for row in ordered):
        ordered.sort(key=lambda row: row.when)
    return ordered


def ordered_by_date(rows: list[Candidate]) -> bool:
    """Whether `candidates` could use capture time. The dialog says so out loud when it could not."""
    return bool(rows) and all(row.when is not None for row in rows)


def unprocessed(rows: Iterable[Candidate]) -> list[Candidate]:
    return [row for row in rows if not row.imported]


def window(rows: list[Candidate], waiting: int = 0, pages: int = 0) -> list[Candidate]:
    """The tail of the list: as many as the round is waiting for, plus `pages` portions of ten.

    The tail rather than the head because a capture round ends at the newest measurement, and the
    tuner opens this having just taken some. `waiting` is the round's own count, so the default
    window is "what I am here for" rather than a number somebody guessed.
    """
    size = max(int(waiting or 0), MIN_WINDOW) + max(int(pages or 0), 0) * PAGE
    return rows[-size:] if size < len(rows) else list(rows)


# ---- the two things worth saying out loud -------------------------------------------------


def missing_imported(measurements: dict, project_dir: Optional[Path] = None) -> list[str]:
    """Titles this project imported that REW is not showing right now.

    Either they were deleted or a filter is hiding them, and the tuner is the only one who can tell
    which — but they cannot tell at all unless somebody counts. This is the one signal available:
    the filter's state is not on the wire, and a filtered answer is renumbered with no gaps.
    """
    live = {str((raw or {}).get("uuid") or "") for raw in (measurements or {}).values()}
    return sorted(
        str(entry.get("title") or uuid)
        for uuid, entry in load_imported(project_dir).items()
        if uuid not in live
    )


def out_of_sequence(rows: list[Candidate]) -> set[str]:
    """Uuids whose capture time is EARLIER than the row above them.

    A re-take: the tuner took something again because it did not come out, and it landed after its
    neighbours in time while sitting among them in the list. The user's own instruction on this
    (2026-09-02) is that it is worth their attention and is not a stopper — so this returns marks,
    and nothing in this module refuses anything.
    """
    marked: set[str] = set()
    previous: Optional[datetime] = None
    for row in rows:
        if row.when is None:
            continue
        if previous is not None and row.when < previous:
            marked.add(row.uuid)
        previous = max(previous, row.when) if previous else row.when
    return marked


def resolve_ordinals(measurements: dict, uuids: Iterable[str]) -> dict[str, str]:
    """`uuid -> REW's ordinal RIGHT NOW`, from a freshly fetched answer.

    Called immediately before the ordinals are used and never earlier: between the list the tuner
    looked at and the call that acts on it, a sort, a filter or a hand can have moved every one of
    them. Measured: a manual swap of two rows exchanged their ordinals while both uuids, titles and
    dates stayed put.
    """
    by_uuid = {str((raw or {}).get("uuid") or ""): str(ordinal)
               for ordinal, raw in (measurements or {}).items()}
    return {uuid: by_uuid[uuid] for uuid in uuids if uuid and uuid in by_uuid}
