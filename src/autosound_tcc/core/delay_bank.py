"""Delays the Arbiter has read off the curves, kept per measurement until they are analysed.

Aligning a car is not one pair of curves. It is a woofer against a woofer, then the pair against
a midbass, then the front against the sub — and each of those readings is worth nothing on its own
because a delay is only ever relative to everything else in the cabin. The curve window used to
lose each one the moment the next pair was loaded, which put the Arbiter in the position of
holding six numbers in their head while reading the seventh (user, 2026-08-12: "було б здорово
мати збереження затримки по кожному каналу... і потім коли ти все виставив — відправити на аналіз
ШІ").

**Not for writing.** This is a reading, not a change: nothing here goes to a DSP, and nothing here
is a delta. The whole set is handed to the model to be *looked at* — the model's job is to say
whether the picture is coherent (a sub 20 ms behind everything else is a measurement error, not a
tuning), and the Arbiter's job is to decide what to do about it. Two more gates stand between this
and any hardware, and both of them are somebody else's (see `project_tcc_safety_gates`).

Keyed by MEASUREMENT TITLE **within a capture series**. Two scopes because neither alone is
enough: a delay read off `w-L_02` was read off that capture, at that crossover, with that gain, so
folding it onto "w-L" would carry a number from round 2 into round 5 — and a series is exactly
what the ledger version cannot tell apart from another pass at the same config (SCR-034), so two
passes can hold the same titles. Switching the measurement panel back to an earlier series brings
that series' own curves; it has to bring that series' own corrections with them (user, 2026-08-12).

**One entry per (series, title)** (#197). The bank held one per title until v1.1.3, with the
series as a field of it: a step after a series switch banks every driver on screen, so it MOVED
each one's entry into the new series, and back on the old one those drivers read nothing — the
button at «(0)» the moment the session opened the next round, and the next step banking what was
drawn over the reading.

Two fields now, so that a TCC rolled back to v1.1.3 loses nothing. `KEY` stays exactly v1.1.3's
field — one entry per title, the series it was last banked under in it — and every step keeps it
current, so v1.1.3 reads the latest reading of each title as it always did. Each series' own
entries live beside it in `BY_SERIES`, a field v1.1.3 has never heard of and carries through its
writes untouched. Under a series the entry shown is `KEY`'s when it was banked under that series
— the series' latest: the same as its own, or written since by v1.1.3, which writes `KEY` alone —
else the series' own, else an entry with no series. A step that takes `KEY`'s place from another
series' entry first puts that entry in the other series' own, so a reading v1.1.3 banked is kept
on the way back. A file of v1.1.3's shape is `KEY` alone: it reads as it is, and the first step
writes `BY_SERIES`. (The list-per-title shape of the first #197 commit was never released and is
not read: a list there is an entry this TCC cannot read, carried as such.)

An entry with no series (written before the scope existed, or with no series to give) is shown
under every series that holds no entry of its own for that title, rather than disappearing from
all of them. Touched under a series it is NOT moved: that series gets its own entry, starting from
it, and the one with no series is kept aside (`BY_SERIES[""]`) for every other — moving it, «it
picks up a series the first time it is touched» until #197, took the reading off every series it
was shown under, and nothing in the entry says which series it was read in. Clear of a series
takes it only where it is what that series shows.

A field that is not the shape this TCC writes — a newer TCC's, or a hand edit — is refused, never
written over: a strict read raises `BankShapeUnknown`, and so do a step and a Clear, before they
write anything. Inside the fields, an entry this TCC cannot read is carried through every write
that does not touch it (G10 M2, #208).

**Zero is a reading too, and it is ambiguous.** A driver plotted here and left at zero may be the
reference everything else was measured from — or a driver nobody has got to yet, since the sub,
the centre and the rears are done last ("w-R немає, бо він був нулем"; "нуль може бути ще те, до
чого руки не дійшли", user, 2026-08-12). Nothing in this data separates the two, so the entry is
kept and the sentence says exactly that and no more. What TCC can state honestly is: this was on
screen and carries no shift; this has never been opened. The inference is the model's.

**Since 2026-08-18 the same entry carries the driver's all-pass too** (`core/allpass.py`, the fourth
of the curve-window asks). It is the same kind of thing as the delay — a proposal about one driver,
read off the curves while looking at the predicted sum, worth nothing on its own and everything as
part of the set — and it has the same problem: a filter dialled on m-L while looking at w-L+m-L has
to still be there when m-L comes back on screen against tw-L, or the workflow the Advisor described
(load a group, look at the sum, isolate a driver with its ×) loses it on the first ×. Kept beside the
delay rather than in a second store, so one clear clears the set and one sentence sends it.

Lives in `.tcc/` with TCC's other state, never in the skill's files (D-6).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Optional

from autosound_tcc.core import config, own_store, project_settings
from autosound_tcc.core.allpass import Allpass

#: The per-title field, exactly as v1.1.3 keeps it: one entry per title, the series it was last
#: banked under a field of it. Kept up to date on every step, so a TCC rolled back reads the latest
#: reading of each title as it always did, and its writes, which touch this field alone, lose
#: nothing of what is below (#197).
KEY = "curve_delays"
#: The per-series field (#197): `{series: {title: entry}}`, and under `""` — never a series, the
#: window's series is `None` or a non-empty id — an entry with no series a series' step took
#: `KEY`'s place from. A field v1.1.3 has never heard of: it carries it through every write.
BY_SERIES = "curve_delays_by_series"
_NONE = object()

#: `put(allpass=_KEEP)`: leave whatever all-pass the entry already carries. The delay is banked on
#: every change of every trace, and a call that only meant to move a delay must not wipe a filter.
_KEEP = object()


#: `{store path: sentence}` — the bank's store found set aside as broken, and the sentence said
#: then, while nothing has been banked since (`aside_said`). The store's own memo goes with any
#: write that lands a fresh file — a gate, an effort or a model pick — and a curve window opened
#: after such a pick read «nothing banked», the copy holding the readings named nowhere on it
#: (Fable's re-review of the branch fix, round 2, m1; #208). Kept here, so every window reads it.
_aside: dict[str, str] = {}
_aside_lock = threading.Lock()


def _store_key(tcc_dir: Optional[Path]) -> str:
    return os.path.abspath(project_settings.path_for(tcc_dir or config.tcc_dir()))


def aside_said(tcc_dir: Optional[Path] = None) -> str:
    """The sentence said when the bank's store was set aside as broken — until the bank's own
    write lands (`put_many`, `clear`) or a read finds readings (`forget_aside`) — or ""."""
    key = _store_key(tcc_dir)
    said = own_store.aside_said(Path(key))
    with _aside_lock:
        if said:
            _aside[key] = said
        return said or _aside.get(key, "")


def forget_aside(tcc_dir: Optional[Path] = None) -> None:
    """The set-aside is over for the bank: readings were found, or the bank wrote a fresh one."""
    with _aside_lock:
        _aside.pop(_store_key(tcc_dir), None)


class Reading(NamedTuple):
    """One driver's reading for `put_many`: what `put` is handed for one title.

    `allpass` as in `put` — an `Allpass` to set, `None` to take off, `_KEEP` to leave the entry's.
    """

    title: str
    ms: float
    arrival_ms: Optional[float] = None
    allpass: Any = _KEEP


class BankShapeUnknown(own_store.StoreUnreadable):
    """A bank field is there and is not the shape this TCC writes: `KEY` not a map of titles,
    `BY_SERIES` not a map of maps — a newer TCC's, or a hand edit. Refused as a store that cannot
    be read is (it is one, to the bank): read strictly, written over never. Its text is the
    sentence said, once for this state of the file."""


class _Bank(NamedTuple):
    """The two fields as stored: `latest` is `KEY` (`{title: entry}`, v1.1.3's own), `by` is
    `BY_SERIES` (`{series: {title: entry}}`, `""` for the entries with no series)."""

    latest: dict
    by: dict


def _known(fields: dict, tcc_dir: Path) -> _Bank:
    """The bank as read, or `BankShapeUnknown` for a field of a shape this TCC does not write —
    for a reader that would put "nothing banked" on screen, and for every write."""
    latest, by = fields.get(KEY), fields.get(BY_SERIES)
    wrong = ""
    if latest is not None and not isinstance(latest, dict):
        wrong = f"{KEY} is a {type(latest).__name__}"
    elif by is not None and not (isinstance(by, dict)
                                 and all(isinstance(v, dict) for v in by.values())):
        wrong = f"{BY_SERIES} is not a map of series"
    if wrong:
        path = project_settings.path_for(tcc_dir)
        message = (f"{path}: the delay bank there is not a shape this TCC reads ({wrong}; a newer "
                   "TCC's?); TCC will not write over it")
        own_store.say_once(path, message, "bank")
        raise BankShapeUnknown(message)
    return _Bank(dict(latest or {}), {str(s): dict(rows) for s, rows in (by or {}).items()})


def _forgiving(fields: dict) -> _Bank:
    """`_known` for a plain read: a field of a shape this TCC does not write is "nothing"."""
    latest, by = fields.get(KEY), fields.get(BY_SERIES)
    if not isinstance(latest, dict):
        latest = {}
    if not isinstance(by, dict) or not all(isinstance(v, dict) for v in by.values()):
        by = {}
    return _Bank(dict(latest), {str(s): dict(rows) for s, rows in by.items()})


def _series_of(row: Any) -> Optional[str]:
    """The series an entry was banked under; None for one with no series — the first version's
    bare number among them."""
    if isinstance(row, dict) and row.get("set") is not None:
        return str(row["set"])
    return None


def _shown(bank: _Bank, title: str, session: Optional[str]) -> Optional[tuple]:
    """Where the entry shown for `title` under `session` is — `(KEY,)` or `(BY_SERIES, series)` —
    or None when none is.

    Under a series: `KEY`'s entry when it was banked under that series (it is that series' latest:
    equal to its own, or written since by a TCC that keeps `KEY` alone — v1.1.3 after a roll
    back); else the series' own; else `KEY`'s entry with no series; else the one with no series
    a series' step took `KEY`'s place from. With no series named — a window with no series
    provider, a caller outside one — `KEY`'s entry, as v1.1.3 reads it, else the one with no
    series kept aside.
    """
    key = bank.latest.get(title, _NONE)
    if session is not None:
        if key is not _NONE and _series_of(key) == session:
            return (KEY,)
        if title in bank.by.get(session, {}):
            return (BY_SERIES, session)
    if key is not _NONE and (session is None or _series_of(key) is None):
        return (KEY,)
    if title in bank.by.get("", {}):
        return (BY_SERIES, "")
    return None


def _row(bank: _Bank, where: tuple, title: str) -> Any:
    return bank.latest[title] if where == (KEY,) else bank.by[where[1]][title]


def _titles(bank: _Bank, session: Optional[str]) -> list:
    """Every title that may have an entry under `session`, in the store's order."""
    out = dict.fromkeys(bank.latest)
    for series in ("", session):
        if series is not None:
            out.update(dict.fromkeys(bank.by.get(series, {})))
    return list(out)


