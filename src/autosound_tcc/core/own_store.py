"""TCC's own small JSON stores, read so that one which cannot be read is never written over.

TCC keeps state of its own in files like `<project>/.tcc/tcc-project.json`: model choices, ticks,
delays, import answers. Each reader answered `{}` for a missing file, a broken one and one it was
not allowed to open alike, and the next write put that `{}` back with one field in it — everything
else the file held was gone, and nothing said so (#173, F5). Here the three are told apart:

* **absent** — `{}`, silently: a project nobody has opened has no settings yet;
* **broken** (bad JSON or nested too deep to parse, bad UTF-8, or JSON that is not an object; a
  byte-order mark is not broken) — the file is moved to `<name>.corrupt-<YYYYMMDD-HHMMSS>`
  beside it (or into the folder its owner names, `aside_dir`), the person is told, and `{}`
  comes back. The next write starts a fresh file, and the original bytes are still there for
  whoever wants them;
* **there but unreadable** (any other `OSError`: no permission, a folder where the file should
  be, a broken file that could not be moved) — the person is told and `StoreUnreadable` is
  raised (`StoreNotSetAside`, a kind of it, for the broken file that could not be moved).
  Nothing is moved and nothing may be written: the bytes may be perfectly good. A plain reader
  catches it and carries on with `{}`; a read-modify-write lets it through.

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


class StoreNotSetAside(StoreUnreadable):
    """A broken store that could not be moved out of the way: read, found broken, and the move
    aside refused — a read-only folder, a lock on the rename, a file where the aside folder should
    be. Not written over, as an unreadable one is not, and caught wherever that is. Its own kind
    because the file did open: advice to check that it can be opened points away from the cause
    (the re-review of Task 19, N2)."""


#: What has been said about each store: `{(absolute path, "read" | "write"): (the file's state,
#: the sentence)}`. Reading and writing apart: every best-effort write reads the store fine first,
#: and a good read forgetting a failed write would say that write again on every call.
_said: dict[tuple[str, str], tuple] = {}
_said_lock = threading.Lock()

#: What a `misshapen` look trips on when the object is not the shape it assumed: a list where a
#: map was, a missing key, a value of the wrong type, nesting too deep to walk (R-bo).
_SHAPE_ERRORS = (TypeError, AttributeError, KeyError, IndexError, ValueError, RecursionError)


def read_json(path: Path, *,
              misshapen: Optional[Callable[[dict[str, Any]], str]] = None,
              aside_dir: Optional[Path] = None) -> dict[str, Any]:
    """The store's object — `{}` when it is not there, or was broken and has been set aside.

    Raises `StoreUnreadable` when the file is there and cannot be read (see the module's header).

    `misshapen`, when given, is the owner's own look inside the object: why it is not a shape the
    owner can read, or "" when it is. An object it refuses goes the broken way — set aside with
    its bytes, and said with that reason: `sessions.json` holding `"phases": []` was valid JSON
    and an object, and the registry's code tripped over it on every read (#173). A look that
    trips on the shape refuses the same way, its exception named in the reason and its traceback
    logged (R-bn, R-bo): before, its exception escaped past every reader. Only what a shape trips
    — `_SHAPE_ERRORS`; anything else from the look (a bug of its own, an import, memory) says
    nothing about the store, and goes up rather than move a good store aside.

    `aside_dir`, when given, is where a broken store's copy goes instead of beside it, the folder
    made when it is not there (R-k). For a store whose own folder travels and whose bytes must
    not: `.mcp.json` sits in the project folder, which git ignores it in by that exact name only,
    and its copy carries the session's token — so it goes into `.tcc/`, ignored whole (ruling 9).
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        _forget(path)  # absent is fine: what was said about reading it no longer stands
        return {}
    except OSError as exc:
        message = f"{path} could not be read ({_why(exc)}); TCC will not write over it"
        _say_once(path, message)
        raise StoreUnreadable(message) from exc
    try:
        # `utf-8-sig`: older Windows Notepad saves UTF-8 with a byte-order mark, and a store edited
        # there is not broken (the review of Task 17).
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, RecursionError) as exc:
        # A JSON error and a UTF-8 error are both ValueErrors. Nesting deeper than the parser can
        # follow is a RecursionError, and bytes it cannot read are broken all the same (R-bn).
        return _set_aside(path, _why(exc), aside_dir)
    if not isinstance(data, dict):
        return _set_aside(path, "valid JSON, but not an object", aside_dir)
    try:
        wrong = misshapen(data) if misshapen is not None else ""
    except _SHAPE_ERRORS as exc:
        # The owner's check tripped over the shape it was there to catch (R-bn). The reason keeps
        # `Type: text`; the line it tripped on is for the log (R-bo).
        app_log.logger().warning("the shape check of %s raised", path, exc_info=True)
        wrong = f"checking its shape raised {type(exc).__name__}: {exc}"
    if wrong:
        return _set_aside(path, f"valid JSON, but {wrong}", aside_dir)
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
    _forget(path, "write")


