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


#: Taken at import, before any test's `monkeypatch` could stand a fresh one in its place.
_UNCONFIRMED_AT_IMPORT = model_choices._UNCONFIRMED


def test_no_test_inherits_which_models_are_unconfirmed():
    """Final review M3: `_UNCONFIRMED` — models read from a cached catalogue and not confirmed since
    — was the carrier of the #140 flake, and the one piece of the catalogue's state every test in a
    worker still shared: what one test's reading left there read «not checked» in the next test's
    pickers. Each test gets its own, empty, as with `_CLI_CACHE`."""
    assert model_choices._UNCONFIRMED is not _UNCONFIRMED_AT_IMPORT
    assert model_choices._UNCONFIRMED == set()


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


def test_the_suite_cannot_reach_github_through_the_methods_repository(monkeypatch):
    """#172: the new-project dialog previews a copy with the method's real `seed()`, whose last act
    is `project_repo.init` -- and where git has no identity, as in most tests (HOME is the test's
    own folder), that starts `gh api user` to find one, which goes to GitHub with any token it
    finds. The method's own switch, `AUTOSOUND_NO_GH=1`, is set for the whole session in
    `conftest`. Checked with a `gh` that is there and a child that only says it was asked, so a
    missing switch shows as a child started, not as nothing on a machine without `gh`."""
    import importlib
    import subprocess

    from autosound_tcc.core import vendor_loader

    if not vendor_loader.is_available():
        pytest.skip("the vendored skill is not checked out")
    vendor_loader.load_project_seed()  # puts `rew_tool/` on `sys.path`, where its seed imports from
    repo = importlib.import_module("project_repo")
    assert Path(repo.__file__).resolve().parent == vendor_loader.rew_tool_dir().resolve(), \
        repo.__file__
    asked: list = []
    monkeypatch.setattr(repo.shutil, "which", lambda name, *_a, **_k: f"/usr/bin/{name}")
    monkeypatch.setattr(repo.subprocess, "run", lambda argv, **_kw: asked.append(argv)
                        or subprocess.CompletedProcess(argv, 0, "", ""))

    assert repo.gh_state() == "absent"
    assert asked == [], "the method started `gh` -- the switch in conftest is gone"


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


def test_a_window_whose_catalogue_read_never_started_leaves_nothing_held():
    """Re-review of fix round 2 of #21, N1: tests build windows with `AUTOSOUND_TCC_MCP=0`, so a
    window's catalogue read is built and never started. Quieting the window handed it to
    `qt_shutdown` as a thread that might be about to run, and every window a test built left one
    more there for the rest of the session. Only a running worker is stopped."""
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc import qt_shutdown
    from autosound_tcc.ui.tcc.main_window import MainWindow
    from tests import _windows

    QApplication.instance() or QApplication([])
    window = MainWindow()
    read = window._cli_catalogue
    assert read is not None and read not in qt_shutdown.live(), "built, never started"

    _windows.quiet(window)

    assert read not in qt_shutdown.detached()


def test_the_window_quieting_asks_for_the_tests_patches_itself():
    """Re-review of fix round 2 of #21, N2: `quiet()` must run before `monkeypatch` undoes the
    test's patches, so a worker it stops does what it still does under them. That held only
    because an earlier autouse fixture happened to ask for `monkeypatch`; the fixture asks for it
    itself, and the order is its own."""
    import inspect
    import sys

    conftest = sys.modules["tests.conftest"]

    assert "monkeypatch" in inspect.signature(conftest._quiet_windows_left_behind).parameters


def test_a_test_may_set_the_app_log_up_and_leave_it_so(tmp_path, monkeypatch):
    """Item 9 of the G5+G8 fix dispatch, first of a pair: `app_log.setup()` run as
    `test_app_log.py`'s first-run test runs it, and left as that test leaves it — TCC's logger and
    `py.warnings` not propagating, a file handler on each, the log path, its thread hook. The next
    test is the check that none of it reaches past this one (`_app_log_left_as_found`)."""
    from autosound_tcc.core import app_log

    monkeypatch.setattr(app_log, "log_dir", lambda: tmp_path / "logs")

    assert app_log.setup(to_stderr=False) is not None
    assert app_log.logger().propagate is False


