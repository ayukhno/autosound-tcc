"""Read-only OUTPUT-channels table — physical drivers, "state at a glance".

One row per output driver: role, high-pass, low-pass, gain, delay (ms + derived
samples), polarity, EQ summary. Data comes from a `DspSnapshot`; nothing writes.
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

from autosound_tcc.state.dsp_state import ChannelState, DspSnapshot

_COLUMNS = ["Channel", "Role", "High-pass", "Low-pass", "Gain dB", "Delay ms", "Samples", "Polarity", "EQ"]
_NUMERIC = {4, 5, 6}


class ChannelsTable(QTableWidget):
    def __init__(self) -> None:
        super().__init__(0, len(_COLUMNS))
        self.setHorizontalHeaderLabels(_COLUMNS)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # read-only
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def set_snapshot(self, snapshot: DspSnapshot) -> None:
        channels = snapshot.channels_ordered()
        self.setRowCount(len(channels))
        for row, ch in enumerate(channels):
            values = [
                ch.name,
                ch.role or "—",
                ch.hp.label,
                ch.lp.label,
                f"{ch.gain_db:+.1f}",
                f"{ch.ta_ms:.2f}",
                str(snapshot.samples_for(ch.ta_ms)),
                ch.polarity,
                _eq_summary(ch),
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    (Qt.AlignmentFlag.AlignRight if col in _NUMERIC else Qt.AlignmentFlag.AlignCenter)
                    | Qt.AlignmentFlag.AlignVCenter
                )
                _tint(item, col, ch)
                if col == 8 and ch.eq:
                    item.setToolTip("\n".join(ch.eq))
                if ch.note:
                    item.setToolTip((item.toolTip() + "\n" if item.toolTip() else "") + ch.note)
                self.setItem(row, col, item)

    def clear_snapshot(self) -> None:
        self.setRowCount(0)


def _eq_summary(ch: ChannelState) -> str:
    parts = []
    if ch.eq:
        parts.append(f"{len(ch.eq)} PEQ")
    if ch.apf:
        parts.append("APF")
    return " · ".join(parts) if parts else "—"


def _tint(item: QTableWidgetItem, col: int, ch: ChannelState) -> None:
    """Subtle cues: inverted polarity and disabled legs stand out."""
    if col == 7 and ch.polarity == "INV":
        item.setForeground(QColor("#c76a00"))
    if col in (2, 3):
        leg = ch.hp if col == 2 else ch.lp
        if not leg.enabled:
            item.setForeground(QColor("#999999"))
