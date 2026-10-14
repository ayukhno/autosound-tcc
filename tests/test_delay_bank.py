"""The delay bank's own store: one step of the curve window is one read and one write (#177, TA-4).

The window banks every driver on screen on every step of the delay box. One `put` per driver was
one load and one write each — seven of both for a whole side — so `put_many` banks the set in
one, and has to leave the store exactly as the seven `put`s would have, failures included.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from autosound_tcc.core import delay_bank, own_store, project_settings
from autosound_tcc.core.allpass import Allpass

_POSIX_MODES = pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX permissions, and root reads and writes whatever the mode",
)

#: What a store holds before the step, in v1.1.3's shape (one entry per title): a driver of the
#: step's own series with an all-pass, an arrival and a series; one from the first version (a bare
#: number, no series); one from another series; one the step's series banks too, from another
#: series.
_SEED = {
    "w-L_01 (sw)": {"ms": 0.198, "at": 4.52, "set": "cap_002",
                    "apf": {"type": "APF2", "f": 250.0, "q": 0.71}},
    "m-L_01 (sw)": 0.4,
    "sw_01 (sw)": {"ms": 1.1, "at": 9.6, "set": "cap_000"},
    "w-R_01 (sw)": {"ms": 0.1, "at": 4.7, "set": "cap_001"},
}


def _step():
    """One step's readings under cap_002: a delay that keeps the all-pass and the arrival it does
    not name; an old entry with no series, which cap_002 takes its own of; a driver another series
    holds, which cap_002 gets its own entry for; a new driver with a filter; the same driver twice,
    the later taking the filter off; a filter banked earlier in the same set and kept."""
    return [
        delay_bank.Reading("w-L_01 (sw)", 0.26),
        delay_bank.Reading("m-L_01 (sw)", 0.5, arrival_ms=4.78),
        delay_bank.Reading("w-R_01 (sw)", 0.0),
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
    assert bank["m-L_01 (sw)"] == {"ms": 0.5, "at": 4.78, "set": "cap_002"}, "v1.1.3's: latest"
    assert bank["w-R_01 (sw)"] == {"ms": 0.0, "at": None, "set": "cap_002"}
    assert bank["sw_01 (sw)"] == {"ms": 1.1, "at": 9.6, "set": "cap_000"}, "another series untouched"
    by = stored[delay_bank.BY_SERIES]
    assert by[""] == {"m-L_01 (sw)": 0.4}, "the one with no series kept for the others (#197)"
    assert by["cap_001"] == {"w-R_01 (sw)": {"ms": 0.1, "at": 4.7, "set": "cap_001"}}, \
        "cap_001's own, not moved (#197)"
    assert by["cap_002"] == {title: bank[title] for title in (
        "w-L_01 (sw)", "m-L_01 (sw)", "w-R_01 (sw)", "tw-L_01 (sw)")}
    assert set(by) == {"", "cap_001", "cap_002"}


def test_put_many_reads_the_store_once_and_writes_it_once(tmp_path, monkeypatch):
    """Counted where the store is read and written, not by the helper's name: since G10 C2 the one
    read is `update_values`'s own, strict, and `load` is not on the write path at all."""
    calls = {"read": 0, "write": 0}
    real_read, real_write = own_store.read_json, own_store.write_json

    def read_json(*args, **kwargs):
        calls["read"] += 1
        return real_read(*args, **kwargs)

    def write_json(*args, **kwargs):
        calls["write"] += 1
        return real_write(*args, **kwargs)

    monkeypatch.setattr(own_store, "read_json", read_json)
    monkeypatch.setattr(own_store, "write_json", write_json)

    delay_bank.put_many(_seven(), tmp_path, session="cap_001")

    assert calls == {"read": 1, "write": 1}
    assert delay_bank.seen(tmp_path) == {f"d{i}_01 (sw)" for i in range(7)}


