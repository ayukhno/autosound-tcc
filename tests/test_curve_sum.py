"""The predicted sum, checked against physics rather than against its own last answer.

Every assertion here is a number that can be derived on paper: two identical drivers gain 6.02 dB,
a half-cycle delay cancels, an LR2 joint nulls in phase and goes flat with one driver inverted. A
snapshot test would pass just as happily on a sum computed in the wrong domain -- which is the one
failure this module exists to prevent, since a wrong sum still draws a plausible curve.

The analytic inputs are handed in the shape REW hands them over: magnitude in dB, phase in WRAPPED
degrees (`np.angle` wraps to (-180, 180] on its own). So the unwrap-before-interpolate path is
exercised by every test here, not only by the one named after it.
"""

from __future__ import annotations

import numpy as np
import pytest

from autosound_tcc.core import curve_sum

#: 20*log10(n) for n drivers adding coherently -- the numbers this whole module has to reproduce.
_PLUS_TWO = 20.0 * np.log10(2.0)
_PLUS_THREE = 20.0 * np.log10(3.0)
_PLUS_FOUR = 20.0 * np.log10(4.0)


def _flat(name: str, freqs, level_db: float = 90.0, **kwargs) -> curve_sum.SumInput:
    """A driver with no character at all: flat magnitude, zero phase. Every interference in a test
    built on these is the arithmetic under test and nothing else."""
    freqs = np.asarray(freqs, dtype=float)
    return curve_sum.SumInput(
        name=name,
        freqs_hz=freqs,
        magnitude_db=np.full(freqs.size, float(level_db)),
        phase_deg=np.zeros(freqs.size),
        **kwargs,
    )


def _measured(name: str, freqs, response, **kwargs) -> curve_sum.SumInput:
    """An analytic transfer function presented the way REW presents a real one.

    dB and wrapped degrees, so the test data goes through the same lossy round trip a measurement
    does -- if the module only worked on complex numbers it never had to reconstruct, that would
    not show up here.
    """
    freqs = np.asarray(freqs, dtype=float)
    response = np.asarray(response, dtype=complex)
    with np.errstate(divide="ignore"):
        magnitude_db = 20.0 * np.log10(np.abs(response))
    return curve_sum.SumInput(
        name=name,
        freqs_hz=freqs,
        magnitude_db=magnitude_db,
        phase_deg=np.degrees(np.angle(response)),
        **kwargs,
    )


def _lr2(freqs, corner_hz: float, kind: str) -> np.ndarray:
    """A Linkwitz-Riley 2nd-order leg: two cascaded Butterworth 1st-orders, `1/(s+1)^2`.

    LR2 is the crossover this test file leans on because its behaviour is a known FACT rather than
    a preference: in phase the two legs null completely at the corner, and with one leg inverted
    they sum to a flat magnitude. Any error in how phase is carried through the sum destroys both.
    """
    s = 1j * np.asarray(freqs, dtype=float) / float(corner_hz)
    denominator = (s + 1.0) ** 2
    return (s * s / denominator) if kind == "hp" else (1.0 / denominator)


# ---- the two-driver identities -----------------------------------------------------------------


def test_two_identical_measurements_in_phase_gain_six_db():
    grid = np.geomspace(20.0, 20000.0, 600)

    result = curve_sum.sum_responses([_flat("w-L_01 (sw)", grid), _flat("w-R_01 (sw)", grid)])

    assert np.allclose(result.magnitude_db, 90.0 + _PLUS_TWO, atol=1e-9)
    assert result.freqs_hz.size == 600


def test_the_same_pair_with_one_inverted_cancels_to_a_deep_null():
    """A deep null, not exactly zero. Two identical arrays DO cancel bit-for-bit here and the
    answer is -inf dB, but that is an artifact of synthetic data: no two microphone captures ever
    subtract to zero, so a test that demanded it would be testing floating point, not the sum."""
    grid = np.geomspace(20.0, 20000.0, 600)

    result = curve_sum.sum_responses(
        [_flat("w-L_01 (sw)", grid), _flat("w-R_01 (sw)", grid, invert=True)]
    )

    assert np.all(result.magnitude_db < -100.0)
    _, depth_db = result.deepest_null()
    assert depth_db < -100.0


