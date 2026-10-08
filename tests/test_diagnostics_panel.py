"""The diagnostics dialog renders a report; it never computes one.

Fed hand-built `ContractReport`s so the rendering is tested independently of whether the submodule
is checked out (`test_contract_check.py` covers the real checker).
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from autosound_tcc.core import config, contract_check, method_binding, vendor_loader  # noqa: E402
from autosound_tcc.core.contract_check import ContractReport  # noqa: E402
from autosound_tcc.ui.tcc import i18n  # noqa: E402
from autosound_tcc.ui.tcc.diagnostics_panel import DiagnosticsDialog  # noqa: E402

from tests._method_copies import entry, linked, linked_and_approved, same_path  # noqa: E402


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


# ---- a stale ▶️ CONTINUE block (#126; contract.py's `continue_head`, S-084, hub #227) ------------

_DRIFT = {"named": ["v_010"], "heads": {"SQ_Jazzi": "v_013"}, "stale": ["v_010"],
          "warning": "`tuning-changelog`'s ▶️ CONTINUE block names HEAD v_010, and the ledger's HEAD "
                     "is v_013 (SQ_Jazzi) — the block was written before the ledger moved. The "
                     "ledger is what resume trusts; bring the block up to it"}


def _clean(**cross):
    return _report(ok=True, files=(), cross_checks={
        "glossary_vs_ledgers": [], "tiers_vs_profile": [], "rew": {}, **cross})


def test_a_stale_continue_block_is_named_and_counted_nowhere(monkeypatch):
    """The checker's one cross-check the panel never showed. A warning, never part of `ok`, so the
    verdict stays as it was; but named, in the Arbiter's words, and forwardable in the checker's."""
    from autosound_tcc.ui.tcc.diagnostics_panel import _AskRow

    _stub_self_checks(monkeypatch)
    _app()
    dialog = DiagnosticsDialog()
    sent: list[str] = []
    dialog.askRequested.connect(sent.append)

    dialog.set_report(_clean(continue_head=_DRIFT))

    assert i18n.t("diagContinueHead").format(named="v_010", at="v_013 (SQ_Jazzi)") in _texts(dialog)
    assert dialog._verdict.text() == i18n.t("diagOk"), "a warning moves no verdict"
    [row] = dialog.findChildren(_AskRow)
    row.findChild(QPushButton).click()
    assert len(sent) == 1 and _DRIFT["warning"] in sent[0] and "tuning-changelog" in sent[0]


def test_a_continue_block_over_several_slots_names_each_head(monkeypatch):
    _stub_self_checks(monkeypatch)
    _app()
    dialog = DiagnosticsDialog()
    drift = dict(_DRIFT, stale=["v_010", "v_011"], heads={"SQ": "v_013", "SPL": "v_007"})

    dialog.set_report(_clean(continue_head=drift))

    line = i18n.t("diagContinueHead").format(named="v_010, v_011", at="v_007 (SPL), v_013 (SQ)")
    assert line in _texts(dialog)


def test_a_drift_in_a_shape_tcc_cannot_read_shows_the_checkers_words(monkeypatch):
    """A newer method may say it otherwise: its own sentence is still a true line."""
    _stub_self_checks(monkeypatch)
    _app()
    dialog = DiagnosticsDialog()

    dialog.set_report(_clean(continue_head={"warning": "the block is stale"}))

    assert "the block is stale" in _texts(dialog)


@pytest.mark.parametrize("lang", ["uk", "en"])
def test_a_block_ahead_of_the_ledger_is_not_said_to_be_behind_it(monkeypatch, lang):
    """#126's review, Minor 1: the block can name a version AHEAD of a HEAD that was rolled back
    (v_009 against v_001, as the real method gives it in `test_contract_check`). The line says
    where each stands and nothing about which moved."""
    _stub_self_checks(monkeypatch)
    _app()
    previous = i18n.current_language()
    i18n.set_language(lang)
    try:
        dialog = DiagnosticsDialog()
        dialog.set_report(_clean(continue_head=dict(_DRIFT, stale=["v_009"], heads={"FULL": "v_001"})))
        line = i18n.t("diagContinueHead").format(named="v_009", at="v_001 (FULL)")
        assert line in _texts(dialog)
        assert "already" not in line and "уже" not in line, line
    finally:
        i18n.set_language(previous)


@pytest.mark.parametrize("drift", [{"named": []}, {"stale": "v_010", "warning": "  "}])
def test_a_continue_head_with_nothing_to_say_shows_no_row(monkeypatch, drift):
    """#126's review, Minor 2: no fields TCC can read and no sentence of the checker's -- an empty
    row with an Ask that sends nothing. Shown as nothing at all."""
    from autosound_tcc.ui.tcc.diagnostics_panel import _AskRow

    _stub_self_checks(monkeypatch)
    _app()
    dialog = DiagnosticsDialog()

    dialog.set_report(_clean(continue_head=drift))

    assert dialog.findChildren(_AskRow) == []
    assert i18n.t("diagNoIssues") in _texts(dialog)


def test_no_opinion_on_the_continue_block_shows_nothing(monkeypatch):
    from autosound_tcc.ui.tcc.diagnostics_panel import _AskRow

    _stub_self_checks(monkeypatch)
    _app()
    dialog = DiagnosticsDialog()

    dialog.set_report(_clean(continue_head=None))

    assert dialog.findChildren(_AskRow) == []
    assert i18n.t("diagNoIssues") in _texts(dialog)


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

    assert dialog._tabs.count() == 5
    assert dialog._tabs.tabText(0) == i18n.t("diagTabProject")
    assert dialog._tabs.tabText(1) == i18n.t("diagTabUpdates")
    assert dialog._tabs.tabText(2) == i18n.t("diagTabInstall")
    assert dialog._tabs.tabText(3) == i18n.t("diagTabLog")
    assert dialog._tabs.tabText(4) == i18n.t("diagTabSessions")
    assert dialog._tabs.currentWidget() is dialog._project_tab, "it opens on the project"


def test_the_updates_have_a_tab_of_their_own():
    """VM-1 (tcc#98): on the Installation tab the updater and the tool rows needed scrolling while
    the report box kept half the height — the Arbiter, «давай зробимо оновлення на окремій
    вкладці». TCC's and the method's rows, the beta box and the tools are on «Updates»; the
    Installation tab keeps what is not about updating."""
    _app()
    dialog = DiagnosticsDialog()
    updates_tab, install_tab = dialog._updates_tab, dialog._install_tab

    for name in ("tcc", "skill"):
        label, button = dialog._update_rows[name]
        assert updates_tab.isAncestorOf(label) and updates_tab.isAncestorOf(button), name
        assert not install_tab.isAncestorOf(button), name
    for widget in (dialog._beta_box, dialog._tools_title):
        assert updates_tab.isAncestorOf(widget) and not install_tab.isAncestorOf(widget)
    tools = dialog._tools_layout.parentWidget()
    assert updates_tab.isAncestorOf(tools) and not install_tab.isAncestorOf(tools)
    for widget in (dialog._install_text, dialog._copy_btn):
        assert install_tab.isAncestorOf(widget) and not updates_tab.isAncestorOf(widget)


def test_the_report_box_takes_the_installation_tab_s_height():
    """The other half of VM-1: with the updater gone the report is the tab — the box is not left
    with half of it under rows that moved away."""
    _app()
    dialog = DiagnosticsDialog()
    dialog.show()
    dialog._tabs.setCurrentWidget(dialog._install_tab)
    QApplication.processEvents()

    assert dialog._install_text.height() > dialog._install_tab.height() * 0.6, (
        f"{dialog._install_text.height()} px of a {dialog._install_tab.height()} px tab")
    dialog.close()


def test_each_tab_asks_only_its_own_questions(monkeypatch):
    """The report is file reads and eight `--version` calls; the updates are GitHub and the
    skill's minute-long `status`. Opening one tab pays for that tab only (VM-1)."""
    from autosound_tcc.core import updates

    asked = []
    monkeypatch.setattr(updates, "check_all", lambda channel="stable": asked.append(channel) or (
        updates.Status("tcc", "0.1.3", "", False), updates.Status("skill", "3.0.8", "3.0.8", False)))
    monkeypatch.setattr(updates, "tools_status", lambda: asked.append("tools") or
                        updates.ToolsStatus(True, ()))
    _app()
    dialog = DiagnosticsDialog()

    dialog._tabs.setCurrentWidget(dialog._install_tab)
    assert dialog._install_read is True
    assert dialog._update_probe is None and dialog._tools_job is None, "no GitHub, no status"

    dialog._tabs.setCurrentWidget(dialog._updates_tab)
    assert dialog._update_probe is not None and dialog._tools_job is not None
    dialog._update_probe._thread.join(timeout=5)
    _finish_tools(dialog)
    assert sorted(asked) == ["stable", "tools"]


def test_the_report_is_read_only_when_the_tab_is_opened():
    """Eight `--version` subprocesses is not something to pay for opening a dialog about a contract
    check."""
    _app()
    dialog = DiagnosticsDialog()

    assert dialog._install_read is False

    started = time.monotonic()
    dialog._tabs.setCurrentWidget(dialog._install_tab)

    assert dialog._install_read is True
    # Everything that reads a file is already on screen; only the tool probes are on a thread.
    assert "[Autosound TCC]" in dialog._install_text.toPlainText()
    probe = dialog._install_worker
    assert probe is not None
    # 30 s, not 10. The probes are up to eight `--version` subprocesses, and on a CI runner
    # already running the rest of the suite they take longer than on a laptop running nothing:
    # this passed alone and failed inside the full suite on Windows (2026-09-07). A wait that is
    # long enough only on an idle machine is a clock, not a condition.
    for _ in range(600):
        if not probe.running:
            break
        QTest.qWait(50)
    dialog._poll_tools()
    text = dialog._install_text.toPlainText()
    # ...and if it still is not there, say WHICH of the two things happened. "not in text" cannot
    # tell a slow probe from a section that is never written, and those need different fixes.
    assert "[Command-line tools]" in text, (
        f"probe still running: {probe.running} after {time.monotonic() - started:.1f} s\n{text}\n"
        + (_thread_stacks() if probe.running else "")
    )


def _thread_stacks() -> str:
    """Where every other live thread is right now — the question a stuck probe leaves open.

    "probe still running" says THAT the probe is stuck, not WHERE. Each `--version` is capped at
    3 s, so a probe alive after 30 s is past that cap: in `communicate()` after a kill, which on
    Windows waits without a timeout for a grandchild holding the pipe, or starved while this thread
    waits, or somewhere nobody has thought of. Only the run that fails can say, so it prints the
    stacks (tcc#31).
    """
    frames = sys._current_frames()
    lines = []
    for thread in threading.enumerate():
        frame = frames.get(thread.ident)
        if thread is threading.current_thread() or frame is None:
            continue
        lines.append(f"--- thread {thread.name}")
        lines.extend(line.rstrip() for line in traceback.format_stack(frame))
    return "\n".join(lines)


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

    dialog._tabs.setCurrentWidget(dialog._log_tab)

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
    dialog._tabs.setCurrentWidget(dialog._log_tab)

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

    dialog._show_update(updates.Status("tcc", "0.1.1", "", False, "source_checkout",
                                       updatable=False))

    label, button = dialog._update_rows["tcc"]
    assert i18n.t("updWhy_source_checkout") in label.text(), "in the reader's language"
    assert not button.isEnabled()


def test_could_not_ask_is_not_the_same_as_up_to_date():
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()

    dialog._show_update(updates.Status("tcc", "0.1.1", "", False))

    assert dialog._update_rows["tcc"][0].text() == i18n.t("updUnknown")


def _finish_skill_update(dialog) -> None:
    """Run the skill button's steps to the end, here and now: each one is a thread the dialog's
    timer would otherwise poll."""
    for _ in range(5):
        job = dialog._skill_job
        if job is None:
            return
        job.join(timeout=10)
        dialog._poll_skill_job()
    raise AssertionError("the skill update never settled")


def _skill_offered(monkeypatch, changed=(), done=None, reloads=True):
    """A dialog whose skill row offers 3.0.7, a clone with `changed`, and `apply_skill` recorded.

    The method is not really read again (`vendor_loader.reload_loaded`, #126): that would re-read
    the real `rew_api` and undo the suite's dead REW port. `dialog.reloaded` counts the asks."""
    from autosound_tcc.core import updates, vendor_loader

    _app()
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("skill", "3.0.6", "3.0.7", True))
    monkeypatch.setattr(updates, "local_changes",
                        lambda tag="": updates.LocalChanges(True, tuple(changed)))
    asked = []
    done = done or updates.SkillUpdate(True, version="v3.0.7",
                                       signature="v3.0.7: signature good (ayukhno)",
                                       libs_ok=True, libs="numpy 2.0.2 → 2.1.0")
    monkeypatch.setattr(updates, "apply_skill",
                        lambda tag="", keep_local=False, send=False:
                        asked.append((tag, keep_local, send)) or done)
    dialog.reloaded = []
    monkeypatch.setattr(vendor_loader, "reload_loaded",
                        lambda: dialog.reloaded.append(1) or reloads)
    return dialog, asked


def _update_cleanly(dialog, monkeypatch):
    monkeypatch.setattr(dialog, "_ask_keep_local", lambda changed: pytest.fail("clean: no question"))
    dialog._update_skill()
    _finish_skill_update(dialog)
    return dialog._update_rows["skill"][0].text()


def test_an_update_that_lands_is_read_by_tcc_at_once(monkeypatch):
    """#126 (the re-review of 697378d): every reader in TCC kept the method it started with until
    a restart. The update that lands has it read again, once; the line says nothing more."""
    dialog, _asked = _skill_offered(monkeypatch)

    text = _update_cleanly(dialog, monkeypatch)

    assert dialog.reloaded == [1]
    assert i18n.t("updSkillRestart").split("{")[0] not in text


def test_an_update_tcc_cannot_read_while_running_says_to_restart(monkeypatch):
    dialog, _asked = _skill_offered(monkeypatch, reloads=False)

    text = _update_cleanly(dialog, monkeypatch)

    assert dialog.reloaded == [1]
    assert i18n.t("updSkillRestart").format(version="3.0.7") in text


def test_a_failed_update_reads_nothing_again(monkeypatch):
    from autosound_tcc.core import updates

    dialog, _asked = _skill_offered(monkeypatch, done=updates.SkillUpdate(False, "clone_failed", "x"))

    _update_cleanly(dialog, monkeypatch)

    assert dialog.reloaded == []