def test_no_reading_is_no_write(tmp_path):
    path = _seeded(tmp_path)
    before = path.read_bytes()

    assert delay_bank.put_many([], tmp_path) == {"w-L_01 (sw)": 0.198, "m-L_01 (sw)": 0.4,
                                                  "sw_01 (sw)": 1.1, "w-R_01 (sw)": 0.1}
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
    real_update = project_settings.update_values
    monkeypatch.setattr(project_settings, "update_values",
                        lambda *args, **kwargs: writes.append(args) or real_update(*args, **kwargs))

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


# ---- a read that failed is never the read a write starts from (G10 C2, #177) ---------------------


def flaky_read_once(monkeypatch, store):
    """The store's FIRST read after this fails, as a Windows sharing violation, an AV or sync lock,
    or another TCC mid-write does (`PermissionError` 13); every later read is normal. The read is
    the one thing mocked here: a failure that lasts exactly one read cannot be made for real.
    Returns the count of reads it failed."""
    import pathlib

    real = pathlib.Path.read_bytes
    failed = []

    def read_bytes(self):
        if not failed and os.path.abspath(self) == os.path.abspath(store):
            failed.append(self)
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", read_bytes)
    return failed


def _two_series(folder):
    delay_bank.put("sub_01 (sw)", 1.5, folder, session="S1")
    delay_bank.put("m-L_01 (sw)", 0.0, folder, session="S1", allpass=Allpass(1, 80.0))
    delay_bank.put("w-L_01 (sw)", 0.2, folder, session="S2")
    return project_settings.path_for(folder)


_ONE_CHANGE = {
    "put": lambda folder: delay_bank.put("w-L_01 (sw)", 0.3, folder, session="S2"),
    "put_many": lambda folder: delay_bank.put_many(
        [delay_bank.Reading("w-L_01 (sw)", 0.3)], folder, session="S2"),
    "clear": lambda folder: delay_bank.clear(folder, session="S2"),
}


@pytest.mark.parametrize("change", sorted(_ONE_CHANGE))
def test_a_read_that_fails_once_writes_nothing_though_a_second_read_would_succeed(
        tmp_path, monkeypatch, app_log_told, change):
    """G10 C2: `put_many` and `clear` read the bank forgivingly — a store that could not be read
    came back `{}` — and then wrote through `set_value`, which read again. When the first read
    failed and the second did not, the write was the readings on screen and nothing else: every
    other driver, every other series and their all-passes gone, under a sentence saying TCC «will
    not write over it». One strict read now, and the write is that read plus the change."""
    store = _two_series(tmp_path)
    before = store.read_bytes()
    failed = flaky_read_once(monkeypatch, store)

    with pytest.raises(own_store.StoreUnreadable):
        _ONE_CHANGE[change](tmp_path)

    assert len(failed) == 1
    assert store.read_bytes() == before, "nothing written"
    assert len(app_log_told) == 1 and "TCC will not write over it" in app_log_told[0], app_log_told
    _ONE_CHANGE[change](tmp_path)  # the next one reads fine, and lands
    assert delay_bank.seen(tmp_path, session="S1") == {"sub_01 (sw)", "m-L_01 (sw)"}, "S1 kept"
    assert delay_bank.allpasses(tmp_path) == {"m-L_01 (sw)": Allpass(1, 80.0)}


# ---- the window's bank writes say a refusal by the one rule the window's writes keep (#177) ------


_OR_SAY = {
    "put_many_or_say": lambda folder: delay_bank.put_many_or_say(_seven(), folder, session="S1"),
    "clear_or_say": lambda folder: delay_bank.clear_or_say(folder, session="S1"),
}


