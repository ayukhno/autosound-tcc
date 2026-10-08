"""Capture rounds written the way the method writes them: through its own `Process` (SCR-034, T-29).

Shared since #175, so the tests that read a round read one the method wrote — a typo superseded,
a skip taken back, a round closed by the next one opening — and none a journal typed by hand. A
hand-written journal pins the shape TCC folds today, not the one the method writes, and the two
had drifted: no fixture here held a `superseded_by` or a closing event's `outstanding`.

**The awkward shape is the default** (2026-09-06). Titles go in ZERO-PADDED, as typed in REW,
while every assertion is written against the derived name — because that is the shape a real
project has and the shape no fixture had. It cost a regression that reached a tag's door: a closed
pass holding fourteen verified captures read as fourteen rows still waiting, and every test passed,
because every fixture wrote the round in the checklist's own spelling.
"""

from __future__ import annotations

import re

from autosound_tcc.core import vendor_loader

from tests import _intake

#: The reason a fixture gives the method for a supersede: it requires none, and keeps one given.
SUPERSEDE_REASON = "fixture: typed under the wrong title, fixed in REW"


def as_typed(title: str) -> str:
    """A title the way a PERSON types it in REW: `sw_1 (sw)` -> `sw_01 (sw)`.

    Zero-padding is what REW titles carry in the field, and the checklist derives the unpadded
    form — `naming.name_key` exists precisely because those two are one name. A fixture that
    writes both sides in the same spelling cannot tell whether the code compares keys or strings.
    """
    return re.sub(r"_(\d)(?=\D|$)", r"_0\1", str(title))


def write_round(project, **fields):
    """Open a capture round in `project` at phase 0 and record into it, through the method's own
    writer; returns the `Process`.

    `expected`, `taken` (in order), `superseded` — `{wrong: right}`, each through
    `Process.supersede_capture`, after the takes, which marks the wrong row and takes the right
    title — and `skipped` (`{title: reason}`, last). `pad=False` for a fixture that is
    deliberately about the tidy case.
    """
    from autosound_tcc.state import process_view

    pad = fields.pop("pad", True)
    typed = as_typed if pad else (lambda title: str(title))
    module = vendor_loader.load_process()
    _intake.seed(project)
    process = module.Process(str(process_view.process_dir(project)))
    process.enter_phase("0")
    process.start_capture(fields.pop("version", 1),
                          expected=[typed(t) for t in fields.pop("expected", ())])
    for title in fields.pop("taken", ()):
        process.record_capture(typed(title))
    for wrong, right in (fields.pop("superseded", {}) or {}).items():
        process.supersede_capture(typed(wrong), typed(right), SUPERSEDE_REASON)
    for title, reason in (fields.pop("skipped", {}) or {}).items():
        process.skip_capture(typed(title), reason)
    assert not fields, f"write_round does not know {sorted(fields)}"
    return process
