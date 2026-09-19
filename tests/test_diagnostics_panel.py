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

    assert dialog._tabs.count() == 4
    assert dialog._tabs.tabText(0) == i18n.t("diagTabProject")
    assert dialog._tabs.tabText(1) == i18n.t("diagTabInstall")
    assert dialog._tabs.tabText(2) == i18n.t("diagTabLog")
    assert dialog._tabs.tabText(3) == i18n.t("diagTabSessions")


def test_the_report_is_read_only_when_the_tab_is_opened():
    """Eight `--version` subprocesses is not something to pay for opening a dialog about a contract
    check."""
    _app()
    dialog = DiagnosticsDialog()

    assert dialog._install_read is False

    started = time.monotonic()
    dialog._tabs.setCurrentIndex(1)

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


def test_updating_the_method_reports_the_version_it_landed_on(monkeypatch):
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("skill", "3.0.6", "3.0.7", True))
    monkeypatch.setattr(updates, "apply_skill", lambda tag="": (True, "v3.0.7", ""))

    dialog._update_skill()

    assert "3.0.7" in dialog._update_rows["skill"][0].text()


def test_a_failed_update_says_why_and_leaves_the_button(monkeypatch):
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("skill", "3.0.6", "3.0.7", True))
    monkeypatch.setattr(updates, "apply_skill", lambda tag="": (False, "git_failed", "no network"))

    dialog._update_skill()

    label, button = dialog._update_rows["skill"]
    assert "no network" in label.text(), "git's own words survive; the framing is translated"
    assert i18n.t("updWhy_git_failed") in label.text()
    assert button.isEnabled(), "a failure the person can retry must leave them the button"


def test_updating_tcc_is_handed_to_a_terminal(monkeypatch):
    """TCC cannot replace its own running files -- on Windows not at all -- so it does not try."""
    from autosound_tcc.core import terminal_launcher, updates

    _app()
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("tcc", "0.1.1", "0.9.9", True))
    seen = []
    monkeypatch.setattr(terminal_launcher, "run_line", lambda line: seen.append(line))
    monkeypatch.setattr(updates, "newest_tcc_tag", lambda channel="stable": "v0.9.9")

    dialog._update_tcc()

    assert len(seen) == 1
    # Pinned to the release the row offered, not to whatever `main` holds by then (F-024).
    assert "autosound-tcc[gui,claude] @ git+" in seen[0]
    assert "@v0.9.9" in seen[0]
    assert "--python 3.12" in seen[0]
    assert str(os.getpid()) in seen[0], "the window waits for THIS process before it replaces it"
    assert dialog._update_rows["tcc"][0].text() == i18n.t("updTccHanded")


def test_re_check_asks_about_updates_again(monkeypatch):
    """The button says Re-check, and the update rows are what a person presses it to see move —
    after installing one, or after the network came back."""
    from autosound_tcc.core import updates

    _app()
    dialog = DiagnosticsDialog()
    dialog._tabs.setCurrentIndex(1)
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
    dialog._tabs.setCurrentIndex(0)
    dialog._install_read = True

    dialog._on_refresh()

    assert dialog._install_read is False, "but it is marked stale, so opening it re-reads"


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

    assert "Autosound TCC" in dialog._report_text()


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


def test_updating_tcc_on_beta_pins_the_candidate(monkeypatch):
    from autosound_tcc.core import config, terminal_launcher, updates

    _app()
    config.set_update_channel("beta")
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("tcc", "0.1.38", "0.2.0-rc2", True))
    seen = []
    monkeypatch.setattr(terminal_launcher, "run_line", lambda line: seen.append(line))
    monkeypatch.setattr(updates, "newest_tcc_tag",
                        lambda channel="stable": "beta-v0.2.0-rc2" if channel == "beta" else "v0.1.39")

    dialog._update_tcc()

    assert "@beta-v0.2.0-rc2" in seen[0]


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

    dialog._tabs.setCurrentIndex(3)

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
    dialog._tabs.setCurrentIndex(3)

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
    dialog._tabs.setCurrentIndex(3)
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

    dialog._tabs.setCurrentIndex(3)

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
