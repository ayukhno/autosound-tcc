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
    yield
