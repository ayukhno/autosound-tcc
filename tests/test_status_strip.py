"""The one-line strip that holds the latest fact — and lets go of it (tcc#25)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc.status_strip import StatusStrip  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_a_fact_that_has_passed_lets_go_of_the_strip():
    """"Opened a terminal running claude" is an EVENT: it was true for a second and then it was
    just words on the screen, under the next thing the person did (user, 2026-09-09 — the line
    was still there long after the terminal had been used and answered).

    Only one place in the whole app ever called `clear()`, so an `info` line stayed for the life
    of the window."""
    _app()
    strip = StatusStrip()

    strip.notify("Opened a terminal running claude in the project folder.")
    assert strip.isVisible() or strip.text()

    strip._expire()

    assert strip.text() == ""


def test_a_warning_stays_until_something_replaces_it():
    """A warning names a condition, not an event: "the MCP config could not be written" is as
    true a minute later. Timing it out would hide a problem that is still there."""
    _app()
    strip = StatusStrip()

    strip.notify("journal: could not write", level="warn")

    assert strip.timer_is_running() is False
    assert strip.text() == "journal: could not write"


def test_a_second_fact_replaces_the_first_and_restarts_the_clock():
    _app()
    strip = StatusStrip()

    strip.notify("first")
    strip.notify("second")

    assert strip.text() == "second"
    assert strip.timer_is_running() is True
