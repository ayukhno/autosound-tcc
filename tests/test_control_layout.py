"""«Режим контролю» (F-069): the layout for a session running in a terminal.

The Arbiter approved the prototype on 2026-09-23 with one condition — «головне щоб можна було
міняти розмір зон» — so the borders between the zones are what is tested hardest here.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
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
    # Not locked on the monitor: a project opens on it, and the Arbiter could not pick a version
    # until he went to another tab (2026-09-26: «давай не обмежувати вибір»).
    assert corner.isEnabled(), "the choice is open on every tab"
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

    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    layout = window._control_layout
    layout.enter()
    bar = layout.tabs.tabBar()

    def dot(text):
        return bar.dot(_tab(layout, text))

    assert dot(i18n.t("ctlTableO")) == "chg", "m-L's gain moved since v_006"
    assert dot(i18n.t("ctlTableV")) == "set"
    assert dot(i18n.t("tabPhase")) == "none"
    assert dot(i18n.t("ctlMonitor")) is None
    assert bar.tabToolTip(_tab(layout, i18n.t("ctlTableO"))) == i18n.t("dotChg").format(
        version="v_006 · FULL-2"), "the whole tab carries the hint"

    layout.compare_combo.setCurrentIndex(layout.compare_combo.findData(None))
    assert dot(i18n.t("ctlTableO")) == "set", "nothing compared, nothing blue"
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



def test_a_narrow_tab_elides_its_label_instead_of_cutting_it_mid_word(tmp_path, monkeypatch):
    """tcc#96, finding 105. Corrected per an opus reviewer's pass on the first fix (IMPORTANT 3):
    the earlier version of this test resized the WHOLE WINDOW to 420 px, but a `MainWindow` here
    cannot go below its own real minimum offscreen (697 px, in English and in Ukrainian alike) --
    the resize is silently clamped, so the eliding branch never actually ran and the test passed
    for nothing.

    A bare `DotTabBar` resized directly does not reliably reproduce genuine per-tab squeeze
    either: measured by hand (see the fix report), Qt's own tab layout on this platform/style
    settles each tab at a floor that still comfortably fits ordinary tab text, however much
    narrower the bar itself is made beyond that -- there may be a REAL narrow-window path to
    genuine squeeze on the Arbiter's own Mac, but it was not reproducible here. `tabRect` is
    forced directly instead, which is what the reviewer's suggested alternative ("set the tab
    bar... to a fixed width smaller than its text") comes down to when the bar's own layout will
    not cooperate -- and tests `fit_text`'s own eliding computation deterministically."""
    from PySide6.QtCore import QRect

    from autosound_tcc.ui.tcc.setting_status import DotTabBar

    _app()
    bar = DotTabBar()
    long = f'{i18n.t("copyEqBank")} m-Left-Tweeter-Front-Channel'
    bar.addTab(long)
    monkeypatch.setattr(bar, "tabRect", lambda _index: QRect(0, 0, 60, 24))
    shown, width = bar.fit_text(0)
    assert shown != long, "genuinely shortened, not left whole"
    assert shown.endswith("…") and len(shown) > 1, "a whole glyph prefix, not a bare cut"
    assert width <= 60, "never wider than the room it was given"

    # With real room, nothing is touched at all.
    monkeypatch.setattr(bar, "tabRect", lambda _index: QRect(0, 0, 2000, 24))
    shown2, _width2 = bar.fit_text(0)
    assert shown2 == long


def test_the_compare_box_gets_no_floor_below_its_own_minimum(tmp_path, monkeypatch):
    """tcc#96, finding 105 -- IMPORTANT 1, an opus reviewer's pass on the first fix: that pass set
    an explicit `setMinimumWidth`, which turned out to REPLACE `minimumSizeHint` as the layout's
    floor even when it is SMALLER (measured: a 34 px guessed chrome constant pulled the effective
    floor down from the combo's own ~121 px to ~98 -- lower than before the fix, not higher).
    Nothing is set explicitly now, so nothing can undercut it; `QComboBox.minimumSizeHint()`
    already equals `sizeHint()` (asserted below, which is what makes it a real floor an ordinary
    layout will not shrink the box past on its own).

    With the Arbiter's header shown, the box measures 121 px and is never empty down to the
    window's own minimum (697 px, in English and in Ukrainian alike)."""
    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    layout = window._control_layout
    layout.enter()
    combo = layout.compare_combo
    assert combo.minimumWidth() == 0, "no explicit override to undercut the natural floor"
    assert combo.minimumSizeHint() == combo.sizeHint(), "QComboBox's own floor IS its sizeHint"
    layout.leave()