def test_updating_the_method_reports_the_version_it_landed_on(monkeypatch):
    from autosound_tcc.core import updates

    dialog, asked = _skill_offered(monkeypatch)
    monkeypatch.setattr(dialog, "_ask_keep_local", lambda changed: pytest.fail("clean: no question"))
    looked = []
    monkeypatch.setattr(updates, "local_changes",
                        lambda tag="": looked.append(tag) or updates.LocalChanges(True, ()))

    dialog._update_skill()
    assert dialog._update_rows["skill"][0].text() == i18n.t("updSkillLooking"), "while it looks"
    _finish_skill_update(dialog)

    assert looked == ["v3.0.7"], "the offered release's updater looks, not the clone's own"
    assert asked == [("v3.0.7", False, False)], "the release the row offered; nothing to keep"
    text = dialog._update_rows["skill"][0].text()
    assert "3.0.7" in text
    assert "v3.0.7: signature good (ayukhno)" in text, "the skill's signature line, as it said it"
    assert "numpy 2.0.2 → 2.1.0" in text, "and the libraries that moved with it"


def test_what_the_update_rows_learn_is_told_to_the_window(monkeypatch):
    """VM-3: the method updated and its row said «up to date», and the main window's title kept
    «update available» until TCC restarted. Every answer a row shows goes out — and the receipt
    of an update says the method is now current. A Re-check landing on a row mid-update is not
    shown, so it is not told either."""
    from autosound_tcc.core import updates

    dialog, _asked = _skill_offered(monkeypatch)
    monkeypatch.setattr(dialog, "_ask_keep_local", lambda changed: pytest.fail("clean: no question"))
    heard = []
    dialog.updateLearned.connect(heard.append)

    dialog._show_update(updates.Status("tcc", "0.1.45", "0.1.46", True))
    dialog._update_skill()
    dialog._show_update(updates.Status("skill", "3.0.6", "3.0.7", True))
    _finish_skill_update(dialog)

    assert [(s.name, s.latest, s.newer) for s in heard] == [
        ("tcc", "0.1.46", True), ("skill", "3.0.7", False)]


def test_a_failed_update_says_why_and_leaves_the_button(monkeypatch):
    from autosound_tcc.core import updates

    said = "v3.0.7: the signature does not check out -- no principal matched; nothing was changed"
    dialog, _asked = _skill_offered(monkeypatch, done=updates.SkillUpdate(False, "refused", said))

    dialog._update_skill()
    _finish_skill_update(dialog)

    label, button = dialog._update_rows["skill"]
    assert said in label.text(), "the skill's own sentence survives; the framing is translated"
    assert i18n.t("updWhy_refused") in label.text()
    assert button.isEnabled(), "a failure the person can retry must leave them the button"


@pytest.mark.parametrize("why, other", [("git_too_old", "openssh_too_old"),
                                        ("openssh_too_old", "git_too_old")])
def test_a_git_too_old_to_check_is_said_as_such_on_the_row(monkeypatch, why, other):
    """And an OpenSSH too old to check is told to update OpenSSH, not git (tcc#123)."""
    from autosound_tcc.core import updates

    dialog, _asked = _skill_offered(monkeypatch, done=updates.SkillUpdate(
        False, why, "git version 2.30.1: unknown option -- Y"))

    dialog._update_skill()
    _finish_skill_update(dialog)

    text = dialog._update_rows["skill"][0].text()
    assert i18n.t(f"updWhy_{why}") in text and "git version 2.30.1" in text
    assert i18n.t(f"updWhy_{why}") != f"updWhy_{why}", "a sentence, not the key"
    assert i18n.t(f"updWhy_{other}") not in text
    assert i18n.t("updWhy_bad_signature") not in text


def test_a_clone_with_local_changes_names_them_and_asks_about_sending(monkeypatch):
    """tcc#91: in place of the grey button, the changed files named and one action. The question
    names the files, because the send takes them off the machine; the patch is kept either way."""
    changed = ("skills/autosound-tuning/rew_tool/contract.py", "skills/autosound-tuning/new.py")
    dialog, asked = _skill_offered(monkeypatch, changed=changed)
    shown = []
    monkeypatch.setattr(dialog, "_ask_keep_local", lambda files: shown.append(files) or False)

    dialog._update_skill()
    _finish_skill_update(dialog)

    assert shown == [changed]
    assert asked == [("v3.0.7", True, False)], "declined: kept and updated, not sent"

    box = dialog._keep_local_box(changed)[0]
    for name in changed:
        assert name in box.text()
    labels = [button.text() for button in box.buttons()]
    assert i18n.t("updKeepSend") in labels and i18n.t("updKeepOnly") in labels
    assert box.defaultButton().text() == i18n.t("updKeepOnly"), "Enter never sends"


def test_a_yes_to_sending_shows_where_it_went(monkeypatch):
    from autosound_tcc.core import updates

    url = "https://github.com/ayukhno/autosound-tuning-skill/issues/123"
    dialog, asked = _skill_offered(monkeypatch, changed=("a.py",), done=updates.SkillUpdate(
        True, version="v3.0.7", patch="/h/.claude/skills/autosound-local-changes/x.patch",
        sent={"sent": True, "url": url}, libs_ok=True))
    monkeypatch.setattr(dialog, "_ask_keep_local", lambda files: True)

    dialog._update_skill()
    _finish_skill_update(dialog)

    assert asked == [("v3.0.7", True, True)]
    text = dialog._update_rows["skill"][0].text()
    assert url in text and "x.patch" in text


def test_a_send_that_did_not_go_says_why_and_still_updated(monkeypatch):
    from autosound_tcc.core import updates

    why = "no GitHub here (`gh` missing or not signed in); the patch is kept"
    dialog, _asked = _skill_offered(monkeypatch, changed=("a.py",), done=updates.SkillUpdate(
        True, version="v3.0.7", patch="/p/x.patch", sent={"sent": False, "why": why}))
    monkeypatch.setattr(dialog, "_ask_keep_local", lambda files: True)

    dialog._update_skill()
    _finish_skill_update(dialog)

    text = dialog._update_rows["skill"][0].text()
    assert why in text and "3.0.7" in text


def test_cancelling_the_question_changes_nothing(monkeypatch):
    dialog, asked = _skill_offered(monkeypatch, changed=("a.py",))
    before = dialog._update_rows["skill"][0].text()
    monkeypatch.setattr(dialog, "_ask_keep_local", lambda files: None)

    dialog._update_skill()
    _finish_skill_update(dialog)

    label, button = dialog._update_rows["skill"]
    assert asked == [], "no keep-local, no reset, no update"
    assert label.text() == before and button.isEnabled()


def test_a_re_check_during_the_skill_update_leaves_its_row_alone(monkeypatch):
    """A minute of `status`, minutes of pip: a Re-check pressed meanwhile must not write "up to
    date" over "updating…", nor hand back a button for a second run."""
    import threading

    from autosound_tcc.core import updates

    dialog, _asked = _skill_offered(monkeypatch)
    release = threading.Event()
    monkeypatch.setattr(updates, "local_changes",
                        lambda tag="": release.wait(5) and updates.LocalChanges(True, ()))
    monkeypatch.setattr(updates, "check_all", lambda channel="stable": (
        updates.Status("tcc", "0.1.3", "0.1.3", False),
        updates.Status("skill", "3.0.7", "3.0.7", False)))

    dialog._update_skill()
    label, button = dialog._update_rows["skill"]
    dialog._start_update_check()
    dialog._show_update(updates.Status("skill", "3.0.7", "3.0.7", False))

    assert label.text() == i18n.t("updSkillLooking") and not button.isEnabled()
    release.set()
    _finish_skill_update(dialog)
    dialog._update_probe._thread.join(timeout=5)


def _finish_tcc_update(dialog) -> None:
    """Run the TCC button's check to the end, here and now: a thread the dialog's timer would
    otherwise poll."""
    job = dialog._tcc_job
    assert job is not None, "the check runs off the GUI thread"
    job.join(timeout=10)
    dialog._poll_tcc_job()
    assert dialog._tcc_job is None, "the TCC update never settled"


def _tcc_at(monkeypatch, version: str, revision: str = "") -> None:
    """The TCC the press runs from — pinned, since the press refuses a tag older than it (review
    of finding 144, I1) and this tree's own version moves with every release."""
    from autosound_tcc.core import install_report

    monkeypatch.setattr(install_report, "app_version", lambda: version)
    monkeypatch.setattr(install_report, "requested_revision", lambda: revision)


def _tag_checked(monkeypatch, answer=(True, "v0.9.9: signature good (ayukhno)", "", "c" * 40)):
    """TCC's own tag check (tcc#102) answered without the network; the tags it was asked about."""
    from autosound_tcc.core import updates

    asked = []
    monkeypatch.setattr(updates, "check_tcc_tag", lambda tag: asked.append(tag) or answer)
    return asked


def test_updating_tcc_is_handed_to_a_terminal(monkeypatch, tmp_path):
    """TCC cannot replace its own running files -- on Windows not at all -- so it does not try.
    The window runs a script file TCC wrote, so what it shows is the person's lines (hub #221)."""
    import tempfile

    from autosound_tcc.core import terminal_launcher, updates

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))  # the script lands here, not in /tmp
    _app()
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("tcc", "0.1.1", "0.9.9", True))
    seen = []
    monkeypatch.setattr(terminal_launcher, "run_script", lambda path: seen.append(path))
    _tcc_at(monkeypatch, "0.1.1")  # the row's own number, not this tree's (review I2)
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda channel="stable": "v0.9.9")
    asked = _tag_checked(monkeypatch)

    dialog._update_tcc()
    label, button = dialog._update_rows["tcc"]
    assert label.text() == i18n.t("updTccChecking") and not button.isEnabled(), "while it checks"
    _finish_tcc_update(dialog)

    assert asked == ["v0.9.9"], "the tag the script installs is the tag that was checked"
    assert len(seen) == 1
    script = seen[0].read_text(encoding="utf-8")
    # Pinned to the release the row offered, not to whatever `main` holds by then (F-024).
    assert "autosound-tcc[gui,claude] @ git+" in script
    assert "@v0.9.9" in script
    assert "--python 3.12" in script
    assert str(os.getpid()) in script, "the window waits for THIS process before it replaces it"
    assert i18n.t("updTermWait") in script, "in the reader's language"
    assert "c" * 40 in script and i18n.t("updTermMoved") in script, (
        "held to the verified commit right before uv, the refusal in the reader's language")
    assert seen[0].parent.parent == tmp_path
    text = dialog._update_rows["tcc"][0].text()
    assert text.startswith(i18n.t("updTccHanded"))
    assert i18n.t("updSkillSigned").format(line="v0.9.9: signature good (ayukhno)") in text, (
        "the check's line is on the row, not only in the log (HUB-032)")


def test_a_tcc_tag_that_does_not_verify_opens_no_terminal_and_says_why(monkeypatch, tmp_path):
    """tcc#102: the update is refused where it would have been handed over — the row — and no
    window opens, so uv never runs."""
    import tempfile

    from autosound_tcc.core import terminal_launcher, updates

    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    _app()
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("tcc", "0.1.44", "0.1.46", True))
    monkeypatch.setattr(terminal_launcher, "run_script",
                        lambda path: pytest.fail("no terminal for a tag that does not verify"))
    _tcc_at(monkeypatch, "0.1.44")  # not this tree's own number: the press refuses a move back
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda channel="stable": "v0.1.46")
    _tag_checked(monkeypatch, (False, "v0.1.46: No principal matched.", "bad_signature", ""))

    dialog._update_tcc()
    _finish_tcc_update(dialog)

    label, button = dialog._update_rows["tcc"]
    assert i18n.t("updWhy_bad_signature") in label.text()
    assert "No principal matched" in label.text(), "git's own words stay"
    assert button.isEnabled(), "the person can try again"
    assert list(temp.iterdir()) == [], "no script was written"


def test_a_re_check_landing_while_tcc_s_tag_is_checked_does_not_overwrite_the_row(monkeypatch):
    import threading

    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("tcc", "0.1.44", "0.1.45", True))
    release = threading.Event()
    monkeypatch.setattr(updates, "prepare_tcc_update",
                        lambda channel="stable", **_kw: release.wait(5) and updates.TccUpdate(
                            None, "bad_signature", "v0.1.45: x"))

    dialog._update_tcc()
    dialog._show_update(updates.Status("tcc", "0.1.44", "0.1.45", True))

    label, button = dialog._update_rows["tcc"]
    assert label.text() == i18n.t("updTccChecking") and not button.isEnabled()
    release.set()
    _finish_tcc_update(dialog)


def test_re_check_asks_about_updates_again(monkeypatch):
    """The button says Re-check, and the update rows are what a person presses it to see move —
    after installing one, or after the network came back."""
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()
    dialog._tabs.setCurrentWidget(dialog._updates_tab)
    dialog._show_update(updates.Status("skill", "3.0.7", "3.0.8", True))
    asked = []
    monkeypatch.setattr(updates, "check_all", lambda channel="stable": asked.append(1) or (
        updates.Status("tcc", "0.1.3", "", False), updates.Status("skill", "3.0.8", "3.0.8", False)))

    dialog._on_refresh()

    label, button = dialog._update_rows["skill"]
    assert label.text() == i18n.t("updChecking"), "the stale answer must not stay on screen"
    assert not button.isEnabled(), "nor a button we cannot honour while the question is open"
    dialog._update_probe._thread.join(timeout=5)
    assert asked, "the probe actually ran"


def test_re_check_from_another_tab_does_not_pay_for_the_probes():
    """Eight subprocesses belong to the moment the tab is opened, not to a button on another one."""
    _app()
    dialog = DiagnosticsDialog()
    dialog._tabs.setCurrentWidget(dialog._project_tab)
    dialog._install_read = True
    dialog._updates_read = True

    dialog._on_refresh()

    assert dialog._install_read is False, "but it is marked stale, so opening it re-reads"
    assert dialog._updates_read is False, "the Updates tab too (VM-1)"
    assert dialog._update_probe is None and dialog._tools_job is None


def test_an_update_does_not_read_a_report_nobody_has_opened(monkeypatch):
    """The report names the method's version, so an update makes it stale. One never read is read
    when the Installation tab is opened, not behind the Updates tab (VM-1); one read before is read
    again at once — `test_a_report_after_an_update_carries_the_tools_whichever_tab_is_shown`."""
    dialog, _asked = _skill_offered(monkeypatch)
    monkeypatch.setattr(dialog, "_ask_keep_local", lambda changed: pytest.fail("clean: no question"))
    dialog._tabs.setCurrentWidget(dialog._updates_tab)

    dialog._update_skill()
    _finish_skill_update(dialog)

    assert dialog._install_read is False and dialog._install_worker is None
    dialog._tabs.setCurrentWidget(dialog._install_tab)
    assert dialog._install_read is True and dialog._install_worker is not None


