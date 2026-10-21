"""What TCC knows of the method's own writer lock (#218, G8 phase 1) — its names, and whether a copy
of the method takes it.

From v3.1.3 every writer of the method holds `<project>/.autosound/write.lock` across its load ->
write -> append (its `rew_tool/write_lock.py`, `CONTRACT.md` item 8). One that meets another writer
waits `AUTOSOUND_LOCK_TIMEOUT_S` seconds, read at each call, then exits 75 with one `busy:` line and
nothing written. A copy that declares `PROTOCOL = 1` in that file locks itself, and TCC takes no
flock of its own around its child (`method_cli.spawn`): one would either wait on its own parent or
bring back the long waits behind another file. A copy that does not — every one up to v3.1.2 — keeps
TCC's whole legacy lock (`project_lock.hold`).

Read as text and never imported: importing it would run the method's code in TCC's process. Qt-free,
and imports nothing of TCC's.
"""

from __future__ import annotations

import re
from pathlib import Path

#: The method's exit for a write another writer held past the wait: nothing written, safe to retry.
BUSY_EXIT = 75

#: How long the method's writer waits for its lock, in seconds, read by the child at each call. Set
#: per call by `method_cli.spawn`, never in `vendor_loader.child_env()`: an agent's session takes its
#: environment from there, and its own writers would inherit TCC's short wait.
WAIT_ENV = "AUTOSOUND_LOCK_TIMEOUT_S"

#: What `Busy` says when the busy write printed nothing of its own: TCC's lock past its wait, or a
#: write asked from inside one of TCC's own holds.
BUSY_SAID = "busy: another write to this project is still running — nothing was written, try again"

# The method's lock module in a copy, and the line that says it locks itself.
_WRITE_LOCK = ("rew_tool", "write_lock.py")
_PROTOCOL_1 = re.compile(r"^PROTOCOL\s*=\s*1[ \t]*(?:#.*)?$", re.MULTILINE)

#: path -> (st_mtime_ns, st_size, the answer): one entry per copy's `write_lock.py`, read again when
#: it changes. Every spawn asks, and the file is 85 KB.
_CACHE: dict[str, tuple[int, int, bool]] = {}


def locks_itself(skill_dir: Path | str) -> bool:
    """Whether this copy of the method takes its own writer lock: `rew_tool/write_lock.py` in its
    skill folder, declaring `PROTOCOL = 1` on a line of its own.

    No copy up to v3.1.2 has the file; v3.1.3 declares it. Read once per file, mtime and size, so an
    update in place is seen on the next call. Never raises: a file that is not there, cannot be read,
    or is not UTF-8 is a copy that does not lock itself.
    """
    path = Path(skill_dir, *_WRITE_LOCK)
    try:
        info = path.stat()
    except (OSError, ValueError):  # not there, a path that cannot be looked at
        return False
    key = (info.st_mtime_ns, info.st_size)
    cached = _CACHE.get(str(path))
    if cached is not None and cached[:2] == key:
        return cached[2]
    try:
        answer = _PROTOCOL_1.search(path.read_text(encoding="utf-8")) is not None
    except (OSError, ValueError):  # a folder, unreadable, not UTF-8
        answer = False
    _CACHE[str(path)] = (*key, answer)
    return answer