def test_the_next_test_starts_with_the_logging_a_fresh_process_has():
    """Second of the pair, and a check only when both run in one process — a serial run, or one
    file's CI shard; split across workers it cannot fail. pytest 9 attaches its log capture to
    every logger that does not propagate, so a TCC logger left so was heard twice by the next test
    that made it propagate for `caplog`: eight tests in the whole-suite run at 5847551."""
    import logging

    from autosound_tcc.core import app_log

    root = logging.getLogger().handlers
    for log in (app_log.logger(), logging.getLogger("py.warnings")):
        assert (log.propagate, log.level) == (True, logging.NOTSET), log.name
        assert [handler for handler in log.handlers if handler not in root] == [], log.name
    assert app_log.log_path() is None
    assert "_install_excepthooks" not in getattr(threading.excepthook, "__qualname__", ""), \
        "app_log's thread hook is still in pytest's place"


def _on_a_thread(target, name: str) -> int:
    """`target` run on a thread of its own, as a worker runs it; back once it has finished, with
    the thread's ident."""
    worker = threading.Thread(target=target, name=name, daemon=True)
    worker.start()
    worker.join(10)
    assert not worker.is_alive(), f"{name} did not finish"
    return worker.ident


def test_an_import_tcc_runs_off_the_main_thread_fails_the_test_at_its_end(
        _no_import_on_a_worker_thread, tmp_path, monkeypatch):
    """#172, §5.1: `install_report.py`'s rule -- every import at the top of its module -- was held
    by reading alone. PySide6's import hook works on every import a program executes, and on a
    worker that contends with the GUI thread (measured 2026-08-19: a report that takes 2.7 s from
    a shell never finished inside the dialog's thread). The guard wraps `builtins.__import__`, so
    an `import` statement TCC's own code runs on any thread but the main one is written down by
    its file and line, and the test fails when it is over.

    Written down, not raised in the worker (R-r): a worker's broad `except` would take a raise for
    its own error and go on, and the test would pass. This worker swallows everything, and still
    does its job as it does in the app."""
    import sys

    from autosound_tcc.core import app_log

    conftest = sys.modules["tests.conftest"]
    # By its path inside the package, wherever `autosound_tcc` was imported from (review M1).
    monkeypatch.delitem(conftest._WORKER_IMPORTS_ALLOWED, ("core/app_log.py", "dump_threads"))
    monkeypatch.setattr(app_log, "_log_path", tmp_path / "tcc.log")
    guard = _no_import_on_a_worker_thread

    app_log.dump_threads("asked on the main thread")
    guard.verdict()  # the main thread imports where it likes

    def watchdog() -> None:  # where the app runs it: the slow-tool watchdog's Timer thread
        try:
            app_log.dump_threads("asked by the watchdog")
        except BaseException:  # noqa: BLE001 — what a worker's own code might do
            pass

    ident = _on_a_thread(watchdog, "tcc-test-watchdog")

    assert "asked by the watchdog" in (tmp_path / "tcc.log").read_text(encoding="utf-8"), \
        "the guard changed nothing the worker does"
    with pytest.raises(pytest.fail.Exception,
                       match=r"(?s)\n  core/app_log\.py:\d+ in dump_threads: "
                             r"import faulthandler -- thread 'tcc-test-watchdog'") as said:
        guard.verdict()
    # The marker goes by ident, and a thread may inherit the ident of one that was alive at the
    # guard's setup and has ended since (`_thread_idents`; glibc reuses them): said exactly when
    # this one's ident was among those. Asserting it absent could flake (Task 23's re-review, N1).
    assert ("started before this test" in str(said.value)) == (ident in guard.older), \
        (ident, str(said.value))
    guard.verdict()  # said once; this test's own end has nothing left to fail on


def test_a_hit_from_a_thread_older_than_the_test_says_so(
        _no_import_on_a_worker_thread, tmp_path, monkeypatch):
    """Review M7: a thread an earlier test left running that imports during this one fails this
    one -- the shape `_an_exception_in_a_qt_slot_fails_the_test` describes for a slot. The guard
    takes the threads alive at its setup, and a hit from one of them says the thread is older than
    the test, so the reader looks at the tests before it too."""
    import sys

    from autosound_tcc.core import app_log

    conftest = sys.modules["tests.conftest"]
    monkeypatch.delitem(conftest._WORKER_IMPORTS_ALLOWED, ("core/app_log.py", "dump_threads"))
    monkeypatch.setattr(app_log, "_log_path", tmp_path / "tcc.log")
    go = threading.Event()

    def left_running() -> None:
        go.wait(10)
        app_log.dump_threads("from a thread older than the test")

    older = threading.Thread(target=left_running, name="tcc-test-older", daemon=True)
    older.start()
    guard = _no_import_on_a_worker_thread
    guard.older = conftest._thread_idents()  # as the next test's setup takes them, this one alive
    go.set()
    older.join(10)

    with pytest.raises(pytest.fail.Exception,
                       match=r"(?s)in dump_threads: import faulthandler -- thread "
                             r"'tcc-test-older', started before this test"):
        guard.verdict()