def test_reporting_a_problem_carries_the_installation_block_into_the_form():
    """The half of a report nobody can assemble by hand is the half that makes it answerable, so
    the GitHub route puts it in the template's own field rather than asking for it."""
    from autosound_tcc.ui.tcc.diagnostics_panel import issue_url

    url = issue_url("", "[Autosound TCC]\n  version  0.1.4\n")

    assert url.startswith("https://github.com/ayukhno/autosound-tcc/issues/new?")
    assert "template=beta-report.yml" in url
    assert "0.1.4" in url, "the installation block travels with the report"
    assert "what=" not in url, "no words written leaves the template's own prompt in place"


def test_a_report_from_a_tab_that_was_never_opened_still_carries_the_versions():
    """The button is in the bottom row now, so it can be pressed from any tab — including before
    the Installation tab has ever been read, when its box still says "reading…"."""
    _app()
    dialog = DiagnosticsDialog()
    assert dialog._install_read is False

    text = dialog._report_text()
    assert "Autosound TCC" in text
    assert "[Command-line tools]" in text and "not asked yet" in text, (
        "the tools are said to be missing, not silently left out (review of VM fix A)")


def _tools_section(**versions):
    from autosound_tcc.core import install_report

    return install_report.Section(
        "Command-line tools", [install_report.Item(name, here) for name, here in versions.items()])


def _finish_report(dialog) -> None:
    """Run the report's `--version` probes to the end, here and now: a thread its timer polls."""
    probe = dialog._install_worker
    assert probe is not None, "the report is being read"
    probe._thread.join(timeout=10)
    dialog._poll_tools()


def test_a_report_after_an_update_carries_the_tools_whichever_tab_is_shown(monkeypatch):
    """Review of VM fix A, Minor 1: omp updated from the Updates tab, then «Report a problem» — and
    the block went without the tools section, because the Installation tab was not on screen. A
    report read before is read again at once; until its tools answer, the block says they have not
    — never the versions from before the update, never nothing."""
    import threading

    from autosound_tcc.core import install_report, updates

    release = threading.Event()
    answers = iter([lambda: _tools_section(omp="17.3.8"),
                    lambda: release.wait(5) and _tools_section(omp="18.2.4")])
    monkeypatch.setattr(install_report, "tools", lambda: next(answers)())
    dialog = _tools_shown(monkeypatch, _tool("omp", "17.3.8", "18.2.4"))
    dialog._tabs.setCurrentWidget(dialog._install_tab)
    _finish_report(dialog)
    assert "omp  17.3.8" in dialog._report_text()
    dialog._tabs.setCurrentWidget(dialog._updates_tab)
    monkeypatch.setattr(updates, "update_tools", lambda names: updates.ToolsUpdate(
        (updates.ToolUpdate("omp", True, "17.3.8", "18.2.4"),)))

    dialog._tool_rows["omp"][1].click()
    _finish_tools(dialog)

    assert dialog._tabs.currentWidget() is dialog._updates_tab
    text = dialog._report_text()
    assert "[Command-line tools]" in text and "17.3.8" not in text, text
    assert "being asked" in text or "not asked yet" in text, text
    release.set()
    _finish_report(dialog)
    text = dialog._report_text()
    assert "[Command-line tools]" in text and "omp  18.2.4" in text, text


def test_a_report_during_a_re_check_carries_the_tools_last_delivered(monkeypatch):
    """Re-check on the Installation tab puts «reading…» back in the box while the tools are asked
    again; nothing was installed, so the block sends the tools as they last answered."""
    import threading

    from autosound_tcc.core import install_report

    release = threading.Event()
    answers = iter([lambda: _tools_section(gh="2.102.0"),
                    lambda: release.wait(5) and _tools_section(gh="2.102.0")])
    monkeypatch.setattr(install_report, "tools", lambda: next(answers)())
    _app()
    dialog = DiagnosticsDialog()
    dialog._tabs.setCurrentWidget(dialog._install_tab)
    _finish_report(dialog)

    dialog._on_refresh()

    assert dialog._install_worker.running
    assert "gh  2.102.0" in dialog._report_text()
    release.set()
    _finish_report(dialog)


def test_a_probe_running_when_an_update_lands_is_let_go(monkeypatch):
    """tcc#130 (the re-review of VM fix A, Minor A): a tools probe already running when omp's update
    landed went on being read, and when it answered the report sent omp from before the update with
    nothing to say so. It is let go, as `_on_beta_toggled` lets the update probe go, and a new one
    asks the tools as they are now."""
    from autosound_tcc.core import install_report, updates

    started, release = threading.Event(), threading.Event()

    def before_the_update():
        started.set()
        release.wait(5)
        return _tools_section(omp="17.3.8")

    answers = iter([before_the_update, lambda: _tools_section(omp="18.2.4")])
    monkeypatch.setattr(install_report, "tools", lambda: next(answers)())
    dialog = _tools_shown(monkeypatch, _tool("omp", "17.3.8", "18.2.4"))
    monkeypatch.setattr(updates, "update_tools", lambda names: updates.ToolsUpdate(
        (updates.ToolUpdate("omp", True, "17.3.8", "18.2.4"),)))
    dialog._tabs.setCurrentWidget(dialog._install_tab)
    running = dialog._install_worker
    assert started.wait(5) and running.running

    dialog._tool_rows["omp"][1].click()
    _finish_tools(dialog)
    release.set()
    running._thread.join(timeout=10)
    _finish_report(dialog)

    text = dialog._report_text()
    assert "omp  18.2.4" in text and "17.3.8" not in text, text
    assert dialog._install_worker is not running


def _probe_given_up(monkeypatch, tools):
    """A dialog whose Installation tab was read, with a probe slower than the poll: the timer has
    taken its last look and stopped, and the probe (`install_report.tools` is `tools`) is still
    asking."""
    from autosound_tcc.core import install_report
    from autosound_tcc.ui.tcc import diagnostics_panel

    monkeypatch.setattr(install_report, "tools", tools)
    _app()
    dialog = DiagnosticsDialog()
    dialog._tabs.setCurrentWidget(dialog._install_tab)
    dialog._install_tries = diagnostics_panel._TOOLS_TRIES - 1
    dialog._poll_tools()
    assert not dialog._install_timer.isActive() and dialog._install_worker.running
    return dialog


def _answers_on(release):
    """The tools, once `release` is set: gh 2.102.0."""
    return lambda: release.wait(5) and _tools_section(gh="2.102.0")


def test_a_probe_slower_than_the_poll_is_sent_once_it_has_answered(monkeypatch):
    """tcc#130 (the re-review of VM fix A, Minor B): a probe slower than the 15-s poll — a slow
    Windows VM — answered after the timer had stopped reading it, and nobody read it: the report
    said «not asked yet» for tools that were asked. The finished probe's section is sent."""
    release = threading.Event()
    dialog = _probe_given_up(monkeypatch, _answers_on(release))
    release.set()
    dialog._install_worker._thread.join(timeout=10)

    text = dialog._report_text()

    assert "gh  2.102.0" in text and "not asked yet" not in text, text


def test_copy_alone_takes_a_probe_that_answered_after_the_poll(monkeypatch):
    """tcc#130, review Minor 2: Copy is the block's other route, and it takes the late answer by
    itself — not only after a report has drawn it into the box."""
    from PySide6.QtGui import QGuiApplication

    release = threading.Event()
    dialog = _probe_given_up(monkeypatch, _answers_on(release))
    release.set()
    dialog._install_worker._thread.join(timeout=10)

    dialog._copy_install()

    assert "gh  2.102.0" in QGuiApplication.clipboard().text()


def test_a_probe_the_poll_gave_up_on_is_said_not_to_have_answered_in_time(monkeypatch):
    """tcc#130: once the poll's 15 s are up and the tools have not answered, the report says so —
    not «not asked yet», and not «still being asked» for a probe nothing reads any more (one stuck
    in a `communicate()`, tcc#31). The box and Copy say the same, not a «reading…» nothing will
    replace with no tools section at all (review Important 1)."""
    from PySide6.QtGui import QGuiApplication

    release = threading.Event()
    dialog = _probe_given_up(monkeypatch, _answers_on(release))

    text = dialog._report_text()
    box = dialog._install_text.toPlainText()
    dialog._copy_install()
    copied = QGuiApplication.clipboard().text()

    release.set()
    dialog._install_worker._thread.join(timeout=10)
    assert "[Command-line tools]" in text and "did not answer in time" in text, text
    assert "not asked yet" not in text and "being asked" not in text, text
    for shown in (box, copied):
        assert "[Command-line tools]" in shown and "did not answer in time" in shown, shown
        assert i18n.t("diagInstallReading") not in shown, shown


def test_re_check_asks_again_past_a_probe_the_poll_gave_up_on(monkeypatch):
    """tcc#130, review Important 2: a probe that never finishes — stuck in a `communicate()` on
    Windows, tcc#31 — kept Re-check from asking the tools again until a restart, and the report on
    «did not answer in time». Re-check lets it go and asks again."""
    started, stuck, second = threading.Event(), threading.Event(), threading.Event()

    def never_answers():
        started.set()
        stuck.wait(30)
        return _tools_section(gh="2.101.0")

    answers = iter([never_answers, _answers_on(second)])
    dialog = _probe_given_up(monkeypatch, lambda: next(answers)())
    assert started.wait(5)
    given_up = dialog._install_worker
    try:
        dialog._on_refresh()

        assert dialog._install_worker is not given_up
        assert "still being asked" in dialog._report_text()
        second.set()
        _finish_report(dialog)
        text = dialog._report_text()
        assert "gh  2.102.0" in text and "did not answer in time" not in text, text
    finally:
        stuck.set()
        given_up._thread.join(timeout=10)


def test_a_probe_ending_while_the_report_reads_it_is_sent(monkeypatch):
    """tcc#130, review Minor 1: a probe read as running by the late take and as ended a moment later
    went to neither — the report said «did not answer in time» for a section that was there."""
    from autosound_tcc.core import install_report

    class _EndsBetweenReads:
        """Running at the first look, ended with its section at every look after."""

        def __init__(self):
            self.section = _tools_section(gh="2.102.0")
            self._reads = iter([True])

        @property
        def running(self):
            return next(self._reads, False)

    monkeypatch.setattr(install_report, "tools", lambda: _tools_section(gh="2.101.0"))
    _app()
    dialog = DiagnosticsDialog()
    dialog._tabs.setCurrentWidget(dialog._install_tab)
    dialog._install_worker._thread.join(timeout=30)
    dialog._install_worker = _EndsBetweenReads()
    dialog._report_tools = None

    text = dialog._report_text()

    assert "gh  2.102.0" in text and "did not answer in time" not in text, text


def test_an_update_behind_another_tab_stops_the_poll_of_the_probe_it_lets_go(monkeypatch):
    """tcc#130, review Minor 3: Re-check from the Updates tab while the tools are asked, then omp's
    update lands. The probe is let go with no re-read — and the timer that read it stops, rather
    than ticking at 4 Hz over nothing for as long as the window is open."""
    from autosound_tcc.core import install_report, updates

    release = threading.Event()
    monkeypatch.setattr(install_report, "tools", _answers_on(release))
    dialog = _tools_shown(monkeypatch, _tool("omp", "17.3.8", "18.2.4"))
    monkeypatch.setattr(updates, "update_tools", lambda names: updates.ToolsUpdate(
        (updates.ToolUpdate("omp", True, "17.3.8", "18.2.4"),)))
    dialog._tabs.setCurrentWidget(dialog._install_tab)
    running = dialog._install_worker
    dialog._tabs.setCurrentWidget(dialog._updates_tab)
    dialog._on_refresh()
    _finish_tools(dialog)
    assert dialog._install_timer.isActive() and running.running

    dialog._tool_rows["omp"][1].click()
    _finish_tools(dialog)

    release.set()
    running._thread.join(timeout=10)
    assert dialog._install_worker is None
    assert not dialog._install_timer.isActive()


def test_the_update_row_carries_the_version_and_not_the_commit():
    """F-036, narrowing HUB-001. The commit was appended to both numbers here; the brackets read
    as noise on the row exactly as they did in the title bar, and the identifier now lives in the
    installation report — whole, and in the artefact people paste into a chat.

    The sha is still what `updates.py` COMPARES on. What changed is only what is printed."""
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()
    here, there = "a" * 40, "b" * 40

    dialog._show_update(updates.Status("skill", "3.0.6", "3.0.7", True,
                                       installed_sha=here, latest_sha=there))

    text = dialog._update_rows["skill"][0].text()
    assert "3.0.6" in text and "3.0.7" in text
    assert here[:12] not in text and there[:12] not in text, "the commit does not drift back in"


def test_a_release_the_manifest_was_not_bumped_on_reads_as_a_newer_build():
    """The case HUB-001 is about, on screen: the two version strings are equal and the commits are
    not. It used to render as "up to date"; it lands in the newer-build sentence instead.

    This is the row F-036 costs something on, and the cost is named rather than discovered: with
    the sha gone the sentence says THAT there is a newer build and not which one. The button still
    offers the update, and the report still names both commits — the row stopped being the place
    that answers "which build", which it only ever answered in twelve characters anyway.
    """
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()

    dialog._show_update(updates.Status("skill", "3.0.36", "3.0.36", True,
                                       installed_sha="a" * 40, latest_sha="b" * 40))

    label, button = dialog._update_rows["skill"]
    assert label.text() == i18n.t("updNewerBuild").format(
        what=i18n.t("updSkillName"), here="3.0.36")
    assert button.isEnabled()


def test_a_newer_build_of_the_same_version_is_said_in_words(monkeypatch):
    """TCC installs from a branch, so "newer" usually means the same number twice. Printing it as
    "0.1.7 — a newer one is out: 0.1.7" would be nonsense, and a hash is not for reading."""
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()

    dialog._show_update(updates.Status("tcc", "0.1.7", "0.1.7", True))

    label, button = dialog._update_rows["tcc"]
    assert label.text() == i18n.t("updNewerBuild").format(what=i18n.t("updTccName"), here="0.1.7")
    assert button.isEnabled()


