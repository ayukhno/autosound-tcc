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
  whoever wants them. A reader to whom that `{}` is not «nothing here» asks `aside_said` and
  `times_set_aside` — and, in a later run, `set_aside_copies`;
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

#: The stores set aside this run, by absolute path: the sentence said when one was moved, until a
#: write lands a fresh file there or the file is read whole again (`aside_said`), and how many
#: times each was set aside, which never goes back (`times_set_aside`). A store set aside read as
#: `{}`, and every reader after it took that for a good, empty store: the gate it held for no gate,
#: the bank for «nothing banked» (the end-of-branch review, code I1; Fable m1). Under `_said_lock`.
_aside_said: dict[str, str] = {}
_asides: dict[str, int] = {}

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
    _forget_aside(path)  # read whole: a file put back where the broken one was
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
    _forget_aside(path)  # a fresh file is there now


def _set_aside(path: Path, why: str, aside_dir: Optional[Path] = None) -> dict[str, Any]:
    """Move a broken store out of the way — beside it, or into `aside_dir` — keeping its bytes,
    and say so. `{}` once it is moved.

    Marked set aside BEFORE the move (`aside_said`, `times_set_aside`): a reader that loses the
    race to it finds the file gone and answers `{}` the moment the move lands, and must find the
    mark already there — and a write that follows that `{}` must come after the mark, or it would
    clear nothing and the mark would stand over the fresh file. A move refused takes the mark
    back; a move that finds the file gone keeps the count — the bytes read were broken all the
    same, whoever moved them — and gives the sentence back to whoever had it."""
    aside: Optional[Path] = None
    marked: Optional[tuple[str, Optional[str]]] = None
    try:
        aside = _reserve_aside(path, aside_dir)
        # Beside the store, its name is where it is; anywhere else, only its whole path says that.
        kept = aside.name if aside_dir is None else str(aside)
        message = (f"{path} could not be read ({why}); it is kept as {kept}, "
                   "and the next save starts it afresh")
        marked = _mark_aside(path, message)
        os.replace(path, aside)
    except OSError as exc:
        if aside is not None:
            with contextlib.suppress(OSError):
                aside.unlink()  # the reserved name, still empty: given back
        gone = isinstance(exc, FileNotFoundError)
        if marked is not None:
            _unmark_aside(path, marked, count=not gone)
        elif gone:
            _count_aside(path, 1)  # gone before a name was reserved: broken bytes all the same
        if gone:
            return {}  # another reader moved it between our read and this move, and said so
        message = (f"{path} could not be read ({why}) and could not be set aside "
                   f"({_why(exc)}); TCC will not write over it")
        _say_once(path, message)
        raise StoreNotSetAside(message) from exc
    app_log.report(message)
    return {}


def _mark_aside(path: Path, message: str) -> tuple[str, Optional[str]]:
    """Mark `path` set aside with `message`; what `_unmark_aside` needs to take it back."""
    key = os.path.abspath(path)
    with _said_lock:
        before = _aside_said.get(key)
        _aside_said[key] = message
    _count_aside(path, 1)
    return message, before


def _count_aside(path: Path, by: int) -> None:
    key = os.path.abspath(path)
    with _said_lock:
        _asides[key] = max(0, _asides.get(key, 0) + by)


def _unmark_aside(path: Path, marked: tuple[str, Optional[str]], *, count: bool) -> None:
    """Take back `_mark_aside`'s sentence — only while it is still this reader's: another reader
    that marked after it has the store's sentence — and, with `count`, its count."""
    key = os.path.abspath(path)
    message, before = marked
    with _said_lock:
        if _aside_said.get(key) == message:
            if before is None:
                _aside_said.pop(key, None)
            else:
                _aside_said[key] = before
    if count:
        _count_aside(path, -1)


def aside_said(path: Path) -> str:
    """The sentence said when this store was set aside as broken — while no write has landed a
    fresh file there and it has not been read whole since — or "". For a reader to whom `{}` from
    a store just set aside is not «nothing here»: the curve window's bank (Fable m1)."""
    with _said_lock:
        return _aside_said.get(os.path.abspath(path), "")


def times_set_aside(path: Path) -> int:
    """How many times this store has been set aside as broken this run. Never goes back: a write
    lands a fresh file, not what the old one held — the gate (`shell_gate.project_gate`, code
    I1)."""
    with _said_lock:
        return _asides.get(os.path.abspath(path), 0)


def set_aside_copies(path: Path) -> list[str]:
    """The names of the copies this store was set aside as beside it (`<name>.corrupt-*`), oldest
    first: what a set-aside leaves once the run that counted it is over — the count is this
    process's, the copy stays until the person deletes it (Fable's re-review of the branch fix,
    I1). `[]` when the folder is not there; a folder that is there and cannot be listed raises
    its `OSError`: whether a copy is in it is not known."""
    path = Path(path)
    prefix = _aside_prefix(path)
    try:
        with os.scandir(path.parent) as entries:
            return sorted(entry.name for entry in entries if entry.name.startswith(prefix))
    except FileNotFoundError:
        return []


def set_aside_state(path: Path) -> tuple:
    """What is beside the store, as a memo's key: the names and sizes of its set-aside copies, from
    one `os.scandir`. Not the folder's time — ext4/tmpfs step it per kernel tick, NTFS per clock
    tick, so a copy made inside one tick of the last look left it where it was (#208, the group
    review's C1). `()` when the folder is not there; the error's name when it cannot be listed."""
    path = Path(path)
    prefix = _aside_prefix(path)
    try:
        with os.scandir(path.parent) as entries:
            found = []
            for entry in entries:
                if entry.name.startswith(prefix):
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        size = -1
                    found.append((entry.name, size))
            return tuple(sorted(found))
    except FileNotFoundError:
        return ()
    except OSError as exc:
        return (type(exc).__name__, exc.errno)


def _forget_aside(path: Path) -> None:
    """A fresh file written, or a file read whole: the store is no longer the one set aside."""
    if _aside_said:
        with _said_lock:
            _aside_said.pop(os.path.abspath(path), None)


def _aside_prefix(path: Path) -> str:
    """What every copy `path` is set aside as is named from, beside it: `<name>.corrupt-`."""
    return f"{path.name}.corrupt-"


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
    stem = f"{_aside_prefix(path)}{_stamp()}"
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

    For a writer that carries on without the write (`project_settings.written_or_said`, R-bl):
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


def file_state(path: Path) -> tuple:
    """`_state`, for a caller that keeps its own memo of a store: `shell_gate` looks beside the
    project's store again when this changes."""
    return _state(path)


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
