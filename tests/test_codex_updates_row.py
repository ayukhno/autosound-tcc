"""Codex on the Updates tab (W-10 tcc#181, the Arbiter's Windows pass): a row of TCC's own under
«Tools the installer put in» — not the method's `upkeep` — for the Codex TCC would use.

* not found → «not installed», and a button that runs TCC's install (`codex_menu.install`);
* known too old → «0.152.0 → 0.162.1 (TCC's own copy)», the same button;
* TCC's own copy at `PIN` → «up to date»;
* the person's own Codex at `MIN_VERSION` or newer → «<version> — your own Codex», no button.

`settled()` runs on a worker, never on the GUI thread. «Update all» takes the install along only
when the row offers it.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from autosound_tcc.core import codex_cli, codex_install, updates  # noqa: E402
from autosound_tcc.core.codex_cli import Found  # noqa: E402
from autosound_tcc.ui.tcc import codex_menu, i18n  # noqa: E402
from autosound_tcc.ui.tcc.diagnostics_panel import DiagnosticsDialog  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _until(predicate, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        _app().processEvents()
        time.sleep(0.01)


def _binary(tmp_path: Path, name: str = "bin") -> str:
    binary = tmp_path / name / "codex"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"\xcf\xfa\xed\xfe native")
    binary.chmod(0o755)
    return str(binary)


@pytest.fixture
def versions(monkeypatch):
    """`codex --version` stood in: path -> version; the thread each read ran on is kept."""
    said: dict[str, tuple] = {}
    on_gui: list[bool] = []

    def version(found, timeout=codex_cli.VERSION_TIMEOUT_S):
        on_gui.append(threading.current_thread() is threading.main_thread())
        read = said.get(found.path)
        stamp = codex_cli._stamp(found)
        with codex_cli._lock:
            codex_cli._VERSIONS[stamp] = read
        return read

    monkeypatch.setattr(codex_cli, "version", version)
    monkeypatch.setattr(codex_cli, "probe", lambda **_k: pytest.fail("no probe for a row"))
    monkeypatch.setattr(updates, "tools_status", lambda: updates.ToolsStatus(True, ()))
    return said, on_gui


def _finds(monkeypatch, *found: Found) -> None:
    """`find()` as it behaves: the first not known too old, else the first old one."""
    def find(**_kw):
        fresh = [f for f in found if not codex_cli.too_old(f)]
        return (fresh or list(found) or [None])[0]

    monkeypatch.setattr(codex_cli, "find", find)


# ---- the core: which Codex, and what it is ------------------------------------------------------


def test_standing_none_found_is_missing(versions):
    assert codex_cli.standing() == codex_cli.Standing(codex_cli.STANDING_MISSING)


def test_standing_an_old_one_alone_is_too_old(tmp_path, monkeypatch, versions):
    said, _ = versions
    old = Found(_binary(tmp_path), codex_cli.SOURCE_PATH)
    said[old.path] = (0, 152, 0)
    _finds(monkeypatch, old)
    got = codex_cli.standing()
    assert got == codex_cli.Standing(codex_cli.STANDING_TOO_OLD, "0.152.0") and got.offered


def test_standing_tccs_own_copy_is_current(tmp_path, monkeypatch, versions):
    said, _ = versions
    old = Found(_binary(tmp_path, "old"), codex_cli.SOURCE_PATH)
    own = Found(_binary(tmp_path, "own"), codex_cli.SOURCE_TCC)
    said[old.path], said[own.path] = (0, 152, 0), (0, 162, 1)
    _finds(monkeypatch, old, own)
    got = codex_cli.standing()
    assert got == codex_cli.Standing(codex_cli.STANDING_TCC, codex_cli.PIN) and not got.offered


def test_standing_the_persons_own_new_enough_codex(tmp_path, monkeypatch, versions):
    said, _ = versions
    mine = Found(_binary(tmp_path), codex_cli.SOURCE_PATH)
    said[mine.path] = (0, 170, 2)
    _finds(monkeypatch, mine)
    got = codex_cli.standing()
    assert got == codex_cli.Standing(codex_cli.STANDING_OWN, "0.170.2") and not got.offered


# ---- the row ------------------------------------------------------------------------------------


class _Strip:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def notify(self, text, **_kw) -> None:
        self.lines.append(text)


class _Host(QWidget):
    """The main window as `codex_menu` sees it: a strip, the pickers, its one Codex job."""

    def __init__(self) -> None:
        _app()  # a QWidget before the QApplication aborts the process
        super().__init__()
        self._status_strip = _Strip()
        self.reloaded: list[bool] = []

    def _reload_model_choices(self) -> None:
        self.reloaded.append(True)


def _shown(host=None) -> DiagnosticsDialog:
    _app()
    dialog = DiagnosticsDialog(host)
    dialog.held_host = host  # the host owns the dialog: kept alive as long as the test holds it
    dialog._tabs.setCurrentWidget(dialog._updates_tab)
    _settle(dialog)
    return dialog


def _settle(dialog) -> None:
    row = dialog._codex_row
    _until(lambda: not row.checking)


def _line(dialog) -> str:
    return dialog._codex_row.label.text()


def test_not_installed_offers_tccs_install(versions):
    host = _Host()
    dialog = _shown(host)
    row = dialog._codex_row
    assert _line(dialog) == i18n.t("updCodexMissing") == "Codex — not installed"
    assert row.button.text() == i18n.t("codexInstall")
    assert not row.button.isHidden()
    assert row.button.isEnabled() and row.offered
    i18n.set_language("uk")
    try:
        assert _line(dialog) == "Codex — не встановлено"
    finally:
        i18n.set_language("en")


def test_too_old_offers_tccs_own_copy_and_never_reads_on_the_gui_thread(
        tmp_path, monkeypatch, versions):
    said, on_gui = versions
    old = Found(_binary(tmp_path), codex_cli.SOURCE_PATH)
    said[old.path] = (0, 152, 0)
    _finds(monkeypatch, old)

    dialog = _shown(_Host())

    assert _line(dialog) == "Codex 0.152.0 → 0.162.1 (TCC's own copy)"
    assert dialog._codex_row.button.isEnabled()
    assert on_gui and not any(on_gui), "`codex --version` ran on the GUI thread"
    i18n.set_language("uk")
    try:
        assert _line(dialog) == "Codex 0.152.0 → 0.162.1 (власна копія TCC)"
    finally:
        i18n.set_language("en")


def test_tccs_own_copy_at_the_pin_is_up_to_date(tmp_path, monkeypatch, versions):
    said, _ = versions
    own = Found(_binary(tmp_path), codex_cli.SOURCE_TCC)
    said[own.path] = (0, 162, 1)
    _finds(monkeypatch, own)

    dialog = _shown(_Host())

    assert _line(dialog) == "Codex 0.162.1 — up to date"
    assert not dialog._codex_row.button.isEnabled() and not dialog._codex_row.offered


def test_the_persons_own_codex_is_theirs_to_update(tmp_path, monkeypatch, versions):
    said, _ = versions
    mine = Found(_binary(tmp_path), codex_cli.SOURCE_PATH)
    said[mine.path] = (0, 170, 2)
    _finds(monkeypatch, mine)

    dialog = _shown(_Host())
    row = dialog._codex_row

    assert _line(dialog) == "Codex 0.170.2 — your own Codex"
    assert row.button.isHidden() and not row.offered
    assert row.label.toolTip() == i18n.t("updCodexOwnTip")
    assert "winget" in row.label.toolTip()
    i18n.set_language("uk")
    try:
        assert _line(dialog) == "Codex 0.170.2 — ваш власний Codex"
    finally:
        i18n.set_language("en")


def test_drawing_the_row_runs_nothing_on_the_gui_thread(monkeypatch, versions):
    """The checks run on their worker; the window itself only reads what came back."""
    def boom(*_a, **_k):
        if threading.current_thread() is threading.main_thread():
            raise AssertionError("settled() on the GUI thread")
        return None, None

    monkeypatch.setattr(codex_cli, "settled", boom)
    dialog = _shown(_Host())
    i18n.set_language("uk")
    i18n.set_language("en")
    dialog._sync_tools()
    assert _line(dialog) == i18n.t("updCodexMissing")


def test_the_button_runs_codex_menus_install_and_reads_the_row_again(
        tmp_path, monkeypatch, versions):
    said, _ = versions
    own = tmp_path / "own"
    threads: list[bool] = []

    def install(progress, cancelled, **_kw):
        threads.append(threading.current_thread() is threading.main_thread())
        progress(50, 100)
        path = _binary(own.parent, "own")
        said[path] = (0, 162, 1)
        _finds(monkeypatch, Found(path, codex_cli.SOURCE_TCC))
        return Path(path)

    monkeypatch.setattr(codex_install, "install", install)
    monkeypatch.setattr(codex_menu, "after_install", lambda: None)
    host = _Host()
    dialog = _shown(host)

    dialog._codex_row.button.click()
    assert not dialog._codex_row.button.isEnabled(), "not twice at once"
    _until(lambda: _line(dialog) == "Codex 0.162.1 — up to date")

    assert threads == [False]
    assert i18n.t("codexInstalled") in host._status_strip.lines, "codex_menu's own receipt"
    assert host.reloaded == [True]


def test_without_the_main_window_nothing_is_offered(versions):
    dialog = _shown(None)
    assert _line(dialog) == i18n.t("updCodexMissing")
    assert not dialog._codex_row.offered and not dialog._codex_row.button.isEnabled()


def _tools_dialog(monkeypatch, host, *tools):
    monkeypatch.setattr(updates, "tools_status", lambda: updates.ToolsStatus(True, tuple(tools)))
    dialog = _shown(host)
    for _ in range(5):
        job = dialog._tools_job
        if job is None:
            break
        job.join(timeout=10)
        dialog._poll_tools_job()
    return dialog


def test_update_all_takes_the_codex_install_only_when_the_row_offers_it(
        tmp_path, monkeypatch, versions):
    said, _ = versions
    asked: list = []
    installs: list = []
    monkeypatch.setattr(updates, "update_tools", lambda names: asked.append(list(names)) or
                        updates.ToolsUpdate(tuple(updates.ToolUpdate(n, True, "1", "2")
                                                  for n in names)))
    monkeypatch.setattr(codex_menu, "install", lambda host: installs.append(host))
    omp = updates.Tool("omp", "17.3.8", "18.2.4", True)

    host = _Host()
    dialog = _tools_dialog(monkeypatch, host, omp)
    dialog._tools_all_btn.click()
    assert installs == [host], "the row offered the install: «Update all» takes it"

    mine = Found(_binary(tmp_path), codex_cli.SOURCE_PATH)
    said[mine.path] = (0, 170, 2)
    _finds(monkeypatch, mine)
    installs.clear()
    dialog = _tools_dialog(monkeypatch, _Host(), omp)
    dialog._tools_all_btn.click()
    assert installs == [], "the person's own Codex is not TCC's to update"


def test_update_all_is_live_for_the_codex_install_alone(versions, monkeypatch):
    gh = updates.Tool("gh", "2.1", "2.1", True)
    dialog = _tools_dialog(monkeypatch, _Host(), gh)
    assert dialog._tools_all_btn.isEnabled()
