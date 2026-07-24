"""The main TCC window.

Two read-only panels fed from the project-local DSP ledger: the OUTPUT drivers
and the VIRTUAL (input-side voicing) channels — the two tiers of the Helix
signal path. REW curve panels come in a later milestone. Nothing here writes to
the DSP — read-only by design (brief §11).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc import __version__
from autosound_tcc.core import config
from autosound_tcc.state.dsp_state import DspSnapshot, load_snapshot
from autosound_tcc.ui.tcc.channels_table import ChannelsTable
from autosound_tcc.ui.tcc.virtual_table import VirtualChannelsTable


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight: 600; margin-top: 6px;")
    return label


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("autosound-tcc — Tuning Command Center")
        self.resize(1040, 720)

        self._header = QLabel()
        self._header.setTextFormat(Qt.TextFormat.RichText)
        self._virtual_table = VirtualChannelsTable()
        self._output_table = ChannelsTable()
        self._status = QLabel()
        self._status.setStyleSheet("color: #888;")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        layout.addWidget(self._header)
        layout.addWidget(_section_label("Virtual channels (input-side voicing)"))
        layout.addWidget(self._virtual_table, stretch=2)
        layout.addWidget(_section_label("Output channels (physical drivers)"))
        layout.addWidget(self._output_table, stretch=3)
        layout.addWidget(self._status)
        self.setCentralWidget(central)

        self._load()

    def _load(self) -> None:
        root = config.state_root()
        preset = config.resolve_preset(root)
        if preset is None:
            self._show_empty(root)
            return
        try:
            snapshot = load_snapshot(str(root), preset)
        except Exception as exc:  # missing/broken ledger — degrade, don't crash
            self._show_error(preset, exc)
            return
        self._show_snapshot(snapshot)

    def _show_snapshot(self, snapshot: DspSnapshot) -> None:
        self._virtual_table.set_snapshot(snapshot)
        self._output_table.set_snapshot(snapshot)
        sr_khz = snapshot.sample_rate / 1000
        self._header.setText(
            f"<b>Preset:</b> {snapshot.preset} &nbsp;&nbsp; "
            f"<b>Sample rate:</b> {sr_khz:g} kHz &nbsp;&nbsp; "
            f"<b>Version:</b> {snapshot.version or '—'}"
        )
        note = f" — {snapshot.note}" if snapshot.note else ""
        self._status.setText(
            f"{len(snapshot.virtual_channels)} virtual · {len(snapshot.channels)} output "
            f"channels · read-only view v{__version__}{note}"
        )

    def _show_empty(self, root) -> None:
        self._virtual_table.clear_snapshot()
        self._output_table.clear_snapshot()
        self._header.setText("<b>No DSP snapshot found</b>")
        self._status.setText(
            f"Looked in {root}. Set AUTOSOUND_TCC_STATE_ROOT / AUTOSOUND_TCC_PRESET "
            f"to point at a project ledger."
        )

    def _show_error(self, preset: str, exc: Exception) -> None:
        self._virtual_table.clear_snapshot()
        self._output_table.clear_snapshot()
        self._header.setText(f"<b>Could not load preset</b> {preset}")
        self._status.setText(f"{type(exc).__name__}: {exc}")
