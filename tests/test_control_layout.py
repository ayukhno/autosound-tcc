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


# ---- the tables in control mode (the Arbiter, 2026-09-25: findings 47, 65, 66; tcc#51) ---------

def _with_rig(window, inputs=True):
    """A loaded project: the window's view, and «порівняти з» offering one older version."""
    from tests.test_detail_pane import _rig_with_eq

    view = _rig_with_eq(inputs=inputs)
    window._view = view
    window._tree.set_view(view)
    window._compare_args = (["v_006"], "v_006", lambda _key: _older(), {"v_006": "v_006 · FULL-2"},
                            [("SQ", [("SQ/v_004", "v_004 · SQ-2")])])
    window._compare_key = "v_006"
    return view


def _older():
    """The same rig one version back: m-L's gain was -4.0."""
    from tests.test_detail_pane import _rig_with_eq

    view = _rig_with_eq(inputs=True)
    outputs = next(g for g in view.groups if g.id == "physical_outputs")
    rows = tuple(r if r.name != "m-L" else type(r)(id=r.id, name=r.name, slot=r.slot,
                                                   raw=dict(r.raw, gain_db=-4.0))
                 for r in outputs.rows)
    groups = tuple(g if g.id != "physical_outputs" else type(g)(
        id=g.id, label=g.label, fields=g.fields, rows=rows) for g in view.groups)
    return type("Older", (), {"groups": groups})()


def _tab(layout, text):
    return next(i for i in range(layout.tabs.count()) if layout.tabs.tabText(i) == text)


