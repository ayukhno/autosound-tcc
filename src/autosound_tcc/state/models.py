"""The shapes the plan and capture panels render — domain types, not mock data (HUB-051).

They were born in `ui/tcc/mock_data.py` beside the prototype's constants, and `state/process_view.py`
and `state/measurement_view.py` took them from there — so the state layer depended on the window,
and on a file named for being fake. They live here now; `mock_data` re-exports them for whoever
still imports them from the old address.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanStep:
    id: str  # stable identity for completion/skip tracking (PlanProgress, plan_panel.py)
    name: dict
    tag: object = ""  # dict {"en","uk"} or "" — mirrors the prototype's tx()-able value
    tag_class: str = ""  # "ok" | "wait" | ""
    source: str = "skill"  # "skill" (base structure) | "project" (situational, inserted by user)
    skip: bool = False  # marked skipped -- still shown, dimmed, order preserved
    attempt: int = 1  # >1 renders an "attempt N" chip (a repeated step, "approach 2")


@dataclass(frozen=True)
class PlanPhase:
    status: str  # "done" | "cur" | "todo"
    name: dict
    steps: tuple[PlanStep, ...] = ()
    current: bool = False


@dataclass(frozen=True)
class MeasItem:
    name: str
    status: str  # "done" | "wait" | "bad"
    count: "int | None" = None
    # `extra`/`additional` (user request 2026-07-28): REW reads can turn up names with a
    # modifier/qualifier beyond the expected `<name> (<method>)` pattern, or graphs outside the
    # expected list entirely -- both are OK, not errors, just flagged blue in the UI rather than
    # silently matched or dropped. `extra` = the qualifier text (row is otherwise a normal
    # expected channel); `additional` = True means this whole row is outside the expected list.
    extra: "str | None" = None
    additional: bool = False
    # What was in the signal path while this capture was measured, as a short phrase ("HP 80
    # LR24"). Empty means the round's record says there was no protective filter — or says
    # nothing, which reads the same downstream (`core/protective.py`). It is on the ITEM rather
    # than looked up by the panel because the row is a renderer: the round and the grammar that
    # turns a title into a channel both live where the session is built.
    protective: str = ""


@dataclass(frozen=True)
class MeasGroup:
    type: str  # column header — a literal label, not translated in the prototype either
    items: tuple[MeasItem, ...]
    # Which capture method this column holds ("sw" / "rta"), when the builder knows. The panel
    # used to infer it from the column INDEX against a three-entry table, which is fine for the
    # mock's fixed three columns and wrong for anything else: phase 2's derived task has five
    # groups, and the fourth would have raised IndexError while rendering. None keeps the old
    # index convention, so the mock and its tests are unaffected.
    method: "str | None" = None


@dataclass(frozen=True)
class MeasTask:
    version: dict
    groups: tuple[MeasGroup, ...]


@dataclass(frozen=True)
class MeasSession(MeasTask):
    """One capture series, current or past (user request 2026-07-28: measurement history,
    scoped to the current preset). `id` is the stable key used for selection
    (measurement_panel.py) and plan-step linkage (`ui/tcc/mock_data.sessions_for_step`,
    `ui/tcc/plan_panel.py`'s per-step measurement icon)."""

    id: str = ""
    # PlanStep ids this session's captures were used for/informed -- the CURRENT session's own
    # entry is what it's *being captured for* right now, not yet "used" past tense.
    used_in_steps: tuple[str, ...] = ()
