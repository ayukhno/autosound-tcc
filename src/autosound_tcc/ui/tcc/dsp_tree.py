"""The left DSP tree — ported from the web prototype's `renderTree`/`groupNode`/`chanRow`
(`data/private/prototype/tcc-main.html`), but driven by the generic, profile-declared
`ProjectView`/`ProfileGroup`/`GroupRow` model (`state/dsp_state.py`) instead of the prototype's
hardcoded Helix-shaped `PRESETS.virtual`/`PRESETS.output`.

One collapsible `TreeGroupSection` per profile group (in profile-declared order — no assumption
that a "virtual" or "output" group exists, so a MUSWAY profile with only `physical_outputs` +
`inputs` renders correctly with zero changes here). Each section holds a clickable "params" row
(opens the full table, M3) followed by one `ChannelRow` per row in that group.

Channel identity comes from the ledger, kept generic: `slot` (the hardware slot letter shown as
the ID badge), `descr` (full descriptive name, tooltip only), and an optional `tag`+`tag_value`
(RearRC/SubRC/RC — Helix-specific feature names, not MUSWAY) rendered as a chip on virtual-tier
rows only — all plain profile-agnostic fields, absent = simply not shown, so a MUSWAY ledger
without them still renders.
"""

from __future__ import annotations

import re
from html import escape
from typing import Optional

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QFont, QFontMetricsF
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import eq_export
from autosound_tcc.state.dsp_state import CrossoverLeg, GroupRow, ProfileGroup, ProjectView
from autosound_tcc.ui.tcc import copy_menu, discard, i18n, rounded_tooltip
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc.labels import ElidedLabel
from autosound_tcc.ui.tcc.rounded_tooltip import RoundedTooltip
from autosound_tcc.ui.tcc.detail_pane import (
    band_changes,
    band_count,
    cell_text,
    changed_fields,
    column_title,
    mark_colour,
    table_fields,
)
from autosound_tcc.ui.tcc.setting_status import StatusDot
from autosound_tcc.ui.tcc.theme import apply_caps, current_theme

# Short, translatable header labels for the known DSP tiers (matches the prototype's T.virtual /
# T.output / T.params). Unknown group ids fall back to the profile's own label, so a novel profile
# still renders — just with its verbose label instead of a short one.
_GROUP_LABEL_KEY = {
    "virtual_channels": "virtual",
    "physical_outputs": "output",
    "inputs": "inputs",
}


_LABEL_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")


def group_label(group: ProfileGroup) -> str:
    """A tier's name for a section header — its own name, and nothing else.

    A profile is free to describe its tier in full (`Virtual channels (Front L/R, Center, Rear,
    Sub, Link L+R)`), and that reads fine in the file it was written in. In a header, next to a
    count, it is a paragraph where a title should be — and the list it spells out is exactly the
    rows underneath (user, 2026-08-07). The known tiers use TCC's own translated names; anything
    else keeps the profile's wording with the trailing aside dropped.
    """
    key = _GROUP_LABEL_KEY.get(group.id)
    if key:
        return i18n.t(key)
    return _LABEL_PARENTHETICAL.sub("", str(group.label or "")).strip() or str(group.label or "")


_group_label = group_label  # the name this module's own call sites already use


def _collapsed_key(group_id: str) -> str:
    return f"ui/tree_collapsed/{group_id}"


def _default_collapsed(group_id: str) -> bool:
    """`physical_outputs` is the one group id every profile is guaranteed to have (the ledger's
    required `channels` key, per state/dsp_state.py's convention) — open it by default, collapse
    everything else. Mirrors the prototype's params:true/virtual:true/output:false defaults
    without hardcoding a Helix-specific group name."""
    return group_id != "physical_outputs"


