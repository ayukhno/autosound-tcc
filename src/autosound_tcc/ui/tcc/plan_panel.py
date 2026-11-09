"""The right-panel Plan — Fact tree — ported from the prototype's `renderPlan`
(`data/private/prototype/tcc-main.html`): a phase list where only the current phase starts
expanded, each phase showing a status dot (done/current/todo) and its steps with a status tag.

Base step structure (`PLAN` in `ui/tcc/mock_data.py`) is mock data -- no real skill-backed plan
backend yet (M4 scope, see the plan file; real sourcing is blocked on the app<->skill boundary,
docs/TCC-TZ.md §4). Layered on top is a small mutable overlay (`_PlanProgress`, this module) that
IS real and persists across sessions via QSettings: per-step completion, and situational
("project") steps the user inserts during a live tuning session -- so the skip/repeat/situational/
completion UI is dogfoodable now even though the base structure itself is still mock (item 8,
2026-07-27).
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import replace

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import config
from autosound_tcc.ui.tcc import discard, i18n
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc.labels import ElidedLabel
from autosound_tcc.ui.tcc.mock_data import PlanPhase, PlanStep, sessions_for_step
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.rounded_tooltip import tip_frame, wrapped
from autosound_tcc.ui.tcc.theme import current_theme

_PROGRESS_KEY = "ui/plan_progress"


class _PlanProgress:
    """Mutable overlay on top of the immutable mock `PLAN`: which steps are done, and any
    situational steps the user has inserted into a phase. Persisted as one JSON blob under a
    single QSettings key -- same "small blob, one key" convention as `ui/tree_collapsed/*`."""

    def __init__(self) -> None:
        self._settings = get_settings()
        raw = self._settings.value(_PROGRESS_KEY, "")
        try:
            data = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            data = {}
        self.done: dict[str, bool] = dict(data.get("done", {}))
        # phase index (str) -> list of inserted-step dicts (id/name/tag/tag_class)  # noqa: E501
        self.inserted: dict[str, list[dict]] = dict(data.get("inserted", {}))

    def _save(self) -> None:
        self._settings.setValue(
            _PROGRESS_KEY, json.dumps({"done": self.done, "inserted": self.inserted})
        )

    def is_done(self, step_id: str) -> bool:
        return bool(self.done.get(step_id))

    def set_done(self, step_id: str, done: bool) -> None:
        self.done[step_id] = done
        self._save()

    def inserted_steps(self, phase_index: int) -> tuple[PlanStep, ...]:
        entries = self.inserted.get(str(phase_index), [])
        return tuple(
            PlanStep(id=e["id"], name=e["name"], source="project")
            for e in entries
        )

    def add_step(self, phase_index: int, text: str) -> None:
        entries = self.inserted.setdefault(str(phase_index), [])
        step_id = f"proj-{phase_index}-{len(entries)}"
        entries.append({"id": step_id, "name": {"en": text, "uk": text}})
        self._save()


class _StatusDot(QLabel):
    def __init__(self, status: str) -> None:
        text = "✓" if status == "done" else ""
        super().__init__(text)
        self.setProperty("class", f"st st-{status}")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(15, 15)


# A phase-0 baseline is one step per driver -- "Baseline solo: tw-L_1 (sw) + tw-L_1 (rta)" nine
# times over. Each is a real step in the skill's plan and each is checked off separately, but as
# nine rows they bury the phase's shape in the one panel whose job is to show it. The detail is
# already in the capture task, channel by channel, which is where it belongs.
#: What each status chip means, keyed by its class. The tick and the chip answer two different
#: questions and were being read as one: the tick is whether the SKILL closed the step, the chip is
#: whether anything on disk stands behind it. A step can be closed and unproven at the same time,
#: which is the whole reason the panel is called plan-versus-fact.
_TAG_HINTS = {
    "ok": "stepTagOkTip",
    "bad": "stepTagUnprovenTip",
    "wait": "stepTagWaitTip",
}

_RUN_PREFIX = re.compile(r"^([^:]{4,}?):\s")

#: Where a step name may be cut for its title (tcc#167): the method writes its rationale after the
#: name, behind one of these. The earliest one that leaves a head of at least `_TITLE_MIN`
#: characters is the cut; an earlier one that leaves less is just a dash in the name.
_TITLE_SEPARATORS = ("\u2014", "\u2013", " (", " + ", "; ")
_TITLE_MIN = 12
_TITLE_MAX = 70


def short_title(text: str) -> tuple[str, str]:
    """`(shown, rest)`: the title a step row shows, and the whole name when there is more to it.

    `rest` is empty when `shown` is the whole name. Otherwise the name is cut at its first
    qualifying separator; a head still longer than `_TITLE_MAX` characters (or a name with no
    separator) is cut at the last space within it and marked with an ellipsis. The row keeps the full name one hover away.
    """
    cut = None
    for sep in _TITLE_SEPARATORS:
        at = text.find(sep)
        while at != -1 and len(text[:at].strip()) < _TITLE_MIN:
            at = text.find(sep, at + 1)
        if at != -1 and (cut is None or at < cut):
            cut = at
    head = text if cut is None else text[:cut].strip()
    if len(head) > _TITLE_MAX:  # a separator past the max cuts nothing short enough (I2)
        space = head.rfind(" ", 0, _TITLE_MAX + 1)
        if space <= 0:  # one token with no space in it: cut it where the title ends
            space = _TITLE_MAX
        head = head[:space].rstrip() + "\u2026"
    return (head, text) if head != text else (text, "")


#: A step's note as a person reads it, the method's field and its label: the Arbiter's answer
#: stands straight after what it answers (tcc#248).
_NOTE_ROWS = (
    ("do", "planNoteDo"),
    ("expect", "planNoteExpect"),
    ("answer", "planNoteAnswer"),
    ("if_not", "planNoteIfNot"),
)
#: A tip's lines per field; past them the tip says the click has the rest.
_NOTE_TIP_LINES = 5


def _note_fields(note) -> list[tuple[str, str]]:
    """(label, text) of the note's filled fields, in reading order."""
    return [(i18n.t(key), getattr(note, name)) for name, key in _NOTE_ROWS if getattr(note, name)]


