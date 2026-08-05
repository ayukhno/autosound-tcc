"""Headless smoke tests for the mock-data-driven Plan-Fact + measurement panels."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.measurement_panel import MeasurementPanel  # noqa: E402
from autosound_tcc.ui.tcc.mock_data import MEAS, MEAS_SESSIONS, PLAN, PlanStep, sessions_for_step  # noqa: E402
from autosound_tcc.ui.tcc.plan_panel import (  # noqa: E402
    _PhaseRow,
    _PhaseStepRow,
    _PlanProgress,
    PlanPanel,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_only_the_current_phase_starts_expanded():
    _app()
    progress = _PlanProgress()
    for i, phase in enumerate(PLAN):
        row = _PhaseRow(phase, i, progress, lambda: None, lambda _sid: None)
        if phase.current:
            assert not row._steps_container.isHidden()
        else:
            assert row._steps_container.isHidden()


def test_plan_panel_builds_one_row_per_phase():
    _app()
    panel = PlanPanel()
    panel.set_plan(PLAN)
    rows = panel.widget().findChildren(_PhaseRow)
    assert len(rows) == len(PLAN)


def test_a_project_with_no_process_state_shows_no_plan_at_all():
    """It used to fall back to the mock, so a real project that had not started tuning showed
    seven invented phases with invented progress -- the same mistake the dialog panel already
    refuses to make with demo bubbles."""
    _app()
    panel = PlanPanel()

    panel.set_plan(None)

    assert panel.widget().findChildren(_PhaseRow) == []
    assert any(
        i18n.t("planEmpty") in label.text() for label in panel.widget().findChildren(QLabel)
    )


def test_no_project_and_no_plan_say_different_things():
    _app()
    panel = PlanPanel()

    panel.set_plan(())

    assert any(
        i18n.t("planNoProject") in label.text() for label in panel.widget().findChildren(QLabel)
    )


def test_retranslate_does_not_leave_stale_rows_behind():
    """Regression: see test_dialog_panel.py's identical-shaped test -- deleteLater() alone
    without setParent(None) first leaves the old rows as real children until the event loop
    next spins, which a synchronous retranslate() call never triggers on its own."""
    _app()
    panel = PlanPanel()
    panel.set_plan(PLAN)
    panel.retranslate()
    assert len(panel.widget().findChildren(_PhaseRow)) == len(PLAN)
    panel.retranslate()
    assert len(panel.widget().findChildren(_PhaseRow)) == len(PLAN)


def test_skip_step_gets_dimmed_row_class():
    _app()
    progress = _PlanProgress()
    step = PlanStep(id="x.1", name={"en": "skipped one", "uk": "пропущено"}, skip=True)
    row = _PhaseStepRow(step, progress, lambda *_: None, lambda _sid: None)
    assert row.property("class") == "step-skip"


def test_attempt_gt_one_renders_attempt_chip():
    _app()
    progress = _PlanProgress()
    step = PlanStep(id="x.2", name={"en": "redone", "uk": "переробили"}, attempt=2)
    row = _PhaseStepRow(step, progress, lambda *_: None, lambda _sid: None)
    from PySide6.QtWidgets import QLabel

    labels = [w for w in row.findChildren(QLabel) if "stag-attempt" in (w.property("class") or "")]
    assert len(labels) == 1
    assert "2" in labels[0].text()


def test_project_source_step_gets_blue_class():
    _app()
    progress = _PlanProgress()
    step = PlanStep(id="x.3", name={"en": "situational", "uk": "ситуативний"}, source="project")
    row = _PhaseStepRow(step, progress, lambda *_: None, lambda _sid: None)
    from PySide6.QtWidgets import QLabel

    name_label = row.findChildren(QLabel)[0]
    assert name_label.property("class") == "substep-name-project"


def test_the_checkbox_shows_what_the_skill_wrote(tmp_path):
    """It used to read a local QSettings overlay left over from the mock, so a finished phase
    showed unticked steps."""
    _app()
    from PySide6.QtWidgets import QCheckBox

    done = PlanStep(id="x.1", name={"en": "done one", "uk": "зроблено"}, tag_class="ok")
    todo = PlanStep(id="x.2", name={"en": "todo one", "uk": "треба"})

    assert _PhaseStepRow(done, _PlanProgress(), lambda *_: None, lambda _s: None
                         ).findChild(QCheckBox).isChecked()
    assert not _PhaseStepRow(todo, _PlanProgress(), lambda *_: None, lambda _s: None
                             ).findChild(QCheckBox).isChecked()


def test_the_checkbox_cannot_be_clicked(tmp_path):
    """SCR-004: v1's only writer is the skill. Ticking one here recorded nothing, contradicted the
    file, and invited a decision against a plan that existed only in this window."""
    _app()
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtWidgets import QCheckBox

    row = _PhaseStepRow(
        PlanStep(id="x.1", name={"en": "one", "uk": "один"}), _PlanProgress(),
        lambda *_: None, lambda _s: None,
    )
    checkbox = row.findChild(QCheckBox)

    assert checkbox.testAttribute(_Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_inserted_step_appears_in_phase_and_persists():
    _app()
    progress = _PlanProgress()
    progress.add_step(0, "extra situational step")
    inserted = progress.inserted_steps(0)
    assert len(inserted) == 1
    assert inserted[0].source == "project"
    assert i18n_tx(inserted[0].name) == "extra situational step"

    reloaded = _PlanProgress()
    assert len(reloaded.inserted_steps(0)) == 1


def i18n_tx(name_dict):
    from autosound_tcc.ui.tcc import i18n

    return i18n.tx(name_dict)


def test_measurement_panel_builds_three_columns():
    _app()
    panel = MeasurementPanel()
    panel.set_sessions(MEAS_SESSIONS)  # the mock is a fixture, not a default
    assert len(MEAS.groups) == 3
    # one _MeasRow per item across all groups
    from autosound_tcc.ui.tcc.measurement_panel import _MeasRow

    rows = panel.findChildren(_MeasRow)
    assert len(rows) == sum(len(g.items) for g in MEAS.groups)


def test_step_with_linked_sessions_shows_measurement_icon():
    """Step "2.3" has a mock session linked to it (user request 2026-07-28) -- its row should
    carry the measurement icon; a step with none (e.g. "0.1") should not."""
    _app()
    progress = _PlanProgress()
    assert sessions_for_step("2.3")
    step_with = next(s for phase in PLAN for s in phase.steps if s.id == "2.3")
    row = _PhaseStepRow(step_with, progress, lambda *_: None, lambda _sid: None)
    from PySide6.QtWidgets import QLabel

    icons = [w for w in row.findChildren(QLabel) if w.property("class") == "step-meas-icon"]
    assert len(icons) == 1

    assert not sessions_for_step("0.1")
    step_without = next(s for phase in PLAN for s in phase.steps if s.id == "0.1")
    row2 = _PhaseStepRow(step_without, progress, lambda *_: None, lambda _sid: None)
    icons2 = [w for w in row2.findChildren(QLabel) if w.property("class") == "step-meas-icon"]
    assert len(icons2) == 0


def test_clicking_measurement_icon_invokes_callback_with_newest_session_id():
    _app()
    progress = _PlanProgress()
    step = next(s for phase in PLAN for s in phase.steps if s.id == "2.3")
    seen = []
    row = _PhaseStepRow(step, progress, lambda *_: None, seen.append)
    from PySide6.QtWidgets import QLabel

    icon = next(w for w in row.findChildren(QLabel) if w.property("class") == "step-meas-icon")
    icon.mousePressEvent(None)
    assert seen == [sessions_for_step("2.3")[0].id]


def test_plan_panel_session_requested_reaches_measurement_panel():
    """End-to-end wiring check (main_window.py connects this the same way): PlanPanel's signal,
    when connected to MeasurementPanel.show_session, actually switches the displayed session."""
    _app()
    plan = PlanPanel()
    meas = MeasurementPanel()
    plan.sessionRequested.connect(meas.show_session)
    assert meas._viewing_id == "v10"
    plan.sessionRequested.emit("v9")
    assert meas._viewing_id == "v9"
