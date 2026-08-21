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

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402


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
