"""One channel's EQ against the same channel in a compared version, band by band (tcc#54,
finding 73): which band is new, which changed and in what, which is gone.

Which band is "the same band" in two versions is the whole question. The DSP's own band number
`i` answers it where both versions carry it on every band. Five presets of six do not (finding 72),
and there the ledger's order is not the DSP's either: the Arbiter's first look (2026-09-26) had
4800 Hz second in one version and seventh in the other, and matched by order an identical band
read as changed. So without the numbers a band is matched by what it is, whatever its place:
first a band identical in every field, then one at the same frequency (its values changed), then
the nearest of the same type within a third of an octave (its frequency moved). What is left is
new on one side and removed on the other.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from autosound_tcc.state.dsp_state import EqBand


@dataclass(frozen=True)
class BandDiff:
    """One band on its own side. `status`: "same" · "chg" · "new" (current side only) ·
    "removed" (compared side only). `other` is the matched band on the other side; `fields` names
    what moved: freq · gain · q · type · bypass."""

    band: EqBand
    status: str
    other: Optional[EqBand] = None
    fields: frozenset = field(default_factory=frozenset)


def _moved(now: EqBand, was: EqBand) -> frozenset:
    pairs = {"type": (_kind(now), _kind(was)),
             "freq": (now.freq_hz, was.freq_hz), "gain": (now.gain_db, was.gain_db),
             "q": (now.q, was.q), "bypass": (bool(now.bypass), bool(was.bypass))}
    return frozenset(name for name, (a, b) in pairs.items() if a != b)


def _numbered(bands: Sequence[EqBand]) -> bool:
    numbers = [b.index for b in bands]
    return None not in numbers and len(set(numbers)) == len(numbers)


#: How far a band's frequency may move and still be the same band: a third of an octave.
_MOVE_OCTAVES = 1 / 3


def _kind(band: EqBand) -> str:
    return (band.type or "").upper()


def _by_content(current: Sequence[EqBand], compared: Sequence[EqBand]) -> list[tuple[int, int]]:
    free_now, free_was = set(range(len(current))), set(range(len(compared)))
    pairs = []

    def take(same) -> None:
        for n in sorted(free_now):
            w = next((w for w in sorted(free_was) if same(current[n], compared[w])), None)
            if w is not None:
                pairs.append((n, w))
                free_now.discard(n)
                free_was.discard(w)

    take(lambda a, b: not _moved(a, b))
    take(lambda a, b: a.freq_hz == b.freq_hz)
    near = sorted((abs(math.log2(current[n].freq_hz / compared[w].freq_hz)), n, w)
                  for n in free_now for w in free_was
                  if _kind(current[n]) == _kind(compared[w])
                  and current[n].freq_hz > 0 and compared[w].freq_hz > 0)
    for distance, n, w in near:
        if distance <= _MOVE_OCTAVES and n in free_now and w in free_was:
            pairs.append((n, w))
            free_now.discard(n)
            free_was.discard(w)
    return pairs


def _pairs(current: Sequence[EqBand], compared: Sequence[EqBand]) -> list[tuple[int, int]]:
    """`(current position, compared position)` of every matched band."""
    if current and compared and _numbered(current) and _numbered(compared):
        where = {b.index: k for k, b in enumerate(compared)}
        return [(k, where[b.index]) for k, b in enumerate(current) if b.index in where]
    return _by_content(current, compared)


def compare_bands(current: Sequence[EqBand],
                  compared: Sequence[EqBand]) -> tuple[list[BandDiff], list[BandDiff]]:
    """`(current side, compared side)`, each in the order it was given."""
    pairs = _pairs(current, compared)
    now_to_was = dict(pairs)
    was_to_now = {w: n for n, w in pairs}

    def side(bands, partners, other_bands, alone):
        out = []
        for k, band in enumerate(bands):
            if k not in partners:
                out.append(BandDiff(band, alone))
                continue
            other = other_bands[partners[k]]
            moved = _moved(band, other)
            out.append(BandDiff(band, "chg" if moved else "same", other, moved))
        return out

    return (side(current, now_to_was, compared, "new"),
            side(compared, was_to_now, current, "removed"))
