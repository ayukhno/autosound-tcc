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
import re
import subprocess
import threading
import time
from collections import Counter
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt, QThread  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget  # noqa: E402

from autosound_tcc.core import config, project_repo, vendor_loader  # noqa: E402
from autosound_tcc.ui.tcc import copy_menu, github_view, i18n, project_github, qt_shutdown, theme  # noqa: E402
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
    widget._built_on = other  # the window itself moved on; a cancelled switch is the next section's
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


def test_a_gitignore_alone_is_no_unsaved_work(repo, host):
    """TCC itself teaches `.gitignore` on a project's first start, and the method counts it as a
    tuning file: every project went red for an edit of TCC's own. It goes with the next save."""
    project, _bare = repo
    (project / ".gitignore").write_text(".tcc/\n.mcp.json\n", encoding="utf-8")
    widget, panel = _painted(repo, host)

    assert _state(widget, panel)[0] != "bad"
    assert _sev(widget, i18n.t("gitChanges"))[0] != "bad"
    assert _send_button(widget) is None


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
                coloured = label.grab().toImage()
                label.setProperty("sev", None)
                label.style().unpolish(label)
                label.style().polish(label)
                QApplication.processEvents()
                assert label.grab().toImage() != coloured, "the `sev` property must reach the sheet"
    finally:
        window._github.stop()
        for worker in list(qt_shutdown.live()) + list(qt_shutdown.detached()):
            worker.wait(20000)


# ── (d) «Відправити» ─────────────────────────────────────────────────────────────────────────────

def _send_button(widget):
    found = [b for b in widget._project_section.findChildren(QPushButton)
             if b.text() in (i18n.t("gitSendBtn"), i18n.t("gitSendingBtn"))]
    return found[0] if found else None


def _answer(monkeypatch, *answers):
    """`QMessageBox.exec` answers in turn and keeps what it was asked; nothing is drawn."""
    asked = []
    queue = list(answers)

    def _exec(box):
        asked.append(box.text())
        answer = queue.pop(0) if queue else QMessageBox.StandardButton.No
        return answer(box) if callable(answer) else answer

    monkeypatch.setattr(QMessageBox, "exec", _exec)
    return asked


def _on_remote(bare) -> list[str]:
    head = _git(bare, "rev-parse", "HEAD")
    return _git(bare, "ls-tree", "-r", "--name-only", head).split("\n")


def _strip(widget) -> str:
    return widget._status_strip.said[-1][0] if widget._status_strip.said else ""


YES, NO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No


def _ready(repo, host):
    project, _bare = repo
    _write(project, "state/v_020.json")
    _write(project, "process/journal.jsonl")
    widget, panel = host()
    panel.show()
    assert _until(lambda: _settled(panel) and _send_button(widget) is not None), (_rows(widget), panel._read)
    return widget, panel


def test_the_button_says_no_when_there_is_nothing_to_send_or_nowhere(repo, host, monkeypatch, tmp_path):
    project, _bare = repo
    widget, panel = _painted(repo, host)
    assert _send_button(widget) is None, "a clean project has nothing to send"

    _write(project, "state/v_021.json")
    panel.request()
    assert _until(lambda: _send_button(widget) is not None)

    _git(project, "remote", "remove", "origin")
    panel.show()
    assert _until(lambda: _settled(panel) and panel._read.remote is None)
    assert _send_button(widget) is None, "no remote, nowhere to send"


def test_no_button_for_a_read_that_could_not_be_read_or_a_detached_head(repo, host, monkeypatch):
    _status_stub(monkeypatch, changes=None, ahead=None)
    widget, panel = _painted(repo, host)
    assert _send_button(widget) is None

    project, _bare = repo
    _status_stub(monkeypatch, changes={"tuning": ["a"], "housekeeping": []}, ahead=[])
    _git(project, "checkout", "-q", "--detach")
    panel.show()
    assert _until(lambda: _settled(panel) and panel._git.detached)
    assert _send_button(widget) is None


def test_the_method_session_rule_keeps_the_button_as_the_spare(repo, host):
    """`project_seed`: «the session; TCC's button is the spare». The row says who sends."""
    widget, panel = _ready(repo, host)

    assert panel._read.sends == "session"
    assert _rows(widget)[i18n.t("gitSendsRow")] == i18n.t("gitSendsSession")
    assert _send_button(widget).hover_tip._text == i18n.t("gitSendTipSpare")


def test_a_project_seeded_before_the_rule_says_the_person_sends(repo, host):
    project, _bare = repo
    for name in ("CLAUDE.md", "AGENTS.md"):
        _write(project, name, "# their own\n")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "their own files")
    _git(project, "push", "-q", "origin", "HEAD")
    widget, panel = _painted(repo, host)

    assert panel._read.sends == "person"
    assert _rows(widget)[i18n.t("gitSendsRow")] == i18n.t("gitSendsPerson")


