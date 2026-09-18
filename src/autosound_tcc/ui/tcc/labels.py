"""The widgets that give ground instead of demanding room — `ElidedLabel`, `ElidedButton`.

Its own module because both the left panel's rows (`main_window._kv_row`, the channel switches)
and the panel's section headers (`sidebar_section`) need it, and `sidebar_section` is imported by
`main_window` rather than the other way round.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetricsF
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
)


class ElidedLabel(QLabel):
    """A label that shortens itself instead of demanding room.

    The side panels were widening on their own and pushing the right edge of a maximised window
    off the screen, because one long row -- `Amp (midbass (front) + center; 1 channel spare)` --
    asked for the width it wanted and Qt gave it. A key is the part that can be guessed from
    context; the value on the right is the fact, so the key is what gets cut first.

    The full text stays in the tooltip whenever anything was cut, so nothing is lost -- only moved
    behind a hover.
    """

    def __init__(
        self,
        text: str = "",
        min_width: int = 24,
        policy: QSizePolicy.Policy = QSizePolicy.Policy.Ignored,
        native_tooltip: bool = True,
    ) -> None:
        super().__init__(text)
        self._full = text
        self._min_width = min_width
        # `native_tooltip=False` for a label that sits INSIDE something which already explains
        # itself -- a DSP-tree channel row carries a rounded hover tip holding the same facts in
        # a fuller form, and a second, square, native tip on one of its lines is the same hint
        # twice in two shapes. The rule below (skip when the label itself has a rounded tip) does
        # not catch that case: the tip is on the parent, not on the label.
        self._native_tooltip = native_tooltip
        self.setMinimumWidth(min_width)
        # `Ignored` for a key: it takes whatever the row has left, however little. `Maximum` for a
        # value: it asks for its natural width and gets it whenever the panel is wide enough, and
        # only gives ground -- down to `min_width` -- when it would otherwise widen the panel.
        self.setSizePolicy(policy, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._full = text
        super().setText(text)
        # The layout has to be told the wanted width changed, or it keeps handing out room for
        # the old one -- see `sizeHint` for why that matters here more than usual.
        self.updateGeometry()
        self._elide()

    def sizeHint(self):  # noqa: N802 (Qt override)
        """The width the FULL text wants, not the width of what is currently drawn.

        QLabel computes its hint from the text it holds, and this widget replaces that text with a
        shortened one. That made a ratchet: the first `_elide` runs before the layout has given
        the label any width, so it cuts to `min_width`; the hint then reports the cut string; and
        a `Maximum` policy -- which asks for at most the hint -- never asks for more again. The
        header of a side panel came up reading "АУДІО АНАЛІЗ А…" and stayed that way with 60 px
        of empty room beside it (user, 2026-08-18, with the picture).

        Reporting the full text's width restores what the policy comment above always claimed:
        the label asks for its natural width and gives ground only when the panel truly cannot
        spare it. `Ignored` labels are unaffected -- a layout does not read their hint at all.
        """
        hint = super().sizeHint()
        metrics = self.fontMetrics()
        # The difference between the hint and the text it was measured from is the label's own
        # chrome (margins, indent, frame). Carried over rather than assumed to be zero.
        chrome = max(0, hint.width() - metrics.horizontalAdvance(super().text()))
        # Rounded UP from the fractional width: `elidedText` measures in fractions of a pixel, so
        # a text 177.08 px wide given the 177 it asked for lost its last letters (TODO F-045).
        wanted = math.ceil(QFontMetricsF(self.font()).horizontalAdvance(self._full))
        hint.setWidth(wanted + chrome)
        return hint

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        """Never more than `min_width`: this widget's whole promise is that it will shrink."""
        hint = super().minimumSizeHint()
        hint.setWidth(min(hint.width(), self._min_width))
        return hint

    def _elide(self) -> None:
        # `fontMetrics()` is the right measure even for the small-caps headers: `theme.apply_caps`
        # puts the uppercasing and the letter-spacing on the QFont (QSS ignores both), so they are
        # in the metrics rather than applied afterwards by the style.
        metrics = self.fontMetrics()
        shown = metrics.elidedText(
            self._full, Qt.TextElideMode.ElideRight, max(self.width(), self._min_width)
        )
        if shown != super().text():
            super().setText(shown)
        # Not when the widget already has one of the app's own rounded tips (`rounded_tooltip.
        # attach` leaves it as `hover_tip`): those are not Qt tooltips, so setting a native one
        # here would put TWO hints on the same widget, in two different shapes.
        if self._native_tooltip and getattr(self, "hover_tip", None) is None:
            self.setToolTip(self._full if shown != self._full else "")

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._elide()


