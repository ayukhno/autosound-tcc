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

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.state.dsp_state import CrossoverLeg, GroupRow, ProfileGroup, ProjectView
from autosound_tcc.ui.tcc import copy_menu, i18n, rounded_tooltip
from autosound_tcc.ui.tcc.app_settings import get_settings
from autosound_tcc.ui.tcc.labels import ElidedLabel
from autosound_tcc.ui.tcc.rounded_tooltip import RoundedTooltip
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


def _sub_line(text: str) -> ElidedLabel:
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
    """
    label = ElidedLabel(text, native_tooltip=False)
    label.setProperty("class", "cline2")
    return label


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

    def __init__(self, count: int) -> None:
        super().__init__(f"EQ {count}" if count else "EQ —")
        self.setProperty("class", "eq-chip" if count else "eq-chip muted")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.accept()
        self.clicked.emit()


class ChannelRow(QWidget):
    """Two-line row: ID badge + name + polarity/mute pill + EQ chip, then (for rows with a
    crossover) a compact HP/LP/gain summary line — mirrors `.cline1`/`.cline2`."""

    clicked = Signal()
    eqRequested = Signal()
    # (channel name, wanted state). A request, not a change: the ledger is the skill's to write.
    toggleRequested = Signal(str, bool)

    def __init__(self, group: ProfileGroup, row: GroupRow) -> None:
        super().__init__()
        self.setProperty("class", "chan")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 4, 8, 5)
        layout.setSpacing(1)

        is_output = "hp" in group.known_fields or "lp" in group.known_fields
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
            # MUTE-only in the working interface (user request 2026-07-27) -- OFF (hardware
            # physically disabled at the DSP level, GroupRow.off) is real data but stays out of
            # the main tree/table for now, deferred to a future settings view to avoid confusing
            # the two states side by side. See pill-off/`_FIELD_COLUMNS["off"]` (detail_pane.py) --
            # left in place, just not wired into any profile's `fields` list right now.
            line1.addWidget(_Pill(i18n.t("pillMute"), "mute"))
            self.setProperty("class", "chan chan-dim")
        elif raw.get("polarity") == "INV":
            # Only flag inversion -- NORM is the default and showing it on every row is noise
            # (user request 2026-07-27).
            line1.addWidget(_Pill("INV", "inv"))

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
        eq_count = row.eq_count()
        self._eq_chip = _EqChip(eq_count)
        self._eq_chip.clicked.connect(self.eqRequested.emit)
        line1.addWidget(self._eq_chip)
        layout.addLayout(line1)

        if is_output:
            hp = CrossoverLeg.from_raw(raw.get("hp")).label
            lp = CrossoverLeg.from_raw(raw.get("lp")).label
            gain = raw.get("gain_db")
            gain_s = f"{gain:+.1f}dB" if isinstance(gain, (int, float)) else "—"
            line2 = _sub_line(f"HP {hp} · LP {lp} · {gain_s}")
            layout.addWidget(line2)
        else:
            # Virtual channels have no crossover, but their gain (and delay) matter in the main
            # list -- surface them the same way (user request 2026-07-27).
            gain = raw.get("gain_db")
            delay = raw.get("ta_ms")
            parts = [f"Gain {gain:+.1f}dB" if isinstance(gain, (int, float)) else "Gain —"]
            if isinstance(delay, (int, float)):
                parts.append(f"Delay {delay:g}ms")
            line2 = _sub_line(" · ".join(parts))
            layout.addWidget(line2)

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
                meta.append(f"Fs&nbsp;{row.fs_hz:g}&nbsp;Hz")
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

        for row in visible_rows:
            chan = ChannelRow(group, row)
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
                widget.setParent(None)
                widget.deleteLater()
        if view.features:
            params = ParamsSection("params", i18n.t("params"), view.features, self._settings)
            self._layout.insertWidget(self._layout.count() - 1, params)
        for group in view.groups:
            section = TreeGroupSection(group, self._settings)
            section.channelClicked.connect(self.channelClicked.emit)
            section.eqRequested.connect(self.eqRequested.emit)
            section.tableRequested.connect(self.tableRequested.emit)
            section.toggleRequested.connect(self.toggleRequested.emit)
            self._layout.insertWidget(self._layout.count() - 1, section)