def test_the_confirmation_names_the_files_the_commits_and_the_remote(repo, host, monkeypatch):
    project, _bare = repo
    _commit(project, "docs/note.md", "a commit already made")
    widget, panel = _ready(repo, host)
    asked = _answer(monkeypatch, NO)

    _send_button(widget).click()

    assert _until(lambda: asked), widget._status_strip.said
    text = asked[0]
    assert i18n.t("gitSendFilesLine").format(n=2) in text
    assert i18n.t("gitSendCommitsLine").format(n=1) in text
    assert panel._git.remote in text
    for name in ("state/v_020.json", "process/journal.jsonl", "a commit already made"):
        assert name in text, (name, text)


def test_no_sends_nothing(repo, host, monkeypatch):
    project, bare = repo
    head = _git(bare, "rev-parse", "HEAD")
    widget, panel = _ready(repo, host)
    _answer(monkeypatch, NO)

    _send_button(widget).click()
    assert _until(panel.idle)

    assert _git(bare, "rev-parse", "HEAD") == head and _git(project, "rev-parse", "HEAD") == head
    assert "state/v_020.json" in _git(project, "status", "--porcelain", "--untracked-files=all")
    assert _send_button(widget).isEnabled()


def test_yes_sends_the_tuning_files_and_the_outcome_is_the_methods_words(repo, host, monkeypatch):
    project, bare = repo
    before = set(_on_remote(bare))
    widget, panel = _ready(repo, host)
    asked = _answer(monkeypatch, YES)

    _send_button(widget).click()

    assert _until(lambda: _send_button(widget) is None and panel.idle()), widget._status_strip.said
    assert len(asked) == 1
    assert _git(bare, "rev-parse", "HEAD") == _git(project, "rev-parse", "HEAD")
    assert set(_on_remote(bare)) == before | {"state/v_020.json", "process/journal.jsonl"}
    said = _strip(widget)
    assert said.startswith(i18n.t("gitSendDone").format(said="").rstrip()) and "sent to origin" in said
    assert not said.startswith("✓")
    assert _until(lambda: _settled(panel) and panel._read.remote_head.hash == _git(project, "rev-parse", "HEAD"))
    assert i18n.t("gitOnGithubUntil").format(hash=_git(project, "rev-parse", "--short=7", "HEAD"),
                                             time=github_view.when(_commit_time(project, "HEAD"))) \
        in _tip(widget, i18n.t("gitBackup"))


def test_the_key_the_link_and_the_logs_never_go(repo, host, monkeypatch):
    """A clone must not get the machine's key or link. The older-project shape: nothing in
    `.gitignore` names them, and the link is a real folder here, which is what git would take."""
    project, bare = repo
    (project / ".gitignore").unlink()
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "an older project: no .gitignore")
    _git(project, "push", "-q", "origin", "HEAD")
    before = set(_on_remote(bare))
    _write(project, ".tcc/mcp-token", "secret\n")
    _write(project, ".sessions.log", "log\n")
    _write(project, ".agents/note.md", "a session's own\n")
    _write(project, ".autosound/state.json", "{}\n")
    link = project / ".claude" / "skills" / "autosound-tuning"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(vendor_loader.REW_TOOL_DIR.parent, target_is_directory=True)
    except OSError:  # Windows without the right to make one: the method's selftest covers a junction
        pass
    _write(project, "state/v_022.json")
    widget, panel = _ready(repo, host)
    _answer(monkeypatch, YES)

    _send_button(widget).click()
    assert _until(lambda: _send_button(widget) is None and panel.idle()), widget._status_strip.said

    assert set(_on_remote(bare)) == before | {"state/v_020.json", "state/v_022.json", "process/journal.jsonl"}


def test_asked_before_each_send(repo, host, monkeypatch):
    project, bare = repo
    widget, panel = _ready(repo, host)
    asked = _answer(monkeypatch, YES, NO)

    _send_button(widget).click()
    assert _until(lambda: _send_button(widget) is None and panel.idle())
    _write(project, "state/v_023.json")
    panel.request()
    assert _until(lambda: _settled(panel) and _send_button(widget) is not None)
    _send_button(widget).click()
    assert _until(lambda: len(asked) == 2 and panel.idle())

    assert len(asked) == 2


def test_a_refusal_is_said_in_the_methods_words(repo, host, monkeypatch, tmp_path):
    project, bare = repo
    widget, panel = _ready(repo, host)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True, capture_output=True, timeout=60)
    _commit(other, "from-elsewhere.txt")
    _git(other, "push", "-q", "origin", "HEAD")
    asked = _answer(monkeypatch, YES)

    _send_button(widget).click()

    assert _until(lambda: "pull first" in _strip(widget)), widget._status_strip.said
    assert len(asked) == 1
    assert widget._status_strip.said[-1][1] == "warn"
    assert not _strip(widget).lstrip().startswith("✗")
    assert "state/v_020.json" in _git(project, "status", "--porcelain", "--untracked-files=all")


