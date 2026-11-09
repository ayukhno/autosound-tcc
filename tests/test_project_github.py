"""«Project on GitHub» in the left panel (#235): a real repository and a bare remote in `tmp_path`,
the method's real `project_repo.py`, no network. The tests read what the person sees and what
landed on the remote.

A stand-in host carries the real section and strip contract, so only the wiring test builds the
window. Everything that starts a thread stops it: the fixture stops the panel before `tmp_path`
goes.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QThread  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget  # noqa: E402

from autosound_tcc.core import config, project_repo  # noqa: E402
from autosound_tcc.ui.tcc import copy_menu, i18n, project_github, qt_shutdown  # noqa: E402
from autosound_tcc.ui.tcc.sidebar_section import SidebarSection  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _git(where, *args) -> str:
    done = subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, env={**os.environ, **GIT_ENV})
    assert done.returncode == 0, (args, done.stderr)
    return done.stdout.strip()


def _write(project: Path, rel: str, text: str = "x\n") -> None:
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(project: Path, rel: str, subject: str = "a commit") -> str:
    _write(project, rel, f"{rel} {time.time()}\n")
    _git(project, "add", rel)
    _git(project, "commit", "-q", "-m", subject)
    return _git(project, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """(project, bare): the method's own `init`, pushed, and the process pointed at it."""
    QApplication.instance() or QApplication([])
    project, bare = tmp_path / "car", tmp_path / "remote.git"
    project.mkdir()
    _write(project, "project.json", "{}\n")
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True, timeout=60)
    made = project_repo.init(project)
    assert made.ok, made.said
    _git(project, "remote", "add", "origin", str(bare))
    _git(project, "push", "-q", "-u", "origin", "HEAD")
    # A repository's first fetch writes `refs/remotes/origin/HEAD` once; a steady project's does not.
    _git(project, "fetch", "-q", "--prune", "origin")
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: project)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: project)
    monkeypatch.setattr(project_github, "COALESCE_MS", 10)
    return project, bare


class _Strip:
    def __init__(self):
        self.said: list[tuple[str, str]] = []

    def notify(self, text, level="info", **_kw):
        self.said.append((text, level))


class _Host(QWidget):
    """What the panel needs of the window."""

    def __init__(self, folder):
        super().__init__()
        self._closing = False
        self._built_on = folder
        self._backup_step = None
        self._status_strip = _Strip()
        layout = QVBoxLayout(self)
        settings = QSettings("autosound-tcc-tests", f"github-{id(self)}")
        self._project_section = SidebarSection("project", "Project", settings, default_collapsed=False,
                                               sub_below=True)
        layout.addWidget(self._project_section)
        self.resize(400, 500)

    def _on_git_init(self):
        pass

    def _on_git_backup(self):
        pass


@pytest.fixture
def host(repo):
    made = []

    def build(shown: bool = True):
        widget = _Host(repo[0])
        panel = project_github.ProjectGithub(widget)
        widget._github = panel
        if shown:
            widget.show()
        made.append(widget)
        return widget, panel

    yield build
    for widget in made:
        widget._github.stop()
        for worker in list(qt_shutdown.live()) + list(qt_shutdown.detached()):
            worker.wait(20000)
        widget.close()


def _until(what, seconds: float = 20.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        if what():
            return True
        time.sleep(0.01)
    return bool(what())


def _rows(widget) -> dict[str, str]:
    labels = widget._project_section.findChildren(QLabel)
    keys = [copy_menu.full_text(x) for x in labels if x.property("class") == "pk"]
    values = [copy_menu.full_text(x) for x in labels if x.property("class") == "pv"]
    return dict(zip(keys, values))


def _settled(panel) -> bool:
    return panel.idle() and panel._read is not None


# ── (a) A live read ──────────────────────────────────────────────────────────────────────────────

def test_the_read_is_the_methods_status_with_a_fetch(repo, tmp_path):
    """The real method, against the bare remote: what another copy pushed is seen, so it fetched."""
    project, bare = repo
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True, capture_output=True, timeout=60)
    moved = _commit(other, "from-elsewhere.txt", "from elsewhere")
    _git(other, "push", "-q", "origin", "HEAD")

    answer = project_repo.read(project)

    assert isinstance(answer, dict), answer
    assert answer["remote_head"]["hash"] == moved
    for key in ("changes", "ahead", "fetched", "fetch_error", "changes_error", "sends"):
        assert key in answer, key


def test_a_commit_and_a_push_made_elsewhere_move_the_rows(repo, host):
    project, _bare = repo
    widget, panel = host()
    panel.show()
    assert _until(lambda: _settled(panel))
    assert i18n.t("gitUnpushed") not in _rows(widget)

    _commit(project, "state/v_002.json", "banked by the session")
    assert _until(lambda: _rows(widget).get(i18n.t("gitUnpushed")) == "1"), _rows(widget)

    _git(project, "push", "-q", "origin", "HEAD")
    assert _until(lambda: i18n.t("gitUnpushed") not in _rows(widget)), _rows(widget)


def test_a_file_changed_reads_as_a_change_after_a_ledger_write(repo, host):
    """The window's reload calls `show`; the count is the method's, not the first paint's."""
    project, _bare = repo
    widget, panel = host()
    panel.show()
    assert _until(lambda: _settled(panel))
    assert _rows(widget)[i18n.t("gitChanges")] == i18n.t("gitClean")

    _write(project, "state/v_003.json")
    panel.show()  # what the window's reload does after a ledger write

    assert _until(lambda: _rows(widget)[i18n.t("gitChanges")] == "1"), _rows(widget)


