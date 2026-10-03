"""Hover follows the mouse after the window was left for another app and back (tcc#137, finding 139).

Driven through Qt's own activation path, not by calling the filter by hand (night review of #137,
M3): the order Qt sends activate and deactivate in is half of what decides the hover, and a test
that picks the order itself cannot see it. Another app is a bare QWindow taking the focus: Qt then
has no active widget window, as when the focus goes to another process, and coming back is
`activateWindow()` -- as is a switch between two of TCC's own windows.
"""

from __future__ import annotations

import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QCursor, QEnterEvent, QWindow  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.ui.tcc import hover_reset  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_hover_filter_left_on_the_app():
    """The conftest fixture of this name makes `install` a no-op for every other file, so an
    `app.main()` in one test leaves no app-wide filter for the next (night review, M4). This file
    is the one that tests `install`, so it gets the real one -- and takes off what it put on."""
    app = QApplication.instance()
    before = set(app.findChildren(hover_reset.HoverReset))
    yield
    for left in set(app.findChildren(hover_reset.HoverReset)) - before:
        app.removeEventFilter(left)
        left.setParent(None)
        left.deleteLater()


@pytest.fixture(autouse=True)
def _cursor_parked():
    """The offscreen cursor stays where the last test left it, and Qt gives a widget shown under it
    the hover by itself. Parked in a corner no window here reaches, so only the test moves it."""
    QCursor.setPos(QPoint(5, 790))
    QApplication.processEvents()


def _page(x: int, y: int, name: str):
    """The finding's page in small: a box, and a button below it."""
    w = QWidget()
    w.setObjectName(name)
    layout = QVBoxLayout(w)
    box, button = QCheckBox("Beta channel"), QPushButton("Update")
    layout.addWidget(box)
    layout.addWidget(button)
    w.setGeometry(x, y, 300, 200)
    w.show()
    QApplication.processEvents()
    return w, box, button


@pytest.fixture
def window():
    w, box, button = _page(20, 40, "main")
    yield w, box, button
    w.close()
    w.deleteLater()


@pytest.fixture
def other():
    """A second TCC window beside the first, not over it: the diagnostics, say."""
    w, _box, _button = _page(400, 40, "other")
    yield w
    w.close()
    w.deleteLater()


def _centre(window, widget) -> QPoint:
    return widget.mapTo(window, widget.rect().center())


def _activate(w) -> None:
    w.activateWindow()
    QApplication.processEvents()


@pytest.fixture
def elsewhere():
    """Another app, as Qt sees one: a focus window that is no widget of ours, away from the rest."""
    window = QWindow()
    window.setGeometry(700, 700, 50, 50)
    window.show()
    yield window
    window.destroy()


def _to_another_app(elsewhere) -> None:
    """The focus goes to another app: no widget window of ours is active."""
    elsewhere.requestActivate()
    QApplication.processEvents()
    assert QApplication.activeWindow() is None


def _hover(window, widget) -> None:
    """The mouse moved onto `widget`."""
    QTest.mouseMove(window, _centre(window, widget))
    QApplication.processEvents()


def test_leaving_the_window_for_another_app_drops_the_hover_it_held(window, elsewhere):
    w, box, _button = window
    hover_reset.install(QApplication.instance())
    _activate(w)
    _hover(w, box)
    assert box.underMouse()

    _to_another_app(elsewhere)

    # The Arbiter's VM: the box kept its orange ring after the switch to a terminal.
    assert not box.underMouse() and not w.underMouse()


def test_coming_back_gives_the_hover_to_what_is_under_the_cursor_now(window, elsewhere):
    w, box, button = window
    cursor = {"at": w.mapToGlobal(QPoint(-50, -50))}
    hover_reset.install(QApplication.instance(), cursor_pos=lambda: cursor["at"])
    _activate(w)
    _hover(w, box)
    _to_another_app(elsewhere)
    # Away, the mouse went over the button: the platform tells an inactive window nothing.
    cursor["at"] = w.mapToGlobal(_centre(w, button))

    _activate(w)

    # «No hover worked on that page until another tab was chosen»: now the button has it at once.
    assert button.underMouse() and not box.underMouse()


