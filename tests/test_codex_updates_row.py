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

import io
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from autosound_tcc.core import codex_cli, codex_install, updates  # noqa: E402
from autosound_tcc.core.codex_cli import Found  # noqa: E402
from autosound_tcc.ui.tcc import codex_menu, i18n  # noqa: E402
from autosound_tcc.ui.tcc.diagnostics_panel import DiagnosticsDialog  # noqa: E402

#: The real query, from before `conftest` puts the suite's stand-in over it for each test.
_REAL_QUERY = getattr(codex_cli, "_pypi_json", None)


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
    assert dialog._codex_row.button.isHidden() and not dialog._codex_row.offered


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


def test_a_row_being_checked_shows_no_greyed_install(monkeypatch):
    """#252: an up-to-date row flashed a greyed «Install Codex» for as long as `codex --version`
    took to answer (up to 10 s). Nothing can be done with the button until the answer is in
    (`offered` needs one), so it is not there; it comes with an answer that offers the install."""
    from autosound_tcc.ui.tcc import codex_tool_row

    class Held:
        running, result, error = True, None, ""

    held = Held()
    monkeypatch.setattr(codex_tool_row, "_Check", lambda: held)
    host = _Host()
    row = codex_tool_row.CodexToolRow(lambda: host, lambda: None)

    row.check()
    assert row.checking and row.button.isHidden(), "asked, not answered: no button"
    held.running, held.result = False, codex_cli.Standing(codex_cli.STANDING_TCC, "0.162.1")
    row._poll()
    assert row.button.isHidden(), "up to date: still none"

    held.running = True
    row.check()
    assert row.button.isHidden()
    held.running, held.result = False, codex_cli.Standing(codex_cli.STANDING_MISSING)
    row._poll()
    assert not row.button.isHidden() and row.offered, "none found: the install is offered"

    held.running, held.result, held.error = False, None, "OSError: boom"
    row.check()
    row._poll()
    assert row.button.isHidden(), "no answer to act on, nothing to press"


# ---- whose Codex, and what is newer than the pin (#254) -------------------------------------------


def _pypi_says(version) -> bytes:
    return json.dumps({"info": {"version": version}}).encode()


def _pypi(monkeypatch, answer) -> list:
    """The PyPI query stood in: its body, or the exception it dies of. Returns the calls' threads."""
    asked: list[bool] = []

    def query():
        asked.append(threading.current_thread() is threading.main_thread())
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(codex_cli, "_pypi_json", query, raising=False)
    return asked


def _tcc_copy(monkeypatch, versions) -> None:
    said, _ = versions
    own = Found(_binary(codex_cli.tcc_copy_path().parents[1]), codex_cli.SOURCE_TCC)
    said[own.path] = (0, 162, 1)
    _finds(monkeypatch, own)


def test_a_link_to_tccs_copy_is_tccs_copy(tmp_path, monkeypatch, versions):
    """The workaround link put TCC's own binary on PATH, and the row called it «your own»."""
    said, _ = versions
    copy = codex_cli.tcc_copy_path()
    copy.parent.mkdir(parents=True)
    copy.write_bytes(b"\xcf\xfa\xed\xfe native")
    copy.chmod(0o755)
    link = tmp_path / "bin" / "codex"
    link.parent.mkdir()
    try:
        link.symlink_to(copy)
    except OSError:
        pytest.skip("no symlinks here")
    found = Found(str(link), codex_cli.SOURCE_PATH)
    said[found.path] = (0, 162, 1)
    _finds(monkeypatch, found)

    dialog = _shown(_Host())

    assert _line(dialog) == "Codex 0.162.1 — up to date"
    assert dialog._codex_row.button.isHidden() and not dialog._codex_row.offered
    assert found.path == str(link), "the path Codex is started by stays as found"


@pytest.mark.parametrize("latest", ["0.165.0", "0.1000.0"])  # 0.1000 sorts before 0.162 as text
def test_a_newer_codex_is_named_and_held_by_the_pin_with_no_button(
        monkeypatch, versions, latest):
    _tcc_copy(monkeypatch, versions)
    asked = _pypi(monkeypatch, _pypi_says(latest))

    dialog = _shown(_Host())

    assert _line(dialog) == f"Codex {latest} is out; TCC holds 0.162.1 (pinned)"
    row = dialog._codex_row
    assert row.button.isHidden() and not row.offered, "a newer file has no pinned sum"
    assert asked == [False], "PyPI asked on the worker, once"


@pytest.mark.parametrize("answer", [
    urllib.error.URLError("offline"),
    ConnectionRefusedError("refused"),
    TimeoutError("timed out"),
    b"<html>not json</html>",
    b'{"info": null}',
    b"[1, 2]",
    _pypi_says(165),
    _pypi_says("0.166.0rc1"),
    _pypi_says("0.162.1"),
    _pypi_says("0.161.9"),
    _pypi_says("0.99.0"),  # sorts after 0.162.1 as text
], ids=["offline", "refused", "timeout", "not-json", "no-info", "a-list", "not-a-string",
        "pre-release", "the-pin", "older", "older-by-number"])