def test_a_second_press_starts_no_second_send(repo, host, monkeypatch):
    project, bare = repo
    widget, panel = _ready(repo, host)
    _answer(monkeypatch, YES)
    real, release, entered, sends = project_repo.save, threading.Event(), threading.Event(), []

    def held(where, dry_run=False):
        if not dry_run:
            sends.append(where)
            entered.set()
            assert release.wait(20)
        return real(where, dry_run=dry_run)

    monkeypatch.setattr(project_repo, "save", held)
    _send_button(widget).click()
    assert _until(entered.is_set)
    button = _send_button(widget)
    assert button.text() == i18n.t("gitSendingBtn") and not button.isEnabled()

    button.click()
    panel._on_send()

    release.set()
    assert _until(lambda: _send_button(widget) is None and panel.idle())
    assert len(sends) == 1, sends


def test_what_changed_after_the_yes_is_said_and_not_sent(repo, host, monkeypatch):
    """A session can bank between the question and the send: the person was not asked about that.
    It goes nowhere, it is said, and the next press asks about what is there."""
    project, bare = repo
    head = _git(bare, "rev-parse", "HEAD")
    before = set(_on_remote(bare))
    widget, panel = _ready(repo, host)

    def yes_and_a_new_file(_box):
        _write(project, "state/v_024.json")
        return YES

    asked = _answer(monkeypatch, yes_and_a_new_file, YES)
    _send_button(widget).click()

    assert _until(lambda: i18n.t("gitSendChanged") in _strip(widget)), widget._status_strip.said
    assert _git(bare, "rev-parse", "HEAD") == head, "what was not asked about does not go"

    assert _until(lambda: _settled(panel) and _send_button(widget) is not None and _send_button(widget).isEnabled())
    _send_button(widget).click()
    assert _until(lambda: _send_button(widget) is None and panel.idle())
    assert len(asked) == 2
    assert set(_on_remote(bare)) == before | {"state/v_020.json", "process/journal.jsonl", "state/v_024.json"}


def test_closing_during_the_question_sends_nothing(repo, host, monkeypatch):
    project, bare = repo
    head = _git(bare, "rev-parse", "HEAD")
    widget, panel = _ready(repo, host)

    def stopped(box):
        panel.stop()
        return YES

    _answer(monkeypatch, stopped)
    _send_button(widget).click()
    assert _until(lambda: not qt_shutdown.live() and panel._job is None)

    assert _git(bare, "rev-parse", "HEAD") == head


def test_closing_mid_send_hands_the_thread_over_and_takes_no_answer(repo, host, monkeypatch):
    project, bare = repo
    widget, panel = _ready(repo, host)
    _answer(monkeypatch, YES)
    release, entered = threading.Event(), threading.Event()

    def held(where, dry_run=False):
        if dry_run:
            return project_repo.RepoResult(True, "would send")
        entered.set()
        release.wait(20)
        return project_repo.RepoResult(True, "sent to origin: something")

    monkeypatch.setattr(project_repo, "save", held)
    monkeypatch.setattr(qt_shutdown, "QUIT_WAIT_MS", 50)
    _send_button(widget).click()
    assert _until(entered.is_set)

    panel.stop()
    said_before = list(widget._status_strip.said)
    running = [w for w in qt_shutdown.detached() if isinstance(w, QThread)]
    release.set()

    assert running, "a send past the wait is handed over, never dropped"
    assert _until(lambda: not qt_shutdown.detached() and not qt_shutdown.live())
    _until(lambda: False, 0.1)
    assert widget._status_strip.said == said_before


def test_the_save_bound_is_above_the_sum_of_the_methods_steps(repo, monkeypatch):
    """The method's own bounds, read from its copy: reset, add and push of `PUSH_SECONDS` each, a
    fetch and a look at the remote's branches of `FETCH_SECONDS` each, a commit of 60 s."""
    text = (vendor_loader.REW_TOOL_DIR / "project_repo.py").read_text(encoding="utf-8")
    push = int(re.search(r"^PUSH_SECONDS = (\d+)", text, re.M).group(1))
    fetch = int(re.search(r"^FETCH_SECONDS = (\d+)", text, re.M).group(1))
    assert project_repo._SAVE_TIMEOUT_S > 3 * push + 2 * fetch + 60
    seen = []
    real = project_repo.method_cli.spawn

    def spy(project, script, args, timeout_s, **kw):
        seen.append((args[0], timeout_s))
        return real(project, script, args, timeout_s=timeout_s, **kw)

    monkeypatch.setattr(project_repo.method_cli, "spawn", spy)
    project_repo.save(repo[0], dry_run=True)

    assert seen == [("save", project_repo._SAVE_TIMEOUT_S)]