def test_an_import_c_makes_on_a_thread_with_no_python_frame_is_not_counted(
        _no_import_on_a_worker_thread):
    """Review M4: C code importing on a thread of its own -- a native thread through
    `PyImport_Import` -- has no Python frame under `__import__`, and `sys._getframe(1)` raises
    `ValueError` there. That is C asking for a module, no line anybody could move; the guard took
    the error for its own failure and failed the test.

    `deque(map(guard, names()))` started by `_thread` is that shape: C calls the guard, and the
    generator that hands it the name is off the stack while the guard runs."""
    import _thread
    import collections

    guard = _no_import_on_a_worker_thread
    answered = threading.Event()

    def names():
        yield "json"
        answered.set()  # `map` asks again only once the guard has given the import back

    _thread.start_new_thread(collections.deque, (map(guard, names()), 0))

    assert answered.wait(10), "the native thread never got its import back"
    guard.verdict()


def test_an_import_on_the_allowlist_does_not_fail_the_test(
        _no_import_on_a_worker_thread, tmp_path, monkeypatch):
    """Today's sites are on an allowlist, by file and function, each with where it runs off the
    main thread and why its import is still inside the function. One of them, run where the app
    runs it -- `app_log.dump_threads` on the watchdog's `threading.Timer` -- fails nothing."""
    from autosound_tcc.core import app_log

    monkeypatch.setattr(app_log, "_log_path", tmp_path / "tcc.log")
    watchdog = threading.Timer(0, app_log.dump_threads, args=("a tool is slow",))
    watchdog.start()
    watchdog.join(10)

    assert "a tool is slow" in (tmp_path / "tcc.log").read_text(encoding="utf-8")
    _no_import_on_a_worker_thread.verdict()


def test_what_is_not_an_import_statement_in_tcc_s_own_code_is_not_counted(
        _no_import_on_a_worker_thread, tmp_path):
    """The rule is TCC's, for lines TCC can move. Not counted: a module C code asks for --
    `datetime.strftime` asks for `time` through the same `builtins.__import__` on every call, from
    `critic.write_package` on an MCP call's thread -- and an import in code that is not TCC's: the
    standard library's, a package's, the method's, a test's own."""
    from autosound_tcc.core import critic

    written: list = []

    def foreign() -> None:
        import json  # noqa: F401 — the test's own code, not TCC's

    _on_a_thread(lambda: written.append(critic.write_package("# package", tmp_path)), "tcc-test-call")
    _on_a_thread(foreign, "tcc-test-foreign")

    assert written and written[0].is_file()
    _no_import_on_a_worker_thread.verdict()


def _spin_until(done, seconds: float = 5.0) -> None:
    """The event loop turned, as a test that waits for a timer turns it, until `done()`."""
    import time

    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + seconds
    while not done() and time.monotonic() < deadline:
        QApplication.processEvents()
    assert done(), "the slot never ran"


def test_a_modal_opened_from_a_timer_slot_fails_the_test_though_the_test_answered_it(
        _no_modal_waits_for_nobody, monkeypatch):
    """TA-6, #172: a modal opened from a callback -- a timer's slot, a worker's queued signal -- is
    a nested event loop inside one, the unbounded wait on the GUI thread #172 is about. A test
    that is about a modal answers it by patching its `exec`, so the guard above never saw it.

    The guard counts how deep the main thread is in Qt's dispatch -- `processEvents`,
    `sendPostedEvents`, the event loops' `exec` -- and a modal opened from inside it fails the
    test at its end, answered or not, named with the code that opened it."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    answered: list = []

    def offer_replacement() -> None:  # stands for a window's slot
        box = QMessageBox()
        box.setText("This project is set to a model nothing here can run")
        answered.append(box.exec())

    QTimer.singleShot(0, offer_replacement)
    _spin_until(lambda: answered)

    assert answered == [QMessageBox.StandardButton.Ok], "the test's own answer reached the slot"
    assert _no_modal_waits_for_nobody.opened == [], "answered: not a modal that waits for nobody"
    with pytest.raises(pytest.fail.Exception,
                       match=r"(?s)opened while the event loop dispatches.*QMessageBox\.exec at "
                             r"tests/test_conftest_guards\.py:\d+ \(.*offer_replacement\)"):
        _no_modal_waits_for_nobody.verdict()
    _no_modal_waits_for_nobody.verdict()  # said once


def test_a_modal_the_test_opens_itself_is_not_from_a_callback(
        _no_modal_waits_for_nobody, monkeypatch):
    """The other side of the line: a test that calls the opener itself is a person's click, not a
    callback -- also right after the loop was turned, which leaves the count where it found it."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    turned: list = []
    QTimer.singleShot(0, lambda: turned.append(True))
    _spin_until(lambda: turned)

    box = QMessageBox()
    box.setText("Open the other folder?")
    assert box.exec() == QMessageBox.StandardButton.Ok

    _no_modal_waits_for_nobody.verdict()


