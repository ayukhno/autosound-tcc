"""Read a Resonalyze virtual-DSP session and say what this DSP can and cannot be given.

A plan can arrive from outside — someone tunes in Resonalyze's virtual crossover and sends the
session file. It carries per-channel crossovers, gains, delays, polarity and PEQ, which is exactly
the ledger's vocabulary, so the conversion is mechanical. What is NOT mechanical is that the plan
was made against no particular processor: the sample the user brought asks for **LR48 on four
legs**, and a Helix DSP Ultra S offers LR at 12/24/36 only. Rounding that to 36 behind the
person's back would be the worst possible outcome — a tune that looks imported and is not the one
that was sent.

**The maths is the method's, and stays there.** `rew_tool/resonalyze_vc.py` owns both the
conversion and the per-field verdict, and it has a CLI so the same answer is available in a
terminal (the user's instruction, 2026-08-23: the terminal path is the starting mode and the
window wraps the same function). This file renders that answer and refuses on it. It re-derives
nothing: two implementations of "can this processor take this value" is how the window and the
method start disagreeing about a piece of hardware.

Three things in the rendering are load-bearing, and each one is a mistake somebody would make
reading the file by hand (all four warnings came from the skill session, 2026-08-23):

* **`enterable` is three-valued.** `false` is a refusal; `null` is "the profile does not state
  that limit, so nothing was checked" — which must never be painted as a pass. They are rolled up
  once at the bottom rather than repeated per leg, because 53 identical shrugs bury the one
  finding that matters.
* **The dormant edge is live-looking garbage.** `crossoverKind` decides which edge applies; the
  other one still holds values, often a constructor default. The sub in the user's own file
  carries `BW 10 Hz / 24` on an edge that is not in use — read it and you invent a subsonic
  filter nobody set. Shown, greyed, labelled as not live.
* **The scene offset is not a value to apply.** `stereoSceneOffsetMs` / `stereoLevelDifferenceDb`
  are what Resonalyze's Auto balance AIMS for; the result is already inside each leg's own gain
  and delay. Shown as context, never as a number to enter.

Banking the rows is deliberately not here. That is `state/apply.py`'s gate — a tuning decision
with a settings sheet and an attestation behind it — and this dialog stops at the truth: here is
what the plan asks for, here is what your processor will take.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from autosound_tcc.core import config, vendor_loader
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.theme import current_theme


def _esc(text: object) -> str:
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _row_line(row: dict) -> str:
    """One leg's ledger row as the six things a person checks it by."""
    def edge(key: str) -> str:
        band = row.get(key)
        if not isinstance(band, dict):
            return f"{key.upper()} OFF"
        return f"{key.upper()} {band.get('f')} {band.get('type')}{band.get('slope')}"

    bits = [edge("hp"), edge("lp")]
    gain, delay = row.get("gain_db"), row.get("ta_ms")
    if gain is not None:
        bits.append(f"gain {gain:+g} dB")
    if delay is not None:
        bits.append(f"delay {delay:g} ms")
    bits.append(str(row.get("polarity") or "NORM"))
    eq = row.get("eq")
    if isinstance(eq, list):
        bits.append(f"EQ {len(eq)}")
    return " · ".join(bits)


