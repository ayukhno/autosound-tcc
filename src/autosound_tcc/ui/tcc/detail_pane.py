"""The center detail pane — ported from the prototype's `.detail` (Table/EQ/⇄L+R tabs + close,
opening in the top half above the AI dialog): `openTable`/`openEq`/`bandHtml`/`siblingName`
(`data/private/prototype/tcc-main.html`).

Two views share one pane:
  * Table  — every row in a group, one column per declared field (HP/LP/Gain/Delay/Pol/Phase/EQ),
    driven entirely by `group.fields` — a group with fewer/different fields just gets fewer/
    different columns, no per-DSP code.
  * EQ     — band cards for one row (Type/Freq/Q/Gain), or two stacked rows (⇄ L+R) with shared-
    frequency color-coding when a sibling channel is found.
"""

from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import eq_export
from autosound_tcc.state.dsp_state import CrossoverLeg, EqBand, GroupRow, ProfileGroup
from autosound_tcc.ui.tcc import copy_menu, i18n, rounded_tooltip
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.theme import apply_caps, current_theme

# field token -> (column header, cell-renderer). Order here is the fallback display order when a
# group declares a field not already covered by a fixed prototype-matching order below.
_FIELD_COLUMNS: dict[str, str] = {
    "hp": "HPF", "lp": "LPF", "gain_db": "Gain dB", "ta_ms": "Delay ms",
    "polarity": "Pol", "phase_deg": "Phase", "mute": "Mute", "off": "Off",
    "eq_bypass": "EQ Byp", "eq": "EQ",
}

#: The controls worth looking at across the whole rig at once, and what each tab is called.
#: Values are callables so the label is read in the CURRENT language every time, not frozen at
#: import; the fields themselves are the ledger's own names.
_PARAM_TABS: dict[str, "object"] = {
    "gain_db": lambda: i18n.t("tabGain"),
    "ta_ms": lambda: i18n.t("tabDelay"),
    "phase_deg": lambda: i18n.t("tabPhase"),
}

_MATCH_PALETTE = ["#5aa9e6", "#4bbf87", "#e8973c", "#c98fe0", "#e8c34a", "#e05c5c"]


def _bank_sentence(channel: str, bank) -> str:
    """What was copied, in what, and what did not make it — in that order.

    The count and the bank size travel together because a fixed-size bank is a FORM: pasting it
    writes its empty rows over whatever those slots held. "8 bands of 30" says that; "copied" does
    not. And a band left out is said with the method's own reason, because "it did not fit" and
    "this format has no room for an all-pass" send a person to different places.
    """
    said = i18n.t("copyEqDone").format(channel=channel, format=bank.format_name)
    if bank.bank_size:
        said = f"{said} {i18n.t('copyEqCount').format(written=bank.written, size=bank.bank_size)}"
    elif bank.written:
        said = f"{said} {i18n.t('copyEqWritten').format(written=bank.written)}"
    if bank.crossovers:
        said = f"{said} {i18n.t('copyEqCrossovers').format(n=bank.crossovers)}"
    for note in bank.notes:
        said = f"{said} {note}"
    if bank.left_out:
        said = f"{said} {i18n.t('copyEqLeftOut').format(what='; '.join(bank.left_out))}"
    return said


def _sibling_name(name: str) -> Optional[str]:
    """Best-effort L<->R sibling lookup across the naming conventions seen in real ledgers:
    "L"/"R" as a standalone word (`Front L Full`, the prototype's own convention) OR as a bare
    trailing suffix with no delimiter at all (`FrontL`/`FrontR`, `w_L`/`w_R`) — the real virtual-
    channel ledger uses the latter. Generic string swap, not tied to any DSP-specific channel
    list; suffix form is tried last since it's the loosest pattern.
    """
    if re.search(r"\bL\b", name):
        return re.sub(r"\bL\b", "R", name, count=1)
    if re.search(r"\bR\b", name):
        return re.sub(r"\bR\b", "L", name, count=1)
    if re.search(r"L$", name):
        return re.sub(r"L$", "R", name)
    if re.search(r"R$", name):
        return re.sub(r"R$", "L", name)
    return None