def test_a_method_without_save_says_update(repo, monkeypatch):
    """A project bound to a copy from before `save`: exit 2, its usage text; TCC says update."""
    import tests.test_project_repo as trepo

    project, _bare = repo
    trepo._own_copy(project.parent, monkeypatch, "import sys; print('usage'); sys.exit(2)")

    result = project_repo.save(project, dry_run=True)

    assert result.too_old and not result.ok


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

        window.stop_workers()
        assert panel._stopped, "the window's close stops the panel"
    finally:
        window._github.stop()
        for worker in list(qt_shutdown.live()) + list(qt_shutdown.detached()):
            worker.wait(20000)


# ── (e) The panel's folder is the window's: a cancelled switch (#235's review) ───────────────────

def _second_project(tmp_path):
    """(project, bare): another repository with its own remote, what a switch points the process at."""
    other, bare = tmp_path / "other-car", tmp_path / "other.git"
    other.mkdir()
    _write(other, "project.json", "{}\n")
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True, timeout=60)
    assert project_repo.init(other).ok
    _git(other, "remote", "add", "origin", str(bare))
    _git(other, "push", "-q", "-u", "origin", "HEAD")
    return other, bare


def _process_folder_is(monkeypatch, folder) -> None:
    """What Open folder does before the close that Cancel then stops (`window_folder`)."""
    monkeypatch.setattr(config, "project_dir", lambda *_a, **_k: folder)
    monkeypatch.setattr(config, "chosen_project_dir", lambda *_a, **_k: folder)


def test_after_a_cancelled_switch_send_is_refused_and_nothing_goes(repo, host, monkeypatch, tmp_path):
    project, bare = repo
    widget, panel = _ready(repo, host)
    other, other_bare = _second_project(tmp_path)
    _write(other, "state/v_900.json")
    heads = _git(bare, "rev-parse", "HEAD"), _git(other_bare, "rev-parse", "HEAD")
    _process_folder_is(monkeypatch, other)
    asked = _answer(monkeypatch, YES)

    _send_button(widget).click()
    assert _until(panel.idle)

    assert asked == [], "the question of one project, the push of another"
    assert (_git(bare, "rev-parse", "HEAD"), _git(other_bare, "rev-parse", "HEAD")) == heads
    assert i18n.t("projectStillShows").format(old=project, new=other) in [said for said, _level in widget._status_strip.said]


def test_after_a_cancelled_switch_the_rows_stay_this_windows(repo, host, monkeypatch, tmp_path):
    """A rebuild, with or without a fresh read, paints this window's folder; no read of either."""
    widget, panel = _painted(repo, host)
    other, _other_bare = _second_project(tmp_path)
    _write(other, "state/v_900.json")
    starts = []
    monkeypatch.setattr(project_repo, "read", lambda p: starts.append(p) or {})
    _process_folder_is(monkeypatch, other)

    panel.show(reuse=True)
    assert _rows(widget)[i18n.t("gitChanges")] == i18n.t("gitClean"), _rows(widget)
    panel.show()
    assert _rows(widget)[i18n.t("gitChanges")] == i18n.t("gitClean"), _rows(widget)
    assert _until(panel.idle)
    _until(lambda: False, 0.2)

    assert starts == [], "a window pinned to one folder reads neither after the switch"


def test_a_read_landing_after_a_cancelled_switch_is_the_windows_own(repo, host, monkeypatch, tmp_path):
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
    other, _other_bare = _second_project(tmp_path)
    _process_folder_is(monkeypatch, other)
    release.set()

    assert _until(panel.idle)
    assert panel._read is not None and panel._read_of == project


def test_a_switch_drops_the_stored_read(repo, host, monkeypatch, tmp_path):
    widget, panel = _ready(repo, host)
    other, _other_bare = _second_project(tmp_path)
    _process_folder_is(monkeypatch, other)
    widget._built_on = other

    panel.show()

    assert _send_button(widget) is None, "a Send button holding the old project's read"
    assert _rows(widget)[i18n.t("gitChanges")] == i18n.t("gitClean"), _rows(widget)
    assert _until(panel.idle)


def test_a_switch_during_a_send_reads_nothing_of_the_new_folder(repo, host, monkeypatch, tmp_path):
    widget, panel = _ready(repo, host)
    other, _other_bare = _second_project(tmp_path)
    starts = []
    real_read = project_repo.read
    release, entered = _held_save(monkeypatch)  # no commit, so no event of `.git` starts a read either
    monkeypatch.setattr(project_repo, "read", lambda p: starts.append(Path(p)) or real_read(p))
    _answer(monkeypatch, YES)
    _send_button(widget).click()
    assert _until(entered.is_set)

    _process_folder_is(monkeypatch, other)
    widget._built_on = other
    release.set()

    assert _until(lambda: panel._send is None and panel.idle(), 15), widget._status_strip.said
    _until(lambda: False, 0.2)
    assert other not in starts, starts


