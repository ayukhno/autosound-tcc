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

**And before any of that, the widget leaves its layout** — which closed `#19`, the Windows access
violation that had killed the CI suite in about one run in three since the first Windows run
(2026-09-07). `setParent(None)` on a widget still in a layout makes Qt delete its `QWidgetItem` in
C++, and PySide had made a Python wrapper for that item when the row joined its parent layout
(`addLayoutOwnership`); nobody tells the wrapper. It stays in shiboken's address table, and the
next Qt object built on the same address finds it and dies in `SignalManager::retrieveMetaObject`.
Measured under cdb on the Windows runner — see `test_discard.py` for the table — and invisible on
macOS, where no detector found the entry at all.
"""

from __future__ import annotations


def drop(widget) -> None:
    """Out of its layout, hide, unparent and schedule deletion — in that order, which is the point.

    **Out of its layout first** (`#19`, 2026-09-12). Taken out by `takeAt`, the item goes through
    PySide and its wrapper with it; left for `setParent(None)` to remove, Qt deletes the item behind
    the wrapper's back. 150 cycles per attempt on the Windows runner: as it was, a crash on the first
    attempt of both jobs; with this step, none in 1500.

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
    _leave_layout(widget)
    _retire(widget)


def _retire(widget) -> None:
    """Hide, unparent, schedule deletion — for a widget that is ALREADY out of every layout."""
    widget.hide()
    widget.setParent(None)
    widget.deleteLater()


def _leave_layout(widget) -> None:
    parent = widget.parentWidget()
    layout = parent.layout() if parent is not None else None
    if layout is not None:
        _take_out(layout, widget)


def _take_out(layout, widget) -> bool:
    """Take the widget's item out of `layout` or any layout nested in it. True when it was there.

    Nested because that is where the crash lived: a chat bubble sits in a row, and the row in the
    chat — the chat's own layout never holds the bubble directly.
    """
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is None:
            continue
        if item.widget() is widget:
            layout.takeAt(index)
            return True
        inner = item.layout()
        if inner is not None and _take_out(inner, widget):
            return True
    return False


def clear(layout) -> None:
    """Empty a layout of its widgets, with each one dropped rather than flashed away.

    No search here, and none is needed: `takeAt` has already taken the item out, which is the whole
    of what `#19` asks for before a widget is unparented. Going through `drop` would scan what is
    left of the layout once per item — quadratic, 244 ms for a 500-bubble transcript against 18 ms.
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            _retire(widget)
