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


def test_show_at_does_not_raise_the_tip_because_on_macos_that_activates_tcc(monkeypatch):
    """Finding 79 again (tcc#71): «Налаштувати omp…» opened the terminal, and TCC came back over
    it a moment later. The button's hover tip was shown with `raise_()`, and Qt's macOS `raise()`
    activates the whole application (`QT_MAC_SET_RAISE_PROCESS`, on by default). Measured on the
    Arbiter's Mac 2026-09-27: the terminal in front, a tip shown with `raise_()` 0.3 s later put
    the app in front again, and the same tip shown without it did not. A `ToolTip` window is
    already above the others, so the raise bought nothing."""
    _app()
    tip = RoundedTooltip.instance()
    raised = []
    monkeypatch.setattr(tip, "raise_", lambda: raised.append(True))
    tip.show_at(QPoint(0, 0), "tip")
    tip.hide_tip()
    assert raised == []


def _owner():
    from PySide6.QtWidgets import QWidget

    owner = QWidget()
    owner.setGeometry(100, 100, 200, 60)
    owner.show()
    _app().processEvents()
    return owner


def test_a_tip_hides_when_tcc_stops_being_the_active_app():
    """Finding 87 (tcc#78): switched to another app, the tip stayed on top of it. It hides only on
    the owner's leave event, and switching apps sends none."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QCursor

    app = _app()
    owner = _owner()
    QCursor.setPos(owner.mapToGlobal(owner.rect().center()))
    tip = RoundedTooltip.instance()
    tip.show_at(QCursor.pos(), "tip", owner=owner)
    assert tip.isVisible()
    app.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
    assert not tip.isVisible()
    owner.close()


def test_a_tip_hides_when_its_owner_is_gone_or_the_cursor_has_left_it():
    """Finding 87: «висить над ТСС хоч миша вже в іншому місці» — a dialog closed or a row rebuilt
    under the cursor sends no leave either. While shown, the tip checks its owner."""
    from PySide6.QtGui import QCursor

    owner = _owner()
    tip = RoundedTooltip.instance()
    QCursor.setPos(owner.mapToGlobal(owner.rect().center()))
    tip.show_at(QCursor.pos(), "tip", owner=owner)
    tip._check_owner()
    assert tip.isVisible(), "the cursor is still on the owner: the tip stays"

    QCursor.setPos(owner.mapToGlobal(owner.rect().bottomRight()) + QPoint(50, 50))
    tip._check_owner()
    assert not tip.isVisible()

    QCursor.setPos(owner.mapToGlobal(owner.rect().center()))
    tip.show_at(QCursor.pos(), "tip", owner=owner)
    owner.hide()
    tip._check_owner()
    assert not tip.isVisible()
    owner.close()


def test_hover_tip_names_its_widget_as_the_owner():
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QCursor, QEnterEvent

    from autosound_tcc.ui.tcc.rounded_tooltip import attach

    owner = _owner()
    attach(owner, "hint")
    QCursor.setPos(owner.mapToGlobal(owner.rect().center()))
    local = QPointF(owner.rect().center())
    owner.enterEvent(QEnterEvent(local, local, QPointF(QCursor.pos())))
    tip = RoundedTooltip.instance()
    assert tip.isVisible()
    owner.hide()
    tip._check_owner()
    assert not tip.isVisible()
    owner.close()
