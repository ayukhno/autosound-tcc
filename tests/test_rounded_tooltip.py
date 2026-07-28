"""Headless test for the channel-hint popup (user report 2026-07-28): a WA_TranslucentBackground
top-level widget's QSS `background` isn't reliably composited by the style engine -- verified
empirically, it silently painted nothing at all, leaving hint text floating with no backing box
over whatever was underneath. `RoundedTooltip.paintEvent` paints the rounded rect manually instead;
this guards against that regressing silently again.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autosound_tcc.ui.tcc.rounded_tooltip import RoundedTooltip  # noqa: E402
from autosound_tcc.ui.tcc.theme import apply_theme  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_show_at_paints_an_opaque_rounded_box_not_a_fully_transparent_one():
    app = _app()
    apply_theme(app, "dark", scale=1.0)
    tip = RoundedTooltip.instance()
    tip.show_at(QPoint(0, 0), "<b>A · Front L Full</b><br>Gain +0.0dB")
    app.processEvents()

    img = tip.grab().toImage()
    w, h = img.width(), img.height()
    assert w > 0 and h > 0

    # Corner: outside the rounded rect path -- must stay transparent (that's what makes the
    # corner *look* rounded rather than a square box with a rounded rect drawn inside it).
    assert img.pixelColor(0, 0).alpha() == 0

    # Center: inside the fill -- must be opaque. Before the fix this was 0 too (nothing painted
    # at all), which is the actual bug report (hint text floating over the tree with no box).
    assert img.pixelColor(w // 2, h - 3).alpha() == 255

    tip.hide_tip()
