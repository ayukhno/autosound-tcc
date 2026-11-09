"""«Checked in the DSP» and «in the DSP now» (#251), said on the «Порівняти з» rows and the header.

The Arbiter's rule (2026-11-09): where TCC can read a DSP's save file (today only the Helix's), a
version is checked when every channel row is entered and the file is on record. On any other DSP the
rule is the person's explicit word, and the ledger holds no such fact per version, so no mark is
shown there. Reading the version files is `ledger_line`'s; this module says what they mean on screen.

The mark is about one version and the file it was checked against, never about what the DSP holds
now. That is the method's `slots[slot].loaded`, a dated claim told apart at a glance: the tick is the
version's own fact, the words «in the DSP» are this one. No `loaded` means unknown, never HEAD.
"""

from __future__ import annotations

import html
from typing import NamedTuple, Optional

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QComboBox

from autosound_tcc.state import ledger_line
from autosound_tcc.state.ledger_line import Loaded, SavedFile
from autosound_tcc.ui.tcc import i18n
from autosound_tcc.ui.tcc.theme import current_theme


def is_helix(vendor, name) -> bool:
    """A Helix-family DSP, told by vendor and name together: a profile may say only the vendor."""
    said = f"{vendor or ''} {name or ''}".lower()
    return "audiotec" in said or "helix" in said


def reads_save_file(profile: dict) -> bool:
    """Whether TCC can read this DSP's save file: today only the Helix's (the Arbiter, 2026-11-09)."""
    prof = profile.get("dsp_profile", profile) if isinstance(profile, dict) else {}
    return isinstance(prof, dict) and is_helix(prof.get("vendor"), prof.get("name"))


def _keys(preset: str, own: list, others: list) -> list[tuple[str, str, str]]:
    """`(preset the version is read from, version, its key in the list)` for every row offered."""
    rows = [(preset, version, version) for version in own]
    for _other, items in others or ():
        rows.extend((*key.split("/", 1), key) for key, _label in items)
    return rows


class RowMark(NamedTuple):
    """What one row carries: the files that make it checked, and the claims that it is in the DSP."""

    files: tuple[SavedFile, ...] = ()
    loaded: tuple[Loaded, ...] = ()


def marks(root, preset: str, own: list, others: list, profile: dict) -> dict[str, RowMark]:
    """`{compare key: its mark}` for the rows that carry one, as plain data: the text is made when
    a row is filled, so a list filled in one language stays in it until the next load refills it.
    The tick needs a DSP whose file TCC reads; the claim is the method's on any DSP."""
    every = ledger_line.all_saved_files(root, preset) if reads_save_file(profile) else None
    claims = ledger_line.loaded_by_version(root)
    found = {}
    for of, version, key in _keys(preset, own, others):
        files = () if every is None else ledger_line.checked_files(root, of, version, every)
        if files or version in claims:
            found[key] = RowMark(files, claims.get(version, ()))
    return found


def _file_line(file: SavedFile) -> str:
    parts = [html.escape(file.name)]
    if file.md5:
        parts.append(i18n.t("dspCheckedMd5").format(md5=file.md5 + ("" if len(file.md5) == 32 else "…")))
    if file.saved:
        parts.append(i18n.t("dspCheckedSaved").format(when=file.saved))
    elif file.recorded:
        parts.append(i18n.t("dspCheckedRecorded").format(when=file.recorded))
    return " · ".join(parts)


def tip(files: tuple[SavedFile, ...]) -> str:
    """The hover: what the mark says and does not, then each file with the same content."""
    lines = [html.escape(i18n.t("dspCheckedTip"))]
    if len(files) > 1:
        lines.append(html.escape(i18n.t("dspCheckedSameFiles")))
    lines.extend(_file_line(file) for file in files)
    return "<br>".join(lines)


def _mark_icon() -> QIcon:
    """A green tick, drawn inside a row of the list."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(current_theme().ok), 2.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawPolyline(QPolygonF([QPointF(3.0, 8.5), QPointF(6.5, 12.0), QPointF(13.0, 4.5)]))
    painter.end()
    return QIcon(pixmap)


def _loaded_sentence(claim: Loaded) -> str:
    return i18n.t("dspLoadedTip").format(preset=claim.slot, version=claim.version, since=claim.since,
                                         source=claim.source)


def mark_row(combo: QComboBox, index: int, mark: Optional[RowMark]) -> None:
    """The tick and/or the words «in the DSP» on one row, and the hover saying each; a row with
    neither gets nothing."""
    if mark is None:
        return
    said = []
    if mark.files:
        combo.setItemIcon(index, _mark_icon())
        said.append(tip(mark.files))
    if mark.loaded:
        combo.setItemText(index, i18n.t("dspLoadedRow").format(label=combo.itemText(index)))
        said.extend(html.escape(_loaded_sentence(claim)) for claim in mark.loaded)
    combo.setItemData(index, "<br><br>".join(said), Qt.ItemDataRole.ToolTipRole)


def now_in_dsp(root, view, slot: Optional[str], head: str) -> tuple[str, str]:
    """`(the header's text, what its hover adds)` about what the DSP holds now: the slot the window
    loaded, whatever `view`'s own file says it was made for. `head` is the header's text for HEAD;
    with no believable `loaded` it stays as it is and the hover says that nothing is on record."""
    claim = ledger_line.loaded_in_dsp(root, slot if isinstance(slot, str) else view.preset)
    if claim is None:
        return head, i18n.t("dspLoadedUnknown")
    at_head = claim.version == (getattr(view, "file_version", None) or view.version)
    return (i18n.t("dspLoadedSub" if at_head else "dspLoadedSubOther").format(head=head, version=claim.version),
            _loaded_sentence(claim))


def header(root, view, profile: dict, base_tip: str,
           loaded: Optional[str] = None, now: str = "") -> tuple[Optional[str], str]:
    """The dot before HEAD's name and its hover: `checked` where the mark stands, otherwise what
    the dot always said — yellow while anything is proposed, green once all of it is entered.

    Asked of `view`, HEAD: the version only looked at has its own row in the list. `view.preset` may
    be null on an old layout: `loaded` is the slot the window loaded it as, and with neither there
    is no mark, never a raise. `now` is `now_in_dsp`'s sentence, plain text, added to the hover."""
    state = view.state
    dot = None if state is None else ("wait" if state == "proposed" else "done")
    said = f"{html.escape(base_tip)}<br><br>{html.escape(now)}" if now else base_tip
    preset = view.preset if isinstance(view.preset, str) else loaded
    if dot != "done" or not reads_save_file(profile) or not isinstance(preset, str):
        return dot, said
    version = getattr(view, "file_version", None) or view.version
    files = ledger_line.checked_files(root, preset, version)
    if not files:
        return dot, said
    return "checked", f"{said if now else html.escape(base_tip)}<br><br>{tip(files)}"
