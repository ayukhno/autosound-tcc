"""`ElidedLabel` — the one label in the app that gives ground instead of demanding room.

Its own module because both the left panel's rows (`main_window._kv_row`, the channel switches)
and the panel's section headers (`sidebar_section`) need it, and `sidebar_section` is imported by
`main_window` rather than the other way round.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy


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
    ) -> None:
        super().__init__(text)
        self._full = text
        self._min_width = min_width
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
        hint.setWidth(metrics.horizontalAdvance(self._full) + chrome)
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
        if getattr(self, "hover_tip", None) is None:
            self.setToolTip(self._full if shown != self._full else "")

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._elide()
