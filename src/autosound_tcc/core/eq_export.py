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
    """What the exporter produced, and what it is.

    `format_name` is shown to the person on purpose: a clipboard whose format cannot be named is
    a trap -- the difference between "paste this into PC-Tool" and "paste this into a text file
    and read it yourself" is the whole value of the copy.
    """

    text: str
    format_name: str
    #: Bands the format could not carry, in the method's own words. Empty is the common case.
    left_out: tuple[str, ...] = ()


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


def format_bank(eq_rows) -> Optional[Bank]:
    """The bank for one channel, or None when it cannot be produced.

    None covers every "not today" in one answer -- no skill, no exporter, no profile, no format
    for this processor -- because the window says the same thing in all of them: there is no
    format for this DSP yet. What it must never do is return something plausible.
    """
    if not eq_rows:
        return None
    profile = _profile()
    if profile is None:
        return None
    try:
        module = vendor_loader.load(_MODULE)
        result = module.format_for(profile, list(eq_rows))
    except Exception:  # noqa: BLE001 — a missing exporter is a state, not a crash
        return None
    if result is None:
        return None
    text, format_name = result[0], result[1]
    left_out = tuple(result[2]) if len(result) > 2 and result[2] else ()
    return Bank(text=text, format_name=str(format_name), left_out=left_out) if text else None
