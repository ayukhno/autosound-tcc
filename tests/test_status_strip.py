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
    assert strip.text().startswith("journal: could not write")
    assert strip.can_close(), "and the Arbiter can close it (2026-09-23)"


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


def test_a_dismissible_message_carries_a_close_button_that_clears_it():
    _app()
    strip = StatusStrip()
    closed = []
    strip.notify("16 unusable", level="warn", action=("show all", lambda: None),
                 dismissible=True, on_dismiss=lambda: closed.append(1))
    assert strip.can_close()
    strip._close.click()
    assert not strip.isVisible()
    assert closed == [1]


def test_a_long_warning_scrolls_inside_three_lines_instead_of_taking_the_window():
    """The Arbiter, 2026-09-23, about the half-screen banner: a long message scrolls, and it can be
    closed — for every warning, not only the unusable captures."""
    _app()
    strip = StatusStrip()
    strip.resize(600, 400)
    strip.notify("\n".join(f"line {n}: something went wrong here" for n in range(30)), level="warn")
    strip.show()
    QApplication.processEvents()
    line = strip._label.fontMetrics().lineSpacing()
    assert strip.height() <= line * 4 + 24, "three lines and its padding, not thirty"
    bar = strip._scroll.verticalScrollBar()
    assert bar.maximum() > 0, "the rest is one scroll away"
    bar.setValue(bar.maximum())
    assert strip._close.isVisible(), "the ✕ stays in view at the last line too"
    strip._close.click()
    assert not strip.isVisible()


def test_one_line_takes_one_line():
    _app()
    strip = StatusStrip()
    strip.resize(600, 200)
    strip.notify("16 unusable", level="warn")
    strip.show()
    QApplication.processEvents()
    line = strip._label.fontMetrics().lineSpacing()
    assert strip.height() < line * 2 + 12, "not a three-line box around one line"


def test_a_passing_fact_has_no_close_button():
    _app()
    strip = StatusStrip()
    strip.notify("opened a terminal running claude")
    assert "<a " not in strip.text()
    assert not strip.can_close()


def test_a_sticky_line_stands_until_its_close_and_later_lines_wait_behind_it():
    """#173, I1: a store set aside at launch was said on the strip and, in the same `__init__`,
    written over by the process's own lines before anyone could read it. A sticky line — what
    `app_log` reports — stands until its ✕: the latest later line waits behind it, counted beside
    it, and `clear()`, which answers its caller's own cause, leaves it."""
    from autosound_tcc.ui.tcc import i18n

    _app()
    strip = StatusStrip()
    strip.notify("the store was set aside", level="warn", sticky=True)
    strip.notify("a channel went stale", level="warn")
    strip.notify("opened a terminal")

    assert strip.text() == "the store was set aside" and strip.can_close()
    assert strip.waiting() == ["opened a terminal"], "the latest, as the strip always held"
    assert not strip._more.isHidden() and strip._more.text() == i18n.t("stripMore").format(n=1)

    strip.clear()
    assert strip.text() == "the store was set aside", "clear() leaves a standing line"
    assert strip.waiting() == [] and strip._more.isHidden()

    strip.notify("Phase 2 is done", action=("Start the next", lambda: None))
    strip._close.click()
    assert strip.text().startswith("Phase 2 is done") and "<a " in strip.text(), \
        "its ✕ brings the line that waited, offer and all"
    assert strip._more.isHidden()


def test_sticky_lines_stand_in_the_order_they_came_and_the_same_one_once():
    """Two reports held for the window were replayed into one line, and the first was gone before
    it was read (I1). Each stands until its own ✕, oldest first; a sentence already standing does
    not stand twice — an exception raised on every refresh is one line, not a pile."""
    _app()
    strip = StatusStrip()
    for text in ("first report", "second report", "first report"):
        strip.notify(text, level="warn", sticky=True)

    assert strip.text() == "first report" and strip.waiting() == ["second report"]
    strip._close.click()
    assert strip.text() == "second report" and strip.waiting() == []
    strip._close.click()
    assert strip.text() == "" and strip.isHidden()


def test_a_fact_waiting_behind_a_sticky_line_starts_its_clock_when_it_is_shown():
    """The re-review, N2: the clock ran while the line waited, so a fact said once — «Not written
    down: …» is said once per fact, and only here — ran out its thirty seconds behind the standing
    report and was never seen. Its clock starts when it is shown: not while it waits, and in full
    again when a new standing line covers it and is closed."""
    _app()
    strip = StatusStrip()
    strip.notify("the store could not be read", level="warn", sticky=True)
    strip.notify("Not written down: the target curve")

    assert not strip.timer_is_running(), "waiting, it is not on its clock"
    strip._close.click()
    assert strip.text() == "Not written down: the target curve" and strip.timer_is_running()

    strip.notify("a second report", level="warn", sticky=True)
    assert not strip.timer_is_running(), "covered, its clock stops"
    assert strip.waiting() == ["Not written down: the target curve"]
    strip._close.click()
    assert strip.timer_is_running(), "shown again, on its clock again"
    strip._expire()
    assert strip.text() == "" and strip.isHidden()


def test_a_line_taken_back_goes_whether_it_is_shown_or_waiting_and_no_other_does():
    """The review of TA-8, I1: a caller whose cause has ended takes its own line back — the capture
    check's «did not run», once a check ran. Taken back only while shown, the line waiting behind a
    report came back at the report's ✕, false, and a warning has no clock to let go of it. What is
    taken back is the caller's own line: not a report, not a line that came after it."""
    _app()
    strip = StatusStrip()

    strip.notify("did not run", level="warn")
    assert strip.withdraw("did not run") is True, "it says whether it took the line back"
    assert strip.text() == ""

    strip.notify("a report", level="warn", sticky=True)
    strip.notify("did not run", level="warn")
    assert strip.text() == "a report" and strip.waiting() == ["did not run"]
    strip.withdraw("did not run")
    assert strip.waiting() == [], "taken back while it waits, too"
    strip.linkActivated.emit("close")
    assert strip.text() == ""

    strip.notify("a report", level="warn", sticky=True)
    strip.notify("something later", level="warn")
    assert strip.withdraw("did not run") is False and strip.withdraw("a report") is False
    assert strip.text() == "a report" and strip.waiting() == ["something later"]
