"""«Збережено в DSP…»: the tuner says which name a version went into the device under (hub #198).

What he keeps he saves into a preset of the DSP under a name of his own — `SQ-1`, `FULL-v1`,
`SQ-2` — and that name is what he compares and talks about; the `v_NNN` is the register's. This
form records it through the method (`core/config_writer`): the name, the slot it went into, the
preset's number in the device, and what it is for. The method finds which earlier configuration it
continues, and says so in its answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from autosound_tcc.core import config_writer
from autosound_tcc.state import ledger_line
from autosound_tcc.ui.tcc import i18n


class SaveConfigDialog(QDialog):
    def __init__(self, state_root: Path, version: str, slot: str, slots: list[str],
                 parent=None) -> None:
        super().__init__(parent)
        self._root = Path(state_root)
        self._version = version
        #: What the method said on a save that went through; None until then.
        self.said: Optional[str] = None
        self.setWindowTitle(i18n.t("cfgTitle"))
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        blurb = QLabel(i18n.t("cfgBlurb").format(version=version))
        blurb.setWordWrap(True)
        blurb.setProperty("class", "fb-hint")
        layout.addWidget(blurb)

        form = QFormLayout()
        self._name = QLineEdit()
        self._name.setPlaceholderText("SQ-2")
        standing = ledger_line.config_of(self._root, version)
        if standing is not None:
            self._name.setText(standing[0])
        form.addRow(i18n.t("cfgName"), self._name)
        self._slot = QComboBox()
        for name in slots or [slot]:
            self._slot.addItem(name, name)
        index = self._slot.findData(slot)
        self._slot.setCurrentIndex(max(index, 0))
        self._slot.currentIndexChanged.connect(self._fill_dsp_preset)
        form.addRow(i18n.t("cfgSlot"), self._slot)
        self._dsp_preset = QLineEdit()
        self._dsp_preset.setPlaceholderText("1")
        form.addRow(i18n.t("cfgDspPreset"), self._dsp_preset)
        self._purpose = QLineEdit()
        self._purpose.setPlaceholderText(i18n.t("cfgPurposeHint"))
        if standing is not None and standing[1].get("purpose"):
            self._purpose.setText(str(standing[1]["purpose"]))
        form.addRow(i18n.t("cfgPurpose"), self._purpose)
        layout.addLayout(form)
        self._fill_dsp_preset()

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setProperty("class", "kv-warn")
        self._result.setVisible(False)
        layout.addWidget(self._result)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.t("cfgSave"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("npCancel"))
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _fill_dsp_preset(self, *_args) -> None:
        """The number this slot was last saved to in the device, if it was."""
        known = ledger_line.dsp_preset(self._root, self._slot.currentData() or "")
        if known and not self._dsp_preset.text().strip():
            self._dsp_preset.setText(known)

    def _on_save(self) -> None:
        name = self._name.text().strip()
        if not name:
            self._say(i18n.t("cfgNoName"))
            return
        result = config_writer.save(
            self._root, self._version, name, slot=self._slot.currentData(),
            dsp_preset=self._dsp_preset.text().strip() or None,
            purpose=self._purpose.text().strip() or None)
        if result.saved:
            self.said = result.said
            self.accept()
            return
        self._say(i18n.t("cfgTooOld") if result.too_old else result.said or i18n.t("cfgNoAnswer"))

    def _say(self, text: str) -> None:
        self._result.setText(text)
        self._result.setVisible(True)
