"""The right column's two cards fold to their header lines (finding 176, tcc#243).

Each card is a child of one vertical `QSplitter`. A folded card keeps its header row (the focus
card's Ready button and REW dot are in it), its body is hidden, and the card is capped at the
header's height, so the splitter gives the rest of the column to the other card.

The body goes inside a shell only this module shows and hides: a reload that calls `show()` on the
plan or a refresh on the focus panel has no way to bring a folded body back.

One card always stays open; folding the second is refused, its arrow greyed.

The sizes are the person's. Folding writes nothing to `ui/right_split`: the column they left is
what comes back on unfolding, from memory in this run and from the setting after a restart; a size
written while a card is folded would be the header's sliver, restored for good.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QFrame, QSplitter, QToolButton, QVBoxLayout, QWidget

from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.labels import ElidedLabel
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip

RIGHT_SPLIT_KEY = "ui/right_split"

#: `QWIDGETSIZE_MAX`: what a card's height is capped at when nothing caps it.
_NO_CAP = 16777215


def _folded_key(name: str) -> str:
    return f"ui/{name}_folded"


@dataclass
class _Card:
    name: str
    frame: QFrame
    shell: QWidget
    arrow: QToolButton
    folded: bool = False


class PanelFold(QObject):
    """Folds the cards of `split`; owns the border's memory (`ui/right_split`) as well, because
    the two decide together what the column looks like."""

    #: A body is back on screen: what it measured while hidden is the owner's to re-read.
    unfolded = Signal()

    def __init__(self, split: QSplitter, settings) -> None:
        super().__init__(split)
        self._split = split
        self._settings = settings
        self._cards: list[_Card] = []
        #: The column as it was when the fold happened; gone on unfolding.
        self._open_sizes: Optional[list[int]] = None

    def add(self, name: str, frame: QFrame, head: QWidget, body: QWidget,
            gives_ground: Optional[ElidedLabel] = None) -> None:
        """`frame` is already in the splitter; `body` is already in `frame`'s layout.

        `gives_ground` is the head's elided subtitle: its floor pays for the arrow, or the row
        would ask 27 px more and push its right end off the column, the dot with it (2026-09-06)."""
        layout = frame.layout()
        index = layout.indexOf(body)
        stretch = layout.stretch(index)
        layout.removeWidget(body)
        shell = QWidget(frame)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.addWidget(body)
        layout.insertWidget(index, shell, stretch)

        room_before = head.layout().minimumSize().width()
        arrow = QToolButton(head)
        arrow.setProperty("class", "panel-fold")
        arrow.setAutoRaise(True)
        arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        attach_tip(arrow)
        head.layout().insertWidget(0, arrow)
        card = _Card(name, frame, shell, arrow)
        arrow.clicked.connect(lambda: self._toggle(card))
        self._cards.append(card)
        frame.installEventFilter(self)
        # The rule holds for a save with both folded in it, too: the first one stands. The refused
        # card's key goes, or that card would come up folded once the first is open again.
        saved = bool(self._settings.value(_folded_key(name), False, type=bool))
        stands = saved and self._folded() is None
        if saved and not stands:
            self._settings.setValue(_folded_key(name), False)
        self._show_folded(card, stands)
        if gives_ground is not None:  # measured once the arrow wears its glyph: a style's own spacing and font decide
            head.layout().invalidate()
            room = head.layout().minimumSize().width() - room_before
            gives_ground.set_min_width(max(0, gives_ground.minimumWidth() - room))

    def arrow(self, name: str) -> QToolButton:
        return self._card(name).arrow

    def _card(self, name: str) -> _Card:
        return next(c for c in self._cards if c.name == name)

    # ---- the border's memory ---------------------------------------------------

    def read(self) -> list[int]:
        """Where the person left the border between the two cards, or nothing."""
        raw = self._settings.value(RIGHT_SPLIT_KEY, None)
        try:
            sizes = [int(v) for v in json.loads(raw)] if raw else []
        except (TypeError, ValueError, OverflowError):
            sizes = []
        return sizes if len(sizes) == 2 and all(0 < v <= _NO_CAP for v in sizes) else []

    def remember(self, *_args) -> None:
        """The border's new place. Not while a card is folded: that is the header's height, not
        a place anyone chose."""
        if self._folded() is None:
            self._settings.setValue(RIGHT_SPLIT_KEY, json.dumps(self._split.sizes()))

    def apply(self) -> None:
        """The first sizing, once the column has a height: sizes set before that are clamped to
        the cards' minimums and the plan ended up with most of the column."""
        try:
            total = sum(self._split.sizes())
        except RuntimeError:
            return
        folded = self._folded()
        if folded is not None:
            self._cap(folded)
            self._squeeze(folded, total)
            return
        sizes = self._open_column(total)
        if sizes:
            self._split.setSizes(sizes)

    def _open_column(self, total: int) -> list[int]:
        """The sizes of a column with both cards open: as it was before the fold, or where the
        border was left, or, the first time, the larger share to the capture card, which has the
        list in it."""
        if self._open_sizes:
            return self._open_sizes
        saved = self.read()
        if saved:
            return saved
        return [total * 3 // 8, total - total * 3 // 8] if total > 0 else []

    # ---- folding -----------------------------------------------------------------

    def retranslate(self) -> None:
        self._dress()

    def reveal(self, name: str) -> None:
        """Something was asked of `name`'s body: a folded card opens so that it can be seen. At
        most one card is folded, so opening one breaks no rule; a card already open stays as it is.
        For a request only: a refresh of the data does not come here and does not unfold."""
        card = self._card(name)
        if card.folded:
            self._unfold(card)

    def revealing(self, name: str, action: Callable[..., None]) -> Callable[..., None]:
        """`action`, with `reveal(name)` before it: what a signal or an offer is wired to."""

        def run(*args) -> None:
            self.reveal(name)
            action(*args)

        return run

    def _folded(self) -> Optional[_Card]:
        return next((c for c in self._cards if c.folded), None)

    def _toggle(self, card: _Card) -> None:
        if card.folded:
            self._unfold(card)
        elif self._folded() is None:
            self._fold(card)

    def _fold(self, card: _Card) -> None:
        sizes = self._split.sizes()
        self._open_sizes = sizes if all(v > 0 for v in sizes) else None
        self._show_folded(card, True)
        self._settings.setValue(_folded_key(card.name), True)
        self._squeeze(card, sum(sizes))

    def _unfold(self, card: _Card) -> None:
        total = sum(self._split.sizes())
        sizes = self._open_column(total)
        self._open_sizes = None
        self._show_folded(card, False)
        self._settings.setValue(_folded_key(card.name), False)
        if sizes:
            self._split.setSizes(sizes)
        self.unfolded.emit()

    def _show_folded(self, card: _Card, folded: bool) -> None:
        card.folded = folded
        card.shell.setVisible(not folded)
        if folded:
            self._cap(card)
        else:
            card.frame.setMaximumHeight(_NO_CAP)
        self._dress()

    def _cap(self, card: _Card) -> None:
        card.frame.setMaximumHeight(card.frame.sizeHint().height())

    def _squeeze(self, card: _Card, total: int) -> None:
        """The freed height to the other card, now rather than on the splitter's next layout."""
        if total > 0:
            height = card.frame.maximumHeight()
            sizes = [total - height] * 2
            sizes[self._split.indexOf(card.frame)] = height
            self._split.setSizes(sizes)

    def _dress(self) -> None:
        folded = self._folded()
        handle = self._split.handle(1)
        if handle is not None:  # a folded card's border cannot move, so it does not offer to
            handle.setCursor(Qt.CursorShape.ArrowCursor if folded else Qt.CursorShape.SplitVCursor)
        for card in self._cards:
            refused = folded is not None and folded is not card
            card.arrow.setText("▸" if card.folded else "▾")
            card.arrow.setEnabled(not refused)
            key = "panelUnfold" if card.folded else "panelFoldRefused" if refused else "panelFold"
            card.arrow.hover_tip.set_text(i18n.t(key))

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt override)
        """A header's height follows its font: a theme, a zoom or a language asks for a layout."""
        if event.type() == QEvent.Type.LayoutRequest:
            folded = self._folded()
            if folded is not None and folded.frame is watched:
                self._cap(folded)
        return False
