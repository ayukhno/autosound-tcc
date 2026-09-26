"""One channel's EQ against the same channel in a compared version, band by band (tcc#54,
finding 73): which band is new, which changed and in what, which is gone.

Which band is "the same band" in two versions is the whole question. The DSP's own band number
`i` answers it where both versions carry it on every band. Five presets of six do not (finding 72),
and a position in the list is not the DSP's band, since empty slots are not recorded — so without
the numbers the bands are aligned by order and (type, frequency): a band put in the middle is new,
and the ones after it do not all read as changed. A band whose frequency moved in its place pairs
with the one it replaced, as a change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
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
    pairs = {"type": ((now.type or "").upper(), (was.type or "").upper()),
             "freq": (now.freq_hz, was.freq_hz), "gain": (now.gain_db, was.gain_db),
             "q": (now.q, was.q), "bypass": (bool(now.bypass), bool(was.bypass))}
    return frozenset(name for name, (a, b) in pairs.items() if a != b)


def _numbered(bands: Sequence[EqBand]) -> bool:
    numbers = [b.index for b in bands]
    return None not in numbers and len(set(numbers)) == len(numbers)


def _pairs(current: Sequence[EqBand], compared: Sequence[EqBand]) -> list[tuple[int, int]]:
    """`(current position, compared position)` of every matched band."""
    if current and compared and _numbered(current) and _numbered(compared):
        where = {b.index: k for k, b in enumerate(compared)}
        return [(k, where[b.index]) for k, b in enumerate(current) if b.index in where]
    key = lambda b: ((b.type or "").upper(), b.freq_hz)  # noqa: E731
    matcher = SequenceMatcher(None, [key(b) for b in compared], [key(b) for b in current],
                              autojunk=False)
    pairs = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "replace"):
            pairs.extend((j1 + k, i1 + k) for k in range(min(i2 - i1, j2 - j1)))
    return pairs


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
