"""The right-panel "IN FOCUS NOW" measurement-task card — ported from the prototype's
`renderMeas` (`data/private/prototype/tcc-main.html`): a yellow-accented card with the current
capture-series version, a wait/done/bad legend, and a 3-column grid of per-channel status rows.

Row/column data is still mock (`ui/tcc/mock_data.py`), but the "Прочитати"/Read button (item 1,
2026-07-27) is real: it pulls the latest measurement from a live REW instance via `RewBridge` and
flips the matching row from wait -> done. The real per-stage REW `/measurements` cross-reference
against the expected channel list (replacing the mock grid entirely) is still separate, later work.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QStyle,
    QStyleOptionComboBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import capture_import, config
from autosound_tcc.core.rew_bridge import RewBridge
from autosound_tcc.state import process_view
from autosound_tcc.ui.tcc import i18n, qt_shutdown
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc.capture_import_dialog import CaptureImportDialog
from autosound_tcc.ui.tcc.channel_order_dialog import ChannelOrderDialog
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.theme import current_theme

# measurement_panel.py -> tcc -> ui -> autosound_tcc -> assets/icons (Lucide, ISC license -- see
# NOTICE.md at the repo root).
_ICONS_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"
from autosound_tcc.ui.tcc.mock_data import MeasItem, MeasSession, MEAS_SESSIONS, PLAN

#: How long a closing panel waits for a REW worker before handing it to `qt_shutdown` (F-027).
#: Six seconds was the old wait; it is the grace for a normal in-flight call, not a fix for a hung
#: one, and what happens after it is what stopped being a crash.
_WORKER_WAIT_MS = 6000

# `ui/capture_order/<preset>/<method>` -- the user's declared REW capture sequence, one per capture
# method (sw/rta/rta_group -- item 9 round 2, 2026-07-27: one button covers all three methods, so
# the order is scoped per method, not just per preset). Deliberately a distinct key namespace from
# `ui/tree_collapsed/*` / `ui/plan_progress`.
_CAPTURE_ORDER_KEY_PREFIX = "ui/capture_order/"
# MEAS.groups index -> method key, in the fixed column order the mock "У фокусі зараз" data uses
# (sw (LB) / RTA (MMM) / RTA · group). Index-based rather than string-matching `group.type` --
# simpler, and that column order is a stable convention already (measurement_panel.py's own
# module docstring / mock_data.py).
_METHOD_KEYS = ("sw", "rta", "rta_group")
# Method key -> the suffix actually written into a REW measurement's title (the skill's
# `naming-and-structure.md` §"Method suffix"): only two exist -- acoustic sweep `(sw)` and MMM RTA
# `(rta)` -- an RTA-GROUP capture is still an RTA capture, so it's `(rta)` too, not a third suffix
# (user request 2026-07-28: "SW+Ws_10 (rta)", not "SW+Ws_10 (rta_group)").
_METHOD_SUFFIX = {"sw": "sw", "rta": "rta", "rta_group": "rta"}


def _method_suffix_for(group, column: int) -> str:
    """The `(method)` suffix a column's rows are named with.

    A group that states its own method is believed. The index fallback is the mock's convention,
    and it is only safe for the mock: a derived phase-2 task has five groups, and `_METHOD_KEYS[3]`
    is an IndexError raised while drawing the panel.
    """
    method = getattr(group, "method", None)
    if method:
        return _METHOD_SUFFIX.get(method, method)
    if column < len(_METHOD_KEYS):
        return _METHOD_SUFFIX[_METHOD_KEYS[column]]
    return "rta"


def with_method(name: str, suffix: str) -> str:
    """`"c_1"` or `"c_1 (sw)"` in, `"c_1 (sw)"` out.

    The skill's expected names already carry the method, so appending it unconditionally prints
    `c_1 (sw) (sw)`. The row rendering learned that once; the capture-order dialog was built from
    the same names later and had to learn it again (user, 2026-08-07) — so the rule lives here now
    rather than at each call site that formats one.
    """
    name = (name or "").strip()
    tail = f"({suffix})"
    return name if name.endswith(tail) else f"{name} {tail}"

#: (traffic-light status, i18n key). Keys, not words: three of the four had a Ukrainian
#: translation sitting unused in the table while the legend showed English (2026-08-12).
_LEGEND = (
    ("wait", "legWait"),
    ("done", "legDone"),
    ("bad", "legBad"),
    # Recorded as decided against, with a reason (SCR-034) -- not the same as outstanding, which is
    # what it looked like before the skill kept a record of the round.
    ("skip", "legSkip"),
)


class _RewScanWorker(QThread):
    """One read-only `measurements()` pull, off the GUI thread — `rew_api`'s HTTP is synchronous.

    Serves both doors: the import dialog, which needs the whole answer (title, uuid and date per
    measurement), and the older assign-names step, which compares what REW holds against the saved
    channel-order count before renaming anything.

    There used to be a second, near-identical worker that mapped the same answer down to titles,
    for a Read that folded everything into the card. That Read is gone (`_on_read_clicked` opens
    the dialog now) and so is the worker: two threads that differ by one comprehension are two
    places to fix the next REW quirk in.

    One HTTP call, not one per measurement: the frequency response is not fetched. It was only ever
    used to print a point count, and paying N round-trips for a cosmetic number is not a trade
    worth making when N is the whole list."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, bridge: RewBridge) -> None:
        super().__init__()
        self._bridge = bridge

    def run(self) -> None:
        try:
            self.done.emit(self._bridge.measurements())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class _RewRenameWorker(QThread):
    """Renames measurements in sequence, one REW HTTP call per pair. Stops at the first failure
    rather than pressing on with a half-renamed batch -- `renamed` in the `failed` payload lets the
    caller report exactly how far it got."""

    done = Signal(list)  # list of (mid, new_title) actually renamed, in order
    failed = Signal(str, list)  # error message, list of (mid, new_title) renamed before it failed

    def __init__(self, bridge: RewBridge, pairs: list[tuple[str, str]]) -> None:
        super().__init__()
        self._bridge = bridge
        self._pairs = pairs

    def run(self) -> None:
        renamed: list[tuple[str, str]] = []
        try:
            for mid, title in self._pairs:
                self._bridge.rename_measurement(mid, title)
                renamed.append((mid, title))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}", renamed)
            return
        self.done.emit(renamed)


