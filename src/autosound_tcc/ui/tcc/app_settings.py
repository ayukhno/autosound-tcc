"""Shared QSettings construction — one place, so every widget that persists UI state
(theme/zoom/language/preset/tree-collapse) reads and writes the same store.

Explicit `IniFormat` rather than the 2-arg `QSettings(org, app)` convenience constructor: on
macOS that convenience form always resolves to `NativeFormat` (a CFPreferences-backed plist)
*regardless* of `QSettings.setDefaultFormat()` — verified empirically, contradicting what the Qt
docs imply — which made test isolation via `QSettings.setPath()` silently no-op and let a test's
settings writes leak into the developer's real preference store (see tests/conftest.py for the
incident: a leaked `ui/preset` value caused a stray directory to be created in real project data
on a later, unrelated run). Explicit IniFormat is also just more portable/inspectable across
macOS/Windows than fighting two native backends (plist vs. registry).
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from autosound_tcc.core import config

ORG = "autosound-tcc"
APP = "TCC"


def get_settings() -> QSettings:
    return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, ORG, APP)


# The core reads the saved project choice through whatever store it is handed, because it does not
# import the window (HUB-051). This is that store, handed in by importing this module — which the
# window, `app.main` and the tuning-session CLI all do before they ask for a project.
config.use_settings(get_settings)
