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

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.state.dsp_state import CrossoverLeg, EqBand, GroupRow, ProfileGroup

# field token -> (column header, cell-renderer). Order here is the fallback display order when a
# group declares a field not already covered by a fixed prototype-matching order below.
_FIELD_COLUMNS: dict[str, str] = {
    "hp": "HPF", "lp": "LPF", "gain_db": "Gain dB", "ta_ms": "Delay ms",
    "polarity": "Pol", "phase_deg": "Phase", "mute": "Mute", "eq_bypass": "EQ Byp", "eq": "EQ",
}

_MATCH_PALETTE = ["#5aa9e6", "#4bbf87", "#e8973c", "#c98fe0", "#e8c34a", "#e05c5c"]


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

    def __init__(self, band: EqBand, match_color: Optional[str] = None) -> None:
        super().__init__()
        self.setProperty("class", "band")
        self.setFixedWidth(112)
        if match_color:
            self.setStyleSheet(f"border-top: 3px solid {match_color};")
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
            fv.setProperty("class", "band-fv")
            row_layout.addWidget(fk)
            row_layout.addStretch(1)
            row_layout.addWidget(fv)
            layout.addWidget(row)

        byp = QLabel("○ ByPass")
        byp.setProperty("class", "band-byp")
        byp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(byp)


def _band_flow(bands: tuple[EqBand, ...], match_map: Optional[dict[float, str]] = None) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for band in bands:
        color = (match_map or {}).get(band.freq_hz)
        layout.addWidget(EqBandCard(band, color))
    layout.addStretch(1)
    return container