def _note_tip(note) -> str:
    """The note as a hover tip: escaped by `wrapped`, each field a few lines at most."""
    parts: list[str] = []
    cut = False
    for label, text in _note_fields(note):
        # A hard break in one endless word: the tip's label does not wrap and would be clipped.
        lines = wrapped(re.sub(r"(\S{64})(?=\S)", "\\1\n", text)).split("<br>")
        if len(lines) > _NOTE_TIP_LINES:
            cut = True
            lines = lines[:_NOTE_TIP_LINES]
            lines[-1] += "\u2026"
        parts.append(f"<b>{html.escape(label)}</b><br>" + "<br>".join(lines))
    if cut:
        parts.append(f"<i>{html.escape(i18n.t('planNoteReadAll'))}</i>")
    return tip_frame("<br>".join(parts))


def _note_text(note) -> str:
    """The whole note for the row's fold: rich text, so every field is escaped here. A zero-width
    space in an endless word gives the label somewhere to wrap it."""
    return "<br>".join(
        f"<b>{html.escape(label)}:</b> "
        + html.escape(re.sub(r"(\S{24})(?=\S)", "\\1\u200b", text)).replace("\n", "<br>")
        for label, text in _note_fields(note)
    )


class _NoteIcon(QWidget):
    """The document mark on a step with a note (tcc#248): hover for the note, click to keep it open
    under the row. Drawn, and at a fixed size: a document glyph is in no font every machine has,
    and the width beside the `?` must not move with the window's font look."""

    def __init__(self, on_click) -> None:
        super().__init__()
        self._on_click = on_click
        self.setProperty("class", "step-note-icon")
        self.setFixedSize(11, 14)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)  # repaints on enter and leave

    def mousePressEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        self._on_click()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        t = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(t.info if self.underMouse() else t.muted), 1))
        painter.drawPolygon(QPolygonF([
            QPointF(1.5, 0.5), QPointF(7.0, 0.5), QPointF(9.5, 3.0),
            QPointF(9.5, 13.5), QPointF(1.5, 13.5),
        ]))
        painter.drawPolyline(QPolygonF([QPointF(7.0, 0.5), QPointF(7.0, 3.0), QPointF(9.5, 3.0)]))
        for y in (6.5, 8.5, 10.5):
            painter.drawLine(QPointF(3.5, y), QPointF(7.5, y))
        painter.end()


