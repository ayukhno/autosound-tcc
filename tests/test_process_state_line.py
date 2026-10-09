"""The plan's guard, out of the window (`process_state_line.Unread`; #176, Task 24's review M2):
a `process-state.json` that is there and does not read keeps the plan, and says so once per state
of the file. Over files a real `Process` wrote, with a strip that writes down what it was told."""

from __future__ import annotations

import pytest

from autosound_tcc.core import vendor_loader
from autosound_tcc.state import process_view
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.process_state_line import Unread
from tests._fresh import qt_loaded

pytestmark = pytest.mark.skipif(
    not vendor_loader.is_available(), reason="rew_tool submodule not checked out"
)


class _Strip:
    """The two calls the guard makes on the window's strip, written down."""

    def __init__(self) -> None:
        self.told: list = []

    def notify(self, text, level="info", **_kw) -> None:
        self.told.append(("said", text, level))

    def withdraw(self, text) -> None:
        if text:
            self.told.append(("withdrawn", text))


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(tmp_path))
    process = vendor_loader.load_process().Process(str(process_view.process_dir(tmp_path)))
    process.enter_phase("-1")
    return tmp_path


def test_the_guard_imports_no_qt():
    assert qt_loaded("""
        from autosound_tcc.ui.tcc import process_state_line
        process_state_line.Unread()
    """) == "[]"


def test_each_state_of_the_file_is_said_once_and_taken_back_when_it_reads(project,
                                                                         app_log_warnings):
    path = process_view.state_file(project)
    good = path.read_bytes()
    guard, strip = Unread(), _Strip()

    path.write_text("{ half", encoding="utf-8")
    assert guard.stops(strip, process_view.load_state(project), project)
    assert guard.stops(strip, process_view.load_state(project), project), "still: still stops"
    half = i18n.t("processStateUnread").format(why=process_view.unreadable(project))
    assert strip.told == [("said", half, "warn")], "once per state, not per refresh"
    path.write_text("[]", encoding="utf-8")
    assert guard.stops(strip, process_view.load_state(project), project)
    listed = i18n.t("processStateUnread").format(why=process_view.unreadable(project))
    assert strip.told[1:] == [("withdrawn", half), ("said", listed, "warn")]
    assert len(app_log_warnings) == 2 and str(path) in app_log_warnings[0].getMessage()

    path.write_bytes(good)
    assert not guard.stops(strip, process_view.load_state(project), project)
    assert strip.told[-1] == ("withdrawn", listed) and len(app_log_warnings) == 2
    assert path.read_bytes() == good, "read, never written or moved aside (R-bw)"


def test_no_file_is_no_stop_and_a_file_that_reads_stops_in_silence(project, app_log_warnings):
    """No file is a fresh project: the refresh goes on to say «no plan yet». A file that reads
    while the state is None — the method did not load — stops as the guard always did, and has
    nothing to say about the file."""
    guard, strip = Unread(), _Strip()

    assert guard.stops(strip, None, project), "there, and no state: the plan stays"
    process_view.state_file(project).unlink()
    assert not guard.stops(strip, None, project)
    assert strip.told == [] and app_log_warnings == []
