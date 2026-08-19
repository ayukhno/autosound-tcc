"""The diagnostics dialog renders a report; it never computes one.

Fed hand-built `ContractReport`s so the rendering is tested independently of whether the submodule
is checked out (`test_contract_check.py` covers the real checker).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
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


def test_a_problem_in_the_skills_files_can_be_forwarded_but_never_fixed_here(monkeypatch):
    """D-6: those files have an owner and it is not TCC. What TCC can do is carry the checker's
    own words to the thing that may write — and then re-check (user, 2026-08-12)."""
    from autosound_tcc.ui.tcc.diagnostics_panel import _AskRow

    _stub_self_checks(monkeypatch)
    _app()
    dialog = DiagnosticsDialog()
    sent: list[str] = []
    dialog.askRequested.connect(sent.append)

    dialog.set_report(_report())
    rows = dialog.findChildren(_AskRow)
    assert rows, "every issue the checker names is forwardable"

    next(r for r in rows).findChild(QPushButton).click()

    assert len(sent) == 1
    # The checker's own words go with it, and so does the file it is about.
    assert "unknown EQ type 'XX'" in sent[0] or "missing -- run intake/onboarding" in sent[0]
    assert "contract.py check" in sent[0], "it says how the claim will be checked"


def test_asking_records_the_time_and_never_claims_success(monkeypatch):
    """The button reports that it asked. The next check reports the truth — a button that painted
    the row green would be reporting on somebody else's work."""
    from autosound_tcc.ui.tcc.diagnostics_panel import _AskRow

    _stub_self_checks(monkeypatch)
    _app()
    dialog = DiagnosticsDialog()
    dialog.set_report(_report())

    first = dialog.findChildren(_AskRow)[0]
    first.findChild(QPushButton).click()

    # Still reported by the checker, so the row is still there — now saying it was asked about.
    text = _texts(dialog)
    assert i18n.t("diagAgoNow") in text
    assert i18n.t("diagOk") not in text


# ---- the installation tab (user, 2026-08-19) ---------------------------------------------------


def test_the_tool_probe_never_owns_a_qthread():
    """Measured, not assumed: the same probes take 1.2 s on a plain thread and 10.7 s on a
    QThread, because PySide6's import hook reads the source of modules imported while it is
    active. And a plain thread may outlive the dialog, where a QThread destroyed running is
    `qFatal`."""
    import inspect

    from autosound_tcc.ui.tcc import diagnostics_panel

    code = "\n".join(
        line for line in inspect.getsource(diagnostics_panel).splitlines()
        if not line.lstrip().startswith("#")
    )
    body = code.split('"""')
    assert not any("QThread" in part for part in body[::2]), "no QThread in the code itself"
    assert "threading.Thread" in code and "daemon=True" in code


def test_the_dialog_has_a_second_tab_with_what_is_installed():
    """A report from a machine nobody debugging it can see starts with "which versions am I looking
    at". That question is now a tab, in the window a person already opens when something is off."""
    from autosound_tcc.ui.tcc import i18n

    _app()
    dialog = DiagnosticsDialog()

    assert dialog._tabs.count() == 3
    assert dialog._tabs.tabText(0) == i18n.t("diagTabProject")
    assert dialog._tabs.tabText(1) == i18n.t("diagTabInstall")
    assert dialog._tabs.tabText(2) == i18n.t("diagTabLog")


def test_the_report_is_read_only_when_the_tab_is_opened():
    """Eight `--version` subprocesses is not something to pay for opening a dialog about a contract
    check."""
    _app()
    dialog = DiagnosticsDialog()

    assert dialog._install_read is False

    dialog._tabs.setCurrentIndex(1)

    assert dialog._install_read is True
    # Everything that reads a file is already on screen; only the tool probes are on a thread.
    assert "[Autosound TCC]" in dialog._install_text.toPlainText()
    probe = dialog._install_worker
    assert probe is not None
    for _ in range(200):
        if not probe.running:
            break
        QTest.qWait(50)
    dialog._poll_tools()
    text = dialog._install_text.toPlainText()
    assert "[Command-line tools]" in text


