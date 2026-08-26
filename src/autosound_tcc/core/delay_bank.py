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

An entry written before the scope existed carries no series and is shown under every one, rather
than disappearing from all of them. It picks up a series the first time it is touched.

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

from pathlib import Path
from typing import Optional

from autosound_tcc.core import config, project_settings
from autosound_tcc.core.allpass import Allpass

KEY = "curve_delays"

#: `put(allpass=_KEEP)`: leave whatever all-pass the entry already carries. The delay is banked on
#: every change of every trace, and a call that only meant to move a delay must not wipe a filter.
_KEEP = object()


def _entries(tcc_dir: Optional[Path] = None, session: Optional[str] = None) -> dict[str, dict]:
    """`{title: {"ms": delay, "at": measured arrival or None, "set": series, "apf": Allpass|None}}`.

    Two shapes are read: a bare number (what the first version wrote) and the object. The arrival
    is what the delay is measured FROM — a delay with no origin is not checkable, and the whole
    point of handing the set to a model is that it can check it. The all-pass is read through
    `Allpass.from_dict`, so what comes back is a valid filter or nothing — never a half of one.
    """
    raw = project_settings.load(tcc_dir or config.tcc_dir()).get(KEY)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    for title, value in raw.items():
        if isinstance(value, dict):
            ms, at, series = value.get("ms"), value.get("at"), value.get("set")
            apf = Allpass.from_dict(value.get("apf"))
        else:
            ms, at, series, apf = value, None, None, None
        if session is not None and series is not None and str(series) != session:
            continue
        try:
            ms = float(ms)
        except (TypeError, ValueError):
            continue
        try:
            at = float(at) if at is not None else None
        except (TypeError, ValueError):
            at = None
        out[str(title)] = {
            "ms": ms, "at": at, "set": None if series is None else str(series), "apf": apf,
        }
    return out


def load(tcc_dir: Optional[Path] = None, session: Optional[str] = None) -> dict[str, float]:
    """`{measurement title: ms}` for the drivers actually MOVED, worst case empty.

    Zeros are excluded here because this feeds the pickers and the label, where "+0.000 ms" beside
    a title says nothing — `references()` is where a deliberate zero surfaces. Never raises: a
    hand-edited file is "nothing banked yet", not a dead curve window.
    """
    return {
        title: entry["ms"] for title, entry in _entries(tcc_dir, session).items() if entry["ms"]
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


def allpasses(tcc_dir: Optional[Path] = None, session: Optional[str] = None) -> dict[str, Allpass]:
    """`{measurement title: Allpass}` for the drivers that carry one."""
    return {
        title: entry["apf"] for title, entry in _entries(tcc_dir, session).items()
        if entry["apf"] is not None
    }


def seen(tcc_dir: Optional[Path] = None, session: Optional[str] = None) -> set:
    """Every driver this series has an opinion about, at zero or otherwise."""
    return set(_entries(tcc_dir, session))


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
    tcc_dir = tcc_dir or config.tcc_dir()
    entries = _entries(tcc_dir)
    title = str(title)
    was = entries.get(title) or {}
    at = arrival_ms if arrival_ms is not None else was.get("at")
    apf = was.get("apf") if allpass is _KEEP else allpass
    if apf is not None and not isinstance(apf, Allpass):
        raise TypeError(f"allpass must be an Allpass or None, got {apf!r}")
    entries[title] = {
        "ms": round(float(ms), 4),
        "at": None if at is None else round(float(at), 4),
        "set": session if session is not None else was.get("set"),
        "apf": apf,
    }
    project_settings.set_value(tcc_dir, KEY, _serialised(entries) or None)
    return {name: entry["ms"] for name, entry in entries.items() if entry["ms"]}


def _serialised(entries: dict[str, dict]) -> dict[str, dict]:
    """The store's own shape: the all-pass as the ledger's band object, or the key absent."""
    out: dict[str, dict] = {}
    for title, entry in entries.items():
        row = {"ms": entry["ms"], "at": entry["at"], "set": entry["set"]}
        if entry.get("apf") is not None:
            row["apf"] = entry["apf"].as_dict()
        out[title] = row
    return out


def clear(tcc_dir: Optional[Path] = None, session: Optional[str] = None) -> None:
    """Forget one capture series' readings, or all of them when no series is named.

    Scoped, because the button sits under a window showing one series and a button that also wiped
    last week's would be doing something nobody asked for.
    """
    tcc_dir = tcc_dir or config.tcc_dir()
    if session is None:
        project_settings.set_value(tcc_dir, KEY, None)
        return
    keep = {
        title: entry for title, entry in _entries(tcc_dir).items()
        if entry["set"] is not None and entry["set"] != session
    }
    project_settings.set_value(tcc_dir, KEY, _serialised(keep) or None)


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
