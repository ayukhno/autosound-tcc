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

import shiboken6
from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from autosound_tcc.core import app_log, project_repo
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
        #: The send's state: None, or "asked", "sending".
        self._send: Optional[str] = None
        #: The next step of a send, kept while a read finishes: one job runs at a time.
        self._after_job: Optional[Callable[[], None]] = None
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
        chosen = self._folder()
        if chosen is None:
            self._read, self._read_of = None, None
            self._box = None
            self._hold(set(), set())
            section.set_sub("")
            section.set_dot(None)
            section.set_sub_tip("")
            return
        self._git = project_view.git_status(chosen, reuse=reuse)
        if self._read_of != chosen:
            self._read, self._read_of = None, None
        if not self._box_alive() or self._box.parentWidget() is None:  # the rebuild cleared it
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

    def _folder(self) -> Optional[Path]:
        """The folder this window shows, its question and its Send's: after a cancelled switch the
        one it was built on, with the process's already the next project's (`window_folder`)."""
        return window_folder.shown(self._window)

    def _box_alive(self) -> bool:
        return self._box is not None and shiboken6.isValid(self._box)

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
                                          i18n.t("gitInitTip" if view.step == 0 else "gitBackupTip"), slot))
        elif view.send is not None or self._send is not None:
            row = self._button(i18n.t("gitSendingBtn" if self._send == "sending" else "gitSendBtn"),
                               view.send or i18n.t("gitSendTip"), self._on_send)
            row.findChild(QPushButton).setEnabled(self._send is None and not view.send_off)
            layout.addWidget(row)

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

    def _button(self, text: str, tip: str, slot) -> QWidget:
        """A one-click fix under the git rows: the method's own command, run on the click."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 2, 12, 6)
        button = QPushButton(text)
        button.setProperty("class", "link-btn")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        attach_tip(button, tip)
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
        folder = self._folder()
        if folder is None:
            return
        folder, root = Path(folder), window_folder.state_root(self._window)

        def work():
            answer = project_repo.read(folder)
            git = project_view.git_status(folder)  # after the fetch: what the remote has now counts
            if isinstance(answer, project_repo.RepoResult):
                return git, (None if answer.too_old else github_view.unread(answer.said))
            return git, github_view.from_status(answer, github_view.newest_version_time(root))

        self._run(work, lambda result: self._read_landed(folder, result))

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
        if self._job is None and self._after_job is not None:
            then, self._after_job = self._after_job, None
            then()
        elif self._again and self._job is None:
            self._again = False
            self._timer.start()

    def _read_landed(self, folder: Path, result) -> None:
        chosen = self._folder()
        if chosen is None or Path(chosen) != folder:
            return
        if isinstance(result, project_repo.RepoResult):  # the job raised (`_Job.run`): said as unread
            read = github_view.unread(result.said)
        else:
            self._git, read = result
        self._read, self._read_of = read, folder
        self._mark = github_view.refs_mark(folder / ".git")  # what this read has already seen
        if self._box_alive():
            self._paint(folder)
        self._arm(folder)

    # ── sending ──────────────────────────────────────────────────────────────────────────────

    def _on_send(self, *_args) -> None:
        """«Відправити»: the method's `save`, on a worker, asked before each send. The question
        opens here, on the person's press, from the last read; what it promised is checked again
        on the worker, so a session's write in the meantime is said rather than sent unasked."""
        folder = self._folder()
        read = self._read
        if self._send is not None or self._stopped or folder is None or read is None:
            return
        if not window_folder.ours(self._window, "the Send button"):  # says so on a line that stays up
            return
        folder = Path(folder)
        promised = github_view.fingerprint(read, folder)  # the files as they are when the question opens
        box = QMessageBox(self._window)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(i18n.t("gitSendBtn"))
        box.setText(github_view.confirm_text(read))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        self._send = "asked"
        yes = box.exec() == QMessageBox.StandardButton.Yes
        if self._stopped or getattr(self._window, "_closing", False):
            self._send = None  # a close that is then cancelled leaves the button working
            return  # the window went while it was being asked: nothing goes
        if not yes:
            self._send = None
            self._repaint()
            return
        self._send = "queued"
        self._repaint()
        self._when_free(lambda: self._start_send(folder, promised))

    def _when_free(self, then: Callable[[], None]) -> None:
        if self._job is None:
            then()
        else:
            self._after_job = then

    def _start_send(self, folder: Path, promised: tuple) -> None:
        self._send = "sending"
        self._repaint()

        def work():
            status = project_repo.backup_status(folder)
            now = github_view.from_status(status) if isinstance(status, dict) else None
            if now is None or github_view.fingerprint(now, folder) != promised:
                return ("changed", None, status)
            # A close during the status: no push starts. `_stopped` too, for a job closed before it
            # was scheduled, which `stop_or_detach` does not ask.
            if self._stopped or QThread.currentThread().isInterruptionRequested():
                return ("stopped", None, None)
            return ("sent", project_repo.save(folder), None)

        self._run(work, lambda result: self._sent(folder, result))

    def _sent(self, folder: Path, result) -> None:
        """The outcome in words, the button back whatever happens, and a fresh read. A job that
        raised came back as its `RepoResult` (`_Job.run`)."""
        try:
            self._say(self._outcome(result))
        finally:
            self._send = None
            self._repaint()
            if Path(self._folder() or "") == folder:
                self._mark = github_view.refs_mark(folder / ".git")
                self.request()

    @staticmethod
    def _outcome(result) -> project_repo.RepoResult:
        if isinstance(result, project_repo.RepoResult):
            return result
        what, answer, status = result
        if what == "sent":
            return answer
        return status if isinstance(status, project_repo.RepoResult) else project_repo.RepoResult(False, i18n.t("gitSendChanged"))

    def _say(self, result: project_repo.RepoResult) -> None:
        strip = self._window._status_strip
        if result.too_old:
            strip.notify(i18n.t("gitTooOld"), level="warn")
        elif result.ok:
            strip.notify(i18n.t("gitSendDone").format(said=result.said))
        else:
            strip.notify(i18n.t("gitSendRefused").format(said=result.said or "—"), level="warn")

    def _repaint(self) -> None:
        chosen = self._folder()
        if chosen is not None and self._git is not None and self._box_alive():
            self._paint(Path(chosen))

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
        chosen = self._folder()
        if chosen is None or self._stopped:
            return
        self._arm(chosen)  # an atomic write drops the path it replaced
        mark = github_view.refs_mark(chosen / ".git")
        if mark != self._mark:
            self._mark = mark
            self.request()

    def may_close(self) -> bool:
        """Whether the window may go. A send still under way is asked about, the default keeping
        it (`_ask_abandon_save`'s rule); `_closing` is already up, so what Cancel's branch of the
        window's close puts back goes back here too."""
        if self._send not in ("queued", "sending") or self._stopped \
                or getattr(self._window, "_quitting", False):  # the window's own close: answered
            return True
        box = QMessageBox(self._window)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(i18n.t("gitSendingBtn"))
        box.setText(i18n.t("gitSendCloseAsk"))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() == QMessageBox.StandardButton.Yes:
            return True
        self._window._closing = False
        for name in ("_agent_refresh_timer", "_project_reload"):  # skipped while the question was up
            timer = getattr(self._window, name, None)
            if timer is not None:
                timer.start()
        return False

    def stop(self) -> None:
        """A closing window's: nothing starts after this, and what runs is handed over rather than
        dropped (`qt_shutdown`). No wait: neither job answers a request to stop soon, so waiting
        was only a freeze. Twice is fine."""
        self._stopped = True
        self._timer.stop()
        self._hold(set(), set())
        job, self._job = self._job, None
        if job is not None:
            qt_shutdown.stop_or_detach(job, 0, mute=(job.done,))


def may_close(window) -> bool:
    """The window's close asks its panel; out here so `main_window.py` does not grow."""
    panel = getattr(window, "_github", None)
    return panel is None or panel.may_close()


def stop_panel(window) -> None:
    """A window may be stopped half-built: no panel yet is nothing to stop."""
    panel = getattr(window, "_github", None)
    if panel is not None:
        panel.stop()
