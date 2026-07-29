"""NewProjectDialog: folder + vendor/model + AI model, then hands off to (a faked)
ProfileInterviewDialog -- the real one spins up a Claude Agent SDK session, which has no place in
a headless unit test.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc import new_project_dialog as npd  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _FakeInterviewDialog:
    def __init__(self, project_dir, vendor, model, ai_model, parent=None):
        self.project_dir = project_dir
        self.vendor = vendor
        self.model = model
        self.ai_model = ai_model
        self.parent_arg = parent


def test_create_disabled_until_folder_vendor_and_model_are_filled(tmp_path):
    _app()
    dlg = npd.NewProjectDialog()
    dlg._folder_edit.setText(str(tmp_path))
    dlg._vendor_edit.setText("")
    dlg._model_edit.setText("")
    assert not dlg._create_btn.isEnabled()

    dlg._vendor_edit.setText("Musway")
    assert not dlg._create_btn.isEnabled()  # model still empty
    dlg._model_edit.setText("M6V4")
    assert dlg._create_btn.isEnabled()


def test_create_mkdirs_persists_project_dir_and_builds_the_interview(tmp_path, monkeypatch):
    _app()
    calls = []
    monkeypatch.setattr(npd.config, "set_project_dir", lambda p: calls.append(p))
    monkeypatch.setattr(npd, "ProfileInterviewDialog", _FakeInterviewDialog)

    project_dir = tmp_path / "brand_new_project"
    dlg = npd.NewProjectDialog()
    dlg._folder_edit.setText(str(project_dir))
    dlg._vendor_edit.setText("Musway")
    dlg._model_edit.setText("M6V4")

    dlg._on_create()

    assert project_dir.is_dir()  # OnboardingSession itself does not create the folder
    assert calls == [project_dir]
    assert dlg.interview_dialog is not None
    assert dlg.interview_dialog.project_dir == project_dir
    assert dlg.interview_dialog.vendor == "Musway"
    assert dlg.interview_dialog.model == "M6V4"
    assert dlg.interview_dialog.ai_model == "claude-opus-5"  # default AI_MAIN_MODELS[0]
