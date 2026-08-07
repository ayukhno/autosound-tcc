"""Right-click to copy what is on the screen — values, whole rows, and the hints behind them.

Nothing in TCC could be copied (user, 2026-08-07). That is worse here than in most apps: a lot of
what the panels show is meant to be carried somewhere else — a model id pasted into a shell, a
channel's settings quoted into a message, a flaw line handed to somebody else's session. Reading a
number off the screen and retyping it is exactly how a `5.38` becomes a `5.83`.

Two mechanisms, because one does not fit both halves of the app:

* **Selection**, for the dialog. A selectable `QLabel` swallows mouse events, which is free in a
  message bubble (nothing under it is clickable) and destructive on a row that opens a detail pane
  when clicked — the click would land on the text instead of the row.
* **This menu**, for everything else. It needs no mouse capture, so a row keeps its click.

Hints get their own item because in this app they are not decoration: the tooltip is where the
route's "whose bill is it" lives, what each effort level costs, why a reviewer is clipboard-only,
and the untruncated text of anything the panel had to elide (`ElidedLabel`). A hint that can only
be hovered cannot be quoted.
"""

from __future__ import annotations

from typing import Callable, Optional, Union

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QGuiApplication, QTextDocumentFragment
from PySide6.QtWidgets import QMenu, QWidget

from autosound_tcc.ui.tcc import i18n

#: Either the text itself or something that produces it when the menu opens. Callables matter for
#: anything that changes after the menu is attached -- a streamed message, a param that refreshes.
Source = Union[str, Callable[[], str], None]


def resolve(source: Source) -> str:
    """A `Source` as text, evaluated now. Never raises: a copy item that throws while the menu is
    opening would take the menu with it, and a failed copy is not worth a crash."""
    if source is None:
        return ""
    try:
        value = source() if callable(source) else source
    except Exception:  # noqa: BLE001 - see docstring
        return ""
    return str(value or "").strip()


def full_text(widget: QWidget) -> str:
    """What a label really says, not what fits.

    `ElidedLabel` shortens its own text in place and keeps the original in `_full`, so reading
    `text()` off one gives back the ellipsis — copying "Amp (midbass (front) + cen…" is worse than
    not offering to copy at all.
    """
    full = getattr(widget, "_full", None)
    if isinstance(full, str) and full:
        return full
    getter = getattr(widget, "text", None)
    return str(getter()).strip() if callable(getter) else ""


def plain(html: str) -> str:
    """Rich text as text a person can paste.

    Stripping tags with a regex is not the same thing and gets both halves wrong: `&amp;` and
    `&nbsp;` survive it verbatim, and a `<br>` between two lines comes out as no space at all.
    Qt's converter is the engine that rendered the thing in the first place.
    """
    return QTextDocumentFragment.fromHtml(html or "").toPlainText().strip()


def copy_text(text: str) -> None:
    clipboard = QGuiApplication.clipboard()
    if clipboard is not None and text:
        clipboard.setText(text)


def enable_copy(
    widget: QWidget,
    *,
    value: Source = None,
    row: Source = None,
    hint: Source = None,
    extra: Optional[list[tuple[str, Source]]] = None,
) -> None:
    """Give `widget` a right-click menu offering whatever of these has content.

    Every item is resolved when the menu opens, and one that resolves to nothing is not shown —
    so a row with no tooltip simply has no "copy hint" entry rather than a dead one. `hint`
    defaults to the widget's own tooltip, which is where `ElidedLabel` puts the text it had to cut.
    """
    widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def items() -> list[tuple[str, str]]:
        """What the menu would offer right now, in order, empties dropped."""
        pairs: list[tuple[str, Source]] = [("copyValue", value), ("copyRow", row)]
        pairs += list(extra or [])
        pairs.append(("copyHint", hint if hint is not None else widget.toolTip))
        return [(i18n.t(key), text) for key, source in pairs if (text := resolve(source))]

    def show(point) -> None:
        menu = QMenu(widget)
        for label, text in items():
            action = QAction(label, menu)
            action.triggered.connect(lambda _checked=False, t=text: copy_text(t))
            menu.addAction(action)
        if menu.actions():
            menu.exec(widget.mapToGlobal(point))

    widget.customContextMenuRequested.connect(show)
    # Readable from outside, so what the menu offers can be asserted without opening a modal one.
    widget.copy_items = items  # type: ignore[attr-defined]
