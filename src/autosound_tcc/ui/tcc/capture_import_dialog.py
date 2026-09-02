"""Choose which of REW's measurements come into this round — a table, and four controls.

Every decision behind it is in `core/capture_import.py` and is tested without a window. This file
is the table: it renders rows, remembers ticks, and hands the ticked ones to the store.

**Why this exists at all.** ⤓ used to fold everything REW held into the capture card: on the run
that produced this design, 102 titles, 16 of them expected and 86 appended as "additional" rows —
a card 1864 px tall, most of it somebody else's library, inside a card called "IN FOCUS NOW". The
user watches that card while capturing, so the noise was expensive. Nothing enters the round now
without a tick.

**No HTTP here.** The measurements arrive as an argument. The panel owns the worker that fetched
them, and a widget that blocks on a network call is a window that stops repainting while somebody
is in the car.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from autosound_tcc.core import capture_import
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.theme import apply_caps

#: Where a row's uuid rides on its checkbox item, so a tick survives a re-render.
_UUID = Qt.ItemDataRole.UserRole


class CaptureImportDialog(QDialog):
    """The list, the two filters over it, and Apply."""

    def __init__(
        self,
        measurements: dict,
        *,
        waiting: int = 0,
        round_id: str = "",
        has_task: bool = True,
        project_dir: Optional[Path] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(i18n.t("capImportTitle"))
        self.setMinimumWidth(640)
        self._measurements = measurements or {}
        self._waiting = int(waiting or 0)
        self._round_id = str(round_id or "")
        self._project_dir = project_dir
        self._pages = 0
        #: How many measurements were written on Apply — the panel reports it.
        self.written = 0

        self._all = capture_import.candidates(self._measurements, project_dir)
        #: Ticked by uuid rather than by row, because +10 and the filter both re-render the table
        #: underneath the tuner, and a tick that survives only until the next redraw is a tick
        #: nobody can trust.
        #:
        #: Opens on exactly as many as the round is waiting for — NOT on everything the window
        #: shows. The window is deliberately wider than the round (see `capture_import.MIN_WINDOW`:
        #: a window of three hides the measurement taken just before the three), and those extra
        #: rows are context. Ticking them by default would take measurements into the round that
        #: nobody captured for it, and the tuner would have to notice and untick. With no round to
        #: be waiting for, nothing is pre-ticked: there is no batch to guess at.
        newest = capture_import.unprocessed(self._all)[-self._waiting:] if self._waiting else []
        self._ticked = {row.uuid for row in newest if row.identified}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        head = QLabel(i18n.t("capImportHead").format(n=self._waiting) if has_task and self._waiting
                      else i18n.t("capImportNoTask"))
        head.setProperty("class", "phead-sub")
        head.setWordWrap(True)
        layout.addWidget(head)

        self._table = QTableWidget(0, 3)
        self._table.setProperty("class", "ptable")
        self._table.setHorizontalHeaderLabels(
            [i18n.t("capImportColTake"), i18n.t("capImportColTitle"), i18n.t("capImportColWhen")])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        apply_caps(header, spacing_px=0.7)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table, stretch=1)

        # What this list is and is not. Measured 2026-09-02: a filter switched on in REW's own
        # window changes what the API answers — 17, then 85, then 102 from one file — and a
        # filtered answer is renumbered with no gaps, so nothing in it reveals what is missing.
        # The dialog cannot see the filter; it can refuse to claim more than it knows.
        self._note = QLabel("")
        self._note.setProperty("class", "phead-sub")
        self._note.setWordWrap(True)
        layout.addWidget(self._note)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._only_new = QCheckBox(i18n.t("capImportOnlyNew"))
        self._only_new.setChecked(True)
        self._only_new.toggled.connect(lambda _on: self._render())
        controls.addWidget(self._only_new)
        self._more_btn = QPushButton(i18n.t("capImportMore"))
        self._more_btn.setProperty("class", "reason-btn")
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.clicked.connect(self._on_more)
        controls.addWidget(self._more_btn)
        controls.addStretch(1)
        cancel = QPushButton(i18n.t("npCancel"))
        cancel.setProperty("class", "reason-btn")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        controls.addWidget(cancel)
        self._apply_btn = QPushButton(i18n.t("capImportApply"))
        self._apply_btn.setProperty("class", "composer-send-ok")
        self._apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_btn.clicked.connect(self._on_apply)
        controls.addWidget(self._apply_btn)
        layout.addLayout(controls)

        self._render()

    # ---- what is on screen ---------------------------------------------------------------

    def visible_rows(self) -> list[capture_import.Candidate]:
        """The filter first, then the window — deliberately in that order.

        Windowing first and filtering after gives a window of ten that shows three: the tuner asked
        for as many as the round is waiting for, and they mean ten they can act on, not ten of
        which seven are already in.
        """
        rows = self._all if not self._only_new.isChecked() else capture_import.unprocessed(self._all)
        return capture_import.window(rows, self._waiting, self._pages)

    def ticked_rows(self) -> list[capture_import.Candidate]:
        return [row for row in self._all if row.uuid in self._ticked and row.identified]

    def _render(self) -> None:
        rows = self.visible_rows()
        self._table.blockSignals(True)  # filling cells emits itemChanged, which would edit `_ticked`
        self._table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            take = QTableWidgetItem("")
            take.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                          if row.identified else Qt.ItemFlag.ItemIsEnabled)
            take.setCheckState(Qt.CheckState.Checked if row.uuid in self._ticked
                               else Qt.CheckState.Unchecked)
            take.setData(_UUID, row.uuid)
            self._table.setItem(index, 0, take)

            title = QTableWidgetItem(row.title)
            if row.imported:
                # Shown only because the tuner asked to see them; saying WHY beats a row that
                # looks the same as the ones being offered.
                title.setToolTip(i18n.t("capImportAlready"))
            self._table.setItem(index, 1, title)

            # REW's own string, verbatim. It is a display date formatted by REW's locale, and
            # printing our own reformatting of something we could not fully parse would be
            # inventing precision.
            self._table.setItem(index, 2, QTableWidgetItem(row.date))
        self._table.blockSignals(False)
        self._render_note(len(rows))

    def _render_note(self, shown: int) -> None:
        lines = [i18n.t("capImportShowing")]
        if not capture_import.ordered_by_date(self._all) and self._all:
            lines.append(i18n.t("capImportRewOrder"))
        missing = capture_import.missing_imported(self._measurements, self._project_dir)
        if missing:
            lines.append(i18n.t("capImportMissing").format(n=len(missing)))
        if not shown:
            lines.append(i18n.t("capImportEmpty"))
        self._note.setText(" ".join(lines))
        self._more_btn.setEnabled(len(self.visible_rows()) < len(self._all))

    # ---- what the tuner does -------------------------------------------------------------

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        uuid = str(item.data(_UUID) or "")
        if not uuid:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._ticked.add(uuid)
        else:
            self._ticked.discard(uuid)

    def _on_more(self) -> None:
        self._pages += 1
        self._render()

    def _on_apply(self) -> None:
        self.written = capture_import.record_imported(
            self.ticked_rows(), round_id=self._round_id, project_dir=self._project_dir)
        self.accept()
