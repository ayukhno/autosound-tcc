"""Band by band, one EQ against a compared version's (tcc#54, finding 73)."""

from __future__ import annotations

from autosound_tcc.state.dsp_state import EqBand
from autosound_tcc.state.eq_diff import compare_bands


def _pk(f, gain=-3.0, q=2.0, i=None, bypass=False, kind="PK"):
    return EqBand(type=kind, freq_hz=float(f), gain_db=gain, q=q, bypass=bypass, index=i)


def _statuses(side):
    return [(d.band.freq_hz, d.status) for d in side]


def test_numbered_bands_are_matched_by_the_dsp_band_number():
    """Where both versions carry `i`, the DSP's own number says which band is which — a band
    moved from 100 Hz to 125 Hz is the same band, changed."""
    now = [_pk(125, i=1), _pk(1000, i=2), _pk(4000, i=4)]
    was = [_pk(100, i=1), _pk(1000, i=2), _pk(2500, i=3)]
    current, compared = compare_bands(now, was)
    assert _statuses(current) == [(125.0, "chg"), (1000.0, "same"), (4000.0, "new")]
    assert _statuses(compared) == [(100.0, "chg"), (1000.0, "same"), (2500.0, "removed")]
    assert current[0].fields == frozenset({"freq"})
    assert current[0].other.freq_hz == 100.0 and compared[0].other.freq_hz == 125.0


def test_every_field_that_moved_is_named():
    current, _ = compare_bands([_pk(100, gain=-2.0, q=4.0, bypass=True, i=1)],
                               [_pk(100, gain=-3.0, q=2.0, i=1)])
    assert current[0].status == "chg"
    assert current[0].fields == frozenset({"gain", "q", "bypass"})


def test_without_numbers_an_inserted_band_does_not_shift_the_rest():
    """No `i` (five presets of six, finding 72): the order and the frequency decide. A band put
    in the middle is new; the ones after it are not all "changed"."""
    now = [_pk(100), _pk(300), _pk(1000), _pk(4000)]
    was = [_pk(100), _pk(1000), _pk(4000)]
    current, compared = compare_bands(now, was)
    assert _statuses(current) == [(100.0, "same"), (300.0, "new"), (1000.0, "same"),
                                  (4000.0, "same")]
    assert [d.status for d in compared] == ["same", "same", "same"]


def test_without_numbers_a_moved_frequency_in_its_place_is_a_change():
    now = [_pk(100), _pk(1100, gain=-4.0), _pk(4000)]
    was = [_pk(100), _pk(1000), _pk(4000)]
    current, compared = compare_bands(now, was)
    assert _statuses(current) == [(100.0, "same"), (1100.0, "chg"), (4000.0, "same")]
    assert current[1].fields == frozenset({"freq", "gain"})
    assert _statuses(compared) == [(100.0, "same"), (1000.0, "chg"), (4000.0, "same")]


def test_without_numbers_a_dropped_band_is_removed_on_the_compared_side_only():
    current, compared = compare_bands([_pk(100), _pk(4000)], [_pk(100), _pk(1000), _pk(4000)])
    assert [d.status for d in current] == ["same", "same"]
    assert _statuses(compared) == [(100.0, "same"), (1000.0, "removed"), (4000.0, "same")]


def test_numbers_on_one_side_only_fall_back_to_the_order():
    """PAS-011 numbered one preset: comparing it with an unnumbered one cannot use `i`."""
    current, _ = compare_bands([_pk(100, i=1), _pk(1000, i=2)], [_pk(100), _pk(1000)])
    assert [d.status for d in current] == ["same", "same"]


def test_nothing_compared_against_nothing():
    assert compare_bands([], []) == ([], [])
    current, compared = compare_bands([_pk(100)], [])
    assert [d.status for d in current] == ["new"] and compared == []
