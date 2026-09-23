"""«Режим контролю» (F-069): the layout for a session running in a terminal.

The Arbiter approved the prototype on 2026-09-23 with one condition — «головне щоб можна було
міняти розмір зон» — so the borders between the zones are what is tested hardest here.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSplitter, QTabWidget  # noqa: E402

from autosound_tcc.core import config  # noqa: E402
from autosound_tcc.ui.tcc import control_layout, i18n, main_window  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path, monkeypatch, store=None):
    _app()
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "chosen_project_dir", lambda: tmp_path)
    monkeypatch.setattr(control_layout, "place_terminal_left", lambda *a, **k: None)
    window = main_window.MainWindow()
    # Leave the mode with the test: the feed's timer would otherwise keep reading a project folder
    # that belongs to the next test.
    monkeypatch.setattr(control_layout.MonitorFeed, "refresh", lambda self: None)
    if store is not None:
        monkeypatch.setattr(window._settings, "setValue", lambda k, v: store.__setitem__(k, v))
        monkeypatch.setattr(window._settings, "value", lambda k, d=None, **kw: store.get(k, d))
    return window


def test_entering_and_leaving_puts_every_panel_back(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    left, right, bar = window._left, window._right, window._dialog.confirm_bar
    home = bar.parentWidget()
    window._control_layout.enter()
    assert window._control_layout.active
    assert not window._main_splitter.isVisible() or window._main_splitter.isHidden()
    assert left.parentWidget() is not window._main_splitter
    window._control_layout.leave()
    assert not window._control_layout.active
    assert left.parentWidget() is window._main_splitter
    assert right.parentWidget() is window._main_splitter
    assert bar.parentWidget() is home


def test_the_top_window_carries_the_tabs_the_arbiter_named(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    window._control_layout.enter()
    tabs = window._control_layout.tabs
    names = [tabs.tabText(i) for i in range(tabs.count())]
    assert names == [i18n.t("ctlMonitor"), i18n.t("ctlTableV"), i18n.t("ctlTableO"), "EQ",
                     i18n.t("tabGain"), i18n.t("tabDelay"), i18n.t("tabPhase")]


def test_both_borders_move_and_their_sizes_are_remembered(tmp_path, monkeypatch):
    """«Головне щоб можна було міняти розмір зон» (the Arbiter, 2026-09-23)."""
    store = {}
    window = _window(tmp_path, monkeypatch, store)
    layout = window._control_layout
    layout.enter()
    assert isinstance(layout.vertical, QSplitter) and isinstance(layout.horizontal, QSplitter)
    assert not layout.vertical.childrenCollapsible() and not layout.horizontal.childrenCollapsible()
    layout.vertical.setSizes([300, 500])
    layout.horizontal.setSizes([250, 550])
    # What the splitters actually hold — Qt fits the asked sizes to the space it has.
    held = (layout.vertical.sizes(), layout.horizontal.sizes())
    layout.remember_sizes()
    layout.leave()
    assert layout.saved_sizes() == held, "left where the Arbiter left them, across a leave"

    layout.enter()
    ratio = held[0][0] / sum(held[0])
    now = layout.vertical.sizes()
    assert abs(now[0] / sum(now) - ratio) < 0.05, "and opened that way again"


def test_the_mode_is_remembered_per_project(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    window._on_layout_toggle()
    assert window._project_setting(main_window._LAYOUT_KEY) == "control"
    window._on_layout_toggle()
    assert window._project_setting(main_window._LAYOUT_KEY) == "gui"


def test_the_switch_waits_while_a_session_runs_in_this_window(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    window._agent_worker = object()
    try:
        window._sync_layout_button()
        assert not window._layout_btn.isEnabled()
    finally:
        window._agent_worker = None
    window._sync_layout_button()
    assert window._layout_btn.isEnabled()


def test_the_tables_follow_a_reloaded_project(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    layout = window._control_layout
    layout.enter()
    built = []
    monkeypatch.setattr(control_layout, "_table_tab", lambda *a, **k: built.append(a) or
                        control_layout.QLabel("x"))
    layout.refresh()
    assert len(built) == 2, "Таблиця-V and Таблиця-О rebuilt from the new view"
    assert isinstance(layout.tabs, QTabWidget) and layout.tabs.count() == 7



def test_a_project_left_in_control_mode_opens_in_it(tmp_path, monkeypatch):
    from autosound_tcc.core import project_settings

    project_settings.set_value(config.tcc_dir(tmp_path), main_window._LAYOUT_KEY, "control")
    window = _window(tmp_path, monkeypatch)
    for _ in range(5):
        QApplication.processEvents()
    assert window._control_layout.active
    assert window._layout_btn.text() == i18n.t("layoutActive")
    window._control_layout.leave()


def test_no_in_app_session_starts_in_control_mode(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    window._control_layout.enter()
    launched = []
    monkeypatch.setattr(window, "_launch_session", lambda *a, **k: launched.append(1))
    window._start_tuning_session()
    assert launched == []
    window._control_layout.leave()


def test_the_feed_follows_the_newest_line_until_the_arbiter_scrolls_up(tmp_path, monkeypatch):
    """It opened on its oldest line: the browser scrolls itself back to the top while it lays text
    out, and that was read as the Arbiter scrolling away."""
    import json as _json

    from PySide6.QtWidgets import QAbstractSlider

    _app()
    monkeypatch.setattr(config, "project_dir", lambda: tmp_path)
    (tmp_path / "process").mkdir()
    lines = [_json.dumps({"at": f"2026-09-23T10:{n % 60:02d}:00", "type": "capture_taken",
                          "title": f"m-L_{n} (sw)"}) for n in range(80)]
    (tmp_path / "process" / "journal.jsonl").write_text("\n".join(lines), encoding="utf-8")
    feed = control_layout.MonitorFeed(window=None)
    feed.resize(400, 200)
    feed.show()
    for _ in range(5):
        QApplication.processEvents()
    bar = feed._feed.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == bar.maximum()

    bar.triggerAction(QAbstractSlider.SliderAction.SliderPageStepSub)
    for _ in range(3):
        QApplication.processEvents()
    held = bar.value()
    assert held < bar.maximum()
    feed.refresh()
    for _ in range(3):
        QApplication.processEvents()
    assert not feed._follow, "scrolled up to read: the feed does not pull him back down"
    feed.close()