def test_up_to_date_beats_the_reason_the_button_is_off():
    """A submodule cannot be updated in place — but when it is already on the newest release, why
    the button is off is not the question the reader has."""
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()

    dialog._show_update(updates.Status("skill", "3.0.8", "3.0.8", False,
                                       "submodule", "/Users/somebody/dev/autosound-tcc",
                                       updatable=False))

    label, button = dialog._update_rows["skill"]
    assert label.text() == i18n.t("updCurrent").format(what=i18n.t("updSkillName"), here="3.0.8")
    assert not button.isEnabled(), "still not something this app may move"


def test_the_reason_is_shown_when_there_IS_something_it_cannot_install():
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()

    dialog._show_update(updates.Status("skill", "3.0.7", "3.0.8", False,
                                       "submodule", "/Users/somebody/dev/autosound-tcc",
                                       updatable=False))

    assert i18n.t("updWhy_submodule") in dialog._update_rows["skill"][0].text()


@pytest.mark.parametrize("name", ["skill", "tcc"])
def test_a_candidate_ahead_of_the_newest_release_says_so_and_offers_nothing(name):
    """Finding 144: «The method 3.1.0 — a newer one is out: 3.0.66» with «Update the method» live,
    on the method's candidate. Ahead of the newest release reads as that, in the reader's
    language, over a button that stays off — on TCC's row as on the method's."""
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()
    before = i18n.current_language()
    try:
        for lang in ("en", "uk"):
            i18n.set_language(lang)
            dialog._show_update(updates.Status(name, "3.1.0", "3.0.66", False, "ahead"))

            label, button = dialog._update_rows[name]
            title = i18n.t("updSkillName" if name == "skill" else "updTccName")
            assert label.text() == i18n.t("updAhead").format(what=title, here="3.1.0",
                                                             there="3.0.66")
            assert "3.1.0" in label.text() and "3.0.66" in label.text()
            assert not button.isEnabled()
    finally:
        i18n.set_language(before)
    assert dialog._skill_latest == "", "no release to press for"


def test_a_tcc_candidate_s_row_reads_the_version_its_tag_names(monkeypatch):
    """Finding 150 (tcc#146), the row itself: the candidate beta-v1.1.0-rc1, its metadata at
    0.1.46, against the newest release 0.1.46 — read through `check_tcc`, no network."""
    from autosound_tcc.core import install_report, updates

    _app()
    _tcc_at(monkeypatch, "0.1.46", "beta-v1.1.0-rc1")
    monkeypatch.setattr(install_report, "install_source", lambda: ("u", "1" * 40))
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda channel="stable": "v0.1.46")
    dialog = DiagnosticsDialog()
    before = i18n.current_language()
    try:
        i18n.set_language("en")
        dialog._show_update(updates.check_tcc())
    finally:
        i18n.set_language(before)

    label, button = dialog._update_rows["tcc"]
    assert label.text() == ("TCC 1.1.0 (beta-v1.1.0-rc1) — newer than the latest release 0.1.46 "
                            "(a candidate)")
    assert not button.isEnabled()


def test_a_press_refused_as_a_move_back_says_why_in_words():
    """`apply_skill`'s own refusal of an older release (finding 144) reaches the row through
    `_reason`, as a sentence and not the bare key."""
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()

    dialog._after_skill_update(updates.SkillUpdate(False, "ahead", "3.1.0 → v3.0.66"))

    label, button = dialog._update_rows["skill"]
    assert i18n.t("updWhy_ahead") != "updWhy_ahead", "a sentence of its own"
    assert label.text() == i18n.t("updFailed").format(
        why=f"{i18n.t('updWhy_ahead')}: 3.1.0 → v3.0.66")


def test_a_press_refused_as_a_move_back_leaves_the_button_off():
    """Review of finding 144, M2: after «ahead» the button came back on, and pressing it again
    fetched, ran the old tag's status and was refused again. Another refusal leaves it on — the
    person can try again; this one would only say the same."""
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()
    label, button = dialog._update_rows["skill"]

    button.setEnabled(True)
    dialog._after_skill_update(updates.SkillUpdate(False, "ahead", "3.1.0 → v3.0.66"))
    assert not button.isEnabled()

    dialog._after_skill_update(updates.SkillUpdate(False, "fetch_failed", "no network"))
    assert button.isEnabled(), "a refusal that can change on its own is pressed again"


def test_a_press_refused_for_a_newer_contract_says_update_tcc_first(monkeypatch):
    """#170: the press's first step refuses a method on a contract newer than this TCC drives
    (`updates.local_changes`), and the row says so in the reader's language, the tag and the
    numbers beside it. Nothing is asked and nothing is kept: the keep-local question never comes,
    `apply_skill` is never called. The second step's refusal reads the same."""
    from autosound_tcc.core import updates

    detail = "v3.0.7: CONTRACT_VERSION 2 > 0"
    dialog, asked = _skill_offered(monkeypatch)
    monkeypatch.setattr(updates, "local_changes", lambda tag="": updates.LocalChanges(
        False, reason="newer_contract", detail=detail))
    monkeypatch.setattr(dialog, "_ask_keep_local", lambda changed: pytest.fail("nothing to keep"))
    label, _button = dialog._update_rows["skill"]
    seen = {}
    before = i18n.current_language()
    try:
        for lang in ("en", "uk"):
            i18n.set_language(lang)
            seen[lang] = i18n.t("updWhy_newer_contract")
            said = i18n.t("updFailed").format(why=f"{seen[lang]}: {detail}")

            dialog._update_skill()
            _finish_skill_update(dialog)
            assert label.text() == said

            dialog._after_skill_update(updates.SkillUpdate(False, "newer_contract", detail))
            assert label.text() == said
    finally:
        i18n.set_language(before)
    assert seen["en"] == "this method is newer than this TCC — update TCC first"
    assert seen["uk"] not in (seen["en"], "updWhy_newer_contract"), "written in Ukrainian"
    assert asked == [], "apply_skill was never asked"


@pytest.mark.parametrize("why", ["ahead", "newer_contract"])
def test_a_refusal_pressing_again_cannot_change_keeps_the_button_off_at_both_steps(monkeypatch,
                                                                                   why):
    """R-as: after «newer than this TCC» the button came back on, and a second press fetched the
    release again — up to five minutes over a phone — to be told the same, the very thing M2 ended
    for «ahead». Both steps of the press read one list of such refusals. A read that failed can go
    on another try, and leaves the button for it."""
    from autosound_tcc.core import updates

    dialog, asked = _skill_offered(monkeypatch)
    monkeypatch.setattr(updates, "local_changes", lambda tag="": updates.LocalChanges(
        False, reason=why, detail="v3.0.7"))
    label, button = dialog._update_rows["skill"]

    dialog._update_skill()
    _finish_skill_update(dialog)
    assert not button.isEnabled(), "off after the first step's refusal"

    button.setEnabled(True)
    dialog._after_skill_update(updates.SkillUpdate(False, why, "v3.0.7"))
    assert not button.isEnabled(), "and after the second step's"

    dialog._after_local_changes(updates.LocalChanges(False, reason="read_failed", detail="v3.0.7"))
    assert button.isEnabled(), "a read that failed is tried again"
    assert i18n.t("updWhy_read_failed") != "updWhy_read_failed", "a sentence of its own"
    assert label.text() == i18n.t("updFailed").format(why=f"{i18n.t('updWhy_read_failed')}: v3.0.7")
    assert asked == []


def test_a_stale_update_tcc_press_says_ahead_and_installs_nothing(monkeypatch, tmp_path):
    """Review of finding 144, I1, at the row: a row gone stale was pressed — a candidate,
    `beta-v0.2.0-rc1` with 0.1.38 in its metadata, and the newest stable `v0.1.45`. No tag is
    checked, no terminal opens, the row says why, and the button stays off."""
    import tempfile

    from autosound_tcc.core import terminal_launcher, updates

    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    _app()
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("tcc", "0.1.38", "0.1.45", True))
    monkeypatch.setattr(terminal_launcher, "run_script",
                        lambda path: pytest.fail("no terminal for an older release"))
    monkeypatch.setattr(updates, "check_tcc_tag",
                        lambda tag: pytest.fail("nothing fetched for an older release"))
    _tcc_at(monkeypatch, "0.1.38", "beta-v0.2.0-rc1")
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda channel="stable": "v0.1.45")

    dialog._update_tcc()
    _finish_tcc_update(dialog)

    label, button = dialog._update_rows["tcc"]
    assert label.text() == i18n.t("updFailed").format(
        why=f"{i18n.t('updWhy_ahead')}: 0.2.0 (beta-v0.2.0-rc1) → v0.1.45")
    assert not button.isEnabled()
    assert list(temp.iterdir()) == []


def test_the_rew_line_reads_the_v3017_shape(monkeypatch):
    """Skill v3.0.17 re-cut the REW cross-check: the count is now the verdict of the OPEN CAPTURE
    ROUND rather than of the ledger's HEAD (a baseline used to report `0/16 MISSING` forever, and a
    real hole would have been invisible in that noise), and two keys arrived with it.

    `round` — because "16 of 18" says nothing without naming which round asked.

    `duplicate_titles` — the one that matters most here, and the reason it is put in front: TCC
    addresses a measurement by its TITLE (`rew_bridge.find_id`), so two measurements sharing a
    title make every answer about that title a coin toss. A checker that finds them and a panel
    that does not show them is the finding arriving nowhere.
    """
    from autosound_tcc.ui.tcc.diagnostics_panel import _rew_line

    counted = _report(cross_checks={"rew": {
        "reachable": True, "round": "cap_003", "phase": 2, "version": "v_004",
        "expected": ["w-L", "w-R", "m-L"], "found": ["w-L", "w-R"], "missing": ["m-L"],
        "complete": False,
    }})
    line = _rew_line(counted)
    assert "round cap_003" in line, "the count has to say which round asked for it"
    assert "2/3 captured" in line and "missing ['m-L']" in line

    nothing_open = _report(cross_checks={"rew": {
        "reachable": True,
        "note": "no capture round open -- nothing is expected of REW right now",
    }})
    assert "no capture round open" in _rew_line(nothing_open)

    dups = _report(cross_checks={"rew": {
        "reachable": True, "duplicate_titles": {"w-L_02": 2},
        "note": "no capture round open -- nothing is expected of REW right now",
    }})
    shown = _rew_line(dups)
    assert shown.startswith("REW: DUPLICATE TITLES"), shown
    assert "w-L_02 ×2" in shown


def test_the_screenshot_is_named_where_the_person_still_has_it():
    """SKL-010: the button opens a browser form, and dragging an image into that form works — so
    the app already puts the reporter where an attachment is possible. Nothing said so, in the
    window or in the form, and four reports arrived without the picture that WAS the report."""
    _app()
    dialog = DiagnosticsDialog()

    assert i18n.t("diagReportShot") in _texts(dialog), "beside the button that opens the form"

    template = (Path(__file__).resolve().parents[1]
                / ".github" / "ISSUE_TEMPLATE" / "beta-report.yml").read_text()
    assert "id: screenshot" in template, "and the form has a box to drop it into"
    assert "autosound-tuning-skill" in template, "and says which reports do not belong here"


def test_the_beta_box_is_unticked_by_default_and_ticking_it_asks_again_on_beta(monkeypatch):
    """The Arbiter's answers of 2026-09-14: unticked unless the app came from a candidate, next to
    the rows it changes — and those rows answer again, for the channel just chosen."""
    from autosound_tcc.core import config, install_report, updates

    _app()
    monkeypatch.setattr(install_report, "requested_revision", lambda: "")
    asked = []
    monkeypatch.setattr(updates, "check_all", lambda channel="stable": asked.append(channel) or (
        updates.Status("tcc", "0.1.3", "", False), updates.Status("skill", "3.0.8", "3.0.8", False)))
    dialog = DiagnosticsDialog()
    assert dialog._beta_box.isChecked() is False

    dialog._beta_box.setChecked(True)

    assert config.update_channel() == "beta"
    assert dialog._update_rows["tcc"][0].text() == i18n.t("updChecking")
    dialog._update_probe._thread.join(timeout=5)
    assert asked[-1] == "beta"


def test_an_app_installed_from_a_candidate_opens_with_the_box_ticked(monkeypatch):
    from autosound_tcc.core import install_report

    _app()
    monkeypatch.setattr(install_report, "requested_revision", lambda: "beta-v0.2.0-rc1")

    assert DiagnosticsDialog()._beta_box.isChecked() is True


def test_updating_tcc_on_beta_pins_the_candidate(monkeypatch, tmp_path):
    import tempfile

    from autosound_tcc.core import config, terminal_launcher, updates

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))  # the script lands here, not in /tmp
    _app()
    config.set_update_channel("beta")
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("tcc", "0.1.38", "0.2.0-rc2", True))
    _tcc_at(monkeypatch, "0.1.38")  # the row's own number, not this tree's (review I2)
    seen = []
    monkeypatch.setattr(terminal_launcher, "run_script", lambda path: seen.append(path))
    monkeypatch.setattr(updates, "newest_tcc_tag",
                        lambda channel="stable": "beta-v0.2.0-rc2" if channel == "beta" else "v0.1.39")
    asked = _tag_checked(monkeypatch)

    dialog._update_tcc()
    _finish_tcc_update(dialog)

    assert "@beta-v0.2.0-rc2" in seen[0].read_text(encoding="utf-8")
    assert asked == ["beta-v0.2.0-rc2"], "the candidate is checked too"


def test_the_rew_line_names_skipped_captures_with_their_reasons_and_no_doubled_v():
    """hub #154 §3 (method v3.0.53): `skipped` is `{title: reason}` apart from `missing`, and the
    round's key reads `v_001` as recorded or `_17` for a bare series — it printed `vv_001`."""
    from autosound_tcc.ui.tcc.diagnostics_panel import _rew_line

    counted = _report(cross_checks={"rew": {
        "reachable": True, "round": "cap_004", "phase": 0, "version": "v_001",
        "expected": ["w-L_1 (sw)", "w-R_1 (sw)", "r-L_1 (sw)"], "found": ["w-L_1 (sw)"],
        "missing": ["w-R_1 (sw)"], "skipped": {"r-L_1 (sw)": "rear deferred"}, "complete": False,
    }})
    line = _rew_line(counted)
    assert "vv_001" not in line and "v_001" in line
    assert "1 skipped" in line and "r-L_1 (sw) — rear deferred" in line
    assert "missing ['w-R_1 (sw)']" in line

    bare = _report(cross_checks={"rew": {
        "reachable": True, "round": "cap_005", "phase": 0, "version": 17,
        "expected": ["w-L_17 (sw)"], "found": ["w-L_17 (sw)"], "missing": [], "complete": True,
    }})
    assert ", _17)" in _rew_line(bare)