# ── (f) A job that raises, a shape nobody expected ───────────────────────────────────────────────

def test_a_worker_raising_in_a_send_says_it_and_gives_the_button_back(repo, host, monkeypatch):
    widget, panel = _ready(repo, host)
    _answer(monkeypatch, YES)

    def boom(_where, dry_run=False):
        raise RuntimeError("the method fell over")

    monkeypatch.setattr(project_repo, "save", boom)
    _send_button(widget).click()

    assert _until(lambda: panel._send is None and panel.idle(), 8), (panel._send, widget._status_strip.said)
    assert "the method fell over" in _strip(widget) and widget._status_strip.said[-1][1] == "warn"
    assert _send_button(widget).isEnabled()


def test_a_read_that_raises_says_it_could_not_read(repo, host, monkeypatch):
    def boom(_where):
        raise RuntimeError("the method fell over")

    monkeypatch.setattr(project_repo, "read", boom)
    widget, panel = _painted(repo, host)

    assert _state(widget, panel) == ("wait", i18n.t("gitSubUnread"))
    assert "the method fell over" in widget._project_section._sub_label.toolTip()


def test_an_answer_of_an_unexpected_shape_is_could_not_read(repo, host, monkeypatch):
    _status_stub(monkeypatch, ahead=[1, 2])
    widget, panel = _painted(repo, host)

    assert _state(widget, panel) == ("wait", i18n.t("gitSubUnread"))


# ── (g) The read refreshes what the header stands on ─────────────────────────────────────────────

def test_a_sessions_checkout_moves_the_header(repo, host):
    project, _bare = repo
    widget, panel = _painted(repo, host)
    assert _state(widget, panel)[0] == "done"

    _git(project, "checkout", "-q", "--detach")

    assert _until(lambda: _state(widget, panel) == ("wait", i18n.t("gitSubDetached"))), _state(widget, panel)


def test_a_remote_added_outside_the_window_reaches_the_rows(repo, host):
    """`gh repo create --push`, what a session runs: the row said «none» until a reload."""
    project, bare = repo
    _git(project, "remote", "remove", "origin")
    widget, panel = _painted(repo, host)
    assert _rows(widget)[i18n.t("gitBackup")] == i18n.t("gitNone"), _rows(widget)

    _git(project, "remote", "add", "origin", str(bare))
    panel.request()

    assert _until(lambda: panel.idle() and _rows(widget)[i18n.t("gitBackup")] != i18n.t("gitNone")), _rows(widget)


def test_the_question_names_the_remote_of_the_last_read(repo, host, monkeypatch, tmp_path):
    project, bare = repo
    widget, panel = _ready(repo, host)
    other_bare = tmp_path / "moved-copy.git"  # the same history: a remote that moved, not a pull to make
    subprocess.run(["git", "clone", "-q", "--bare", str(bare), str(other_bare)], check=True, capture_output=True, timeout=60)
    _git(project, "remote", "set-url", "origin", str(other_bare))
    panel.request()
    assert _until(lambda: panel.idle() and str(panel._read.remote) == str(other_bare))
    asked = _answer(monkeypatch, NO)

    _send_button(widget).click()

    assert asked and str(other_bare)[:-4] in asked[0], asked


def test_a_remote_repointed_after_the_yes_is_not_sent_to(repo, host, monkeypatch, tmp_path):
    project, bare = repo
    head = _git(bare, "rev-parse", "HEAD")
    widget, panel = _ready(repo, host)
    empty = tmp_path / "elsewhere.git"
    subprocess.run(["git", "init", "-q", "--bare", str(empty)], check=True, capture_output=True, timeout=60)

    def yes_and_repoint(_box):
        _git(project, "remote", "set-url", "origin", str(empty))
        return YES

    _answer(monkeypatch, yes_and_repoint)
    _send_button(widget).click()

    assert _until(lambda: i18n.t("gitSendChanged") in _strip(widget)), widget._status_strip.said
    assert _git(bare, "rev-parse", "HEAD") == head
    assert _git(empty, "rev-list", "--all", "--count") == "0"


# ── (h) What the question promises ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rewrite", [
    lambda path: path.write_text("rewritten, longer than it was\n", encoding="utf-8"),
    lambda path: os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000)),
], ids=["size", "mtime"])
def test_a_named_file_rewritten_after_the_question_is_not_sent(repo, host, monkeypatch, rewrite):
    project, bare = repo
    head = _git(bare, "rev-parse", "HEAD")
    widget, panel = _ready(repo, host)

    def yes_and_rewrite(_box):
        rewrite(project / "state/v_020.json")
        return YES

    _answer(monkeypatch, yes_and_rewrite)
    _send_button(widget).click()

    assert _until(lambda: i18n.t("gitSendChanged") in _strip(widget)), widget._status_strip.said
    assert _git(bare, "rev-parse", "HEAD") == head


