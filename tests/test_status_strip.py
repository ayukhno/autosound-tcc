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


def test_an_action_is_a_link_that_runs_once_and_clears_the_line():
    _app()
    strip = StatusStrip()
    calls = []
    strip.notify("Intake ready", action=("Start the session", lambda: calls.append(1)))
    assert "Start the session" in strip.text() and "<a " in strip.text()
    assert not strip.timer_is_running(), "an offer waits for the click, it does not expire"
    strip.linkActivated.emit("action")
    assert calls == [1]
    assert not strip.isVisible()
    strip.linkActivated.emit("action")
    assert calls == [1], "a cleared offer cannot be taken twice"


def test_a_plain_message_after_an_offer_has_no_link():
    _app()
    strip = StatusStrip()
    strip.notify("Intake ready", action=("Start", lambda: None))
    strip.notify("a <b>fact</b> & nothing else")
    assert "<a " not in strip.text()
    assert strip.timer_is_running()


def test_a_dismissible_message_carries_a_close_link_that_clears_it():
    _app()
    strip = StatusStrip()
    closed = []
    strip.notify("16 unusable", level="warn", action=("show all", lambda: None),
                 dismissible=True, on_dismiss=lambda: closed.append(1))
    assert 'href="close"' in strip.text()
    strip.linkActivated.emit("close")
    assert not strip.isVisible()
    assert closed == [1]
