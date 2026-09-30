"""«Режим контролю» (F-069): the layout for a session running in a terminal.

The Arbiter approved the prototype on 2026-09-23 with one condition — «головне щоб можна було
міняти розмір зон» — so the borders between the zones are what is tested hardest here.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QRect  # noqa: E402
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
    from PySide6.QtGui import QFontMetrics

    from autosound_tcc.ui.tcc.setting_status import DotTabBar

    _app()
    bar = DotTabBar()
    long = f'{i18n.t("copyEqBank")} m-Left-Tweeter-Front-Channel'
    bar.addTab(long)
    # 60 px, or -- where this font's first letter and «…» alone are wider (a stretch of 200 on
    # the Mac: «C…» is 79 px) -- just that: short of the text, room for a beginning.
    room = max(60, QFontMetrics(bar._font(0)).horizontalAdvance(long[:1] + "…") + 2)
    monkeypatch.setattr(bar, "tabRect", lambda _index: QRect(0, 0, room, 24))
    shown, width = bar.fit_text(0)
    assert shown != long, "genuinely shortened, not left whole"
    assert shown.endswith("…") and len(shown) > 1, "a whole glyph prefix, not a bare cut"
    assert width <= room, "never wider than the room it was given"

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

    The window is SHOWN and laid out at a width MEASURED to be roomy for this font (`_roomy`):
    on a window never shown, no layout hands the labels a width, `text()` stays whole under
    either policy, and a test reading it passes for nothing (the previous version of this test
    did exactly that). Measured, not 1600 px: that was roomy on the Mac and not on the Windows
    runner, whose offscreen text is twice as wide (fix round 5, CI run 36623891341)."""
    window = _window(tmp_path, monkeypatch)
    _with_rig(window)
    window.show()
    layout = window._control_layout
    layout.enter()
    layout.compare_combo.setCurrentIndex(layout.compare_combo.findData("SQ/v_004"))
    _settle(window, 1600)
    _settle(window, _roomy(window))
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


def _control_window(tmp_path, monkeypatch, lang="en", screen=1512):
    """Shown, in control mode, speaking `lang` -- set AFTER the window is built, which applies its
    own saved language as it starts -- on the Arbiter's 1512-px screen unless another is named:
    the offscreen platform's own is 800, too narrow to say anything about half a real screen,
    and these tests put the window at 756, its half."""
    window = _window(tmp_path, monkeypatch)
    i18n.set_language(lang)
    _arbiter_header(window)
    if screen is not None:
        _on_screen(window, monkeypatch, QRect(0, 0, screen, 982))
    window.show()
    window._control_layout.enter()
    return window


def _settle(window, width):
    """The window `width` px wide (or its floor, if more) once every layout has had its say. A
    resize is clamped to the floor the window has AT THAT MOMENT, and a pick in the corner moves
    the floor through every layout from the corner up to the window, one posted event each --
    so the resize goes again until it lands, as `_at_minimum` does."""
    for _ in range(4):
        window.resize(width, 900)
        for _ in range(4):
            QApplication.processEvents()
        if window.width() == width:
            break


def _corner_words(window):
    """What «порівняти з» and «інша конфігурація» show: the text, or None while hidden."""
    layout = window._control_layout
    return tuple(label.text() if label.isVisibleTo(window) else None
                 for label in (layout._compare_label, layout._compare_other))


def _header_asks(window):
    """The window widths at which the header can show «порівняти з» whole, and both labels
    whole: the header's ask with everything at its natural width -- what `_fit_corner` judges
    against -- plus what the window adds around the header. Read off the shown, laid-out window.

    Measured rather than assumed (fix round 5): 1600 px was roomy on the Mac and not on the
    Windows runner, whose offscreen text is twice as wide (Qt's FreeType font database finds no
    fonts there and draws every glyph as wide as the pixel size), so the tag stayed hidden at
    1600 and the flicker sweep started below both thresholds (CI run 36623891341)."""
    layout = window._control_layout
    corner = layout._corner
    header = corner.parentWidget()
    spacing = corner.layout().spacing()
    label, tag = layout._compare_label, layout._compare_other
    wants = {w: w.sizeHint().width() + spacing for w in (label, tag)}
    bare = header.sizeHint().width() - sum(n for w, n in wants.items() if not w.isHidden())
    around = window.width() - header.width()
    return bare + wants[label] + around, bare + wants[label] + wants[tag] + around


