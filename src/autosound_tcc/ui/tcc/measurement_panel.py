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
from html import escape
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QSizePolicy,
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

from autosound_tcc.core import capture_import, config, process_writer
from autosound_tcc.core.rew_bridge import RewBridge
from autosound_tcc.state import process_view
from autosound_tcc.ui.tcc import i18n, qt_shutdown
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc.capture_import_dialog import CaptureImportDialog
from autosound_tcc.ui.tcc.flow_layout import FlowLayout as _FlowLayout
from autosound_tcc.ui.tcc.mock_data import MeasItem, MeasSession, MEAS_SESSIONS, PLAN
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.theme import current_theme

# measurement_panel.py -> tcc -> ui -> autosound_tcc -> assets/icons (Lucide, ISC license -- see
# NOTICE.md at the repo root).
_ICONS_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"

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
    """Renames measurements in sequence, one REW HTTP call per pair, addressed by uuid.

    **The pairs come in as `(uuid, title)` and the ordinal is worked out HERE**, from a
    `measurements()` call made immediately before the first rename. That is the whole reason this
    worker exists rather than a loop in the dialog: between the list a person read and the moment
    they pressed Apply, REW's ordinals can have moved — measured on 2026-09-02, a manual drag
    swapped two of them while every uuid, title and date stayed put. A pair built when the table
    was drawn would rename the wrong measurement, which is the exact failure the method's identity
    hygiene is written against (`rew-api-quirks.md`).

    Renaming itself does not reshuffle (`rew_api.rename_measurement`: the ordinal is unchanged,
    only the title), so one resolve at the top of the batch is enough.

    Stops at the first failure rather than pressing on with a half-renamed batch -- `renamed` in
    the `failed` payload lets the caller report exactly how far it got, and record exactly that
    much."""

    done = Signal(list)  # list of (uuid, new_title) actually renamed, in order
    failed = Signal(str, list)  # error message, list of (uuid, new_title) renamed before it failed

    def __init__(self, bridge: RewBridge, pairs: list[tuple[str, str]]) -> None:
        super().__init__()
        self._bridge = bridge
        self._pairs = pairs

    def run(self) -> None:
        renamed: list[tuple[str, str]] = []
        try:
            live = self._bridge.measurements()
        except Exception as exc:  # noqa: BLE001 — REW went away between the list and Apply
            self.failed.emit(f"{type(exc).__name__}: {exc}", renamed)
            return
        ordinals = capture_import.resolve_ordinals(live, [uuid for uuid, _title in self._pairs])
        for uuid, title in self._pairs:
            mid = ordinals.get(uuid)
            if mid is None:
                # Deleted, or hidden by a filter switched on since the list was drawn. Either way
                # there is no measurement to rename, and guessing one by position is how `m-R`
                # data ends up under the `m-L` label.
                self.failed.emit(i18n.t("capImportGone").format(title=title), renamed)
                return
            try:
                self._bridge.rename_measurement(mid, title)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(f"{type(exc).__name__}: {exc}", renamed)
                return
            renamed.append((uuid, title))
        self.done.emit(renamed)