def _entries(tcc_dir: Optional[Path] = None, session: Optional[str] = None,
             strict: bool = False) -> dict[str, dict]:
    """`{title: {"ms": delay, "at": measured arrival or None, "set": series, "apf": Allpass|None}}`
    — the entry shown under `session` for each title (`_shown`).

    Read forgivingly unless `strict`: a store that cannot be read, or a field of a shape this TCC
    does not write, is "nothing banked", or, strict, `StoreUnreadable` (`BankShapeUnknown`). A
    write never starts from this — see `put_many`.
    """
    tcc_dir = tcc_dir or config.tcc_dir()
    data = project_settings.load(tcc_dir, strict=strict)
    return _parsed(_known(data, tcc_dir) if strict else _forgiving(data), session)


def _parsed(bank: _Bank, session: Optional[str] = None) -> dict[str, dict]:
    """Per title, the entry shown under `session`, when it can be read."""
    out: dict[str, dict] = {}
    for title in _titles(bank, session):
        where = _shown(bank, title, session)
        entry = _read(_row(bank, where, title)) if where else None
        if entry is not None:
            out[str(title)] = entry
    return out


def _read(row: Any) -> Optional[dict]:
    """One entry as `_entries` gives it, or None for one whose delay is not a number.

    Two forms are read: a bare number (what the first version wrote) and the object. The arrival
    is what the delay is measured FROM — a delay with no origin is not checkable, and the whole
    point of handing the set to a model is that it can check it. The all-pass is read through
    `Allpass.from_dict`, so what comes back is a valid filter or nothing — never a half of one.
    """
    apf_raw = None
    if isinstance(row, dict):
        ms, at = row.get("ms"), row.get("at")
        apf = Allpass.from_dict(row.get("apf"))
        if apf is None and row.get("apf") is not None:
            apf_raw = row["apf"]  # a kind this TCC does not read: kept as read (#208)
    else:
        ms, at, apf = row, None, None
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return None
    try:
        at = float(at) if at is not None else None
    except (TypeError, ValueError):
        at = None
    return {"ms": ms, "at": at, "set": _series_of(row), "apf": apf, "apf_raw": apf_raw}


