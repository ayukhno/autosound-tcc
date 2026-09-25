"""«Режим контролю» — the window's layout while the tuning session runs in a terminal (F-069).

The Arbiter's description (2026-09-22, DECISIONS-W-2 A9–A13), approved as a prototype on
2026-09-23 with one condition: «головне щоб можна було міняти розмір зон».

* One button toggles «Активний TCC» / «Режим контролю»; the choice is remembered per project.
* TCC takes the right half of the screen; the terminal goes on the left half (macOS: the front
  Terminal window, best effort).
* The top zone is full width, with tabs: «Моніторинг» (what TCC sees of the terminal session —
  the process journal it writes — plus the two bus buttons), «Таблиця-V», «Таблиця-О», «Таблиця-I»
  when the rig has inputs, then EQ, level, delays, phases.
* The tabs ARE the navigation (the Arbiter, 2026-09-25, finding 47): no tab carries the full
  window's menu or «Закрити ✕»; one «порівняти з» sits by the tabs and drives them all; a row
  opens the EQ tab on its channel, with «← Таблиця-О» back; the tree's «params» and EQ open their
  tabs here. Each tab carries a status dot (finding 65). The list sits in the window's header,
  just left of «Активний TCC»: half a screen holds the eight tabs with their dots, not the list
  beside them as well (measured offscreen 2026-09-25: ~690 px of tabs + ~250 px of list).
* TCC's own confirmation strip sits above the tabs; it shows itself only when a request arrives
  (the terminal auto-confirms by default).
* Below, the left and right panels side by side. Both borders — top/bottom and left/right — are
  dragged, and where they were left is remembered for the next time.

Everything shown is the window's own panels, moved rather than copied: leaving the mode puts
each of them back where it was.
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import config
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.detail_pane import (
    DetailPane,
    eq_field_order,
    fill_compare_combo,
    is_other_preset,
)
from autosound_tcc.ui.tcc.setting_status import DotTabBar, field_status, group_status, tip_for

#: How many journal events the feed shows, newest last.
_FEED_EVENTS = 80
#: Where the two borders were left, per machine (a screen's size is the machine's, not the project's).
_SIZES_KEY_V = "ui/control_layout/vertical"
_SIZES_KEY_H = "ui/control_layout/horizontal"
_DEFAULT_V = [420, 480]
_DEFAULT_H = [1, 1]


def _event_line(event: dict) -> str:
    """One journal event as one line of the feed — time, kind, and the one field that says what."""
    at = html.escape(str(event.get("at") or "")[11:16])
    kind = html.escape(str(event.get("type") or "?"))
    what = (event.get("name") or event.get("title") or event.get("step") or event.get("question")
            or event.get("phase") or event.get("capture") or "")
    what = str(what).replace("\n", " ")
    if len(what) > 160:
        what = what[:159] + "…"
    return f"<span style='color:#8b97a6'>{at}</span> &nbsp;<b>{kind}</b> &nbsp;{html.escape(what)}"


class MonitorFeed(QWidget):
    """«Моніторинг»: read-only. What TCC can see of a session running in a terminal — the process
    journal it writes (phases, steps, capture rounds, decisions) — plus the two bus buttons. Typing
    is in the terminal: two places to write to one session is one too many (A13)."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self._feed = QTextBrowser()
        self._feed.setOpenExternalLinks(False)
        layout.addWidget(self._feed, 1)
        buttons = QHBoxLayout()
        self._done = QPushButton(i18n.t("captureReady"))
        self._done.setProperty("class", "reason-btn")
        self._done.clicked.connect(lambda: getattr(window, "_on_capture_ready", lambda: None)())
        self._listen = QPushButton(i18n.t("lsnBtn"))
        self._listen.setProperty("class", "reason-btn")
        self._listen.clicked.connect(lambda: getattr(window, "_open_listening", lambda: None)())
        self._note = QLabel(i18n.t("ctlMonitorNote"))
        self._note.setProperty("class", "phead-sub")
        self._note.setWordWrap(True)
        buttons.addWidget(self._done)
        buttons.addWidget(self._listen)
        buttons.addWidget(self._note, 1)
        layout.addLayout(buttons)
        # Follow the newest line until the Arbiter scrolls up to read; follow again once he is back
        # at the bottom. Driven by the scroll RANGE, which is what changes when text is laid out —
        # before that the range is zero, and the feed opened on its oldest line.
        self._follow = True
        bar = self._feed.verticalScrollBar()
        bar.rangeChanged.connect(lambda _lo, hi: bar.setValue(hi) if self._follow else None)
        # Only the Arbiter's own scrolling decides it: the browser scrolls itself back to the top
        # while it lays new text out, and reading that as "he scrolled up" froze the feed there.
        bar.actionTriggered.connect(lambda _action: QTimer.singleShot(
            0, lambda: setattr(self, "_follow", bar.value() >= bar.maximum() - 4)))
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        journal = config.project_dir() / "process" / "journal.jsonl"
        try:
            lines = journal.read_text(encoding="utf-8").splitlines()[-_FEED_EVENTS:]
        except OSError:
            self._feed.setHtml(f"<i>{html.escape(i18n.t('ctlMonitorEmpty'))}</i>")
            return
        rows = []
        for line in lines:
            try:
                rows.append(_event_line(json.loads(line)))
            except ValueError:
                continue
        self._feed.setHtml("<br>".join(rows))  # resets the scroll; `_follow` says where it goes
        if self._follow:
            # The browser scrolls to its text cursor once it has laid the text out, and setHtml puts
            # the cursor at the top — so the cursor goes to the end, and the scroll follows it.
            self._feed.moveCursor(QTextCursor.MoveOperation.End)
            bar = self._feed.verticalScrollBar()
            bar.setValue(bar.maximum())
        button = getattr(self._window, "_capture_ready_btn", None)
        self._done.setEnabled(button.isEnabled() if button is not None else True)


