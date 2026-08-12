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

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

FILENAME = "tcc-project.json"
SCHEMA_VERSION = 1


def path_for(tcc_dir: Path) -> Path:
    return Path(tcc_dir) / FILENAME


def load(tcc_dir: Path) -> dict[str, Any]:
    """Whatever is on disk, or an empty dict. A missing or broken file is not an error.

    A project that has never been opened has no settings, and one whose file was hand-edited into
    invalid JSON should degrade to "no preference" rather than take the window down.
    """
    try:
        data = json.loads(path_for(tcc_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get(tcc_dir: Path, key: str, default: Optional[str] = None) -> Optional[str]:
    value = load(tcc_dir).get(key)
    return str(value) if isinstance(value, (str, int, float)) else default


def set_value(tcc_dir: Path, key: str, value: Any = None) -> None:
    """Write one field, keeping the rest. Atomic, same shape as `core/session_registry.py`.

    `value` is usually a string (a model key, a language). It may be any JSON-serialisable thing —
    `core/delay_bank.py` keeps a `{title: ms}` mapping here — but the reader is the caller's
    problem then: `get()` deliberately returns only scalars, so a structured value needs its own
    accessor rather than a cast at every call site. `None` removes the field.

    Write-then-rename rather than write-in-place: this is touched on model changes, which can
    happen while a session is mid-turn, and a half-written settings file would read as "no
    preference" on the next launch -- silently forgetting what the user chose.
    """
    tcc_dir = Path(tcc_dir)
    tcc_dir.mkdir(parents=True, exist_ok=True)
    data = load(tcc_dir)
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    data["schema_version"] = SCHEMA_VERSION
    target = path_for(tcc_dir)
    handle, tmp = tempfile.mkstemp(dir=str(tcc_dir), prefix=".tcc-project-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
