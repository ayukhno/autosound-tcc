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
import urllib.parse
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import (
    app_log,
    config,
    form_report,
    install_report,
    self_check,
    session_export,
    terminal_launcher,
    updates,
)
from autosound_tcc.core.contract_check import ContractReport
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.feedback_dialog import FeedbackDialog
from autosound_tcc.ui.tcc.measurement_panel import TrafficLight
from autosound_tcc.ui.tcc.sidebar_section import clear_layout

# The core's self-check takes its words from the window's table, handed in rather than imported
# from there (HUB-051).
self_check.use_translator(i18n.t)


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


def _reason(key: str, detail: str = "") -> str:
    """One of `core.updates`' reason KEYS, in the reader's language.

    The translation lives here and not there on purpose: that module is Qt-free and language-free,
    and a sentence composed inside it came out in English in a Ukrainian window. An unknown key
    falls through as itself — a stray identifier on screen is ugly, and silence is worse.
    """
    text = i18n.t(f"updWhy_{key}")
    if text == f"updWhy_{key}":  # no translation for this one
        text = key
    return f"{text}: {detail}" if detail else text


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


#: Where a beta report goes. The repository's own form, not a blank issue: a form has fields, and
#: fields are what let a pile of reports be read by something other than a person one at a time.
ISSUES_URL = "https://github.com/ayukhno/autosound-tcc/issues/new"