def render_html(result: dict) -> str:
    """The whole answer as one rich-text block.

    A pure function of the converter's result so the rendering can be tested without a window,
    and so the colours are the only thing Qt contributes.
    """
    t = current_theme()
    out = [f'<div style="color:{t.text};">']

    source = result.get("source") or {}
    scene = result.get("scene") or {}
    name = Path(str(source.get("path") or "")).name
    out.append(f'<p><b>{_esc(name)}</b> <span style="color:{t.muted};">'
               f'{_esc(source.get("format"))} v{_esc(source.get("version"))}</span></p>')

    profile = result.get("profile") or {}
    if profile.get("name"):
        out.append(f'<p style="color:{t.muted};">{_esc(i18n.t("riAgainst"))}: '
                   f'{_esc(profile.get("vendor"))} {_esc(profile.get("name"))}</p>')
    else:
        out.append(f'<p style="color:{t.yellow};">{_esc(i18n.t("riNoProfile"))}</p>')

    offset = scene.get("stereo_scene_offset_ms")
    if offset:
        side = scene.get("stereo_near_side") or ""
        cut = scene.get("stereo_near_side_cut_db")
        drive = "RHD" if scene.get("stereo_right_hand_drive") else "LHD"
        out.append(
            f'<p style="color:{t.muted};">{_esc(i18n.t("riScene"))}: {offset:g} ms ({drive})'
            + (f", {cut:g} dB — {_esc(side)}" if cut else "")
            + f'<br>{_esc(i18n.t("riSceneNote"))}</p>'
        )

    for leg in result.get("legs") or []:
        channel = leg.get("channel")
        head = _esc(channel) if channel else (
            f'<span style="color:{t.warn};">{_esc(leg.get("channel_hint") or "?")} — '
            f'{_esc(i18n.t("riUnbound"))}</span>'
        )
        where = f'pair {leg.get("pair")} {leg.get("side")}'
        out.append(f'<p><b>{head}</b> <span style="color:{t.faint};">{_esc(where)}</span><br>'
                   f'<span style="color:{t.muted};">{_esc(leg.get("display_name"))}</span><br>'
                   f'{_esc(_row_line(leg.get("row") or {}))}')

        for check in leg.get("checks") or []:
            if check.get("enterable") is False:
                out.append(
                    f'<br><span style="color:{t.warn};">✗ {_esc(check.get("field"))}: '
                    f'{_esc(check.get("wanted"))} — {_esc(check.get("reason"))}</span>'
                )
        for key, band in (leg.get("dormant") or {}).items():
            out.append(
                f'<br><span style="color:{t.faint};">○ {_esc(key.upper())} '
                f'{_esc(band.get("f"))} {_esc(band.get("type"))}{_esc(band.get("slope"))} — '
                f'{_esc(i18n.t("riDormant"))}</span>'
            )
        for band in leg.get("dropped_eq_bands") or []:
            out.append(
                f'<br><span style="color:{t.faint};">⊘ {_esc(band.get("type"))} '
                f'{_esc(band.get("f"))} Hz {_esc(band.get("gain_db"))} dB — '
                f'{_esc(i18n.t("riDropped"))}</span>'
            )
        if leg.get("peq_preamp_db"):
            out.append(f'<br><span style="color:{t.warn};">✗ preamp '
                       f'{_esc(leg.get("peq_preamp_db"))} dB</span>')
        out.append("</p>")

    gaps = result.get("profile_gaps") or []
    if gaps:
        # Once, at the bottom. A per-leg list of identical shrugs buries the refusals above it.
        items = ", ".join(f'{_esc(gap.get("key"))} ({gap.get("checks")})' for gap in gaps)
        out.append(f'<p style="color:{t.yellow};">{_esc(i18n.t("riNotChecked"))}: {items}</p>')

    out.append("</div>")
    return "".join(out)


