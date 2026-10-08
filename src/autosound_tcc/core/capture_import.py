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

import difflib

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

from autosound_tcc.core import app_log, config, own_store, vendor_loader

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
    #: Whether REW holds an impulse for this one. False for an RTA capture: importable like any
    #: other, but there is no capture check that could say anything about it (the method's
    #: `rew_api.is_swept`).
    swept: bool = True
    #: Taken although the capture check called it unusable — the tuner's «Take it as it is»
    #: (tcc#21). Read back from the store, so that capture is not asked about again; a re-take
    #: under the same title is another uuid and is checked afresh (SCR-040).
    as_is: bool = False
    #: What the import window's check said about this capture, kept for the card until the method
    #: reads a sweep's own range (tcc#149, hub #247 — drop with the patch): `usable` (over its own
    #: range, `check_sweeps`), or a clash's own name (`verdict_reader`). "" said nothing.
    checked: str = ""

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
    """`uuid -> {title, round, when, date[, as_is]}`, or `{}` — `as_is` once a capture the check
    called unusable was taken anyway (tcc#21).

    A missing file is the normal state of a project nobody has imported into yet. A broken one, or
    one shaped wrong inside (`_misshapen`), is set aside with its bytes and said, and one that
    cannot be opened is said and left where it is (`own_store`, #173); for a reader all of them
    still degrade to "nothing imported" rather than taking the dialog down: the worst that follows
    is a list showing rows the tuner has seen before, which they can read. A write must not do the
    same — see `record_imported`.
    """
    return _section(_read_store(project_dir), "measurements")


#: The store's two `uuid -> entry` maps: what was imported, and what was left for a re-take.
_SECTIONS = ("measurements", "retake")


def _misshapen(store: dict[str, Any]) -> str:
    """Why `store` is not an import store this module can read, or "" when it is (`own_store`).

    Each section, when there is one, is a `uuid -> entry` map with every entry an object. A
    section that was a list, or an entry that was a string, read as "nothing imported" — or as
    the entries that were — and the next write replaced it: every earlier round gone, F5 one level
    down (#173, R-bm). Such a store is set aside like a broken one instead.
    """
    for name in _SECTIONS:
        section = store.get(name, {})
        if not isinstance(section, dict):
            return f'"{name}" is not an object'
        for uuid, entry in section.items():
            if not isinstance(entry, dict):
                return f'the "{name}" entry for {uuid} is not an object'
    return ""


def _read_store(project_dir: Optional[Path]) -> dict[str, Any]:
    """The whole store for a reader: `{}` when it is not there, was broken or shaped wrong, or
    cannot be opened.

    Never raises (R-l): `own_store` has already said what was wrong. The writers read through
    `_read_store_for_write`, so that a store they cannot read is never written over.
    """
    try:
        return _read_store_for_write(project_dir)
    except own_store.StoreUnreadable:
        return {}


def _read_store_for_write(project_dir: Optional[Path]) -> dict[str, Any]:
    """The read under a write: `StoreUnreadable` goes through. A broken store, or one shaped wrong
    inside, has been set aside with its bytes and said by the time this answers `{}`."""
    return own_store.read_json(store_path(project_dir), misshapen=_misshapen)


def _section(store: dict[str, Any], name: str) -> dict[str, dict]:
    """One `uuid -> entry` map of the store, `{}` when it has none. A copy, for the writers to
    change; that it is a map of objects is `_misshapen`'s to check, before the store is let in."""
    return dict(store.get(name) or {})


def _write_store(measurements: dict, retake: dict, project_dir: Optional[Path]) -> None:
    """The whole store, through a temp file and on the disk before it takes the name
    (`own_store.write_json`) — see `record_imported` for why."""
    data: dict[str, Any] = {"schema": SCHEMA, "measurements": measurements}
    if retake:
        data["retake"] = retake
    own_store.write_json(store_path(project_dir), data)


def retakes(project_dir: Optional[Path] = None) -> dict[str, str]:
    """`uuid -> title` of the sweeps the tuner left on «Re-take» in the import window (tcc#21).

    The other half of «Take it as it is», and kept beside it for the same reason: it is the
    tuner's answer about one capture. Not an import — the capture stays unprocessed and comes
    back in the window — but the card reads it: a title whose curve in REW is one left for a
    re-take waits for a new sweep rather than offering that one for import (finding 147).
    """
    return {uuid: str(entry.get("title") or "") for uuid, entry in
            _section(_read_store(project_dir), "retake").items()}


def record_retakes(rows: Iterable["Candidate"], project_dir: Optional[Path] = None) -> int:
    """Remember these captures as left for a re-take. Returns how many were added.

    Read once, and the way `record_imported` reads: a store that cannot be read raises
    `StoreUnreadable` here rather than come back empty and be written over (#173, R-l).
    """
    store = _read_store_for_write(project_dir)
    left = _section(store, "retake")
    stamp = datetime.now().replace(microsecond=0).isoformat()
    added = 0
    for row in rows:
        if row.identified and row.uuid not in left:
            left[row.uuid] = {"title": row.title, "when": stamp}
            added += 1
    if added:
        _write_store(_section(store, "measurements"), left, project_dir)
    return added


