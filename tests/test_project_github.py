"""«Project on GitHub» in the left panel (#235): a real repository and a bare remote in `tmp_path`,
the method's real `project_repo.py`, no network. The tests read what the person sees and what
landed on the remote.

A stand-in host carries the real section and strip contract, so only the wiring test builds the
window. Everything that starts a thread stops it: the fixture stops the panel before `tmp_path`
goes.
"""

from __future__ import annotations

import datetime
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
from autosound_tcc.ui.tcc import copy_menu, github_view, i18n, project_github, qt_shutdown  # noqa: E402
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


# ── (b) Names on hover ───────────────────────────────────────────────────────────────────────────

def _labels(widget, key_text):
    """The row whose key reads `key_text`: its key label and its value label."""
    labels = widget._project_section.findChildren(QLabel)
    keys = [x for x in labels if x.property("class") == "pk" and copy_menu.full_text(x) == key_text]
    assert keys, key_text
    row = keys[0].parentWidget()
    value = next(x for x in row.findChildren(QLabel) if x.property("class") == "pv")
    return keys[0], value


def _tip(widget, key_text) -> str:
    return _labels(widget, key_text)[1].toolTip()


def test_the_changes_row_names_the_files_by_kind_on_hover(repo, host):
    project, _bare = repo
    _write(project, "state/v_009.json")
    _write(project, ".sessions.log", "a session's log\n")
    widget, panel = host()
    panel.show()

    assert _until(lambda: _settled(panel) and _rows(widget).get(i18n.t("gitChanges")) == "2"), _rows(widget)
    tip = _tip(widget, i18n.t("gitChanges"))

    assert i18n.t("gitTipTuning").format(n=1) in tip and "state/v_009.json" in tip
    assert i18n.t("gitTipHousekeeping").format(n=1) in tip and ".sessions.log" in tip
    assert tip.index("state/v_009.json") < tip.index(".sessions.log"), "tuning files first"
    tuning_half = tip[:tip.index(i18n.t("gitTipHousekeeping").format(n=1))]
    assert ".sessions.log" not in tuning_half


def test_the_unsent_row_names_the_commits_and_what_github_holds(repo, host):
    project, _bare = repo
    pushed = _git(project, "rev-parse", "HEAD")
    new = _commit(project, "docs/notes.md", "a banked version")
    widget, panel = host()
    panel.show()

    assert _until(lambda: _settled(panel) and _rows(widget).get(i18n.t("gitUnpushed")) == "1"), _rows(widget)
    tip = _tip(widget, i18n.t("gitUnpushed"))

    assert new[:7] in tip and "a banked version" in tip
    until = i18n.t("gitOnGithubUntil").format(hash=pushed[:7], time=github_view.when(_commit_time(project, pushed)))
    assert until in tip
    assert until in _tip(widget, i18n.t("gitBackup"))


def _commit_time(project, rev: str) -> str:
    return _git(project, "log", "-1", "--format=%cI", rev)


def test_a_clean_project_says_what_github_holds(repo, host):
    project, _bare = repo
    widget, panel = host()
    panel.show()

    assert _until(lambda: _settled(panel))
    pushed = _git(project, "rev-parse", "HEAD")
    expected = i18n.t("gitOnGithubUntil").format(hash=pushed[:7], time=github_view.when(_commit_time(project, pushed)))
    assert expected in _tip(widget, i18n.t("gitBackup"))
    assert _labels(widget, i18n.t("gitChanges"))[1].toolTip() == ""


def test_a_remote_never_pushed_to_says_so(repo, host, tmp_path):
    project, _bare = repo
    _git(project, "remote", "remove", "origin")
    empty = tmp_path / "empty.git"
    subprocess.run(["git", "init", "-q", "--bare", str(empty)], check=True, capture_output=True, timeout=60)
    _git(project, "remote", "add", "origin", str(empty))
    widget, panel = host()
    panel.show()

    assert _until(lambda: _settled(panel) and i18n.t("gitUnpushed") in _rows(widget)), _rows(widget)
    assert i18n.t("gitOnGithubNever") in _tip(widget, i18n.t("gitBackup"))