def unread_entries(tcc_dir: Optional[Path] = None, session: Optional[str] = None
                   ) -> dict[str, tuple[str, str]]:
    """`{title: (what, why)}` for this series' entries the bank holds and cannot read — `what` is
    `"ms"` for a delay that is not a number (the entry is skipped by every read), `"apf"` for a
    filter of a kind this TCC does not know (read as none). Read strictly: `StoreUnreadable` for
    a store that is there and cannot be read, or a field of a shape this TCC does not write.

    For the curve window (G10 M2 on screen, #208): such a driver on screen is drawn without what
    is banked for it, and a step banked what was drawn over the entry — so it keeps the entry as
    it is until the person moves that driver, and says why."""
    tcc_dir = tcc_dir or config.tcc_dir()
    bank = _known(project_settings.load(tcc_dir, strict=True), tcc_dir)
    out: dict[str, tuple[str, str]] = {}
    for title in _titles(bank, session):
        where = _shown(bank, title, session)
        if where is None:
            continue
        row = _row(bank, where, title)
        if not isinstance(row, dict):
            # The first version's bare form, which carries no series: one that is a number is
            # read; one that is not (`"1,25"`) is named as the object's is, and kept until moved —
            # skipped silently, the next step wrote over it (#208's group review).
            try:
                float(row)
            except (TypeError, ValueError):
                out[str(title)] = ("ms", f"delay {row!r} is not a number")
            continue
        try:
            float(row.get("ms"))
        except (TypeError, ValueError):
            out[str(title)] = ("ms", f"delay {row.get('ms')!r} is not a number")
            continue
        if row.get("apf") is not None and Allpass.from_dict(row.get("apf")) is None:
            out[str(title)] = ("apf", f"an all-pass this TCC does not read: {row['apf']}")
    return out