def test_a_pure_delay_produces_the_textbook_comb():
    """Two identical drivers one delay apart give `|2A cos(pi f tau)|`.

    Read off that expression: a half cycle (f*tau = 0.5) cancels, a whole cycle adds 6.02 dB, and a
    third of a cycle leaves the pair at exactly ONE driver's level -- which is the reading that
    catches a sum computed with the delay in the wrong units, since 6 dB and -inf survive a factor
    of two in tau at some other frequency but the 0 dB point does not.
    """
    freqs = np.arange(20.0, 5001.0, 1.0)
    pair = [_flat("m-L_01 (sw)", freqs), _flat("m-R_01 (sw)", freqs, delay_ms=1.0)]

    nulls = curve_sum.sum_responses(pair, grid=np.array([500.0, 1500.0, 2500.0]))
    peaks = curve_sum.sum_responses(pair, grid=np.array([1000.0, 2000.0, 3000.0]))
    thirds = curve_sum.sum_responses(pair, grid=np.array([1000.0 / 3.0, 4000.0 / 3.0]))

    assert np.all(nulls.magnitude_db < -60.0)
    assert np.allclose(peaks.magnitude_db, 90.0 + _PLUS_TWO, atol=1e-6)
    assert np.allclose(thirds.magnitude_db, 90.0, atol=1e-6)


def test_an_lr2_joint_nulls_in_phase_and_goes_flat_with_one_leg_inverted():
    """The reason a tuner wants to see a sum before typing anything in.

    An LR2 crossover wired in phase does not "dip a bit" at the corner -- it disappears there, and
    the same pair with one driver inverted is textbook flat. Both halves come out of the same
    measured curves and differ only by a checkbox, which is exactly the question this module is
    asked.
    """
    freqs = np.geomspace(100.0, 10000.0, 1201)
    low = _measured("m-L_02 (sw)", freqs, _lr2(freqs, 1000.0, "lp"))
    high = _measured("t-L_02 (sw)", freqs, _lr2(freqs, 1000.0, "hp"))

    in_phase = curve_sum.sum_responses([low, high])
    inverted = curve_sum.sum_responses(
        [low, _measured("t-L_02 (sw)", freqs, _lr2(freqs, 1000.0, "hp"), invert=True)]
    )

    worst = int(np.argmin(in_phase.magnitude_db))
    assert in_phase.magnitude_db[worst] < -100.0
    assert abs(in_phase.freqs_hz[worst] - 1000.0) < 10.0
    assert np.allclose(inverted.magnitude_db, 0.0, atol=1e-9)


# ---- three and four drivers, which is the point of the feature ----------------------------------


def test_three_identical_drivers_gain_nine_and_a_half_db():
    grid = np.geomspace(20.0, 20000.0, 400)
    names = ("w-L_02 (sw)", "m-L_02 (sw)", "t-L_02 (sw)")

    result = curve_sum.sum_responses([_flat(name, grid) for name in names])

    assert np.allclose(result.magnitude_db, 90.0 + _PLUS_THREE, atol=1e-9)
    assert [c.name for c in result.contributions] == list(names)


def test_four_identical_drivers_gain_twelve_db():
    """A whole side: sub, woofer, mid, tweeter. Four is not a special case in the arithmetic, and
    the test exists to say that out loud -- the feature was asked for at three and four."""
    grid = np.geomspace(20.0, 20000.0, 400)
    names = ("sub_02 (sw)", "w-L_02 (sw)", "m-L_02 (sw)", "t-L_02 (sw)")

    result = curve_sum.sum_responses([_flat(name, grid) for name in names])

    assert np.allclose(result.magnitude_db, 90.0 + _PLUS_FOUR, atol=1e-9)


