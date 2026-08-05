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
