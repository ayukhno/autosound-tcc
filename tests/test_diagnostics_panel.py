"""The diagnostics dialog renders a report; it never computes one.

Fed hand-built `ContractReport`s so the rendering is tested independently of whether the submodule
is checked out (`test_contract_check.py` covers the real checker).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from autosound_tcc.core.contract_check import ContractReport  # noqa: E402
from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.diagnostics_panel import DiagnosticsDialog  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _texts(dialog: DiagnosticsDialog) -> str:
    return "\n".join(label.text() for label in dialog.findChildren(QLabel))


def _report(**overrides) -> ContractReport:
    base = dict(
        ok=False,
        project_dir="/tmp/proj",
        files=(
            {"file": "project.json", "exists": True, "schema_version": 1, "valid": True,
             "issues": [], "open_questions": ["car.make"]},
            {"file": "dsp_profile.json", "exists": False, "schema_version": None, "valid": None,
             "issues": ["missing -- run intake/onboarding"]},
            {"file": "state/SQ/v_002.json", "exists": True, "schema_version": 2, "valid": False,
             "issues": ["unknown EQ type 'XX'"]},
        ),
        cross_checks={
            "glossary_vs_ledgers": ["SQ: ledger channel(s) not in the glossary: ['tw-R']"],
            "tiers_vs_profile": [],
            "rew": {"reachable": False, "note": "REW not reachable (conn refused) -- skipped"},
        },
        checked_at="2026-07-31T12:00:00+00:00",
        duration_s=0.25,
    )
    base.update(overrides)
    return ContractReport(**base)


def test_renders_every_file_row_and_the_cross_check_finding():
    _app()
    dialog = DiagnosticsDialog()

    dialog.set_report(_report())

    text = _texts(dialog)
    assert "project.json" in text
    assert "dsp_profile.json" in text
    assert "state/SQ/v_002.json" in text
    assert "unknown EQ type 'XX'" in text
    assert "not in the glossary" in text
    assert "REW not reachable" in text
    assert "/tmp/proj" in text


def test_verdict_counts_defects_only():
    """Two: the invalid ledger and the cross-file mismatch. A file that is merely MISSING and an
    open question on project.json are both intake that hasn't happened, not defects — the checker's
    own `ok` treats them that way, and a verdict that disagreed with it would be the panel's."""
    _app()
    dialog = DiagnosticsDialog()

    dialog.set_report(_report())

    text = _texts(dialog)
    assert i18n.t("diagIssues").format(n=2) in text
    assert "car.make" in text
    assert "missing -- run intake/onboarding" in text  # still SHOWN, just not counted


def test_ok_report_says_so():
    _app()
    dialog = DiagnosticsDialog()

    dialog.set_report(
        _report(ok=True, files=(), cross_checks={"glossary_vs_ledgers": [], "tiers_vs_profile": [],
                                                 "rew": {}})
    )

    assert i18n.t("diagOk") in _texts(dialog)


def test_a_failed_run_shows_the_reason_not_an_empty_table():
    _app()
    dialog = DiagnosticsDialog()

    dialog.set_report(
        ContractReport(ok=False, project_dir="/tmp/proj", error="contract.py not found at /nope")
    )

    text = _texts(dialog)
    assert i18n.t("diagUnavailable") in text
    assert "contract.py not found at /nope" in text


def test_none_means_checking_not_stale_data():
    _app()
    dialog = DiagnosticsDialog()
    dialog.set_report(_report())

    dialog.set_report(None)

    text = _texts(dialog)
    assert i18n.t("diagChecking") in text
    assert "unknown EQ type 'XX'" not in text
    assert not dialog._refresh_btn.isEnabled()


def test_refresh_asks_the_window_and_does_not_check_anything_itself():
    _app()
    dialog = DiagnosticsDialog()
    dialog.set_report(_report())
    calls = []
    dialog.refreshRequested.connect(lambda: calls.append(1))

    dialog._refresh_btn.click()

    assert calls == [1]
    assert i18n.t("diagChecking") in _texts(dialog)


def test_language_switch_retranslates_an_open_dialog():
    _app()
    dialog = DiagnosticsDialog()
    dialog.set_report(_report())
    try:
        i18n.set_language("uk")
        text = _texts(dialog)
        assert i18n.t("diagFiles") in text
        assert "unknown EQ type 'XX'" in text  # the skill's own words stay as they are
    finally:
        i18n.set_language("en")
