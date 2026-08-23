"""One channel's EQ bank, on the clipboard, in the format that processor takes.

The formats live in the METHOD and nowhere else. That is the user's own instruction ("це повинно
бути в скілі") and it is the same boundary the rest of this app keeps: a format is knowledge about
a piece of hardware, not rendering. `rew_tool/atf_eq.py` already writes the Audiotec-Fischer
30-band bank Helix PC-Tool imports; whatever exists for the next processor will live beside it,
and where nothing exists the user says he will supply it rather than have anyone invent one.

So this module is an adapter and nothing more: it finds the method's exporter, hands it the
project's profile and the ledger's own EQ rows, and passes back what came out. It maps no band
types, pads no banks and knows no vendor. If a band cannot be carried by a format -- an all-pass
in an EQ-only file, say -- what happens to it is the method's decision to make and to report; this
module only makes sure the answer reaches the window.

`available()` is what the UI asks before offering the copy at all. A button that copies nothing,
or copies something nobody can identify, is worse than no button.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from autosound_tcc.core import config, vendor_loader

#: The method's module, if this checkout has one. Absent until the exporter lands there; the UI
#: hides the copy rather than offering a format it cannot produce.
_MODULE = "eq_export.py"


@dataclass(frozen=True)
class Bank:
    """What the exporter produced, and everything about it a person needs told.

    `format_name` is shown on purpose: a clipboard whose format cannot be named is a trap -- the
    difference between "paste this into PC-Tool" and "paste this into a text file and read it
    yourself" is the whole value of the copy. `bank_size` matters for the same reason from the
    other side: a fixed-size bank is a FORM, and its empty rows overwrite whatever those slots
    held before.
    """

    text: str
    format_name: str
    #: Bands actually written.
    written: int = 0
    #: Crossover legs written with them. Zero for a bank that has no room for crossovers.
    crossovers: int = 0
    #: The block's fixed size, when it has one.
    bank_size: Optional[int] = None
    #: What was left out, already phrased -- "item — why". Never silent, never a bare list.
    left_out: tuple[str, ...] = ()
    #: Things the exporter wants said out loud.
    notes: tuple[str, ...] = ()


def available() -> bool:
    """Whether this installation can export a bank at all."""
    try:
        vendor_loader.load(_MODULE)
    except Exception:  # noqa: BLE001 — no skill, or a skill without the exporter yet
        return False
    return True


def _profile() -> Optional[dict]:
    path = config.dsp_profile_path()
    if not path.is_file():
        return None
    try:
        return vendor_loader.load_dsp_profile().load_profile(str(path))
    except Exception:  # noqa: BLE001
        return None


def _leg_label(value) -> str:
    """`{"hp": {"f": 350.0, "type": "LR", "slope": 36}}` -> `HP 350 LR36`.

    The method reports a left-out crossover as the ledger structure it refused to carry, which is
    the right thing for it to hand over and the wrong thing to show a person. Turning a structure
    into a label is this side's job -- the same label the tables already use, spelled here rather
    than imported so a core module keeps its one-way dependency on `config` alone.
    """
    if not isinstance(value, dict):
        return str(value)
    parts = []
    for key in ("hp", "lp"):
        leg = value.get(key)
        if isinstance(leg, dict) and leg.get("f") is not None:
            freq = leg["f"]
            freq = f"{freq:g}" if isinstance(freq, (int, float)) else str(freq)
            parts.append(f"{key.upper()} {freq} {leg.get('type', '')}{leg.get('slope', '')}".strip())
    return " · ".join(parts) if parts else str(value)


def _said(entry) -> str:
    """One `left_out` entry as a sentence. The method phrases the reason; this only joins it."""
    if isinstance(entry, dict):
        item, why = _leg_label(entry.get("item")), entry.get("why")
        return f"{item} — {why}" if item and why else str(item or why or "")
    return str(entry)


def format_bank(
    eq_rows,
    *,
    crossovers=None,
    group_id: str = "physical_outputs",
    channel: Optional[str] = None,
) -> Optional[Bank]:
    """One channel for the clipboard, or None when it cannot be produced.

    None covers every "not today" in one answer -- no skill, no exporter, no profile -- because
    the window says the same thing in all of them. What it must never do is return something
    plausible.

    `crossovers` is the ledger's own `{"hp": …, "lp": …}` for this channel and `group_id` is the
    tier it sits in. Both are passed rather than worked out here: whether a crossover belongs in
    the block at all depends on the format AND on what the profile says that tier has, and both
    of those are the method's to decide.
    """
    # A dict of empty legs is not a crossover. `{"hp": None, "lp": None}` is what a virtual
    # channel hands over, and it is truthy -- which would have produced a bank of thirty empty
    # rows for a channel that has nothing to export, offered from the right-click menu as if it
    # did.
    live_legs = [leg for leg in (crossovers or {}).values() if isinstance(leg, dict)]
    if not eq_rows and not live_legs:
        return None
    profile = _profile()
    if profile is None:
        return None
    try:
        module = vendor_loader.load(_MODULE)
        export = module.export_eq(
            profile, list(eq_rows or []),
            crossovers=crossovers, group_id=group_id, channel=channel,
        )
    except Exception:  # noqa: BLE001 — a missing exporter is a state, not a crash
        return None
    if export is None or not getattr(export, "text", ""):
        return None
    return Bank(
        text=export.text,
        format_name=str(export.format_name),
        written=int(getattr(export, "written", 0) or 0),
        crossovers=int(getattr(export, "crossovers", 0) or 0),
        bank_size=getattr(export, "bank_size", None),
        left_out=tuple(_said(item) for item in (getattr(export, "left_out", None) or ())),
        notes=tuple(str(note) for note in (getattr(export, "notes", None) or ())),
    )
