"""The gate that stops TCC opening a folder nobody chose."""

from __future__ import annotations

import json
import os
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from autosound_tcc.core import config, model_choices, project_settings  # noqa: E402
from autosound_tcc.ui.tcc import project_gate_dialog  # noqa: E402
from autosound_tcc.ui.tcc.project_gate_dialog import (  # noqa: E402
    ProjectGateDialog,
    ensure_project_chosen,
)


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_omp(monkeypatch):
    monkeypatch.setattr(model_choices, "omp_available", lambda: False)


def test_a_chosen_project_is_not_asked_about_again():
    """The gate is for the unanswered case only; it must not interrupt every launch."""
    assert config.chosen_project_dir() is not None  # conftest points the suite at a temp project
    assert ensure_project_chosen() is True


def test_an_empty_folder_is_a_valid_new_project(tmp_path, monkeypatch):
    """Choosing a folder and creating a project are one act: the intake conversation fills it. A
    gate that decided what counts as a project would invent a rule the method does not have."""
    monkeypatch.delenv("AUTOSOUND_PROJECT_DIR", raising=False)  # env override outranks a choice
    target = tmp_path / "brand-new"
    dialog = ProjectGateDialog()
    dialog._folder_edit.setText(str(target))

    dialog._accept()

    assert dialog.folder == target
    assert target.is_dir()  # typed, not browsed: a new project is created by naming it
    assert config.chosen_project_dir() == target


def test_the_models_are_written_with_the_project_not_globally(tmp_path):
    dialog = ProjectGateDialog()
    dialog._folder_edit.setText(str(tmp_path / "car"))
    dialog._generator.setCurrentIndex(dialog._generator.findData("sdk:claude-sonnet-5"))

    dialog._accept()

    saved = project_settings.load(config.tcc_dir(dialog.folder))
    assert saved["generator"] == "sdk:claude-sonnet-5"
    assert saved["critic"]


def test_the_gate_will_not_open_without_a_folder():
    dialog = ProjectGateDialog()

    assert not dialog._buttons.button(dialog._buttons.StandardButton.Ok).isEnabled()

    dialog._folder_edit.setText("/tmp/somewhere")

    assert dialog._buttons.button(dialog._buttons.StandardButton.Ok).isEnabled()


def test_an_unwritable_path_does_not_accept(tmp_path, monkeypatch):
    """Refusing to accept leaves the typed path on screen to be fixed, which is more use than a
    dialog stacked on a dialog."""
    dialog = ProjectGateDialog()
    dialog._folder_edit.setText("/proc/definitely-not-writable/car")

    dialog._accept()

    assert dialog.folder is None
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_backing_out_of_the_gate_stops_the_launch(monkeypatch):
    """An unanswered gate must stop the launch rather than fall through to a folder nobody
    picked -- which is what used to happen, silently, on every fresh install."""
    monkeypatch.setattr(config, "chosen_project_dir", lambda: None)
    monkeypatch.setattr(ProjectGateDialog, "exec", lambda self: QDialog.DialogCode.Rejected)

    assert ensure_project_chosen() is False


def test_a_terminal_launch_from_another_folder_asks_which_project(tmp_path, monkeypatch):
    """`cd testTCC-5 && python -m autosound_tcc.app` opened testTCC-3 and said nothing, so the
    window and the person disagreed about which car they were tuning."""
    from pathlib import Path

    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import project_gate_dialog

    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path / "remembered")
    monkeypatch.setattr(project_gate_dialog, "_launched_from", lambda: tmp_path / "here")
    asked: list = []
    monkeypatch.setattr(project_gate_dialog, "ProjectGateDialog",
                        lambda parent=None, suggested=None: asked.append(suggested) or _Refused())

    project_gate_dialog.ensure_project_chosen()

    assert asked == [tmp_path / "here"]  # pre-filled with the folder you are standing in


def test_the_remembered_project_still_wins_when_you_are_standing_in_it(tmp_path, monkeypatch):
    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import project_gate_dialog

    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(project_gate_dialog, "_launched_from", lambda: tmp_path)

    assert project_gate_dialog.ensure_project_chosen() is True


def test_a_bundle_with_no_terminal_never_gets_gated(tmp_path, monkeypatch):
    """A double-clicked bundle has `cwd` of `/` or home and no tty; gating that would ask about a
    folder nobody chose, on every launch."""
    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import project_gate_dialog

    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(project_gate_dialog, "_launched_from", lambda: None)

    assert project_gate_dialog.ensure_project_chosen() is True


class _Refused:
    folder = None

    def exec(self):
        from PySide6.QtWidgets import QDialog

        return QDialog.DialogCode.Rejected


def test_standing_in_a_project_opens_it_without_asking(tmp_path, monkeypatch):
    """`cd my-car && autosound-tcc` is a choice, and a fresher one than last week's.

    It used to hit the "you are somewhere else" branch and cost an Enter to confirm the folder the
    person was already standing in (user, 2026-08-13). The gate is there to stop the window opening
    on a folder nobody picked, which this is not.
    """
    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import project_gate_dialog

    elsewhere = tmp_path / "other-car"
    elsewhere.mkdir()
    here = tmp_path / "this-car"
    (here / ".tcc").mkdir(parents=True)  # what `looks_like_project` recognises

    saved: list = []
    monkeypatch.setattr(config, "chosen_project_dir", lambda: elsewhere)
    monkeypatch.setattr(config, "set_project_dir", lambda p: saved.append(p))
    monkeypatch.setattr(project_gate_dialog, "_launched_from", lambda: here)

    def _must_not_open(*args, **kwargs):
        raise AssertionError("the gate asked about the folder the user was standing in")

    monkeypatch.setattr(project_gate_dialog, "ProjectGateDialog", _must_not_open)

    assert project_gate_dialog.ensure_project_chosen() is True
    assert saved == [here], "the folder you opened is the one it should remember next time"


def test_standing_in_an_empty_folder_still_asks(tmp_path, monkeypatch):
    """The shortcut only fires on a folder that already holds a project. An empty one is exactly
    the case the gate exists for: nothing says the person meant to start a car here."""
    from autosound_tcc.core import config
    from autosound_tcc.ui.tcc import project_gate_dialog

    remembered = tmp_path / "remembered"
    remembered.mkdir()
    empty = tmp_path / "empty"
    empty.mkdir()

    monkeypatch.setattr(config, "chosen_project_dir", lambda: remembered)
    monkeypatch.setattr(project_gate_dialog, "_launched_from", lambda: empty)

    class _RefusedDialog(_Refused):
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(project_gate_dialog, "ProjectGateDialog", _RefusedDialog)

    assert project_gate_dialog.ensure_project_chosen() is False, "should have asked, and been refused"