def load(tcc_dir: Optional[Path] = None, session: Optional[str] = None, *,
         strict: bool = False) -> dict[str, float]:
    """`{measurement title: ms}` for the drivers actually MOVED, worst case empty.

    Zeros are excluded here because this feeds the pickers and the label, where "+0.000 ms" beside
    a title says nothing — `references()` is where a deliberate zero surfaces. Never raises: a
    hand-edited file is "nothing banked yet", not a dead curve window.

    `strict` raises `StoreUnreadable` for a store that is there and cannot be read: for a reader
    that puts what it reads on screen, where "nothing banked" is every driver at zero, and the
    next step banks what is on screen (G10 C1).
    """
    return {
        title: entry["ms"]
        for title, entry in _entries(tcc_dir, session, strict).items() if entry["ms"]
    }


def references(tcc_dir: Optional[Path] = None, session: Optional[str] = None) -> list[str]:
    """Drivers that have been on screen and carry no shift — and no all-pass either.

    Named for what it is, not for what it might mean: this is the reference on some passes and an
    untouched driver on others, and only the person tuning knows which. A driver at zero delay
    that carries an all-pass is neither: it has a proposal, and `allpasses()` names it.
    """
    return sorted(
        title for title, entry in _entries(tcc_dir, session).items()
        if not entry["ms"] and entry["apf"] is None
    )


