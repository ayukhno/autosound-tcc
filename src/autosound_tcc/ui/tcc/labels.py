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
        self._elide()

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
        self.setToolTip(self._full if shown != self._full else "")

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._elide()