def _roomy(window):
    """A width with both labels' ask met and room to spare past the refit slack."""
    return _header_asks(window)[1] + 60


@pytest.mark.parametrize("lang", ["en", "uk"])
def test_the_corner_labels_are_whole_or_hidden_never_cut(tmp_path, monkeypatch, lang):
    """tcc#96, finding 105 -- the controller's ruling after measuring the second pass: at control
    mode's own width (756 px, half the Arbiter's 1512-px screen) «порівняти з» still read «пор…» /
    «compa…», and with another configuration picked «п…» beside «інша конфі…». Each label is now
    shown whole or not at all. What a hidden one said moves into the box: its hover says
    «порівняти з», and another configuration's version is shown with its preset's name,
    «3.S-shelf · v_002» (the open list's rows stay as #103 left them).

    "Roomy" is measured for the font at hand (`_roomy`), and "half a screen" is 756 px or the
    window's own floor where this font's header is wider than that (fix round 5: on the Windows
    runner's twice-as-wide offscreen text, 1600 px was not roomy and 756 not reachable)."""
    try:
        window = _control_window(tmp_path, monkeypatch, lang)
        layout = window._control_layout
        combo = layout.compare_combo
        full = (i18n.t("cmpWith"), i18n.t("cmpOtherTag"))
        _settle(window, 1600)
        for roomy in (True, False):
            for picked in ("v_001", "3.S-shelf/v_002"):
                combo.setCurrentIndex(combo.findData(picked))
                _settle(window, _roomy(window) if roomy else 756)
                words = _corner_words(window)
                if roomy:
                    assert words == (full[0], full[1] if "/" in picked else None), words
                assert all(w is None or w == f for w, f in zip(words, full)), (roomy, words)
                if words[0] is None:
                    assert i18n.t("cmpWith") in combo.hover_tip.text(), "the hidden word is kept"
        # Half a screen, another configuration picked. Both labels give way there unless the
        # font is narrow enough for «порівняти з» to fit whole, which the rule allows.
        with_label, _with_both = _header_asks(window)
        if window.width() + control_layout._REFIT_SLACK_PX < with_label:
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
    settles to one state. The sweep runs from 60 px above both labels' ask to 60 px below
    «порівняти з»'s, both measured for the font at hand (`_header_asks`; fix round 5 -- a sweep
    fixed at 1160–745 px started below both thresholds on the Windows runner)."""
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
    _settle(window, 1600)
    with_label, with_both = _header_asks(window)
    floor = window.minimumSizeHint().width()
    if with_label - 60 <= floor:
        pytest.skip(f"the window's floor ({floor} px) is above where «порівняти з» goes "
                    f"({with_label} px): no threshold to cross in this font")
    toggles = _Toggles()
    for label in (layout._compare_label, layout._compare_other):
        label.installEventFilter(toggles)
    widths = list(range(with_both + 60, with_label - 60, -5))
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


_LONG_PRESET = "5.W-wide-stage-for-rear-seat-A"  # 30 characters
_LONG_NAMES = "v_002 · P3, SQ-2, SQ-3, SQ-Comp-4"  # every name v_002 was saved under


@pytest.mark.parametrize("lang", ["en", "uk"])
@pytest.mark.parametrize("stretch", [100, 106, 110, 141])
def test_a_long_configuration_name_keeps_the_window_in_half_a_screen(
        tmp_path, monkeypatch, lang, stretch):
    """tcc#96, the controller's finding on the third pass: the box asked for the whole «<preset> ·
    <row>», and the window's floor grew with it one for one -- past 756 px (half the Arbiter's
    1512-px screen, where control mode puts the window) at about 28 characters, so the window
    stuck out past the screen's right edge. On the project line a row carries every name its
    version was saved under («v_002 · P3, SQ-2, SQ-3»). The box's floor is now «<preset> · v_NNN»
    and no more than a cap: the saved names give way first, then a preset name too long for the
    cap; the version stays, and the hover has the whole text.

    The cap is the box's `floor_cap()`: the letters «<13 letters> · v_NNN» take in its font (fix
    round 5), or what half the screen leaves the box after the rest of the header, whichever is
    less (the re-review: at a font stretched to 106, 108 and 110 -- the zoom's first steps --
    the letters alone put the 30-character preset's floor at 760, 771 and 780). The window
    stands on the Arbiter's 1512-px screen and the half is measured off it. It is checked where
    the header can sit in the half at all: on a font whose header is wider than that even with
    the smallest box -- the Windows runner's offscreen text, or a stretch of 141 -- the floor is
    the header's doing, not the box's, and the check is skipped and says so."""
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QComboBox

    app = _app()
    before = QFont(app.font())
    if stretch != 100:
        wide = QFont(before)
        wide.setStretch(stretch)
        app.setFont(wide)
    try:
        window = _control_window(tmp_path, monkeypatch, lang)
        assert len(_LONG_PRESET) == 30
        others = [("3.S-shelf", [("3.S-shelf/v_002", _LONG_NAMES), ("3.S-shelf/v_001", "v_001")]),
                  (_LONG_PRESET, [(f"{_LONG_PRESET}/v_002", "v_002")])]
        window._compare_args = window._compare_args[:4] + (others,) + window._compare_args[5:]
        layout = window._control_layout
        layout._fill_compare()
        combo = layout.compare_combo
        half = layout._right_half()[1].width()
        smallest = QComboBox.minimumSizeHint(combo).width()
        too_wide = []
        for key in ("3.S-shelf/v_002", f"{_LONG_PRESET}/v_002"):
            combo.setCurrentIndex(combo.findData(key))
            _settle(window, half)
            cap = combo.floor_cap()
            floor, box = window.minimumSizeHint().width(), combo.minimumSizeHint().width()
            assert box <= max(cap, smallest), (key, box, cap, smallest)
            shown, full = combo.fit_text(), combo.shown_text()
            if key.startswith("3.S"):
                # The saved names give way first; the preset too only where the cap leaves the
                # box less than «3.S-shelf · v_002…» (ubuntu's fonts on CI at 467c655: «3… ·
                # v_002» where this expected the preset whole) -- the version whole either way.
                base = QComboBox.minimumSizeHint(combo)
                held = combo._text_width("3.S-shelf · v_002…") + base.width() - combo._room(base)
                if box >= held:
                    assert shown.startswith("3.S-shelf · v_002"), \
                        f"the saved names give way: {shown}"
                assert shown.endswith(" · v_002") or shown.startswith("3.S-shelf · v_002"), shown
            else:
                # The version whole and the preset's beginning -- as much of it as the cap
                # leaves, never none (the Arbiter: cut is fine if the beginning shows). ubuntu's
                # fonts at a stretch of 141 (CI at 9bb37b7) leave «5… · v_002», where this
                # expected four letters: the Mac's metrics. Four only where the box holds them.
                assert shown.endswith(" · v_002"), shown
                head = shown[:-len(" · v_002")]
                assert head == _LONG_PRESET or (
                    len(head) > 1 and head.endswith("…") and _LONG_PRESET.startswith(head[:-1])), \
                    f"the preset's beginning shows: {shown}"
                base = QComboBox.minimumSizeHint(combo)
                held = combo._text_width("5.W-… · v_002") + base.width() - combo._room(base)
                if box >= held:
                    assert head.startswith("5.W-"), f"the box holds four letters: {shown}"
            assert full in combo.hover_tip.text(), "the whole text is in the hover"
            if floor > half and floor - box + smallest > half:
                too_wide.append((key, floor - box, smallest))
                continue
            assert floor <= half and window.width() == half, (key, floor, window.width(), cap)
        layout.leave()
        if too_wide:
            pytest.skip(f"this font's header does not sit in half a {1512}-px screen ({half}) "
                        f"with the smallest box (the zoom finding, not the box's cap): {too_wide}")
    finally:
        app.setFont(before)
        i18n.set_language("en")


def test_the_compare_box_s_floor_holds_a_typical_name_in_any_font():
    """tcc#96, fix round 5: the fourth pass capped the box's floor at 190 px, measured offscreen
    on the Mac. The Windows runner's offscreen text is twice as wide (Qt's FreeType font
    database finds no fonts there and draws every glyph as wide as the pixel size), and under
    that cap «3.S-shelf · v_002» came out «3.… · v_002» (CI run 36623891341). The cap is the
    width of «<13 letters> · v_NNN» in the box's own font now, so the same names fit whole at
    any font: the box's font is widened to about twice and four times here, and the picked name
    still shows whole with the box at its own floor.

    Whether the font widens at all is measured first (CI at f9d3a9e): the Windows runner's
    fontless offscreen text ignores the stretch, every cap came out 279 px, and "the cap follows
    the font" had nothing to follow there. The cap holding «<13 letters> · v_NNN» and the picked
    name whole are checked in every font; the growth only where the font grows."""
    import math

    from PySide6.QtGui import QFont, QFontMetricsF
    from PySide6.QtWidgets import QComboBox

    from autosound_tcc.ui.tcc.control_layout import _COMPARE_BOX_FLOOR_NAME, _CompareBox
    from autosound_tcc.ui.tcc.detail_pane import fill_compare_combo

    _app()
    caps, widths = [], []
    for stretch in (100, 141, 200):
        combo = _CompareBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(6)
        font = QFont(combo.font())
        font.setStretch(stretch)
        combo.setFont(font)
        fill_compare_combo(combo, ["v_001"], {"v_001": "v_001"},
                           [("3.S-shelf", [("3.S-shelf/v_002", "v_002")])], "4.C-cut", None)
        combo.setCurrentIndex(combo.findData("3.S-shelf/v_002"))
        combo.resize(combo.minimumSizeHint())
        held = QFontMetricsF(combo.font()).horizontalAdvance(f"{_COMPARE_BOX_FLOOR_NAME} · v_000")
        assert combo.floor_cap() >= math.ceil(held), (stretch, combo.floor_cap(), held)
        assert combo.minimumSizeHint().width() <= combo.floor_cap(), stretch
        assert combo.fit_text() == combo.shown_text() == "3.S-shelf · v_002", \
            (stretch, combo.fit_text())
        caps.append(combo.floor_cap())
        widths.append(held)
    if not widths[0] < widths[1] < widths[2]:
        pytest.skip(f"this font engine ignores the stretch (the floor name measures {widths}): "
                    f"no growth for the cap to follow, caps {caps}")
    assert caps[0] < caps[1] < caps[2], f"the cap follows the font: {caps}"


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


# ---- control mode's minimum holds «Таблиця-О» whole (tcc#107, finding 115) -----------------------

def _xo(freq, kind, slope):
    return {"f": freq, "type": kind, "slope": slope}


def _arbiter_outputs(lpf_mid=3500, hpf_tw=3500):
    """The Arbiter's outputs as his Helix profile declares them, with his crossovers: m-L/m-R's LPF
    and tw-L/tw-R's HPF at 3500 Hz, LR4 -- the cells that read «3500 …» at the minimum."""
    from autosound_tcc.state.dsp_state import ProjectView

    groups = [
        {"id": "virtual_channels", "label": "Virtual channels",
         "fields": ["gain_db", "ta_ms", "polarity", "phase_deg", "mute", "eq_bypass", "eq"]},
        {"id": "physical_outputs", "label": "Output channels",
         "fields": ["hp", "lp", "gain_db", "ta_ms", "polarity", "phase_deg", "mute", "eq"]},
    ]
    band = {"type": "PK", "f": 482, "gain_db": -1.7, "q": 3.0}
    channels = {
        "c": {"hp": _xo(714, "LR", 24), "lp": _xo(1897, "LR", 24), "gain_db": -8.5,
              "ta_ms": 1.95, "polarity": "NORM", "eq": [band] * 8},
        "m-L": {"hp": _xo(460, "BW", 24), "lp": _xo(lpf_mid, "LR", 24), "gain_db": -3.5,
                "ta_ms": 3.4, "polarity": "INV", "eq": [band] * 12},
        "m-R": {"hp": _xo(460, "BW", 24), "lp": _xo(lpf_mid, "LR", 24), "gain_db": 0.9,
                "ta_ms": 2.13, "polarity": "INV", "eq": [band] * 12},
        "sw": {"hp": None, "lp": _xo(88, "LR", 24), "gain_db": 0.0, "ta_ms": 0.0,
               "polarity": "NORM"},
        "tw-L": {"hp": _xo(hpf_tw, "LR", 24), "lp": None, "gain_db": -5.8, "ta_ms": 2.49,
                 "polarity": "INV", "eq": [band] * 10},
        "tw-R": {"hp": _xo(hpf_tw, "LR", 24), "lp": None, "gain_db": -4.2, "ta_ms": 15.75,
                 "polarity": "INV", "eq": [band] * 10},
        "w-L": {"hp": _xo(92, "LR", 12), "lp": _xo(215, "LR", 12), "gain_db": -0.3,
                "ta_ms": 4.33, "polarity": "NORM"},
    }
    identities = {name: {"code": name, "slot": slot, "tier": "channels"}
                  for name, slot in zip(channels, "BEFKLMC")}
    identities["VFL"] = {"code": "VFL", "slot": "A", "tier": "virtual_channels"}
    ledger = {"preset": "FULL", "sample_rate": 96000, "channels": channels,
              "virtual_channels": {"VFL": {"gain_db": 0.0}}}
    profile = {"dsp_profile": {"name": "Helix", "vendor": "Audiotec Fischer", "groups": groups}}
    return ProjectView.from_dict(ledger, profile, channels=identities)