def _is_left(name: str) -> bool:
    return bool(re.search(r"(\bL\b|L$)", name))


class _DTab(QLabel):
    clicked = Signal()

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setProperty("class", "d-tab")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.accept()
        self.clicked.emit()

    def set_on(self, on: bool) -> None:
        cls = "d-tab on" if on else "d-tab"
        self.setProperty("class", cls)
        self.style().unpolish(self)
        self.style().polish(self)


class EqBandCard(QFrame):
    """One EQ band card: Type/Freq/Q/Gain + a read-only ByPass row. `match_color`, when given,
    draws the colored top border used to flag a shared frequency between paired L/R channels."""

    def __init__(
        self, band: EqBand, match_color: Optional[str] = None, gain_mismatch: bool = False
    ) -> None:
        super().__init__()
        self.setProperty("class", "band")
        self.setFixedWidth(112)
        if match_color:
            # A bare (selector-less) setStyleSheet() rule is implicitly "*" and cascades to every
            # descendant widget, not just this QFrame -- without the type-selector scope, this
            # border-top would also apply to each Freq/Q/Gain row inside, producing a colored bar
            # under every row (a "zebra stripe") instead of a single accent line at the card top.
            self.setStyleSheet(f"EqBandCard {{ border-top: 3px solid {match_color}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bid = QLabel(band.type)
        bid.setProperty("class", "band-id")
        bid.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(bid)

        for label, value in (("Freq", f"{band.freq_hz:g} Hz"),
                              ("Q", f"{band.q:.2f}" if band.q is not None else "—"),
                              ("Gain", f"{band.gain_db:+.1f} dB" if band.gain_db is not None else "—")):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 3, 8, 3)
            fk = QLabel(label)
            fk.setProperty("class", "band-fk")
            fv = QLabel(value)
            # A shared frequency (same top-border match_color) whose L/R gain still differs looked
            # identical to a same-freq/same-gain match -- flag the Gain value specifically so the
            # asymmetry is visible at a glance (user request 2026-07-27).
            fv.setProperty("class", "band-fv-mismatch" if (label == "Gain" and gain_mismatch) else "band-fv")
            row_layout.addWidget(fk)
            row_layout.addStretch(1)
            row_layout.addWidget(fv)
            layout.addWidget(row)

        byp = QLabel("○ ByPass")
        byp.setProperty("class", "band-byp")
        apply_caps(byp, spacing_px=0.8)
        byp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(byp)


def _band_flow(
    bands: tuple[EqBand, ...],
    match_map: Optional[dict[float, str]] = None,
    gain_mismatch_freqs: Optional[set] = None,
) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for band in bands:
        color = (match_map or {}).get(band.freq_hz)
        mismatch = band.freq_hz in (gain_mismatch_freqs or ())
        layout.addWidget(EqBandCard(band, color, mismatch))
    layout.addStretch(1)
    return container


