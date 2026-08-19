"""An all-pass is a parameter set here and a filter in the skill; both halves have to hold.

The physics below is closed-form — the phase at `f0`, the span, the delay far below `f0` — and
that is what the tests are written against, not what the code printed last time. A test that
agreed with the implementation would have agreed with the day `eq_complex` drew an APF as a shelf.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from autosound_tcc.core import allpass, vendor_loader
from autosound_tcc.core.allpass import Allpass, AllpassError

needs_skill = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out"
)


def _grid(points: int = 2000):
    return np.geomspace(2.0, 40000.0, points)


# ---- the parameter set --------------------------------------------------------------------------


def test_the_two_kinds_are_spelled_the_way_the_ledger_spells_them():
    """`APF1`/`APF2` are `state.EQ_TYPES`; a model reading them here can propose them there."""
    assert Allpass(1, 250.0).kind == "APF1"
    assert Allpass(2, 250.0, 0.7).kind == "APF2"
    assert allpass.KINDS == ("APF1", "APF2")


def test_a_first_order_all_pass_has_no_q_and_says_so():
    with pytest.raises(AllpassError):
        Allpass(1, 250.0, 0.7)
    assert Allpass(1, 250.0).q is None


def test_a_second_order_all_pass_needs_a_q():
    with pytest.raises(AllpassError):
        Allpass(2, 250.0)
    with pytest.raises(AllpassError):
        Allpass(2, 250.0, None)


@pytest.mark.parametrize("bad", [0, 3, "2", None])
def test_only_first_and_second_order_exist(bad):
    with pytest.raises(AllpassError):
        Allpass(bad, 250.0, 0.7)


@pytest.mark.parametrize("f0", [0.0, -100.0, 5.0, 30000.0, float("nan"), "abc", None])
def test_an_f0_outside_the_audible_fence_is_refused(f0):
    with pytest.raises(AllpassError):
        Allpass(1, f0)


@pytest.mark.parametrize("q", [0.0, -1.0, 0.05, 11.0, float("inf"), "x"])
def test_a_q_outside_the_fence_is_refused(q):
    with pytest.raises(AllpassError):
        Allpass(2, 250.0, q)


def test_the_label_is_the_filter_in_one_breath():
    """The same string goes into the legend, the reading and the prompt — a dot, no locale."""
    assert Allpass(2, 250.0, 0.71).label() == "APF2 250 Hz Q 0.71"
    assert Allpass(1, 80.0).label() == "APF1 80 Hz"
    assert Allpass(2, 315.5, 1.0).label() == "APF2 315.5 Hz Q 1.00"


def test_the_dict_form_is_the_ledgers_band_shape_and_round_trips():
    """`{"type", "f", "q"}` — a `state.EQ_TYPES` band object, so it can be proposed verbatim.
    Never written by TCC anywhere the skill reads (D-6); it is what the bank keeps."""
    two = Allpass(2, 250.0, 0.7)
    assert two.as_dict() == {"type": "APF2", "f": 250.0, "q": 0.7}
    assert Allpass.from_dict(two.as_dict()) == two
    one = Allpass(1, 80.0)
    assert one.as_dict() == {"type": "APF1", "f": 80.0}
    assert Allpass.from_dict(one.as_dict()) == one


@pytest.mark.parametrize(
    "raw",
    [None, {}, "APF2", {"type": "PK", "f": 250.0}, {"type": "APF2", "f": 250.0},
     {"type": "APF1", "f": -1.0}, {"type": "APF2", "f": 250.0, "q": 99.0}, {"type": "APF3"}],
)
def test_anything_that_is_not_a_valid_all_pass_reads_back_as_none(raw):
    """A hand-edited settings file, or an entry from before the field existed: nothing, not a
    crash, and never a half-valid filter."""
    assert Allpass.from_dict(raw) is None


def test_the_dict_form_tolerates_a_lower_case_type():
    assert Allpass.from_dict({"type": "apf2", "f": 250.0, "q": 0.7}) == Allpass(2, 250.0, 0.7)


def test_the_module_needs_no_qt():
    """The window draws with it and the sentence to the model is built from it; neither should be
    the only way to compute it, and an accidental Qt import here is what would make it so."""
    with open(allpass.__file__, encoding="utf-8") as handle:
        imports = [line.strip() for line in handle if line.strip().startswith(("import ", "from "))]

    assert not [line for line in imports if "PySide6" in line or "pyqtgraph" in line]


# ---- the filter, from the skill --------------------------------------------------------------


@needs_skill
def test_a_first_order_all_pass_is_minus_ninety_degrees_at_f0_and_unit_magnitude():
    ap = Allpass(1, 100.0)
    h = ap.response(_grid())
    assert np.allclose(np.abs(h), 1.0, atol=1e-12), "an all-pass changes no level anywhere"
    at_f0 = np.degrees(np.angle(ap.response([100.0])))[0]
    assert at_f0 == pytest.approx(-90.0, abs=1e-9)


@needs_skill
def test_a_first_order_all_pass_turns_half_a_turn_and_only_ever_lags():
    """0 → −180° through `f0`, monotonically: the SCR-050 description, in numbers."""
    phase = Allpass(1, 100.0).phase_deg(_grid())
    assert phase[0] == pytest.approx(0.0, abs=3.0)
    assert phase[-1] == pytest.approx(-180.0, abs=3.0)
    assert np.all(np.diff(phase) < 0.0)


@needs_skill
def test_far_below_f0_a_first_order_all_pass_is_a_pure_delay_of_one_over_pi_f0():
    """1/(π·100 Hz) = 3.18 ms — the whole reason the method aligns a joint with an all-pass rather
    than raw delay: the delay is confined to the band around and below `f0`."""
    tau_s = 1.0 / (math.pi * 100.0)
    low = 2.0
    phase = np.degrees(np.angle(Allpass(1, 100.0).response([low])))[0]
    assert phase == pytest.approx(-360.0 * low * tau_s, abs=1e-3)


@needs_skill
def test_a_second_order_all_pass_is_minus_one_eighty_at_f0_and_a_full_turn_overall():
    ap = Allpass(2, 100.0, 0.7)
    h = ap.response(_grid())
    assert np.allclose(np.abs(h), 1.0, atol=1e-12)
    at_f0 = np.degrees(np.angle(ap.response([100.0])))[0]
    assert abs(at_f0) == pytest.approx(180.0, abs=1e-9)
    phase = ap.phase_deg(_grid())
    assert phase[0] == pytest.approx(0.0, abs=4.0)
    assert phase[-1] == pytest.approx(-360.0, abs=4.0)
    assert np.all(np.diff(phase) < 0.0)


@needs_skill
def test_a_higher_q_turns_faster_near_f0():
    """What Q MEANS on an all-pass: not depth, but how much of the turn happens next to `f0`."""
    just_above = 100.0 * 2 ** (1 / 6)
    steep = Allpass(2, 100.0, 4.0).phase_deg([100.0, just_above])[1]
    gentle = Allpass(2, 100.0, 0.7).phase_deg([100.0, just_above])[1]
    assert steep < gentle < -180.0


@needs_skill
def test_two_first_order_sections_are_one_second_order_all_pass_at_q_one_half():
    """The identity that would break first if the two functions did not share a convention —
    and the fact a tuner with two APF1 slots and no APF2 can lean on."""
    f = _grid()
    twice = Allpass(1, 100.0).response(f) ** 2
    assert np.allclose(twice, Allpass(2, 100.0, 0.5).response(f), atol=1e-12)


@needs_skill
def test_the_phase_is_continuous_and_not_re_wrapped():
    """A phase plot of a joint is read for its slope; a curve that jumps ±360° hides it."""
    phase = Allpass(2, 1000.0, 2.0).phase_deg(_grid())
    assert np.max(np.abs(np.diff(phase))) < 90.0, "no wrap step anywhere on the grid"


@needs_skill
def test_the_maths_comes_from_the_skill_and_not_from_a_copy_in_tcc():
    """SCR-050: two implementations of one filter is how the front-end and the method start
    disagreeing about what a proposal means. This module holds no formula of its own."""
    import inspect

    source = inspect.getsource(allpass)
    assert "arctan" not in source and "atan" not in source
    assert "load_dsp_math" in source
    maths = vendor_loader.load_dsp_math()
    f = _grid(200)
    assert np.allclose(Allpass(2, 250.0, 0.7).response(f), maths.apf2_response(f, 250.0, 0.7))
    assert np.allclose(Allpass(1, 250.0).response(f), maths.apf1_response(f, 250.0))
