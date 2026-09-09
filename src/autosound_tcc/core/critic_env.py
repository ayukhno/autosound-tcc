"""Where the reviewer's key actually lives, read the way the method reads it.

The method keeps the reviewer key in a MACHINE file — `~/.config/autosound/critic-env`, or
`%APPDATA%\\autosound\\critic-env` — and tells the user NOT to export it from a shell profile:
the project folder is the one the README says to back up to a private GitHub, so a key kept there
is one `git push` from leaving, and `.gitignore` stops none of `git add -f`, a folder copy, or a
backup that is not git (HUB-025). `scripts/autosound_ai.py` and `_gemini_common.sh` are the two
doors onto that file; this is a third, and it must agree with them or TCC judges a channel it
cannot see.

It judged it blind until now: `model_choices.critic_reaches` asked the process environment and
PATH, which is exactly where the method says the key must NOT be. A key stored as documented made
the footer say "unreachable" while the call would have gone through — and the Arbiter found that
out only after waiting for a clipboard fallback (SKL-024).

**This mirrors path resolution and parsing, and nothing else.** No key is logged, returned to a
model, or written anywhere; the values stay in this process. The mirror's one risk is drift — the
method moving the file while TCC keeps looking at the old place — and that is held by a test
comparing this module's path with the script's own `machine_config_path()`, not by a promise.

Reading the script itself was the alternative and it is worse: importing it runs `load_env_file()`
at import time, which MUTATES `os.environ` in whatever process imports it. A settings screen that
silently exports a key into the app's environment is not a settings screen.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Parsed once. A picker asks this per model on every repaint, and the file changes when a person
#: edits it — which is not something that happens between two paints. `forget()` drops it.
_CACHE: dict[str, str] | None = None


def machine_config_path() -> Path:
    """The machine file, resolved the way `autosound_ai.machine_config_path` resolves it."""
    if os.name == "nt" or os.environ.get("APPDATA"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "autosound" / "critic-env"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path(os.path.expanduser("~")) / ".config"
    return base / "autosound" / "critic-env"


def _parse(path: Path) -> dict[str, str]:
    """`KEY=VALUE` lines, with the method's own refusals kept intact.

    A value that can RUN something is not a value: the shell wrapper reads this same file with
    `.`, so a line dropped there must be dropped here too, or the doors disagree about what the
    config says. Same for a key that is not a plain identifier.
    """
    found: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return found
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        if "$(" in line or "`" in line or ";" in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.replace("_", "").isalnum() or key[:1].isdigit():
            continue
        found[key] = value.strip().strip("'\"")
    return found


def values() -> dict[str, str]:
    """Everything the machine config defines. Empty when there is no file — never an error."""
    global _CACHE
    if _CACHE is None:
        _CACHE = _parse(machine_config_path())
    return dict(_CACHE)


def forget() -> None:
    """Drop the cache. For tests, and for a settings screen that has just written the file."""
    global _CACHE
    _CACHE = None


def has_key(name: str) -> bool:
    """Is this key reachable at all — from the process environment OR from the machine file.

    Both, in that order, because the method reads both: the file is where it tells you to put the
    key, and an environment variable still works for anyone who already had one.
    """
    if os.environ.get(name):
        return True
    return bool(values().get(name))
