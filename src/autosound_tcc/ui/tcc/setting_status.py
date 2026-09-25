"""Whether a part of the rig carries settings, and whether they moved (the Arbiter, 2026-09-25,
finding 65) — a dot beside the DSP tree's groups and on the tabs that show them.

One dot, three states, in colours the window already gives these facts:

* ``none`` — grey, ``off``: nothing is set there;
* ``set`` — green, ``ok``, as the DSP section's version dot: something is;
* ``chg`` — blue, ``info``, as the changed cells of «порівняти з»: it differs from that version.

Blue only while something is compared: with «—» there is nothing to differ from.
"""

from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from autosound_tcc.state.dsp_state import CrossoverLeg, GroupRow, ProfileGroup
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.theme import current_theme

#: The painted dot, and the square that answers the mouse around it: «можна зробити зону
#: спрацювання трохи більше, бо важко попасти» (the Arbiter, 2026-09-25).
DOT_DIAMETER = 8
_TARGET = 18

#: What counts as a setting. `off` is not among them: an off channel is not in the rows at all.
_JUDGED = ("hp", "lp", "gain_db", "ta_ms", "phase_deg", "polarity", "mute", "eq_bypass", "eq")
_TIP_KEY = {"none": "dotNone", "set": "dotSet", "chg": "dotChg"}


def _is_set(field: str, raw: dict) -> bool:
    value = raw.get(field)
    if field in ("gain_db", "ta_ms", "phase_deg"):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value != 0
    if field in ("hp", "lp"):
        try:
            return CrossoverLeg.from_raw(value).enabled
        except ValueError:
            return False
    if field == "polarity":
        return value == "INV"
    return bool(value)


def _judge(row: GroupRow, old: Optional[GroupRow], compared: bool,
           fields: Iterable[str]) -> tuple[bool, bool]:
    """`(carries a setting, differs from the compared version)` for one channel."""
    fields = tuple(fields)
    has = any(_is_set(f, row.raw) for f in fields)
    if not compared:
        return has, False
    if old is None:  # a channel the compared version does not have
        return has, has
    return has, any(row.raw.get(f) != old.raw.get(f) for f in fields)


def _status(has: bool, changed: bool) -> str:
    return "chg" if changed else ("set" if has else "none")


def _fields(group: ProfileGroup) -> tuple[str, ...]:
    if group.fields_unknown:
        return _JUDGED
    return tuple(f for f in group.known_fields if f in _JUDGED)


def group_status(group: ProfileGroup, compared_group: Optional[ProfileGroup] = None,
                 compared: bool = False) -> str:
    """One tier as a whole — the tree's group header, a table's tab."""
    olds = {r.id: r for r in compared_group.rows} if compared_group is not None else {}
    has = changed = False
    for row in group.rows_visible():
        h, c = _judge(row, olds.get(row.id), compared, _fields(group))
        has, changed = has or h, changed or c
    return _status(has, changed)


def field_status(groups: Iterable[ProfileGroup], field: str,
                 compared_groups: Optional[Iterable[ProfileGroup]] = None,
                 compared: bool = False) -> str:
    """One control across every tier that has it — the EQ, Level, Delays and Phases tabs."""
    by_id = {g.id: g for g in (compared_groups or ())}
    has = changed = False
    for group in groups:
        if not group.fields_unknown and field not in group.known_fields:
            continue
        old_group = by_id.get(group.id)
        olds = {r.id: r for r in old_group.rows} if old_group is not None else {}
        for row in group.rows_visible():
            h, c = _judge(row, olds.get(row.id), compared, (field,))
            has, changed = has or h, changed or c
    return _status(has, changed)


class StatusDot(QWidget):
    """The dot: painted small, hovered large, with its meaning on hover."""

    def __init__(self, parent: Optional[QWidget] = None, width: int = _TARGET,
                 align_right: bool = False) -> None:
        """`width` narrower than the target where room is short — a tab, whose own tooltip then
        carries the hint over the whole tab. `align_right` paints the dot at the right edge (a
        tab's, finding 67, 3)."""
        super().__init__(parent)
        self.setFixedSize(width, _TARGET)
        self.align_right = align_right
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._status: Optional[str] = None
        self._tip_text = ""
        self._tip = attach_tip(self)
        self.setHidden(True)

    def set_status(self, status: Optional[str], version: Optional[str] = None) -> None:
        """`None` hides the dot: a tab with nothing to judge carries none."""
        self._status = status
        self.setHidden(status is None)
        self._tip_text = ("" if status is None
                          else i18n.t(_TIP_KEY[status]).format(version=version or ""))
        self._tip.set_text(self._tip_text)
        self.update()

    def status(self) -> Optional[str]:
        return self._status

    def tip_text(self) -> str:
        return self._tip_text

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        if self._status is None:
            return
        t = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor({"none": t.off, "set": t.ok, "chg": t.info}[self._status]))
        x = (self.width() - DOT_DIAMETER - 1) if self.align_right else (self.width() - DOT_DIAMETER) / 2
        y = (self.height() - DOT_DIAMETER) / 2
        painter.drawEllipse(QRectF(x, y, DOT_DIAMETER, DOT_DIAMETER))
        painter.end()
