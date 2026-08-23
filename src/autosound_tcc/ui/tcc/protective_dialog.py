"""What was in the signal path while this round was measured — per channel, written down.

A driver is usually swept behind a protective high-pass so a sweep does not throw a mid or a
tweeter past its excursion limit, and that filter is IN the recording: it rotates phase far past
its own corner, and a junction three times away from it carries about fifty degrees that belong to
the measuring rig rather than to the car. Nothing downstream can tell by looking, because a
protective `LR4 @100` and a designed `LR4 @100` are the same filter.

**A button, not a checkbox** (the user's own correction of a worse design): you ENTER what was in
the chain, and the fact that this round was captured with protection is then derived from the
record. A tick that could be set without the filters behind it would be an assertion that drifts
from the data it claims to describe.

**Three answers, and the middle one is the point.** A channel can be recorded with filters, or
recorded as `OFF` — swept with nothing in the chain, which is an ANSWER — or left alone, which
means nobody said. The de-embed refuses that third state rather than treating it as clean, so this
dialog offers it as a first-class choice ("not recorded") and never fills it in for you.

**This dialog collects; it does not validate.** The skill refuses a leg missing its frequency,
type or slope at write time, and that refusal is shown here verbatim. A UI that quietly fixes what
a gate would have refused trains people to trust the UI over the gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import process_writer, protective
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.theme import mini_combo

#: The ledger's own crossover vocabulary. Not read from the DSP profile on purpose: a protective
#: filter is whatever was in the chain during the sweep — often the processor, sometimes an
#: interface or an amplifier's own high-pass — so the profile's list of what this DSP can be SET
#: to is the wrong constraint here.
TYPES = ("LR", "BW", "BE", "CH")
SLOPES = (6, 12, 18, 24, 30, 36, 42, 48)

#: What a channel row says about itself. Three states, because there are three answers.
STATE_UNSET = "unset"
STATE_OFF = "off"
STATE_FILTER = "filter"


class _ChannelRow:
    """One channel's answer, and the widgets that collect it."""

    def __init__(self, code: str, legs, grid: QGridLayout, row: int) -> None:
        self.code = code
        self.original = legs

        name = QLabel(code)
        name.setProperty("class", "kv-val")
        grid.addWidget(name, row, 0)

        self.state = mini_combo()
        self.state.addItem(i18n.t("protUnset"), STATE_UNSET)
        self.state.addItem(i18n.t("protOff"), STATE_OFF)
        self.state.addItem(i18n.t("protFilter"), STATE_FILTER)
        self.state.currentIndexChanged.connect(self._sync)
        grid.addWidget(self.state, row, 1)

        self.hp_f, self.hp_type, self.hp_slope = self._leg_widgets(grid, row, 2, "protHp")
        self.lp_f, self.lp_type, self.lp_slope = self._leg_widgets(grid, row, 5, "protLp")

        self._fill_from(legs)
        self._sync()

    def _leg_widgets(self, grid: QGridLayout, row: int, col: int, label_key: str):
        freq = QLineEdit()
        freq.setPlaceholderText(i18n.t(label_key))
        freq.setMaximumWidth(90)
        grid.addWidget(freq, row, col)
        kind = mini_combo()
        kind.addItem("—", "")
        for name in TYPES:
            kind.addItem(name, name)
        grid.addWidget(kind, row, col + 1)
        slope = mini_combo()
        slope.addItem("—", "")
        for value in SLOPES:
            slope.addItem(str(value), value)
        grid.addWidget(slope, row, col + 2)
        return freq, kind, slope

    def _fill_from(self, legs) -> None:
        """Show what the round already says about this channel, unchanged."""
        if legs is None:
            self.state.setCurrentIndex(self.state.findData(STATE_UNSET))
            return
        live = {kind: leg for kind, leg in legs.items() if isinstance(leg, dict)}
        if not live:
            self.state.setCurrentIndex(self.state.findData(STATE_OFF))
            return
        self.state.setCurrentIndex(self.state.findData(STATE_FILTER))
        for kind, (freq, typ, slope) in (
            ("hp", (self.hp_f, self.hp_type, self.hp_slope)),
            ("lp", (self.lp_f, self.lp_type, self.lp_slope)),
        ):
            leg = live.get(kind)
            if not leg:
                continue
            value = leg.get("f")
            freq.setText(f"{value:g}" if isinstance(value, (int, float)) else str(value or ""))
            typ.setCurrentIndex(max(0, typ.findData(leg.get("type"))))
            slope.setCurrentIndex(max(0, slope.findData(leg.get("slope"))))

    def _sync(self) -> None:
        editing = self.state.currentData() == STATE_FILTER
        for widget in (self.hp_f, self.hp_type, self.hp_slope,
                       self.lp_f, self.lp_type, self.lp_slope):
            widget.setEnabled(editing)

    def _leg(self, freq: QLineEdit, typ: QComboBox, slope: QComboBox):
        """One leg as the ledger states it, or None when the row is empty.

        Empty is passed through as absent rather than as a refusal: a channel with only a
        high-pass is ordinary. A HALF-filled leg is not repaired here — it goes to the writer as
        typed, and the writer's refusal is what the person reads.
        """
        text = freq.text().strip()
        if not text and not typ.currentData() and not slope.currentData():
            return None
        try:
            value = float(text.replace(",", "."))
        except ValueError:
            value = text  # the gate says what is wrong with it, in its own words
        return {"f": value, "type": typ.currentData() or "", "slope": slope.currentData() or ""}

    def answer(self):
        """`"OFF"`, a `{hp, lp}` dict, or None for "nobody said" — which writes nothing at all."""
        state = self.state.currentData()
        if state == STATE_UNSET:
            return None
        if state == STATE_OFF:
            return "OFF"
        legs = {}
        hp, lp = (self._leg(self.hp_f, self.hp_type, self.hp_slope),
                  self._leg(self.lp_f, self.lp_type, self.lp_slope))
        if hp:
            legs["hp"] = hp
        if lp:
            legs["lp"] = lp
        return legs or "OFF"


