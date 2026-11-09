"""The nine hand-held points' fixed order, drawn (#259, finding 192).

The drawing is the capture sheet's own (`references/phases/capture-session-sheet.md`, skill #210):
a vertical plane in front of the nose, seen from the seat, so the sheet's left is the drawing's
left. Painted rather than shipped as an image because it has to follow the theme, the zoom and the
language, and an asset is a second copy of the sheet's words to keep in step.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.theme import current_theme

#: In steps from the centre, x to the person's right and y down: p3 → p4 is the sheet's «down»,
#: twice a step, so it ends a step below the side point.
_PLACES = {
    "p1": (0, 0), "p2": (-1, 0), "p3": (-1, -1), "p4": (-1, 1), "p5": (0, 0),
    "p6": (1, 0), "p7": (1, -1), "p8": (1, 1), "p9": (0, 0),
}
#: The legs that retrace a line already drawn, so they bow outwards to stay readable.
_BOWED = ("p3", "p7")
_CENTRE_MARK = "p1 · p5 · p9"
_DOT = 4.5
_ARROW = 7.0


class NinePointsFigure(QWidget):
    """The plane in front of the nose: nine numbered places and the path through them."""

    def _step(self) -> float:
        metrics = QFontMetricsF(self.font())
        centre = metrics.horizontalAdvance(i18n.t("measPointsCentre"))
        return max(6.2 * metrics.height(), centre / 2 + 1.5 * metrics.height())

    def _pill(self) -> QRectF:
        """The one mark for the one place p1, p5 and p9 share, around the origin."""
        metrics = QFontMetricsF(self.font())
        width = metrics.horizontalAdvance(_CENTRE_MARK) + metrics.height()
        height = metrics.height() * 1.5
        return QRectF(-width / 2, -height / 2, width, height)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        self.ensurePolished()
        metrics = QFontMetricsF(self.font())
        step = self._step()
        words = max(metrics.horizontalAdvance(i18n.t("measPointsLeft")),
                    metrics.horizontalAdvance(i18n.t("measPointsRight")))
        return QSize(math.ceil(2 * (step * 1.4 + words + metrics.height())),
                     math.ceil(2 * (step + 2.2 * metrics.height())))

    def marks(self) -> dict[str, QPointF]:
        """Where each of the nine is drawn, in order: the widget's coordinates."""
        centre = QRectF(self.rect()).center()
        step = self._step()
        return {name: centre + QPointF(x * step, y * step) for name, (x, y) in _PLACES.items()}

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.panel))
        marks = self.marks()
        centre = marks["p1"]
        step = self._step()
        height = QFontMetricsF(self.font()).height()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.panel3))
        painter.drawEllipse(centre, step * 0.62, step * 0.62)  # the head, the nose in front of it

        names = list(marks)
        for start, end in zip(names, names[1:]):
            self._draw_leg(painter, theme, marks[start], marks[end], start in _BOWED, centre)

        for name, place in marks.items():
            if _PLACES[name] != (0, 0):
                self._draw_mark(painter, theme, name, place, centre)
        pill = self._pill().translated(centre)
        fill = QColor(theme.accent)
        fill.setAlphaF(0.22)
        painter.setPen(QPen(QColor(theme.accent), 1.2))
        painter.setBrush(fill)
        painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
        painter.setPen(QColor(theme.text))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, _CENTRE_MARK)

        painter.setPen(QColor(theme.muted))
        above = QRectF(centre.x() - step, centre.y() - step * 0.62 - height * 1.3, 2 * step, height)
        painter.drawText(above, Qt.AlignmentFlag.AlignCenter, i18n.t("measPointsCentre"))
        margin = height / 2
        sides = QRectF(margin, centre.y() - height, self.width() - 2 * margin, 2 * height)
        painter.drawText(sides, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         i18n.t("measPointsLeft"))
        painter.drawText(sides, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         i18n.t("measPointsRight"))
        painter.end()

    def _draw_leg(self, painter, theme, start: QPointF, end: QPointF, bowed: bool,
                  centre: QPointF) -> None:
        colour = QColor(theme.accent)
        painter.setPen(QPen(colour, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        clear = _DOT + 3
        if bowed:
            outwards = -1 if start.x() < centre.x() else 1
            bend = QPointF(start.x() + outwards * self._step() * 0.8, (start.y() + end.y()) / 2)
            first = self._toward(start, bend, clear)
            last = self._toward(end, bend, clear)
            path = QPainterPath(first)
            path.quadTo(bend, last)
            painter.drawPath(path)
            self._draw_head(painter, colour, last, last - bend)
            return
        first = self._leave(start, end, centre, clear)
        last = self._leave(end, start, centre, clear)
        painter.drawLine(first, last)
        self._draw_head(painter, colour, last, last - first)

    def _leave(self, point: QPointF, other: QPointF, centre: QPointF, clear: float) -> QPointF:
        """Where a leg stops short of `point`: the pill's edge at the centre, the dot's elsewhere."""
        if point != centre:
            return self._toward(point, other, clear)
        delta = other - point
        length = math.hypot(delta.x(), delta.y())
        pill = self._pill()
        half_w, half_h = pill.width() / 2 + 3, pill.height() / 2 + 3
        ux, uy = delta.x() / length, delta.y() / length
        return point + QPointF(ux, uy) / math.hypot(ux / half_w, uy / half_h)

    @staticmethod
    def _toward(point: QPointF, other: QPointF, distance: float) -> QPointF:
        delta = other - point
        return point + delta * (distance / math.hypot(delta.x(), delta.y()))

    @staticmethod
    def _draw_head(painter, colour: QColor, tip: QPointF, direction: QPointF) -> None:
        angle = math.atan2(direction.y(), direction.x())
        wings = [tip - QPointF(math.cos(angle + spread) * _ARROW, math.sin(angle + spread) * _ARROW)
                 for spread in (0.42, -0.42)]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawPolygon(QPolygonF([tip, *wings]))

    def _draw_mark(self, painter, theme, name: str, place: QPointF, centre: QPointF) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.accent))
        painter.drawEllipse(place, _DOT, _DOT)
        painter.setPen(QColor(theme.text))
        metrics = QFontMetricsF(self.font())
        box = QRectF(0, 0, metrics.horizontalAdvance(name) + 2, metrics.height())
        gap = _DOT + 3
        toward_centre = 1 if place.x() < centre.x() else -1
        if place.y() < centre.y():  # the top row: over the dot
            box.moveCenter(QPointF(place.x(), place.y() - gap - box.height() / 2))
        elif place.y() > centre.y():  # the bottom row: under it
            box.moveCenter(QPointF(place.x(), place.y() + gap + box.height() / 2))
        else:  # the side point: below it, on the side the bowed leg leaves free
            box.moveCenter(QPointF(place.x() + toward_centre * (gap + box.width() / 2),
                                   place.y() + box.height() / 2 + 2))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, name)


class NinePointsPopover(QFrame):
    """The figure with the sheet's words, under the way in; a click anywhere else closes it."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self._intro = QLabel()
        self._intro.setWordWrap(True)
        self._figure = NinePointsFigure()
        self._caption = QLabel()
        self._caption.setWordWrap(True)
        layout.addWidget(self._intro)
        layout.addWidget(self._figure)
        layout.addWidget(self._caption)

    def open_at(self, anchor: QWidget) -> None:
        """Filled at every opening: language and zoom can only change while it is closed."""
        self.ensurePolished()
        self._figure.setFixedSize(self._figure.sizeHint())
        for label, key in ((self._intro, "measPointsIntro"), (self._caption, "measPointsCaption")):
            label.setText(i18n.t(key))
            label.setFixedWidth(self._figure.width())
        self.adjustSize()
        screen = anchor.screen().availableGeometry()
        under = anchor.mapToGlobal(QPoint(0, anchor.height() + 2))
        self.move(max(screen.left(), min(under.x(), screen.right() + 1 - self.width())),
                  max(screen.top(), min(under.y(), screen.bottom() + 1 - self.height())))
        self.show()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        theme = current_theme()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.panel))
        painter.setPen(QColor(theme.border2))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()