class TrafficLight(QLabel):
    """A small colored dot, `status` one of the `tl-*` QSS classes (theme.py) -- originally this
    panel's own legend dot, public because main_window.py reuses it for the REW-online indicator."""

    def __init__(self, status: str) -> None:
        super().__init__()
        self.setProperty("class", f"tl tl-{status}")
        self.setFixedSize(9, 9)

    def set_status(self, status: str) -> None:
        self.setProperty("class", f"tl tl-{status}")
        self.style().unpolish(self)
        self.style().polish(self)


class _MeasRow(QWidget):
    """One channel's status row. Shows the FULL name a capture will actually get in REW --
    `<name> (<method>)` -- not just the bare channel id (user request 2026-07-28), so the list
    doubles as a preview of the real filenames. `extra`/`additional` (same request) render in blue:
    `additional` colors the whole name (a graph outside the expected list turned up during a read/
    scan); `extra` colors only the qualifier text trailing an otherwise-expected name."""

    def __init__(self, item: MeasItem, method_suffix: str) -> None:
        super().__init__()
        self.item_name = item.name
        self.method_suffix = method_suffix
        self._status = item.status
        self._count = item.count
        self._extra = item.extra
        self._additional = item.additional
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(6)
        self._dot = TrafficLight(item.status)
        layout.addWidget(self._dot)
        self._name_label = QLabel()
        self._name_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._name_label)
        layout.addStretch(1)
        self._render()

    def _render(self) -> None:
        t = current_theme()
        base = with_method(self.item_name, self.method_suffix)
        if self._count:
            base += f" · {self._count}"
        if self._additional:
            html = f'<span style="color:{t.info}">{base}</span>'
        elif self._extra:
            html = f'{base} <span style="color:{t.info}">{self._extra}</span>'
        else:
            html = base
        self._name_label.setText(html)
        self._name_label.setProperty("class", f"mn mn-{self._status}")
        self._name_label.style().unpolish(self._name_label)
        self._name_label.style().polish(self._name_label)

    @property
    def status(self) -> str:
        """What this row currently shows -- one of the `_LEGEND` keys."""
        return self._status



def _step_label(step_id: str) -> str:
    """A short human-readable label for a `mock_data.PLAN` step id (e.g. "2.3 target-match
    (SQ-Comp-Ref)"), or the bare id if it's not found (a stale/removed step)."""
    for phase in PLAN:
        for step in phase.steps:
            if step.id == step_id:
                return i18n.tx(step.name)
    return step_id


_SERIES_ID = re.compile(r"^v(\d+)$")


def _session_label(session_id: str) -> str:
    """`v6` reads as a version of something and explains nothing; `series 6` says which axis it
    is on. A round id (`cap_001`) is the OTHER axis -- two passes at one config -- and keeps the
    name the journal gave it, which is what makes the two tellable apart in one list.

    User, 2026-08-21: "ось цей v6 (а до цього було v4 і ще щось) не дуже розумію і інтуітивно не
    зрозуміло що означає". The curve window spells the same number the same way now.
    """
    found = _SERIES_ID.match(session_id)
    return i18n.t("seriesItem").format(v=found.group(1)) if found else session_id