def test_no_newer_version_read_keeps_todays_text(monkeypatch, versions, answer):
    _tcc_copy(monkeypatch, versions)
    asked = _pypi(monkeypatch, answer)

    dialog = _shown(_Host())

    assert _line(dialog) == "Codex 0.162.1 — up to date"
    assert dialog._codex_row.button.isHidden()
    assert asked == [False], "the row did ask"


def test_a_slow_pypi_does_not_hold_the_row(monkeypatch, versions):
    """A dead line can sit in a DNS lookup past any socket timeout: the row says what it knows."""
    _tcc_copy(monkeypatch, versions)
    asked, release = threading.Event(), threading.Event()

    def query():
        asked.set()
        release.wait(10)
        return _pypi_says("0.165.0")

    monkeypatch.setattr(codex_cli, "_pypi_json", query, raising=False)
    from autosound_tcc.ui.tcc import codex_tool_row

    host = _Host()
    row = codex_tool_row.CodexToolRow(lambda: host, lambda: None)
    row.check()
    try:
        _until(lambda: row.label.text() == "Codex 0.162.1 — up to date" and asked.is_set())
        assert row.button.isHidden()
    finally:
        release.set()
    _until(lambda: row.label.text() == "Codex 0.165.0 is out; TCC holds 0.162.1 (pinned)")
    assert row.button.isHidden()


def test_the_query_asks_pypi_for_the_packages_latest_with_a_timeout(monkeypatch):
    calls: list = []

    def urlopen(url, timeout=None):
        calls.append((url, timeout))
        return io.BytesIO(b"the body")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert _REAL_QUERY is not None and _REAL_QUERY() == b"the body"
    assert calls == [("https://pypi.org/pypi/openai-codex-cli-bin/json", codex_cli.PYPI_TIMEOUT_S)]
    assert 0 < codex_cli.PYPI_TIMEOUT_S <= 10


# ---- the path a terminal can use (#253) -----------------------------------------------------------

POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="a symlink is made by hand here")


def _the_copy(monkeypatch, versions) -> Path:
    said, _ = versions
    copy = codex_cli.tcc_copy_path()
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(b"\xcf\xfa\xed\xfe native")
    copy.chmod(0o755)
    found = Found(str(copy), codex_cli.SOURCE_TCC)
    said[found.path] = (0, 162, 1)
    _finds(monkeypatch, found)
    return copy


def test_tccs_own_copy_says_the_path_and_whose_it_is(monkeypatch, versions):
    copy = _the_copy(monkeypatch, versions)

    dialog = _shown(_Host())
    row = dialog._codex_row

    folder = str(codex_cli.current_bin(copy))
    assert row.standing.current == folder
    assert _line(dialog) == "Codex 0.162.1 — up to date", "the status line is kept"
    assert not row.path_label.isHidden() and not row.path_note.isHidden()
    assert row.path_label.text() == folder, "alone on its line, to select and copy"
    said = row.path_note.text()
    assert "TCC's own copy" in said and "PATH" in said and "yourself" in said
    assert row.button.isHidden(), "#252 kept: a current copy has no button"
    assert (Path(folder) / copy.name).is_file(), "the path said is one that works"


def test_an_install_from_before_this_gets_current_on_the_rows_worker(monkeypatch, versions):
    """No reinstall, and not on the GUI thread."""
    copy = _the_copy(monkeypatch, versions)
    assert not os.path.lexists(copy.parents[3] / codex_cli.CURRENT)
    threads: list[bool] = []
    real = codex_install.refresh_current

    def watched(*a, **k):
        threads.append(threading.current_thread() is threading.main_thread())
        return real(*a, **k)

    monkeypatch.setattr(codex_install, "refresh_current", watched)

    dialog = _shown(_Host())

    assert threads == [False]
    assert (codex_cli.current_bin(copy) / copy.name).is_file()
    assert not dialog._codex_row.path_label.isHidden()


def test_is_out_and_the_path_are_said_together(monkeypatch, versions):
    copy = _the_copy(monkeypatch, versions)
    _pypi(monkeypatch, _pypi_says("0.165.0"))

    dialog = _shown(_Host())

    assert _line(dialog) == "Codex 0.165.0 is out; TCC holds 0.162.1 (pinned)"
    assert dialog._codex_row.path_label.text() == str(codex_cli.current_bin(copy))


@POSIX_ONLY
def test_a_current_that_is_not_tccs_keeps_the_row_and_says_no_path(monkeypatch, versions, caplog):
    copy = _the_copy(monkeypatch, versions)
    mine = copy.parents[3] / codex_cli.CURRENT
    mine.mkdir()
    (mine / "notes.txt").write_text("mine")

    with caplog.at_level("WARNING"):
        dialog = _shown(_Host())

    row = dialog._codex_row
    assert _line(dialog) == "Codex 0.162.1 — up to date"
    assert row.path_label.isHidden() and row.path_note.isHidden() and row.standing.current == ""
    assert (mine / "notes.txt").read_text() == "mine"
    assert "left alone" in caplog.text


