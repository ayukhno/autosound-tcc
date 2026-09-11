"""Take a widget out of a layout without it flashing across the screen on the way out.

`setParent(None)` is the usual way to clear a layout, and on its own it is a bug on Windows.
A widget with no parent **is a top-level window**, so a VISIBLE child handed `None` becomes, for
the instant before `deleteLater()` runs, a real window on the desktop — sized like the panel it
came from and titled with the application name, because a parentless widget inherits that.

That is not a theory. A `SetWinEventHook` watcher on the Arbiter's machine caught it by class and
title (2026-09-11):

    CREATE  class='Qt6112QWindowIcon'  title='Autosound TCC'  owner=pythonw.exe
    SHOW    vis=True   213x764
    SHOW    vis=False  0x0            ← gone, about 60 ms later

Once per MCP call, because that is how often the panels rebuild. Every window watcher before that
one polled the desktop and missed it, which is why this was hunted as a console problem for a day:
the flash a person could see was never a subprocess at all. It was ours.

`hide()` first costs nothing and closes it: a hidden widget has no window to map, so the reparent
is invisible. Keeping `setParent(None)` matters too — `deleteLater()` alone leaves the old,
un-laid-out widget overlapping its freshly built replacement until the next event-loop pass.
"""

from __future__ import annotations


def drop(widget) -> None:
    """Hide, unparent and schedule deletion — in that order, which is the whole point."""
    if widget is None:
        return
    widget.hide()
    widget.setParent(None)
    widget.deleteLater()


def clear(layout) -> None:
    """Empty a layout of its widgets, with each one dropped rather than flashed away."""
    while layout.count():
        item = layout.takeAt(0)
        drop(item.widget())
