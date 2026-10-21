"""#225: the project folder watcher ignores TCC's own `.tcc/`; a project file still reloads.

The real slot is called on a stand-in host (no window is built); it reaches the project folder
through `config.chosen_project_dir`.
"""

import pytest

from autosound_tcc.core import config
from autosound_tcc.ui.tcc import project_watch
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
