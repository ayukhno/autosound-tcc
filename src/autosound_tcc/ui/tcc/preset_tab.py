"""The «Пресет» tab's page, and the words of a version's `preset_settings` (#256, hub #324).

`state/preset_settings.py` reads the ledger; this says it on screen. `lines` is the one list the
tab and the tree's section both draw, so what the two say cannot differ.

Grey is the method's reading of a field nobody stated: the default, unknown, a dash. Against
«порівняти з», what differs is drawn as every other table's changed cell: blue and bold, with what
it was on hover (`detail_pane._styled_cell`). The status and the source file are no change of the
DSP, so neither is compared. TCC writes nothing here.
"""

from __future__ import annotations

import html
from typing import Callable, NamedTuple, Optional

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from autosound_tcc.state.dsp_state import UNREAD_LEG
from autosound_tcc.state import preset_settings as model
from autosound_tcc.state.preset_settings import DASH, DEFAULT, STATED, UNKNOWN, UNREAD, PresetSettings
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.detail_pane import CHANGED_ROLE, _ContentTable
from autosound_tcc.ui.tcc.theme import apply_caps, current_theme

#: A reading on a table cell, for the theme change's repaint (`_PresetTable`).
READING_ROLE = Qt.ItemDataRole.UserRole + 10
#: A line about the source file that says the file and the version disagree.
WARN = "warn"
#: The heading row of the source file's block.
HEAD = "head"
#: The order the DSP shows them, the Conductor's lamps beside the FX group (hub #324).
_ORDER = ("input_gain_db", "sources.main", "sources.hec", "sources.digital", "fx.realcenter",
          "fx.dynamic_bass", "fx.subxpander", "conductor.sub_lamps", "rtc.on", "rtc.curve",
          "bt.source", "bt.auto_switch")
_LABEL_KEY = {
    "input_gain_db": "presetInputGain", "sources.main": "presetMain", "sources.hec": "presetHec",
    "sources.digital": "presetDigital", "fx.realcenter": "presetRealcenter",
    "fx.dynamic_bass": "presetDynBass", "fx.subxpander": "presetSubxpander", "rtc.on": "presetRtc",
    "rtc.curve": "presetRtcCurve", "bt.source": "presetBtSource", "bt.auto_switch": "presetBtAuto",
    "conductor.sub_lamps": "presetConductor",
}
_ROW_HEIGHT = 26


class PresetLine(NamedTuple):
    """One row, as it is said: its key, its label, its text, how it reads, and its hover."""

    key: str
    label: str
    text: str
    reading: str
    changed: bool = False
    tip: str = ""
    copy: str = ""


def value_said(setting) -> str:
    """The value in the words of a sheet: unknown is said, a value nobody stated is a dash."""
    if setting.reading == UNREAD:
        return UNREAD_LEG
    value = setting.value
    if setting.reading == UNKNOWN or value is None:
        return i18n.t("presetUnknown") if setting.kind == "switch" else "—"
    if setting.kind == "db":
        return f"{value:g} dB"
    if setting.kind == "switch":
        return i18n.t("presetOn" if value else "presetOff")
    if setting.kind == "curve":
        return " · ".join(f"{k} {v:g}" for k, v in value.items())
    return str(value)


def _safe(text: str) -> str:
    """A hover that may hold the ledger's words: Qt reads a tooltip with tags as rich text."""
    escaped = html.escape(text, quote=False)
    return f"<qt>{escaped}</qt>" if escaped != text else text


def _setting_line(setting, was, compared: bool) -> PresetLine:
    label = i18n.t(_LABEL_KEY[setting.path])
    text, tip = value_said(setting), ""
    if setting.reading == UNREAD:
        tip = i18n.t("presetUnreadTip").format(value=setting.held)
    elif setting.reading == DEFAULT:
        tip = i18n.t("presetDefaultTip")
    elif setting.reading == UNKNOWN:
        tip = i18n.t("presetUnknownTip")
    elif setting.reading == DASH:
        tip = i18n.t("presetDashTip")
    changed = compared and was is not None and setting.changes_from(was)
    if changed:
        tip = i18n.t("cmpWas").format(value=value_said(was))
    elif compared and was is not None and setting.unknown_against_off(was):
        tip = i18n.t("presetUnknownSideTip")
    copy = f"{setting.value:g}" if setting.kind == "db" and setting.value is not None else ""
    return PresetLine(setting.path, label, text, setting.reading, bool(changed), _safe(tip), copy)


def lines(view, compared_view=None) -> list[PresetLine]:
    """The settings of `view`, in the DSP's order, against `compared_view` if one is compared."""
    settings = getattr(view, "preset_settings", None)
    if settings is None:
        return []
    old = getattr(compared_view, "preset_settings", None) if compared_view is not None else None
    was_all = None if compared_view is None else (old if old is not None else model.read(None, settings.audiotec))
    order = {path: i for i, path in enumerate(_ORDER)}
    out = []
    for setting in sorted(settings.settings, key=lambda s: order[s.path]):
        was = was_all.by_path(setting.path) if was_all is not None else None
        out.append(_setting_line(setting, was, compared_view is not None))
    return out


