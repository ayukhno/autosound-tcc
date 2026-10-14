"""«Open terminal in this project…» as a submenu (tcc #180, W-10 Codex task 8): Terminal, Claude,
Codex, Antigravity, OMP — a missing client greyed, the plain terminal always there, a click opens
exactly the client chosen and never another one."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from autosound_tcc.core import child, codex_cli, critic, terminal_launcher  # noqa: E402
from autosound_tcc.ui.tcc import i18n, main_menu, menu_registry, terminal_menu  # noqa: E402

LABELS = ["Claude", "Codex", "Antigravity", "OMP"]


def _app():
    return QApplication.instance() or QApplication([])


def _installed(monkeypatch, *clients):
    monkeypatch.setattr(terminal_launcher, "client_available",
                        lambda client: client == "terminal" or client in clients)


def _host(tmp_path, notes, harness="sdk", model="the-model"):
    return SimpleNamespace(
        _mcp_server=SimpleNamespace(project_dir=tmp_path),
        _generator_choice=lambda: SimpleNamespace(harness=harness, model=model),
        _status_strip=SimpleNamespace(notify=lambda text, **k: notes.append(text)),
        _control_layout=SimpleNamespace(active=False))


@pytest.fixture
def launched(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(terminal_launcher, "launch",
                        lambda project_dir, **kw: calls.append(("launch", kw)) or kw["cli"])
    monkeypatch.setattr(terminal_launcher, "open_shell",
                        lambda project_dir, **kw: calls.append(("shell", kw)))
    monkeypatch.setattr(critic, "session_env", lambda project_dir: {"ENV": "1"})
    monkeypatch.setattr(codex_cli, "find",
                        lambda **_kw: codex_cli.Found("/x/codex", codex_cli.SOURCE_PATH))
    return calls


def test_the_submenu_s_order_is_terminal_then_the_clients():
    lines = menu_registry.ordered(menu_registry.collect(), "terminal")

    assert [e.text() for e in lines] == [i18n.t("terminalPlain"), *LABELS]


def test_a_missing_client_is_greyed_and_the_terminal_never_is(monkeypatch):
    _installed(monkeypatch, "claude", "omp")
    lines = menu_registry.ordered(menu_registry.collect(), "terminal")

    assert [e.enabled(None) for e in lines] == [True, True, False, False, True]


def test_the_toolbar_button_offers_the_same_choices_refreshed_when_shown(monkeypatch, tmp_path):
    _app()
    _installed(monkeypatch)
    button = QPushButton()
    picked = []
    host = SimpleNamespace(_open_terminal=lambda client=None: picked.append(client))

    terminal_menu.attach(button, host)
    menu = button.menu()
    assert [a.text() for a in menu.actions()] == [i18n.t("terminalPlain"), *LABELS]
    assert [a.isEnabled() for a in menu.actions()] == [True, False, False, False, False]

    _installed(monkeypatch, "codex")
    menu.aboutToShow.emit()
    assert [a.isEnabled() for a in menu.actions()] == [True, False, True, False, False]

    menu.actions()[2].trigger()
    assert picked == ["codex"]


def test_the_main_menu_s_submenu_asks_again_when_it_opens(monkeypatch):
    """Availability is a stat, asked when the submenu is about to show — not once at render."""
    _app()
    from PySide6.QtWidgets import QToolButton

    _installed(monkeypatch)
    host = SimpleNamespace(_agent_worker=None)
    entries = [e for e in menu_registry.window_entries()
               if e.id == "terminal" or e.place == "terminal"]
    menu = main_menu.MainMenu(QToolButton(), host, entries=lambda: entries)
    menu.render()
    assert not menu.action("terminal_claude").isEnabled()

    _installed(monkeypatch, "claude")
    menu.action("terminal").menu().aboutToShow.emit()
    assert menu.action("terminal_claude").isEnabled()


@pytest.mark.parametrize("client, cli, model", [
    ("claude", "claude", "the-model"), ("agy", "agy", None), ("omp", "omp", None)])
def test_a_click_launches_exactly_the_client_chosen(tmp_path, launched, client, cli, model):
    notes: list[str] = []

    terminal_menu.open_in(_host(tmp_path, notes, harness="sdk"), client)

    ((kind, kw),) = launched
    assert (kind, kw["cli"], kw["model"]) == ("launch", cli, model)
    assert kw["env"] == {"ENV": "1"}
    assert notes == [i18n.t("terminalOpened").format(cli=cli)]


def test_codex_opens_the_codex_line_with_the_pick_s_model(tmp_path, launched):
    notes: list[str] = []

    terminal_menu.open_in(_host(tmp_path, notes, harness="codex", model="gpt-5.6-luna"), "codex")

    ((kind, kw),) = launched
    assert kw["cli"] == child.script_interpreter() and kw["model"] == "gpt-5.6-luna"
    assert kw["extra"] == ("-m", "autosound_tcc.core.codex_terminal", str(tmp_path))
    assert notes == [i18n.t("terminalOpened").format(cli="codex")]


def test_the_plain_terminal_starts_no_client_and_names_how_to_start_codex(tmp_path, launched):
    notes: list[str] = []

    terminal_menu.open_in(_host(tmp_path, notes), "terminal")

    ((kind, kw),) = launched
    assert kind == "shell"
    assert kw["env"] == {"ENV": "1"}
    assert "autosound_tcc.core.codex_terminal" in kw["note"]
    assert kw["note"] == terminal_menu.codex_note()
    assert kw["note"].startswith(i18n.t("codexTerminalHint").split("{")[0]), "an i18n key"
    assert notes == [i18n.t("terminalOpened").format(cli=i18n.t("terminalPlain"))]


@pytest.mark.parametrize("client", ["claude", "agy", "omp"])
def test_a_client_gone_at_click_time_is_said_and_nothing_else_opens(tmp_path, monkeypatch,
                                                                    launched, client):
    """No fallback: an explicit choice never becomes `default_cli()` or the pick's CLI."""
    def refuse(project_dir, **kw):
        launched.append(("launch", kw))
        raise terminal_launcher.TerminalLaunchError(f"{kw['cli']!r} is not on PATH")

    monkeypatch.setattr(terminal_launcher, "launch", refuse)
    notes: list[str] = []

    terminal_menu.open_in(_host(tmp_path, notes, harness="sdk"), client)

    assert [kw["cli"] for _kind, kw in launched] == [client]
    assert notes == [f"{client!r} is not on PATH"]


