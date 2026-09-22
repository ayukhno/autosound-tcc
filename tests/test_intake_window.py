"""The window's side of the intake form: the menu line, one form per window, stopped on close."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import config, intake_form  # noqa: E402
from autosound_tcc.ui.tcc import i18n, main_window  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


class _FakeForm:
    made = []

    def __init__(self, project_dir, lang, **_kw):
        self.project_dir, self.lang = project_dir, lang
        self.opens, self.stopped, self.was_opened = 0, 0, False
        self.error = None
        _FakeForm.made.append(self)

    def open_url(self):
        if self.error:
            raise self.error
        self.opens += 1
        self.was_opened = True
        return "http://127.0.0.1:45678/"

    def stop(self):
        self.stopped += 1


def _window(tmp_path, monkeypatch):
    _app()
    _FakeForm.made = []
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(intake_form, "IntakeForm", _FakeForm)
    opened = []
    monkeypatch.setattr(main_window.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toString()) or True))
    return main_window.MainWindow(), opened


def test_the_menu_line_opens_the_form_in_the_interface_language(tmp_path, monkeypatch):
    window, opened = _window(tmp_path, monkeypatch)
    window._intake_action.trigger()
    assert opened == ["http://127.0.0.1:45678/"]
    form = _FakeForm.made[0]
    assert form.project_dir == tmp_path and form.lang == i18n.current_language()


def test_a_second_click_reuses_the_same_form(tmp_path, monkeypatch):
    window, opened = _window(tmp_path, monkeypatch)
    window._intake_action.trigger()
    window._intake_action.trigger()
    assert len(_FakeForm.made) == 1 and _FakeForm.made[0].opens == 2


def test_a_method_without_the_form_says_so_in_the_strip(tmp_path, monkeypatch):
    window, opened = _window(tmp_path, monkeypatch)
    said = []
    monkeypatch.setattr(window._status_strip, "notify",
                        lambda text, level="info", action=None: said.append((text, level)))
    window._open_intake_form()
    _FakeForm.made[0].error = intake_form.IntakeFormError("no_form", "/x/intake_form.py")
    window._open_intake_form()
    assert said[-1] == (i18n.t("intakeNoForm"), "warn")


def test_closing_the_window_stops_the_form(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    window._open_intake_form()
    window.close()
    assert _FakeForm.made[0].stopped >= 1
