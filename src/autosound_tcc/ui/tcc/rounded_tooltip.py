"""A rounded-corner replacement for `QToolTip` (user report 2026-07-28: channel hints looked
square-cornered despite `QToolTip`'s own QSS already declaring `border-radius` -- macOS's native
tooltip window keeps a square frame regardless, a known Qt/platform limitation; QSS only reaches
the content, not the window shape). A frameless, translucent-background popup gives us the window
shape too, so the rounded rect is real rather than painted-then-clipped square.

One shared instance (`instance()`) -- cheap to reuse across every hoverable row rather than
building a fresh popup per hover. `attach()` is the one-line way for any widget to use it instead
of `setToolTip()` (user report 2026-07-28: the fix shouldn't be one-off per widget -- every
tooltip in the app should look the same).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QLabel, QWidget

from autosound_tcc.ui.tcc.theme import current_theme


class RoundedTooltip(QLabel):
    _instance: "RoundedTooltip | None" = None

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Showing on hover must not steal focus from whatever the user is actually working in.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setProperty("class", "rounded-tip")
        self.setContentsMargins(9, 6, 9, 6)

    @classmethod
    def instance(cls) -> "RoundedTooltip":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def show_at(self, global_pos: QPoint, html: str) -> None:
        self.setText(html)
        self.adjustSize()
        # Offset so the cursor doesn't sit on top of (and immediately re-trigger leave/enter on)
        # the popup itself -- same rough offset the native tooltip uses.
        self.move(self._fit_on_screen(global_pos + QPoint(14, 18)))
        self.show()
        self.raise_()

    def _fit_on_screen(self, top_left: QPoint) -> QPoint:
        """Keep the whole tip on the screen the cursor is on.

        Placed blind, a hint near the right edge is simply cut off -- and the hints in this app are
        where the reasoning lives, so half of one is worse than none (user, 2026-08-07). It flips
        to the other side of the cursor when there is no room, and only slides as a last resort:
        sliding alone would park the tip under the pointer and re-trigger the hover it came from.
        """
        screen = QGuiApplication.screenAt(top_left) or QGuiApplication.primaryScreen()
        if screen is None:
            return top_left
        area = screen.availableGeometry()
        size = self.size()
        x, y = top_left.x(), top_left.y()
        if x + size.width() > area.right():
            flipped = x - 28 - size.width()  # back across the cursor, same 14px gap on that side
            x = flipped if flipped >= area.left() else area.right() - size.width()
        if y + size.height() > area.bottom():
            flipped = y - 32 - size.height()
            y = flipped if flipped >= area.top() else area.bottom() - size.height()
        return QPoint(max(x, area.left()), max(y, area.top()))

    def hide_tip(self) -> None:
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # A WA_TranslucentBackground top-level widget's own QSS `background`/`border-radius`
        # isn't reliably composited by the style engine (verified: it silently didn't paint at
        # all, leaving the label's text floating over whatever was beneath it with no backing
        # box -- user report 2026-07-28). Paint the rounded rect ourselves so it's guaranteed,
        # then let QLabel draw its text on top as normal.
        t = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.fillPath(path, QColor(t.panel3))
        painter.setPen(QColor(t.border2))
        painter.drawPath(path)
        painter.end()
        super().paintEvent(event)


class HoverTip:
    """Attaches a rounded hover tooltip to any widget in place of `setToolTip()`. Keep the
    returned object around (as an attribute) if the text needs to change later (language switch,
    state change) -- call `set_text()` rather than re-attaching. If nothing needs to update it
    later, the widget itself keeps this alive (its enterEvent/leaveEvent close over `self`), so
    the constructor call alone is enough -- no need to hold a reference."""

    def __init__(self, widget: QWidget, text: str = "") -> None:
        self._text = text
        orig_enter = widget.enterEvent
        orig_leave = widget.leaveEvent

        def _enter(event, _orig=orig_enter) -> None:
            _orig(event)
            if self._text:
                RoundedTooltip.instance().show_at(QCursor.pos(), self._text)

        def _leave(event, _orig=orig_leave) -> None:
            _orig(event)
            RoundedTooltip.instance().hide_tip()

        widget.enterEvent = _enter  # type: ignore[assignment]
        widget.leaveEvent = _leave  # type: ignore[assignment]

    def set_text(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        """The hint as it stands. These tips are not Qt tooltips — `widget.toolTip()` is empty on
        anything using this — so a reader that wants the hint (copy_menu) has to ask the tip."""
        return self._text


def attach(widget: QWidget, text: str = "") -> HoverTip:
    """Shorthand for `HoverTip(widget, text)` -- reads better at call sites replacing a
    `widget.setToolTip(text)` line one-for-one.

    The tip is also left on the widget as `hover_tip`. These are not Qt tooltips, so `toolTip()`
    is empty on anything using them, and a reader that wants the hint -- "copy hint", a test
    asking whether a chip explains itself -- would otherwise have no way to find it.
    """
    tip = HoverTip(widget, text)
    widget.hover_tip = tip  # type: ignore[attr-defined]
    return tip