def allpasses(tcc_dir: Optional[Path] = None, session: Optional[str] = None, *,
              strict: bool = False) -> dict[str, Allpass]:
    """`{measurement title: Allpass}` for the drivers that carry one; `strict` as in `load`."""
    return {
        title: entry["apf"] for title, entry in _entries(tcc_dir, session, strict).items()
        if entry["apf"] is not None
    }


def seen(tcc_dir: Optional[Path] = None, session: Optional[str] = None, *,
         strict: bool = False) -> set:
    """Every driver this series has an opinion about, at zero or otherwise; `strict` as in
    `load`."""
    return set(_entries(tcc_dir, session, strict))


def arrivals(tcc_dir: Optional[Path] = None, session: Optional[str] = None) -> dict[str, float]:
    """`{title: measured arrival in ms}` for the entries that have one."""
    return {
        title: entry["at"] for title, entry in _entries(tcc_dir, session).items()
        if entry["at"] is not None
    }


def put(
    title: str,
    ms: float,
    tcc_dir: Optional[Path] = None,
    arrival_ms: Optional[float] = None,
    session: Optional[str] = None,
    allpass=_KEEP,
) -> dict[str, float]:
    """Bank one reading, zero included — and the driver's all-pass, when the caller says.

    `allpass` is an `Allpass` to set, `None` to take off, or left alone to keep whatever the entry
    carries: the delay is banked on every change of every trace on screen, and a call that only
    meant to move a delay must not wipe a filter that was dialled a minute ago.

    Negative is a real reading, not an error: on a later pass the channel already carries a delay
    and the correction takes time back off it (user, 2026-08-12). What may not go below zero is
    the channel's TOTAL, which is a fact about the ledger and is checked where the ledger is
    known — see `CurveView.total_delay_ms`.

    Zero is kept, not dropped. It was dropped at first on the reasoning that "needs no delay" and
    "not looked at" should not be confused — right distinction, wrong resolution: a driver on
    screen and left at zero is the REFERENCE the rest are aligned to, and dropping it made the
    reference indistinguishable from a channel nobody opened. What separates the two now is
    whether there is an entry at all.
    """
    return put_many([Reading(title, ms, arrival_ms, allpass)], tcc_dir, session)


def put_many(
    readings: Iterable[Reading],
    tcc_dir: Optional[Path] = None,
    session: Optional[str] = None,
) -> dict[str, float]:
    """Bank a whole set of readings in one read and one write, as one `put` per reading would.

    The curve window banks every driver on screen on every step of the delay box, and one `put`
    each was one load and one write of the whole store per driver — seven of both for a side and
    the sub, on every step (#177). Applied in order to one copy of the entries, so the store ends
    exactly as the `put`s leave it: a later reading of the same title over an earlier one, an
    all-pass kept or taken off, an arrival not named kept, the series set.

    It fails as they do: a store that cannot be read or written raises what `put` raises, once for
    the set. And the store never holds half a set — a reading that cannot be stored stops the
    write before it starts, where the `put`s ahead of it would already have written. No reading
    is no write.

    The write is ONE strict read plus these readings (`project_settings.update_values`, both
    fields at once). The bank was read forgivingly first and written through `set_value`, which
    read again: a first read that failed and a second that did not wrote the readings alone over
    every other driver, series and all-pass (G10 C2).

    A reading under a series is that series' entry for its title (#197), and `KEY`'s entry too, as
    v1.1.3 would have written it. What `KEY` held there is not lost to it: another series' latest
    goes to that series' own (it is never older than what is there), an entry with no series aside
    under `""`, for the series that still show it. With no series named, `KEY`'s entry alone, with
    no series — never a series' own: which one was meant is not known. Every other entry is
    written back exactly as it was read, so what this TCC cannot read is never lost to a step on
    something else: a delay that is not a number, a filter of a kind it does not know, a field it
    has never heard of (G10 M2). A series with no entry of its own starts from the one it was
    shown: an arrival and a filter the reading does not name carry.
    """
    tcc_dir = tcc_dir or config.tcc_dir()
    readings = list(readings)
    if not readings:
        return load(tcc_dir, session)
    banked: dict[str, float] = {}

    def change(fields: dict) -> dict[str, Any]:
        bank = _known(fields, tcc_dir)
        for reading in readings:
            title = str(reading.title)
            where = _shown(bank, title, session)
            was = (_read(_row(bank, where, title)) if where else None) or {}
            row = _serialised(_entry(was, reading, session))
            if title in bank.latest:
                held = _series_of(bank.latest[title])
                if held is None and session is not None:
                    bank.by.setdefault("", {})[title] = bank.latest[title]
                elif held is not None and held != session:
                    bank.by.setdefault(held, {})[title] = bank.latest[title]
            bank.latest[title] = row
            if session is not None:
                bank.by.setdefault(session, {})[title] = dict(row)
            else:
                bank.by.get("", {}).pop(title, None)  # `KEY`'s is the one with no series now
        banked.update(
            (name, entry["ms"]) for name, entry in _parsed(bank, session).items() if entry["ms"])
        return _stored(bank)

    project_settings.update_values(tcc_dir, (KEY, BY_SERIES), change)
    forget_aside(tcc_dir)  # the fresh bank the set-aside line said the next step would start
    return banked