def test_facts_carried_in_from_another_project_are_named_and_not_counted_as_issues(monkeypatch):
    """hub #154 §3/§4: `inherited` and `sources_gone` are reported, never gated — a front-end is to
    show them rather than parse the checker's prose."""
    from PySide6.QtWidgets import QLabel

    _stub_self_checks(monkeypatch)
    _app()
    dialog = DiagnosticsDialog()
    dialog.set_report(_report(
        ok=True, files=(), cross_checks={},
        inherited=({"path": "channels.tw-L.fs_hz", "value": 1800, "from": "/cars/old",
                    "from_exists": False},),
        sources_gone=("/cars/old",),
    ))

    said = "\n".join(label.text() for label in dialog.findChildren(QLabel))
    assert i18n.t("diagInherited") in said
    assert "channels.tw-L.fs_hz = 1800" in said and "/cars/old" in said
    assert i18n.t("diagSourceGone").format(path="/cars/old") in said
    assert i18n.t("diagOk") in said, "reported, not an issue"


def _rows(tmp_path, monkeypatch, count: int = 2):
    """Two sessions of the project, a day apart, as the chooser would list them."""
    import json
    from datetime import datetime

    from autosound_tcc.core import config, session_export

    made = []
    for n in range(count):
        path = tmp_path / f"{'abcdefgh' if n == 0 else 'ijklmnop'}-{n}.jsonl"
        path.write_text(json.dumps({
            "type": "user", "timestamp": "2026-09-14T14:09:00Z",
            "message": {"role": "user", "content": f"hello car {n}"},
        }) + "\n", encoding="utf-8")
        made.append(session_export.SessionRow(
            path=path, when=datetime(2026, 9, 18 + n, 20, 17), size=path.stat().st_size,
            phase="-1" if n == 0 else None))
    monkeypatch.setattr(config, "project_dir", lambda *a, **k: tmp_path / "EPY-Sep2026")
    monkeypatch.setattr(session_export, "sessions", lambda *a, **k: made)
    return made


def test_the_sessions_tab_lists_what_there_is_and_ticks_the_newest(tmp_path, monkeypatch):
    """The user, 2026-09-19: a tab that shows the CHOICE and not the transcripts. Each row says
    when, how big and which phase, so the right ones can be ticked without opening any."""
    _rows(tmp_path, monkeypatch)
    _app()
    dialog = DiagnosticsDialog()

    dialog._tabs.setCurrentWidget(dialog._sessions_tab)

    assert dialog._sessions_list.count() == 2
    assert "18.09 20:17" in dialog._sessions_list.item(0).text()
    assert "фаза" in dialog._sessions_list.item(0).text() or "phase" in \
        dialog._sessions_list.item(0).text()
    assert [dialog._sessions_list.item(n).checkState().name for n in range(2)] == \
        ["Checked", "Unchecked"]
    assert "EPY-Sep2026" in dialog._sessions_head.text()


def test_the_name_follows_what_is_ticked_and_how_it_is_saved(tmp_path, monkeypatch):
    """Named for the days being saved, not for today; `.zip` only when there is more than one file
    in it (the user, 2026-09-19)."""
    _rows(tmp_path, monkeypatch)
    _app()
    dialog = DiagnosticsDialog()
    dialog._tabs.setCurrentWidget(dialog._sessions_tab)

    assert dialog._sessions_name.text() == "EPY-Sep2026-sessions-2026-09-18.md"

    dialog._tick_all_sessions(True)
    assert dialog._sessions_name.text() == "EPY-Sep2026-sessions-2026-09-18_2026-09-19.zip"

    dialog._sessions_one.setChecked(True)
    assert dialog._sessions_name.text() == "EPY-Sep2026-sessions-2026-09-18_2026-09-19.md"


def test_saving_writes_one_file_per_session_into_the_archive(tmp_path, monkeypatch):
    """The user, 2026-09-19: «може кожну окремим файлом і архів»."""
    import zipfile

    _rows(tmp_path, monkeypatch)
    _app()
    dialog = DiagnosticsDialog()
    dialog._tabs.setCurrentWidget(dialog._sessions_tab)
    dialog._tick_all_sessions(True)
    dialog._sessions_folder.setText(str(tmp_path / "out"))

    dialog._save_sessions()

    target = tmp_path / "out" / "EPY-Sep2026-sessions-2026-09-18_2026-09-19.zip"
    assert target.exists(), dialog._sessions_status.text()
    with zipfile.ZipFile(target) as archive:
        assert len(archive.namelist()) == 2
        assert "hello car 0" in archive.read(sorted(archive.namelist())[0]).decode("utf-8")
    assert str(target) in dialog._sessions_status.text()


def test_no_sessions_says_so_and_the_button_cannot_be_pressed(tmp_path, monkeypatch):
    from autosound_tcc.core import config, session_export

    monkeypatch.setattr(config, "project_dir", lambda *a, **k: tmp_path)
    monkeypatch.setattr(session_export, "sessions", lambda *a, **k: [])
    _app()
    dialog = DiagnosticsDialog()

    dialog._tabs.setCurrentWidget(dialog._sessions_tab)

    assert dialog._sessions_list.count() == 0
    assert dialog._sessions_head.text() == i18n.t("diagSessionsNone")
    assert not dialog._sessions_btn.isEnabled()


def test_report_a_problem_offers_both_routes_with_the_installation_block(monkeypatch):
    """TODO F-042: the button went to GitHub only. It now opens the same choice as "Message the
    developer" — the form for a person without an account, GitHub with its template for one with
    it — and the installation block goes either way, shown before Send."""
    from autosound_tcc.core import form_report
    from autosound_tcc.ui.tcc import diagnostics_panel as dp

    made = []

    class _Dialog:
        def __init__(self, github_url, form_url, parent=None, **kwargs):
            made.append((form_url, kwargs))

        def exec(self):
            return 0

    monkeypatch.setattr(dp, "FeedbackDialog", _Dialog)
    _app()
    dialog = DiagnosticsDialog()
    dialog._install_read = True
    dialog._report_tools = _tools_section(omp="17.3.8")  # the box is the whole answer
    dialog._install_text.setPlainText("[Autosound TCC]\n  version  0.1.4\n")

    dialog._open_issue()

    assert len(made) == 1
    form_url, kwargs = made[0]
    assert form_url == form_report.post_url()
    assert kwargs["kind"] == "problem"
    assert "0.1.4" in kwargs["attachment"], "the installation block travels with the report"
    link = kwargs["github_link"]("it froze")
    assert link.startswith("https://github.com/ayukhno/autosound-tcc/issues/new?")
    assert "template=beta-report.yml" in link and "0.1.4" in link and "it+froze" in link


def test_the_rew_line_marks_a_skip_of_a_title_the_round_never_expected():
    """Method `TCC-022` (hub #190): every skip is reported now, including one outside `expected`.

    It used to intersect `skipped` with `missing`, and `missing` comes from `expected` — so a skip
    of a title nobody asked for vanished from the report entirely. Four rear titles went that way
    on a live project. `skipped_unplanned` names them, and this line has to say which is which:
    "decided against" and "nobody ever asked for this" are different facts, and a reader who
    cannot tell them apart learns the wrong thing from the same sentence.

    The words are the method's own (`contract.py`, the `skipped_unplanned` branch) — one
    vocabulary, not a second one invented here.
    """
    from autosound_tcc.ui.tcc.diagnostics_panel import _rew_line

    mixed = _report(cross_checks={"rew": {
        "reachable": True, "round": "cap_006", "phase": 0, "version": "v_002",
        "expected": ["w-L_1 (sw)", "r-L_1 (sw)"], "found": ["w-L_1 (sw)"],
        "missing": [], "complete": True,
        "skipped": {"r-L_1 (sw)": "rear deferred", "r-R_1 (sw)": "rears not wired"},
        "skipped_unplanned": ["r-R_1 (sw)"],
    }})
    line = _rew_line(mixed)

    assert "r-R_1 (sw) — rears not wired  (never expected by this round)" in line
    # The planned skip keeps its plain form: the mark is the exception, not decoration on both.
    assert "r-L_1 (sw) — rear deferred\n" in line + "\n"
    assert "r-L_1 (sw) — rear deferred  (never" not in line


def test_the_rew_line_of_a_method_that_does_not_send_the_key_is_unchanged():
    """The pin is still `v3.0.58` until the method tags, so both shapes arrive at this reader."""
    from autosound_tcc.ui.tcc.diagnostics_panel import _rew_line

    old = _report(cross_checks={"rew": {
        "reachable": True, "round": "cap_007", "phase": 0, "version": "v_001",
        "expected": ["w-L_1 (sw)"], "found": [], "missing": [], "complete": True,
        "skipped": {"w-L_1 (sw)": "not today"},
    }})
    line = _rew_line(old)

    assert "w-L_1 (sw) — not today" in line and "never expected" not in line


# ---- omp, agy, gh and Claude Code (tcc#98) ------------------------------------------------------


def _tool(name, here, there, updatable=True):
    from autosound_tcc.core import updates

    return updates.Tool(name, here, there, updatable)


def _finish_tools(dialog) -> None:
    """Run the tools' job to the end, here and now: a thread the dialog's timer would poll."""
    for _ in range(5):
        job = dialog._tools_job
        if job is None:
            return
        job.join(timeout=10)
        dialog._poll_tools_job()
    raise AssertionError("the tools' job never settled")


def _tools_shown(monkeypatch, *tools):
    """A dialog whose Installation tab was opened and whose tools' status came back as `tools`."""
    from autosound_tcc.core import updates

    monkeypatch.setattr(updates, "tools_status", lambda: updates.ToolsStatus(True, tuple(tools)))
    _app()
    dialog = DiagnosticsDialog()
    dialog._tabs.setCurrentWidget(dialog._updates_tab)
    _finish_tools(dialog)
    return dialog


def test_the_tool_rows_appear_after_the_worker_not_before(monkeypatch):
    """The skill's `status` takes up to a minute (Homebrew, npm, GitHub): the window opens at once
    and the rows come when the answer does. Opening it updates nothing."""
    from autosound_tcc.core import updates

    release = threading.Event()
    monkeypatch.setattr(updates, "tools_status", lambda: release.wait(5) and updates.ToolsStatus(
        True, (_tool("omp", "17.3.8", "18.2.4"), _tool("agy", "1.2.14", ""),
               _tool("gh", "2.102.0", "2.102.0"), _tool("claude", "2.1.280", "2.1.284"))))
    monkeypatch.setattr(updates, "update_tools",
                        lambda names: pytest.fail("nothing is updated without a press"))
    _app()
    dialog = DiagnosticsDialog()
    assert dialog._tools_job is None, "the window opening asks nothing"

    dialog._tabs.setCurrentWidget(dialog._updates_tab)

    assert dialog._tools_job is not None and dialog._tool_rows == {}, "not before the worker"
    assert i18n.t("updToolsChecking") in _texts(dialog)
    release.set()
    _finish_tools(dialog)

    assert list(dialog._tool_rows) == ["omp", "agy", "gh", "claude"]
    label, button = dialog._tool_rows["omp"]
    assert label.text() == i18n.t("updToolAvailable").format(name="omp", here="17.3.8",
                                                             there="18.2.4")
    assert button.isEnabled()
    label, button = dialog._tool_rows["agy"]
    assert label.text() == i18n.t("updToolUnknown").format(name="agy", here="1.2.14"), (
        "an empty `available` reads unknown, never up to date")
    assert button.isEnabled()
    label, button = dialog._tool_rows["gh"]
    assert label.text() == i18n.t("updToolCurrent").format(name="gh", here="2.102.0")
    assert not button.isEnabled(), "nothing to install: no live button"
    assert "Claude Code" in dialog._tool_rows["claude"][0].text()
    assert dialog._tools_all_btn.isEnabled()


def test_no_tools_here_and_no_updater_here_are_each_said(monkeypatch):
    from autosound_tcc.core import updates

    dialog = _tools_shown(monkeypatch)
    assert i18n.t("updToolsNone") in _texts(dialog) and dialog._tool_rows == {}

    monkeypatch.setattr(updates, "tools_status",
                        lambda: updates.ToolsStatus(False, reason="no_upkeep_here"))
    dialog._on_refresh()
    _finish_tools(dialog)

    assert i18n.t("updWhy_no_upkeep_here") in _texts(dialog) and dialog._tool_rows == {}


def test_a_tool_s_button_updates_that_tool_and_all_updates_what_is_still_offered(monkeypatch):
    """Each press is the Arbiter's (a newer omp changes what a session runs on, tcc#97): the row's
    button sends its one tool, «Update all» the tools whose buttons are live."""
    from autosound_tcc.core import updates

    dialog = _tools_shown(monkeypatch, _tool("omp", "17.3.8", "18.2.4"),
                          _tool("agy", "1.2.14", ""), _tool("gh", "2.102.0", "2.102.0"))
    asked = []
    monkeypatch.setattr(updates, "update_tools", lambda names: asked.append(list(names)) or
                        updates.ToolsUpdate(tuple(updates.ToolUpdate(name, True, "1.0", "2.0")
                                                  for name in names)))

    dialog._tool_rows["omp"][1].click()
    assert dialog._tool_rows["omp"][0].text() == i18n.t("updToolUpdating").format(
        name="omp", here="17.3.8")
    assert not any(button.isEnabled() for _label, button in dialog._tool_rows.values()), (
        "one update at a time")
    assert not dialog._tools_all_btn.isEnabled()
    _finish_tools(dialog)

    assert asked == [["omp"]]
    assert dialog._tool_rows["omp"][0].text() == i18n.t("updToolDone").format(
        name="omp", old="1.0", new="2.0")
    assert not dialog._tool_rows["omp"][1].isEnabled(), "done: nothing more to press"

    dialog._tools_all_btn.click()
    _finish_tools(dialog)

    assert asked == [["omp"], ["agy"]], "omp is done and gh is current: agy alone is still offered"