@pytest.mark.parametrize("write", sorted(_OR_SAY))
def test_a_bank_write_for_the_window_says_a_store_it_cannot_read_once_and_returns(
        tmp_path, app_log_told, write):
    """Task 30's review, Minors 1 and 3: the window's rule for its own writes — a store that cannot
    be read was said where it was read, a write that failed is said once for this state of the
    file, and the window carries on (`project_settings.set_value_or_say`, R-bl) — was written a
    second time in the curve window for its steps, and its Clear had none: `delay_bank.clear`
    raised out of the slot. Both bank writes keep the one rule now. A folder where the store
    should be: every platform."""
    intact = _a_folder_where_the_store_is(tmp_path)

    assert _OR_SAY[write](tmp_path) is False
    assert _OR_SAY[write](tmp_path) is False

    assert intact(), "never written over"
    path = project_settings.path_for(tmp_path)
    assert len(app_log_told) == 1 and str(path) in app_log_told[0], app_log_told
    assert "could not be read" in app_log_told[0]


@pytest.mark.parametrize("write", sorted(_OR_SAY))
def test_a_bank_write_for_the_window_says_a_write_that_fails_once_and_returns(
        tmp_path, monkeypatch, app_log_told, write):
    """A full disk fails the write itself — the read before it is fine. Said once for this state of
    the file, however many steps fail, and the next write that lands is True."""
    path = _seeded(tmp_path)
    before = path.read_bytes()
    real_write, full = own_store.write_json, [True]

    def write_json(target, data):
        if full:
            raise OSError(28, "No space left on device")
        real_write(target, data)

    monkeypatch.setattr(own_store, "write_json", write_json)

    assert _OR_SAY[write](tmp_path) is False
    assert _OR_SAY[write](tmp_path) is False

    assert path.read_bytes() == before
    assert len(app_log_told) == 1, app_log_told
    assert str(path) in app_log_told[0] and "No space left on device" in app_log_told[0]
    full.clear()
    assert _OR_SAY[write](tmp_path) is True
    assert path.read_bytes() != before, "and that one landed"


# ---- what the bank cannot read is carried through a write, never erased by it (G10 M2, #177) -----


#: Entries this TCC cannot read: a delay that is not a number (a hand edit), and a filter of a kind
#: it does not know (a newer TCC's) — beside a field of the entry it has never heard of.
_UNREAD = {
    "c_01 (sw)": {"ms": "0.4 ms", "at": None, "set": "S1"},
    "sub_01 (sw)": {"ms": 1.5, "at": 9.6, "set": "S1", "apf": {"type": "APF3", "f": 60.0},
                    "note": "kept"},
}


def _fields(folder) -> dict:
    return json.loads(project_settings.path_for(folder).read_text(encoding="utf-8"))


def _stored(folder) -> dict:
    return _fields(folder)[delay_bank.KEY]


def test_a_step_carries_what_the_bank_cannot_read_through_unchanged(tmp_path):
    """G10 M2: the step re-wrote the whole bank from what `_parsed` read, and what it could not
    read went: the hand-edited delay skipped, the unknown filter read as none and written as
    none, the unknown field dropped — on the first step on any other driver, with no word. Every
    entry the readings do not touch is written back as it was read."""
    project_settings.set_value(tmp_path, delay_bank.KEY, _UNREAD)

    delay_bank.put_many([delay_bank.Reading("w-L_01 (sw)", 0.2)], tmp_path, session="S1")

    stored = _stored(tmp_path)
    assert {title: stored[title] for title in _UNREAD} == _UNREAD
    assert stored["w-L_01 (sw)"] == {"ms": 0.2, "at": None, "set": "S1"}


def test_the_entries_the_bank_cannot_read_are_named_with_why(tmp_path):
    """#208: the curve window keeps an on-screen driver whose entry it cannot read as it is, and
    says why — a delay that is not a number, a filter of a kind this TCC does not know — for the
    series asked, and for no other."""
    project_settings.set_value(tmp_path, delay_bank.KEY, {
        **_UNREAD, "w-L_01 (sw)": {"ms": 0.2, "at": None, "set": "S1"},
        "tw-L_01 (sw)": {"ms": "late", "set": "S2"}})

    odd = delay_bank.unread_entries(tmp_path, session="S1")

    assert set(odd) == {"c_01 (sw)", "sub_01 (sw)"}, odd
    assert odd["c_01 (sw)"][0] == "ms" and "0.4 ms" in odd["c_01 (sw)"][1]
    assert odd["sub_01 (sw)"][0] == "apf" and "APF3" in odd["sub_01 (sw)"][1]


