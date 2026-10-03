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

**What opens ticked is decided by NAME** (`capture_import.preselect`, 2026-09-06): a row whose
title already answers to one of the names the round is waiting for. It used to be the newest N
rows, which is a guess about position — and on the user's own list the measurements the round
wanted were not the newest ones. A name two rows answer to ticks neither of them.

**The ticked sweeps are checked here, while the microphone is still in place** (tcc#21). Only the
method's own capture verdict (SCR-013), only for what is ticked, on a worker — and the check is
the panel's, handed in, so this file still makes no HTTP call. An unusable sweep gets a red mark
and two answers: «Re-take» (not taken, the recommendation) or «Take it as it is». Apply is never
refused for it (the Arbiter, 2026-10-02).
"""

from __future__ import annotations

from dataclasses import replace
from html import escape
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import capture_import
from autosound_tcc.ui.tcc import i18n, qt_shutdown, sizing
from autosound_tcc.ui.tcc.channel_order_dialog import ChannelOrderDialog
from autosound_tcc.ui.tcc.protective_dialog import ProtectiveLegsDialog
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.theme import apply_caps

#: Where a row's uuid rides on its checkbox item, so a tick survives a re-render.
_UUID = Qt.ItemDataRole.UserRole

#: The table's columns, by name rather than by number: the REW number was added between the tick
#: and the title (user, 2026-09-06), and every `item(row, 3)` in here would otherwise have had to
#: be re-counted by hand. The check's column (tcc#21) is added LAST so every other keeps its number,
#: and is shown beside the title it judges (`moveSection` in `__init__`).
_COL_TAKE, _COL_NUM, _COL_TITLE, _COL_WHEN, _COL_NAME, _COL_PROT, _COL_CHECK = range(7)


class _SweepCheckWorker(QThread):
    """The capture verdict for the rows handed in, off the GUI thread (tcc#21).

    `verify.verdict` pulls a frequency response and an impulse per sweep over HTTP, hundreds of
    milliseconds apiece — four to eight ticked is a second or two, fine on a thread and not on the
    one that repaints. `check` is whatever the panel handed the dialog (`check_sweeps` over its
    REW): this file knows nothing about REW. It is handed `stop`, the thread's own interruption
    flag, so a window that closes stops the pulls between two sweeps rather than after the last.
    """

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, check: Callable[..., dict], rows: list) -> None:
        super().__init__()
        self._check = check
        self._rows = list(rows)
        # Say who you were if you are destroyed before you finished (finding 35): Qt's own
        # fatal line names no class, and this app has eight kinds of worker.
        qt_shutdown.watch(self)

    def run(self) -> None:
        try:
            self.done.emit(dict(self._check(self._rows, stop=self.isInterruptionRequested) or {}))
        except Exception as exc:  # noqa: BLE001 — REW gone, a method that failed: said, not raised
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def legs_summary(legs) -> str:
    """`HP LR24 80 · LP —` for a row, `—` when nothing was in its chain."""
    if not legs:
        return "—"
    parts = []
    for kind, key in (("hp", "capImportHp"), ("lp", "capImportLp")):
        leg = legs.get(kind)
        if not leg:
            parts.append(f"{i18n.t(key)} —")
            continue
        value = leg.get("f")
        freq = f"{value:g}" if isinstance(value, (int, float)) else str(value or "?")
        parts.append(f"{i18n.t(key)} {leg.get('type') or ''}{leg.get('slope') or ''} {freq}")
    return " · ".join(parts)


class _NameDelegate(QStyledItemDelegate):
    """The new-name cell as a list of what the round still waits for, with room to type (F-056).

    A delegate over the cell's own item, not a widget beside it: the item stays the one place the
    name lives, so "Give names", a typed name and the clash check keep working on the item.
    """

    def __init__(self, dialog: "CaptureImportDialog") -> None:
        super().__init__(dialog)
        self._dialog = dialog

    def createEditor(self, parent, option, index):  # noqa: N802 — Qt's name
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.lineEdit().setPlaceholderText(i18n.t("capImportNamePick"))
        # Every choice lands at once: a persistent editor otherwise commits only when focus leaves.
        combo.activated.connect(lambda _index, c=combo: self.commitData.emit(c))
        combo.lineEdit().editingFinished.connect(lambda c=combo: self.commitData.emit(c))
        return combo

    def setEditorData(self, editor, index):  # noqa: N802
        editor.blockSignals(True)
        editor.clear()
        editor.addItems(self._dialog.name_choices(self._dialog.uuid_at(index.row())))
        editor.setCurrentText(str(index.data() or ""))
        editor.blockSignals(False)

    def setModelData(self, editor, model, index):  # noqa: N802
        text = editor.currentText().strip()
        if text != str(index.data() or ""):
            model.setData(index, text)


class _WholeCellDelegate(QStyledItemDelegate):
    """The check's answer gets its whole cell (tcc#21).

    A styled delegate puts a cell's widget inside the item's text rectangle — the cell minus the
    sheet's `::item` padding — while the column is sized to the widget itself, so the pair of
    answers came out cut by exactly that padding, at «Взяти як є».
    """

    def updateEditorGeometry(self, editor, option, index):  # noqa: N802 — Qt's name
        editor.setGeometry(option.rect)


class CaptureImportDialog(QDialog):
    """The list, the two filters over it, and Apply."""

    def __init__(
        self,
        measurements: dict,
        *,
        waiting: int = 0,
        expected: Optional[list] = None,
        round_id: str = "",
        has_task: bool = True,
        name_sets: Optional[dict] = None,
        project_dir: Optional[Path] = None,
        parent=None,
        save_order=None,
        check: Optional[Callable[..., dict]] = None,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(i18n.t("capImportTitle"))
        self.setMinimumWidth(640)
        # 80% of the main window (user, 2026-09-06). This is a table of a hundred rows that people
        # read and tick in; at its old size it opened showing eleven of them.
        sizing.fit_to_parent(self, 0.8)
        self._measurements = measurements or {}
        #: The names this round is still waiting for. The count alone used to be enough, because
        #: the tick was positional; the names are what makes it a match instead of a guess.
        self._expected = [str(name) for name in (expected or []) if str(name).strip()]
        self._waiting = int(waiting or 0) or len(self._expected)
        self._round_id = str(round_id or "")
        self._project_dir = project_dir
        self._pages = 0
        #: `{method: [(channel id, the full name a capture gets in REW)]}` — the round's own name
        #: sets, in the order the tuner declared. Built by the panel, which owns the sessions.
        self._name_sets = dict(name_sets or {})
        #: The panel's own writer for a declared capture order (`save_order(method, ids)`), handed
        #: to the order dialog so «Зберегти порядок» reaches the place the order is read from.
        self._save_order = save_order
        #: Proposed names, by uuid. Empty means "leave the title alone".
        self._names: dict[str, str] = {}
        #: `{uuid: {"hp": {f, type, slope}, "lp": {…}}}` — what was in each row's chain, as the
        #: Protection form's fields gave it. No entry means "read this curve as measured", which is
        #: not a claim that the chain was empty; see `core/protective.py`.
        self._legs: dict[str, dict] = {}
        #: What the last "Give names" or Apply had to say about the names themselves — a count that
        #: did not line up, or a clash. Cleared by the next successful fill.
        self._plan_note = ""
        #: Channels whose two rows described two different chains. Filled by `protective()`.
        self.protective_conflicts: list[str] = []
        #: The capture check (tcc#21): `check(rows, stop=…) -> {uuid: the method's verdict}`, run
        #: on a worker over the ticked sweeps. None — a test, or no panel to reach REW — checks nothing.
        self._check = check
        #: Every verdict this window has received, by uuid. A row is checked once per window; an
        #: empty verdict is "asked, nothing to say" (gone from REW, or the check could not run).
        self._verdicts: dict[str, dict] = {}
        #: The uuids the running worker is asking about; empty when none runs.
        self._checking: set[str] = set()
        self._check_worker: Optional[_SweepCheckWorker] = None
        #: Why the check could not run, said under the table; the import goes on regardless.
        self._check_error = ""
        #: Apply was pressed while sweeps were still being checked: it goes as soon as they are,
        #: unless one turns out unusable — then the window stays for the tuner to see it once.
        self._apply_waiting = False
        self._to_retake_at_apply: set[str] = set()
        #: How many times the check could not run; an Apply that waited through a new one stays.
        self._check_failures = 0
        self._failures_at_apply = 0
        self._closed = False

        self._all = capture_import.candidates(self._measurements, project_dir)
        #: Why a typed name is not in the naming grammar, in the method's words (hub #153 E).
        self._explain_name = capture_import.name_explainer(project_dir)
        #: Ticked by uuid rather than by row, because +10 and the filter both re-render the table
        #: underneath the tuner, and a tick that survives only until the next redraw is a tick
        #: nobody can trust.
        #:
        #: Opens on the measurements that already ANSWER TO a name the round is waiting for
        #: (`capture_import.preselect`, 2026-09-06). It used to open on the last N unprocessed
        #: rows, which is a positional guess: the ones worth taking are not always the newest, and
        #: on the user's own list they were not. With no round to be waiting for, nothing is
        #: pre-ticked: there is no batch to match against.
        picked = capture_import.preselect(self._all, self._expected, project_dir)
        self._ticked = set(picked.ticked)
        #: The New name opens with the name each ticked row was matched to, in the round's own
        #: spelling (finding 28) -- it was the one column left empty, and it is what the form is for.
        self._names.update(picked.names)
        #: Rows whose New name was found by matching, not already right — filled, NOT ticked:
        #: an automatic match is the Arbiter's to accept (A17, 2026-09-23).
        self._proposed = set(picked.proposed)
        #: How many the DIALOG ticked, kept apart from `_ticked`, which the tuner then edits. The
        #: line under the table is about what was decided for them, not about the running total.
        self._picked = len(picked.ticked)
        #: Rows that answer to an expected name TOGETHER with another row. Never pre-ticked, always
        #: on screen: which of two graphs with one name is the one that came out is the person's
        #: question, not a rule's.
        self._ambiguous = set(picked.ambiguous)
        #: Every uuid whose title is not unique in REW's current answer — marked in the row, so a
        #: tick on one of a pair is made knowing there is a pair.
        self._repeated = capture_import.repeated_titles(self._all)
        #: The same pairs by NAME, for the line under the table: the mark says "there is a pair",
        #: this says what it costs — the curve window and the method read by title (tcc#94).
        self._dup_titles = capture_import.duplicate_titles(self._measurements)
        #: The table is scrolled to the first pre-ticked row ONCE, when it opens. Re-rendering
        #: (a filter, +10, a typed name) must not yank the view back while somebody is working.
        self._scrolled_to_pick = False
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

        self._table = QTableWidget(0, 7)
        self._table.setProperty("class", "ptable")
        self._table.setHorizontalHeaderLabels(
            [i18n.t("capImportColTake"), i18n.t("capImportColNum"), i18n.t("capImportColTitle"),
             i18n.t("capImportColWhen"), i18n.t("capImportColName"), i18n.t("capImportColProt"),
             i18n.t("capImportColCheck")])
        # Only the name column is typed into; `_render` gives exactly that column the flag.
        self._table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked
                                    | QTableWidget.EditTrigger.EditKeyPressed
                                    | QTableWidget.EditTrigger.AnyKeyPressed)
        self._table.setItemDelegateForColumn(_COL_NAME, _NameDelegate(self))
        self._table.setItemDelegateForColumn(_COL_CHECK, _WholeCellDelegate(self))
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_TAKE, QHeaderView.ResizeMode.ResizeToContents)
        # REW's own number, for finding the row in REW's window and nothing else — see
        # `_render_note` for why it is never written down.
        header.setSectionResizeMode(_COL_NUM, QHeaderView.ResizeMode.ResizeToContents)
        # Title, date and name are dragged to the width the person needs (finding 28: the REW
        # title and the timestamp squeezed the name). The last column takes what is left.
        # The date sits BESIDE the proposed name on purpose: they are read together. A re-take
        # lands out of time order, and the name about to be written on it is the thing that goes
        # wrong when it does.
        for column, width in ((_COL_TITLE, 240), (_COL_WHEN, 170), (_COL_NAME, 220)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(column, width)
        header.setSectionResizeMode(_COL_PROT, QHeaderView.ResizeMode.Stretch)
        # The check's answer sits right after the title it is about: "this one, re-take it" is
        # read off one place. Shown there, numbered last — `_COL_CHECK` says why.
        header.setSectionResizeMode(_COL_CHECK, QHeaderView.ResizeMode.ResizeToContents)
        header.moveSection(header.visualIndex(_COL_CHECK), header.visualIndex(_COL_WHEN))
        apply_caps(header, spacing_px=0.7)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.cellActivated.connect(self._on_cell_clicked)
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
        # The rows to untick are usually all but two (finding 28): one click for all, one for none.
        self._select_all_btn = QPushButton(i18n.t("capImportSelectAll"))
        self._select_all_btn.setProperty("class", "reason-btn")
        self._select_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_all_btn.clicked.connect(lambda: self._tick_all(True))
        controls.addWidget(self._select_all_btn)
        self._clear_btn = QPushButton(i18n.t("capImportSelectNone"))
        self._clear_btn.setProperty("class", "reason-btn")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(lambda: self._tick_all(False))
        controls.addWidget(self._clear_btn)
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

        Whatever was ticked by name comes along wherever it sits (`keep`): a row this dialog has
        decided for the person has to be a row the person can see. So does a sweep the check left
        out for a re-take (tcc#21): unticked by the check, it would otherwise drop out of the
        window it was only in because it was ticked, and take its «Take it as it is» with it.
        """
        rows = self._all if not self._only_new.isChecked() else capture_import.unprocessed(self._all)
        keep = (self._ticked | self._ambiguous | self._to_retake()) & {row.uuid for row in rows}
        return capture_import.window(rows, self._waiting, self._pages, keep=keep)

    def ticked_rows(self) -> list[capture_import.Candidate]:
        return [row for row in self._all if row.uuid in self._ticked and row.identified]

    def uuid_at(self, row: int) -> str:
        """The uuid of the measurement on table row `row`, or ""."""
        take = self._table.item(row, _COL_TAKE)
        return str(take.data(_UUID) or "") if take is not None else ""

    def set_legs(self, uuid: str, legs) -> None:
        """What was in this row's chain: a `{hp, lp}` dict, or None for "read it as measured"."""
        if legs:
            self._legs[uuid] = dict(legs)
            # A record nobody takes in is none — but a row the check left out for a re-take is
            # answered with its own buttons, not by entering its chain (tcc#21, review M1).
            if uuid not in self._to_retake():
                self._ticked.add(uuid)
        else:
            self._legs.pop(uuid, None)
        self._render()

    def name_choices(self, uuid: str) -> list[str]:
        """What the round still waits for, minus the names other rows have already chosen."""
        chosen_elsewhere = {name for other, name in self._names.items() if other != uuid}
        return [name for name in self._expected if name not in chosen_elsewhere]

    def _refresh_name_lists(self) -> None:
        """Re-offer every row's list once a name was chosen or cleared somewhere else."""
        delegate = self._table.itemDelegateForColumn(_COL_NAME)
        for row in range(self._table.rowCount()):
            index = self._table.model().index(row, _COL_NAME)
            editor = self._table.indexWidget(index)
            if editor is not None:
                delegate.setEditorData(editor, index)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        """The protective cell opens the Protection form's own fields for this one row (F-056)."""
        if column != _COL_PROT:
            return
        uuid = self.uuid_at(row)
        if not any(candidate.uuid == uuid and candidate.identified for candidate in self._all):
            return
        form = ProtectiveLegsDialog(self._legs.get(uuid), parent=self)
        if form.exec() == QDialog.DialogCode.Accepted:
            self.set_legs(uuid, form.legs())

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
            self._table.setItem(index, _COL_TAKE, take)

            # REW's number as REW is showing it NOW. Navigation only: it is the index of a view
            # (a filter renumbers it, a drag moves it), so nothing here stores or resolves by it.
            number = QTableWidgetItem(row.ordinal)
            number.setFlags(Qt.ItemFlag.ItemIsEnabled)
            number.setToolTip(i18n.t("capImportNumTip"))
            self._table.setItem(index, _COL_NUM, number)

            title = QTableWidgetItem(row.title)
            if row.imported:
                # Shown only because the tuner asked to see them; saying WHY beats a row that
                # looks the same as the ones being offered.
                title.setToolTip(i18n.t("capImportAlready"))
            if row.uuid in self._repeated:
                # Two graphs, one name. Marked rather than resolved: REW holds both, and which one
                # came out is the person's call (user, 2026-09-06).
                title.setText(f"{row.title} ⧉")
                title.setToolTip(i18n.t("capImportDupTip"))
            elif row.uuid in self._proposed and row.uuid not in self._ticked:
                # Its New name was matched, not typed: said, and left for a conscious tick.
                title.setText(f"{row.title}  ≈")
                title.setToolTip(i18n.t("capImportProposed"))
            self._table.setItem(index, _COL_TITLE, title)

            # REW's own string, verbatim. It is a display date formatted by REW's locale, and
            # printing our own reformatting of something we could not fully parse would be
            # inventing precision.
            when = QTableWidgetItem(row.date)
            if row.uuid in self._retakes:
                when.setText(f"↻ {row.date}")
                when.setToolTip(i18n.t("capImportRetake"))
            self._table.setItem(index, _COL_WHEN, when)

            name = QTableWidgetItem(self._names.get(row.uuid, ""))
            if row.identified:
                name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
                              | Qt.ItemFlag.ItemIsSelectable)
            else:
                name.setFlags(Qt.ItemFlag.ItemIsEnabled)
                name.setToolTip(i18n.t("capImportNoUuid"))
            self._table.setItem(index, _COL_NAME, name)
            if row.identified:
                self._table.openPersistentEditor(name)

            # What was in the chain, as one line; a click opens the Protection form's own fields
            # for this row (F-056, the Arbiter 2026-09-16 — it used to be two typed frequencies).
            prot = QTableWidgetItem(legs_summary(self._legs.get(row.uuid)))
            prot.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            prot.setToolTip(i18n.t("capImportProtTip") if row.identified
                            else i18n.t("capImportNoUuid"))
            self._table.setItem(index, _COL_PROT, prot)
            self._render_check(index, row)
        self._table.blockSignals(False)
        self._fit_check_column()
        self._render_note(len(rows))
        self._scroll_to_pick(rows)
        self._schedule_check()

    # ---- the capture check (tcc#21) ----------------------------------------------------------

    def _render_check(self, index: int, row: capture_import.Candidate) -> None:
        """What the check said about one row: nothing yet, checking, fine, or unusable."""
        self._table.removeCellWidget(index, _COL_CHECK)
        cell = QTableWidgetItem("")
        cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
        verdict = self._verdicts.get(row.uuid)
        if row.as_is:
            # Answered on an earlier import and remembered by its uuid: not asked again.
            cell.setText(i18n.t("capCheckAsIsDone"))
            cell.setToolTip(i18n.t("capCheckAsIsTip"))
        elif row.uuid in self._checking:
            cell.setText(i18n.t("capCheckRunning"))
        elif capture_import.unusable(verdict):
            self._table.setItem(index, _COL_CHECK, cell)
            self._table.setCellWidget(index, _COL_CHECK, self._answer(row.uuid, verdict))
            return
        elif verdict and verdict.get("valid"):
            cell.setText("✓")
            cell.setToolTip(i18n.t("capCheckOkTip"))
        self._table.setItem(index, _COL_CHECK, cell)

    def _answer(self, uuid: str, verdict: dict) -> QWidget:
        """The red mark, the method's reasons on its hover, and the two answers beside it.

        The pair is the row's tick seen from the check's side: «Re-take» is unticked, «Take it as it
        is» is ticked. One decision in two places, so neither can say something the other does not.
        """
        box = QWidget()
        line = QHBoxLayout(box)
        line.setContentsMargins(4, 0, 4, 0)
        line.setSpacing(6)
        # The card's own dot for «taken, unusable» (`measurement_panel.TrafficLight("bad")`), by
        # its class: the panel imports this dialog, so the widget cannot come the other way.
        mark = QLabel()
        mark.setProperty("class", "tl tl-bad")
        mark.setFixedSize(9, 9)
        line.addWidget(mark)
        taken = uuid in self._ticked
        for key, take in (("capCheckRetake", False), ("capCheckAsIs", True)):
            button = QPushButton(i18n.t(key))
            button.setProperty("class", "reason-btn cap-answer")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setCheckable(True)
            button.setChecked(taken == take)
            sizing.fit_to_text(button)
            attach_tip(button, i18n.t(f"{key}Tip"))
            button.clicked.connect(lambda _on=False, u=uuid, t=take: self._choose(u, t))
            line.addWidget(button)
        # The method's own words, not a paraphrase: "no clear arrival" and "covers 200-2000 Hz"
        # lead to different things done at the car (`main_window._on_capture_check_done`).
        reasons = "<br>".join(escape(str(issue)) for issue in verdict.get("issues") or [])
        said = f"{escape(i18n.t('capCheckBadTip'))}<br>{reasons}"
        attach_tip(box, said)
        attach_tip(mark, said)
        return box

    def _choose(self, uuid: str, take: bool) -> None:
        """«Re-take» or «Take it as it is» for one unusable sweep."""
        if take:
            self._ticked.add(uuid)
        else:
            self._ticked.discard(uuid)
        # Deferred: this runs inside the button's own click, and the refresh replaces the button.
        QTimer.singleShot(0, self, self._refresh_checks)

    def _refresh_checks(self) -> None:
        """Ticks and check cells redrawn in place. Not `_render`: that rebuilds the name editors,
        and a verdict arriving while somebody types a name must not take the typing with it."""
        by_uuid = {row.uuid: row for row in self._all}
        self._table.blockSignals(True)
        for index in range(self._table.rowCount()):
            row = by_uuid.get(self.uuid_at(index))
            if row is None:
                continue
            take = self._table.item(index, _COL_TAKE)
            if take is not None and row.identified:
                take.setCheckState(Qt.CheckState.Checked if row.uuid in self._ticked
                                   else Qt.CheckState.Unchecked)
            self._render_check(index, row)
        self._table.blockSignals(False)
        self._fit_check_column()
        self._render_note(self._table.rowCount())

    def _fit_check_column(self) -> None:
        """The check's column to the answer it now holds. A widget put in a cell after the header
        last sized its sections is not counted until it is asked again, and the pair of answers came
        out cut at «Взяти як є»."""
        self._table.horizontalHeader().resizeSections()

    def _unchecked(self) -> list[capture_import.Candidate]:
        """Ticked sweeps the check has not answered for yet — the SELECTED ones only (the Arbiter,
        2026-10-02): a verdict per listed row is an FR and an impulse for rows nobody chose."""
        if self._check is None:
            return []
        return [row for row in capture_import.to_check(self.ticked_rows())
                if row.uuid not in self._verdicts]

    def checking(self) -> bool:
        """Whether a ticked sweep is still waiting for its verdict."""
        return bool(self._checking) or bool(self._unchecked())

    def _to_retake(self) -> set[str]:
        """Unusable sweeps left out — the ones to re-take."""
        return {row.uuid for row in self._all if row.uuid not in self._ticked
                and capture_import.unusable(self._verdicts.get(row.uuid))}

    def _schedule_check(self) -> None:
        if self._check is not None:
            # Deferred, so a burst of ticks is one batch and the window is on screen first.
            # Bound to this dialog, so a timer outliving a closed window does nothing.
            QTimer.singleShot(0, self, self._check_selected)

    def _check_selected(self) -> None:
        """Start the worker on the ticked sweeps that have no verdict yet; one worker at a time,
        and whatever was ticked while it ran is taken up when it answers."""
        if self._closed or self._checking:
            return
        rows = self._unchecked()
        if not rows:
            return
        self._checking = {row.uuid for row in rows}
        worker = _SweepCheckWorker(self._check, rows)
        worker.done.connect(self._on_checked)
        worker.failed.connect(self._on_check_failed)
        self._check_worker = worker
        worker.start()
        self._refresh_checks()

    def _on_checked(self, verdicts: dict) -> None:
        if self._closed:
            return  # queued before `done()` cut the line: the window's answer is already given
        asked, self._checking = self._checking, set()
        for uuid in asked:
            verdict = dict(verdicts.get(uuid) or {})
            self._verdicts[uuid] = verdict
            if capture_import.unusable(verdict):
                # The recommendation, applied where it can be seen: a re-take, so not taken —
                # one click on «Take it as it is» takes it (the Arbiter, 2026-10-02).
                self._ticked.discard(uuid)
        self._refresh_checks()
        self._check_selected()
        self._resolve_wait()

    def _on_check_failed(self, error: str) -> None:
        if self._closed:
            return
        asked, self._checking = self._checking, set()
        for uuid in asked:
            self._verdicts[uuid] = {}  # not checked: no mark, and not asked again in this window
        self._check_error = error
        self._check_failures += 1
        self._refresh_checks()
        self._check_selected()
        self._resolve_wait()

    def _resolve_wait(self) -> None:
        """An Apply that waited for the check goes now — unless the check left a new sweep out."""
        if not self._apply_waiting or self.checking():
            return
        self._apply_waiting = False
        if (self._to_retake() - self._to_retake_at_apply
                or self._check_failures > self._failures_at_apply):
            # The window stays, once: the mark and the line under the table say what to re-take
            # — or that the sweeps were NOT checked, which a closed window would say to nobody
            # (review M2). The next Apply goes whatever is chosen.
            self._render_note(self._table.rowCount())
            return
        self._on_apply()

    def done(self, result: int) -> None:  # noqa: N802 — Qt's name; Apply and Cancel both end here
        """A check still running is told to stop and let go rather than waited on: it only reads,
        and the Apply that closed the window must not freeze it. `qt_shutdown` holds the thread
        until it ends, and a verdict already queued is dropped on arrival (`_closed`)."""
        self._closed = True
        self._apply_waiting = False
        worker = self._check_worker
        if worker is not None:
            for signal in (worker.done, worker.failed):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):  # nothing connected any more
                    pass
            qt_shutdown.stop_or_detach(worker, 0)
        super().done(result)

    def _scroll_to_pick(self, rows: list) -> None:
        """Put the first pre-ticked row in view, once, when the dialog opens.

        A tick nobody scrolled to is a decision made off screen — and the whole reason the tick is
        by name rather than by position is that the right rows can be anywhere in the list.
        """
        if self._scrolled_to_pick:
            return
        picked = self._ticked | self._ambiguous
        index = next((i for i, row in enumerate(rows) if row.uuid in picked), None)
        if index is None:
            return
        item = self._table.item(index, _COL_TITLE)
        if item is not None:
            self._table.scrollToItem(item, QTableWidget.ScrollHint.PositionAtCenter)
        self._scrolled_to_pick = True

    def _render_note(self, shown: int) -> None:
        lines = [self._plan_note] if self._plan_note else []
        to_retake = self._to_retake()
        retakes = sorted({row.title for row in self._all if row.uuid in to_retake})
        if retakes:
            # What to re-take, by name, while the microphone is still in place (tcc#21's title).
            lines.append(i18n.t("capCheckRetakeList").format(names=", ".join(retakes)))
        if self._apply_waiting:
            lines.append(i18n.t("capCheckWaiting"))
        if self._check_error:
            lines.append(i18n.t("capCheckFailed").format(error=self._check_error))
        if self._dup_titles:
            # Said, never resolved: which of the two is meant is the tuner's to settle in REW (the
            # Arbiter, 2026-10-02 — a pair is not to be addressed by uuid, tcc#94).
            lines.append(i18n.t("capImportDupWarn").format(names=", ".join(self._dup_titles)))
        lines.append(i18n.t("capImportShowing"))
        if self._picked:
            lines.append(i18n.t("capImportPicked").format(n=self._picked))
        if self._ambiguous:
            # Named, not counted: the person is about to choose between rows that read alike, and
            # the name is what tells them which pair they are looking at.
            # A title the warning above already names is not named again (tcc#94): what is left
            # here is two spellings the grammar reads alike, which the warning never holds. Why
            # neither of a same-title pair is ticked is the ⧉ mark's hover.
            names = [name for name in sorted({row.title for row in self._all
                                              if row.uuid in self._ambiguous})
                     if name not in self._dup_titles]
            if names:
                lines.append(i18n.t("capImportDupNote").format(names=", ".join(names)))
        if not capture_import.ordered_by_date(self._all) and self._all:
            lines.append(i18n.t("capImportRewOrder"))
        missing = capture_import.missing_imported(self._measurements, self._project_dir)
        if missing:
            lines.append(i18n.t("capImportMissing").format(n=len(missing)))
        if not shown:
            lines.append(i18n.t("capImportEmpty"))
        # A name the analysis will never find by its title, said when it is typed (hub #153 E) —
        # not refused: an extra measurement may be named on purpose, and the person may know better.
        for name in sorted(set(self._names.values())):
            why = self._explain_name(name)
            if why:
                lines.append(i18n.t("capImportOffGrammar").format(name=name, why=why))
        self._note.setText(" ".join(lines))
        self._more_btn.setEnabled(len(self.visible_rows()) < len(self._all))

    # ---- what the tuner does -------------------------------------------------------------

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        row = item.row()
        take = self._table.item(row, _COL_TAKE)
        uuid = str(take.data(_UUID) or "") if take is not None else ""
        if not uuid:
            return
        if item.column() == _COL_TAKE:
            if item.checkState() == Qt.CheckState.Checked:
                self._ticked.add(uuid)
            else:
                self._ticked.discard(uuid)
            # On a row the check marked, the tick IS the answer: ticked is «Take it as it is»,
            # unticked «Re-take» (tcc#21). Deferred, as the editors' refresh below is.
            QTimer.singleShot(0, self, self._refresh_checks)
            self._schedule_check()
        elif item.column() == _COL_NAME:
            typed = item.text().strip()
            if typed:
                self._names[uuid] = typed
                # Typing a name is asking for that measurement, so it stops being unticked by
                # accident: a rename nobody takes in is a rename for nothing. Not a row the check
                # left out for a re-take: taking that one is «Take it as it is», given with its own
                # button and seen, as «Give names» and «Select all» already leave it (tcc#21, I1).
                if uuid not in self._to_retake():
                    self._ticked.add(uuid)
            else:
                self._names.pop(uuid, None)
            # Deferred: this runs inside the editor's own commit, and repopulating that editor
            # while it is still emitting is not something to do under Qt.
            # Bound to this dialog, so a timer outliving a closed window does nothing.
            QTimer.singleShot(0, self, self._refresh_name_lists)
            # The tick a name gives is shown in the tick box, and the sweep it took is checked
            # like any ticked one (tcc#21, I2): it was neither, and Apply then waited on nothing.
            QTimer.singleShot(0, self, self._refresh_checks)
            self._schedule_check()
            self._render_note(self._table.rowCount())

    def _on_give_names(self) -> None:
        """Fill names downwards from the selected row, out of a set the tuner picks.

        The set and the order are `ChannelOrderDialog`'s, unchanged — it already asks exactly the
        two questions this needs ("which capture method" and "in what order do you sweep"), and it
        already remembers the answer per preset. What moved is where it is asked FROM: it used to
        be a button on the card that then guessed which REW measurements were "the newest batch"
        by their ordinals. That guess is what the measurements of 2026-09-02 disproved.
        """
        picker = ChannelOrderDialog(self._name_sets, parent=self, save_order=self._save_order)
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
        to_retake = self._to_retake()
        for uuid, name in plan.pairs:
            self._names[uuid] = name
            if uuid not in to_retake:  # a red row is answered on its own (tcc#21)
                self._ticked.add(uuid)
        self._plan_note = "" if plan.lines_up else i18n.t("capImportUneven").format(
            rows=len(plan.unnamed), names=len(plan.leftover))
        self._render()

    def renames(self) -> list[tuple[str, str]]:
        """`(uuid, new title)` for every ticked row that is actually being renamed."""
        return [(row.uuid, self._names[row.uuid]) for row in self.ticked_rows()
                if self._names.get(row.uuid) and self._names[row.uuid] != row.title]

    def _tick_all(self, on: bool) -> None:
        """Tick every row on screen that can be taken, or untick everything.

        Not the rows the check left out for a re-take: taking one of those is an answer the tuner
        gives that row by name, not a side effect of «Select all» (tcc#21)."""
        if on:
            retakes = self._to_retake()
            self._ticked |= {row.uuid for row in self.visible_rows()
                             if row.identified and row.uuid not in retakes}
        else:
            self._ticked.clear()
        self._render()

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
        if self.checking() and not self._apply_waiting:
            # Opened and applied at once is the common way through, and it must not walk past
            # the check that is the point of #21. So the first Apply waits for the verdicts and
            # goes by itself when they are in; a second one goes now. Never refused.
            self._apply_waiting = True
            self._to_retake_at_apply = self._to_retake()
            self._failures_at_apply = self._check_failures
            # And starts the check itself, so a wait always has a worker behind it, whichever
            # door ticked the row (review I2). A check already running is left to finish.
            self._check_selected()
            self._render_note(self._table.rowCount())
            return
        self._apply_waiting = False
        self.accept()

    def taken(self) -> list[capture_import.Candidate]:
        """What the panel should write down once whatever renaming there is has happened.

        A sweep the check called unusable and the tuner took anyway goes as `as_is`, so the store
        remembers that answer for that capture (tcc#21, `record_imported`)."""
        return [replace(row, as_is=True) if capture_import.unusable(self._verdicts.get(row.uuid))
                else row for row in self.ticked_rows()]

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
            legs = self._legs.get(row.uuid)
            if not legs:
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
