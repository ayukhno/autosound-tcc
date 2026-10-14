"""A Codex row in the pickers says what is true of this machine's Codex (W-10 tcc#181, the
Arbiter's Windows pass): not found → «not installed»; found and known too old → its version and
the menu line that installs TCC's own copy; a version not read yet → available (unknown is not a
block, as the launch blocker's rule); signed out → «sign in», with the blocker's line on hover.

All from what is already known — stat calls and cached readings — never a subprocess: the pickers
are drawn on the GUI thread.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from autosound_tcc.core import availability, codex_cli, model_choices  # noqa: E402
from autosound_tcc.core.codex_cli import Found  # noqa: E402
from autosound_tcc.ui.tcc import availability_view, i18n  # noqa: E402

#: The real one, bound at import: the suite's conftest answers False for every route.
_CLI_AVAILABLE = model_choices.cli_available


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    availability.reset()
    monkeypatch.setattr(model_choices, "cli_available", _CLI_AVAILABLE)

    def boom(*_a, **_k):
        raise AssertionError("a subprocess on the GUI thread")

    monkeypatch.setattr(codex_cli, "version", boom)
    monkeypatch.setattr(codex_cli, "probe", boom)
    yield
    availability.reset()
    i18n.set_language("en")


def _found(tmp_path: Path) -> Found:
    binary = tmp_path / "bin" / "codex"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"\xcf\xfa\xed\xfe native")
    binary.chmod(0o755)
    return Found(str(binary), codex_cli.SOURCE_PATH)


def _row():
    return next(c for c in model_choices.codex_choices())


def _state(choice):
    return availability.status(choice, signed_in=lambda: True, unconfirmed=lambda _c: False)


def test_no_codex_reads_not_installed():
    choice = _row()
    state = _state(choice)
    assert not choice.available
    assert state.reason == availability.NOT_INSTALLED
    assert availability_view.word(state) == i18n.t("availNotInstalled") == "not installed"


def test_a_codex_known_too_old_names_its_version_and_the_install_line(tmp_path, monkeypatch):
    found = _found(tmp_path)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    monkeypatch.setitem(codex_cli._VERSIONS, codex_cli._stamp(found), (0, 152, 0))

    choice = _row()
    state = _state(choice)

    assert not choice.available, "it cannot run: the row stays unpickable"
    assert state.reason == availability.TOO_OLD
    assert availability_view.word(state) == (
        "Codex 0.152.0 is too old — ☰ → ⚙ Settings → Install Codex")
    # On hover, the launch blocker's own sentence, not a second one.
    assert availability_view.detail(state, choice) == i18n.t("codexTooOld").format(
        version="0.152.0", min="0.162.0")
    # `get_tcc_state` has its English phrase for it too.
    assert "too old" in availability.PHRASES[availability.TOO_OLD]

    i18n.set_language("uk")
    assert availability_view.word(state) == (
        "Codex 0.152.0 застарий — ☰ → ⚙ Налаштування → Встановити Codex")


def test_the_install_line_in_the_row_is_the_menus_own_in_every_language(tmp_path, monkeypatch):
    found = _found(tmp_path)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    monkeypatch.setitem(codex_cli._VERSIONS, codex_cli._stamp(found), (0, 152, 0))
    state = _state(_row())
    for lang, _key, _badge in i18n.LANGS:
        i18n.set_language(lang)
        said = availability_view.word(state)
        assert "0.152.0" in said and said.endswith(
            f"☰ → ⚙ {i18n.t('menuSettings')} → {i18n.t('codexInstall')}"), lang
        assert availability_view.phrase(state), lang


def test_a_version_not_read_yet_is_available(tmp_path, monkeypatch):
    found = _found(tmp_path)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)

    choice = _row()

    assert choice.available
    assert _state(choice).ready
    monkeypatch.setitem(codex_cli._VERSIONS, codex_cli._stamp(found), None)  # read, unreadable
    assert _row().available and _state(_row()).ready


def test_a_signed_out_codex_says_sign_in_like_the_other_routes(tmp_path, monkeypatch):
    found = _found(tmp_path)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    monkeypatch.setattr(codex_cli, "_PROBE", codex_cli.Probe(signed_in=False, asked=True))

    choice = _row()
    state = _state(choice)

    assert choice.available and state.reason == availability.SIGN_IN
    assert availability_view.word(state) == i18n.t("availSignIn")
    assert availability_view.detail(state, choice) == i18n.t("codexSignedOut")


def test_the_picker_row_of_a_too_old_codex(tmp_path, monkeypatch):
    from autosound_tcc.ui.tcc.main_window import MainWindow

    found = _found(tmp_path)
    monkeypatch.setattr(codex_cli, "find", lambda **_kw: found)
    monkeypatch.setitem(codex_cli._VERSIONS, codex_cli._stamp(found), (0, 152, 0))
    QApplication.instance() or QApplication([])
    combo = QComboBox()

    choice = _row()
    MainWindow._fill_combo(combo, [choice], "")

    row = combo.findData(choice.key)
    text = combo.itemText(row)
    assert text.endswith("Codex 0.152.0 is too old — ☰ → ⚙ Settings → Install Codex"), text
    assert "not installed" not in text
    tip = combo.itemData(row, Qt.ItemDataRole.ToolTipRole)
    assert i18n.t("codexTooOld").format(version="0.152.0", min="0.162.0") in tip
    assert i18n.t("modelInstallCli").format(cli="codex") not in tip, "the CLI is installed"