def test_a_bare_entry_that_is_not_a_number_is_named_as_the_dict_form_is(tmp_path):
    """#208's group review: the first version wrote a bare number; a bare `"1,25"` (a decimal
    comma typed by hand) was skipped silently by `unread_entries`, so the curve window did not
    keep it and the next step wrote over it. Named as the dict form's delay is; a bare number
    that reads is no such entry."""
    project_settings.set_value(tmp_path, delay_bank.KEY, {
        "w-L_01 (sw)": "1,25", "w-R_01 (sw)": 0.4, "c_01 (sw)": "0.3"})

    odd = delay_bank.unread_entries(tmp_path, session="S1")

    assert set(odd) == {"w-L_01 (sw)"}, odd
    assert odd["w-L_01 (sw)"][0] == "ms" and "'1,25'" in odd["w-L_01 (sw)"][1]


def test_a_reading_that_keeps_the_filter_keeps_one_of_a_kind_it_cannot_read(tmp_path):
    """#208: a step that moves a driver's delay and leaves its filter (`allpass` not given) wrote
    the entry anew from what `_parsed` read, and a filter of a kind it does not know read as none
    went with it. Kept as it was read."""
    project_settings.set_value(tmp_path, delay_bank.KEY, _UNREAD)

    delay_bank.put_many([delay_bank.Reading("sub_01 (sw)", 1.7)], tmp_path, session="S1")

    stored = _stored(tmp_path)["sub_01 (sw)"]
    assert stored["ms"] == 1.7 and stored["apf"] == {"type": "APF3", "f": 60.0}, stored


def test_a_clear_of_one_series_carries_another_s_entries_it_cannot_read(tmp_path):
    """The same for Clear of one series: the other series' entries are kept as they were read, not
    as `_parsed` read them. This series' own go with it, read or not."""
    other = {title: {**entry, "set": "S2"} for title, entry in _UNREAD.items()}
    project_settings.set_value(tmp_path, delay_bank.KEY, {
        **other, "w-L_01 (sw)": {"ms": 0.2, "at": None, "set": "S1"},
        "tw-L_01 (sw)": {"ms": "late", "set": "S1"},
    })

    delay_bank.clear(tmp_path, session="S1")

    assert _stored(tmp_path) == other


# ---- one entry per (series, title) (#197, F-100 O4) -----------------------------------------------


_V113 = Path(__file__).parent / "fixtures" / "tcc-project-bank-v1.1.3.json"


def _from_v113(folder):
    """The store as TCC v1.1.3 left it: written by that version's `delay_bank` (one entry per
    title, the series a field of it), with one entry banked with no series."""
    folder.mkdir(parents=True, exist_ok=True)
    path = project_settings.path_for(folder)
    path.write_bytes(_V113.read_bytes())
    return path


def test_a_v113_bank_reads_every_reading_under_its_own_series(tmp_path):
    _from_v113(tmp_path)

    assert delay_bank.load(tmp_path, "cap_001") == {
        "w-L_01 (sw)": 0.198, "m-L_01 (sw)": 1.25, "c_01 (sw)": 0.4}
    assert delay_bank.references(tmp_path, "cap_001") == ["w-R_01 (sw)"]
    assert delay_bank.allpasses(tmp_path, "cap_001") == {"w-L_01 (sw)": Allpass(2, 250.0, 0.71)}
    assert delay_bank.load(tmp_path, "cap_002") == {"sub_01 (sw)": 1.5, "c_01 (sw)": 0.4}
    assert delay_bank.allpasses(tmp_path, "cap_002") == {"m-R_01 (sw)": Allpass(1, 80.0)}
    assert delay_bank.load(tmp_path, "cap_009") == {"c_01 (sw)": 0.4}, "no series: under every one"
    assert delay_bank.arrivals(tmp_path, "cap_001")["w-L_01 (sw)"] == 4.52