def test_a_delay_common_to_every_driver_changes_nothing_in_the_sum():
    """The invariant that separates a real complex sum from one with a sign or a unit wrong.

    Delaying the whole side by the same amount moves the sum later in time and cannot touch its
    magnitude by a single dB, because interference depends on the DIFFERENCE between arrivals. It
    also fixes the phase exactly: the summed response is the old one times `exp(-j2*pi*f*tau)`.
    """
    freqs = np.geomspace(30.0, 16000.0, 900)
    legs = (
        ("w-L_02 (sw)", _lr2(freqs, 300.0, "lp")),
        ("m-L_02 (sw)", _lr2(freqs, 300.0, "hp") * _lr2(freqs, 2500.0, "lp")),
        ("t-L_02 (sw)", _lr2(freqs, 2500.0, "hp")),
    )
    shift_ms = 2.5

    plain = curve_sum.sum_responses([_measured(n, freqs, h) for n, h in legs])
    shifted = curve_sum.sum_responses(
        [_measured(n, freqs, h, delay_ms=shift_ms) for n, h in legs]
    )

    assert np.allclose(plain.magnitude_db, shifted.magnitude_db, atol=1e-9)
    expected = plain.response * np.exp(-2j * np.pi * plain.freqs_hz * shift_ms / 1000.0)
    assert np.allclose(shifted.response, expected, atol=1e-9 * np.abs(plain.response).max())


# ---- grids ---------------------------------------------------------------------------------------


def test_inputs_on_different_grids_land_on_the_closed_form_answer():
    """Resampling is compared against the MATHS, not against another run of the same code.

    Two legs of one crossover, exported at different resolutions over different spans -- which is
    what happens the moment a measurement is smoothed or a target is imported. The answer is
    checked against the transfer functions evaluated directly on the grid the module chose, so the
    test measures interpolation error and nothing else.

    Tolerance: 1e-3 of a driver's own passband level. The error actually observed is around 1e-5,
    two orders below, so this fails on a real regression in how curves are resampled and not on a
    numpy release changing its last bit.
    """
    fine = np.geomspace(20.0, 20000.0, 700)
    coarse = np.geomspace(30.0, 16000.0, 400)
    low = _measured("m-L_02 (sw)", fine, _lr2(fine, 2500.0, "lp"))
    high = _measured("t-L_02 (sw)", coarse, _lr2(coarse, 2500.0, "hp"))

    result = curve_sum.sum_responses([low, high])

    on_grid = _lr2(result.freqs_hz, 2500.0, "lp") + _lr2(result.freqs_hz, 2500.0, "hp")
    assert np.max(np.abs(result.response - on_grid)) < 1e-3
    # ...and in dB, away from the null, where a dB comparison means anything at all.
    loud = np.abs(on_grid) > 0.1
    assert np.max(np.abs(result.magnitude_db[loud] - 20.0 * np.log10(np.abs(on_grid[loud])))) < 0.01


def test_the_grid_is_never_finer_than_the_coarsest_input():
    """Resolution the measurements do not have is resolution nobody may read a null off.

    A 4000-point export beside a 97-point one does not make the pair a 4000-point pair; the extra
    points would be the interpolator's opinion drawn at the same weight as measured data.
    """
    fine = _flat("m-L_01 (sw)", np.geomspace(20.0, 20000.0, 4000))
    coarse = _flat("m-R_01 (sw)", np.geomspace(20.0, 20000.0, 97))

    result = curve_sum.sum_responses([fine, coarse])

    assert result.freqs_hz.size == 97
    assert result.freqs_hz[0] == pytest.approx(20.0)
    assert result.freqs_hz[-1] == pytest.approx(20000.0)


def test_the_default_grid_is_the_overlap_and_not_the_union():
    """Outside the overlap one driver has no data, and a sum of one driver is not a sum."""
    low = _flat("sub_01 (sw)", np.geomspace(10.0, 500.0, 200))
    high = _flat("w-L_01 (sw)", np.geomspace(60.0, 4000.0, 200))

    grid = curve_sum.common_grid([low, high])

    assert grid[0] == pytest.approx(60.0)
    assert grid[-1] == pytest.approx(500.0)


def test_a_frequency_no_driver_covers_is_a_gap_and_not_a_guess():
    """`np.interp` holds the edge value outside the data by default, which would draw a driver
    carrying on flat forever past where the export stops. A gap says "not measured"; a flat line
    says "measured, and flat", and only one of those is true."""
    band = np.geomspace(50.0, 500.0, 200)
    pair = [_flat("w-L_01 (sw)", band), _flat("w-R_01 (sw)", band)]

    result = curve_sum.sum_responses(pair, grid=np.array([20.0, 100.0, 1000.0]))

    assert np.isnan(result.magnitude_db[0])
    assert np.isnan(result.magnitude_db[2])
    assert result.magnitude_db[1] == pytest.approx(90.0 + _PLUS_TWO, abs=1e-6)
    assert result.covered_hz == (100.0, 100.0)


