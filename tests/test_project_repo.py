"""The project folder as a repository, through the method's `project_repo.py` (hub #199)."""

from __future__ import annotations

import os
import subprocess

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

from autosound_tcc.core import child, config, project_repo  # noqa: E402
from autosound_tcc.ui.tcc import i18n  # noqa: E402
from tests import _hung_child  # noqa: E402


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


def _button(window, text):
    return next(b for b in window._project_section.findChildren(QPushButton) if b.text() == text)


def _backup_buttons(window):
    """The texts of the panel's «Back up to GitHub» buttons, in any step."""
    return [b.text() for b in window._project_section.findChildren(QPushButton)
            if b.text().startswith(i18n.t("gitBackupBtn"))]


def test_a_folder_without_history_offers_to_make_it_a_repository(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    window._set_project_params(None)
    calls = []
    monkeypatch.setattr(project_repo, "init", lambda project: calls.append(project) or
                        project_repo.RepoResult(True, "a first commit"))
    _button(window, "Back up to GitHub (0/2)").click()
    assert calls == [tmp_path]
    assert "a first commit" in window._status_strip.text()


def test_the_backup_button_counts_its_steps_from_the_folder(tmp_path, monkeypatch):
    """Finding 145: the backup is two steps, and the first one looked like all of it. The button
    says how far it has come — read from the folder, not counted: no repository is 0/2, a
    repository with no remote is 1/2, and a backup has no button at all."""
    window = _window(tmp_path, monkeypatch)
    window._set_project_params(None)
    assert _backup_buttons(window) == ["Back up to GitHub (0/2)"]

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    window._set_project_params(None)
    assert _backup_buttons(window) == ["Back up to GitHub (1/2)"]

    # The backup's remote is a folder next to the project: nothing is contacted, no GitHub, no gh.
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin",
                    str(tmp_path.parent / "backup.git")], check=True)
    window._set_project_params(None)
    assert _backup_buttons(window) == []


_FIRST_STEP = {
    "en": ("Back up to GitHub (0/2)", "Step 1 of 2 done: {said}\nNext: press «Back up to GitHub "
           "(1/2)» again to create the private copy on GitHub.", "Back up to GitHub (1/2)"),
    "uk": ("Копія на GitHub (0/2)", "Крок 1 з 2 зроблено: {said}\nДалі: натисни «Копія на GitHub "
           "(1/2)» ще раз, щоб створити приватну копію на GitHub.", "Копія на GitHub (1/2)"),
}


@pytest.mark.parametrize("lang", sorted(_FIRST_STEP))
def test_the_first_step_says_what_comes_next(tmp_path, monkeypatch, lang):
    """Finding 145: after the first press the line said «Done: … is a git repository now, first
    commit made» and nothing about a second press, and «Backup: none» stayed."""
    before, line, after = _FIRST_STEP[lang]
    said = f"✓ {tmp_path} is a git repository now, first commit made"

    def init(project):
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        return project_repo.RepoResult(True, said)

    monkeypatch.setattr(project_repo, "init", init)
    window = _window(tmp_path, monkeypatch)
    i18n.set_language(lang)  # after the window: it starts in the language of its settings
    try:
        window._set_project_params(None)
        _button(window, before).click()
        assert window._status_strip.text() == line.format(said=said)
        assert _backup_buttons(window) == [after]
    finally:
        i18n.set_language("en")


def test_the_second_step_does_not_say_there_is_a_next(tmp_path, monkeypatch):
    """The «Next:» line belongs to the first press only: after the GitHub copy is made there is
    nothing left to press, and the button is gone."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    window = _window(tmp_path, monkeypatch)
    window._set_project_params(None)
    offer = "gh repo create car --private --source . --push"
    monkeypatch.setattr(project_repo, "available", lambda: True)
    monkeypatch.setattr(project_repo, "status", lambda project: {"gh": "signed-in", "offer": offer})

    def made(o, project):
        subprocess.run(["git", "-C", str(project), "remote", "add", "origin",
                        str(project.parent / "backup.git")], check=True)
        return project_repo.RepoResult(True, "created")

    monkeypatch.setattr(project_repo, "run_offer", made)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    _button(window, "Back up to GitHub (1/2)").click()
    assert window._status_strip.text() == "Done: created"
    assert _backup_buttons(window) == []


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
    _button(window, "Back up to GitHub (1/2)").click()
    assert asked and offer in asked[0], "the command is shown whole before anything runs"
    assert ran == [], "no means nothing is created"
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    window._on_git_backup()
    assert ran == [offer]


def test_a_push_that_never_ends_is_killed_with_git_under_gh(monkeypatch, tmp_path):
    """`gh repo create … --push` runs git, and git its https helper, on gh's own pipes -- and the
    yes runs it on the GUI thread. On Windows a push past the 120 s froze the window until the
    push ended (review of #132). The tree goes at the timeout, and the row says why."""
    spawns = _hung_child.install(monkeypatch)

    result = project_repo.run_offer("gh repo create car-tune --private --source . --push", tmp_path)

    assert not result.ok and result.said.startswith("TimeoutExpired")
    [gh] = spawns.hung
    assert gh.timeouts == [project_repo._TIMEOUT_S, child.REAP_TIMEOUT_S]
    assert spawns.taskkills == [["taskkill", "/T", "/F", "/PID", str(gh.pid)]]
