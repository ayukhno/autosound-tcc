"""The main AI's pick is checked when it is made, as the Critic's is (finding 160, tcc#222): the
decision as plain data (`core.generator_check`), the line beside the picker with a stand-in host
and a stand-in worker (`ui.tcc.generator_check_view`) — no window is built."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QWidget  # noqa: E402

from autosound_tcc.core import claude_sdk, codex_cli, generator_check, model_choices  # noqa: E402
from autosound_tcc.core.generator_check import Result  # noqa: E402
from autosound_tcc.core.model_choices import Choice  # noqa: E402
from autosound_tcc.ui.tcc import availability_view, i18n, main_window  # noqa: E402
from autosound_tcc.ui.tcc.generator_check_view import GeneratorCheckView  # noqa: E402
from autosound_tcc.ui.tcc.main_window import MainWindow  # noqa: E402

LUNA = Choice(harness="codex", model="gpt-6-luna", label="GPT-6-Luna", provider="openai")
ASTRA = Choice(harness="codex", model="gpt-6-astra", label="GPT-6-Astra", provider="openai")
OPUS = Choice(harness="sdk", model="claude-opus-5-5", label="Claude Opus 5.5", provider="anthropic")
OMP = Choice(harness="omp", model="google/gemini-3.1-pro-preview", label="Gemini", provider="google")


@pytest.fixture(autouse=True)
def _english():
    i18n.set_language("en")


class _Worker(QObject):
    """Stands in for `GeneratorCheckWorker`: started, then answered by the test."""

    done = Signal(object)
    finished = Signal()
    made: list = []

    def __init__(self, choice) -> None:
        super().__init__()
        self.choice = choice
        self.started = False
        _Worker.made.append(self)

    def start(self) -> None:
        self.started = True

    def answer(self, state: str) -> None:
        self.done.emit(Result(self.choice.key, state, at=0.0))
        self.finished.emit()


class _Host:
    """The window's three methods the view asks of it."""

    def __init__(self) -> None:
        self.pick = None
        self.reloads = 0
        self.tints = 0

    def _generator_choice(self):
        return self.pick

    def _reload_model_choices(self) -> None:
        self.reloads += 1

    def _refresh_main_warning(self) -> None:
        self.tints += 1


@pytest.fixture
def view():
    QApplication.instance() or QApplication([])
    _Worker.made = []
    host = _Host()
    return host, GeneratorCheckView(host, worker=_Worker)


def _said(shown_view) -> str:
    """The whole line, as the label holds it before eliding cuts it to the width it is given."""
    return shown_view.label._full


def _pick(host, shown_view, choice) -> None:
    host.pick = choice
    shown_view.picked(choice)


# --- the pick triggers the check -------------------------------------------------------------------


def test_picking_the_main_ai_starts_a_check_of_that_pick(view):
    host, shown = view

    _pick(host, shown, LUNA)

    assert [w.choice.key for w in _Worker.made] == [LUNA.key]
    assert _Worker.made[0].started
    assert _said(shown) == "checking…"


def test_a_route_with_no_cheap_check_says_not_checked_and_is_never_green(view):
    host, shown = view

    _pick(host, shown, OMP)

    assert _Worker.made == [], "omp lists every provider's catalogue, not this login's"
    assert _said(shown) == "not checked"
    assert not shown.ok()


# --- the result is shown beside the pick -----------------------------------------------------------


def test_the_answer_is_shown_beside_the_pick_and_frames_it_green(view):
    host, shown = view
    _pick(host, shown, LUNA)

    _Worker.made[0].answer(generator_check.LISTED)

    assert _said(shown).startswith("on this login · ")
    assert shown.ok()
    assert host.reloads == 1, "the lists the check read reach the pickers"
    combo = QComboBox()
    combo.addItem("CODEX · GPT-6-Luna", LUNA.key)
    availability_view.mark_missing(combo, [LUNA], ok=shown.ok())
    assert "is-ok" in combo.property("class")


def test_a_pick_this_login_does_not_list_reads_red_not_green(view):
    host, shown = view
    _pick(host, shown, LUNA)

    _Worker.made[0].answer(generator_check.NOT_LISTED)

    assert _said(shown) == "not on this login"
    assert "kv-warn" in shown.label.property("class")
    assert not shown.ok()


# --- a stale answer for an old pick is ignored -----------------------------------------------------


def test_an_answer_for_an_earlier_pick_does_not_paint_the_new_one(view):
    host, shown = view
    _pick(host, shown, LUNA)
    _pick(host, shown, ASTRA)  # while Luna's check still runs
    assert len(_Worker.made) == 1, "one check at a time"

    _Worker.made[0].answer(generator_check.LISTED)  # Luna's, late

    assert not shown.ok()
    assert host.reloads == 0
    assert [w.choice.key for w in _Worker.made] == [LUNA.key, ASTRA.key], "Astra asked next"
    assert _said(shown) == "checking…"
    _Worker.made[1].answer(generator_check.NOT_LISTED)
    assert _said(shown) == "not on this login"