def _with_arbiter_outputs(window):
    """His outputs, compared with the version before, where the crossovers stood elsewhere: the
    3500s are changed cells, drawn bold."""
    view = _arbiter_outputs()
    window._view = view
    window._tree.set_view(view)
    older = _arbiter_outputs(lpf_mid=3000, hpf_tw=4000)
    window._compare_args = (["v_006"], "v_006", lambda _key: older, {"v_006": "v_006"}, [])
    window._compare_key = "v_006"
    return view


class _Screen:
    """A screen with this free area: the offscreen one is 800 px wide, too narrow to say anything
    about half a real screen."""

    def __init__(self, free):
        self._free = QRect(free)

    def availableGeometry(self):  # noqa: N802 (Qt naming)
        return QRect(self._free)

    def geometry(self):
        return QRect(self._free)


def _on_screen(window, monkeypatch, free):
    monkeypatch.setattr(window, "screen", lambda: _Screen(free))


def _at_minimum(window):
    """The window at its own minimum width, once every layout has had its say."""
    for _ in range(4):
        window.resize(1, 900)
        for _ in range(4):
            QApplication.processEvents()
    return window.width()


def _cut_columns(table):
    """The output table's columns narrower than Qt's own ask for their heading and values."""
    header = table.horizontalHeader()
    return [(table.horizontalHeaderItem(c).text(), header.sectionSize(c),
             max(table.sizeHintForColumn(c), header.sectionSizeHint(c)))
            for c in range(table.columnCount())
            if header.sectionSize(c) < max(table.sizeHintForColumn(c), header.sectionSizeHint(c))]