class DetailPane(QFrame):
    """The whole `.detail` panel: tabs, title, close, and a body that shows either a table or an
    EQ view. Hidden by default (`.detail` starts at max-height 0 in the prototype)."""

    closed = Signal()
    tableRowActivated = Signal(str, str)  # group_id, row_id -> caller opens EQ for it
    eqRequested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("class", "panel")
        self.setVisible(False)
        self._mode: Optional[str] = None  # "table" | "eq"
        self._group: Optional[ProfileGroup] = None
        self._row: Optional[GroupRow] = None
        self._pair_mode = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QWidget()
        head.setProperty("class", "phead")
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(12, 6, 12, 6)
        head_layout.setSpacing(6)

        self._tab_table = _DTab("Table")
        self._tab_table.clicked.connect(self._on_tab_table)
        head_layout.addWidget(self._tab_table)
        self._tab_eq = _DTab("EQ")
        self._tab_eq.clicked.connect(self._on_tab_eq)
        head_layout.addWidget(self._tab_eq)
        self._pair_btn = _DTab("⇄ L + R")
        self._pair_btn.clicked.connect(self._on_pair_toggle)
        self._pair_btn.setVisible(False)
        head_layout.addWidget(self._pair_btn)
        self._title = QLabel("")
        self._title.setProperty("class", "phead-sub")
        head_layout.addWidget(self._title)
        head_layout.addStretch(1)

        close_btn = QPushButton("close ✕")
        close_btn.setProperty("class", "d-close")
        close_btn.clicked.connect(self.close_pane)
        head_layout.addWidget(close_btn)
        outer.addWidget(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(self._scroll, stretch=1)
        # A fixed cap rather than the prototype's dynamic "50% of the center column" — simpler,
        # and the internal QScrollArea already handles anything taller. Revisit if it feels wrong
        # once this sits next to the real AI dialog (M5).
        self.setMaximumHeight(420)

    # ---- public API ----------------------------------------------------

    def close_pane(self) -> None:
        self.setVisible(False)
        self.closed.emit()

    def open_table(self, group: ProfileGroup, select_row_id: Optional[str] = None) -> None:
        self._group, self._row, self._mode = group, None, "table"
        self._pair_btn.setVisible(False)
        self._title.setText(f"{group.label} · {len(group.rows)}")
        table = self._build_table(group)
        self._scroll.setWidget(table)
        if select_row_id is not None:
            for r, row in enumerate(group.rows_ordered()):
                if row.id == select_row_id:
                    table.selectRow(r)
                    break
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

    # ---- tabs -----------------------------------------------------------

    def _sync_tabs(self) -> None:
        self._tab_table.set_on(self._mode == "table")
        self._tab_eq.set_on(self._mode == "eq")
        self._pair_btn.set_on(self._pair_mode)

    def _on_tab_table(self) -> None:
        if self._group is not None:
            self.open_table(self._group)

    def _on_tab_eq(self) -> None:
        if self._row is not None:
            self.open_eq(self._group, self._row)
        elif self._group is not None and self._group.rows:
            self.open_eq(self._group, self._group.rows_ordered()[0])

    def _on_pair_toggle(self) -> None:
        self._pair_mode = not self._pair_mode
        if self._row is not None:
            self.open_eq(self._group, self._row)

    # ---- table view -------------------------------------------------------

    def _build_table(self, group: ProfileGroup) -> QTableWidget:
        columns = [f for f in group.fields if f in _FIELD_COLUMNS]
        headers = ["ID", "Channel"] + [_FIELD_COLUMNS[f] for f in columns]
        table = QTableWidget(len(group.rows), len(headers))
        table.setProperty("class", "ptable")
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(False)

        for r, row in enumerate(group.rows_ordered()):
            table.setItem(r, 0, QTableWidgetItem(row.id))
            table.setItem(r, 1, QTableWidgetItem(row.name))
            for c, field in enumerate(columns, start=2):
                table.setItem(r, c, QTableWidgetItem(self._cell_text(field, row)))
            table.setRowHeight(r, 26)

        def _activate(r: int, _c: int) -> None:
            row_obj = group.rows_ordered()[r]
            self.tableRowActivated.emit(group.id, row_obj.id)
            self.open_eq(group, row_obj)

        table.cellClicked.connect(_activate)
        table.resizeColumnsToContents()
        return table

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
        if field == "eq_bypass":
            return "Y" if raw.get("eq_bypass") else "—"
        if field == "eq":
            n = row.eq_count()
            return f"{n} band{'s' if n != 1 else ''}" if n else "—"
        return "—"

    # ---- EQ view ----------------------------------------------------------

    def _render_eq(self, group: ProfileGroup, row: GroupRow, sib_row: Optional[GroupRow]) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "Only active bands shown. Bypass is read-only for now."
        )
        hint.setProperty("class", "eq-hint")
        layout.addWidget(hint)

        if self._pair_mode and sib_row:
            l_row, r_row = (row, sib_row) if _is_left(row.name) else (sib_row, row)
            l_bands, r_bands = l_row.eq_bands(), r_row.eq_bands()
            shared = sorted({b.freq_hz for b in l_bands} & {b.freq_hz for b in r_bands})
            match_map = {f: _MATCH_PALETTE[i % len(_MATCH_PALETTE)] for i, f in enumerate(shared)}

            if shared:
                legend = QWidget()
                legend_layout = QHBoxLayout(legend)
                legend_layout.setContentsMargins(0, 0, 0, 0)
                legend_layout.addWidget(QLabel("shared frequencies:"))
                for f in shared:
                    chip = QLabel(f"⬤ {f:g} Hz")
                    chip.setStyleSheet(f"color: {match_map[f]};")
                    legend_layout.addWidget(chip)
                legend_layout.addStretch(1)
                layout.addWidget(legend)
            else:
                layout.addWidget(QLabel("no shared frequencies"))

            for label, r in (("L", l_row), ("R", r_row)):
                row_label = QLabel(f"{label} · {r.name} ({len(r.eq_bands())})")
                row_label.setProperty("class", "eq-rowlab")
                layout.addWidget(row_label)
                layout.addWidget(_band_flow(r.eq_bands(), match_map))
        else:
            layout.addWidget(_band_flow(row.eq_bands()))

        layout.addStretch(1)
        self._scroll.setWidget(container)
        self._title.setText(f"EQ · {row.id} · {row.name}")