# ---- unwrap before interpolate ------------------------------------------------------------------


def test_wrapped_phase_gives_the_same_sum_as_the_equivalent_unwrapped_phase():
    """REW returns wrapped degrees. Interpolating across a +/-180 step invents a curve.

    The two inputs below are the SAME driver -- a flat response carrying a 1 ms bulk delay --
    described once continuously and once wrapped into (-180, 180]. They must sum identically. The
    second driver sits on a different grid so the wrapped curve really is resampled rather than
    passed straight through, because that is where a naive implementation goes wrong: it does not
    fail at the wrap, it fails between the two samples either side of it.
    """
    fine = np.geomspace(20.0, 20000.0, 2000)
    continuous_deg = -360.0 * fine * 1.0e-3
    wrapped_deg = (continuous_deg + 180.0) % 360.0 - 180.0
    assert np.max(np.abs(np.diff(wrapped_deg))) > 300.0, "the input must actually wrap"

    other = _flat("m-R_01 (sw)", np.geomspace(25.0, 18000.0, 900))
    as_wrapped = curve_sum.SumInput(
        name="m-L_01 (sw)", freqs_hz=fine, magnitude_db=np.full(fine.size, 90.0),
        phase_deg=wrapped_deg,
    )
    as_continuous = curve_sum.SumInput(
        name="m-L_01 (sw)", freqs_hz=fine, magnitude_db=np.full(fine.size, 90.0),
        phase_deg=continuous_deg,
    )

    from_wrapped = curve_sum.sum_responses([as_wrapped, other])
    from_continuous = curve_sum.sum_responses([as_continuous, other])

    assert np.allclose(from_wrapped.magnitude_db, from_continuous.magnitude_db, atol=1e-9)
    # And the answer is the comb it should be, not two curves agreeing on the same mistake.
    assert from_wrapped.magnitude_db.max() < 90.0 + _PLUS_TWO + 1e-9
    assert from_wrapped.magnitude_db.max() > 90.0 + _PLUS_TWO - 0.2
    assert from_wrapped.magnitude_db.min() < 50.0


# ---- what may be refused, and what may not ------------------------------------------------------


def test_a_measurement_with_no_phase_is_refused_by_name():
    """An MMM/RTA capture has a magnitude and nothing else -- REW returns no phase for one -- and a
    magnitude has nothing to interfere with. This is the one precondition that IS provable from the
    numbers, so it is the one that is enforced."""
    grid = np.geomspace(20.0, 20000.0, 300)
    rta = curve_sum.SumInput(
        name="c_01 (rta)", freqs_hz=grid, magnitude_db=np.full(300, 85.0), phase_deg=None
    )

    with pytest.raises(curve_sum.CurveSumError) as excinfo:
        curve_sum.sum_responses([_flat("w-L_01 (sw)", grid), rta])

    assert "c_01 (rta)" in str(excinfo.value)


def test_an_all_nan_phase_is_refused_the_same_way():
    """The same capture arriving as NaN rather than as None. A caller that builds arrays before it
    checks them is normal, and both spellings mean "there is no phase here"."""
    grid = np.geomspace(20.0, 20000.0, 300)
    empty = curve_sum.SumInput(
        name="c_01 (rta)", freqs_hz=grid, magnitude_db=np.full(300, 85.0),
        phase_deg=np.full(300, np.nan),
    )

    with pytest.raises(curve_sum.CurveSumError) as excinfo:
        curve_sum.sum_responses([_flat("w-L_01 (sw)", grid), empty])

    assert "c_01 (rta)" in str(excinfo.value)


def test_a_few_dead_bins_cost_those_bins_and_not_the_driver():
    """One NaN would otherwise take everything above it: `np.unwrap` carries a NaN forward through
    the whole rest of the curve, so a single dead bin at 200 Hz would turn a working tweeter into
    a column of NaN and the sum with it."""
    grid = np.geomspace(20.0, 20000.0, 400)
    magnitude = np.full(grid.size, 90.0)
    phase = np.zeros(grid.size)
    phase[10:13] = np.nan

    holed = curve_sum.SumInput(
        name="m-L_01 (sw)", freqs_hz=grid, magnitude_db=magnitude, phase_deg=phase
    )
    result = curve_sum.sum_responses([holed, _flat("m-R_01 (sw)", grid)])

    assert np.all(np.isfinite(result.magnitude_db))
    assert result.magnitude_db[-1] == pytest.approx(90.0 + _PLUS_TWO, abs=1e-9)