class _SubLine(ElidedLabel):
    """A channel row's second line -- one line, elided, never wrapped.

    A row is one channel; making it two lines tall as soon as the panel narrows turns a list you
    read at a glance into a list you scroll. Elided says the same thing in the room there is, and
    the row's rounded hover tip already holds the fuller facts -- which is why this asks for no
    native tooltip of its own.

    It also stops the label lying about its height, which mattered once and could again: a
    word-wrapped QLabel measures its HINT at a width Qt guesses, so this line asked for two lines
    (28px) where it draws one (14px). That is normally harmless -- Qt asks `heightForWidth` along
    the layout chain instead -- but any widget in the chain WITHOUT a layout of its own answers
    with the hint, and this tree used to be exactly that (a QScrollArea, F-002/F-021). Fourteen
    rows of it made 196px of scroll running past the end of the content (user, 2026-08-22, with
    the screenshot; measured offscreen: 814px of content inside a 1010px claim).

    A value that differs from «порівняти з» is drawn in the window's colour for a change, and
    bold, as the table's changed cells are (tcc#104, finding 113; tcc#108, finding 116). So the
    line is rich text, cut on its words: the colour and the weight kept on what is left of each.
    """

    def __init__(self) -> None:
        super().__init__("", native_tooltip=False)
        self.setProperty("class", "cline2")
        self.setTextFormat(Qt.TextFormat.RichText)
        self._parts: list = []

    def set_parts(self, parts: list) -> None:
        """`[(text, changed)]`, said one after another with « · » between."""
        self._parts = list(parts)
        self.setText(" · ".join(text for text, _ in self._parts))

    def parts(self) -> list:
        return list(self._parts)

    def _elide(self) -> None:
        """Cut where the line runs out of room, each run measured in the weight it is drawn in.

        Measuring the line as plain text, as `ElidedLabel` does, is wrong here twice: bold is wider
        than plain in most faces (Menlo is an exception; in the offscreen default face m-R's line
        ran 5.4 px past its edge), and whole-pixel metrics round (0.5 px past). Fractional metrics
        are what the rich text is laid out with, and neighbours of one weight are measured
        together, as they are drawn.
        """
        plain = QFontMetricsF(self.font())
        heavy = QFont(self.font())
        heavy.setBold(True)
        bold = QFontMetricsF(heavy)
        runs: list = []  # [text, lit]
        for i, (text, changed) in enumerate(self._parts):
            for piece, lit in ((" · " if i else "", False), (text, changed)):
                if runs and runs[-1][1] == lit:
                    runs[-1][0] += piece
                elif piece:
                    runs.append([piece, lit])
        room = max(self.width(), self._min_width)
        cut = sum((bold if lit else plain).horizontalAdvance(text) for text, lit in runs) > room
        if cut:
            room -= plain.horizontalAdvance("…")
        colour = mark_colour("chg")
        out = []
        for text, lit in runs:
            metrics = bold if lit else plain
            wide = metrics.horizontalAdvance(text)
            n = len(text)
            while n and metrics.horizontalAdvance(text[:n]) > room:
                n -= 1
            if n:
                piece = escape(text[:n])
                out.append(f'<span style="color:{colour};font-weight:700">{piece}</span>'
                           if lit else piece)
            if n < len(text):
                break
            room -= wide
        said = "".join(out) + ("…" if cut else "")
        if said != QLabel.text(self):
            QLabel.setText(self, said)


class _Pill(QLabel):
    def __init__(self, text: str, kind: str) -> None:
        super().__init__(text)
        self.setProperty("class", f"pill pill-{kind}")
        apply_caps(self, spacing_px=0.6)


class _EqChip(QLabel):
    """Always clickable, even at zero bands -- the tree chip is the one-click path to a channel's
    EQ view (vs. the crash-prone route of opening the table and clicking the row); an empty-band
    channel still has an EQ view worth seeing (e.g. to confirm it's genuinely empty)."""

    clicked = Signal()

    def __init__(self, said: str) -> None:
        """`said` is «12/15» — active of configured, the empty slots not counted — or empty."""
        super().__init__(f"EQ {said}" if said else "EQ —")
        self.setProperty("class", "eq-chip" if said else "eq-chip muted")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.accept()
        self.clicked.emit()


def _eq_bank_text(row, group_id: str) -> str:
    """This channel's bank as text, or "" when there is no format to write it in.

    Empty is a real answer here rather than a failure: `copy_menu` drops an item that resolves to
    nothing, which is exactly the behaviour wanted when the method has no exporter for this DSP.

    The tier travels with the row because whether a crossover belongs in the block is read from
    the profile for THAT tier -- a virtual channel has none, and the method is what knows it.
    """
    bank = eq_export.format_bank(
        row.raw.get("eq"),
        crossovers={"hp": row.raw.get("hp"), "lp": row.raw.get("lp")},
        group_id=group_id,
        channel=row.name,
    )
    return bank.text if bank else ""


#: How the second line names a value it shows only when it changed; the rest go by the table's
#: column heads («Pol NORM», «EQ Byp Y»).
_VALUE_WORD = {"ta_ms": ("Delay", "ms"), "phase_deg": ("Phase", "")}