@POSIX_ONLY
def test_a_link_that_failed_leaves_the_row_as_it_was(monkeypatch, versions):
    _the_copy(monkeypatch, versions)

    def refused(_version, _link):
        raise OSError("no links here")

    monkeypatch.setattr(codex_install, "_make_link", refused)

    dialog = _shown(_Host())

    assert _line(dialog) == "Codex 0.162.1 — up to date"
    assert dialog._codex_row.path_label.isHidden() and dialog._codex_row.path_note.isHidden()


def test_the_persons_own_codex_says_no_path(tmp_path, monkeypatch, versions):
    said, _ = versions
    _the_copy(monkeypatch, versions)  # TCC's copy is there too, and not the one used
    mine = Found(_binary(tmp_path), codex_cli.SOURCE_PATH)
    said[mine.path] = (0, 170, 2)
    _finds(monkeypatch, mine)

    dialog = _shown(_Host())

    assert _line(dialog) == "Codex 0.170.2 — your own Codex"
    assert dialog._codex_row.path_label.isHidden() and dialog._codex_row.path_note.isHidden()
    assert not os.path.lexists(codex_cli.tcc_copy_path().parents[3] / codex_cli.CURRENT)


def test_the_long_path_is_not_cut_and_can_be_copied(monkeypatch, versions):
    copy = _the_copy(monkeypatch, versions)
    dialog = _shown(_Host())
    dialog.resize(420, 500)
    dialog.show()  # offscreen: the module sets the platform above
    try:
        _app().processEvents()
        label = dialog._codex_row.path_label
        width = label.fontMetrics().horizontalAdvance(str(codex_cli.current_bin(copy)))
        assert label.width() >= width, "the path is one word: a narrow row must not clip it"
        assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    finally:
        dialog.close()


# ---- a copy of TCC's behind the pin: `current` on PATH, and a TCC that pins a newer one (#253) ---

OLDER = "0.162.0"


def _behind_the_pin(monkeypatch, versions, read=(0, 162, 0)) -> tuple[Found, Path, Path]:
    """What a pin bump leaves: `current` on the person's PATH, still at the old pin's folder.
    (what `find` answers, the copy the new pin names, the link)."""
    said, _ = versions
    copy = codex_cli.tcc_copy_path()
    older = copy.parents[3] / OLDER / "codex_cli_bin" / "bin" / copy.name
    older.parent.mkdir(parents=True)
    older.write_bytes(b"\xcf\xfa\xed\xfe native")
    older.chmod(0o755)
    link = copy.parents[3] / codex_cli.CURRENT
    link.symlink_to(OLDER, target_is_directory=True)
    found = Found(str(codex_cli.current_bin(copy) / copy.name), codex_cli.SOURCE_PATH)
    said[found.path] = read
    _finds(monkeypatch, found)
    return found, copy, link


@POSIX_ONLY
def test_a_link_to_an_older_tcc_folder_says_its_real_version_and_offers_the_install(
        monkeypatch, versions):
    """Said «up to date» before, with no way to install: `find` stops at the PATH hit and never
    reaches the new pin's path."""
    _found, _copy, link = _behind_the_pin(monkeypatch, versions)

    got = codex_cli.standing()
    dialog = _shown(_Host())
    row = dialog._codex_row

    assert got == codex_cli.Standing(codex_cli.STANDING_TOO_OLD, OLDER) and got.offered
    assert _line(dialog) == f"Codex {OLDER} → {codex_cli.PIN} (TCC's own copy)"
    assert not row.button.isHidden() and row.button.isEnabled() and row.offered
    assert row.path_label.isHidden(), "the folder leads to the old copy: not said as current"
    assert os.readlink(link) == OLDER, "a read does not move it"


@POSIX_ONLY
def test_an_unread_copy_behind_the_pin_is_named_by_its_folder(monkeypatch, versions):
    _behind_the_pin(monkeypatch, versions, read=None)
    assert codex_cli.standing() == codex_cli.Standing(codex_cli.STANDING_TOO_OLD, OLDER)


@POSIX_ONLY
def test_the_install_offered_moves_current_and_the_row_ends_up_to_date(monkeypatch, versions):
    """`install()` itself moving a live `current` is `test_an_install_over_a_stale_current_…`."""
    said, _ = versions
    found, copy, link = _behind_the_pin(monkeypatch, versions)

    def install(_progress, _cancelled, **_kw):
        copy.parent.mkdir(parents=True)
        copy.write_bytes(b"\xcf\xfa\xed\xfe native, the new pin's")
        copy.chmod(0o755)
        said[found.path] = (0, 162, 1)
        codex_install.refresh_current(copy, repoint=True)
        return copy

    monkeypatch.setattr(codex_install, "install", install)
    monkeypatch.setattr(codex_menu, "after_install", lambda: None)
    dialog = _shown(_Host())
    assert _line(dialog) == f"Codex {OLDER} → {codex_cli.PIN} (TCC's own copy)"

    dialog._codex_row.button.click()
    _until(lambda: _line(dialog) == "Codex 0.162.1 — up to date")

    assert os.readlink(link) == codex_cli.PIN
    assert dialog._codex_row.button.isHidden()
    assert dialog._codex_row.path_label.text() == str(codex_cli.current_bin(copy))