def test_a_four_digit_crossover_reads_whole_at_control_mode_s_minimum(tmp_path, monkeypatch):
    """tcc#107, finding 115: at control mode's minimum the Arbiter read «3500 …» in m-L/m-R's LPF
    and tw-L/tw-R's HPF -- «розмір зробити трохи більше і ок». The minimum now holds the output
    table whole: every heading and value at Qt's own measure of it, whatever is compared. The
    screen is one whose half holds the table (the half-screen rule is the next test's); the
    widths are Qt's measures in the font at hand, so this holds on the Windows runner's wide
    offscreen text as well."""
    from PySide6.QtWidgets import QTableWidget

    window = _window(tmp_path, monkeypatch)
    _with_arbiter_outputs(window)
    _on_screen(window, monkeypatch, QRect(0, 0, 20000, 1000))
    window.show()
    layout = window._control_layout
    layout.enter()
    outputs = layout._index["physical_outputs"]
    layout.tabs.setCurrentIndex(outputs)
    combo = layout.compare_combo
    floors = []
    for picked in ("v_006", None):
        combo.setCurrentIndex(combo.findData(picked))
        floors.append(_at_minimum(window))
        table = layout.tabs.widget(outputs).findChild(QTableWidget)
        texts = {table.item(r, c).text() for r in range(table.rowCount())
                 for c in range(table.columnCount())}
        assert "3500 LR4" in texts
        assert not _cut_columns(table), (picked, window.width(), _cut_columns(table))
    assert floors[0] == floors[1], f"the minimum does not move with «порівняти з»: {floors}"
    layout.leave()


