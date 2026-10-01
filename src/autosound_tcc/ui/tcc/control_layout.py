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
import math
import subprocess
import sys
from typing import Optional

import shiboken6
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QFont, QFontMetricsF, QTextCursor
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyle,
    QStyleOptionComboBox,
    QTableWidget,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import config
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.discard import drop
from autosound_tcc.ui.tcc.detail_pane import (
    cell_width,
    DetailPane,
    eq_field_order,
    fill_compare_combo,
    is_other_preset,
    mark_unreadable,
    paint_compare_box,
    unread_mark,
    unread_mark_width,
    with_unread_mark,
)
from autosound_tcc.ui.tcc.labels import ElidedLabel
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
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


_NURSERY: Optional[QWidget] = None


def _nursery() -> QWidget:
    """A parent that is never shown, for a pane between its making and its tab.

    A widget with no parent that is shown IS a window: `_embedded` shows its pane, and
    `open_table`/`open_eq` show it again, before the tab takes it — on Windows one small window
    flashed per tab on the way into this mode, and none on the way out (finding 104, tcc#62). A
    child of a hidden widget can be told to show without anything appearing; the tab reparents it."""
    global _NURSERY
    if _NURSERY is None or not shiboken6.isValid(_NURSERY):
        _NURSERY = QWidget()
    return _NURSERY


def _embedded(window, view) -> DetailPane:
    """A pane inside a tab: no menu of its own — the tab above IS the choice — and compared with
    what the window compares with, which the one list by the tabs sets (finding 47, 1 and 4)."""
    pane = DetailPane()
    pane.setParent(_nursery())
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


def table_width_whole(table: QTableWidget) -> int:
    """The width at which every column of `table` shows its heading and its values whole (tcc#107).

    Each value is measured regular and bold: a compared change is drawn bold (`DetailPane.
    _styled_cell`), and a floor that followed «порівняти з» would move the window's minimum with
    every pick. The pane's table sizes each column to its content (`detail_pane._ContentTable`),
    so each needs its own room; a column that stretched would need the widest one's, and the
    branch for it stays for a table that does. A vertical scroll bar that takes room is counted:
    the top zone is the Arbiter's to shorten."""
    table.ensurePolished()
    header = table.horizontalHeader()
    fonts = (table.font(), QFont(table.font()))
    fonts[1].setBold(True)
    own, stretched = 0, []
    for column in range(table.columnCount()):
        if header.isSectionHidden(column):
            continue
        need = header.sectionSizeHint(column)
        for row in range(table.rowCount()):
            item = table.item(row, column)
            if item is not None and item.text():
                need = max(need, *(cell_width(table, item.text(), font) for font in fonts))
        if header.sectionResizeMode(column) == QHeaderView.ResizeMode.Stretch:
            stretched.append(need)
        else:
            own += need
    width = own + len(stretched) * max(stretched, default=0) + 2 * table.frameWidth()
    if not table.verticalHeader().isHidden():
        width += table.verticalHeader().sizeHint().width()
    bar = table.verticalScrollBar()
    if not table.style().styleHint(QStyle.StyleHint.SH_ScrollBar_Transient, None, bar):
        width += bar.sizeHint().width()
    return width


def _min_chrome(widget: QWidget, top: QWidget) -> Optional[int]:
    """How much wider than `widget` Qt makes `top`'s minimum when `widget`'s own is the widest in
    each row on the way up -- each box layout's margins, each frame, a tab widget's frame; a
    stacked page or a main window's central widget adds none. None if `widget` is not inside
    `top`."""
    chrome, node = 0, widget
    while node is not top:
        parent = node.parentWidget()
        if parent is None:
            return None
        if isinstance(parent, QTabWidget):
            # Its minimum is its frame around the wider of its pages and its bar.
            inside = max(node.minimumSizeHint().width(),
                         parent.tabBar().minimumSizeHint().width())
            chrome += parent.minimumSizeHint().width() - inside
        else:
            margins = parent.contentsMargins()
            chrome += margins.left() + margins.right()
            layout = parent.layout()
            if isinstance(layout, QBoxLayout):
                margins = layout.contentsMargins()
                chrome += margins.left() + margins.right()
        node = parent
    return chrome


