"""What a DSP table's cell reads, and whether it moved since the compared version: the ONE rule
the table's rows, the DSP tree's marks and the status dots all ask, so they never disagree
(tcc#104, tcc#122).

Plain Python, no Qt (tcc#132, W-5's review): it lived in the widget module `detail_pane`, and the
dot — which `detail_pane` imports — reached back into it through an import inside a function.
Both import it from here now.
"""

from __future__ import annotations

from typing import Optional

from autosound_tcc.state.dsp_state import EqBand, GroupRow, ProfileGroup, leg_label

# field token -> column header. Order here is the fallback display order when a group declares a
# field not already covered by a fixed prototype-matching order.
FIELD_COLUMNS: dict[str, str] = {
    "hp": "HPF", "lp": "LPF", "gain_db": "Gain dB", "ta_ms": "Delay ms",
    "polarity": "Pol", "phase_deg": "Phase", "mute": "Mute", "off": "Off",
    "eq_bypass": "EQ Byp", "eq": "EQ",
}


def band_empty(band: EqBand) -> bool:
    """A slot with nothing in it: not drawn (PAS-011) — the gap shows in the band numbers. PC-Tool's
    white slot is one: a frequency and no gain, no Q (finding 71, 5); a BYPASSED band with its
    settings is a band, and is drawn."""
    return ((band.type or "").upper() in ("", "OFF", "NONE") or not band.freq_hz
            or (band.gain_db is None and band.q is None))


def band_count(bands) -> str:
    """«(8/12)»: active of configured, the empty slots not counted (finding 71, 3 and 5)."""
    configured = [b for b in bands if not band_empty(b)]
    if not configured:
        return ""
    return f"({sum(not b.bypass for b in configured)}/{len(configured)})"


def table_fields(group: ProfileGroup) -> list:
    """The controls a tier's table draws as columns, in the tier's own order."""
    return [f for f in group.known_fields if f in FIELD_COLUMNS]


def column_title(field: str) -> str:
    """A control's name as the table's column heads it («Pol», «EQ Byp»)."""
    return FIELD_COLUMNS.get(field, field)


def cell_text(field: str, row: GroupRow) -> str:
    """A value as the table reads it — and as it is compared (`field_changed`)."""
    raw = row.raw
    if field in ("hp", "lp"):
        return leg_label(raw.get(field))
    if field == "gain_db":
        v = raw.get("gain_db")
        return f"{v:+.1f}" if isinstance(v, (int, float)) else "—"
    if field == "ta_ms":
        v = raw.get("ta_ms")
        return f"{v:g}" if isinstance(v, (int, float)) else "—"
    if field == "phase_deg":
        v = raw.get("phase_deg")
        return f"{v:g}°" if isinstance(v, (int, float)) else "—"
    if field == "polarity":
        return raw.get("polarity") or "—"
    if field == "mute":
        return "MUTE" if raw.get("mute") else "—"
    if field == "off":
        return "OFF" if raw.get("off") else "—"
    if field == "eq_bypass":
        return "Y" if raw.get("eq_bypass") else "—"
    if field == "eq":
        # «(active/configured)», as the pickers say it: «15 bands» counted the empty slots.
        count = band_count(row.eq_bands())
        return f"{count} ▸" if count else "—"
    return "—"


def field_changed(field: str, row: GroupRow, old_row: Optional[GroupRow]) -> bool:
    """Whether this value differs from the same channel in the compared version: the ONE rule for
    the table's changed cells and the DSP tree's marks, so the two never disagree (tcc#104,
    finding 113 — the table marked sw's HPF, the tree only its EQ). `old_row` None: that version
    lacks the channel, and every value is new."""
    if old_row is None:
        return True
    # «7 bands ▸» reads the same with a band moved; the bands are what changed.
    bands_moved = field == "eq" and old_row.raw.get("eq") != row.raw.get("eq")
    return cell_text(field, old_row) != cell_text(field, row) or bands_moved


def changed_fields(group: ProfileGroup, row: GroupRow, old_row: Optional[GroupRow]) -> frozenset:
    """Every column of `group`'s table that `field_changed` marks for this channel."""
    return frozenset(f for f in table_fields(group) if field_changed(f, row, old_row))