def test_the_question_says_how_many_names_it_left_out_and_what_it_cannot_list():
    answer = {"repo": True, "remote": "git@github.com:o/car.git",
              "changes": {"tuning": [f"m{i}.txt" for i in range(30)], "housekeeping": []},
              "ahead": [{"hash": f"{i:040d}", "time": "2026-11-01T10:00:00+00:00", "subject": f"c{i}"} for i in range(14)],
              "remote_head": None, "sends": "person"}

    text = github_view.confirm_text(github_view.from_status(answer))

    assert "github.com/o/car" in text
    assert "m0.txt" in text and "m29.txt" not in text
    assert i18n.t("gitTipMore").format(n=18) in text
    assert i18n.t("gitTipMore").format(n=2) in text
    assert i18n.t("gitSendLeftOut") in text


def test_a_commit_made_after_the_yes_is_not_sent(repo, host, monkeypatch):
    project, bare = repo
    head = _git(bare, "rev-parse", "HEAD")
    widget, panel = _ready(repo, host)

    def yes_and_commit(_box):
        _commit(project, "docs/late.md", "made after the question")
        return YES

    _answer(monkeypatch, yes_and_commit)
    _send_button(widget).click()

    assert _until(lambda: panel._send is None and panel.idle(), 15), widget._status_strip.said
    assert _git(bare, "rev-parse", "HEAD") == head, _on_remote(bare)


def test_a_failed_recheck_sends_nothing_and_says_why(repo, host, monkeypatch):
    _project, bare = repo
    head = _git(bare, "rev-parse", "HEAD")
    widget, panel = _ready(repo, host)
    monkeypatch.setattr(project_repo, "backup_status", lambda _p: project_repo.RepoResult(False, "the method broke"))
    _answer(monkeypatch, YES)

    _send_button(widget).click()

    assert _until(lambda: panel._send is None and panel.idle(), 15), widget._status_strip.said
    assert _git(bare, "rev-parse", "HEAD") == head
    assert "the method broke" in _strip(widget)


# ── (i) Closing during a send ────────────────────────────────────────────────────────────────────

def _held_save(monkeypatch):
    release, entered = threading.Event(), threading.Event()

    def held(_where, dry_run=False):
        entered.set()
        assert release.wait(20)
        return project_repo.RepoResult(True, "sent to origin: something")

    monkeypatch.setattr(project_repo, "save", held)
    return release, entered


def test_closing_the_real_window_during_a_send_asks_first(repo, monkeypatch):
    """Keep waiting keeps the window and the send, and the outcome is still said."""
    from tests.test_project_repo import _window

    project, _bare = repo
    _write(project, "state/v_030.json")
    window = _window(project, monkeypatch)
    window.show()
    panel = window._github
    release, entered = _held_save(monkeypatch)
    try:
        window._set_project_params(None)
        assert _until(lambda: _settled(panel) and _send_button(window) is not None)
        asked = _answer(monkeypatch, YES, NO)
        _send_button(window).click()
        assert _until(entered.is_set)

        assert window.close() is False, "a send under way is asked about"
        assert len(asked) == 2 and i18n.t("gitSendCloseAsk") in asked[1], asked
        assert window.isVisible() and not window._closing

        release.set()
        assert _until(lambda: panel._send is None and panel.idle(), 10)
        assert "sent to origin" in window._status_strip.text()
    finally:
        release.set()
        window._github.stop()
        for worker in list(qt_shutdown.live()) + list(qt_shutdown.detached()):
            worker.wait(20000)


def test_the_windows_own_close_after_saving_does_not_ask_again(repo, host, monkeypatch):
    """A session's save turn ends in the window's own `close()`: the answer was already given."""
    widget, panel = host()
    asked = _answer(monkeypatch, NO)
    panel._send = "sending"
    widget._quitting = True
    try:
        assert panel.may_close() is True and asked == []
    finally:
        panel._send = None
        panel.stop()


def test_reading_the_status_takes_no_lock_of_gits(repo, monkeypatch):
    """The read runs about when a session's `save` commits: an index lock of ours would fail it."""
    from autosound_tcc.state import project_view

    project, _bare = repo
    seen, run = [], subprocess.run

    def spy(argv, *args, **kwargs):
        seen.append(list(argv))
        return run(argv, *args, **kwargs)

    monkeypatch.setattr(project_view.subprocess, "run", spy)
    project_view.git_status(project)
    assert [a for a in seen if "status" in a and "--no-optional-locks" in a], seen


