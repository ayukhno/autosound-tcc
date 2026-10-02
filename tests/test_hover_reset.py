"""Hover follows the mouse after the window was left for another app and back (tcc#137, finding 139)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF  # noqa: E402
from PySide6.QtGui import QEnterEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QVBoxLayout, QWidget  # noqa: E402

from autosound_tcc.ui.tcc import hover_reset  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window():
    """The finding's page in small: a box, and a button below it."""
    w = QWidget()
    layout = QVBoxLayout(w)
    box, button = QCheckBox("Beta channel"), QPushButton("Update")
    layout.addWidget(box)
    layout.addWidget(button)
    w.resize(300, 200)
    w.show()
    QApplication.processEvents()
    yield w, box, button
    w.close()
    w.deleteLater()


def _centre(window, widget) -> QPoint:
    return widget.mapTo(window, widget.rect().center())


def _enter(window, widget) -> None:
    """The platform saying the mouse came into the window over `widget`."""
    point = QPointF(_centre(window, widget))
    QApplication.sendEvent(window.windowHandle(),
                           QEnterEvent(point, point, QPointF(window.mapToGlobal(point.toPoint()))))


def test_leaving_the_window_for_another_app_drops_the_hover_it_held(window):
    w, box, _button = window
    reset = hover_reset.HoverReset(cursor_pos=lambda: w.mapToGlobal(QPoint(-50, -50)))
    _enter(w, box)
    assert box.underMouse()

    reset.eventFilter(w, QEvent(QEvent.Type.WindowDeactivate))

    # The Arbiter's VM: the box kept its orange ring after the switch to a terminal.
    assert not box.underMouse() and not w.underMouse()


def test_coming_back_gives_the_hover_to_what_is_under_the_cursor_now(window):
    w, box, button = window
    cursor = {"at": w.mapToGlobal(_centre(w, button))}
    reset = hover_reset.HoverReset(cursor_pos=lambda: cursor["at"])
    _enter(w, box)
    reset.eventFilter(w, QEvent(QEvent.Type.WindowDeactivate))

    reset.eventFilter(w, QEvent(QEvent.Type.WindowActivate))

    # «No hover worked on that page until another tab was chosen»: now the button has it at once.
    assert button.underMouse() and not box.underMouse()


def test_coming_back_with_the_cursor_outside_enters_nothing(window):
    w, box, button = window
    reset = hover_reset.HoverReset(cursor_pos=lambda: w.mapToGlobal(QPoint(-50, -50)))
    reset.eventFilter(w, QEvent(QEvent.Type.WindowActivate))

    assert not box.underMouse() and not button.underMouse()


def test_a_child_or_a_popup_is_left_alone(window):
    w, box, _button = window
    reset = hover_reset.HoverReset(cursor_pos=lambda: w.mapToGlobal(QPoint(-50, -50)))
    _enter(w, box)

    reset.eventFilter(box, QEvent(QEvent.Type.WindowDeactivate))

    assert box.underMouse(), "a child's own deactivate is not the window's"


def test_the_app_wide_filter_is_installed_and_lives_with_the_app():
    app = QApplication.instance()
    reset = hover_reset.install(app)
    try:
        assert reset.parent() is app
    finally:
        app.removeEventFilter(reset)
        reset.setParent(None)
