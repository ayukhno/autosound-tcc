"""The console Windows forces on the launch is read in the second it is on screen."""

from __future__ import annotations

from autosound_tcc.app import STARTUP_CONSOLE_TEXT


def test_the_startup_console_says_one_short_english_line():
    """The Arbiter, 2026-09-13, on v0.1.38: the first window carried a Ukrainian sentence and an
    English one under the name — "always English, and as short as possible, so the eye can catch
    it". It is on screen for `child.APP_CONSOLE_VISIBLE_S`, a little over a second.

    English whatever the interface language: the line is written before the settings that hold the
    language are read, and a single fixed line is what a glance can take in."""
    assert STARTUP_CONSOLE_TEXT.isascii(), "English only"
    assert "\n" not in STARTUP_CONSOLE_TEXT.strip(), "one line"
    assert len(STARTUP_CONSOLE_TEXT.strip()) <= 32, "short enough to read at a glance"
