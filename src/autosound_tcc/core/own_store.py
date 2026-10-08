"""TCC's own small JSON stores, read so that one which cannot be read is never written over.

TCC keeps state of its own in files like `<project>/.tcc/tcc-project.json`: model choices, ticks,
delays, import answers. Each reader answered `{}` for a missing file, a broken one and one it was
not allowed to open alike, and the next write put that `{}` back with one field in it — everything
else the file held was gone, and nothing said so (#173, F5). Here the three are told apart:

* **absent** — `{}`, silently: a project nobody has opened has no settings yet;
* **broken** (bad JSON, bad UTF-8, or JSON that is not an object; a byte-order mark is not
  broken) — the file is moved to `<name>.corrupt-<YYYYMMDD-HHMMSS>` beside it, the person is told,
  and `{}` comes back. The next write starts a fresh file, and the original bytes are still there
  for whoever wants them;
* **there but unreadable** (any other `OSError`: no permission, a folder where the file should
  be, a broken file that could not be moved) — the person is told and `StoreUnreadable` is
  raised. Nothing is moved and nothing may be written: the bytes may be perfectly good. A plain
  reader catches it and carries on with `{}`; a read-modify-write lets it through.

Told once per state of the file, not on every read: a store is read on every tool call, and one
sentence repeated on each would bury the strip and the log. A store read whole again is news
again the next time it fails.

Light and Qt-free: the MCP server and the CLI read these stores too.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from autosound_tcc.core import app_log


class StoreUnreadable(OSError):
    """A store that is there and could not be read — so it must not be written over.

    An `OSError` because to a caller it is a store that could not be used, the same as a write
    that failed: whoever already handles that handles this. Its text is the sentence the person
    was told.
    """


#: What has been said about each store: `{(absolute path, "read" | "write"): (the file's state,
#: the sentence)}`. Reading and writing apart: every best-effort write reads the store fine first,
#: and a good read forgetting a failed write would say that write again on every call.
_said: dict[tuple[str, str], tuple] = {}
_said_lock = threading.Lock()


def read_json(path: Path, *,
              misshapen: Optional[Callable[[dict[str, Any]], str]] = None) -> dict[str, Any]:
    """The store's object — `{}` when it is not there, or was broken and has been set aside.

    Raises `StoreUnreadable` when the file is there and cannot be read (see the module's header).

    `misshapen`, when given, is the owner's own look inside the object: why it is not a shape the
    owner can read, or "" when it is. An object it refuses goes the broken way — set aside with
    its bytes, and said with that reason: `sessions.json` holding `"phases": []` was valid JSON
    and an object, and the registry's code tripped over it on every read (#173).
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        message = f"{path} could not be read ({_why(exc)}); TCC will not write over it"
        _say_once(path, message)
        raise StoreUnreadable(message) from exc
    try:
        # `utf-8-sig`: older Windows Notepad saves UTF-8 with a byte-order mark, and a store edited
        # there is not broken (the review of Task 17).
        data = json.loads(raw.decode("utf-8-sig"))
    except ValueError as exc:  # a JSON error and a UTF-8 error are both ValueErrors
        return _set_aside(path, _why(exc))
    if not isinstance(data, dict):
        return _set_aside(path, "valid JSON, but not an object")
    wrong = misshapen(data) if misshapen is not None else ""
    if wrong:
        return _set_aside(path, f"valid JSON, but {wrong}")
    _forget(path)
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    """The whole store, through a temp file beside it: written, flushed, fsynced, renamed over.

    The rename is what keeps a half-written file from ever being read back. The fsync before it
    is what makes the rename safe: without it the new name can reach the disk before the bytes it
    names, and a power cut leaves an empty store under the right name.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _set_aside(path: Path, why: str) -> dict[str, Any]:
    """Move a broken store out of the way, keeping its bytes, and say so. `{}` once it is moved."""
    aside: Optional[Path] = None
    try:
        aside = _reserve_aside(path)
        os.replace(path, aside)
    except OSError as exc:
        if aside is not None:
            with contextlib.suppress(OSError):
                aside.unlink()  # the reserved name, still empty: given back
        if isinstance(exc, FileNotFoundError):
            return {}  # another reader moved it between our read and this move, and said so
        message = (f"{path} could not be read ({why}) and could not be set aside "
                   f"({_why(exc)}); TCC will not write over it")
        _say_once(path, message)
        raise StoreUnreadable(message) from exc
    app_log.report(f"{path} could not be read ({why}); it is kept as {aside.name}, "
                   "and the next save starts it afresh")
    return {}


def _reserve_aside(path: Path) -> Path:
    """`<name>.corrupt-<YYYYMMDD-HHMMSS>` beside the store, then `-2`, `-3` …: reserved, not looked
    up.

    The stamp is to the second, and on POSIX a rename onto a taken name replaces the copy already
    there without a word. Created exclusively (`"x"`: `O_CREAT | O_EXCL`), the name is this
    process's alone: the window and the CLI setting one store aside in the same second cannot
    both take it (the review of Task 17). The empty file is what `os.replace` then puts the
    broken store over."""
    stem = f"{path.name}.corrupt-{_stamp()}"
    n = 1
    while True:
        aside = path.with_name(stem if n == 1 else f"{stem}-{n}")
        try:
            aside.open("xb").close()
        except FileExistsError:
            n += 1
            continue
        return aside


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def say_unwritten(path: Path, exc: OSError) -> None:
    """Say that a write to the store failed — once for this state of the file, naming it and why.

    For a writer that carries on without the write (`project_settings.set_value_or_say`, R-bl):
    a read-only folder or a full disk fails every write the same way, and the window writes on
    every pick. `write_json` itself raises, and says nothing."""
    _say_once(Path(path), f"{path} could not be written ({_why(exc)}); the change was not saved",
              kind="write")


def _say_once(path: Path, message: str, kind: str = "read") -> None:
    """Report `message` unless it was already said about this same state of the file."""
    key = (os.path.abspath(path), kind)
    said = (_state(path), message)
    with _said_lock:
        if _said.get(key) == said:
            return
        _said[key] = said
    app_log.report(message)


def _forget(path: Path) -> None:
    """A store read whole: what was said about it no longer stands. `chmod 0`, a fix and `chmod 0`
    again is the same state twice, and the second time is news (the review of Task 17)."""
    if _said:
        with _said_lock:
            _said.pop((os.path.abspath(path), "read"), None)


def _state(path: Path) -> tuple:
    """Which file this is, as far as `stat` can tell: a changed file is a new thing to say. The
    mode is in it because `chmod` moves neither the size nor the mtime."""
    try:
        st = os.stat(path)
    except OSError as exc:
        return (type(exc).__name__,)
    return (st.st_ino, st.st_size, st.st_mtime_ns, st.st_mode)


def _why(exc: BaseException) -> str:
    """The reason, without the path the sentence has already named."""
    if isinstance(exc, OSError) and exc.strerror:
        return exc.strerror
    return str(exc) or type(exc).__name__
