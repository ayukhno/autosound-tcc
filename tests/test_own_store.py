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
        with pytest.raises(own_store.StoreUnreadable) as refused:
            own_store.read_json(store)

    assert not isinstance(refused.value, own_store.StoreNotSetAside), (
        "not read at all: not the broken store whose move was refused (N2)")
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


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0,
                    reason="POSIX permissions, and root reads a file whatever its mode")
def test_a_store_made_unreadable_again_is_said_again(store, app_log_told):
    """`chmod` moves neither the size nor the mtime, so a store said unreadable, read fine after a
    fix and made unreadable again was the same state and never said again; a mode change while
    it stays unreadable was not either (the review of Task 17, Minor 2)."""
    store.write_text('{"generator": "sdk:claude-opus-5"}', encoding="utf-8")
    try:
        for mode in (0, 0o600, 0, 0o200):
            store.chmod(mode)
            if mode & 0o400:
                assert own_store.read_json(store) == {"generator": "sdk:claude-opus-5"}
            else:
                with pytest.raises(own_store.StoreUnreadable):
                    own_store.read_json(store)
    finally:
        store.chmod(0o600)

    assert len(app_log_told) == 3, app_log_told


def test_two_processes_setting_one_store_aside_in_one_second_keep_both_copies(store,
                                                                              monkeypatch):
    """Naming was look-then-rename: the window and the CLI setting one store aside in the same
    second could both find a name free, and on POSIX the second rename replaced the first copy
    (the review of Task 17, Minor 3). Here the other process sets its copy aside the moment
    before this one moves — by the same rule: exclusive creation, `-2` on a taken name — and
    both copies are kept."""
    monkeypatch.setattr(own_store, "_stamp", lambda: "20261008-153012")
    names = [store.parent / "store.json.corrupt-20261008-153012",
             store.parent / "store.json.corrupt-20261008-153012-2"]
    store.write_bytes(b"{ ours")

    def the_other_process_first(real):
        def move(src, dst, *args, **kwargs):
            for name in names:
                try:
                    with open(name, "xb") as theirs:
                        theirs.write(b"{ theirs")
                    break
                except FileExistsError:
                    continue
            return real(src, dst, *args, **kwargs)
        return move

    for verb in ("rename", "replace"):
        monkeypatch.setattr(own_store.os, verb, the_other_process_first(getattr(os, verb)))

    assert own_store.read_json(store) == {}

    assert sorted(p.read_bytes() for p in store.parent.iterdir()) == [b"{ ours", b"{ theirs"]


def test_a_broken_store_that_cannot_be_moved_is_refused_and_leaves_no_name_behind(
        store, monkeypatch, app_log_told):
    """A broken file is only safe to start afresh once it is out of the way. When the move is
    refused, it is the unreadable case: said, refused, never written over — and the aside name
    reserved for it is given back. Refused as `StoreNotSetAside`, a `StoreUnreadable` of its own
    kind: the file was read, so the advice for one that could not be opened is not its (N2)."""
    store.write_bytes(b"{ broken")

    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(own_store.os, "rename", refuse)
    monkeypatch.setattr(own_store.os, "replace", refuse)
    for _ in range(2):
        with pytest.raises(own_store.StoreNotSetAside):
            own_store.read_json(store)

    assert _left(store) == ["store.json"] and store.read_bytes() == b"{ broken"
    assert len(app_log_told) == 1 and str(store) in app_log_told[0], app_log_told


def test_a_store_saved_with_a_byte_order_mark_is_read_not_set_aside(store, app_log_told):
    """Older Windows Notepad saves UTF-8 with a BOM, and `json.loads` refuses one: a settings file
    edited there was set aside and the settings restarted empty (the review of Task 17, Minor 4)."""
    store.write_bytes(b'\xef\xbb\xbf{"generator": "sdk:claude-opus-5"}')

    assert own_store.read_json(store) == {"generator": "sdk:claude-opus-5"}
    assert _left(store) == ["store.json"] and app_log_told == []


def test_a_store_its_owner_calls_misshapen_is_set_aside_like_a_broken_one(store, app_log_told):
    """Valid JSON and an object, but not what its owner can read — `sessions.json` holding
    `"phases": []` (the review of Task 18, Minor 1): the owner's code tripped over it on every
    read and nothing was said. The owner's `misshapen` says why, and the store goes the broken
    way: set aside with its bytes, said once with the reason, `{}` back. A store it finds well
    shaped is read as it is."""
    body = b'{"phases": []}'
    store.write_bytes(body)

    def misshapen(data):
        return "" if isinstance(data.get("phases", {}), dict) else '"phases" is not an object'

    assert own_store.read_json(store, misshapen=misshapen) == {}
    assert own_store.read_json(store, misshapen=misshapen) == {}, "nothing more to say"

    left = _left(store)
    assert len(left) == 1 and _ASIDE.fullmatch(left[0]), left
    assert (store.parent / left[0]).read_bytes() == body, "the original bytes are kept"
    assert len(app_log_told) == 1 and '"phases" is not an object' in app_log_told[0], app_log_told
    store.write_bytes(b'{"phases": {}}')
    assert own_store.read_json(store, misshapen=misshapen) == {"phases": {}}