def test_checks_keep_only_the_answer_for_the_pick_on_screen():
    checks = generator_check.Checks()
    assert checks.picked(LUNA) == LUNA.key
    assert checks.picked(ASTRA) is None

    assert not checks.answered(Result(LUNA.key, generator_check.LISTED), current=ASTRA.key)
    assert checks.result is None
    assert checks.ended(ASTRA) == ASTRA.key


# --- what each route is asked ----------------------------------------------------------------------


def test_codex_is_asked_its_list_for_this_login(monkeypatch):
    monkeypatch.setattr(model_choices, "read_route_list", lambda harness: ([LUNA], ""))
    monkeypatch.setattr(codex_cli, "signed_in", lambda: True)

    assert generator_check.run(LUNA).state == generator_check.LISTED
    assert generator_check.run(ASTRA).state == generator_check.NOT_LISTED


def test_a_signed_out_codex_is_sign_in_not_a_missing_model(monkeypatch):
    monkeypatch.setattr(model_choices, "read_route_list", lambda harness: ([], "no login"))
    monkeypatch.setattr(codex_cli, "signed_in", lambda: False)

    assert generator_check.run(LUNA).state == generator_check.SIGN_IN


def test_claude_is_asked_its_login_then_its_list(monkeypatch):
    asked = []
    monkeypatch.setattr(claude_sdk, "probe_signed_in", lambda force=False: asked.append(force))
    monkeypatch.setattr(claude_sdk, "signed_in", lambda reviewer=False: True)
    monkeypatch.setattr(model_choices, "read_route_list", lambda harness: ([OPUS], ""))

    assert generator_check.run(OPUS).state == generator_check.LISTED
    assert asked == [True]


def test_a_list_that_did_not_come_is_not_checked_with_its_reason(monkeypatch):
    monkeypatch.setattr(claude_sdk, "probe_signed_in", lambda force=False: None)
    monkeypatch.setattr(claude_sdk, "signed_in", lambda reviewer=False: None)
    monkeypatch.setattr(model_choices, "read_route_list", lambda harness: ([], "no answer in 15 s"))

    result = generator_check.run(OPUS)
    said = generator_check.shown(OPUS, result, checking=False)

    assert result.state == generator_check.UNREAD
    assert said.note == "mainCheckNotChecked" and said.frame == ""
    assert "no answer in 15 s" in i18n.t(said.tip).format(**said.args)


