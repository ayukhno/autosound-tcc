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
from autosound_tcc.ui.tcc.channel_order_dialog import ChannelOrderDialog
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
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
        name_sets: Optional[dict] = None,
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
        #: `{method: [(channel id, the full name a capture gets in REW)]}` — the round's own name
        #: sets, in the order the tuner declared. Built by the panel, which owns the sessions.
        self._name_sets = dict(name_sets or {})
        #: Proposed names, by uuid. Empty means "leave the title alone".
        self._names: dict[str, str] = {}
        #: `{uuid: {"hp": "80", "lp": ""}}` — what was typed into the two protective cells, as
        #: typed. Empty means "read this curve as measured", which is not a claim that the chain
        #: was empty; see `core/protective.py` for why those are different things.
        self._legs: dict[str, dict] = {}
        #: What the last "Give names" or Apply had to say about the names themselves — a count that
        #: did not line up, or a clash. Cleared by the next successful fill.
        self._plan_note = ""
        #: Channels whose two rows described two different chains. Filled by `protective()`.
        self.protective_conflicts: list[str] = []

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
        #: Rows whose capture time runs backwards against the row above — a sweep taken again
        #: because the first attempt did not come out. Marked, never refused: the user's own
        #: instruction (2026-09-02). In capture order this set is empty by construction; it fills
        #: when the dates could not be read and the list is in REW's own order instead.
        self._retakes = capture_import.out_of_sequence(self._all)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        head = QLabel(i18n.t("capImportHead").format(n=self._waiting) if has_task and self._waiting
                      else i18n.t("capImportNoTask"))
        head.setProperty("class", "phead-sub")
        head.setWordWrap(True)
        layout.addWidget(head)

        self._table = QTableWidget(0, 6)
        self._table.setProperty("class", "ptable")
        self._table.setHorizontalHeaderLabels(
            [i18n.t("capImportColTake"), i18n.t("capImportColTitle"), i18n.t("capImportColWhen"),
             i18n.t("capImportColName"), i18n.t("capImportColHp"), i18n.t("capImportColLp")])
        # Only the name column is typed into; `_render` gives exactly that column the flag.
        self._table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked
                                    | QTableWidget.EditTrigger.EditKeyPressed
                                    | QTableWidget.EditTrigger.AnyKeyPressed)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # The date sits BESIDE the proposed name on purpose: they are read together. A re-take
        # lands out of time order, and the name about to be written on it is the thing that goes
        # wrong when it does.
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
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
        self._name_btn = QPushButton(i18n.t("capImportGiveNames"))
        self._name_btn.setProperty("class", "reason-btn")
        self._name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._name_btn.clicked.connect(self._on_give_names)
        self._name_btn.setEnabled(bool(self._name_sets))
        attach_tip(self._name_btn, i18n.t("assignNames"))
        controls.addWidget(self._name_btn)
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
            when = QTableWidgetItem(row.date)
            if row.uuid in self._retakes:
                when.setText(f"↻ {row.date}")
                when.setToolTip(i18n.t("capImportRetake"))
            self._table.setItem(index, 2, when)

            name = QTableWidgetItem(self._names.get(row.uuid, ""))
            if row.identified:
                name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
                              | Qt.ItemFlag.ItemIsSelectable)
            else:
                name.setFlags(Qt.ItemFlag.ItemIsEnabled)
                name.setToolTip(i18n.t("capImportNoUuid"))
            self._table.setItem(index, 3, name)

            # The protective chain, in the row and nothing but the row (user, 2026-09-02: "все в
            # строчці без форм"). A frequency here IS the statement, and the statement is an LR24
            # — whoever ran something else opens `Protection`, where both dropdowns live.
            for column, key in ((4, "hp"), (5, "lp")):
                cell = QTableWidgetItem(self._legs.get(row.uuid, {}).get(key, ""))
                if row.identified:
                    cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
                                  | Qt.ItemFlag.ItemIsSelectable)
                else:
                    cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
                cell.setToolTip(i18n.t("capImportProtTip"))
                self._table.setItem(index, column, cell)
        self._table.blockSignals(False)
        self._render_note(len(rows))

    def _render_note(self, shown: int) -> None:
        lines = [self._plan_note] if self._plan_note else []
        lines.append(i18n.t("capImportShowing"))
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
        row = item.row()
        take = self._table.item(row, 0)
        uuid = str(take.data(_UUID) or "") if take is not None else ""
        if not uuid:
            return
        if item.column() == 0:
            if item.checkState() == Qt.CheckState.Checked:
                self._ticked.add(uuid)
            else:
                self._ticked.discard(uuid)
        elif item.column() == 3:
            typed = item.text().strip()
            if typed:
                self._names[uuid] = typed
                # Typing a name is asking for that measurement, so it stops being unticked by
                # accident: a rename nobody takes in is a rename for nothing.
                self._ticked.add(uuid)
            else:
                self._names.pop(uuid, None)
        elif item.column() in (4, 5):
            key = "hp" if item.column() == 4 else "lp"
            typed = item.text().strip()
            legs = self._legs.setdefault(uuid, {})
            if typed:
                legs[key] = typed
                self._ticked.add(uuid)  # same reason as a name: a record nobody takes in is none
            else:
                legs.pop(key, None)
            if not legs:
                self._legs.pop(uuid, None)

    def _on_give_names(self) -> None:
        """Fill names downwards from the selected row, out of a set the tuner picks.

        The set and the order are `ChannelOrderDialog`'s, unchanged — it already asks exactly the
        two questions this needs ("which capture method" and "in what order do you sweep"), and it
        already remembers the answer per preset. What moved is where it is asked FROM: it used to
        be a button on the card that then guessed which REW measurements were "the newest batch"
        by their ordinals. That guess is what the measurements of 2026-09-02 disproved.
        """
        picker = ChannelOrderDialog(self._name_sets, parent=self)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        method = picker.get_method()
        if method is None:
            return
        labels = dict(self._name_sets.get(method) or [])
        names = [labels.get(code, code) for code in picker.get_order()]
        rows = self.visible_rows()
        start = max(self._table.currentRow(), 0)
        plan = capture_import.plan_renames(rows, names, start)
        for uuid, name in plan.pairs:
            self._names[uuid] = name
            self._ticked.add(uuid)
        self._plan_note = "" if plan.lines_up else i18n.t("capImportUneven").format(
            rows=len(plan.unnamed), names=len(plan.leftover))
        self._render()

    def renames(self) -> list[tuple[str, str]]:
        """`(uuid, new title)` for every ticked row that is actually being renamed."""
        return [(row.uuid, self._names[row.uuid]) for row in self.ticked_rows()
                if self._names.get(row.uuid) and self._names[row.uuid] != row.title]

    def _on_more(self) -> None:
        self._pages += 1
        self._render()

    def _on_apply(self) -> None:
        """Check the names here, where they were typed; the renaming itself is the panel's.

        The check is not tidiness. The method's identity model rests on a title being one
        measurement's name — two graphs called `m-L_02 (sw)` are a channel nothing can resolve
        afterwards — and a batch caught before it is sent is a batch nobody has to undo.
        """
        clashes = capture_import.duplicate_targets(self.renames(), self._measurements)
        if clashes:
            self._plan_note = i18n.t("capImportClash").format(names=", ".join(clashes))
            self._render()
            return
        conflicts = (self.protective(), self.protective_conflicts)[1]
        if conflicts:
            self._plan_note = i18n.t("capImportProtClash").format(
                channels=", ".join(sorted(set(conflicts))))
            self._render()
            return
        self.accept()

    def taken(self) -> list[capture_import.Candidate]:
        """What the panel should write down once whatever renaming there is has happened."""
        return self.ticked_rows()

    def protective(self) -> dict:
        """`{channel: legs}` for every ticked row that names a chain — the round's own record.

        Keyed by CHANNEL and not by row, because that is what the record is about: the same channel
        captured twice with two methods is two rows and one signal path. Two rows that disagree are
        not silently merged — the first one wins and the second is reported, since a chain that was
        described two ways is a question for the person, not for a rule.
        """
        out: dict[str, dict] = {}
        self.protective_conflicts = []
        for row in self.ticked_rows():
            legs = capture_import.legs_from(*(self._legs.get(row.uuid, {}).get(k, "")
                                              for k in ("hp", "lp")))
            if legs is None:
                continue
            channel = capture_import.channel_of(
                row, self._names.get(row.uuid, ""), self._project_dir)
            if not channel:
                continue
            if channel in out and out[channel] != legs:
                self.protective_conflicts.append(channel)
                continue
            out[channel] = legs
        return out