def file_lines(view) -> list[PresetLine]:
    """The source file's rows, for a DSP whose save file TCC can read; none otherwise."""
    settings = getattr(view, "preset_settings", None)
    if settings is None or not settings.audiotec:
        return []
    source = settings.source
    if source is None:
        if settings.source_unread:
            return [PresetLine("file", i18n.t("presetFile"), UNREAD_LEG, UNREAD, tip=i18n.t("presetFileUnreadTip"))]
        return [PresetLine("file", i18n.t("presetFile"), i18n.t("presetNotFromFile"), DASH)]
    out = [PresetLine("file", i18n.t("presetFile"), source.name or UNREAD_LEG, STATED, tip=_safe(source.path or ""))]
    for key, value in (("presetMd5", source.md5[:8] if source.md5 else None), ("presetSaved", source.saved),
                       ("presetReadAt", source.read_at), ("presetPctool", source.pctool),
                       ("presetDevice", source.device)):
        if value:
            out.append(PresetLine(key, i18n.t(key), value, STATED))
    if source.differences:
        out.append(PresetLine("presetCompared", i18n.t("presetCompared"), "; ".join(source.differences), WARN,
                        tip=_safe("\n".join(source.differences))))
    elif source.compared:
        out.append(PresetLine("presetCompared", i18n.t("presetCompared"), i18n.t("presetNoDifference"), STATED))
    return out


def section_lines(view, compared_view=None) -> list[PresetLine]:
    """What the tree's section says: the settings, and the file as one row (name · md5)."""
    out = lines(view, compared_view)
    file = file_lines(view)
    if file:
        said, tip = file[0].text, file[0].tip
        md5 = next((f.text for f in file[1:] if f.key == "presetMd5"), "")
        out.append(file[0]._replace(text=f"{said} · {md5}" if md5 else said, tip=tip))
    return out


def colour_of(reading: str, changed: bool) -> Optional[str]:
    """The colour of a value, in the theme showing now; None is the default text colour."""
    t = current_theme()
    if changed:
        return t.info
    if reading == HEAD:
        return t.muted
    if reading in (DEFAULT, UNKNOWN, DASH):
        return t.faint
    return t.warn if reading in (UNREAD, WARN) else None


class _PresetTable(_ContentTable):
    """The tab's table. Its colours are read off the theme showing now on a theme switch: the cells'
    foregrounds are written once otherwise, and a switch left the old theme's blue (tcc#122)."""

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().changeEvent(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            for row in range(self.rowCount()):
                for column in range(self.columnCount()):
                    item = self.item(row, column)
                    if item is not None and item.data(READING_ROLE) is not None:
                        _paint(item)


def _paint(item: QTableWidgetItem) -> None:
    changed = item.data(CHANGED_ROLE) is True
    colour = colour_of(str(item.data(READING_ROLE)), changed)
    if colour:
        item.setForeground(QColor(colour))


def _fill_row(table: QTableWidget, row: int, line: PresetLine) -> None:
    name = QTableWidgetItem(line.label)
    name.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    table.setItem(row, 0, name)
    value = QTableWidgetItem(line.text)
    value.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    value.setData(READING_ROLE, line.reading)
    value.setData(Qt.ItemDataRole.UserRole, line.copy or line.text)
    if line.tip:
        value.setToolTip(line.tip)
    if line.changed:
        value.setData(CHANGED_ROLE, True)
        font = value.font()
        font.setBold(True)
        value.setFont(font)
    _paint(value)
    table.setItem(row, 1, value)
    table.setRowHeight(row, _ROW_HEIGHT)


def _note(text: str, layout: QVBoxLayout, classes: str = "phead-sub") -> None:
    label = QLabel(text)
    label.setProperty("class", classes)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setContentsMargins(8, 6, 8, 2)
    layout.addWidget(label)


def page(view, compared_view, copy_on_right_click: Callable[[QTableWidget], None]) -> QWidget:
    """The tab: what it is, the settings, the file. Built whole on every open or compare: a new
    table in the scroll area is what takes the old one away."""
    settings: PresetSettings = view.preset_settings
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    if not settings.any_recorded:
        _note(i18n.t("presetNothingStated"), layout)
    if settings.status:
        _note(i18n.t("presetStatusLine").format(status=i18n.t(f"presetStatus_{settings.status}")), layout)

    rows = lines(view, compared_view)
    source = file_lines(view)
    table = _PresetTable(len(rows) + (len(source) + 1 if source else 0), 2)
    table.setProperty("class", "ptable")
    table.setHorizontalHeaderLabels([i18n.t("presetColSetting"), i18n.t("presetColValue")])
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    apply_caps(table.horizontalHeader(), spacing_px=0.7)
    for row, line in enumerate(rows):
        _fill_row(table, row, line)
    if source:
        head = QTableWidgetItem(i18n.t("presetSourceHead"))
        head.setData(READING_ROLE, HEAD)
        _paint(head)
        table.setItem(len(rows), 0, head)
        table.setSpan(len(rows), 0, 1, 2)
        table.setRowHeight(len(rows), _ROW_HEIGHT)
        for row, line in enumerate(source, start=len(rows) + 1):
            _fill_row(table, row, line)
    copy_on_right_click(table)
    layout.addWidget(table)
    return holder
