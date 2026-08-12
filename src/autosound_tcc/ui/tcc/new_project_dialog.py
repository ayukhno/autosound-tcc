""""Create new project" entry point (docs/TCC-TZ.md): folder + vendor/model + AI model, then
hands off to the existing `ProfileInterviewDialog` -- no new interview logic here, just supplying
the three inputs it already needs (the same ones `dsp_profile_interview.py`'s CLI takes as
`--project-dir`/`--vendor`/`--model`; the interview itself asks everything else conversationally).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
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

from autosound_tcc.core import config, terminal_launcher
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.mock_data import AI_MAIN_MODELS, AI_MODEL_IDS
from autosound_tcc.ui.tcc.profile_interview_dialog import ProfileInterviewDialog


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("class", "kv-lbl")
    return label


def _bundled_profiles(bundled_dir: Path) -> list[tuple[str, str]]:
    """(vendor, name) pairs from the packaged `dsp_profiles/*.json` -- read directly rather than through
    the vendored `rew_tool` so this dialog still works if that submodule isn't checked out.

    Picking one of these guarantees an EXACT match against `dsp_profile.find_bundled()`'s
    deliberately strict, no-fuzzy-matching check (project-intake.md §4) -- free-typing "Helix" /
    "Ultra S" against a profile actually keyed `Audiotec-Fischer` / `Helix DSP Ultra S` is exactly
    how a real bundled profile gets missed (user report 2026-07-29)."""
    import json

    pairs = []
    for path in sorted(bundled_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        profile = data.get("dsp_profile", data) if isinstance(data, dict) else data
        vendor = str(profile.get("vendor", "")).strip()
        name = str(profile.get("name", "")).strip()
        if vendor and name:
            pairs.append((vendor, name))
    return pairs


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
        # Set by _on_create() instead when "run via" picks a terminal CLI rather than the in-app
        # chat -- main_window._open_new_project_dialog() branches on whichever ended up non-None.
        self.open_terminal_cli: Optional[str] = None
        self.project_dir: Optional[Path] = None
        self.onboarding_vendor: str = ""
        self.onboarding_model: str = ""
        self.onboarding_ai_model: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(10)

        layout.addWidget(_field_label(i18n.t("npFolder")))
        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        # The currently open project is the most relevant starting point TCC already knows about
        # (user request 2026-07-29) -- more useful than a bare home dir, and still just text the
        # user can edit or browse away from.
        self._folder_edit.setText(str(config.project_dir()))
        self._folder_edit.textChanged.connect(self._sync_create_enabled)
        folder_row.addWidget(self._folder_edit, stretch=1)
        browse_btn = QPushButton(i18n.t("npBrowse"))
        browse_btn.setProperty("class", "reason-btn")
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._on_browse)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)

        layout.addWidget(_field_label(i18n.t("npProfile")))
        self._profile_combo = QComboBox()
        self._profile_combo.setProperty("class", "mini-select")
        for vendor, name in _bundled_profiles(config.bundled_profiles_dir()):
            self._profile_combo.addItem(f"{vendor} — {name}", (vendor, name))
        self._profile_combo.addItem(i18n.t("npAddNew"), None)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        layout.addWidget(self._profile_combo)

        self._vendor_edit = QLineEdit()
        self._vendor_edit.setPlaceholderText(i18n.t("npVendorPlaceholder"))
        self._vendor_edit.textChanged.connect(self._sync_create_enabled)
        self._vendor_label = _field_label(i18n.t("npVendor"))
        layout.addWidget(self._vendor_label)
        layout.addWidget(self._vendor_edit)

        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText(i18n.t("npModelPlaceholder"))
        self._model_edit.textChanged.connect(self._sync_create_enabled)
        self._model_label = _field_label(i18n.t("npModel"))
        layout.addWidget(self._model_label)
        layout.addWidget(self._model_edit)

        # "Terminal" options only appear for CLIs actually installed (terminal_launcher's own
        # detection, already provider-agnostic -- claude/gemini/codex all speak MCP). Onboarding's
        # own MCP tools (core/mcp_server.py) are what makes this path real, not just a raw shell.
        layout.addWidget(_field_label(i18n.t("npRunVia")))
        self._run_via_combo = QComboBox()
        self._run_via_combo.setProperty("class", "mini-select")
        self._run_via_combo.addItem(i18n.t("npRunInApp"), None)
        for exe, label in terminal_launcher.available_clis():
            self._run_via_combo.addItem(f"Terminal — {label}", exe)
        self._run_via_combo.currentIndexChanged.connect(self._on_run_via_selected)
        layout.addWidget(self._run_via_combo)

        self._ai_model_label = _field_label(i18n.t("npAiModel"))
        layout.addWidget(self._ai_model_label)
        self._ai_combo = QComboBox()
        self._ai_combo.setProperty("class", "mini-select")
        self._ai_combo.addItems(AI_MAIN_MODELS)
        layout.addWidget(self._ai_combo)

        # Terminal path's own model field: free-text, since each CLI has its own model-name
        # vocabulary (TCC doesn't maintain a Gemini/Codex catalog the way it does for Claude) --
        # passed through as `--model <value>` (terminal_launcher.launch), blank = CLI's own default.
        self._terminal_model_label = _field_label(i18n.t("npTerminalModel"))
        layout.addWidget(self._terminal_model_label)
        self._terminal_model_edit = QLineEdit()
        self._terminal_model_edit.setPlaceholderText(i18n.t("npTerminalModelPlaceholder"))
        layout.addWidget(self._terminal_model_edit)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_btn = QPushButton(i18n.t("npCancel"))
        cancel_btn.setProperty("class", "reason-btn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        self._create_btn = QPushButton(i18n.t("npCreate"))
        self._create_btn.setProperty("class", "reason-btn")
        self._create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._create_btn.setEnabled(False)
        self._create_btn.clicked.connect(self._on_create)
        actions.addWidget(self._create_btn)
        layout.addLayout(actions)

        self._on_profile_selected(self._profile_combo.currentIndex())
        self._on_run_via_selected(self._run_via_combo.currentIndex())

    def _on_run_via_selected(self, _index: int) -> None:
        """The Claude-specific AI_MAIN_MODELS picker only means anything for the in-app path;
        a terminal CLI gets its own free-text model field instead (2026-07-29: "would be right to
        call terminals with a model applied too")."""
        is_in_app = self._run_via_combo.currentData() is None
        self._ai_model_label.setVisible(is_in_app)
        self._ai_combo.setVisible(is_in_app)
        self._terminal_model_label.setVisible(not is_in_app)
        self._terminal_model_edit.setVisible(not is_in_app)

    def _on_profile_selected(self, _index: int) -> None:
        """A bundled pick fills vendor/model with the EXACT strings `find_bundled()` checks
        against and hides the free-text fields (nothing to type); "Add new" clears and reveals
        them for a DSP that isn't in the packaged `dsp_profiles/` yet."""
        pair = self._profile_combo.currentData()
        is_new = pair is None
        if not is_new:
            vendor, model = pair
            self._vendor_edit.setText(vendor)
            self._model_edit.setText(model)
        else:
            self._vendor_edit.clear()
            self._model_edit.clear()
        for widget in (self._vendor_label, self._vendor_edit, self._model_label, self._model_edit):
            widget.setVisible(is_new)
        self._sync_create_enabled()

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

        # Mirrors dsp_profile_interview.py's CLI path exactly -- OnboardingSession itself does not
        # create the folder.
        project_dir.mkdir(parents=True, exist_ok=True)
        config.set_project_dir(project_dir)
        self.project_dir = project_dir

        cli = self._run_via_combo.currentData()
        if cli is None:
            ai_model = AI_MODEL_IDS.get(self._ai_combo.currentText())
            self.interview_dialog = ProfileInterviewDialog(
                project_dir, vendor, model, ai_model, i18n.current_language(),
                parent=self.parent(),
            )
        else:
            self.open_terminal_cli = cli
            self.onboarding_vendor = vendor
            self.onboarding_model = model
            self.onboarding_ai_model = self._terminal_model_edit.text().strip() or None
        self.accept()
