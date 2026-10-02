"""A turning wheel for a wait nobody can time — the reviewer's check (finding 142, tcc#140).

The window had none to reuse: the splash's "spinner" is the system's busy cursor over a window not
painted yet, and the diagnostics panel's old export one was a number box. A wait is shown elsewhere
as a count («asked 4 s ago») or as moving dots; beside the footer's «!» there is room for neither,
and the Arbiter asked for a wheel: «на місці чи поруч зі знаком питання крутити колесико поки іде
перевірка».

Painted, not styled: it reads the theme it is drawn in (`current_theme`), so a theme switch moves
it with the rest, as the DSP tree's status dots do.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from autosound_tcc.ui.tcc.theme import current_theme

#: The «!» it stands beside is 18 px square; the wheel is the same, so the row does not jump.
_SIZE = 18
#: Twelve steps a turn, a turn a second: moving enough to read as "still going" from the corner
#: of an eye, slow enough not to pull the eye to the footer.
_STEP_MS = 80
_STEP_DEG = 30
#: How much of the ring the turning arc covers; the rest is a faint track.
_ARC_DEG = 270


class Spinner(QWidget):
    """Hidden until `start`; `stop` hides it again. Its tip is the owner's (`rounded_tooltip`)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_SIZE, _SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(_STEP_MS)
        self._timer.timeout.connect(self._turn)
        self.setHidden(True)

    def start(self) -> None:
        self.setHidden(False)
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.setHidden(True)

    def is_spinning(self) -> bool:
        return self._timer.isActive()

    def interval_ms(self) -> int:
        return self._timer.interval()

    def _turn(self) -> None:
        self._angle = (self._angle + _STEP_DEG) % 360
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Inside by the pen's width: the stroke is centred on the ring, and its outer half would
        # be clipped at the widget's edge.
        ring = QRectF(2, 2, self.width() - 4, self.height() - 4)
        pen = QPen(QColor(theme.border2))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.drawEllipse(ring)
        # The Critic's own blue (`info` colours its bubble), on the track. Qt counts sixteenths of
        # a degree, anticlockwise from three o'clock: a falling start turns it clockwise.
        pen.setColor(QColor(theme.info))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(ring, -self._angle * 16, _ARC_DEG * 16)
        painter.end()