def test_a_v113_bank_loses_no_reading_to_a_step_under_the_next_series(tmp_path):
    """The bug, on the file a user has today: the next round (cap_003) banks the side on screen.
    Every earlier series still reads what it read, and the step stored the new shape — a list for
    a title two series hold — with every other entry as it was."""
    path = _from_v113(tmp_path)
    before = json.loads(path.read_text(encoding="utf-8"))
    readings = [delay_bank.Reading(title, 0.05 * i) for i, title in enumerate(
        ("w-L_01 (sw)", "w-R_01 (sw)", "c_01 (sw)", "sub_01 (sw)"))]

    delay_bank.put_many(readings, tmp_path, session="cap_003")

    for series in ("cap_001", "cap_002"):
        assert delay_bank.load(tmp_path, series) == {
            title: entry["ms"] for title, entry in before[delay_bank.KEY].items()
            if entry["set"] in (series, None) and entry["ms"]}, series
        assert delay_bank.seen(tmp_path, series) == {
            title for title, entry in before[delay_bank.KEY].items()
            if entry["set"] in (series, None)}, series
    assert delay_bank.allpasses(tmp_path, "cap_001") == {"w-L_01 (sw)": Allpass(2, 250.0, 0.71)}
    assert delay_bank.load(tmp_path, "cap_003") == {
        "w-R_01 (sw)": 0.05, "c_01 (sw)": 0.1, "sub_01 (sw)": 0.15}
    assert delay_bank.references(tmp_path, "cap_003") == ["w-L_01 (sw)"]
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["generator"] == "sdk:claude-opus-5", "the rest of the file is kept"
    was, bank, by = before[delay_bank.KEY], stored[delay_bank.KEY], stored[delay_bank.BY_SERIES]
    assert bank["w-L_01 (sw)"] == {"ms": 0.0, "at": None, "set": "cap_003"}, "v1.1.3's: latest"
    assert bank["m-L_01 (sw)"] == was["m-L_01 (sw)"], "untouched"
    assert by["cap_001"] == {title: was[title] for title in ("w-L_01 (sw)", "w-R_01 (sw)")}, \
        "what the step took KEY's place from, as it was read"
    assert by["cap_002"] == {"sub_01 (sw)": was["sub_01 (sw)"]}
    assert by[""] == {"c_01 (sw)": was["c_01 (sw)"]}, "no series: kept aside"


def test_an_entry_with_no_series_stays_for_the_others_when_one_series_touches_it(tmp_path):
    """#197's rule for an entry written before the scope: shown under every series with none of
    its own; touched under one, that one gets its own, starting from it (the arrival and the
    filter carry), and the one with no series stays for every other. A step with no series moves
    the one with no series, as it always has."""
    project_settings.set_value(tmp_path, delay_bank.KEY, {
        "w-L_01 (sw)": {"ms": 0.198, "at": 4.52, "set": None,
                        "apf": {"type": "APF1", "f": 80.0}}})

    delay_bank.put("w-L_01 (sw)", 0.3, tmp_path, session="A")

    assert delay_bank.load(tmp_path, "A") == {"w-L_01 (sw)": 0.3}
    assert delay_bank.arrivals(tmp_path, "A") == {"w-L_01 (sw)": 4.52}, "the arrival carried"
    assert delay_bank.allpasses(tmp_path, "A") == {"w-L_01 (sw)": Allpass(1, 80.0)}, "and the filter"
    assert delay_bank.load(tmp_path, "B") == {"w-L_01 (sw)": 0.198}, "not lost to B"

    delay_bank.put("w-L_01 (sw)", 0.25, tmp_path)

    assert delay_bank.load(tmp_path, "B") == {"w-L_01 (sw)": 0.25}, "no series: the shared one"
    assert delay_bank.load(tmp_path, "A") == {"w-L_01 (sw)": 0.3}, "A's own untouched"


