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

**Two answers, and empty is one of them** (user, 2026-09-06). A row with no filter in it says
there was no PROTECTIVE filter, and that is an instruction to the analysis: process this curve as
measured, take nothing out. Whether a working crossover was in the chain is a different question
and not this record's — it belongs there and must not be removed either way. A row with a filter
says: take this one out before reading the curve.

There used to be a third state here, a per-row "not recorded", and it was the leftover of a reading
`core/protective.py` had already corrected: the record is an INSTRUCTION, not a description of the
chain. A flag whose absence and whose "off" mean the same thing to every reader downstream is a
question that costs the person a click per channel and buys nothing.

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
from autosound_tcc.ui.tcc.rounded_tooltip import attach as attach_tip
from autosound_tcc.ui.tcc.theme import mini_combo

#: The ledger's own crossover vocabulary. Not read from the DSP profile on purpose: a protective
#: filter is whatever was in the chain during the sweep — often the processor, sometimes an
#: interface or an amplifier's own high-pass — so the profile's list of what this DSP can be SET
#: to is the wrong constraint here.
TYPES = ("LR", "BW", "BE", "CH")
SLOPES = (6, 12, 18, 24, 30, 36, 42, 48)

#: What the one-press button fills in. Linkwitz-Riley 24 dB/oct: the protective filter nearly
#: every measuring chain actually carries, and the one a tuner would otherwise pick out of two
#: dropdowns for every channel of every round.
QUICK_TYPE, QUICK_SLOPE = "LR", 24
QUICK_LABEL = f"{QUICK_TYPE}{QUICK_SLOPE}"


class _ChannelRow:
    """One channel's answer, and the widgets that collect it."""

    def __init__(self, code: str, legs, grid: QGridLayout, row: int) -> None:
        self.code = code
        self.original = legs

        name = QLabel(code)
        name.setProperty("class", "kv-val")
        grid.addWidget(name, row, 0)

        self.hp_f, self.hp_type, self.hp_slope, self.hp_quick = self._leg_widgets(
            grid, row, 1, "protHp")
        self.lp_f, self.lp_type, self.lp_slope, self.lp_quick = self._leg_widgets(
            grid, row, 5, "protLp")

        self._fill_from(legs)

    def _leg_widgets(self, grid: QGridLayout, row: int, col: int, label_key: str):
        freq = QLineEdit()
        freq.setPlaceholderText(i18n.t(label_key))
        # Wide enough for the placeholder that names it ("ФВЧ Гц" was reaching the user as
        # "ФВЧ …"), and no wider: eight rows of these share the dialog with two combos each.
        freq.setMinimumWidth(freq.fontMetrics().horizontalAdvance(i18n.t(label_key)) + 20)
        freq.setMaximumWidth(120)
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
        # The one press that covers the ordinary case (user, 2026-09-02: "додати маленьку кнопочку
        # по нажаттю якої фільтр стає LR24"). Two combos are the honest surface — a protective
        # filter can be anything that was in the chain — but nearly every one of them is an LR24,
        # and choosing it twice per channel is a toll on the common path.
        #
        # It also removes a real trap: the skill's writer refuses a leg with a frequency and no
        # type or slope, so "type 80 and press Record" is a refusal today. This is the fix for it.
        quick = QPushButton(QUICK_LABEL)
        quick.setProperty("class", "reason-btn")
        quick.setCursor(Qt.CursorShape.PointingHandCursor)
        # Measured off the text, not a fixed 46 px: Qt's `sizeHint` for a QPushButton leaves out
        # the horizontal padding the stylesheet adds (`.reason-btn` is `padding: 4px 12px`), so a
        # hard width cuts the label — "LR24" reached the user as ".R24" (2026-09-06), the same way
        # "Protection" once reached them as "Protectior" (`measurement_panel._fit_fact_buttons`).
        # A minimum rather than a fixed size, so a zoomed-in font still fits.
        quick.setMinimumWidth(quick.fontMetrics().horizontalAdvance(QUICK_LABEL) + 34)
        attach_tip(quick, i18n.t("protQuickTip"))
        quick.clicked.connect(lambda: self._quick_fill(kind, slope))
        grid.addWidget(quick, row, col + 3)
        return freq, kind, slope, quick

    def _quick_fill(self, kind: QComboBox, slope: QComboBox) -> None:
        """LR24 into this leg — the type and slope nearly every protective filter actually is."""
        kind.setCurrentIndex(max(0, kind.findData(QUICK_TYPE)))
        slope.setCurrentIndex(max(0, slope.findData(QUICK_SLOPE)))

    def _fill_from(self, legs) -> None:
        """Show what the round already says about this channel, unchanged.

        `None` (nothing recorded) and `"OFF"` (recorded as no protective filter) both come up as an
        empty row, because they are the same instruction to the analysis — see the module
        docstring and `core/protective.py`.
        """
        live = {kind: leg for kind, leg in (legs or {}).items() if isinstance(leg, dict)} \
            if isinstance(legs, dict) else {}
        if not live:
            return
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
        """`"OFF"` for an empty row, or a `{hp, lp}` dict for a row with filters in it.

        Never "nobody said": an empty row IS the answer "no protective filter here, read the curve
        as measured" (user, 2026-09-06). Every channel of the pass is therefore written, which is
        also what makes a baseline round's record complete — the one case the method still asks a
        person about (`core/protective.should_de_embed`, the `"check"` answer).
        """
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
    Record writes EVERY row of the pass: a row with filters as those filters, an empty row as
    `"OFF"` — which is the same instruction to the analysis, spelled out. Cancel writes nothing.
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


