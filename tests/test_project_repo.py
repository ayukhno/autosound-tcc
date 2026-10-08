"""The project folder as a repository, through the method's `project_repo.py` (hub #199)."""

from __future__ import annotations

import os
import subprocess

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

from autosound_tcc.core import child, config, method_binding, project_repo, vendor_loader  # noqa: E402
from autosound_tcc.ui.tcc import i18n  # noqa: E402
from tests import _hung_child  # noqa: E402


def _own_copy(tmp_path, monkeypatch, script: str | None = None):
    """TCC's own copy — the one a project with no entry runs (`method_binding.own_copy`, #169) — as
    a folder whose `rew_tool/project_repo.py` is `script`, or that has none: a method older than the
    command. The commands run the copy the project is bound to, so this is where a fake one goes."""
    own = tmp_path / "tccs-own"
    if script is not None:
        path = own / "rew_tool" / "project_repo.py"
        path.parent.mkdir(parents=True)
        path.write_text(script, encoding="utf-8")
    monkeypatch.setattr(method_binding, "own_copy", lambda: own)


def _nothing_starts(monkeypatch) -> None:
    """Both doors a child could take: `method_cli`'s bounded run, and the bare run — whose real
    `init` asks `gh` for an identity and whose `status` asks `gh` whether it is signed in."""
    for owner, name in ((child, "run_bounded"), (subprocess, "run")):
        monkeypatch.setattr(owner, name, lambda argv, **_kw: pytest.fail(f"a child started: {argv}"))


def test_a_method_without_the_command_says_update(tmp_path, monkeypatch):
    _own_copy(tmp_path, monkeypatch)
    _nothing_starts(monkeypatch)
    result = project_repo.init(tmp_path)
    assert not result.ok and result.too_old
    assert project_repo.status(tmp_path) is None


def test_init_runs_the_methods_command_on_the_project(tmp_path, monkeypatch):
    _own_copy(tmp_path, monkeypatch, "import sys; print('initialised', sys.argv[1:])")
    result = project_repo.init(tmp_path / "car")
    assert result.ok and "init" in result.said and "car" in result.said


def test_a_copy_tcc_will_not_run_answers_the_backup_with_its_sentence(tmp_path, monkeypatch):
    """The backup's second step reads `backup_status`, and for a project whose copy TCC will not run
    (#169) that is a failed answer carrying the binding's sentence — not a status with no `gh` in
    it, which the window read as «gh is not signed in». `status` keeps its one «cannot say», None.
    Nothing is started either way."""
    project = tmp_path / "car"
    (project / ".claude" / "skills" / vendor_loader.SKILL_NAME).mkdir(parents=True)
    _nothing_starts(monkeypatch)
    reason = method_binding.for_project(project).reason

    assert project_repo.backup_status(project) == project_repo.RepoResult(False, reason)
    assert project_repo.status(project) is None


def test_an_approved_copy_without_the_command_is_too_old_for_the_backup(tmp_path, monkeypatch):
    """A copy the project is bound to and TCC trusts, older than `project_repo.py` — the vendored
    method with that one file taken out, approved on this machine — is «update the method» for both
    steps of the backup, as TCC's own copy without it always was. Nothing is started."""
    import shutil

    if not vendor_loader._looks_like_the_skill(vendor_loader._SUBMODULE_DIR):
        pytest.skip("skill submodule not checked out")
    older = tmp_path / "older-method" / "skills" / vendor_loader.SKILL_NAME
    shutil.copytree(vendor_loader._SUBMODULE_DIR, older,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (older / "rew_tool" / "project_repo.py").unlink()
    project = tmp_path / "car"
    entry = project / ".claude" / "skills" / vendor_loader.SKILL_NAME
    entry.parent.mkdir(parents=True)
    entry.symlink_to(older, target_is_directory=True)
    binding = method_binding.approve(method_binding.for_project(project))
    assert binding.state == method_binding.APPROVED, binding.reason
    _nothing_starts(monkeypatch)

    assert project_repo.backup_status(project) == project_repo.RepoResult(False, "", too_old=True)
    assert project_repo.init(project).too_old


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
    monkeypatch.setattr(project_repo, "backup_status",
                        lambda project: {"gh": "signed-in", "offer": offer})

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
    """...and not at all for a project whose copy TCC will not run (#169): the press says the
    binding's sentence — it read «gh is not signed in» — and asks nothing."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    window = _window(tmp_path, monkeypatch)
    window._set_project_params(None)
    entry = tmp_path / ".claude" / "skills" / vendor_loader.SKILL_NAME
    entry.mkdir(parents=True)
    started = []
    with monkeypatch.context() as guard:
        # The press runs the real chain, and an entry that bound after all would start the real
        # `project_repo.py status`, which asks `gh`. Only the method's runner is barred: the panel
        # reads git through a bare `subprocess.run` (`project_view`).
        guard.setattr(child, "run_bounded", lambda argv, **_kw: started.append(argv)
                      or pytest.fail(f"a child started: {argv}"))
        _button(window, "Back up to GitHub (1/2)").click()
    assert started == [], "a child started"
    assert window._status_strip.text() == (
        f"Did not work: {method_binding.for_project(tmp_path).reason}")
    entry.rmdir()
    offer = f'gh repo create car --private --source "{tmp_path}" --push'
    monkeypatch.setattr(project_repo, "backup_status",
                        lambda project: {"gh": "signed-in", "offer": offer})
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


def test_the_no_repository_tip_names_the_button_by_its_own_label(tmp_path, monkeypatch):
    """Review of finding 145, M12: the header's tip wrote «Back up to GitHub (0/2)» out in four
    languages, so a new word for the button (the Advisor's pass on pl and de) would leave the tip
    naming a button that is not there. It takes the button's label as the button has it."""
    window = _window(tmp_path, monkeypatch)
    monkeypatch.setitem(i18n.T["en"], "gitBackupBtn", "Copy to GitHub")
    window._set_project_params(None)

    assert "«Copy to GitHub (0/2)»" in window._project_section._sub_label.toolTip()
    assert _backup_buttons(window) == ["Copy to GitHub (0/2)"]
