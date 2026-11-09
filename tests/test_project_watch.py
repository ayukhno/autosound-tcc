"""#225: the project folder watcher ignores TCC's own `.tcc/`; a project file still reloads.

The real slot is called on a stand-in host (no window is built); it reaches the project folder
through `config.chosen_project_dir`.
"""

import pytest

from types import SimpleNamespace

from PySide6.QtCore import QFileSystemWatcher
from PySide6.QtWidgets import QApplication

from autosound_tcc.core import config
from autosound_tcc.ui.tcc import process_watch, project_watch
from autosound_tcc.ui.tcc.main_window import MainWindow


class _Timer:
    def __init__(self):
        self.starts = 0

    def start(self):
        self.starts += 1


class _Host:
    """What the slot touches: the re-arm, the reload timer, and the listing kept on the host."""

    def __init__(self):
        self._project_reload = _Timer()

    def _arm_project_watcher(self):
        pass


@pytest.fixture
def armed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    (tmp_path / "project.json").write_text("{}")
    host = _Host()
    project_watch.watch_folder(host, tmp_path)  # as `_watched_project_dirs` does, `state/` missing
    return host, tmp_path


def test_own_tcc_write_triggers_no_reload(armed):
    host, folder = armed
    (folder / ".tcc").mkdir()
    (folder / ".tcc" / "settings.json").write_text("{}")
    MainWindow._on_project_file_changed(host, str(folder))
    assert host._project_reload.starts == 0


def test_project_file_change_still_reloads(armed):
    host, folder = armed
    (folder / "dsp_profile.json").write_text("{}")
    MainWindow._on_project_file_changed(host, str(folder))
    MainWindow._on_project_file_changed(host, str(folder / "project.json"))
    assert host._project_reload.starts == 2


def test_each_new_file_reloads_once_and_a_quiet_event_does_not(armed):
    """The listing is re-noted on every call: new file, nothing new, another new file -> 2 starts."""
    host, folder = armed
    (folder / "a.txt").write_text("1")
    MainWindow._on_project_file_changed(host, str(folder))
    MainWindow._on_project_file_changed(host, str(folder))
    (folder / "b.txt").write_text("2")
    MainWindow._on_project_file_changed(host, str(folder))
    assert host._project_reload.starts == 2


def test_an_edited_glossary_reloads_and_a_tcc_write_still_does_not(armed):
    """The intake gate reads `glossary.json`, which is not watched as a file (contract.py)."""
    host, folder = armed
    glossary = folder / "glossary.json"
    glossary.write_text("{}")
    MainWindow._on_project_file_changed(host, str(folder))  # appeared: listing changed
    assert host._project_reload.starts == 1
    glossary.write_text('{"a": "bb"}')  # same entries, new content
    MainWindow._on_project_file_changed(host, str(folder))
    assert host._project_reload.starts == 2
    (folder / ".tcc").mkdir()
    (folder / ".tcc" / "settings.json").write_text("{}")
    MainWindow._on_project_file_changed(host, str(folder))
    assert host._project_reload.starts == 2


# ---- a watch Qt refused (#246): one log line, and nothing on the screen ----


def _refused(app_log_warnings) -> list[str]:
    return [r.getMessage() for r in app_log_warnings if "not-there" in r.getMessage()]


def test_a_plan_watch_qt_refused_is_logged(tmp_path, app_log_warnings):
    QApplication.instance() or QApplication([])
    watch = process_watch.StateWatch(QFileSystemWatcher(), lambda: None)

    watch._hold([], {str(tmp_path / "not-there")})

    assert len(_refused(app_log_warnings)) == 1


@pytest.mark.parametrize("kind", ["file", "folder"])
def test_a_project_watch_qt_refused_is_logged(tmp_path, app_log_warnings, monkeypatch, kind):
    """The real slot on a stand-in host, which is what the file's header says it does."""
    QApplication.instance() or QApplication([])
    missing = str(tmp_path / "not-there")
    if kind == "file":  # the slot looks first: gone between that look and the add
        monkeypatch.setattr("autosound_tcc.ui.tcc.main_window.Path.exists", lambda _self: True)
    host = SimpleNamespace(_project_watcher=QFileSystemWatcher(),
                           _watched_project_files=lambda: [missing] if kind == "file" else [],
                           _watched_project_dirs=lambda: [missing] if kind == "folder" else [])

    MainWindow._arm_project_watcher(host)

    assert len(_refused(app_log_warnings)) == 1
