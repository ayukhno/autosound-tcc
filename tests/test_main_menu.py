"""G13 A2 (#161): one renderer draws the menu registry; a handler never sees Qt's `checked` flag."""

from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

from autosound_tcc.ui.tcc import i18n, main_menu, menu_registry, rounded_tooltip  # noqa: E402
from autosound_tcc.ui.tcc.main_menu import MainMenu  # noqa: E402
from autosound_tcc.ui.tcc.menu_registry import MenuEntry  # noqa: E402
from tests import _menu_pin  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


class _Host:
    """What the window offers the menu's predicates, and nothing else."""

    def __init__(self):
        self.running = False
        self.gate = "a"
        self._agent_worker = None

    def _effective_gate(self):
        return "auto"

    def _eq_order_pref(self):
        return "auto"


def _menu(entries, host=None):
    """A renderer on a bare button; the button rides on the renderer so it outlives the test."""
    _app()
    button = QToolButton()
    rendered = MainMenu(button, host or _Host(), lambda: entries)
    rendered.button = button
    return rendered


def test_a_handler_never_receives_qts_checked_flag():
    seen = []
    entries = [MenuEntry("plain", "project", label="Plain", on=lambda *args: seen.append(args)),
               MenuEntry("tick", "project", label="Tick", on=lambda *args: seen.append(args),
                         checked=lambda _w: False)]
    host = _Host()
    menu = _menu(entries, host)
    menu.render()

    menu.action("plain").trigger()
    menu.action("tick").trigger()  # a checkable line emits triggered(True)
    assert seen == [(host,), (host,)]

    menu.action("tick").setChecked(False)  # a tick moved by code is not a press
    menu.sync()
    assert seen == [(host,), (host,)]


def test_a_render_from_inside_an_entry_defers_the_old_menu():
    """The language switch's shape: the menu is rebuilt from inside its own line's handler, and
    destroying the menu that emitted the signal is the crash this app has paid for twice."""
    holder = {}
    entries = [MenuEntry("again", "project", label="Again", on=lambda _w: holder["menu"].render())]
    menu = holder["menu"] = _menu(entries)
    old = menu.render()

    menu.action("again").trigger()
    new = menu.button.menu()
    assert new is not old and shiboken6.isValid(old), "the old menu outlives its own handler"

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(old)
    assert menu.button.menu() is new and menu.action("again") in new.actions()


def test_sync_re_asks_enabled_and_checked():
    entries = [MenuEntry("save", "session", label="Save", on=print, enabled=lambda w: w.running),
               MenuEntry("gate_a", "session", label="A", on=print, checked=lambda w: w.gate == "a"),
               MenuEntry("gate_b", "session", label="B", on=print, checked=lambda w: w.gate == "b")]
    host = _Host()
    menu = _menu(entries, host)
    menu.render()
    save, a, b = (menu.action(i) for i in ("save", "gate_a", "gate_b"))
    assert (save.isEnabled(), a.isChecked(), b.isChecked()) == (False, True, False)

    host.running, host.gate = True, "b"
    menu.sync()
    assert (save.isEnabled(), a.isChecked(), b.isChecked()) == (True, False, True)


def test_headings_are_disabled_upper_case_lines():
    """Not `QMenu.addSection`, which draws nothing under a stylesheet: a disabled line in capitals."""
    menu = _menu([MenuEntry("one", "project", label="One", on=print)])
    drawn = menu.render()
    rows = _menu_pin.rows_of(drawn)
    headings = [row[2] for row in rows if row[1] == "heading"]
    assert headings == [i18n.t(key).upper() for _place, key in menu_registry.SECTIONS]
    assert [row[1] for row in rows[:3]] == ["heading", "line", "sep"]
    assert all(not a.isEnabled() for a in drawn.actions() if a.text() in headings)


