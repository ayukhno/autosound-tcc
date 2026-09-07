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
def _collect_qt_leftovers():
    """Free the test's discarded Qt objects HERE, between tests, not at a moment Python picks.

    A `QThread` with no parent lives until the garbage collector takes it, and the tests make
    plenty of those — `AgentWorker(...).shutdown()` on one line builds a thread and drops it. On
    Windows the collection landing inside the next `QThread(...)` constructor is an access
    violation that kills the whole run: 4 of 10 full runs, always in `agent_worker.py:46`
    (2026-09-07, `#19`). A cycle collected between tests costs microseconds and lands nowhere.

    Not a fix for the product: there every worker has a parent widget that owns it. This is the
    suite being tidy about what it throws away.
    """
    yield
    gc.collect()


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
    """
    try:
        from autosound_tcc.core import vendor_loader

        api = vendor_loader.load_rew_api()
    except Exception:  # noqa: BLE001 — no skill checked out: nothing can call REW anyway
        yield
        return
    previous = api.BASE_URL
    api.BASE_URL = "http://127.0.0.1:1"  # refused instantly, on every platform
    try:
        yield
    finally:
        api.BASE_URL = previous


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
    from autosound_tcc.ui.tcc import qt_shutdown

    qt_shutdown.destroy_application()


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setenv("HOME", str(tmp_path))  # IniFormat UserScope resolves under $HOME
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # ...and under this one on Windows
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
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
def _isolated_machine_config(tmp_path, monkeypatch):
    """Third layer, same lesson: keep tests out of `~/.config/autosound-tcc`.

    `model_overrides` lives there, and once diagnostics started reporting on it (2026-08-12) two
    existing tests began failing on this machine and nowhere else — they were reading the
    developer's own model aliases. A test that passes or fails depending on whose laptop it runs on
    is not a test, and one that could WRITE there would edit a real configuration.
    """
    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "machine-config"))
    # ...and out of the answer to "which agent CLIs does this developer have installed". That is a
    # probe of the machine, so a suite that reads it passes here and fails on the next laptop —
    # `test_ok_report_says_so` started failing the moment diagnostics learned to report an
    # installed-but-silent CLI, on a machine that happens to have `agy`. Tests that care about a
    # CLI being present monkeypatch this themselves; their patch runs later and wins.
    from autosound_tcc.core import model_choices

    monkeypatch.setattr(model_choices, "_CLI_CACHE", {}, raising=False)
    monkeypatch.setattr(model_choices, "cli_available", lambda harness: False, raising=False)
    # ...and the same probe wearing another name. `critic_reaches` does NOT go through
    # `cli_available`: it asks `os.environ` and `shutil.which` itself, so the patch above never
    # sees it. Two tests were therefore decided by what the developer happened to have installed,
    # and nobody could tell until there was a second machine (CI, 2026-09-07). Tests that need a
    # reachable critic patch it back themselves; their patch runs later and wins.
    monkeypatch.setattr(model_choices, "critic_reaches", lambda choice: False, raising=False)
    # ...and off the network. Opening the diagnostics dialog's Installation tab asks GitHub what
    # the newest TCC and method are; a suite that does that is slow when the network is there and
    # red when it is not. Tests about the update rows patch this themselves.
    from autosound_tcc.core import updates

    monkeypatch.setattr(
        updates, "check_all",
        lambda: (updates.Status("tcc", "0.0.0", "", False, "offline in tests", updatable=False),
                 updates.Status("skill", "0.0.0", "", False, "offline in tests", updatable=False)),
        raising=False,
    )
    yield
