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
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core.rew_bridge import RewBridge
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc.channel_order_dialog import ChannelOrderDialog
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.theme import current_theme

# measurement_panel.py -> tcc -> ui -> autosound_tcc -> assets/icons (Lucide, ISC license -- see
# NOTICE.md at the repo root).
_ICONS_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"
from autosound_tcc.ui.tcc.mock_data import MeasItem, MeasSession, MEAS_SESSIONS, PLAN

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

_LEGEND = (("wait", "waiting"), ("done", "done"), ("bad", "taken, unusable"))


class _RewReadWorker(QThread):
    """Pulls the latest measurement's metadata + frequency response off a background thread --
    `rew_api`'s HTTP calls are synchronous (plain `urllib`), so calling them from the GUI thread
    would freeze the window for the duration of the request. Mirrors the QThread+signals shape
    already used for `profile_interview_dialog.py`'s `_AgentWorker` (that one also runs asyncio,
    which this doesn't need since REW's client isn't async)."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, bridge: RewBridge) -> None:
        super().__init__()
        self._bridge = bridge

    def run(self) -> None:
        try:
            measurements = self._bridge.measurements()
            if not measurements:
                self.failed.emit(i18n.t("measReadNoMeas"))
                return
            # REW's measurement ids are ordinals, not stable identity (rew-api-quirks.md) -- there
            # is no "currently selected measurement" concept in the API at all. Highest ordinal is
            # used as a "most recent" heuristic, same caveat rew_api.py itself documents for id
            # reuse; if this proves unreliable in practice, replace with an explicit picker rather
            # than trusting the heuristic further.
            mid = max(measurements, key=lambda k: int(k) if str(k).isdigit() else -1)
            title = (measurements[mid] or {}).get("title", "")
            freqs, mag, _phase = self._bridge.frequency_response(mid)
            self.done.emit({"id": mid, "title": title, "n_points": len(freqs)})
        except Exception as exc:  # noqa: BLE001 — surface any REW/network failure, don't crash
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class _RewScanWorker(QThread):
    """Item 9's "scan for new measurements" step: a read-only `measurements()` pull, so the caller
    can compare what REW actually holds against the saved channel-order count before renaming
    anything."""

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
        # The skill's expected names already carry the method (`c_1 (sw)`), so appending it again
        # printed `c_1 (sw) (sw)` down the whole task -- reported from a real phase-0 task.
        suffix = f"({self.method_suffix})"
        name = self.item_name.strip()
        base = name if name.endswith(suffix) else f"{name} {suffix}"
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

    def mark_done(self, extra: Optional[str] = None) -> None:
        self._status = "done"
        if extra:
            self._extra = extra
        self._dot.set_status("done")
        self._render()


def _step_label(step_id: str) -> str:
    """A short human-readable label for a `mock_data.PLAN` step id (e.g. "2.3 target-match
    (SQ-Comp-Ref)"), or the bare id if it's not found (a stale/removed step)."""
    for phase in PLAN:
        for step in phase.steps:
            if step.id == step_id:
                return i18n.tx(step.name)
    return step_id


class MeasurementPanel(QWidget):
    """The card's own yellow-tinted border is applied by the caller (main_window.py) — this widget is just the content that goes inside it."""

    # A real Read/Scan call is the freshest possible signal of whether REW is actually reachable --
    # main_window.py's REW-online dot listens to this rather than polling on its own.
    rewStatusChanged = Signal(bool)

    def __init__(self, preset_provider: Optional[Callable[[], str]] = None) -> None:
        """`preset_provider` returns the current preset name, so each capture method's saved order
        is kept per-preset; defaults to None for headless/no-project use."""
        super().__init__()
        self._bridge = RewBridge()
        self._worker: "_RewReadWorker | None" = None
        self._scan_worker: "_RewScanWorker | None" = None
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
            self._session_combo.addItem(session.id + marker, session.id)
        self._session_combo.currentIndexChanged.connect(
            lambda _idx: self.show_session(self._session_combo.currentData())
        )
        head_row.addWidget(self._session_combo, 1)
        self._version = QLabel("")
        self._version.setProperty("class", "meas-head")
        self._version_tip = attach_tip(self._version)
        head_row.addWidget(self._version, 4)
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
        self._read_btn = QPushButton()
        self._read_btn.setIcon(QIcon(str(_ICONS_DIR / "download.svg")))
        self._read_btn.setIconSize(QSize(16, 16))
        self._read_btn.setProperty("class", "meas-icon-btn meas-icon-btn-read")
        self._read_btn.setFixedSize(28, 28)
        self._read_tip = attach_tip(self._read_btn, i18n.t("measRead"))
        self._read_btn.clicked.connect(self._on_read_clicked)
        head_row.addWidget(self._read_btn)
        layout.addLayout(head_row)

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
        for status, label in _LEGEND:
            dot = TrafficLight(status)
            text = QLabel(label)
            text.setProperty("class", "meas-legend-label")
            legend_layout.addWidget(dot)
            legend_layout.addWidget(text)
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
        self._no_project_active = False

        self.show_session(self._viewing_id)
        # ...and then hide it. `MEAS_SESSIONS` still builds the grid so the widget has its real
        # shape (and the unit tests keep it as a fixture), but a project is never shown a capture
        # series it did not take: opening one and being met with "capture series v10" over
        # invented channel names is the plan panel's retired demo plan in a second place.
        self.set_no_project(i18n.t("measNoTask"))

    def set_no_project(self, message: str) -> None:
        """Hide the (mock) capture grid and show a plain message instead -- called by MainWindow
        when there's no real project on disk at all. `set_sessions()` reverses this the moment a
        real capture task arrives. `_no_project_active` is what stops `retranslate()` from
        rebuilding the mock grid back in via `show_session()` on a language switch."""
        self._no_project_active = True
        for widget in (
            self._session_combo,
            self._version,
            self._assign_names_btn,
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
        self._no_project_active = False
        for widget in (
            self._session_combo,
            self._version,
            self._assign_names_btn,
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
        self._sessions = tuple(sessions)
        self._viewing_id = self._sessions[0].id
        self._session_combo.blockSignals(True)
        self._session_combo.clear()
        for session in self._sessions:
            marker = " ●" if session.id == self._sessions[0].id else ""
            self._session_combo.addItem(session.id + marker, session.id)
        self._session_combo.blockSignals(False)
        self.show_session(self._viewing_id)

    def show_session(self, session_id: str) -> None:
        """Switch the grid to show `session_id` -- the live session ([0]) is fully interactive
        (Read/Scan/assign-names enabled) and the title banner shows what to capture; any other is
        a read-only history view (those actions stay pointed at the live session regardless, see
        their own guards, so they're disabled here rather than silently acting on the wrong
        series), and the banner instead shows the plan step(s) it was used for/created (user
        request 2026-07-28). Called by picking this panel's own session dropdown and, from the
        other direction, `ui/tcc/plan_panel.py`'s per-step measurement icon."""
        session = self._session(session_id)
        self._viewing_id = session_id
        is_live = session_id == self._sessions[0].id
        if is_live:
            self._version.setText(i18n.tx(session.version))
            self._version_tip.set_text("")
        else:
            steps = ", ".join(session.used_in_steps) or "—"
            self._version.setText(i18n.t("measUsedInStep").format(steps=steps))
            self._version_tip.set_text("<br>".join(_step_label(s) for s in session.used_in_steps))
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
        for c, group in enumerate(session.groups):
            header = QLabel(group.type)
            header.setProperty("class", "mcol-h")
            self._cols_layout.addWidget(header, 0, c)
            method_suffix = _METHOD_SUFFIX[_METHOD_KEYS[c]]
            for r, item in enumerate(group.items, start=1):
                row = _MeasRow(item, method_suffix)
                self._rows.append(row)
                self._cols_layout.addWidget(row, r, c)
            self._col_next_row.append(len(group.items) + 1)

    def retranslate(self) -> None:
        # show_session() rebuilds _cols_layout from the (mock) session data -- skip it while
        # set_no_project() is active, or a language switch would silently bring the mock grid
        # back over a real "no project" state.
        if not self._no_project_active:
            self.show_session(self._viewing_id)
        # ...and then hide it. `MEAS_SESSIONS` still builds the grid so the widget has its real
        # shape (and the design/unit tests keep a fixture), but a project is not shown a capture
        # series it never took: opening one and being met with "capture series v10" over invented
        # channel names is the plan panel's retired demo plan in a second place.
        self.set_no_project(i18n.t("measNoTask"))  # re-renders the banner text in the new language
        self._read_tip.set_text(i18n.t("measRead"))
        self._assign_names_tip.set_text(i18n.t("assignNames"))

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
            meas_pairs = [(item.name, f"{item.name} ({suffix})") for item in group.items]
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
        self._status_label.setText(i18n.t("measReading"))
        self._pending_order = order
        self._scan_worker = _RewScanWorker(self._bridge)
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_read_failed)
        self._scan_worker.start()

    def _on_scan_done(self, measurements: dict) -> None:
        self.rewStatusChanged.emit(True)
        order = self._pending_order
        expected = len(order)
        found_count = len(measurements)
        if found_count < expected:
            self._status_label.setText(
                i18n.t("captureScanMismatch").format(found=found_count, expected=expected)
            )
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
        self._status_label.setText(i18n.t("captureRenaming").format(n=len(pairs)))
        self._rename_worker = _RewRenameWorker(self._bridge, pairs)
        self._rename_worker.done.connect(self._on_rename_done)
        self._rename_worker.failed.connect(self._on_rename_failed)
        self._rename_worker.start()

    def _on_rename_done(self, renamed: list) -> None:
        self._status_label.setText(i18n.t("captureRenameOk").format(n=len(renamed)))

    def _on_rename_failed(self, message: str, renamed: list) -> None:
        self._status_label.setText(
            i18n.t("captureRenameFail").format(error=message, n=len(renamed))
        )

    def shutdown(self) -> None:
        """Block briefly for any in-flight REW worker before the window closes -- Qt aborts the
        whole process ("QThread: Destroyed while thread is still running") if a QThread object is
        garbage-collected while still alive, which a running-but-unawaited worker risks the moment
        this panel (and its `self._worker`/etc. references) goes away. Each worker's own HTTP calls
        are timeout-bounded (rew_api.py's `_TIMEOUT_S`), so this wait is bounded too -- not a fix
        for a truly hung call, just enough to let a normal in-flight one finish first."""
        for worker in (self._worker, self._scan_worker, self._rename_worker):
            if worker is not None and worker.isRunning():
                worker.wait(6000)

    def _on_read_clicked(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._read_btn.setEnabled(False)
        self._status_label.setHidden(False)
        self._status_label.setText(i18n.t("measReading"))
        self._worker = _RewReadWorker(self._bridge)
        self._worker.done.connect(self._on_read_done)
        self._worker.failed.connect(self._on_read_failed)
        self._worker.start()

    def _on_read_done(self, result: dict) -> None:
        self.rewStatusChanged.emit(True)
        self._read_btn.setEnabled(True)
        title = result.get("title", "")
        self._status_label.setText(
            i18n.t("measReadOk").format(title=title, n=result.get("n_points", 0))
        )
        row, extra = self._classify_title(title)
        if row is not None:
            row.mark_done(extra)
            return
        # No expected channel matched at all -- not an error, an "additional" graph (user request
        # 2026-07-28: names with modifiers or wholly extra graphs are OK, just flag them rather
        # than silently drop them). Base name = the title with any trailing "(method)" stripped.
        base = title.split(" (")[0].strip()
        col = self._guess_column_for_new_title(title)
        self._add_dynamic_row(col, MeasItem(name=base, status="done", additional=True))

    def _classify_title(self, title: str) -> tuple[Optional["_MeasRow"], Optional[str]]:
        """Match a REW measurement title against the known rows. Returns `(row, extra)`: `extra`
        is any qualifier text trailing the row's own expected `"<name> (<method>)"` pattern (a
        capture-mode modifier REW or the user added, e.g. a re-take note) -- None if it matches
        exactly. `(None, None)` means the title doesn't correspond to any expected channel at all
        (see `_on_read_done` for what happens then)."""
        for row in self._rows:
            if not title.startswith(row.item_name):
                continue
            remainder = title[len(row.item_name):].strip()
            expected_suffix = f"({row.method_suffix})"
            if remainder == "" or remainder == expected_suffix:
                return row, None
            if remainder.startswith(expected_suffix):
                extra = remainder[len(expected_suffix):].strip()
                return row, extra or None
            # Starts with this row's channel id, but the parenthetical doesn't match this row's
            # own method (e.g. an "(rta)" title coincidentally prefix-matching a sw-column row) --
            # not this row; keep looking rather than misreport the wrong method as "extra".
        return None, None

    def _guess_column_for_new_title(self, title: str) -> int:
        """Which column an "additional" graph (unmatched by `_classify_title`) should land in.
        Heuristic, not authoritative -- `(sw)` is unambiguous, but `(rta)` covers both the plain
        RTA column and RTA-GROUP (same suffix, see `_METHOD_SUFFIX`), so group-shaped names
        (combined-driver tokens, matching the mock RTA-GROUP column's own Ws/Ms/TWs/SW+Ws/L/R/ALL
        convention) route there; anything else defaults to the plain RTA column. A wrong guess
        just means a two-second manual re-check, not lost data."""
        if title.rstrip().endswith("(sw)"):
            return 0
        base = title.split(" (")[0].strip()
        if "+" in base or base in {"L", "R", "ALL"} or base.startswith(("Ws", "Ms", "TWs")):
            return 2
        return 1

    def _add_dynamic_row(self, col: int, item: MeasItem) -> None:
        method_suffix = _METHOD_SUFFIX[_METHOD_KEYS[col]]
        row = _MeasRow(item, method_suffix)
        self._rows.append(row)
        r = self._col_next_row[col]
        self._col_next_row[col] = r + 1
        self._cols_layout.addWidget(row, r, col)

    def _on_read_failed(self, message: str) -> None:
        self._read_btn.setEnabled(True)
        self._status_label.setText(i18n.t("measReadFail").format(error=message))