def test_clear_takes_the_shown_series_and_the_entries_with_no_series_and_nothing_else(tmp_path):
    """Clear's meaning is kept (#197): the series shown, and the entries with no series, which are
    shown under it. Another series' entry of the same title stays — under the old per-title bank
    it could not have been there to stay. No series named: everything."""
    delay_bank.put("w-L_01 (sw)", 0.5, tmp_path, session="A")
    delay_bank.put("w-L_01 (sw)", 0.7, tmp_path, session="B")
    delay_bank.put("sub_01 (sw)", 1.5, tmp_path, session="B")
    delay_bank.put("c_01 (sw)", 0.4, tmp_path)

    delay_bank.clear(tmp_path, session="B")

    assert delay_bank.load(tmp_path, "A") == {"w-L_01 (sw)": 0.5}
    assert delay_bank.load(tmp_path, "B") == {}
    assert delay_bank.load(tmp_path, "C") == {}, "c_01, shown under B, went with it"
    a = {"w-L_01 (sw)": {"ms": 0.5, "at": None, "set": "A"}}
    assert _stored(tmp_path) == a, "A's back in v1.1.3's field: a roll back reads it under A"
    assert _fields(tmp_path)[delay_bank.BY_SERIES] == {"A": a}

    delay_bank.clear(tmp_path)

    assert delay_bank.KEY not in json.loads(
        project_settings.path_for(tmp_path).read_text(encoding="utf-8"))


def test_what_one_series_cannot_read_is_named_for_it_alone_and_carried_through_the_other(tmp_path):
    """#208 per series: a title two series hold, A's entry a hand edit. Named for A, not for B; a
    step under B writes B's entry and carries A's exactly as it was read."""
    odd = {"ms": "0,5", "at": None, "set": "A", "note": "kept"}
    b = {"ms": 0.7, "at": None, "set": "B"}
    project_settings.set_value(tmp_path, delay_bank.KEY, {"w-L_01 (sw)": b})
    project_settings.set_value(tmp_path, delay_bank.BY_SERIES, {
        "A": {"w-L_01 (sw)": odd}, "B": {"w-L_01 (sw)": b}})

    assert set(delay_bank.unread_entries(tmp_path, "A")) == {"w-L_01 (sw)"}
    assert delay_bank.unread_entries(tmp_path, "B") == {}

    delay_bank.put("w-L_01 (sw)", 0.8, tmp_path, session="B")

    by = _fields(tmp_path)[delay_bank.BY_SERIES]
    assert by["A"] == {"w-L_01 (sw)": odd}, "A's as it was read"
    assert by["B"] == {"w-L_01 (sw)": {"ms": 0.8, "at": None, "set": "B"}}


@pytest.mark.parametrize("field", [["w-L_01 (sw)", 0.198], "w-L_01 (sw)=0.198", 3],
                         ids=["list", "text", "number"])
def test_a_bank_of_a_shape_this_tcc_does_not_know_is_refused_never_written_over(
        tmp_path, app_log_told, field):
    """A newer TCC's bank, or a hand edit: not a map of titles. A plain read is «nothing banked»;
    a strict read, a step and a Clear refuse it, and the file keeps its bytes. Said once."""
    project_settings.set_value(tmp_path, delay_bank.KEY, field)
    path = project_settings.path_for(tmp_path)
    before = path.read_bytes()

    assert delay_bank.load(tmp_path, "A") == {}
    for refused in (lambda: delay_bank.load(tmp_path, "A", strict=True),
                    lambda: delay_bank.unread_entries(tmp_path, "A"),
                    lambda: delay_bank.put("w-L_01 (sw)", 0.3, tmp_path, session="A"),
                    lambda: delay_bank.clear(tmp_path, session="A"),
                    lambda: delay_bank.clear(tmp_path)):
        with pytest.raises(delay_bank.BankShapeUnknown):
            refused()
    assert delay_bank.put_many_or_say(_seven(), tmp_path, session="A") is False
    assert delay_bank.clear_or_say(tmp_path, session="A") is False

    assert path.read_bytes() == before, "never written over"
    told = [line for line in app_log_told if "delay bank" in line]
    assert len(told) == 1 and "not a shape this TCC reads" in told[0], app_log_told


