"""The project's chosen target curve as a FILE, and whether the comparison tool already has it.

Clicking the header's target-curve value opens the method's visualiser in a browser. That tool
carries exactly the curves the skill ships — today one, `SQ-Comp-Ref` — and everything else it
learns by having a `.txt` dropped on it. A project's own curve lives in the project
(`rew_analitic/target-curves/<name>/<name>_0db_REW.txt`), so a tune whose target is anything else
opened a tool that had never heard of it: the header said "Resonalyze", the page showed a curve
that was not it, and nothing said so (the user's own report, 2026-08-25).

What this module answers is the two halves of that:

* **where the project's curve actually is**, which is a small search rather than one path — the
  folder-per-curve layout is the method's README, but the same file also turns up at the project
  root in real projects, and a curve nobody has filed yet is a legitimate state;
* **whether the tool already carries it**, read from the skill's own `curves/` directory rather
  than from a list kept here. A hardcoded `{"SQ-Comp-Ref"}` would be right until the day the skill
  ships a second curve, and then wrong silently, which is the failure this whole module is about.

It does not open anything and does not touch the browser: a window decides what to do with the
answer, and `core` stays testable without one.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autosound_tcc.core import child, vendor_loader

#: Where the method keeps the curves its visualiser is built with.
_SKILL_CURVES = ("references", "patterns", "target-curves", "curves")

#: Where a project keeps its own, per the method's `target-curves/README.md`.
_PROJECT_CURVES = ("rew_analitic", "target-curves")

#: Suffixes a curve file's name carries beyond the curve's own name. `SQ-Comp-Ref_0db_REW.txt` is
#: the curve `SQ-Comp-Ref` exported at 0 dB in REW's format; the export detail is not the identity.
_EXPORT_SUFFIXES = ("_0db_rew", "_0db", "_rew")


@dataclass(frozen=True)
class Target:
    """What is known about the project's target curve, and what the tool will show without help."""

    name: str
    #: The project's own file, when there is one. `None` means the curve is named in the ledger
    #: and no file for it was found — which is a real state and NOT an error: a target can be
    #: chosen before anybody exports it.
    path: Optional[Path]
    #: Whether the visualiser already carries a curve of this name.
    in_tool: bool

    @property
    def needs_dropping(self) -> bool:
        """True when the tool cannot show this curve unless the file is handed to it."""
        return bool(self.name) and not self.in_tool and self.path is not None


def curve_name(stem: str) -> str:
    """`SQ-Comp-Ref_0db_REW` -> `SQ-Comp-Ref`. Case-insensitive, one suffix at a time."""
    out = stem
    lowered = out.lower()
    for suffix in _EXPORT_SUFFIXES:
        if lowered.endswith(suffix):
            return out[: len(out) - len(suffix)]
    return out


def tool_curves() -> tuple[str, ...]:
    """The curves the visualiser is built with, read from the skill rather than listed here.

    An empty tuple when the submodule is not checked out: the honest answer is then "I do not know
    what the tool has", and the caller must not read that as "the tool has nothing" — see
    `describe`, which declines to claim anything in that case.
    """
    try:
        root = Path(vendor_loader.skill_dir()).joinpath(*_SKILL_CURVES)
    except Exception:  # noqa: BLE001 — no skill, no answer
        return ()
    if not root.is_dir():
        return ()
    return tuple(sorted(curve_name(path.stem) for path in root.glob("*.txt")))


def find_file(project_dir: Path, name: str) -> Optional[Path]:
    """The project's file for the curve `name`, or None.

    Three places, in the order they are worth trusting: the folder the method's README names, any
    other curve folder whose file carries the name, and the project root — where an exported curve
    does end up in practice, and where refusing to look would leave the honest answer ("it is
    right there") unsaid.
    """
    if not name:
        return None
    project_dir = Path(project_dir)
    folder = project_dir.joinpath(*_PROJECT_CURVES, name)
    candidates: list[Path] = []
    if folder.is_dir():
        candidates += sorted(folder.glob("*.txt"))
    curves_root = project_dir.joinpath(*_PROJECT_CURVES)
    if curves_root.is_dir():
        candidates += sorted(curves_root.glob("*/*.txt"))
        candidates += sorted(curves_root.glob("*.txt"))
    candidates += sorted(project_dir.glob("*.txt"))
    for path in candidates:
        if curve_name(path.stem).lower() == name.lower():
            return path
    # A folder named for the curve settles it even when the file inside is named something else:
    # the method's layout is one folder per curve, so a lone `.txt` in `<name>/` IS that curve.
    if folder.is_dir():
        inside = sorted(folder.glob("*.txt"))
        if len(inside) == 1:
            return inside[0]
    return None


def reveal_command(path: Path) -> list[str]:
    """The platform's "show me this file" command, with the file SELECTED where that is possible.

    Selected and not merely "open the folder": the point is to put the file one drag away from the
    browser window that needs it, and a folder of a dozen exports leaves the person hunting. macOS
    and Windows both have a select form; on the rest, opening the folder is the best that exists.
    """
    path = Path(path)
    if sys.platform == "darwin":
        return ["open", "-R", str(path)]
    if os.name == "nt":
        # One string, comma, no space: `explorer /select,C:\x\y.txt`. With a space it opens the
        # user's Documents folder instead and reports success.
        return ["explorer", f"/select,{path}"]
    return ["xdg-open", str(path.parent)]


def reveal(path: Path) -> bool:
    """Show the curve file in the file manager. False when the platform would not play."""
    try:
        subprocess.Popen(reveal_command(path), **child.quiet())
    except OSError:
        return False
    return True


def describe(project_dir: Path, name: Optional[str]) -> Target:
    """Everything a window needs to decide what to say before it opens the tool."""
    name = (name or "").strip()
    known = tool_curves()
    # With no skill checked out we cannot tell whether the tool has this curve. Claiming it does
    # is the safe-looking lie: it produces silence, which is exactly the bug being fixed here.
    # Claiming it does not would send somebody hunting for a file that may not be needed. So the
    # tie is broken by whether we found a file at all -- if we did, offering it costs nothing.
    in_tool = bool(known) and any(name.lower() == curve.lower() for curve in known)
    return Target(name=name, path=find_file(project_dir, name), in_tool=in_tool)