def test_a_burst_of_ledger_writes_is_one_read(repo, host, monkeypatch):
    monkeypatch.setattr(project_github, "COALESCE_MS", 80)
    project, _bare = repo
    starts = []
    real = project_repo.read
    monkeypatch.setattr(project_repo, "read", lambda p: starts.append(p) or real(p))
    widget, panel = host()

    for _ in range(12):
        panel.show()
        QApplication.processEvents()

    assert _until(lambda: panel.idle() and starts), starts
    assert _until(lambda: panel.idle() and len(starts) >= 1)
    time.sleep(0.15)
    QApplication.processEvents()
    assert len(starts) == 1, starts


def test_a_write_during_a_read_reads_once_more_not_many_times(repo, host, monkeypatch):
    release, entered = threading.Event(), threading.Event()
    starts = []
    real = project_repo.read

    def slow(project):
        starts.append(project)
        if len(starts) == 1:
            entered.set()
            assert release.wait(15)
        return real(project)

    monkeypatch.setattr(project_repo, "read", slow)
    widget, panel = host()
    panel.show()
    assert _until(entered.is_set)
    for _ in range(5):
        panel.request()
        _until(lambda: False, 0.03)
    release.set()

    assert _until(lambda: panel.idle() and len(starts) == 2), starts
    _until(lambda: False, 0.2)
    assert len(starts) == 2, starts


def test_the_read_never_runs_on_the_gui_thread(repo, host, monkeypatch):
    seen = []
    real = project_repo.read
    monkeypatch.setattr(project_repo, "read",
                        lambda p: seen.append(threading.current_thread()) or real(p))
    widget, panel = host()
    panel.show()

    assert _until(lambda: panel.idle() and seen)
    assert seen[0] is not threading.main_thread()


def test_its_own_fetch_does_not_start_another_read(repo, host, monkeypatch):
    starts = []
    real = project_repo.read
    monkeypatch.setattr(project_repo, "read", lambda p: starts.append(p) or real(p))
    widget, panel = host()
    panel.show()

    assert _until(lambda: _settled(panel))
    _until(lambda: False, 0.6)

    assert len(starts) == 1, starts


def test_a_window_nobody_sees_goes_to_no_remote(repo, host, monkeypatch):
    """Every test window that never shows would otherwise start a method child on its folder."""
    starts = []
    monkeypatch.setattr(project_repo, "read", lambda p: starts.append(p) or {})
    widget, panel = host(shown=False)

    panel.show()
    _until(lambda: False, 0.3)

    assert starts == []


def test_an_answer_for_another_folder_is_dropped(repo, host, monkeypatch, tmp_path):
    project, _bare = repo
    release, entered = threading.Event(), threading.Event()
    real = project_repo.read

    def held(where):
        entered.set()
        assert release.wait(15)
        return real(where)

    monkeypatch.setattr(project_repo, "read", held)
    widget, panel = host()
    panel.show()
    assert _until(entered.is_set)
    other = tmp_path / "other-car"
    other.mkdir()
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: other)
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: other)
    release.set()

    assert _until(panel.idle)
    assert panel._read is None


def test_a_close_mid_read_stops_the_thread_without_an_abort(repo, host, monkeypatch):
    release, entered = threading.Event(), threading.Event()

    def held(_where):
        entered.set()
        release.wait(15)
        return {}

    monkeypatch.setattr(project_repo, "read", held)
    widget, panel = host()
    panel.show()
    assert _until(entered.is_set)
    monkeypatch.setattr(qt_shutdown, "QUIT_WAIT_MS", 50)

    panel.stop()
    running = [w for w in qt_shutdown.detached() if isinstance(w, QThread)]
    release.set()

    assert running, "a job past the wait is handed over, never dropped"
    assert _until(lambda: not qt_shutdown.detached() and not qt_shutdown.live())
    assert panel._read is None, "a stopped panel takes no answer"


def test_a_project_with_no_repository_starts_no_read(repo, host, monkeypatch, tmp_path):
    empty = tmp_path / "bare-folder"
    empty.mkdir()
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: empty)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: empty)
    starts = []
    monkeypatch.setattr(project_repo, "read", lambda p: starts.append(p) or {})
    widget, panel = host()
    widget._built_on = empty

    panel.show()
    _until(lambda: False, 0.2)

    assert starts == []
    assert widget._project_section.sub_text() == i18n.t("gitSubNoRepo")
    assert widget._backup_step == 0


def test_the_window_shows_the_read_and_a_read_starts_no_reload(repo, monkeypatch):
    """The whole wiring on the real window: a commit moves the rows, no project reload is started
    (a reload wipes the capture grid, #225), and looking at an old version (#249) changes nothing,
    because the state is of the folder."""
    from tests.test_project_repo import _window

    project, _bare = repo
    window = _window(project, monkeypatch)
    window.show()
    reloads = []
    monkeypatch.setattr(window, "_safe_load_project", lambda *a, **k: reloads.append(a))
    panel = window._github
    try:
        window._set_project_params(None)
        assert _until(lambda: _settled(panel))
        # An empty commit: nothing the window's project watcher holds moves, only `.git`.
        _git(project, "commit", "--allow-empty", "-q", "-m", "banked")
        assert _until(lambda: _rows(window).get(i18n.t("gitUnpushed")) == "1"), _rows(window)
        assert reloads == []

        before = _rows(window)
        window._shown_key = "v_001"
        window._set_project_params(None, reuse_git=True)
        assert _rows(window) == before
    finally:
        window._github.stop()
        for worker in list(qt_shutdown.live()) + list(qt_shutdown.detached()):
            worker.wait(20000)