def _collapse_runs(steps: "tuple[PlanStep, ...]") -> "list[PlanStep]":
    """Fold consecutive steps sharing a "Prefix: " into one row that counts them.

    Only consecutive ones, and only on the prefix the skill itself wrote, so nothing is grouped
    that the plan did not already write as a series. A run of one is left exactly as it was. A step
    with a note stands alone: a counted row has one icon and the note is one step's (tcc#248).
    """
    out: list[PlanStep] = []
    run: list[PlanStep] = []

    def flush() -> None:
        if not run:
            return
        if len(run) == 1:
            out.append(run[0])
        else:
            done = sum(1 for s in run if s.tag_class == "ok")
            prefix = _RUN_PREFIX.match(i18n.tx(run[0].name)).group(1)
            out.append(replace(
                run[0],
                id=f"{run[0].id}+{len(run)}",
                name={"en": f"{prefix} · {done}/{len(run)}", "uk": f"{prefix} · {done}/{len(run)}"},
                tag_class="ok" if done == len(run) else run[0].tag_class,
                skip=all(s.skip for s in run),
            ))
        run.clear()

    for step in steps:
        if step.note is not None:
            flush()
            out.append(step)
            continue
        found = _RUN_PREFIX.match(i18n.tx(step.name))
        if run and found and _RUN_PREFIX.match(i18n.tx(run[0].name)).group(1) == found.group(1):
            run.append(step)
            continue
        flush()
        run.append(step) if found else out.append(step)
    flush()
    return out