def _value_said(field: str, row: GroupRow) -> str:
    value = cell_text(field, row)
    word, unit = _VALUE_WORD.get(field, (column_title(field), ""))
    return f"{word} {value}{unit if value != '—' else ''}"


def _restyle(widget: QWidget, classes: str) -> None:
    if widget.property("class") != classes:
        widget.setProperty("class", classes)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def _light(widget: QWidget, on: bool) -> None:
    """Add or drop `act` in a row's class — the row the window is showing (the Arbiter, on the
    prototype, 2026-09-25: «поточна група активна!»)."""
    words = [w for w in str(widget.property("class") or "").split() if w != "act"]
    widget.setProperty("class", " ".join(words + (["act"] if on else [])))
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ChannelRow(QWidget):
    """Two-line row: ID badge + name + polarity/mute pill + EQ chip, then (for rows with a
    crossover) a compact HP/LP/gain summary line — mirrors `.cline1`/`.cline2`. Against
    «порівняти з», what differs is drawn changed (`set_compared`)."""

    clicked = Signal()
    eqRequested = Signal()
    # (channel name, wanted state). A request, not a change: the ledger is the skill's to write.
    toggleRequested = Signal(str, bool)

    def __init__(self, group: ProfileGroup, row: GroupRow) -> None:
        super().__init__()
        self.setProperty("class", "chan")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._group = group
        self._row = row
        self._changes: Optional[dict] = None
        #: The table's columns that differ from «порівняти з» for this channel (tcc#104).
        self._changed: frozenset = frozenset()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 4, 8, 5)
        layout.setSpacing(1)

        is_output = "hp" in group.known_fields or "lp" in group.known_fields
        self._is_output = is_output
        line1 = QHBoxLayout()
        line1.setSpacing(6)
        if row.slot:
            # The hardware slot letter (e.g. "A".."K") is the channel's ID badge. Falls back to
            # nothing when a ledger has no slot field (older captures) -- the name still shows.
            cid = QLabel(row.slot)
            cid.setProperty("class", "cid")
            line1.addWidget(cid)
        name = QLabel(row.name)
        name.setProperty("class", "cn")
        line1.addWidget(name)

        raw = row.raw
        # Speaker type (woofer/mid/tweeter/...) shown next to the name on output rows so the
        # physical driver behind a channel is identifiable at a glance (user request 2026-07-26).
        if is_output and raw.get("role"):
            ctype = QLabel(raw["role"])
            ctype.setProperty("class", "ctype")
            line1.addWidget(ctype)
        if row.muted:
            self.setProperty("class", "chan chan-dim")
        # MUTE or the polarity -- which one, and whether it is a change, `_sync_marks` says.
        self._pill = _Pill("", "mute")
        line1.addWidget(self._pill)

        # Feature tag (RearRC/SubRC/RC) is a virtual-tier convention -- the prototype shows it only
        # on virtual channels, not on the physical outputs that carry the same tag. Include the
        # tag's configured value (e.g. "RearRC 3/4", "SubRC -4dB", "RC ON") when the ledger has one,
        # so the chip reads as a fact rather than just a feature name (user request 2026-07-28).
        if row.tag and not is_output:
            tag_text = f"{row.tag} {row.tag_value}" if row.tag_value else row.tag
            tag = QLabel(tag_text)
            tag.setProperty("class", "ctag2")
            line1.addWidget(tag)

        line1.addStretch(1)
        # Against «порівняти з»: the EQ legend's dots with their counts, no names, left of the
        # chip (the Arbiter, 2026-09-26, finding 74). Nothing moved, or nothing compared — none.
        self._cmp = QLabel()
        self._cmp.setProperty("class", "eq-cmp")
        self._cmp.setTextFormat(Qt.TextFormat.RichText)
        self._cmp.setVisible(False)
        line1.addWidget(self._cmp)
        self._eq_chip = _EqChip(band_count(row.eq_bands()).strip("()"))
        self._eq_chip.clicked.connect(self.eqRequested.emit)
        line1.addWidget(self._eq_chip)
        layout.addLayout(line1)

        self._line2 = _SubLine()
        layout.addWidget(self._line2)
        self._sync_marks()

        # rounded_tooltip.attach(), not setToolTip() -- native QToolTip's window frame stays
        # square on macOS regardless of its own QSS border-radius (user request 2026-07-28).
        # Kept rather than discarded: these are not Qt tooltips, so `toolTip()` is empty here and
        # "copy hint" has to read the tip itself. The hint is where the driver and Fs live -- the
        # facts the row has no room to show.
        self._tip = rounded_tooltip.attach(self, self._tooltip_html(row, raw, is_output))
        summary = " · ".join(row.params(group.known_fields))
        copy_menu.enable_copy(
            self,
            value=row.name,
            row=lambda: f"{row.name}: {summary}" if summary else row.name,
            hint=lambda: copy_menu.plain(self._tip.text()),
        )

    def set_compared(self, old_row: Optional[GroupRow], compared: bool) -> None:
        """This channel against the same one in the compared version; `compared` False clears.

        The bands as dots with counts beside the chip (finding 74), and every other value the
        table marks drawn changed where the row says it: the tree read the bands alone, so sw's
        HPF and m-R's delay and polarity were marked in the table and nowhere here (tcc#104,
        finding 113). Both by the table's own rule (`changed_fields`)."""
        self._changes = band_changes(self._row, old_row) if compared else None
        self._changed = (changed_fields(self._group, self._row, old_row) if compared
                         else frozenset())
        parts = [f'<span style="color:{mark_colour(status)}">●&nbsp;({n})</span>'
                 for status, n in (self._changes or {}).items() if n]
        if not parts and "eq" in self._changed:
            # The table marks the EQ cell and no band counts as moved (an empty slot's values, a
            # channel new with no bands): a bare dot, so the tree still says what the table says.
            parts = [f'<span style="color:{mark_colour("chg")}">●</span>']
        self._cmp.setText("&nbsp;&nbsp;".join(parts))
        self._cmp.setVisible(bool(parts))
        self._sync_marks()

    def band_changes(self) -> Optional[dict]:
        return dict(self._changes) if self._changes is not None else None

    def changed_fields(self) -> frozenset:
        return self._changed

    def _sync_marks(self) -> None:
        """The pill and the second line, with what differs from «порівняти з» drawn changed."""
        row, raw, changed = self._row, self._row.raw, self._changed
        pill = None
        if row.muted:
            # MUTE-only in the working interface (user request 2026-07-27) -- OFF (hardware
            # physically disabled at the DSP level, GroupRow.off) is real data but stays out of
            # the main tree/table for now, deferred to a future settings view to avoid confusing
            # the two states side by side. See pill-off/`_FIELD_COLUMNS["off"]` (detail_pane.py) --
            # left in place, just not wired into any profile's `fields` list right now.
            pill = ("mute", i18n.t("pillMute"), "mute")
        elif raw.get("polarity") == "INV" or "polarity" in changed:
            # Only flag inversion -- NORM is the default and showing it on every row is noise
            # (user request 2026-07-27). A NORM the compared version did not have is not noise:
            # it is the change (finding 113).
            said = cell_text("polarity", row)
            pill = ("polarity", said, "inv" if said == "INV" else "norm")
        self._pill.setVisible(pill is not None)
        if pill is not None:
            field, said, kind = pill
            self._pill.setText(said)
            _restyle(self._pill, f"pill pill-{kind}" + (" chg" if field in changed else ""))

        if self._is_output:
            gain = raw.get("gain_db")
            parts = [("hp", f"HP {CrossoverLeg.from_raw(raw.get('hp')).label}"),
                     ("lp", f"LP {CrossoverLeg.from_raw(raw.get('lp')).label}"),
                     ("gain_db", f"{gain:+.1f}dB" if isinstance(gain, (int, float)) else "—")]
        else:
            # Virtual channels have no crossover, but their gain (and delay) matter in the main
            # list -- surface them the same way (user request 2026-07-27).
            gain = raw.get("gain_db")
            delay = raw.get("ta_ms")
            parts = [("gain_db", f"Gain {gain:+.1f}dB" if isinstance(gain, (int, float))
                      else "Gain —")]
            if isinstance(delay, (int, float)):
                parts.append(("ta_ms", f"Delay {delay:g}ms"))
        # Any other value that differs joins the line: an output's delay was not on it at all
        # (finding 113). The EQ has its dots, the pill its field.
        placed = {f for f, _ in parts} | {"eq"} | ({pill[0]} if pill else set())
        parts += [(f, _value_said(f, row)) for f in table_fields(self._group)
                  if f in changed and f not in placed]
        self._line2.set_parts([(text, f in changed) for f, text in parts])

    @staticmethod
    def _tooltip_html(row: GroupRow, raw: dict, is_output: bool) -> str:
        """A formatted, colour-coded hover hint (QToolTip renders rich text). Driver make + Fs,
        the crossover, and gain/polarity/EQ all use the same colours as the table so the hint
        reads at a glance."""
        t = current_theme()

        def c(text: str, color: str) -> str:
            return f"<span style='color:{color}'>{text}</span>"

        head = f"{row.slot} · {row.descr or row.name}" if row.slot else (row.descr or row.name)
        html = [f"<b>{head}</b>"]

        if is_output:
            # Driver / role / Fs are channel IDENTITY and reach this row from `project.json` by way
            # of the SCR-001 join (`GroupRow.driver`/`role`/`fs_hz`), not from the ledger row: the
            # skill never wrote `driver`/`fs` keys there, so reading `raw` left this block
            # permanently empty and raised nothing.
            meta = []
            if row.driver:  # speaker make/model, e.g. "Audiofrog GB25" -- shown when captured
                meta.append(f"<b>{row.driver}</b>")
            if row.role:
                meta.append(str(row.role))
            if row.fs_hz is not None:
                # Said when it was carried in from another project (hub #154 §4). A warning and no
                # more: the tuner sets in the DSP what they need, taking the advice or not (the
                # Arbiter, 2026-09-17).
                inherited = f"&nbsp;({i18n.t('factInherited')})" if row.fs_inherited else ""
                meta.append(f"Fs&nbsp;{row.fs_hz:g}&nbsp;Hz{inherited}")
            if meta:
                html.append(c(" · ".join(meta), t.muted))
            hp = CrossoverLeg.from_raw(raw.get("hp")).label
            lp = CrossoverLeg.from_raw(raw.get("lp")).label
            html.append(f"HP&nbsp;<b>{hp}</b> &nbsp;·&nbsp; LP&nbsp;<b>{lp}</b>")

        parts = []
        gain = raw.get("gain_db")
        if isinstance(gain, (int, float)):
            parts.append("Gain " + c(f"{gain:+.1f}&nbsp;dB", t.ok if gain >= 0 else t.accent))
        delay = raw.get("ta_ms")
        if isinstance(delay, (int, float)):
            parts.append(f"Delay {delay:g}&nbsp;ms")
        pol = raw.get("polarity")
        if pol:
            parts.append("Pol " + (c("INV", t.inv) if pol == "INV" else c(pol, t.muted)))
        phase = raw.get("phase_deg")
        if isinstance(phase, (int, float)):
            # Lost from the tooltip in an earlier pass even though the table always had it
            # (user report 2026-07-28).
            parts.append(f"Phase {phase:g}°")
        if parts:
            html.append(" &nbsp;·&nbsp; ".join(parts))

        n = row.eq_count()
        if n:
            html.append("EQ " + c(f"{n} band{'s' if n != 1 else ''}", t.accent))
        return "<div>" + "<br>".join(html) + "</div>"

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().mousePressEvent(event)
        # Left button only. It used to fire on any press, which was invisible until the row gained
        # a right-click copy menu: one right-click then opened the detail pane AND the menu.
        if event.button() == Qt.MouseButton.LeftButton:
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
        # Elided: "params · усі параметри таблицею" is wider than the tree's own viewport in UK,
        # and a row that insists on its width makes the whole tree scroll sideways -- taking every
        # channel's crossover line with it.
        label = ElidedLabel(i18n.t("paramsRow"), min_width=60)
        layout.addWidget(label, 1)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.accept()
        self.clicked.emit()