def _stored(bank: _Bank) -> dict[str, Any]:
    """The two fields to write: an empty one removed."""
    by = {series: rows for series, rows in bank.by.items() if rows}
    return {KEY: bank.latest or None, BY_SERIES: by or None}


def put_many_or_say(readings: Iterable[Reading], tcc_dir: Optional[Path] = None,
                    session: Optional[str] = None) -> bool:
    """`put_many` for the curve window, which banks on every step of the box and must not be
    stopped by the store: True when written, False when not — said once for this state of the
    file, by the window's one rule (`project_settings.written_or_said`, R-cb)."""
    tcc_dir = tcc_dir or config.tcc_dir()
    return project_settings.written_or_said(tcc_dir, lambda: put_many(readings, tcc_dir, session))


def _entry(was: dict, reading: Reading, session: Optional[str]) -> dict:
    """The entry `reading` leaves, over what the bank held for its title (`was`, or `{}`)."""
    at = reading.arrival_ms if reading.arrival_ms is not None else was.get("at")
    apf = was.get("apf") if reading.allpass is _KEEP else reading.allpass
    if apf is not None and not isinstance(apf, Allpass):
        raise TypeError(f"allpass must be an Allpass or None, got {apf!r}")
    return {
        "ms": round(float(reading.ms), 4),
        "at": None if at is None else round(float(at), 4),
        "set": session,
        "apf": apf,
        # Kept means kept: a filter of a kind this TCC cannot read goes on as it was read (#208).
        "apf_raw": was.get("apf_raw") if reading.allpass is _KEEP else None,
    }


def _serialised(entry: dict) -> dict:
    """One entry in the store's own shape: the all-pass as the ledger's band object, or the key
    absent."""
    row = {"ms": entry["ms"], "at": entry["at"], "set": entry["set"]}
    if entry.get("apf") is not None:
        row["apf"] = entry["apf"].as_dict()
    elif entry.get("apf_raw") is not None:
        row["apf"] = entry["apf_raw"]
    return row


def clear(tcc_dir: Optional[Path] = None, session: Optional[str] = None) -> None:
    """Forget one capture series' readings, or all of them when no series is named.

    Scoped, because the button sits under a window showing one series and a button that also wiped
    last week's would be doing something nobody asked for. What goes is what that series shows,
    and only that: its own entries, and an entry with no series where it is the one the series
    shows — for a title the series holds none of its own (as since the scope came in,
    2026-08-12). An entry with no series the series no longer shows stays for the others (#197's
    review, I1), and so does another series' entry of the same title. Through one strict read, as
    `put_many` is (G10 C2): a read that failed clears nothing, and a field of a shape this TCC
    does not write is not cleared either.
    """
    tcc_dir = tcc_dir or config.tcc_dir()

    def change(fields: dict) -> dict[str, Any]:
        # Another series' entries as they were read, not as `_parsed` reads them: one it cannot
        # read is still that series' (G10 M2).
        bank = _known(fields, tcc_dir)
        if session is None:
            return {KEY: None, BY_SERIES: None}
        for title in _titles(bank, session):
            where = _shown(bank, title, session)
            if where == (KEY,):
                del bank.latest[title]
            elif where is not None:
                del bank.by[where[1]][title]
        bank.by.pop(session, None)  # its own, shown or under `KEY`'s newer one
        for series, rows in bank.by.items():
            # A title `KEY` no longer holds gets another series' own back in it, as v1.1.3 kept
            # it: a TCC rolled back reads it under that series, and no series reads it here.
            for title, row in rows.items():
                if series and title not in bank.latest:
                    bank.latest[title] = row
        return _stored(bank)

    project_settings.update_values(tcc_dir, (KEY, BY_SERIES), change)
    forget_aside(tcc_dir)


