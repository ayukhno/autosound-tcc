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

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc.mock_data import PLAN, PlanPhase, PlanStep, sessions_for_step
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip

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
        # phase index (str) -> list of inserted-step dicts (id/name/tag/tag_class)
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


class _PhaseStepRow(QWidget):
    def __init__(self, step: PlanStep, progress: _PlanProgress, on_toggle, on_session_click) -> None:
        super().__init__()
        done = progress.is_done(step.id)
        if step.skip:
            self.setProperty("class", "step-skip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 6, 3)
        layout.setSpacing(8)

        check = QCheckBox()
        check.setChecked(done)
        check.toggled.connect(lambda checked, sid=step.id: on_toggle(sid, checked))
        layout.addWidget(check)

        name = QLabel(i18n.tx(step.name))
        if done:
            name.setProperty("class", "substep-name-done")
            font = QFont(name.font())
            font.setStrikeOut(True)
            name.setFont(font)
        elif step.source == "project":
            name.setProperty("class", "substep-name-project")
        else:
            name.setProperty("class", "substep-name")
        layout.addWidget(name)
        layout.addStretch(1)

        if step.attempt > 1:
            attempt = QLabel(f"{i18n.t('attempt')} {step.attempt}")
            attempt.setProperty("class", "stag stag-attempt")
            layout.addWidget(attempt)

        tag_text = i18n.tx(step.tag) if step.tag else ""
        if tag_text:
            tag = QLabel(tag_text)
            tag.setProperty("class", f"stag stag-{step.tag_class}" if step.tag_class else "stag")
            layout.addWidget(tag)

        # Measurement icon (user request 2026-07-28): shown when this step has capture series
        # linked to it (`mock_data.sessions_for_step`); hover lists them all, click opens the
        # newest in the measurement panel below (PlanPanel.sessionRequested -> main_window.py ->
        # MeasurementPanel.show_session).
        sessions = sessions_for_step(step.id)
        if sessions:
            meas_icon = QLabel("▤")
            meas_icon.setProperty("class", "step-meas-icon")
            meas_icon.setCursor(Qt.CursorShape.PointingHandCursor)
            attach_tip(meas_icon, "<br>".join(f"{s.id} — {i18n.tx(s.version)}" for s in sessions))
            meas_icon.mousePressEvent = (  # type: ignore[assignment]
                lambda _e, sid=sessions[0].id: on_session_click(sid)
            )
            layout.addWidget(meas_icon)


class _PhaseRow(QWidget):
    def __init__(
        self, phase: PlanPhase, phase_index: int, progress: _PlanProgress, on_changed,
        on_session_click,
    ) -> None:
        super().__init__()
        steps = phase.steps + progress.inserted_steps(phase_index)
        has_steps = len(steps) > 0
        # The "+ add step" affordance below means the steps container is never truly empty, even
        # for a phase with zero base steps (e.g. Phase 5) -- always collapsible, collapsed by
        # default except for the current phase.
        collapsed = not phase.current

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
        name = QLabel(i18n.tx(phase.name))
        name.setProperty("class", "pname-current" if phase.current else "pname")
        head_layout.addWidget(name)
        head_layout.addStretch(1)
        if has_steps:
            count = QLabel(str(len(steps)))
            count.setProperty("class", "pcnt")
            head_layout.addWidget(count)
        outer.addWidget(header)

        self._steps_container = QWidget()
        steps_layout = QVBoxLayout(self._steps_container)
        steps_layout.setContentsMargins(0, 0, 0, 2)
        steps_layout.setSpacing(0)

        def _on_toggle(step_id: str, checked: bool) -> None:
            progress.set_done(step_id, checked)

        for step in steps:
            steps_layout.addWidget(_PhaseStepRow(step, progress, _on_toggle, on_session_click))

        add_btn = QPushButton(i18n.t("addStep"))
        add_btn.setProperty("class", "add-step-btn")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(lambda: self._add_step(phase_index, progress, on_changed))
        steps_layout.addWidget(add_btn)

        self._steps_container.setHidden(collapsed)
        outer.addWidget(self._steps_container)

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


class PlanPanel(QScrollArea):
    sessionRequested = Signal(str)  # session id -- main_window.py wires this to MeasurementPanel

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._progress = _PlanProgress()
        # The real plan from the skill's process-state, or None for "there isn't one yet".
        # None used to fall back to the mock `PLAN`, which meant a real project that had not
        # started tuning showed seven invented phases with invented progress -- the same mistake
        # the dialog panel already refuses to make with demo bubbles. An empty plan says so.
        self._plan: tuple[PlanPhase, ...] | None = None
        self._body = QWidget()
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(8, 8, 8, 12)
        self._layout.setSpacing(2)
        self.setWidget(self._body)
        self.retranslate()

    def set_plan(self, phases: "tuple[PlanPhase, ...] | None") -> None:
        """Swap in the real plan, or None when the project has no process state yet."""
        self._plan = phases
        self.retranslate()

    @property
    def plan(self) -> "tuple[PlanPhase, ...]":
        return self._plan if self._plan is not None else ()

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
                widget.setParent(None)
                widget.deleteLater()
        plan = self.plan
        if not plan:
            # Which of the two empty states this is matters: a project with no plan is waiting for
            # a session, a window with no project is waiting for a folder.
            empty = QLabel(i18n.t("planEmpty" if self._plan is None else "planNoProject"))
            empty.setWordWrap(True)
            empty.setProperty("class", "muted")
            self._layout.addWidget(empty)
            self._layout.addStretch(1)
            return
        for i, phase in enumerate(plan):
            self._layout.addWidget(
                _PhaseRow(phase, i, self._progress, self.retranslate, self.sessionRequested.emit)
            )
        self._layout.addStretch(1)
