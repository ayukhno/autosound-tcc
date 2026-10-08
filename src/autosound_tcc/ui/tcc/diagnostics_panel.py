"""The read-only diagnostics panel — "what TCC found on disk", one place, in every mode.

TCC-TZ.md §8 calls this out explicitly: the disk-state facts used to land as system bubbles in the
dialog, mixed into the conversation, which is wrong in `view` and `control` alike. `StatusStrip`
took the one-line half of that job; this dialog is the detailed half — the full machine-file
report from the skill's own checker (`rew_tool/contract.py`, run via `core/contract_check.py`),
rendered rather than re-derived. TCC does not decide here what "valid" means: the skill owns the
schemas and the checker, so every verdict on screen is quoted from it.

Read-only toward the method's files by construction — no control on this panel writes them. The
buttons in TCC's own section repair TCC's own setup, and the one that reaches into the project,
«re-link to TCC's copy» (#169), moves aside what sits where TCC links its own copy, deleting
nothing (`core/self_check.py` draws that line). What it shows is one snapshot; `refreshRequested`
asks the window to run the check again (off the GUI thread), and `set_report()` brings the answer
back.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
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
    method_binding,
    self_check,
    session_export,
    terminal_launcher,
    updates,
    vendor_loader,
)
from autosound_tcc.core.contract_check import ContractReport, stamp
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

    def __init__(self, subject: str, issue: str, asked_at: Optional[float],
                 shown: Optional[str] = None) -> None:
        """`shown` is the line the Arbiter reads when TCC words it in his language (#126); the
        session is still sent the checker's own `issue`, which is what lets it answer with a write."""
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 1, 12, 1)
        layout.setSpacing(8)
        text = _note(str(shown or issue))
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


#: The refusals pressing again cannot change: the press would only fetch and say the same, so its
#: button stays off until the next Re-check redraws the row. «ahead» (review of finding 144, M2),
#: and a method newer than this TCC, which only a newer TCC changes (#170). Read by every press
#: that can be refused; any other refusal can change on its own, and leaves the button on.
_STANDING_REFUSALS = frozenset({"ahead", "newer_contract"})


#: The sentences a tag's signature check writes — `updates._verify_tag` for TCC's own tags, the
#: skill's `upkeep.py verify_tag` for its own, word for word the same — by their parts (tcc#122:
#: «Підпис релізу: v3.0.7: signature good (ayukhno)» in a Ukrainian row). A failure never reaches
#: this line: it goes through `_reason`.
_SIGNATURE_FORMS = (
    (re.compile(r"(?P<tag>\S+): signature good \((?P<principal>[^()]+)\)"), "updSigGood"),
    (re.compile(r"(?P<tag>\S+) predates signed tags \(they start at (?P<first>\S+)\): "
                r"installed without a signature check"), "updSigPredates"),
    (re.compile(r"signature NOT checked: (?P<var>\S+)=1 is set \(a developer's switch\)"),
     "updSigSkipped"),
)


def _signature_said(line: str) -> str:
    """The signature line in the reader's language, the tag and the key's name as they are; a
    line in no form TCC knows — a newer method's, git's own — as it was printed."""
    for form, key in _SIGNATURE_FORMS:
        found = form.fullmatch(line.strip())
        if found:
            return i18n.t(key).format(**found.groupdict())
    return line


#: The tools a running AI session runs on (ruling 21, tcc#98): omp drives it and Claude Code is
#: the other harness. Their rows wait while a session runs; agy and gh do not.
_SESSION_TOOLS = ("omp", "claude")


#: The version an update in this run of TCC left each tool on, by name (finding 140, tcc#138). A
#: source that cannot tell its newest made a Re-check straight after the update read «unknown» with
#: «Update» live again — while the update itself had just installed the newest. Until the method's
#: v3.1.0 that was agy's and a native Claude Code's every time; since then `upkeep.py` names their
#: newest (hub #237), and only a source that does not answer (no network, a platform agy builds
#: nothing for) still cannot tell. What the update reported is the newest until the tool says
#: another version, or for `_LEARNED_FOR_S`. The process's and not a window's: the tools are the
#: machine's, and a new project opens a new window with a new diagnostics window in the same run.
#: Name -> (version, `time.time()` when the update reported it).
_UPDATED_TO: dict[str, tuple[str, float]] = {}
#: How long what an update learned stands in for a source that cannot tell (Ruling 3 on tcc#138):
#: the working session it was learned in, not the night after, when a newer one may be out — a
#: source that keeps not answering names none, so nothing else would end it. The wall clock, not
#: `time.monotonic()`, which on macOS may not count the hours the Mac sleeps.
_LEARNED_FOR_S = 12 * 3600


def _tool_title(name: str) -> str:
    """The name a person knows the tool by: `upkeep.py` says `claude` for Claude Code."""
    return {"claude": "Claude Code"}.get(name, name)


def _updated_to_newest(tool) -> bool:
    """The tool's source cannot tell, and it is on the version an update in this run left it on,
    less than `_LEARNED_FOR_S` ago."""
    version, learned_at = _UPDATED_TO.get(tool.name, ("", 0.0))
    return (not tool.available and bool(tool.installed) and version == tool.installed
            and time.time() - learned_at < _LEARNED_FOR_S)


