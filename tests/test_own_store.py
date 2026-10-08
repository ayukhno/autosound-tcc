"""TCC's own stores: one that cannot be read is set aside and said, never written over (#173).

Each store used to answer `{}` for a missing file, a broken one and one it could not open alike,
and the next write put that `{}` back with one field in it — every other field gone, and nothing
said (F5). `own_store` tells the three apart; these hold it to that on real files.
"""

from __future__ import annotations

import json
import os
import re

import pytest

from autosound_tcc.core import own_store

#: `<name>.corrupt-<YYYYMMDD-HHMMSS>`, beside the store.
_ASIDE = re.compile(r"store\.json\.corrupt-\d{8}-\d{6}")


@pytest.fixture
def store(tmp_path):
    """A store in a folder of its own: the autouse fixtures put a `project/` into `tmp_path`."""
    folder = tmp_path / "own"
    folder.mkdir()
    return folder / "store.json"


def _left(store) -> list[str]:
    return sorted(p.name for p in store.parent.iterdir())


def test_a_store_that_is_not_there_is_empty_and_nothing_is_said(store, app_log_told,
                                                                app_log_errors):
    """A project nobody has opened has no settings yet: the ordinary state, not news."""
    assert own_store.read_json(store) == {}
    assert _left(store) == [], "nothing moved, nothing made"
    assert app_log_told == [] and app_log_errors == []


@pytest.mark.parametrize("broken", [
    b'{\n  "generator": "sdk:claude-opus-5",\n}\n',
    b'{"generator": "\xff"}',
    b'["generator", "sdk:claude-opus-5"]',
], ids=["trailing-comma", "not-utf8", "not-an-object"])
def test_a_broken_store_is_set_aside_with_its_bytes_and_said_once(store, broken, app_log_told,
                                                                  app_log_errors):
    store.write_bytes(broken)

    assert own_store.read_json(store) == {}
    assert own_store.read_json(store) == {}, "a second read finds nothing more to say"

    left = _left(store)
    assert len(left) == 1 and _ASIDE.fullmatch(left[0]), left
    assert (store.parent / left[0]).read_bytes() == broken, "the original bytes are kept"
    assert not store.exists(), "so the next write starts a fresh file"
    assert len(app_log_told) == 1, app_log_told
    assert str(store) in app_log_told[0] and left[0] in app_log_told[0], (
        "it names the store and where the old one went")
    assert [r.getMessage() for r in app_log_errors] == app_log_told, "the same sentence, logged"


def test_a_second_broken_store_in_the_same_second_keeps_the_first_one(store, monkeypatch):
    """The stamp is to the second. A second broken file within it must not take the first one's
    place: the point of setting a file aside is that its bytes are still there."""
    monkeypatch.setattr(own_store, "_stamp", lambda: "20261008-153012")
    store.write_bytes(b"{ first")
    own_store.read_json(store)
    store.write_bytes(b"{ second")
    own_store.read_json(store)

    assert _left(store) == ["store.json.corrupt-20261008-153012",
                            "store.json.corrupt-20261008-153012-2"]
    assert (store.parent / "store.json.corrupt-20261008-153012").read_bytes() == b"{ first"
    assert (store.parent / "store.json.corrupt-20261008-153012-2").read_bytes() == b"{ second"


def test_a_store_that_cannot_be_opened_is_refused_said_once_and_left_where_it_is(store,
                                                                                app_log_told):
    """There, and not readable: a folder where the file should be is refused on every platform
    (`IsADirectoryError` on POSIX, `PermissionError` on Windows). Bytes behind a refusal like that
    may be perfectly good, so nothing is moved — and the read is said once per state of the file,
    not on every read: a store is read on every tool call."""
    store.mkdir()
    (store / "inside").write_text("kept", encoding="utf-8")

    for _ in range(3):
        with pytest.raises(own_store.StoreUnreadable):
            own_store.read_json(store)

    assert len(app_log_told) == 1 and str(store) in app_log_told[0], app_log_told
    assert _left(store) == ["store.json"], "nothing set aside"
    assert (store / "inside").read_text(encoding="utf-8") == "kept"


def test_a_write_is_on_the_disk_before_it_takes_the_name(store, monkeypatch):
    """A rename is atomic, but without the fsync the name can reach the disk before the bytes it
    names, and a power cut then leaves an empty store under it. So: written and flushed (the size
    is in the file when it is synced), synced, and only then renamed over the store."""
    calls = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd):
        calls.append(("fsync", os.fstat(fd).st_size))
        real_fsync(fd)

    def replace(src, dst, *args, **kwargs):
        calls.append(("replace", os.path.dirname(os.fspath(src)), os.fspath(dst)))
        real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(own_store.os, "fsync", fsync)
    monkeypatch.setattr(own_store.os, "replace", replace)

    own_store.write_json(store, {"generator": "sdk:claude-opus-5"})

    assert calls == [("fsync", store.stat().st_size), ("replace", str(store.parent), str(store))]
    assert json.loads(store.read_text(encoding="utf-8")) == {"generator": "sdk:claude-opus-5"}
    assert _left(store) == ["store.json"], "and no temp file is left beside it"
