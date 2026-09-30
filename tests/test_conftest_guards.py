"""The suite must not be able to read this machine.

`conftest.py` states the rule for `cli_available` and patches it; these tests are the same claim,
checked rather than assumed. Written after the first CI runs (2026-09-07) found two tests that
passed on the author's laptop and failed everywhere else — the rule was right and the guard had a
second door nobody had noticed.
"""
import threading
from pathlib import Path

import pytest

from autosound_tcc.core import model_choices


def test_the_suite_cannot_see_which_clis_this_machine_has():
    assert model_choices.cli_available("agy") is False


def test_the_suite_cannot_see_whether_a_critic_is_reachable():
    """`critic_reaches` asks `os.environ` and `shutil.which` directly, so patching
    `cli_available` never covers it. That gap is what made
    `test_no_row_repeats_what_the_row_already_says` green on a machine with `agy` installed and
    red on both CI platforms."""
    choice = model_choices.Choice(
        harness="agy",
        model="gemini-3.1-pro-high",
        label="Gemini 3.1 Pro (High)",
        provider="google",
    )
    assert model_choices.critic_reaches(choice) is False


def test_the_suite_cannot_read_this_machines_reviewer_key(monkeypatch, real_critic_reaches):
    """A third door onto the same machine, opened the day `critic_reaches` learned to look in
    `~/.config/autosound/critic-env` (SKL-024): a developer with a real key there would get a
    reachable critic and CI would not, which is the 2026-09-07 failure again wearing a new coat.
    `real_critic_reaches` deliberately un-stubs the function — so if the isolation is missing,
    this test reads the actual laptop and says so."""
    from autosound_tcc.core import critic_env

    # Both cleared FIRST, and that is the fix rather than a tidy-up. A developer's laptop has
    # neither set, so the assertion below passed here and failed on every CI runner: GitHub sets
    # `XDG_CONFIG_HOME` on Linux and `APPDATA` on Windows, and either one takes the resolution
    # away from HOME before the isolation can be observed. The property being tested is "HOME
    # still decides"; a test of it has to be the one deciding what else is in the environment.
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    # What isolates this is `conftest`'s tmp HOME, and that only works while the path is resolved
    # through `~` on every call. Hard-code it, or cache it at import time, and the suite silently
    # starts reading the developer's own key again. `Path.home()` is already the tmp one here,
    # which is the isolation working.
    assert Path.home() in critic_env.machine_config_path().parents

    other = Path.home().parent / "somewhere-else"
    monkeypatch.setenv("HOME", str(other))
    monkeypatch.setenv("USERPROFILE", str(other))  # what `~` follows on Windows

    assert critic_env.machine_config_path() == other / ".config" / "autosound" / "critic-env"


def test_no_test_can_leave_a_console_keeper_running():
    """A keeper is a daemon thread with a twelve-hour budget, and on a Windows runner the pid it
    watches is pytest's own — alive until the very end. Two tests reached one without meaning to
    and left two such threads for the whole run: they sit in every crash dump of 2026-09-11 (run
    34639559016, three crashes in a row, where one in three was usual).

    `conftest` hands every test a spawn that starts nothing; this checks it is still there.
    """
    from autosound_tcc.core import child

    ran = threading.Event()
    child._spawn_daemon(lambda **_kw: ran.set(), {})

    assert not ran.wait(0.2), "a real thread started — the keeper stub in conftest is gone"


def test_the_suite_cannot_run_this_machines_claude(monkeypatch):
    """A window's catalogue worker asks `claude auth status`, and on a machine with Claude Code that
    was the real CLI. With HOME in `tmp_path` it wrote `.claude.json` there, the window's project
    watcher took that for a change to the project, and the reload emptied the capture card in the
    middle of `test_the_right_column_scrolls_when_the_capture_list_is_long` — 2 of 15 parallel
    runs, 2026-09-14. A CI runner has no `claude`, which is why CI never saw it."""
    import subprocess

    from autosound_tcc.core import claude_sdk

    spawned: list = []
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(claude_sdk.subprocess, "run",
                        lambda *a, **k: spawned.append(a) or subprocess.CompletedProcess(a, 1, "", ""))

    claude_sdk.probe_signed_in(force=True)

    assert not spawned, "the real `claude` was asked — the stub in conftest is gone"