def test_a_tool_that_did_not_update_keeps_its_row_says_why_and_hides_no_other(monkeypatch):
    from autosound_tcc.core import updates

    dialog = _tools_shown(monkeypatch, _tool("omp", "17.3.8", "18.2.4"),
                          _tool("agy", "1.2.14", ""), _tool("gh", "2.102.0", "2.102.0"))
    omp_before = dialog._tool_rows["omp"][0].text()
    gh_before = dialog._tool_rows["gh"][0].text()
    why = "Error: omp: Permission denied @ rb_sysopen"
    monkeypatch.setattr(updates, "update_tools", lambda names: updates.ToolsUpdate((
        updates.ToolUpdate("omp", False, "17.3.8", "17.3.8", why),
        updates.ToolUpdate("agy", True, "1.2.14", "1.3.0"))))

    dialog._tools_all_btn.click()
    _finish_tools(dialog)

    label, button = dialog._tool_rows["omp"]
    assert label.text() == omp_before + "\n" + i18n.t("updToolFailed").format(why=why)
    assert button.isEnabled(), "the person can try again"
    assert dialog._tool_rows["agy"][0].text() == i18n.t("updToolDone").format(
        name="agy", old="1.2.14", new="1.3.0")
    assert dialog._tool_rows["gh"][0].text() == gh_before, "a row nobody asked about is untouched"
    assert list(dialog._tool_rows) == ["omp", "agy", "gh"], "no row hidden"


def test_an_update_that_did_not_answer_leaves_every_row_it_asked_about_as_it_was(monkeypatch):
    from autosound_tcc.core import updates

    dialog = _tools_shown(monkeypatch, _tool("omp", "17.3.8", "18.2.4"))
    before = dialog._tool_rows["omp"][0].text()
    monkeypatch.setattr(updates, "update_tools", lambda names: updates.ToolsUpdate(
        (), "upkeep_failed", "OSError: disk full"))

    dialog._tool_rows["omp"][1].click()
    _finish_tools(dialog)

    label, button = dialog._tool_rows["omp"]
    assert label.text().startswith(before + "\n") and "disk full" in label.text()
    assert button.isEnabled()


def test_a_re_check_during_a_tool_update_leaves_its_rows_alone(monkeypatch):
    from autosound_tcc.core import updates

    dialog = _tools_shown(monkeypatch, _tool("omp", "17.3.8", "18.2.4"))
    release = threading.Event()
    monkeypatch.setattr(updates, "update_tools", lambda names: release.wait(5) and
                        updates.ToolsUpdate((updates.ToolUpdate("omp", True, "17.3.8", "18.2.4"),)))
    monkeypatch.setattr(updates, "tools_status",
                        lambda: pytest.fail("no status while a tool is being updated"))

    dialog._tool_rows["omp"][1].click()
    dialog._on_refresh()

    assert dialog._tool_rows["omp"][0].text() == i18n.t("updToolUpdating").format(
        name="omp", here="17.3.8")
    release.set()
    _finish_tools(dialog)
    assert "18.2.4" in dialog._tool_rows["omp"][0].text()


def test_the_tool_rows_get_their_height_when_they_land(monkeypatch):
    """The window takes its size before the rows exist, and they land a minute later: at that size
    each row and «Update all» still get at least the height they need — a sliver of 5 px is a row
    nobody can read or press (review of tcc#98)."""
    from autosound_tcc.core import updates

    monkeypatch.setattr(updates, "tools_status", lambda: updates.ToolsStatus(True, (
        _tool("claude", "2.1.280", "2.1.284"), _tool("omp", "17.3.8", "18.2.4"),
        _tool("agy", "1.2.14", ""), _tool("gh", "2.102.0", "2.102.0"))))
    _app()
    dialog = DiagnosticsDialog()
    dialog.show()
    QApplication.processEvents()
    dialog._tabs.setCurrentWidget(dialog._updates_tab)
    QApplication.processEvents()
    size = dialog.size()
    _finish_tools(dialog)
    for _ in range(5):
        QApplication.processEvents()

    assert dialog.size() == size, "the rows fit without the window being resized"
    rows = [button.parentWidget() for _label, button in dialog._tool_rows.values()]
    rows.append(dialog._tools_all_btn.parentWidget())
    assert len(rows) == 5
    for row in rows:
        assert row.height() >= row.minimumSizeHint().height(), (
            f"{row.height()} px of {row.minimumSizeHint().height()}")
    dialog.close()


def _session(dialog, live: list) -> None:
    """The main window's answer to "is an AI session running", as a switch the test flips."""
    dialog.set_session_probe(lambda: live[0])


def test_a_running_session_holds_omp_and_claude_and_says_why(monkeypatch):
    """Ruling 21 (tcc#98): a session runs on omp and Claude Code, so while one runs their buttons —
    and «Update all», which would take them along — wait, with the reason on the row. agy and gh
    stay offered. Read again when the window opens and on Re-check."""
    from autosound_tcc.core import updates

    monkeypatch.setattr(updates, "tools_status", lambda: updates.ToolsStatus(True, (
        _tool("claude", "2.1.280", "2.1.284"), _tool("omp", "17.3.8", "18.2.4"),
        _tool("agy", "1.2.14", ""), _tool("gh", "2.92.0", "2.102.0"))))
    monkeypatch.setattr(updates, "update_tools",
                        lambda names: pytest.fail("nothing under a running session"))
    _app()
    dialog = DiagnosticsDialog()
    live = [True]
    _session(dialog, live)
    dialog._tabs.setCurrentWidget(dialog._updates_tab)
    _finish_tools(dialog)

    for name in ("omp", "claude"):
        assert not dialog._tool_rows[name][1].isEnabled(), name
        assert not dialog._tool_guards[name].isHidden(), name
        assert dialog._tool_guards[name].text() == i18n.t("updToolSession")
    for name in ("agy", "gh"):
        assert dialog._tool_rows[name][1].isEnabled(), name
    assert not dialog._tools_all_btn.isEnabled(), "«all» would take omp and Claude Code along"
    assert i18n.t("updToolsSessionAll").format(names="Claude Code, omp") in _texts(dialog)
    dialog._update_tools(["omp"])  # a press that slipped past the button: still nothing runs
    assert dialog._tools_job is None

    live[0] = False
    dialog._on_refresh()  # Re-check
    _finish_tools(dialog)
    assert dialog._tool_rows["omp"][1].isEnabled() and dialog._tools_all_btn.isEnabled()
    assert dialog._tool_guards["omp"].isHidden()

    live[0] = True
    dialog.show()  # the window opened again: asked again, no new status needed
    assert not dialog._tool_rows["omp"][1].isEnabled()
    assert not dialog._tool_guards["omp"].isHidden()
    dialog.close()


def test_the_session_hold_is_said_in_orange_not_in_the_error_red(monkeypatch):
    """VM-5 (ruling 21, tcc#98): the hold read red, like an error. The Arbiter: «не сірим -
    помаранчевим, бо це стопер але не помилка». The theme's own test holds the colour itself."""
    from autosound_tcc.core import updates

    monkeypatch.setattr(updates, "tools_status", lambda: updates.ToolsStatus(True, (
        _tool("claude", "2.1.280", "2.1.284"), _tool("omp", "17.3.8", "18.2.4"))))
    _app()
    dialog = DiagnosticsDialog()
    _session(dialog, [True])
    dialog._tabs.setCurrentWidget(dialog._updates_tab)
    _finish_tools(dialog)

    held = [dialog._tool_guards["omp"], dialog._tool_guards["claude"], dialog._tools_all_note]
    for label in held:
        assert not label.isHidden()
        assert label.property("class") == "kv-caution", label.text()


def test_a_second_failure_of_the_same_tool_says_its_reason_once(monkeypatch):
    from autosound_tcc.core import updates

    dialog = _tools_shown(monkeypatch, _tool("omp", "17.3.8", "18.2.4"))
    why = "Error: omp: Permission denied @ rb_sysopen"
    monkeypatch.setattr(updates, "update_tools", lambda names: updates.ToolsUpdate((
        updates.ToolUpdate("omp", False, "17.3.8", "17.3.8", why),)))

    for _press in range(2):
        dialog._tool_rows["omp"][1].click()
        _finish_tools(dialog)

    assert dialog._tool_rows["omp"][0].text() == (
        i18n.t("updToolAvailable").format(name="omp", here="17.3.8", there="18.2.4") + "\n"
        + i18n.t("updToolFailed").format(why=why))


def _re_check(monkeypatch, dialog, *tools) -> None:
    """Re-check, with the tools' status now answering `tools`."""
    from autosound_tcc.core import updates

    monkeypatch.setattr(updates, "tools_status", lambda: updates.ToolsStatus(True, tuple(tools)))
    dialog._on_refresh()
    _finish_tools(dialog)


def test_a_re_check_keeps_what_the_update_just_learned(monkeypatch):
    """Finding 140 (tcc#138), the Arbiter on the VM: «Update all» left Claude Code on 2.1.287 and
    agy on 1.2.15, «already the newest», greyed — and Re-check put both back to «unknown» with
    «Update» live, because their sources cannot tell without installing. The update could: the
    version it left stays the newest on every Re-check that still finds it. A tool whose source
    CAN tell is the source's to answer."""
    from autosound_tcc.core import updates

    dialog = _tools_shown(monkeypatch, _tool("claude", "2.1.286", ""),
                          _tool("omp", "18.4.8", "18.4.12"), _tool("agy", "1.2.15", ""))
    monkeypatch.setattr(updates, "update_tools", lambda names: updates.ToolsUpdate((
        updates.ToolUpdate("claude", True, "2.1.286", "2.1.287"),
        updates.ToolUpdate("omp", True, "18.4.8", "18.4.12"),
        updates.ToolUpdate("agy", True, "1.2.15", "1.2.15"))))
    dialog._tools_all_btn.click()
    _finish_tools(dialog)

    for _re_check_number in range(2):
        _re_check(monkeypatch, dialog, _tool("claude", "2.1.287", ""),
                  _tool("omp", "18.4.12", "18.4.13"), _tool("agy", "1.2.15", ""))

        for name, title, here in (("claude", "Claude Code", "2.1.287"), ("agy", "agy", "1.2.15")):
            label, button = dialog._tool_rows[name]
            assert label.text() == i18n.t("updToolSame").format(name=title, here=here), name
            assert not button.isEnabled(), name
        label, button = dialog._tool_rows["omp"]
        assert label.text() == i18n.t("updToolAvailable").format(
            name="omp", here="18.4.12", there="18.4.13"), "its source names a newer one: it wins"
        assert button.isEnabled()
        assert dialog._tools_all_btn.isEnabled(), "omp is still offered"


def test_another_version_of_the_tool_drops_what_the_update_learned(monkeypatch):
    """What the update learned is about the version it left (tcc#138). Once the tool says another —
    moved by its own updater, or outside TCC — the source's «cannot tell» is all there is, and it
    stays so if the old number comes back: that was learned of an install no longer here."""
    from autosound_tcc.core import updates

    dialog = _tools_shown(monkeypatch, _tool("claude", "2.1.286", ""))
    monkeypatch.setattr(updates, "update_tools", lambda names: updates.ToolsUpdate((
        updates.ToolUpdate("claude", True, "2.1.286", "2.1.287"),)))
    dialog._tool_rows["claude"][1].click()
    _finish_tools(dialog)
    _re_check(monkeypatch, dialog, _tool("claude", "2.1.287", ""))
    assert dialog._tool_rows["claude"][0].text() == i18n.t("updToolSame").format(
        name="Claude Code", here="2.1.287")

    for here in ("2.1.288", "2.1.287"):
        _re_check(monkeypatch, dialog, _tool("claude", here, ""))

        label, button = dialog._tool_rows["claude"]
        assert label.text() == i18n.t("updToolUnknown").format(name="Claude Code", here=here), here
        assert button.isEnabled(), "the person may still update"


def test_what_an_update_learned_outlives_the_window_it_was_learned_in(monkeypatch):
    """A new project opens a new main window in the same run of TCC (`_open_new_project_dialog`),
    and with it a new diagnostics window. The tools are the machine's, not a window's: the new one
    does not offer again what the old one has just installed (tcc#138)."""
    from autosound_tcc.core import updates

    first = _tools_shown(monkeypatch, _tool("agy", "1.2.15", ""))
    monkeypatch.setattr(updates, "update_tools", lambda names: updates.ToolsUpdate((
        updates.ToolUpdate("agy", True, "1.2.15", "1.2.15"),)))
    first._tool_rows["agy"][1].click()
    _finish_tools(first)

    second = _tools_shown(monkeypatch, _tool("agy", "1.2.15", ""))

    label, button = second._tool_rows["agy"]
    assert label.text() == i18n.t("updToolSame").format(name="agy", here="1.2.15")
    assert not button.isEnabled()


def _update_all_answering(monkeypatch, dialog, *rows) -> None:
    """«Update all», with the skill's `tools` answering `rows`."""
    from autosound_tcc.core import updates

    monkeypatch.setattr(updates, "update_tools", lambda names: updates.ToolsUpdate(tuple(rows)))
    dialog._tools_all_btn.click()
    _finish_tools(dialog)


def test_what_an_update_learned_lapses_after_twelve_hours(monkeypatch):
    """Ruling 3 on tcc#138: what the update learned has an end besides the tool's version. agy's
    source and a native Claude Code's never name a version, so without one a TCC left open
    overnight would say «already the newest», with «Update» off, over a release that came out in
    the night. The update's word stands for the working session it was said in: twelve hours."""
    from autosound_tcc.core import updates
    from autosound_tcc.ui.tcc import diagnostics_panel

    learned = time.time()
    monkeypatch.setattr(diagnostics_panel.time, "time", lambda: learned)
    dialog = _tools_shown(monkeypatch, _tool("claude", "2.1.286", ""))
    _update_all_answering(monkeypatch, dialog,
                          updates.ToolUpdate("claude", True, "2.1.286", "2.1.287"))

    monkeypatch.setattr(diagnostics_panel.time, "time", lambda: learned + 12 * 3600 - 60)
    _re_check(monkeypatch, dialog, _tool("claude", "2.1.287", ""))
    assert dialog._tool_rows["claude"][0].text() == i18n.t("updToolSame").format(
        name="Claude Code", here="2.1.287"), "a minute short of twelve hours: still the update's"

    monkeypatch.setattr(diagnostics_panel.time, "time", lambda: learned + 12 * 3600)
    _re_check(monkeypatch, dialog, _tool("claude", "2.1.287", ""))

    label, button = dialog._tool_rows["claude"]
    assert label.text() == i18n.t("updToolUnknown").format(name="Claude Code", here="2.1.287")
    assert button.isEnabled(), "the person may update again"