def _min_width_without(widget: QWidget, skip: QWidget) -> int:
    """`widget`'s minimum width less `skip`'s, summed from its own margins, its box layout's
    margins and spacing, and the other items' own minimums -- the same number whatever `skip`
    asks for now. A layout's own `minimumSize` is a cached sum refreshed only by a posted event,
    so "the layout's minimum less the widget's fresh one" is two moments mixed. A nested widget
    on the way to `skip` is summed the same way."""
    margins, layout = widget.contentsMargins(), widget.layout()
    width, shown = margins.left() + margins.right(), 0
    if layout is None:
        return width
    margins = layout.contentsMargins()
    width += margins.left() + margins.right()
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.isEmpty():
            continue
        shown += 1
        inner = item.widget()
        if inner is skip:
            continue
        if inner is not None and inner.isAncestorOf(skip):
            width += _min_width_without(inner, skip)
        else:
            width += item.minimumSize().width()
    return width + max(0, shown - 1) * layout.spacing()


#: How much room past its own width a hidden corner label waits for before it comes back, so a
#: header a pixel either side of the line does not flicker (tcc#96). The header's own ask moves by
#: a few pixels as the names beside it elide (measured 1014–1020 px for one header).
_REFIT_SLACK_PX = 12

#: The preset name the compare box holds whole as its floor where the header has the room,
#: «<this name> · v_NNN» (tcc#96, the controller's finding on the third pass): 13 letters of
#: ordinary width, longer than any of the Arbiter's («3.S-shelf», «4.C-cut»). The window's floor
#: grows one for one with the box, so the box's floor is capped twice over -- in the box's own
#: font, not in pixels, and by what half the screen leaves it after the rest of the header
#: (`_CompareBox.floor_cap`). A 190-px cap (the fourth pass, measured offscreen on the Mac) held
#: these 13 letters there and about six on the Windows runner, where the offscreen text is twice
#: as wide (Qt's FreeType font database finds no fonts and draws every glyph as wide as the pixel
#: size; CI run 36623891341). In the Mac's font the letters come to the same 190 px: the rest of
#: the Arbiter's header measured 518 (English and Ukrainian alike), the window adds 16, so the
#: floor is 724 -- inside 756, half his 1512-px screen, where control mode puts the window. The
#: letters alone were not enough (the re-review of fix round 5): a font a little wider -- the
#: stretch 106 to 110, the zoom's first steps -- widened the rest of the header AND the letters,
#: and with a 30-character preset the floor went to 760-780 where the 190 px would have kept it
#: in 756. So the half screen's leftover caps the letters: the box gives up letters before the
#: window leaves the half. Only a font whose header does not fit the half even with the smallest
#: box widens the floor past it -- the zoom finding, not this box's.
_COMPARE_BOX_FLOOR_NAME = "a" * 13


