"""Read-only VIRTUAL-channels table — the input-side voicing / matrix stage.

One row per virtual channel: role, crossover (if any), level, delay, polarity,
voicing EQ, and routing/feed. Looser than the output table — many cells are "—"
because a virtual channel may be full-range or carry only a state (e.g. FX on).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

from autosound_tcc.state.dsp_state import DspSnapshot, VirtualChannel

_COLUMNS = ["Virtual", "Role", "High-pass", "Low-pass", "Level dB", "Delay ms", "Polarity", "Voicing EQ", "Feed / routing"]
_NUMERIC = {4, 5}


class VirtualChannelsTable(QTableWidget):
    def __init__(self) -> None:
        super().__init__(0, len(_COLUMNS))
        self.setHorizontalHeaderLabels(_COLUMNS)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # read-only
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)

    def set_snapshot(self, snapshot: DspSnapshot) -> None:
        virtuals = snapshot.virtual_ordered()
        self.setRowCount(len(virtuals))
        for row, vc in enumerate(virtuals):
            values = [
                vc.name,
                vc.role or "—",
                vc.hp.label,
                vc.lp.label,
                f"{vc.level_db:+.1f}" if vc.level_db is not None else "—",
                f"{vc.ta_ms:.2f}" if vc.ta_ms is not None else "—",
                vc.polarity or "—",
                " · ".join(vc.eq) if vc.eq else "—",
                vc.feed or "—",
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    (Qt.AlignmentFlag.AlignRight if col in _NUMERIC else Qt.AlignmentFlag.AlignLeft
                     if col in (7, 8) else Qt.AlignmentFlag.AlignCenter)
                    | Qt.AlignmentFlag.AlignVCenter
                )
                if col == 6 and vc.polarity == "INV":
                    item.setForeground(QColor("#c76a00"))
                if not vc.active:
                    item.setForeground(QColor("#999999"))
                self.setItem(row, col, item)

    def clear_snapshot(self) -> None:
        self.setRowCount(0)


__all__ = ["VirtualChannelsTable"]
