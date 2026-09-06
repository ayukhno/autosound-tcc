"""How big a window opens — measured against the window it came from, not typed in pixels.

Every dialog in this app states its own size as a number (`resize(880, 560)`, `setMinimumWidth(640)`)
and none of them ever looked at the main window or at the screen. On a laptop that is a small
window in the middle of a big one; on the user's own screen (2026-09-06) it was the read table
showing eleven rows of a hundred with the buttons squeezed against the bottom.

Two shapes, because two things are being asked for:

* `fit_to_parent` — a working window that should be BIG but still obviously a window over the app:
  a share of the main window, centred on it.
* `open_maximised` — a window you work in for an hour and read numbers off: the curve window. The
  user asked for it outright, in those words: "вікно з графіками на макс.розмір".

Both degrade to the screen when there is no usable parent (a dialog opened before the main window
is on screen, or in a headless test), and neither ever asks for more than the screen can show.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication

#: Never smaller than this, whatever the parent is. A share of a small window is still a form
#: somebody has to fill in.
MIN_WIDTH, MIN_HEIGHT = 640, 460


def _available(widget) -> Optional[QRect]:
    """The usable area of the screen `widget` is on — the desk, minus the taskbar."""
    screen = (widget.screen() if widget is not None else None) or QGuiApplication.primaryScreen()
    return screen.availableGeometry() if screen is not None else None


def _reference(widget) -> QRect:
    """What to measure against: the window this came from, or the screen when there is none."""
    window = widget.window() if widget is not None else None
    if window is not None and window.isVisible() and window.width() > MIN_WIDTH // 2:
        return window.geometry()
    return _available(widget) or QRect(0, 0, 1280, 800)


def fit_to_parent(dialog, fraction: float = 0.8) -> None:
    """Open `dialog` at `fraction` of the window it belongs to, centred on it.

    Called from `__init__`, before `exec()`: a modal that resizes after it is on screen jumps.
    """
    reference = _reference(dialog.parent() if dialog.parent() is not None else dialog)
    width = max(int(reference.width() * fraction), MIN_WIDTH)
    height = max(int(reference.height() * fraction), MIN_HEIGHT)
    room = _available(dialog)
    if room is not None:
        # A minimum that does not fit the screen is not a minimum worth keeping: the buttons at
        # the bottom of a dialog taller than the desk cannot be reached at all.
        width, height = min(width, room.width()), min(height, room.height())
    dialog.resize(width, height)
    dialog.move(reference.center() - QPoint(width // 2, height // 2))


def open_maximised(window) -> None:
    """Show `window` filling the screen, falling back to the screen's own rectangle.

    `showMaximized` is the honest one — it is the state a person can undo with the same button
    they know from every other window — but a frameless or tool window is not maximisable
    everywhere, so the fallback puts it over the available area instead.
    """
    window.showMaximized()
    if window.isMaximized():
        return
    room = _available(window)
    if room is not None:
        window.setGeometry(room)
    window.show()