def test_a_broken_store_is_set_aside_into_the_folder_it_is_given(store, tmp_path, app_log_told):
    """R-k: `aside_dir` puts the copy there instead of beside the store, and makes the folder when
    it is not there yet. `.mcp.json` needs it (ruling 9): git ignores that file by its exact name,
    so a `.mcp.json.corrupt-…` beside it would travel with the project, carrying the old token —
    `.tcc/` is ignored whole. The sentence names the copy's whole path: its name alone would send
    the person to look beside the store."""
    elsewhere = tmp_path / "elsewhere" / "deeper"
    store.write_bytes(b"{ broken")

    assert own_store.read_json(store, aside_dir=elsewhere) == {}

    assert _left(store) == [], "nothing beside the store: neither the copy nor a reserved name"
    kept = list(elsewhere.iterdir())
    assert len(kept) == 1 and _ASIDE.fullmatch(kept[0].name), kept
    assert kept[0].read_bytes() == b"{ broken", "the original bytes are kept"
    assert len(app_log_told) == 1, app_log_told
    assert str(store) in app_log_told[0] and str(kept[0]) in app_log_told[0], app_log_told


def test_a_store_whose_aside_folder_cannot_be_made_is_refused_and_left_where_it_is(
        store, tmp_path, app_log_told):
    """A broken file is only safe to start afresh once it is out of the way. A file where the
    aside folder should be is a move that cannot happen: the unreadable case — said, refused,
    and never written over."""
    blocked = tmp_path / "blocked"
    blocked.write_text("a file, where the folder should be", encoding="utf-8")
    store.write_bytes(b"{ broken")

    with pytest.raises(own_store.StoreNotSetAside):
        own_store.read_json(store, aside_dir=blocked)

    assert _left(store) == ["store.json"] and store.read_bytes() == b"{ broken"
    assert len(app_log_told) == 1 and str(store) in app_log_told[0], app_log_told


def test_a_shape_check_that_raises_reads_as_a_misshapen_store(store, app_log_told):
    """R-bn: the owner's `misshapen` is code, and code trips — on the very shapes it is there to
    catch. Its exception escaped past every reader of the store. It now reads as a shape the
    owner cannot read: set aside with its bytes, said once, the exception named in the reason."""
    body = b'{"phases": []}'
    store.write_bytes(body)

    def misshapen(data):  # assumes the outer shape: a list has no `.values()`
        return "" if all(isinstance(p, dict) for p in data["phases"].values()) else "a bad phase"

    assert own_store.read_json(store, misshapen=misshapen) == {}
    assert own_store.read_json(store, misshapen=misshapen) == {}, "nothing more to say"

    left = _left(store)
    assert len(left) == 1 and _ASIDE.fullmatch(left[0]), left
    assert (store.parent / left[0]).read_bytes() == body, "the original bytes are kept"
    assert len(app_log_told) == 1 and "AttributeError" in app_log_told[0], app_log_told


@pytest.mark.parametrize("error", [TypeError, AttributeError, KeyError, IndexError, ValueError,
                                   RecursionError], ids=lambda error: error.__name__)
def test_a_shape_check_that_trips_on_the_shape_logs_where(store, app_log_told, app_log_warnings,
                                                          error):
    """R-bo (the review of Task 19, M1): what a look inside an object trips on when the shape is
    not the one it assumed reads as misshapen — set aside, said once, the type in the reason. The
    reason keeps only `Type: text`, so the traceback goes to the log: the line the check tripped
    on is what its owner needs."""
    body = b'{"phases": []}'
    store.write_bytes(body)

    def misshapen(data):
        raise error("tripped")

    assert own_store.read_json(store, misshapen=misshapen) == {}

    left = _left(store)
    assert len(left) == 1 and (store.parent / left[0]).read_bytes() == body, left
    assert len(app_log_told) == 1 and error.__name__ in app_log_told[0], app_log_told
    assert any(r.exc_info and r.exc_info[0] is error for r in app_log_warnings), (
        "the traceback is logged")


@pytest.mark.parametrize("error", [NameError, ImportError, MemoryError],
                         ids=lambda error: error.__name__)
def test_a_shape_check_failing_for_reasons_of_its_own_is_not_the_store_s_shape(
        store, app_log_told, error):
    """R-bo (the review of Task 19, M1): a bug in the check itself, a module it could not import,
    a machine out of memory — none says anything about the store, which an owner whose check
    works reads fine. Taken for a shape, it moved a good store aside and kept only `Type: text`.
    It goes up instead, and the store stays where it is."""
    body = b'{"phases": {}}'
    store.write_bytes(body)

    def misshapen(data):
        raise error("not about the store")

    with pytest.raises(error):
        own_store.read_json(store, misshapen=misshapen)

    assert _left(store) == ["store.json"] and store.read_bytes() == body, "left where it is"
    assert app_log_told == [], "and nothing said about it"


def test_a_store_nested_too_deep_to_parse_is_broken_json(store, app_log_told):
    """R-bn: `json.loads` answers nesting deeper than the interpreter can follow with
    `RecursionError`, not a `ValueError`, so it escaped past every reader. Bytes the parser cannot
    read are broken JSON: set aside with their bytes, said once."""
    depth = 100_000  # Python 3.12 parses 5 000 and gives up before 20 000
    body = b'{"phases": ' + b"[" * depth + b"]" * depth + b"}"
    store.write_bytes(body)

    assert own_store.read_json(store) == {}
    assert own_store.read_json(store) == {}, "nothing more to say"

    left = _left(store)
    assert len(left) == 1 and _ASIDE.fullmatch(left[0]), left
    assert (store.parent / left[0]).read_bytes() == body, "the original bytes are kept"
    assert len(app_log_told) == 1 and str(store) in app_log_told[0], app_log_told
