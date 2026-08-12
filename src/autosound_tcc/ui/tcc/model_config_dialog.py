"""Which of omp's models this user actually has. Ticks, not a text field.

omp reports several hundred models and nobody holds credentials for most of them, so the generator
picker cannot just show the catalogue. TCC will not choose a subset on the user's behalf either —
that would be an app deciding what someone is allowed to run with their own accounts. So the
catalogue is browsable here and the marks are remembered.

The free/paid column is the reason this dialog is worth its own screen rather than being a list of
strings: the whole harness decision was made on cost (`spike/HANDOFF.md` §5-bis), and a model's
price belongs where the model is being chosen.

Claude's models are absent on purpose: they run through the Agent SDK against the user's own CLI,
which is a fixed list this dialog has no say over.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from autosound_tcc.core import model_choices
from autosound_tcc.ui.tcc import i18n


class ModelConfigDialog(QDialog):
    """Pick the omp models to offer in the generator picker. `active` holds the result."""

    def __init__(self, active: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.t("configureModelsTitle"))
        self.active: list[str] = list(active)
        self._error: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        blurb = QLabel(i18n.t("configureModelsBlurb"))
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText(i18n.t("configureModelsFilter"))
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self._list, 1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()

    # ---- contents ----------------------------------------------------------

    def _populate(self) -> None:
        try:
            catalogue = model_choices.omp_catalogue()
        except model_choices.OmpCatalogueError as exc:
            # Marked models stay marked even when the catalogue cannot be read: forgetting a
            # user's choices because a subprocess failed would be a worse answer than an empty
            # list with the reason under it.
            self._error = str(exc)
            self._status.setText(str(exc))
            return
        known = {choice.model for choice in catalogue}
        # A model marked earlier that omp no longer reports still belongs on screen -- otherwise
        # unticking it is impossible and it silently haunts the picker.
        for selector in self.active:
            if selector not in known:
                catalogue.append(
                    model_choices.Choice(harness="omp", model=selector, label=selector)
                )
        for choice in sorted(catalogue, key=lambda c: (c.provider, c.label.lower())):
            label = f"{choice.label}  ·  {choice.model}"
            if choice.free:
                label += f"  ·  {i18n.t('modelFree')}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, choice.model)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if choice.model in self.active else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)
        self._status.setText(i18n.t("configureModelsCount").format(n=self._list.count()))

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self._list.count()):
            item = self._list.item(row)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _accept(self) -> None:
        if self._error is not None:
            # Nothing was listed, so nothing was unticked -- keep what was there rather than
            # writing an empty list the user never chose.
            self.accept()
            return
        self.active = [
            self._list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self._list.count())
            if self._list.item(row).checkState() == Qt.CheckState.Checked
        ]
        self.accept()