def test_the_table_s_floor_gives_way_at_half_a_screen(tmp_path, monkeypatch):
    """tcc#107 under tcc#96's rule: control mode's window sits in half a screen. Where half the
    screen cannot hold the output table whole, the table's floor stops there -- at the half as
    the window measures it, its frame counted (the review of #107/#110: a `<=` against a half
    that ignored the frame passed on the old code, and never said the cap was reached); the
    header's own floor is the header's doing (the zoom finding), not the table's."""
    window = _window(tmp_path, monkeypatch)
    _with_arbiter_outputs(window)
    _on_screen(window, monkeypatch, QRect(0, 0, 20000, 1000))
    window.show()
    layout = window._control_layout
    layout.enter()
    held = _at_minimum(window)
    layout.leave()

    half = held - 40
    _on_screen(window, monkeypatch, QRect(0, 0, 2 * half, 1000))
    layout.enter()
    floor = _at_minimum(window)
    rest = _rest_floor(window)
    assert floor == max(layout._right_half()[1].width(), rest), (floor, half, rest, held)
    layout.leave()


def _rest_floor(window):
    """The window's minimum from everything but control mode's zones: the header and the footer
    (the footer sets it at the default font, 697 px)."""
    root = window.centralWidget().layout()
    zones = window._control_layout.vertical
    rows = [root.itemAt(i).widget() for i in range(root.count())]
    header = window._layout_btn.parentWidget()
    return (max(w.minimumSizeHint().width() for w in rows
                if w is not None and w is not zones and w.isVisible())
            + window.width() - header.width())


