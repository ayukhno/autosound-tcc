"""The delay bank's own store: one step of the curve window is one read and one write (#177, TA-4).

The window banks every driver on screen on every step of the delay box. One `put` per driver was
one load and one write each — seven of both for a whole side — so `put_many` banks the set in
one, and has to leave the store exactly as the seven `put`s would have, failures included.
"""

from __future__ import annotations

import json
import os

import pytest

from autosound_tcc.core import delay_bank, own_store, project_settings
from autosound_tcc.core.allpass import Allpass

_POSIX_MODES = pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX permissions, and root reads and writes whatever the mode",
)

#: What a store holds before the step: a driver with an all-pass, an arrival and a series; one
#: from the first version (a bare number, no series); one from another series; a field that is
#: not the bank's at all.
_SEED = {
    "w-L_01 (sw)": {"ms": 0.198, "at": 4.52, "set": "cap_001",
                    "apf": {"type": "APF2", "f": 250.0, "q": 0.71}},
    "m-L_01 (sw)": 0.4,
    "sw_01 (sw)": {"ms": 1.1, "at": 9.6, "set": "cap_000"},
}


def _step():
    """One step's readings: a delay that keeps the all-pass and the arrival it does not name; an
    old entry that picks up an arrival and the series; a new driver with a filter; the same driver
    twice, the later taking the filter off; a filter banked earlier in the same set and kept."""
    return [
        delay_bank.Reading("w-L_01 (sw)", 0.26),
        delay_bank.Reading("m-L_01 (sw)", 0.5, arrival_ms=4.78),
        delay_bank.Reading("tw-L_01 (sw)", 0.0, allpass=Allpass(1, 80.0)),
        delay_bank.Reading("w-L_01 (sw)", 0.3, allpass=None),
        delay_bank.Reading("tw-L_01 (sw)", -0.1),
    ]


def _seeded(folder):
    project_settings.set_value(folder, "generator", "sdk:claude-opus-5")
    project_settings.set_value(folder, delay_bank.KEY, _SEED)
    return project_settings.path_for(folder)


def _seven():
    return [delay_bank.Reading(f"d{i}_01 (sw)", 0.1 * i) for i in range(7)]


def test_put_many_stores_exactly_what_one_put_per_reading_stores(tmp_path):
    by_put, by_many = tmp_path / "put", tmp_path / "many"
    one, many = _seeded(by_put), _seeded(by_many)

    for reading in _step():
        moved = delay_bank.put(reading.title, reading.ms, by_put, arrival_ms=reading.arrival_ms,
                               session="cap_002", allpass=reading.allpass)
    moved_many = delay_bank.put_many(_step(), by_many, session="cap_002")

    assert many.read_bytes() == one.read_bytes(), "the same store, byte for byte"
    assert moved_many == moved, "and the same answer: the drivers that carry a delay"
    stored = json.loads(many.read_text(encoding="utf-8"))
    assert stored["generator"] == "sdk:claude-opus-5", "the rest of the file is kept"
    bank = stored[delay_bank.KEY]
    assert bank["w-L_01 (sw)"] == {"ms": 0.3, "at": 4.52, "set": "cap_002"}, "filter off, arrival kept"
    assert bank["tw-L_01 (sw)"]["apf"] == {"type": "APF1", "f": 80.0}, "kept within the set"
    assert bank["m-L_01 (sw)"] == {"ms": 0.5, "at": 4.78, "set": "cap_002"}
    assert bank["sw_01 (sw)"] == {"ms": 1.1, "at": 9.6, "set": "cap_000"}, "another series untouched"


def test_put_many_reads_the_store_once_and_writes_it_once(tmp_path, monkeypatch):
    calls = {"load": 0, "set_value": 0}
    real_load, real_set = project_settings.load, project_settings.set_value

    def load(*args, **kwargs):
        calls["load"] += 1
        return real_load(*args, **kwargs)

    def set_value(*args, **kwargs):
        calls["set_value"] += 1
        return real_set(*args, **kwargs)

    monkeypatch.setattr(project_settings, "load", load)
    monkeypatch.setattr(project_settings, "set_value", set_value)

    delay_bank.put_many(_seven(), tmp_path, session="cap_001")

    assert calls == {"load": 1, "set_value": 1}
    assert delay_bank.seen(tmp_path) == {f"d{i}_01 (sw)" for i in range(7)}