def test_measurements_that_share_no_frequencies_are_an_error_the_caller_can_report():
    """A sub exported to 200 Hz and a tweeter starting at 2 kHz overlap nowhere. The window has to
    say so; a crash in a worker thread says it to the log and to nobody else."""
    low = _flat("sub_01 (sw)", np.geomspace(10.0, 200.0, 100))
    high = _flat("t-L_01 (sw)", np.geomspace(2000.0, 20000.0, 100))

    with pytest.raises(curve_sum.CurveSumError) as excinfo:
        curve_sum.sum_responses([low, high])

    message = str(excinfo.value)
    assert "sub_01 (sw)" in message and "t-L_01 (sw)" in message
    assert isinstance(excinfo.value, ValueError), "a caller catching ValueError still catches this"


def test_nothing_to_sum_is_an_error_rather_than_an_empty_curve():
    with pytest.raises(curve_sum.CurveSumError):
        curve_sum.sum_responses([])


def test_one_measurement_sums_to_itself():
    """The window draws a sum over the drivers it has; with one selected that is the driver. An
    empty answer there would look like a bug in the sum rather than a selection of one."""
    grid = np.geomspace(20.0, 20000.0, 300)

    result = curve_sum.sum_responses([_flat("w-L_01 (sw)", grid, level_db=87.5)])

    assert np.allclose(result.magnitude_db, 87.5, atol=1e-9)


# ---- what the caller draws and prints -----------------------------------------------------------


def test_the_contributions_are_the_drivers_as_proposed_not_as_measured():
    """What the window puts under the sum. The point of the panel is comparing the sum against what
    each driver is doing AT THE PROPOSED SETTING -- drawing the measured curve there would put the
    trim and the polarity in the sum and nowhere else, and the eye would read the difference as
    interference."""
    grid = np.geomspace(20.0, 20000.0, 300)
    trimmed = _flat("m-R_01 (sw)", grid, gain_db=-_PLUS_TWO, invert=True)

    result = curve_sum.sum_responses([_flat("m-L_01 (sw)", grid), trimmed])

    drawn = {c.name: c for c in result.contributions}["m-R_01 (sw)"]
    assert drawn.magnitude_db.size == result.freqs_hz.size
    assert np.allclose(drawn.magnitude_db, 90.0 - _PLUS_TWO, atol=1e-9)
    # Half the amplitude, subtracted: the pair sits 6.02 dB below one driver on its own.
    assert np.allclose(result.magnitude_db, 90.0 - _PLUS_TWO, atol=1e-9)


def test_the_timing_reference_is_reported_and_never_judged():
    """The 5 ms that means two opposite things.

    `rew-api-quirks.md` records that a floating per-measurement reference makes `startTime` jump by
    about 5 ms between adjacent captures. It also records why that cannot be used as a test: with a
    shared loopback reference the startTimes differ too, and that difference IS the acoustic
    arrival -- the thing being measured. The same pair of numbers is correct under one rig and
    meaningless under another, so the module reports them and states the assumption, and the
    verdict stays with the person who set the rig up.
    """
    grid = np.geomspace(20.0, 20000.0, 300)
    near = _flat("w-L_01 (sw)", grid, start_time_s=0.005180)
    far = _flat("w-R_01 (sw)", grid, start_time_s=0.010180)

    result = curve_sum.sum_responses([near, far])

    assert result.start_times_s == {"w-L_01 (sw)": 0.005180, "w-R_01 (sw)": 0.010180}
    sentence = result.as_sentence()
    assert curve_sum.TIMING_ASSUMPTION in sentence
    assert "0.005180" in sentence and "0.010180" in sentence


def test_the_assumption_is_printed_even_when_no_timing_facts_were_supplied():
    """The case where the assumption is entirely unbacked is the one it most needs stating."""
    grid = np.geomspace(20.0, 20000.0, 300)

    sentence = curve_sum.sum_responses(
        [_flat("w-L_01 (sw)", grid), _flat("w-R_01 (sw)", grid)]
    ).as_sentence()

    assert curve_sum.TIMING_ASSUMPTION in sentence
    assert "w-L_01 (sw)" in sentence and "w-R_01 (sw)" in sentence