def retake_titles(measurements: dict, project_dir: Optional[Path] = None) -> list[str]:
    """Titles still waiting for their re-take: every curve REW's `measurements` holds under the
    title is one left for a re-take. A new sweep under the same title is a new uuid, and from then
    on the title is there to be imported. With nothing read from REW, the answer alone decides."""
    left = retakes(project_dir)
    held: dict[str, set[str]] = {}
    for raw in (measurements or {}).values():
        raw = raw or {}
        held.setdefault(str(raw.get("title") or ""), set()).add(str(raw.get("uuid") or ""))
    return sorted({title for title in left.values()
                   if title.strip() and held.get(title, set()) <= set(left)})


def window_verdicts(project_dir: Optional[Path] = None) -> dict[str, str]:
    """`uuid -> what the import window's check said` for the captures taken through it (tcc#149):
    `usable`, or a clash's name. Keyed by REW's uuid as the method keys its own verdict, so a
    re-take — a new uuid — never inherits it. Read by the card until hub #247 (drop with it)."""
    return {uuid: str(entry["checked"]) for uuid, entry in load_imported(project_dir).items()
            if entry.get("checked")}


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

    Read once, through `_read_store_for_write` rather than `load_imported`: both halves put back
    come from one state of the file, and a store that is there and cannot be read raises
    `StoreUnreadable` out of here instead of coming back as `{}` — which, written back with this
    round in it, was every earlier round, «Take it as it is» answer and re-take gone (#173, R-l).
    A broken store, or one shaped wrong inside, has been set aside, bytes and all, by the time
    this writes a fresh one.
    """
    store = _read_store_for_write(project_dir)
    measurements = _section(store, "measurements")
    left = _section(store, "retake")
    stamp = datetime.now().replace(microsecond=0).isoformat()
    written = 0
    for row in rows:
        if not row.identified:
            continue
        title = str((titles or {}).get(row.uuid) or row.title)
        entry = {"title": title, "round": str(round_id or ""), "when": stamp, "date": row.date}
        # «Take it as it is» is pinned here, beside the uuid this store already keys by (tcc#21):
        # it is a fact about one capture, like everything else in this log, and a later import of
        # the same capture must not quietly forget that the tuner already answered for it.
        if row.as_is or (measurements.get(row.uuid) or {}).get("as_is"):
            entry["as_is"] = True
        # The window's verdict, by the same uuid and kept the same way (tcc#149, hub #247 patch).
        checked = row.checked or str((measurements.get(row.uuid) or {}).get("checked") or "")
        if checked:
            entry["checked"] = checked
        measurements[row.uuid] = entry
        left.pop(row.uuid, None)  # taken in after all: no longer waiting for a re-take
        written += 1
    if not written:
        return 0
    _write_store(measurements, left, project_dir)
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


def _swept_by_the_method() -> Callable[[dict], bool]:
    """The method's `rew_api.is_swept` (autosound-hub#110, method v3.0.47), which replaced ours (tcc#20).

    Whether a capture is swept is knowledge about REW, and front ends guessing it separately guess
    it differently: ours asked for impulse fields in the listing and skipped the check without
    them, the method reads REW's notes and checks whatever it cannot rule out. A method too old to
    have it, or none at all, answers "check it" for every row — the method's own direction: a
    wrongly included RTA is one confusing row, a skipped sweep is a verdict the tuner never gets.
    """
    try:
        answer = getattr(vendor_loader.load_rew_api(), "is_swept", None)
    except Exception:  # noqa: BLE001 — no method on this machine: nothing to ask, nothing skipped
        answer = None
    return answer if callable(answer) else (lambda _record: True)


def candidates(measurements: dict, project_dir: Optional[Path] = None,
               imported: Optional[dict] = None) -> list[Candidate]:
    """REW's answer as rows, oldest first.

    Sorted by capture time when every row carries a readable one, and left in REW's own order when
    they do not — never half and half. A list sorted by whatever parsed, with the rest swept to one
    end, is the shape that looks ordered and is not.
    """
    seen = load_imported(project_dir) if imported is None else imported
    is_swept = _swept_by_the_method()
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
            swept=bool(is_swept(raw)),
            as_is=bool(uuid) and bool((seen.get(uuid) or {}).get("as_is")),
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


def window(rows: list[Candidate], waiting: int = 0, pages: int = 0,
           keep: Iterable[str] = ()) -> list[Candidate]:
    """The tail of the list: as many as the round is waiting for, plus `pages` portions of ten.

    The tail rather than the head because a capture round ends at the newest measurement, and the
    tuner opens this having just taken some. `waiting` is the round's own count, so the default
    window is "what I am here for" rather than a number somebody guessed.

    `keep` is added to the tail wherever those rows actually sit: a measurement the dialog has
    ticked by name must be visible, and the ones worth ticking are not always the newest ("не
    завжди вони останні, як у мене" — user, 2026-09-06). Order is the list's own either way.
    """
    size = max(int(waiting or 0), MIN_WINDOW) + max(int(pages or 0), 0) * PAGE
    tail = rows[-size:] if size < len(rows) else list(rows)
    wanted = {str(uuid) for uuid in keep if uuid}
    if not wanted:
        return tail
    shown = {row.uuid for row in tail}
    if wanted <= shown:
        return tail
    return [row for row in rows if row.uuid in shown or row.uuid in wanted]


# ---- the capture check, while the microphone is still in place (tcc#21) ---------------------


def _verdict_by_the_method() -> Optional[Callable[..., dict]]:
    """The method's `verify.verdict` (SCR-013), or None without a method that has one.

    Only the method's verdict, nothing of ours (the Arbiter, 2026-10-02): a sweep that never
    completed, a flat loopback, a silent capture. Noise and distortion are REW's to report. It is
    also the function the method's own `capture-check` runs after the import, which the card reads
    — but not asked the same question since tcc#148: the window asks it over each sweep's own range
    (`check_sweeps`) and adds what a title contradicts (`verdict_reader`), while the method's check
    still asks over 20-20000 Hz and reads no titles. The card agrees with the window through TCC's
    own patch (tcc#149: `window_verdicts`, `measurement_view.held_by_the_window`); what still
    disagrees is the method's step gate, which counts such a sweep unusable until the method asks
    over the same range (hub #247).
    """
    try:
        answer = getattr(vendor_loader.load_verify(), "verdict", None)
    except Exception:  # noqa: BLE001 — no method on this machine: nothing to ask
        answer = None
    return answer if callable(answer) else None


def to_check(rows: Iterable[Candidate], names: Optional[dict] = None) -> list[Candidate]:
    """Which of `rows` the check has something to say about.

    Swept, because an RTA answers none of a sweep's questions (TCC-008) — unless its title names a
    sweep, which is a clash the check says (tcc#148) and costs no pull: the method answers an RTA
    from the listing alone. `names` are the titles being given in the window, `{uuid: name}`, read
    in place of REW's. Identified, because the verdict is pinned to a uuid; and not already taken as
    it is — the tuner answered for that one, and asking again is what «Take it as it is» is
    remembered to prevent.
    """
    names = names or {}
    return [row for row in rows if row.identified and not row.as_is
            and (row.swept or _method_tag(names.get(row.uuid) or row.title) == _TAG_SWEEP)]


# The method's tags (`naming.METHOD_SWEEP`, `naming.METHOD_RTA`) and its kinds
# (`rew_api.SWEEP`, `RTA`, `IMPEDANCE`), by value: read off a verdict a test or an older method made.
_TAG_SWEEP, _TAG_RTA = "sw", "rta"
_KIND_SWEEP, _NOT_SWEPT = "sweep", ("rta", "impedance")

#: Where a sweep plainly is not the driver its title names (tcc#148, the Arbiter 2026-10-03: «якщо
#: треба твітер, а там саб — добре б знаходити»). Only the clear extremes, by where the sweep PEAKS
#: (the verdict's `max_freq`, read at the method's 1/6): a tweeter peaking below 200 Hz plays a
#: sub's or a woofer's range, a sub peaking above 2 kHz a tweeter's. A woofer is not judged — a
#: door woofer can peak at 2-4 kHz on its break-up — and a midrange or a mid-bass never is.
TWEETER_PEAK_FLOOR_HZ = 200.0
SUB_PEAK_CEILING_HZ = 2000.0
#: The method's reference codes where a project names no role (`path_check.ROLES`): its driver part.
_ROLE_OF_CODE = {"tw": "tweeter", "sw": "sub"}
_ROLES = {"tweeter": "tweeter", "sub": "sub", "subwoofer": "sub"}


def _method_tag(title: str) -> str:
    """`sw`, `rta`, `imp` — the method tag a title carries by the method's grammar, or ""."""
    try:
        parsed = vendor_loader.load_naming().parse_name(str(title or "").strip())
    except Exception:  # noqa: BLE001 — no method, or a title it cannot read: no tag
        return ""
    return str((parsed or {}).get("method") or "")


def sweep_band(record: Optional[dict]) -> Optional[tuple[float, float]]:
    """The range the sweep itself was set to, as REW holds it for that measurement — the listing's
    `startFreq` / `endFreq` (among its fields in `rew_api.py`, measured on a live REW V5.40) — or
    None where REW gives no range a sweep can have (tcc#148)."""
    try:
        low, high = float((record or {})["startFreq"]), float((record or {})["endFreq"])
    except (KeyError, TypeError, ValueError):
        return None
    return (low, high) if 0 < low < high < float("inf") else None


def _truncated(issue: Any) -> bool:
    """The method's own «covers A-B Hz, asked for C-D — truncated» (`verify.verdict`)."""
    text = str(issue)
    return text.startswith("covers ") and text.rstrip().endswith("truncated")


def only_truncated(issues: Any) -> bool:
    """Whether a verdict's issues are the method's «covers … — truncated» and nothing else — the one
    match for it, the window's drop (`_without_truncation`) and the card's (tcc#149) alike. A line
    the method rewords is not matched, and the verdict stays the method's red."""
    issues = list(issues or [])
    return bool(issues) and all(_truncated(issue) for issue in issues)


#: Every clash `verdict_reader` names — the kind's and the driver's — which the card reads as the
#: window did (tcc#149, the review's m4). Until hub #247; drop with the patch.
CLASHES = ("sweep_named_rta", "rta_named_sweep", "tweeter_plays_low", "sub_plays_high")
#: The window's verdict on a capture it found usable over its own range (tcc#149). Until hub
#: #247; drop with the patch.
CHECKED_USABLE = "usable"


def window_said(verdict: Optional[dict]) -> str:
    """What the window's check said about one capture, as `Candidate.checked` keeps it: `usable`
    for a usable verdict, a clash's own name for a title its data contradicts, else "" (tcc#149).
    Until hub #247; drop with the patch."""
    verdict = verdict or {}
    found = [clash.get("why") for clash in verdict.get("clashes") or []
             if clash.get("why") in CLASHES]
    if found:
        return str(found[0])
    if verdict.get("exists") and verdict.get("applicable", True) is not False \
            and verdict.get("valid"):
        return CHECKED_USABLE
    return ""


def _without_truncation(verdict: dict) -> dict:
    """The verdict with its «truncated» left out: asked over no range of the sweep's own, the
    method's default band is not one it stopped short of (the Arbiter, 2026-10-03: «Якщо немає
    діапазону, то і не перевіряємо»). The rest stands — flat, silent, unreadable — and `valid` is
    the method's own rule over what is left."""
    issues = list(verdict.get("issues") or [])
    kept = [issue for issue in issues if not _truncated(issue)]
    if len(kept) == len(issues):
        return verdict
    return dict(verdict, issues=kept, valid=not kept)


#: Where `check_sweeps` puts a sweep's «could not judge: <error>» (#170 F16-3) — a key the method's
#: verdict never has. With no `exists` beside it, `unusable` never reads it red, `window_said` never
#: `usable` and `verdict_reader` adds no clash: it is its own answer, said as such on the row.
_NOT_JUDGED = "not_judged"


def could_not_judge(verdict: Optional[dict]) -> str:
    """`could not judge: <error>` for a sweep the method's verdict raised on, "" for any other."""
    return str((verdict or {}).get(_NOT_JUDGED) or "")


def check_sweeps(rows: Iterable[Candidate], listing: Optional[Callable[[], dict]] = None,
                 verdict: Optional[Callable[..., dict]] = None,
                 stop: Optional[Callable[[], bool]] = None) -> dict[str, dict]:
    """`{uuid: the method's verdict}` for every row of `rows` the check applies to (`to_check`).

    HTTP throughout — one `listing()` and an FR and an impulse per sweep — so it is called from a
    worker, never from the window. `listing` is REW's `GET /measurements`; `verdict` the method's.

    Each sweep is handed to the method as the ONE record carrying its uuid, at the ordinal REW gives
    it now. The method resolves a title, and two graphs under one title — a re-take before the dud
    is deleted — is exactly where a title cannot say which; the ordinal is read fresh because a
    hand can have moved it since the list was drawn (`resolve_ordinals`). A row REW no longer shows
    gets no verdict: there is nothing there to judge.

    `stop` is asked between two sweeps: a window that closed wants no more of them, and each is up
    to five seconds against a REW that hangs (review M4).

    Each is asked over the range REW holds for it (`sweep_band`, tcc#148): over 20-20000 Hz every
    sub, mid-bass and woofer sweep read «truncated» (finding 146). Where REW gives no range the
    method reads its own default band, and its «truncated» is left out (`_without_truncation`).

    A sweep the verdict raised on gets «could not judge: <error>» (`could_not_judge`), its
    traceback in the log (#170 F16-3): it used to drop out of the answer, and its row read as one
    nobody had asked about.
    """
    wanted = to_check(rows)
    if not wanted:
        return {}
    judge = verdict or _verdict_by_the_method()
    if judge is None:
        return {}
    answer = (listing or vendor_loader.load_rew_api().get_measurements)() or {}
    by_uuid = {str((raw or {}).get("uuid") or ""): (str(ordinal), raw or {})
               for ordinal, raw in answer.items()}
    found: dict[str, dict] = {}
    for row in wanted:
        if stop is not None and stop():
            break
        if row.uuid not in by_uuid:
            continue
        ordinal, raw = by_uuid[row.uuid]
        band = sweep_band(raw)
        asked = {"f_low": band[0], "f_high": band[1]} if band else {}
        try:
            answer = dict(judge(str(raw.get("title") or ""), measurements={ordinal: raw},
                                **asked) or {})
        except Exception as exc:  # noqa: BLE001 — the verdict «never raises»; one that does is said
            app_log.logger().exception("capture check: the method's verdict raised on %r",
                                       raw.get("title"))
            found[row.uuid] = {_NOT_JUDGED: f"could not judge: {type(exc).__name__}: {exc}"}
            continue
        found[row.uuid] = answer if band else _without_truncation(answer)
    return found


def verdict_reader(
        project_dir: Optional[Path] = None) -> Callable[[Optional[dict], str], Optional[dict]]:
    """`(the method's verdict, the title the capture goes by) -> the verdict the window shows`,
    with this project's roles read once (tcc#148).

    What the title says and REW's data plainly contradicts is added as `clashes` — `{"why": …}`
    keys and their numbers, for the window to say in words — and makes the verdict red (`valid`
    false). Asked of the title the capture GOES BY, so a name given in the window that puts the
    title right takes the red off. Two clashes:

    * **The kind**: a title tagged `(rta)` on what REW holds as a sweep, or `(sw)` on an RTA or an
      impedance capture — read off the verdict's `kind` (`rew_api.measurement_kind`), REW's
      definite answer. A capture whose notes say nothing (`unknown`, which `is_swept` checks as a
      sweep on purpose) is not called the wrong kind.
    * **The driver**: a tweeter or a sub whose sweep peaks where the other plays
      (`TWEETER_PEAK_FLOOR_HZ`, `SUB_PEAK_CEILING_HZ`).

    The method's verdict is not changed for anything else; an RTA it did not judge (`applicable`
    false) is red for its clash alone, with none of the method's «nothing here was checked».
    """
    naming, glossary = _grammar(project_dir)
    roles = _channel_roles(project_dir)

    def read(title: str) -> tuple[str, str]:
        try:
            parsed = naming.parse_name(str(title or "").strip(), glossary) if naming else None
        except Exception:  # noqa: BLE001 — one unreadable title is not a broken list
            parsed = None
        if not parsed:
            return "", ""
        code = str(parsed.get("code_current") or parsed.get("code") or "")
        role = roles.get(code) or roles.get(str(parsed.get("code") or ""))
        if role is None and "+" not in code:
            # One driver's code only: a junction typed channel-first, `tw-L+w-L`, is two drivers,
            # and its first segment is not its role (the review of tcc#148, M3).
            role = _ROLE_OF_CODE.get(code.split("-", 1)[0].split(" ", 1)[0], "")
        return str(parsed.get("method") or ""), _ROLES.get(str(role or "").lower(), "")

    def judged(verdict: Optional[dict], title: str) -> Optional[dict]:
        if not verdict or not verdict.get("exists"):
            return verdict
        tag, role = read(title)
        kind = str(verdict.get("kind") or "")
        found: list[dict] = []
        if tag == _TAG_RTA and kind == _KIND_SWEEP:
            found.append({"why": "sweep_named_rta"})
        elif tag == _TAG_SWEEP and kind in _NOT_SWEPT:
            found.append({"why": "rta_named_sweep", "kind": kind})
        peak = (verdict.get("stats") or {}).get("max_freq")
        if (verdict.get("applicable", True) is not False and isinstance(peak, (int, float))
                and not isinstance(peak, bool)):
            if role == "tweeter" and peak < TWEETER_PEAK_FLOOR_HZ:
                found.append({"why": "tweeter_plays_low", "peak": peak})
            elif role == "sub" and peak > SUB_PEAK_CEILING_HZ:
                found.append({"why": "sub_plays_high", "peak": peak})
        if not found:
            return verdict
        out = dict(verdict, clashes=found, valid=False)
        if out.get("applicable") is False:
            out.update(applicable=True, issues=[])
        return out

    return judged


def _channel_roles(project_dir: Optional[Path] = None) -> dict[str, str]:
    """`{channel code: role}` from `project.json`'s channel rows (SCR-001), `{}` without them."""
    try:
        path = Path(project_dir or config.project_dir()) / "project.json"
        rows = json.loads(path.read_text(encoding="utf-8")).get("channels") or []
    except (OSError, ValueError, AttributeError, TypeError):
        return {}
    out = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("code"):
            continue
        role = row.get("role")
        role = role.get("value") if isinstance(role, dict) else role  # a `fact()`, unwrapped
        if isinstance(role, str) and role:
            out[str(row["code"])] = role
    return out


def unusable(verdict: Optional[dict]) -> bool:
    """Measured, and the method says it cannot be used — the one verdict the window marks red.

    Not a curve REW does not hold (`exists: false` is "nobody measured it", a different
    conversation in the method's own words), and not a capture the check does not apply to
    (`applicable: false`, an RTA: grey, never red — TCC-008) — unless its title names a sweep,
    which `verdict_reader` makes red (tcc#148).
    """
    verdict = verdict or {}
    return (bool(verdict.get("exists")) and verdict.get("applicable", True) is not False
            and not verdict.get("valid"))


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


def key_reader(project_dir: Optional[Path] = None) -> Callable[[str], str]:
    """`title -> the identity the grammar gives it`, built once for a whole list.

    The glossary is read once here rather than per title: matching a hundred REW titles against a
    round's expected names is the one place in this module that asks the question in bulk. Without
    the skill it falls back to the plain casefolded title, which is right for every name the
    grammar itself would have built and merely strict about zero-padding.
    """
    return _key_reader(*_grammar(project_dir))


def _grammar(project_dir: Optional[Path] = None) -> tuple[Any, Any]:
    """`(the method's naming module, this project's glossary)`, or `(None, None)` without the skill."""
    try:
        from autosound_tcc.core import config as _config, vendor_loader

        naming = vendor_loader.load_naming()
        glossary = naming.Glossary.for_project(str(project_dir or _config.project_dir()))
    except Exception:  # noqa: BLE001 — no skill, no glossary: read names as written
        return None, None
    return naming, glossary


def _key_reader(naming: Any, glossary: Any) -> Callable[[str], str]:
    if naming is None:
        return lambda title: str(title or "").strip().casefold()

    def read(title: str) -> str:
        text = str(title or "").strip()
        try:
            parsed = naming.parse_name(text, glossary)
        except Exception:  # noqa: BLE001 — one unreadable title is not a broken list
            parsed = None
        return str(naming.name_key(parsed)) if parsed else text.casefold()

    return read


def repeated_titles(rows: Iterable[Candidate]) -> set[str]:
    """Uuids whose title is not unique in what REW is showing right now.

    Two graphs with one name is a normal state of REW and a question only the person can settle
    (user, 2026-09-06). Nothing here refuses or picks: it marks, so the row can say so and the
    tick can be made deliberately.
    """
    counts: dict[str, int] = {}
    rows = list(rows)
    for row in rows:
        counts[row.title] = counts.get(row.title, 0) + 1
    return {row.uuid for row in rows if row.uuid and counts.get(row.title, 0) > 1}


@dataclass(frozen=True)
class Preselect:
    """Which rows the dialog opens ticked, and which ones it refuses to guess between."""

    ticked: frozenset
    ambiguous: frozenset
    #: `{uuid: the expected name it answers to}` for every ticked row, spelled as the ROUND spells
    #: it — the name the row is filed under, which is what the New name column opens with
    #: (finding 28). A REW title that differs only in how the grammar reads it (`_01` for `_1`)
    #: becomes a rename to the round's spelling, which the method's own check now asks for.
    names: dict = field(default_factory=dict)
    #: Rows whose New name was FOUND rather than already right: a spelling the grammar matched
    #: (`_01` for `_1`), or a close match to a name the round still misses (a likely typo). Filled
    #: in and left UNTICKED — an automatic match is the Arbiter's to accept (A17, 2026-09-23).
    proposed: frozenset = frozenset()

    @property
    def shown(self) -> frozenset:
        """Everything the window must put on screen even if it falls outside the tail."""
        return self.ticked | self.ambiguous


#: How alike a title has to be to a missing expected name to be offered as its typo.
_TYPO_CUTOFF = 0.8

#: What may stand where a name's series number stands, in a title the grammar refuses: one word
#: (`B1`, `S3`), so a title that differs anywhere else is not read as another series.
_SERIES_WORD = re.compile(r"[^\s()]+")


def likely_typos(titles: Sequence[str], missing: Iterable[str], expected: Iterable[str],
                 naming: Any = None, glossary: Any = None) -> dict[int, str]:
    """`{index in titles: the missing name it is a likely typo of}` — the import form's and the
    strip's one answer (tcc#114).

    Every pair is scored and the closest wins, highest ratio first, each title and each name used
    once. Walking the titles in REW's order gave a name to the first title past the cutoff: on the
    live REW of 2026-10-01 (finding 122) `sw_B1 (sw)` took `sw_3 (sw)` at 0.84 and the real typo,
    `sw+w-L_3 (se)` at 0.92, got nothing.

    A title that is ANOTHER SERIES of a name the round expects (`_another_series`) is a
    measurement of its own and no typo of any name — not only of its own: `sw+w-L_B1 (sw)` reads
    0.82 like `sw+w-R_3 (sw)` too.
    """
    titles = [str(title) for title in titles]
    names = list(dict.fromkeys(str(name) for name in missing if str(name).strip()))
    if not titles or not names:
        return {}
    another_series = _another_series(expected, naming, glossary)
    scored = []
    for index, title in enumerate(titles):
        if another_series(title):
            continue
        for order, name in enumerate(names):
            # `get_close_matches`'s own orientation: the name first, the title second.
            ratio = difflib.SequenceMatcher(None, name, title).ratio()
            if ratio >= _TYPO_CUTOFF:
                scored.append((-ratio, index, order))
    found: dict[int, str] = {}
    taken: set[int] = set()
    for _ratio, index, order in sorted(scored):
        if index not in found and order not in taken:
            found[index] = names[order]
            taken.add(order)
    return dict(sorted(found.items()))


def _another_series(expected: Iterable[str], naming: Any, glossary: Any) -> Callable[[str], bool]:
    """`title -> whether it is another series of one of the expected names` (tcc#114).

    The grammar always reads the round's names: the round builds them with it. A title it reads
    too is compared by `name_key` with the series left out (`sw_4 (sw)` for `sw_3 (sw)`). A title
    it refuses — `sw_B1 (sw)`: `_N` is digits or `final` — is held against the name itself: the
    name with only its series changed, `sw_` + `B1` + ` (sw)` for `sw_3 (sw)`. Without the skill
    nothing here can tell a series, and the ratio decides alone.
    """
    if naming is None:
        return lambda _title: False

    def parse(text: str) -> Optional[dict]:
        try:
            return naming.parse_name(text, glossary)
        except Exception:  # noqa: BLE001 — one unreadable title is not a broken list
            return None

    def unnumbered(parsed: dict) -> Any:
        # Through `name_key`, both sides: the tuple's shape is the method's (its docstring).
        return naming.name_key({**parsed, "version": None, "version_n": None})

    shapes = []
    for name in expected:
        parsed = parse(str(name).strip())
        if not parsed or parsed.get("version") is None:
            continue  # `(imp)` has no series to differ in
        text, series = str(parsed["title"]), str(parsed["version"])
        cut = text.rfind("_" + series)
        if cut < 0:
            continue
        shapes.append((unnumbered(parsed), naming.name_key(parsed),
                       text[:cut + 1], text[cut + 1 + len(series):], series))

    def another(title: str) -> bool:
        text = str(title or "").strip()
        parsed = parse(text)
        mine = (unnumbered(parsed), naming.name_key(parsed)) if parsed is not None else None
        for bare, key, head, tail, series in shapes:
            if mine is not None:
                if mine[0] == bare and mine[1] != key:
                    return True
            elif len(text) > len(head) + len(tail) and text.startswith(head) \
                    and text.endswith(tail):
                word = text[len(head):len(text) - len(tail)]
                if word != series and _SERIES_WORD.fullmatch(word):
                    return True
        return False

    return another


def preselect(rows: Iterable[Candidate], expected: Iterable[str],
              project_dir: Optional[Path] = None) -> Preselect:
    """Tick the measurements that already answer to a name the round is waiting for.

    This replaces "the last N unprocessed rows" (2026-09-06). That guess was positional, and the
    user's own list is the counter-example: the measurements a round is waiting for are not always
    the newest ones — a re-take, an import from another sitting, a filter in REW, and the tail
    holds somebody else's curves while the right ones sit further up.

    Names are compared through the grammar (`key_reader`), so `c_01 (rta)` and `c_1 (rta)` are one
    name. **Two rows answering to the same expected name tick NEITHER**: which of the two is the
    one that came out is exactly what the person is looking at the list to decide.
    """
    rows, expected = list(rows), list(expected)
    naming, glossary = _grammar(project_dir)
    read = _key_reader(naming, glossary)
    spelled: dict[str, str] = {}
    for name in expected:
        if str(name).strip():
            spelled.setdefault(read(name), str(name))
    wanted = set(spelled)
    wanted.discard("")
    by_key: dict[str, list[Candidate]] = {}
    for row in rows:
        if not row.identified or row.imported:
            continue
        key = read(row.title)
        if key in wanted:
            by_key.setdefault(key, []).append(row)
    ticked, ambiguous, names, proposed = set(), set(), {}, set()
    for key, group in by_key.items():
        if len(group) == 1:
            row = group[0]
            names[row.uuid] = spelled[key]
            if row.title == spelled[key]:
                ticked.add(row.uuid)
            else:
                proposed.add(row.uuid)
        else:
            ambiguous.update(row.uuid for row in group)
    # A likely typo: a row that answers to nothing the round expects, whose title reads almost
    # like a name the round is still missing (`r-R_1 (se)` for `r-R_1 (sw)`). In the round's order,
    # so a tie goes the same way on every run.
    missing = [spelled[key] for key in spelled if key in wanted and key not in by_key]
    grouped = {row.uuid for group in by_key.values() for row in group}
    loose = [row for row in rows
             if row.identified and not row.imported and row.uuid not in grouped]
    found = likely_typos([row.title for row in loose], missing, expected, naming, glossary)
    for index, name in found.items():
        names[loose[index].uuid] = name
        proposed.add(loose[index].uuid)
    return Preselect(ticked=frozenset(ticked), ambiguous=frozenset(ambiguous), names=names,
                     proposed=frozenset(proposed))


@dataclass(frozen=True)
class Naming:
    """What "Give names" worked out: the pairs to send, and what did not line up.

    `leftover` and `unnamed` are the same fact from two ends, and the fact is worth a sentence
    because it is the way this goes wrong in a car. The tuner captures a declared sequence; one
    sweep does not come out and is taken again; now there are six measurements for five names, and
    filling downwards puts every name after the dud on the wrong measurement. The dates cannot
    reveal it — a re-take is LATER, so the list is in perfect capture order — and the names cannot
    either, because they have not been given yet. What reveals it is the count.
    """

    pairs: tuple[tuple[str, str], ...]
    leftover: tuple[str, ...]
    unnamed: tuple[str, ...]

    @property
    def lines_up(self) -> bool:
        return not self.leftover and not self.unnamed


def plan_renames(rows: list[Candidate], names: Iterable[str], start: int = 0) -> Naming:
    """Lay `names` onto `rows` from `start` downwards, one to one.

    Downwards from a row the tuner picked, rather than onto "the newest N": that is the user's own
    description of the flow (2026-09-02, "я стаю в перший замір"), and it is the half a person can
    do that a heuristic cannot — they know which measurement is the first of the batch, including
    when the first one was a dud they are leaving behind.
    """
    targets = [row for row in rows[max(int(start), 0):] if row.identified]
    wanted = [str(name) for name in names if str(name).strip()]
    paired = tuple((row.uuid, name) for row, name in zip(targets, wanted))
    return Naming(
        pairs=paired,
        leftover=tuple(wanted[len(paired):]),
        unnamed=tuple(row.uuid for row in targets[len(paired):]),
    )


def duplicate_targets(pairs: Iterable[tuple[str, str]], measurements: dict) -> list[str]:
    """Proposed titles that would leave REW holding one name twice.

    Checked before anything is sent, and against both ends: the batch's own names, and the titles
    REW already holds — minus the measurements being renamed, since a batch that shuffles names
    among its own members passes through a moment where they collide and comes out fine.

    The method's whole identity model rests on a title being one measurement's name
    (`rew_api.duplicate_titles` exists for the same reason), so this is not tidiness: two graphs
    called `m-L_02 (sw)` are a channel that cannot be resolved afterwards.
    """
    pairs = list(pairs)
    moving = {uuid for uuid, _name in pairs}
    held = {str((raw or {}).get("title") or "")
            for uuid, raw in ((str((raw or {}).get("uuid") or ""), raw)
                              for raw in (measurements or {}).values())
            if uuid not in moving}
    clashes, seen = [], set()
    for _uuid, name in pairs:
        if name in seen or name in held:
            clashes.append(name)
        seen.add(name)
    return sorted(set(clashes))


def duplicate_titles(measurements: dict, renamed: Optional[dict] = None) -> list[str]:
    """Titles REW already holds on more than one measurement, sorted — for a warning, nothing more.

    `duplicate_targets` stops TCC from MAKING such a pair; this names one REW already has (tcc#94).
    The Arbiter, 2026-10-02: a pair is not to be resolved by uuid («не стабільно»), only said —
    the curve window and the method read a measurement by its title, and two graphs under one
    title is a question they cannot answer.

    The rule is the method's own `rew_api.duplicate_titles`, so the warning names what the method's
    check names; without a method that has it, or with one that fails, the same one-line rule —
    this line is advice, and the import window must open without it. `renamed` (`{uuid: title}`)
    is what was renamed since the answer was read — a rename in the import window can be what
    settles a pair. An empty title is not a name, so it is never one held twice.
    """
    renamed = dict(renamed or {})
    current = {}
    for ordinal, raw in (measurements or {}).items():
        raw = dict(raw or {})
        uuid = str(raw.get("uuid") or "")
        if uuid in renamed:
            raw["title"] = renamed[uuid]
        current[ordinal] = raw
    held = None
    try:
        method = getattr(vendor_loader.load_rew_api(), "duplicate_titles", None)
        if callable(method):
            held = method(current)
    except Exception:  # noqa: BLE001 — a method that fails: advice must not cost ⤓ its window
        held = None
    if held is None:
        counts: dict[str, int] = {}
        for raw in current.values():
            title = raw.get("title")
            if title is not None:
                counts[title] = counts.get(title, 0) + 1
        held = [title for title, n in counts.items() if n > 1]
    return sorted(str(title) for title in held if str(title or "").strip())


def channel_of(row: "Candidate", proposed: str = "", project_dir: Optional[Path] = None) -> str:
    """Which channel this row is about: from the name it is being GIVEN, or the one it has.

    "Імʼя або є, або буде в цій таблиці" (user, 2026-09-02) — so a row always knows its channel by
    the time it matters, and a protective filter typed on the row belongs to that channel.

    The grammar answers first, because it is the one that knows `w-L_02 (sw)` and `w-L_2 (sw)` are
    one channel. Without the skill installed the fallback is the plain reading — everything before
    the first `_` — which is right for every name the grammar itself would build.
    """
    return channel_from_title(str(proposed or row.title or ""), project_dir)


def channel_from_title(title: str, project_dir: Optional[Path] = None) -> str:
    """The channel a REW title names, by the grammar where there is one."""
    title = str(title or "").strip()
    if not title:
        return ""
    try:
        from autosound_tcc.core import config as _config, vendor_loader

        naming = vendor_loader.load_naming()
        glossary = naming.Glossary.for_project(str(project_dir or _config.project_dir()))
        parsed = naming.parse_name(title, glossary)
        # `code_current`, then `code` (hub #153 B): the record has never had a `channel` key, so
        # this used to fall through to the split below for every title, and a renamed channel's
        # old titles (SCR-039) missed its protective record.
        code = (parsed or {}).get("code_current") or (parsed or {}).get("code")
        if code:
            return str(code)
    except Exception:  # noqa: BLE001 — no skill, no glossary: read the name as written
        pass
    return title.split("_", 1)[0].split(" ", 1)[0].strip()


def name_explainer(project_dir: Optional[Path] = None) -> Callable[[str], str]:
    """`title -> why it is not in the naming grammar`, "" for a title that is (hub #153 E).

    The method's own `explain_name` (v3.0.53), built once with this project's glossary: a dialog asks
    it on every typed name. A method too old to have it, or none at all, explains nothing rather
    than guessing — the grammar is the method's to read.
    """
    try:
        from autosound_tcc.core import config as _config, vendor_loader

        naming = vendor_loader.load_naming()
        explain = getattr(naming, "explain_name", None)
        if explain is None:
            return lambda _title: ""
        project = Path(project_dir or _config.project_dir())
        glossary = (naming.Glossary.for_project(str(project))
                    if (project / "glossary.json").is_file() or (project / "project.json").is_file()
                    else None)
    except Exception:  # noqa: BLE001 — no method, no glossary: nothing here can read a title
        return lambda _title: ""

    def why(title: str) -> str:
        try:
            _record, reason = explain(str(title).strip(), glossary)
        except Exception:  # noqa: BLE001 — a reader that fails explains nothing
            return ""
        return str(reason or "")

    return why


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
