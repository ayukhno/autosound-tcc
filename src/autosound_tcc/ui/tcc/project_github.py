"""The project's git in the left panel (#235): a live read, off the GUI thread, and the rows.

`_show_git_state` lived on the window and read `git_status` on a reload only, so the numbers stood
still while a session committed and pushed. Here the rows follow `.git` (HEAD and refs, its own
watcher, the window's project watcher never hears of it) and every ledger write (the window's
reload calls `show`); the read is coalesced, one at a time, and it repaints these rows and the
header alone: a project reload re-renders from disk and wipes the capture grid (#225).

The method's `status --json --fetch` is the read, so it goes to the remote: it never runs on the
GUI thread, and a window nobody sees (a test's, a window being closed) starts none.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from autosound_tcc.core import app_log, config, project_repo
from autosound_tcc.state import project_view
from autosound_tcc.ui.tcc import github_view, i18n, labels, process_watch, qt_shutdown, window_folder
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.sidebar_section import clear_layout

#: A burst of ledger writes and git's own several events are one read.
COALESCE_MS = 1500


class _Job(QThread):
    """One piece of the panel's work, off the GUI thread: a read or a step of a send."""

    done = Signal(object)

    def __init__(self, work: Callable[[], object]) -> None:
        super().__init__()
        self._work = work
        qt_shutdown.watch(self)

    def run(self) -> None:
        try:
            answer = self._work()
        except Exception as exc:  # noqa: BLE001 -- said in the panel, as a run that gave no answer
            app_log.logger().warning("project on GitHub: a job failed", exc_info=True)
            answer = project_repo.RepoResult(False, f"{type(exc).__name__}: {exc}")
        self.done.emit(answer)