def test_the_corner_labels_ask_for_their_own_width_not_zero(tmp_path, monkeypatch):
    """tcc#96, finding 105 -- CRITICAL 1, an opus reviewer's pass on the first fix: `ElidedLabel`
    defaults to `QSizePolicy.Ignored`, which asks the layout for ZERO width of its own and grows
    only into whatever the row's OTHER items leave over -- this row has its own explicit stretch
    (`head_layout.addStretch(1)`, `main_window.py`) competing for exactly that leftover space, so
    the label got none of it. Measured (English): «compare with» read «c…» and «another
    configuration» «a…» at 1600, 1000 and 756 px alike. `Maximum` -- `ElidedLabel`'s own
    documented "value" mode -- asks for the label's natural width instead.

    The window is SHOWN and laid out at a roomy 1600 px: on a window never shown, no layout hands
    the labels a width, `text()` stays whole under either policy, and a test reading it passes
    for nothing (the previous version of this test did exactly that)."""
    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    window.show()
    layout = window._control_layout
    layout.enter()
    layout.compare_combo.setCurrentIndex(layout.compare_combo.findData("SQ/v_004"))
    window.resize(1600, 900)
    for _ in range(4):
        QApplication.processEvents()
    assert layout._compare_other.isVisibleTo(window), "another preset picked: its tag is up"
    assert layout._compare_label.text() == i18n.t("cmpWith"), layout._compare_label.text()
    assert layout._compare_other.text() == i18n.t("cmpOtherTag"), layout._compare_other.text()
    layout.leave()


_OTHERS = ("3.S-shelf", "5.M-mid", "6.W-wide", "7.E-epy")


def _arbiter_header(window):
    """The header the Arbiter works in (tcc#96, finding 105): the project, the open preset and its
    slot, a target link, and «порівняти з» over the preset's own two versions and four other
    configurations' (#103)."""
    _with_rig(window)
    window._project_label.setText("⌂ passat-b8-2026-aya")
    window._preset_combo.addItem("4.C-cut")
    window._show_slot_and_save("P4", "")
    window._target_label.setText("SQ-Comp ↗")
    window._compare_args = (
        ["v_002", "v_001"], "v_001", lambda _key: _older(), {"v_002": "v_002", "v_001": "v_001"},
        [(p, [(f"{p}/v_002", "v_002"), (f"{p}/v_001", "v_001")]) for p in _OTHERS],
        "4.C-cut", "v_002")
    window._compare_key = "v_001"


def _control_window(tmp_path, monkeypatch, lang="en"):
    """Shown, in control mode, speaking `lang` -- set AFTER the window is built, which applies its
    own saved language as it starts."""
    window = _window(tmp_path, monkeypatch)
    i18n.set_language(lang)
    _arbiter_header(window)
    window.show()
    window._control_layout.enter()
    return window


def _settle(window, width):
    window.resize(width, 900)
    for _ in range(4):
        QApplication.processEvents()


def _corner_words(window):
    """What «порівняти з» and «інша конфігурація» show: the text, or None while hidden."""
    layout = window._control_layout
    return tuple(label.text() if label.isVisibleTo(window) else None
                 for label in (layout._compare_label, layout._compare_other))


@pytest.mark.parametrize("lang", ["en", "uk"])
def test_the_corner_labels_are_whole_or_hidden_never_cut(tmp_path, monkeypatch, lang):
    """tcc#96, finding 105 -- the controller's ruling after measuring the second pass: at control
    mode's own width (756 px, half the Arbiter's 1512-px screen) «порівняти з» still read «пор…» /
    «compa…», and with another configuration picked «п…» beside «інша конфі…». Each label is now
    shown whole or not at all. What a hidden one said moves into the box: its hover says
    «порівняти з», and another configuration's version is shown with its preset's name,
    «3.S-shelf · v_002» (the open list's rows stay as #103 left them)."""
    try:
        window = _control_window(tmp_path, monkeypatch, lang)
        layout = window._control_layout
        combo = layout.compare_combo
        full = (i18n.t("cmpWith"), i18n.t("cmpOtherTag"))
        for width in (1600, 756):
            for picked in ("v_001", "3.S-shelf/v_002"):
                combo.setCurrentIndex(combo.findData(picked))
                _settle(window, width)
                words = _corner_words(window)
                if width == 1600:
                    assert words == (full[0], full[1] if "/" in picked else None), words
                assert all(w is None or w == f for w, f in zip(words, full)), (width, words)
                if words[0] is None:
                    assert i18n.t("cmpWith") in combo.hover_tip.text(), "the hidden word is kept"
        # 756 px, another configuration picked:
        assert _corner_words(window) == (None, None), "half a screen: both give way"
        assert combo.shown_text() == "3.S-shelf · v_002", "the picked version names its preset"
        assert combo.fit_text() == combo.shown_text(), "and shows it whole"
        assert combo.itemText(combo.currentIndex()) == "v_002", "the list's own row is unchanged"
        assert i18n.t("cmpOtherTip").format(version="3.S-shelf · v_002") in combo.hover_tip.text()
        layout.leave()
    finally:
        i18n.set_language("en")