class ProtectiveDialog(QDialog):
    """The round's protective record, entered per channel.

    Opens on what the round already says, so re-opening it is a review rather than a blank form.
    A channel nobody has answered for stays unanswered unless somebody chooses one of the other
    two — closing this dialog does not turn silence into `OFF`.
    """

    def __init__(self, project_dir: Path, channels, parent=None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(i18n.t("protTitle"))
        self.setMinimumWidth(640)
        self._project_dir = Path(project_dir)
        self._record = protective.record_for(self._project_dir)
        self.written: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        head = QLabel(
            i18n.t("protRound").format(series=self._record.get("series"))
            if self._record else i18n.t("protNoRound")
        )
        head.setWordWrap(True)
        head.setProperty("class", "kv-lbl" if self._record else "kv-warn")
        layout.addWidget(head)

        why = QLabel(i18n.t("protWhy"))
        why.setWordWrap(True)
        why.setProperty("class", "kv-lbl")
        layout.addWidget(why)

        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        self._rows = [
            _ChannelRow(code, protective.legs_of(self._record, code) if self._record else None,
                        grid, index)
            for index, code in enumerate(channels)
        ]
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(holder)
        layout.addWidget(scroll, stretch=1)

        self._problem = QLabel("")
        self._problem.setWordWrap(True)
        self._problem.setProperty("class", "kv-warn")
        self._problem.setVisible(False)
        layout.addWidget(self._problem)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton(i18n.t("npCancel"))
        cancel.setProperty("class", "reason-btn")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self._save = QPushButton(i18n.t("protSave"))
        self._save.setProperty("class", "composer-send-ok")
        self._save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save.setEnabled(bool(self._record))
        self._save.clicked.connect(self._on_save)
        actions.addWidget(self._save)
        layout.addLayout(actions)

    def _on_save(self) -> None:
        """Write every answered channel, and stop at the first refusal with its own words.

        Stops rather than continues: the refusals are about a leg somebody typed, and writing the
        rest while one is wrong leaves a record that is half this dialog and half the last one.
        """
        self.written = []
        for row in self._rows:
            answer = row.answer()
            if answer is None:
                continue  # nobody said, and that stays said by nobody
            try:
                process_writer.set_protective(self._project_dir, row.code, answer)
            except Exception as exc:  # noqa: BLE001 — the gate's words, not ours
                self._problem.setText(
                    i18n.t("protRefused").format(channel=row.code, why=_last_line(str(exc)))
                )
                self._problem.setVisible(True)
                return
            self.written.append(row.code)
        self.accept()


def _last_line(text: str) -> str:
    """The gate's sentence, without the traceback the CLI wraps it in."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if not line.startswith(("File \"", "Traceback", "  ")):
            return line
    return lines[-1] if lines else ""


def channel_codes(view) -> list[str]:
    """Every channel of the rig, outputs first, in the order the panels show them."""
    codes: list[str] = []
    for group in getattr(view, "groups", ()) or ():
        for row in group.rows_visible():
            if row.name not in codes:
                codes.append(row.name)
    return codes


def open_for(project_dir: Path, view, parent=None) -> Optional[ProtectiveDialog]:
    """Build the dialog for the current rig, or None when there are no channels to ask about."""
    codes = channel_codes(view)
    if not codes:
        return None
    return ProtectiveDialog(project_dir, codes, parent=parent)
