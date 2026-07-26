"""The right-panel Plan — Fact tree — ported from the prototype's `renderPlan`
(`data/private/prototype/tcc-main.html`): a phase list where only the current phase starts
expanded, each phase showing a status dot (done/current/todo) and its steps with a status tag.

Mock data only (`ui/tcc/mock_data.py`) — no real project-plan backend yet (M4 scope, see the
plan file).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.mock_data import PLAN, PlanPhase


class _StatusDot(QLabel):
    def __init__(self, status: str) -> None:
        text = "✓" if status == "done" else ""
        super().__init__(text)
        self.setProperty("class", f"st st-{status}")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(15, 15)


class _PhaseStepRow(QWidget):
    def __init__(self, step) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(26, 3, 6, 3)
        layout.setSpacing(8)
        name = QLabel(i18n.tx(step.name))
        name.setProperty("class", "substep-name")
        layout.addWidget(name)
        layout.addStretch(1)
        tag_text = i18n.tx(step.tag) if step.tag else ""
        if tag_text:
            tag = QLabel(tag_text)
            tag.setProperty("class", f"stag stag-{step.tag_class}" if step.tag_class else "stag")
            layout.addWidget(tag)


class _PhaseRow(QWidget):
    def __init__(self, phase: PlanPhase) -> None:
        super().__init__()
        has_steps = len(phase.steps) > 0
        collapsed = has_steps and not phase.current

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setProperty("class", "prow-current" if phase.current else "prow")
        if has_steps:
            header.setCursor(Qt.CursorShape.PointingHandCursor)
        head_layout = QHBoxLayout(header)
        head_layout.setContentsMargins(6, 4, 6, 4)
        head_layout.setSpacing(8)

        self._caret = QLabel("▸" if collapsed else "▾" if has_steps else "")
        self._caret.setProperty("class", "pcaret")
        self._caret.setFixedWidth(12)
        head_layout.addWidget(self._caret)
        head_layout.addWidget(_StatusDot(phase.status))
        name = QLabel(i18n.tx(phase.name))
        name.setProperty("class", "pname-current" if phase.current else "pname")
        head_layout.addWidget(name)
        head_layout.addStretch(1)
        if has_steps:
            count = QLabel(str(len(phase.steps)))
            count.setProperty("class", "pcnt")
            head_layout.addWidget(count)
        outer.addWidget(header)

        self._steps_container = QWidget()
        steps_layout = QVBoxLayout(self._steps_container)
        steps_layout.setContentsMargins(0, 0, 0, 2)
        steps_layout.setSpacing(0)
        for step in phase.steps:
            steps_layout.addWidget(_PhaseStepRow(step))
        self._steps_container.setHidden(collapsed)
        outer.addWidget(self._steps_container)

        if has_steps:
            header.mousePressEvent = self._toggle  # type: ignore[assignment]

    def _toggle(self, _event) -> None:
        collapsed = not self._steps_container.isHidden()
        self._steps_container.setHidden(collapsed)
        self._caret.setText("▸" if collapsed else "▾")


class PlanPanel(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 12)
        layout.setSpacing(2)
        for phase in PLAN:
            layout.addWidget(_PhaseRow(phase))
        layout.addStretch(1)
        self.setWidget(body)