class _PhaseStepRow(QWidget):
    def __init__(
        self, step: PlanStep, progress: _PlanProgress, on_toggle, on_session_click,
        sessions_for=sessions_for_step, open_questions=frozenset(), opened=None,
    ) -> None:
        super().__init__()
        #: The list of facts this step closes, built only when there are any (SKL-047).
        self._covers_list = None
        #: The step's note, opened under the row; built only when there is one (tcc#248).
        self._note_view = None
        self._step_id = step.id
        #: What is open under the rows, kept by the panel across a rebuild: ("note"|"covers", id).
        self._opened = set() if opened is None else opened
        # Done is what the skill wrote, never what was clicked here. The checkbox used to read a
        # local QSettings overlay left over from the mock, so a finished phase showed unticked
        # steps *and* the Arbiter could tick one -- recording nothing, contradicting the file, and
        # inviting a decision to be made against a plan that only existed in this window.
        done = step.tag_class == "ok"
        if step.skip:
            self.setProperty("class", "step-skip")
        # One line, with the chips right-aligned on it (user, 2026-08-07). They used to sit on a
        # second line of their own -- which kept the name column wide, at the cost of a status that
        # floated under the step it belonged to and read as a separate entry. The name still wraps,
        # so what the chips take is width from a sentence that has somewhere to go, not a truncated
        # one; and a step's status belongs beside the step.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 3, 6, 3)
        outer.setSpacing(2)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        outer.addLayout(layout)
        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(6)

        check = QCheckBox()
        check.setChecked(done)
        # Its own class, so the sheet gives a done step's box the ok green and a tick (tcc#166),
        # and no other check box in the app.
        check.setProperty("class", "plan-step-check")
        # Read-only on purpose (SCR-004): v1's only writer is the skill, and the Arbiter changes
        # the plan by saying so in the dialog -- which lands as a journal event -- not by clicking
        # a box that writes nowhere.
        check.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(check)

        full_name = i18n.tx(step.name)
        shown, rest = short_title(full_name)
        name = QLabel(shown)
        # Wrapped, not elided: a step name is a sentence the skill wrote ("Bonus baseline solo:
        # c_1 (sw) + c_1 (rta) (captured early, out of order)") and the panel has vertical room
        # but only about 190 px of width. Unwrapped, the longest step decided the panel's width,
        # so the whole column scrolled sideways and every other row lost its right-hand end.
        name.setWordWrap(True)
        # And it never sets the column's width either: wrapping breaks at spaces, so one token
        # with no space in it — a path, a long REW title — still makes the label's minimum the
        # token's width, and the whole column follows (the left column learned this from a
        # ledger refusal naming two Windows paths, 2026-09-06).
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        if done:
            name.setProperty("class", "substep-name-done")
            font = QFont(name.font())
            font.setStrikeOut(True)
            name.setFont(font)
        elif step.source == "project":
            name.setProperty("class", "substep-name-project")
        else:
            name.setProperty("class", "substep-name")
        layout.addWidget(name, 1)
        # A column after the title: the icon stands under the `?`, not beside it. The right column
        # can be 200 px with a chip on the row, and the title lives on what is left (tcc#248).
        hints = QVBoxLayout()
        hints.setContentsMargins(0, 0, 0, 0)
        hints.setSpacing(2)
        top = Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        if rest:
            # The rest of the name, one hover away, right after the title (tcc#167), in the panel's
            # own rounded tip as the chips beside it. Plain text, escaped: the name is the method's.
            hint = QLabel("?")
            hint.setProperty("class", "step-title-hint")
            attach_tip(hint, html.escape(rest))
            hints.addWidget(hint, 0, top)
        if step.note is not None:
            icon = _NoteIcon(self._toggle_note)
            attach_tip(icon, _note_tip(step.note))
            hints.addWidget(icon, 0, top)
        if hints.count():
            hints.addStretch(1)
            layout.addLayout(hints)

        has_chip = False
        if step.attempt > 1:
            attempt = QLabel(f"{i18n.t('attempt')} {step.attempt}")
            attempt.setProperty("class", "stag stag-attempt")
            chips.addWidget(attempt)
            has_chip = True

        tag_text = i18n.tx(step.tag) if step.tag else ""
        if tag_text:
            tag = QLabel(tag_text)
            tag.setProperty("class", f"stag stag-{step.tag_class}" if step.tag_class else "stag")
            # What the chip means, and — for the two that are easy to read as "not done" — how it
            # differs from an unticked box (user, 2026-08-07: "what is 'unproven', and how is it
            # different from no tick?"). The tick says the skill closed the step; the chip says
            # whether anything on disk stands behind it.
            hint = _TAG_HINTS.get(str(step.tag_class or ""))
            if hint:
                attach_tip(tag, i18n.t(hint))
            chips.addWidget(tag)
            has_chip = True

        # Measurement icon (user request 2026-07-28): shown when this step has capture series
        # linked to it; hover lists them all, click opens the newest in the measurement panel
        # below (PlanPanel.sessionRequested -> main_window.py -> MeasurementPanel.show_session).
        # `sessions_for` used to be `mock_data.sessions_for_step` directly, so the icon could only
        # ever appear on mock step ids — invisible on every real project (user, 2026-08-11).
        sessions = sessions_for(step.id)
        if sessions:
            meas_icon = QLabel("▤")
            meas_icon.setProperty("class", "step-meas-icon")
            meas_icon.setCursor(Qt.CursorShape.PointingHandCursor)
            attach_tip(meas_icon, "<br>".join(f"{s.id} — {i18n.tx(s.version)}" for s in sessions))
            meas_icon.mousePressEvent = (  # type: ignore[assignment]
                lambda _e, sid=sessions[0].id: on_session_click(sid)
            )
            chips.addWidget(meas_icon)
            has_chip = True

        # What this step CLOSES, not only how many (method SKL-047, hub #189). The Arbiter read a
        # step as `Закрити відкриті поля: project.json (8) і dsp_profile.json (5)` and said it meant
        # nothing to him -- thirteen facts named nowhere, in the one artefact he acts on. The names
        # existed all along (`project.py open-questions`); the step had no field to carry them.
        #
        # Collapsed by default, and that is not timidity: a phase has a dozen steps, and a plan
        # where every list is open is a wall. The chip carries the count, which is the affordance
        # -- the same job the `+N` does inside the composed name.
        if step.covers:
            covers_chip = QLabel(f"\u25be {len(step.covers)}")
            covers_chip.setProperty("class", "stag step-covers-chip")
            covers_chip.setCursor(Qt.CursorShape.PointingHandCursor)
            attach_tip(covers_chip, i18n.t("planCoversTip"))
            covers_chip.mousePressEvent = (  # type: ignore[assignment]
                lambda _e: self._toggle_covers()
            )
            chips.addWidget(covers_chip)
            has_chip = True

        if has_chip:
            layout.addLayout(chips)

        if step.covers:
            # Marked on the OPEN ones, not on the answered: the list exists to say what is left.
            # `open_questions` is `_open_questions` from both files keyed the way `covers` spells
            # them (`project_view.open_questions_by_file`), so this is a lookup and not a guess --
            # which is the whole reason the method writes dotted paths rather than a summary.
            mark = i18n.t("planCoversOpen")
            lines = [
                f"\u2022 {fact}" + (f"  \u2014 {mark}" if fact in open_questions else "")
                for fact in step.covers
            ]
            self._covers_list = QLabel("\n".join(lines))
            self._covers_list.setProperty("class", "step-covers-list")
            self._covers_list.setWordWrap(True)
            # Same reason the name does it: one dotted path with no space in it would otherwise
            # set the whole column's minimum width.
            self._covers_list.setSizePolicy(QSizePolicy.Policy.Ignored,
                                            QSizePolicy.Policy.Preferred)
            self._covers_list.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            outer.addWidget(self._covers_list)
            self._covers_list.setHidden(("covers", step.id) not in self._opened)

        if step.note is not None:
            # In the row, not a window: nothing blocks, and the text can be selected. Rich text
            # with every field escaped (`_note_text`): the note is what a session wrote.
            self._note_view = QLabel(_note_text(step.note))
            self._note_view.setTextFormat(Qt.TextFormat.RichText)
            self._note_view.setProperty("class", "step-note-view")
            # The policy first: `setWordWrap` sets its height-for-width, and a policy set after it
            # takes that off again and a long note is cut at the height of a short one.
            self._note_view.setSizePolicy(QSizePolicy.Policy.Ignored,
                                          QSizePolicy.Policy.Preferred)
            self._note_view.setWordWrap(True)
            self._note_view.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            outer.addWidget(self._note_view)
            self._note_view.setHidden(("note", step.id) not in self._opened)

    def _toggle_fold(self, view: QLabel, kind: str) -> None:
        """Open or close something under the row, and remember it across a rebuild of the plan."""
        view.setHidden(not view.isHidden())
        key = (kind, self._step_id)
        (self._opened.discard if view.isHidden() else self._opened.add)(key)

    def _toggle_covers(self) -> None:
        """Open or close the list. Read-only either way: `covers` is set when the step is added
        and steps are never rewritten (SCR-004) -- the window has nothing to write back."""
        if self._covers_list is not None:
            self._toggle_fold(self._covers_list, "covers")

    def _toggle_note(self) -> None:
        """Open or close the note. Read-only too: the note is the method's."""
        if self._note_view is not None:
            self._toggle_fold(self._note_view, "note")