def _set_aside(path: Path, why: str, aside_dir: Optional[Path] = None) -> dict[str, Any]:
    """Move a broken store out of the way — beside it, or into `aside_dir` — keeping its bytes,
    and say so. `{}` once it is moved."""
    aside: Optional[Path] = None
    try:
        aside = _reserve_aside(path, aside_dir)
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
        raise StoreNotSetAside(message) from exc
    # Beside the store, its name is where it is; anywhere else, only its whole path says that.
    kept = aside.name if aside_dir is None else str(aside)
    app_log.report(f"{path} could not be read ({why}); it is kept as {kept}, "
                   "and the next save starts it afresh")
    return {}


def _reserve_aside(path: Path, aside_dir: Optional[Path] = None) -> Path:
    """`<name>.corrupt-<YYYYMMDD-HHMMSS>` beside the store — or in `aside_dir`, made when it is not
    there — then `-2`, `-3` …: reserved, not looked up.

    The stamp is to the second, and on POSIX a rename onto a taken name replaces the copy already
    there without a word. Created exclusively (`"x"`: `O_CREAT | O_EXCL`), the name is this
    process's alone: the window and the CLI setting one store aside in the same second cannot
    both take it (the review of Task 17). The empty file is what `os.replace` then puts the
    broken store over."""
    folder = path.parent
    if aside_dir is not None:
        folder = Path(aside_dir)
        folder.mkdir(parents=True, exist_ok=True)
    stem = f"{path.name}.corrupt-{_stamp()}"
    n = 1
    while True:
        aside = folder / (stem if n == 1 else f"{stem}-{n}")
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


def said_about(path: Path) -> str:
    """The sentence last said about this store and still standing — about reading it, else about
    writing it — or "". For an answer the memo must not silence: a Save is the person asking,
    and the failure was said once already (the re-review of Task 17). A good or absent read
    forgets the first, a landed write the second."""
    key = os.path.abspath(path)
    for kind in ("read", "write"):
        said = _said.get((key, kind))
        if said:
            return said[1]
    return ""


def _say_once(path: Path, message: str, kind: str = "read") -> None:
    """Report `message` unless it was already said about this same state of the file."""
    key = (os.path.abspath(path), kind)
    said = (_state(path), message)
    with _said_lock:
        if _said.get(key) == said:
            return
        _said[key] = said
    app_log.report(message)


def _forget(path: Path, kind: str = "read") -> None:
    """A store read whole, or written whole: what was said about reading it, or writing it, no
    longer stands. `chmod 0`, a fix and `chmod 0` again is the same state twice, and the second
    time is news (the review of Task 17); so is a write failing with the store absent, one
    landing, the store deleted and the same failure again (N2)."""
    if _said:
        with _said_lock:
            _said.pop((os.path.abspath(path), kind), None)


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
