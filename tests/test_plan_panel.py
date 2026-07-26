"""Headless smoke tests for the mock-data-driven Plan-Fact + measurement panels."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc.measurement_panel import MeasurementPanel  # noqa: E402
from autosound_tcc.ui.tcc.mock_data import MEAS, PLAN  # noqa: E402
from autosound_tcc.ui.tcc.plan_panel import PlanPanel, _PhaseRow  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_only_the_current_phase_starts_expanded():
    _app()
    for phase in PLAN:
        row = _PhaseRow(phase)
        if phase.current:
            assert not row._steps_container.isHidden()
        elif phase.steps:
            assert row._steps_container.isHidden()


def test_plan_panel_builds_one_row_per_phase():
    _app()
    panel = PlanPanel()
    rows = panel.widget().findChildren(_PhaseRow)
    assert len(rows) == len(PLAN)


def test_retranslate_does_not_leave_stale_rows_behind():
    """Regression: see test_dialog_panel.py's identical-shaped test -- deleteLater() alone
    without setParent(None) first leaves the old rows as real children until the event loop
    next spins, which a synchronous retranslate() call never triggers on its own."""
    _app()
    panel = PlanPanel()
    panel.retranslate()
    assert len(panel.widget().findChildren(_PhaseRow)) == len(PLAN)
    panel.retranslate()
    assert len(panel.widget().findChildren(_PhaseRow)) == len(PLAN)


def test_measurement_panel_builds_three_columns():
    _app()
    panel = MeasurementPanel()
    assert len(MEAS.groups) == 3
    # one _MeasRow per item across all groups
    from autosound_tcc.ui.tcc.measurement_panel import _MeasRow

    rows = panel.findChildren(_MeasRow)
    assert len(rows) == sum(len(g.items) for g in MEAS.groups)