def test_a_long_list_is_cut_with_how_many_more():
    answer = {"repo": True, "remote": "x", "changes": {"tuning": [f"m{i}.txt" for i in range(30)], "housekeeping": []},
              "ahead": [], "remote_head": None, "sends": "person"}
    tip = github_view.changes_tip(github_view.from_status(answer))

    assert "m0.txt" in tip and "m29.txt" not in tip
    assert i18n.t("gitTipMore").format(n=30 - github_view.NAMES_IN_TIP) in tip


def test_a_time_reads_today_or_with_its_day():
    now = datetime.datetime.now().astimezone()
    today = now.replace(hour=9, minute=5, second=0, microsecond=0)
    assert github_view.when(today.isoformat(timespec="seconds")) == "09:05"
    earlier = today - datetime.timedelta(days=3)
    assert github_view.when(earlier.isoformat(timespec="seconds")) == f"{earlier:%d.%m} 09:05"
    assert github_view.when("not a time") == "not a time"


# ── (c) The dot and the labels by severity, and the words not cut ────────────────────────────────

def _state(widget, panel) -> tuple:
    section = widget._project_section
    return section.dot_status(), section.sub_text()


def _sev(widget, key_text):
    key, value = _labels(widget, key_text)
    return key.property("sev"), value.property("sev")


def _status_stub(monkeypatch, **fields) -> None:
    answer = {"repo": True, "remote": "git@github.com:o/car.git", "gh": "absent", "init": None, "offer": None,
              "changes": {"tuning": [], "housekeeping": []}, "ahead": [],
              "remote_head": {"hash": "a" * 40, "time": "2026-11-01T10:00:00+00:00"}, "fetched": None,
              "fetch_error": None, "changes_error": None, "sends": "person"}
    answer.update(fields)
    monkeypatch.setattr(project_repo, "read", lambda _p: dict(answer))


def _painted(repo, host):
    widget, panel = host()
    panel.show()
    assert _until(lambda: _settled(panel))
    return widget, panel


def test_all_clear_is_green_only_when_the_real_read_says_so(repo, host):
    widget, panel = _painted(repo, host)
    assert _state(widget, panel) == ("done", i18n.t("gitSubOk"))
    assert widget._project_section._sub_label.property("sev") in (None, "")


def test_a_tuning_file_uncommitted_is_red_and_its_row_is_too(repo, host):
    project, _bare = repo
    _write(project, "state/v_010.json")
    widget, panel = _painted(repo, host)

    assert _state(widget, panel) == ("bad", i18n.t("gitSubUnsaved").format(n=1))
    assert _sev(widget, i18n.t("gitChanges")) == ("bad", "bad")
    assert widget._project_section._sub_label.property("sev") == "bad"


def test_only_housekeeping_uncommitted_is_amber(repo, host):
    project, _bare = repo
    _write(project, ".sessions.log")
    widget, panel = _painted(repo, host)

    assert _state(widget, panel) == ("wait", i18n.t("gitSubHousekeeping").format(n=1))
    assert _sev(widget, i18n.t("gitChanges")) == ("wait", "wait")


def test_commits_not_on_github_are_amber(repo, host):
    project, _bare = repo
    _commit(project, "docs/x.md")
    widget, panel = _painted(repo, host)

    assert _state(widget, panel) == ("wait", i18n.t("gitSubBehind").format(n=1))
    assert _sev(widget, i18n.t("gitUnpushed")) == ("wait", "wait")


def test_a_banked_version_newer_than_the_last_push_is_red(repo, host):
    project, _bare = repo
    _write(project, "state/SQ/v_001.json",
           '{"created": "' + (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat(timespec="seconds") + '"}\n')
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "a banked version, not pushed")
    widget, panel = _painted(repo, host)

    assert _state(widget, panel) == ("bad", i18n.t("gitSubBehind").format(n=1))
    assert _sev(widget, i18n.t("gitUnpushed")) == ("bad", "bad")


def test_a_null_is_could_not_read_never_zero_and_never_green(repo, host, monkeypatch):
    _status_stub(monkeypatch, changes=None, ahead=None, changes_error="git could not read this project's changes")
    widget, panel = _painted(repo, host)

    assert _state(widget, panel) == ("wait", i18n.t("gitSubUnread"))
    assert _rows(widget)[i18n.t("gitChanges")] == "?"
    assert _rows(widget)[i18n.t("gitUnpushed")] == "?"
    assert "git could not read this project's changes" in widget._project_section._sub_label.toolTip()