def test_the_corner_labels_settle_and_do_not_flicker_at_their_threshold(tmp_path, monkeypatch):
    """Shown or hidden is decided from the header's width against what the header asks for WITH
    the label, and a hidden label comes back only with room to spare: resized a few pixels at a
    time across both thresholds and back, each label changes once each way, and every width
    settles to one state."""
    from PySide6.QtCore import QEvent, QObject

    class _Toggles(QObject):
        count = 0

        def eventFilter(self, _watched, event):  # noqa: N802 (Qt override)
            if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
                self.count += 1
            return False

    window = _control_window(tmp_path, monkeypatch)
    layout = window._control_layout
    layout.compare_combo.setCurrentIndex(layout.compare_combo.findData("3.S-shelf/v_002"))
    toggles = _Toggles()
    for label in (layout._compare_label, layout._compare_other):
        label.installEventFilter(toggles)
    widths = list(range(1160, 740, -5))
    seen = []
    for width in widths + widths[::-1]:
        _settle(window, width)
        toggles.count = 0
        for _ in range(4):
            QApplication.processEvents()
        assert toggles.count == 0, f"still toggling at {width} px"
        seen.append(tuple(w is not None for w in _corner_words(window)))
    down, up = seen[:len(widths)], seen[len(widths):]
    assert down[0] == up[-1] == (True, True), "roomy: both whole"
    assert down[-1] == up[0] == (False, False), "half a screen and less: both give way"
    for states in (down, up):
        for which in (0, 1):
            run = [s[which] for s in states]
            assert sum(run[i] != run[i - 1] for i in range(1, len(run))) == 1, run
    rising = widths[::-1]
    for which in (0, 1):
        went = next(widths[i] for i in range(1, len(down)) if down[i][which] != down[i - 1][which])
        back = next(rising[i] for i in range(1, len(up)) if up[i][which] != up[i - 1][which])
        assert back - went >= 10, f"label {which}: gone at {went} px, back at {back} px"
    layout.leave()


def test_a_squeezed_compare_box_settles_at_its_floor_not_below(tmp_path, monkeypatch):
    """The same box, built the same way `_build_corner` builds it, sharing a row with a widget
    that demands far more room than the row can give -- a real, if artificial, squeeze (a whole
    `MainWindow` cannot be forced this narrow offscreen, per the test above)."""
    from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

    _app()
    container = QWidget()
    row = QHBoxLayout(container)
    hungry = QLabel("x" * 400)
    combo = QComboBox()
    combo.setProperty("class", "mini-select")
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(6)
    combo.addItem("v_006 · SQ-Comp")
    row.addWidget(hungry)
    row.addWidget(combo)
    container.resize(120, 30)
    container.show()
    for _ in range(5):
        QApplication.processEvents()

    assert combo.width() >= combo.minimumSizeHint().width(), \
        "never squeezed past its own floor even when a sibling wants everything"
    assert combo.width() > 0 and combo.currentText(), "the box still has something to show"


def test_the_tab_dots_sit_close_to_the_text(tmp_path, monkeypatch):
    """Finding 71, 1: on macOS a tab button sits at the tab's very edge whatever the stylesheet
    says (the Arbiter's screenshot after 8fbbab6), so the bar draws the dot itself, just after the
    text, the same on every platform."""
    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    layout = window._control_layout
    layout.enter()
    bar = layout.tabs.tabBar()
    for text in ("EQ", i18n.t("tabDelay"), i18n.t("ctlTableV")):
        index = _tab(layout, text)
        text_rect, dot_rect = bar.label_geometry(index)
        assert 0 <= dot_rect.left() - text_rect.right() <= 7, text
        assert bar.tabRect(index).right() - dot_rect.right() >= 5, "not at the edge"
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


def test_building_the_tabs_shows_no_window_of_its_own(tmp_path, monkeypatch):
    """Finding 104 (tcc#62): entering «Режим контролю» on Windows flashed many small windows, and
    leaving did not. Each tab's `DetailPane` was built with no parent and shown at once
    (`_embedded`, then `open_table`/`open_eq`), and a widget with no parent that is shown IS a
    window — one per tab, for the moment before the tab took it."""
    from PySide6.QtCore import QEvent, QObject

    window = _window(tmp_path, monkeypatch)
    shown = []

    class Spy(QObject):
        def eventFilter(self, obj, event):  # noqa: N802
            if event.type() == QEvent.Type.Show and getattr(obj, "isWindow", lambda: False)() \
                    and obj is not window:
                shown.append(type(obj).__name__)
            return False

    spy = Spy()
    QApplication.instance().installEventFilter(spy)
    try:
        pane = control_layout._embedded(window, getattr(window, "_view", None))
        assert not pane.isWindow(), "an embedded pane is never a window of its own"
        window._control_layout.enter()
    finally:
        QApplication.instance().removeEventFilter(spy)
        window._control_layout.leave()
    assert "DetailPane" not in shown, shown
