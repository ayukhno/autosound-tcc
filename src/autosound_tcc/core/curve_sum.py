"""What N measured drivers will do together, worked out from the curves already on disk.

A crossover joint is settled by SUMMATION, not by either driver's own curve — the skill's own
timing policy says so for the case where the impulse cannot be trusted at all ("don't pin the sub's
timing on the raw IR onset; read the sub↔midbass alignment from summation", `rew-api-quirks.md`).
Until now the only way to see a sum was to type a delay into the DSP, re-run the sweep and look:
minutes per guess, with a microphone on a stand in somebody's car. This module does the arithmetic
instead, so a guess costs nothing and only the accepted one is typed in.

**The precondition, and it is most of the reason this file is careful.** A complex sum is
meaningful only when every input was captured against ONE timing reference. With a floating
per-measurement reference `startTime` jumps by ~5 ms between adjacent captures, the relative phase
between two of them is arbitrary, and the sum still draws — it is just fiction, and a confident
fiction is the exact failure this project exists to avoid.

Half of that is checkable and half is not, and the split is the design here:

*Checkable, and enforced.* The method already writes the rule down. `phase_1_foundation.md` says a
round is captured with "a shared Time Offset ≈ the physical arrival of the reference speaker,
applied to all sweeps", and `naming-and-structure.md` §3 puts the evidence in the title: `_N` is the
DSP config version the capture was taken under, and the method suffix says `(sw)` sweep or `(rta)`
MMM. So all-`(sw)` at one shared `_N` means one round, one Time Offset, one DSP config. A MIXED `_N`
is not a timing quibble — a bumped version means the DSP config changed between those captures, so
the drivers being added together were not the ones that play together now. That is summing two
different cars, and it is said as loudly as a missing phase rather than footnoted.

*Not checkable, and stated instead.* Whether the operator actually set the offset that day. A shared
reference produces DIFFERENT `startTime`s per channel too — that difference IS the acoustic arrival,
which is the thing being measured. The same spread means "correct" under one rig and "meaningless"
under another (`rew-api-quirks.md`, Timing: it "cannot be settled from the numbers alone"). So the
timing facts the caller has are reported verbatim, the assumption is printed with every result, and
the verdict stays with the person who set the rig up. A check here that guessed would be the one
nobody re-checks.

**No title parsing here.** The grammar belongs to the skill, which owns it and changes it; TCC
reaches `parse_name` through `vendor_loader`. This module holds the RULE and the verdict, the caller
supplies the facts — so the rule is what a test pins and what a reviewer argues with.

Qt-free and numpy-only on purpose: the window draws the result and the MCP server puts it in a
sentence, and neither should be the only way to compute it. Note that `numpy` reaches this project
as a `gui` extra (it arrives with pyqtgraph), so this module must not be imported from any of the
CLI modules `tests/test_packaging.py` guards, or the light install stops importing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from autosound_tcc.core.allpass import Allpass


class CurveSumError(ValueError):
    """A sum that must not be drawn, with the reason in words the window can show.

    Subclasses `ValueError` so a caller that already funnels bad data through one `except` keeps
    working; raised rather than returned because there is no partial answer to hand back — a curve
    that is missing one driver is a different curve, not a worse one.
    """


#: All inputs are sweeps from one DSP config version: the footing the method itself prescribes.
SUMMABLE = "summable"
#: More than one `_N` in the set. Computed if the caller insists, labelled as two different cars.
MIXED_CONFIG = "mixed_config"
#: At least one input whose config version nobody could supply. Not a match, and not a mismatch.
UNKNOWN_CONFIG = "unknown_config"
#: Cannot be summed at all: an MMM/RTA capture, a curve with no phase, or nothing selected.
REFUSED = "refused"

#: Printed verbatim by the window and by anything that hands this sum to a model.
#:
#: English, and deliberately not run through `i18n`: this sentence goes into a prompt at least as
#: often as onto a screen, and the language TCC speaks to a model in is an open decision that should
#: be made once for everything rather than settled here by accident.
TIMING_ASSUMPTION = (
    "ASSUMED, NOT CHECKED: every measurement in this sum was captured against one shared timing "
    "reference (a loopback, or a fixed Time Offset applied to all sweeps in the round). If the "
    "reference floated between captures, the relative phase between them is arbitrary and this "
    "sum is meaningless. No measured number can tell the two cases apart."
)


@dataclass(frozen=True, eq=False)
class SumInput:
    """One measured driver as REW hands it over, plus what the tuner is proposing to do to it.

    `phase_deg` is WRAPPED — `get_fr` returns it that way — and `None` for a capture that has none.
    `delay_ms`, `gain_db`, `invert` and `allpass` are the PROPOSAL: applied to the measured curve
    here instead of being typed into the DSP and re-measured, which is the whole point. The
    all-pass is the one of the four that is not arithmetic on the numbers already in hand — it is
    a filter, and the filter is the skill's (`core/allpass.py`, SCR-050): unit magnitude, so it
    moves nothing on a magnitude plot and everything on the sum.

    `config_version` and `method` are what the caller parsed off the title (`_N` and `sw`/`rta`,
    `naming-and-structure.md` §3). Both optional, because a REW list also holds imports, room-sim
    results and hand-named curves — the skill's own parser returns `None` for those rather than
    erroring, and a curve that is not named to the convention is still a curve somebody may want to
    look at. `start_time_s` is REW's `startTime`/`delay` for this capture, carried through and
    reported; see the module docstring for why it is never judged.

    `eq=False` because dataclass equality over numpy arrays raises instead of answering, and
    identity is the only comparison that means anything for a bundle of measured data.
    """

    name: str
    freqs_hz: np.ndarray
    magnitude_db: np.ndarray
    phase_deg: Optional[np.ndarray]
    delay_ms: float = 0.0
    invert: bool = False
    gain_db: float = 0.0
    start_time_s: Optional[float] = None
    config_version: Optional[str] = None
    method: Optional[str] = None
    allpass: Optional[Allpass] = None


@dataclass(frozen=True, eq=False)
class Summability:
    """Whether this set is one round of one car — the half of the precondition that IS checkable.

    Separate from the sum itself so a window can ask before it computes (grey out the button, show
    the reason) and so the same sentence reaches a model unchanged. `status` is one of the four
    constants above; `text` is that status in words, already naming the measurements and versions
    involved, because a verdict a reader has to reconstruct is a verdict they skip.
    """

    status: str
    config_version: Optional[str]
    versions: tuple[str, ...]
    text: str

    @property
    def ok(self) -> bool:
        """One round, all sweeps. Anything else is drawn with a label or not at all."""
        return self.status == SUMMABLE

    @property
    def refused(self) -> bool:
        return self.status == REFUSED


@dataclass(frozen=True, eq=False)
class Contribution:
    """One input as it entered the sum: on the result grid, with delay, gain and polarity applied.

    This is what the window draws under the sum — each driver AT THE PROPOSED SETTING, not as
    measured. Drawing the measured curve instead would put the trim and the polarity into the sum
    and nowhere else, and the eye would read that difference as interference.
    """

    name: str
    magnitude_db: np.ndarray
    #: Unwrapped and continuous, in degrees. A phase plot of a joint is read for slope, and a
    #: re-wrapped curve hides the slope behind the jumps.
    phase_deg: np.ndarray
    #: The complex term actually added. Kept so a caller can re-sum a subset without re-fetching.
    response: np.ndarray
    delay_ms: float
    invert: bool
    gain_db: float
    start_time_s: Optional[float]
    #: The input's OWN measured span, before the grid was chosen. What the sum had to work with.
    measured_hz: tuple[float, float]
    #: The all-pass this driver entered the sum through, or None. Carried so the sentence can name
    #: it beside the delay it was dialled with — a rotation with no filter named is a picture
    #: nobody can re-enter.
    allpass: Optional[Allpass] = None


@dataclass(frozen=True, eq=False)
class SumResult:
    """The predicted sum, everything needed to draw it, and everything needed to doubt it."""

    freqs_hz: np.ndarray
    #: The summed level. An exact null is `-inf` and stays `-inf`: this module will not invent a
    #: floor, because the floor a caller picks is a drawing decision and belongs where the drawing
    #: happens. Real captures never cancel bit-for-bit; synthetic ones do.
    magnitude_db: np.ndarray
    #: Unwrapped phase of the SUM, in degrees.
    phase_deg: np.ndarray
    response: np.ndarray
    contributions: tuple[Contribution, ...]
    #: The span where every input actually had data. Narrower than `freqs_hz` only when the caller
    #: supplied its own grid; outside it the sum is NaN rather than a guess.
    covered_hz: tuple[float, float]
    summability: Summability
    assumption: str = TIMING_ASSUMPTION

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.contributions)

    @property
    def start_times_s(self) -> dict[str, Optional[float]]:
        """`{name: REW startTime}` exactly as supplied, `None` where the caller had none."""
        return {c.name: c.start_time_s for c in self.contributions}

    def deepest_null(self) -> tuple[float, float]:
        """`(frequency, dB relative to the loudest single driver there)` at the worst cancellation.

        Relative to the loudest contribution and not to an absolute level, because that is the
        reading a joint is judged by: −20 dB says the pair is destroying the driver that was
        carrying the band, whatever SPL the sweep happened to be run at. A perfectly coherent pair
        comes out at +6.02 dB by the same measure, which is the honest answer to "how deep is the
        null" when there is not one.
        """
        loudest = np.max(np.abs(np.array([c.response for c in self.contributions])), axis=0)
        with np.errstate(divide="ignore"):
            relative = self.magnitude_db - 20.0 * np.log10(loudest)
        if not np.any(np.isfinite(relative) | np.isneginf(relative)):
            return (float("nan"), float("nan"))
        # `nanargmin` and not `argmin`: an out-of-range point on a caller-supplied grid is NaN, and
        # NaN would otherwise win the comparison and report a null where there is no data at all.
        worst = int(np.nanargmin(np.where(np.isnan(relative), np.inf, relative)))
        return (float(self.freqs_hz[worst]), float(relative[worst]))

    def as_sentence(self) -> str:
        """The whole prediction as something a model can read and a person can check before sending.

        Same shape as `delay_bank.as_sentence`: the evidence, then what it does and does not show.
        English for the reason given at `TIMING_ASSUMPTION`.
        """
        lines = [
            f"Predicted acoustic sum of {len(self.contributions)} measurement(s), "
            f"{self.freqs_hz[0]:.1f}–{self.freqs_hz[-1]:.1f} Hz, {self.freqs_hz.size} points.",
        ]
        for c in self.contributions:
            parts = [f"{c.delay_ms:+.3f} ms", f"{c.gain_db:+.2f} dB"]
            if c.invert:
                parts.append("POLARITY INVERTED")
            if c.allpass is not None:
                # In the ledger's own vocabulary (`APF2 250 Hz Q 0.71`), so what the model reads
                # here is what it would propose there.
                parts.append(c.allpass.label())
            lines.append(f"  {c.name}: " + ", ".join(parts))

        where_hz, depth_db = self.deepest_null()
        if np.isfinite(where_hz):
            lines.append(
                f"Worst cancellation: {depth_db:+.1f} dB relative to the loudest single driver "
                f"there, at {where_hz:.0f} Hz."
            )
        if (self.covered_hz[0], self.covered_hz[1]) != (
            float(self.freqs_hz[0]), float(self.freqs_hz[-1])
        ):
            lines.append(
                f"Only {self.covered_hz[0]:.1f}–{self.covered_hz[1]:.1f} Hz is covered by every "
                "measurement; outside that the sum is undefined, not flat."
            )

        known = {n: t for n, t in self.start_times_s.items() if t is not None}
        if known:
            lines.append(
                "REW timing reference per capture (startTime, s): "
                + "; ".join(f"{name} {value:.6f}" for name, value in known.items())
            )
        else:
            lines.append(
                "No REW timing reference was supplied with these measurements, so not even the "
                "raw startTimes are available to check the assumption below against."
            )
        return "\n".join([*lines, self.summability.text, self.assumption])


def summability(inputs: Sequence[SumInput]) -> Summability:
    """Can these be summed, and on what footing — from the facts the caller parsed off the titles.

    Public and side-effect free so a window can ask before it computes. `sum_responses` calls it
    first and raises on `REFUSED`, which keeps one rule in one place: two implementations of "may
    these be added together" would eventually disagree, and the disagreement would surface as a
    curve that one half of the app is willing to draw.
    """
    if not inputs:
        return Summability(REFUSED, None, (), "Nothing to sum: no measurements were given.")

    voiceless = [inp.name for inp in inputs if not _carries_phase(inp)]
    if voiceless:
        return Summability(
            REFUSED, None, (),
            "Cannot be summed: " + ", ".join(voiceless) + " — an MMM/RTA capture carries a "
            "magnitude and nothing else (REW returns no phase for one), and a magnitude has "
            "nothing to interfere with. Sum acoustic sweeps ((sw)) only.",
        )

    seen = [_version_key(inp.config_version) for inp in inputs]
    known = sorted({v for v in seen if v is not None}, key=_version_order)
    unnamed = [inp.name for inp, v in zip(inputs, seen) if v is None]

    if len(known) > 1:
        # Louder than "unknown" even when both apply: a version that changed is positive evidence
        # that the DSP config changed under these captures, which is a different claim from not
        # knowing.
        return Summability(
            MIXED_CONFIG, None, tuple(known),
            "These measurements come from DIFFERENT DSP config versions (" + ", ".join(known)
            + "). A bumped version means the DSP configuration changed between the captures, so "
            "these drivers never played together at any one setting — this is not one car summed, "
            "and the result below is a comparison, not a prediction.",
        )
    if unnamed:
        return Summability(
            UNKNOWN_CONFIG, known[0] if known else None, tuple(known),
            "The DSP config version is unknown for " + ", ".join(unnamed) + ", so this set cannot "
            "be shown to be one capture round. If it is not, the drivers were measured under "
            "different DSP configurations and the sum below is not a prediction about this car.",
        )
    return Summability(
        SUMMABLE, known[0], tuple(known),
        f"All {len(inputs)} measurements are sweeps from DSP config version {known[0]}, so by the "
        "method they are one capture round under one shared Time Offset — the footing a complex "
        "sum needs. What that does not show is whether the offset was actually set on the day.",
    )


def common_grid(inputs: Sequence[SumInput]) -> np.ndarray:
    """The frequencies a sum of these inputs can honestly be stated on.

    The intersection of their ranges, sampled logarithmically, at no more points than the COARSEST
    input carries over that span. Not the union: outside the overlap one driver has no data, and a
    sum of one driver is not a sum. Not finer than the coarsest: the extra points would be the
    interpolator's opinion, drawn at the same weight as measured data, and a null read off one of
    them would be read off nothing.
    """
    return _grid([_prepare(inp) for inp in inputs])


def sum_responses(
    inputs: Sequence[SumInput], *, grid: Optional[np.ndarray] = None
) -> SumResult:
    """Predict the acoustic sum of `inputs`, on `grid` or on the one `common_grid` picks.

    Per input, `H_i(f) = 10**((mag_i + gain_i)/20) * exp(1j*(phi_i − 2πf·delay_i))`, negated when
    `invert` and multiplied by the all-pass when one is proposed; the answer is `|Σ H_i|` back in
    dB. Raises `CurveSumError` — never returns a partial curve — when the set cannot be summed at
    all: no phase, no shared frequencies, an empty selection, an all-pass with no skill to compute
    it. A set that CAN be summed but is not one round is computed and labelled; see
    `SumResult.summability`.
    """
    verdict = summability(inputs)
    if verdict.refused:
        raise CurveSumError(verdict.text)

    prepared = [_prepare(inp) for inp in inputs]
    freqs = _grid(prepared) if grid is None else _check_grid(grid)
    log_freqs = np.log10(freqs)

    contributions: list[Contribution] = []
    for p in prepared:
        # Magnitude against log(f), phase against f, and the split is deliberate. A driver's
        # magnitude is smooth per OCTAVE — slopes are dB/octave, corners are ratios — while phase
        # under a delay is exactly linear in f (φ = −2πfτ). Interpolating each where it is nearly
        # straight keeps a pure delay a pure delay and a 12 dB/octave slope a 12 dB/octave slope.
        # One domain for both would have to be wrong about one of them, and it would be wrong about
        # the one this feature exists for.
        magnitude = np.interp(log_freqs, p.log_freqs, p.magnitude_db, left=np.nan, right=np.nan)
        magnitude = magnitude + p.inp.gain_db
        phase = np.interp(freqs, p.freqs, p.phase_rad, left=np.nan, right=np.nan)
        phase = phase - 2.0 * np.pi * freqs * (p.inp.delay_ms / 1000.0)

        response = np.power(10.0, magnitude / 20.0) * np.exp(1j * phase)
        if p.inp.invert:
            response = -response
            phase = phase + np.pi  # the reported curve only; −H and a 180° shift are one thing
        if p.inp.allpass is not None:
            # On the RESULT grid, not on the input's own and then resampled: the filter is a
            # closed form and can be stated exactly wherever the sum is stated, while a resampled
            # rotation would be one more interpolation between two samples of a curve that turns
            # fast near f0. Its phase goes into the reported curve the same way the delay ramp
            # did — continuous, so the slope a joint is read for survives — and the magnitude is
            # untouched by construction, which is what makes it an all-pass.
            try:
                rotation = p.inp.allpass.response(freqs)
            except Exception as exc:  # noqa: BLE001 — no skill, or one without the function
                raise CurveSumError(
                    f"{p.inp.name}: cannot apply {p.inp.allpass.label()} — the skill's filter "
                    f"maths could not be loaded ({exc}). Sum without it, or install the skill."
                ) from exc
            response = response * rotation
            phase = phase + np.unwrap(np.angle(rotation))
        contributions.append(
            Contribution(
                name=p.inp.name,
                magnitude_db=magnitude,
                phase_deg=np.degrees(phase),
                response=response,
                delay_ms=float(p.inp.delay_ms),
                invert=bool(p.inp.invert),
                gain_db=float(p.inp.gain_db),
                start_time_s=p.inp.start_time_s,
                measured_hz=(float(p.freqs[0]), float(p.freqs[-1])),
                allpass=p.inp.allpass,
            )
        )

    total = np.sum([c.response for c in contributions], axis=0)
    covered = np.all(np.isfinite([c.response for c in contributions]), axis=0)
    if not covered.any():
        raise CurveSumError(
            "no frequency on this grid is covered by every measurement, so there is nothing to "
            "sum: " + _spans(prepared)
        )
    with np.errstate(divide="ignore"):
        magnitude_db = 20.0 * np.log10(np.abs(total))
    return SumResult(
        freqs_hz=freqs,
        magnitude_db=magnitude_db,
        phase_deg=np.degrees(_unwrap_gaps(np.angle(total))),
        response=total,
        contributions=tuple(contributions),
        covered_hz=(float(freqs[covered][0]), float(freqs[covered][-1])),
        summability=verdict,
    )


# ---- the parts nobody outside this module should need -------------------------------------------


@dataclass(frozen=True, eq=False)
class _Prepared:
    """One input reduced to what the sum needs: sorted, finite, and unwrapped ONCE."""

    inp: SumInput
    freqs: np.ndarray
    log_freqs: np.ndarray
    magnitude_db: np.ndarray
    phase_rad: np.ndarray


def _carries_phase(inp: SumInput) -> bool:
    """Does this measurement have a phase at all — by its own label, then by its numbers.

    The method suffix is checked first and is allowed to refuse on its own. A curve titled `(rta)`
    that somehow arrives carrying phase is a derived or imported trace wearing an MMM's name, and
    trusting the array over the title would sum something nobody captured.
    """
    if str(inp.method or "").strip().lower() == "rta":
        return False
    if inp.phase_deg is None:
        return False
    return bool(np.isfinite(np.asarray(inp.phase_deg, dtype=float)).any())


def _version_key(value) -> Optional[str]:
    """`2`, `"2"`, `"02"` and `"v_02"` are one config version, not four.

    REW titles are hand-typed and zero-padding is common — `measurement_view` keys its parsed
    titles this way for exactly that reason. A sum that read `_02` and `_2` as two configs would
    refuse a perfectly good round and send somebody re-measuring for nothing.
    """
    if value is None:
        return None
    text = str(value).strip().lstrip("vV").lstrip("_")
    if not text:
        return None
    try:
        return str(int(text))
    except ValueError:
        return text


def _version_order(value: str) -> tuple[int, int, str]:
    """Numeric versions in numeric order, anything else after them, so `10` follows `9`."""
    return (0, int(value), "") if value.isdigit() else (1, 0, value)


def _prepare(inp: SumInput) -> _Prepared:
    freqs = np.asarray(inp.freqs_hz, dtype=float).ravel()
    magnitude = np.asarray(inp.magnitude_db, dtype=float).ravel()
    if inp.phase_deg is None:
        raise CurveSumError(f"{inp.name}: no phase, so it cannot be summed.")
    phase = np.asarray(inp.phase_deg, dtype=float).ravel()
    if not (freqs.size == magnitude.size == phase.size):
        raise CurveSumError(
            f"{inp.name}: {freqs.size} frequencies, {magnitude.size} magnitudes and {phase.size} "
            "phase points — three arrays that came from one measurement and no longer agree."
        )

    # Drop the dead samples BEFORE unwrapping, not after. `np.unwrap` carries a NaN forward through
    # everything above it, so one bad bin at 200 Hz would turn the rest of the driver into a column
    # of NaN and take the whole sum with it. This costs the resolution of exactly those bins.
    usable = np.isfinite(freqs) & np.isfinite(magnitude) & np.isfinite(phase) & (freqs > 0.0)
    if np.count_nonzero(usable) < 2:
        raise CurveSumError(
            f"{inp.name}: fewer than two usable points (a positive frequency with a finite "
            "magnitude and phase), so there is no curve here to sum."
        )
    freqs, magnitude, phase = freqs[usable], magnitude[usable], phase[usable]

    # REW returns ascending frequencies, and this sort is insurance rather than doubt: `np.interp`
    # does not check that `xp` ascends. It returns a plausible-looking wrong curve instead of
    # raising, which is precisely the failure mode this module may not have.
    order = np.argsort(freqs, kind="stable")
    freqs, magnitude, phase = freqs[order], magnitude[order], phase[order]

    return _Prepared(
        inp=inp,
        freqs=freqs,
        log_freqs=np.log10(freqs),
        magnitude_db=magnitude,
        # Unwrapped here, once, and never re-wrapped. Interpolating REW's wrapped degrees across a
        # ±180° step invents a curve that is not in the measurement — it does not go wrong AT the
        # wrap, it goes wrong between the two samples either side of it, which is why the mistake
        # looks like data.
        #
        # Not real/imaginary interpolation either, though it avoids the wrap just as well (the
        # skill's own `dsp_math.complex_interp` takes that route). Between two adjacent points a
        # delay-dominated response rotates a long way — at 20 kHz on a log grid with ~20 Hz
        # spacing, 5 ms of delay turns ~36° from one sample to the next. Interpolating the real and
        # imaginary parts cuts the CHORD across that arc, shortening the vector and inventing a
        # magnitude dip of about 5% that no microphone recorded. Unwrapping walks the arc. This
        # feature has to be trusted at the exact moment a tuner is dragging milliseconds around,
        # so the arc is the one that matters.
        #
        # The limit, since unwrap has one and it is silent: it can only recover a rotation the
        # sample spacing supports (under half a turn between adjacent points). A sparse export
        # carrying several ms of bulk delay wraps faster than that and comes back aliased, looking
        # like a curve. There is no detector for it here on purpose — the obvious one, "flag a
        # per-sample step near 180°", fires on healthy data every time, because the phase across a
        # genuine deep notch really does swing that far in one bin.
        phase_rad=np.unwrap(np.deg2rad(phase)),
    )


def _grid(prepared: Sequence[_Prepared]) -> np.ndarray:
    if not prepared:
        raise CurveSumError("Nothing to sum: no measurements were given.")
    low = max(float(p.freqs[0]) for p in prepared)
    high = min(float(p.freqs[-1]) for p in prepared)
    if not high > low:
        raise CurveSumError(
            "these measurements share no frequency range, so there is nothing to sum: "
            + _spans(prepared)
        )

    octaves = float(np.log2(high / low))
    # Points per octave, measured on each input's own samples inside the overlap — intervals, not
    # points, so two inputs that end up on the same grid stay on it exactly rather than drifting by
    # one sample. The coarsest wins: this is the line between resampling data and manufacturing it.
    per_octave = min(
        max(int(np.count_nonzero((p.freqs >= low) & (p.freqs <= high))) - 1, 1) / octaves
        for p in prepared
    )
    return np.geomspace(low, high, max(2, int(round(per_octave * octaves)) + 1))


def _check_grid(grid) -> np.ndarray:
    """A caller-supplied grid, refused rather than silently repaired.

    The window may well want a fixed 20 Hz–20 kHz axis so two sums can be laid over each other, and
    that is a legitimate reason to override. What it may not do is hand over something the maths
    cannot stand on — a non-positive frequency has no logarithm, and an out-of-order one turns
    `np.interp` into a random-number generator.
    """
    freqs = np.asarray(grid, dtype=float).ravel()
    if freqs.size == 0:
        raise CurveSumError("the grid supplied is empty, so there is nothing to compute on.")
    if not np.all(np.isfinite(freqs)) or np.any(freqs <= 0.0):
        raise CurveSumError(
            "the grid supplied contains a non-finite or non-positive frequency; a sum is stated on "
            "a logarithmic axis and there is no such point on one."
        )
    if freqs.size > 1 and np.any(np.diff(freqs) <= 0.0):
        raise CurveSumError("the grid supplied must ascend, with no repeated frequencies.")
    return freqs


def _unwrap_gaps(angles: np.ndarray) -> np.ndarray:
    """Unwrap across the samples that exist, leaving the ones that do not as NaN.

    A caller-supplied grid can reach past where the measurements stop, and `np.unwrap` would carry
    the first NaN through the rest. The join across a gap is not meaningful, but nothing is
    meaningful there — that stretch has no data by construction.
    """
    out = np.full(angles.shape, np.nan)
    good = np.isfinite(angles)
    if good.any():
        out[good] = np.unwrap(angles[good])
    return out


def _spans(prepared: Sequence[_Prepared]) -> str:
    """Each input's measured range: an error about ranges has to name them to be actionable."""
    return ", ".join(f"{p.inp.name} {p.freqs[0]:g}–{p.freqs[-1]:g} Hz" for p in prepared)