def test_a_close_answered_yes_lets_the_window_go(repo, host, monkeypatch):
    widget, panel = _ready(repo, host)
    release, entered = _held_save(monkeypatch)
    asked = _answer(monkeypatch, YES, YES)
    _send_button(widget).click()
    assert _until(entered.is_set)

    assert project_github.may_close(widget) is True
    assert len(asked) == 2
    release.set()


def test_no_question_at_close_with_no_send_under_way(repo, host, monkeypatch):
    widget, panel = _ready(repo, host)
    asked = _answer(monkeypatch)

    assert project_github.may_close(widget) is True
    assert asked == []


def test_a_close_during_the_status_starts_no_push(repo, host, monkeypatch):
    project, bare = repo
    head = _git(bare, "rev-parse", "HEAD")
    widget, panel = _ready(repo, host)
    real, release, entered, saves = project_repo.backup_status, threading.Event(), threading.Event(), []

    def held(where):
        entered.set()
        assert release.wait(20)
        return real(where)

    monkeypatch.setattr(project_repo, "backup_status", held)
    monkeypatch.setattr(project_repo, "save", lambda *a, **k: saves.append(a) or project_repo.RepoResult(True, "x"))
    monkeypatch.setattr(qt_shutdown, "QUIT_WAIT_MS", 50)
    _answer(monkeypatch, YES)
    _send_button(widget).click()
    assert _until(entered.is_set)

    panel.stop()
    release.set()

    assert _until(lambda: not qt_shutdown.detached() and not qt_shutdown.live())
    assert saves == [] and _git(bare, "rev-parse", "HEAD") == head


def test_stopping_mid_send_does_not_sit_on_the_thread(repo, host, monkeypatch):
    """The push can take minutes; the wait froze the window on its way out for nothing."""
    widget, panel = _ready(repo, host)
    release, entered = _held_save(monkeypatch)
    monkeypatch.setattr(qt_shutdown, "QUIT_WAIT_MS", 4000)
    _answer(monkeypatch, YES)
    _send_button(widget).click()
    assert _until(entered.is_set)

    began = time.monotonic()
    panel.stop()
    took = time.monotonic() - began
    release.set()

    assert took < 2, took


# ── (j) The button's word and its reason ─────────────────────────────────────────────────────────

def test_the_button_says_sending_only_while_sending(repo, host, monkeypatch):
    widget, panel = _ready(repo, host)
    seen = []

    def repainted_during_the_question(_box):
        panel.show(reuse=True)  # a window action repaints the rows under the open question
        seen.append(_send_button(widget).text())
        return NO

    _answer(monkeypatch, repainted_during_the_question)
    _send_button(widget).click()

    assert seen == [i18n.t("gitSendBtn")], seen


def test_a_yes_during_a_read_waits_without_saying_sending_and_still_sends(repo, host, monkeypatch):
    project, bare = repo
    before = set(_on_remote(bare))
    widget, panel = _ready(repo, host)
    release, entered = threading.Event(), threading.Event()
    real = project_repo.read

    def held(where):
        entered.set()
        assert release.wait(15)
        return real(where)

    monkeypatch.setattr(project_repo, "read", held)
    panel.request()
    assert _until(entered.is_set)
    _answer(monkeypatch, YES)

    _send_button(widget).click()
    queued = _send_button(widget)
    assert queued.text() == i18n.t("gitSendBtn") and not queued.isEnabled(), queued.text()

    release.set()
    assert _until(lambda: _send_button(widget) is None and panel.idle(), 8), (panel._send, widget._status_strip.said)
    assert set(_on_remote(bare)) == before | {"state/v_020.json", "process/journal.jsonl"}


def test_send_is_off_with_the_reason_when_a_pull_comes_first(repo, host, monkeypatch, tmp_path):
    project, bare = repo
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True, capture_output=True, timeout=60)
    _commit(other, "from-elsewhere.txt")
    _git(other, "push", "-q", "origin", "HEAD")
    _write(project, "state/v_031.json")

    widget, panel = host()
    panel.show()
    assert _until(lambda: _settled(panel) and _send_button(widget) is not None), (_rows(widget), panel._read)

    button = _send_button(widget)
    assert not button.isEnabled()
    assert button.hover_tip._text == i18n.t("gitSendTipPull").format(n=1)


# ── (k) What the review's mutations showed had no test ───────────────────────────────────────────

def test_a_null_alone_is_could_not_read(repo, host, monkeypatch):
    _status_stub(monkeypatch, ahead=None)
    widget, panel = _painted(repo, host)
    assert _state(widget, panel) == ("wait", i18n.t("gitSubUnread"))


def test_null_changes_alone_are_could_not_read(repo, host, monkeypatch):
    _status_stub(monkeypatch, changes=None)
    widget, panel = _painted(repo, host)
    assert _state(widget, panel) == ("wait", i18n.t("gitSubUnread"))


