"""«Виправити в REW…»: the wrong titles, fixed in REW and then in the round (the Arbiter's A17).

The list is the method's comparison (`core/title_fixes`): a grammar difference comes ticked, a
likely typo unticked — its intended name is a guess until the Arbiter confirms it. Apply renames
in REW by the title REW holds now, reads REW back, and records in the open round only what REW
shows done (hub #201: REW first, then the round).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from autosound_tcc.core import title_fixes
from autosound_tcc.ui.tcc import i18n, qt_shutdown


class TitleFixDialog(QDialog):
    def __init__(self, fixes: list[title_fixes.TitleFix], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.t("tfTitle"))
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        blurb = QLabel(i18n.t("tfBlurb"))
        blurb.setWordWrap(True)
        blurb.setProperty("class", "fb-hint")
        layout.addWidget(blurb)
        self._boxes: list[tuple[QCheckBox, title_fixes.TitleFix]] = []
        for fix in fixes:
            box = QCheckBox(f"{fix.wrong}  →  {fix.right}   ·  "
                            f"{i18n.t('tfGrammar' if fix.kind == 'grammar' else 'tfTypo')}")
            box.setChecked(fix.kind == "grammar")
            layout.addWidget(box)
            self._boxes.append((box, fix))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(i18n.t("tfApply"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("npCancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen(self) -> list[title_fixes.TitleFix]:
        return [fix for box, fix in self._boxes if box.isChecked()]


class TitleFixWorker(QThread):
    """Rename in REW, read REW back, then supersede in the round — off the GUI thread."""

    #: (fixes REW shows done, [(fix, what the method said on supersede)])
    done = Signal(list, list)
    failed = Signal(str)

    def __init__(self, bridge, fixes: list[title_fixes.TitleFix], project_dir: Path) -> None:
        super().__init__()
        self._bridge = bridge
        self._fixes = fixes
        self._project_dir = Path(project_dir)
        qt_shutdown.watch(self)

    def run(self) -> None:
        try:
            for fix in self._fixes:
                # By the title REW holds NOW: an ordinal from an earlier list can have moved.
                mid = self._bridge.find_id(fix.wrong)
                self._bridge.rename_measurement(mid, fix.right)
            live = self._bridge.measurements() or {}
        except Exception as exc:  # noqa: BLE001 — REW went away, or a title is ambiguous
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        titles = [str(m.get("title", "")) for m in (live.values() if isinstance(live, dict)
                                                     else live) if isinstance(m, dict)]
        good = title_fixes.confirmed(self._fixes, titles)
        said = [(fix, title_fixes.supersede(self._project_dir, fix.wrong, fix.right)[1])
                for fix in good]
        self.done.emit(good, said)
