"""A window's own project folder after a cancelled switch (#206, the group review's I1)."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from autosound_tcc.core import config  # noqa: E402
from autosound_tcc.ui.tcc import i18n, window_folder  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _window(said: list) -> QWidget:
    _app()
    window = QWidget()
    window._built_on = window_folder.pin()
    window._status_strip = SimpleNamespace(
        notify=lambda text, **kwargs: said.append((text, kwargs)))
    return window


def _switch(tmp_path, monkeypatch):
    new = tmp_path / "new-car"
    new.mkdir()
    monkeypatch.setenv("AUTOSOUND_PROJECT_DIR", str(new))
    return new


def test_a_window_on_its_own_folder_reads_and_writes_there(tmp_path):
    said: list = []
    window = _window(said)
    assert window_folder.ours(window, "a read")
    assert window_folder.tcc_dir(window) == config.tcc_dir()
    assert said == []


def test_after_a_switch_a_window_reads_nothing_and_says_so_on_a_line_that_stays(tmp_path,
                                                                             monkeypatch):
    """The line names both folders and is sticky: one notify that a later fact replaced, then INFO
    in the log, was the whole of it before (the group review, I1)."""
    said: list = []
    window = _window(said)
    old = window._built_on
    new = _switch(tmp_path, monkeypatch)

    for what in ("the header's reload", "a preset pick", "the contract check"):
        assert not window_folder.ours(window, what)
    assert said == [(i18n.t("projectStillShows").format(old=old, new=new),
                     {"level": "warn", "sticky": True})], said


def test_a_widget_inside_the_window_answers_for_its_window(tmp_path, monkeypatch):
    """The curve window is a child of the main one: it asks the main window's folder."""
    said: list = []
    window = _window(said)
    old = window._built_on
    child = QWidget(window)
    inner = QWidget(child)
    _switch(tmp_path, monkeypatch)

    assert window_folder.tcc_dir(inner) == config.tcc_dir(old), \
        "its writes go to the folder the window shows, where its session writes too"
    assert not window_folder.ours(inner, "the curve window's bank")
    assert len(said) == 1


def test_a_widget_with_no_pinned_window_follows_the_process(tmp_path, monkeypatch):
    _app()
    loose = QWidget()
    new = _switch(tmp_path, monkeypatch)
    assert window_folder.ours(loose, "a read")
    assert window_folder.tcc_dir(loose) == config.tcc_dir(new)


def test_may_reread_still_skips_a_closing_window(tmp_path):
    said: list = []
    window = _window(said)
    window._closing = True
    assert not window_folder.may_reread(window, "the agent's re-read")
    assert said == []
