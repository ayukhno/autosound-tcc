"""The window's side of the intake form: the menu line, one form per window, stopped on close."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.core import config, intake_form  # noqa: E402
from autosound_tcc.core.contract_check import ContractReport  # noqa: E402
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



def _report(complete=True):
    return ContractReport(ok=True, project_dir="/p", complete=complete)


def _offers(window, monkeypatch):
    said = []
    monkeypatch.setattr(window._status_strip, "notify",
                        lambda text, level="info", action=None: said.append((text, action)))
    return said


def test_a_green_gate_offers_the_session_once(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    said = _offers(window, monkeypatch)
    window._on_gate_result(_report())
    window._on_gate_result(_report())
    offers = [s for s in said if s[1] is not None]
    assert len(offers) == 1 and offers[0][0] == i18n.t("intakeReady")


def test_the_offer_returns_after_the_gate_went_red_and_green_again(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    said = _offers(window, monkeypatch)
    window._on_gate_result(_report())
    window._on_gate_result(_report(complete=False))
    window._on_gate_result(_report())
    assert len([s for s in said if s[1] is not None]) == 2


def test_no_offer_while_a_session_runs(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    said = _offers(window, monkeypatch)
    window._agent_worker = object()
    try:
        window._on_gate_result(_report())
    finally:
        window._agent_worker = None
    assert said == []


def test_no_gate_check_for_a_form_never_opened(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    built = []
    monkeypatch.setattr(main_window, "_ContractWorker", lambda *a, **k: built.append(a))
    window._check_intake_gate()
    assert built == []


def test_the_offer_starts_the_in_app_session(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    started = []
    monkeypatch.setattr(window, "_start_tuning_session", lambda *a, **k: started.append(1))
    window._intake_terminal_cli = None
    window._start_after_intake()
    assert started == [1]


def test_the_offer_starts_the_terminal_the_project_was_created_with(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    launched = []
    monkeypatch.setattr(main_window.terminal_launcher, "launch",
                        lambda project_dir, cli, hint, model=None: launched.append((cli, hint, model)))
    window._intake_terminal_cli, window._intake_terminal_model = "claude", "opus"
    window._start_after_intake()
    cli, hint, model = launched[0]
    assert (cli, model) == ("claude", "opus")
    assert i18n.language_name() in hint


class _Dialog:
    def __init__(self, project_dir, cli=None):
        from PySide6.QtWidgets import QDialog
        self._accepted = QDialog.DialogCode.Accepted
        self.project_dir = project_dir
        self.open_terminal_cli, self.onboarding_ai_model = cli, ("opus" if cli else None)
        self.in_app_model, self.seeded, self.seeded_from = None, None, None

    def exec(self):
        return self._accepted


class _NewWindow:
    made = []

    def __init__(self):
        self.calls = []
        _NewWindow.made.append(self)
        self._status_strip = type("S", (), {"notify": lambda *a, **k: None})()

    def show(self):
        self.calls.append("show")

    def _adopt_choices_from_new_project(self, dialog):
        self.calls.append("adopt")

    def _open_intake_form(self):
        self.calls.append("intake")


def test_create_opens_the_new_window_on_the_form(tmp_path, monkeypatch):
    window, _ = _window(tmp_path, monkeypatch)
    _NewWindow.made = []
    monkeypatch.setattr(main_window, "NewProjectDialog",
                        lambda parent, seed_first=False: _Dialog(tmp_path / "n", cli="claude"))
    monkeypatch.setattr(main_window, "MainWindow", _NewWindow)
    monkeypatch.setattr(main_window, "_force_project_dir_env", lambda p: None)
    launched = []
    monkeypatch.setattr(main_window.terminal_launcher, "launch",
                        lambda *a, **k: launched.append(a))
    monkeypatch.setattr(window, "close", lambda: True)
    window._open_new_project_dialog()
    new = _NewWindow.made[0]
    assert new.calls == ["show", "adopt", "intake"]
    assert (new._intake_terminal_cli, new._intake_terminal_model) == ("claude", "opus")
    assert launched == [], "the terminal waits for the gate, it does not start at Create"


def test_the_dsp_section_shows_the_configuration_in_the_processor(tmp_path, monkeypatch):
    """F-070, placed by the Arbiter on 2026-09-23 in the left column's DSP header «як поточний в
    процесорі»: `v_NNN` with a yellow dot while anything is only proposed and a green one once all
    of it is entered; the processor's name is on the hover."""
    from types import SimpleNamespace

    window, _ = _window(tmp_path, monkeypatch)
    profile = {"dsp_profile": {"vendor": "Audiotec-Fischer", "name": "Helix DSP Ultra S"}}
    view = SimpleNamespace(version="v_008", preset="SQ", state="proposed",
                           status_counts=(("applied", 9), ("proposed", 1)))
    window._show_version(view, profile)
    section = window._dsp_section
    assert section.sub_text() == "v_008"
    assert section.dot_status() == "wait"
    view.state = "applied"
    window._show_version(view, profile)
    assert section.dot_status() == "done"
    assert "Helix DSP Ultra S" in section._sub_label.toolTip()


