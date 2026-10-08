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

from pathlib import Path
from typing import Any, Optional

from autosound_tcc.core import own_store

FILENAME = "tcc-project.json"
SCHEMA_VERSION = 1


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


def get(tcc_dir: Path, key: str, default: Optional[str] = None) -> Optional[str]:
    value = load(tcc_dir).get(key)
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