class _CompareBox(QComboBox):
    """«Порівняти з» in the header. Another configuration's version is shown with its preset's
    name, «3.S-shelf · v_002», so the «інша конфігурація» tag beside it can give way without the
    meaning going with it (tcc#96, the controller's ruling after finding 105's second pass). The
    open list's rows stay as they are: #103's headings name the preset there.

    It asks for the whole of that, but holds as its floor only «<preset> · v_NNN» -- the names a
    project-line version was saved under («v_002 · P3, SQ-2, SQ-3», `ledger_line.label`) give way
    first -- and never more than `floor_cap()`: the room «<_COMPARE_BOX_FLOOR_NAME> · v_NNN»
    takes in its font, or what half the screen leaves the box after the rest of the header
    (`set_half_room`), whichever is less; a preset name too long for that gives way next, the
    version still whole. The hover has the whole text. Whatever it shows is drawn elided, never
    cut mid-glyph («v_0(», the Arbiter's first screenshot)."""

    def __init__(self) -> None:
        super().__init__()
        self._sized_for: Optional[str] = None
        #: What half the screen leaves this box (`ControlLayout._fit_corner`); None until measured.
        self._half_room: Optional[int] = None

    def set_half_room(self, room: Optional[int]) -> None:
        """The most this box may hold as its floor for the window to stay in half its screen:
        the half, less the rest of the header at its minimum and what the window adds around
        it. Measured by the header's owner, since the box cannot see past its own edge."""
        if room != self._half_room:
            self._half_room = room
            self.updateGeometry()

    def shown_text(self) -> str:
        return self._shown(self.currentText())

    def _shown(self, row: str) -> str:
        key = self.currentData()
        if is_other_preset(key):
            return f"{key.split('/', 1)[0]} · {row}"
        return row

    def _row(self) -> str:
        """The picked row's own text: a row marked «не читається» without the mark."""
        split = unread_mark(self)
        return split[0] if split else self.currentText()

    def _parts(self, row: Optional[str] = None) -> Optional[tuple[str, str, str]]:
        """Another configuration's pick as `(preset, v_NNN, the saved names after it)`, read off
        `row` (the picked row's own text by default)."""
        key = self.currentData()
        if not is_other_preset(key):
            return None
        preset, version = key.split("/", 1)
        row = self._row() if row is None else row
        if not row.startswith(version):
            return preset, row, ""
        return preset, version, row[len(version):]

    def _text_width(self, text: str) -> int:
        # Rounded up: `elidedText` measures in fractions of a pixel (TODO F-045).
        return math.ceil(QFontMetricsF(self.font()).horizontalAdvance(text))

    def _room(self, size=None) -> int:
        """The width the text has: the style's edit field, less the pixel each side of it that
        the label is drawn inside."""
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        if size is not None:
            option.rect = QRect(QPoint(0, 0), size)
        field = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                            QStyle.SubControl.SC_ComboBoxEditField, self)
        return max(0, field.width() - 2)

    def fit_text(self) -> str:
        """What the closed box draws: `shown_text`, elided to the room it has now -- the saved
        names first, then the preset's name; «v_NNN» goes only when nothing else is left. A row
        marked «не читається»: its names, its preset, then the mark's words down to a sign, never
        the version (`with_unread_mark`, tcc#122, Ruling 26)."""
        key = self.currentData()
        return with_unread_mark(self, self._room(), self._fit,
                                key.split("/", 1)[-1] if key else "")

    def _fit(self, row: str, room: int) -> str:
        metrics, full = self.fontMetrics(), self._shown(row)
        cut = metrics.elidedText(full, Qt.TextElideMode.ElideRight, room)
        if cut == full:
            return cut
        parts = self._parts(row)
        if parts is None:
            # This configuration's own: «v_NNN…» before Qt cuts into the version, as the full
            # window's list holds it (`detail_pane._HeadBox`) -- the room a «не читається» takes
            # beside it at the cap left «v_00…» (tcc#122).
            version = row.split(" ", 1)[0]
            if version.startswith("v_") and not cut.startswith(version):
                for alone in (version + "…", version):
                    if self._text_width(alone) <= room:
                        return alone
            return cut
        preset, version, names = parts
        if cut.startswith(f"{preset} · {version}"):
            return cut
        # The version whole, and the «…» after it that says saved names were cut: where the cap
        # fell between «<preset> · v_NNN» and that «…», the names went without a mark and the box
        # read as a version saved under none (tcc#122). The preset gives way for both; only where
        # not one of its letters is left beside them does the mark go, as «… · v_NNN».
        for rest in ((f" · {version}…", f" · {version}") if names else (f" · {version}",)):
            short = metrics.elidedText(preset, Qt.TextElideMode.ElideRight,
                                       room - self._text_width(rest))
            if short:
                return short + rest
        # Not a letter of the preset left beside it: the version alone, its names' «…» after it
        # where it fits -- what a «не читається» leaves at the cap (tcc#122).
        for alone in ((f"{version}…", version) if names else (version,)):
            if self._text_width(alone) <= room:
                return alone
        return cut

    def sizeHint(self):  # noqa: N802 (Qt override)
        hint = super().sizeHint()
        if is_other_preset(self.currentData()):
            chrome = hint.width() - self._room(hint)
            hint.setWidth(max(hint.width(), self._text_width(self.shown_text()) + chrome))
        else:  # this configuration's: six letters' room, and a «не читається» beside them where
            # the header has it to give -- asked, not held: the floor is `minimumSizeHint`'s
            hint.setWidth(hint.width() + unread_mark_width(self))
        return hint

    def floor_cap(self) -> int:
        """The most this box holds as its floor: «<_COMPARE_BOX_FLOOR_NAME> · v_NNN» in its own
        font, plus its chrome -- 190 px in the Mac's offscreen font, and as many letters in any
        other -- or less where half the screen leaves it less (`set_half_room`), down to
        «… · v_NNN»: the version whole, with the «…» that says a name was cut before it. Where
        the half leaves not even that, the letters could not keep the window in it whatever they
        gave (the zoom finding), and the font's own cap stands: the name whole is worth more than
        a few pixels off a window that is past the half anyway."""
        hint = super().minimumSizeHint()
        chrome = hint.width() - self._room(hint)
        cap = self._text_width(f"{_COMPARE_BOX_FLOOR_NAME} · v_000") + chrome
        least = self._text_width("… · v_000") + chrome
        if self._half_room is not None and self._half_room >= least:
            cap = min(cap, self._half_room)
        return cap

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        # A QComboBox's own floor is its size hint. Read off the row without a «не читається»:
        # the mark asks no floor of its own, and a pick never moves the window's (tcc#122,
        # Ruling 26 -- held whole, it took the version at W-4's widths).
        hint = super().minimumSizeHint()
        parts = self._parts()
        if parts is not None:
            preset, version, names = parts
            chrome = hint.width() - self._room(hint)
            held = self._text_width(f"{preset} · {version}" + ("…" if names else "")) + chrome
            hint.setWidth(max(hint.width(), min(held, self.floor_cap())))
        return hint

    def sync_width(self) -> None:
        """Tells the layout the width changed -- only when the name shown did: it re-lays the
        header out, and the header's refit is what calls this."""
        shown = self.shown_text()
        if shown != self._sized_for:
            self._sized_for = shown
            self.updateGeometry()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        paint_compare_box(self, self.fit_text())