# ---- control mode's window on the right half of its screen, full height (tcc#110, finding 118) ---

def _right_half_of(free):
    half = free.width() // 2
    return QRect(free.x() + half, free.y(), free.width() - half, free.height())


def _settled(window):
    for _ in range(8):
        QApplication.processEvents()


@pytest.mark.parametrize("free", [QRect(0, 0, 6000, 900), QRect(6000, 25, 6000, 875)],
                         ids=["one-screen", "a-second-screen-under-a-menu-bar"])
def test_control_mode_puts_its_frame_on_the_right_half_of_its_screen(tmp_path, monkeypatch, free):
    """tcc#110, finding 118: on the Windows VM control mode opened shifted left. The WINDOW'S
    FRAME takes the right half of the free area of the screen the window is on -- not past the
    middle line, not past the top, the bottom or the right edge -- and the left half stays free for
    the terminal. The screens are wide enough for this window in any font: placing it is what is
    tested, not its width. Leaving puts the full window back where it was."""
    window = _window(tmp_path, monkeypatch)
    _on_screen(window, monkeypatch, free)
    window.show()
    window.setGeometry(QRect(free.x() + 40, free.y() + 60, 1400, 700))
    _settled(window)
    before = window.geometry()
    window._control_layout.enter()
    _settled(window)
    frame, target = window.frameGeometry(), _right_half_of(free)
    assert target.left() <= frame.left() <= target.left() + 2, (frame, target)
    assert target.right() - 2 <= frame.right() <= target.right(), (frame, target)
    assert target.top() <= frame.top() <= target.top() + 2, (frame, target)
    assert target.bottom() - 2 <= frame.bottom() <= target.bottom(), (frame, target)
    window._control_layout.leave()
    _settled(window)
    assert window.geometry() == before


def test_a_windows_frame_is_kept_inside_the_right_half(tmp_path, monkeypatch):
    """tcc#110: Windows draws a title bar above the window's area and invisible resize borders at
    its sides and bottom (8 px there, 31 above, at 100 %), where the Mac draws a title bar only.
    The client area is what `setGeometry` places, so the frame is taken off it: the window's area
    is the right half less that frame. Offscreen Qt draws a 2-px frame, so the Windows one is
    stood in for here."""
    window = _window(tmp_path, monkeypatch)
    free = QRect(0, 0, 6000, 1000)
    _on_screen(window, monkeypatch, free)
    window.show()
    _settled(window)
    monkeypatch.setattr(window, "frameGeometry",
                        lambda: window.geometry().adjusted(-8, -31, 8, 8))
    window._control_layout.enter()
    _settled(window)
    assert window.geometry() == _right_half_of(free).adjusted(8, 31, -8, -8)
    window._control_layout.leave()


def test_a_maximised_window_goes_to_the_right_half_and_comes_back_maximised(tmp_path, monkeypatch):
    """tcc#110: a maximised window keeps its state through `setGeometry`, and Windows draws such a
    window as maximised at whatever rect it is given. It becomes a normal window on the right half
    first; leaving maximises it again, the full mode's own state as well as its geometry."""
    window = _window(tmp_path, monkeypatch)
    free = QRect(0, 0, 6000, 900)
    window.show()
    window.showMaximized()
    _settled(window)
    assert window.isMaximized()
    _on_screen(window, monkeypatch, free)
    window._control_layout.enter()
    _settled(window)
    assert not window.isMaximized()
    frame, target = window.frameGeometry(), _right_half_of(free)
    assert target.left() <= frame.left() <= target.left() + 2, (frame, target)
    assert target.bottom() - 2 <= frame.bottom() <= target.bottom(), (frame, target)
    window._control_layout.leave()
    _settled(window)
    assert window.isMaximized()