def test_coming_back_with_the_cursor_outside_enters_nothing(window, elsewhere):
    w, box, button = window
    hover_reset.install(QApplication.instance(), cursor_pos=lambda: w.mapToGlobal(QPoint(-50, -50)))
    _to_another_app(elsewhere)

    _activate(w)

    assert not box.underMouse() and not button.underMouse()


def test_a_switch_between_two_of_our_windows_keeps_the_hover(window, other):
    """Night review, I1: Qt activates the new window BEFORE it deactivates the old one, and a leave
    sent to the old window clears Qt's one app-wide record of where the mouse is -- the hover the
    new window had just been given. The platform sends no new enter, because the mouse never left.
    Closing the diagnostics, a modal, a keyboard switch: every switch between TCC's own windows."""
    w, _box, button = window
    hover_reset.install(QApplication.instance())
    _activate(other)
    _hover(w, button)

    _activate(w)
    QTest.mouseMove(w, _centre(w, button) + QPoint(1, 1))  # one more move on the button
    QApplication.processEvents()

    assert button.underMouse()


def test_coming_back_under_another_window_enters_nothing_beneath_it(window):
    """Night review, M1: the cursor inside this window's rectangle is not the cursor over it when
    another window covers that point -- the diagnostics over the main window. The widget under it
    would keep a stale hover until the mouse crossed it again."""
    w, _box, button = window
    cover, _cbox, _cbutton = _page(20, 40, "cover")  # made later, so it is the one on top
    try:
        where = w.mapToGlobal(_centre(w, button))
        hover_reset.install(QApplication.instance(), cursor_pos=lambda: where)
        assert QApplication.topLevelAt(where) is cover
        _activate(cover)
        assert not button.underMouse()

        _activate(w)

        assert not button.underMouse()
    finally:
        cover.close()
        cover.deleteLater()


def test_a_child_is_left_alone(window):
    """A child sees its window's activate and deactivate too; only the window itself answers."""
    w, box, _button = window
    reset = hover_reset.HoverReset(cursor_pos=lambda: w.mapToGlobal(QPoint(-50, -50)))
    point = QPointF(_centre(w, box))
    QApplication.sendEvent(w.windowHandle(),
                           QEnterEvent(point, point, QPointF(w.mapToGlobal(point.toPoint()))))
    assert box.underMouse()

    reset.eventFilter(box, QEvent(QEvent.Type.WindowDeactivate))

    assert box.underMouse(), "a child's own deactivate is not the window's"


def test_a_popup_keeps_its_own_hover():
    """A menu or a combo's list keeps its hover while it is open, and closes on deactivation."""
    popup = QWidget(None, Qt.WindowType.Popup)
    layout = QVBoxLayout(popup)
    item = QPushButton("Item")
    layout.addWidget(item)
    popup.setGeometry(20, 40, 200, 100)
    popup.show()
    QApplication.processEvents()
    try:
        reset = hover_reset.HoverReset(cursor_pos=lambda: popup.mapToGlobal(QPoint(-50, -50)))
        QTest.mouseMove(popup, _centre(popup, item))
        QApplication.processEvents()
        assert item.underMouse()

        reset.eventFilter(popup, QEvent(QEvent.Type.WindowDeactivate))

        assert item.underMouse()
    finally:
        popup.close()
        popup.deleteLater()


def test_one_filter_for_the_app_and_it_lives_without_a_python_reference(window, elsewhere):
    """Installed once, in `app.main`; a second call hands back the first rather than stacking a
    second filter (M4). Its parent keeps it: with the Python reference dropped, a switch away
    still drops the hover."""
    w, box, _button = window
    app = QApplication.instance()
    assert hover_reset.install(app) is hover_reset.install(app)
    gc.collect()
    _activate(w)
    _hover(w, box)

    _to_another_app(elsewhere)

    assert not box.underMouse()
    assert len(app.findChildren(hover_reset.HoverReset)) == 1