class _HeaderWatch(QObject):
    """Refits the corner, and holds the output table's floor, whenever the header is resized, laid
    out again or shown."""

    def __init__(self, refit, parent: QObject) -> None:
        super().__init__(parent)
        self._refit = refit

    def eventFilter(self, _watched, event) -> bool:  # noqa: N802 (Qt override)
        if event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest, QEvent.Type.Show):
            self._refit()
        return False


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
        self.compare_combo: Optional[_CompareBox] = None
        self._compare_label: Optional[QLabel] = None
        self._compare_other: Optional[QLabel] = None
        self._compare_tip = None
        self._header_watch: Optional[_HeaderWatch] = None
        #: `(table, its font, its width whole)`: measured once per table and font (tcc#107).
        self._table_whole: Optional[tuple] = None

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
        # The full window's own place, and its state: a maximised window goes back maximised.
        full = w.windowState() & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen)
        self._saved_geometry = (w.normalGeometry() if full else w.geometry(), w.windowState())

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
        self._hold_table()
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
        # Each out of its layout before it is unparented (`discard.drop`, tcc#19). The header's
        # items are fetched to measure the corner's room (`_min_width_without`), and PySide keeps
        # a wrapper for each fetched item as long as the header lives; unparented in place, the
        # corner's item was deleted by Qt behind that wrapper, and the next Qt object built on
        # its address came back to Python as a `QWidgetItem` -- a new table's `viewport()` on
        # ubuntu's CI at 0750776. The splitter goes the same way: its layout is the window's.
        if self.vertical is not None:
            drop(self.vertical)
        if self._corner is not None:
            self._corner.parentWidget().removeEventFilter(self._header_watch)
            drop(self._corner)
        self.vertical = self.horizontal = self.tabs = None
        self._corner = self.compare_combo = self._compare_label = self._compare_other = None
        self._compare_tip = self._header_watch = None
        self._table_whole = None
        self._index = {}
        self._compact(False)
        if self._saved_geometry is not None:
            geometry, state = self._saved_geometry
            # A window the Arbiter maximised IN this mode keeps that state through `setGeometry`
            # (the defect tcc#110 fixed on the way in, mirrored on the way out): a normal window
            # first, then the full window's own place, then its own state.
            if w.windowState() & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen):
                w.showNormal()
            w.setGeometry(geometry)
            if state & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen):
                w.setWindowState(state)
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
        self._hold_table()

    def refresh(self) -> None:
        """Rebuild the tabs from the view the window holds now — after a reload, a preset switch
        or a language change. The feed refreshes itself; the tables are data the view carries."""
        if self.active and self.tabs is not None:
            # Before `_fill_tabs`, whose `_fit_corner` judges them by their width in these words:
            # they kept the language the corner was built in (tcc#122, W-4's review of #96).
            self._compare_label.setText(i18n.t("cmpWith"))
            self._compare_other.setText(i18n.t("cmpOtherTag"))
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
            self._hold_table()
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
        # Shown whole or not at all (tcc#96, finding 105: «порівнят», then «пор…» at half a screen
        # after the first two passes): `_fit_corner` hides it, and the «інша конфігурація» tag,
        # whenever the header cannot give it its full width -- judged on every resize of the
        # header. An `ElidedLabel` still, so the moment between a resize and that refit never
        # cuts it mid-word; a floor of 0, so a label shown only where it fits whole adds nothing
        # to the window's own minimum.
        # `Maximum`, not `ElidedLabel`'s own default `Ignored`: `Ignored` asks the LAYOUT for zero
        # width and takes only whatever is left over after everything else is placed, which in
        # this row left it 0 px and reading «c…» at every width, including full screen -- an
        # opus reviewer's own measurement of the first pass of this fix, caught before commit.
        # `Maximum` is `ElidedLabel`'s documented "value" mode: its natural width, ground given
        # only under real squeeze.
        self._compare_label = ElidedLabel(i18n.t("cmpWith"), min_width=0,
                                          policy=QSizePolicy.Policy.Maximum)
        self._compare_label.setProperty("class", "phead-sub")
        layout.addWidget(self._compare_label)
        self.compare_combo = _CompareBox()
        # `cmp-box`: a refused pick's closed box greyed (`paint_compare_box`, tcc#122).
        self.compare_combo.setProperty("class", "mini-select cmp-box")
        self.compare_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.compare_combo.setMinimumContentsLength(6)
        # NO explicit `setMinimumWidth` here (tcc#96, finding 105) -- a first attempt set one,
        # and an opus reviewer's pass caught that it made things WORSE: an explicit minimum
        # REPLACES `minimumSizeHint` as the layout's floor even when it is smaller, so a guessed
        # constant (34 px, a Fusion-style guess; the app runs the platform style with QSS) pulled
        # the floor down from the combo's own natural ~121 px to ~98. `QComboBox.
        # minimumSizeHint()` already equals `sizeHint()` (verified: a plain `QComboBox` built the
        # same way reports the same QSize for both; `_CompareBox` keeps it so) -- Qt does not let
        # an ordinary layout shrink it below that on its own, so the box already has a real floor
        # without anything set here. Measured with the Arbiter's header shown: 121 px, and never
        # empty down to the window's own minimum (697 px, in English and in Ukrainian alike).
        self.compare_combo.currentIndexChanged.connect(self._on_compare_picked)
        # What a hidden corner label said, and which configuration a picked version belongs to.
        self._compare_tip = attach_tip(self.compare_combo)
        layout.addWidget(self.compare_combo)
        self._compare_other = ElidedLabel(i18n.t("cmpOtherTag"), min_width=0,
                                          policy=QSizePolicy.Policy.Maximum)
        self._compare_other.setProperty("class", "cmp-other")
        self._compare_other.setVisible(False)
        layout.addWidget(self._compare_other)
        button = self.window._layout_btn
        header = button.parentWidget().layout()
        header.insertWidget(header.indexOf(button), self._corner)
        # The header re-lays itself out on a zoom or a language switch too, which is when the
        # table's fonts and headings change: its floor is held again then (tcc#107).
        self._header_watch = _HeaderWatch(self._refit, self._corner)
        button.parentWidget().installEventFilter(self._header_watch)

    def _refit(self) -> None:
        self._fit_corner()
        self._hold_table()

    def _fill_compare(self) -> None:
        args = getattr(self.window, "_compare_args", None) or ()
        own = args[0] if len(args) > 0 else []
        labels = args[3] if len(args) > 3 else None
        others = args[4] if len(args) > 4 else None
        preset = args[5] if len(args) > 5 else None
        current = args[6] if len(args) > 6 else None
        key = getattr(self.window, "_compare_key", None)
        combo = self.compare_combo
        blocked = combo.blockSignals(True)
        fill_compare_combo(combo, own, labels, others, preset, current)
        combo.setCurrentIndex(max(combo.findData(key) if key else 0, 0))
        combo.blockSignals(blocked)
        if self._unreadable(key, _compare_now(self.window)[1]):
            mark_unreadable(combo, key)  # the refill forgot what the pick found (tcc#122)
        selectable = [v for v in own if v != current]
        self._corner.setVisible(bool(selectable or others))
        self._fit_corner()

    def _unreadable(self, key: Optional[str], view) -> bool:
        """Whether `key` is a version the window has a loader for and could not read."""
        args = getattr(self.window, "_compare_args", None) or ()
        return bool(key) and view is None and len(args) > 2 and args[2] is not None

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
        if self._unreadable(key, view):
            # A version the window could not read: said on its row, not compared with in silence.
            mark_unreadable(self.compare_combo, key)
        self._fit_corner()
        self._hold_table()
        self.sync_dots()

    def _fit_corner(self) -> None:
        """«порівняти з» and «інша конфігурація»: whole, or not shown at all (tcc#96, the
        controller's ruling after finding 105's second pass) -- at control mode's own 756 px they
        read «пор…», and «п…» beside «інша конфі…», which say nothing.

        Each is judged by the header's width against what the header asks for WITH it, i.e. with
        everything at its natural width; a hidden one comes back only with `_REFIT_SLACK_PX` to
        spare. The project name and the mode button give ground by eliding once both have gone
        (measured: letting «порівняти з» keep its width instead raised the window's floor to
        735–757 px and cut the tag to «a…»). The tag gives way first: its meaning is in the box,
        which names the configuration. What a hidden label said is in the box's hover."""
        corner, combo = self._corner, self.compare_combo
        if corner is None or not shiboken6.isValid(corner):
            return
        label, tag = self._compare_label, self._compare_other
        header = corner.parentWidget()
        if header is not None:
            # What half the screen leaves the box: the half, less the rest of the header at its
            # minimum and what the window adds around the header (tcc#96, the re-review of fix
            # round 5: a font a little wider than the Mac's put a 30-character preset past 756).
            # The rest is summed from the other items themselves (`_min_width_without`), never
            # read as "the header's minimum less the box's": the header's is a layout's CACHED
            # number and the box's a fresh one, and their difference ratcheted on a pick -- the
            # room traced 247, 190, 162, 190, 218, the window's minimum spiked to 780 and Qt
            # grew the window past the half for good (the review of the follow-up).
            around = _min_chrome(header, self.window) or 0
            rest = _min_width_without(header, combo)
            combo.set_half_room(self._right_half()[1].width() - around - rest)
        combo.sync_width()
        other = is_other_preset(combo.currentData())
        if header is None or not header.isVisible():
            # Nothing laid out yet to measure; the header's first resize judges.
            show_label, show_tag = True, other
        else:
            spacing = corner.layout().spacing()
            wants = {w: w.sizeHint().width() + spacing for w in (label, tag)}
            bare = header.sizeHint().width() - sum(n for w, n in wants.items() if not w.isHidden())
            room = header.width()

            def fits(widget, need: int) -> bool:
                return room >= need + (_REFIT_SLACK_PX if widget.isHidden() else 0)

            show_label = fits(label, bare + wants[label])
            show_tag = other and show_label and fits(tag, bare + wants[label] + wants[tag])
        for widget, show in ((label, show_label), (tag, show_tag)):
            if widget.isHidden() == show:
                widget.setVisible(show)
        said = [] if show_label else [i18n.t("cmpWith")]
        if other:
            said.append(i18n.t("cmpOtherTip").format(version=combo.shown_text()))
        elif combo.fit_text() != combo.shown_text():
            said.append(combo.shown_text())  # this preset's own version, its saved names cut
        self._compare_tip.set_text("<br>".join(html.escape(line) for line in said))

    def _on_tab_changed(self, index: int) -> None:
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

    def _hold_table(self) -> None:
        """Control mode's minimum shows «Таблиця-О» whole, «3500 LR4» and not «3500 …» (tcc#107,
        finding 115: the Arbiter at the minimum, «розмір зробити трохи більше і ок»).

        The floor is the output table's page's: its table's width with every heading and value
        whole (`table_width_whole`), measured in the fonts it is drawn in -- a zoom or the Windows
        fonts widen it with them. It stops where the window would no longer sit in the half
        screen this mode puts it in (tcc#96): with nine equal columns the Arbiter's table needed
        about 830 px in the Mac's offscreen font, past half of his 1512-px screen; sized to its
        content (`detail_pane._ContentTable`) it needs about 740, inside it. Where a font or a
        rig still asks more, the floor is the half and the columns give way in proportion. The
        rest of the window keeps its own floor, whatever the table's."""
        w = self.window
        index = self._index.get("physical_outputs")
        page = self.tabs.widget(index) if self.tabs is not None and index is not None else None
        table = page.findChild(QTableWidget) if isinstance(page, DetailPane) else None
        if table is None or not w.isAncestorOf(page):
            return
        inside, outside = _min_chrome(table, page), _min_chrome(page, w)
        if inside is None or outside is None:
            return
        key = (table, table.font().key())
        if self._table_whole is None or self._table_whole[:2] != key:
            self._table_whole = (*key, table_width_whole(table))
        floor = min(self._table_whole[2] + inside, self._right_half()[1].width() - outside)
        # An explicit minimum replaces the page's own even when smaller (tcc#96): never below it.
        before = page.minimumWidth()
        page.setMinimumWidth(max(floor, page.minimumSizeHint().width(), 0))
        # A floor that rose on a shown window: the window grows to it where it stands, to the
        # right (tcc#106, `_keep_on_screen`). A reload in this mode rebuilds the tabs on the event
        # loop's next pass, after the window's own check has run, so a window at its minimum
        # flush right went 9 px past a 1920-px screen when a crossover grew from 350 to 3500 Hz
        # (the review of #107/#110). Asked here, when the floor is raised -- with every widget
        # and layout between the page and the window told first: each keeps its minimum cached
        # until a posted event reaches it (measured: the window's own read of its minimum stayed
        # at the old number after the central layout was activated), and the check measures the
        # growth, so the window has to grow NOW.
        if page.minimumWidth() > before and w.isVisible():
            node = page
            while node is not None and node is not w:
                node.updateGeometry()
                if node.layout() is not None:
                    node.layout().invalidate()
                node = node.parentWidget()
            w._keep_on_screen()

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

    def _right_half(self) -> tuple[QRect, QRect]:
        """`(the free area of the window's screen, the window's own area that puts its FRAME on
        the right half of it)`.

        The frame, not the window's area (tcc#110, finding 118: on the Windows VM the window opened
        shifted left). `setGeometry` places the area inside the frame, and the frame goes around
        it: a title bar above, and on Windows invisible resize borders at the sides and the bottom
        too. The right half given to the area put the frame over the middle line and past the top
        and the bottom of the free area. The frame is read off the window as drawn now (the same
        before `show` as the area, until the window system has drawn one). The free area is the
        screen's the window is on, less the taskbar or the dock and the menu bar."""
        w = self.window
        free = w.screen().availableGeometry()
        frame, inner = w.frameGeometry(), w.geometry()
        half = free.width() // 2
        right = QRect(free.x() + half, free.y(), free.width() - half, free.height())
        return free, right.adjusted(max(0, inner.left() - frame.left()),
                                    max(0, inner.top() - frame.top()),
                                    -max(0, frame.right() - inner.right()),
                                    -max(0, frame.bottom() - inner.bottom()))

    def _place_on_screen(self) -> None:
        """TCC on the right half of its screen, full height; the terminal on the left (A12,
        tcc#110)."""
        w = self.window
        # A maximised window keeps its state through `setGeometry`, and Windows draws it maximised
        # at a rect that is not its screen's: a normal window first (`leave` maximises it again).
        if w.windowState() & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen):
            w.showNormal()
        free, area = self._right_half()
        # The full window's minimum, left behind until this mode's layout is laid out, would
        # widen the window past the half; this mode's own comes with its layout.
        w.setMinimumWidth(0)
        w.setGeometry(area)
        place_terminal_left(free)