def test_codex_gone_at_click_time_is_said_and_nothing_else_opens(tmp_path, monkeypatch, launched):
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: None)
    notes: list[str] = []

    terminal_menu.open_in(_host(tmp_path, notes, harness="codex"), "codex")

    assert launched == []
    assert len(notes) == 1 and "Codex" in notes[0]


def test_no_client_named_opens_the_one_that_carries_the_pick(tmp_path, launched):
    """The handoff's «start in a terminal» keeps today's rule: the CLI of the current pick."""
    notes: list[str] = []

    terminal_menu.open_in(_host(tmp_path, notes, harness="omp", model="m"))

    ((_kind, kw),) = launched
    assert kw["cli"] == "omp" and kw["model"] == "m"


def test_the_launcher_never_falls_back_when_a_client_is_named(monkeypatch, tmp_path):
    """`launch(cli=…)` with a named CLI that is gone raises; `default_cli` is never asked."""
    monkeypatch.setattr(terminal_launcher, "find_cli", lambda exe: None)
    monkeypatch.setattr(terminal_launcher, "default_cli",
                        lambda: pytest.fail("an explicit choice fell back"))

    with pytest.raises(terminal_launcher.TerminalLaunchError):
        terminal_launcher.launch(Path(tmp_path), cli="agy")


_WINDOWED = r"C:\Users\u\AppData\Roaming\uv\tools\autosound-tcc\Scripts\pythonw.exe"
_CONSOLE = _WINDOWED[: -len("pythonw.exe")] + "python.exe"


@pytest.fixture
def windows_gui(monkeypatch):
    """TCC as it runs on Windows: the GUI's interpreter is `pythonw.exe`, `python.exe` beside it."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", _WINDOWED)
    real = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self, *a, **k: (
        str(self) == _CONSOLE or real(self, *a, **k)))


def test_on_windows_the_codex_line_runs_the_console_interpreter(tmp_path, launched, windows_gui):
    """`pythonw.exe` has no console: `codex_terminal`'s refusals print to nowhere and Codex gets a
    console of its own. The line runs `python.exe` beside it (`child.script_interpreter`)."""
    terminal_menu.open_in(_host(tmp_path, [], harness="codex"), "codex")

    ((_kind, kw),) = launched
    assert kw["cli"] == _CONSOLE


def test_on_windows_the_plain_terminal_s_note_names_the_console_interpreter(windows_gui):
    note = terminal_menu.codex_note()

    assert f'"{_CONSOLE}" -m autosound_tcc.core.codex_terminal .' in note
    assert "pythonw" not in note
