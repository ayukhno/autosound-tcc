"""An all-pass the tuner is proposing for one driver — the parameters, and the skill's own filter.

An all-pass changes nothing about a driver's level and everything about where its phase sits, which
is why the method aligns a crossover joint with one rather than by shifting raw delay: a delay moves
every arrival of the driver, an all-pass rotates the band around `f0` and leaves the rest alone
(`phase_2_eq.md` §"align joints with APF rather than raw delay"). Until now the only way to see what
one would do was to type it into the DSP, re-sweep, and look. The curve window applies it to the
measured trace instead, and draws the predicted sum with it in.

**The maths is not here.** `response()` calls the skill's `dsp_math.apf1_response` /
`apf2_response` through `vendor_loader`, and there is no fallback copy: two implementations of one
filter is how the front-end and the method start disagreeing about what a proposal means, and the
number that leaves this window is going to be typed into a processor (SCR-050, and
`CURVE-ANALYSIS-PLAN.md` step 4). What this module owns is the PARAMETER SET — validated once, named
the way the ledger names it (`APF1`/`APF2` are `state.EQ_TYPES`), and printed the same way in the
legend, the reading and the sum's sentence.

**Scope, decided by the user (2026-08-18): `APF1` and `APF2` only.** The Helix "Phase" control is
a second-order all-pass whose frequency the processor takes from that channel's crossover, so the
user sets an ANGLE there and not an `f0`, and it exists on that vendor. An `APF1`/`APF2` in an EQ
slot is `f0` (+ `Q` for the second order), typed in, and every processor with a PEQ bank can take
one. Nothing here simulates a Helix phase angle, and `phase_deg` in the ledger stays a field the
skill records when a Helix user sets it by hand.

Qt-free, and light: numpy is imported only inside `response()`, so the parameter set can be read,
validated, labelled and banked by the light install (`delay_bank` keeps it beside the delay), while
the filter itself is asked for only where the GUI extra — and the skill — are present.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

#: The two kinds, spelled as the ledger spells them (`state.EQ_TYPES`) — and the only spellings
#: that appear anywhere in this window, so a model reading "APF2" here can propose "APF2" there.
APF1 = "APF1"
APF2 = "APF2"
KINDS = (APF1, APF2)

#: What the controls offer, and the fence `Allpass` refuses to step over. Not the hardware's own
#: limits — those come from the DSP profile when it states them, and TCC has not read them for an
#: EQ band yet — but the span inside which an all-pass on a car's crossover joint means anything: a
#: joint lives between the sub and the tweeter, and a Q past 10 turns the whole 360° inside a
#: sixth of an octave, which no measured pair of drivers holds still enough to use
#: (`dsp_math.ROBUST_PERT`, and the razor-optima lesson in `xover_select.repair_joint_apf`).
F0_RANGE_HZ = (10.0, 20000.0)
Q_RANGE = (0.1, 10.0)
#: What the second order opens on: a Butterworth-ish 0.71 turns its 360° over about an octave and
#: a half either side of `f0`, the gentlest rotation that still reads as a rotation on a plot.
DEFAULT_Q = 0.71


class AllpassError(ValueError):
    """A parameter set no all-pass can be built from, in words the window can show."""


@dataclass(frozen=True)
class Allpass:
    """One all-pass, as a proposal: which order, where, and (second order only) how sharp.

    `q` is `None` for the first order, which has no Q — a first-order all-pass is fully described
    by its `f0`, and carrying a Q it does not use would let two settings print differently while
    being one filter. Frozen, so a value banked or put in a sentence cannot drift after the fact.
    """

    order: int
    f0_hz: float
    q: Optional[float] = None

    def __post_init__(self) -> None:
        if self.order not in (1, 2):
            raise AllpassError(f"an all-pass is first or second order, not {self.order!r}")
        try:
            f0 = float(self.f0_hz)
        except (TypeError, ValueError):
            raise AllpassError(f"f0 must be a frequency in Hz, got {self.f0_hz!r}") from None
        if not math.isfinite(f0) or not (F0_RANGE_HZ[0] <= f0 <= F0_RANGE_HZ[1]):
            raise AllpassError(
                f"f0 = {self.f0_hz!r} Hz is outside {F0_RANGE_HZ[0]:g}–{F0_RANGE_HZ[1]:g} Hz"
            )
        object.__setattr__(self, "f0_hz", f0)
        if self.order == 1:
            if self.q is not None:
                raise AllpassError("a first-order all-pass has no Q; leave it None")
            return
        try:
            q = float(self.q)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise AllpassError(f"a second-order all-pass needs a Q, got {self.q!r}") from None
        if not math.isfinite(q) or not (Q_RANGE[0] <= q <= Q_RANGE[1]):
            raise AllpassError(f"Q = {self.q!r} is outside {Q_RANGE[0]:g}–{Q_RANGE[1]:g}")
        object.__setattr__(self, "q", q)

    @property
    def kind(self) -> str:
        """`APF1` or `APF2` — the ledger's own name for this band type."""
        return APF1 if self.order == 1 else APF2

    def label(self) -> str:
        """The filter in one breath, for a legend or a sentence: `APF2 250 Hz Q 0.71`.

        A dot for the decimal and no locale, like every other number this window prints — the same
        string goes into a prompt as onto the screen, and the two must not disagree.
        """
        f0 = f"{self.f0_hz:g}" if self.f0_hz == round(self.f0_hz) else f"{self.f0_hz:.1f}"
        if self.order == 1:
            return f"{self.kind} {f0} Hz"
        return f"{self.kind} {f0} Hz Q {self.q:.2f}"

    def as_dict(self) -> dict:
        """The band the way the ledger writes one: `{"type": "APF2", "f": 250.0, "q": 0.71}`.

        Same keys as a `state.EQ_TYPES` band object, so a model that reads this can propose it
        verbatim — but TCC never writes it anywhere the skill reads (D-6): it is what goes into
        the bank and the sentence, and nothing else.
        """
        out = {"type": self.kind, "f": float(self.f0_hz)}
        if self.order == 2:
            out["q"] = float(self.q)  # type: ignore[arg-type]
        return out

    @classmethod
    def from_dict(cls, raw) -> Optional["Allpass"]:
        """The inverse of `as_dict`, for a banked entry. `None` for anything that is not one.

        Lenient on purpose about what it is handed — a hand-edited settings file, an entry from a
        version that never had the field — and strict about what it returns: a value that came
        back is a valid `Allpass`, or nothing did.
        """
        if not isinstance(raw, dict):
            return None
        kind = str(raw.get("type") or "").strip().upper()
        if kind not in KINDS:
            return None
        try:
            if kind == APF1:
                return cls(1, raw.get("f"))
            return cls(2, raw.get("f"), raw.get("q"))
        except AllpassError:
            return None

    def response(self, freqs_hz):
        """The complex response on `freqs_hz` (a numpy array), from the skill's own `dsp_math` —
        never from here.

        Raises `vendor_loader.VendorNotInitializedError` when there is no skill to ask, and the
        caller says so rather than drawing nothing: a sum that quietly leaves the all-pass out is
        a sum of a different proposal.
        """
        import numpy as np

        from autosound_tcc.core import vendor_loader

        maths = vendor_loader.load_dsp_math()
        freqs = np.asarray(freqs_hz, dtype=float)
        if self.order == 1:
            return np.asarray(maths.apf1_response(freqs, self.f0_hz), dtype=complex)
        return np.asarray(maths.apf2_response(freqs, self.f0_hz, self.q), dtype=complex)

    def phase_deg(self, freqs_hz):
        """The rotation in degrees, unwrapped and continuous, on `freqs_hz` (ascending).

        Continuous rather than wrapped because the one place a phase plot is read for its SLOPE is
        the joint, and this is what gets added to a driver's phase there. Recovered with `unwrap`
        from the complex response rather than from a formula of our own — the formula is the
        skill's. The unwrap has one limit, under a half-turn per sample, and it holds with room to
        spare: a second-order all-pass turns at most 4·Q radians per unit of f/f0, which on REW's
        sweep grid (48 points per octave by default) is about 33° per sample at the Q 10 ceiling,
        and a 1/12-octave export still stays under 140°.
        """
        import numpy as np

        return np.degrees(np.unwrap(np.angle(self.response(freqs_hz))))
