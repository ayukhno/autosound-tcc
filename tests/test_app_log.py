"""TCC's errors must land in a file, not in the terminal it was launched from.

The terminal is not a neutral place to print on macOS: a line arriving there while the window is
a full-screen space switches the user out of the app mid-tune (reported and confirmed by the line
appearing at the moment of the switch, 2026-08-11).
"""

from __future__ import annotations

import logging
import sys
import threading

import pytest

from autosound_tcc.core import app_log


@pytest.fixture
def installed(tmp_path, monkeypatch):
    monkeypatch.setattr(app_log, "log_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)
    monkeypatch.setattr(threading, "excepthook", threading.__excepthook__)
    path = app_log.setup(to_stderr=False)
    yield path
    app_log.set_ui_sink(None)
    for handler in list(app_log.logger().handlers):
        handler.close()
        app_log.logger().removeHandler(handler)


def test_an_unhandled_exception_goes_to_the_file_and_not_to_stderr(installed, capsys):
    try:
        raise ValueError("a delay of -3 ms")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    assert "a delay of -3 ms" in installed.read_text(encoding="utf-8")
    assert "Traceback" in installed.read_text(encoding="utf-8")
    assert capsys.readouterr().err == ""


def test_a_library_warning_lands_in_the_file_instead_of_the_first_screen(installed, capsys):
    """The first line of a fresh install used to be `pydantic_settings` complaining, through
    `mcp`, about a field named `lifespan` — three lines of somebody else's jargon, nothing of ours
    involved, and it reads as "this is broken". Captured, not filtered: an ignore rule would
    swallow the next real warning from the same category and nobody would think to check."""
    import warnings

    warnings.warn("a forward reference nobody here can fix", UserWarning)

    assert "a forward reference nobody here can fix" in installed.read_text(encoding="utf-8")
    assert capsys.readouterr().err == "", "the terminal is the one place it must not appear"


def test_the_window_is_told_so_a_failure_is_not_silent(installed):
    seen = []
    app_log.set_ui_sink(lambda message, path: seen.append((message, path)))
    try:
        raise RuntimeError("REW went away")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())

    assert seen == [("RuntimeError: REW went away", installed)]


def test_a_failing_sink_cannot_mask_the_error_it_was_reporting(installed):
    app_log.set_ui_sink(lambda message, path: (_ for _ in ()).throw(RuntimeError("sink died")))
    try:
        raise ValueError("the original")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    text = installed.read_text(encoding="utf-8")
    assert "the original" in text and "sink died" in text


def test_ctrl_c_is_a_decision_not_a_defect(installed, capsys):
    """KeyboardInterrupt keeps the default hook: it belongs on the terminal, where the person who
    pressed it is looking."""
    try:
        raise KeyboardInterrupt
    except KeyboardInterrupt:
        sys.excepthook(*sys.exc_info())

    assert "KeyboardInterrupt" in capsys.readouterr().err
    assert "KeyboardInterrupt" not in installed.read_text(encoding="utf-8")


def test_a_thread_that_dies_is_logged_too(installed):
    seen = []
    app_log.set_ui_sink(lambda message, path: seen.append(message))

    def boom():
        raise OSError("port 4735 refused")

    thread = threading.Thread(target=boom, name="rew-ping")
    thread.start()
    thread.join()

    text = installed.read_text(encoding="utf-8")
    assert "rew-ping" in text and "port 4735 refused" in text
    assert seen == ["OSError: port 4735 refused"]


def test_an_unwritable_log_directory_still_leaves_a_working_app(tmp_path, monkeypatch):
    """A machine where the log cannot be written is a machine where TCC still has to open."""
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(app_log, "log_dir", lambda: blocked / "logs")
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)

    path = app_log.setup(to_stderr=False)

    assert path is None
    # ...and with nowhere to write, the messages go back to stderr rather than nowhere at all.
    assert any(isinstance(h, logging.StreamHandler) for h in app_log.logger().handlers)
    for handler in list(app_log.logger().handlers):
        app_log.logger().removeHandler(handler)
