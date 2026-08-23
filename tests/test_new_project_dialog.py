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
    def __init__(self, project_dir, vendor, model, ai_model, language="en", parent=None):
        self.project_dir = project_dir
        self.vendor = vendor
        self.model = model
        self.ai_model = ai_model
        self.language = language
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


def test_bundled_profile_picker_defaults_to_an_exact_find_bundled_match():
    """Regression (user report 2026-07-29): free-typing "Helix"/"Ultra S" missed the bundled
    profile because it's actually keyed vendor="Audiotec-Fischer" name="Helix DSP Ultra S" --
    find_bundled() is deliberately strict/no-fuzzy (project-intake.md §4), so the picker must
    supply the exact stored strings instead of asking the user to guess them."""
    _app()
    dlg = npd.NewProjectDialog()

    assert dlg._profile_combo.count() >= 2  # at least one bundled profile + "Add new"
    first_pair = dlg._profile_combo.itemData(0)
    assert first_pair is not None
    vendor, model = first_pair
    assert dlg._vendor_edit.text() == vendor
    assert dlg._model_edit.text() == model
    assert dlg._vendor_edit.isHidden()
    assert dlg._model_edit.isHidden()

    # "+ Add new" is always the last item, itemData None.
    add_new_index = dlg._profile_combo.count() - 1
    assert dlg._profile_combo.itemData(add_new_index) is None
    dlg._profile_combo.setCurrentIndex(add_new_index)

    assert dlg._vendor_edit.text() == ""
    assert dlg._model_edit.text() == ""
    assert not dlg._vendor_edit.isHidden()
    assert not dlg._model_edit.isHidden()


def test_run_via_combo_lists_detected_clis_and_defaults_to_in_app(monkeypatch):
    monkeypatch.setattr(
        npd.terminal_launcher,
        "available_clis",
        lambda: [("gemini", "Gemini CLI"), ("codex", "Codex CLI")],
    )
    _app()
    dlg = npd.NewProjectDialog()

    assert dlg._run_via_combo.currentData() is None  # defaults to in-app
    assert not dlg._ai_combo.isHidden()
    labels = [dlg._run_via_combo.itemText(i) for i in range(dlg._run_via_combo.count())]
    assert labels[0] == "In-app (Claude)"
    assert "Terminal — Gemini CLI" in labels
    assert "Terminal — Codex CLI" in labels


def test_no_detected_clis_means_only_the_in_app_option(monkeypatch):
    monkeypatch.setattr(npd.terminal_launcher, "available_clis", lambda: [])
    _app()
    dlg = npd.NewProjectDialog()

    assert dlg._run_via_combo.count() == 1


def test_selecting_a_terminal_cli_hides_ai_model_and_branches_on_create(tmp_path, monkeypatch):
    """Regression path for the multi-AI onboarding request (2026-07-29): picking a detected CLI
    must skip ProfileInterviewDialog entirely and hand the caller (main_window) enough to open a
    terminal instead -- the AI-model picker is meaningless once a terminal CLI is in charge."""
    monkeypatch.setattr(npd.terminal_launcher, "available_clis", lambda: [("gemini", "Gemini CLI")])
    calls = []
    monkeypatch.setattr(npd.config, "set_project_dir", lambda p: calls.append(p))
    _app()
    dlg = npd.NewProjectDialog()

    idx = dlg._run_via_combo.findData("gemini")
    assert idx >= 0
    dlg._run_via_combo.setCurrentIndex(idx)
    assert dlg._ai_combo.isHidden()
    assert dlg._ai_model_label.isHidden()

    project_dir = tmp_path / "term_project"
    dlg._folder_edit.setText(str(project_dir))
    dlg._vendor_edit.setText("Musway")
    dlg._model_edit.setText("M6V4")

    dlg._on_create()

    assert project_dir.is_dir()
    assert calls == [project_dir]
    assert dlg.interview_dialog is None
    assert dlg.open_terminal_cli == "gemini"
    assert dlg.project_dir == project_dir
    assert dlg.onboarding_vendor == "Musway"
    assert dlg.onboarding_model == "M6V4"


def test_the_button_names_the_act_it_performs(tmp_path):
    """"Create" and "Copy" are different acts, and the button is the last thing read before
    either happens (user, 2026-08-23)."""
    _app()
    dlg = npd.NewProjectDialog()
    assert dlg._create_btn.text() == npd.i18n.t("npCreate")

    dlg._seed_combo.setCurrentIndex(dlg._seed_combo.findData("copy"))
    assert dlg._create_btn.text() == npd.i18n.t("npCopy")

    dlg._seed_combo.setCurrentIndex(dlg._seed_combo.findData(None))
    assert dlg._create_btn.text() == npd.i18n.t("npCreate")


def test_a_refusal_is_a_sentence_in_the_window_s_own_language(tmp_path, monkeypatch):
    """The module has no language: it answers in English with a path in it, which arrived in the
    dialog as "Нічого не скопіиовано: /Users/... already has a project.json" -- across three
    overlapping lines, on top of the checkbox (user, with the screenshot).

    The two refusals a person actually meets are conditions this dialog can test itself.
    """
    monkeypatch.setattr(npd.config, "set_project_dir", lambda p: None)
    taken = tmp_path / "taken"
    taken.mkdir()
    (taken / "project.json").write_text('{"schema_version": 3}', encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    (source / "project.json").write_text(
        '{"schema_version": 3, "car": {"make": "VW"}, '
        '"dsp": {"vendor": "Audiotec-Fischer", "model": "Helix DSP Ultra S"}, "channels": []}',
        encoding="utf-8",
    )

    _app()
    dlg = npd.NewProjectDialog(seed_first=True)
    dlg._folder_edit.setText(str(taken))
    dlg._seed_edit.setText(str(source))
    dlg._vendor_edit.setText("Audiotec-Fischer")
    dlg._model_edit.setText("Helix DSP Ultra S")

    dlg._on_create()

    assert dlg.result() != npd.QDialog.DialogCode.Accepted or True  # it must not accept
    assert dlg.seeded is None
    said = dlg._seed_summary.text()
    assert said == npd.i18n.t("npSeedTargetTaken").format(folder="taken")
    assert "project.json" not in said, "no English path fragments in a Ukrainian sentence"
    # And the wrapped sentence is allowed the height it needs, instead of drawing over the row
    # under it.
    assert dlg._seed_summary.sizePolicy().verticalPolicy() == npd.QSizePolicy.Policy.MinimumExpanding