def test_the_receipt_names_the_version_the_row_showed(monkeypatch):
    """Finding 140 on the VM: Claude Code read 2.1.286, «Update all» left it on 2.1.287, and its
    receipt said «2.1.287: already the newest». A native Claude Code updates itself in the
    background, and the skill reads `old` at the press — after that move. The person saw 2.1.286 on
    the row, and the receipt is about that row (review of tcc#138, M1). A tool the row showed on the
    version it stayed on is still «already the newest»."""
    from autosound_tcc.core import updates

    dialog = _tools_shown(monkeypatch, _tool("claude", "2.1.286", ""), _tool("agy", "1.2.15", ""))
    _update_all_answering(monkeypatch, dialog,
                          updates.ToolUpdate("claude", True, "2.1.287", "2.1.287"),
                          updates.ToolUpdate("agy", True, "1.2.15", "1.2.15"))

    assert dialog._tool_rows["claude"][0].text() == i18n.t("updToolDone").format(
        name="Claude Code", old="2.1.286", new="2.1.287")
    assert dialog._tool_rows["agy"][0].text() == i18n.t("updToolSame").format(
        name="agy", here="1.2.15")


def test_a_tool_that_would_not_say_its_version_keeps_what_the_update_learned(monkeypatch):
    """`--version` that fails or runs past the skill's timeout is an empty version (`upkeep.py`
    `tool_version`): a slow VM, a binary in the middle of its swap. The tool would not say — not
    that it is on another version — so the next Re-check that hears 2.1.287 still has the update's
    word, and does not offer it again (review of tcc#138, M2)."""
    from autosound_tcc.core import updates

    dialog = _tools_shown(monkeypatch, _tool("claude", "2.1.286", ""))
    _update_all_answering(monkeypatch, dialog,
                          updates.ToolUpdate("claude", True, "2.1.286", "2.1.287"))
    _re_check(monkeypatch, dialog, _tool("claude", "", ""))

    _re_check(monkeypatch, dialog, _tool("claude", "2.1.287", ""))

    label, button = dialog._tool_rows["claude"]
    assert label.text() == i18n.t("updToolSame").format(name="Claude Code", here="2.1.287")
    assert not button.isEnabled()


def test_a_failed_update_teaches_nothing(monkeypatch):
    """The skill writes `new` for a tool that did not update too: the version it was left on. That
    is no word on the newest, so a Re-check reads «unknown» with «Update» live — not «already the
    newest» over a «not updated» the person has just seen (review of tcc#138, M3)."""
    from autosound_tcc.core import updates

    dialog = _tools_shown(monkeypatch, _tool("agy", "1.2.15", ""))
    _update_all_answering(monkeypatch, dialog, updates.ToolUpdate(
        "agy", False, "1.2.15", "1.2.15", "agy: the update server did not answer"))

    _re_check(monkeypatch, dialog, _tool("agy", "1.2.15", ""))

    label, button = dialog._tool_rows["agy"]
    assert label.text() == i18n.t("updToolUnknown").format(name="agy", here="1.2.15")
    assert button.isEnabled()


@pytest.mark.parametrize("lang", [code for code, _key, _badge in i18n.LANGS])
def test_a_tool_whose_source_cannot_tell_is_not_written_as_an_offer(lang):
    """Finding 140 (tcc#138): «agy 1.2.15 → unknown» had the offer's own shape — here → there, as
    «omp 18.4.8 → 18.4.12» read beside it — and under a live «Update» it read as one more update to
    make. It says what is so instead: the newest cannot be known without installing. Its button
    stays (`test_the_tool_rows_appear_after_the_worker_not_before`): the person may still update."""
    assert "→" in i18n.T[lang]["updToolAvailable"], "the offer keeps its arrow"
    assert "→" not in i18n.T[lang]["updToolUnknown"]


def test_agy_and_a_native_claude_code_read_up_to_date_or_newer_from_the_methods_answer(tmp_path):
    """hub #237 (TCC-047), the method's v3.1.0: `upkeep.py` names the newest version of a
    self-installed agy (its update server's manifest for this platform) and of a native Claude Code
    (the npm dist-tag of its update channel), where it said "" before — so their rows read «up to
    date» or «→ x.y.z» as omp's and gh's do, and «cannot be known» stays for a source that does
    not answer. Asked of the vendored `available_version` through its own `fetch`: no network."""
    import importlib.util

    from autosound_tcc.core import updates
    from autosound_tcc.ui.tcc import diagnostics_panel

    script = updates.upkeep_script()
    if not script.is_file():
        pytest.skip("the method's submodule is not checked out")
    spec = importlib.util.spec_from_file_location("upkeep_under_test", script)
    upkeep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upkeep)

    def fetch(url, timeout=20):
        if "/manifests/" in url:
            return {"version": "1.2.16"}
        if "dist-tags" in url:
            return {"latest": "2.1.287", "stable": "2.1.280"}
        return None

    def newest(name, package, source=fetch):
        return upkeep.available_version(name, str(tmp_path / name), "self", package,
                                        fetch=source, home=str(tmp_path))

    agy = updates.Tool("agy", "1.2.15", newest("agy", "agy"), True)
    claude = updates.Tool("claude", "2.1.287", newest("claude", "@anthropic-ai/claude-code"), True)
    silent = updates.Tool("agy", "1.2.15", newest("agy", "agy", lambda url, timeout=20: None), True)

    assert diagnostics_panel._tool_line(agy) == i18n.t("updToolAvailable").format(
        name="agy", here="1.2.15", there="1.2.16") and agy.offered
    assert diagnostics_panel._tool_line(claude) == i18n.t("updToolCurrent").format(
        name="Claude Code", here="2.1.287") and not claude.offered
    assert diagnostics_panel._tool_line(silent) == i18n.t("updToolUnknown").format(
        name="agy", here="1.2.15") and silent.offered


#: `conftest.py` stands in for `update_tools`; the real one, for the test that runs it end to end.
from autosound_tcc.core import updates as _updates  # noqa: E402

_REAL_UPDATE_TOOLS = _updates.update_tools


def test_a_name_the_skill_refuses_restores_the_row_with_its_reason(monkeypatch, tmp_path):
    """`--only` with a name the script does not know is argparse's: exit 2, usage on stderr, no
    JSON. The row is put back as it was, with the script's own last line as the reason."""
    from autosound_tcc.core import updates, vendor_loader

    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "scripts" / "upkeep.py").write_text("raise SystemExit('never runs')\n")
    monkeypatch.setattr(vendor_loader, "skill_dir", lambda: skill)
    said = ("upkeep.py tools: error: argument --only: invalid choice: 'uv' "
            "(choose from 'claude', 'omp', 'agy', 'gh')")
    monkeypatch.setattr(updates, "_run_upkeep",
                        lambda argv, timeout: (2, "", f"usage: upkeep.py tools [-h]\n{said}\n"))
    dialog = _tools_shown(monkeypatch, _tool("uv", "0.8.0", "0.9.0"))
    before = dialog._tool_rows["uv"][0].text()
    monkeypatch.setattr(updates, "update_tools", _REAL_UPDATE_TOOLS)

    dialog._tool_rows["uv"][1].click()
    _finish_tools(dialog)

    label, button = dialog._tool_rows["uv"]
    assert label.text() == before + "\n" + i18n.t("updToolFailed").format(
        why=i18n.t("updWhy_upkeep_failed") + ": " + said)
    assert button.isEnabled()


def test_coming_back_to_the_window_asks_again_without_the_minute_long_status(monkeypatch):
    """A session that ended while this window stayed open lets go of omp and Claude Code as soon
    as the person comes back to the window — not only after Re-check, which asks every tool's
    source again (re-review of tcc#98)."""
    from PySide6.QtCore import QEvent

    from autosound_tcc.core import updates

    dialog = _tools_shown(monkeypatch, _tool("omp", "17.3.8", "18.2.4"))
    live = [True]
    _session(dialog, live)
    assert not dialog._tool_rows["omp"][1].isEnabled()
    monkeypatch.setattr(updates, "tools_status",
                        lambda: pytest.fail("coming back does not ask the tools again"))
    monkeypatch.setattr(dialog, "isActiveWindow", lambda: True)

    live[0] = False
    QApplication.sendEvent(dialog, QEvent(QEvent.Type.ActivationChange))

    assert dialog._tools_job is None, "no status was started"
    assert dialog._tool_rows["omp"][1].isEnabled()
    assert dialog._tool_guards["omp"].isHidden()


_SIGNATURE_LINES = (
    ("v3.0.7: signature good (ayukhno)", "updSigGood", {"tag": "v3.0.7", "principal": "ayukhno"}),
    ("v3.0.40 predates signed tags (they start at v3.0.64): installed without a signature check",
     "updSigPredates", {"tag": "v3.0.40", "first": "v3.0.64"}),
)


@pytest.mark.parametrize("lang", ["uk", "en"])
@pytest.mark.parametrize("line, key, parts", _SIGNATURE_LINES)
def test_the_signature_line_is_said_in_the_reader_s_language(line, key, parts, lang):
    """tcc#122 (W-4's review of tcc#102): «Підпис релізу: v3.0.7: signature good (ayukhno)» — the
    row in Ukrainian, the line in git's English. The forms TCC and the skill write are said by
    their parts, the tag and the key's name as they are; English reads as it did."""
    from autosound_tcc.ui.tcc.diagnostics_panel import _signature_said

    try:
        i18n.set_language(lang)
        assert _signature_said(line) == i18n.t(key).format(**parts)
        if lang == "en":
            assert _signature_said(line) == line, "the English is the line as it was"
    finally:
        i18n.set_language("en")


def test_the_developer_s_switch_is_said_in_the_reader_s_language():
    from autosound_tcc.core.signed_tags import SKIP_VERIFY_VAR
    from autosound_tcc.ui.tcc.diagnostics_panel import _signature_said

    line = f"signature NOT checked: {SKIP_VERIFY_VAR}=1 is set (a developer's switch)"
    try:
        i18n.set_language("uk")
        assert _signature_said(line) == i18n.t("updSigSkipped").format(var=SKIP_VERIFY_VAR)
    finally:
        i18n.set_language("en")


@pytest.mark.parametrize("line", ["", "Good \"git\" signature for ayukhno with ED25519 key SHA256:x",
                                  "v3.0.7: signature good"])
def test_a_signature_line_tcc_does_not_know_is_left_as_git_printed_it(line):
    from autosound_tcc.ui.tcc.diagnostics_panel import _signature_said

    try:
        i18n.set_language("uk")
        assert _signature_said(line) == line
    finally:
        i18n.set_language("en")


def test_the_updated_method_s_row_says_its_signature_in_ukrainian(monkeypatch):
    """The row the Arbiter reads: the receipt of a method update, in his language end to end."""
    dialog, _asked = _skill_offered(monkeypatch)
    monkeypatch.setattr(dialog, "_ask_keep_local", lambda changed: pytest.fail("clean: no question"))
    try:
        i18n.set_language("uk")
        dialog._update_skill()
        _finish_skill_update(dialog)
        text = dialog._update_rows["skill"][0].text()
        said = i18n.t("updSigGood").format(tag="v3.0.7", principal="ayukhno")
        assert i18n.t("updSkillSigned").format(line=said) in text, text
        assert "signature good" not in text
    finally:
        i18n.set_language("en")


def _agy_reading(monkeypatch, asked: list) -> None:
    """agy installed; the method's reading recorded with the thread it was asked on."""
    from autosound_tcc.core import contract_check, critic, model_choices

    monkeypatch.setattr(contract_check, "run", lambda *a, **k: _report())
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")
    monkeypatch.setattr(
        critic, "agy_sign_in",
        lambda project_dir=None, register=None: asked.append(
            (project_dir, threading.current_thread() is threading.main_thread()))
        or ("adc", "ADC (Google Cloud), /x/adc.json"))


def test_the_check_brings_agys_sign_in_with_the_report_from_off_the_gui_thread(
        monkeypatch, tmp_path):
    """Night review of tcc#135, I2: the agy row started the method in a Python child from the
    panel's render, on the GUI thread, on every open, Re-check, «ask», fix and language switch.
    The worker that already runs for every check asks now, and the row reads what it brought."""
    from autosound_tcc.ui.tcc import workers

    _app()
    asked: list = []
    _agy_reading(monkeypatch, asked)
    worker = workers._ContractWorker(tmp_path)

    worker.start()
    assert worker.wait(10_000)

    assert asked == [(tmp_path, False)], "asked once, for this project, off the GUI thread"
    dialog = DiagnosticsDialog()
    dialog.set_report(_report())
    assert i18n.t("selfAgyAdcTitle") in _texts(dialog)
    assert asked == [(tmp_path, False)], "the render asked nothing"


def test_the_intake_gates_check_does_not_ask_agys_sign_in(monkeypatch, tmp_path):
    """The gate's check after an intake save feeds no panel: a child there is a child for nobody."""
    from autosound_tcc.ui.tcc import workers

    _app()
    asked: list = []
    _agy_reading(monkeypatch, asked)
    worker = workers._ContractWorker(tmp_path, skip_rew=True, agy_sign_in=False)

    worker.start()
    assert worker.wait(10_000)

    assert asked == []


def test_a_check_cancelled_at_close_does_not_go_on_to_ask_agy(monkeypatch, tmp_path):
    """`stop_workers` cancels the check and waits three seconds: the agy reading after a cancel
    would be a child of up to 15 s that the window then has to let go of running."""
    from autosound_tcc.core import contract_check
    from autosound_tcc.ui.tcc import workers

    _app()
    asked: list = []
    _agy_reading(monkeypatch, asked)
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(contract_check, "run",
                        lambda *a, **k: (entered.set(), release.wait(10), _report())[-1])
    worker = workers._ContractWorker(tmp_path)
    worker.start()
    assert entered.wait(10)

    worker.cancel()
    release.set()
    assert worker.wait(10_000)

    assert asked == []


class _AgyChild:
    """The agy reading's child as the worker sees it: alive until killed."""

    def __init__(self) -> None:
        self.killed = threading.Event()

    def poll(self):
        return -9 if self.killed.is_set() else None

    def kill(self) -> None:
        self.killed.set()


def test_the_report_goes_out_before_agys_reading_and_the_reading_on_its_own_signal(
        monkeypatch, tmp_path):
    """Final review M2: the REW dot, the strip and the panel of the launch check and of every
    Re-check waited for the agy reading — a Python child, under a second usually, up to 15 s. The
    report goes first; the reading follows, and says so on a signal of its own."""
    from PySide6.QtCore import Qt

    from autosound_tcc.core import contract_check, critic, model_choices
    from autosound_tcc.ui.tcc import workers

    _app()
    reading, release = threading.Event(), threading.Event()
    monkeypatch.setattr(contract_check, "run", lambda *a, **k: _report())
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")
    monkeypatch.setattr(critic, "agy_sign_in", lambda project_dir=None, register=None: (
        reading.set(), release.wait(10), ("adc", "ADC (Google Cloud), /x/adc.json"))[-1])
    reported, read = threading.Event(), threading.Event()
    worker = workers._ContractWorker(tmp_path)
    worker.result.connect(lambda _report: reported.set(), Qt.ConnectionType.DirectConnection)
    worker.start()
    try:
        assert reading.wait(10)
        assert reported.wait(5), "the report waited for agy's reading"
        worker.signInRead.connect(read.set, Qt.ConnectionType.DirectConnection)
        assert not read.is_set()
    finally:
        release.set()
        assert worker.wait(10_000)

    assert read.is_set(), "the reading came back and nothing said so"
    from autosound_tcc.core import self_check

    assert self_check._AGY_SIGN_IN["found"] == ("adc", "ADC (Google Cloud), /x/adc.json")


