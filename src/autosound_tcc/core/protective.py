"""What was in the signal path while measuring, and taking it back out of the curve.

A driver is usually swept behind a protective high-pass so the sweep does not throw a mid or a
tweeter past its excursion limit. That filter is IN the recording, and nothing downstream can tell
by looking: a protective `LR4 @100` and a designed `LR4 @100` are the same filter. It is a PHASE
problem rather than a level one — the method measured the same junction at **−49°** with the
protection in the chain and **+3°** with it removed, which is the difference between "fix this" and
"leave it alone".

**The maths is the method's** (`rew_tool/protective.py`) and stays there, like every other number
in this app: this module finds it, hands it a curve, and passes back what came out. What lives here
is the two things a window needs and a library cannot answer:

* **whether the correction can run at all** on this installation (`available()`), because a toggle
  that produces an exception is worse than one that is not offered;
* **turning a measurement into what the maths takes and back**: REW gives magnitude in dB and phase
  in degrees, the correction works on a complex response.

**What the record IS, corrected 2026-09-02.** This module used to say a channel with no record was
an unanswered question, and that `de_embed` refuses it because a correction over an unknown chain
produces data that looks corrected. That was our reading, not the method's, and it was wrong at the
root: it treated the record as a DESCRIPTION of the measuring chain. There is nearly always
something in that chain — the DSP's own working crossovers, which belong there and must not be
taken out — so "no record" cannot mean "nothing was in it".

The record is an INSTRUCTION to the analysis. Empty: process the curve as measured, take nothing
out. Filled: take these out first. The method already says exactly this, in
`rew_tool/protective.should_de_embed`, whose default answer is `("no", ...)` — in its own words,
"a working capture: it measured the system as configured, so whatever filters were in it belong
there. This is the DEFAULT and it is an answer, not a shrug." `de_embed` does raise on `None`, but
its own message says the caller should have asked `should_de_embed` first.

The one case the method still wants a person for is `("check", ...)`: a BASELINE capture — taken
before any crossover was designed — carrying no record. Filters in force during a baseline sweep
are protection almost by definition, and that is the single place a forgotten flag is recoverable.

⚠️ **Not for verifying a finished tune.** There the filter is supposed to be in the chain, and
removing it measures something nobody configured. De-embedding belongs to reading a driver's own
behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from autosound_tcc.core import vendor_loader

_MODULE = "protective.py"


class ProtectiveUnavailable(RuntimeError):
    """The correction cannot run here — no skill, no module, or no scipy."""


@dataclass(frozen=True)
class Corrected:
    """A de-embedded curve and everything about it a plot has to say out loud.

    `capped_below_hz` / `capped_above_hz` bound the region where the correction was deliberately
    NOT completed: below a protective corner the filter's response goes to zero, so dividing by it
    would lift the noise floor with the signal. The method caps the boost at 40 dB and says where;
    inside that region the phase is not the driver's and must not be read as if it were. A plot
    that draws it without marking it is the same trap as a clipboard with no format name.
    """

    magnitude_db: Any
    phase_deg: Any
    applied: tuple[str, ...] = ()
    capped_below_hz: Optional[float] = None
    capped_above_hz: Optional[float] = None
    capped_bins: int = 0
    note: str = ""

    @property
    def changed(self) -> bool:
        """Did anything actually come out of the chain? `"OFF"` records answer honestly: no."""
        return bool(self.applied)


def _module():
    try:
        return vendor_loader.load(_MODULE)
    except Exception as exc:  # noqa: BLE001 — no skill, or a skill that predates the module
        raise ProtectiveUnavailable(str(exc)) from exc


def available() -> bool:
    """Can this installation take a protective filter out of a curve?

    Two ways it cannot, and they need different sentences from a UI, which is why `reason()`
    exists beside this: the method's module may be missing (an old pin), or scipy may be — the
    protective response is a crossover, and `dsp_math.xo_response` is the method's one scipy
    caller. The skill's own `requirements.txt` asks for scipy, but the installer puts it in the
    system python while `uv tool install` gives TCC its own environment.
    """
    return reason() == ""


def reason() -> str:
    """Why the correction cannot run, or "" when it can. Phrased for a person, not a log."""
    try:
        module = _module()
    except ProtectiveUnavailable as exc:
        return f"the method's protective module is not in this checkout: {exc}"
    try:
        import numpy  # noqa: F401
        from scipy import signal  # noqa: F401
    except ImportError:
        return (
            "taking a protective filter out of a curve needs scipy, and this installation does "
            "not have it: uv tool install --upgrade 'autosound-tcc[gui] @ "
            "git+https://github.com/ayukhno/autosound-tcc'"
        )
    return "" if hasattr(module, "de_embed") else "this skill's protective module has no de_embed"


def record_for(project_dir=None) -> Optional[dict]:
    """The open capture round's protective record, read through the skill's own module.

    A READ, so it happens in-process, like every other process read here -- writes are the ones
    that go out through the CLI so there is one implementation of "record a move" in the world.

    `None` has two causes and the caller must not flatten them into one: no round is open, or the
    skill is not installed. Neither means "there was no protection", and the window says so rather
    than defaulting to clean.
    """
    from autosound_tcc.core import config, vendor_loader as loader

    project = Path(project_dir or config.project_dir())
    try:
        process = loader.load_process()
    except Exception:  # noqa: BLE001 — no skill: nothing knows what was in the chain
        return None
    try:
        return process.Process(str(project / "process")).protective_record()
    except Exception:  # noqa: BLE001 — no process yet, or a version without the record
        return None


def default_corrected(record: Optional[dict]) -> Optional[bool]:
    """Should the plot open corrected, as the ROUND itself decides?

    The rule is the method's, and it is readable rather than inferred: a round carries the `phase`
    it belongs to and the ledger `version` it was taken against.

    * phase 0 or 1 -- reading a driver's own behaviour, which is what de-embedding exists for --
      corrected;
    * a round at any later phase -- verifying a tune that is supposed to have those filters in it
      -- as measured. Removing a filter that is part of the design measures something nobody
      configured;
    * no round, no record: `None`, and the caller must ask rather than default. "Nobody said" is
      not "there was nothing".
    """
    if not record:
        return None
    phase = str(record.get("phase") or "").strip()
    if phase in ("0", "-1", "1"):
        return True
    return False if phase else None


def legs_of(record: Optional[dict], channel: str):
    """The `{hp, lp}` to take out of this channel's curve, or None for "take nothing out".

    Straight through to the method. `{"hp": "OFF", "lp": "OFF"}` is the same instruction spelled
    explicitly, and older records use it; both mean the curve is analysed as measured.
    """
    return _module().legs_of(record, channel)


def should_de_embed(record: Optional[dict], channel: str, *, baseline: bool = False):
    """`("no"|"yes"|"check", detail)` — the method's own decision, asked instead of guessed.

    This is the call `de_embed`'s error message points at, and the reason nothing in TCC should ask
    `de_embed` cold: `"no"` is the default and is an answer, not a shrug. `"check"` is the one that
    needs a person — a baseline capture with no record — and the caller passes `baseline` because
    only it knows which phase the round belongs to; this module deliberately does not go looking.

    Degrades to `("no", reason)` when the skill is not installed: with no maths to take anything
    out with, "as measured" is the only thing that can honestly be drawn.
    """
    try:
        module = _module()
    except ProtectiveUnavailable as exc:
        return "no", str(exc)
    return module.should_de_embed(record, channel, baseline=baseline)


def matters_at(legs, freq_hz: float) -> bool:
    """Would the protective chain still be rotating phase at this frequency?"""
    return bool(_module().matters_at(legs, freq_hz))


def de_embed(freqs_hz, magnitude_db, phase_deg, legs) -> Corrected:
    """Take the protective chain out of a measured magnitude/phase pair.

    Raises `ProtectiveUnavailable` when the maths is not installed and lets the method's own
    `ProtectiveError` through when the record is missing — the caller must tell those apart: the
    first is this machine, the second is this project's record, and only one of them is fixed by
    installing something.
    """
    import numpy as np

    module = _module()
    problem = reason()
    if problem:
        raise ProtectiveUnavailable(problem)
    freqs = np.asarray(freqs_hz, dtype=float)
    mag = np.asarray(magnitude_db, dtype=float)
    phase = np.asarray(phase_deg, dtype=float)
    # REW states a response as dB and degrees; the correction works on the complex response, and
    # this is the only place in TCC that converts between them.
    measured = 10.0 ** (mag / 20.0) * np.exp(1j * np.deg2rad(phase))
    corrected, info = module.de_embed(freqs, measured, legs)
    return Corrected(
        magnitude_db=20.0 * np.log10(np.maximum(np.abs(corrected), 1e-300)),
        phase_deg=np.rad2deg(np.angle(corrected)),
        applied=tuple(info.get("applied") or ()),
        capped_below_hz=info.get("capped_below_hz"),
        capped_above_hz=info.get("capped_above_hz"),
        capped_bins=int(info.get("capped_bins") or 0),
        note=str(info.get("note") or ""),
    )