def test_a_changes_error_alone_is_could_not_read(repo, host, monkeypatch):
    _status_stub(monkeypatch, changes_error="git could not read the remote's last-known commit")
    widget, panel = _painted(repo, host)
    assert _state(widget, panel) == ("wait", i18n.t("gitSubUnread"))


def test_no_button_when_one_half_is_null(repo, host, monkeypatch):
    _status_stub(monkeypatch, changes=None, ahead=[{"hash": "b" * 40, "time": "2026-11-01T10:00:00+00:00", "subject": "x"}])
    widget, panel = _painted(repo, host)
    assert _send_button(widget) is None


def test_a_method_too_old_for_the_read_stays_on_the_first_paint(repo, host, monkeypatch):
    monkeypatch.setattr(project_repo, "read", lambda _p: project_repo.RepoResult(False, "", too_old=True))
    widget, panel = host()
    panel.show()
    assert _until(panel.idle)
    assert panel._read is None and _state(widget, panel) == ("done", i18n.t("gitSubOk")), _state(widget, panel)


def test_a_commit_on_a_remote_not_named_origin_is_not_green(repo, host):
    project, _bare = repo
    _git(project, "remote", "rename", "origin", "backup")
    _commit(project, "docs/x.md")
    widget, panel = _painted(repo, host)
    assert _state(widget, panel)[0] != "done", _state(widget, panel)


def test_a_ledger_older_than_the_push_is_amber(repo, host):
    project, _bare = repo
    _write(project, "state/SQ/v_001.json", '{"created": "2020-01-01T10:00:00+00:00"}\n')
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "old version")
    _git(project, "push", "-q", "origin", "HEAD")
    _commit(project, "docs/x.md")
    widget, panel = _painted(repo, host)
    assert _state(widget, panel) == ("wait", i18n.t("gitSubBehind").format(n=1)), _state(widget, panel)


def _ink(label: QLabel) -> str:
    """The commonest fully opaque colour of `label`: the inside of its glyphs, the transparent ground
    and the edge smoothing left out. The sheet is built at a large scale so stems are many whole
    pixels wide. Not "everything but pixel (0, 0)": where glyphs are boxes that pixel is ink."""
    image = label.grab().toImage()
    seen = Counter(image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())
                   if image.pixelColor(x, y).alpha() == 255)
    return seen.most_common(1)[0][0]


def test_the_ink_is_found_where_the_first_pixel_is_ink_too():
    """Windows' offscreen Qt draws every glyph as a box, so pixel (0, 0) can be ink: taking that
    pixel for the ground threw the ink away and read the transparent ground as `#000000`
    (CI, run 42677312857)."""
    _ = QApplication.instance() or QApplication([])
    image = QImage(12, 12, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    for x in range(0, 5):
        for y in range(0, 12):
            image.setPixelColor(x, y, QColor("#7d8999"))

    class Grabbed:
        @staticmethod
        def grab():
            return QPixmap.fromImage(image)

    assert _ink(Grabbed()) == "#7d8999"


def _dot_colour(section) -> str:
    image = section._dot.grab().toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2).name()


def test_the_severity_shows_on_screen(repo, host, monkeypatch):
    """The sheet, not the property: a re-polished label and the dot's colour, by pixels."""
    t = theme.get_theme("dark")
    widget, panel = host()
    widget.setStyleSheet(theme.build_qss(t, scale=4.0))
    section = widget._project_section
    section.set_sub("Not on GitHub")
    section.set_sub_level(None)
    QApplication.processEvents()
    assert _ink(section._sub_label) == QColor(t.faint).name()

    for level, colour in (("bad", t.warn), ("wait", t.yellow)):
        section.set_sub_level(level)
        QApplication.processEvents()
        assert _ink(section._sub_label) == QColor(colour).name(), level
    section.set_sub_level(None)
    QApplication.processEvents()
    assert _ink(section._sub_label) == QColor(t.faint).name(), "the quiet colour comes back too"

    for status, colour in (("bad", t.warn), ("wait", t.yellow), ("done", t.ok)):
        section.set_dot(status)
        QApplication.processEvents()
        assert _dot_colour(section) == QColor(colour).name(), status


def test_a_row_of_the_panel_takes_the_severity_on_screen(repo, host):
    project, _bare = repo
    _write(project, "state/v_032.json")
    t = theme.get_theme("dark")
    widget, panel = host()
    widget.setStyleSheet(theme.build_qss(t, scale=4.0))
    panel.show()
    assert _until(lambda: _settled(panel)), _rows(widget)
    QApplication.processEvents()

    key, value = _labels(widget, i18n.t("gitChanges"))
    assert _ink(key) == QColor(t.warn).name()
    assert _ink(value) == QColor(t.warn).name()