class DetailPane(QFrame):
    """The whole `.detail` panel: tabs, title, close, and a body that shows either a table or an
    EQ view. Hidden by default (`.detail` starts at max-height 0 in the prototype)."""

    closed = Signal()
    tableRowActivated = Signal(str, str)
    #: What was copied and in what format, for the window's status line.
    bankCopied = Signal(str)  # group_id, row_id -> caller opens EQ for it
    eqRequested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("class", "panel")
        self.setVisible(False)
        self._mode: Optional[str] = None  # "table" | "eq" | "param"
        self._group: Optional[ProfileGroup] = None
        self._row: Optional[GroupRow] = None
        self._pair_mode = False
        #: The whole project view, for the one-parameter tabs: gain, delay and phase are asked
        #: about ACROSS the rig ("show the table for all channels, physical and virtual" -- user,
        #: 2026-08-23), and a single group cannot answer that.
        self._view = None
        self._param: Optional[str] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QWidget()
        head.setProperty("class", "phead")
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(12, 6, 12, 6)
        head_layout.setSpacing(6)

        self._tab_table = _DTab(i18n.t("tabTable"))
        self._tab_table.clicked.connect(self._on_tab_table)
        head_layout.addWidget(self._tab_table)
        self._tab_eq = _DTab("EQ")
        self._tab_eq.clicked.connect(self._on_tab_eq)
        head_layout.addWidget(self._tab_eq)
        self._pair_btn = _DTab("⇄ L + R")
        self._pair_btn.clicked.connect(self._on_pair_toggle)
        self._pair_btn.setVisible(False)
        head_layout.addWidget(self._pair_btn)
        self._eq_help = QLabel("?")
        self._eq_help.setProperty("class", "eq-help")
        self._eq_help.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._eq_help.setVisible(False)
        self._eq_help_tip = attach_tip(self._eq_help)
        head_layout.addWidget(self._eq_help)

        # The bank of the channel on screen, in the format its processor takes -- named after the
        # channel, because in the single-channel view that is what "copy EQ" means. Hidden unless
        # the method can produce one for this DSP: a copy button that yields nothing, or
        # something nobody can identify, is worse than no button (user, 2026-08-23).
        self._eq_copy = _DTab(i18n.t("copyEqBank"))
        self._eq_copy.clicked.connect(self._on_copy_eq_bank)
        self._eq_copy.setVisible(False)
        head_layout.addWidget(self._eq_copy)

        # At the END of the left cluster, after the buttons that belong to what is on screen
        # (user, 2026-08-23: "the new buttons at the end of the left set, not in the middle").
        # One parameter, every channel, both tiers -- the same kind of thing as "Table" and "EQ",
        # a way of looking at the rig, but a wider one: the question they answer is a comparison,
        # which a per-group table cannot show while it is one group at a time.
        self._param_tabs: dict[str, _DTab] = {}
        for field, label in _PARAM_TABS.items():
            tab = _DTab(label())
            tab.clicked.connect(lambda _checked=False, f=field: self.open_param(f))
            head_layout.addWidget(tab)
            self._param_tabs[field] = tab
        self._title = QLabel("")
        self._title.setProperty("class", "phead-sub")
        head_layout.addWidget(self._title)
        head_layout.addStretch(1)

        self._close_btn = QPushButton(i18n.t("close"))
        self._close_btn.setProperty("class", "d-close")
        self._close_btn.clicked.connect(self.close_pane)
        head_layout.addWidget(self._close_btn)
        outer.addWidget(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(self._scroll, stretch=1)
        # Sized by the parent QSplitter now (main_window._build_center), which gives the user a
        # drag handle between this pane and the AI dialog below it -- no fixed cap here anymore.

        i18n.on_language_changed(self.retranslate)

    def retranslate(self) -> None:
        """The head is set once at construction; the body is rebuilt from the open group.

        Its four labels were English literals while both translations already sat in the table
        (found 2026-08-12) — the pane simply never registered, so switching to Ukrainian left
        "Table", "close ✕", "Channel" and "shared frequencies:" behind in an otherwise translated
        window.
        """
        self._tab_table.setText(i18n.t("tabTable"))
        for field, tab in getattr(self, "_param_tabs", {}).items():
            tab.setText(_PARAM_TABS[field]())
        self._close_btn.setText(i18n.t("close"))
        if self._group is not None:
            self.refresh_with(self._group)

    # ---- public API ----------------------------------------------------

    def close_pane(self) -> None:
        self.setVisible(False)
        # Clear what's "open" along with visibility -- otherwise `current_group_id()`/
        # `refresh_with()` would keep reporting the just-closed group as open (`_group` isn't
        # otherwise touched by closing), and a later reload would silently re-open a pane the user
        # explicitly closed.
        self._group, self._row, self._mode = None, None, None
        self.closed.emit()

    def open_table(self, group: ProfileGroup, select_row_id: Optional[str] = None) -> None:
        self._group, self._row, self._mode = group, None, "table"
        self._pair_btn.setVisible(False)
        # `rows_visible()` and not `rows`: an off channel is not part of the rig being tuned, and
        # counting it here said "· 8" over six rows (user, 2026-08-21).
        self._title.setText(f"{group.label} · {len(group.rows_visible())}")
        table = self._build_table(group)
        self._scroll.setWidget(table)
        if select_row_id is not None:
            for r, row in enumerate(group.rows_visible()):
                if row.id == select_row_id:
                    table.selectRow(r)
                    break
        self._sync_tabs()
        self.setVisible(True)

    def set_view(self, view) -> None:
        """The project view behind the panel, refreshed on every load.

        Held rather than passed per call because the parameter tabs are pressed from inside this
        widget, long after whoever opened it has gone; and re-rendered from here so a preset
        switch does not leave a table of the previous preset's delays on screen.
        """
        self._view = view
        self._sync_param_tabs()
        if self._mode == "param" and self._param:
            self.open_param(self._param)

    def _param_groups(self, field: str) -> list:
        """Every tier that declares this control and has channels to show, in the view's order."""
        groups = getattr(self._view, "groups", ()) or ()
        return [g for g in groups if field in g.known_fields and g.rows_visible()]

    def _sync_param_tabs(self) -> None:
        """A control no tier declares is not offered -- a processor without phase does not get a
        Phase tab that opens an empty table."""
        for field, tab in self._param_tabs.items():
            tab.setVisible(bool(self._param_groups(field)))
            tab.set_on(self._mode == "param" and self._param == field)

    def open_param(self, field: str) -> None:
        """One control, every channel, both tiers, in one table.

        The per-group table answers "what is this tier set to"; this answers "how do these compare
        across the rig", which is the question somebody actually has about a gain or a delay --
        and it is the one shape the panel could not make before, because it only ever held one
        group at a time.
        """
        groups = self._param_groups(field)
        if not groups:
            return
        self._mode, self._param, self._row = "param", field, None
        self._pair_btn.setVisible(False)
        # The tab's own word, not the column header's: the header is the DSP's vocabulary
        # ("Delay ms", as PC-Tool spells it) and the title is the window's.
        self._title.setText(i18n.t("paramAllChannels").format(param=_PARAM_TABS[field]()))
        self._scroll.setWidget(self._build_param_table(field, groups))
        self._sync_tabs()
        self.setVisible(True)

    def open_eq(self, group: ProfileGroup, row: GroupRow) -> None:
        self._group, self._row, self._mode = group, row, "eq"
        sib_name = _sibling_name(row.name)
        sib_row = next((r for r in group.rows if r.name == sib_name), None) if sib_name else None
        self._pair_btn.setVisible(sib_row is not None)
        if not sib_row:
            self._pair_mode = False
        self._render_eq(group, row, sib_row)
        self._sync_tabs()
        self.setVisible(True)

    def current_group_id(self) -> Optional[str]:
        """The id of the group currently shown (table or EQ), or None if nothing's open --
        lets a caller re-fetch the up-to-date `ProfileGroup` after a project reload without this
        module knowing anything about where groups come from."""
        return self._group.id if self._group is not None else None

    def refresh_with(self, group: ProfileGroup) -> None:
        """Re-render whatever's currently open (table or EQ) using a freshly loaded `group` with
        the same id. `ProfileGroup`/`GroupRow` are immutable snapshots -- without this, a table or
        EQ view left open across a preset switch keeps showing the OLD preset's frozen values
        (mute state and everything else) since nothing tells it a new version was loaded (user
        report 2026-07-28). No-op if the pane isn't currently open.

        Checks `self._group` rather than `self.isVisible()` -- the latter also depends on every
        ancestor being shown, which is false in headless tests (and would make this a silent
        no-op there) even though the pane's own open/closed state is unambiguous."""
        if self._mode == "param" and self._param:
            # Its rows come from the whole view, which `set_view` has already replaced.
            self.open_param(self._param)
            return
        if self._group is None:
            return
        if self._mode == "eq" and self._row is not None:
            row = next((r for r in group.rows if r.id == self._row.id), None)
            if row is not None:
                self.open_eq(group, row)
                return
        self.open_table(group)

    # ---- tabs -----------------------------------------------------------

    def _sync_tabs(self) -> None:
        self._tab_table.set_on(self._mode == "table")
        self._tab_eq.set_on(self._mode == "eq")
        # The tab says WHOSE bank is on screen. With one channel showing, nothing else on the
        # left of the header did: the only name was on the copy button, and the title that
        # carries it sits greyed at the far end of the row (user, 2026-08-23). In pair mode it
        # stays plain -- each heading names its own channel there.
        single = (self._mode == "eq" and self._row is not None
                  and not (self._pair_mode and self._pair_btn.isVisible()))
        self._tab_eq.setText(f"EQ {self._row.name}" if single else "EQ")
        self._sync_param_tabs()
        self._pair_btn.set_on(self._pair_mode)
        self._eq_help.setVisible(self._mode == "eq")
        if self._mode == "eq" and self._row is not None:
            self._eq_copy.setText(f'{i18n.t("copyEqBank")} {self._row.name}')
        else:
            self._eq_copy.setText(i18n.t("copyEqBank"))
        # Gone in pair mode: with two channels on screen it would name one of them, and each
        # heading carries its own copy instead.
        self._eq_copy.setVisible(
            self._mode == "eq"
            and self._row is not None
            and not (self._pair_mode and self._pair_btn.isVisible())
            and bool(self._row.raw.get("eq"))
            and eq_export.available()
        )

    def _on_tab_table(self) -> None:
        if self._group is not None:
            self.open_table(self._group)

    def _on_tab_eq(self) -> None:
        if self._row is not None:
            self.open_eq(self._group, self._row)
        elif self._group is not None and self._group.rows_visible():
            self.open_eq(self._group, self._group.rows_visible()[0])

    def _on_copy_eq_bank(self) -> None:
        """The header's copy: the channel this view was opened on."""
        if self._row is not None and self._group is not None:
            self._copy_bank_of(self._group, self._row)

    def _copy_bank_of(self, group: ProfileGroup, row: GroupRow) -> None:
        """One channel's whole bank, ready to paste into the DSP's own software.

        The window formats nothing: it asks the method, puts what came back on the clipboard, and
        says WHICH format that was -- plus anything the format could not carry, because a band
        quietly dropped on the way to a processor is the kind of loss nobody notices until the
        tune sounds wrong.
        """
        raw = row.raw
        bank = eq_export.format_bank(
            raw.get("eq"),
            crossovers={"hp": raw.get("hp"), "lp": raw.get("lp")},
            group_id=group.id,
            channel=row.name,
        )
        if bank is None:
            self.bankCopied.emit(i18n.t("copyEqNoFormat"))
            return
        QGuiApplication.clipboard().setText(bank.text)
        self.bankCopied.emit(_bank_sentence(row.name, bank))

    def _on_pair_toggle(self) -> None:
        self._pair_mode = not self._pair_mode
        if self._row is not None:
            self.open_eq(self._group, self._row)

    # ---- table view -------------------------------------------------------

    def _build_table(self, group: ProfileGroup) -> QTableWidget:
        columns = [f for f in group.known_fields if f in _FIELD_COLUMNS]
        headers = ["ID", i18n.t("colChan")] + [_FIELD_COLUMNS[f] for f in columns]
        rows = group.rows_visible()
        table = QTableWidget(len(rows), len(headers))
        table.setProperty("class", "ptable")
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        # Fill the pane width (user request: "table on full width"): every column shares the space
        # equally, except the narrow ID column which sizes to its content.
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        apply_caps(header, spacing_px=0.7)  # QSS text-transform/letter-spacing don't apply to th

        t = current_theme()
        for r, row in enumerate(rows):
            id_item = QTableWidgetItem(row.slot or row.id)
            id_item.setForeground(QColor(t.accent))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            table.setItem(r, 0, id_item)
            name_item = QTableWidgetItem(row.name)
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            table.setItem(r, 1, name_item)
            for c, field in enumerate(columns, start=2):
                table.setItem(r, c, self._styled_cell(field, row, t))
            table.setRowHeight(r, 26)

        def _activate(r: int, _c: int) -> None:
            row_obj = rows[r]
            self.tableRowActivated.emit(group.id, row_obj.id)
            # cellClicked fires from inside QTableWidget's own mouseReleaseEvent; open_eq()
            # replaces this table's widget in self._scroll (QScrollArea.setWidget deletes the
            # old widget synchronously), which would destroy `table` while it is still executing
            # its own C++ event handler -- a use-after-free that crashes with SIGSEGV. Deferring
            # to the next event-loop tick lets mouseReleaseEvent return first.
            QTimer.singleShot(0, lambda: self.open_eq(group, row_obj))

        table.cellClicked.connect(_activate)
        self._copy_on_right_click(table)
        return table

    def _build_param_table(self, field: str, groups: list) -> QWidget:
        """One column per tier, side by side -- virtual channels next to the outputs.

        Stacked, the two tiers were a scroll: eight outputs below six virtual channels, with the
        heading of the second block off screen by the time you reached it (user, 2026-08-23:
        "make it two columns, virtual beside output"). Side by side they fit, and the comparison
        that the whole view exists for -- how these numbers sit against each other -- is one
        glance instead of two.
        """
        holder = QWidget()
        columns = QHBoxLayout(holder)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(12)
        for group in groups:
            columns.addWidget(self._param_column(field, group), stretch=1)
        return holder

    def _param_column(self, field: str, group: ProfileGroup) -> QWidget:
        """One tier: its name, then `ID · channel · value` for every channel in it."""
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The tier's name in the panel's language. `group.label` is the PROFILE's word for it
        # ("Output channels"), which is English in a file written once, and reads as a foreign
        # line among Ukrainian rows -- the same fix the project-params rows got.
        said = i18n.t(f"chanSum_{group.id}")
        title = QLabel(said if said != f"chanSum_{group.id}" else group.label)
        title.setProperty("class", "kv-lbl")
        title.setContentsMargins(8, 6, 8, 2)
        layout.addWidget(title)

        rows = group.rows_visible()
        table = QTableWidget(len(rows), 3)
        table.setProperty("class", "ptable")
        table.setHorizontalHeaderLabels(["ID", i18n.t("colChan"), _FIELD_COLUMNS[field]])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        apply_caps(header, spacing_px=0.7)

        t = current_theme()
        for r, row in enumerate(rows):
            id_item = QTableWidgetItem(row.slot or row.id)
            id_item.setForeground(QColor(t.accent))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            table.setItem(r, 0, id_item)
            name_item = QTableWidgetItem(row.name)
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            table.setItem(r, 1, name_item)
            table.setItem(r, 2, self._styled_cell(field, row, t))
            table.setRowHeight(r, 26)

        def _activate(clicked: int, _c: int) -> None:
            row_obj = rows[clicked]
            self.tableRowActivated.emit(group.id, row_obj.id)
            # Deferred for the same reason as the group table's: this runs inside the table's own
            # mouse handler, and opening the EQ replaces (and destroys) the widget under it.
            QTimer.singleShot(0, lambda: self.open_eq(group, row_obj))

        table.cellClicked.connect(_activate)
        self._copy_on_right_click(table)
        layout.addWidget(table)
        return block

    def _copy_on_right_click(self, table: QTableWidget) -> None:
        """Right-click a cell and its value is on the clipboard, with a tip saying which.

        No menu: "copy the value" was the only item a table cell could offer, and a one-item menu
        is a question with one answer (user, 2026-08-23). The tip is the receipt -- a copy with no
        feedback leaves you pressing again to be sure, which is how the number you wanted gets
        replaced by the one under it.
        """
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def _copy(pos) -> None:
            item = table.itemAt(pos)
            if item is None:
                return
            # The cell's own pasteable value when it has one, its text otherwise (an ID, a name).
            text = (item.data(Qt.ItemDataRole.UserRole) or item.text() or "").strip()
            if not text:
                return
            copy_menu.copy_text(text)
            said = i18n.t("copiedValue").format(value=text)
            tip = rounded_tooltip.RoundedTooltip.instance()
            tip.show_at(table.viewport().mapToGlobal(pos) + QPoint(14, 14), said)
            # Hidden on a timer, and only if it is still OUR tip: another one may have taken the
            # singleton over in the meantime, and hiding somebody else's would be a flicker
            # nobody could explain.
            QTimer.singleShot(1500, lambda: tip.hide_tip() if tip.text() == said else None)

        table.customContextMenuRequested.connect(_copy)

    def _styled_cell(self, field: str, row: GroupRow, t) -> QTableWidgetItem:
        """A value cell with prototype-style alignment + colour: numbers right-aligned, gain
        green/orange by sign, INV highlighted, the EQ count an accent link. Mirrors the web
        `.ptable` cell classes (`.gpos/.gneg/.tinv/.eqcell`)."""
        item = QTableWidgetItem(self._cell_text(field, row))
        # The pasteable form rides along with the cell, so the copy does not have to work out
        # afterwards what kind of number it is looking at.
        item.setData(Qt.ItemDataRole.UserRole, self._copy_value(field, row))
        if field in ("hp", "lp", "gain_db", "ta_ms", "phase_deg", "eq"):
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        elif field in ("polarity", "mute", "off", "eq_bypass"):
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        color = None
        if field in ("gain_db", "ta_ms", "phase_deg"):
            # Zero is not a setting, it is the absence of one, and it was reading as a boost:
            # a column of green `+0.0` next to the two channels that actually carry gain (user,
            # 2026-08-23: "colours — nought in grey"). Only a real value gets a colour, and gain
            # keeps its sign meaning: up is the app's green, down is its accent.
            v = row.raw.get(field)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if not v:
                    color = t.faint
                elif field == "gain_db":
                    color = t.ok if v > 0 else t.accent
        elif field == "polarity":
            color = t.inv if row.raw.get("polarity") == "INV" else t.muted
        elif field == "eq":
            color = t.accent if row.eq_count() > 0 else t.faint
        elif field == "off":
            color = t.off if row.raw.get("off") else None
        elif field in ("hp", "lp") and self._cell_text(field, row) == "OFF":
            color = t.faint
        if color:
            item.setForeground(QColor(color))
        return item

    @staticmethod
    def _copy_value(field: str, row: GroupRow) -> str:
        """What a right-click puts on the clipboard: what you would TYPE, not what you read.

        A crossover cell reads `350 LR6` and only the 350 can be pasted -- the type is a dropdown
        in the DSP's software, not a number field (user, 2026-08-23). The same rule settles the
        rest: no leading `+` on a gain, no degree sign on a phase, no unit anywhere. The screen
        keeps the reading; the clipboard carries the value.
        """
        raw = row.raw
        if field in ("hp", "lp"):
            leg = CrossoverLeg.from_raw(raw.get(field))
            return f"{leg.freq_hz:g}" if leg.enabled and leg.freq_hz is not None else ""
        if field in ("gain_db", "ta_ms", "phase_deg"):
            v = raw.get(field)
            return f"{v:g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else ""
        return ""

    @staticmethod
    def _cell_text(field: str, row: GroupRow) -> str:
        raw = row.raw
        if field in ("hp", "lp"):
            return CrossoverLeg.from_raw(raw.get(field)).label
        if field == "gain_db":
            v = raw.get("gain_db")
            return f"{v:+.1f}" if isinstance(v, (int, float)) else "—"
        if field == "ta_ms":
            v = raw.get("ta_ms")
            return f"{v:g}" if isinstance(v, (int, float)) else "—"
        if field == "phase_deg":
            v = raw.get("phase_deg")
            return f"{v:g}°" if isinstance(v, (int, float)) else "—"
        if field == "polarity":
            return raw.get("polarity") or "—"
        if field == "mute":
            return "MUTE" if raw.get("mute") else "—"
        if field == "off":
            return "OFF" if raw.get("off") else "—"
        if field == "eq_bypass":
            return "Y" if raw.get("eq_bypass") else "—"
        if field == "eq":
            n = row.eq_count()
            return f"{n} band{'s' if n != 1 else ''} ▸" if n else "—"
        return "—"

    # ---- EQ view ----------------------------------------------------------

    def _render_eq(self, group: ProfileGroup, row: GroupRow, sib_row: Optional[GroupRow]) -> None:
        self._eq_help_tip.set_text(i18n.t("eqHint"))

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        if self._pair_mode and sib_row:
            l_row, r_row = (row, sib_row) if _is_left(row.name) else (sib_row, row)
            l_bands, r_bands = l_row.eq_bands(), r_row.eq_bands()
            shared = sorted({b.freq_hz for b in l_bands} & {b.freq_hz for b in r_bands})
            match_map = {f: _MATCH_PALETTE[i % len(_MATCH_PALETTE)] for i, f in enumerate(shared)}
            l_gain_by_freq = {b.freq_hz: b.gain_db for b in l_bands}
            r_gain_by_freq = {b.freq_hz: b.gain_db for b in r_bands}
            gain_mismatch = {f for f in shared if l_gain_by_freq.get(f) != r_gain_by_freq.get(f)}

            if shared:
                legend = QWidget()
                legend_layout = QHBoxLayout(legend)
                legend_layout.setContentsMargins(0, 0, 0, 0)
                legend_layout.addWidget(QLabel(i18n.t("shared")))
                for f in shared:
                    chip = QLabel(f"⬤ {f:g} Hz")
                    chip.setStyleSheet(f"color: {match_map[f]};")
                    legend_layout.addWidget(chip)
                legend_layout.addStretch(1)
                layout.addWidget(legend)
            else:
                # The key existed and the string was hardcoded past it: an English line among
                # Ukrainian ones, in the view that compares two channels.
                layout.addWidget(QLabel(i18n.t("noShared")))

            for label, r in (("L", l_row), ("R", r_row)):
                # The heading carries its own copy: with two channels on screen, one button in
                # the header says "copy EQ" and means only one of them (user, 2026-08-23). Beside
                # the name there is no ambiguity about whose bank it is.
                heading = QWidget()
                heading_row = QHBoxLayout(heading)
                heading_row.setContentsMargins(0, 0, 0, 0)
                heading_row.setSpacing(8)
                row_label = QLabel(f"{label} · {r.name} ({len(r.eq_bands())})")
                row_label.setProperty("class", "eq-rowlab")
                heading_row.addWidget(row_label)
                if eq_export.available() and r.raw.get("eq"):
                    copy_btn = _DTab(i18n.t("copyEqBank"))
                    copy_btn.clicked.connect(
                        lambda _checked=False, target=r: self._copy_bank_of(group, target)
                    )
                    heading_row.addWidget(copy_btn)
                heading_row.addStretch(1)
                layout.addWidget(heading)
                layout.addWidget(_band_flow(r.eq_bands(), match_map, gain_mismatch))
        else:
            layout.addWidget(_band_flow(row.eq_bands()))

        layout.addStretch(1)
        self._scroll.setWidget(container)
        # `id` and `name` are the same string until a channel is renamed (SCR-039), and repeating
        # it reads as a bug in the header rather than as two facts.
        self._title.setText(f"EQ · {row.name}" if row.id == row.name
                            else f"EQ · {row.name} ({row.id})")
