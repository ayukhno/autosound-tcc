"""The right-panel "IN FOCUS NOW" measurement-task card — ported from the prototype's
`renderMeas` (`data/private/prototype/tcc-main.html`): a yellow-accented card with the current
capture-series version, a wait/done/bad legend, and a 3-column grid of per-channel status rows.

Mock data only (`ui/tcc/mock_data.py`). The real data source is the REW `/measurements`
cross-reference against the expected channel list for a stage — the same check done manually
earlier this session — wiring that in is separate, later work (see the plan file's M4 note).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.mock_data import MEAS

_LEGEND = (("wait", "waiting"), ("done", "done"), ("bad", "taken, unusable"))


class _TrafficLight(QLabel):
    def __init__(self, status: str) -> None:
        super().__init__()
        self.setProperty("class", f"tl tl-{status}")
        self.setFixedSize(9, 9)


class _MeasRow(QWidget):
    def __init__(self, item) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(6)
        layout.addWidget(_TrafficLight(item.status))
        text = item.name + (f" ({item.count})" if item.count else "")
        name = QLabel(text)
        name.setProperty("class", f"mn mn-{item.status}")
        layout.addWidget(name)
        layout.addStretch(1)


class MeasurementPanel(QWidget):
    """The card's own yellow-tinted border is applied by the caller to the enclosing `.panel`
    frame (main_window.py) — this widget is just the content that goes inside it."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        self._version = QLabel(i18n.tx(MEAS.version))
        self._version.setProperty("class", "meas-head")
        layout.addWidget(self._version)

        legend = QWidget()
        legend_layout = QHBoxLayout(legend)
        legend_layout.setContentsMargins(0, 0, 0, 0)
        legend_layout.setSpacing(10)
        for status, label in _LEGEND:
            dot = _TrafficLight(status)
            text = QLabel(label)
            text.setProperty("class", "meas-legend-label")
            legend_layout.addWidget(dot)
            legend_layout.addWidget(text)
        legend_layout.addStretch(1)
        layout.addWidget(legend)

        cols = QGridLayout()
        cols.setHorizontalSpacing(8)
        cols.setVerticalSpacing(2)
        for c, group in enumerate(MEAS.groups):
            header = QLabel(group.type)
            header.setProperty("class", "mcol-h")
            cols.addWidget(header, 0, c)
            for r, item in enumerate(group.items, start=1):
                cols.addWidget(_MeasRow(item), r, c)
        layout.addLayout(cols)

    def retranslate(self) -> None:
        self._version.setText(i18n.tx(MEAS.version))
