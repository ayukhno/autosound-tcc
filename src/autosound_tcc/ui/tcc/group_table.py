"""Generic, profile-driven table for one DSP-profile group.

Deliberately NOT a bespoke column-per-field layout (that's what the old, retired
`ChannelsTable`/`VirtualChannelsTable` did, hardcoded to Helix's shape). A group's declared
`fields` vary by DSP and by tier (a Helix `physical_outputs` row has hp/lp/gain/delay/pol/eq; a
MUSWAY `inputs` row has just gain/eq/delay, no crossover at all) — rather than inventing a
column-schema language, each row renders its declared fields as "label: value" chips in one
wrapped column. Less visually polished than a bespoke layout; the tradeoff accepted for v1 so
zero new Qt code is needed per DSP (see docs/TCC-TZ.md §2, plan: dsp-profile-onboarding).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

from autosound_tcc.state.dsp_state import ProfileGroup

_COLUMNS = ["ID", "Channel", "Params"]


class GroupTable(QTableWidget):
    def __init__(self) -> None:
        super().__init__(0, len(_COLUMNS))
        self.setHorizontalHeaderLabels(_COLUMNS)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # read-only
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

    def set_group(self, group: ProfileGroup) -> None:
        rows = group.rows_ordered()
        self.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            params = row.params(group.fields)
            values = [row.id, row.name, "  ·  ".join(params) if params else "—"]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    (Qt.AlignmentFlag.AlignCenter if col == 0 else Qt.AlignmentFlag.AlignLeft)
                    | Qt.AlignmentFlag.AlignVCenter
                )
                if col == 2:
                    item.setToolTip(text)
                self.setItem(row_idx, col, item)

    def clear_group(self) -> None:
        self.setRowCount(0)