def clear_or_say(tcc_dir: Optional[Path] = None, session: Optional[str] = None) -> bool:
    """`clear` for the curve window's Clear, as `put_many_or_say` is `put_many` for its steps: True
    when cleared, False when the store refused — said once, and nothing cleared."""
    tcc_dir = tcc_dir or config.tcc_dir()
    return project_settings.written_or_said(tcc_dir, lambda: clear(tcc_dir, session))


def as_sentence(
    bank: dict[str, float],
    processing_rate_hz: Optional[float] = None,
    lang_t=None,
    current=None,
    at: Optional[dict] = None,
    unplaced: Optional[list] = None,
    reference: Optional[list] = None,
    allpasses: Optional[dict] = None,
) -> str:
    """The whole set as something a model can read, and a person can check before it is sent.

    Every line carries the sample count when a rate is on record, because the skill's own rule is
    that a delay is stated in milliseconds AND samples — and because the arithmetic between them
    is exactly where a plausible-looking set turns out to be unreachable on the hardware.

    `current(title) -> ms | None` supplies what each channel is set to NOW. With it, each line
    also states the resulting total, and a total below zero is called out on the line rather than
    left for the model to notice — a set that cannot be applied should not need a reader to spot
    it. Without it the lines are readings alone, which is honest about what TCC knows.

    `allpasses` (`{title: Allpass}`) is the other half of the set: its own block after the delays,
    because `ta_ms` and an EQ band are two settings typed in two places, and each one named in the
    ledger's own words so it can be proposed verbatim. With its own caveat: simulated on the
    sweeps in hand, never verified by a summation sweep — that is the model's job to ask for.
    """
    allpasses = allpasses or {}
    if not bank and not reference and not allpasses:
        return ""
    t = lang_t or (lambda key: key)
    at = at or {}
    lines, impossible, landings = [], False, []
    # **The common part comes off before anything is proposed.** A delay set is only defined up to
    # a constant: the curves measure the DIFFERENCE between arrivals, and where the tuner dropped
    # them is not a measurement of anything. A set banked by dragging three drivers onto a common
    # 14.8 ms read +10.690 / +10.670 / +10.000, which is meaningless as a delay and beyond what
    # most processors accept (user, 2026-08-18: "затримки виходять значно більшими, ніж вони там
    # є"). Relative, the same set is 0.000 / +0.670 / +0.690 — 0.69 ms is 23 cm of car. Every
    # difference survives the shift, so the landings below still have exactly the same spread.
    #
    # Stored raw and normalised HERE, on the way out: the stored number is what the tuner dragged
    # and what gets restored onto the plot when a driver comes back on screen. This is a
    # proposal, and only a proposal has to be enterable.
    offset = min(bank.values()) if len(bank) > 1 else 0.0
    origin = min(bank.items(), key=lambda kv: (kv[1], kv[0]))[0] if offset else ""
    bank = {title: ms - offset for title, ms in bank.items()}
    # By where each driver ENDS UP, not by how far it moves. The outlier is the whole point of
    # sending this, and sorted by delay it sat in the middle of the list (user's own set,
    # 2026-08-12: four drivers inside 37 µs and one a millisecond out).
    order = sorted(bank.items(), key=lambda kv: (at.get(kv[0], 0.0) + kv[1], kv[0]))
    for title, ms in order:
        unit = t("unitMs")
        line = f"  {title}: {ms:+.3f} {unit}"
        if processing_rate_hz:
            line += f" ({int(round(ms * processing_rate_hz / 1000.0)):+d} {t('unitSmp')})"
        measured = at.get(title)
        if measured is not None:
            # The arrival as CAPTURED, and where this delay puts it. Without the origin a set of
            # deltas cannot be checked for coherence, which is the only reason it is being sent.
            landings.append(measured + ms)
            line += f" | {t('curveBankArrival')} {measured:.3f} → {measured + ms:.3f} {unit}"
        now = current(title) if current else None
        if now is not None:
            total = now + ms
            line += f" | {t('curveBankChannel')} {now:.3f} → {total:.3f} {unit}"
            if total < 0:
                line += "  << " + t("curveDelayBelowZero")
                impossible = True
        lines.append(line)
    if allpasses and not bank:
        # An all-pass set with no delays in it is still a set; the delay head would announce a
        # list that is not there.
        head = [t("curveBankAskApfOnly")]
    else:
        head = [t("curveBankAsk"), t("curveBankConvention")]
        if origin:
            # Named, because a set of differences with no stated origin is a set the reader has
            # to reverse-engineer — and the origin IS the alignment: "hold the others back until
            # they meet this one".
            head.append(t("curveDelayRelative").format(name=origin))
    tail = [t("curveBankNotForWriting")]
    if allpasses:
        # After the delays and before the zeros: it is part of the proposal, not a caveat about
        # it. One line per driver in the ledger's words, then the one caveat that is this block's
        # own — nothing here was checked against a summation sweep.
        if lines:
            lines.append("")
        lines.append(t("curveBankApf"))
        for title in sorted(allpasses):
            lines.append(f"  {title}: {allpasses[title].label()}")
        lines.append(t("curveBankApfCaveat"))
    if reference:
        # Stated, not interpreted. A zero here may be the reference the set was built on or a
        # driver not reached yet, and the panel cannot tell — claiming "reference" would put a
        # conclusion of TCC's into a message that is supposed to carry evidence (user, 2026-08-12:
        # "не знаю як це відрізнити... а він вже сам зробить висновки").
        lines.append("")
        lines.append(t("curveBankAtZero").format(names=", ".join(sorted(reference))))
    if unplaced:
        # A driver with NO reading is not a driver at zero. It is one nobody has placed yet, and
        # the difference decides whether the set above is a plan or a fragment — the user's own
        # first set left w-R, both rears, the centre and the sub off it entirely, with nothing
        # saying so (2026-08-12). Named, because "5 more" does not tell the model which.
        lines.append("")
        lines.append(t("curveBankUnplaced").format(names=", ".join(sorted(unplaced))))
    if len(landings) > 1:
        spread = max(landings) - min(landings)
        tail.insert(0, t("curveBankSpread").format(spread=f"{spread:.3f}", n=len(landings)))
    if impossible:
        tail.insert(0, t("curveBankImpossible"))
    return "\n".join([*head, *lines, *tail])


