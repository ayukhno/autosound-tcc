"""The suite must not be able to read this machine.

`conftest.py` states the rule for `cli_available` and patches it; these tests are the same claim,
checked rather than assumed. Written after the first CI runs (2026-09-07) found two tests that
passed on the author's laptop and failed everywhere else — the rule was right and the guard had a
second door nobody had noticed.
"""
import threading
from pathlib import Path

import pytest

from autosound_tcc.core import model_choices


def test_the_suite_cannot_see_which_clis_this_machine_has():
    assert model_choices.cli_available("agy") is False


def test_the_suite_cannot_see_whether_a_critic_is_reachable():
    """`critic_reaches` asks `os.environ` and `shutil.which` directly, so patching
    `cli_available` never covers it. That gap is what made
    `test_no_row_repeats_what_the_row_already_says` green on a machine with `agy` installed and
    red on both CI platforms."""
    choice = model_choices.Choice(
        harness="agy",
        model="gemini-3.1-pro-high",
        label="Gemini 3.1 Pro (High)",
        provider="google",
    )
    assert model_choices.critic_reaches(choice) is False


def test_the_suite_cannot_read_this_machines_reviewer_key(monkeypatch, real_critic_reaches):
    """A third door onto the same machine, opened the day `critic_reaches` learned to look in
    `~/.config/autosound/critic-env` (SKL-024): a developer with a real key there would get a
    reachable critic and CI would not, which is the 2026-09-07 failure again wearing a new coat.
    `real_critic_reaches` deliberately un-stubs the function — so if the isolation is missing,
    this test reads the actual laptop and says so."""
    from autosound_tcc.core import critic_env

    # Both cleared FIRST, and that is the fix rather than a tidy-up. A developer's laptop has
    # neither set, so the assertion below passed here and failed on every CI runner: GitHub sets
    # `XDG_CONFIG_HOME` on Linux and `APPDATA` on Windows, and either one takes the resolution
    # away from HOME before the isolation can be observed. The property being tested is "HOME
    # still decides"; a test of it has to be the one deciding what else is in the environment.
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    # What isolates this is `conftest`'s tmp HOME, and that only works while the path is resolved
    # through `~` on every call. Hard-code it, or cache it at import time, and the suite silently
    # starts reading the developer's own key again. `Path.home()` is already the tmp one here,
    # which is the isolation working.
    assert Path.home() in critic_env.machine_config_path().parents

    other = Path.home().parent / "somewhere-else"
    monkeypatch.setenv("HOME", str(other))
    monkeypatch.setenv("USERPROFILE", str(other))  # what `~` follows on Windows

    assert critic_env.machine_config_path() == other / ".config" / "autosound" / "critic-env"


def test_no_test_can_leave_a_console_keeper_running():
    """A keeper is a daemon thread with a twelve-hour budget, and on a Windows runner the pid it
    watches is pytest's own — alive until the very end. Two tests reached one without meaning to
    and left two such threads for the whole run: they sit in every crash dump of 2026-09-11 (run
    34639559016, three crashes in a row, where one in three was usual).

    `conftest` hands every test a spawn that starts nothing; this checks it is still there.
    """
    from autosound_tcc.core import child

    ran = threading.Event()
    child._spawn_daemon(lambda **_kw: ran.set(), {})

    assert not ran.wait(0.2), "a real thread started — the keeper stub in conftest is gone"


def test_the_suite_cannot_run_this_machines_claude(monkeypatch):
    """A window's catalogue worker asks `claude auth status`, and on a machine with Claude Code that
    was the real CLI. With HOME in `tmp_path` it wrote `.claude.json` there, the window's project
    watcher took that for a change to the project, and the reload emptied the capture card in the
    middle of `test_the_right_column_scrolls_when_the_capture_list_is_long` — 2 of 15 parallel
    runs, 2026-09-14. A CI runner has no `claude`, which is why CI never saw it."""
    import subprocess

    from autosound_tcc.core import claude_sdk

    spawned: list = []
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(claude_sdk.subprocess, "run",
                        lambda *a, **k: spawned.append(a) or subprocess.CompletedProcess(a, 1, "", ""))
    monkeypatch.setattr(claude_sdk.child, "run_bounded",
                        lambda *a, **k: spawned.append(a) or subprocess.CompletedProcess(a, 1, "", ""))

    claude_sdk.probe_signed_in(force=True)

    assert not spawned, "the real `claude` was asked — the stub in conftest is gone"


