"""A capture under a wrong title is FIXED, not refused (the Arbiter's A17, 2026-09-23).

«Коли назва не співпада на нолік, чи помилка в назві — треба запропонувати виправлення і
виправити, а не відмовляти. А відмовляти (червона лампочка) тоді, коли там немає заміру, чи він
хибний.» Two kinds of wrong title, and both are the method's words:

* **grammar** — the method's own comparison already matches it, and says so: `validate_series`
  returns `renames`, `{title in REW: canonical title}` (`sw_01 (sw)` → `sw_1 (sw)`, skill #47). The
  fix is a rename, never a re-measurement; the uuid survives it.
* **typo** — a title the grammar does not match to anything expected, or reads as a measurement
  the round did not ask for, while an expected title is still missing and reads almost the same.
  Another series of a name the round expects (`sw_B1 (sw)`, `sw_4 (sw)` for `sw_3 (sw)`) is not
  one: it is a measurement of its own (tcc#114).

Where the fix is made is the import form (the Arbiter, 2026-09-23): its New name column opens with
the found name filled in and the row UNTICKED — an automatic match is his to accept. The strip
only says there is something to fix and opens that form. The order is the method's (hub #201):
the import renames in REW first; a title the open round had already taken under the wrong name is
then superseded in the round (`supersede`). A round that never took it answers exit 1 with the
method's refusal, which is not a failure here: the rename and the import were the whole fix. Nor is
it a change to the round, so it is never said as one (Task 27 M1). A crash exits 1 as well, with a
traceback instead, and that is a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional

from autosound_tcc.core import app_log, capture_import, config, process_writer, vendor_loader

Kind = Literal["grammar", "typo"]
REASON = process_writer.SUPERSEDE_REASON

#: The answers that say the same about every call still to come: busy behind another write (#171),
#: or the project's copy of the method refused (#169). After one, the rest are not asked.
_STOPS = (process_writer.Busy, process_writer.Refused)

#: What one `capture-supersede` came to: the round holds the right title now (exit 0); the method's
#: own refusal — the round never took the wrong one, or another writer closed it since it was read —
#: no failure of the fix, and no change to the round either; or no answer at all.
CHANGED, UNCHANGED, FAILED = "changed", "unchanged", "failed"


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
    expected = list(expected)
    verdict = naming.validate_series(titles, expected, glossary)
    fixes = [TitleFix(wrong, right, "grammar")
             for wrong, right in sorted((verdict.get("renames") or {}).items())]
    # The import form's own pass (tcc#114): the closest pair first, and another series of a name
    # the round expects is no typo of any — the form and the strip must not offer different fixes.
    loose = sorted(set(verdict.get("foreign") or []) | set(verdict.get("extra") or []))
    found = capture_import.likely_typos(loose, verdict.get("missing") or [], expected,
                                        naming, glossary)
    fixes.extend(TitleFix(loose[index], right, "typo") for index, right in found.items())
    return fixes


def offered(rew_titles: Iterable[str], round_: Optional[dict]) -> list[TitleFix]:
    """What the window's strip offers to fix in the open `round_`: `proposals` over what REW holds
    and what the round expects, read with the project's glossary. Nothing for no project, a round
    closed or none, or no method or a grammar it cannot read: nothing to offer then, which is not
    a failure to say. Out of the window's `_offer_title_fixes` (W-9)."""
    project = config.chosen_project_dir()
    if project is None or not round_ or round_.get("closed"):
        return []
    try:
        return proposals(rew_titles, round_.get("expected") or [], glossary_for(project))
    except Exception:  # noqa: BLE001 — no method, or a grammar it cannot read: nothing to offer
        return []


def supersede(project_dir: Path, wrong: str, right: str) -> tuple[bool, str]:
    """`capture-supersede` in the open round. `(done, what the method said)`; exit 1 with the
    method's refusal — the round never took the wrong title — counts as done: the REW rename was
    the whole fix. A call that got no answer is `(False, why)` — busy behind another write, the
    project's copy refused, timed out, a method without it, or a crash: Python exits 1 too, with a
    traceback where the refusal would be (#169 review I1)."""
    try:
        outcome, said = _supersede(project_dir, wrong, right)
    except _STOPS as exc:
        return False, str(exc)
    return outcome != FAILED, said


def supersede_each(
    project_dir: Path, fixes: Iterable[tuple[str, str]]
) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]], list[tuple[str, str]]]:
    """`supersede` for each `(wrong, right)` in turn, as the import renames them. Returns
    `(done, refused, not_asked)`: the `(wrong, right)` the round now holds — exit 0, and only that
    (Task 27 M1: a refusal read as «never took it» was counted done, about a round closed between
    the panel's read and the call); `(wrong, right, what was said)` for each one that got no
    answer; and the `(wrong, right)` left unasked after a busy or refused answer (`_STOPS`) — every
    next one would get the same answer, after the same wait or none, so they are handed back to be
    named instead. The method's own refusal is in neither of the first two: nothing failed, and
    nothing in the round changed."""
    fixes = list(fixes)
    done: list[tuple[str, str]] = []
    refused: list[tuple[str, str, str]] = []
    for index, (wrong, right) in enumerate(fixes):
        try:
            outcome, said = _supersede(project_dir, wrong, right)
        except _STOPS as exc:
            return done, refused + [(wrong, right, str(exc))], fixes[index + 1:]
        if outcome == CHANGED:
            done.append((wrong, right))
        elif outcome == FAILED:
            refused.append((wrong, right, said))
    return done, refused, []


def _supersede(project_dir: Path, wrong: str, right: str) -> tuple[str, str]:
    """`supersede`'s call, as `(CHANGED | UNCHANGED | FAILED, what was said)`, with a busy or
    refused answer left raised (`_STOPS`): the refusals that say something about the calls still to
    come. Told apart by the exit code and the method's refusal line (`process_writer.refusal`), not
    by its words."""
    try:
        code, out, err = process_writer.supersede_capture(Path(project_dir), wrong, right)
    except _STOPS:
        raise
    except process_writer.ProcessWriterError as exc:
        return FAILED, str(exc)
    app_log.logger().info("capture-supersede %r -> %r: exit %s", wrong, right, code)
    if code == 0:
        return CHANGED, out or err
    said = process_writer.refusal(code, err)
    if said:  # the method's own «never took it», or a round closed since: nothing to correct
        return UNCHANGED, said
    return FAILED, str(process_writer.no_answer("capture-supersede", code, out, err))


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
