"""Where «Copy the car…» takes a car from: one interface, a folder its first source (G13, #163).

A source recognises its input (`accepts`), turns it into the folder the method's `seed()` copies
from (`resolve`), and lets go of whatever it held (`release`) — a package unpacked into a temporary
folder, later (F-096). The dialog asks a `Picker`, which remembers what it resolved per path and
releases the previous source when the text moves on, so a refused file is opened once, not once per
keystroke. Sentences travel as keys (`Line`); the dialog translates them. No Qt here.

A source that raises is answered like one that refuses: the fault is logged and said as the copy's
refusal (`npSeedFailed`), never remembered as "nothing typed" -- that let «Copy» create an empty
project. A source that cannot let go is logged and forgotten, so closing the dialog never depends on
a clean-up (a temporary folder Windows will not delete while a file in it is held).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Protocol

from autosound_tcc.core import app_log


@dataclass(frozen=True)
class Line:
    """An untranslated sentence: an i18n key and its arguments."""

    key: str
    args: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Resolved:
    """A source's answer: the folder to copy from, or the problem; and what to say beside it."""

    folder: Optional[Path]
    problem: Optional[Line] = None
    about: tuple[Line, ...] = ()
    warnings: tuple[Line, ...] = ()

    def __post_init__(self) -> None:
        if self.folder is not None and self.problem is not None:
            raise ValueError("a source answers with a folder or a problem, not both")


@dataclass(frozen=True)
class Chooser:
    """The source's browse button: a folder or a file dialog, its label, title and filter keys."""

    kind: str  # "folder" | "file"
    label_key: str
    title_key: str
    filter_key: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ("folder", "file"):
            raise ValueError(f"a chooser's kind is 'folder' or 'file', not {self.kind!r}")


class CarSource(Protocol):
    chooser: Chooser

    def accepts(self, path: Path) -> bool: ...

    def resolve(self, path: Path) -> Resolved: ...

    def release(self) -> None: ...


class FolderSource:
    """A project folder: copied from as it is. Anything that is not a file is one — a folder not
    made yet included, which `seed()` then refuses in its own words."""

    chooser = Chooser("folder", "npBrowse", "npSeedFrom")

    def accepts(self, path: Path) -> bool:
        # `os.path`, not `Path.is_file()`: the latter raises on a folder nobody may enter (3.12),
        # and such a path is a folder the seeder then refuses ("no readable project.json").
        return not os.path.isfile(path)

    def resolve(self, path: Path) -> Resolved:
        return Resolved(path)

    def release(self) -> None:
        """Nothing is held for a folder."""


#: The sources, most specific first; they take disjoint inputs. Also the browse buttons' order.
SOURCES: tuple[type, ...] = (FolderSource,)


class Picker:
    """The dialog's one way to a source: resolves the typed text once per path."""

    def __init__(self, sources=None) -> None:
        self.sources = list(sources) if sources is not None else [kind() for kind in SOURCES]
        self._path: Optional[Path] = None
        self._held: Optional[CarSource] = None
        self._answer: Optional[Resolved] = None

    def resolve(self, text: str) -> Optional[Resolved]:
        """None for blank text; the same answer for the same path; a new path releases the old."""
        text = (text or "").strip()
        if not text:
            self.release()
            return None
        path = Path(text).expanduser()
        if path == self._path:
            return self._answer
        self.release()
        asking = None
        try:
            for asking in self.sources:
                if asking.accepts(path):
                    self._held = asking
                    answer = asking.resolve(path)
                    break
            else:
                answer = Resolved(None, problem=Line("npSeedNotAProject"))
        except Exception as exc:  # noqa: BLE001 — a source's fault is the copy's refusal, said
            app_log.logger().warning("car source %s could not read %s: %s",
                                     type(asking).__name__, path, exc, exc_info=True)
            answer = Resolved(None, problem=Line("npSeedFailed",
                                                 {"problem": str(exc) or type(exc).__name__}))
        self._path, self._answer = path, answer
        return answer

    def release(self) -> None:
        held, path = self._held, self._path
        self._path = self._held = self._answer = None
        if held is None:
            return
        try:
            held.release()
        except Exception:  # noqa: BLE001 — closing must not depend on a clean-up
            app_log.logger().warning("car source %s could not let go of %s",
                                     type(held).__name__, path, exc_info=True)