class _LedgerWriteWorker(QThread):
    """Everything the ledger has to be told about a batch that just came in, off the GUI thread.

    **It opens the round when there is none.** A capture round is a PASS (SCR-034), and until now
    only a session could open one, through MCP `start_capture` — there was no path from the window
    at all. So a tuner working without a model took measurements the ledger never heard of, and the
    first thing that writes about the pass refused: "Набір замірів не відкрито, тож писати нема до
    чого" on the Protection dialog, with seven green rows on screen behind it (user, 2026-09-06).
    Taking measurements in IS the pass; this is where that is written down.

    Off the thread because each of these is the skill's own CLI in a subprocess (`process_writer`),
    a few hundred milliseconds apiece. The protective half used to run on the GUI thread; one round
    of seven channels plus the captures is several seconds of a window that does not repaint.

    Every write is independent and a refusal is named rather than raised: a channel the gate turns
    down must not silence the six that were fine, and a capture that will not record must not take
    the protective record with it.
    """

    done = Signal(dict)

    def __init__(self, *, project_dir: Path, round_id: str, version, expected: list,
                 titles: list, protective: dict) -> None:
        super().__init__()
        self._project_dir = project_dir
        self._round_id = str(round_id or "")
        self._version = version
        self._expected = list(expected or [])
        self._titles = list(titles or [])
        self._protective = dict(protective or {})

    @staticmethod
    def _why(exc: Exception) -> str:
        """The gate's own last line — its words, not ours (`PROTOCOL` §2.6 in the hub, and the
        same rule the Protection dialog follows)."""
        lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
        return lines[-1] if lines else f"{type(exc).__name__}: {exc}"

    def run(self) -> None:
        result: dict = {"round_id": self._round_id, "opened": "", "recorded": [],
                        "refused": [], "prot_done": [], "prot_refused": []}
        if not self._round_id:
            try:
                process_writer.start_capture(
                    self._project_dir, str(self._version), self._expected)
                round_ = process_view.capture_round(self._project_dir) or {}
                result["round_id"] = str(round_.get("id") or "")
                result["opened"] = result["round_id"]
            except Exception as exc:  # noqa: BLE001 — the gate's words, not ours
                # Without a round there is nowhere for the rest to go. The measurements are in the
                # project's own store either way (`capture_import.record_imported` ran first).
                result["refused"].append(self._why(exc))
                self.done.emit(result)
                return
        for title in self._titles:
            try:
                process_writer.record_capture(self._project_dir, title)
                result["recorded"].append(title)
            except Exception as exc:  # noqa: BLE001
                result["refused"].append(self._why(exc))
        for channel, legs in sorted(self._protective.items()):
            try:
                process_writer.set_protective(self._project_dir, channel, legs)
                result["prot_done"].append(channel)
            except Exception as exc:  # noqa: BLE001
                result["prot_refused"].append(
                    i18n.t("capImportProtRefused").format(channel=channel, why=self._why(exc)))
        self.done.emit(result)


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


