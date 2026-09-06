"""A row that wraps — one implementation, two callers.

It was written for the curve window's chip row and is now also the measurement card's legend,
which is what made it worth its own module: the legend was a `QHBoxLayout` of four items that
could not shrink, so its 345 px was the minimum width of the whole right column, and on a narrow
window the card was cut at the edge with the columns gone (user, on Windows, 2026-09-06, with the
picture). A legend is read, not scanned: eliding "знятий, не підходить" to "зня…" would keep the
width and lose the point, and wrapping to a second line keeps both.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    """A row that wraps: items go left to right and start a new line when they run out of width.

    Here because a selection is as many measurements as the tuner wants — a whole side is four
    drivers and ALL+C is seven — and the alternatives are both wrong for a row that has to be
    READ. A QHBoxLayout squeezes seven chips until their names are ellipses, which is exactly the
    "saying (3) while listing two names" the Advisor refused; a scroll area hides the overflow,
    which is the same refusal wearing a different control.

    Hidden items take no space. That matters because the chips are pooled rather than destroyed
    (`CurveDialog._render_chips`), so the spares live in this layout for the whole session.

    No `__del__`. The Qt for Python example ships one that drains the layout on collection, and in
    this app a destructor running at a moment Python chooses is the exact shape of the segfaults
    `tests/test_curve_view.py` and `qt_shutdown.py` document: nothing here is ever removed anyway,
    so there is no leak to chase.
    """

    def __init__(self, parent: Optional[QWidget] = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    # ---- the five QLayout has to have -----------------------------------

    def addItem(self, item) -> None:  # noqa: N802 (Qt override)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 (Qt override)
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 (Qt override)
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 (Qt override)
        return Qt.Orientation(0)

    # ---- height for width, which is the whole point ---------------------

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt override)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt override)
        return self._lay_out(QRect(0, 0, width, 0), place=False)

    def setGeometry(self, rect) -> None:  # noqa: N802 (Qt override)
        super().setGeometry(rect)
        self._lay_out(rect, place=True)

    def sizeHint(self):  # noqa: N802 (Qt override)
        """One row: what this asks for when there is room, which is a different question from what
        it can survive on.

        It used to answer `minimumSize()` — the widest single item — and that is the answer to
        "how narrow may I be", not "how wide would I like to be". A parent that reads the hint as
        the preference then hands over the narrowest width and gets every item on its own line: the
        measurement card's legend came out 92 px wide and 90 px tall, eight rows of one item
        (2026-09-06). `minimumSize` below still says how far it will give.
        """
        width, height = 0, 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            width += hint.width() + self.spacing()
            height = max(height, hint.height())
        margins = self.contentsMargins()
        return QSize(max(width - self.spacing(), 0) + margins.left() + margins.right(),
                     height + margins.top() + margins.bottom())

    def minimumSize(self):  # noqa: N802 (Qt override)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    def _lay_out(self, rect, place: bool) -> int:
        """Walk the items, wrapping at `rect`'s right edge; answer the height that took."""
        margins = self.contentsMargins()
        left = rect.x() + margins.left()
        right = rect.right() - margins.right()
        x, y, line_height = left, rect.y() + margins.top(), 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            if x > left and x + hint.width() - 1 > right:
                x = left
                y += line_height + self.spacing()
                line_height = 0
            if place:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line_height = max(line_height, hint.height())
        return y + line_height + margins.bottom() - rect.y()