def test_what_the_app_writes_for_the_machine_is_not_in_the_tests_own_folder(tmp_path):
    """Tests use `tmp_path` as a project folder, and a window watches its project folder. With the
    app's settings and caches in that same folder, a window saw its own writes as a change to the
    project and rebuilt the DSP tree 400 ms later, in the middle of whatever the test was holding
    (tcc#28: one Windows run in ten from 2026-09-11, when APPDATA moved into `tmp_path`; on macOS a
    `cli-catalogue.json` written by the catalogue worker did the same, only after the test ended).

    HOME stays in `tmp_path`: tests read `~/.claude` through it, and a window writes nothing there.
    """
    import os

    from autosound_tcc.ui.tcc.app_settings import get_settings

    written_for_the_machine = {
        "QSettings": get_settings().fileName(),
        "LOCALAPPDATA": os.environ["LOCALAPPDATA"],
        "APPDATA": os.environ["APPDATA"],
        "XDG_CONFIG_HOME": os.environ["XDG_CONFIG_HOME"],
        "XDG_STATE_HOME": os.environ["XDG_STATE_HOME"],
        "AUTOSOUND_TCC_CONFIG_DIR": os.environ["AUTOSOUND_TCC_CONFIG_DIR"],
    }

    inside = {name: path for name, path in written_for_the_machine.items()
              if tmp_path.resolve() in Path(path).resolve().parents}
    assert not inside, f"written into the test's own folder: {inside}"


def test_a_modal_a_test_reaches_fails_the_test_at_its_end_instead_of_waiting(
        _no_modal_waits_for_nobody):
    """A real modal in a test waits for a person who is not there: a plain `-n 4` run sat in
    the «model gone» box for 24 minutes (2026-09-30), and CI's Windows shard hit its 25-minute
    limit in the same stretch. The guard in conftest makes the modal fail the test by name.

    Not by raising where the modal opens (tcc#123, W-4 review): that is inside the window's code,
    and a `try` there that catches broadly took the guard's error for its own and went on -- the
    test passed. The modal answers «nobody chose», as Escape would, and is written down; the
    test fails when it is over, naming each modal it reached."""
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    QApplication.instance() or QApplication([])
    log = _no_modal_waits_for_nobody
    box = QMessageBox()
    box.setWindowTitle("Model gone")
    box.setText("This project is set to a model nothing here can run")

    assert box.exec() == 0 and box.clickedButton() is None
    assert QDialog().exec() == 0
    assert QMessageBox.question(None, "Switch?", "Open the other folder?") \
        == QMessageBox.StandardButton.NoButton

    # By its text: the title is a no-op on macOS, where a message box has none.
    assert "a model nothing" in log.opened[0] and log.opened[0].startswith("QMessageBox ")
    assert log.opened[1].startswith("QDialog ")
    assert log.opened[2].startswith("QMessageBox.question ")
    with pytest.raises(pytest.fail.Exception, match="a test opened a modal: QMessageBox .*"
                                                    "a model nothing.*QDialog.*QMessageBox.question"):
        log.verdict()
    assert log.opened == [], "said once; this test's own end has nothing left to fail on"


def test_a_question_asked_again_after_cancel_ends_the_test_instead_of_spinning(
        _no_modal_waits_for_nobody):
    """Cancel lets the code go on, and code that asks again after a cancel would ask forever --
    the old raise broke out of that (review of tcc#123). After `_MODAL_CAP` modals in one test
    the guard fails the test where it stands, past a broad `except Exception` too."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    from tests.conftest import _MODAL_CAP

    QApplication.instance() or QApplication([])
    asked = 0
    with pytest.raises(pytest.fail.Exception, match=f"{_MODAL_CAP} modals in one test"):
        while True:
            try:
                QMessageBox.question(None, "Again?", "Open the other folder?")
            except Exception:  # noqa: BLE001 — what a window's own code might do
                pass
            asked += 1
    assert asked == _MODAL_CAP
    assert _no_modal_waits_for_nobody.opened == [], "said once; the test's end has nothing left"


def test_every_dialog_static_answers_cancel_and_is_written_down(_no_modal_waits_for_nobody):
    """A dialog's static -- `QFileDialog.getExistingDirectory`, `QInputDialog.getText` -- is a
    modal of its own: its `exec` is C++'s, the guard's `QDialog.exec` never sees it, and a test
    that reached one waited like the «model gone» box did. Each answers what Cancel answers and
    is written down like any modal. `QInputDialog.getInt` and `QFileDialog.getSaveFileName` are
    cancelled quietly by `_isolated_machine_config`: tests walk through those questions."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (QApplication, QColorDialog, QFileDialog, QFontDialog,
                                   QInputDialog, QMessageBox)

    QApplication.instance() or QApplication([])
    log = _no_modal_waits_for_nobody
    asked = {
        "QFileDialog.getOpenFileName": (QFileDialog.getOpenFileName(None, "Pick"), ("", "")),
        "QFileDialog.getOpenFileNames": (QFileDialog.getOpenFileNames(None, "Pick"), ([], "")),
        "QFileDialog.getExistingDirectory": (QFileDialog.getExistingDirectory(None, "Pick"), ""),
        "QFileDialog.getOpenFileUrl": (QFileDialog.getOpenFileUrl(None, "Pick"), (QUrl(), "")),
        "QFileDialog.getOpenFileUrls": (QFileDialog.getOpenFileUrls(None, "Pick"), ([], "")),
        "QFileDialog.getSaveFileUrl": (QFileDialog.getSaveFileUrl(None, "Pick"), (QUrl(), "")),
        "QFileDialog.getExistingDirectoryUrl": (QFileDialog.getExistingDirectoryUrl(None, "Pick"),
                                                QUrl()),
        "QInputDialog.getText": (QInputDialog.getText(None, "Step", "Name"), ("", False)),
        "QInputDialog.getMultiLineText": (QInputDialog.getMultiLineText(None, "Note", "Text"),
                                          ("", False)),
        "QInputDialog.getItem": (QInputDialog.getItem(None, "Pick", "One", ["a", "b"]),
                                 ("", False)),
        "QInputDialog.getDouble": (QInputDialog.getDouble(None, "Level", "dB"), (0.0, False)),
        "QMessageBox.about": (QMessageBox.about(None, "About", "TCC"), None),
        "QMessageBox.aboutQt": (QMessageBox.aboutQt(None), None),
    }
    colour = QColorDialog.getColor()
    ok, _font = QFontDialog.getFont()

    for name, (got, cancel) in asked.items():
        assert got == cancel, name
    assert not colour.isValid() and colour == QColor() and ok is False
    assert [entry.split()[0] for entry in log.opened] == [
        *asked, "QColorDialog.getColor", "QFontDialog.getFont"]
    log.opened.clear()