def project_channel_codes(project_dir: Optional[Path] = None) -> list[str]:
    """Every channel `project.json` names, in file order, minus the empty slots.

    Channel IDENTITY lives in `project.json` and tunable state lives in the ledger (SCR-001), so
    this is the list that exists from intake onwards — before a single snapshot has been written.
    `hidden` is a slot with no driver assigned: nothing was in its chain, because there is no
    chain.
    """
    from autosound_tcc.state import project_view

    try:
        entries = project_view.load_channels(project_dir).values()
    except Exception:  # noqa: BLE001 — an unreadable project is "no channels", not a crash
        return []
    codes: list[str] = []
    for entry in entries:
        code = str(entry.get("code") or "")
        # The map is keyed by id, code and every previous name, so one channel arrives up to three
        # times; `code` is the identity and dedupes them.
        if code and code not in codes and not entry.get("hidden"):
            codes.append(code)
    return codes


def channel_codes(view, project_dir: Optional[Path] = None) -> list[str]:
    """Every channel of the rig: the loaded view's order first, then whatever it left out.

    The view WAS the only source, and that is F-041 — the button was dead in exactly the state it
    exists for. A view is a ledger snapshot shaped by the profile, and phase 0 is before any
    snapshot: `main_window` only draws a rig without one when `project.json` gives a channel a
    `tier`, which today it does for spare slots alone, so on a project that is being measured for
    the first time `_view` is `None`. Empty list, no dialog, and the refusal went to a strip at
    the top of the window while the button is at the bottom of the right column — which is what
    "нічого не відбувається" was (user, Windows, 2026-09-01).

    The view stays FIRST because it carries the order the panels show and the rule about what is
    switched off. `project.json` then adds what it did not have: on a tuned project usually
    nothing, on a fresh one everything, and in between the channels no ledger row has met yet.
    """
    codes: list[str] = []
    for group in getattr(view, "groups", ()) or ():
        for row in group.rows_visible():
            if row.name not in codes:
                codes.append(row.name)
    for code in project_channel_codes(project_dir):
        if code not in codes:
            codes.append(code)
    return codes


def round_channel_codes(project_dir: Optional[Path] = None) -> list[str]:
    """The channels the open capture round is actually about, in the order it expects them.

    This is what the button opens on now that the import table is where a protective filter is
    ENTERED (`docs/CAPTURE-IMPORT-PLAN.md`): the dialog's job is reviewing and correcting what was
    written, and the record belongs to a round. Showing the whole rig here would offer rows for
    channels this pass never touched.
    """
    from autosound_tcc.core import capture_import
    from autosound_tcc.state import process_view

    round_ = process_view.capture_round(project_dir) or {}
    titles = list(round_.get("expected") or []) + list((round_.get("taken") or {}).keys())
    codes: list[str] = []
    for title in titles:
        code = capture_import.channel_from_title(title, project_dir)
        if code and code not in codes:
            codes.append(code)
    return codes


def open_for(project_dir: Path, view, parent=None) -> Optional[ProtectiveDialog]:
    """Build the dialog over the open round's channels, or the whole rig when there is no round.

    The fallback is not a formality: a project with no round open is exactly where somebody goes
    to READ what a past pass recorded, and offering nothing there would be the F-041 symptom
    again — a button that answers a press with nothing.
    """
    codes = round_channel_codes(project_dir) or channel_codes(view, project_dir)
    if not codes:
        return None
    return ProtectiveDialog(project_dir, codes, parent=parent)