def test_the_sentence_carries_the_reading_a_joint_is_judged_by():
    """How far the pair falls below the driver that was carrying the band, and where. That is the
    number a crossover argument is actually about; an absolute SPL is not, because it moves with
    the gain of whatever was measured."""
    freqs = np.geomspace(100.0, 10000.0, 1201)
    low = _measured("m-L_02 (sw)", freqs, _lr2(freqs, 1000.0, "lp"))
    high = _measured("t-L_02 (sw)", freqs, _lr2(freqs, 1000.0, "hp"))

    result = curve_sum.sum_responses([low, high])
    where_hz, depth_db = result.deepest_null()

    assert abs(where_hz - 1000.0) < 10.0
    assert depth_db < -100.0
    assert f"at {where_hz:.0f} Hz" in result.as_sentence()


def test_a_sum_with_no_cancellation_reports_no_null():
    """Two drivers dead in phase gain 6 dB everywhere and cancel nowhere. A "deepest null" of
    +6 dB relative to one driver would read as a null to anybody skimming, so the reading is
    relative to the loudest single contribution and comes out at exactly 0 dB below it... which is
    what a perfectly coherent pair does."""
    grid = np.geomspace(20.0, 20000.0, 300)

    result = curve_sum.sum_responses([_flat("w-L_01 (sw)", grid), _flat("w-R_01 (sw)", grid)])
    _, depth_db = result.deepest_null()

    assert depth_db == pytest.approx(_PLUS_TWO, abs=1e-9)


def test_the_module_needs_no_qt():
    """It is imported by the window, by the MCP server and by tests that build no QApplication.
    An accidental `from PySide6...` here would make the light install stop importing, and that is
    exactly the kind of import somebody adds for a type hint."""
    import autosound_tcc.core.curve_sum as module

    with open(module.__file__, encoding="utf-8") as handle:
        imports = [line.strip() for line in handle if line.strip().startswith(("import ", "from "))]

    assert not [line for line in imports if "PySide6" in line or "pyqtgraph" in line]


# ---- one round of one car: the half of the precondition that IS checkable ------------------------


def test_one_round_of_sweeps_is_summable_and_the_verdict_names_the_version():
    """`phase_1_foundation.md` has the round captured with one shared Time Offset across all
    sweeps, and `naming-and-structure.md` §3 puts the DSP config version in the title. All `(sw)`
    at one `_N` is therefore one round on the method's own footing -- and the verdict says which
    version, because "trust me" and "config version 2" are not the same statement."""
    grid = np.geomspace(20.0, 20000.0, 300)
    side = [
        _flat(name, grid, config_version=2, method="sw")
        for name in ("w-L_02 (sw)", "m-L_02 (sw)", "t-L_02 (sw)")
    ]

    result = curve_sum.sum_responses(side)

    assert result.summability.ok
    assert result.summability.status == curve_sum.SUMMABLE
    assert result.summability.config_version == "2"
    assert "version 2" in result.summability.text
    assert result.summability.text in result.as_sentence()


def test_a_mixed_config_version_set_is_computed_but_labelled_with_both_versions():
    """Not a timing quibble. A bumped `_N` means the DSP configuration CHANGED between the two
    captures, so the drivers being added together never played together at any one setting -- this
    is two cars summed. It still computes, because a tuner comparing rounds on purpose is a real
    thing to want, and it is labelled so nobody reads it as a prediction about this car."""
    grid = np.geomspace(20.0, 20000.0, 300)
    before = _flat("m-L_01 (sw)", grid, config_version="01", method="sw")
    after = _flat("t-L_02 (sw)", grid, config_version="02", method="sw")

    result = curve_sum.sum_responses([before, after])

    assert result.summability.status == curve_sum.MIXED_CONFIG
    assert not result.summability.ok
    assert result.summability.versions == ("1", "2")
    assert "1" in result.summability.text and "2" in result.summability.text
    # ...and it is an answer, not an exception: the curve is there to be looked at.
    assert np.allclose(result.magnitude_db, 90.0 + _PLUS_TWO, atol=1e-9)


