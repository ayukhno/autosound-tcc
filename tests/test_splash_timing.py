"""The splash must outlive the empty window, not the `show()` call (tcc#27)."""

from __future__ import annotations

from autosound_tcc.app import _wait_until_painted


def test_it_waits_while_the_window_is_not_painted_yet():
    """`QSplashScreen.finish(window)` waits for the window to be SHOWN, and on Windows `show()`
    returns long before anything is drawn. Caught on video, 2026-09-09: the splash said "building
    the window", vanished, and left a blank white rectangle with a spinner where the app should
    be — which is what reads as a flash."""
    painted = iter([False, False, True])
    spun = []

    _wait_until_painted(
        is_painted=lambda: next(painted),
        pump=lambda: spun.append(True),
        budget_s=5.0,
        now=iter([0.0, 0.1, 0.2, 0.3]).__next__,
    )

    assert len(spun) == 2, "it pumps the event loop until the window has drawn"


def test_it_gives_up_rather_than_holding_the_app_hostage():
    """A window that never reports itself painted must not keep the splash on screen forever. The
    budget is small on purpose: a late splash is untidy, a stuck one is a hang."""
    spun = []
    clock = iter([0.0, 1.0, 2.0, 9.0]).__next__

    _wait_until_painted(
        is_painted=lambda: False, pump=lambda: spun.append(True), budget_s=1.5, now=clock
    )

    assert spun, "it tried"
    assert len(spun) < 5, "and stopped when the budget ran out"


# --- naming the window that flashes (tcc#28) -------------------------------------------------


class _W:
    def __init__(self, name, visible, title="", w=200, h=800, known=False):
        self._n, self._v, self._t, self._w, self._h = name, visible, title, w, h
        self.known = known

    def isVisible(self):
        return self._v

    def windowTitle(self):
        return self._t

    def width(self):
        return self._w

    def height(self):
        return self._h

    def metaObject(self):
        class _M:
            def className(_s):
                return self._n
        return _M()


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, fmt, *args):
        self.lines.append(fmt % args)


class _App:
    def __init__(self, *widgets):
        self._widgets = widgets

    def topLevelWidgets(self):
        return list(self._widgets)


def _watch(monkeypatch, known):
    from autosound_tcc import app as app_module

    log = _Log()
    monkeypatch.setitem(app_module._STRAY, "log", log)
    monkeypatch.setitem(app_module._STRAY, "known", known)
    monkeypatch.setitem(app_module._STRAY, "seen", set())
    return app_module._note_strays, log


def test_it_names_a_stray_top_level_window(monkeypatch):
    """Caught on video, 2026-09-09: a narrow tall window with a title bar and the app's name
    appears OVER the painted main window and vanishes. A frame means it is not the splash; the
    name means Qt supplied it, i.e. a widget of ours was shown before it had a parent — which Qt
    turns into a top-level window.

    4 400 lines of window code is too many to find that by reading, so it names itself."""
    main = _W("MainWindow", True)
    note, log = _watch(monkeypatch, [main])

    note(_App(main, _W("QLabel", True, title="Autosound TCC")))

    window_lines = [line for line in log.lines if " window: " in line]
    assert [line.split(" window: ")[0] for line in window_lines] == ["own", "stray"]
    assert "QLabel 200x800 'Autosound TCC'" in window_lines[1]


def test_it_says_nothing_about_windows_that_are_not_shown(monkeypatch):
    main = _W("MainWindow", True)
    note, log = _watch(monkeypatch, [main])

    note(_App(_W("QDialog", False)))

    assert [line for line in log.lines if " window: " in line] == []


def test_it_reports_each_shape_once(monkeypatch):
    note, log = _watch(monkeypatch, [])
    app = _App(_W("QLabel", True))

    note(app)
    note(app)

    assert len([line for line in log.lines if line.startswith("stray window: ")]) == 1
