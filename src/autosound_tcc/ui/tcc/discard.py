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
is invisible. `setParent(None)` stays, and `drop()` says why — dropping it was proposed by an
outside review and refuted by the suite in one run.
"""

from __future__ import annotations


def drop(widget) -> None:
    """Hide, unparent and schedule deletion — in that order, which is the whole point.

    **`setParent(None)` was tried and put back, and the reason is worth keeping.** An outside
    review (agy, 2026-09-11) argued it should go entirely: `hide()` is synchronous, so the widget
    leaves rendering and layout before the call returns, and never unparenting would make a
    top-level window impossible rather than merely unlikely. The argument is good and the
    conclusion is wrong, which the suite said within a second: `test_plan_panel` counted **14
    rows where 7 were expected**.

    `setParent(None)` does a second job nobody had written down. It detaches from the parent's
    CHILD LIST, and it does that immediately — while `deleteLater()` waits for the event loop, so
    until then everything that walks the object tree (`findChildren`, and the rebuild code that
    uses it) sees the old rows beside the new. Hiding a widget does not remove it from the tree.

    So the order carries both: `hide()` first, which is what makes the reparent invisible — a
    hidden widget has no window to map — and `setParent(None)` second, which takes it out of the
    tree at once.
    """
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