class ElidedButton(QPushButton):
    """A button that comes down to its leading glyph instead of pushing the row off the edge.

    The footer's two right-hand buttons carry whole sentences -- `💬 Message the developer` --
    and a QPushButton asks for every pixel of its text and gives up none of them: the default
    `Minimum` policy has no shrink flag, so a layout hands it `sizeHint` even when the row has
    nothing left to hand out. Seven of the footer's ten controls were like that, and their sum
    became the WINDOW's minimum width: on Windows, where the UI text is wider, a window asked to
    be 1280 px came out 1454 and the two buttons sat past its edge (TODO F-060, CI 2026-09-18).

    Nothing changes while the row is roomy: `sizeHint` is still the full sentence, and a box
    layout gives a zero-stretch item exactly its hint whenever a stretch beside it can absorb the
    rest. Squeezed, the text elides, and the floor is the glyph on its own -- which is what the
    button looked like to everyone who ever clicked it without reading the words. Both of these
    are also in the main menu's help section in full, so nothing becomes unreachable.
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._full = text
        # `Preferred`, not the QPushButton default `Minimum`: only a policy carrying the shrink
        # flag lets a layout read `minimumSizeHint` at all (`qSmartMinSize`). The vertical half
        # stays `Fixed` -- this row's height is not in question.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._full = text
        super().setText(text)
        self.updateGeometry()

    def _short(self) -> str:
        """The leading glyph -- everything up to the first space, or the whole label if it has no
        space in it. The emoji is part of the translated string in both of these buttons."""
        head = self._full.split(" ", 1)[0]
        return head or self._full

    def _chrome(self) -> int:
        """What the button spends on something other than its text: padding, border, the style's
        own margins. Measured off the real hint rather than assumed, the way `ElidedLabel` does
        it, so a stylesheet change carries into this number instead of going unnoticed."""
        return max(0, super().minimumSizeHint().width()
                   - self.fontMetrics().horizontalAdvance(self._full))

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        hint = super().minimumSizeHint()
        hint.setWidth(self._chrome() + math.ceil(
            QFontMetricsF(self.font()).horizontalAdvance(self._short())))
        return hint

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Drawn elided, never re-`setText`-ed: changing the text would change the hint, the
        layout would hand out a different width, and the two would chase each other."""
        metrics = self.fontMetrics()
        room = max(0, self.width() - self._chrome())
        shown = metrics.elidedText(self._full, Qt.TextElideMode.ElideRight, room)
        if shown == self._full:
            super().paintEvent(event)
            self._tell_the_full_text(cut=False)
            return
        # `elidedText` walks down to "…" and then to nothing; the glyph is more use than either,
        # and `minimumSizeHint` above guarantees there is room for it.
        if metrics.horizontalAdvance(shown) < metrics.horizontalAdvance(self._short()):
            shown = self._short()
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = shown
        QStylePainter(self).drawControl(QStyle.ControlElement.CE_PushButton, option)
        self._tell_the_full_text(cut=True)

    def _tell_the_full_text(self, cut: bool) -> None:
        # Same rule as `ElidedLabel`: skip a widget that already carries one of the app's own
        # rounded tips, or the same words would hover over it twice in two shapes.
        if getattr(self, "hover_tip", None) is not None:
            return
        wanted = self._full if cut else ""
        if self.toolTip() != wanted:
            self.setToolTip(wanted)