def test_what_the_app_writes_for_the_machine_is_not_in_the_tests_own_folder(tmp_path):
    """Tests use `tmp_path` as a project folder, and a window watches its project folder. With the
    app's settings and caches in that same folder, a window saw its own writes as a change to the
    project and rebuilt the DSP tree 400 ms later, in the middle of whatever the test was holding
    (tcc#28: one Windows run in ten from 2026-09-11, when APPDATA moved into `tmp_path`; on macOS a
    `cli-catalogue.json` written by the catalogue worker did the same, only after the test ended).

    HOME stays in `tmp_path`: tests read `~/.claude` through it, and a window writes nothing there.
    """
    import os

    from autosound_tcc.ui.tcc.app_settings import get_settings

    written_for_the_machine = {
        "QSettings": get_settings().fileName(),
        "LOCALAPPDATA": os.environ["LOCALAPPDATA"],
        "APPDATA": os.environ["APPDATA"],
        "XDG_CONFIG_HOME": os.environ["XDG_CONFIG_HOME"],
        "XDG_STATE_HOME": os.environ["XDG_STATE_HOME"],
        "AUTOSOUND_TCC_CONFIG_DIR": os.environ["AUTOSOUND_TCC_CONFIG_DIR"],
    }

    inside = {name: path for name, path in written_for_the_machine.items()
              if tmp_path.resolve() in Path(path).resolve().parents}
    assert not inside, f"written into the test's own folder: {inside}"


def test_a_modal_a_test_reaches_fails_the_test_instead_of_waiting():
    """A real modal in a test waits for a person who is not there: a plain `-n 4` run sat in
    the «model gone» box for 24 minutes (2026-09-30), and CI's Windows shard hit its 25-minute
    limit in the same stretch. The guard in conftest makes the modal fail the test by name."""
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    QApplication.instance() or QApplication([])
    box = QMessageBox()
    box.setWindowTitle("Model gone")
    box.setText("This project is set to a model nothing here can run")
    # By its text: the title is a no-op on macOS, where a message box has none.
    with pytest.raises(RuntimeError, match="a test opened a modal: QMessageBox .*a model nothing"):
        box.exec()
    with pytest.raises(RuntimeError, match="a test opened a modal: QDialog"):
        QDialog().exec()
    with pytest.raises(RuntimeError, match="a test opened a modal: QMessageBox.question"):
        QMessageBox.question(None, "Switch?", "Open the other folder?")


@pytest.fixture(params=["true", "a lie"])
def _sheet_record(request):
    """`apply_theme`'s record of the sheet as `app_ground` finds it: naming the sheet on the
    application, or one that is not on it. Set before `app_ground` and put back after it."""
    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc import theme

    app = QApplication.instance() or QApplication([])
    was = theme._APPLIED
    on = app.styleSheet()
    theme._APPLIED = ("dark", 1.0, on if request.param == "true" else on + "/* not on */")
    yield request.param
    theme._APPLIED = was


def test_app_ground_drops_a_record_that_lies_and_keeps_one_that_is_true(_sheet_record,
                                                                        app_ground):
    """A lie -- the sheet cleared, the record saying it is on -- made the next window skip its
    sheet and measure itself unstyled (four head tests, the full `-n 4` run at 942dd61): dropped,
    the window applies its own. A true record is kept: cleared, it made every test on this
    fixture re-style every window the worker still holds, for a sheet already on -- CI's Windows
    shard 4 past its 25-minute limit."""
    from autosound_tcc.ui.tcc import theme

    if _sheet_record == "true":
        assert theme._APPLIED is not None and theme._APPLIED[2] == app_ground.styleSheet()
    else:
        assert theme._APPLIED is None


def test_a_finished_test_s_panes_leave_the_language_switch():
    """F-065: every `MainWindow` switches to its saved language as it is built, and a switch
    called every pane the run had made so far -- in one process the cost of a window grew with
    its place in the run. What a test registered is dropped when it ends; what was there before
    it stays, and the language still reaches it."""
    import weakref

    from PySide6.QtWidgets import QApplication

    from autosound_tcc.ui.tcc import i18n
    from autosound_tcc.ui.tcc.detail_pane import DetailPane
    from tests import _windows

    QApplication.instance() or QApplication([])
    earlier = DetailPane()  # stands for what a module fixture, or an import, registered
    before = _windows.language_listeners()
    finished = DetailPane()  # stands for what the test itself made

    def owners():
        return [entry().__self__ for entry in i18n._listeners
                if isinstance(entry, weakref.WeakMethod) and entry() is not None]

    assert earlier in owners() and finished in owners()
    _windows.drop_language_listeners_since(before)
    assert earlier in owners() and finished not in owners()
    english = finished._tab_table.text()
    i18n.set_language("uk")
    try:
        assert earlier._tab_table.text() == i18n.t("tabTable") != english, "it still follows"
        assert finished._tab_table.text() == english, "a finished test's pane keeps its words"
    finally:
        i18n.set_language("en")


def test_a_test_starts_on_a_frozen_heap_and_its_own_cycles_are_still_collected():
    """F-065: a full collection between tests walked every Python object the run's earlier
    windows still hold -- 437 s of a 2730-s serial run. `_collect_qt_leftovers` freezes what is
    alive when a test starts, so a collection walks only what the test made since; a cycle the
    test drops is collected all the same."""
    import gc
    import weakref

    assert gc.get_freeze_count() > 0, "what was alive before this test is out of the collection"

    class _Cycle:
        pass

    dropped = _Cycle()
    dropped.itself = dropped
    gone = weakref.ref(dropped)
    del dropped
    gc.collect()
    assert gone() is None, "a cycle made and dropped in the test is collected"
