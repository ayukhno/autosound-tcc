"""What this machine says about models, so an install survives a generation it was not built for.

Every model name TCC or the skill ever wrote down — a project's chosen Generator, a journal entry,
a prescribed default — is a name that will one day stop existing. Shipping a new list is one answer
and it needs somebody to ship it; this is the other half, owned by the installation itself:

    aliases   "everything that asks for X, run Y instead"
    added     a model a catalogue does not report but this machine can run
    hidden    a model this machine should stop offering

**The alias is the load-bearing one.** It reaches the names TCC cannot go back and edit: what is
stored in a project's settings, what the skill prescribes, what a journal entry from March refers
to. One indirection, applied at the moment of use, and every stale reference follows.

Nobody is expected to write this file by hand. It fills itself from the picker: when a stored
choice is no longer offered, TCC says so and offers a replacement, and the replacement is recorded
here — which is the difference between a config file and a mechanism that actually gets used.

Machine-scoped, not project-scoped: which models exist is a fact about this computer and its
logins, while WHICH ONE a project uses is already stored per project.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1
#: Guard against `a -> b -> a`. Hand-edited files can contain one, and a resolver that loops is a
#: window that never opens.
_MAX_ALIAS_HOPS = 8


def config_dir() -> Path:
    """`$AUTOSOUND_TCC_CONFIG_DIR`, else `$XDG_CONFIG_HOME/autosound-tcc`, else `~/.config/…`."""
    explicit = os.environ.get("AUTOSOUND_TCC_CONFIG_DIR")
    if explicit:
        return Path(explicit).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "autosound-tcc"


def overrides_path() -> Path:
    return config_dir() / "models.json"


def load() -> dict:
    """The file, or an empty shape. A malformed file reads as empty rather than as an error.

    Deliberately forgiving: this is the file that keeps a machine working when a model retires, so
    a typo in it must not be the thing that stops the app from opening. Its absence is the normal
    state of most installs.
    """
    try:
        data = json.loads(overrides_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema_version": SCHEMA_VERSION, "aliases": {}, "added": [], "hidden": []}
    if not isinstance(data, dict):
        return {"schema_version": SCHEMA_VERSION, "aliases": {}, "added": [], "hidden": []}
    data.setdefault("aliases", {})
    data.setdefault("added", [])
    data.setdefault("hidden", [])
    return data


def save(data: dict) -> Path:
    """Write atomically — a half-written overrides file is a machine that cannot pick a model."""
    path = overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data["schema_version"] = SCHEMA_VERSION
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def set_alias(from_key: str, to_key: str, why: str = "") -> dict:
    """Record "everything that asks for `from_key`, run `to_key`".

    Stamped with the date and the reason, because an alias is a fact about the record as much as
    about the machine: a session that ran Opus 6 under a project that asked for Opus 5 must be
    able to say so afterwards.
    """
    if not from_key or not to_key or from_key == to_key:
        return load()
    data = load()
    data["aliases"][from_key] = {
        "to": to_key,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "why": why,
    }
    save(data)
    return data


def clear_alias(from_key: str) -> dict:
    data = load()
    if data.get("aliases", {}).pop(from_key, None) is not None:
        save(data)
    return data


@dataclass(frozen=True)
class Alias:
    """One hop the resolver took, so a caller can say what it actually ran and why."""

    from_key: str
    to_key: str
    at: str = ""
    why: str = ""


def resolve_key(key: str, data: Optional[dict] = None) -> tuple[str, Optional[Alias]]:
    """Follow the alias chain from `key`. Returns the final key and the hop that got there.

    The hop returned is the FIRST one, because that is the one worth reporting: "this project asks
    for Opus 5, and this machine sends that to Opus 6". Intermediate hops are bookkeeping.
    """
    data = load() if data is None else data
    aliases = data.get("aliases") or {}
    first: Optional[Alias] = None
    seen = {key}
    current = key
    for _ in range(_MAX_ALIAS_HOPS):
        entry = aliases.get(current)
        if not isinstance(entry, dict):
            break
        nxt = str(entry.get("to") or "")
        if not nxt or nxt in seen:
            break  # a cycle, or a dead end: stop where we are rather than looping
        if first is None:
            first = Alias(
                from_key=key, to_key=nxt, at=str(entry.get("at") or ""), why=str(entry.get("why") or "")
            )
        seen.add(nxt)
        current = nxt
    return current, (Alias(first.from_key, current, first.at, first.why) if first else None)


def hidden_keys(data: Optional[dict] = None) -> set[str]:
    data = load() if data is None else data
    return {str(k) for k in (data.get("hidden") or []) if str(k).strip()}


def added_entries(data: Optional[dict] = None) -> list[dict]:
    """Models this machine can run that no catalogue reports — a private deployment, a preview."""
    data = load() if data is None else data
    return [row for row in (data.get("added") or []) if isinstance(row, dict) and row.get("model")]
