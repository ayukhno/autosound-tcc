"""The first screen when no project has been chosen: which folder, and which models drive it.

TCC binds one folder at startup — the MCP server, the session registry, the file watchers and
every panel — so the folder is not a setting that can be changed later in place; it is the
question the window cannot open without an answer to. Until now it answered itself, falling back
to this checkout's own dogfood directory, which meant a fresh install opened somebody else's
project and said nothing about it.

Folder and models together, because those are the project's own parameters: which build this is,
and what drives it. Both land in `<project>/.tcc/tcc-project.json`, so the choice belongs to the
project rather than to whoever opened it (`core/project_settings.py`).

**An empty folder is a valid answer.** The intake is a conversation that fills it, so choosing a
folder and creating a project are one act. Nothing here inspects the contents — a gate that
decided what counts as a project would be inventing a rule the method does not have.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from autosound_tcc.core import config, model_choices, project_settings
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.app_settings import get_settings

ACTIVE_OMP_KEY = "ai/active_omp"


def _label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("class", "kv-lbl")
    return label


class ProjectGateDialog(QDialog):
    """Answers "which project": `folder` is set once accepted, or None if the user backed out."""

    def __init__(self, parent=None, suggested: Optional[Path] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.t("gateTitle"))
        self.setMinimumWidth(560)
        self.folder: Optional[Path] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        blurb = QLabel(i18n.t("gateBlurb"))
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        layout.addWidget(_label(i18n.t("gateFolder")))
        row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText(i18n.t("gateFolderPlaceholder"))
        if suggested is not None:
            self._folder_edit.setText(str(suggested))
        self._folder_edit.textChanged.connect(self._sync_ok)
        row.addWidget(self._folder_edit, 1)
        browse = QPushButton(i18n.t("gateBrowse"))
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        layout.addLayout(row)

        # The models are the project's other parameter, asked here so the first session does not
        # start on a default nobody picked.
        active = [s for s in str(get_settings().value(ACTIVE_OMP_KEY, "")).split(",") if s]
        self._choices = model_choices.choices(active)
        layout.addWidget(_label(i18n.t("aiMain")))
        self._generator = self._model_combo()
        layout.addWidget(self._generator)
        layout.addWidget(_label(i18n.t("aiCritic")))
        self._critic = self._model_combo()
        layout.addWidget(self._critic)

        note = QLabel(i18n.t("gateNote"))
        note.setWordWrap(True)
        layout.addWidget(note)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(i18n.t("gateOpen"))
        self._buttons.accepted.connect(self._accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._sync_ok()

    def _model_combo(self) -> QComboBox:
        combo = QComboBox()
        for choice in self._choices:
            prefix = "SDK · " if choice.harness == "sdk" else ""
            suffix = f"  ·  {i18n.t('modelFree')}" if choice.free else ""
            combo.addItem(f"{prefix}{choice.label}{suffix}", choice.key)
        return combo

    def _browse(self) -> None:
        start = self._folder_edit.text().strip() or str(Path.home())
        picked = QFileDialog.getExistingDirectory(self, i18n.t("gateFolder"), start)
        if picked:
            self._folder_edit.setText(picked)

    def _sync_ok(self) -> None:
        # A folder that does not exist yet is fine to type -- it is created on accept, which is
        # what "create a new project" means here.
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            bool(self._folder_edit.text().strip()) and bool(self._choices)
        )

    def _accept(self) -> None:
        folder = Path(self._folder_edit.text().strip()).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Unwritable path: say nothing new, just refuse to accept. The user can see the path
            # they typed and fix it, which is more useful than a dialog on top of a dialog.
            return
        config.set_project_dir(folder)
        project_settings.set_value(config.tcc_dir(folder), "generator", self._generator.currentData())
        project_settings.set_value(config.tcc_dir(folder), "critic", self._critic.currentData())
        self.folder = folder
        self.accept()


def ensure_project_chosen(parent=None, force: bool = False) -> bool:
    """Gate the launch. True if a project is chosen (already, or now); False if the user backed out.

    Nothing else in the window is meaningful without one -- an unanswered gate has to stop the
    launch rather than fall through to a folder nobody picked.

    `force` is `--choose-project`. Without it a remembered choice wins silently, which is right
    almost always and surprising exactly once: launching from inside a different folder changes
    nothing, because TCC does not read the working directory. `--project-dir .` is the answer to
    that, and this is the answer when the remembered one should simply be re-asked.
    """
    remembered = config.chosen_project_dir()
    here = _launched_from()
    # Standing inside a real project and typing `autosound-tcc` is already a choice, and a clearer
    # one than anything remembered from last week. The gate exists to stop the window opening on a
    # folder nobody picked; a folder the person is standing in, which already holds a project, is
    # not that folder. Asking there cost an Enter to confirm what they had just said by being
    # there (user, 2026-08-13). An empty or unrelated folder still asks.
    if not force and here is not None and here != remembered and config.looks_like_project(here):
        config.set_project_dir(here)
        return True
    if not force and remembered is not None and here is not None and here != remembered:
        # Started from a shell, standing in a folder that is not the remembered project. The
        # remembered one used to win silently, which is right for a double-clicked bundle and
        # wrong here: `cd testTCC-5 && python -m autosound_tcc.app` opened testTCC-3 and said
        # nothing, so the window and the person disagreed about which car they were tuning.
        # Asking, with the folder you are standing in already filled in, costs one Enter.
        force = True
    if not force and remembered is not None:
        return True
    dialog = ProjectGateDialog(parent, suggested=here if here != remembered else remembered)
    return dialog.exec() == QDialog.DialogCode.Accepted and dialog.folder is not None


def _launched_from() -> Optional[Path]:
    """The working directory, but only when a human typed the command.

    A bundle opened from the Finder has `cwd` of `/` or the home directory and no terminal, and
    treating that as "the project I meant" would gate every launch on a folder nobody chose. A tty
    is the difference between the two, and it is the only signal that does not guess.

    `sys.stdin` itself can be None: the windowed launcher on Windows (`autosound-tcc-gui`, a
    `gui_scripts` entry point) starts the process with no console at all, and asking None for
    `isatty()` was a crash on the first double-click of the shortcut.
    """
    if sys.stdin is None or not sys.stdin.isatty():
        return None
    here = Path.cwd()
    if here == Path.home() or here == Path(here.root):
        return None
    return here
