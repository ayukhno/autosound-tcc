"""Taking a protective filter back out of a measured curve — TCC's half of it.

The maths is the method's (`rew_tool/protective.py`) and is tested there. What is tested here is
the seam: whether this installation can run the correction at all, the conversion between what REW
gives (dB and degrees) and what the maths takes (a complex response), and the one distinction the
whole feature turns on — a channel nobody recorded is not a channel recorded as clean.
"""

from __future__ import annotations

import numpy as np
import pytest

from autosound_tcc.core import protective


def test_this_installation_can_say_why_it_cannot_correct(monkeypatch):
    """A toggle that raises is worse than one that is not offered, and the two ways it cannot run
    need different sentences: an old pin has no module, and a light install has no scipy."""
    assert protective.reason() == "", "the dev environment has both halves"
    assert protective.available() is True

    monkeypatch.setattr(protective, "_module", lambda: (_ for _ in ()).throw(
        protective.ProtectiveUnavailable("no such module")))
    said = protective.reason()
    assert "not in this checkout" in said and not protective.available()


def test_a_protective_high_pass_comes_back_out():
    """The method's own numbers, through this module's dB/degree conversion: an LR4 at 100 Hz
    leaves about 52 degrees at 320 Hz, and taking it out returns them."""
    legs = {"hp": {"f": 100, "type": "LR", "slope": 24}, "lp": "OFF"}
    freqs = np.array([50.0, 100.0, 320.0, 1000.0])
    flat_db, flat_deg = np.zeros(4), np.zeros(4)

    corrected = protective.de_embed(freqs, flat_db, flat_deg, legs)

    assert corrected.applied == ("hp",)
    assert corrected.changed
    # Below the corner the filter cut; undoing it lifts. At the corner an LR4 is -6 dB.
    assert corrected.magnitude_db[0] > 20
    assert corrected.magnitude_db[1] == pytest.approx(6.0, abs=0.1)
    assert corrected.magnitude_db[3] == pytest.approx(0.0, abs=0.1)
    # And the phase the filter was carrying: ~52 degrees three-ish times above the corner.
    assert corrected.phase_deg[2] == pytest.approx(-52, abs=2)


def test_a_record_that_says_nothing_was_in_the_chain_changes_nothing():
    """`"OFF"` is an answer. The curve comes back as it was, and `changed` says so — which is not
    the same as the correction having failed."""
    legs = {"hp": "OFF", "lp": "OFF"}
    freqs = np.array([50.0, 200.0, 1000.0])
    mag, phase = np.array([1.0, 2.0, 3.0]), np.array([10.0, 20.0, 30.0])

    corrected = protective.de_embed(freqs, mag, phase, legs)

    assert not corrected.changed and corrected.applied == ()
    assert corrected.magnitude_db == pytest.approx(mag, abs=1e-6)
    assert corrected.phase_deg == pytest.approx(phase, abs=1e-6)
    assert corrected.note, "and it says why nothing happened"


def test_nobody_said_is_refused_rather_than_treated_as_clean():
    """The failure this whole design exists to prevent: a correction over an unknown chain
    produces data that LOOKS corrected. The method raises; this module lets that through rather
    than turning it into an empty result."""
    freqs = np.array([100.0, 1000.0])

    with pytest.raises(Exception) as caught:
        protective.de_embed(freqs, np.zeros(2), np.zeros(2), None)

    assert "never written down" in str(caught.value)
    assert not isinstance(caught.value, protective.ProtectiveUnavailable), (
        "a missing RECORD is not a missing INSTALL — the caller has to tell them apart"
    )


def test_legs_of_keeps_the_two_answers_apart():
    record = {"series": "3", "channels": {"m-L": {"hp": {"f": 100, "type": "LR", "slope": 24}},
                                          "w-L": "OFF"}}

    assert protective.legs_of(record, "m-L")["hp"]["f"] == 100
    assert protective.legs_of(record, "m-L")["lp"] == "OFF", "an unstated leg in a stated channel"
    assert protective.legs_of(record, "w-L") == {"hp": "OFF", "lp": "OFF"}
    assert protective.legs_of(record, "tw-L") is None, "nobody said, and that is not OFF"
    assert protective.legs_of(None, "m-L") is None


def test_the_capped_region_is_reported_because_the_phase_there_is_not_the_driver_s():
    """Below a protective corner the filter's response goes to zero and dividing by it lifts the
    noise floor with the signal. The method caps at 40 dB; a plot has to mark where, or it draws
    invented phase as if it were measured."""
    legs = {"hp": {"f": 100, "type": "LR", "slope": 48}, "lp": "OFF"}
    freqs = np.array([5.0, 10.0, 20.0, 100.0, 1000.0])

    corrected = protective.de_embed(freqs, np.zeros(5), np.zeros(5), legs)

    assert corrected.capped_bins > 0
    assert corrected.capped_below_hz is not None
    assert corrected.magnitude_db[0] <= 40.0 + 1e-6, "the cap is what stops it inventing signal"
