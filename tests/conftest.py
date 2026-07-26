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