def _group(view, group_id: str):
    return next((g for g in getattr(view, "groups", ()) or () if g.id == group_id), None)


def _compare_now(window) -> tuple:
    """`(key, loaded view, how the list names it)` — what the window compares with now."""
    key = getattr(window, "_compare_key", None)
    view = window._compare_view_now() if hasattr(window, "_compare_view_now") else None
    said = window._compare_said() if hasattr(window, "_compare_said") else (key or "")
    return key, view, said


def _embedded(window, view) -> DetailPane:
    """A pane inside a tab: no menu of its own — the tab above IS the choice — and compared with
    what the window compares with, which the one list by the tabs sets (finding 47, 1 and 4)."""
    pane = DetailPane()
    pane.set_embedded(True)
    pane.set_eq_order(getattr(window, "_eq_order", None) or eq_field_order(None))
    pane.set_view(view)
    pane.use_compare(*_compare_now(window))
    pane.setVisible(True)
    return pane


def _table_tab(window, view, group_id: str, empty_key: str) -> QWidget:
    """A tier's table — the same table the detail pane shows, so «порівняти з» works here too."""
    group = _group(view, group_id)
    if group is None:
        label = QLabel(i18n.t(empty_key))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("class", "phead-sub")
        return label
    pane = _embedded(window, view)
    pane.open_table(group)
    return pane


def _param_tab(window, view, field: str) -> QWidget:
    pane = _embedded(window, view)
    pane.open_param(field)
    return pane


def _first_eq(view):
    """What the EQ tab opens on: the first output with an EQ, else the first channel with one,
    else the first channel at all — an EQ, never a table (finding 47, 5)."""
    groups = sorted(getattr(view, "groups", ()) or (), key=lambda g: g.id != "physical_outputs")
    for group in groups:
        for row in group.rows_visible():
            if row.eq_count() > 0:
                return group, row
    return next(((g, g.rows_visible()[0]) for g in groups if g.rows_visible()), None)


def _eq_tab(window, view) -> QWidget:
    pane = _embedded(window, view)
    first = _first_eq(view)
    if first is not None:
        pane.open_eq(*first)
    return pane