class _MeasName(QLabel):
    """A capture's name, which gives ground instead of demanding room.

    `labels.ElidedLabel` is the app's own answer to this and it is plain text only; this label has
    to colour a trailing qualifier and the whole name of an off-checklist graph, so it renders
    HTML. It therefore elides the composite string itself and re-colours what survived.

    Why it has to: the right column is a fixed ~300 px (`main_window._build_right`) with its
    horizontal scrollbar deliberately off, so a card that asks for more is simply cut. Three
    columns of `m-L_01 (sw) · 3` ask for more — and what went over the edge was the right-hand end
    of the card, including the two icon buttons in its header (user, 2026-09-06, with the picture).

    The full name is on the hover whenever anything was cut, so nothing is lost — only moved.
    """

    #: Enough for a dot, a channel and the start of the method — below this the row says nothing.
    _MIN_WIDTH = 46

    def __init__(self) -> None:
        super().__init__()
        self.setTextFormat(Qt.TextFormat.RichText)
        # `Ignored`: the row takes the width the column has, and never sets it.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(self._MIN_WIDTH)
        self._base = ""
        self._extra = ""
        self._additional = False

    def set_parts(self, base: str, extra: Optional[str] = None, additional: bool = False) -> None:
        self._base = str(base or "")
        self._extra = str(extra or "")
        self._additional = bool(additional)
        self._draw()

    def full_text(self) -> str:
        """The name as it stands, uncut — what the row is actually about."""
        return f"{self._base} {self._extra}".strip() if self._extra else self._base

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._draw()

    def _draw(self) -> None:
        theme = current_theme()
        full = self.full_text()
        shown = self.fontMetrics().elidedText(
            full, Qt.TextElideMode.ElideRight, max(self.width(), self._MIN_WIDTH))
        self.setToolTip(full if shown != full else "")
        head, tail = shown[:len(self._base)], shown[len(self._base):].strip()
        if self._additional:
            html = f'<span style="color:{theme.info}">{escape(shown)}</span>'
        elif tail:
            html = f'{escape(head)} <span style="color:{theme.info}">{escape(tail)}</span>'
        else:
            html = escape(shown)
        super().setText(html)


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
        self._protective = getattr(item, "protective", "")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(6)
        self._dot = TrafficLight(item.status)
        layout.addWidget(self._dot)
        self._name_label = _MeasName()
        layout.addWidget(self._name_label, 1)
        #: What was in the signal path while this channel was measured. A glyph, not the numbers:
        #: the column is ~100 px wide and the numbers go on the hover (the same lesson as the
        #: names themselves). Hidden when the round says there was no protective filter — two
        #: states, which is what the record has since 2026-09-06.
        self._prot = QLabel("⌁")
        self._prot.setProperty("class", "mn-prot")
        self._prot_tip = attach_tip(self._prot)
        layout.addWidget(self._prot)
        self._render()

    def _render(self) -> None:
        base = with_method(self.item_name, self.method_suffix)
        if self._count:
            base += f" · {self._count}"
        # Class first, text second: the class carries the font (`.mn` is the monospace face), and
        # eliding against the font the label had a moment ago cuts at the wrong character.
        self._name_label.setProperty("class", f"mn mn-{self._status}")
        self._name_label.style().unpolish(self._name_label)
        self._name_label.style().polish(self._name_label)
        self._name_label.set_parts(base, self._extra, self._additional)
        self._prot.setVisible(bool(self._protective))
        if self._protective:
            self._prot_tip.set_text(i18n.t("measProtTip").format(legs=self._protective))

    @property
    def status(self) -> str:
        """What this row currently shows -- one of the `_LEGEND` keys."""
        return self._status

    @property
    def additional(self) -> bool:
        """Whether this row is a graph outside the checklist rather than one it asks for.

        Read when the round says what it is waiting for: an extra is something REW happens to hold
        at this version, and pre-ticking those would take another sitting's curves into the round —
        the exact noise the import window exists to keep out.
        """
        return bool(self._additional)



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
    #: The grid switched to another capture series. The curve window listens: its delay bank is
    #: scoped by series, and a window left open while the panel moves would keep showing the
    #: corrections of a series nobody is looking at any more (user, 2026-08-12).
    sessionChanged = Signal(str)

    def __init__(self, preset_provider: Optional[Callable[[], str]] = None) -> None:
        """`preset_provider` returns the current preset name, so each capture method's saved order
        is kept per-preset; defaults to None for headless/no-project use."""
        super().__init__()
        self._bridge = RewBridge()
        self._worker: "_RewScanWorker | None" = None
        # Every title this panel has seen REW hold, this session. There was no such collection at
        # all: `known_titles()` was called by the checklist and by the supervisor's own audit, and
        # the panel never defined it, so both silently ran on "REW holds nothing" -- a checklist
        # that could never mark anything captured from REW, and an audit that could never back a
        # step with a measurement.
        self._known_titles: set[str] = set()
        self._rename_worker: "_RewRenameWorker | None" = None
        #: What the open import dialog handed over: the rows to write down, the renames to send,
        #: and the round they belong to. Held between the dialog closing and the rename returning.
        self._taking: list = []
        self._renaming: list = []
        self._protective: dict = {}
        self._round_id = ""
        #: What the round was waiting for when ⤓ was pressed — the pass's own list, read before
        #: anything was written and used to open the round if none was open.
        self._expected: list = []
        #: The ledger series the checklist was derived at, handed down by the window with the
        #: sessions. Needed to OPEN a round: a round is a pass AT a version (SCR-034).
        self._capture_version = None
        self._ledger_worker: "_LedgerWriteWorker | None" = None
        #: Extra sentences on the status line, kept as keys — see `_add_status`.
        self._status_extra: list = []
        self._rows: list[_MeasRow] = []
        self._preset_provider = preset_provider
        self._settings = get_settings()
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
        # A row that WRAPS, not one that cannot shrink. Measured on the user's own project
        # (2026-09-06): this legend's minimum was 345 px against a card that had 249, so it — not
        # the measurement columns — was what pushed the card past the edge of the panel and cut
        # it. Eliding is the wrong tool here: a legend explaining "знятий, не підходить" is read,
        # and "зня…" keeps the width while losing the point.
        legend_layout = _FlowLayout(legend, spacing=10)
        legend_layout.setContentsMargins(0, 0, 0, 0)
        # A wrapping layout answers its height only when asked WITH a width, and a widget has to
        # say it works that way or the layout above it reserves one row and the second is drawn
        # over whatever is under it. The curve window's chip row says the same thing about itself.
        policy = legend.sizePolicy()
        policy.setHeightForWidth(True)
        legend.setSizePolicy(policy)
        self._legend_labels: list[QLabel] = []
        for status, key in _LEGEND:
            dot = TrafficLight(status)
            text = QLabel(i18n.t(key))
            text.setProperty("class", "meas-legend-label")
            legend_layout.addWidget(dot)
            legend_layout.addWidget(text)
            self._legend_labels.append(text)
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
        self._status_extra = []
        self._render_status()

    def _add_status(self, key: str, **kwargs) -> None:
        """A second sentence on the same line — an import says two things at once (what came in,
        and what was written about the chain), and remembering them as KEYS rather than as text is
        what keeps a language switch from freezing them mid-sentence."""
        self._status_extra.append((key, kwargs))
        self._render_status()

    def _render_status(self) -> None:
        if self._status is None:
            return
        parts = []
        for key, kwargs in [self._status, *self._status_extra]:
            parts.append(i18n.t(key).format(**kwargs) if kwargs else i18n.t(key))
        self._status_label.setText(" ".join(parts))

    def set_no_project(self, message: str) -> None:
        """Hide the (mock) capture grid and show a plain message instead -- called by MainWindow
        when there's no real project on disk at all. `set_sessions()` reverses this the moment a
        real capture task arrives."""
        self._has_real_sessions = False  # whatever was derived is gone; do not redraw it later
        for widget in (
            self._session_combo,
            self._version,
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
            self._curves_btn,
            self._read_btn,
        ):
            widget.setVisible(True)
        self._legend.setVisible(True)
        self._no_project_label.setVisible(False)

    def _session(self, session_id: str) -> MeasSession:
        return next(s for s in self._sessions if s.id == session_id)

    def set_sessions(self, sessions, version=None) -> None:
        """Replace the mock series with one derived from the glossary + REW (SCR-008).

        Passing None or an empty tuple says so in words. An empty grid would read as "everything
        captured" rather than "nothing known", and the mock it used to fall back to read as a
        series someone had already taken.

        `version` is the ledger series the checklist was derived at — the window works it out
        (`main_window._capture_version`) and the panel needs it to OPEN a capture round when the
        tuner takes measurements without a session having opened one (2026-09-06).
        """
        if version is not None:
            self._capture_version = version
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
        # A stretch survives the widgets it was set for, so a session with fewer groups than the
        # last one would keep reserving room for columns that no longer exist.
        for column in range(len(getattr(self, "_col_methods", ()))):
            self._cols_layout.setColumnStretch(column, 0)
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
            # Every column gets the same share of a column that cannot grow: without this the
            # first group takes the width its longest name asks for and the last one goes over
            # the edge of the card (user, 2026-09-06). The rows elide inside their share.
            self._cols_layout.setColumnStretch(c, 1)
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
        for button in (self._protective_btn,):
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
        self._curves_tip.set_text(i18n.t("curveBtn"))
        # Both of these are WORDS on the button, not glyphs, so the label has to move too -- the
        # icon buttons above only need their tip re-set.
        self._protective_btn.setText(i18n.t("protBtn"))
        self._protective_tip.set_text(i18n.t("protBtnTip"))
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

    def known_titles(self) -> list[str]:
        """Every capture title this project can be said to have: what REW showed this session, and
        what the project has taken in. Sorted, so callers are order-stable.

        The second half is the new one, and it is the half that survives. "Captured" used to mean
        "REW is showing a title like that RIGHT NOW", so the checklist emptied itself when REW was
        closed — or filtered, which is worse, because a filter is invisible from here: the same
        call answered 17, then 85, then 102 from one file as the user changed it (2026-09-02).
        """
        return sorted(self._known_titles | set(capture_import.imported_titles()))

    def taken_titles(self) -> list[str]:
        """What this project has TAKEN IN — the half of `known_titles` that colours a row.

        Split out on 2026-09-06: folded together, a title REW happened to be showing turned a slot
        green before anything was taken, and the tuner then hit "no capture round is open" on the
        first thing that actually writes (Protection). REW's list is an offer; this is the record.
        """
        return sorted(capture_import.imported_titles())

    def outstanding_titles(self) -> list[str]:
        """The full REW names this round is still waiting for, in the grid's own order.

        What the import window opens ticked on. Extras are left out on purpose: they are graphs
        REW holds that this checklist never asked for.
        """
        return [with_method(row.item_name, row.method_suffix) for row in self._rows
                if row.status == "wait" and not row.additional]

    def _remember_titles(self, titles) -> None:
        before = len(self._known_titles)
        self._known_titles.update(t for t in titles if str(t).strip())
        if len(self._known_titles) != before:
            self.titlesChanged.emit()

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
        for worker in (self._worker, self._rename_worker, self._ledger_worker):
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
        self._round_id = str(round_.get("id") or "")
        # Read once, HERE, and kept: this is what the pass is about. By the time the batch is
        # written down the grid has already been rebuilt off the store, so asking again would
        # answer with what is STILL outstanding — and open a round expecting the leftovers.
        self._expected = self.outstanding_titles()
        dialog = CaptureImportDialog(
            measurements,
            expected=self._expected,
            round_id=self._round_id,
            has_task=bool(self._sessions and self._sessions[0].groups),
            name_sets=self._method_channel_pairs() if self._sessions else {},
            project_dir=config.project_dir(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._set_status("measReadCancelled", n=len(measurements))
            return
        self._taking = list(dialog.taken())
        self._renaming = dialog.renames()
        self._protective = dialog.protective()
        if not self._renaming:
            self._finish_import({})
            return
        # Renaming is HTTP, so it is a worker; and the worker resolves uuid -> ordinal itself, from
        # an answer it fetches immediately before the first call. See `_RewRenameWorker`.
        self._set_status("capImportRenaming", n=len(self._renaming))
        self._replace_worker("_rename_worker", _RewRenameWorker(self._bridge, self._renaming))
        self._rename_worker.done.connect(self._on_import_renamed)
        self._rename_worker.failed.connect(self._on_import_rename_failed)
        self._rename_worker.start()

    def _finish_import(self, titles: dict, only: "set | None" = None) -> None:
        """Write down what was taken in, under the names REW now has for them.

        `only` narrows the batch to what actually carries its new name: a measurement whose rename
        never happened is still called what it was called, and recording it under a name it does
        not have would put a title in the checklist that nothing in REW answers to. Left out, it
        simply comes back on the next ⤓ — untouched, and still unprocessed.
        """
        rows = self._taking if only is None else [r for r in self._taking if r.uuid in only]
        written = capture_import.record_imported(
            rows, round_id=self._round_id, project_dir=config.project_dir(), titles=titles)
        if titles:
            self._set_status("capImportRenamed", n=written, renamed=len(titles))
        else:
            self._set_status("capImportDone", n=written)
        # The store changed, so what this project holds changed: the window rebuilds the checklist
        # off it (`main_window._on_rew_titles_changed`).
        self.titlesChanged.emit()
        self._write_ledger(rows, titles)

    def _write_ledger(self, rows: list, titles: dict) -> None:
        """Tell the ledger about the pass: open the round if there is none, record each capture
        under the name REW now has for it, and write the protective record.

        Under the names REW NOW has: a measurement recorded under the name it had before the
        rename is a title nothing in REW answers to — the same rule `_finish_import` already keeps
        for the project's own store.
        """
        taken = [str((titles or {}).get(row.uuid) or row.title)
                 for row in rows if row.identified]
        if not taken and not self._protective:
            return
        protective = self._protective_for(rows, titles)
        if not process_writer.is_available():
            return  # no skill installed: the project's own store is all there is to write
        if not self._round_id and self._capture_version is None:
            # Nothing to open a round AT. Rather than invent a version, leave the ledger alone and
            # keep the measurements where they already are.
            return
        worker = self._replace_worker("_ledger_worker", _LedgerWriteWorker(
            project_dir=config.project_dir(),
            round_id=self._round_id,
            version=self._capture_version,
            expected=list(self._expected),
            titles=taken,
            protective=protective,
        ))
        worker.done.connect(self._on_ledger_written)
        worker.start()

    def _protective_for(self, rows: list, titles: dict) -> dict:
        """What was in the chain, for every channel coming in — typed legs, or `"OFF"`.

        `"OFF"` for a row whose two cells were left empty, rather than nothing at all: an empty
        cell IS the answer "there was no protective filter here, read the curve as measured"
        (user, 2026-09-06). Written down, it is also what keeps a BASELINE round out of the one
        state the method still wants a person for — a baseline capture carrying no record, which
        `core/protective.should_de_embed` answers with `"check"`.
        """
        out = dict(self._protective)
        for row in rows:
            if not row.identified:
                continue
            channel = capture_import.channel_of(
                row, str((titles or {}).get(row.uuid) or ""), config.project_dir())
            if channel and channel not in out:
                out[channel] = "OFF"
        return out

    def _on_ledger_written(self, result: dict) -> None:
        """What the ledger accepted, in the status line — refusals named one by one."""
        self._round_id = str(result.get("round_id") or self._round_id)
        if result.get("opened"):
            self._add_status("capRoundOpened", round=result["opened"])
        if result.get("recorded"):
            self._add_status("capRoundRecorded", n=len(result["recorded"]))
        for why in result.get("refused") or []:
            self._add_status("capRoundRefused", why=why)
        if result.get("prot_done"):
            self._add_status("capImportProtSaved", channels=", ".join(result["prot_done"]))
        for sentence in result.get("prot_refused") or []:
            self._add_status("capImportProtRefusedLine", line=sentence)
        # The round is a fact about the checklist too: what it recorded as taken is what the grid
        # colours, and the Protection dialog now has a pass to write into.
        self.titlesChanged.emit()

    def _on_import_renamed(self, renamed: list) -> None:
        self._finish_import(dict(renamed))

    def _on_import_rename_failed(self, message: str, renamed: list) -> None:
        titles = dict(renamed)
        asked = {uuid for uuid, _title in self._renaming}
        keep = {row.uuid for row in self._taking if row.uuid in titles or row.uuid not in asked}
        rows = [row for row in self._taking if row.uuid in keep]
        written = capture_import.record_imported(
            rows, round_id=self._round_id, project_dir=config.project_dir(), titles=titles)
        self._set_status("capImportRenameFail", n=len(renamed), error=message, taken=written)
        self.titlesChanged.emit()
        # Half a batch is still a pass: what did come in is recorded, under the names it answers
        # to now. What did not is untouched and comes back on the next ⤓.
        self._write_ledger(rows, titles)

    def _on_read_failed(self, message: str) -> None:
        self._read_btn.setEnabled(True)
        self._set_status("measReadFail", error=message)
        # The dot goes out with it. This signal only ever carried the good news, so a REW that was
        # reachable at launch and has since been closed left a green dot over a failed read
        # (user, 2026-09-06).
        self.rewStatusChanged.emit(False)
