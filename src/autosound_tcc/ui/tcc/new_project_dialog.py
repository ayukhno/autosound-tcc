""""Create new project" entry point (docs/TCC-TZ.md): folder + vendor/model + AI model, then
hands off to the existing `ProfileInterviewDialog` -- no new interview logic here, just supplying
the three inputs it already needs (the same ones `dsp_profile_interview.py`'s CLI takes as
`--project-dir`/`--vendor`/`--model`; the interview itself asks everything else conversationally).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from autosound_tcc.core import config
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.mock_data import AI_MAIN_MODELS, AI_MODEL_IDS
from autosound_tcc.ui.tcc.profile_interview_dialog import ProfileInterviewDialog


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("class", "kv-lbl")
    return label


class NewProjectDialog(QDialog):
    """Collects folder + vendor + model + AI model, then constructs (but does not show)
    `ProfileInterviewDialog` -- the caller (`main_window._open_new_project_dialog`) owns showing
    it and reacting to its `profile_saved` signal, since that's where the "restart pointed at the
    new project" logic belongs."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(i18n.t("npTitle"))
        self.setMinimumWidth(420)
        self.interview_dialog: Optional[ProfileInterviewDialog] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(10)

        layout.addWidget(_field_label(i18n.t("npFolder")))
        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        recent = config.recent_projects()
        self._folder_edit.setText(str(recent[0]) if recent else str(Path.home()))
        self._folder_edit.textChanged.connect(self._sync_create_enabled)
        folder_row.addWidget(self._folder_edit, stretch=1)
        browse_btn = QPushButton(i18n.t("npBrowse"))
        browse_btn.clicked.connect(self._on_browse)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)

        layout.addWidget(_field_label(i18n.t("npVendor")))
        self._vendor_edit = QLineEdit()
        self._vendor_edit.setPlaceholderText(i18n.t("npVendorPlaceholder"))
        self._vendor_edit.textChanged.connect(self._sync_create_enabled)
        layout.addWidget(self._vendor_edit)

        layout.addWidget(_field_label(i18n.t("npModel")))
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText(i18n.t("npModelPlaceholder"))
        self._model_edit.textChanged.connect(self._sync_create_enabled)
        layout.addWidget(self._model_edit)

        layout.addWidget(_field_label(i18n.t("npAiModel")))
        self._ai_combo = QComboBox()
        self._ai_combo.setProperty("class", "mini-select")
        self._ai_combo.addItems(AI_MAIN_MODELS)
        layout.addWidget(self._ai_combo)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_btn = QPushButton(i18n.t("npCancel"))
        cancel_btn.setProperty("class", "reason-btn")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        self._create_btn = QPushButton(i18n.t("npCreate"))
        self._create_btn.setProperty("class", "reason-btn")
        self._create_btn.setEnabled(False)
        self._create_btn.clicked.connect(self._on_create)
        actions.addWidget(self._create_btn)
        layout.addLayout(actions)

    def _sync_create_enabled(self) -> None:
        self._create_btn.setEnabled(
            bool(self._folder_edit.text().strip())
            and bool(self._vendor_edit.text().strip())
            and bool(self._model_edit.text().strip())
        )

    def _on_browse(self) -> None:
        start = self._folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, i18n.t("npFolder"), start)
        if chosen:
            self._folder_edit.setText(chosen)

    def _on_create(self) -> None:
        project_dir = Path(self._folder_edit.text().strip()).expanduser()
        vendor = self._vendor_edit.text().strip()
        model = self._model_edit.text().strip()
        ai_model = AI_MODEL_IDS.get(self._ai_combo.currentText())

        # Mirrors dsp_profile_interview.py's CLI path exactly -- OnboardingSession itself does not
        # create the folder.
        project_dir.mkdir(parents=True, exist_ok=True)
        config.set_project_dir(project_dir)

        self.interview_dialog = ProfileInterviewDialog(
            project_dir, vendor, model, ai_model, parent=self.parent()
        )
        self.accept()