def test_a_modal_from_a_callback_on_the_allowlist_does_not_fail_the_test(
        _no_modal_waits_for_nobody, monkeypatch):
    """Today's sites are on an allowlist by file and function, as the imports' are; one on it --
    here the test's own slot, put there for the test -- fails nothing."""
    import sys

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    conftest = sys.modules["tests.conftest"]
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    answered: list = []

    def offer_replacement() -> None:
        answered.append(QMessageBox().exec())

    monkeypatch.setitem(conftest._MODALS_FROM_A_CALLBACK_ALLOWED,
                        ("tests/test_conftest_guards.py", offer_replacement.__qualname__),
                        "stands for a site that is on the list today")
    QTimer.singleShot(0, offer_replacement)
    _spin_until(lambda: answered)

    _no_modal_waits_for_nobody.verdict()


def test_the_series_question_asked_from_a_callback_is_noted_too(_no_modal_waits_for_nobody):
    """Review M5: `_isolated_machine_config` answers three questions quietly, and the capture's
    series question (`MeasurementPanel._ask_series`) is reached from a worker's slot
    (`_on_import_renamed` -> `_finish_import` -> `_write_ledger`). Noted like the other two when a
    callback asks it; the quiet answer still answers."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc.measurement_panel import MeasurementPanel

    QApplication.instance() or QApplication([])
    asked: list = []

    def write_ledger() -> None:  # stands for the panel's slot
        asked.append(MeasurementPanel._ask_series(None))

    QTimer.singleShot(0, write_ledger)
    _spin_until(lambda: asked)

    assert asked == [None], "Cancel, as before"
    with pytest.raises(pytest.fail.Exception,
                       match=r"(?s)MeasurementPanel\._ask_series at tests/test_conftest_guards\.py:"
                             r"\d+ \(.*write_ledger\)"):
        _no_modal_waits_for_nobody.verdict()


def _functions_in(path: Path) -> dict:
    """The functions in `path` by qualified name (as `co_qualname` spells them), each with whether
    its own body -- not a function nested in it -- holds an `import` statement."""
    import ast

    found: dict = {}

    def visit(node, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                found[name] = any(isinstance(inner, (ast.Import, ast.ImportFrom))
                                  for inner in _own_statements(child))
                visit(child, f"{name}.<locals>.")
            else:
                visit(child, prefix)

    visit(ast.parse(path.read_text(encoding="utf-8")), "")
    return found


def _own_statements(function):
    """Every node of `function`'s body that is not inside a function or class nested in it."""
    import ast

    stack = list(function.body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))


def test_the_allowlists_may_only_shrink():
    """#172: each allowlist holds the sites that exist today, found by running the suite, each with
    its reason -- and neither may grow. A site moved to the top of its module leaves its entry
    stale: delete the entry and lower its number here, in the same commit."""
    import sys

    conftest = sys.modules["tests.conftest"]
    source = Path(conftest.__file__).resolve().parents[1] / "src/autosound_tcc"

    assert len(conftest._WORKER_IMPORTS_ALLOWED) == 14
    assert len(conftest._MODALS_FROM_A_CALLBACK_ALLOWED) == 0
    for (path, function), reason in conftest._WORKER_IMPORTS_ALLOWED.items():
        assert reason.strip(), f"{path} {function}: an entry says why"
        assert _functions_in(source / path).get(function), \
            f"{path} {function} is gone or imports nothing inside any more: the entry is stale"
    for (path, function), reason in conftest._MODALS_FROM_A_CALLBACK_ALLOWED.items():
        assert reason.strip(), f"{path} {function}: an entry says why"
        assert function in _functions_in(source / path), \
            f"{path} {function} is gone: the entry is stale"