def test_no_reading_is_no_write(tmp_path):
    path = _seeded(tmp_path)
    before = path.read_bytes()

    assert delay_bank.put_many([], tmp_path) == {"w-L_01 (sw)": 0.198, "m-L_01 (sw)": 0.4,
                                                  "sw_01 (sw)": 1.1}
    assert path.read_bytes() == before


def test_a_reading_the_bank_cannot_hold_leaves_it_as_it_was(tmp_path):
    """Seven `put`s stopped at the fourth have written three. One write at the end has written
    none: the bank never ends half a step."""
    path = _seeded(tmp_path)
    before = path.read_bytes()
    readings = _seven()
    readings[3] = delay_bank.Reading("d3_01 (sw)", 0.3, allpass="APF1 80 Hz")

    with pytest.raises(TypeError):
        delay_bank.put_many(readings, tmp_path)

    assert path.read_bytes() == before


def _a_folder_where_the_store_is(folder):
    path = project_settings.path_for(folder)
    path.mkdir(parents=True)
    (path / "inside").write_text("kept", encoding="utf-8")
    return lambda: (path / "inside").read_text(encoding="utf-8") == "kept"


def _a_store_nobody_may_open(folder):
    path = _seeded(folder)
    before = path.read_bytes()
    path.chmod(0)
    return lambda: path.chmod(0o600) or path.read_bytes() == before


@pytest.mark.parametrize("unreadable", [
    _a_folder_where_the_store_is,
    pytest.param(_a_store_nobody_may_open, marks=_POSIX_MODES),
], ids=["folder", "mode-0"])
def test_a_store_that_cannot_be_read_refuses_put_many_as_it_refuses_put_and_says_it_once(
        tmp_path, monkeypatch, app_log_told, unreadable):
    """Task 17: the read-modify-write lets `StoreUnreadable` through rather than write `{}` with
    one field back over the store. `put_many` does what `put` does — once for the set: one
    attempt at the write, not seven, and the sentence said once."""
    intact = unreadable(tmp_path)
    writes = []
    real_set = project_settings.set_value
    monkeypatch.setattr(project_settings, "set_value",
                        lambda *args, **kwargs: writes.append(args) or real_set(*args, **kwargs))

    with pytest.raises(OSError) as by_put:
        delay_bank.put("d0_01 (sw)", 0.0, tmp_path)
    with pytest.raises(OSError) as by_many:
        delay_bank.put_many(_seven(), tmp_path)

    assert by_put.type is own_store.StoreUnreadable
    assert by_many.type is by_put.type, "the store's own refusal, as `put` gets it"
    assert len(writes) == 2, "one attempt for `put`, one for the seven readings"
    assert intact(), "never written over"
    assert not list(tmp_path.rglob("*.corrupt-*")), "and not set aside: its bytes may be fine"
    path = project_settings.path_for(tmp_path)
    assert len(app_log_told) == 1 and str(path) in app_log_told[0], app_log_told


@_POSIX_MODES
def test_a_store_that_cannot_be_written_refuses_put_many_as_it_refuses_put_and_keeps_its_bytes(
        tmp_path):
    folder = tmp_path / "read-only"
    path = _seeded(folder)
    before = path.read_bytes()
    folder.chmod(0o500)
    try:
        with pytest.raises(OSError) as by_put:
            delay_bank.put("d0_01 (sw)", 0.0, folder)
        with pytest.raises(OSError) as by_many:
            delay_bank.put_many(_seven(), folder)
    finally:
        folder.chmod(0o700)

    assert by_many.type is by_put.type is PermissionError
    assert path.read_bytes() == before, "the store as it was"
    assert [p.name for p in folder.iterdir()] == [project_settings.FILENAME], "and no temp file"