def code_of(title: str) -> str:
    """The channel code a measurement title starts with: `w-L_02 (sw)` → `w-L`.

    The skill's own naming convention (`<code>_<round>[ (method)]`), and the ledger keys its
    channels by exactly that code — `{"m-L": {"ta_ms": 1.266}, ...}` in a real snapshot. So the
    join is a split, not a guess. A title that does not follow the convention yields something
    that matches no channel, which reads as "not known" and is the right answer.
    """
    return str(title).split("_", 1)[0].strip()


def current_delays(view) -> dict[str, float]:
    """`{channel code: ta_ms}` from a loaded project view — what the DSP is set to right now.

    Duck-typed on `.groups[].rows[].raw` so this module stays out of the state layer's business.
    Used for one thing: checking that a proposal does not take a channel below zero. A channel
    with no delay field simply is not in the mapping, and an absent entry means "unknown", never
    "zero" — a −0.15 ms proposal against those two is a different conversation.
    """
    out: dict[str, float] = {}
    for group in getattr(view, "groups", ()) or ():
        for row in getattr(group, "rows", ()) or ():
            raw = getattr(row, "raw", None) or {}
            for field in ("ta_ms", "delay_ms"):
                value = raw.get(field)
                if isinstance(value, (int, float)):
                    out.setdefault(str(getattr(row, "id", "")), float(value))
                    break
    return out
