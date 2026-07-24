"""The main TCC window.

An empty placeholder for now — no REW/DSP data is displayed yet. This proves
the window opens; wiring `rew_bridge` / `dsp_state` into it is the next
milestone.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow

from autosound_tcc import __version__


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("autosound-tcc — Tuning Command Center")
        self.resize(960, 640)

        placeholder = QLabel(
            "Tuning Command Center\n"
            f"read-only scaffold v{__version__}\n\n"
            "REW / DSP data wiring comes next."
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(placeholder)