def test_a_close_during_agys_reading_ends_its_child(monkeypatch, tmp_path):
    """Final review M2 (a): the reading's child was not the worker's to end, so `cancel()` killed
    only the contract child. A close during the reading waited out `stop_or_detach`'s 3 s, let the
    thread go, and the exit waited for it again."""
    from autosound_tcc.core import contract_check, critic, model_choices
    from autosound_tcc.ui.tcc import workers

    _app()
    child, reading = _AgyChild(), threading.Event()

    def agy_sign_in(project_dir=None, register=None):
        if register is not None:
            register(child)
        reading.set()
        child.killed.wait(10)
        return None

    monkeypatch.setattr(contract_check, "run", lambda *a, **k: _report())
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")
    monkeypatch.setattr(critic, "agy_sign_in", agy_sign_in)
    worker = workers._ContractWorker(tmp_path)
    worker.start()
    try:
        assert reading.wait(10)
        worker.cancel()

        assert child.killed.is_set(), "the close left agy's reading running"
        assert worker.wait(5000)
    finally:
        child.kill()
        worker.wait(10_000)


def test_a_close_just_before_agys_child_exists_still_ends_it(monkeypatch, tmp_path):
    """The other order: the close lands after the worker decided to read and before the child is
    handed over, when `cancel()` finds no child to kill. Handed over late, it is ended at once."""
    from autosound_tcc.core import contract_check, critic, model_choices
    from autosound_tcc.ui.tcc import workers

    _app()
    child, entered, go = _AgyChild(), threading.Event(), threading.Event()

    def agy_sign_in(project_dir=None, register=None):
        entered.set()
        go.wait(10)
        if register is not None:
            register(child)
        child.killed.wait(10)
        return None

    monkeypatch.setattr(contract_check, "run", lambda *a, **k: _report())
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: harness == "agy")
    monkeypatch.setattr(critic, "agy_sign_in", agy_sign_in)
    worker = workers._ContractWorker(tmp_path)
    worker.start()
    try:
        assert entered.wait(10)
        worker.cancel()
        go.set()

        assert worker.wait(5000), "the child handed over after the close was left to run"
        assert child.killed.is_set()
    finally:
        go.set()
        child.kill()
        worker.wait(10_000)


# ---- which copy of the method the project runs (#169, G5 S1) ----------------------------------


@pytest.fixture
def project(own_copy_is_the_submodule):
    """This test's project — conftest's `AUTOSOUND_PROJECT_DIR`, which the self-check reads — with
    TCC's own copy the vendored one."""
    return config.project_dir()


def _check_rows(dialog, check_id: str) -> list:
    from autosound_tcc.ui.tcc.diagnostics_panel import _CheckRow

    return [row for row in dialog.findChildren(_CheckRow) if row.check.id == check_id]


def _method_rows(dialog) -> list:
    return _check_rows(dialog, "method")


def _said(widget) -> str:
    return "\n".join(label.text() for label in widget.findChildren(QLabel))


def _buttons(row) -> list:
    return [button.text() for button in row.findChildren(QPushButton)]


def _press(row, label: str) -> None:
    next(button for button in row.findChildren(QPushButton) if button.text() == label).click()


def _deliver(dialog, report) -> None:
    """A report as the window delivers one: the check's `result`, then agy's reading, which follows
    every check the window runs (`workers._ContractWorker`), and its redraw (`signInRead` →
    `own_checks_changed`)."""
    dialog.set_report(report)
    dialog.own_checks_changed()


def _as_the_window_checks(project):
    """The panel on the report the window gets for `project` from `contract_check.run` — which,
    for a copy TCC refuses, starts nothing and answers the binding's sentence as its error — and
    the window's Re-check: «Checking…», then a report comes back (hand-built; the project's files
    are not these tests' business), delivered as the window delivers it. Answers the dialog and the
    list of times it asked."""
    _app()
    dialog = DiagnosticsDialog()
    asked: list = []
    dialog.refreshRequested.connect(
        lambda: (asked.append(1), dialog.set_report(None), _deliver(dialog, _report())))
    report = contract_check.run(project)
    assert not report.available, "a refused copy: the check could not run"
    _deliver(dialog, report)
    return dialog, asked


def test_a_project_on_tccs_own_copy_shows_no_method_row(project):
    vendor_loader.link_skill_into(project)
    _app()
    dialog = DiagnosticsDialog()

    dialog.set_report(_report())

    assert _method_rows(dialog) == []


@pytest.mark.parametrize("bound, how", [("known", "selfMethodKnown"),
                                        ("approved", "selfMethodApproved")])
def test_a_trusted_copy_that_is_not_tccs_own_is_named_with_no_button(project, other_copy, bound,
                                                                     how):
    """Decision 1: what TCC reads itself stays on its own copy, so the Arbiter has to be able to
    see that the project runs another."""
    if bound == "known":
        linked(Path.home(), other_copy)  # the personal install TCC finds
        linked(project, other_copy)
    else:
        linked_and_approved(project, other_copy)
    binding = method_binding.for_project(project)
    assert binding.state == bound, binding.reason
    _app()
    dialog = DiagnosticsDialog()

    dialog.set_report(_report())

    [row] = _method_rows(dialog)
    assert i18n.t("selfMethodOtherTitle").format(path=binding.skill_dir) in _said(row)
    assert i18n.t(how) in _said(row)
    assert _buttons(row) == []


def test_a_refused_copy_is_shown_with_both_fixes_though_the_check_could_not_run(project,
                                                                              other_copy):
    """For a copy TCC refuses, the project's check is the binding's sentence and nothing more
    (`contract_check.run`), and the panel stopped there: TCC's own section was drawn only under a
    check that ran, so the row with the two fixes would never have been seen."""
    link = linked(project, other_copy)
    binding = method_binding.for_project(project)

    dialog, asked = _as_the_window_checks(project)

    assert i18n.t("diagUnavailable") in dialog._verdict.text()
    [row] = _method_rows(dialog)
    assert binding.reason in _said(row)
    assert _buttons(row) == [i18n.t("selfMethodApprove"), i18n.t("selfMethodRelink")]
    assert asked == [] and config.approved_methods() == () and same_path(link, other_copy), \
        "shown, and nothing pressed"


def test_a_refused_folder_is_offered_no_approval(project):
    entry(project).mkdir(parents=True)

    dialog, _asked = _as_the_window_checks(project)

    [row] = _method_rows(dialog)
    assert _buttons(row) == [i18n.t("selfMethodRelink")]


def test_approve_approves_the_copy_and_the_row_then_says_so(project, other_copy, monkeypatch):
    linked(project, other_copy)
    shown = method_binding.for_project(project)
    approved: list = []
    real = method_binding.approve
    monkeypatch.setattr(method_binding, "approve",
                        lambda binding: approved.append(binding) or real(binding))
    dialog, asked = _as_the_window_checks(project)

    _press(_method_rows(dialog)[0], i18n.t("selfMethodApprove"))

    copy = os.path.realpath(other_copy)
    assert approved == [shown] and config.approved_methods() == (copy,)
    assert asked == [1], "the check is asked again: the report on screen was the refusal"
    [row] = _method_rows(dialog)
    assert i18n.t("selfMethodApproved") in _said(row) and _buttons(row) == []
    receipt = i18n.t("diagFixDone").format(what=i18n.t("selfMethodApproveDone").format(path=copy))
    assert receipt in dialog._verdict.text()
    assert i18n.t("diagUnavailable") not in dialog._verdict.text(), "the refusal is not said again"


def test_re_link_moves_the_old_entry_aside_and_the_row_goes(project, other_copy):
    link = linked(project, other_copy)
    dialog, asked = _as_the_window_checks(project)

    _press(_method_rows(dialog)[0], i18n.t("selfMethodRelink"))

    aside = project / ".tcc" / "method-aside"
    [stamp] = os.listdir(aside)
    assert same_path(aside / stamp / vendor_loader.SKILL_NAME, other_copy), "kept, not deleted"
    assert same_path(link, vendor_loader.skill_dir())
    assert _method_rows(dialog) == []
    assert asked == [1]
    assert str(aside) in dialog._verdict.text(), "the receipt says where the old entry went"


def _recording(real, raised: list):
    def call(binding):
        try:
            return real(binding)
        except method_binding.MethodRefused as exc:
            raised.append(str(exc))
            raise
    return call


@pytest.mark.parametrize("fix", ["approve", "relink"])
def test_a_fix_that_fails_says_why_on_its_row_and_the_row_stays(project, other_copy, monkeypatch,
                                                               fix):
    """`MethodRefused` carries one sentence naming the entry and what to do, and that sentence is
    the row's to say — not «Fixed:» over it, and not a redraw that drops it: a re-link that moved
    the entry and could make no link leaves the project reading `same`, and a redrawn panel would
    show no method row at all, with no word of where the entry went."""
    linked(project, other_copy)
    dialog, asked = _as_the_window_checks(project)
    [row] = _method_rows(dialog)
    verdict = dialog._verdict.text()
    if fix == "approve":
        monkeypatch.setattr(config, "_settings_provider", None)  # a store that keeps nothing
    else:
        monkeypatch.setattr(vendor_loader, "link_skill_into", lambda project_dir: None)
    raised: list = []
    monkeypatch.setattr(method_binding, fix, _recording(getattr(method_binding, fix), raised))

    _press(row, i18n.t({"approve": "selfMethodApprove", "relink": "selfMethodRelink"}[fix]))

    [sentence] = raised
    assert _method_rows(dialog) == [row], "the row stays"
    assert i18n.t("selfActionFailed").format(why=sentence) in _said(row)
    assert all(button.isEnabled() for button in row.findChildren(QPushButton))
    assert (asked, dialog._verdict.text()) == ([], verdict), "no receipt, no re-check"


def test_a_receipt_stays_through_its_reports_redraws_until_a_newer_report_or_a_re_check(
        tmp_path, monkeypatch):
    """Fix round 1 of #169's row, I1. The receipt was said once and dropped, and the window draws
    every report it delivers again — agy's reading follows each check — so it was gone before
    anyone read it. It stays with the report it was said with, through every redraw of that one
    (the reading, the window handing the same report back as the panel opens again), and goes
    with a newer report, a Re-check, or the next fix."""
    from autosound_tcc.core import model_choices, model_overrides

    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(model_choices, "_CLI_CACHE", {})
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: False)
    receipt = i18n.t("diagFixDone").format(what=i18n.t("selfAliasFixed").format(n=1))
    _app()
    dialog = DiagnosticsDialog()

    def fixed_over(shown):
        model_overrides.set_alias("agy:gemini-3.1-pro-high", "sdk:claude-opus-5", "gone")
        _deliver(dialog, shown)
        _press(_check_rows(dialog, "aliases")[0], i18n.t("selfAliasFix"))

    shown = _report()
    fixed_over(shown)
    dialog.own_checks_changed()  # agy's reading
    dialog.set_report(shown)  # the same report, handed back as the panel is opened again
    assert receipt in dialog._verdict.text(), "through every redraw of its report"

    _deliver(dialog, _report())
    assert receipt not in dialog._verdict.text(), "a newer report says its own verdict"

    shown = _report()
    fixed_over(shown)
    assert receipt in dialog._verdict.text()
    dialog._refresh_btn.click()
    dialog.set_report(shown)  # the same report again: only the Re-check can have ended it
    assert receipt not in dialog._verdict.text(), "a Re-check ends it"


def test_a_fix_pressed_while_a_check_runs_lands_its_receipt_on_the_check_after_it(project,
                                                                                  other_copy,
                                                                                  monkeypatch):
    """I1's second half. The window shows its last report while a check runs, and a Re-check
    asked for meanwhile waits for that check (`main_window._open_diagnostics`,
    `_start_contract_check`). Its report comes first, begun before the fix — the old state, here
    the refusal — and the receipt is not spent on it: it lands on the report of the check after.

    On a clock that does not move from the running check's start to the press (N1): CPython 3.12's
    `time.monotonic()` on Windows moves in 15.625 ms steps, and the two used to tie there."""
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    linked(project, other_copy)
    _app()
    dialog = DiagnosticsDialog()
    asked: list = []
    dialog.refreshRequested.connect(lambda: asked.append(1))  # one runs: the window queues it
    _deliver(dialog, contract_check.run(project))  # the last report, shown as the panel opens
    running = contract_check.run(project)  # the check running as the fix is pressed
    copy = os.path.realpath(other_copy)
    receipt = i18n.t("diagFixDone").format(what=i18n.t("selfMethodApproveDone").format(path=copy))

    _press(_method_rows(dialog)[0], i18n.t("selfMethodApprove"))
    dialog.set_report(running)

    assert asked == [1]
    assert receipt not in dialog._verdict.text(), "not on a check begun before the fix"
    assert i18n.t("diagUnavailable") in dialog._verdict.text(), "that one is the old refusal"
    dialog.own_checks_changed()
    assert receipt not in dialog._verdict.text()

    dialog.set_report(None)  # the queued check starts
    _deliver(dialog, _report())

    assert receipt in dialog._verdict.text()
    [row] = _method_rows(dialog)
    assert i18n.t("selfMethodApproved") in _said(row)


def test_a_fix_button_is_never_the_dialogs_default(project, other_copy):
    """Ruling R-aq: a QPushButton in a QDialog is auto-default, so Enter presses the one that has
    focus — and a press disables its button, which hands focus to the one beside it. Approve and
    re-link decide which copy of the method TCC runs: a deliberate press, never a stray Enter."""
    from PySide6.QtCore import Qt

    link = linked(project, other_copy)
    dialog, asked = _as_the_window_checks(project)
    [row] = _method_rows(dialog)
    buttons = row.findChildren(QPushButton)

    for button in buttons:
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            QTest.keyClick(button, key)

    assert config.approved_methods() == () and same_path(link, other_copy), "Enter pressed nothing"
    assert asked == []
    assert [(b.autoDefault(), b.isDefault()) for b in buttons] == [(False, False)] * 2
