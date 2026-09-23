"""The project folder as a repository, through the method's `project_repo.py` (hub #199)."""

from __future__ import annotations

import os
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

from autosound_tcc.core import config, project_repo  # noqa: E402
from autosound_tcc.ui.tcc import i18n  # noqa: E402


def test_a_method_without_the_command_says_update(tmp_path, monkeypatch):
    monkeypatch.setattr(project_repo, "script_path", lambda: tmp_path / "missing.py")
    result = project_repo.init(tmp_path)
    assert not result.ok and result.too_old
    assert project_repo.status(tmp_path) is None


def test_init_runs_the_methods_command_on_the_project(tmp_path, monkeypatch):
    script = tmp_path / "project_repo.py"
    script.write_text("import sys; print('initialised', sys.argv[1:])", encoding="utf-8")
    monkeypatch.setattr(project_repo, "script_path", lambda: script)
    result = project_repo.init(tmp_path / "car")
    assert result.ok and "init" in result.said and "car" in result.said


def test_only_a_gh_line_is_ever_run(tmp_path):
    result = project_repo.run_offer("rm -rf /", tmp_path)
    assert not result.ok and "not a gh command" in result.said


def _window(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc.main_window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: tmp_path)
    return MainWindow()


def _button(window, key):
    return next(b for b in window._project_section.findChildren(QPushButton)
                if b.text() == i18n.t(key))


def test_a_folder_without_history_offers_to_make_it_a_repository(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    window._set_project_params(None)
    calls = []
    monkeypatch.setattr(project_repo, "init", lambda project: calls.append(project) or
                        project_repo.RepoResult(True, "a first commit"))
    _button(window, "gitInitBtn").click()
    assert calls == [tmp_path]
    assert "a first commit" in window._status_strip.text()


def test_the_backup_runs_only_after_yes(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    window = _window(tmp_path, monkeypatch)
    window._set_project_params(None)
    offer = f'gh repo create car --private --source "{tmp_path}" --push'
    monkeypatch.setattr(project_repo, "available", lambda: True)
    monkeypatch.setattr(project_repo, "status", lambda project: {"gh": "signed-in", "offer": offer})
    ran = []
    monkeypatch.setattr(project_repo, "run_offer", lambda o, p: ran.append(o) or
                        project_repo.RepoResult(True, "created"))
    asked = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: asked.append(self.text()) or
                        QMessageBox.StandardButton.No)
    _button(window, "gitBackupBtn").click()
    assert asked and offer in asked[0], "the command is shown whole before anything runs"
    assert ran == [], "no means nothing is created"
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    window._on_git_backup()
    assert ran == [offer]
