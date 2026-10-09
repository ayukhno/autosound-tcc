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

from autosound_tcc.ui.tcc.rounded_tooltip import RoundedTooltip, tip_html  # noqa: E402
from autosound_tcc.ui.tcc.theme import apply_theme, current_theme  # noqa: E402


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


# ---- `tip_html`, the markup these tips are written in (#177, TA-7) ---------------------------


def _tip_div(body: str) -> str:
    return f'<div style="font-size: 15px; color: {current_theme().text}">{body}</div>'


def test_tip_html_escapes_the_text_and_sets_it_large():
    assert tip_html("Plain & <simple>") == _tip_div("Plain &amp; &lt;simple&gt;")


def test_tip_html_puts_a_bold_head_on_its_own_line():
    assert tip_html("body", head="Head <b>") == _tip_div("<b>Head &lt;b&gt;</b><br>body")


def test_tip_html_colours_head_and_body_when_it_warns():
    warn = current_theme().warn
    assert tip_html("x", head="H", warn=True) == _tip_div(
        f'<span style="color: {warn}"><b>H</b><br>x</span>')


def test_tip_html_wraps_at_72_characters_by_hand():
    """The shared tip label does not wrap, so the text arrives broken into lines. At 72, counted
    before escaping: the first line is 72 long and would break at 71, and the next paragraph's
    first line is 70 and would take its next word at 73. A hyphenated word and an over-long one
    stay whole, and a blank line stays a blank line."""
    text = (
        "Delay the chosen trace by one step & the predicted sum follows it on the screen, while "
        "the readout says what the DSP <would> be set to.\n"
        "Delay the chosen trace by a single step & the predicted sum follows it on screen.\n"
        "The level line is read where it crosses each curve, nearest the middle-of-the-screen "
        "point.\n\n" + "w" * 80 + " end"
    )

    assert tip_html(text) == _tip_div("<br>".join([
        "Delay the chosen trace by one step &amp; the predicted sum follows it on the",
        "screen, while the readout says what the DSP &lt;would&gt; be set to.",
        "Delay the chosen trace by a single step &amp; the predicted sum follows it",
        "on screen.",
        "The level line is read where it crosses each curve, nearest the",
        "middle-of-the-screen point.",
        "",
        "w" * 80,
        "end",
    ]))