def test_unusable_captures_are_one_line_with_the_rest_behind_a_link(tmp_path, monkeypatch):
    """Finding 29: sixteen UNUSABLE lines took half the window and could not be closed."""
    window, _ = _window(tmp_path, monkeypatch)
    said = []
    monkeypatch.setattr(window._status_strip, "notify",
                        lambda text, level="info", action=None, dismissible=False, on_dismiss=None:
                        said.append((text, level, action, dismissible, on_dismiss)))
    monkeypatch.setattr(main_window.process_view, "load_state", lambda *a, **k: None)
    lines = "\n".join(f"UNUSABLE sw_{n} (sw) — No measurement titled 'sw_{n} (sw)'" for n in range(1, 17))
    window._on_capture_check_done(lines)
    text, level, action, dismissible, on_dismiss = said[-1]
    assert "<br>" not in text and "16" in text and "sw_1 (sw)" in text
    assert action is not None and dismissible
    on_dismiss()
    window._on_capture_check_done(lines)
    assert len(said) == 1, "a list closed by hand does not come back until it changes"
    window._on_capture_check_done(lines + "\nUNUSABLE sw_17 (sw) — gone")
    assert len(said) == 2


def test_done_on_the_capture_card_follows_the_open_round_and_signals_the_ai(tmp_path, monkeypatch):
    """Finding 31: «Готово» hands what was just captured to the AI — disabled until the open
    round has taken something, and a SIGNAL, so a terminal session gets it too."""
    from types import SimpleNamespace

    window, _ = _window(tmp_path, monkeypatch)
    round_ = {"id": "cap_006", "taken": {}}
    monkeypatch.setattr(main_window.process_view, "capture_round", lambda *a, **k: round_)
    window._sync_capture_ready()
    assert not window._capture_ready_btn.isEnabled()
    round_["taken"] = {"m-L_1 (sw)": {}, "m-R_1 (sw)": {}}
    window._sync_capture_ready()
    assert window._capture_ready_btn.isEnabled()

    pushed = []
    bus = SimpleNamespace(push=lambda kind, **payload: pushed.append((kind, payload)),
                          pending_count=0, unacked_brief=lambda: "", is_open=lambda _id: False)
    # Through monkeypatch, so the fake server leaves with the test: assigned directly, it stayed
    # on a window a later test's timer then reached (found by the full run, 2026-09-22).
    monkeypatch.setattr(window, "_mcp_server", SimpleNamespace(bus=bus))
    monkeypatch.setattr(window, "_nudge_for_open_signals", lambda: pushed.append("nudged"))
    window._on_capture_ready()
    kind, payload = pushed[0]
    assert kind == main_window.signal_bus.CAPTURE_READY
    assert payload == {"round": "cap_006", "titles": ["m-L_1 (sw)", "m-R_1 (sw)"]}
    assert pushed[-1] == "nudged"


def test_a_reviewer_refused_by_region_turns_the_closed_picker_red(tmp_path, monkeypatch):
    """Finding 20: the refused reviewer was red in the open list and plain in the closed picker."""
    from types import SimpleNamespace

    from autosound_tcc.core import availability

    choice = SimpleNamespace(key="agy:gemini-3.1-pro-high", available=True, harness="agy")
    window, _ = _window(tmp_path, monkeypatch)
    combo = main_window.QComboBox()
    combo.addItem("AGY · Gemini 3.1 Pro (High)", choice.key)
    monkeypatch.setattr(availability, "status",
                        lambda c: availability.Status(False, availability.LOCATION))
    main_window._mark_missing(combo, [choice])
    assert "is-missing" in combo.property("class")
    monkeypatch.setattr(availability, "status",
                        lambda c: availability.Status(False, availability.NOT_CHECKED))
    main_window._mark_missing(combo, [choice])
    assert "is-missing" not in combo.property("class"), "not checked is not refused"
