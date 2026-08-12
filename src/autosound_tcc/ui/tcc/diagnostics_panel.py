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

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import self_check
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

        for issue in entry.get("issues") or []:
            outer.addWidget(_note(str(issue)))
        if not entry.get("exists") and not (entry.get("issues") or []):
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


class DiagnosticsDialog(QDialog):
    """Non-modal so it can stay open beside the tune it describes."""

    refreshRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._report: Optional[ContractReport] = None
        self._checks: list = []
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
        outer.addWidget(scroll, stretch=1)

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

    # ---- state ---------------------------------------------------------------

    def set_report(self, report: Optional[ContractReport]) -> None:
        """`None` means a check is running — the panel says so rather than showing stale data as
        if it were current."""
        self._report = report
        self._refresh_btn.setEnabled(report is not None)
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
        self._render()

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
            self._body_layout.addWidget(_FileRow(entry))

        cross = report.cross_checks or {}
        cross_notes = list(cross.get("glossary_vs_ledgers") or []) + list(
            cross.get("tiers_vs_profile") or []
        )
        self._body_layout.addWidget(_section_title(i18n.t("diagCross")))
        for note in cross_notes or [i18n.t("diagNoIssues")]:
            self._body_layout.addWidget(_note(f"⚠ {note}" if cross_notes else note))
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
