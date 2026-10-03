"""Hover that follows the mouse after the window was left for another app and back (tcc#137).

Finding 139, the Arbiter on the Windows VM: in the diagnostics window, after a switch to a
terminal and back, the widget that had been under the mouse kept its hover look (the «Beta
channel» box kept its orange ring with the mouse on «Update»), and no hover worked on that page
until another tab was chosen. A window that loses activation with the mouse still over it is
sent no leave, so Qt's own record of which widget the mouse is in -- the one every later enter
and leave is dispatched against -- goes stale, and stays stale after the return.

The cure goes through the window's own enter/leave path rather than around it. A `Leave` sent to
the top-level's QWindow is how the platform says the mouse left the window: QWidgetWindow
answers it by dispatching a leave down to whatever it last saw the mouse in and forgetting it
(measured offscreen: the child's `underMouse()` goes False with the window's). On the return, an
`Enter` at the cursor dispatches enter to what is under it now, so hover works at once instead of
after the next tab switch. App-wide, one filter for every top-level widget.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QCursor, QEnterEvent
from PySide6.QtWidgets import QApplication, QWidget


class HoverReset(QObject):
    """Sends a top-level window a leave when it loses activation, and an enter when it gets it back."""

    def __init__(self, parent: Optional[QObject] = None,
                 cursor_pos: Optional[Callable[[], QPoint]] = None) -> None:
        super().__init__(parent)
        # Injected by the tests: offscreen there is no real cursor to ask.
        self._cursor_pos = cursor_pos or QCursor.pos

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        kind = event.type()
        if kind not in (QEvent.Type.WindowDeactivate, QEvent.Type.WindowActivate):
            return False
        # Only the window itself (its children see the same event), and never a popup: a menu or a
        # combo's list keeps its own hover while it is open, and closes on deactivation anyway.
        if not isinstance(obj, QWidget) or not obj.isWindow() \
                or obj.windowType() == Qt.WindowType.Popup:
            return False
        handle = obj.windowHandle()
        if handle is None:
            return False
        if kind == QEvent.Type.WindowDeactivate:
            # One of our windows to another (night review of tcc#137, I1): Qt activates the new one
            # BEFORE it deactivates this one, and a leave here goes to Qt's one app-wide record of
            # where the mouse is -- clearing the hover the new window was just given, with no
            # enter to follow, since the mouse never left it. Qt's own enter/leave follows the
            # mouse between our windows. A switch to another app has no active window by now.
            active = QApplication.activeWindow()
            if active is not None and active is not obj:
                return False
            QApplication.sendEvent(handle, QEvent(QEvent.Type.Leave))
            return False
        where = self._cursor_pos()
        # The window under the cursor, not merely one whose rectangle holds it (M1): with another
        # window over that point -- the diagnostics over the main one -- the widget beneath would
        # be entered and keep a stale hover until the mouse crossed it again.
        if QApplication.topLevelAt(where) is obj:
            point = QPointF(obj.mapFromGlobal(where))
            QApplication.sendEvent(handle, QEnterEvent(point, point, QPointF(where)))
        return False


def install(app: QApplication,
            cursor_pos: Optional[Callable[[], QPoint]] = None) -> HoverReset:
    """One filter for the whole application, parented to it so it lives as long as it does.

    A second call hands back the first rather than stacking a second filter (night review, M4)."""
    found = app.findChild(HoverReset)
    if found is not None:
        return found
    reset = HoverReset(app, cursor_pos=cursor_pos)
    app.installEventFilter(reset)
    return reset