def test_a_window_maximised_in_control_mode_leaves_it_as_the_full_window_was(tmp_path, monkeypatch):
    """The review of #107/#110: the defect tcc#110 fixed on the way in, mirrored on the way out.
    A window the Arbiter maximised IN control mode is still maximised when `leave` restores the
    full window's geometry, and Windows draws a maximised window at whatever rect it is given.
    A normal window first; then the full window's own place and state -- normal, here."""
    window = _window(tmp_path, monkeypatch)
    free = QRect(0, 0, 6000, 900)
    _on_screen(window, monkeypatch, free)
    window.setGeometry(100, 50, 1300, 800)
    window.show()
    _settled(window)
    full = window.geometry()
    assert not window.isMaximized()
    window._control_layout.enter()
    _settled(window)
    window.showMaximized()
    _settled(window)
    assert window.isMaximized()
    window._control_layout.leave()
    _settled(window)
    assert not window.isMaximized(), "the full window was not maximised"
    assert window.geometry() == full, (window.geometry(), full)


def test_a_reload_that_raises_the_table_s_floor_keeps_a_flush_right_window_on_its_screen(
        tmp_path, monkeypatch):
    """The review of #107/#110: the output table's floor is held again when the tabs are rebuilt
    on a reload, and that happens on the event loop's next pass -- after the window's own check
    that a floor which rose keeps it on its screen (tcc#106). A control window at its minimum,
    flush right on a 1920-px screen, grew 9 px past the edge when a crossover went from 350 to
    3500 Hz. `_hold_table` asks the window to stay on its screen when it raises the floor."""
    window = _window(tmp_path, monkeypatch)
    free = QRect(0, 0, 1920, 1000)
    _on_screen(window, monkeypatch, free)
    monkeypatch.setattr(main_window, "_screen_room", lambda _widget: QRect(free))

    def load(lpf_mid, hpf_tw):
        view = _arbiter_outputs(lpf_mid=lpf_mid, hpf_tw=hpf_tw)
        window._view = view
        window._tree.set_view(view)
        older = _arbiter_outputs(lpf_mid=300, hpf_tw=400)
        window._compare_args = (["v_006"], "v_006", lambda _key: older, {"v_006": "v_006"}, [])
        window._compare_key = "v_006"

    load(350, 350)
    window.show()
    layout = window._control_layout
    layout.enter()
    narrow = _at_minimum(window)
    window.move(free.right() + 1 - window.frameGeometry().width(), 0)
    _settled(window)
    assert window.frameGeometry().right() == free.right(), "flush right"

    load(3500, 3500)
    layout.refresh()
    _settled(window)
    wide = _at_minimum(window)
    if wide <= narrow:
        pytest.skip(f"in this font the table's floor did not rise with the wider crossover "
                    f"({narrow} -> {wide} px): the rest of the window sets the minimum")
    frame = window.frameGeometry()
    assert frame.right() <= free.right() and frame.left() >= free.left(), (frame, free, narrow, wide)
    layout.leave()