# ---- #197's review: what a Clear, a step with no series and a roll back to v1.1.3 must not lose --


def test_clear_under_a_series_keeps_a_reading_with_no_series_that_series_no_longer_shows(tmp_path):
    """#197's review, I1 (probe P1): touched under A, the entry with no series stays for B; a
    Clear under A took it from B as well, though A showed its own. Only what A shows goes."""
    project_settings.set_value(tmp_path, delay_bank.KEY, {
        "w-L_01 (sw)": {"ms": 0.198, "at": None, "set": None}})
    delay_bank.put("w-L_01 (sw)", 0.3, tmp_path, session="A")

    delay_bank.clear(tmp_path, session="A")

    assert delay_bank.load(tmp_path, "A") == {"w-L_01 (sw)": 0.198}, "A's own gone: shown again"
    assert delay_bank.load(tmp_path, "B") == {"w-L_01 (sw)": 0.198}, "B keeps it"


def test_a_step_with_no_series_writes_the_entry_with_no_series_never_a_series_own(tmp_path):
    """#197's review, M2 (probe P5): with no series named — a series provider missing or raising —
    a step wrote into the last series' own entry. Which series was meant is not known: it writes
    the entry with no series, and every series' own stays."""
    delay_bank.put("w-L_01 (sw)", 0.5, tmp_path, session="A")
    delay_bank.put("w-L_01 (sw)", 0.7, tmp_path, session="B")

    delay_bank.put("w-L_01 (sw)", 0.9, tmp_path)

    assert delay_bank.load(tmp_path, "A") == {"w-L_01 (sw)": 0.5}
    assert delay_bank.load(tmp_path, "B") == {"w-L_01 (sw)": 0.7}
    assert delay_bank.load(tmp_path, "C") == {"w-L_01 (sw)": 0.9}, "no series: under every other"
    assert delay_bank.load(tmp_path) == {"w-L_01 (sw)": 0.9}
    assert _stored(tmp_path) == {"w-L_01 (sw)": {"ms": 0.9, "at": None, "set": None}}


def _v113_step(folder, readings, series):
    """A step of TCC v1.1.3 (`git show v1.1.3:src/autosound_tcc/core/delay_bank.py`, `put_many`):
    `KEY` alone — each title's one entry replaced, its arrival and filter kept, the series set —
    and every other field of the file left as it was."""
    def change(raw):
        bank = dict(raw or {})
        for title, ms in readings:
            was = bank.get(title) if isinstance(bank.get(title), dict) else {}
            bank[title] = {"ms": ms, "at": was.get("at"), "set": series,
                           **({"apf": was["apf"]} if was.get("apf") else {})}
        return bank
    project_settings.update_value(folder, delay_bank.KEY, change)


def _v113_clear(folder, series):
    """v1.1.3's Clear of one series: `KEY` keeps the entries of another series, and nothing else."""
    project_settings.update_value(folder, delay_bank.KEY, lambda raw: {
        title: value for title, value in (raw or {}).items()
        if isinstance(value, dict) and value.get("set") is not None
        and str(value["set"]) != series} or None)


def _three_series(folder):
    delay_bank.put_many([delay_bank.Reading("w-L_01 (sw)", 0.5),
                         delay_bank.Reading("w-R_01 (sw)", 0.2)], folder, session="A")
    delay_bank.put("w-L_01 (sw)", 0.7, folder, session="B")