def test_a_read_that_never_answered_says_so_with_the_reason(repo, host, monkeypatch):
    monkeypatch.setattr(project_repo, "read", lambda _p: project_repo.RepoResult(False, "the method timed out"))
    widget, panel = _painted(repo, host)

    assert _state(widget, panel) == ("wait", i18n.t("gitSubUnread"))
    assert "the method timed out" in widget._project_section._sub_label.toolTip()


def test_offline_is_not_all_clear_and_says_why(repo, host):
    """The real method, a remote that cannot be reached: `fetch_error`, and the dot amber."""
    project, _bare = repo
    _git(project, "remote", "set-url", "origin", str(project.parent / "no-such-remote.git"))
    widget, panel = _painted(repo, host)

    dot, sub = _state(widget, panel)
    assert dot == "wait" and sub == i18n.t("gitSubOffline")
    assert panel._read.fetch_error
    assert panel._read.fetch_error[:30] in widget._project_section._sub_label.toolTip()


def test_a_tuning_change_stays_red_even_offline(repo, host):
    project, _bare = repo
    _git(project, "remote", "set-url", "origin", str(project.parent / "no-such-remote.git"))
    _write(project, "state/v_011.json")
    widget, panel = _painted(repo, host)

    assert _state(widget, panel)[0] == "bad"
    assert panel._read.fetch_error


def test_a_detached_head_is_never_green(repo, host):
    project, _bare = repo
    _git(project, "checkout", "-q", "--detach")
    widget, panel = _painted(repo, host)

    dot, sub = _state(widget, panel)
    assert dot == "wait" and sub == i18n.t("gitSubDetached")


def test_a_project_from_before_the_methods_status_keeps_its_first_read(repo, host, monkeypatch):
    """An older copy of the method answers with the five keys: the panel stays as it was, no
    Send and no «could not read»."""
    monkeypatch.setattr(project_repo, "read", lambda _p: {"repo": True, "remote": "x", "gh": "absent",
                                                          "init": None, "offer": None})
    widget, panel = host()
    panel.show()

    assert _until(panel.idle)
    assert panel._read is None
    assert _state(widget, panel) == ("done", i18n.t("gitSubOk"))


def test_the_status_is_whole_at_the_narrowest_column_in_every_language(repo, monkeypatch):
    """The header read «не ві…» at the 30.10 session. It takes the sub off the title's line and
    gives it the column, at the 200 px floor, the typewriter look and every language."""
    from autosound_tcc.ui.tcc import font_looks, labels
    from tests.test_project_repo import _window

    project, _bare = repo
    window = _window(project, monkeypatch)
    window.show()
    panel = window._github
    window._settings.setValue(font_looks.KEY, font_looks.TYPEWRITER)
    window._restyle()
    section = window._project_section
    subs = ("gitSubUnsaved", "gitSubBehind", "gitSubOffline", "gitSubUnread", "gitSubHousekeeping", "gitSubDetached",
            "gitSubOk", "gitSubNoRemote")
    keys = ("gitChanges", "gitUnpushed", "gitBackup")
    try:
        for lang in ("en", "uk", "pl", "de"):
            monkeypatch.setattr(i18n, "_lang", lang)
            window._left.setFixedWidth(max(200, font_looks.left_floor(window)))
            QApplication.processEvents()
            for key in subs:
                text = i18n.t(key).format(n=12)
                section.set_sub(text)
                QApplication.processEvents()
                assert section._sub_label.text() == text, (lang, key, section._sub_label.width())
            _status_stub(monkeypatch, changes={"tuning": ["a"] * 12, "housekeeping": []}, ahead=[
                {"hash": "b" * 40, "time": "2026-11-01T10:00:00+00:00", "subject": "x"}] * 12)
            panel._read = github_view.from_status(project_repo.read(project))
            panel._read_of = project
            panel._paint(project)
            QApplication.processEvents()
            for key in keys[:2]:
                label, value = _labels(window, i18n.t(key))
                row = label.parentWidget()
                room = row.width() - row.layout().contentsMargins().left() - row.layout().contentsMargins().right() \
                    - row.layout().spacing() - value.width()
                whole = label.text() == i18n.t(key)
                assert whole or label.width() >= room - 1, (lang, key, label.text())
                assert isinstance(label, labels.ElidedLabel)
    finally:
        window._github.stop()
        for worker in list(qt_shutdown.live()) + list(qt_shutdown.detached()):
            worker.wait(20000)


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