class _PhaseRow(QWidget):
    def __init__(
        self, phase: PlanPhase, phase_index: int, progress: _PlanProgress, on_changed,
        on_session_click, sessions_for=sessions_for_step, open_questions=frozenset(),
        folds=None, opened=None,
    ) -> None:
        super().__init__()
        steps = phase.steps + progress.inserted_steps(phase_index)
        has_steps = len(steps) > 0
        # The "+ add step" affordance below means the steps container is never truly empty, even
        # for a phase with zero base steps (e.g. Phase 5) -- always collapsible, collapsed by
        # default except for the current phase.
        #: Only what the person changed is kept (`folds`, the panel's): a phase he never touched
        #: follows the plan, so the next phase still opens itself when the session moves on.
        self._folds = {} if folds is None else folds
        self._index = phase_index
        self._default_collapsed = not phase.current
        collapsed = self._folds.get(phase_index, self._default_collapsed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setProperty("class", "prow-current" if phase.current else "prow")
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        head_layout = QHBoxLayout(header)
        head_layout.setContentsMargins(6, 4, 6, 4)
        head_layout.setSpacing(8)

        self._caret = QLabel("▸" if collapsed else "▾")
        self._caret.setProperty("class", "pcaret")
        self._caret.setFixedWidth(12)
        head_layout.addWidget(self._caret)
        head_layout.addWidget(_StatusDot(phase.status))
        # Elided, unlike the steps below it: a phase header is one line with a count chip at its
        # right, and wrapping it would push that chip around. The full title is in the tooltip.
        name = ElidedLabel(i18n.tx(phase.name), min_width=60)
        name.setProperty("class", "pname-current" if phase.current else "pname")
        head_layout.addWidget(name, 1)
        if has_steps:
            count = QLabel(str(len(steps)))
            count.setProperty("class", "pcnt")
            head_layout.addWidget(count)
        outer.addWidget(header)

        # Parented AT CONSTRUCTION, and that is not style. A widget with no parent IS a
        # top-level window, so `setHidden(False)` below put a real 200x728 window on the
        # desktop for ~60 ms — once per phase, on every rebuild, which is once per MCP
        # call. That was the flash hunted for a day as a console problem; a Qt event
        # filter finally named this line by its own stack (probe35, 2026-09-11).
        self._steps_container = QWidget(self)
        steps_layout = QVBoxLayout(self._steps_container)
        steps_layout.setContentsMargins(0, 0, 0, 2)
        steps_layout.setSpacing(0)

        def _on_toggle(step_id: str, checked: bool) -> None:
            progress.set_done(step_id, checked)

        for step in _collapse_runs(steps):
            steps_layout.addWidget(
                _PhaseStepRow(step, progress, _on_toggle, on_session_click, sessions_for,
                              open_questions, opened)
            )

        # "+ add step" wrote into the same local overlay the checkbox did, so a step added here
        # existed in this window and nowhere else -- not in the plan the model reads, not in the
        # journal. Adding a step is `add_step` on the MCP surface; the Arbiter asks for it in the
        # dialog. Gone rather than disabled: a control that cannot work is not a hint.

        # In the layout FIRST, shown second. Belt and braces beside the parent above: whichever
        # of the two a later edit undoes, the other still makes a window impossible.
        outer.addWidget(self._steps_container)
        self._steps_container.setHidden(collapsed)

        header.mousePressEvent = self._toggle  # type: ignore[assignment]

    def _add_step(self, phase_index: int, progress: _PlanProgress, on_changed) -> None:
        text, ok = QInputDialog.getText(self, i18n.t("addStep"), i18n.t("addStepPrompt"))
        if ok and text.strip():
            progress.add_step(phase_index, text.strip())
            on_changed()

    def _toggle(self, _event) -> None:
        collapsed = not self._steps_container.isHidden()
        self._steps_container.setHidden(collapsed)
        self._caret.setText("▸" if collapsed else "▾")
        if collapsed == self._default_collapsed:
            self._folds.pop(self._index, None)
        else:
            self._folds[self._index] = collapsed


class PlanPanel(QScrollArea):
    sessionRequested = Signal(str)  # session id -- main_window.py wires this to MeasurementPanel

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        # Sideways too, when a step is wider than the card (the Arbiter, 2026-09-23).
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._progress = _PlanProgress()
        self._sessions: tuple = ()
        self._open_questions: frozenset = frozenset()
        # The real plan from the skill's process-state, or None for "there isn't one yet".
        # None used to fall back to the mock `PLAN`, which meant a real project that had not
        # started tuning showed seven invented phases with invented progress -- the same mistake
        # the dialog panel already refuses to make with demo bubbles. An empty plan says so.
        self._plan: tuple[PlanPhase, ...] | None = None
        #: Why `process-state.json` does not read, when it does not (`process_view.StateUnread`):
        #: said in place of «No plan yet» while no plan is on screen (K-2, #219).
        self._unread = None
        #: What the person opened or closed, so a reload of the plan keeps it (tcc#248): phase
        #: index -> collapsed, what is open under the rows, and the project they belong to.
        self._phase_folds: dict[int, bool] = {}
        self._opened: set[tuple[str, str]] = set()
        self._folds_of = None
        self._body = QWidget()
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(8, 8, 8, 12)
        self._layout.setSpacing(2)
        self.setWidget(self._body)
        self.retranslate()

    def set_plan(self, phases: "tuple[PlanPhase, ...] | None") -> None:
        """Swap in the real plan, or None when the project has no process state yet.

        The window calls this on every write of the state. A write that left the plan as it was
        leaves the rows alone; one that changed it rebuilds them with the folds kept (tcc#248).
        """
        project = config.chosen_project_dir()
        if project != self._folds_of:
            self._folds_of = project
            self._phase_folds.clear()
            self._opened.clear()
        elif phases == self._plan:
            return
        self._plan = phases
        self.retranslate()

    def set_unread(self, said) -> None:
        """`process-state.json` does not read (`process_view.StateUnread`), or None once it does. A
        plan on screen stays — the last one known to be true; a panel with none says why and the
        method's repair, not «No plan yet» over a file with a plan in it (#219)."""
        if said != self._unread:
            self._unread = said
            self.retranslate()

    def set_open_questions(self, questions) -> None:
        """Which intake facts the project still has open, keyed `<file>:<dotted.path>`.

        Only ever read here: a step's `covers` names the facts it closes, and this says which of
        them are left. The panel's own tick stays the skill's to write (SCR-004), so "still open"
        is a fact off disk rather than something anybody clicks.
        """
        questions = frozenset(questions or ())
        if questions != self._open_questions:
            self._open_questions = questions
            self.retranslate()

    def set_sessions(self, sessions) -> None:
        """The project's real capture series, live first (see `measurement_view.build_sessions`).

        Until they arrive the per-step measurement icon falls back to the mock's own linkage, which
        is what the design fixture needs and what a real project never matches.
        """
        self._sessions = tuple(sessions or ())
        self.retranslate()

    def _sessions_for_step(self, step_id: str):
        if not self._sessions:
            return sessions_for_step(step_id)
        return tuple(s for s in self._sessions if step_id in s.used_in_steps)

    @property
    def plan(self) -> "tuple[PlanPhase, ...]":
        return self._plan if self._plan is not None else ()

    def _empty_text(self) -> str:
        """What an empty panel says: why the state does not read, and its repair, when it does not;
        else «No plan yet» or «No project open»."""
        said = self._unread
        if said is None:
            return i18n.t("planEmpty" if self._plan is None else "planNoProject")
        text = i18n.t("planUnread").format(why=said.why)
        return f"{text} {i18n.t('processStateRepair').format(repair=said.repair)}" if said.repair \
            else text

    def retranslate(self) -> None:
        """Rebuild every phase/step row from the active plan + the progress overlay in the current
        language --
        simplest correct approach for data this small (no in-place text-swapping to keep in sync),
        same full-rebuild convention used by dsp_tree.py's set_view()."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                # setParent(None) first -- deleteLater() alone leaves the old, un-laid-out
                # widget visibly overlapping the freshly-built replacement until the next
                # event-loop pass.
                discard.drop(widget)
        plan = self.plan
        if not plan:
            # Which of the two empty states this is matters: a project with no plan is waiting for
            # a session, a window with no project is waiting for a folder.
            empty = QLabel(self._empty_text())
            empty.setWordWrap(True)
            empty.setProperty("class", "muted")
            self._layout.addWidget(empty)
            self._layout.addStretch(1)
            return
        for i, phase in enumerate(plan):
            row = _PhaseRow(phase, i, self._progress, self.retranslate,
                            self.sessionRequested.emit, self._sessions_for_step,
                            self._open_questions, self._phase_folds, self._opened)
            self._layout.addWidget(row)
            # Shown now, in the layout already. Left to Qt it happens a tick later, and the layout
            # pass in between measures an empty panel: the scroll range goes to 0 and the place
            # the person had scrolled to is lost on every write of the state (tcc#248).
            row.show()
        self._layout.addStretch(1)