class ProjectGithub(QObject):
    """The git rows and the header's dot and words for one window."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._box: Optional[QWidget] = None
        self._git: Optional[project_view.GitStatus] = None
        self._read: Optional[github_view.Read] = None
        self._read_of: Optional[Path] = None
        self._job: Optional[_Job] = None
        self._on_answer: Callable = lambda _answer: None
        self._again = False
        self._stopped = False
        self._mark: tuple = ()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(COALESCE_MS)
        self._timer.timeout.connect(self._start_read)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_git_changed)
        self._watcher.directoryChanged.connect(self._on_git_changed)

    # ── drawing ──────────────────────────────────────────────────────────────────────────────

    def show(self, reuse: bool = False) -> None:
        """What the window's project-params rebuild calls: the git rows, read from the folder.
        Unless `reuse`, a live read follows."""
        section = self._window._project_section
        self._window._backup_step = None
        chosen = config.chosen_project_dir()
        if chosen is None:
            self._read, self._read_of = None, None
            self._box = None
            self._hold(set(), set())
            section.set_sub("")
            section.set_dot(None)
            section.set_sub_tip("")
            return
        self._git = project_view.git_status(reuse=reuse)
        if self._read_of != chosen:
            self._read, self._read_of = None, None
        self._box = QWidget()
        box_layout = QVBoxLayout(self._box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(0)
        section.body_layout().addWidget(self._box)
        self._paint(chosen)
        self._arm(chosen)
        if not reuse:
            self._mark = github_view.refs_mark(chosen / ".git")
            self.request()

    def _paint(self, chosen: Path) -> None:
        section = self._window._project_section
        view = github_view.panel(self._git, self._read, chosen.name)
        section.set_sub(view.sub)
        section.set_dot(view.level)
        section.set_sub_level(None if view.level == "done" else view.level)
        section.set_sub_tip(view.tip)
        self._window._backup_step = view.step
        layout = self._box.layout()
        clear_layout(layout)
        for row in view.rows:
            layout.addWidget(self._row(row))
        if view.step is not None:
            slot = self._window._on_git_init if view.step == 0 else self._window._on_git_backup
            layout.addWidget(self._button(github_view.backup_label(view.step),
                                          "gitInitTip" if view.step == 0 else "gitBackupTip", slot))

    @staticmethod
    def _row(row: github_view.Row) -> QWidget:
        widget = labels.kv_row(row.key, row.value)
        key, value = widget.findChildren(labels.ElidedLabel)
        for label in (key, value):
            if row.tip:
                label.set_tip(row.tip)  # kept through the resizes that re-cut the label
            if row.level:
                label.setProperty("sev", row.level)
        if row.count:  # the number is short and asks for its width; the key takes the rest
            layout = widget.layout()
            layout.setStretch(0, 1)
            layout.setStretch(1, 0)
            value.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            value.set_min_width(min(value.sizeHint().width(), 56))
        return widget

    def _button(self, text: str, tip_key: str, slot) -> QWidget:
        """A one-click fix under the git rows: the method's own command, run on the click."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 2, 12, 6)
        button = QPushButton(text)
        button.setProperty("class", "link-btn")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        attach_tip(button, i18n.t(tip_key))
        button.clicked.connect(slot)
        layout.addWidget(button)
        layout.addStretch(1)
        return row

    # ── reading ──────────────────────────────────────────────────────────────────────────────

    def request(self) -> None:
        """Read again soon. Coalesced; if a read is running, one more after it."""
        if self._stopped or self._git is None or not (self._git.works and self._git.repo):
            return
        self._timer.start()

    def idle(self) -> bool:
        return self._job is None and not self._timer.isActive()

    def _start_read(self) -> None:
        if self._stopped:
            return
        if self._job is not None:
            self._again = True
            return
        if not self._window.isVisible() or not window_folder.may_reread(self._window, "the GitHub read"):
            return
        folder = config.chosen_project_dir()
        if folder is None:
            return
        root = config.state_root()

        def work():
            return folder, project_repo.read(folder), github_view.newest_version_time(root)

        self._run(work, self._read_landed)

    def _run(self, work: Callable[[], object], on_answer: Callable) -> None:
        job = _Job(work)
        self._job, self._on_answer = job, on_answer
        job.done.connect(self._job_done)
        job.start()

    def _job_done(self, answer: object) -> None:
        self._job = None
        if self._stopped:
            return
        self._on_answer(answer)
        if self._again and self._job is None:
            self._again = False
            self._timer.start()

    def _read_landed(self, result) -> None:
        folder, answer, newest = result
        chosen = config.chosen_project_dir()
        if chosen is None or Path(chosen) != Path(folder):
            return
        if isinstance(answer, project_repo.RepoResult):
            read = None if answer.too_old else github_view.unread(answer.said)
        else:
            read = github_view.from_status(answer, newest)
        self._read, self._read_of = read, Path(folder)
        self._mark = github_view.refs_mark(Path(folder) / ".git")  # what this read has already seen
        if self._box is not None:
            self._paint(Path(folder))
        self._arm(Path(folder))

    # ── the watch ────────────────────────────────────────────────────────────────────────────

    def _arm(self, folder: Path) -> None:
        files, folders = github_view.watch_paths(folder / ".git")
        self._hold(files, folders)

    def _hold(self, files: set[str], folders: set[str]) -> None:
        for held, wanted in ((self._watcher.files(), files), (self._watcher.directories(), folders)):
            if gone := set(held) - wanted:
                self._watcher.removePaths(sorted(gone))
            if new := wanted - set(held):
                process_watch.add(self._watcher, sorted(new))

    def _on_git_changed(self, *_args) -> None:
        chosen = config.chosen_project_dir()
        if chosen is None or self._stopped:
            return
        self._arm(chosen)  # an atomic write drops the path it replaced
        mark = github_view.refs_mark(chosen / ".git")
        if mark != self._mark:
            self._mark = mark
            self.request()

    def stop(self) -> None:
        """A closing window's: nothing starts after this, and what runs is handed over rather than
        dropped (`qt_shutdown`). Twice is fine."""
        self._stopped = True
        self._timer.stop()
        self._hold(set(), set())
        job, self._job = self._job, None
        if job is not None:
            qt_shutdown.stop_or_detach(job, qt_shutdown.QUIT_WAIT_MS, mute=(job.done,))
