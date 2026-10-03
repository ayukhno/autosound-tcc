"""Test-wide fixtures.

Isolate QSettings from the developer's real OS-level preference store. Without this, any test
that touches MainWindow (theme/zoom/language/preset selection all persist via
`QSettings("autosound-tcc", "TCC")`) writes to the SAME store a real interactive run would use --
a real incident: a test that set `ui/preset` to a nonexistent name leaked into a later run and
silently created a stray directory in the developer's actual project data (PresetHistory's
constructor `os.makedirs()`s the preset dir just from being asked to look at it). Redirecting to
a per-test-session tmp .ini file makes every test's settings writes disappear with the tmp dir.
"""

from __future__ import annotations

import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Captured at import, before any fixture can patch it: `real_critic_reaches` hands this back to
# the tests that examine the probe rather than live with its answer.
from autosound_tcc.core import model_choices as _model_choices_at_import

_REAL_CRITIC_REACHES = _model_choices_at_import.critic_reaches

import sys  # noqa: E402
import traceback  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402


@pytest.fixture(autouse=True)
def _an_exception_in_a_qt_slot_fails_the_test():
    """A slot that raises must not leave the run green.

    Qt cannot let a Python exception cross back into C++, so it hands it to `sys.excepthook` and
    carries on -- and pytest captures stderr on a passing test, so the traceback is not even
    printed. Measured on 2026-09-07: `main_window`'s two-second nudge timer hit a test double
    with no `pending_count` twice per run of `test_main_window.py`, and the file reported
    "134 passed" both times. Only `pytest -s` showed anything (HUB-046).

    The traceback names the culprit; the test name does not necessarily. A window one test left
    alive keeps its timers, and they fire during whatever test is running when they go off -- so
    read the frames, not the heading.
    """
    caught: list[str] = []
    previous = sys.excepthook

    def _record(kind, value, tb):
        caught.append("".join(traceback.format_exception(kind, value, tb)))

    sys.excepthook = _record
    try:
        yield
    finally:
        sys.excepthook = previous
    if caught:
        pytest.fail(
            f"{len(caught)} exception(s) escaped from a Qt slot during this test -- Qt printed "
            f"them to stderr and carried on. The frames below are the real location, and may "
            f"belong to a widget an earlier test left alive:\n\n" + "\n".join(caught),
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def _collect_qt_leftovers(request):
    """Free the test's discarded Qt objects HERE, between tests, not at a moment Python picks.

    A `QThread` with no parent lives until the garbage collector takes it, and the tests make
    plenty of those — `AgentWorker(...).shutdown()` on one line builds a thread and drops it. On
    Windows the collection landing inside the next `QThread(...)` constructor is an access
    violation that kills the whole run: 4 of 10 full runs, always in `agent_worker.py:46`
    (2026-09-07, `#19`). A cycle collected between tests costs microseconds and lands nowhere.

    Not a fix for the product: there every worker has a parent widget that owns it. This is the
    suite being tidy about what it throws away.

    FROZEN between tests (F-065). The windows of every earlier test are still alive (F-053), and
    a full collection walks every Python object they hold: late in one-process `pytest tests/`
    a quarter of a second, paid by every test -- 437 s of a 2730-s serial run on the Mac at
    956e8a8, where CI's whole-suite jobs ran out of time. So what is alive when a test starts is
    frozen (`gc.freeze`), and each collection here walks only what was made since, which is all a
    test can have discarded. The previous test's leftovers are collected first, once its
    fixtures have let go of them. A file's first test collects everything, unfrozen, so what a
    finished file's module fixtures held is not kept past it; the session ends unfrozen and
    collected, as it did before, while Qt is still whole.
    """
    global _GC_FILE
    if request.node.path != _GC_FILE:
        _GC_FILE = request.node.path
        gc.unfreeze()
    gc.collect()
    gc.freeze()
    yield
    gc.collect()


#: The file whose tests are running, for `_collect_qt_leftovers`: a new one unfreezes the heap.
_GC_FILE = None


@pytest.fixture(autouse=True)
def _no_console_keeper_threads(monkeypatch):
    """Every test gets a spawn that starts nothing: a console keeper outlives its test by hours.

    A keeper is a daemon thread with a budget of up to twelve hours, and on a Windows runner the
    pid two tests handed one was pytest's own, alive to the end. Those two threads sat in every
    crash dump of 2026-09-11. They did not cause `#19`: with them gone (2026-09-12) the dumps show
    no Python thread but the main one, and it still dies in `QThread.__init__`. Tests that examine
    spawning inject their own `spawn` or `defer`.
    """
    from autosound_tcc.core import child

    monkeypatch.setattr(child, "_spawn_daemon", lambda target, kwargs: None)


@pytest.fixture(autouse=True)
def _no_hover_filter_left_on_the_app(monkeypatch):
    """`app.main()` installs one app-wide hover filter (tcc#137), and a test that runs `main` left
    it on the application for every later test in the worker, answering their activations with the
    real cursor -- 32 tests across three files (night review, M4). Installed by nobody here;
    `test_hover_reset.py` overrides this fixture by name, because `install` is what it tests."""
    from autosound_tcc.ui.tcc import hover_reset

    monkeypatch.setattr(hover_reset, "install", lambda app, cursor_pos=None: None)


@pytest.fixture(autouse=True)
def _no_mcp_call_outlives_its_test():
    """tcc#141: an MCP call runs on a daemon thread since tcc#132, which `asyncio.run` no longer
    joins at a test's end. One left running reached `availability` in the next test after its
    monkeypatches were undone — the serial suite's flaky six at W-5's release. Drained here, so
    whatever a late call wrote is there before the next test's `_fresh_availability` resets it.

    Only the calls this test started (night review of tcc#141, M11). A call that never ends -- a
    confirm waiting out its 600 s -- added 2 s to every later test in the worker and named nobody;
    now it fails its own test, once, by the tool it runs. Imported at setup, not at teardown: a
    test that patches `sys.platform` made the first import of `mcp` take another OS's branch
    (`test_terminal_launcher.py` on its own: five errors at teardown)."""
    from autosound_tcc.core import mcp_server

    before = mcp_server.calls_out()
    yield
    left = mcp_server.drain_calls(timeout=2.0, ignore=before)
    if left:
        stuck = sorted(mcp_server.call_name(t) for t in mcp_server.calls_out() - before)
        pytest.fail(f"{left} MCP call(s) outlived this test, still running: {', '.join(stuck)}",
                    pytrace=False)


@pytest.fixture(autouse=True)
def _fresh_availability():
    """Every test starts on a fresh launch's availability, and leaves one behind.

    It is process-wide state, written from worker threads: a refusal, a harness still being read or
    a registered startup reading one test left behind turns rows red in whichever test runs next.
    """
    from autosound_tcc.core import availability

    availability.reset()
    yield
    availability.reset()


@pytest.fixture
def real_critic_reaches(monkeypatch):
    """The unguarded `critic_reaches`, for the tests whose subject IS the probe.

    The autouse fixture above answers False for everyone, so the developer's PATH cannot decide a
    result. That is right for every test about badges, footers and state — and wrong for the four
    that check the probe itself, which would otherwise assert against their own guard. Asking for
    this fixture is how a test says "I am testing the machine question, not depending on the
    answer"; it still controls what the probe sees through `shutil.which` and the environment.
    """
    monkeypatch.setattr(
        _model_choices_at_import, "critic_reaches", _REAL_CRITIC_REACHES, raising=False
    )
    return _REAL_CRITIC_REACHES


@pytest.fixture(scope="session", autouse=True)
def _no_live_rew():
    """Point the REW API at a port nothing listens on, for the whole session.

    The suite was green because REW happened to be CLOSED. With a real REW open on this machine
    -- which is the normal state while somebody is tuning -- `test_main_window.py` built a real
    curve window, its workers really fetched impulse responses over HTTP, and closing the dialog
    while two of them sat in `urlopen` aborted the process: exit 134, mid-run, in a test about a
    button (measured 2026-08-23, with REW live on 4735).

    Two things were wrong and this fixes both. A unit test must not reach a service on the
    developer's machine, and a suite whose result depends on whether an unrelated application is
    running is not a suite. A refused connection is what every one of these tests already expects,
    so this changes nothing about what they assert -- only that they get the same answer whether
    or not the tuner is mid-session.

    NOT "stop REW": it may be live and mid-measurement, and this repository does not touch it
    (cockpit rule 6). Tests that want REW's behaviour fake it themselves.

    The variable as well as the module (tcc#21): the method's `verify.py` imports its OWN bare
    `rew_api` by name, a second copy of the file this one never patched, and the copy reads its
    endpoint from `REW_API_URL` when it loads. So do the method's scripts run as children.
    """
    dead = "http://127.0.0.1:1"  # refused instantly, on every platform
    before = os.environ.get("REW_API_URL")
    os.environ["REW_API_URL"] = dead
    bare = sys.modules.get("rew_api")  # a bare copy already loaded is re-pointed too
    if bare is not None:
        bare.BASE_URL = dead
    try:
        from autosound_tcc.core import vendor_loader

        api = vendor_loader.load_rew_api()
    except Exception:  # noqa: BLE001 — no skill checked out: nothing can call REW anyway
        api = None
    previous = api.BASE_URL if api is not None else None
    if api is not None:
        api.BASE_URL = dead
    try:
        yield
    finally:
        if api is not None:
            api.BASE_URL = previous
        if before is None:
            os.environ.pop("REW_API_URL", None)
        else:
            os.environ["REW_API_URL"] = before


@pytest.fixture(autouse=True)
def _quiet_windows_left_behind():
    """TODO F-053: a window a test leaves alive stops acting once its test is over — its timers,
    its watchers, its writes — without being deleted (see `tests/_windows.py` for why not)."""
    from tests import _windows

    # The windows themselves are held, not just their ids. An id alone can be handed to the
    # test's own window once what it named is freed -- then it counted as "there before" and was
    # never quieted (with the wrappers `topLevelWidgets()` made just to be counted, it was at
    # once). The registry, not that walk: see `main_windows`. Measured in a plain `-n 4` run:
    # `test_a_marked_omp_model_joins_...`'s window stayed live, its deferred placeholder drop
    # wrote its omp pick into the NEXT test's project, and that test's window opened the «model
    # gone» box on it -- a real modal, which waits for nobody and held the worker until it was
    # killed.
    before = _windows.main_windows()
    seen = {id(window) for window in before}
    yield
    for window in _windows.main_windows():
        if id(window) not in seen:
            _windows.quiet(window)
    del before


@pytest.fixture(autouse=True)
def _a_finished_test_s_widgets_are_not_retranslated():
    """A language switch retranslates the widgets of the test that switches, not of every test
    before it (F-065).

    `i18n.set_language` calls every registered `retranslate`, and every `MainWindow` calls it as
    it is built. The widgets of earlier tests are still alive (F-053), so in one process each
    switch -- and each window built -- redid the words of every detail pane and diagnostics panel
    the run had made so far: 415 switches, 827 s of a 2730-s serial run on the Mac at 956e8a8,
    up to 4.3 s for one late in `test_main_window.py`. What a test registered is dropped from the
    list when the test is over; what was registered before it (a module's fixture, an import)
    stays. Nothing is deleted: a finished test's widgets simply keep the words they had, like its
    quieted windows keep their last state."""
    from tests import _windows

    before = _windows.language_listeners()
    yield
    _windows.drop_language_listeners_since(before)


#: How many modals one test may reach before the guard fails it where it stands. Cancel lets the
#: code go on, and code that asks again after a cancel would ask forever (review of tcc#123).
_MODAL_CAP = 20


class _ModalLog:
    """The modals a test reached, by name, for its end to fail on (`_no_modal_waits_for_nobody`)."""

    def __init__(self) -> None:
        self.opened: list = []

    def record(self, what: str, answer):
        if len(self.opened) >= _MODAL_CAP:
            # `pytest.fail` raises a BaseException: a broad `except Exception` around the
            # question does not swallow it and ask again.
            opened, self.opened = self.opened, []
            pytest.fail(f"{_MODAL_CAP} modals in one test, the last {opened[-1]} -- asked "
                        f"again after Cancel? Nobody answers it in a test; patch its exec, or "
                        f"the call that opens it, in the test", pytrace=False)
        self.opened.append(what)
        return answer

    def verdict(self) -> None:
        if self.opened:
            opened, self.opened = self.opened, []
            pytest.fail(f"a test opened a modal: {'; '.join(opened)} -- nobody answers it in a "
                        f"test; patch its exec, or the call that opens it, in the test",
                        pytrace=False)


def _dialog_statics() -> tuple:
    """`(class, static, what Cancel answers)` for each dialog static the guard answers. Each is
    a modal of its own: its `exec` is C++'s, which the guard's `QDialog.exec` never sees.
    `QInputDialog.getInt` and `QFileDialog.getSaveFileName` are not here: `_isolated_machine_config`
    cancels them quietly, because tests walk through those questions."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QColor, QFont
    from PySide6.QtWidgets import (QColorDialog, QFileDialog, QFontDialog, QInputDialog,
                                   QMessageBox)

    return (
        (QFileDialog, "getOpenFileName", lambda: ("", "")),
        (QFileDialog, "getOpenFileNames", lambda: ([], "")),
        (QFileDialog, "getExistingDirectory", lambda: ""),
        (QFileDialog, "getOpenFileUrl", lambda: (QUrl(), "")),
        (QFileDialog, "getOpenFileUrls", lambda: ([], "")),
        (QFileDialog, "getSaveFileUrl", lambda: (QUrl(), "")),
        (QFileDialog, "getExistingDirectoryUrl", lambda: QUrl()),
        (QInputDialog, "getText", lambda: ("", False)),
        (QInputDialog, "getMultiLineText", lambda: ("", False)),
        (QInputDialog, "getItem", lambda: ("", False)),
        (QInputDialog, "getDouble", lambda: (0.0, False)),
        (QColorDialog, "getColor", lambda: QColor()),  # an invalid colour is the cancel
        (QFontDialog, "getFont", lambda: (False, QFont())),
        (QMessageBox, "about", lambda: None),
        (QMessageBox, "aboutQt", lambda: None),
    )


@pytest.fixture(autouse=True)
def _no_modal_waits_for_nobody(monkeypatch):
    """A modal a test reaches fails that test, naming the modal, instead of holding the run.

    Nobody answers a modal in a test, and a real one waits forever. A plain `-n 4` run of four
    files here (2026-09-30) sat in `_offer_replacement`'s «model gone» box until the worker was
    killed, 24 minutes on; CI's Windows shard 4 at 0750776 was cancelled at its 25-minute limit
    in the same stretch of the suite.

    The modal answers what nobody choosing answers -- Escape, Cancel -- and is written down, and
    the test fails at its end naming each one it reached. It used to raise where the modal
    opened (tcc#123, W-4 review): that is inside the window's code, and a `try` there that
    catches broadly took the guard's error for its own and went on, so the test passed.

    `QDialog.exec` is the one `exec` every dialog in PySide reaches, `QMessageBox`'s included;
    the static `QMessageBox` questions and the dialog statics (`_dialog_statics`) are modals of
    their own. A test that is ABOUT a modal patches its `exec` (or the call that opens it)
    itself; its patch runs later and wins. Yields the log, for the test of this guard."""
    from PySide6.QtWidgets import QDialog, QMessageBox

    log = _ModalLog()

    def exec_(self, *_args, **_kwargs):
        text = self.text() if isinstance(self, QMessageBox) else ""
        return log.record(f"{type(self).__name__} «{self.windowTitle()}» {text[:200]!r}", 0)

    monkeypatch.setattr(QDialog, "exec", exec_)
    for name in ("question", "warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *args, _name=name, **_kwargs: log.record(
                f"QMessageBox.{_name} {args[1:3] if len(args) > 2 else args!r}",
                QMessageBox.StandardButton.NoButton)))
    for owner, name, cancel in _dialog_statics():
        monkeypatch.setattr(owner, name, staticmethod(
            lambda *args, _what=f"{owner.__name__}.{name}", _cancel=cancel, **_kwargs:
                log.record(f"{_what} {args[:3]!r}", _cancel())))
    yield log
    log.verdict()


@pytest.fixture(scope="session", autouse=True)
def _end_qt_before_python_finalises():
    """Destroy the QApplication here, while the interpreter is still whole.

    The suite prints `passed` and the PROCESS then dies: exit 139, about one run in ten (4/40, and
    2/12 on a tree nobody was editing). It leaves 16631 top-level widgets alive, and
    `~QApplication` -- which PySide runs from an `atexit` handler inside `Py_FinalizeEx` --
    destroys every one of them against Python halves that are already going. Running the same
    destructor here changes nothing about WHAT is destroyed, only when: early enough that PySide
    can still find the Python half of everything it touches.

    Session-scoped, and it destroys the whole application rather than walking the widgets, because
    both narrower shapes have been measured and both were worse: per-test widget teardown on
    2026-08-13 (2 crashes in 5 runs), and a `deleteLater` sweep over top-level widgets on
    2026-08-18 (6 in 6 on the plot files alone). `qt_shutdown`'s docstring lists every variant and
    the frame it died in. Nothing here changes when a test's widgets die.
    """
    yield
    # What `_collect_qt_leftovers` froze goes back to the collector, and is collected here while
    # Python and Qt are both whole -- where the per-test collection would have taken it.
    gc.unfreeze()
    gc.collect()
    from autosound_tcc.ui.tcc import qt_shutdown

    qt_shutdown.destroy_application()


@pytest.fixture
def _machine_dir(tmp_path_factory):
    """Where the app's own settings, logs and caches go during a test — beside `tmp_path`, not in it.

    Tests use `tmp_path` as a project folder, and a window watches its project folder. With the
    app's writes in the same folder, a window took its own `TCC.ini`, `AppData` or
    `cli-catalogue.json` for a change to the project and rebuilt the DSP tree 400 ms later, in the
    middle of whatever the test held: tcc#28, one Windows run in ten from the day APPDATA moved
    into `tmp_path` (2026-09-11).
    """
    return tmp_path_factory.mktemp("machine")


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path, _machine_dir, monkeypatch):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    # HOME stays in `tmp_path`: tests read `~/.claude` through it, and a window writes nothing there
    # — the one thing that did was the real `claude` CLI, kept off in `_isolated_machine_config`.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # what `~` follows on Windows
    # And every OTHER door onto the user's directories. HOME alone is enough on the machine this
    # was written on, where nothing else is set — and that is exactly why it kept passing here and
    # failing on CI. GitHub's runners set `LOCALAPPDATA` and `APPDATA` on Windows and
    # `XDG_CONFIG_HOME` on Linux, and code that reads those (the log directory, the reviewer's
    # machine key) went straight past the tmp HOME to the runner's real folders. Two of the four
    # red tests on 11.09 were that, wearing different coats; a third was the same shape a day
    # earlier. One fixture is the place to answer it, not ten tests.
    monkeypatch.setenv("LOCALAPPDATA", str(_machine_dir / "AppData" / "Local"))
    monkeypatch.setenv("APPDATA", str(_machine_dir / "AppData" / "Roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(_machine_dir / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(_machine_dir / ".local" / "state"))
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(_machine_dir))
    # The core reads the saved project choice through the store it is handed (HUB-051). Handed in
    # here for every test, rather than by whichever test happened to import the window first.
    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import app_settings

    monkeypatch.setattr(config, "_settings_provider", app_settings.get_settings, raising=False)
    yield


@pytest.fixture(autouse=True)
def _isolated_project_dir(tmp_path, monkeypatch):
    """Keep tests out of the developer's real project folder, and off the network.

    Same failure mode the QSettings fixture exists for, one layer up: `config.project_dir()` falls
    back to the real ledger root, and MainWindow writes `.mcp.json` and `.tcc/` into whatever it
    resolves to. Without this, merely constructing a window during a test drops files into
    `data/private/state/` -- observed, not hypothetical.

    `AUTOSOUND_TCC_MCP=0` additionally keeps the tests from binding a real port: a suite that
    starts uvicorn per window is slow, and two tests scanning for a free port at once is a race
    nobody wants to debug later.
    """
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(project))
    monkeypatch.setenv("AUTOSOUND_TCC_MCP", "0")
    # Setting the variable is not the same as the redirection working: a cached value, an
    # override read earlier, a helper resolving the path its own way, and the tests are back on
    # the developer's real car with nothing said. The fixture sets it, so the fixture checks it
    # (2026-08-21, after a test glossary was found sitting in a live project).
    from autosound_tcc.core import config

    resolved = config.project_dir().resolve()
    assert resolved == project.resolve(), (
        f"AUTOSOUND_PROJECT_DIR was set to {project}, but config.project_dir() answers "
        f"{resolved} -- the tests are not isolated from the real project"
    )
    yield


@pytest.fixture(autouse=True)
def _isolated_machine_config(tmp_path, _machine_dir, monkeypatch):
    """Third layer, same lesson: keep tests out of `~/.config/autosound-tcc`.

    `model_overrides` lives there, and once diagnostics started reporting on it (2026-08-12) two
    existing tests began failing on this machine and nowhere else — they were reading the
    developer's own model aliases. A test that passes or fails depending on whose laptop it runs on
    is not a test, and one that could WRITE there would edit a real configuration.
    """
    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(_machine_dir / "machine-config"))
    # ...and out of the answer to "which agent CLIs does this developer have installed". That is a
    # probe of the machine, so a suite that reads it passes here and fails on the next laptop —
    # `test_ok_report_says_so` started failing the moment diagnostics learned to report an
    # installed-but-silent CLI, on a machine that happens to have `agy`. Tests that care about a
    # CLI being present monkeypatch this themselves; their patch runs later and wins.
    from autosound_tcc.core import model_choices

    monkeypatch.setattr(model_choices, "_CLI_CACHE", {}, raising=False)
    # ...and when each route was last ASKED, which sits beside the answers and decides whether an
    # empty answer counts as "installed and silent". Left over from whichever test asked last, it
    # made `test_an_installed_cli_that_answered_nothing_gets_a_row_and_a_retry` pass after
    # `test_model_choices.py` and fail on its own or in a parallel worker: 15 of 15 parallel runs,
    # 2026-09-14.
    monkeypatch.setattr(model_choices, "_LAST_ASKED", {}, raising=False)
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: False, raising=False)
    # ...and the same probe wearing another name. `critic_reaches` does NOT go through
    # `cli_available`: it asks `os.environ` and `shutil.which` itself, so the patch above never
    # sees it. Two tests were therefore decided by what the developer happened to have installed,
    # and nobody could tell until there was a second machine (CI, 2026-09-07). Tests that need a
    # reachable critic patch it back themselves; their patch runs later and wins.
    monkeypatch.setattr(model_choices, "critic_reaches", lambda choice: False, raising=False)
    # ...and where the reviewer's key lives, which the METHOD answers by running its own script
    # (`key status`, hub #197). A test must not run it: it would read this developer's Keychain.
    # "The method cannot answer" is the neutral reply — reachability falls back to the file, which
    # the tests already control. Tests of the reader patch `_run` themselves.
    from autosound_tcc.core import reviewer_key

    monkeypatch.setattr(reviewer_key, "_ask", lambda: None, raising=False)
    monkeypatch.setattr(reviewer_key, "_STATUS", False, raising=False)
    # ...and how agy signs in, which the method also answers by running its own script against
    # this machine's critic-env (tcc#135). "The method cannot say" is the neutral reply; tests of
    # the reader take the real one at import. What a reading left for the panel goes with it, so
    # one test's agy row never shows in the next (night review of tcc#135, M7).
    from autosound_tcc.core import critic, self_check

    monkeypatch.setattr(critic, "agy_sign_in", lambda project_dir=None, register=None: None,
                        raising=False)
    monkeypatch.setattr(self_check, "_AGY_SIGN_IN", {}, raising=False)
    # ...and the same probe for Claude. A window's catalogue worker asks `claude auth status`, and
    # on a machine with Claude Code that ran the real CLI: with HOME in `tmp_path` it wrote
    # `.claude.json` there, and the window's project watcher reloaded over the test (2026-09-14).
    # What it remembered leaked between tests as well, so which test paid for it was down to order.
    # Tests about the login probe patch these themselves; their patch runs later and wins.
    from autosound_tcc.core import claude_sdk

    monkeypatch.setattr(claude_sdk, "cli_path", lambda: None, raising=False)
    monkeypatch.setattr(claude_sdk, "_ASKED", False, raising=False)
    monkeypatch.setattr(claude_sdk, "_SIGNED_IN", None, raising=False)
    # ...and off the network. Opening the diagnostics dialog's Installation tab asks GitHub what
    # the newest TCC and method are; a suite that does that is slow when the network is there and
    # red when it is not. Tests about the update rows patch this themselves.
    from autosound_tcc.core import updates

    monkeypatch.setattr(
        updates, "check_all",
        lambda channel="stable": (
            updates.Status("tcc", "0.0.0", "", False, "offline in tests", updatable=False),
            updates.Status("skill", "0.0.0", "", False, "offline in tests", updatable=False)),
        raising=False,
    )
    # ...and the tools under the same tab (tcc#98): the skill's `upkeep.py status` asks Homebrew,
    # npm and GitHub, and its `tools` would update the developer's own omp, gh and Claude Code.
    # Tests about the tool rows patch these themselves.
    monkeypatch.setattr(updates, "tools_status",
                        lambda: updates.ToolsStatus(False, reason="offline in tests"),
                        raising=False)
    monkeypatch.setattr(updates, "update_tools",
                        lambda names: updates.ToolsUpdate((), "offline in tests"), raising=False)
    # ...and what an update taught those rows, which lives as long as the process (tcc#138): one
    # test's update would grey the row of whichever test the same worker runs next.
    from autosound_tcc.ui.tcc import diagnostics_panel

    monkeypatch.setattr(diagnostics_panel, "_UPDATED_TO", {})
    # ...and no modal question waits for a person who is not there. A first capture round with no
    # series asks for its number (hub #153 A); in a test nobody answers, and a real QInputDialog
    # holds the whole run — it did, for five minutes, on the first try. Cancel is the answer here;
    # tests about that question patch this themselves, later, and win.
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getInt", staticmethod(lambda *_a, **_k: (0, False)))
    # That question grew a second half on 2026-09-20 (S-048: where the measurements came from), so
    # it is its own dialog now and `QInputDialog` no longer covers it. Cancel here too; the rule it
    # applies afterwards is `_origin_of`, which is a plain function precisely so it can be tested
    # without anybody clicking anything.
    from autosound_tcc.ui.tcc.measurement_panel import MeasurementPanel

    monkeypatch.setattr(MeasurementPanel, "_ask_series", lambda self: None)
    # The same for a save dialog (TODO F-054): nobody picks a file in a test.
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: ("", "")))
    yield


@pytest.fixture
def app_ground():
    """The whole application's state a window's measurements stand on, set by the test that
    measures rather than inherited from whichever test ran before it in the same xdist worker.
    The full `-n 4` run at 942dd61 failed four head tests that passed alone: a test before them
    in the worker cleared the application's sheet and left `apply_theme`'s record saying the
    sheet was on, so the next window skipped it and measured itself unstyled.

    Here: the platform's own font -- at the stretch the run declares, `WIDE_STRETCH` (the
    wide-font emulation's variable), or none; English. The window's own `apply_theme` applies its
    sheet at its own zoom (per test, from the isolated settings) unless that very sheet is already
    on the application -- it compares the application's sheet itself since tcc#123, so a sheet a
    test before this one took off is put back. Everything goes back after.

    Each of these is written only where it differs. Every write here is the whole application's
    -- `setStyleSheet` re-polishes every live widget in the process, `setFont` and `setPalette`
    send each one an event, `set_language` retranslates every window -- and the windows of every
    test before this one in the worker are all still alive (F-053). Re-styling them all for a
    sheet that was already on (d3f4cc1) cost 1.8-3.1 s a test in `test_detail_pane.py` on the Mac
    and 30 s in control mode's chip test, the two files 121 s -> 211 s; CI's Windows shard 4 went
    from 806 s (942dd61) to 1232 s, then to its 25-minute limit (2026-09-30)."""
    from PySide6.QtGui import QFont, QFontDatabase, QPalette
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc import i18n, theme

    app = QApplication.instance() or QApplication([])
    was = (QFont(app.font()), app.styleSheet(), QPalette(app.palette()), theme._CURRENT,
           i18n.current_language())
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    stretch = int(os.environ.get("WIDE_STRETCH", "100"))
    if stretch != 100:
        font.setStretch(stretch)
    if app.font() != font:
        app.setFont(font)
    theme._CURRENT = None
    if i18n.current_language() != "en":
        i18n.set_language("en")
    try:
        yield app
    finally:
        if app.font() != was[0]:
            app.setFont(was[0])
        if app.styleSheet() != was[1]:
            app.setStyleSheet(was[1])
        if app.palette() != was[2]:
            app.setPalette(was[2])
        theme._CURRENT = was[3]
        if i18n.current_language() != was[4]:
            i18n.set_language(was[4])
