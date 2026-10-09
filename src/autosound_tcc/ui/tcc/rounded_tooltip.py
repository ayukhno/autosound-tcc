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

import html
import textwrap
from typing import Optional

import shiboken6
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QLabel, QWidget

from autosound_tcc.ui.tcc.theme import current_theme

#: How the hover tips that replaced the paragraphs under the plot are built.
#:
#: `_TIP_FONT_PX` because the paragraphs they replaced were 11 px `phead-sub` grey and the user
#: could not read them (2026-08-18). `_TIP_WRAP_CHARS` because the shared tip widget is a QLabel
#: with word wrap OFF, so a long sentence asks for a label as wide as the sentence and
#: `adjustSize` clips it to two thirds of the screen: measured here, a 200-character line wants
#: 1434 px and gets 533. Wrapping the text by hand is the only lever that leaves that label
#: alone, and it is shared with every other tip in the app.
_TIP_WRAP_CHARS = 72
_TIP_FONT_PX = 15


def _wrapped(text: str) -> str:
    """`text` escaped and broken into lines by hand — see `_TIP_WRAP_CHARS` for why by hand."""
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        wrapped = textwrap.wrap(
            paragraph, _TIP_WRAP_CHARS, break_long_words=False, break_on_hyphens=False
        )
        lines.extend(html.escape(part) for part in (wrapped or [""]))
    return "<br>".join(lines)


def tip_html(text: str, head: str = "", warn: bool = False) -> str:
    """`text` as a hover tip: large, wrapped, with a bold head, warning-coloured when in doubt.

    The three paragraphs that used to stand under the plot are behind buttons now (user,
    2026-08-18: they took the space and could not be read), so the text that was a wall of small
    grey type is the same text laid out to be read — which is the whole point of moving it.

    Nothing that LEAVES the curve window comes through here: `statement()` and the bank's own
    sentence are built from the plain strings and are unchanged. This is drawing, only.

    It lives beside the tip it formats for, not in `curve_view`, which imports pyqtgraph and
    numpy: the main window uses it too, and starting the app paid for both (#177).
    """
    theme = current_theme()
    body = _wrapped(text)
    if head:
        body = f"<b>{html.escape(head)}</b><br>{body}"
    if warn:
        body = f'<span style="color: {theme.warn}">{body}</span>'
    return f'<div style="font-size: {_TIP_FONT_PX}px; color: {theme.text}">{body}</div>'


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
        # A tip was hidden only by its owner's leave event, and nothing sends one when TCC stops
        # being the active app, or when the owner is hidden or rebuilt under the cursor — so it
        # stayed on top of the next app, or hung over TCC with the mouse elsewhere (finding 87,
        # tcc#78). It now hides on either, and while shown checks that the cursor is still on
        # its owner.
        self._owner: Optional[QWidget] = None
        self._watch = QTimer(self)
        self._watch.setInterval(250)
        self._watch.timeout.connect(self._check_owner)
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state)

    @classmethod
    def instance(cls) -> "RoundedTooltip":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def show_at(self, global_pos: QPoint, html: str, owner: Optional[QWidget] = None) -> None:
        """`owner` is the widget the tip is about; while it is shown, the tip hides once the cursor
        is off it or it is gone. Without one (a menu's action, a «copied» note) the caller hides it."""
        self._owner = owner
        if owner is None:
            self._watch.stop()
        else:
            self._watch.start()
        self.setText(html)
        self.adjustSize()
        # Offset so the cursor doesn't sit on top of (and immediately re-trigger leave/enter on)
        # the popup itself -- same rough offset the native tooltip uses.
        self.move(self._fit_on_screen(global_pos + QPoint(14, 18)))
        # No `raise_()`: a `ToolTip` window is above the others already, and on macOS Qt's
        # `raise()` activates the whole application — a tip shown while the terminal
        # «Налаштувати omp…» opened was in front put TCC back over it (finding 79, tcc#71).
        self.show()

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
        self._owner = None
        self._watch.stop()
        self.hide()

    def _on_app_state(self, state) -> None:
        if state != Qt.ApplicationState.ApplicationActive:
            self.hide_tip()

    def _check_owner(self) -> None:
        owner = self._owner
        if owner is None:
            return
        if (
            not shiboken6.isValid(owner)
            or not owner.isVisible()
            or not owner.rect().contains(owner.mapFromGlobal(QCursor.pos()))
        ):
            self.hide_tip()

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
                RoundedTooltip.instance().show_at(QCursor.pos(), self._text, owner=widget)

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