def test_the_window_hands_it_the_facts_only_the_window_knows():
    """The MCP server's URL — or the reason it is not running — is state of the running window, so
    it is passed in rather than reached for: `core/install_report` holds no Qt."""
    _app()
    dialog = DiagnosticsDialog()

    dialog.set_install_extra({"MCP": "not running: ValueError"})

    assert dialog._install_extra()["MCP"] == "not running: ValueError"


def test_the_log_tab_shows_the_tail_and_where_it_came_from():
    """The third thing every report has needed after the versions and the reason. Re-read on every
    open: a log looked at once is a log that lies about the run you are in."""
    from autosound_tcc.core import app_log

    _app()
    dialog = DiagnosticsDialog()

    dialog._tabs.setCurrentIndex(2)

    assert dialog._log_text.toPlainText() == app_log.tail()
    path = app_log.log_path()
    assert dialog._log_where.text() == (str(path) if path else i18n.t("diagLogNone"))


def test_copying_the_log_takes_the_path_with_it(monkeypatch, tmp_path):
    """A log with no filename is a log nobody can ask about again."""
    from PySide6.QtGui import QGuiApplication

    from autosound_tcc.core import app_log

    log = tmp_path / "tcc.log"
    log.write_text("first line\nsecond line\n", encoding="utf-8")
    monkeypatch.setattr(app_log, "_log_path", log)
    _app()
    dialog = DiagnosticsDialog()
    dialog._tabs.setCurrentIndex(2)

    dialog._copy_log()

    copied = QGuiApplication.clipboard().text()
    assert str(log) in copied and "second line" in copied


def test_the_update_row_only_offers_a_button_when_there_is_something_to_install():
    """A live "Update" button on an up-to-date install is a question, not an offer."""
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()

    dialog._show_update(updates.Status("skill", "3.0.6", "3.0.7", True))
    label, button = dialog._update_rows["skill"]
    assert "3.0.7" in label.text() and button.isEnabled()

    dialog._show_update(updates.Status("skill", "3.0.7", "3.0.7", False))
    assert not button.isEnabled()
    assert i18n.t("updCurrent").format(what=i18n.t("updSkillName"), here="3.0.7") == label.text()


def test_an_installation_that_is_not_ours_says_so_and_stays_disabled():
    """Somebody's own checkout: the reason is on screen, and no button to break it with."""
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()

    dialog._show_update(updates.Status("tcc", "0.1.1", "", False,
                                       "running from a source checkout — update it with git",
                                       updatable=False))

    label, button = dialog._update_rows["tcc"]
    assert "source checkout" in label.text()
    assert not button.isEnabled()


def test_could_not_ask_is_not_the_same_as_up_to_date():
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()

    dialog._show_update(updates.Status("tcc", "0.1.1", "", False))

    assert dialog._update_rows["tcc"][0].text() == i18n.t("updUnknown")


def test_updating_the_method_reports_the_version_it_landed_on(monkeypatch):
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("skill", "3.0.6", "3.0.7", True))
    monkeypatch.setattr(updates, "apply_skill", lambda tag="": (True, "v3.0.7"))

    dialog._update_skill()

    assert "3.0.7" in dialog._update_rows["skill"][0].text()


def test_a_failed_update_says_why_and_leaves_the_button(monkeypatch):
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("skill", "3.0.6", "3.0.7", True))
    monkeypatch.setattr(updates, "apply_skill", lambda tag="": (False, "fetch failed: no network"))

    dialog._update_skill()

    label, button = dialog._update_rows["skill"]
    assert "no network" in label.text()
    assert button.isEnabled(), "a failure the person can retry must leave them the button"


def test_updating_tcc_is_handed_to_a_terminal(monkeypatch):
    """TCC cannot replace its own running files -- on Windows not at all -- so it does not try."""
    from autosound_tcc.core import terminal_launcher, updates

    _app()
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("tcc", "0.1.1", "abc123", True))
    seen = []
    monkeypatch.setattr(terminal_launcher, "run_line", lambda line: seen.append(line))

    dialog._update_tcc()

    assert seen == [updates.TCC_INSTALL_COMMAND]
    assert "uv tool install" in seen[0] and "--python 3.12" in seen[0]
    assert dialog._update_rows["tcc"][0].text() == i18n.t("updTccHanded")