def test_a_finished_test_s_panes_leave_the_language_switch():
    """F-065: every `MainWindow` switches to its saved language as it is built, and a switch
    called every pane the run had made so far -- in one process the cost of a window grew with
    its place in the run. What a test registered is dropped when it ends; what was there before
    it stays, and the language still reaches it."""
    import weakref

    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc.detail_pane import DetailPane
    from tests import _windows

    QApplication.instance() or QApplication([])
    earlier = DetailPane()  # stands for what a module fixture, or an import, registered
    before = _windows.language_listeners()
    finished = DetailPane()  # stands for what the test itself made

    def owners():
        return [entry().__self__ for entry in i18n._listeners
                if isinstance(entry, weakref.WeakMethod) and entry() is not None]

    assert earlier in owners() and finished in owners()
    _windows.drop_language_listeners_since(before)
    assert earlier in owners() and finished not in owners()
    english = finished._tab_table.text()
    i18n.set_language("uk")
    try:
        assert earlier._tab_table.text() == i18n.t("tabTable") != english, "it still follows"
        assert finished._tab_table.text() == english, "a finished test's pane keeps its words"
    finally:
        i18n.set_language("en")


def test_a_test_starts_on_a_frozen_heap_and_its_own_cycles_are_still_collected():
    """F-065: a full collection between tests walked every Python object the run's earlier
    windows still hold -- 437 s of a 2730-s serial run. `_collect_qt_leftovers` freezes what is
    alive when a test starts, so a collection walks only what the test made since; a cycle the
    test drops is collected all the same."""
    import gc
    import weakref

    assert gc.get_freeze_count() > 0, "what was alive before this test is out of the collection"

    class _Cycle:
        pass

    dropped = _Cycle()
    dropped.itself = dropped
    gone = weakref.ref(dropped)
    del dropped
    gc.collect()
    assert gone() is None, "a cycle made and dropped in the test is collected"


def test_the_suite_cannot_reach_this_machines_rew_through_the_capture_check():
    """A second door onto REW, opened by tcc#21: the method's `verify.py` talks to REW through its
    OWN bare `rew_api` (it puts `rew_tool/` on `sys.path` and imports it by name), not the namespaced
    one `conftest._no_live_rew` re-points. With a REW live on this Mac — the normal state while
    somebody tunes — a test reaching the real verdict would pull curves out of it."""
    from autosound_tcc.core import vendor_loader

    if not vendor_loader.is_available():
        pytest.skip("the vendored skill is not checked out")

    assert vendor_loader.load_verify()._api.BASE_URL == "http://127.0.0.1:1"


def test_a_finished_test_s_window_leaves_no_worker_running():
    """tcc#140's flaky reviewer tests, traced (fix round 2 of tcc#21): a window's catalogue read was
    still running when its test's patches came off, and in the NEXT test's setup it read the
    developer's own `~/.config/autosound-tcc/cli-catalogue.json` — every agy model in it then read
    "not checked" for the rest of that xdist worker. A window a test leaves behind stops its
    threads as a closing window does (`stop_workers`), while the test's patches are still on: a
    running read is asked to stop and its answer cut, so nothing of it reaches a later test."""
    from PySide6.QtCore import QThread, Signal
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc import qt_shutdown
    from autosound_tcc.ui.tcc.main_window import MainWindow
    from tests import _windows

    class _Read(QThread):
        done = Signal()

        def run(self) -> None:
            while not self.isInterruptionRequested():
                self.msleep(5)

    QApplication.instance() or QApplication([])
    window = MainWindow()
    read = qt_shutdown.watch(_Read())
    previous, window._cli_catalogue = window._cli_catalogue, read
    qt_shutdown.stop_or_detach(previous, 5000, mute=(previous.done,) if previous else ())
    read.start()
    try:
        _windows.quiet(window)

        assert read.wait(0) and not read.isRunning(), "the read did not outlive its test"
    finally:
        read.requestInterruption()
        read.wait(5000)
