"""The left DSP tree — ported from the web prototype's `renderTree`/`groupNode`/`chanRow`
(`data/private/prototype/tcc-main.html`), but driven by the generic, profile-declared
`ProjectView`/`ProfileGroup`/`GroupRow` model (`state/dsp_state.py`) instead of the prototype's
hardcoded Helix-shaped `PRESETS.virtual`/`PRESETS.output`.

One collapsible `TreeGroupSection` per profile group (in profile-declared order — no assumption
that a "virtual" or "output" group exists, so a MUSWAY profile with only `physical_outputs` +
`inputs` renders correctly with zero changes here). Each section holds a clickable "params" row
(opens the full table, M3) followed by one `ChannelRow` per row in that group.

Deliberately NOT ported: the prototype's per-name abbreviation table (`ABBR`) and Helix-specific
`tag` (RearATT/SubRC) — both were conventions tied to *known Helix channel names*, not part of
the generic profile schema. Rows show their real name as-is; abbreviation can return later as an
optional profile-declared field if it proves worth the complexity.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.state.dsp_state import GroupRow, ProfileGroup, ProjectView

_SETTINGS_ORG = "autosound-tcc"
_SETTINGS_APP = "TCC"


def _collapsed_key(group_id: str) -> str:
    return f"ui/tree_collapsed/{group_id}"


def _default_collapsed(group_id: str) -> bool:
    """`physical_outputs` is the one group id every profile is guaranteed to have (the ledger's
    required `channels` key, per state/dsp_state.py's convention) — open it by default, collapse
    everything else. Mirrors the prototype's params:true/virtual:true/output:false defaults
    without hardcoding a Helix-specific group name."""
    return group_id != "physical_outputs"


class _Pill(QLabel):
    def __init__(self, text: str, kind: str) -> None:
        super().__init__(text)
        self.setProperty("class", f"pill pill-{kind}")


class _EqChip(QLabel):
    clicked = Signal()

    def __init__(self, count: int) -> None:
        super().__init__(f"EQ {count}" if count else "EQ —")
        self.setProperty("class", "eq-chip" if count else "eq-chip muted")
        self.setCursor(Qt.CursorShape.PointingHandCursor if count else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self.property("class") == "eq-chip":
            event.accept()
            self.clicked.emit()
        else:
            super().mousePressEvent(event)


class ChannelRow(QWidget):
    """Two-line row: ID badge + name + polarity/mute pill + EQ chip, then (for rows with a
    crossover) a compact HP/LP/gain summary line — mirrors `.cline1`/`.cline2`."""

    clicked = Signal()
    eqRequested = Signal()

    def __init__(self, group: ProfileGroup, row: GroupRow) -> None:
        super().__init__()
        self.setProperty("class", "chan")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 4, 8, 5)
        layout.setSpacing(1)

        line1 = QHBoxLayout()
        line1.setSpacing(6)
        cid = QLabel(row.id)
        cid.setProperty("class", "cid")
        line1.addWidget(cid)
        name = QLabel(row.name)
        name.setProperty("class", "cn")
        line1.addWidget(name)

        raw = row.raw
        muted_or_off = bool(raw.get("mute")) or bool(raw.get("off"))
        if muted_or_off:
            line1.addWidget(_Pill("MUTE" if raw.get("mute") else "OFF", "off"))
        elif raw.get("polarity"):
            pol = raw["polarity"]
            line1.addWidget(_Pill(pol, "inv" if pol == "INV" else "norm"))
        if muted_or_off:
            self.setProperty("class", "chan chan-dim")

        line1.addStretch(1)
        eq_count = row.eq_count()
        self._eq_chip = _EqChip(eq_count)
        self._eq_chip.clicked.connect(self.eqRequested.emit)
        line1.addWidget(self._eq_chip)
        layout.addLayout(line1)

        if "hp" in group.fields or "lp" in group.fields:
            from autosound_tcc.state.dsp_state import CrossoverLeg

            hp = CrossoverLeg.from_raw(raw.get("hp")).label
            lp = CrossoverLeg.from_raw(raw.get("lp")).label
            gain = raw.get("gain_db")
            gain_s = f"{gain:+.1f}dB" if isinstance(gain, (int, float)) else "—"
            line2 = QLabel(f"HP {hp} · LP {lp} · {gain_s}")
            line2.setProperty("class", "cline2")
            layout.addWidget(line2)

        tip_lines = [f"{row.id} · {row.name}"]
        params = row.params(group.fields)
        if params:
            tip_lines.append(" · ".join(params))
        self.setToolTip("\n".join(tip_lines))

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().mousePressEvent(event)
        self.clicked.emit()


class _ParamsOpenRow(QWidget):
    """The "⊞ params" link row that opens the full table for this group (M3)."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("class", "prow-params")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 4, 8, 4)
        layout.setSpacing(6)
        icon = QLabel("⊞")
        icon.setProperty("class", "prow-params-ic")
        layout.addWidget(icon)
        label = QLabel("params · all parameters as a table")
        layout.addWidget(label)
        layout.addStretch(1)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.accept()
        self.clicked.emit()


class TreeGroupSection(QWidget):
    """One collapsible group section (PARAMS / VIRTUAL / OUTPUT / ... — whatever the profile
    declares). Collapse state persists per group id via QSettings."""

    channelClicked = Signal(str, str)  # group_id, row_id
    eqRequested = Signal(str, str)
    tableRequested = Signal(str)

    def __init__(self, group: ProfileGroup, settings: QSettings) -> None:
        super().__init__()
        self._group = group
        self._settings = settings
        collapsed = settings.value(
            _collapsed_key(group.id), _default_collapsed(group.id), type=bool
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = QWidget()
        self._header.setProperty("class", "ghead")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        head_layout = QHBoxLayout(self._header)
        head_layout.setContentsMargins(8, 4, 8, 4)
        head_layout.setSpacing(6)
        self._twist = QLabel()
        self._twist.setProperty("class", "tw")
        head_layout.addWidget(self._twist)
        title = QLabel(group.label.upper())
        head_layout.addWidget(title)
        count = QLabel(f"{len(group.rows)}")
        count.setProperty("class", "cnt")
        head_layout.addWidget(count)
        head_layout.addStretch(1)
        self._header.mousePressEvent = self._on_header_clicked  # type: ignore[assignment]
        outer.addWidget(self._header)

        self._children = QWidget()
        children_layout = QVBoxLayout(self._children)
        children_layout.setContentsMargins(0, 0, 0, 0)
        children_layout.setSpacing(0)

        params_row = _ParamsOpenRow()
        params_row.clicked.connect(lambda: self.tableRequested.emit(group.id))
        children_layout.addWidget(params_row)

        for row in group.rows_ordered():
            chan = ChannelRow(group, row)
            chan.clicked.connect(lambda r=row: self.channelClicked.emit(group.id, r.id))
            chan.eqRequested.connect(lambda r=row: self.eqRequested.emit(group.id, r.id))
            children_layout.addWidget(chan)

        outer.addWidget(self._children)
        self._set_collapsed(collapsed)

    def _on_header_clicked(self, event) -> None:
        self._set_collapsed(not self._children.isHidden())
        self._settings.setValue(_collapsed_key(self._group.id), self._children.isHidden())

    def _set_collapsed(self, collapsed: bool) -> None:
        self._children.setHidden(collapsed)
        self._twist.setText("▸" if collapsed else "▾")


class DspTreeWidget(QScrollArea):
    """The whole left-panel tree: one `TreeGroupSection` per profile-declared group, in profile
    order. Rebuild via `set_view()` whenever the project/preset changes."""

    channelClicked = Signal(str, str)
    eqRequested = Signal(str, str)
    tableRequested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._body = QWidget()
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(0, 6, 0, 12)
        self._layout.setSpacing(2)
        self._layout.addStretch(1)
        self.setWidget(self._body)

    def set_view(self, view: ProjectView) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for group in view.groups:
            section = TreeGroupSection(group, self._settings)
            section.channelClicked.connect(self.channelClicked.emit)
            section.eqRequested.connect(self.eqRequested.emit)
            section.tableRequested.connect(self.tableRequested.emit)
            self._layout.insertWidget(self._layout.count() - 1, section)