@pytest.mark.parametrize("stretch", [100, 106, 110, 141])
def test_a_pick_at_the_half_never_pushes_the_window_past_it(tmp_path, monkeypatch, stretch):
    """The review of the follow-up: a long other-configuration pick at the half, at a font a
    little wider than the Mac's (stretch 106 -> 760 px, 110 -> 755 and then 780 on a second long
    pick, zoom 120% -> 763), left the window past the half for good, and the tests' `_settle`
    resized it back and hid it. The room the half left the box was read as "the header's
    minimum less the box's" -- a layout's cached number against a fresh one -- and ratcheted
    (247, 190, 162, 190, 218) through the layouts' posted events, so the window's minimum spiked,
    Qt grew the window, and nothing shrank it back. The rest of the header is summed from the
    other items themselves now. Picked at the half with NO resize after: the window stays at
    the half and its frame inside the screen, through a long pick, back, and a long pick again.
    Where the header does not sit in the half even with the smallest box (stretch 141) there is
    no half to keep, and the test says so."""
    from PySide6.QtGui import QFont

    app = _app()
    before = QFont(app.font())
    if stretch != 100:
        wide = QFont(before)
        wide.setStretch(stretch)
        app.setFont(wide)
    try:
        window = _control_window(tmp_path, monkeypatch)
        others = [("3.S-shelf", [("3.S-shelf/v_002", _LONG_NAMES), ("3.S-shelf/v_001", "v_001")]),
                  (_LONG_PRESET, [(f"{_LONG_PRESET}/v_002", "v_002")])]
        window._compare_args = window._compare_args[:4] + (others,) + window._compare_args[5:]
        layout = window._control_layout
        layout._fill_compare()
        _settled(window)
        combo, half = layout.compare_combo, layout._right_half()[1].width()
        free = window.screen().availableGeometry()
        if window.width() > half:
            pytest.skip(f"this font's header does not sit in half a 1512-px screen: the window "
                        f"is {window.width()} px wide at the half's {half} before any pick")
        assert window.width() == half and window.frameGeometry().right() <= free.right()
        for key in ("3.S-shelf/v_002", f"{_LONG_PRESET}/v_002", "v_001", f"{_LONG_PRESET}/v_002"):
            combo.setCurrentIndex(combo.findData(key))
            _settled(window)
            frame = window.frameGeometry()
            assert window.width() == half and frame.right() <= free.right(), (
                key, window.width(), half, frame, window.minimumWidth())
            assert combo.fit_text().endswith(combo.currentText()[:5]) or "v_00" in combo.fit_text()
        layout.leave()
    finally:
        app.setFont(before)
        i18n.set_language("en")


@pytest.mark.parametrize("lang", ["en", "uk"])
def test_control_mode_s_eq_chips_paint_what_they_say_at_the_half(tmp_path, monkeypatch, lang):
    """The re-review of fix round 1 (N1, CRITICAL) in control mode at the half, the Mac's font,
    the default setup -- finding 105's screenshot again: «← Tab», «⇅ Com», «Copy EQ», «⇄ L»
    drawn cut with no «…» where the round before had them whole; in Ukrainian «← Табл», «⇅ Пор»,
    «Копіювати Е». The paint rect was the contents rect less the chrome once more, 26 px short of
    where the label draws its own text. Each chip is grabbed at the half: its ink is the text
    `fit_text` names, present and ending where that text ends; and where the head has the room
    for its whole ask -- English at the Mac's font -- every chip is whole."""
    from tests.test_detail_pane import _paints_what_it_says

    window = _control_window(tmp_path, monkeypatch, lang)
    try:
        view = window._view
        layout = window._control_layout
        table_o = _tab(layout, i18n.t("ctlTableO"))
        layout.tabs.setCurrentIndex(table_o)
        names = [r.name for r in next(g for g in view.groups
                                      if g.id == "physical_outputs").rows_visible()]
        layout.tabs.currentWidget()._scroll.widget().cellClicked.emit(names.index("m-L"), 1)
        _settled(window)
        eq = layout.tabs.currentWidget()
        assert eq._row.name == "m-L" and eq._back_btn.isVisibleTo(window)
        chips = [eq._back_btn, eq._cmp_btn, eq._eq_copy, eq._pair_btn]
        assert all(chip.isVisibleTo(window) for chip in (*chips, eq._eq_help))
        # At the half -- or at the window's own floor where this font's header is wider than
        # the half (the runner's twice-as-wide text): the paint is checked either way.
        half = layout._right_half()[1].width()
        assert window.width() == max(half, window.minimumWidth()), (window.width(), half)
        # Not the «?»: it never elides, and its round border curves into its contents rect.
        fontless = {_paints_what_it_says(chip) for chip in chips} - {""}
        if fontless:
            layout.leave()
            pytest.skip(f"in {lang} the fit's rule held for every chip; the ink is not checked: "
                        f"{', '.join(sorted(fontless))}")
        # Whole where the head has the room for its ask -- English at the Mac's font does, by
        # one pixel (734 for an ask of 733), once the hint asks only what the paint needs. A
        # font whose ask is wider than the row (Ukrainian, or the runner's twice-as-wide text)
        # says so: the paint above is checked either way.
        ask, room = eq.head_asks()[0], eq._head.width()
        if room < ask:
            layout.leave()
            pytest.skip(f"in {lang} in this font the EQ head asks {ask} px of the {room} it has "
                        f"at the half: the chips elide, and the paint above is what is checked")
        assert all(chip.fit_text() == chip.text() for chip in chips), \
            [(c.text(), c.fit_text()) for c in chips]
        layout.leave()
    finally:
        i18n.set_language("en")
