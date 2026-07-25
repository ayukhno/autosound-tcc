"""The main TCC window.

Renders one read-only table per group declared in the project's DSP capability profile
(`core/vendor_loader.load_dsp_profile`) — not a hardcoded VIRTUAL/OUTPUT pair. A Helix profile
declares `virtual_channels` + `physical_outputs`; a MUSWAY profile might declare only
`physical_outputs` + `inputs`. No per-DSP Qt code is needed either way (docs/TCC-TZ.md §2).
REW curve panels come in a later milestone. Nothing here writes to the DSP — read-only by
design (brief §11).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc import __version__
from autosound_tcc.core import config
from autosound_tcc.state.dsp_state import ProjectView, load_project_view
from autosound_tcc.ui.tcc.group_table import GroupTable


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight: 600; margin-top: 6px;")
    return label


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("autosound-tcc — Tuning Command Center")
        self.resize(1040, 720)

        self._header = QLabel()
        self._header.setTextFormat(Qt.TextFormat.RichText)
        self._status = QLabel()
        self._status.setStyleSheet("color: #888;")

        self._central = QWidget()
        self._layout = QVBoxLayout(self._central)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(6)
        self._layout.addWidget(self._header)
        self._group_widgets: list[tuple[QLabel, GroupTable]] = []
        self._layout.addWidget(self._status)
        self.setCentralWidget(self._central)

        self._load()

    def _clear_group_widgets(self) -> None:
        for label, table in self._group_widgets:
            self._layout.removeWidget(label)
            self._layout.removeWidget(table)
            label.deleteLater()
            table.deleteLater()
        self._group_widgets = []

    def _build_group_widgets(self, count: int) -> None:
        """(Re)build exactly `count` section-label + GroupTable pairs, inserted before the
        trailing status label — one pair per profile group, in profile-declared order."""
        self._clear_group_widgets()
        status_index = self._layout.indexOf(self._status)
        for _ in range(count):
            label = _section_label("")
            table = GroupTable()
            self._layout.insertWidget(status_index, label)
            self._layout.insertWidget(status_index + 1, table, stretch=1)
            status_index += 2
            self._group_widgets.append((label, table))

    def _load(self) -> None:
        profile_path = config.dsp_profile_path()
        if not profile_path.is_file():
            self._show_no_profile(profile_path)
            return
        try:
            from autosound_tcc.core import vendor_loader

            dsp_profile = vendor_loader.load_dsp_profile()
            profile = dsp_profile.load_profile(str(profile_path))
            dsp_profile.validate_profile(profile)
        except Exception as exc:  # missing/broken profile — degrade, don't crash
            self._show_error("DSP profile", exc)
            return

        root = config.state_root()
        preset = config.resolve_preset(root)
        if preset is None:
            self._show_no_ledger(root, profile)
            return
        try:
            view = load_project_view(str(root), preset, profile)
        except Exception as exc:
            self._show_error(preset, exc)
            return
        self._show_view(view, profile)

    def _show_view(self, view: ProjectView, profile: dict) -> None:
        self._build_group_widgets(len(view.groups))
        for (label, table), group in zip(self._group_widgets, view.groups):
            label.setText(f"{group.label} ({len(group.rows)})")
            table.set_group(group)

        prof = profile.get("dsp_profile", profile)
        sr = f"{view.sample_rate / 1000:g} kHz" if view.sample_rate else "—"
        self._header.setText(
            f"<b>DSP:</b> {prof.get('vendor', '?')} {prof.get('name', '?')} &nbsp;&nbsp; "
            f"<b>Preset:</b> {view.preset} &nbsp;&nbsp; "
            f"<b>Sample rate:</b> {sr} &nbsp;&nbsp; "
            f"<b>Version:</b> {view.version or '—'}"
        )
        note = f" — {view.note}" if view.note else ""
        counts = " · ".join(f"{g.label.lower()}: {len(g.rows)}" for g in view.groups)
        self._status.setText(f"{counts} · read-only view v{__version__}{note}")

    def _show_no_profile(self, path) -> None:
        self._clear_group_widgets()
        self._header.setText("<b>No DSP profile found</b>")
        self._status.setText(
            f"Looked for {path}. Run the DSP onboarding interview "
            f"(`python -m autosound_tcc.dsp_profile_interview`) to create one."
        )

    def _show_no_ledger(self, root, profile: dict) -> None:
        self._clear_group_widgets()
        prof = profile.get("dsp_profile", profile)
        self._header.setText(f"<b>{prof.get('vendor', '?')} {prof.get('name', '?')}</b> — no ledger yet")
        self._status.setText(
            f"Profile OK, but no preset snapshot found under {root}. Set "
            f"AUTOSOUND_TCC_STATE_ROOT / AUTOSOUND_TCC_PRESET to point at a project ledger."
        )

    def _show_error(self, what: str, exc: Exception) -> None:
        self._clear_group_widgets()
        self._header.setText(f"<b>Could not load</b> {what}")
        self._status.setText(f"{type(exc).__name__}: {exc}")