class _ParamRow(QWidget):
    """One `key → value` DSP-feature row (RealCenter ON, SubRC −4 dB, ...) inside PARAMS."""

    def __init__(self, key: str, value: str) -> None:
        super().__init__()
        self.setProperty("class", "paramrow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 3, 8, 3)
        layout.setSpacing(6)
        k = QLabel(key)
        k.setProperty("class", "pk")
        layout.addWidget(k)
        layout.addStretch(1)
        v = QLabel(value)
        v.setProperty("class", "pv")
        layout.addWidget(v)
        copy_menu.enable_copy(
            self,
            value=lambda: copy_menu.full_text(v),
            row=lambda: f"{copy_menu.full_text(k)}: {copy_menu.full_text(v)}",
        )


class ParamsSection(QWidget):
    """One flat key/value collapsible section (DSP feature toggles, car/setup params, car-body
    params, ...). Mirrors the prototype's `groupNode("params", ...)` built from `p.features` --
    generalized so more than one flat section can exist side by side (each with its own id/label/
    collapse-state, user request 2026-07-27 item 2). Collapsed by default."""

    def __init__(
        self, section_id: str, label: str, params: tuple[tuple[str, str], ...], settings: QSettings
    ) -> None:
        super().__init__()
        self._settings = settings
        self._gid = section_id
        collapsed = settings.value(_collapsed_key(self._gid), True, type=bool)

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
        params_label = QLabel(label)
        if section_id != "params":
            # Project-config sections (car/setup, body/chassis, ...) read visually lighter than
            # the DSP-features "params" section -- styled like the left panel's top "DSP" badge
            # instead (user request 2026-07-27).
            params_label.setProperty("class", "phead-badge")
        apply_caps(params_label, spacing_px=1.0)
        head_layout.addWidget(params_label)
        head_layout.addStretch(1)
        self._header.mousePressEvent = self._on_header_clicked  # type: ignore[assignment]
        outer.addWidget(self._header)

        self._children = QWidget()
        children_layout = QVBoxLayout(self._children)
        children_layout.setContentsMargins(0, 0, 0, 0)
        children_layout.setSpacing(0)
        for key, value in params:
            children_layout.addWidget(_ParamRow(key, value))
        outer.addWidget(self._children)
        self._set_collapsed(collapsed)

    def _on_header_clicked(self, event) -> None:
        self._set_collapsed(not self._children.isHidden())
        self._settings.setValue(_collapsed_key(self._gid), self._children.isHidden())

    def _set_collapsed(self, collapsed: bool) -> None:
        self._children.setHidden(collapsed)
        self._twist.setText("▸" if collapsed else "▾")


class TreeGroupSection(QWidget):
    """One collapsible group section (PARAMS / VIRTUAL / OUTPUT / ... — whatever the profile
    declares). Collapse state persists per group id via QSettings."""

    channelClicked = Signal(str, str)  # group_id, row_id
    eqRequested = Signal(str, str)
    tableRequested = Signal(str)
    toggleRequested = Signal(str, str, bool)  # group_id, channel name, wanted state

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
        title = QLabel(_group_label(group).upper())
        apply_caps(title, spacing_px=1.0)
        head_layout.addWidget(title)
        # The working tree shows what is being worked on: unused slots stay out of it (user,
        # 2026-08-06 -- "in the main place, only what we work with"). Every channel, in use or not,
        # with its ON/OFF, lives in System params instead, where looking at the whole rig is the
        # point rather than a distraction.
        visible_rows = group.rows_visible()
        count_text = (
            f"{len(visible_rows)}/{group.max_count}" if group.max_count else f"{len(visible_rows)}"
        )
        count = QLabel(count_text)
        count.setProperty("class", "cnt")
        head_layout.addWidget(count)
        # Whether the tier carries settings, and whether they moved since «порівняти з» (the
        # Arbiter, 2026-09-25, finding 65). The window says which; until it does, no dot.
        self.dot = StatusDot()
        head_layout.addWidget(self.dot)
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
        self._params_row = params_row
        self._rows: dict[str, ChannelRow] = {}

        for row in visible_rows:
            chan = ChannelRow(group, row)
            self._rows[row.id] = chan
            chan.clicked.connect(lambda r=row: self.channelClicked.emit(group.id, r.id))
            chan.eqRequested.connect(lambda r=row: self.eqRequested.emit(group.id, r.id))
            chan.toggleRequested.connect(
                lambda name, on, gid=group.id: self.toggleRequested.emit(gid, name, on)
            )
            children_layout.addWidget(chan)

        outer.addWidget(self._children)
        self._set_collapsed(collapsed)

    def _on_header_clicked(self, event) -> None:
        self._set_collapsed(not self._children.isHidden())
        self._settings.setValue(_collapsed_key(self._group.id), self._children.isHidden())

    def _set_collapsed(self, collapsed: bool) -> None:
        self._children.setHidden(collapsed)
        self._twist.setText("▸" if collapsed else "▾")

    def set_compared(self, old_group: Optional[ProfileGroup], compared: bool) -> None:
        """Each channel against its namesake in `old_group` (finding 74)."""
        olds = {r.id: r for r in old_group.rows} if old_group is not None else {}
        for row_id, chan in self._rows.items():
            chan.set_compared(olds.get(row_id), compared)

    def set_active(self, what: Optional[str]) -> None:
        """Light «params» (`"params"`), one channel (its row id), or nothing (`None`)."""
        _light(self._params_row, what == "params")
        for row_id, chan in self._rows.items():
            _light(chan, what == row_id)


class DspTreeWidget(QWidget):
    """The whole left-panel tree: one `TreeGroupSection` per profile-declared group, in profile
    order. Rebuild via `set_view()` whenever the project/preset changes."""

    channelClicked = Signal(str, str)
    eqRequested = Signal(str, str)
    tableRequested = Signal(str)
    toggleRequested = Signal(str, str, bool)  # (group id, channel name, wanted state)

    def __init__(self) -> None:
        super().__init__()
        # A plain widget holding its rows in its own layout -- deliberately not a QScrollArea.
        # The left panel is one scroll from top to bottom (`main_window._build_left`), and a
        # scrolling tree inside that scroll is a wheel that stops working halfway down (F-002,
        # user 2026-08-21). That was first answered by keeping the QScrollArea and taking its
        # scrolling away: scrollbars off, `sizeHint` overridden to the content height, and
        # `updateGeometry` called by hand after every rebuild. It fixed the wheel and left the
        # other half: a QScrollArea does not tell its parent layout when the widget inside it
        # changes size, so folding or unfolding a group -- which no rebuild goes through -- left
        # the column holding the height it had computed before. Measured offscreen: 66px given to
        # a tree asking for 886, rows sliced off mid-row with free space underneath and the
        # column's own scrollbar at range 0 (user, 2026-08-22, with the screenshot).
        # A widget whose own layout holds the rows announces its height change by itself, which
        # is what those hand-written calls were imitating one rebuild at a time.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._settings = get_settings()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 6, 0, 12)
        self._layout.setSpacing(2)
        self._layout.addStretch(1)
        self._sections: dict[str, TreeGroupSection] = {}
        self._active: tuple = (None, None)

    def set_active(self, group_id: Optional[str], what: Optional[str]) -> None:
        """What the window shows now: a tier's table (`"params"`), a channel, or nothing."""
        self._active = (group_id, what) if group_id else (None, None)
        for gid, section in self._sections.items():
            section.set_active(what if gid == group_id else None)

    def active(self) -> tuple:
        return self._active

    def set_status(self, statuses: dict, version: str = "") -> None:
        """`{group id: "none" | "set" | "chg"}` — the dot beside each tier's name."""
        for group_id, section in self._sections.items():
            section.dot.set_status(statuses.get(group_id), version)

    def set_compared(self, groups) -> None:
        """The compared version's groups, or None when nothing is compared: each channel's band
        changes beside its EQ chip (finding 74)."""
        by_id = {g.id: g for g in groups or ()}
        for group_id, section in self._sections.items():
            section.set_compared(by_id.get(group_id), groups is not None)

    def status_dots(self) -> dict:
        return {group_id: section.dot for group_id, section in self._sections.items()}

    def set_view(self, view: ProjectView) -> None:
        # A rebuild (preset switch) can happen while a row's hover popup is showing -- hide it so
        # it doesn't linger over a now-destroyed row.
        RoundedTooltip.instance().hide_tip()
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                # setParent(None) removes it from the visual tree immediately; deleteLater()
                # alone leaves it a visible, un-laid-out child until the next event-loop pass,
                # which overlaps with the freshly-added replacement widgets on a preset switch.
                discard.drop(widget)
        if view.features:
            params = ParamsSection("params", i18n.t("params"), view.features, self._settings)
            self._layout.insertWidget(self._layout.count() - 1, params)
        self._sections = {}
        # A tier with nothing in it is not drawn: «ВХОДИ 0» on a rig with no inputs (finding 71, 4).
        for group in (g for g in view.groups if g.rows_visible()):
            section = TreeGroupSection(group, self._settings)
            self._sections[group.id] = section
            if group.id == self._active[0]:
                section.set_active(self._active[1])
            section.channelClicked.connect(self.channelClicked.emit)
            section.eqRequested.connect(self.eqRequested.emit)
            section.tableRequested.connect(self.tableRequested.emit)
            section.toggleRequested.connect(self.toggleRequested.emit)
            self._layout.insertWidget(self._layout.count() - 1, section)
