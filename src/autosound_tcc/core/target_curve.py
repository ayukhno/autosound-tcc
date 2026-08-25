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

import json
import os
import subprocess
import sys
import tempfile
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autosound_tcc.core import child, vendor_loader

#: Where the method keeps the curves its visualiser is built with.
_SKILL_CURVES = ("references", "patterns", "target-curves", "curves")

#: Where a project keeps its own, per the method's `target-curves/README.md`.
_PROJECT_CURVES = ("rew_analitic", "target-curves")

#: The two ids the injected copy relies on, checked before anything is written. The tool's own
#: file input and its drop zone — public DOM, not internal JavaScript. If either is ever renamed
#: the injection would quietly do nothing and the page would open with only its own curve, which
#: is the exact bug this feature exists to fix, so the absence of one is a refusal instead.
_VIEWER_ANCHORS = ('id="curveFile"', 'id="dropZone"')

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


def viewer_source() -> Optional[Path]:
    """The method's visualiser as it exists in this checkout, or None."""
    try:
        path = Path(vendor_loader.skill_dir()).joinpath(
            "references", "patterns", "target-curves", "target_curves_visualizer.html")
    except Exception:  # noqa: BLE001
        return None
    return path if path.is_file() else None


def local_viewer_dir() -> Path:
    """Where the injected copy is written. One place, overwritten, never the project folder."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches" / "autosound-tcc"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "autosound-tcc"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "autosound-tcc"
    return base / "target-curve-viewer"


def tool_takes_a_fragment() -> bool:
    """Whether the method's visualiser can be handed a curve in the URL fragment.

    Read from the vendored copy, which is what tells us the FEATURE exists in the method. The page
    that actually opens is the published one, built from the same branch — so this is a proxy, and
    the honest thing to know about it is that a pin newer than the deploy would be wrong for the
    minutes between a push and Pages catching up. That window is why the local copy stays: it is
    the fallback whenever this answers False.
    """
    source = viewer_source()
    if source is None:
        return False
    try:
        html = source.read_text(encoding="utf-8")
    except OSError:
        return False
    return "location.hash" in html and "'curve'" in html and "'data'" in html


def fragment_for(curve_path: Path, name: str) -> Optional[str]:
    """`curve=<name>&data=<REW text>`, percent-encoded, for the URL FRAGMENT.

    ⚠️ **Built and tested, and NOT yet the path the window takes** (2026-08-25). The loader in the
    method's page adds the curve TWICE: one fragment load produces two cards, `<name>` and
    `<name> (loaded)`. Measured on a cleared localStorage with a forced reload and a name the
    browser had never seen — the first two attempts at this were worthless because changing only
    the fragment does not reload a page, so nothing ran at all. Reported to the skill; until it is
    one card, the window keeps using the local injected copy, which was verified to produce
    exactly three.

    The fragment and not the query on purpose, and it is the method's choice as much as ours: a
    fragment is never sent to the server, so a person's own measured curve does not reach GitHub's
    logs on the way to a page that only needed to draw it.
    """
    try:
        text = Path(curve_path).read_text(encoding="utf-8")
    except OSError:
        return None
    return f"curve={quote(name, safe='')}&data={quote(text, safe='')}"


def build_local_viewer(curve_path: Path, name: str, out_dir: Optional[Path] = None) -> Optional[Path]:
    """A copy of the visualiser that already has this curve on it, or None if it cannot be made.

    This is the user's own question answered ("why not just put the curve in the viewer's
    folder?"): the folder is not read. The page performs no network request of any kind — the one
    curve it ships is a JavaScript array inside the HTML, and `curves/` exists so a PERSON can
    pick a file up from it and drop it. So the curve goes INTO the copy, not next to it.

    The injection uses the tool's own front door rather than its insides: it builds a `File` and
    hands it to the page's file input, which is exactly what the picker does. Nothing about the
    tool's internal functions or data structures is assumed — only that the input exists, which is
    checked first, because an injection that silently does nothing would restore the original bug
    in a form nobody can see.

    Returns None rather than raising: every caller has a working fallback (reveal the file and let
    the person drop it), and a failure here must degrade to that rather than to an error dialog.
    """
    source = viewer_source()
    if source is None:
        return None
    try:
        html = source.read_text(encoding="utf-8")
        curve = Path(curve_path).read_text(encoding="utf-8")
    except OSError:
        return None
    if not all(anchor in html for anchor in _VIEWER_ANCHORS):
        return None
    if "</body>" not in html:
        return None

    payload = json.dumps({"name": Path(curve_path).name, "text": curve})
    script = f"""
<!-- Added by TCC: this project's own target curve, handed to the tool through its own file
     input — the same path a dropped file takes. Nothing else in this page is changed. -->
<script>
(function () {{
  var curve = {payload};
  function place() {{
    var input = document.getElementById('curveFile');
    if (!input || typeof DataTransfer === 'undefined') return;
    var box = new DataTransfer();
    box.items.add(new File([curve.text], curve.name, {{ type: 'text/plain' }}));
    input.files = box.files;
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }}
  if (document.readyState === 'complete') {{ place(); }}
  else {{ window.addEventListener('load', place); }}
}})();
</script>
</body>"""
    out_dir = Path(out_dir or local_viewer_dir())
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # Written beside the target and moved into place: a half-written 500 KB page opened by a
        # browser is a blank screen with no explanation.
        handle, temp = tempfile.mkstemp(dir=str(out_dir), suffix=".html")
        os.close(handle)
        temp_path = Path(temp)
        temp_path.write_text(html.replace("</body>", script, 1), encoding="utf-8")
        final = out_dir / f"{name or 'curve'}.html"
        temp_path.replace(final)
    except OSError:
        return None
    return final


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