class MeasurementPanel(QWidget):
    """The card's own yellow-tinted border is applied by the caller (main_window.py) — this widget is just the content that goes inside it."""

    # A real Read/Scan call is the freshest possible signal of whether REW is actually reachable --
    # main_window.py's REW-online dot listens to this rather than polling on its own.
    rewStatusChanged = Signal(bool)
    # REW's own list of titles changed (a scan, or a read that named one). The window rebuilds the
    # checklist off this and runs the capture check; the panel itself decides nothing about them.
    titlesChanged = Signal()
    #: The header's "Protection" button. The panel does not own the dialog: it has neither the
    #: project's channel list nor the writer, and both live where the window already keeps them.
    protectiveRequested = Signal()
    #: The header's "Listening" button (Phase 4). Same reason as the one above: the panel has
    #: neither the method's vocabulary nor the writer.
    listeningRequested = Signal()
    #: The grid switched to another capture series. The curve window listens: its delay bank is
    #: scoped by series, and a window left open while the panel moves would keep showing the
    #: corrections of a series nobody is looking at any more (user, 2026-08-12).
    sessionChanged = Signal(str)

    def __init__(self, preset_provider: Optional[Callable[[], str]] = None) -> None:
        """`preset_provider` returns the current preset name, so each capture method's saved order
        is kept per-preset; defaults to None for headless/no-project use."""
        super().__init__()
        self._bridge = RewBridge()
        self._worker: "_RewReadWorker | None" = None
        self._scan_worker: "_RewScanWorker | None" = None
        # Every title this panel has seen REW hold, this session. There was no such collection at
        # all: `known_titles()` was called by the checklist and by the supervisor's own audit, and
        # the panel never defined it, so both silently ran on "REW holds nothing" -- a checklist
        # that could never mark anything captured from REW, and an audit that could never back a
        # step with a measurement.
        self._known_titles: set[str] = set()
        self._rename_worker: "_RewRenameWorker | None" = None
        self._rows: list[_MeasRow] = []
        self._preset_provider = preset_provider
        self._settings = get_settings()
        self._pending_order: list[str] = []
        # Sessions, newest first -- [0] is the live, in-progress task (see MEAS_SESSIONS' own
        # docstring). `_viewing_id` is whichever one the grid currently shows; Read/Scan/assign-
        # names always act on the live session regardless (see `_on_read_clicked` etc.'s guard).
        self._sessions = MEAS_SESSIONS
        self._viewing_id = self._sessions[0].id
        # Whether `_sessions` is a REAL derived capture task or still the mock fixture. The
        # difference only ever mattered on a language switch, which is exactly where it was
        # missing -- see `retranslate`.
        self._has_real_sessions = False
        # Which session the grid was last actually BUILT for. Distinct from `_viewing_id`, which
        # `set_sessions` assigns before it renders anything -- comparing against that one would
        # answer "unchanged" for every switch that arrives with new data.
        self._shown_id: Optional[str] = None
        # The last status line as (i18n key, format args) rather than as finished text, so a
        # language switch re-renders it instead of leaving a Ukrainian sentence under an English
        # window. None = nothing to say yet, which is not the same as an empty string.
        self._status: Optional[tuple[str, dict]] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        # Session picker (user request 2026-07-28): a dropdown, ~1/5 of the row, a gap, then the
        # title banner taking the rest -- picking a past series switches that banner from "what to
        # capture" to "which step it was used for" (see `show_session`). Stretch 1:4 (not a fixed
        # width) so both keep their ratio if the panel is resized.
        self._session_combo = QComboBox()
        self._session_combo.setProperty("class", "mini-select")
        for session in self._sessions:
            marker = " ●" if session.id == self._sessions[0].id else ""
            self._session_combo.addItem(_session_label(session.id) + marker, session.id)
        self._session_combo.currentIndexChanged.connect(
            lambda _idx: self.show_session(self._session_combo.currentData())
        )
        # A round id is `cap_001` plus the live-marker dot, and at stretch 1 against the banner's
        # 4 it was eliding to "cap_00…" — a picker whose entries cannot be told apart (user,
        # 2026-08-11). Sized to its own contents instead of to a share of the row.
        self._session_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._session_combo.setMinimumContentsLength(11)
        # And a floor measured off the rows themselves, because that length is counted in `x`
        # widths and a round id is not made of `x`: eleven of them come to less than `cap_002 ●`,
        # so the closed box went back to "cap_00…" — a picker whose entries cannot be told apart,
        # for the second time (user, 2026-08-11 and again 2026-08-21).
        self._session_tip = attach_tip(self._session_combo)
        self._fit_session_combo()
        head_row.addWidget(self._session_combo)
        self._version = QLabel("")
        self._version.setProperty("class", "meas-head")
        self._version_tip = attach_tip(self._version)
        head_row.addWidget(self._version, 1)
        # Icon-only, not full-text buttons -- the text labels ate too much of this header row next
        # to the version banner (user request 2026-07-27). Full label moved to the tooltip. Real
        # SVG icons (Lucide, ISC-licensed -- NOTICE.md), not unicode glyphs, for a sharper look.
        self._assign_names_btn = QPushButton()
        self._assign_names_btn.setIcon(QIcon(str(_ICONS_DIR / "reorder.svg")))
        self._assign_names_btn.setIconSize(QSize(16, 16))
        self._assign_names_btn.setProperty("class", "meas-icon-btn")
        self._assign_names_btn.setFixedSize(28, 28)
        self._assign_names_tip = attach_tip(self._assign_names_btn, i18n.t("assignNames"))
        self._assign_names_btn.clicked.connect(self._on_assign_names_clicked)
        head_row.addWidget(self._assign_names_btn)
        # Curves, with markers on them: the panel that turns "I read it differently" into a
        # number (see `curve_view.py`). Beside Read because that is where the measurements are.
        self._curves_btn = QPushButton()
        self._curves_btn.setIcon(QIcon(str(_ICONS_DIR / "activity.svg")))
        self._curves_btn.setIconSize(QSize(16, 16))
        self._curves_btn.setProperty("class", "meas-icon-btn")
        self._curves_btn.setFixedSize(28, 28)
        self._curves_tip = attach_tip(self._curves_btn, i18n.t("curveBtn"))
        self._curves_btn.clicked.connect(self._on_curves_clicked)
        head_row.addWidget(self._curves_btn)

        self._read_btn = QPushButton()
        self._read_btn.setIcon(QIcon(str(_ICONS_DIR / "download.svg")))
        self._read_btn.setIconSize(QSize(16, 16))
        self._read_btn.setProperty("class", "meas-icon-btn meas-icon-btn-read")
        self._read_btn.setFixedSize(28, 28)
        self._read_tip = attach_tip(self._read_btn, i18n.t("measRead"))
        self._read_btn.clicked.connect(self._on_read_clicked)
        head_row.addWidget(self._read_btn)
        layout.addLayout(head_row)

        # A second row for the two buttons that carry WORDS. They were in the row above and the
        # words came out clipped ("Protectior", "Listening" against the edge — the user's own
        # screenshot, 2026-08-25): that row is sized for 28×28 glyphs beside a stretching banner,
        # and a label has no width to bargain with there. They belong together anyway — both write
        # down a fact about the pass in front of you rather than acting on it, one from the
        # measuring chain and one from the ear.
        facts_row = QHBoxLayout()
        facts_row.setSpacing(8)

        # What was in the signal path while this round was measured: a fact about the CAPTURE, one
        # protective set per pass. A word rather than a glyph, because there is no icon for "what
        # was in the chain" and inventing one would be a picture nobody can read.
        self._protective_btn = QPushButton(i18n.t("protBtn"))
        self._protective_btn.setProperty("class", "reason-btn")
        self._protective_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._protective_tip = attach_tip(self._protective_btn, i18n.t("protBtnTip"))
        self._protective_btn.clicked.connect(self.protectiveRequested.emit)
        facts_row.addWidget(self._protective_btn)

        # What the EAR says about the state now in the car (Phase 4).
        self._listening_btn = QPushButton(i18n.t("lsnBtn"))
        self._listening_btn.setProperty("class", "reason-btn")
        self._listening_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._listening_tip = attach_tip(self._listening_btn, i18n.t("lsnBtnTip"))
        self._listening_btn.clicked.connect(self.listeningRequested.emit)
        facts_row.addWidget(self._listening_btn)

        facts_row.addStretch(1)
        layout.addLayout(facts_row)
        self._fit_fact_buttons()

        self._status_label = QLabel("")
        self._status_label.setProperty("class", "meas-legend-label")
        self._status_label.setWordWrap(True)
        self._status_label.setHidden(True)
        layout.addWidget(self._status_label)

        legend = QWidget()
        self._legend = legend
        legend_layout = QHBoxLayout(legend)
        legend_layout.setContentsMargins(0, 0, 0, 0)
        legend_layout.setSpacing(10)
        self._legend_labels: list[QLabel] = []
        for status, key in _LEGEND:
            dot = TrafficLight(status)
            text = QLabel(i18n.t(key))
            text.setProperty("class", "meas-legend-label")
            legend_layout.addWidget(dot)
            legend_layout.addWidget(text)
            self._legend_labels.append(text)
        legend_layout.addStretch(1)
        layout.addWidget(legend)

        self._cols_layout = QGridLayout()
        self._cols_layout.setHorizontalSpacing(8)
        self._cols_layout.setVerticalSpacing(2)
        self._col_next_row: list[int] = []
        layout.addLayout(self._cols_layout)

        # Shown instead of the grid when there's no real project to derive a capture task from --
        # an EMPTY grid reads as "everything captured" (see `set_sessions`), which is worse than
        # the mock it would otherwise fall back to, so this needs its own real state.
        self._no_project_label = QLabel("")
        self._no_project_label.setProperty("class", "phead-sub")
        self._no_project_label.setWordWrap(True)
        self._no_project_label.setVisible(False)
        layout.addWidget(self._no_project_label)

        self.show_session(self._viewing_id)
        # ...and then hide it. `MEAS_SESSIONS` still builds the grid so the widget has its real
        # shape (and the unit tests keep it as a fixture), but a project is never shown a capture
        # series it did not take: opening one and being met with "capture series v10" over
        # invented channel names is the plan panel's retired demo plan in a second place.
        self.set_no_project(i18n.t("measNoTask"))

    def _set_status(self, key: str, **kwargs) -> None:
        """Show a status line, remembering WHICH line it is so `retranslate` can redraw it."""
        self._status = (key, kwargs)
        self._render_status()

    def _render_status(self) -> None:
        if self._status is None:
            return
        key, kwargs = self._status
        self._status_label.setText(i18n.t(key).format(**kwargs) if kwargs else i18n.t(key))

    def set_no_project(self, message: str) -> None:
        """Hide the (mock) capture grid and show a plain message instead -- called by MainWindow
        when there's no real project on disk at all. `set_sessions()` reverses this the moment a
        real capture task arrives."""
        self._has_real_sessions = False  # whatever was derived is gone; do not redraw it later
        for widget in (
            self._session_combo,
            self._version,
            self._assign_names_btn,
            self._curves_btn,
            self._read_btn,
        ):
            widget.setVisible(False)
        self._legend.setVisible(False)
        while self._cols_layout.count():
            item = self._cols_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []
        self._no_project_label.setText(message)
        self._no_project_label.setVisible(True)

    def _show_content(self) -> None:
        for widget in (
            self._session_combo,
            self._version,
            self._assign_names_btn,
            self._curves_btn,
            self._read_btn,
        ):
            widget.setVisible(True)
        self._legend.setVisible(True)
        self._no_project_label.setVisible(False)

    def _session(self, session_id: str) -> MeasSession:
        return next(s for s in self._sessions if s.id == session_id)

    def set_sessions(self, sessions) -> None:
        """Replace the mock series with one derived from the glossary + REW (SCR-008).

        Passing None or an empty tuple says so in words. An empty grid would read as "everything
        captured" rather than "nothing known", and the mock it used to fall back to read as a
        series someone had already taken.
        """
        if not sessions:
            self.set_no_project(i18n.t("measNoTask"))
            return
        self._show_content()  # reverses a prior set_no_project(), a no-op otherwise
        self._has_real_sessions = True
        self._sessions = tuple(sessions)
        self._viewing_id = self._sessions[0].id
        self._session_combo.blockSignals(True)
        self._session_combo.clear()
        for session in self._sessions:
            marker = " ●" if session.id == self._sessions[0].id else ""
            self._session_combo.addItem(_session_label(session.id) + marker, session.id)
        self._fit_session_combo()
        self._session_combo.blockSignals(False)
        self.show_session(self._viewing_id)

    def viewing_session_id(self) -> str:
        """Which capture series the grid is showing. The curve window scopes its delay bank by
        this: switching back to an earlier series must bring that series' own corrections, not the
        current one's (user, 2026-08-12)."""
        return self._viewing_id

    def _fit_session_combo(self) -> None:
        """Never let the picker be narrower than the longest id it is holding.

        `minimumContentsLength` is Qt's own way to say this and it is counted in the width of an
        `x`, which underestimates `cap_002 ●` — digits, an underscore and the live-round dot are
        all wider. Measured off the rows instead, plus the chrome the stylesheet spends: 22 px of
        right padding reserving the arrow, 9 px on the left, and the 1 px border either side.
        """
        metrics = self._session_combo.fontMetrics()
        widest = max(
            (metrics.horizontalAdvance(self._session_combo.itemText(i))
             for i in range(self._session_combo.count())),
            default=0,
        )
        # The chrome was a constant of 33 and `серія 6` still came back clipped on a real macOS
        # build (user, 2026-08-21, second run). Ask the style what its own frame costs instead of
        # trusting the stylesheet's numbers to be the whole story, and keep a floor under it.
        style_option = QStyleOptionComboBox()
        style_option.initFrom(self._session_combo)
        chrome = self._session_combo.style().sizeFromContents(
            QStyle.ContentsType.CT_ComboBox, style_option, QSize(0, 0), self._session_combo
        ).width()
        self._session_combo.setMinimumWidth(widest + max(chrome, 33) + 4)

    def show_session(self, session_id: str) -> None:
        """Switch the grid to show `session_id` -- the live session ([0]) is fully interactive
        (Read/Scan/assign-names enabled) and the title banner shows what to capture; any other is
        a read-only history view (those actions stay pointed at the live session regardless, see
        their own guards, so they're disabled here rather than silently acting on the wrong
        series), and the banner instead shows the plan step(s) it was used for/created (user
        request 2026-07-28). Called by picking this panel's own session dropdown and, from the
        other direction, `ui/tcc/plan_panel.py`'s per-step measurement icon."""
        session = self._session(session_id)
        if session_id != self._shown_id:
            # A count of what matched belongs to the grid it was counted against. Carrying "16
            # matched" over to a phase showing different rows -- or none -- states something false
            # about what is on screen (user, 2026-08-11).
            self._status = None
            self._status_label.setText("")
        self._viewing_id = self._shown_id = session_id
        self.sessionChanged.emit(session_id)
        is_live = session_id == self._sessions[0].id
        if is_live:
            # No banner here either, since 2026-08-21's second run: kept for the live round on
            # the argument that its text is the panel's title, it turned out to elide to
            # "Фаза −1 ·" -- a title with the title cut off -- while taking the width the picker
            # needed. Both halves now live on the picker's hint, which never elides.
            self._session_tip.set_text(i18n.tx(session.version))
        else:
            # No banner for a past round (user, 2026-08-21: "кнопка «Використа» не потрібна — це
            # може бути хінт на поле"). "Used in step 3" is a fact about the round the picker is
            # already naming, and as a widget it was taking the width the picker needed to print
            # `cap_002` — while eliding to "Використа" itself. It survives as the picker's hint,
            # where the fuller per-step wording already lived.
            steps = ", ".join(session.used_in_steps) or "—"
            self._session_tip.set_text(
                "<br>".join([i18n.t("measUsedInStep").format(steps=steps)]
                            + [_step_label(s) for s in session.used_in_steps])
            )
        self._version.setVisible(False)
        self._assign_names_btn.setEnabled(is_live)
        self._read_btn.setEnabled(is_live)
        idx = self._session_combo.findData(session_id)
        if idx >= 0 and self._session_combo.currentIndex() != idx:
            self._session_combo.blockSignals(True)
            self._session_combo.setCurrentIndex(idx)
            self._session_combo.blockSignals(False)

        while self._cols_layout.count():
            item = self._cols_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []
        self._col_next_row = []
        self._col_methods: list[str] = []
        # A phase that captures nothing (phase 1 analyses the series phase 0 took) is a real
        # answer, and `measurement_view` already returns it as a session with no groups. It was
        # rendered as an empty grid under a live legend, which reads as a mock left on screen
        # rather than as an answer (user, 2026-08-11) — and the legend explains colours that no
        # row has. Say it in words instead, and keep the header: the series is still selectable.
        empty_phase = not session.groups
        self._legend.setVisible(not empty_phase)
        self._no_project_label.setVisible(empty_phase)
        if empty_phase:
            self._no_project_label.setText(i18n.t("measPhaseNoCapture"))
        for c, group in enumerate(session.groups):
            header = QLabel(group.type)
            header.setProperty("class", "mcol-h")
            self._cols_layout.addWidget(header, 0, c)
            method_suffix = _method_suffix_for(group, c)
            self._col_methods.append(method_suffix)
            for r, item in enumerate(group.items, start=1):
                row = _MeasRow(item, method_suffix)
                self._rows.append(row)
                self._cols_layout.addWidget(row, r, c)
            self._col_next_row.append(len(group.items) + 1)

    def _fit_fact_buttons(self) -> None:
        """Keep the two word buttons wide enough for the words actually on them.

        Qt's `sizeHint` for a QPushButton does not count the horizontal padding the stylesheet
        adds (`.reason-btn` is `padding: 4px 12px`), so a label longer than the short ones that
        class was built for gets clipped -- which is how "Protection" reached the user as
        "Protectior". German is the long case here ("Schutz" is short but "Hören" sits beside a
        wider neighbour in other rows), so this runs again after every language change rather than
        once at build time.
        """
        for button in (self._protective_btn, self._listening_btn):
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance(button.text()) + 34)

    def retranslate(self) -> None:
        """Re-render whatever this panel is currently showing, in the new language.

        It used to end with an unconditional `set_no_project()`. That was written when the mock was
        the only thing the panel could hold, and the line's own job was to hide it -- but `set_
        sessions()` (SCR-008) later gave the panel a REAL capture task to hold, and the language
        switch went on wiping it. Sixteen captures read from REW, switch to English, empty card
        (user, 2026-08-11). What a panel shows must not depend on which language it shows it in.
        """
        if self._has_real_sessions:
            self.show_session(self._viewing_id)
        else:
            # No real task derived yet. `MEAS_SESSIONS` is still the widget's shape fixture, but a
            # project is never SHOWN a capture series it did not take: being met with "capture
            # series v10" over invented channel names is the plan panel's retired demo plan in a
            # second place.
            self.set_no_project(i18n.t("measNoTask"))
        self._render_status()  # the last Read/Scan result, in the new language too
        for label, (_status, key) in zip(self._legend_labels, _LEGEND):
            label.setText(i18n.t(key))
        self._read_tip.set_text(i18n.t("measRead"))
        self._assign_names_tip.set_text(i18n.t("assignNames"))
        self._curves_tip.set_text(i18n.t("curveBtn"))
        # Both of these are WORDS on the button, not glyphs, so the label has to move too -- the
        # icon buttons above only need their tip re-set.
        self._protective_btn.setText(i18n.t("protBtn"))
        self._protective_tip.set_text(i18n.t("protBtnTip"))
        self._listening_btn.setText(i18n.t("lsnBtn"))
        self._listening_tip.set_text(i18n.t("lsnBtnTip"))
        self._fit_fact_buttons()

    # ---- capture-order (item 9) ---------------------------------------------

    def _capture_order_key(self, method: str) -> str:
        preset = self._preset_provider() if self._preset_provider else None
        return f"{_CAPTURE_ORDER_KEY_PREFIX}{preset or 'default'}/{method}"

    def _saved_order(self, method: str) -> Optional[list[str]]:
        raw = self._settings.value(self._capture_order_key(method), None)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    def _method_channel_pairs(self) -> dict[str, list[tuple[str, str]]]:
        """One entry per capture method that actually has channels in the live session's data
        (`self._sessions[0]` -- always the current/in-progress task, regardless of which session
        the grid happens to be displaying, see `show_session`) -- a phase/step with no RTA-group
        channels just won't offer that tab. A previously-saved order for a method overrides the
        session's own item order as the seed, same relabel-by-id fallback as before."""
        methods: dict[str, list[tuple[str, str]]] = {}
        for key, group in zip(_METHOD_KEYS, self._sessions[0].groups):
            # Display label is the FULL name the capture will actually get in REW -- "<id> (method)"
            # -- not just the bare channel id (user request 2026-07-28); the id itself (first tuple
            # element) stays bare so previously-saved orders keyed by it are unaffected.
            suffix = _METHOD_SUFFIX[key]
            meas_pairs = [(item.name, with_method(item.name, suffix)) for item in group.items]
            if not meas_pairs:
                continue
            saved = self._saved_order(key)
            if saved is None:
                methods[key] = meas_pairs
            else:
                # Reorder by the saved sequence, but never DROP a channel MEAS currently has just
                # because a stale saved order (from before MEAS's item list changed) doesn't
                # mention it -- append any such leftover at the end, in its original MEAS order.
                by_id = dict(meas_pairs)
                ordered = [(cid, by_id[cid]) for cid in saved if cid in by_id]
                saved_ids = set(saved)
                remaining = [(cid, label) for cid, label in meas_pairs if cid not in saved_ids]
                methods[key] = ordered + remaining
        return methods

    def _on_assign_names_clicked(self) -> None:
        # Always opens -- one button now covers all three capture methods (sw/RTA/RTA-group), so
        # picking a method is mandatory every time; there's no "just reuse the last one" default to
        # silently fall back to (user request 2026-07-27 round 2, replacing the old first-use/
        # modifier-key/"don't show again" gating, which assumed a single implicit method).
        dialog = ChannelOrderDialog(self._method_channel_pairs(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        method = dialog.get_method()
        if method is None:
            return
        order = dialog.get_order()
        self._settings.setValue(self._capture_order_key(method), json.dumps(order))
        self._scan_and_match(order)

    def _scan_and_match(self, order: list[str]) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        self._status_label.setHidden(False)
        self._set_status("measReading")
        self._pending_order = order
        self._replace_worker("_scan_worker", _RewScanWorker(self._bridge))
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_read_failed)
        self._scan_worker.start()

    def known_titles(self) -> list[str]:
        """Every capture title this project can be said to have: what REW showed this session, and
        what the project has taken in. Sorted, so callers are order-stable.

        The second half is the new one, and it is the half that survives. "Captured" used to mean
        "REW is showing a title like that RIGHT NOW", so the checklist emptied itself when REW was
        closed — or filtered, which is worse, because a filter is invisible from here: the same
        call answered 17, then 85, then 102 from one file as the user changed it (2026-09-02).
        """
        return sorted(self._known_titles | set(capture_import.imported_titles()))

    def _remember_titles(self, titles) -> None:
        before = len(self._known_titles)
        self._known_titles.update(t for t in titles if str(t).strip())
        if len(self._known_titles) != before:
            self.titlesChanged.emit()

    def _on_scan_done(self, measurements: dict) -> None:
        self.rewStatusChanged.emit(True)
        self._remember_titles(
            (m or {}).get("title", "") for m in (measurements or {}).values()
        )
        order = self._pending_order
        expected = len(order)
        found_count = len(measurements)
        if found_count < expected:
            self._set_status("captureScanMismatch", found=found_count, expected=expected)
            return
        # The `expected` highest-ordinal ids are treated as "the newest batch" -- same "highest
        # ordinal = most recent" heuristic as _RewReadWorker (rew-api-quirks.md: REW's own ordinal
        # position is fragile, not a real timestamp). Sorted ascending so the OLDEST of that batch
        # lines up with the FIRST channel in the saved capture order, matching capture sequence.
        newest_ids = sorted(
            measurements, key=lambda k: int(k) if str(k).isdigit() else -1
        )[-expected:]
        # First-cut naming: the target title is just the channel id from the saved order (e.g.
        # "w_L") -- no capture-version or sweep/RTA-method suffix, since neither is tracked by this
        # button yet (see naming-and-structure.md §3 for the fuller `<channel>_<version> (method)`
        # convention). Extend here once a "current capture version/method" concept exists.
        pairs = list(zip(newest_ids, order))
        self._set_status("captureRenaming", n=len(pairs))
        self._replace_worker("_rename_worker", _RewRenameWorker(self._bridge, pairs))
        self._rename_worker.done.connect(self._on_rename_done)
        self._rename_worker.failed.connect(self._on_rename_failed)
        self._rename_worker.start()

    def _on_rename_done(self, renamed: list) -> None:
        self._set_status("captureRenameOk", n=len(renamed))

    def _on_rename_failed(self, message: str, renamed: list) -> None:
        self._set_status("captureRenameFail", error=message, n=len(renamed))

    def _replace_worker(self, attr: str, worker: QThread) -> QThread:
        """Put `worker` in `self.<attr>`, waiting out whatever was there.

        Assigning over an attribute that still holds a RUNNING QThread destroys it on the spot,
        and Qt answers that with `qFatal` -- the process aborts, mid-session, with a crash report
        (seen: `QThread::~QThread()` reached through `Sbk_QWidget_setattro`). The read button
        guards itself; scan and rename did not, so a second scan while the first was in flight, or
        a rename started from a scan that was still running, could take the window out.
        """
        previous = getattr(self, attr, None)
        if previous is not None and previous.isRunning():
            previous.wait(6000)
        setattr(self, attr, worker)
        return worker

    def shutdown(self) -> None:
        """Block briefly for any in-flight REW worker before the window closes -- Qt aborts the
        whole process ("QThread: Destroyed while thread is still running") if a QThread object is
        garbage-collected while still alive, which a running-but-unawaited worker risks the moment
        this panel (and its `self._worker`/etc. references) goes away. Each worker's own HTTP calls
        are timeout-bounded (rew_api.py's `_TIMEOUT_S`), so this wait is bounded too -- not a fix
        for a truly hung call, just enough to let a normal in-flight one finish first.

        The wait alone was the same half-guard F-027 found in the curve window, one file over: it
        waited and then closed ANYWAY, so a REW still answering after six seconds took the process
        with it. These workers have no parent either, so `qt_shutdown.quiesce_widgets` never saw
        them. One that outlasts the wait now goes to `qt_shutdown` instead of being destroyed --
        which also puts it in front of the exit path, where it can be declined over rather than
        aborted on.
        """
        for worker in (self._worker, self._scan_worker, self._rename_worker):
            qt_shutdown.stop_or_detach(worker, _WORKER_WAIT_MS)

    curvesRequested = Signal(list)  # REW titles to plot — MainWindow opens the window

    def _on_curves_clicked(self) -> None:
        """Ask for the curve window over whatever titles are on screen.

        The panel does not own the window: it knows which measurements this task is about, and
        MainWindow knows about REW and the dialog. Kept apart so the same window can later be
        opened by the model through MCP without going through a widget.
        """
        rows = [with_method(r.item_name, r.method_suffix) for r in self._rows]
        known = self.known_titles()
        # Prefer titles REW actually holds; fall back to the expected names so the picker is not
        # empty on a task where nothing has been read yet.
        titles = [t for t in rows if t in known] or known or rows
        self.curvesRequested.emit(titles)

    def _on_read_clicked(self) -> None:
        """Fetch what REW is showing, then ask which of it comes in.

        It used to fold the whole answer into the grid. On the run that produced the redesign that
        was 102 titles — 16 expected, 86 appended as "additional" rows — a card 1864 px tall,
        most of it another car's library, inside a card called "IN FOCUS NOW" (user, 2026-09-02).
        """
        if self._worker is not None and self._worker.isRunning():
            return
        self._read_btn.setEnabled(False)
        self._status_label.setHidden(False)
        self._set_status("measReading")
        self._replace_worker("_worker", _RewScanWorker(self._bridge))
        self._worker.done.connect(self._on_import_offer)
        self._worker.failed.connect(self._on_read_failed)
        self._worker.start()

    def _on_import_offer(self, measurements: dict) -> None:
        """REW answered; put the answer in front of the tuner.

        `_remember_titles` first and unconditionally: what REW HOLDS is a fact whether or not
        anything is ticked, and the plan audit and the curve window's title list both ask this
        panel that question. What the tick decides is a different thing — which measurements this
        project has taken IN, which is what the store keeps and what survives REW being closed.
        """
        self.rewStatusChanged.emit(True)
        self._read_btn.setEnabled(True)
        if not measurements:
            self._set_status("measReadNoMeas")
            return
        self._remember_titles(
            (m or {}).get("title", "") for m in measurements.values()
        )
        round_ = process_view.capture_round() or {}
        dialog = CaptureImportDialog(
            measurements,
            waiting=sum(1 for row in self._rows if row.status == "wait"),
            round_id=str(round_.get("id") or ""),
            has_task=bool(self._sessions and self._sessions[0].groups),
            project_dir=config.project_dir(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._set_status("measReadCancelled", n=len(measurements))
            return
        self._set_status("capImportDone", n=dialog.written)
        # The store changed, so what this project holds changed: the window rebuilds the checklist
        # off it (`main_window._on_rew_titles_changed`).
        self.titlesChanged.emit()

    def _on_read_failed(self, message: str) -> None:
        self._read_btn.setEnabled(True)
        self._set_status("measReadFail", error=message)
