"""The diagnostics dialog renders a report; it never computes one.

Fed hand-built `ContractReport`s so the rendering is tested independently of whether the submodule
is checked out (`test_contract_check.py` covers the real checker).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

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


def _stub_self_checks(monkeypatch):
    """The dialog's job is to render and COUNT whatever `self_check.run()` returns; which checks
    exist is `test_self_check.py`'s business. Letting the real list in made these tests depend on
    which agent CLIs the developer has installed."""
    from autosound_tcc.core import self_check

    monkeypatch.setattr(self_check, "run", list)


def test_verdict_counts_defects_only(monkeypatch):
    """Two: the invalid ledger and the cross-file mismatch. A file that is merely MISSING and an
    open question on project.json are both intake that hasn't happened, not defects — the checker's
    own `ok` treats them that way, and a verdict that disagreed with it would be the panel's."""
    _stub_self_checks(monkeypatch)
    _app()
    dialog = DiagnosticsDialog()

    dialog.set_report(_report())

    text = _texts(dialog)
    assert i18n.t("diagIssues").format(n=2) in text
    assert "car.make" in text
    assert "missing -- run intake/onboarding" in text  # still SHOWN, just not counted


def test_ok_report_says_so(monkeypatch):
    _stub_self_checks(monkeypatch)
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


def test_tcc_s_own_setup_gets_a_section_with_a_working_fix(tmp_path, monkeypatch):
    """User, 2026-08-12: "why isn't that in the diagnostics window — it belongs there, with a Fix
    button". The remedy for three redirected reviewers was editing a JSON file nobody opens."""
    from autosound_tcc.core import model_choices, model_overrides, self_check
    from autosound_tcc.ui.tcc.diagnostics_panel import _CheckRow

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(model_choices, "_CLI_CACHE", {})
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: False)
    model_overrides.set_alias("agy:gemini-3.1-pro-high", "sdk:claude-opus-5", "gone")
    _app()

    dialog = DiagnosticsDialog()
    dialog.set_report(_report())
    rows = dialog.findChildren(_CheckRow)

    assert rows, "the section renders even when the project's own files are clean"
    alias_row = next(r for r in rows if r.findChild(QPushButton) is not None)
    alias_row.findChild(QPushButton).click()

    assert model_overrides.load()["aliases"] == {}
    # ...and the panel now agrees with itself: the row is gone, not just a banner claiming it.
    assert not any(r.findChild(QPushButton) for r in dialog.findChildren(_CheckRow))
    alias_check = next(c for c in self_check.run() if c.id == "aliases")
    assert alias_check.status == self_check.OK


def test_the_headline_counts_tccs_own_problems_too(tmp_path, monkeypatch):
    """It read the project's verdict alone, so the panel could say "OK — nothing to fix" directly
    above a red row of its own making."""
    from autosound_tcc.core import self_check

    _app()
    dialog = DiagnosticsDialog()

    clean = _report(ok=True, files=(), cross_checks={
        "glossary_vs_ledgers": [], "tiers_vs_profile": [], "rew": {"reachable": True}})
    _stub_self_checks(monkeypatch)
    dialog.set_report(clean)
    assert dialog._verdict.text() == i18n.t("diagOk")

    monkeypatch.setattr(self_check, "run", lambda: [
        self_check.Check("stub", self_check.BAD, "something of TCC's own is wrong")
    ])
    dialog._render()

    assert dialog._verdict.text() != i18n.t("diagOk"), "a red row of its own making counts"
    assert "1" in dialog._verdict.text()