def place_terminal_left(screen) -> None:
    """The front Terminal window on the left half of `screen` (macOS; best effort, silent).

    Only when Terminal is already running: `tell application "Terminal"` would otherwise START it,
    and a window appearing because a layout changed is a surprise, not a placement."""
    if sys.platform != "darwin":
        return
    half = screen.width() // 2
    script = (
        'tell application "System Events" to set running to (name of processes) contains "Terminal"\n'
        'if running then\n'
        f'  tell application "Terminal" to if (count of windows) > 0 then set bounds of front window '
        f'to {{{screen.x()}, {screen.y()}, {screen.x() + half}, {screen.y() + screen.height()}}}\n'
        'end if'
    )
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


class ControlLayout:
    """Enter and leave the control layout on a live `MainWindow`, moving its real panels."""

    def __init__(self, window) -> None:
        self.window = window
        self.active = False
        self.tabs: Optional[QTabWidget] = None
        self.vertical: Optional[QSplitter] = None
        self.horizontal: Optional[QSplitter] = None
        self._saved_geometry = None
        self._confirm_home: Optional[tuple] = None
        self._hidden: list = []
        #: Which tab holds what: a group id, "eq", a parameter field, or "monitor".
        self._index: dict[str, int] = {}
        self._corner: Optional[QWidget] = None
        self.compare_combo: Optional[QComboBox] = None
        self._compare_other: Optional[QLabel] = None

    # ---- the two borders ----------------------------------------------------------------------

    def _read_sizes(self, key: str, default: list) -> list:
        raw = self.window._settings.value(key, None)
        try:
            sizes = [int(v) for v in json.loads(raw)] if raw else []
        except (TypeError, ValueError):
            sizes = []
        return sizes if len(sizes) == 2 and all(v > 0 for v in sizes) else list(default)

    def saved_sizes(self) -> tuple[list, list]:
        return self._read_sizes(_SIZES_KEY_V, _DEFAULT_V), self._read_sizes(_SIZES_KEY_H, _DEFAULT_H)

    def remember_sizes(self, *_args) -> None:
        """Where the Arbiter left the two borders, for the next time the mode opens."""
        if self.vertical is not None:
            self.window._settings.setValue(_SIZES_KEY_V, json.dumps(self.vertical.sizes()))
        if self.horizontal is not None:
            self.window._settings.setValue(_SIZES_KEY_H, json.dumps(self.horizontal.sizes()))

    # ---- in and out ---------------------------------------------------------------------------

    def enter(self) -> None:
        w = self.window
        if self.active:
            return
        self._saved_geometry = w.geometry()

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(4)
        # TCC's own confirmation, out of the hidden dialog and above the tabs: it shows itself only
        # when a request arrives, which is what «as it arises» asks for (A11).
        bar = w._dialog.confirm_bar
        home = bar.parentWidget().layout()
        self._confirm_home = (home, home.indexOf(bar))
        top_layout.addWidget(bar)
        self.tabs = QTabWidget()
        # The bar draws each tab's status dot itself, just after the text (finding 71, 1).
        self.tabs.setTabBar(DotTabBar())
        # Eight tabs, their dots and «порівняти з» share half a screen: tighter tabs than the
        # window's own (theme, `#ctl-tabs`).
        self.tabs.setObjectName("ctl-tabs")
        top_layout.addWidget(self.tabs, 1)
        self._build_corner()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._fill_tabs()

        self.horizontal = QSplitter(Qt.Orientation.Horizontal)
        self.horizontal.setChildrenCollapsible(False)
        self.horizontal.addWidget(w._left)
        self.horizontal.addWidget(w._right)

        self.vertical = QSplitter(Qt.Orientation.Vertical)
        self.vertical.setChildrenCollapsible(False)
        self.vertical.addWidget(top)
        self.vertical.addWidget(self.horizontal)

        sizes_v, sizes_h = self.saved_sizes()
        self.vertical.setSizes(sizes_v)
        self.horizontal.setSizes(sizes_h)
        self.vertical.splitterMoved.connect(self.remember_sizes)
        self.horizontal.splitterMoved.connect(self.remember_sizes)

        outer = w._main_splitter.parentWidget().layout()
        outer.insertWidget(outer.indexOf(w._main_splitter), self.vertical, 1)
        w._main_splitter.setVisible(False)

        self._compact(True)
        self._place_on_screen()
        self.active = True

    def leave(self) -> None:
        w = self.window
        if not self.active:
            return
        # Back in the full window, the tree lights what ITS pane shows.
        w._tree.set_active(*w._detail.focus())
        self.remember_sizes()
        w._main_splitter.insertWidget(0, w._left)
        w._main_splitter.insertWidget(2, w._right)
        layout, index = self._confirm_home
        layout.insertWidget(index, w._dialog.confirm_bar)
        w._main_splitter.setVisible(True)
        if self.vertical is not None:
            self.vertical.setParent(None)
            self.vertical.deleteLater()
        if self._corner is not None:
            self._corner.setParent(None)
            self._corner.deleteLater()
        self.vertical = self.horizontal = self.tabs = None
        self._corner = self.compare_combo = self._compare_other = None
        self._index = {}
        self._compact(False)
        if self._saved_geometry is not None:
            w.setGeometry(self._saved_geometry)
        self.active = False

    def toggle(self) -> None:
        self.leave() if self.active else self.enter()

    # ---- the tabs -----------------------------------------------------------------------------

    def _add(self, key: str, page: QWidget, text: str) -> None:
        self._index[key] = self.tabs.addTab(page, text)

    def _fill_tabs(self) -> None:
        view = getattr(self.window, "_view", None)
        current = self.tabs.currentIndex()
        while self.tabs.count():
            page = self.tabs.widget(0)
            self.tabs.removeTab(0)
            page.deleteLater()
        self._index = {}
        w = self.window
        self._add("monitor", MonitorFeed(w), i18n.t("ctlMonitor"))
        self._add("virtual_channels", _table_tab(w, view, "virtual_channels", "ctlNoVirtual"),
                  i18n.t("ctlTableV"))
        self._add("physical_outputs", _table_tab(w, view, "physical_outputs", "ctlNoOutputs"),
                  i18n.t("ctlTableO"))
        # The input table exists even while it is empty (finding 47, 2): «params» under ВХОДИ opens
        # it, so it needs a tab — but only on a rig whose profile has inputs at all.
        # No tab over nothing: «Таблиця-I» only when the rig HAS inputs (finding 71, 4).
        inputs = _group(view, "inputs")
        if inputs is not None and inputs.rows_visible():
            self._add("inputs", _table_tab(w, view, "inputs", "ctlNoOutputs"), i18n.t("ctlTableI"))
        self._add("eq", _eq_tab(w, view), "EQ")
        for field, key in (("gain_db", "tabGain"), ("ta_ms", "tabDelay"), ("phase_deg", "tabPhase")):
            self._add(field, _param_tab(w, view, field), i18n.t(key))
        for key, index in self._index.items():
            page = self.tabs.widget(index)
            if not isinstance(page, DetailPane):
                continue
            page.focusChanged.connect(lambda *_a, p=page: self._light_tree(p))
            if key != "eq":
                page.eqRequested.connect(
                    lambda gid, rid, src=key: self.show_eq(gid, rid, back=src))
        self._fill_compare()
        self.sync_dots()
        if current >= 0:
            self.tabs.setCurrentIndex(min(current, self.tabs.count() - 1))
        self._on_tab_changed(self.tabs.currentIndex())

    def refresh(self) -> None:
        """Rebuild the tabs from the view the window holds now — after a reload, a preset switch
        or a language change. The feed refreshes itself; the tables are data the view carries."""
        if self.active and self.tabs is not None:
            self._fill_tabs()

    # ---- where the tree and the tables lead ----------------------------------------------------

    def show_table(self, group_id: str, row_id: Optional[str] = None) -> None:
        """The tree's «params» (and a channel's row) open that tier's table tab (finding 47, 2)."""
        index = self._index.get(group_id)
        if self.tabs is None or index is None:
            return
        page = self.tabs.widget(index)
        group = _group(getattr(self.window, "_view", None), group_id)
        if row_id is not None and isinstance(page, DetailPane) and group is not None:
            page.open_table(group, select_row_id=row_id)
        self.tabs.setCurrentIndex(index)

    def show_eq(self, group_id: str, row_id: str, back: Optional[str] = None) -> None:
        """The EQ tab on this channel. From a tab's row, «← <that tab>» leads back to it; from
        the tree there is no table to go back to (finding 47, 5)."""
        index = self._index.get("eq")
        group = _group(getattr(self.window, "_view", None), group_id)
        row = next((r for r in group.rows if r.id == row_id), None) if group is not None else None
        pane = self.tabs.widget(index) if self.tabs is not None and index is not None else None
        if not isinstance(pane, DetailPane) or row is None:
            return
        source = self._index.get(back) if back is not None else None
        if source is not None:
            pane.set_back("← " + self.tabs.tabText(source),
                          lambda i=source: self.tabs.setCurrentIndex(i))
        else:
            pane.set_back(None)
        pane.open_eq(group, row)
        self.tabs.setCurrentIndex(index)

    # ---- «порівняти з» by the tabs, and the dots on them ----------------------------------------

    def _build_corner(self) -> None:
        """One «порівняти з» for every tab (finding 47, 4), in the header above them."""
        self._corner = QWidget()
        layout = QHBoxLayout(self._corner)
        layout.setContentsMargins(0, 0, 6, 2)
        layout.setSpacing(6)
        label = QLabel(i18n.t("cmpWith"))
        label.setProperty("class", "phead-sub")
        layout.addWidget(label)
        self.compare_combo = QComboBox()
        self.compare_combo.setProperty("class", "mini-select")
        self.compare_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.compare_combo.setMinimumContentsLength(6)
        self.compare_combo.currentIndexChanged.connect(self._on_compare_picked)
        layout.addWidget(self.compare_combo)
        self._compare_other = QLabel(i18n.t("cmpOtherTag"))
        self._compare_other.setProperty("class", "cmp-other")
        self._compare_other.setVisible(False)
        layout.addWidget(self._compare_other)
        button = self.window._layout_btn
        header = button.parentWidget().layout()
        header.insertWidget(header.indexOf(button), self._corner)

    def _fill_compare(self) -> None:
        args = getattr(self.window, "_compare_args", None) or ()
        own = args[0] if len(args) > 0 else []
        labels = args[3] if len(args) > 3 else None
        others = args[4] if len(args) > 4 else None
        key = getattr(self.window, "_compare_key", None)
        combo = self.compare_combo
        blocked = combo.blockSignals(True)
        fill_compare_combo(combo, own, labels, others)
        combo.setCurrentIndex(max(combo.findData(key) if key else 0, 0))
        combo.blockSignals(blocked)
        self._corner.setVisible(bool(own or others))
        self._compare_other.setVisible(is_other_preset(key))

    def _on_compare_picked(self, _index: int) -> None:
        chosen = getattr(self.window, "_on_compare_chosen", None)
        if chosen is not None:
            chosen(self.compare_combo.currentData())

    def use_compare(self, key: Optional[str], view, said: str = "") -> None:
        """The window's one choice, onto every tab."""
        if self.tabs is None:
            return
        for index in self._index.values():
            page = self.tabs.widget(index)
            if isinstance(page, DetailPane):
                page.use_compare(key, view, said)
        blocked = self.compare_combo.blockSignals(True)
        self.compare_combo.setCurrentIndex(max(self.compare_combo.findData(key) if key else 0, 0))
        self.compare_combo.blockSignals(blocked)
        self._compare_other.setVisible(is_other_preset(key))
        self.sync_dots()

    def _on_tab_changed(self, index: int) -> None:
        if self._corner is not None:
            # The monitor has nothing to compare.
            self._corner.setEnabled(index != self._index.get("monitor"))
        self._light_tree(self.tabs.widget(index) if self.tabs is not None else None)

    def _light_tree(self, page) -> None:
        """The tree lights what the CURRENT tab shows (the Arbiter on the prototype: «поточна
        група активна!»); a pane in a tab behind it says nothing."""
        tree = getattr(self.window, "_tree", None)
        if tree is None or self.tabs is None or page is not self.tabs.currentWidget():
            return
        tree.set_active(*(page.focus() if isinstance(page, DetailPane) else (None, None)))

    def sync_dots(self) -> None:
        """Grey, green or blue on each tab that shows the DSP (finding 65)."""
        if self.tabs is None:
            return
        view = getattr(self.window, "_view", None)
        groups = getattr(view, "groups", ()) or ()
        _key, compared_view, said = _compare_now(self.window)
        old = getattr(compared_view, "groups", ()) or ()
        compared = compared_view is not None
        bar = self.tabs.tabBar()
        for key, index in self._index.items():
            if key == "monitor":
                continue
            if key in ("virtual_channels", "physical_outputs", "inputs"):
                group = _group(view, key)
                status = (group_status(group, _group(compared_view, key), compared)
                          if group is not None else None)
            else:
                status = field_status(groups, key, old, compared) if groups else None
            bar.set_dot(index, status)
            # The whole tab answers the hover, not just the dot: «зону спрацювання трохи більше,
            # бо важко попасти» (the Arbiter, 2026-09-25).
            bar.setTabToolTip(index, tip_for(status, said))

    # ---- fitting half a screen ----------------------------------------------------------------

    def _compact(self, on: bool) -> None:
        """Make the header and the footer fit half a screen.

        Measured 2026-09-22 on the Passat: the header's minimum was ~1525 px and the footer's
        ~800, against half of a 1512 px MacBook screen. In this mode the language, zoom and theme
        controls leave the header (the menu has all three), the field captions go, the preset and
        target shrink, and the menu button is its glyph; the Generator's effort leaves the footer
        (it steers the in-app session, which this mode does not run). The model picker STAYS: it
        decides which CLI and model the terminal opens with.
        """
        w = self.window
        hidden = [w._preset_field_lbl, w._target_field_lbl, w._lang_combo,
                  w._zoom_label.parentWidget(), w._theme_btn,
                  w._ai_effort_lbl, w._ai_effort_combo]
        if on:
            self._hidden = [(x, x.isVisible()) for x in hidden]
            for widget in hidden:
                widget.setVisible(False)
            self._preset_state = (w._preset_combo.minimumWidth(), w._preset_combo.sizeAdjustPolicy(),
                                  w._preset_combo.minimumContentsLength())
            w._preset_combo.setMinimumWidth(0)
            w._preset_combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            w._preset_combo.setMinimumContentsLength(6)
            w._preset_combo.setMaximumWidth(140)
            self._target_policy = w._target_label.sizePolicy()
            # Preferred, not Ignored: an Ignored item is laid out below its own minimum, and the
            # link then painted its 60 px over whatever came next («порівняти з», finding 67, 1).
            w._target_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            w._target_label.setMinimumWidth(60)
            w._target_label.setMaximumWidth(170)
            self._menu_text = w._menu_btn.text()
            w._menu_btn.setText("☰")
            # The header's 14 px between each of its items was the half screen it did not have:
            # «SQ-Comp» ran over «порівняти з» (finding 67, 1).
            header = w._layout_btn.parentWidget().layout()
            self._header_spacing = header.spacing()
            header.setSpacing(6)
        else:
            for widget, was in self._hidden:
                widget.setVisible(was)
            self._hidden = []
            minimum, policy, length = getattr(self, "_preset_state", (0, None, 0))
            w._preset_combo.setMinimumWidth(minimum)
            if policy is not None:
                w._preset_combo.setSizeAdjustPolicy(policy)
                w._preset_combo.setMinimumContentsLength(length)
            w._preset_combo.setMaximumWidth(16777215)
            w._target_label.setMaximumWidth(16777215)
            w._target_label.setMinimumWidth(0)
            if getattr(self, "_target_policy", None) is not None:
                w._target_label.setSizePolicy(self._target_policy)
            if getattr(self, "_menu_text", None):
                w._menu_btn.setText(self._menu_text)
            if getattr(self, "_header_spacing", None) is not None:
                w._layout_btn.parentWidget().layout().setSpacing(self._header_spacing)

    def _place_on_screen(self) -> None:
        """TCC on the right half of its screen; the terminal on the left (A12)."""
        w = self.window
        screen = w.screen().availableGeometry()
        half = screen.width() // 2
        w.setMinimumWidth(0)
        w.setGeometry(screen.x() + half, screen.y(), half, screen.height())
        place_terminal_left(screen)
