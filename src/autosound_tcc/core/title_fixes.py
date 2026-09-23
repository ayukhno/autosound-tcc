"""A capture under a wrong title is FIXED, not refused (the Arbiter's A17, 2026-09-23).

«Коли назва не співпада на нолік, чи помилка в назві — треба запропонувати виправлення і
виправити, а не відмовляти. А відмовляти (червона лампочка) тоді, коли там немає заміру, чи він
хибний.» Two kinds of wrong title, and both are the method's words:

* **grammar** — the method's own comparison already matches it, and says so: `validate_series`
  returns `renames`, `{title in REW: canonical title}` (`sw_01 (sw)` → `sw_1 (sw)`, skill #47). The
  fix is a rename, never a re-measurement; the uuid survives it.
* **typo** — a title the grammar does not match to anything expected, or matches to a series the
  round did not ask for, while an expected title is still missing and reads almost the same.

Where the fix is made is the import form (the Arbiter, 2026-09-23): its New name column opens with
the found name filled in and the row UNTICKED — an automatic match is his to accept. The strip
only says there is something to fix and opens that form. The order is the method's (hub #201):
the import renames in REW first; a title the open round had already taken under the wrong name is
then superseded in the round (`supersede`). A round that never took it answers exit 1, which is
not a failure here: the rename and the import were the whole fix.
"""

from __future__ import annotations

import difflib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional

from autosound_tcc.core import app_log, child, process_writer, vendor_loader

Kind = Literal["grammar", "typo"]
REASON = "renamed in REW by TCC (A17)"
#: How alike a typo has to be to its intended name to be offered at all.
_TYPO_CUTOFF = 0.8


@dataclass(frozen=True)
class TitleFix:
    wrong: str
    right: str
    kind: Kind


def proposals(rew_titles: Iterable[str], expected: Iterable[str],
              glossary=None) -> list[TitleFix]:
    """What to rename, by the method's own comparison first and a close match second."""
    naming = vendor_loader.load_naming()
    titles = [str(t) for t in rew_titles if str(t).strip()]
    verdict = naming.validate_series(titles, list(expected), glossary)
    fixes = [TitleFix(wrong, right, "grammar")
             for wrong, right in sorted((verdict.get("renames") or {}).items())]
    missing = list(verdict.get("missing") or [])
    for title in sorted(set(verdict.get("foreign") or []) | set(verdict.get("extra") or [])):
        close = difflib.get_close_matches(title, missing, n=1, cutoff=_TYPO_CUTOFF)
        if close:
            fixes.append(TitleFix(title, close[0], "typo"))
            missing.remove(close[0])
    return fixes


def supersede(project_dir: Path, wrong: str, right: str) -> tuple[bool, str]:
    """`capture-supersede` in the open round. `(done, what the method said)`; exit 1 — the round
    never took the wrong title — counts as done: the REW rename was the whole fix."""
    try:
        proc = subprocess.run(
            [child.script_interpreter(), str(process_writer.script_path()),
             str(Path(project_dir) / "process"), "capture-supersede", wrong, right, REASON],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            env=vendor_loader.child_env(), **child.quiet())
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    app_log.logger().info("capture-supersede %r -> %r: exit %s", wrong, right, proc.returncode)
    said = (proc.stdout.strip() or proc.stderr.strip())
    return proc.returncode in (0, 1), said


def glossary_for(project_dir: Path):
    """The project's glossary through the method, or None — as the capture view reads it."""
    from autosound_tcc.state import measurement_view

    try:
        naming = vendor_loader.load_naming()
        return (naming.Glossary.for_project(str(project_dir))
                if measurement_view.has_glossary(project_dir) else None)
    except Exception:  # noqa: BLE001
        return None


def summary(fixes: list[TitleFix]) -> Optional[str]:
    """`sw_01 (sw) → sw_1 (sw)` for the first, for a one-line notice."""
    return f"{fixes[0].wrong} → {fixes[0].right}" if fixes else None
