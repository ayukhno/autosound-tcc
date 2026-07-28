"""The left panel's top-level accordion: Project params / System params / Car audio analysis /
DSP / ... (user request 2026-07-28) -- one collapsible `SidebarSection` per top-level item,
styled like the old static left-panel header bar (`.phead`) but clickable, with a twist triangle
matching the DSP-tree's `.ghead` group headers (`dsp_tree.TreeGroupSection`). Each section owns a
`body_layout()` that callers fill with whatever that section shows (the DSP tree, a flat params
list, or a "no data yet" placeholder) -- this module only owns the collapsible chrome.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from autosound_tcc.ui.tcc.theme import apply_caps


def _collapsed_key(section_id: str) -> str:
    return f"ui/sidebar_collapsed/{section_id}"


class SidebarSection(QWidget):
    """One top-level, collapsible left-panel section. Collapse state persists per section id via
    QSettings, same convention as `dsp_tree.TreeGroupSection`/`ParamsSection`."""

    def __init__(
        self, section_id: str, title: str, settings: QSettings, default_collapsed: bool = True
    ) -> None:
        super().__init__()
        self._id = section_id
        self._settings = settings
        collapsed = settings.value(_collapsed_key(section_id), default_collapsed, type=bool)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = QWidget()
        self._header.setProperty("class", "sidebar-head")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        # Fixed vertical policy -- without it, a widget with extra room to give (only "DSP" gets
        # `stretch=1` in the outer left-panel layout) and no other stretch-priority sibling to hand
        # it to (true when body is collapsed/hidden) gets stretched to fill that room itself, even
        # at stretch factor 0 (verified empirically). Fixed makes that impossible regardless of
        # collapse state, so the header always stays pinned to its own sizeHint.
        self._header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        head_layout = QHBoxLayout(self._header)
        head_layout.setContentsMargins(12, 8, 12, 8)
        head_layout.setSpacing(8)
        self._twist = QLabel()
        self._twist.setProperty("class", "tw")
        head_layout.addWidget(self._twist)
        self._title_label = QLabel(title)
        self._title_label.setProperty("class", "sidebar-title")
        apply_caps(self._title_label, spacing_px=1.4)
        head_layout.addWidget(self._title_label)
        self._sub_label = QLabel("")
        self._sub_label.setProperty("class", "phead-sub")
        head_layout.addWidget(self._sub_label)
        head_layout.addStretch(1)
        self._header.mousePressEvent = self._on_header_clicked  # type: ignore[assignment]
        outer.addWidget(self._header, 0, Qt.AlignmentFlag.AlignTop)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        # stretch=1: when the *outer* left-panel layout hands this whole section extra vertical
        # room (only "DSP" gets `stretch=1` there), that room must go to the body -- e.g. the DSP
        # tree's own QScrollArea, which otherwise sized itself to its content and left a big blank
        # gap below it (user report 2026-07-28) rather than actually filling/scrolling the section.
        # Combined with the header's Fixed policy above, this also keeps the header pinned when
        # body is collapsed (hidden) instead of inflating to soak up the room itself.
        outer.addWidget(self._body, 1)

        self._set_collapsed(collapsed)

    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

    def set_title(self, text: str) -> None:
        self._title_label.setText(text)

    def set_sub(self, text: str) -> None:
        self._sub_label.setText(text)

    def sub_text(self) -> str:
        return self._sub_label.text()

    def _on_header_clicked(self, event) -> None:
        self._set_collapsed(not self._body.isHidden())
        self._settings.setValue(_collapsed_key(self._id), self._body.isHidden())

    def _set_collapsed(self, collapsed: bool) -> None:
        self._body.setHidden(collapsed)
        self._twist.setText("▸" if collapsed else "▾")


def clear_layout(layout: QVBoxLayout) -> None:
    """Remove and dispose of every widget in `layout` -- shared by callers that rebuild a
    section's body from scratch on project load (same setParent(None)+deleteLater() pattern as
    `dsp_tree.DspTreeWidget.set_view`, for the same reason: setParent(None) drops the widget from
    the visual tree immediately instead of leaving a stale, un-laid-out child around until the
    next event-loop pass)."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.setParent(None)
            widget.deleteLater()
