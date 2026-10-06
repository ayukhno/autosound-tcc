"""Where «Copy the car…» takes a car from: one interface, a folder its first source (G13, #163).

A source recognises its input (`accepts`), turns it into the folder the method's `seed()` copies
from (`resolve`), and lets go of whatever it held (`release`) — a package unpacked into a temporary
folder, later (F-096). The dialog asks a `Picker`, which remembers what it resolved per path and
releases the previous source when the text moves on, so a refused file is opened once, not once per
keystroke. Sentences travel as keys (`Line`); the dialog translates them. No Qt here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Protocol


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


@dataclass(frozen=True)
class Chooser:
    """The source's browse button: a folder or a file dialog, its label, title and filter keys."""

    kind: str  # "folder" | "file"
    label_key: str
    title_key: str
    filter_key: str = ""


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
        return not path.is_file()

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
        self._path = path
        for source in self.sources:
            if source.accepts(path):
                self._held = source
                self._answer = source.resolve(path)
                break
        else:
            self._answer = Resolved(None, problem=Line("npSeedNotAProject"))
        return self._answer

    def release(self) -> None:
        if self._held is not None:
            self._held.release()
        self._path = self._held = self._answer = None