def test_v113_reads_the_latest_reading_of_each_title_as_it_always_did(tmp_path):
    """#197's review, I3: `KEY` stays v1.1.3's own field, kept current on every step — a TCC
    rolled back reads each title's latest reading under the series it was banked in."""
    _three_series(tmp_path)

    assert _stored(tmp_path) == {"w-L_01 (sw)": {"ms": 0.7, "at": None, "set": "B"},
                                 "w-R_01 (sw)": {"ms": 0.2, "at": None, "set": "A"}}


def test_a_v113_step_after_a_roll_back_loses_no_series_reading_on_the_way_back(tmp_path):
    """#197's review, I3 (probe P2): v1.1.3 writes `KEY` alone. Its step under another series
    replaces each title's entry there; back on this TCC every series still reads its own, and the
    series v1.1.3 banked under reads what it banked."""
    _three_series(tmp_path)

    _v113_step(tmp_path, [("w-L_01 (sw)", 0.0), ("w-R_01 (sw)", 0.3)], "C")

    assert delay_bank.load(tmp_path, "A") == {"w-L_01 (sw)": 0.5, "w-R_01 (sw)": 0.2}
    assert delay_bank.load(tmp_path, "B") == {"w-L_01 (sw)": 0.7}
    assert delay_bank.load(tmp_path, "C") == {"w-R_01 (sw)": 0.3}
    assert delay_bank.references(tmp_path, "C") == ["w-L_01 (sw)"]

    delay_bank.put("w-L_01 (sw)", 0.6, tmp_path, session="A")  # this TCC, the next step

    assert delay_bank.load(tmp_path, "C") == {"w-R_01 (sw)": 0.3}, "v1.1.3's kept in C's own"
    assert delay_bank.references(tmp_path, "C") == ["w-L_01 (sw)"]
    assert delay_bank.load(tmp_path, "A") == {"w-L_01 (sw)": 0.6, "w-R_01 (sw)": 0.2}
    assert delay_bank.load(tmp_path, "B") == {"w-L_01 (sw)": 0.7}


def test_a_v113_step_under_a_series_is_that_series_latest(tmp_path):
    """The rule for a series whose own entry is older than `KEY`'s: `KEY`'s, banked under that
    series, wins — this TCC writes both on every step, so a `KEY` entry of that series that
    differs from its own was written since, by v1.1.3. The own one is not dropped: it is the
    older reading of the same series, and the next step of this TCC writes over both."""
    _three_series(tmp_path)

    _v113_step(tmp_path, [("w-R_01 (sw)", 0.25)], "A")

    assert delay_bank.load(tmp_path, "A") == {"w-L_01 (sw)": 0.5, "w-R_01 (sw)": 0.25}
    assert delay_bank.load(tmp_path, "B") == {"w-L_01 (sw)": 0.7}


def test_a_v113_clear_after_a_roll_back_touches_v113_s_field_alone(tmp_path):
    """v1.1.3's Clear keeps `KEY`'s entries of other series and drops the rest; the per-series
    field is not its own. So a Clear made there does not reach a series' own readings: on the
    way back they are there again — kept rather than lost, and a Clear here takes them."""
    _three_series(tmp_path)

    _v113_clear(tmp_path, "A")

    assert _stored(tmp_path) == {"w-L_01 (sw)": {"ms": 0.7, "at": None, "set": "B"}}
    assert delay_bank.load(tmp_path, "B") == {"w-L_01 (sw)": 0.7}
    assert delay_bank.load(tmp_path, "A") == {"w-L_01 (sw)": 0.5, "w-R_01 (sw)": 0.2}

    delay_bank.clear(tmp_path, session="A")

    assert delay_bank.seen(tmp_path, "A") == set()
    assert delay_bank.load(tmp_path, "B") == {"w-L_01 (sw)": 0.7}
