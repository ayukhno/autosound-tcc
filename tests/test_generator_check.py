"""The main AI's pick is checked when it is made, as the Critic's is (finding 160, tcc#222): the
decision as plain data (`core.generator_check`), the line beside the picker with a stand-in host
and a stand-in worker (`ui.tcc.generator_check_view`) — no window is built."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from autosound_tcc.core import claude_sdk, codex_cli, generator_check, model_choices  # noqa: E402
from autosound_tcc.core.generator_check import Result  # noqa: E402
from autosound_tcc.core.model_choices import Choice  # noqa: E402
from autosound_tcc.ui.tcc import availability_view, i18n  # noqa: E402
from autosound_tcc.ui.tcc.generator_check_view import GeneratorCheckView  # noqa: E402

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