class ResonalyzeImportDialog(QDialog):
    """Pick a session file, see what it asks for, and see what this DSP will take.

    The project supplies both halves of the context the way the CLI does: `project.json` binds
    each leg to a channel, `dsp_profile.json` is what the values are checked against. A project
    with neither still converts -- every verdict simply comes back "not checked", which is the
    honest answer and not a silent pass.
    """

    def __init__(self, project_dir: Optional[Path] = None, parent=None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(i18n.t("riTitle"))
        self.setMinimumSize(720, 560)
        self._project_dir = Path(project_dir or config.project_dir())
        self.result: Optional[dict] = None
        self._binders: dict[str, QComboBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        file_row = QHBoxLayout()
        self._file_edit = QLineEdit()
        self._file_edit.setPlaceholderText(i18n.t("riFilePlaceholder"))
        self._file_edit.returnPressed.connect(self.reconvert)
        file_row.addWidget(self._file_edit, stretch=1)
        browse = QPushButton(i18n.t("npBrowse"))
        browse.setProperty("class", "reason-btn")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._on_browse)
        file_row.addWidget(browse)
        layout.addLayout(file_row)

        self._report = QTextEdit()
        self._report.setReadOnly(True)
        layout.addWidget(self._report, stretch=1)

        # Built only when a leg fails to bind -- the skill's `bind_channels` resolves the common
        # case on its own (all seven of the user's legs bound with no help), so this is the dialog
        # built for the MISS, as it was asked to be.
        self._bind_box = QWidget()
        self._bind_form = QFormLayout(self._bind_box)
        self._bind_form.setContentsMargins(0, 0, 0, 0)
        self._bind_box.setVisible(False)
        layout.addWidget(self._bind_box)

        self._verdict = QLabel("")
        self._verdict.setWordWrap(True)
        layout.addWidget(self._verdict)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self._copy_btn = QPushButton(i18n.t("riCopyRows"))
        self._copy_btn.setProperty("class", "reason-btn")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._copy_rows)
        actions.addWidget(self._copy_btn)
        close = QPushButton(i18n.t("riClose"))
        close.setProperty("class", "reason-btn")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        layout.addLayout(actions)

    # ── conversion ────────────────────────────────────────────────────────────────────────

    def _on_browse(self) -> None:
        start = self._file_edit.text().strip() or str(self._project_dir)
        chosen, _ = QFileDialog.getOpenFileName(
            self, i18n.t("riTitle"), start, "Resonalyze session (*.json)"
        )
        if chosen:
            self._file_edit.setText(chosen)
            self.reconvert()

    def mapping(self) -> dict:
        """What the person answered for the legs that did not bind. Explicit always wins."""
        return {
            hint: combo.currentData()
            for hint, combo in self._binders.items()
            if combo.currentData()
        }

    def _on_binding_changed(self, _index: int) -> None:
        """A combo said which channel a leg is. Re-check, but LEAVE THE COMBOS ALONE.

        `_rebuild_binders` takes the combos apart, and this runs from inside one of their own
        signal handlers -- the shape that has cost this app a SIGSEGV before (see
        `ui/tcc/qt_shutdown.py`). The list of legs that needed help does not change when one of
        them is answered, so there is nothing to rebuild anyway, and a person who picks the wrong
        channel can still see the row and change their mind.
        """
        self.reconvert(rebuild=False)

    def reconvert(self, rebuild: bool = True) -> None:
        """Run the method's converter and show what it says. Never raises into the event loop."""
        path = self._file_edit.text().strip()
        if not path:
            return
        try:
            vc = vendor_loader.load_resonalyze_vc()
            profile = self._profile()
            proj = self._project()
            doc = vc.load_session(path)
            self.result = vc.convert(
                doc, profile=profile, proj=proj, mapping=self.mapping(), source_path=path
            )
        except Exception as exc:  # noqa: BLE001 — a bad file is an answer, not a traceback
            self.result = None
            self._report.setHtml("")
            self._say(f"{i18n.t('riFailed')} {type(exc).__name__}: {exc}", warn=True)
            self._copy_btn.setEnabled(False)
            return
        self._report.setHtml(render_html(self.result))
        if rebuild:
            self._rebuild_binders()
        self._say_verdict()

    def _project(self):
        try:
            return vendor_loader.load_project().Project(str(self._project_dir))
        except Exception:  # noqa: BLE001 — no skill, or no project: the legs stay unbound
            return None

    def _profile(self):
        """The project's own profile, exactly as the CLI resolves it -- no bundled fallback.

        A project whose DSP is not the one this plan was aimed at is precisely the case that must
        not be papered over with a profile picked by resemblance.
        """
        path = self._project_dir / "dsp_profile.json"
        if not path.is_file():
            return None
        try:
            return vendor_loader.load_dsp_profile().load_profile(str(path))
        except Exception:  # noqa: BLE001
            return None

    # ── the answer ────────────────────────────────────────────────────────────────────────

    def _rebuild_binders(self) -> None:
        while self._bind_form.count():
            item = self._bind_form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self._binders = {}

        unbound = [leg for leg in (self.result or {}).get("legs", []) if not leg.get("channel")]
        self._bind_box.setVisible(bool(unbound))
        if not unbound:
            return
        codes = self._channel_codes()
        for leg in unbound:
            hint = leg.get("channel_hint") or leg.get("display_name") or ""
            combo = QComboBox()
            combo.setProperty("class", "mini-select")
            combo.addItem(i18n.t("riBindNone"), None)
            for code in codes:
                combo.addItem(code, code)
            combo.currentIndexChanged.connect(self._on_binding_changed)
            self._binders[hint] = combo
            self._bind_form.addRow(QLabel(f"{hint} →"), combo)

    def _channel_codes(self) -> list[str]:
        try:
            data = json.loads((self._project_dir / "project.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        rows = data.get("channels")
        if not isinstance(rows, list):
            return []
        return [str(row.get("code")) for row in rows if isinstance(row, dict) and row.get("code")]

    def _say_verdict(self) -> None:
        summary = (self.result or {}).get("summary") or {}
        blocked, unbound = summary.get("blocked"), summary.get("unbound") or 0
        refused = summary.get("unsupported") or 0
        self._copy_btn.setEnabled(bool(self.result) and not blocked)
        if blocked:
            self._say(i18n.t("riBlocked").format(refused=refused, unbound=unbound), warn=True)
        else:
            self._say(i18n.t("riClear").format(legs=summary.get("legs") or 0), warn=False)

    def _say(self, text: str, *, warn: bool) -> None:
        self._verdict.setText(text)
        self._verdict.setProperty("class", "kv-warn" if warn else "kv-lbl")
        self._verdict.style().unpolish(self._verdict)
        self._verdict.style().polish(self._verdict)

    def _copy_rows(self) -> None:
        """The rows, as JSON, for the terminal to bank through the gate.

        Not a write. Banking is `state/apply.py`'s job -- it validates against HEAD, versions the
        snapshot and produces the settings sheet somebody enters by hand -- and a window that
        wrote ledger state behind that gate would be inventing a second way in.
        """
        rows = {
            leg.get("channel") or leg.get("channel_hint"): leg.get("row")
            for leg in (self.result or {}).get("legs", [])
        }
        QGuiApplication.clipboard().setText(json.dumps(rows, indent=2, ensure_ascii=False))
        self._say(i18n.t("riCopied"), warn=False)