def test_an_rta_capture_is_refused_on_its_method_even_when_it_carries_phase():
    """A curve titled `(rta)` that arrives with a phase array is a derived or imported trace
    wearing an MMM's name. Trusting the numbers over the title would sum something nobody
    captured, so the suffix refuses on its own."""
    grid = np.geomspace(20.0, 20000.0, 300)
    sweep = _flat("w-L_02 (sw)", grid, config_version=2, method="sw")
    impostor = _flat("c_02 (rta)", grid, config_version=2, method="rta")

    with pytest.raises(curve_sum.CurveSumError) as excinfo:
        curve_sum.sum_responses([sweep, impostor])

    assert "c_02 (rta)" in str(excinfo.value)


def test_a_measurement_with_no_config_version_is_unknown_and_not_a_match():
    """A REW list holds imports, room-sim results and hand-named curves, and the skill's parser
    returns None for those rather than erroring. "No version" must not quietly join whatever
    version its neighbours have -- that is the reading that would let two rounds sum in silence."""
    grid = np.geomspace(20.0, 20000.0, 300)
    named = _flat("w-L_02 (sw)", grid, config_version=2, method="sw")
    stray = _flat("some import.txt", grid, method="sw")

    verdict = curve_sum.sum_responses([named, stray]).summability

    assert verdict.status == curve_sum.UNKNOWN_CONFIG
    assert not verdict.ok
    assert "some import.txt" in verdict.text


def test_zero_padding_is_not_a_different_config_version():
    """`_02` and `_2` are one round. REW titles are hand-typed and zero-padding is common --
    `measurement_view` already keys its parsed titles this way -- and a sum that saw two configs
    here would send somebody re-measuring for nothing."""
    grid = np.geomspace(20.0, 20000.0, 300)
    padded = _flat("w-L_02 (sw)", grid, config_version="02", method="sw")
    bare = _flat("m-L_2 (sw)", grid, config_version=2, method="sw")

    verdict = curve_sum.summability([padded, bare])

    assert verdict.ok
    assert verdict.config_version == "2"


def test_summability_can_be_asked_before_anything_is_computed():
    """The window greys the button out and shows the reason; it should not have to compute a sum
    it is about to refuse, nor catch an exception to find out."""
    grid = np.geomspace(20.0, 20000.0, 300)

    assert curve_sum.summability([]).refused
    assert curve_sum.summability([_flat("c_01 (rta)", grid, method="rta")]).refused
    assert not curve_sum.summability([_flat("w-L_02 (sw)", grid, config_version=2)]).refused


# ---- how phase is carried across a grid change --------------------------------------------------


def test_a_pure_delay_survives_resampling_where_a_real_imaginary_interpolation_would_not():
    """The property that decides the interpolation method, stated as a test.

    A pure delay is flat in magnitude by definition. Between two adjacent samples of a real export
    it can rotate a long way -- at 20 kHz with ~20 Hz spacing, 5 ms turns about 36 degrees per
    sample. Interpolating the real and imaginary parts cuts the CHORD across that arc, shortening
    the vector and inventing a dip of roughly 5% that no microphone recorded; unwrapping the phase
    and interpolating magnitude and phase separately walks the arc instead.

    Both halves are asserted on purpose. The second one records what the rejected method does here,
    so that a later "simplification" back to `complex_interp` fails loudly rather than shipping a
    0.4 dB fiction at the top of the band.
    """
    fine = np.geomspace(20.0, 20000.0, 6907)  # ~20 Hz between samples at 20 kHz
    delay_s = 0.005
    continuous_deg = -360.0 * fine * delay_s
    wrapped_deg = (continuous_deg + 180.0) % 360.0 - 180.0
    driver = curve_sum.SumInput(
        name="m-L_02 (sw)", freqs_hz=fine, magnitude_db=np.full(fine.size, 90.0),
        phase_deg=wrapped_deg, config_version=2, method="sw",
    )
    between = np.sqrt(fine[:-1] * fine[1:])  # halfway between samples: worst case for any method

    result = curve_sum.sum_responses([driver], grid=between)

    assert np.allclose(result.magnitude_db, 90.0, atol=1e-9)

    original = np.power(10.0, 90.0 / 20.0) * np.exp(1j * np.deg2rad(continuous_deg))
    chord = np.interp(between, fine, original.real) + 1j * np.interp(between, fine, original.imag)
    assert np.min(20.0 * np.log10(np.abs(chord)) - 90.0) < -0.3
