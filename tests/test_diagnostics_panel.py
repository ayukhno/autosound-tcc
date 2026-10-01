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


def _skill_offered(monkeypatch, changed=(), done=None):
    """A dialog whose skill row offers 3.0.7, a clone with `changed`, and `apply_skill` recorded."""
    from autosound_tcc.core import updates

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
    return dialog, asked


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


def test_updating_tcc_on_beta_pins_the_candidate(monkeypatch, tmp_path):
    import tempfile

    from autosound_tcc.core import config, terminal_launcher, updates

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))  # the script lands here, not in /tmp
    _app()
    config.set_update_channel("beta")
    dialog = DiagnosticsDialog()
    dialog._show_update(updates.Status("tcc", "0.1.38", "0.2.0-rc2", True))
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
    dialog._tabs.setCurrentIndex(1)
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

    dialog._tabs.setCurrentIndex(1)

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
    dialog._tabs.setCurrentIndex(1)
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
    dialog._tabs.setCurrentIndex(1)
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
