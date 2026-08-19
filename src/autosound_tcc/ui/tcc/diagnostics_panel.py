"""The read-only diagnostics panel — "what TCC found on disk", one place, in every mode.

TCC-TZ.md §8 calls this out explicitly: the disk-state facts used to land as system bubbles in the
dialog, mixed into the conversation, which is wrong in `view` and `control` alike. `StatusStrip`
took the one-line half of that job; this dialog is the detailed half — the full machine-file
report from the skill's own checker (`rew_tool/contract.py`, run via `core/contract_check.py`),
rendered rather than re-derived. TCC does not decide here what "valid" means: the skill owns the
schemas and the checker, so every verdict on screen is quoted from it.

Read-only by construction — there is no control on this panel that writes anything. What it shows
is one snapshot; `refreshRequested` asks the window to run the check again (off the GUI thread),
and `set_report()` brings the answer back.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import (
    app_log,
    install_report,
    self_check,
    terminal_launcher,
    updates,
)
from autosound_tcc.core.contract_check import ContractReport
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.measurement_panel import TrafficLight
from autosound_tcc.ui.tcc.sidebar_section import clear_layout


def _dot_status(entry: dict) -> str:
    """The `tl-*` class for one file row.

    Missing is deliberately neutral (`wait`), not red: a project that hasn't been intake'd yet is
    normal, and the checker's own `ok` treats it the same way. Red is reserved for a file that
    exists and fails its schema.
    """
    if entry.get("valid") is False:
        return "bad"
    if not entry.get("exists"):
        return "wait"
    return "done"


def request_text(subject: str, issue: str) -> str:
    """The message that goes to the session about a problem TCC may not touch.

    Exact on purpose. "Please fix the flaw map" is a sentence a model answers with a sentence; the
    file, the checker's own words, and what "fixed" means are what let it answer with a write. And
    it goes into the COMPOSER, not out — the Arbiter reads it, edits it if it is wrong, and sends
    it. Nothing here asks a model to change a project behind them.
    """
    return i18n.t("diagAskText").format(subject=subject, issue=issue)


class _AskRow(QWidget):
    """One problem in the skill's own files, with an offer to forward it to the session.

    No Fix button: these files have an owner and it is not TCC (D-6). What TCC can do is carry the
    checker's finding to the thing that may write, and then — the half that matters — re-check and
    say whether it actually went away. The button never claims success; it records that it asked.
    """

    ask = Signal(str)

    def __init__(self, subject: str, issue: str, asked_at: Optional[float]) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 1, 12, 1)
        layout.setSpacing(8)
        text = _note(str(issue))
        layout.addWidget(text, stretch=1)
        if asked_at is not None:
            # Still here, and we already asked. Saying WHEN is the whole verification: a button
            # that reported success would be reporting on somebody else's work.
            stale = _note(i18n.t("diagAskedAgo").format(ago=_ago_minutes(asked_at)))
            stale.setProperty("class", "kv-warn")
            layout.addWidget(stale)
        button = QPushButton(i18n.t("diagAsk"))
        button.setProperty("class", "reason-btn")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self.ask.emit(request_text(subject, issue)))
        layout.addWidget(button)


def _ago_minutes(when: float) -> str:
    minutes = max(0, int((time.time() - when) // 60))
    return i18n.t("diagAgoNow") if minutes < 1 else i18n.t("diagAgoMin").format(n=minutes)


class _FileRow(QWidget):
    """One machine file: status dot, path, schema version, and its issues underneath."""

    def __init__(self, entry: dict) -> None:
        super().__init__()
        self.setProperty("class", "paramrow")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 5, 12, 5)
        outer.setSpacing(2)

        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(TrafficLight(_dot_status(entry)))
        name = QLabel(str(entry.get("file", "?")))
        name.setProperty("class", "mn")
        head.addWidget(name)
        head.addStretch(1)
        schema = entry.get("schema_version")
        version = QLabel(f"v{schema}" if schema is not None else "—")
        version.setProperty("class", "pv")
        head.addWidget(version)
        outer.addLayout(head)

        self.issues = list(entry.get("issues") or [])
        self.subject = str(entry.get("file", "?"))
        if not entry.get("exists") and not self.issues:
            outer.addWidget(_note(i18n.t("diagMissing")))


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("class", "phead-sub")
    label.setWordWrap(True)
    label.setContentsMargins(15, 0, 0, 0)
    return label


def _section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("class", "mcol-h")
    return label


class _CheckRow(QWidget):
    """One of TCC's own checks, with its Fix button when the repair is TCC's to make.

    The button is the whole point of the section. A diagnostic that describes a problem and leaves
    the remedy in a file the Arbiter has no reason to open is a diagnostic that gets read once —
    which is how three model aliases sat redirecting every reviewer call for five days.
    """

    fixed = Signal(str)

    def __init__(self, check: self_check.Check) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(2)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(TrafficLight(check.status))
        title = QLabel(check.title)
        title.setWordWrap(True)
        head.addWidget(title, stretch=1)
        if check.fixable:
            self._btn = QPushButton(check.fix_label)
            self._btn.setProperty("class", "reason-btn")
            self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._btn.clicked.connect(lambda: self._run(check))
            head.addWidget(self._btn)
        layout.addLayout(head)

        for line in (check.detail or "").splitlines():
            if line.strip():
                layout.addWidget(_note(line))

    def _run(self, check: self_check.Check) -> None:
        self._btn.setEnabled(False)
        try:
            message = check.fix() or ""
        except Exception as exc:  # noqa: BLE001 — a failed repair is a sentence, not a crash
            message = f"{type(exc).__name__}: {exc}"
        self.fixed.emit(message)


#: How often, and for how long, the panel looks to see whether the tool probes have finished.
_TOOLS_POLL_MS = 250
_TOOLS_TRIES = 60
#: Longer than the tools probe: this one waits on GitHub, not on local binaries.
_UPDATE_TRIES = 120


class _ToolsProbe:
    """Ask each command-line tool its version, on a plain thread, and hold the answer.

    ONLY that section: eight `--version` calls is a window that stops repainting, while the rest
    of the report must NOT leave the GUI thread — its metadata lookups are milliseconds here.

    A `threading.Thread` and not a `QThread`, and this one is measured rather than assumed: the
    same probes take **1.2 s on a plain thread and 10.7 s on a QThread** (2026-08-19). PySide6
    installs an import hook that reads the SOURCE of modules imported while it is active, and a
    Qt-owned thread pays it. Nothing here touches Qt, so it may also outlive the dialog that
    started it — which is the other half of why: a running QThread destroyed is `qFatal`.
    """

    def __init__(self) -> None:
        self.section = None
        self._thread = threading.Thread(target=self._run, name="tcc-tools", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.section = install_report.tools()
        except Exception as exc:  # noqa: BLE001 — a section that cannot be read still says so
            self.section = install_report.Section(
                "Command-line tools",
                [install_report.Item("probe", "failed", f"{type(exc).__name__}: {exc}")],
            )

    @property
    def running(self) -> bool:
        return self._thread.is_alive()


class _UpdateProbe:
    """Asks GitHub what the newest TCC and the newest method are, on a plain thread.

    Two `git ls-remote` calls, so this is network-bound and can take seconds on a tethered phone in
    a car park — which is exactly where this tab gets opened. Same shape and the same reason as
    `_ToolsProbe`: nothing of Qt's, so it may outlive the dialog that started it.
    """

    def __init__(self) -> None:
        self.result = None
        self._thread = threading.Thread(target=self._run, name="tcc-updates", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.result = updates.check_all()
        except Exception:  # noqa: BLE001 — an unanswered question is a row that says so
            self.result = None

    @property
    def running(self) -> bool:
        return self._thread.is_alive()


class DiagnosticsDialog(QDialog):
    """Non-modal so it can stay open beside the tune it describes."""

    refreshRequested = Signal()
    #: Text for the dialog composer — a problem in the skill's files, forwarded to the session.
    askRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._report: Optional[ContractReport] = None
        self._checks: list = []
        #: `subject::issue` -> when it was last forwarded. In memory on purpose: the durable
        #: record of the ask is the message in the transcript, and this only decides whether the
        #: row says "still here, asked N minutes ago".
        self._asked: dict[str, float] = {}
        self.setModal(False)
        self.setMinimumSize(560, 420)
        self.setProperty("class", "fb-card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)

        self._title = QLabel(i18n.t("diagTitle"))
        self._title.setProperty("class", "phead-title")
        outer.addWidget(self._title)

        self._verdict = QLabel("")
        self._verdict.setWordWrap(True)
        outer.addWidget(self._verdict)

        self._path = QLabel("")
        self._path.setProperty("class", "mn")
        self._path.setWordWrap(True)
        self._path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self._path)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(2)
        scroll.setWidget(body)

        # TWO tabs: what is wrong with this PROJECT, and what is installed on this MACHINE. The
        # second one is here rather than in a window of its own because this is the window a
        # person already opens when something is off, and the first question every report from a
        # machine nobody can see has needed is "which versions am I looking at" (user,
        # 2026-08-19).
        self._tabs = QTabWidget()
        self._tabs.addTab(scroll, i18n.t("diagTabProject"))
        self._tabs.addTab(self._build_install_tab(), i18n.t("diagTabInstall"))
        self._tabs.addTab(self._build_log_tab(), i18n.t("diagTabLog"))
        self._tabs.currentChanged.connect(self._on_tab)
        outer.addWidget(self._tabs, stretch=1)

        self._checked = QLabel("")
        self._checked.setProperty("class", "phead-sub")
        outer.addWidget(self._checked)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._refresh_btn = QPushButton(i18n.t("diagRefresh"))
        self._refresh_btn.setProperty("class", "reason-btn")
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.clicked.connect(self._on_refresh)
        buttons.addWidget(self._refresh_btn)
        self._close_btn = QPushButton(i18n.t("diagClose"))
        self._close_btn.setProperty("class", "reason-btn")
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self.close)
        buttons.addWidget(self._close_btn)
        outer.addLayout(buttons)

        i18n.on_language_changed(self._retranslate)
        self._render()

    # ---- what is installed ---------------------------------------------------

    def _build_install_tab(self) -> QWidget:
        """One selectable, copyable block. Not a table: it is written to be PASTED — into a
        message, an issue, a screenshot — and a monospace block survives all three."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        blurb = QLabel(i18n.t("diagInstallBlurb"))
        blurb.setWordWrap(True)
        blurb.setProperty("class", "phead-sub")
        layout.addWidget(blurb)
        layout.addWidget(self._build_update_row())
        self._install_text = QPlainTextEdit()
        self._install_text.setReadOnly(True)
        self._install_text.setPlainText(i18n.t("diagInstallReading"))
        # Monospace, because the report aligns itself with spaces.
        self._install_text.setProperty("class", "mn")
        self._install_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._install_text, stretch=1)
        row = QHBoxLayout()
        row.addStretch(1)
        self._copy_btn = QPushButton(i18n.t("diagInstallCopy"))
        self._copy_btn.setProperty("class", "reason-btn")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.clicked.connect(self._copy_install)
        row.addWidget(self._copy_btn)
        layout.addLayout(row)
        self._install_worker: Optional[_ToolsProbe] = None
        self._install_read = False
        # The timer belongs to this dialog, so it stops when the dialog goes; the thread does not,
        # because it holds nothing of Qt's.
        self._install_tries = 0
        self._install_timer = QTimer(self)
        self._install_timer.setInterval(_TOOLS_POLL_MS)
        self._install_timer.timeout.connect(self._poll_tools)
        return page

    def _build_update_row(self) -> QWidget:
        """Two lines, two buttons: is there a newer one, and the thing that installs it.

        Above the report rather than below it, because it is the one part of this tab a person can
        ACT on — the block underneath is for pasting into a message. The buttons are disabled until
        the check comes back, and stay disabled when there is nothing to do: a live "Update" button
        on an up-to-date install is a question mark, not an offer.
        """
        box = QWidget()
        grid = QVBoxLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self._update_rows = {}
        for name, key in (("tcc", "updTcc"), ("skill", "updSkill")):
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(i18n.t("updChecking"))
            label.setWordWrap(True)
            label.setProperty("class", "mn")
            row.addWidget(label, stretch=1)
            button = QPushButton(i18n.t(key))
            button.setProperty("class", "reason-btn")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setEnabled(False)
            button.clicked.connect(
                self._update_tcc if name == "tcc" else self._update_skill)
            row.addWidget(button)
            grid.addLayout(row)
            self._update_rows[name] = (label, button)
        self._update_probe: Optional[_UpdateProbe] = None
        self._update_tries = 0
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(_TOOLS_POLL_MS)
        self._update_timer.timeout.connect(self._poll_updates)
        return box

    def _poll_updates(self) -> None:
        self._update_tries += 1
        probe = self._update_probe
        if probe is None or (probe.result is None and self._update_tries < _UPDATE_TRIES
                             and probe.running):
            return
        self._update_timer.stop()
        if probe is None or probe.result is None:
            for name, (label, _btn) in self._update_rows.items():
                label.setText(i18n.t("updUnknown"))
            return
        for status in probe.result:
            self._show_update(status)

    def _show_update(self, status) -> None:
        """One row's worth of the answer, in the words that tell a person what to do next."""
        label, button = self._update_rows[status.name]
        title = i18n.t("updTccName") if status.name == "tcc" else i18n.t("updSkillName")
        here = status.installed or "?"
        # Assigned every time, not only switched on: this row is re-rendered after an update and
        # on every re-check, and a button still live over "up to date" is an offer to do nothing.
        button.setEnabled(status.newer and status.updatable)
        if status.newer:
            label.setText(i18n.t("updAvailable").format(
                what=title, here=here, there=status.latest))
        elif status.note:
            label.setText(f"{title} {here} — {status.note}")
        elif not status.latest:
            label.setText(i18n.t("updUnknown"))
        else:
            label.setText(i18n.t("updCurrent").format(what=title, here=here))

    def _update_skill(self) -> None:
        """Done here, in the app: it is another folder's git checkout and takes about a second."""
        label, button = self._update_rows["skill"]
        button.setEnabled(False)
        label.setText(i18n.t("updWorking"))
        # Blocking on purpose, and it is allowed to be: a shallow fetch of one tag is a second at
        # most, and the alternative -- a thread for a call this short -- is a window that can be
        # clicked twice before the first one lands.
        ok, what = updates.apply_skill()
        if ok:
            label.setText(i18n.t("updSkillDone").format(version=what.lstrip("v")))
            self._install_read = False
            self.refresh_install()
        else:
            label.setText(i18n.t("updFailed").format(why=what))
            button.setEnabled(True)

    def _update_tcc(self) -> None:
        """Handed to a terminal, with the reason said out loud.

        TCC cannot replace its own files while it is running -- on Windows it cannot at all, and
        the failure would land halfway through -- so the command goes to a window the person can
        watch, and the app says the one thing that matters: close TCC first.
        """
        label, _button = self._update_rows["tcc"]
        try:
            terminal_launcher.run_line(updates.TCC_INSTALL_COMMAND)
        except Exception as exc:  # noqa: BLE001 — no terminal we know how to drive
            label.setText(i18n.t("updFailed").format(why=f"{type(exc).__name__}: {exc}"))
            return
        label.setText(i18n.t("updTccHanded"))

    def _poll_tools(self) -> None:
        """Put the tools section in as soon as it lands, and stop asking either way."""
        self._install_tries += 1
        probe = self._install_worker
        if probe is None or (probe.section is None and self._install_tries < _TOOLS_TRIES
                             and probe.running):
            return
        self._install_timer.stop()
        self._render_install(probe.section if probe is not None else None)

    def _build_log_tab(self) -> QWidget:
        """The end of the log file, and one button to take it away with.

        The third thing every report has needed after the versions and the reason: the log itself.
        It lived at a path in a message nobody could click, on a machine nobody debugging it could
        see (user, 2026-08-19). Read fresh every time the tab is opened — a log looked at once and
        never re-read is a log that lies about the run you are in.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        self._log_where = QLabel("")
        self._log_where.setProperty("class", "mn")
        self._log_where.setWordWrap(True)
        self._log_where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._log_where)
        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setProperty("class", "mn")
        self._log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._log_text, stretch=1)
        row = QHBoxLayout()
        row.addStretch(1)
        self._log_copy_btn = QPushButton(i18n.t("diagInstallCopy"))
        self._log_copy_btn.setProperty("class", "reason-btn")
        self._log_copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_copy_btn.clicked.connect(self._copy_log)
        row.addWidget(self._log_copy_btn)
        layout.addLayout(row)
        return page

    def refresh_log(self) -> None:
        """Re-read the tail, and say where it came from — the path is what a report needs next."""
        path = app_log.log_path()
        self._log_where.setText(str(path) if path else i18n.t("diagLogNone"))
        self._log_text.setPlainText(app_log.tail())
        # The end is where the answer is.
        bar = self._log_text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _copy_log(self) -> None:
        """The tail AND the path: a log with no filename is a log nobody can ask about again."""
        path = app_log.log_path()
        head = f"{path}\n\n" if path else ""
        QGuiApplication.clipboard().setText(head + self._log_text.toPlainText())
        self._log_copy_btn.setText(i18n.t("diagInstallCopied"))

    def _on_tab(self, index: int) -> None:
        """Read the report the first time the tab is opened, and never on the way to the other one.

        Eight subprocesses is not something to pay for opening a dialog about a contract check.
        """
        if index == 1 and not self._install_read:
            self.refresh_install()
        elif index == 2:
            # Every time, not once: the log grows while this window is open, and that is exactly
            # when something is going wrong.
            self.refresh_log()

    def refresh_install(self) -> None:
        """Everything that reads a file, now; everything that runs a program, on a thread.

        The block is on screen the moment the tab opens — versions, paths, where the skill is —
        with the tools section filling in a second later, rather than an empty box and a wait.
        """
        if self._install_worker is not None and self._install_worker.running:
            return
        self._install_read = True
        self._render_install(None)
        self._install_worker = _ToolsProbe()
        self._install_tries = 0
        self._install_timer.start()
        if self._update_probe is None or not self._update_probe.running:
            self._update_probe = _UpdateProbe()
            self._update_tries = 0
            self._update_timer.start()

    def _render_install(self, tools_section) -> None:
        try:
            sections = install_report.report(
                extra=self._install_extra(),
                with_tools=False,
                tools_section=tools_section,
            )
            text = install_report.as_text(sections)
        except Exception as exc:  # noqa: BLE001
            text = f"{type(exc).__name__}: {exc}"
        if tools_section is None:
            text += "\n" + i18n.t("diagInstallReading")
        self._install_text.setPlainText(text)

    def _install_extra(self) -> dict:
        """Facts only the running window knows. Set by the window through `set_install_extra`;
        empty is a fine answer, and the report says the rest either way."""
        return dict(getattr(self, "_install_extra_facts", {}) or {})

    def set_install_extra(self, facts: dict) -> None:
        self._install_extra_facts = dict(facts or {})

    def _copy_install(self) -> None:
        QGuiApplication.clipboard().setText(self._install_text.toPlainText())
        self._copy_btn.setText(i18n.t("diagInstallCopied"))

    # ---- state ---------------------------------------------------------------

    def set_report(self, report: Optional[ContractReport]) -> None:
        """`None` means a check is running — the panel says so rather than showing stale data as
        if it were current."""
        self._report = report
        self._refresh_btn.setEnabled(report is not None)
        self._render()

    def _ask_row(self, subject: str, issue: str) -> QWidget:
        row = _AskRow(subject, issue, self._asked.get(f"{subject}::{issue}"))
        row.ask.connect(lambda text, key=f"{subject}::{issue}": self._on_ask(key, text))
        return row

    def _on_ask(self, key: str, text: str) -> None:
        """Remember WHEN, then hand the text to the composer. The next re-check is what says
        whether it worked; this only ever claims to have asked."""
        self._asked[key] = time.time()
        self.askRequested.emit(text)
        self._render()

    def _on_fixed(self, message: str) -> None:
        """Re-render so the row that was fixed says so itself, rather than only a banner claiming
        it. A panel whose contents disagree with its own message is a panel nobody believes."""
        self._verdict.setText(i18n.t("diagFixDone").format(what=message))
        self._render()
        self._verdict.setText(i18n.t("diagFixDone").format(what=message))

    def _on_refresh(self) -> None:
        self.set_report(None)
        self.refreshRequested.emit()

    def _retranslate(self) -> None:
        self.setWindowTitle(i18n.t("diagTitle"))
        self._title.setText(i18n.t("diagTitle"))
        self._refresh_btn.setText(i18n.t("diagRefresh"))
        self._close_btn.setText(i18n.t("diagClose"))
        self._tabs.setTabText(0, i18n.t("diagTabProject"))
        self._tabs.setTabText(1, i18n.t("diagTabInstall"))
        self._tabs.setTabText(2, i18n.t("diagTabLog"))
        for name, key in (("tcc", "updTcc"), ("skill", "updSkill")):
            self._update_rows[name][1].setText(i18n.t(key))
        self._copy_btn.setText(i18n.t("diagInstallCopy"))
        self._log_copy_btn.setText(i18n.t("diagInstallCopy"))
        self._render()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Nothing to wait for: the probe is a plain daemon thread holding no Qt object, and the
        timer that reads it belongs to this dialog and dies with it."""
        timer = getattr(self, "_install_timer", None)
        if timer is not None:
            timer.stop()
        super().closeEvent(event)

    # ---- rendering -----------------------------------------------------------

    def _render(self) -> None:
        self.setWindowTitle(i18n.t("diagTitle"))
        clear_layout(self._body_layout)
        report = self._report

        if report is None:
            self._verdict.setText(i18n.t("diagChecking"))
            self._path.setText("")
            self._checked.setText("")
            return

        self._path.setText(report.project_dir)
        self._checked.setText(
            i18n.t("diagCheckedAt").format(at=report.checked_at, ms=round(report.duration_s * 1000))
        )

        if not report.available:
            self._verdict.setText(f"{i18n.t('diagUnavailable')} — {report.error}")
            return

        # The headline counts BOTH halves. It read `report.ok` alone, so the panel could say
        # "OK — nothing to fix" directly above a red row of its own making, which is the exact
        # shape of thing this section was added to stop.
        checks = self_check.run()
        self._checks = checks
        own = [c for c in checks if c.status != self_check.OK]
        issues = report.issues()
        total = len(issues) + len(own)
        self._verdict.setText(
            i18n.t("diagOk") if report.ok and not own else i18n.t("diagIssues").format(n=total)
        )

        self._body_layout.addWidget(_section_title(i18n.t("diagFiles")))
        for entry in report.files:
            row = _FileRow(entry)
            self._body_layout.addWidget(row)
            for issue in row.issues:
                self._body_layout.addWidget(self._ask_row(row.subject, issue))

        cross = report.cross_checks or {}
        cross_notes = list(cross.get("glossary_vs_ledgers") or []) + list(
            cross.get("tiers_vs_profile") or []
        )
        self._body_layout.addWidget(_section_title(i18n.t("diagCross")))
        for note in cross_notes:
            self._body_layout.addWidget(self._ask_row(i18n.t("diagCross"), note))
        if not cross_notes:
            self._body_layout.addWidget(_note(i18n.t("diagNoIssues")))
        self._body_layout.addWidget(_note(_rew_line(report)))

        # TCC's own setup, after the project's. Separate section because it is a different
        # question with a different owner: these are things TCC did to itself, and the ones it may
        # undo carry a button (see `core/self_check.py` for where that line is drawn).
        self._body_layout.addWidget(_section_title(i18n.t("selfSection")))
        for check in checks:
            row = _CheckRow(check)
            row.fixed.connect(self._on_fixed)
            self._body_layout.addWidget(row)

        open_questions = report.open_questions()
        if open_questions:
            self._body_layout.addWidget(_section_title(i18n.t("diagOpenQ")))
            for question in open_questions:
                self._body_layout.addWidget(_note(question))

        self._body_layout.addStretch(1)


def _rew_line(report: ContractReport) -> str:
    """The REW leg of the cross-checks, in the checker's own terms.

    It is best-effort by design there (REW not running is reported, never an error), so this
    renders whichever of the three shapes came back: a note, a capture count, or nothing said.
    """
    rew = report.rew()
    if not rew:
        return "REW: —"
    if rew.get("note"):
        return f"REW: {rew['note']}"
    if "expected" in rew:
        found, expected = len(rew.get("found") or []), len(rew.get("expected") or [])
        line = (
            f"REW (phase {rew.get('phase')}, v{rew.get('version')}): {found}/{expected} captured"
        )
        return line if rew.get("complete") else f"{line} — missing {rew.get('missing')}"
    return "REW: —"