def test_the_input_table_has_its_own_tab_when_the_rig_has_inputs(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    layout = window._control_layout
    layout.enter()
    names = [layout.tabs.tabText(i) for i in range(layout.tabs.count())]
    assert names == [i18n.t("ctlMonitor"), i18n.t("ctlTableV"), i18n.t("ctlTableO"),
                     i18n.t("ctlTableI"), "EQ", i18n.t("tabGain"), i18n.t("tabDelay"),
                     i18n.t("tabPhase")]
    layout.leave()


def test_no_tab_carries_a_menu_of_its_own_and_one_compare_serves_them_all(tmp_path, monkeypatch):
    """Finding 47, 1, 3 and 4."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane

    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    layout = window._control_layout
    layout.enter()
    corner = layout._corner
    assert layout.compare_combo.parentWidget() is corner
    assert corner.parentWidget() is window._layout_btn.parentWidget(), \
        "in the header, above the tabs: half a screen holds the tabs or the list, not both"
    for i in range(layout.tabs.count()):
        pane = layout.tabs.widget(i)
        if isinstance(pane, DetailPane):
            shown = [w for w in (pane._tab_table, pane._tab_eq, pane._close_btn,
                                 pane._compare_combo, *pane._param_tabs.values())
                     if w.isVisibleTo(pane)]
            assert not shown, layout.tabs.tabText(i)
    layout.tabs.setCurrentIndex(0)
    assert not corner.isEnabled(), "the monitor has nothing to compare"
    layout.tabs.setCurrentIndex(_tab(layout, i18n.t("ctlTableO")))
    assert corner.isEnabled()
    layout.leave()
    assert corner.parentWidget() is None, "leaving takes the list out of the header"


def test_a_row_opens_the_eq_tab_and_the_back_button_returns(tmp_path, monkeypatch):
    """Finding 47, 5 — the main point: the EQ tab shows that channel, the way back is named."""
    window = _window(tmp_path, monkeypatch)
    view = _with_rig(window)
    layout = window._control_layout
    layout.enter()
    table_o = _tab(layout, i18n.t("ctlTableO"))
    layout.tabs.setCurrentIndex(table_o)
    pane = layout.tabs.currentWidget()
    names = [r.name for r in next(g for g in view.groups
                                  if g.id == "physical_outputs").rows_visible()]
    pane._scroll.widget().cellClicked.emit(names.index("m-L"), 1)
    QApplication.processEvents()

    assert layout.tabs.tabText(layout.tabs.currentIndex()) == "EQ"
    eq = layout.tabs.currentWidget()
    assert eq._row.name == "m-L"
    assert eq._back_btn.text() == "← " + i18n.t("ctlTableO")
    assert pane._mode == "table", "the table tab is still a table"
    eq._back_btn.clicked.emit()
    assert layout.tabs.currentIndex() == table_o
    layout.leave()


def test_the_eq_tab_shows_an_eq(tmp_path, monkeypatch):
    """Finding 47, 5: «the EQ tab itself shows the output table, not the EQ»."""
    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    layout = window._control_layout
    layout.enter()
    eq = layout.tabs.widget(_tab(layout, "EQ"))
    assert eq._mode == "eq" and eq._row is not None
    layout.leave()


def test_the_left_panel_opens_its_table_and_its_eq_in_the_tabs(tmp_path, monkeypatch):
    """Finding 47, 2: «params» opened no table in control mode, and EQ did nothing."""
    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    layout = window._control_layout
    layout.enter()
    window._on_table_requested("virtual_channels")
    assert layout.tabs.tabText(layout.tabs.currentIndex()) == i18n.t("ctlTableV")
    window._on_table_requested("inputs")
    assert layout.tabs.tabText(layout.tabs.currentIndex()) == i18n.t("ctlTableI")
    window._on_eq_requested("physical_outputs", "c")
    eq = layout.tabs.currentWidget()
    assert layout.tabs.tabText(layout.tabs.currentIndex()) == "EQ" and eq._row.name == "c"
    assert not eq._back_btn.isVisibleTo(eq), "opened from the tree: no table to go back to"
    window._on_channel_clicked("physical_outputs", "m-R")
    assert layout.tabs.tabText(layout.tabs.currentIndex()) == i18n.t("ctlTableO")
    layout.leave()


def test_one_compare_drives_every_tab_and_the_dots(tmp_path, monkeypatch):
    """Findings 47, 4 and 65."""
    from autosound_tcc.ui.tcc.detail_pane import DetailPane
    from autosound_tcc.ui.tcc.setting_status import StatusDot

    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    layout = window._control_layout
    layout.enter()
    bar = layout.tabs.tabBar()

    def dot(text):
        from PySide6.QtWidgets import QTabBar

        return bar.tabButton(_tab(layout, text), QTabBar.ButtonPosition.RightSide)

    assert isinstance(dot(i18n.t("ctlTableO")), StatusDot)
    assert dot(i18n.t("ctlTableO")).status() == "chg", "m-L's gain moved since v_006"
    assert dot(i18n.t("ctlTableV")).status() == "set"
    assert dot(i18n.t("tabPhase")).status() == "none"
    assert dot(i18n.t("ctlMonitor")) is None

    layout.compare_combo.setCurrentIndex(layout.compare_combo.findData(None))
    assert dot(i18n.t("ctlTableO")).status() == "set", "nothing compared, nothing blue"
    panes = [layout.tabs.widget(i) for i in range(layout.tabs.count())
             if isinstance(layout.tabs.widget(i), DetailPane)]
    assert all(p._compare_view is None for p in panes)

    layout.compare_combo.setCurrentIndex(layout.compare_combo.findData("SQ/v_004"))
    assert layout._compare_other.isVisibleTo(layout._corner), "another preset, said"
    assert all(p._compare_view is not None for p in panes)
    layout.leave()


def test_the_tree_groups_carry_status_dots(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    window._sync_status_dots()
    dots = window._tree.status_dots()
    assert dots["physical_outputs"].status() == "chg"
    assert dots["virtual_channels"].status() == "set"
    assert dots["inputs"].status() == "set"


def test_the_tree_lights_what_the_tabs_show(tmp_path, monkeypatch):
    """«Поточна група активна!» (the Arbiter on the prototype, 2026-09-25)."""
    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    layout = window._control_layout
    layout.enter()
    layout.tabs.setCurrentIndex(_tab(layout, i18n.t("ctlTableO")))
    assert window._tree.active() == ("physical_outputs", "params")
    section = window._tree._sections["physical_outputs"]
    assert "act" in section._params_row.property("class").split()
    window._on_eq_requested("physical_outputs", "c")
    assert window._tree.active() == ("physical_outputs", "c")
    assert "act" not in section._params_row.property("class").split()
    layout.tabs.setCurrentIndex(0)
    assert window._tree.active() == (None, None)
    layout.leave()


def test_the_tree_lights_what_the_full_window_s_pane_shows(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    window._on_table_requested("virtual_channels")
    assert window._tree.active() == ("virtual_channels", "params")
    window._on_eq_requested("physical_outputs", "m-L")
    assert window._tree.active() == ("physical_outputs", "m-L")
    window._detail.close_pane()
    assert window._tree.active() == (None, None)


def test_the_target_link_stays_clear_of_the_compare_list(tmp_path, monkeypatch):
    """Finding 67, 1: at half a screen the header's widgets ran over each other — «SQ-Comp» on top
    of «порівняти з». The link moves left, up to the preset field; nothing overlaps."""
    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    window._preset_combo.addItem("1.B-base")
    window._show_slot_and_save("", "")
    window._target_label.setText("SQ-Comp ↗")
    window.show()
    layout = window._control_layout
    layout.enter()
    window.resize(756, 900)
    for _ in range(3):
        QApplication.processEvents()
    target, corner = window._target_label.geometry(), layout._corner.geometry()
    assert target.right() < corner.left(), (target, corner)
    assert not window._save_label.isVisibleTo(window), "an empty label takes no room"
    layout.leave()



def test_the_tab_dots_sit_close_to_the_text(tmp_path, monkeypatch):
    """Finding 71, 1 (after 67, 3 put them at the edge)."""
    from PySide6.QtWidgets import QTabBar

    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    layout = window._control_layout
    layout.enter()
    dot = layout.tabs.tabBar().tabButton(_tab(layout, "EQ"), QTabBar.ButtonPosition.RightSide)
    assert not dot.align_right
    layout.leave()


def test_a_tier_with_nothing_in_it_has_no_tab_and_no_tree_group(tmp_path, monkeypatch):
    """Finding 71, 4: «Таблиця-I» with no inputs, and «ВХОДИ 0» in the left panel."""
    from tests.test_detail_pane import _rig_with_eq

    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    view = _rig_with_eq(empty_inputs=True)
    window._view = view
    window._tree.set_view(view)
    assert "inputs" not in window._tree._sections
    layout = window._control_layout
    layout.enter()
    names = [layout.tabs.tabText(i) for i in range(layout.tabs.count())]
    assert i18n.t("ctlTableI") not in names
    layout.leave()