def test_the_list_the_check_reads_is_the_pickers_own(tmp_path, monkeypatch):
    """No second registry: what `claude` listed at the pick is what the picker's rows are read from."""
    monkeypatch.setenv("AUTOSOUND_TCC_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(model_choices, "_CLI_CACHE", {})
    monkeypatch.setattr(model_choices, "_UNCONFIRMED", set())
    monkeypatch.setattr(model_choices, "_ask_claude_models", lambda: [OPUS])

    rows, why = model_choices.read_route_list("sdk")

    assert (rows, why) == ([OPUS], "")
    assert model_choices._CLI_CACHE["sdk-cli"] == [OPUS]


# --- the group review's round (Gemini Argon, checked against the tree) ----------------------------


class _WindowHost(QWidget):
    """The window's own reload, pick and tint, borrowed onto a stand-in: the real path a check's
    answer takes into the pickers, with no full window built (the ratchet). The registry is the
    test's list — what the route's list for this login turned out to be."""

    _reload_model_choices = MainWindow._reload_model_choices
    _generator_choice = MainWindow._generator_choice
    _refresh_main_warning = MainWindow._refresh_main_warning
    _fill_combo = staticmethod(MainWindow._fill_combo)

    def __init__(self, generator: str) -> None:
        super().__init__()
        self.settings = {main_window._GENERATOR_KEY: generator}
        self.offered: list = []
        self._ai_main_combo = QComboBox(self)
        self._ai_critic_combo = QComboBox(self)
        self._ai_effort_combo = QComboBox(self)
        self._main_warn = QLabel(self)
        self._main_warn_tip = SimpleNamespace(set_text=lambda _text: None)
        self._status_strip = SimpleNamespace(notify=lambda *_a, **_k: None)
        self._gen_check = GeneratorCheckView(self, worker=_Worker)

    def _active_omp(self) -> list:
        return []

    def _project_setting(self, key: str) -> str:
        return self.settings.get(key, "")

    def _set_project_setting(self, key: str, value: str) -> bool:
        self.settings[key] = value
        return True

    def _offer_replacement(self, key, entries, setting="") -> None:
        self.offered.append(key)  # the «gone» dialog, which a test must not open

    def _refresh_critic_warning(self) -> None:
        pass


@pytest.fixture
def window(monkeypatch):
    QApplication.instance() or QApplication([])
    _Worker.made = []
    registry = [LUNA, ASTRA]
    monkeypatch.setattr(model_choices, "choices", lambda _active: list(registry))
    monkeypatch.setattr(model_choices, "critic_choices", lambda _active: [])
    host = _WindowHost(LUNA.key)
    host._reload_model_choices()
    host._gen_check.picked(host._generator_choice())
    return host, registry


def _frame(host) -> str:
    return host._ai_main_combo.property("class")


def test_a_pick_the_login_does_not_list_keeps_saying_so_after_the_pickers_reload(window):
    """The answer reloads the pickers from the list it read; the pick is not in it, so the registry
    loses it and the picker keeps its key in a «missing» row. The line went blank there — the one
    thing it was for."""
    host, registry = window
    registry[:] = [ASTRA]  # what Codex's `model/list` named for this login

    _Worker.made[0].answer(generator_check.NOT_LISTED)

    assert host._ai_main_combo.currentData() == LUNA.key, "the missing row keeps the pick"
    assert _said(host._gen_check) == "not on this login"
    assert "is-missing" in _frame(host)


def test_a_pick_the_login_does_not_list_frames_the_picker_red_even_when_a_row_still_offers_it(
        window):
    """A row the login's list does not name can stay in the picker — a hand-added model, an
    alias's target: the check's red reaches the picker itself, not only the line."""
    host, _registry = window

    _Worker.made[0].answer(generator_check.NOT_LISTED)

    assert host._ai_main_combo.currentData() == LUNA.key
    assert "is-missing" in _frame(host)
    assert "is-ok" not in _frame(host)


def test_a_pick_changed_with_the_pickers_signals_blocked_drops_the_old_answer(window):
    """A reload, an accepted replacement, a new project's model: the picker moves with its signals
    blocked, and the line went on saying the previous model was on this login."""
    host, _registry = window
    _Worker.made[0].answer(generator_check.LISTED)
    assert _said(host._gen_check).startswith("on this login")

    host.settings[main_window._GENERATOR_KEY] = ASTRA.key  # as `_adopt_choices_from_new_project`
    host._reload_model_choices()

    assert host._ai_main_combo.currentData() == ASTRA.key
    assert not _said(host._gen_check).startswith("on this login")
    assert "is-ok" not in _frame(host)


def test_the_line_follows_a_language_switch(view):
    host, shown = view
    _pick(host, shown, LUNA)
    _Worker.made[0].answer(generator_check.SIGN_IN)
    try:
        i18n.set_language("uk")
        assert _said(shown) == i18n.t("availPhraseSignIn")
    finally:
        i18n.set_language("en")
    assert _said(shown) == i18n.t("availPhraseSignIn")


class _Closing(_Worker):
    """A worker that answers while the closing window waits for it — the race `stop` met."""

    def isRunning(self) -> bool:
        return True

    def isFinished(self) -> bool:
        return False

    def requestInterruption(self) -> None:
        pass

    def wait(self, _ms) -> bool:
        self.answer(generator_check.NOT_LISTED)
        return True


def test_an_answer_that_comes_while_the_window_closes_reaches_nothing(view):
    host, shown = view
    shown._make = _Closing
    _pick(host, shown, LUNA)
    said = _said(shown)

    shown.stop()

    assert host.reloads == 0, "the closing window's pickers are not reloaded"
    assert _said(shown) == said


def test_a_pick_made_again_while_another_is_checked_is_asked_again():
    """Luna, then Astra, then Luna again while Astra's check runs: Luna's answer from before is not
    a check of this pick, and it was taken as one."""
    checks = generator_check.Checks()
    checks.picked(LUNA)
    checks.answered(Result(LUNA.key, generator_check.LISTED, at=1.0), current=LUNA.key)
    checks.ended(LUNA)
    assert checks.picked(ASTRA) == ASTRA.key
    assert checks.picked(LUNA) is None, "one check at a time"

    assert not checks.answered(Result(ASTRA.key, generator_check.LISTED), current=LUNA.key)

    assert checks.ended(LUNA) == LUNA.key


def test_no_second_check_starts_until_the_first_ones_thread_has_ended():
    """The answer comes at `done`; the thread is still unwinding until `finished`. A pick between
    the two started a second thread and dropped the first one's last reference."""
    checks = generator_check.Checks()
    checks.picked(LUNA)
    checks.answered(Result(LUNA.key, generator_check.LISTED), current=LUNA.key)

    assert not checks.checking(LUNA), "answered: the line says the answer, not «checking»"
    assert checks.picked(ASTRA) is None
    assert checks.checking(ASTRA)
    assert checks.ended(ASTRA) == ASTRA.key


def test_a_pick_missing_from_a_list_read_only_in_part_is_not_checked_not_refused(monkeypatch):
    """`claude`'s list had rows that could not be read: the pick may be one of them."""
    sonnet = Choice(harness="sdk", model="claude-sonnet-5-5", label="Sonnet", provider="anthropic")
    monkeypatch.setattr(claude_sdk, "probe_signed_in", lambda force=False: None)
    monkeypatch.setattr(claude_sdk, "signed_in", lambda reviewer=False: True)
    monkeypatch.setattr(model_choices, "read_route_list", lambda harness: ([sonnet], ""))
    monkeypatch.setattr(model_choices, "_PARTIAL", {model_choices._SDK_CLI_ROUTE})

    result = generator_check.run(OPUS)
    said = generator_check.shown(OPUS, result, checking=False)

    assert result.state != generator_check.NOT_LISTED
    assert said.note == "mainCheckNotChecked" and said.frame == ""
    assert generator_check.run(sonnet).state == generator_check.LISTED
