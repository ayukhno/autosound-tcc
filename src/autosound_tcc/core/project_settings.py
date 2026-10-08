"""TCC's own per-project settings — `<project>/.tcc/tcc-project.json`.

A project is not just a folder. Which models drive it is a property of the project, not of the
person: a Helix build being tuned for competition and a scratch folder for reproducing a bug want
different generators, and remembering one globally means opening the second silently changes the
first. So the choice travels with the project.

What deliberately stays global (`QSettings`, user scope) is *which omp models this machine can
reach* — that is a fact about the user's accounts and their PATH, not about any project, and
copying it into every folder would mean editing all of them when a subscription changes.

Not `project.json`: the skill owns that name at the project root (SCR-011), and TCC does not write
the skill's files. This is TCC's own, next to the rest of its state in `.tcc/`, and the skill is
free to ignore it.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, NamedTuple, Optional

from autosound_tcc.core import own_store

FILENAME = "tcc-project.json"
SCHEMA_VERSION = 1

#: The fields a person picks — the gate, the effort, the two models (the window's `_GATE_KEY`,
#: `_EFFORT_KEY`, `_GENERATOR_KEY`, `_CRITIC_KEY`). One whose write did not land is in force for
#: the rest of the run all the same (#173, I2): the window reads them back from the store — the
#: gate at every permission, the effort at every session start — so a pick that did not reach it
#: had no effect at all. `always_allowed` is not one: a tick that did not land asks again, which
#: is the safe way to be wrong (the review of Task 17, N1).
HELD_FOR_THE_RUN = frozenset({"gate", "effort", "generator", "critic"})

#: The picks that did not land, `{(absolute store path, key): value}`, for this run (`pick`).
_held: dict[tuple[str, str], Any] = {}
_held_lock = threading.Lock()
_NOT_HELD = object()


def path_for(tcc_dir: Path) -> Path:
    return Path(tcc_dir) / FILENAME


def load(tcc_dir: Path) -> dict[str, Any]:
    """Whatever is on disk, or an empty dict — never an exception.

    A project that has never been opened has no settings, and that is not news. A file that cannot
    be read is (#173): `own_store` sets a broken one aside with its bytes and says so, and says so
    about one it may not open. For a reader both still come back as "no preference" rather than
    take the window down. A write must not do the same — see `set_value`.
    """
    try:
        return own_store.read_json(path_for(tcc_dir))
    except own_store.StoreUnreadable:
        return {}


def get(tcc_dir: Path, key: str, default: Optional[str] = None, *,
        strict: bool = False) -> Optional[str]:
    """One scalar field: a pick held for this run first (`pick`), else what the store holds.

    `strict` is for a reader to whom a store that is there and cannot be read is not «no
    preference»: it raises `StoreUnreadable` instead of answering `default` — the gate, which
    then runs on the strictest mode (R-bt). Absent, or broken and set aside, answers `default`
    either way: there is nothing more to know."""
    with _held_lock:
        value = _held.get(_slot(tcc_dir, key), _NOT_HELD)
    if value is _NOT_HELD:
        value = (own_store.read_json(path_for(tcc_dir)) if strict else load(tcc_dir)).get(key)
    return str(value) if isinstance(value, (str, int, float)) else default


def set_value(tcc_dir: Path, key: str, value: Any = None) -> None:
    """Write one field, keeping the rest. Atomic, and on the disk before it takes the name.

    `value` is usually a string (a model key, a language). It may be any JSON-serialisable thing —
    `core/delay_bank.py` keeps a `{title: ms}` mapping here — but the reader is the caller's
    problem then: `get()` deliberately returns only scalars, so a structured value needs its own
    accessor rather than a cast at every call site. `None` removes the field.

    Read through `own_store.read_json`, not `load()`: a file that is there and cannot be read
    raises `StoreUnreadable` out of here instead of coming back as `{}` — and that `{}`, written
    back with one field in it, was every model choice, tick, delay and import answer gone (#173,
    F5). A broken file has been set aside, bytes and all, by the time this writes a fresh one.

    Write-then-rename (`own_store.write_json`) rather than write-in-place: this is touched on model
    changes, which can happen while a session is mid-turn, and a half-written settings file would
    read as "no preference" on the next launch -- silently forgetting what the user chose.
    """
    target = path_for(tcc_dir)
    data = own_store.read_json(target)
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    data["schema_version"] = SCHEMA_VERSION
    own_store.write_json(target, data)
    with _held_lock:
        _held.pop(_slot(tcc_dir, key), None)  # on the disk now: what was held is no longer news


def set_value_or_say(tcc_dir: Path, key: str, value: Any = None) -> bool:
    """`set_value` for the window, which must not be stopped by its own settings file.

    True when written, False when not — and then said, once for this state of the file:
    a store that is there and cannot be read has been said by `own_store` when it was read, and
    a write that failed (a read-only `.tcc/`, a full disk) is said here (R-bl). The window writes
    from slots and from `closeEvent`, and either failure raised there skipped the rest of the
    slot, or the whole orderly quit — the session's stop, the workers, the agent's thread — on
    every quit while it lasted (the review of Task 17). `set_value` itself still raises (R-l): a
    caller outside the window decides.
    """
    try:
        set_value(tcc_dir, key, value)
    except own_store.StoreUnreadable:
        return False
    except OSError as exc:
        own_store.say_unwritten(path_for(tcc_dir), exc)
        return False
    return True


class Picked(NamedTuple):
    """`pick`'s answer: whether the write landed, and whether the window has a pick to say."""

    landed: bool
    say: bool


def pick(tcc_dir: Path, key: str, value: Any = None) -> Picked:
    """A field the person picked, written by `set_value_or_say` — and, for one of
    `HELD_FOR_THE_RUN` that did not land, held in force for the rest of the run: `get` answers it
    before the store (#173, I2). `say` is True when such a pick is new — not for the same value
    picked again, nor for one picker answering twice for one choice — and the window then says
    it as a Save does (`why_not_saved`): the store's report was spent, likely at launch, and a
    pick is the person asking. Never raises, as `set_value_or_say` does not."""
    landed = set_value_or_say(tcc_dir, key, value)
    if landed or key not in HELD_FOR_THE_RUN:
        return Picked(landed, False)
    with _held_lock:
        new = _held.get(_slot(tcc_dir, key), _NOT_HELD) != value
        _held[_slot(tcc_dir, key)] = value
    return Picked(False, new)


def held(tcc_dir: Path, key: str) -> Optional[str]:
    """The pick held for the run for `key` because its write did not land (`pick`), or None when
    nothing is held. For a Save, which lands a held gate with the pickers (the re-review, O3): no
    picker re-asserts the gate, so one picked while the store was out stayed off the disk."""
    with _held_lock:
        value = _held.get(_slot(tcc_dir, key))
    return str(value) if isinstance(value, (str, int, float)) else None


def _slot(tcc_dir: Path, key: str) -> tuple[str, str]:
    return os.path.abspath(path_for(tcc_dir)), key


def why_not_saved(tcc_dir: Path) -> str:
    """What keeps this project's settings off the disk, for a Save that did not land: the
    sentence said about the file, said again because a Save is the person asking (the re-review
    of Task 17) — or, when nothing stands, just the file's path."""
    path = path_for(tcc_dir)
    return own_store.said_about(path) or str(path)