def test_render_sets_the_aliases_the_tests_use():
    entries = [MenuEntry("intake", "project", label="Intake", on=print, alias="_intake_action"),
               MenuEntry("g2", "session", label="G2", on=print, checked=lambda _w: False,
                         alias="_gate_actions", alias_key="second"),
               MenuEntry("g1", "session", label="G1", on=print, checked=lambda _w: True,
                         alias="_gate_actions", alias_key="first", before="g2")]
    host = _Host()
    host._gate_actions = {"stale": None}
    menu = _menu(entries, host)
    menu.render()
    assert host._intake_action is menu.action("intake")
    assert list(host._gate_actions) == ["first", "second"], "render order, the old dict gone"
    assert host._gate_actions["first"] is menu.action("g1")

    first = host._intake_action
    menu.render()
    assert host._intake_action is menu.action("intake") and host._intake_action is not first


def test_the_window_s_lines_draw_today_s_menu():
    menu = _menu(menu_registry.window_entries())
    drawn = menu.render()
    assert _menu_pin.rows_of(drawn) == _menu_pin.pinned_rows()
    assert menu.button.menu() is drawn and drawn.property("class") == "support-menu"


def test_by_default_the_renderer_draws_every_provider_s_line(monkeypatch):
    feature = types.ModuleType("tcc_fake_menu_feature")
    feature.menu_entries = lambda: [MenuEntry("save_car", "project", label="Save the car…",
                                              on=print, before="intake")]
    monkeypatch.setitem(sys.modules, "tcc_fake_menu_feature", feature)
    monkeypatch.setattr(menu_registry, "PROVIDERS", ("tcc_fake_menu_feature",))
    _app()
    button = QToolButton()
    menu = MainMenu(button, _Host())
    texts = [a.text() for a in menu.render().actions()]
    assert texts[texts.index("Save the car…") + 1] == i18n.t("menuIntake")


def test_a_page_line_opens_its_address(monkeypatch):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    menu = _menu([MenuEntry("page", "help", label="Page", url=lambda: "https://example.invalid/p")])
    menu.render()
    menu.action("page").trigger()
    assert opened == ["https://example.invalid/p"]
    assert menu.action("no such line") is None


def test_a_tip_shows_in_the_rounded_popup_and_a_bare_line_hides_it():
    """The app's own rounded popup, not the platform tooltip whose frame stays square on macOS
    whatever the QSS says (user report 2026-07-28)."""
    menu = _menu([MenuEntry("tipped", "project", label="Tipped", tip_key="projectFreshSessionTip",
                            on=print),
                  MenuEntry("bare", "project", label="Bare", on=print)])
    menu.render()
    popup = rounded_tooltip.RoundedTooltip.instance()

    main_menu.show_action_tip(menu.action("tipped"))
    assert popup.isVisible()
    main_menu.show_action_tip(menu.action("bare"))
    assert not popup.isVisible()


def test_the_tip_follows_the_highlight_and_goes_with_the_menu():
    menu = _menu([MenuEntry("tipped", "project", label="Tipped", tip_key="projectFreshSessionTip",
                            on=print)])
    drawn = menu.render()
    popup = rounded_tooltip.RoundedTooltip.instance()
    drawn.hovered.emit(menu.action("tipped"))
    assert popup.isVisible()
    drawn.aboutToHide.emit()
    assert not popup.isVisible()


def test_a_predicate_that_fails_greys_its_line_and_the_rest_still_sync(caplog):
    """A line whose state cannot be asked is shown off and unticked, and said in the log; before,
    the first one stopped `sync()` and left «Save state» enabled with no gate or EQ tick."""
    def broken(_w):
        raise AttributeError("_view")

    host = _Host()
    entries = [MenuEntry("bad", "session", label="Bad", on=print, enabled=broken),
               MenuEntry("tick", "session", label="Tick", on=print, checked=broken),
               MenuEntry("save", "session", label="Save", on=print, enabled=lambda w: w.running)]
    menu = _menu(entries, host)
    menu.render()
    assert not menu.action("bad").isEnabled()
    assert not menu.action("tick").isEnabled() and not menu.action("tick").isChecked()
    host.running = True
    menu.sync()
    assert menu.action("save").isEnabled(), "a broken line does not stop the others"
    assert "'bad'" in caplog.text and "'tick'" in caplog.text


def test_a_render_says_what_is_wrong_with_its_lines(caplog):
    menu = _menu([MenuEntry("twice", "project", label="One", on=print),
                  MenuEntry("twice", "help", label="Two", on=print)])
    menu.render()
    assert "main menu" in caplog.text and "'twice'" in caplog.text