def issue_url(what: str, install: str) -> str:
    """The beta-report form with the person's words and the installation block in its own fields.

    Four hundred lines of log do not fit in a URL, so the log is not sent this way: its tab has a
    Copy button, and the form has a field waiting for it.
    """
    fields = {"template": "beta-report.yml", "labels": "beta", "install": install}
    if what:
        fields["what"] = what
    return f"{ISSUES_URL}?{urllib.parse.urlencode(fields)}"

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

    def __init__(self, channel: str = "stable") -> None:
        self.result = None
        self._channel = channel
        self._thread = threading.Thread(target=self._run, name="tcc-updates", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.result = updates.check_all(self._channel)
        except Exception:  # noqa: BLE001 — an unanswered question is a row that says so
            self.result = None

    @property
    def running(self) -> bool:
        return self._thread.is_alive()


class _UpdateStep:
    """One step of an update on a plain thread, and its answer when it lands.

    For the method the step is the skill's own `upkeep.py` (hub #221): `status` can take a minute
    — it asks Homebrew and GitHub about the tools too — and `libs` longer, pip on a phone's
    network. For TCC it is the check of its own tag before the terminal gets it (tcc#102): a fetch
    and a `git verify-tag`. The press used to block the window for a second-long git fetch; this
    cannot. Same shape as `_UpdateProbe`: nothing of Qt's, so it may outlive the dialog that
    started it.
    """

    def __init__(self, work) -> None:
        self.result = None
        self.error = ""
        self._thread = threading.Thread(target=self._run, args=(work,),
                                        name="tcc-skill-update", daemon=True)
        self._thread.start()

    def _run(self, work) -> None:
        try:
            self.result = work()
        except Exception as exc:  # noqa: BLE001 — an answer on the row, not a dead thread
            self.error = f"{type(exc).__name__}: {exc}"

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def join(self, timeout: Optional[float] = None) -> None:
        self._thread.join(timeout)


#: How many changed files the keep-local question lists before "…and N more". A session's patch
#: is a file or two; a clone somebody worked in by hand can be hundreds, and a dialog taller than
#: the screen hides its own buttons.
_KEEP_LOCAL_SHOWN = 12


def _human_size(size: int) -> str:
    """A transcript's size in units a person compares at a glance. No locale, no decimals below a
    megabyte: the number is there to tell a long conversation from a short one, not to be added up.
    """
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{round(size / 1024)} KB"
    return f"{size} B"


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
        self._tabs.addTab(self._build_sessions_tab(), i18n.t("diagTabSessions"))
        self._tabs.currentChanged.connect(self._on_tab)
        outer.addWidget(self._tabs, stretch=1)

        self._checked = QLabel("")
        self._checked.setProperty("class", "phead-sub")
        outer.addWidget(self._checked)

        buttons = QHBoxLayout()
        # Left of the stretch, away from this dialog's own two actions: it is not "another button
        # about this window", it is the way out of the window into a report. And it lives HERE
        # rather than on the Installation tab so it is on screen whichever tab is open — a button
        # that has to be found is a report that does not get written (user, 2026-08-19).
        self._report_btn = QPushButton(i18n.t("diagReport"))
        self._report_btn.setProperty("class", "reason-btn")
        self._report_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._report_btn.clicked.connect(self._open_issue)
        buttons.addWidget(self._report_btn)
        # For a bug in a WINDOW the screenshot is the evidence, and the button opens the one place
        # it can be attached — a browser form, where dragging an image in works. Nothing said so:
        # not here, not in the form (SKL-010, after four reports arrived with the picture missing
        # and the reporter blocked on `gh issue create` having no attachment flag). This is the
        # last moment the person still has the picture in front of them.
        self._report_hint = QLabel(i18n.t("diagReportShot"))
        self._report_hint.setProperty("class", "phead-sub")
        buttons.addWidget(self._report_hint)
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
        # Under the rows it changes (the Arbiter, 2026-09-14). The method is not on it yet: it keeps
        # following released tags on both channels, and the label says TCC for that reason.
        self._beta_box = QCheckBox(i18n.t("updBetaChannel"))
        self._beta_box.setChecked(updates.current_channel() == updates.BETA)
        self._beta_box.toggled.connect(self._on_beta_toggled)
        grid.addWidget(self._beta_box)
        self._update_probe: Optional[_UpdateProbe] = None
        self._update_tries = 0
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(_TOOLS_POLL_MS)
        self._update_timer.timeout.connect(self._poll_updates)
        # «Update the method» runs in steps off the GUI thread (`_UpdateStep`), with a question in
        # the middle when the clone carries local changes. No cap on the tries, unlike the probe:
        # each step is a subprocess with its own timeout, so it always ends.
        self._skill_job: Optional[_UpdateStep] = None
        self._skill_then = None
        self._skill_latest = ""
        self._skill_before = ""
        self._skill_timer = QTimer(self)
        self._skill_timer.setInterval(_TOOLS_POLL_MS)
        self._skill_timer.timeout.connect(self._poll_skill_job)
        # «Update TCC» checks TCC's own tag first, off the GUI thread too (tcc#102).
        self._tcc_job: Optional[_UpdateStep] = None
        self._tcc_timer = QTimer(self)
        self._tcc_timer.setInterval(_TOOLS_POLL_MS)
        self._tcc_timer.timeout.connect(self._poll_tcc_job)
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
        if (self._skill_job if status.name == "skill" else self._tcc_job) is not None:
            # A Re-check landing while that half is being updated: the steps' own receipt is on
            # its way, and "up to date" or a live button in its place would be both wrong and a
            # second press.
            return
        label, button = self._update_rows[status.name]
        title = i18n.t("updTccName") if status.name == "tcc" else i18n.t("updSkillName")
        here = status.installed or "?"
        if status.name == "skill":
            # The release the row offers is the one the button installs (F-024's rule for TCC).
            self._skill_latest = status.latest if status.newer else ""
        # Version numbers only, since F-036: the commit used to be appended to both of these, and
        # the brackets read as noise on the row the same way they did in the title bar. The sha is
        # still what the COMPARISON is made on (`updates.py`), and it is still printed whole in the
        # report below — it stopped being repeated in the line that only announces the number.
        # Assigned every time, not only switched on: this row is re-rendered after an update and
        # on every re-check, and a button still live over "up to date" is an offer to do nothing.
        button.setEnabled(status.newer and status.updatable)
        if status.newer and status.latest and status.latest != here:
            label.setText(i18n.t("updAvailable").format(
                what=title, here=here, there=status.latest))
        elif status.newer:
            # Same version number, different build. Normal for TCC, because it installs from a
            # branch and the number only moves when a release is cut — and, since HUB-001, a real
            # case for the method too: a release the manifest was not bumped on lands here rather
            # than reading as up to date. This row is the thinnest one on the panel since F-036:
            # both numbers are equal and the commits that differ are no longer printed, so it says
            # THAT there is a newer build and not which. The report below still names both.
            key = "updNewerBuildOn" if status.detail else "updNewerBuild"
            label.setText(i18n.t(key).format(what=title, here=here, date=status.detail))
        elif status.latest and status.latest == here:
            # Up to date FIRST, whatever else is true of this installation. A caveat about why the
            # button cannot act — a submodule, a working tree — is an answer to "why can I not
            # update", and that is not the question when there is nothing to update (spotted by
            # reading the row after a submodule bump, 2026-08-19).
            label.setText(i18n.t("updCurrent").format(what=title, here=here))
        elif status.reason:
            label.setText(f"{title} {here} — {_reason(status.reason, status.detail)}")
        elif not status.latest:
            label.setText(i18n.t("updUnknown"))
        else:
            label.setText(i18n.t("updCurrent").format(what=title, here=here))

    def _on_beta_toggled(self, checked: bool) -> None:
        """The channel is a setting, and the rows above must answer for the one just chosen.

        A probe still running asks for the OLD channel; it is let go rather than waited for — a
        daemon thread holding no Qt object — and a new one starts.
        """
        config.set_update_channel(updates.BETA if checked else updates.STABLE)
        self._update_probe = None
        self._start_update_check()

    def _update_skill(self) -> None:
        """The skill's own updater, in steps: what was changed here, a question if anything was,
        then keep it, move the clone, bring the libraries (hub #221, tcc#91).

        Off the GUI thread since the skill's `upkeep.py` does it (`_UpdateStep`): the first step —
        fetch the release, check its signature, `status` — can take a minute, and the row says so.
        """
        if self._skill_job is not None:
            return
        label, button = self._update_rows["skill"]
        self._skill_before = label.text()
        button.setEnabled(False)
        label.setText(i18n.t("updSkillLooking"))
        # Both steps run the `upkeep.py` of the release the row offers — the clone's own may
        # predate the script (`updates._upkeep_from_tag`).
        tag = f"v{self._skill_latest}" if self._skill_latest else ""
        self._run_skill_step(lambda: updates.local_changes(tag), self._after_local_changes)

    def _run_skill_step(self, work, then) -> None:
        self._skill_job = _UpdateStep(work)
        self._skill_then = then
        self._skill_timer.start()

    def _poll_skill_job(self) -> None:
        job = self._skill_job
        if job is None or job.running:
            return
        self._skill_timer.stop()
        then, self._skill_job, self._skill_then = self._skill_then, None, None
        if job.error or job.result is None:
            label, button = self._update_rows["skill"]
            label.setText(i18n.t("updFailed").format(why=job.error or "?"))
            button.setEnabled(True)
            return
        then(job.result)

    def _after_local_changes(self, found) -> None:
        """Clean: straight on. Changed: the files named, and the one question — send them too?"""
        label, button = self._update_rows["skill"]
        if not found.ok:
            label.setText(i18n.t("updFailed").format(why=_reason(found.reason, found.detail)))
            button.setEnabled(True)
            return
        send = False
        if found.changed:
            answer = self._ask_keep_local(found.changed)
            if answer is None:
                # Cancelled: nothing kept, nothing reset, the row back to its offer.
                label.setText(self._skill_before)
                button.setEnabled(True)
                return
            send = answer
        label.setText(i18n.t("updWorking"))
        tag = f"v{self._skill_latest}" if self._skill_latest else ""
        keep = bool(found.changed)
        self._run_skill_step(lambda: updates.apply_skill(tag, keep_local=keep, send=send),
                             self._after_skill_update)

    def _keep_local_box(self, changed) -> tuple[QMessageBox, QPushButton, QPushButton, QPushButton]:
        """The question, built and not shown: the files named, because a yes takes them off the
        machine (tcc#91 — «можливість це виправити і відправити issue для інфо скілу»).

        The default is to update WITHOUT sending: Enter is not a yes to something that leaves the
        machine. Escape cancels, and cancelling touches nothing.
        """
        shown = list(changed[:_KEEP_LOCAL_SHOWN])
        files = "\n".join(f"• {name}" for name in shown)
        if len(changed) > len(shown):
            files += "\n" + i18n.t("updKeepMore").format(count=len(changed) - len(shown))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(i18n.t("updKeepTitle"))
        box.setText(i18n.t("updKeepText").format(files=files))
        send = box.addButton(i18n.t("updKeepSend"), QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton(i18n.t("updKeepOnly"), QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton(i18n.t("updKeepCancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        box.setEscapeButton(cancel)
        return box, send, keep, cancel

    def _ask_keep_local(self, changed) -> Optional[bool]:
        """True: keep, send, update. False: keep and update. None: do nothing."""
        box, send, keep, _cancel = self._keep_local_box(changed)
        box.exec()
        clicked = box.clickedButton()
        if clicked is send:
            return True
        if clicked is keep:
            return False
        return None

    def _after_skill_update(self, done) -> None:
        """The receipt: where the skill landed, and each thing that happened on the way — the
        kept patch and the send's answer above all, since a reset clone no longer shows them."""
        label, button = self._update_rows["skill"]
        if done.ok:
            lines = [i18n.t("updSkillDone").format(version=done.version.lstrip("v"))]
            if done.signature:
                lines.append(i18n.t("updSkillSigned").format(line=done.signature))
        else:
            lines = [i18n.t("updFailed").format(why=_reason(done.reason, done.detail))]
        if done.patch:
            lines.append(i18n.t("updKeepSaved").format(path=done.patch))
        if done.sent:
            lines.append(i18n.t("updKeepSent").format(url=done.sent.get("url", ""))
                         if done.sent.get("sent")
                         else i18n.t("updKeepNotSent").format(why=done.sent.get("why", "")))
        if done.libs_ok is True:
            lines.append(i18n.t("updLibsDone").format(what=done.libs) if done.libs
                         else i18n.t("updLibsCurrent"))
        elif done.libs_ok is False:
            lines.append(i18n.t("updLibsFailed").format(why=done.libs))
        label.setText("\n".join(lines))
        if done.ok:
            # The report underneath must show the new version — but the row keeps what it just
            # said until the next Re-check, because that sentence is the receipt for the press.
            self._install_read = False
            self.refresh_install(check_updates=False)
        else:
            button.setEnabled(True)

    def _update_tcc(self) -> None:
        """Handed to a terminal, with the reason said out loud — once TCC's own tag checks out.

        TCC cannot replace its own files while it is running -- on Windows it cannot at all, and
        the failure would land halfway through -- so the update goes to a window the person can
        watch, and the app says the one thing that matters: close TCC first. The window runs a
        script file TCC writes, in the reader's language, and shows only those lines and uv's
        answer (hub #221 ask 3).

        Before any of that, the tag is checked (tcc#102): fetched and verified off the GUI thread,
        and a tag that does not verify opens no window at all — the row says why instead.
        """
        if self._tcc_job is not None:
            return
        label, button = self._update_rows["tcc"]
        button.setEnabled(False)
        label.setText(i18n.t("updTccChecking"))
        # Read here, on the GUI thread: the channel is a QSettings value, the words the reader's.
        # The tag is the newest on that channel, not whatever `main` holds by then (F-024).
        channel = updates.current_channel()
        words = {"wait": i18n.t("updTermWait"), "updating": i18n.t("updTermUpdating"),
                 "done": i18n.t("updTermDone"), "failed": i18n.t("updTermFailed"),
                 "moved": i18n.t("updTermMoved")}
        self._tcc_job = _UpdateStep(lambda: updates.prepare_tcc_update(channel, words=words))
        self._tcc_timer.start()

    def _poll_tcc_job(self) -> None:
        job = self._tcc_job
        if job is None or job.running:
            return
        self._tcc_timer.stop()
        self._tcc_job = None
        label, button = self._update_rows["tcc"]
        ready = job.result
        if job.error or ready is None:
            label.setText(i18n.t("updFailed").format(why=job.error or "?"))
            button.setEnabled(True)
            return
        if ready.script is None:
            # Nothing was written, so nothing runs: the reason where the window would have been.
            label.setText(i18n.t("updFailed").format(why=_reason(ready.reason, ready.detail)))
            button.setEnabled(True)
            return
        try:
            terminal_launcher.run_script(ready.script)
        except Exception as exc:  # noqa: BLE001 — no terminal we know how to drive
            label.setText(i18n.t("updFailed").format(why=f"{type(exc).__name__}: {exc}"))
            button.setEnabled(True)
            return
        label.setText("\n".join([i18n.t("updTccHanded"),
                                  i18n.t("updSkillSigned").format(line=ready.signature)]))

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
        # The session export used to live here as a spinner and a button — "the newest five" and a
        # save dialog. It is its own tab now (the user, 2026-09-19): a choice of WHICH sessions
        # cannot be made by a number, and the log tab is for the log.
        row.addStretch(1)
        self._log_copy_btn = QPushButton(i18n.t("diagInstallCopy"))
        self._log_copy_btn.setProperty("class", "reason-btn")
        self._log_copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_copy_btn.clicked.connect(self._copy_log)
        row.addWidget(self._log_copy_btn)
        layout.addLayout(row)
        return page

    def _build_sessions_tab(self) -> QWidget:
        """Which conversations with the AI to take off this machine, and where to put them.

        What it does NOT do is show them: the transcripts are long, nobody reads them in a dialog,
        and the two questions a person actually has are which sessions and which file (the user,
        2026-09-19). The list says when each ran, how big it is and which phase it belonged to —
        enough to tick the right ones without opening any.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self._sessions_head = QLabel("")
        self._sessions_head.setProperty("class", "mn")
        self._sessions_head.setWordWrap(True)
        layout.addWidget(self._sessions_head)

        self._sessions_list = QListWidget()
        self._sessions_list.itemChanged.connect(self._on_sessions_ticked)
        layout.addWidget(self._sessions_list, stretch=1)

        picks = QHBoxLayout()
        self._sessions_all_btn = QPushButton(i18n.t("diagSessionsTickAll"))
        self._sessions_none_btn = QPushButton(i18n.t("diagSessionsTickNone"))
        for button, ticked in ((self._sessions_all_btn, True), (self._sessions_none_btn, False)):
            button.setProperty("class", "reason-btn")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _c=False, on=ticked: self._tick_all_sessions(on))
            picks.addWidget(button)
        picks.addStretch(1)
        # Each separately by default, because that is what the archive is for: one file per
        # conversation reads and gets sent on its own (the user, 2026-09-19).
        self._sessions_each = QRadioButton(i18n.t("diagSessionsEachFile"))
        self._sessions_each.setChecked(True)
        self._sessions_one = QRadioButton(i18n.t("diagSessionsOneFile"))
        for radio in (self._sessions_each, self._sessions_one):
            radio.setCursor(Qt.CursorShape.PointingHandCursor)
            radio.toggled.connect(self._sync_sessions_name)
            picks.addWidget(radio)
        layout.addLayout(picks)

        name_row = QHBoxLayout()
        self._sessions_name_label = QLabel(i18n.t("diagSessionsNameLabel"))
        self._sessions_name_label.setProperty("class", "phead-sub")
        name_row.addWidget(self._sessions_name_label)
        self._sessions_name = QLineEdit()
        # Typing here means the name is the person's: it stops being rewritten under them when the
        # ticks change, which is the difference between a suggestion and a fight.
        self._sessions_name.textEdited.connect(self._on_sessions_name_typed)
        name_row.addWidget(self._sessions_name, stretch=1)
        layout.addLayout(name_row)

        where_row = QHBoxLayout()
        self._sessions_folder_label = QLabel(i18n.t("diagSessionsFolder"))
        self._sessions_folder_label.setProperty("class", "phead-sub")
        where_row.addWidget(self._sessions_folder_label)
        self._sessions_folder = QLabel("")
        self._sessions_folder.setProperty("class", "mn")
        self._sessions_folder.setWordWrap(True)
        self._sessions_folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        where_row.addWidget(self._sessions_folder, stretch=1)
        self._sessions_browse_btn = QPushButton(i18n.t("diagSessionsBrowse"))
        self._sessions_browse_btn.setProperty("class", "reason-btn")
        self._sessions_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sessions_browse_btn.clicked.connect(self._pick_sessions_folder)
        where_row.addWidget(self._sessions_browse_btn)
        layout.addLayout(where_row)

        save_row = QHBoxLayout()
        self._sessions_btn = QPushButton(i18n.t("diagSessionsSaveN").format(n=0))
        self._sessions_btn.setProperty("class", "composer-send")
        self._sessions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sessions_btn.clicked.connect(self._save_sessions)
        save_row.addWidget(self._sessions_btn)
        self._sessions_status = QLabel("")
        self._sessions_status.setProperty("class", "phead-sub")
        self._sessions_status.setWordWrap(True)
        self._sessions_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        save_row.addWidget(self._sessions_status, stretch=1)
        layout.addLayout(save_row)
        return page

    # ---- the sessions tab ----------------------------------------------------

    def refresh_sessions(self) -> None:
        """Re-read the list every time the tab opens: a session that ran while this window was
        open is exactly the one somebody came here for."""
        project = config.project_dir()
        self._sessions_rows = session_export.sessions(project) if project else []
        self._sessions_head.setText(
            i18n.t("diagSessionsPick").format(project=Path(project).name if project else "—")
            if self._sessions_rows else i18n.t("diagSessionsNone"))
        self._sessions_list.blockSignals(True)
        self._sessions_list.clear()
        for row in self._sessions_rows:
            item = QListWidgetItem(i18n.t("diagSessionsRow").format(
                when=f"{row.when:%d.%m %H:%M}",
                size=_human_size(row.size),
                phase=(i18n.t("diagSessionsPhase").format(phase=row.phase) if row.phase
                       else i18n.t("diagSessionsNoPhase"))))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # The newest is what somebody came for; everything older is a deliberate tick.
            item.setCheckState(Qt.CheckState.Checked if row is self._sessions_rows[0]
                               else Qt.CheckState.Unchecked)
            self._sessions_list.addItem(item)
        self._sessions_list.blockSignals(False)
        if not self._sessions_folder.text():
            default = (config.tcc_dir(project) / "exports") if project else Path.home()
            self._sessions_folder.setText(str(default))
        self._sync_sessions_name()

    def _ticked_sessions(self) -> list:
        return [row for index, row in enumerate(getattr(self, "_sessions_rows", []))
                if index < self._sessions_list.count()
                and self._sessions_list.item(index).checkState() == Qt.CheckState.Checked]

    def _tick_all_sessions(self, on: bool) -> None:
        self._sessions_list.blockSignals(True)
        for index in range(self._sessions_list.count()):
            self._sessions_list.item(index).setCheckState(
                Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self._sessions_list.blockSignals(False)
        self._sync_sessions_name()

    def _on_sessions_ticked(self, _item) -> None:
        self._sync_sessions_name()

    def _on_sessions_name_typed(self, _text: str) -> None:
        self._sessions_name_owned = True

    def _sync_sessions_name(self, *_args) -> None:
        """The suggested file name, and how many sessions the button says it will save."""
        chosen = self._ticked_sessions()
        self._sessions_btn.setText(i18n.t("diagSessionsSaveN").format(n=len(chosen)))
        self._sessions_btn.setEnabled(bool(chosen))
        if getattr(self, "_sessions_name_owned", False):
            return
        project = config.project_dir()
        stem = session_export.default_stem(project or "project", chosen)
        each = self._sessions_each.isChecked() and len(chosen) > 1
        self._sessions_name.setText(f"{stem}{'.zip' if each else '.md'}")

    def _pick_sessions_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, i18n.t("diagSessionsFolder"), self._sessions_folder.text())
        if chosen:
            self._sessions_folder.setText(chosen)

    def _save_sessions(self) -> None:
        """The ticked sessions into the named file — one document, or one file each in a zip."""
        chosen = self._ticked_sessions()
        if not chosen:
            return
        folder = Path(self._sessions_folder.text() or Path.home())
        target = folder / (self._sessions_name.text().strip() or "sessions.md")
        title = Path(config.project_dir() or "").name
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if self._sessions_each.isChecked():
                session_export.save_each_file(chosen, target, title=title)
            else:
                session_export.save_one_file(chosen, target, title=title)
        except OSError as exc:
            self._sessions_status.setText(f"{type(exc).__name__}: {exc}")
            return
        self._sessions_status.setText(
            i18n.t("diagSessionsSaved").format(n=len(chosen), path=target))

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
        elif index == 3:
            self.refresh_sessions()

    def refresh_install(self, check_updates: bool = True) -> None:
        """Everything that reads a file, now; everything that runs a program, on a thread.

        The block is on screen the moment the tab opens — versions, paths, where the skill is —
        with the tools section filling in a second later, rather than an empty box and a wait.

        `check_updates=False` re-reads the report WITHOUT asking GitHub again: used straight after
        an update, where the row has just said what it installed and replacing that with "checking
        for updates…" would take the answer away at the moment it was earned.
        """
        # Before the early return below, not after: the tools probe can be a slow one, and
        # "Re-check" doing nothing at all because a previous probe is still running is the kind of
        # dead button people press three times.
        if check_updates:
            self._start_update_check()
        if self._install_worker is not None and self._install_worker.running:
            return
        self._install_read = True
        self._render_install(None)
        self._install_worker = _ToolsProbe()
        self._install_tries = 0
        self._install_timer.start()

    def _start_update_check(self) -> None:
        """Ask GitHub again — unless it is already being asked."""
        if self._update_probe is not None and self._update_probe.running:
            return
        # Back to "checking", buttons off: a row still saying "a newer one is out" with a live
        # button while the question is being asked again is an offer we cannot honour yet.
        for name, (label, button) in self._update_rows.items():
            if name == "skill" and self._skill_job is not None:
                continue  # mid-update: its row says which step it is on
            label.setText(i18n.t("updChecking"))
            button.setEnabled(False)
        self._update_probe = _UpdateProbe(updates.current_channel())
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

    def _report_text(self) -> str:
        """The installation block for a report, whichever tab is open.

        The half of a bug report nobody can be asked to assemble by hand — versions, where each
        piece came from, which tools answer — is the half that decides whether the report can be
        answered at all (user, 2026-08-19: "дуже хочу обробляти їх напівавтоматично").
        """
        if self._install_read:
            return self._install_text.toPlainText()
        # The tab was never opened, so the box still holds "reading…". Compose the report now,
        # WITHOUT the tools section: that one starts eight processes, and the versions and paths —
        # which are what a report needs — are file reads that cost nothing.
        try:
            return install_report.as_text(install_report.report(
                extra=self._install_extra(), with_tools=False))
        except Exception as exc:  # noqa: BLE001 — a report that cannot be built still opens
            return f"{type(exc).__name__}: {exc}"

    def _open_issue(self) -> None:
        """Ask for the words and send them the way the person can: the form without an account,
        the beta-report issue with one (TODO F-042). The installation block goes either way — in
        the form's text under the words, or in the issue template's own field."""
        report = self._report_text()
        FeedbackDialog(
            ISSUES_URL, form_report.post_url(), self, kind="problem", attachment=report,
            github_link=lambda body: issue_url(body, report),
        ).exec()

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
        """Re-check means everything this window shows, not only the project.

        The update rows are the part a person presses this button to see move — after an update
        was installed, or after the network came back (user, 2026-08-19). The Installation tab is
        marked unread rather than read here: it starts eight subprocesses, and if the person is
        looking at another tab that cost belongs at the moment they open it, not now.
        """
        self.set_report(None)
        self.refreshRequested.emit()
        self._install_read = False
        if self._tabs.currentIndex() == 1:
            self.refresh_install()
        elif self._tabs.currentIndex() == 2:
            self.refresh_log()

    def _retranslate(self) -> None:
        self.setWindowTitle(i18n.t("diagTitle"))
        self._title.setText(i18n.t("diagTitle"))
        self._refresh_btn.setText(i18n.t("diagRefresh"))
        self._close_btn.setText(i18n.t("diagClose"))
        self._tabs.setTabText(0, i18n.t("diagTabProject"))
        self._tabs.setTabText(1, i18n.t("diagTabInstall"))
        self._tabs.setTabText(2, i18n.t("diagTabLog"))
        self._tabs.setTabText(3, i18n.t("diagTabSessions"))
        for name, key in (("tcc", "updTcc"), ("skill", "updSkill")):
            self._update_rows[name][1].setText(i18n.t(key))
        self._beta_box.setText(i18n.t("updBetaChannel"))
        self._copy_btn.setText(i18n.t("diagInstallCopy"))
        self._report_btn.setText(i18n.t("diagReport"))
        self._report_hint.setText(i18n.t("diagReportShot"))
        self._log_copy_btn.setText(i18n.t("diagInstallCopy"))
        self._sessions_all_btn.setText(i18n.t("diagSessionsTickAll"))
        self._sessions_none_btn.setText(i18n.t("diagSessionsTickNone"))
        self._sessions_each.setText(i18n.t("diagSessionsEachFile"))
        self._sessions_one.setText(i18n.t("diagSessionsOneFile"))
        self._sessions_name_label.setText(i18n.t("diagSessionsNameLabel"))
        self._sessions_folder_label.setText(i18n.t("diagSessionsFolder"))
        self._sessions_browse_btn.setText(i18n.t("diagSessionsBrowse"))
        self._sync_sessions_name()
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

        # Facts carried in from another project, and sources that are gone (hub #154 §3/§4).
        # Reported, never gated — so not counted in the headline — but named: a fragile driver's
        # inherited Fs holds the pre-sweep gate until the Arbiter confirms or measures it.
        if report.inherited or report.sources_gone:
            self._body_layout.addWidget(_section_title(i18n.t("diagInherited")))
            for row in report.inherited:
                self._body_layout.addWidget(_note(
                    f"{row.get('path')} = {row.get('value')!r} "
                    f"({i18n.t('diagInheritedFrom').format(path=row.get('from') or '?')})"))
            for path in report.sources_gone:
                self._body_layout.addWidget(_note(i18n.t("diagSourceGone").format(path=path)))

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
    renders whichever shape came back: a note, a capture count, or nothing said.

    Since skill v3.0.17 the count is the verdict of the OPEN CAPTURE ROUND rather than of the
    ledger's HEAD -- on a baseline it used to read `0/16 MISSING` forever, and a real hole would
    have been invisible inside that noise. Two keys came with it: `round`, said here because "16
    of 18" means nothing without knowing which round asked, and `duplicate_titles`, which is put
    FIRST because it is the one finding that makes the rest untrustworthy: TCC addresses a
    measurement by its title (`rew_bridge.find_id`), so two measurements sharing one title mean
    every answer about that title is a coin toss.
    """
    rew = report.rew()
    if not rew:
        return "REW: —"
    dups = rew.get("duplicate_titles") or {}
    prefix = ""
    if dups:
        named = ", ".join(f"{title} ×{n}" for title, n in sorted(dups.items()))
        prefix = f"REW: DUPLICATE TITLES — {named}. "
    if rew.get("note"):
        return f"{prefix}REW: {rew['note']}" if prefix else f"REW: {rew['note']}"
    if "expected" in rew:
        found, expected = len(rew.get("found") or []), len(rew.get("expected") or [])
        skipped = rew.get("skipped") or {}
        where = f"round {rew['round']}, " if rew.get("round") else ""
        line = (
            f"REW ({where}phase {rew.get('phase')}, {_round_label(rew.get('version'))}): "
            f"{found}/{expected} captured" + (f", {len(skipped)} skipped" if skipped else "")
        )
        if not rew.get("complete"):
            line = f"{line} — missing {rew.get('missing')}"
        # A skip is a decision with a reason, not work still owed (hub #154 §3) — said apart.
        # And a skip of a title the round never asked for is a THIRD fact (method TCC-022, hub
        # #190): before it, such a skip was reported nowhere at all, because `skipped` was
        # intersected with `missing`. Now it arrives, and reads exactly like a decided-against
        # capture unless it is marked. The words are the method's own, from the same branch of
        # `contract.py` — one vocabulary for one fact, not a second one invented here.
        unplanned = set(rew.get("skipped_unplanned") or [])
        for title, reason in skipped.items():
            mark = "  (never expected by this round)" if title in unplanned else ""
            line = f"{line}\n    skipped: {title} — {reason or 'no reason on record'}{mark}"
        return f"{prefix}{line}" if prefix else line
    return f"{prefix}REW: —" if prefix else "REW: —"


def _round_label(version) -> str:
    """How a round's key reads: `v_001` as recorded, a bare `_N` as `_17` — never `vv_001`.

    The method's own `contract.round_label` rule (v3.0.53, hub #154 §3), for a line this panel
    composes itself.
    """
    text = str(version if version is not None else "?")
    return text if text.startswith("v") or text == "?" else f"_{text}"