def _tool_offered(tool) -> bool:
    """Whether the row's button may be live: the status offers it, and no update here has just
    found the version it is on to be the newest (tcc#138)."""
    return tool.offered and not _updated_to_newest(tool)


def _tool_line(tool) -> str:
    """One tool's row (tcc#98): the version here → the one out there, in words. An empty
    `available` is UNKNOWN (hub #219), never "up to date" — unless an update in this run left the
    tool on the version it is on, and then it is that update's «already the newest» (tcc#138)."""
    name, here = _tool_title(tool.name), tool.installed or "?"
    if not tool.updatable:
        return i18n.t("updToolNotOurs").format(name=name, here=here)
    if _updated_to_newest(tool):
        return i18n.t("updToolSame").format(name=name, here=here)
    if not tool.available:
        return i18n.t("updToolUnknown").format(name=name, here=here)
    if tool.newer:
        return i18n.t("updToolAvailable").format(name=name, here=here, there=tool.available)
    return i18n.t("updToolCurrent").format(name=name, here=here)


def _tool_done_line(row, shown: str = "") -> str:
    """The receipt of one tool that updated: old → new, or that it already was the newest.

    `shown` is the version its row showed. The skill reads `old` at the press, and a native Claude
    Code updates itself in the background: on the VM it moved 2.1.286 → 2.1.287 before the press,
    and the receipt said «2.1.287: already the newest» under a row that had read 2.1.286 (finding
    140, review of tcc#138). The person saw the row, so the move is said from it."""
    name = _tool_title(row.name)
    old = shown if shown and row.old == row.new else row.old
    if row.new and row.new == old:
        return i18n.t("updToolSame").format(name=name, here=row.new)
    return i18n.t("updToolDone").format(name=name, old=old or "?", new=row.new or "?")


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
    """One of TCC's own checks, with a button for each repair that is TCC's to make.

    The buttons are the whole point of the section. A diagnostic that describes a problem and
    leaves the remedy in a file the Arbiter has no reason to open is a diagnostic that gets read
    once — which is how three model aliases sat redirecting every reviewer call for five days.

    A repair that cannot be made says why on its own row, and the row stays (#169). It used to go
    out as the receipt — «Fixed: RuntimeError: …» — with the panel redrawn under it; and a re-link
    that moved the project's entry and then could make no link leaves the project reading TCC's
    copy, so a redrawn panel would show no method row at all, nor the sentence saying where the
    entry went.
    """

    fixed = Signal(str)

    def __init__(self, check: self_check.Check) -> None:
        super().__init__()
        self.check = check
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(2)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(TrafficLight(check.status))
        title = QLabel(check.title)
        title.setWordWrap(True)
        head.addWidget(title, stretch=1)
        self._buttons: list[QPushButton] = []
        for action in check.actions:
            button = QPushButton(action.label)
            button.setProperty("class", "reason-btn")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            # Never the dialog's default (R-aq): in a QDialog a push button is auto-default, so
            # Enter pressed the one with focus — the one beside a press, which disables its own.
            # A repair, approving a copy of the method among them, is a deliberate press.
            button.setAutoDefault(False)
            button.setDefault(False)
            button.clicked.connect(lambda _checked=False, action=action: self._run(action))
            head.addWidget(button)
            self._buttons.append(button)
        layout.addLayout(head)

        for line in (check.detail or "").splitlines():
            if line.strip():
                layout.addWidget(_note(line))
        self._failed: Optional[QLabel] = None

    def _run(self, action: self_check.Action) -> None:
        for button in self._buttons:
            button.setEnabled(False)
        try:
            message = action.run() or ""
        except method_binding.MethodRefused as exc:  # one sentence, the method's: said as it is
            self._say_failed(str(exc))
        except Exception as exc:  # noqa: BLE001 — a failed repair is a sentence, not a crash
            self._say_failed(f"{type(exc).__name__}: {exc}")
        else:
            self.fixed.emit(message)

    def _say_failed(self, why: str) -> None:
        if self._failed is None:
            self._failed = _note("")
            self._failed.setProperty("class", "kv-warn")
            self.layout().addWidget(self._failed)
        self._failed.setText(i18n.t("selfActionFailed").format(why=why))
        for button in self._buttons:
            button.setEnabled(True)


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

    def __init__(self, work, name: str = "tcc-skill-update") -> None:
        self.result = None
        self.error = ""
        self._thread = threading.Thread(target=self._run, args=(work,), name=name, daemon=True)
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
    #: An `updates.Status` this window has just learned — a row's answer, or an update's receipt.
    #: The main window's title says «update available» by it (VM-3): it kept the word after the
    #: method was updated here, through Re-check and ↻, until TCC restarted.
    updateLearned = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._report: Optional[ContractReport] = None
        self._checks: list = []
        #: `subject::issue` -> when it was last forwarded. In memory on purpose: the durable
        #: record of the ask is the message in the transcript, and this only decides whether the
        #: row says "still here, asked N minutes ago".
        self._asked: dict[str, float] = {}
        #: A fix's receipt (`_on_fixed`), said above the verdict of the report it lands on for as
        #: long as that report is on screen — through every redraw of it — until a newer report, a
        #: Re-check or the next fix. `_receipt_on` is that report, None while the receipt waits
        #: for one begun after `_receipt_after` — both `contract_check.stamp()`s, a count and
        #: not a clock, so the two can never tie (N1).
        self._receipt = ""
        self._receipt_on: Optional[ContractReport] = None
        self._receipt_after = 0
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

        # What is wrong with this PROJECT first, then what is on this MACHINE. The installation is
        # here rather than in a window of its own because this is the window a person already
        # opens when something is off, and the first question every report from a machine nobody
        # can see has needed is "which versions am I looking at" (user, 2026-08-19).
        #
        # Updates are a tab of their own (VM-1, tcc#98): on the Installation tab the updater and
        # the tool rows had to be scrolled while the report box kept half the height — the Arbiter,
        # «давай зробимо оновлення на окремій вкладці». Second, in the order the ⚙'s tip names them:
        # the project check, updates, the logs. The window still opens on the project: the ⚙ and
        # the status strip's contract line send people here for that, and opening on Updates would
        # ask GitHub and the minute-long tool status at every open. No update action in TCC opens
        # this window; the ⚙ and the menu are its doors.
        self._project_tab = scroll
        self._updates_tab = self._build_updates_tab()
        self._install_tab = self._build_install_tab()
        self._log_tab = self._build_log_tab()
        self._sessions_tab = self._build_sessions_tab()
        self._tabs = QTabWidget()
        for tab, key in self._tab_keys():
            self._tabs.addTab(tab, i18n.t(key))
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

    def _tab_keys(self) -> tuple:
        """Each tab and the key of its name, in the order they stand."""
        return ((self._project_tab, "diagTabProject"), (self._updates_tab, "diagTabUpdates"),
                (self._install_tab, "diagTabInstall"), (self._log_tab, "diagTabLog"),
                (self._sessions_tab, "diagTabSessions"))

    # ---- updates -------------------------------------------------------------

    def _build_updates_tab(self) -> QWidget:
        """TCC's and the method's rows, the beta box, and the tools the installer put in."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_update_row())
        layout.addStretch(1)
        self._updates_read = False
        # The page scrolls rather than squeezing. The window takes its height when it opens, and
        # the tool rows land up to a minute later (tcc#98): with no room to grow into, each was
        # crushed to 5 px of the 25 it needs — unreadable, and a button nobody could press (review
        # of tcc#98). In a scroll area the page keeps its minimum height and the window keeps its
        # size; the Project tab is shaped the same way.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def refresh_updates(self) -> None:
        """Ask GitHub about TCC and the method, and the skill's `upkeep.py` about the tools — each
        off the GUI thread, each only if it is not being asked already."""
        self._updates_read = True
        self._start_update_check()
        self._start_tools_check()

    # ---- what is installed ---------------------------------------------------

    def _build_install_tab(self) -> QWidget:
        """One selectable, copyable block. Not a table: it is written to be PASTED — into a
        message, an issue, a screenshot — and a monospace block survives all three. The box takes
        the tab's height: nothing lands above it later, now that the updates have their own tab
        (VM-1)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        blurb = QLabel(i18n.t("diagInstallBlurb"))
        blurb.setWordWrap(True)
        blurb.setProperty("class", "phead-sub")
        layout.addWidget(blurb)
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
        #: The tools section the report's probe last delivered, while it still describes this
        #: machine: an update drops it (`_install_changed`). «Report a problem» sends it whichever
        #: tab is shown, or says it has not answered (`_report_text`).
        self._report_tools: Optional[install_report.Section] = None
        # The timer belongs to this dialog, so it stops when the dialog goes; the thread does not,
        # because it holds nothing of Qt's.
        self._install_tries = 0
        self._install_timer = QTimer(self)
        self._install_timer.setInterval(_TOOLS_POLL_MS)
        self._install_timer.timeout.connect(self._poll_tools)
        return page

    def _install_changed(self) -> None:
        """Something was installed, so the report's versions are stale. Read again now if its tab
        is on screen or it was read before — «Report a problem» sends it from any tab, and a block
        sent straight after updating omp went without the tools (review of VM fix A). A report
        nobody has opened is not read behind the Updates tab: it is read when its tab is."""
        was_read = self._install_read
        self._install_read = False
        self._report_tools = None
        # A probe still running asked the tools before this landed, and its answer would put the
        # old versions back. It is let go as `_on_beta_toggled` lets the update probe go — a daemon
        # thread holding no Qt object — and the re-read below starts a new one (tcc#130).
        self._install_worker = None
        self._install_timer.stop()
        if was_read or self._tabs.currentWidget() is self._install_tab:
            self.refresh_install()

    def _build_update_row(self) -> QWidget:
        """Two lines, two buttons: is there a newer one, and the thing that installs it.

        The buttons are disabled until the check comes back, and stay disabled when there is
        nothing to do: a live "Update" button on an up-to-date install is a question mark, not an
        offer.
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
        # omp, agy, gh and Claude Code (tcc#98): what the installer put in beside TCC, as the
        # skill's own `upkeep.py` finds it (hub #219). The rows come after its `status` does — up to
        # a minute — and nothing is updated without a press: a newer omp changes what a session
        # runs on (tcc#97).
        self._tools_title = _section_title(i18n.t("updToolsTitle"))
        grid.addWidget(self._tools_title)
        tools = QWidget()
        self._tools_layout = QVBoxLayout(tools)
        self._tools_layout.setContentsMargins(0, 0, 0, 0)
        self._tools_layout.setSpacing(4)
        grid.addWidget(tools)
        self._tools: dict = {}
        self._tool_rows: dict = {}
        #: Whether each row's button would be live with no session running: offered by the
        #: status, off once that tool updated. The buttons are drawn from this (`_sync_tools`).
        self._tool_offer: dict = {}
        #: The «a session runs on it» line under the omp and Claude Code rows (ruling 21).
        self._tool_guards: dict = {}
        self._tools_all_btn: Optional[QPushButton] = None
        self._tools_all_note: Optional[QLabel] = None
        self._tools_job: Optional[_UpdateStep] = None
        self._tools_then = None
        self._tools_asked: list = []
        #: Is an AI session running — asked of the main window (`set_session_probe`) when this
        #: window opens or is come back to, on Re-check, when the rows land and at the press;
        #: False with nobody to ask.
        self._session_probe = None
        self._session_running = False
        self._tools_timer = QTimer(self)
        self._tools_timer.setInterval(_TOOLS_POLL_MS)
        self._tools_timer.timeout.connect(self._poll_tools_job)
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
        elif status.reason == "ahead":
            # Past the newest release — a candidate (finding 144). Said with the release it is past,
            # over a button that stays off: «a newer one is out: 3.0.66» on 3.1.0 offered a rollback.
            label.setText(i18n.t("updAhead").format(what=title, here=here, there=status.latest))
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
        self.updateLearned.emit(status)

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
            button.setEnabled(found.reason not in _STANDING_REFUSALS)
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
                lines.append(i18n.t("updSkillSigned").format(line=_signature_said(done.signature)))
            # TCC's own readers kept the method it started with until a restart (#126, the
            # re-review of 697378d). Read again here, on the GUI thread, between two of its passes;
            # when the new files do not load in this process, the old method stays and he is told.
            if not vendor_loader.reload_loaded():
                lines.append(i18n.t("updSkillRestart").format(version=done.version.lstrip("v")))
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
            # The report must show the new version — but the row keeps what it just said until the
            # next Re-check, because that sentence is the receipt for the press.
            self._install_changed()
            # And the receipt is an answer: the method is now the release it was offered (VM-3).
            version = done.version.lstrip("v")
            self.updateLearned.emit(updates.Status("skill", version, version, False))
        else:
            # Pressed again, a standing refusal would only fetch and say the same: off until a
            # Re-check (`_STANDING_REFUSALS`). Any other refusal can change on its own.
            button.setEnabled(done.reason not in _STANDING_REFUSALS)

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
            # And a standing refusal keeps the button off, as on the method's row («ahead»).
            label.setText(i18n.t("updFailed").format(why=_reason(ready.reason, ready.detail)))
            button.setEnabled(ready.reason not in _STANDING_REFUSALS)
            return
        try:
            terminal_launcher.run_script(ready.script)
        except Exception as exc:  # noqa: BLE001 — no terminal we know how to drive
            label.setText(i18n.t("updFailed").format(why=f"{type(exc).__name__}: {exc}"))
            button.setEnabled(True)
            return
        label.setText("\n".join([i18n.t("updTccHanded"),
                                  i18n.t("updSkillSigned").format(
                                      line=_signature_said(ready.signature))]))

    # ---- omp, agy, gh, Claude Code (tcc#98) ----------------------------------

    def set_session_probe(self, probe) -> None:
        """How to ask whether an AI session is running: the main window's `_session_running`.
        A session runs on omp and Claude Code, so their rows wait while one runs (ruling 21,
        tcc#98). Updated under it, the running session keeps the old one on macOS and the update
        fails on a locked file on Windows, and nothing said why."""
        self._session_probe = probe
        self._read_session()

    def _session_live(self) -> bool:
        return bool(self._session_probe()) if self._session_probe is not None else False

    def _read_session(self) -> None:
        """Ask again and redraw the buttons by the answer: on open, on Re-check, when rows land."""
        self._session_running = self._session_live()
        self._sync_tools()

    def _sync_tools(self) -> None:
        """Every tool button from what is offered, whether an update is running, and whether a
        session runs on the tool — with the reason under each row a session holds, and beside
        «Update all», which would take those along."""
        busy = self._tools_job is not None
        held = []
        for name, (_label, button) in self._tool_rows.items():
            offered = self._tool_offer.get(name, False)
            guarded = offered and self._session_running and name in _SESSION_TOOLS
            if guarded:
                held.append(_tool_title(name))
            button.setEnabled(offered and not busy and not guarded)
            guard = self._tool_guards.get(name)
            if guard is not None:
                guard.setHidden(not guarded)
        if self._tools_all_btn is not None:
            self._tools_all_btn.setEnabled(not busy and not held and any(self._tool_offer.values()))
            self._tools_all_note.setText(
                i18n.t("updToolsSessionAll").format(names=", ".join(held)))
            self._tools_all_note.setHidden(not held)

    def _start_tools_check(self) -> None:
        """Ask the skill's `upkeep.py status` about the tools — but not while one is being
        updated: its row says so, and the receipt is on its way."""
        if self._tools_job is not None:
            return
        self._show_tools_note(i18n.t("updToolsChecking"))
        self._run_tools_step(updates.tools_status, self._after_tools_status)

    def _run_tools_step(self, work, then) -> None:
        self._tools_job = _UpdateStep(work, name="tcc-tools")
        self._tools_then = then
        self._tools_timer.start()

    def _poll_tools_job(self) -> None:
        job = self._tools_job
        if job is None or job.running:
            return
        self._tools_timer.stop()
        then, self._tools_job, self._tools_then = self._tools_then, None, None
        then(job)

    def _clear_tools(self) -> None:
        clear_layout(self._tools_layout)
        self._tools, self._tool_rows, self._tool_offer, self._tool_guards = {}, {}, {}, {}
        self._tools_all_btn = self._tools_all_note = None

    def _show_tools_note(self, text: str) -> None:
        """One line where the rows go: still asking, none here, or why it could not be asked."""
        self._clear_tools()
        self._tools_layout.addWidget(_note(text))

    def _after_tools_status(self, job) -> None:
        """A row per tool that is present: here → out there, and its own button; then «all»."""
        found = job.result
        if job.error or found is None:
            self._show_tools_note(i18n.t("updToolsUnknown").format(why=job.error or "?"))
            return
        if not found.ok:
            self._show_tools_note(i18n.t("updToolsUnknown").format(
                why=_reason(found.reason, found.detail)))
            return
        if not found.tools:
            self._show_tools_note(i18n.t("updToolsNone"))
            return
        self._clear_tools()
        self._tools = {tool.name: tool for tool in found.tools}
        for tool in found.tools:
            if (tool.installed and tool.name in _UPDATED_TO
                    and _UPDATED_TO[tool.name][0] != tool.installed):
                # Another version than the update left — its own updater, or something outside
                # TCC: what the update learned was of an install no longer here (tcc#138). An
                # empty one is a `--version` that failed or timed out: the tool would not say,
                # which is not another version, and dropping it brought the offer back.
                del _UPDATED_TO[tool.name]
            label = QLabel(_tool_line(tool))
            label.setWordWrap(True)
            label.setProperty("class", "mn")
            left = label
            if tool.name in _SESSION_TOOLS:
                left = QWidget()
                column = QVBoxLayout(left)
                column.setContentsMargins(0, 0, 0, 0)
                column.setSpacing(2)
                column.addWidget(label)
                guard = _note(i18n.t("updToolSession"))
                # Orange, not the error's red: a stopper, not a failure (VM-5, the Arbiter: «не
                # сірим - помаранчевим, бо це стопер але не помилка»).
                guard.setProperty("class", "kv-caution")
                column.addWidget(guard)
                self._tool_guards[tool.name] = guard
            button = self._tools_row(left, i18n.t("updTool"))
            button.clicked.connect(lambda _c=False, name=tool.name: self._update_tools([name]))
            self._tool_rows[tool.name] = (label, button)
            self._tool_offer[tool.name] = _tool_offered(tool)
        self._tools_all_note = _note("")
        self._tools_all_note.setProperty("class", "kv-caution")
        self._tools_all_btn = self._tools_row(self._tools_all_note, i18n.t("updToolsAll"))
        self._tools_all_btn.clicked.connect(self._update_offered_tools)
        self._read_session()

    def _tools_row(self, left: QWidget, text: str) -> QPushButton:
        """A line of the tools' list — `left`, and a button held to the right even when `left` is
        hidden — in a widget of its own, so `clear_layout` takes the whole of it."""
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        line.addWidget(left, stretch=1)
        button = QPushButton(text)
        button.setProperty("class", "reason-btn")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        line.addWidget(button, alignment=Qt.AlignmentFlag.AlignRight)
        self._tools_layout.addWidget(row)
        return button

    def _update_offered_tools(self) -> None:
        """«Update all» is every row whose button is live — what the rows offer now, not every tool
        present: one already updated, or current, is not touched again."""
        self._update_tools([name for name, (_label, button) in self._tool_rows.items()
                            if button.isEnabled()])

    def _update_tools(self, names: list) -> None:
        """The skill's `upkeep.py tools --only …`, off the GUI thread: a package manager per tool.
        Every tool button waits meanwhile — one update at a time."""
        if self._tools_job is not None or not names:
            return
        # Asked again at the press: a session started since the rows were drawn holds its tools
        # all the same, and the rows now say why.
        self._read_session()
        if self._session_running and any(name in _SESSION_TOOLS for name in names):
            return
        self._tools_asked = list(names)
        for name in names:
            self._tool_rows[name][0].setText(i18n.t("updToolUpdating").format(
                name=_tool_title(name), here=self._tools[name].installed or "?"))
        asked = list(names)
        self._run_tools_step(lambda: updates.update_tools(asked), self._after_tools_update)
        self._sync_tools()

    def _after_tools_update(self, job) -> None:
        """Each tool asked about: old → new, or its own line with the reason under it. A row
        nobody asked about keeps its words, and its button comes back — a failure hides nothing."""
        done = job.result
        if job.error or done is None:
            done = updates.ToolsUpdate((), "upkeep_failed", job.error or "?")
        answered = {row.name: row for row in done.rows}
        moved = False
        for name in self._tools_asked:
            label = self._tool_rows[name][0]
            row = answered.get(name)
            if row is not None and row.ok:
                moved = True
                label.setText(_tool_done_line(row, self._tools[name].installed))
                self._tool_offer[name] = False
                if row.new:
                    # The package manager has just installed the newest: kept past Re-check, where
                    # a source that cannot tell would offer the update again (tcc#138).
                    _UPDATED_TO[name] = (row.new, time.time())
                continue
            if row is not None:
                why = row.why or "?"
            elif done.reason:
                why = _reason(done.reason, done.detail)
            else:  # asked for, and the skill no longer found it here
                why = _reason("not_found")
            # From the tool's own line, not from what the label said: a second failure stacked a
            # second reason under the first (review of tcc#98).
            label.setText(_tool_line(self._tools[name]) + "\n"
                          + i18n.t("updToolFailed").format(why=why))
        self._read_session()
        if moved:
            # The report names each tool's version; the rows keep their receipts until the next
            # Re-check, as the method's row does.
            self._install_changed()

    def _poll_tools(self) -> None:
        """Put the tools section in as soon as it lands, and stop asking either way."""
        self._install_tries += 1
        probe = self._install_worker
        if probe is None or (probe.section is None and self._install_tries < _TOOLS_TRIES
                             and probe.running):
            return
        self._install_timer.stop()
        if probe.section is not None:
            self._report_tools = probe.section
            self._render_install(probe.section)
        else:
            # Given up with the probe still asking: the box says so, as the report does — not a
            # «reading…» nothing will replace, which Copy sent with no tools section (tcc#130).
            # `_report_tools` stays empty, so a late answer is still taken (`_take_late_tools`).
            self._render_install(self._tools_unanswered(probe, probe.running))

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
        """Ask a tab's questions the first time it is opened, and never on the way to another one.

        Eight subprocesses is not something to pay for opening a dialog about a contract check,
        and GitHub with the skill's minute-long `status` is not either (VM-1: each tab pays for
        its own).
        """
        tab = self._tabs.widget(index)
        if tab is self._updates_tab and not self._updates_read:
            self.refresh_updates()
        elif tab is self._install_tab and not self._install_read:
            self.refresh_install()
        elif tab is self._log_tab:
            # Every time, not once: the log grows while this window is open, and that is exactly
            # when something is going wrong.
            self.refresh_log()
        elif tab is self._sessions_tab:
            self.refresh_sessions()

    def refresh_install(self) -> None:
        """Everything that reads a file, now; everything that runs a program, on a thread.

        The block is on screen the moment the tab opens — versions, paths, where the skill is —
        with the tools section filling in a second later, rather than an empty box and a wait.
        GitHub is not asked from here: that is the Updates tab's (`refresh_updates`), so a re-read
        straight after an update does not take the row's receipt away at the moment it was earned.
        """
        probe = self._install_worker
        # A probe the poll gave up on is let go, as `_install_changed` lets one go: one stuck in a
        # `communicate()` (tcc#31) would otherwise leave Re-check dead until a restart (tcc#130).
        if probe is not None and probe.running and self._install_tries < _TOOLS_TRIES:
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
        # Read once, before the late take: a probe that ends between two reads of `running` was
        # neither taken nor «still being asked», and read as one that never answered (tcc#130).
        probe = self._install_worker
        running = probe is not None and probe.running
        self._take_late_tools()
        if self._install_read and self._report_tools is not None and not running:
            return self._install_text.toPlainText()
        # The box is not the whole answer: the tab was never opened, or it is being read again
        # (Re-check, an update). Compose the report now with the tools as last delivered — or a
        # section that SAYS they have not answered: they start eight processes, and the versions
        # and paths are file reads that cost nothing. Left out silently, a report sent straight
        # after an update read as one with no tools at all (review of VM fix A).
        try:
            return install_report.as_text(install_report.report(
                extra=self._install_extra(), with_tools=False,
                tools_section=self._report_tools or self._tools_unanswered(probe, running)))
        except Exception as exc:  # noqa: BLE001 — a report that cannot be built still opens
            return f"{type(exc).__name__}: {exc}"

    def _tools_unanswered(self, probe, running: bool) -> install_report.Section:
        """The tools section when there is no answer to send, built in one place so the box and
        the report say the same (tcc#130). In the report's own English, like its other lines."""
        if probe is None:
            said, detail = "not asked yet", "the Installation tab reads them"
        elif running and self._install_tries < _TOOLS_TRIES:
            said, detail = "still being asked", ""
        else:
            # Asked, and the poll's 15 s ran out first: a slow Windows VM, or a probe stuck in a
            # `communicate()` (tcc#31). Not «not asked yet», which this read before (tcc#130).
            said, detail = "did not answer in time", f"{_TOOLS_TRIES * _TOOLS_POLL_MS // 1000} s"
        return install_report.Section(
            "Command-line tools", [install_report.Item("probe", said, detail)])

    def _open_issue(self) -> None:
        """Ask for the words and send them the way the person can: the form without an account,
        the beta-report issue with one (TODO F-042). The installation block goes either way — in
        the form's text under the words, or in the issue template's own field."""
        report = self._report_text()
        FeedbackDialog(
            ISSUES_URL, form_report.post_url(), self, kind="problem", attachment=report,
            github_link=lambda body: issue_url(body, report),
        ).exec()

    def _take_late_tools(self) -> None:
        """A probe slower than the poll (`_TOOLS_TRIES` looks, 15 s) answers after the timer has
        stopped reading it, and nobody read it: the report said «not asked yet» for tools that were
        asked (tcc#130). Its section is taken when the block is next sent or copied, and the box —
        which says it «did not answer in time» since the give-up — is drawn with it: the box is
        what a complete report sends."""
        probe = self._install_worker
        if (self._report_tools is None and probe is not None and not probe.running
                and probe.section is not None):
            self._report_tools = probe.section
            self._render_install(probe.section)

    def _copy_install(self) -> None:
        self._take_late_tools()
        QGuiApplication.clipboard().setText(self._install_text.toPlainText())
        self._copy_btn.setText(i18n.t("diagInstallCopied"))

    # ---- state ---------------------------------------------------------------

    def set_report(self, report: Optional[ContractReport]) -> None:
        """`None` means a check is running — the panel says so rather than showing stale data as
        if it were current. A newer report than the one a fix's receipt was said with ends the
        receipt: it has had its turn, and the new verdict is its own."""
        if report is not None and self._receipt_on is not None and report is not self._receipt_on:
            self._receipt, self._receipt_on = "", None
        self._report = report
        self._refresh_btn.setEnabled(report is not None)
        self._render()

    def own_checks_changed(self) -> None:
        """A reading the self-check rows show came in after the report — agy's sign-in, which
        follows it (final review of W-6, M2). Drawn again with it; a check still running keeps its
        «Checking…» until its own report."""
        if self._report is not None:
            self._render()

    def _ask_row(self, subject: str, issue: str, shown: Optional[str] = None) -> QWidget:
        row = _AskRow(subject, issue, self._asked.get(f"{subject}::{issue}"), shown)
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
        it. A panel whose contents disagree with its own message is a panel nobody believes.

        The receipt goes above the verdict (`_say`), and stays there through every redraw of its
        report: the window draws each report again when agy's reading follows it, so a receipt
        said once was gone before anyone read it — and after a re-link, whose row goes, it is the
        one place that says where the old entry went (fix round 1 of #169, I1).

        Over a check that could not run, the check is asked for again first, and the receipt waits
        for its answer (#169): the fix may be what it lacked — a project on a copy TCC refuses
        fails the check with the binding's sentence, and that sentence would stand over a row that
        says the copy is approved now. It waits for a check BEGUN after the fix: the window shows
        its last report while a check runs and queues a Re-check behind it, and the running
        check's report, coming first, is the old state."""
        self._receipt = i18n.t("diagFixDone").format(what=message)
        if self._report is not None and not self._report.available:
            self._receipt_on, self._receipt_after = None, stamp()
            self.set_report(None)
            self.refreshRequested.emit()
            return
        self._receipt_on = self._report
        self._render()

    def _say(self, verdict: str) -> None:
        """The verdict, under the receipt of a fix when this is its report: the one on screen when
        it was made, or the first one begun after it when it asked for the check again."""
        if (self._receipt and self._receipt_on is None
                and self._report.started > self._receipt_after):
            self._receipt_on = self._report
        if self._receipt and self._receipt_on is self._report:
            verdict = f"{self._receipt}\n{verdict}"
        self._verdict.setText(verdict)

    def _on_refresh(self) -> None:
        """Re-check means everything this window shows, not only the project.

        The update rows are the part a person presses this button to see move — after an update
        was installed, or after the network came back (user, 2026-08-19). The Updates and
        Installation tabs are marked unread rather than read here: they ask GitHub, the skill's
        `status` and eight subprocesses, and if the person is looking at another tab that cost
        belongs at the moment they open it, not now.

        A fix's receipt ends here: what the person asked for now is a fresh look.
        """
        self._receipt, self._receipt_on = "", None
        self.set_report(None)
        self.refreshRequested.emit()
        self._install_read = False
        self._updates_read = False
        self._read_session()  # whether a session holds omp and Claude Code (ruling 21)
        tab = self._tabs.currentWidget()
        if tab is self._updates_tab:
            self.refresh_updates()
        elif tab is self._install_tab:
            self.refresh_install()
        elif tab is self._log_tab:
            self.refresh_log()

    def _retranslate(self) -> None:
        self.setWindowTitle(i18n.t("diagTitle"))
        self._title.setText(i18n.t("diagTitle"))
        self._refresh_btn.setText(i18n.t("diagRefresh"))
        self._close_btn.setText(i18n.t("diagClose"))
        for tab, key in self._tab_keys():
            self._tabs.setTabText(self._tabs.indexOf(tab), i18n.t(key))
        for name, key in (("tcc", "updTcc"), ("skill", "updSkill")):
            self._update_rows[name][1].setText(i18n.t(key))
        self._beta_box.setText(i18n.t("updBetaChannel"))
        self._tools_title.setText(i18n.t("updToolsTitle"))
        for _label, button in self._tool_rows.values():
            button.setText(i18n.t("updTool"))
        if self._tools_all_btn is not None:
            self._tools_all_btn.setText(i18n.t("updToolsAll"))
        for guard in self._tool_guards.values():
            guard.setText(i18n.t("updToolSession"))
        self._sync_tools()
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

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Opening the window asks again whether a session holds omp and Claude Code (ruling 21):
        the rows may be from before it started, or from before it ended."""
        super().showEvent(event)
        self._read_session()

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Coming back to the window asks again too: a session the person ended in the main
        window while this one stayed open lets go of omp and Claude Code here and now. Only the
        question to the main window — the tools' status takes a minute and is Re-check's."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self._read_session()

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
            self._say(f"{i18n.t('diagUnavailable')} — {report.error}")
            # TCC's own setup does not wait on the project's check. It was drawn only under a check
            # that ran — and a project on a copy TCC refuses fails that check with the binding's
            # sentence (#169), so the row with the two fixes for it could never be seen.
            self._own_checks(self_check.run())
            self._body_layout.addStretch(1)
            return

        # The headline counts BOTH halves. It read `report.ok` alone, so the panel could say
        # "OK — nothing to fix" directly above a red row of its own making, which is the exact
        # shape of thing this section was added to stop.
        checks = self_check.run()
        own = [c for c in checks if c.status != self_check.OK]
        issues = report.issues()
        total = len(issues) + len(own)
        self._say(
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
        # A ▶️ CONTINUE block behind the ledger (#126; the method's S-084, hub #227). A warning the
        # checker keeps out of `ok`, so out of the headline too -- but the block is what a person
        # opens first and what the next session reads beside the ledger, and the panel never said
        # it was stale. Forwardable like the rest.
        # Nothing to read and no sentence to send is no row at all (#126's review, Minor 2).
        drift = report.continue_head() or {}
        shown = _continue_head_line(drift) if drift else None
        said = str(drift.get("warning") or "").strip() or shown
        if said:
            self._body_layout.addWidget(self._ask_row("tuning-changelog", said, shown))
        if not cross_notes and not said:
            self._body_layout.addWidget(_note(i18n.t("diagNoIssues")))
        self._body_layout.addWidget(_note(_rew_line(report)))

        # Facts carried in from another project, and sources that are gone (hub #154 §3/§4).
        # Reported, never gated — so not counted in the headline — but named. The pre-sweep gate
        # gates on them no more either (the method's v3.0.65, hub #225): a fragile driver's
        # inherited Fs is a warning before the sweep (`presweep_warnings`), the sweep goes on, and
        # the high-pass is still held to 1.1 × that Fs.
        if report.inherited or report.sources_gone:
            self._body_layout.addWidget(_section_title(i18n.t("diagInherited")))
            for row in report.inherited:
                self._body_layout.addWidget(_note(
                    f"{row.get('path')} = {row.get('value')!r} "
                    f"({i18n.t('diagInheritedFrom').format(path=row.get('from') or '?')})"))
            for path in report.sources_gone:
                self._body_layout.addWidget(_note(i18n.t("diagSourceGone").format(path=path)))

        self._own_checks(checks)

        open_questions = report.open_questions()
        if open_questions:
            self._body_layout.addWidget(_section_title(i18n.t("diagOpenQ")))
            for question in open_questions:
                self._body_layout.addWidget(_note(question))

        self._body_layout.addStretch(1)

    def _own_checks(self, checks: list) -> None:
        """TCC's own setup, after the project's. Separate section because it is a different
        question with a different owner: these are things TCC did to itself, and the ones it may
        undo carry a button (see `core/self_check.py` for where that line is drawn)."""
        self._checks = checks
        self._body_layout.addWidget(_section_title(i18n.t("selfSection")))
        for check in checks:
            row = _CheckRow(check)
            row.fixed.connect(self._on_fixed)
            self._body_layout.addWidget(row)


def _continue_head_line(drift: dict) -> Optional[str]:
    """`continue_head` in the Arbiter's words, from its fields: which versions the block names,
    and where the ledger stands, slot by slot. None when the fields are not the shape the method's
    v3.0.65 gives, and the row shows the checker's own sentence instead."""
    stale, heads = drift.get("stale"), drift.get("heads")
    if not (isinstance(stale, list) and stale and isinstance(heads, dict) and heads):
        return None
    at = ", ".join(f"{head} ({slot})" for slot, head in sorted(heads.items()))
    return i18n.t("diagContinueHead").format(named=", ".join(map(str, stale)), at=at)


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
